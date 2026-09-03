# Riskgate — one-page write-up

## What it is

An autonomous, paper-trading-only agent that trades defined-risk **Bull Put
Spreads** on Alpaca. It scans liquid underlyings, scores candidates
quantitatively, asks an LLM for a structured second opinion, and executes
only what a deterministic Risk Engine approves — with automatic position
sizing, configurable exit rules, and a full audit trail of why every trade
was approved or rejected.

## Why the architecture is safe by design

The rule the system is built around: **the LLM's power is purely subtractive
— it can stop a trade, never start one.**

That is a narrower claim than "the AI only advises", and the journal shows
why the narrower one is the honest version. Of 42,926 candidates priced, the
deterministic gates rejected 42,874 before the AI was consulted at all. The
52 survivors had already passed every deterministic gate — so among *those*,
the AI's verdict was decisive: 32 approved, 20 rejected, and all 20 fell on
the AI score, not one on a risk gate. The engine does not overrule the AI on
the candidates that reach it; it decides which candidates the AI is allowed
to weigh in on, and it alone sizes whatever gets through.

So neither party can authorise a trade by itself. The engine's consent is a
precondition, the AI's is the last word among the candidates that earn one,
and an order requires both. What the AI can never do — the property that
matters — is cause a trade that the deterministic rules would have refused.

`AIDecisionLayer` returns a Pydantic-validated `AIProposal`
(decision, score, confidence, rationale, risk flags) or, on any invalid or
missing response, a forced `REJECT`. That proposal then passes through
`RiskEngine.evaluate()` — a pure function with no LLM involvement — which
independently checks paper mode, DTE window, minimum credit, liquidity
(bid/ask spread, open interest, volume), defined-risk (no naked/unlimited
exposure), daily loss circuit breaker, portfolio risk, duplicate exposure,
open-position count, AI score threshold, and computes contract sizing from
account equity (`floor(risk_dollars / max_loss_per_contract)`, never
hardcoded). `OrderManager` re-checks the risk decision a second time before
constructing an order and refuses to run outside paper mode. There is no
code path from an AI response directly to `submit_order`.

## Alpaca integration

Built on `alpaca-py`: `TradingClient` (paper=True, hardcoded, not
env-toggleable at the client level), `OptionHistoricalDataClient` for
option-chain/quote data, and multi-leg (`OrderClass.MLEG`) limit orders with
`OptionLegRequest` legs (`sell_to_open` short put, `buy_to_open` long put) to
submit the spread as one atomic unit. The official
[Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server) is wired
in as a read-only query/demo path (`scripts/mcp_read_only_demo.py`),
callable from any MCP client for natural-language account and option-chain
inspection, while the headless autonomous loop always uses direct
`alpaca-py` calls so the Risk Engine gate can't be affected by anything
happening on the MCP side.

## AI methodology

The AI Analyst receives a fully structured JSON payload (underlying price,
trend, realized/implied volatility, market regime, and the specific option
leg data) — never raw HTML or free text — and must return output matching a
strict Pydantic schema. It is not asked to "predict the market"; it's a
decision-support layer over quantitative inputs that are computed
deterministically upstream by the scoring module. Every proposal, valid or
rejected, is journaled with its full rationale.

The provider is **Featherless.ai** (an OpenAI-compatible host for
open-weight models), currently configured with
`Qwen/Qwen3-30B-A3B-Instruct-2507`, a non-reasoning MoE variant chosen
specifically so responses are plain JSON with no `<think>` preamble to
strip. The raw output is validated by the same Pydantic schema before it
can influence anything — a malformed response becomes a forced `REJECT`.

To keep the AI cost/latency bounded at scale, `TradeWorkflow` runs a
`RiskEngine.pre_screen()` pass first and skips the AI call entirely for a
candidate that already fails a deterministic gate (liquidity, DTE, credit,
sizing) — discovered necessary after a live run against ~200 real candidates
timed out calling the AI on every one of them, most of which could never
have been approved regardless of the AI's opinion.

## Risk methodology

All risk parameters are environment-configurable (`MAX_PORTFOLIO_RISK`,
`MAX_POSITION_RISK`, `MAX_DAILY_LOSS`, `MAX_OPEN_POSITIONS`, `MIN_DTE`/
`MAX_DTE`, `MIN_OPEN_INTEREST`, `MAX_BID_ASK_SPREAD`, `MIN_AI_SCORE`, exit
fractions) — nothing risk-relevant is hardcoded. Exit rules (profit target,
stop loss, time exit, regime exit) run continuously via
`scripts/monitor_positions.py`, so positions are never held to expiration by
default. **Known, documented limitation:** there is no earnings/event-risk
gate — Alpaca does not expose a reliable earnings calendar, and rather than
fake this check it is left out and called out explicitly.

## Fill confirmation: found live, fixed live

A trade is journaled when its opening order is **submitted**, because that is
when the decision happens — but an order that is submitted is not yet a
position. Early in the run this mattered: an order that never filled still
appeared as an open position, and the monitor would "close" it against a
favourable quote and journal a realized P&L for something the broker never
held. Rather than argue about it, `scripts/reconcile_journal.py` measures it:
it classifies every journalled trade against the broker's own orders — never
filled, filled at a different size, closed only in the journal, or reconciled
— and compares realized P&L only on the rows the broker can actually price.
On the account submitted for judging, all 14 journalled openings exist at the
broker; 6 expired without ever filling (journalled at zero, so no P&L effect);
and across every trade the broker can price, the journal and the actual fills
agree to within $5.50 in total, the largest single row differing by $3. The
journal's arithmetic is sound.

Three rows written on the first day, before fill confirmation landed, are
marked closed with no recorded closing order behind them, carrying +$202.70.
Adding those to the +$608 the broker's fills confirm, plus +$87 of live
unrealized value, gives +$897.70 against +$901.29 of actual equity gain — a
$3.59 residual, which says that P&L was genuinely earned and the journal
merely lost the link to the closing order that earned it. That distinction
matters: "closed only in the journal" is a broken reference, not invented
money, and only reconciliation against the broker can tell the two apart.

The execution path now confirms fill state before acting on a position: the
monitor fetches the real order status, marks an order that ended
canceled/expired/rejected as never-filled with zero P&L, resizes a partial
fill to the contracts that actually filled (so exit thresholds and the
closing order match the real position), and simply skips a position whose
opening order is still working rather than pricing an exit against it. The
closing side is symmetric — a trade counts as closed only once the closing
order itself fills, and a closing order that expires unfilled re-arms the
remainder instead of being assumed done.

Rows written before those fixes landed are still in the journal, so the
**Alpaca account remains the authoritative record of performance** while the
journal's job is to explain *reasoning* — what was considered, scored,
approved or rejected, and why. The dashboard states this on every page that
shows P&L rather than presenting a journal total as account performance.

## Explainability

Every candidate the agent ever evaluates — approved or rejected — is written
to the `decisions` table with its market/option inputs, AI proposal,
rationale, and the itemized risk-engine checks that passed or failed. Every
order actually submitted is separately tracked in `trades` from open to
close, with exit reason and realized P&L. The dashboard
(`app/dashboard/app.py`) surfaces both tables plus aggregate scan/approve/
reject counts.

The journal runs on SQLAlchemy Core against either local SQLite or a
Postgres database (Supabase, under a dedicated `alpaca` schema — the schema
name lives in `DATABASE_URL` itself, not hardcoded), so GitHub Actions, local
development and a Vercel-hosted copy of the same dashboard can all read and
write one live journal instead of disconnected per-environment copies. This
was verified against a real Supabase project, not just assumed to work:
GitHub Actions writing 300+ real decision rows into it, queried back
directly to confirm.

## Dashboard

Four pages behind a shared navbar — Overview, Daily KPIs, Positions &
Trades, Decision Journal — each filterable by a real inclusive date range
(native `<input type="date">`, no JavaScript) plus symbol/status/decision
filters on the two journal pages, with per-page summary stats (matching
count, win/loss, realized P&L, approval rate) instead of only raw tables.

**Public hosting (optional):** `api/index.py` re-exports the same FastAPI
app with no logic changes, and `vercel.json` routes requests to it —
Vercel's Python runtime supports ASGI apps natively. With `DATABASE_URL`
set to the shared Supabase database, a Vercel-hosted dashboard shows the
live journal with no separate sync step. Alpaca credentials are
deliberately **not** required for this: the Portfolio section degrades to
"unavailable" without them rather than handing a third-party host API keys
it doesn't need — the dashboard never calls `submit_order`, so it never
needed trading-capable credentials in the first place.

## Simulated backtest (theoretical, not validated performance)

Alpaca's available historical options data isn't deep enough to replay real
past option quotes, so rather than fake that, `app/backtest/` reconstructs
option prices with Black-Scholes over **real historical stock prices**,
reusing the actual production sizing and exit-rule code. It's labeled
theoretical everywhere it appears and is never used as evidence of expected
performance — only of the rule mechanics behaving sanely. Exit checks run
against real 5-minute intraday bars, not just the daily close, specifically
because an earlier daily-only version materially overstated stop-loss losses
whenever the underlying gapped intraday — a discrepancy only visible once
the simulation's checking cadence was compared against the live agent's.

## Validated by live testing, not just unit tests

Two real defects were found by actually running the agent against a live
paper account and a live AI provider, not by unit tests alone: the AI was
being called on every scanned candidate even when a cheaper deterministic
gate had already failed it (fixed by pre-screening before the AI call), and
`duplicate_exposure` was computed once before a scan instead of per
candidate, letting multiple positions open on the same underlying within one
run (fixed by updating the risk context in-memory after each approval). A
separate infrastructure issue surfaced running the agent continuously:
GitHub Actions' native `schedule:` trigger fired unreliably (one run in
several hours) despite a valid 5-minute cron, so the production trigger is
an external scheduler (cron-job.org) calling the workflow's `workflow_dispatch`
API — GitHub's own `schedule:` is kept only as a redundant backup. Wiring
the shared Supabase journal surfaced two more real integration bugs, again
only visible against the real service: Supabase's pooler connection string
includes a `pgbouncer=true` parameter meant for other drivers (asyncpg/Prisma)
that `psycopg2` doesn't recognize and rejects outright, and the Postgres
schema selection initially lived as a Python constant before being moved
into `DATABASE_URL` itself (`options=-c search_path=alpaca`) so it's visible
and changeable from configuration, not buried in code. Real usage of the
dashboard surfaced one more: every page load was rebuilding the database
engine from scratch — including a Postgres round trip to check/create the
schema and tables — instead of reusing one, making every navigation
noticeably slow; fixed by caching the engine per connection URL so that
bootstrap only runs once per process.

## Status

70+ automated tests cover position sizing, max-loss calculation, every risk
gate, invalid-AI-output handling, liquidity rejection, daily-loss limits,
duplicate-position handling, exit conditions, the options scanner, the
simulated backtest, and both the SQLite and URL-parsing paths of the shared
journal. `DRY_RUN=true` by default; paper trading is enforced at two
separate points before any order can be submitted.
