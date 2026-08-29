# Architecture

Options Alpha Agent is an autonomous, paper-trading-only agent that scans for
Bull Put Spread candidates, scores them quantitatively, asks an LLM for a
consultative opinion, and only ever executes a trade if a fully deterministic
Risk Engine approves it. The LLM can never submit an order on its own.

## Pipeline

```
                    MARKET DATA (Alpaca Market Data API)
                                 |
                                 v
                    +---------------------------+
                    |  Stock/Options data layer  |   app/alpaca/{market_data,options}.py
                    +-------------+---------------+
                                  |
                                  v
                    +---------------------------+
                    |  Market Analyst            |   app/agents/market_analyst.py
                    |  trend/regime/realized vol |
                    |  from real daily bars      |
                    +-------------+---------------+
                                  |
                                  v
                    +---------------------------+
                    |  Options Scanner           |   app/agents/options_scanner.py
                    |  real chain + greeks ->    |
                    |  BullPutSpreadCandidate    |
                    +-------------+---------------+
                                  |
                                  v
                    +---------------------------+
                    |  Deterministic Scoring     |   app/strategy/scoring.py
                    |  (0-100, configurable      |
                    |   weights, no LLM)         |
                    +-------------+---------------+
                                  |
                                  v
                    +---------------------------+
                    |  AI Analyst (LLM)          |   app/agents/ai_decision.py
                    |  structured in -> Pydantic |
                    |  validated out; REJECT on  |
                    |  invalid/missing output    |
                    +-------------+---------------+
                                  |
                                  v
                    +---------------------------+
                    |  RISK ENGINE (deterministic)|  app/risk/risk_engine.py
                    |  paper mode, DTE, credit,   |
                    |  liquidity, volume, defined |
                    |  risk, daily loss, portfolio|
                    |  risk, duplicate exposure,  |
                    |  position count, AI score,  |
                    |  automatic contract sizing  |
                    +-------------+---------------+
                                  |
                       REJECT ----+---- APPROVE
                                  |
                                  v
                    +---------------------------+
                    |  Alpaca Execution           |  app/execution/order_manager.py
                    |  MLEG limit order (short put|
                    |  sell_to_open + long put    |
                    |  buy_to_open), paper=True   |
                    +-------------+---------------+
                                  |
                                  v
                    +---------------------------+
                    |  Position Manager           |  app/execution/position_manager.py
                    |  profit target / stop loss /|
                    |  time exit / regime exit    |
                    |  -> scripts/monitor_positions.py
                    +-------------+---------------+
                                  |
                                  v
                    +---------------------------+
                    |  Trade Journal (SQLite)     |  app/database/repository.py
                    |  decisions + trades tables  |
                    +-------------+---------------+
                                  |
                                  v
                    +---------------------------+
                    |  Dashboard (FastAPI)        |  app/dashboard/app.py
                    +---------------------------+
```

## The control principle

```
AI proposal (score, confidence, rationale)
        |
        v
  Risk Engine  <-- deterministic, no LLM involved
        |
        +---- REJECT  -> journaled, no order
        |
        +---- APPROVE -> automatic position sizing -> Alpaca MLEG order
```

`RiskEngine.evaluate()` is called unconditionally for every candidate and
independently forces rejection whenever the AI proposal itself is not
`APPROVE`. `OrderManager` re-checks `risk_decision.approved` a second time
right before constructing an order, and refuses to run outside paper mode.
There is no code path from an AI response directly to `submit_order`.

## MCP / CLI layer

```
AI Layer (Claude, or any MCP-compatible client)
        |
        v
Alpaca MCP Server (alpacahq/alpaca-mcp-server) -- read-only query/demo path
        |                                          scripts/mcp_read_only_demo.py
        v
Alpaca (paper account)

Autonomous loop (headless, no interactive LLM client attached):
        |
        v
alpaca-py TradingClient / OptionHistoricalDataClient  -- execution path
        |
        v
Alpaca (paper account)
```

The MCP server satisfies the hackathon's MCP/CLI requirement and is a real,
working integration (`scripts/mcp_read_only_demo.py` lists its tools and
calls `get_account_info` / `get_option_chain`). It is intentionally kept out
of the autonomous execution loop: a long-running MCP subprocess is a natural
fit for interactive/demo use, not for a headless scheduled agent, and keeping
execution on direct `alpaca-py` calls means the Risk Engine gate cannot be
bypassed by anything the MCP client does or doesn't do.

## Production scheduling

The autonomous loop needs to run continuously across the multi-day scoring
window. GitHub Actions' native `schedule:` cron trigger proved unreliable in
practice — a valid 5-minute cron fired only once across several hours, a
known platform limitation (GitHub does not guarantee schedule frequency,
especially at short intervals on low-traffic repos). The actual trigger in
production is an **external scheduler (cron-job.org)** calling the
workflow's `workflow_dispatch` REST endpoint every 5 minutes with a scoped
GitHub token; GitHub's own `schedule:` entry is left in the workflow only as
a redundant backup, not the primary mechanism.

```
cron-job.org (real 5-min timer)
        |
        v  POST /repos/.../actions/workflows/agent.yml/dispatches
GitHub Actions runner (ubuntu-latest, ephemeral)
        |
        v
market_open_check.py --> skip if closed
        |
        v
monitor_positions.py  ->  run_agent.py
        |
        v
options_alpha.db persisted via actions/cache between runs
```

**Token exposure risk, and its mitigation:** cron-job.org must hold the
GitHub token in plaintext to send it as a request header on every call —
this is inherent to any HTTP-webhook scheduler, not something that can be
hidden. The mitigation is scope minimization, not secrecy: the token is a
fine-grained PAT restricted to this one repository with only the
`Actions: Read and write` permission, so a leak lets an attacker trigger or
cancel workflow runs on this repo and nothing else — no code access, no
other repos, no account-level access. It also carries a short expiration
(through the end of the scoring window) and is revoked manually once the
competition ends, rather than left live indefinitely.

### Deployment options considered

The scan-to-decision loop and position monitor are plain Python scripts
with no framework lock-in, so several deployment shapes were viable. None
of them is universally "correct" — the right choice depends on the
time horizon, budget, and who is operationally responsible for uptime.

| Option | Where secrets live | Uptime responsibility | Cost | Why (not) chosen here |
|---|---|---|---|---|
| **GitHub Actions + external scheduler (chosen)** | GitHub's encrypted Secrets store, decrypted only inside an ephemeral runner that lives ~1 minute per run | GitHub's infrastructure | Free (within Actions minutes quota) | No server to patch or secure, no persistent process holding credentials, matches a short (4-day) competition window. Trade-off: GitHub's own `schedule:` cron is unreliable at short intervals (see above), so an external scheduler is still needed to trigger it reliably — and that scheduler must hold a token, which is the one real weakness of this approach (mitigated by scope + expiration, not eliminated). |
| **GitHub Actions native `schedule:` only** | Same as above | Same as above | Free | Simplest possible setup, but empirically unreliable (one run fired in several hours despite a valid 5-minute cron) — not viable alone for a scoring window where consistent execution matters. Kept as a redundant backup, not the primary trigger. |
| **Local always-on machine** (`scripts/loop_forever.py`) | A local `.env` file | You, personally, for the whole window | Free (if the machine is already on) | Zero infrastructure to set up, but a laptop sleeping, losing network, or being closed for the night stops the whole agent — too fragile for an unattended multi-day window. |
| **Small VPS** (e.g. a $4-6/mo droplet) | A `.env` file on a server that's reachable 24/7 | You — OS patching, SSH hardening, process supervision | ~$5-10/mo | Removes the third-party-scheduler token risk entirely, but trades it for a persistent, always-reachable box holding live credentials, plus real ops work (security updates, firewall, process restarts) for a project with a one-week horizon. More sense for a system meant to run indefinitely, not a hackathon window. |
| **Serverless cloud** (AWS Lambda + EventBridge, or GCP Cloud Functions + Cloud Scheduler) | The cloud provider's own secret manager | The cloud provider | Effectively free at this call volume | Arguably the "best" long-term answer — native, reliable scheduling and secrets never leave the provider's ecosystem — but requires porting the scripts to a serverless entrypoint and standing up cloud infrastructure, which wasn't worth the setup time for a one-week deadline. Worth revisiting if this project continues past the hackathon. |
| **Self-hosted GitHub Actions runner** | GitHub Secrets (same as the chosen option) | You, for the runner machine | Free (+ your own hardware/VPS) | Doesn't actually solve the reliability problem on its own — the runner still needs something to trigger it on schedule, so it just relocates the compute without removing the need for an external scheduler. |

Given a one-week competition, zero budget, and no dedicated ops time,
GitHub Actions triggered by an external scheduler was the best fit: no
server to secure, ephemeral credential exposure instead of a persistent
one, and a single documented, scoped weak point (the trigger token) that
was mitigated deliberately rather than ignored.

## Data model

- **decisions** — every candidate ever evaluated: market inputs, option
  inputs, AI proposal + rationale, risk-engine checks, final decision.
  Written for both approvals and rejections.
- **trades** — opened only when an order is actually submitted (real or
  dry-run); updated with `closed_at`, `exit_reason`, `realized_pnl` when
  `monitor_positions.py` triggers an exit.

**Shared database (optional).** `DecisionRepository` runs on SQLAlchemy
Core, so the same table definitions and queries work against local SQLite
(the default — a separate file per environment) or a remote Postgres
database such as Supabase, by setting `DATABASE_URL` to a `postgresql://...`
connection string. Which Postgres schema (namespace) to use — a dedicated
one instead of the default `public` — is read directly from that same URL's
`options=-c search_path=<schema>` parameter (e.g.
`...?options=-c%20search_path%3Dalpaca`) rather than hardcoded in code, so
it's visible and changeable from `.env` alone. The one place code does need
the schema name is a one-time `CREATE SCHEMA IF NOT EXISTS` bootstrap, which
parses it back out of the URL instead of duplicating it as a constant.
SQLite has no schema concept, so this parameter is simply absent from a
`sqlite:///...` URL and nothing schema-related runs. With `DATABASE_URL`
set, GitHub Actions, local development and a hosted dashboard all read and
write the same journal instead of each holding its own disconnected copy —
replacing the artifact-download workflow below with just querying the live
database directly.

**Publishing the journal as an artifact.** The workflow uploads
`options_alpha.db` as a downloadable GitHub Actions artifact (in addition
to the `actions/cache` copy used to persist it between runs), so the real
journal produced by the official run can be pulled locally
(`gh run download`) and inspected with the same dashboard used in
development. Checked before doing this: none of `BullPutSpreadCandidate`,
`AIProposal` or `RiskDecision` — the only models ever serialized into the
database — carry any key/secret/token/credential field, so the artifact
itself never contains anything sensitive.

What does change once the repository is made public (required for
submission): GitHub Actions artifacts on a public repo are downloadable by
anyone with the run URL, no authentication required — so the trade/decision
journal becomes effectively public alongside the code, not just visible to
judges. This is treated as consistent with the project's transparency
principle (every decision is meant to be reconstructable) rather than as a
leak to prevent, precisely because the content was checked and contains no
credentials — only strikes, credit, AI scores and rationale.

## Fail-closed behavior

| Failure | Behavior |
|---|---|
| Alpaca API error / timeout | Exception propagates, no order attempted |
| Incomplete market/option data | Candidate not built, or `defined_risk`/`liquidity` gates reject it |
| AI unavailable or returns invalid JSON (either provider) | `AIDecisionLayer.analyze` catches the error and returns a forced `REJECT` with `invalid_ai_output` flag |
| Candidate already fails a deterministic gate | `RiskEngine.pre_screen()` rejects it before the AI is ever called — saves cost/latency, never affects the outcome |
| Live quote unavailable during monitoring | `monitor_positions.py` skips the position rather than guessing a price |
| Paper mode misconfigured | `Settings.require_paper_mode()` raises at startup; `OrderManager` re-checks before every submit |
