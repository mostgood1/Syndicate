# Findings 2026-09-01 — MLB Polymarket prop no-match: the rate, complete

Lane `prop-rung-miss-rate`, session e063e054. Instrument: `prop_unmatched_classes`
(complete per-row classification, deployed `839bfa06` live 20:18:42Z), read off
the first post-boot `POLYMARKET_UNMATCHED` line, cycle ~20:30Z. License: per
family, sum(classes) == `no_match|mlb|<family>` on the SAME line — held exactly
on all 7 families, 532 = 532.

## The rate (denominator: 532 prop no_match rows, one cycle, date 2026-09-01)

| class | rows | share |
|---|---|---|
| player_not_listed | 347 | **65.2%** |
| rung_miss | 146 | **27.4%** |
| near_token (`wilcon2`-class candidate) | 26 | 4.9% |
| fixture_miss | 13 | 2.4% |

**The lane's hypothesis is FALSIFIED.** Rung-miss is not the plurality —
player-not-listed is, by 2.4×. The 19:18:45Z three-sample read (2 of 3
rung-misses) was exactly the anecdote-for-a-rate trap the counter was built to
remove, and it removed it against my own written hypothesis.

## The structure under the headline: batter vs pitcher props are different populations

- **Batter families** (hits 175, hits_runs_rbis 134, total_bases 167 = 476 rows):
  player_not_listed 342 (**71.8%**), rung_miss 98 (20.6%), near_token 26 (5.5%),
  fixture_miss 10 (2.1%). The venue lists ~6–10 star/lineup batters per game
  (visible in every sample's `fixture_tokens`); our board quotes far more.
- **Pitcher families** (strikeouts 35, outs 17, earned_runs 3, hits_allowed 1 =
  56 rows): rung_miss 48 (**85.7%**), player_not_listed 5, fixture_miss 3.
  Strikeouts is 35/35 = **100% rung_miss** — the venue lists our pitchers, just
  not our exact line (e.g. Gasser K: board 4.5, venue {1.5, 2.5, 6.5}).

So "widen rung matching" is a PITCHER-prop lever (and a batter minor); batter
coverage is bounded by the venue's listing depth, not by rungs. Note rung
recovery means quoting a DIFFERENT contract than the board line (alternate
rungs), a coverage-widening decision with its own pricing question — not a join
fix.

## Two named observations (not conclusions)

1. **Board-name disambiguators poison our token derivation.** Sample: player
   `Max Muncy (2002)` derived token `max200` — the parenthetical year survives
   cleaning and becomes the "surname". Every such row classifies
   player_not_listed regardless of venue listing. Fixing derivation CHANGES
   MATCHING for exactly the names that exist to disambiguate two real players —
   needs its own lane, tests for both-Muncys-on-board, and the ambiguity
   refusal in view. Do not hotfix.
2. **batter_home_runs refusals went 65 (19:18Z) → 0 (20:30Z)** while total prop
   no_match grew 224 → 532 (board_rows 1375 → 2409; the 19:54:35Z
   `props_now_available` sim expanded the board side). Whether hr all matched or
   left the board this cycle is not decomposable from this line; a matched-by-
   family counter would answer it if anyone needs it.

## Rate stability caveat — THIS IS A PREGAME RATE, and it decays in minutes

This is ONE cycle's rate on a moving population (board grew 75% between the two
readings as props became available). The counter emits every cycle now — the
next reader should quote a fresh line, not this table.

**Measured decay (peer cross-read, lane kalshi-soccer-forward-date, who first
reproduced the 20:30:58Z table above EXACTLY from the raw line, then read the
next cycle):** 12 minutes later (20:42:57Z) the denominator collapsed n=532 →
237 (−55%) as MLB first pitches arrived (~3:30–3:45pm CT); pitcher families
fell n=56 → 11 (strikeouts 35 → 5) and their split inverted to fixture_miss
72.7% — an underpowered re-read of a shrinking denominator, NOT a
contradiction. So: **the 85.7% pitcher rung-miss figure is a PREGAME rate.
Anyone re-reading mid-slate will watch it evaporate and could wrongly record
this finding as unreproducible.** Same rule as the standing board-coverage
lesson: split by game state, and quote the slate state + read time beside any
rate from this counter.

## Instrument cost

Same-cycle `POLYMARKET_BOARD_JOIN elapsed_s=11.92` (pre-change baseline 20.24s
at 18:10Z on a smaller board) — no visible regression; the per-fixture profile
cache did its job.
