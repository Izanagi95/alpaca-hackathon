# Demo script (3-5 minutes)

Goal: show the full story — market detected -> opportunity found -> AI
analyzed it -> risk engine approved it -> Alpaca executed it -> agent
monitored it -> agent exited -> P&L recorded — and prove every trade (or
rejection) is explainable.

Setup beforehand (not part of the timed demo):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# fill in paper ALPACA_API_KEY / ALPACA_SECRET_KEY in .env
# (DATABASE_URL optional — empty uses a local SQLite file)
pytest -q
```

## 0:00 - 0:30 — Framing

"This is Options Alpha Agent: an autonomous paper-trading agent that trades
Bull Put Spreads. The one rule the whole system is built around: the AI can
analyze and propose, but a deterministic Risk Engine is the only thing that
can approve a trade. Everything runs against a $100,000 Alpaca **paper**
account — no real capital, ever."

Show `.env`: `PAPER_TRADING_ONLY=true`, `ALPACA_PAPER=true`.

## 0:30 - 1:15 — Read-only integration + MCP

```powershell
.\.venv\Scripts\python.exe scripts\integration_check.py
```

"This confirms we're really talking to Alpaca paper: account status, live
stock quotes, real option contracts, real option quotes." Point at
`READ-ONLY INTEGRATION CHECK PASSED`.

```powershell
.\.venv\Scripts\python.exe scripts\mcp_read_only_demo.py
```

"And this is the official Alpaca MCP Server — the same server you could
point Claude Desktop or Cursor at and ask 'what's my paper account balance'
in plain English. It lists the tools it exposes and calls two read-only
ones: account info and an option chain lookup."

## 1:15 - 2:30 — One trade end to end

Run (or reference) the workflow test / a small driver script that builds one
candidate, runs `TradeWorkflow.evaluate`, and prints the result — or walk
through `tests/test_workflow.py` live:

"Here's one Bull Put Spread candidate on AAPL. It goes through: scoring
(market regime, trend, volatility, liquidity, risk/reward — all numeric, no
LLM), then the AI Analyst, which returns a structured, Pydantic-validated
proposal — score, confidence, rationale, risk flags. If that JSON is
malformed or missing, we hard-reject; we never guess."

"Now the Risk Engine: paper mode, DTE window, minimum credit, bid/ask
spread, open interest, volume, defined-risk check, daily loss circuit
breaker, portfolio risk, duplicate exposure, position count, AI score
threshold — and automatic position sizing from account equity, not a
hardcoded number of contracts."

Show the approved result: `execution.submitted == True`, and — with
`DRY_RUN=true` — that no real order was placed, just a simulated one.

## 2:30 - 3:15 — Monitoring and exit

```powershell
.\.venv\Scripts\python.exe scripts\monitor_positions.py
```

"This is the position manager loop: for every open trade it fetches a live
quote, checks profit target / stop loss / days-to-expiration / regime, and —
if a rule fires — closes the spread and journals the realized P&L. It never
holds to expiration by default, and if a quote isn't available it skips the
position instead of guessing a fill price."

## 3:15 - 4:15 — Dashboard: the "why"

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.dashboard.app:app --reload
```

Open `http://127.0.0.1:8000`. "Four pages: Overview, Daily KPIs, Positions &
Trades, Decision Journal. Every position with entry credit, strikes, exit
reason and realized P&L. The decision journal — for literally every
candidate we ever evaluated, approved or rejected, you can see the AI score
and the exact rationale behind the call. And every page filters by a real
date range, symbol, or decision — not just 'last N rows'."

"This same journal lives in Supabase, not just a local file — GitHub
Actions, this local dashboard, and an optional public copy hosted on Vercel
all read and write the exact same live data. No separate sync step, no
stale snapshot."

## 4:15 - 4:45 — Bugs live testing actually found

"Unit tests can't catch everything. Running this against a real paper
account with the AI actually connected surfaced two real bugs: the AI was
being called on every single candidate, even ones a cheap deterministic
check had already ruled out — timing us out scanning 200 real candidates.
And a risk check for 'don't open two positions on the same underlying' was
only computed once per scan instead of per candidate, letting three
positions open on the same symbol in one run. Both are fixed now, and both
were only found by actually running it, not by writing more unit tests."

If time allows, mention the infrastructure lessons too: "We also found
GitHub Actions' own cron scheduler doesn't reliably fire every 5 minutes —
one run in several hours — so the agent is actually triggered by an
external scheduler instead. And wiring up the shared Supabase database
surfaced a connection-string parameter our driver didn't actually support —
found by testing against the real service, not assumed to work."

## 4:45 - 5:00 — Close

"Everything here is paper-only, fail-closed, and the LLM never has a direct
line to `submit_order` — the Risk Engine is the only gate. That's the whole
pitch: an AI that explains and proposes, and a deterministic engine that
decides."
