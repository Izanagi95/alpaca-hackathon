# Options Alpha Agent

Paper-only foundation for an autonomous Bull Put Spread agent.

## Official competition setup

Per Alpaca's hackathon rules, this repository was built and tested against a
separate **testing** paper account before the official window. For the
scored measurement (Monday 9:30 a.m. ET through Friday 9:30 a.m. ET), a
**new, dedicated $100,000 paper account** must be created and its keys put
into `.env` — the testing account's credentials must not be used for
scoring. Everything in this repository (workflow, risk engine, scanner,
scripts, dashboard) was written before and during the hackathon window as
infrastructure/tooling, per the organizers' pre-event-work disclosure
requirement; no trades were placed against the official scoring account
before Monday 9:30 a.m. ET.

To keep the agent trading autonomously across the multi-day scoring window
rather than a single one-off scan, there are two options:

**Local / always-on machine:**

```powershell
.\.venv\Scripts\python.exe scripts\loop_forever.py
```

This alternates `scripts\run_agent.py` (scan for new candidates) and
`scripts\monitor_positions.py` (evaluate exits on open positions) on
configurable intervals, gated to real market hours via Alpaca's clock so it
never spins or trades while the market is closed. Requires a machine that
stays powered on and connected for the whole window.

**GitHub Actions (recommended — no always-on host required):**
`.github/workflows/agent.yml` runs on a 5-minute cron schedule, checks
`scripts/market_open_check.py` and skips the run entirely outside market
hours, then runs `monitor_positions.py` followed by `run_agent.py`. The
SQLite journal (`options_alpha.db`) is persisted between scheduled runs via
`actions/cache`, so open positions and past decisions carry forward. To
enable it:

1. Push this repository to GitHub (may stay private per the hackathon rules).
2. Add repository **secrets**: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` (the
   official competition paper account, from Monday 9:30 a.m. ET onward),
   and optionally `ANTHROPIC_API_KEY`.
3. Add repository **variables** to override any risk/strategy default from
   `.env.example` (e.g. `AI_PROVIDER=anthropic`, `WATCHLIST`, `MIN_AI_SCORE`)
   — anything not set falls back to the same defaults as `.env.example`.
4. Enable the workflow under the Actions tab (scheduled workflows on a
   fresh push start enabled; GitHub disables a schedule after 60 days of
   repository inactivity, well outside this event's window).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full pipeline diagram,
[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) for a 3-5 minute walkthrough, and
[docs/WRITEUP.md](docs/WRITEUP.md) for the one-page hackathon summary.

## Phase 2 status

This phase provides:

- environment-based configuration;
- explicit paper-trading guard;
- Alpaca Trading, stock-data and options-data adapters;
- account verification entry point;
- offline tests that do not require credentials or network access.

No order is submitted yet. `DRY_RUN=true` is the default and execution will remain disabled until the risk engine and order manager are implemented.

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
pytest
```

Use paper-account credentials only. The SDK clients are constructed with `paper=True`, and startup refuses any configuration where `PAPER_TRADING_ONLY` or `ALPACA_PAPER` is not `true`.

## Read-only integration check

After putting paper credentials in `.env`, run:

```powershell
.\.venv\Scripts\python.exe scripts\integration_check.py
```

This checks the paper account, stock quotes, option contracts and option quotes. It never submits, replaces or cancels an order. A successful run ends with `READ-ONLY INTEGRATION CHECK PASSED`.

The network test is optional and is skipped by default when credentials are not present:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Phase 3: strategy and risk

The current quantitative layer supports Bull Put Spread candidates with:

- deterministic score from market, volatility, liquidity, strike and reward inputs;
- theoretical max-loss calculation;
- automatic contract sizing from account equity and configured risk fraction;
- fail-closed gates for paper mode, DTE, credit, liquidity, volume, daily loss, portfolio risk, duplicate exposure, position count and AI score.

**Known limitation:** there is no earnings/event-risk gate. Alpaca does not provide a reliable earnings-calendar feed, and no other verified data source has been wired in yet, so this check is intentionally absent rather than faked — do not assume the agent screens for earnings dates.

Run the isolated strategy and risk tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_strategy_risk.py
```

No order submission is connected yet. The `RiskEngine` returns a decision and an auditable set of checks for the future execution layer.

## Phase 6: position monitoring

`PositionManager` evaluates open Bull Put Spreads using current debit, entry credit, contracts and DTE. It exits at the configured profit target, stop-loss fraction, expiry buffer or incompatible market regime. The rule engine returns `HOLD` or a named exit reason; multi-leg closing is kept as a separate execution action so individual legs are not closed accidentally.

`scripts/monitor_positions.py` connects this rule engine to the rest of the system: it reads every open row from the `trades` table, fetches a live option quote to compute the current debit (or falls back to the entry credit in `DRY_RUN`), evaluates the exit rules, and — when a rule fires — calls `OrderManager.close_bull_put_spread` and journals the realized P&L via `DecisionRepository.record_trade_close`. If a quote is unavailable it skips the position rather than guessing a price (fail closed).

**Known limitation:** the regime-exit check currently re-uses a fixed `"BULLISH"` regime rather than re-running the Market Analyst on every poll; a full re-scan of the underlying's regime is left for a future iteration.

## Phase 7: dashboard

Start the read-only journal dashboard with:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.dashboard.app:app --reload
```

Open `http://127.0.0.1:8000`. It shows a live **Portfolio** section (equity,
cash, buying power, daily P&L — fetched directly from the Alpaca paper
account, `/api/account`), **Agent activity** (scanned/approved/rejected
counts), the full trade journal (strikes, contracts, entry credit, exit
reason, realized P&L per position), and the decision journal with each
candidate's AI score, final decision, risk flags and rationale — i.e. the
"why" behind every approval and rejection. If credentials are missing or the
API is unreachable, the portfolio section degrades to "unavailable" instead
of failing to render (`DASHBOARD_FETCH_ACCOUNT=false` disables the live
fetch entirely, e.g. for offline demos). It does not expose secrets or
submit orders; `/api/decisions`, `/api/trades` and `/api/account` return the
same data as JSON.

## Trade journal

`DecisionRepository` persists two SQLite tables:

- `decisions` — every candidate evaluated, its market/options inputs, the AI proposal, rationale, risk-engine checks and the final APPROVE/REJECT outcome. Written for both approved and rejected candidates, so any decision is fully reconstructable after the fact.
- `trades` — opened only when `OrderManager` actually submits an order (real or dry-run); updated by `monitor_positions.py` with `closed_at`, `exit_reason` and `realized_pnl` once an exit rule fires.

`TradeWorkflow.evaluate` writes to `decisions` unconditionally and to `trades` only when execution is submitted, via `DecisionRepository.record_trade_open`.

## End-to-end dry run

`TradeWorkflow` connects the AI proposal, deterministic risk checks, SQLite journal and paper order manager. Every candidate is journaled; an AI rejection or failed risk gate cannot reach execution. With the default `DRY_RUN=true`, an approved candidate produces only a simulated order result.

## Single paper mleg verification

After rotating exposed keys and explicitly authorizing one paper order, set `DRY_RUN=false` in `.env` and run:

```powershell
.\.venv\Scripts\python.exe scripts\paper_mleg_check.py
```

The script selects one real SPY put spread from Alpaca contracts and quotes, journals the decision, applies the Risk Engine and submits at most one paper order. Restore `DRY_RUN=true` immediately afterward. Never run this script with live credentials.

## Phase 5: paper execution

`OrderManager` builds a two-leg `mleg` limit order for a Bull Put Spread: short put (`sell_to_open`) plus long put (`buy_to_open`). `DRY_RUN=true` is the default and returns a simulated execution result without constructing or calling an Alpaca client. Outside dry-run, paper mode, an approved `RiskDecision`, positive sizing and an Alpaca client are all required.

## Phase 8: autonomous scan-to-decision loop

Two pieces close the gap between the deterministic pipeline (tested with
hand-built candidates) and a genuinely autonomous agent:

- `app/agents/market_analyst.py` — `MarketAnalyst.assess(symbol)` computes
  trend, market regime and annualized realized volatility from real Alpaca
  daily bars (10/20-day moving averages, log-return volatility). Returns
  `None` — fail closed — when there isn't enough price history.
- `app/agents/options_scanner.py` — `OptionsScanner.scan(assessment)` pulls
  real put contracts and an option chain snapshot (quotes, greeks, implied
  volatility) for one underlying, and builds `BullPutSpreadCandidate`
  objects by pairing a short leg whose delta falls in
  `TARGET_SHORT_DELTA_MIN`/`MAX` with the nearest listed long leg at or below
  `short_strike - SPREAD_WIDTH`. Any contract missing a quote or greeks is
  skipped, never guessed.

`scripts/run_agent.py` ties these to the existing `TradeWorkflow`: for every
symbol in `WATCHLIST` it assesses the market, scans for candidates, computes
each one's deterministic quant score (`app/strategy/scoring.py`, weights
configurable via `SCORE_WEIGHT_*` and validated to sum to 100), then runs the
full AI -> Risk Engine -> execution -> journal pipeline per candidate.
`RiskContext` (equity, daily P&L fraction, open positions/symbols, portfolio
risk used) is computed from the live account and the journal's open trades.

```powershell
.\.venv\Scripts\python.exe scripts\run_agent.py
```

`short_volume`/`long_volume` come from a real, batched daily-bar volume
lookup (`OptionsDataService.daily_volume`, one `get_option_bars` request per
underlying covering every leg symbol) — not an approximation. A contract
with no trade yet today correctly reports 0 volume and can fail the
`MIN_VOLUME` liquidity gate; this was verified against a real paper account
where an earlier approximation (last trade size) made the gate fail for
every candidate.

## AI Analyst — real provider

`app/agents/ai_provider.py` supports two interchangeable providers, selected
via `AI_PROVIDER`. Either way, the raw output passes through
`AIDecisionLayer.analyze`, which validates it against the same `AIProposal`
Pydantic schema used everywhere else — anything unparseable becomes a forced
`REJECT` with `invalid_ai_output`, exactly like any other AI failure mode.
With `AI_PROVIDER=none` (the default), `scripts/run_agent.py` refuses to run
rather than silently skipping AI evaluation.

- **`AI_PROVIDER=anthropic`** (`ANTHROPIC_API_KEY`, `AI_MODEL`) — calls the
  Anthropic API with a forced tool call (`submit_options_proposal`) so the
  model cannot reply with free text.
- **`AI_PROVIDER=featherless`** (`FEATHERLESS_API_KEY`, `AI_MODEL` set to a
  model id hosted on [Featherless.ai](https://featherless.ai), optionally
  `FEATHERLESS_BASE_URL`) — Featherless serves many different open-weight
  models behind an OpenAI-compatible API, and tool-calling support isn't
  uniform across all of them, so this provider instead instructs the model
  to reply with a plain JSON object and parses it directly (stripping a
  markdown code fence if the model adds one despite instructions not to).
  Malformed JSON is caught the same way any other invalid AI output is.

## Simulated backtest (theoretical, not validated performance)

`app/backtest/` reconstructs what the strategy's rules would have done using
**real historical stock prices** (Alpaca daily bars) combined with a
**Black-Scholes theoretical option price** — not real historical option
quotes, which Alpaca's available historical options data does not go back
far enough (nor carry the historical bid/ask, open interest or IV surface)
to reconstruct honestly. Rather than fake a backtest against data we don't
have, this is clearly labeled as a theoretical/simulated approximation: it
reuses the actual production `calculate_contracts` and
`PositionManager.evaluate_exit` code (so it at least validates the rule
mechanics), but liquidity gates and the AI Analyst are not simulated at all.

```powershell
.\.venv\Scripts\python.exe scripts\run_simulated_backtest.py 365
```

This is the "historical backtest" the hackathon FAQ allows as supporting
evidence of the agent's guardrails — official scoring is still based
entirely on the live paper account, never on this simulation.

Exit rules are checked against real **5-minute intraday bars** within each
trading day (not only the daily close), so a stop-loss is caught close to
its configured threshold rather than only discovered — much worse than
intended — after a full day's gap has already happened. An earlier version
of this backtest checked exits once per day and materially overstated
stop-loss losses for exactly that reason; this was caught by comparing the
simulation's polling cadence against the live agent's actual 5-minute
monitoring loop.

## MCP Server integration

The autonomous trading loop (`app/agents/workflow.py`) always talks to Alpaca
directly through `alpaca-py`, so the deterministic Risk Engine remains the
sole authority over order submission. Alongside that, the project uses the
official [Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server)
as a read-only query/demo path, callable from any MCP client (Claude
Desktop, Cursor, this repo's own demo script) for account and option-chain
inspection in plain English or via `scripts/mcp_read_only_demo.py`:

```powershell
uv tool install alpaca-mcp-server
.\.venv\Scripts\python.exe scripts\mcp_read_only_demo.py
```

The script lists the tools the server exposes, then calls only
`get_account_info` and `get_option_chain` — it never calls
`place_option_order` or any other mutating tool. `MCP_SERVER_COMMAND` /
`MCP_SERVER_ARGS` in `.env` control how the server subprocess is launched.

## Phase 4: AI decision layer

AI responses are validated through `AIProposal`. Invalid, incomplete or unavailable responses become a rejection with the `invalid_ai_output` flag. The AI layer never submits orders. `DecisionRepository` stores the candidate inputs, AI proposal, rationale, risk checks and final decision in SQLite.
