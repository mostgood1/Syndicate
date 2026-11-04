# FINDINGS — Soccer Suggested "loses at the close": the corners half is the EVALUATOR, not the board

Lane `soccer-corners-fair-inflation`, session 8000dc38, 2026-11-04 ~17:20–17:50Z. **Read-only**: no code, env or fleet change.
Substrate: the fleet (served `/api/board/layer2-shortlist`, `soccer_source/tracking/book_quotes/*.jsonl` + `.state.json`),
and the 11-02 grade's own per-row output (`C:\tmp\edge-analyses\suggested-grade\out_1026_1101\ev_close.rows.jsonl`).

## The question

The 11-02 Suggested grade (`findings_2026-11-02_suggested_grade.md` §4) put pregame soccer Suggested at **−4.86% [−7.30, −2.44]
EV at the Shin close** (61 bets / 34 games, third window 10-26..11-01), the one cell that tripped the 2% criterion. Its engine
read said the board's fair sat above a fair rebuilt from the quote logs, "the `fair-price-v2` H6 question".

## 1. Where the 61 bets went (11-02 rows, unchanged)

| market | n | board EV at sighting | EV at Shin close | board fair − rebuilt sighting fair | close − sighting drift | flat P&L |
|---|---|---|---|---|---|---|
| alternate_totals_corners | 54 | +3.25% | **−3.78%** | **+2.68 pp** (41 rebuilt; median +2.76) | −0.33 pp | +11.3 u |
| h2h | 5 | +3.11% | −14.17% | +0.36 pp | −3.78 pp | −0.8 u |
| totals | 2 | +3.08% | −10.68% | +0.23 pp | −5.62 pp | +0.4 u |

Every other market, all sports: board fair − rebuilt **+0.20 pp** (348 rows). So the soccer number is corners (54 of 61), and on
corners the loss is the FAIR, not price movement. h2h/totals (7 bets) are genuine early-sighting drift (the 11-02 lead).

## 2. The board's corners fair is correct

Served build 2026-11-04 17:09:37Z (`date=2026-11-05`, 603 corners rows, kickoffs 11-05..11-08). Three fairs per row, all via
production's `consensus_fair_probability(..., method="shin")` from the fleet checkout:

- **board** — the row's `quote.fair_probability`;
- **live** — each book's last price at or before the build, kept only if the shard's `.state.json` saw that key at or after
  build − 10 min (`read_quote_last_seen`: "when did we last LOOK");
- **ev12** — the 11-02 evaluator's rule (`fair_price_eval.evaluate`): each book's last price CHANGE within 12 h before the moment.

| | all rows (n) | suggested rows (n=14) |
|---|---|---|
| board − live | **+0.00 pp** (602; 5 beyond 1 pp) | +0.13 pp (1 beyond 1 pp) |
| board − ev12 | +0.24 pp (582; 101 beyond 1 pp) | **+2.73 pp, median +2.65** (11 beyond 1 pp) |
| ev12 − live | −0.24 pp | **−2.60 pp** |

The board equals the live-book fair. The evaluator's rule reproduces the 11-02 gap (+2.68 pp) on today's Suggested rows.

## 3. Mechanism

The quote tape is a CHANGE log (one row per price change). `odds_book_quotes.read_quote_last_seen`'s docstring:
"`book_age_seconds` ... answer[s] 'when did this price last MOVE' ... A market can be legitimately motionless for twelve hours and
still be perfectly fresh." `fair_price_eval.evaluate` ages books by change time: sighting keeps a book only if its price
changed within `max_age_h` (12 h) before the sighting; the close keeps it only if its last change was within `max_stale_h` (6 h)
of commence. Corners ladders sit motionless for hours, so live books are dropped and the fair rests on whichever book moved —
usually the book being bet. EV against a book's own de-vigged price is minus its margin: the 11-02 rebuilt sighting EV on
these rows was **−2.86%** where the board said +3.18%.

Why Suggested is hit and the population is not (+0.24 pp): Suggested selects rows where the bet book is generous relative to
the other books; dropping the other books removes exactly the evidence that made the row Suggested.

`fair-price-v2`'s H5 (10-16, FALSIFIED) already concluded "the 'stale share' on the served board is cells whose last SIGHTING
is old, not prices that moved -- an unchanged price is still the price". The evaluator's change-age windows contradict that
reading and were not part of H5's test (H5 compared `shin_fresh` vs `shin`, both under the same windows).

## 4. What this does and does not say

- **Does:** the −3.78% corners EV at the close comes from an instrument artifact, so the true corners EV at the close is unknown
  in size and sign, and the soccer −4.86% cannot be read as "soccer Suggested loses". The board's corners fair is not the defect.
  The SIGHTING bias is measured (§2). The CLOSE bias is inferred from the same rule (6 h change window), not measured; the small
  close − sighting drift (−0.33 pp) is consistent with both sides dropping the same books.
- **Does not:** say corners Suggested has edge. Realised: corners +11.3 u on 54 bets (noisy); soccer Suggested per bet pooled
  −7.2% [−24.4, +11.9] (353 / 163), third window +5.2% [−24.1, +36.5] (150 / 66) — no interval excludes 0.
- **Real and small:** h2h/totals sighted early lose to genuine movement (7 bets).

## 5. Owed (not done here — `scripts/fair_price_eval.py` is claimed by OPEN lane `fair-price-v2`)

A liveness-aware method beside `shin` (a book counts at moment t if its key was observed — a change or the state's last-seen —
at or after t − tolerance), reported alongside the existing one, then the 10-26..11-01 grade re-run (the shards survive as
`.jsonl.gz`, which `read_quotes` already reads). Until then any EV-at-close reading of a motionless market (corners, alt ladders)
from this evaluator is suspect, in every sport.
