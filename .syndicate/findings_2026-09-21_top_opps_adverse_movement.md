# Top Layer 2 opportunities move AGAINST the pick — mechanical, and in MLB it is value, not adverse selection

Lane `layer2-adverse-movement-sanity`, session 9e340058, 2026-09-21. Read-only.
Hypotheses were registered in the lane (`691689d0`) BEFORE any test.

## The observation — confirmed

User: *"a majority of our top board opps have line movement in the opposite direction
of the recommendation."* Board `written_at` 2026-09-21T15:25:28Z, 2,000 scored rows:

| | away (moved against the pick) | flat | toward |
|---|---|---|---|
| **top 100** | **67%** | 21% | 12% |
| top 25 | 64% | 24% | 12% |
| whole board | 50% | 29% | 21% |

The top is **enriched** for `away` (67% vs a 50% base rate) and depleted for `toward`.

## H1 — mechanical selection: SUPPORTED

A price that lengthens on our side carries more EV, and EV dominates the score.

| | median `ev_component` | median movement penalty |
|---|---|---|
| away, whole board | **−2.38** | — |
| flat, whole board | −3.82 | — |
| toward, whole board | −4.55 | — |
| away, top 100 | 3.47 | −0.59 |
| toward, top 100 | 2.74 | +0.45 |

The ~2 pp EV gap is larger than a movement penalty capped near 1, so away-moved rows
clear into the top by arithmetic. **This is not a model signal.**

## H2 — single-book drift: MOSTLY SUPPORTED

For the 67 top-100 `away` rows: the **book** moved a median **2.84 pp**, the **consensus
fair** only **0.79 pp**. In 60% the consensus moved the same way; in **55%** it moved less
than a third as far. Best-of-N is selecting the book that drifted long relative to the market.

## H3 — adverse selection: REJECTED FOR MLB. NOT MEASURED ELSEWHERE.

`scripts/decompose_movement_clv.py` over the published price trail (39 hourly chunks,
47,558 points), dates 2026-09-20..21. FORWARD CLV = observation -> close, the only
non-circular target; + means a bet at the observed price BEATS the close.

| scope | moved toward (n) | moved away (n) | diff toward−away, 95% CI |
|---|---|---|---|
| **price, same book** (cleanest) | **−5.97** (55) | **+6.72** (45) | −12.68 [−17.00, −8.37] |
| price, book-agnostic close | −2.48 (345) | +2.93 (1,132) | −5.41 [−6.16, −4.66] |
| price, different-book close | −16.87 (14) | +6.13 (14) | thin |

**Rows that moved away REVERT toward the pick.** A bet at the drifted-long price beats the
close; a bet at a price that had already moved toward us loses to it.

**The circular control is what makes this interpretable.** Open -> close CLV is the SAME for
both arms (same book: +0.61 toward vs +0.03 away; book-agnostic: +1.37 vs +1.55). The close
ends where it would have regardless of the interim move — **the interim movement is
transient and fully reverts.** That is consistent with regression toward the mean in a
noisy best-of-N price, and it is exactly why betting at the long moment wins.

**Stale-quote alternative: NOT SUPPORTED.** If `away` prices were our feed lagging a book
that had already moved back, the reversion would be fictional. Quote age says otherwise:
top-100 `away` median book age ~1,181 s, the same as `flat` (~1,193 s); `toward` is OLDER
(~2,588 s). Whole board: all three within seconds (~3,990–4,012 s).

## What this rests on — the limit that matters most

**Almost entirely MLB.** Resolved rows: MLB 4,947 (09-20) + 1,039 (09-21); soccer 231
(09-20); **NFL, NCAAF and WNBA: 0 on both dates.** The top-100 `away` rows are NCAAF 22,
WNBA 21, MLB 20, NFL 2, soccer 2 — so **the outcome evidence covers only 22 of 67 (33%)**.

- **MLB** (91% of its top-100 rows move away — the most extreme skew): the concern is
  answered. Those rows are value, not adverse selection.
- **NCAAF / WNBA / NFL** (45 of the 67): **unanswered.** H1 and H2 apply to them, but
  whether they revert is unmeasured. Not extrapolated from MLB.

## Implication for the movement term — recorded, NOT acted on

The term REWARDS `toward` and PENALISES `away`. In MLB, `toward` then loses ~6 pp to the
close at the same book and `away` gains ~7. **For a bet-now ranking its sign looks
backwards: it pushes down the rows that beat the close.** This is exactly the evidence
`_SCORE_MOVEMENT_WEIGHT`'s own comment names as the gate for changing it ("settled rows, with
CLV decomposed by component"). **It is not enough to act on:** ~2 dates, one sport, same-book
n 55/45. Re-run when NCAAF/WNBA/NFL closes resolve and several more days accumulate.

## Not claimed

- CLV is not ROI; the population is the published board, not filled orders.
- Fillability is supported (quotes no staler), not proven: a quote can be fresh in our data
  and gone at the book.
- The result is for PRICE movement; line-move arms are thin (n ≤ 32 per arm).

## Leads, recorded not chased

- **Trail chunk names lack the WRITE date.** `<board date>T<write hour UTC>.jsonl` —
  `2026-09-21T18.jsonl` was written 09-20 18:00Z for the next-day board. A board date written
  across two calendar days at the same hour shares one file; points survive (epoch-sorted) but
  publish-on-seal can mark the file sent before the second day's points arrive.
- **The CLV join resolved 0 NCAAF / WNBA / NFL rows** for 2026-09-20 and 09-21, including
  Saturday's NCAAF slate. **ROOT-CAUSED 2026-09-21 (lane block, Z-series):** the closes are not
  captured. The odds-history writer never runs on the fast-mode lanes that refresh those sports
  (`refresh_odds_sources.py:3083` returns before the post-refresh step); web holds 0 NFL and 0 NCAAF
  history shards ever, and no WNBA shard for 08-31..09-21. Football has two further defects behind
  that one (week-keyed shards vs a date-keyed join lookup; legacy writer inputs absent on web), so
  waiting will not fill this gap. Movement and edge in those sports cannot be graded by CLV until fixed.

## UPDATE 2026-09-21 ~17:10Z — NFL and WNBA answered; a correction to the MLB population

Lane `clv-close-from-book-quotes` gave the CLV join a close for NFL, WNBA and NCAAF (the
per-book quote log; web `1dc4f7ec` -> `de6da1b7`, every prediction matched). Re-run of
`scripts/decompose_movement_clv.py` on **2026-09-20 only** -- every game on that date had
finished -- against the published trail (which starts 09-20 ~18:25Z, so it covers the late
NFL window, SNF, the evening WNBA and MLB games). Forward CLV, same-book price moves,
toward minus away (negative = rows that moved AWAY beat the close by more):

| sport | toward − away, 95% CI | n toward / away | circular control |
|---|---|---|---|
| **NFL** | **−9.92 [−11.49, −8.36]** | 213 / 206 | +0.35 |
| **WNBA** | **−6.50 [−7.62, −5.38]** | 382 / 466 | +1.15 |
| MLB | −14.23 [−20.15, −8.32] | 31 / 31 (book-agnostic −12.78, n 146/301) | +0.35 |
| NCAAF | not measurable yet -- Saturday's games predate the trail | 0 | — |

**H3 (adverse selection) is REJECTED for NFL and WNBA as well as MLB.** Rows whose price
moved against the pick revert toward it and beat the close at the same book; the circular
open->close control stays near zero. NCAAF is owed after this week's games (Thu 09-24 on).

**CORRECTION to the MLB population above.** The "MLB 4,947 (09-20) + 1,039 (09-21)" rows
included 09-21 closes read at ~15:40Z, before that day's games started: the odds-history
path handed back the latest price as a "close" (today's report at 17:07:51Z: 971 of 1,102
resolved rows were unstarted games). Fixed in `a720941d` (no close for an unstarted game
from any source). The MLB verdict does not change -- the 09-20-only numbers above point the
same way -- but the 09-21 part of the earlier n was not CLV.

**Movement term: still NOT changed.** Three sports now agree in sign with CIs well clear
of zero, so the sign looks backwards for a bet-now ranking. But this is one evening of
trail coverage. Re-run over 5-7 days (and NCAAF's first slate) before proposing a change.
