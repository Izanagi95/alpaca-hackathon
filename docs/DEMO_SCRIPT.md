# Demo script (3 minutes)

Written to be **spoken by a non-native English speaker**: short sentences, plain
words, one idea per line. Roughly 320 words of narration — about 3 minutes at a
calm pace. Every line is short enough to say in one breath, so you can record it
in small takes and stop wherever you need to.

The screen does most of the work. You do not have to describe what is visible —
just say the number and let the viewer see it.

Judging weighs P&L, technology, creativity and presentation. So this shows a
running system, not the source code. The repo is one click away.

## Before recording

- Open **https://alpaca-hackathon.vercel.app** five minutes early. The free
  Vercel tier is slow on the first request.
- Three tabs: the live dashboard, the Alpaca account `PA3XHQWG6YPZ`, a terminal.
- Check the numbers again before you record. They change while the agent runs.
- Zoom the browser in. Text must stay readable after video compression.
- Speak slowly. Slow and clear is better than fast and fluent.

---

## 0:00 - 0:20 — Open with the number

*Show: the Overview funnel.*

> "This agent priced forty-two thousand option spreads this week."
>
> "It asked the AI about fifty-two of them."
>
> "It traded thirty-two."
>
> "This is the design: the AI proposes. A risk engine decides."

## 0:20 - 0:50 — The rule

*Show: the four funnel tiles, then scroll down slowly.*

> "Many agents let the model send the order. This one does not."
>
> "First, deterministic gates run. Liquidity. Credit. Days to expiry. Risk
> budget."
>
> "They reject ninety-nine percent of candidates. No AI call. No cost."
>
> "Then the AI gives a structured opinion."
>
> "Then the gates run again, before any order."
>
> "The AI can block a trade. It can never force one."

## 0:50 - 1:30 — Why it rejects so much

*Show: "What the risk engine turned away".*

> "Here is which rule stopped what."
>
> "Duplicate exposure: forty thousand candidates. Ninety-five percent."
>
> "The agent already holds a position in almost every symbol it watches."
>
> "So it refuses to double up. That is the whole reason for the low approval
> rate."

## 1:30 - 2:00 — Every decision is on the record

*Show: Decision Journal. Then filter to APPROVE.*

> "Every candidate is here. Approved or rejected."
>
> "The strikes. The expiry. The exact rules it failed."
>
> "And where the AI was asked, its reasoning is saved too."
>
> "Structured data in. Validated schema out. A bad response becomes a reject."

## 2:00 - 2:40 — The numbers are real

*Show: the Alpaca account. Then run the command.*

> "This is the paper account. Up about nine hundred dollars."
>
> "I did not trust my own journal. I checked it."

```powershell
.\.venv\Scripts\python.exe scripts\reconcile_journal.py
```

> "This compares every trade against the broker's real orders."
>
> "All fourteen exist. Six never filled. Those are recorded as zero."
>
> "The rest agree with the real fills, within five dollars and fifty cents."
>
> "The broker is the truth about money. The journal explains the reasoning."

## 2:40 - 3:00 — Close

*Show: the Overview one more time.*

> "Two things I did not fake. There is no earnings filter — the data is not
> reliable. And the backtest is theoretical. It says so everywhere."
>
> "Paper trading only. Checked twice before any order."
>
> "The AI explains. The engine decides."

---

## If you want 2 minutes

Keep 0:00-0:20, 0:50-1:30, 2:00-2:40, and the last two lines. Drop the rest.

## Words to avoid while speaking

If a word is hard to say, replace it. Meaning matters more than vocabulary:

| Hard | Say instead |
|---|---|
| deterministic | fixed rules / the rules |
| reconciliation | I checked it against the broker |
| duplicate exposure | two positions on the same stock |
| schema-validated | checked against a strict format |
| candidate | option spread |

You can also put these words on screen as text and simply say the short version.
