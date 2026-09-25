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

## UPDATE 2026-09-25 — NCAAF

Scheduled task `ncaaf-adverse-movement-check`, run 2026-09-25 ~15:20-15:50Z (10:20-10:50 CT). Read-only:
no code, no deploy. The trail was synced from web: all 139 `reports/intelligence/clv_price_trail/*` files
were fetched via `/api/ops/artifacts/stream`, and every one matched its listed `bytes`. Harness:
`scripts/decompose_movement_clv.py --show-circular` at origin/main `29482a44`. Pre-check: `/api/ops/clv/report`
for NCAAF 09-24 has `resolved` 77. Forward CLV is in probability points; diff = toward − away, and a
negative value means the away-moved rows beat the close by more. **CLV, not ROI.**

**What is new here, and it matters: the harness CI treats every re-rank as independent.** One trail key
(event|market|player|segment|side) contributes one observation per re-rank, so `n` counts re-ranks, not
bets or games. I re-ran a scratch copy of the harness (the repo is not modified). It reproduces every
number below exactly and also records the key per observation. That gives two more honest CIs: a Welch
test on per-key means, and a 2,000-draw bootstrap that resamples events.

| sport, window | scope | diff (harness), 95% CI | n toward/away obs | keys t/a | events | key-level diff, CI | event-cluster bootstrap CI | circular control |
|---|---|---|---|---|---|---|---|---|
| **NCAAF 09-20..25** | price:same_book | −2.53 [−3.66, −1.40] | 71/68 | **11/11** | **1** | −1.40 [−2.65, −0.16] | n/a (1 event) | +0.76 |
| NCAAF | line:same_book | — | 0/2 | 0/1 | 1 | — | — | — |
| NFL 09-20..24 | price:same_book | −2.81 [−3.29, −2.33] | 931/1282 | 242/290 | 16 | −4.96 [−5.95, −3.97] | [−11.35, −1.55] | +2.97 |
| NFL | line:same_book | −1.39 [−2.51, −0.27] | 150/133 | 72/60 | 11 | −1.88 [−3.98, +0.22] | [−4.26, −0.18] | +0.19 |
| WNBA 09-20..24 | price:same_book | −3.13 [−3.38, −2.89] | 4849/7668 | 1266/1609 | 18 | −3.57 [−4.06, −3.07] | [−3.94, −2.58] | +2.34 |
| WNBA | line:same_book | −2.32 [−3.22, −1.42] | 347/347 | 99/95 | 16 | −2.65 [−4.25, −1.04] | [−4.77, −0.68] | +0.44 |
| MLB 09-20..24 | price:same_book | −7.37 [−8.00, −6.74] | 1704/2121 | 558/721 | 56 | −7.02 [−7.89, −6.16] | [−8.61, −6.10] | +1.60 |
| MLB | line:same_book | −2.23 [−3.10, −1.37] | 321/254 | 100/62 | 51 | −3.31 [−5.42, −1.20] | [−3.44, −0.97] | −0.01 |
| MLB | price:book_agnostic_close | −2.12 [−2.37, −1.88] | 1434/4606 | 706/1437 | 56 | −3.05 [−3.44, −2.66] | [−3.15, −1.28] | +0.26 |

`price:book_agnostic_close` is **absent** for NCAAF, NFL and WNBA: every joined close for those sports
comes back `same_book`. They are the quote-log closes from `clv-close-from-book-quotes`. Joined keys:
NCAAF 81 of 30,415 in the trail, NFL 1,395, WNBA 2,558, MLB 4,900.

### NCAAF verdict: UNRESOLVED

The sign agrees with the other three sports: away-moved rows beat the close. But **the whole scored
population is ONE game** (event `9e0eaa3f…`, Thursday 09-24): 11 keys per arm, re-observed across the
09-21..24 board dates. With one event, no CI can separate "away-moved rows revert" from "this game's market
did something." The harness's [−3.66, −1.40] is not a pass at this n. The other 30,334 NCAAF trail keys
have no close yet, because they are Saturday 09-26 games. Per-date split for the one game: 09-21 −1.20,
09-22 −1.25, 09-23 +0.09, 09-24 −3.90.
**n still needed:** at least ~50 keys per arm spread over at least ~10 games. Saturday 09-26's full slate should give
that. Re-run over 2026-09-26..27 after those games are final.

### NFL / WNBA / MLB over five dates: the 09-20 finding holds, smaller and still clear of zero

- **Away-moved rows beat the close at the same book in all three sports.** This holds for both price and line moves, and
  under the event-cluster bootstrap. The one exception is NFL line at key level, where the upper bound is +0.22.
  **H3 stays REJECTED for NFL, WNBA and MLB, now on 16, 18 and 56 events.**
- The effect is **smaller** than on 09-20 alone: NFL −9.92 → −2.81, WNBA −6.50 → −3.13. MLB grew
  (−14.23 at n 31/31 → −7.37 at n 1704/2121). NFL rests on only 16 games; its event-cluster CI is wide
  ([−11.35, −1.55]) but excludes 0.
- **CORRECTION to "the interim movement is transient and fully reverts" (09-21).** Over five dates the
  circular price:same_book control is NOT near zero: NFL +2.97, WNBA +2.34, MLB +1.60. Open→close CLV =
  interim move + forward. So the away-moved rows revert **partly**, not fully. The move partly persists to the
  close, and part of it comes back. For a bet-now ranking only the forward leg matters, and it still favours away.

**Movement term: the sign looks backwards for a bet-now ranking. A weight change is now a user decision.**
Three sports, five dates, event-clustered CIs clear of zero: the term penalises the rows that beat the close.
It was **NOT changed** (`_SCORE_MOVEMENT_WEIGHT` / `_SCORE_MOVEMENT_LINE_WEIGHT` untouched).
