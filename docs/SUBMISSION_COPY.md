# lablab.ai submission — copy draft

Not a project document — this is copy-paste material for the submission
form itself (title, descriptions, tags, slide outline). Not linked from
README, not meant to be browsed by judges as a repo file.

## Project title

Options Alpha Agent — Autonomous Bull Put Spread Trading with a Deterministic Risk Gate

(Shorter alternative if there's a character limit: "Options Alpha Agent")

## Short description

An autonomous options-trading agent for Alpaca paper trading: an LLM
proposes Bull Put Spreads with a score and rationale, but a fully
deterministic Risk Engine is the only thing that can approve an order —
safe, explainable, and battle-tested against a live paper account.

## Long description

**What it does.** Options Alpha Agent scans a watchlist of liquid
underlyings, builds real Bull Put Spread candidates from Alpaca's live
option chain (real strikes, real greeks, real quotes), scores them
deterministically, and asks an LLM for a structured second opinion. Every
candidate — approved or rejected — passes through a deterministic Risk
Engine that checks liquidity, DTE, credit, defined-risk, daily loss limits,
portfolio risk, duplicate exposure, and position sizing before anything can
be submitted as a real (paper) order. The AI never has a direct line to
`submit_order`.

**Why it's safe by design.** The one rule everything is built around: the
LLM proposes, it never decides. Its output is validated against a strict
schema before it can influence anything, and even a valid "APPROVE" from the
AI can be overridden by the Risk Engine. This isn't a slogan — it was
verified by actually running the agent against a live paper account, which
surfaced two real bugs (the AI being called on hopeless candidates instead
of being pre-screened out, and a duplicate-exposure check that didn't
update mid-scan) that were found and fixed through live testing, not just
unit tests.

**Technology.** Built on `alpaca-py` (Trading API + Market Data API,
multi-leg MLEG orders for the spread), the official Alpaca MCP Server
(wired in as a read-only query/demo path), and two interchangeable LLM
backends — Anthropic Claude and Featherless.ai (serving open-weight models
like Qwen3). The autonomous loop runs continuously across the multi-day
scoring window via GitHub Actions, triggered by an external scheduler
(cron-job.org) after discovering GitHub's own cron scheduler doesn't
reliably fire at short intervals — another real issue found and fixed
during development, not assumed away.

**Honesty about limits.** There's no earnings/event-risk filter — Alpaca
doesn't expose a reliable earnings calendar, and rather than fake it, it's
explicitly documented as absent. A simulated backtest (Black-Scholes over
real historical stock prices, since Alpaca's historical options data isn't
deep enough to replay honestly) is clearly labeled as theoretical evidence
of the rule mechanics, never as a performance guarantee.

**Explainability.** Every decision — approved or rejected — is journaled
with its full market/option inputs, AI rationale, and itemized risk checks.
A dashboard surfaces live portfolio data alongside the trade and decision
journal, so the "why" behind every trade is always reconstructable.

## Technology & category tags

`Alpaca Trading API` `Alpaca MCP Server` `Options Trading` `Algorithmic
Trading` `AI Agents` `LLM` `Anthropic Claude` `Featherless.ai` `Python`
`FastAPI` `Risk Management` `Autonomous Agents` `GitHub Actions`

(Check the platform's actual available tag list when submitting — pick the
closest matches from lablab.ai's fixed set if these exact tags don't exist.)

## Slide outline (turn into an actual deck — Google Slides / PowerPoint)

1. **Title** — project name, one-line pitch, your name/team.
2. **The problem** — options trading is complex and risky; an AI agent
   needs guardrails a human would apply, not just a model that "sounds
   confident."
3. **Architecture** — the pipeline diagram from `docs/ARCHITECTURE.md`
   (Market Analyst → Scanner → Scoring → AI Analyst → Risk Engine →
   Execution → Monitor → Journal).
4. **The core principle** — "AI proposes, Risk Engine decides" — one slide,
   the AI-proposal → Risk-Engine → approve/reject diagram.
5. **Risk Engine in detail** — list the actual gates (liquidity, DTE,
   credit, defined-risk, daily loss, portfolio risk, duplicate exposure,
   position sizing formula).
6. **Found by testing, not assumed** — the two live bugs (AI pre-screening,
   duplicate exposure) and the GitHub Actions scheduling fix. This is your
   strongest "robustness" evidence — don't bury it, put it on its own slide.
7. **AI Analyst** — structured JSON in, validated schema out, two
   interchangeable providers (Anthropic / Featherless), fail-closed on
   invalid output.
8. **Dashboard screenshot** — portfolio, trade journal, decision journal
   with rationale.
9. **Honest limitations** — no earnings filter, theoretical-only backtest —
   framed as rigor, not as weaknesses to hide.
10. **Results / status** — test count, live-verified pipeline, what's
    running now (GitHub Actions + cron-job.org, every 5 minutes, all week).
11. **Thank you / links** — repo, demo video, contact.
