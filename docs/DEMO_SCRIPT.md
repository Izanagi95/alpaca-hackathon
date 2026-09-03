# Demo script (4 minutes)

Judging weighs P&L, technology, creativity and presentation. So this is not a
code tour: it shows a system that is *running*, and the evidence that its
numbers are real. Source code is one click away in the repo if a judge wants
it — spending video time scrolling through files trades away the part only a
video can deliver.

**Lead with the funnel.** 42,926 candidates priced, 52 worth asking the AI
about, 32 traded. That single line is the architecture, the cost argument and
the discipline all at once, and it is the thing no other submission will have.

## Before recording

- Open **https://alpaca-hackathon.vercel.app** a few minutes early. Vercel's
  free tier cold-starts in ~5s; a judge watching you wait is a bad first
  impression, and so is a cold start in the recording.
- Have three tabs ready: the live dashboard, the Alpaca paper account for
  `PA3XHQWG6YPZ`, and a terminal in the repo.
- Warm the numbers you plan to read aloud — they move while the agent runs.
- Screen recording with voiceover is enough. Face cam optional; legible text
  is not. Record at 1080p and keep the browser zoom high enough that the
  tables are readable after compression.

## 0:00 - 0:25 — The number, then the rule

"This agent priced 42,926 option spreads this week. It asked the AI about 52 of
them. It traded 32. That ratio is the whole design: **the AI proposes, and a
deterministic risk engine decides.**"

Show the Overview funnel while saying it.

## 0:25 - 1:00 — Why that order matters

"Most people would wire an LLM to the order endpoint and let it decide. Here
the deterministic gates run *first* — liquidity, days to expiry, credit,
defined risk, portfolio budget, duplicate exposure — and they reject 99.9% of
candidates before a single token is spent. Then the AI gives a structured,
schema-validated opinion. Then the gates run **again**, and the order manager
re-checks the verdict before it will submit anything."

"The AI can veto a trade. It can never force one through. There is no code path
from an AI response to `submit_order`."

## 1:00 - 2:00 — The live dashboard

Scroll the Overview to **What the risk engine turned away**:

"This is which constraint is actually binding. Duplicate exposure stopped
40,893 candidates — 95%. Thin open interest, 24,573. So the 0.07% approval rate
isn't the strategy being arbitrary: the agent is simply already exposed to
almost everything it watches, and it refuses to double up."

Then the **Decision Journal**:

"Every candidate it ever priced is here — approved or rejected — with the
strikes, the expiry, and the exact gates it failed. One scan prices every strike
pair on every expiry, so you see dozens of rows a minute that differ by strike,
not by repetition."

Filter to `APPROVE` to surface the AI rationale rows:

"And where the AI *was* consulted, its actual reasoning is on the record —
implied volatility below realized, regime aligned with trend. Structured JSON in,
validated schema out. A malformed response becomes a forced reject, never a
guess."

## 2:00 - 2:45 — Proof the numbers are real

Switch to the Alpaca account: equity above $100,000, real filled multi-leg
orders.

"Paper account `PA3XHQWG6YPZ`, up about $900. And I didn't take the journal's
word for that."

```powershell
.\.venv\Scripts\python.exe scripts\reconcile_journal.py
```

"This reconciles every journalled trade against the broker's own orders. All 14
openings exist at Alpaca. Six expired unfilled — journalled at zero. And across
every trade the broker can price, the journal and the actual fills agree to
within **$5.50 in total**. The broker is the authority on performance; the
journal explains reasoning. The dashboard says so on every page that shows
P&L."

## 2:45 - 3:30 — What live testing found that tests didn't

"Three things only showed up by running this for real."

1. "The AI was being called on every candidate, including ones a cheap
   deterministic check had already killed — that's what the pre-screen fixed,
   and it's where the 52-out-of-42,926 comes from."
2. "A duplicate-exposure check computed once per scan instead of per candidate
   let three positions open on one underlying in a single run."
3. "GitHub Actions' own cron fired once in several hours despite a valid
   five-minute schedule, so the production trigger is an external scheduler
   calling the workflow API. And Supabase's pooler connection string carries a
   parameter `psycopg2` rejects outright — found against the real service, not
   assumed to work."

## 3:30 - 4:00 — Limits, then close

"Two things I deliberately didn't fake. There's no earnings filter, because
Alpaca doesn't expose a reliable earnings calendar. And the backtest reconstructs
option prices with Black-Scholes over real historical stock prices, because the
historical option data isn't deep enough to replay honestly — so it's labelled
theoretical everywhere it appears."

"Everything is paper-only, enforced at two separate points. The LLM explains and
proposes. A deterministic engine decides. That's the pitch."

## If you only have 2 minutes

Keep: the funnel (0:00-0:25), the gate breakdown (1:00-1:30), the reconciliation
(2:00-2:30), the close. Drop the bug list and the limitations — they live in the
write-up, and the repo is linked.
