# Options Alpha Agent — one-page write-up

## What it is

An autonomous, paper-trading-only agent that trades defined-risk **Bull Put
Spreads** on Alpaca. It scans liquid underlyings, scores candidates
quantitatively, asks an LLM for a structured second opinion, and executes
only what a deterministic Risk Engine approves — with automatic position
sizing, configurable exit rules, and a full audit trail of why every trade
was approved or rejected.

## Why the architecture is safe by design

The single rule the system is built around: **the LLM proposes, it never
decides.** `AIDecisionLayer` returns a Pydantic-validated `AIProposal`
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

## Explainability

Every candidate the agent ever evaluates — approved or rejected — is written
to the `decisions` table with its market/option inputs, AI proposal,
rationale, and the itemized risk-engine checks that passed or failed. Every
order actually submitted is separately tracked in `trades` from open to
close, with exit reason and realized P&L. The dashboard
(`app/dashboard/app.py`) surfaces both tables plus aggregate scan/approve/
reject counts.

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
API — GitHub's own `schedule:` is kept only as a redundant backup.

## Status

55+ automated tests cover position sizing, max-loss calculation, every risk
gate, invalid-AI-output handling, liquidity rejection, daily-loss limits,
duplicate-position handling, exit conditions, both AI providers, the
options scanner, and the simulated backtest. `DRY_RUN=true` by default;
paper trading is enforced at two separate points before any order can be
submitted.
