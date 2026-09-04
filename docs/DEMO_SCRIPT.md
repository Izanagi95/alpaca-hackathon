# Video script — slides + live demo (3 min 30)

The submission asks for a slide deck **and** a video. The deck is submitted
whole, on its own. The video does not walk through all eleven slides — it uses
five of them as the spine, then switches to the running system for the middle,
then returns to the deck to close. Slides carry the argument; the live product
proves it.

Written to be **spoken by a non-native English speaker**: short sentences, plain
words, one idea per line. About 300 words of narration in 3:30, so there is room
to speak slowly and to pause on each screen.

**Deck:** https://claude.ai/code/artifact/b4e5900c-800f-4264-8d20-954c240d5fb0
(arrow keys or click the edges to advance)

**Deck order in this video: 1 → 2 → 4 → (switch to the browser) → 6 → 9 → 11.
Always forward, never back.** The deck only moves one slide at a time, so
jumping backward mid-recording means the viewer sees you flip through slides
you already showed — that is the "it looks like it's skipping pages" problem.
Skipping a slide forward (3, 5, 7, 8, 10) is fine: land on it for a fraction of
a second on the way past, which reads as a normal advance, not a stumble.

## Before recording

- Open **https://alpaca-hackathon.vercel.app** five minutes early. The free
  Vercel tier is slow on the first request.
- Four tabs: the deck, the live dashboard, the Alpaca account `PA3XHQWG6YPZ`,
  a terminal.
- Check the numbers again before recording. They change while the agent runs.
- Zoom in. Text must stay readable after video compression.
- Speak slowly. Slow and clear beats fast and fluent.

---

# PART 1 — SLIDES (0:00 - 1:15)

## 0:00 - 0:20 · Slide 1 "Riskgate"

Start here and stay on it for the whole line — the numbers are said, not
shown yet. The live dashboard proves them on screen in Part 2, which lands
better than showing the same numbers twice.

> "This is Riskgate. An autonomous options trading agent on Alpaca."
>
> "This week it priced forty-two thousand option spreads."
>
> "It asked the AI about fifty-two of them."
>
> "It traded thirty-two."

## 0:20 - 0:45 · Slide 2 "The problem"

Press → once to advance.

> "Options carry real risk. A model that sounds confident is not enough."
>
> "So I did not give the AI the order button."

## 0:45 - 1:15 · Slide 4 "The AI can stop a trade. It can never start one."

Press → twice — this passes slide 3 in an instant, which is fine, then lands
on slide 4. Stay here; it is the most important slide.

> "Fixed rules run first. Liquidity. Credit. Days to expiry. Risk budget."
>
> "They stopped forty-two thousand candidates. The AI was never asked."
>
> "Fifty-two passed. Those went to the AI."
>
> "The AI stopped twenty of them."
>
> "Thirty-two cleared both. And only the rules decide the size."
>
> "Each side can refuse. Neither can approve alone."

---

# PART 2 — LIVE DEMO (1:15 - 3:05)

Switch to the browser. Say it out loud so the change is clear:

> "This is not a mockup. It is running right now."

## 1:15 - 1:35 · Dashboard Overview — the funnel

> "Same four numbers, live."
>
> "Every candidate is priced from the real option chain."

## 1:35 - 2:05 · "What the risk engine turned away"

> "This is which rule stopped what."
>
> "Two positions on the same stock: forty thousand candidates. Ninety-five
> percent."
>
> "The agent already holds almost every symbol it watches."
>
> "So it refuses to double up. That explains the low approval rate."

## 2:05 - 2:30 · Decision Journal (then filter to APPROVE)

> "Every candidate is here. Approved or rejected."
>
> "The strikes. The expiry. The exact rules it failed."
>
> "And where the AI was asked, its reasoning is saved too."

## 2:30 - 3:05 · The Alpaca account, then the check

Switch to the Alpaca tab. Then show the prepared screenshot (see below) instead
of running the command live — a live command can fail, hang, or take too long
on camera, and this result does not need to be recomputed on the spot.

> "This is the paper account. Up about nine hundred dollars."
>
> "I did not trust my own journal. I checked it."
>
> "I compared every trade against the broker's real orders."
>
> "All fourteen exist. Six never filled. Those count as zero."
>
> "The rest match the real fills, within five dollars and fifty cents."

**Prepare this screenshot ahead of time, not during recording:** run
`.\.venv\Scripts\python.exe scripts\reconcile_journal.py` once, beforehand,
with credentials and `DATABASE_URL` pointed at the **same** account — the
judged one, `PA3XHQWG6YPZ` — and screenshot the `--- realized P&L ---` block.
The script itself warns if the two are mismatched (`MISMATCH: none of the
journal's orders exist on this account`) rather than showing wrong numbers, so
a mismatch there means the environment is misconfigured, not that anything is
wrong with the agent.

---

# PART 3 — BACK TO SLIDES (3:05 - 3:30)

The deck was left on slide 4. Switch back to that tab — do not reopen or
reset it, so the next advance continues forward from where it was.

## 3:05 - 3:15 · Slide 6 "Found by testing"

Press → twice (passes slide 5) to land on slide 6. This is the one place in
the video that names a specific bug instead of just claiming rigor — "I
tested it" says nothing on its own; the fifty-two ties back to a number
already on screen.

> "One real bug: the AI used to be asked about every candidate."
>
> "That's forty-two thousand calls. Now it's fifty-two."

## 3:15 - 3:25 · Slide 9 "Who it's for"

Press → three times (passes slides 7 and 8) to land on slide 9.

> "This is not only for options."
>
> "It's a pattern for any AI agent near something that can lose money."

## 3:25 - 3:30 · Slide 11 "Close"

Press → twice (passes slide 10) to land on the last slide.

> "Fixed rules first. The AI second. Neither one alone."

---

## Slides used in the video

| Deck slide | Used | Why |
|---|---|---|
| 1 Title | ✓ | one line of identity |
| 2 The problem | ✓ | sets up the rule |
| 3 Architecture pipeline | — | detail; deck only |
| 4 AI proposes / engine decides | ✓ | the core argument |
| 5 Nine gates | — | the live table shows this better |
| 6 Found by testing | ✓ | robustness, 10 seconds |
| 7 AI analyst | — | covered by the journal demo |
| 8 Dashboard + funnel | — | the live dashboard shows this better, and showing it live beats repeating a static copy |
| 9 Who it's for | ✓ | vision beyond this one hackathon |
| 10 Status | — | deck only |
| 11 Close | ✓ | closing line |

Skipped slides are not wasted — the deck is judged as its own deliverable, and a
judge who wants the pipeline diagram or the full gate list will find them there.

## If you want 2 minutes

Slide 4 (the rule) → the gate breakdown live → the reconciliation → the last two
lines. Drop parts 1 and 3 except the closing line.

## Words to avoid while speaking

If a word is hard to say, replace it. The slide can show the technical term
while your voice says the simple one:

| Hard | Say instead |
|---|---|
| deterministic | fixed rules / the rules |
| reconciliation | I checked it against the broker |
| duplicate exposure | two positions on the same stock |
| schema-validated | checked against a strict format |
| candidate | option spread |
