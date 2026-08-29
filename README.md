# Options Alpha Agent

An autonomous, paper-trading-only agent that trades defined-risk **Bull Put
Spreads** on Alpaca. It scans a watchlist with live market data, scores
candidates deterministically, asks an LLM for a structured second opinion,
and executes only what a fully deterministic **Risk Engine** approves — with
automatic position sizing, configurable exit rules, and a full audit trail
of why every candidate was approved or rejected.

**The one rule everything is built around: the AI proposes, it never
decides.** Its output is Pydantic-validated before it can influence
anything, and even a valid "APPROVE" can be overridden by the Risk Engine.
This has been verified by actually running the agent against a live paper
account — see [Found by live testing](#found-by-live-testing-not-just-unit-tests)
for two real bugs that surfaced that way, not from unit tests alone.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full pipeline
diagram, [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) for a 3-5 minute
walkthrough, and [docs/WRITEUP.md](docs/WRITEUP.md) for the one-page
hackathon summary.

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
pytest
```

Use paper-account credentials only. `AlpacaClients` constructs every SDK
client with `paper=True`, and startup refuses any configuration where
`PAPER_TRADING_ONLY` or `ALPACA_PAPER` is not `true` — checked twice,
once at client construction and again before every order submission.

Confirm real connectivity (read-only — never submits, replaces or cancels
an order) once credentials are in `.env`:

```powershell
.\.venv\Scripts\python.exe scripts\integration_check.py
```

## How it works

1. **Market Analyst** (`app/agents/market_analyst.py`) computes trend,
   market regime and annualized realized volatility from real Alpaca daily
   bars (10/20-day moving averages, log-return volatility). Returns `None`
   — fail closed — when there isn't enough price history.
2. **Options Scanner** (`app/agents/options_scanner.py`) pulls real put
   contracts and an option chain snapshot (quotes, greeks, implied
   volatility) for one underlying, and builds `BullPutSpreadCandidate`
   objects by pairing a short leg whose delta falls in
   `TARGET_SHORT_DELTA_MIN`/`MAX` with the nearest listed long leg at or
   below `short_strike - SPREAD_WIDTH`. Any contract missing a quote or
   greeks is skipped, never guessed. `short_volume`/`long_volume` come from
   a real, batched daily-bar volume lookup — a contract with no trade yet
   today correctly reports 0 volume and can fail the `MIN_VOLUME` gate.
3. **Scoring** (`app/strategy/scoring.py`) — a deterministic 0-100 score
   from market regime, trend, volatility, liquidity, strike selection and
   risk/reward, with configurable weights (`SCORE_WEIGHT_*`, validated to
   sum to 100). No LLM involved.
4. **AI Analyst** (`app/agents/ai_provider.py`) — see
   [AI Analyst](#ai-analyst-two-interchangeable-providers) below. Skipped
   entirely for a candidate that already fails a deterministic gate (see
   [Found by live testing](#found-by-live-testing-not-just-unit-tests)).
5. **Risk Engine** (`app/risk/risk_engine.py`) — the sole authority over
   execution. Checks paper mode, DTE window, minimum credit, liquidity
   (bid/ask spread, open interest, volume), defined-risk (no naked/unlimited
   exposure), daily loss circuit breaker, portfolio risk, duplicate
   exposure, open-position count, AI score threshold, and computes contract
   sizing from account equity (`floor(risk_dollars / max_loss_per_contract)`,
   never hardcoded).
6. **Execution** (`app/execution/order_manager.py`) — a two-leg `MLEG`
   limit order (short put `sell_to_open`, long put `buy_to_open`).
   `DRY_RUN=true` (the default) returns a simulated result without
   constructing or calling an Alpaca client; outside dry-run, paper mode, an
   approved `RiskDecision`, positive sizing and a real client are all
   required.
7. **Position Manager** (`app/execution/position_manager.py`) — profit
   target, stop loss, time exit and regime exit, run continuously via
   `scripts/monitor_positions.py`. It fetches a live option quote to
   reprice the position (or falls back to entry credit in `DRY_RUN`) and
   skips a position rather than guessing a price if a quote is unavailable.
   **Known limitation:** the regime-exit check currently reuses a fixed
   `"BULLISH"` regime instead of re-running the Market Analyst on every
   poll.
8. **Trade journal** (`app/database/repository.py`) — two tables, on
   SQLAlchemy Core so the same code runs against local SQLite (default) or a
   remote Postgres database (`DATABASE_URL=postgresql://...`, e.g. Supabase)
   to share one journal across GitHub Actions, local development and a
   hosted dashboard. `decisions` records every candidate ever evaluated
   (approved or rejected) with its full market/option inputs, AI proposal,
   rationale and itemized risk checks. `trades` is opened only when an order
   is actually submitted, and updated with
   `closed_at`/`exit_reason`/`realized_pnl` when an exit rule fires.
9. **Dashboard** (`app/dashboard/app.py`) — `uvicorn app.dashboard.app:app --reload`,
   then open `http://127.0.0.1:8000`. Shows a live **Portfolio** section
   (equity, cash, buying power, daily P&L, degrading to "unavailable"
   rather than crashing if the API is unreachable — `DASHBOARD_FETCH_ACCOUNT=false`
   disables it for offline demos), **Agent activity** (scanned/approved/
   rejected counts), the full trade journal, and the decision journal with
   each candidate's AI score, final decision, risk flags and rationale.
   `/api/decisions`, `/api/trades` and `/api/account` return the same data
   as JSON.

   **Hosting it publicly (Vercel):** `api/index.py` re-exports the same
   FastAPI `app` with no logic changes, and `vercel.json` routes every
   request to it — Vercel's Python runtime supports ASGI apps natively, so
   this is a thin entrypoint, not a rewrite. `api/requirements.txt` is a
   slimmer dependency set (no `openai`/`mcp`, which the
   dashboard never imports) to stay under Vercel's function size limit. Set
   `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER=true`,
   `PAPER_TRADING_ONLY=true` and `DATABASE_URL` as Vercel environment
   variables — with `DATABASE_URL` pointing at the same Supabase database
   the trading loop writes to, the hosted dashboard shows the live journal
   with no separate sync step.

Run the whole scan-to-decision loop once against real Alpaca data:

```powershell
.\.venv\Scripts\python.exe scripts\run_agent.py
```

**Known limitation:** there is no earnings/event-risk gate. Alpaca does not
provide a reliable earnings-calendar feed, and rather than fake this check
it is left out and called out explicitly.

## AI Analyst

`AI_PROVIDER=featherless` (`FEATHERLESS_API_KEY`, `AI_MODEL` set to a model
id hosted on [Featherless.ai](https://featherless.ai), optionally
`FEATHERLESS_BASE_URL`) calls an OpenAI-compatible chat completion. The raw
output passes through `AIDecisionLayer.analyze`, which validates it against
the `AIProposal` Pydantic schema — anything unparseable becomes a forced
`REJECT` with `invalid_ai_output`. With `AI_PROVIDER=none` (the default),
`scripts/run_agent.py` refuses to run rather than silently skipping AI
evaluation. Featherless serves many different open-weight models behind one
API, and tool-calling support isn't uniform across all of them, so the
provider instead instructs the model to reply with a plain JSON object and
parses it directly (stripping a markdown code fence if the model adds one
despite instructions not to).

## Running it continuously

The agent needs to run across a multi-day scoring window, not as a single
one-off scan. Two options:

**Local / always-on machine:**

```powershell
.\.venv\Scripts\python.exe scripts\loop_forever.py
```

Alternates `run_agent.py` and `monitor_positions.py` on configurable
intervals, gated to real market hours via Alpaca's clock. Requires a
machine that stays powered on and connected for the whole window.

**GitHub Actions + an external scheduler (recommended):**
`.github/workflows/agent.yml` checks `scripts/market_open_check.py` and
skips the run entirely outside market hours, then runs
`monitor_positions.py` followed by `run_agent.py`. The SQLite journal is
persisted between runs via `actions/cache`. GitHub's own `schedule:` cron
trigger is kept as a backup, but in practice **it fired unreliably** (one
run in several hours despite a valid 5-minute cron — a known platform
limitation, not something specific to this repo), so the actual trigger is
an external scheduler ([cron-job.org](https://cron-job.org)) calling the
workflow's `workflow_dispatch` REST endpoint every 5 minutes with a scoped
GitHub token.

To enable it:

1. Push this repository to GitHub (may stay private during development).
2. Add repository **secrets**: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` (the
   official competition paper account), and `FEATHERLESS_API_KEY`.
3. Add repository **variables** to override any default from
   `.env.example` (`AI_PROVIDER`, `AI_MODEL`, `WATCHLIST`, `MIN_AI_SCORE`,
   etc.) — anything not set falls back to the same defaults.
4. Point an external scheduler at
   `POST https://api.github.com/repos/<owner>/<repo>/actions/workflows/agent.yml/dispatches`
   with body `{"ref":"main"}` and an `Authorization: Bearer <token>` header
   (a fine-grained PAT scoped to this repo, `Actions: Read and write`).

## Found by live testing, not just unit tests

Two real defects were found by actually running the agent against a live
paper account with a live AI provider connected, not by unit tests alone:

- The AI was being called on **every** scanned candidate, even ones a
  cheaper deterministic gate had already ruled out — this timed out
  scanning ~200 real candidates. Fixed with `RiskEngine.pre_screen()`,
  which runs every gate except the AI score first; `TradeWorkflow` only
  calls the AI for a candidate that could still be approved.
- `duplicate_exposure` (no more than one position per underlying) was
  computed once before a scan instead of per candidate, letting multiple
  positions open on the same symbol within a single run. Fixed in
  `scripts/run_agent.py`, which now updates the risk context in-memory
  after every approval.
- A theoretical/simulated backtest (see below) initially checked exit
  rules once per day and materially overstated stop-loss losses whenever
  the underlying gapped intraday — only visible once its checking cadence
  was compared against the live agent's real 5-minute monitoring loop.

## Simulated backtest (theoretical, not validated performance)

Alpaca's available historical options data isn't deep enough to replay real
past option quotes, so rather than fake that, `app/backtest/` reconstructs
option prices with Black-Scholes over **real historical stock prices**,
reusing the actual production `calculate_contracts` and
`PositionManager.evaluate_exit` code — it validates the rule mechanics, not
performance. Exit rules are checked against real 5-minute intraday bars,
not just the daily close. Liquidity gates and the AI Analyst are not
simulated at all. This is the "historical backtest" the hackathon FAQ
allows as supporting evidence of the agent's guardrails; official scoring
is still based entirely on the live paper account.

```powershell
.\.venv\Scripts\python.exe scripts\run_simulated_backtest.py 365
```

## MCP Server integration

The autonomous trading loop always talks to Alpaca directly through
`alpaca-py`, so the Risk Engine remains the sole authority over order
submission. Alongside that, the official
[Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server) is wired
in as a read-only query/demo path, callable from any MCP client (Claude
Desktop, Cursor, or this repo's own demo script) for account and
option-chain inspection in plain English:

```powershell
uv tool install alpaca-mcp-server
.\.venv\Scripts\python.exe scripts\mcp_read_only_demo.py
```

The script lists the tools the server exposes, then calls only
`get_account_info` and `get_option_chain` — it never calls
`place_option_order` or any other mutating tool.

## Manual single-order verification

After rotating any exposed keys and explicitly authorizing one paper order,
set `DRY_RUN=false` and run:

```powershell
.\.venv\Scripts\python.exe scripts\paper_mleg_check.py
```

Selects one real SPY put spread from Alpaca contracts and quotes, journals
the decision, applies the Risk Engine, and submits at most one paper order.
Restore `DRY_RUN=true` immediately afterward. Never run this script with
live credentials.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

56+ tests cover position sizing, max-loss calculation, every risk gate,
invalid-AI-output handling (both providers), liquidity rejection, daily-loss
limits, duplicate-position handling, exit conditions, the options scanner,
the market analyst, and the simulated backtest. The one network-dependent
integration test is skipped automatically when credentials aren't present.
