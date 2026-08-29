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

## Data model

- **decisions** — every candidate ever evaluated: market inputs, option
  inputs, AI proposal + rationale, risk-engine checks, final decision.
  Written for both approvals and rejections.
- **trades** — opened only when an order is actually submitted (real or
  dry-run); updated with `closed_at`, `exit_reason`, `realized_pnl` when
  `monitor_positions.py` triggers an exit.

## Fail-closed behavior

| Failure | Behavior |
|---|---|
| Alpaca API error / timeout | Exception propagates, no order attempted |
| Incomplete market/option data | Candidate not built, or `defined_risk`/`liquidity` gates reject it |
| AI unavailable or returns invalid JSON (either provider) | `AIDecisionLayer.analyze` catches the error and returns a forced `REJECT` with `invalid_ai_output` flag |
| Candidate already fails a deterministic gate | `RiskEngine.pre_screen()` rejects it before the AI is ever called — saves cost/latency, never affects the outcome |
| Live quote unavailable during monitoring | `monitor_positions.py` skips the position rather than guessing a price |
| Paper mode misconfigured | `Settings.require_paper_mode()` raises at startup; `OrderManager` re-checks before every submit |
