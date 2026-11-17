# NBA live props: does the stat-progress re-sim beat the books, and at what quote age? (pre-registration)

Lane `nba-live-prop-grade`, for `#736` (the Decision Engine). `plan_one_engine_pregame_live.md` section 4 ranks "live
props from stat progress" second: a player's pace against his projection is information a slow book may not price.
It was unmeasured. The first-ranked lead, college halves, was graded the same way (`findings_2026-11-13_college_segment_grade.md`):
no edge against fresh books. Session e32fef1a.

**REGISTERED 2026-11-14 20:05Z (2:05 PM CST), BEFORE ANY OUTCOME WAS READ.** The grade has not run. The "Result" section is appended once,
after one grade run; nothing above it is edited after that.

## What is graded

Every OPINED row of the stat-progress expert (`engine_experts.stat_progress_expert`, `stat_progress/1`, on main
`00d55f97a`) for every NBA game in the official box score dated 2026-11-11 through 2026-11-16. Each row: at one logged
re-sim tick, one player prop line a book was quoting; the re-sim's P(over) given what the player has banked
(`liveModelProbOver`, Agresti-Coull at n = `simsRun`) beside the books' de-vigged median at that instant; and the quote
age, the age of the NEWEST usable book's quote then (at most 900 s; older books are left out of the prior). The props
log is read from `live_evidence/nba/<date>.props.jsonl` for 11-10 through 11-17; each file is priced against its own
`book_quotes` shard plus the neighbouring shards' prop rows for the same games. Rows seen twice are counted once.

- **Outcome:** the player's final line in `<SYNDICATE_DATA_ROOT>/nba_source/data/processed/player_logs.csv`
  (stats.nba.com via nba_api, rebuilt daily). This is not the ESPN box the re-sim banks from. Join: the game by
  (`GAME_DATE`, home, away) read from `MATCHUP`; the player by (team, the engine's own name key
  `live_resim.normalize_name`, which merges spellings such as Herb / Herbert Jones). A player not found on his own team
  is not graded (counted).
- **Event:** final above the line ("over"). Points PTS, rebounds REB, assists AST, threes FG3M, steals STL, blocks BLK;
  the combos are sums; double-double / triple-double count how many of PTS REB AST STL BLK reached 10 (lines 1.5 /
  2.5, the producer's). A final on the line is a push and is dropped. A row whose over was already banked at the tick
  is dropped (0 at registration: the producer refuses an exact 0 or 1).
- **Score:** per row, d = engine Brier minus books Brier, negative where the engine is better. A cell reads the
  row-weighted mean of d with a GAME-clustered bootstrap interval (20,000 draws, seed 736).

## The decision (fixed here; `PREREG` in `scripts/nba_live_prop_grade.py`)

Twelve primary tests: six market groups x quote age at most 30 s and at most 120 s (cumulative).

| group | markets |
|---|---|
| points | points |
| rebounds | rebounds |
| assists | assists |
| threes | threes |
| combos | points + rebounds, points + assists, rebounds + assists, points + rebounds + assists |
| other | steals, blocks, double-double, triple-double |

A test **PASSES** when its cell has at least 30 graded games AND the upper bound of its family-wise interval
(Bonferroni over the twelve: two-sided 1 - 0.05/12 = 99.583%) is below 0. Fewer than 30 games is `insufficient`, which
is no decision. Anything else is `no_edge`.

- **No test passes:** the hypothesis holds. On this evidence the stat-progress expert does not beat fresh books on any
  NBA prop group. The 95% half-widths say how large an edge this sample could have missed.
- **A test passes:** the hypothesis is falsified for that group. Its smallest passing ceiling is the candidate
  quote-age ceiling for the Decision Engine's M2 / M3. That is a candidate, not a switch: pricing or betting on it is
  the user's decision.

**Hypothesis (the lane's, written before this):** as on college halves, against prop quotes 120 s old or younger the
expert's Brier is not better than the books' in any market group, and its apparent advantage grows with quote age
(`#780`'s stale-quote pattern).

**Read beside it, never a decision:** d by disjoint quote-age bucket (0-30, 30-120, 120-300, 300-900 s); every group
pooled; d by clock bucket at 120 s or younger; and on rows where the engine and books differ by 5 pp or more, the
claimed edge against the realised one, betting the engine's side at the books' fair, at 120 s or younger and at all
ages.

**A known handicap, stated before the data:** the re-sim publishes P(over) from 100 draws a tick (every opined row at
registration). Its number carries Monte Carlo noise of about p(1 - p)/100, about 0.0025 Brier at p = 0.5, that the
books' number does not. It counts against the engine in d, as it would in any use of that number. Each primary cell
reports its estimate (`mc_noise_brier`) beside d, never subtracted from it.

## When it runs

ONCE, `--grade`, on the fleet, read-only, at nice 19, with refresh-worker's environment, on or after 11-17, once
`player_logs.csv` lists games dated 2026-11-16. The grader's blob is checked against the one pinned below first. A run
that fails before printing any `PRIMARY` line may be repeated; once one is printed, that run is the grade.

## Found while counting (no outcome read)

- **Memory.** The expert's batch function returns every opinion of a night with its inputs: 957 MB peak on three
  nights. The grader streams the expert one prop at a time instead (542 MB), and a test pins that the stream opines
  exactly what `stat_progress_opinions` opines, refusals and skips included.
- **Neighbouring shards matter.** The 11-11 props file took 37,733 of its games' quote rows from the 11-10 / 11-12
  shards (a game's rows can carry two kickoff stamps, `kickoff_shard_date`). 11-12 and 11-13 took none.

## Pinned

- Grader: `scripts/nba_live_prop_grade.py`, blob `9a73f03f1fa0adc38126bcea12e709f79e08b73d`, commit `f3d30ac4d` (worktree branch; it goes to main on
  the user's yes). 18 grader tests pass, including a planted-edge positive control (all twelve PASS), two nulls (none
  PASS) and an end-to-end collector test through the real expert. Eight mutations are each caught: the over / under
  flipped, the pass rule's bound, the neighbour shards dropped, a raw name key, the doubles threshold, the banked-over
  drop removed, skips kept in the stream, and a count-only run that reads stat values.
- Experts module: `syndicate/features/shared/engine_experts.py`, blob `8119d924d5a9a9a4ea00ed530cd413d05ed8c403`, the same on main at registration.

## Counts at registration (`--count-only`, fleet, no stat value read)

Three of the six nights are logged so far (11-11 / 11-12 / 11-13: 10 / 4 / 9 games). 210,363 opined rows on 23
games; every game and every player found in the box score (0 not in the box, 0 duplicates, 0 without a team side,
0 without a quote age).

| group | <= 30 s rows (games) | <= 120 s rows (games) | all ages rows (games) |
|---|---|---|---|
| points | 868 (23) | 8,265 (23) | 41,244 (23) |
| rebounds | 575 (22) | 5,417 (23) | 21,254 (23) |
| assists | 402 (22) | 3,841 (23) | 14,665 (23) |
| threes | 461 (22) | 4,145 (23) | 12,948 (23) |
| combos | 1,629 (21) | 19,575 (23) | 115,492 (23) |
| other | 39 (11) | 980 (23) | 4,760 (23) |

- 42,223 of the 210,363 rows (20%) sit at a quote 120 s old or younger, against 16% on college halves.
- Not opined (no prior): 193,004 `prior_stale` (every book older than 900 s), 77,095 `no_quote_before_instant`,
  7,064 `prior_implausible_hold`, 2,445 one-sided, 610 unpaired, 12 no consensus. Not priced by the producer:
  320,538 `quote_pulled`, 57,171 `certainty_refused`. Not a line: 294,207 at a line no book quoted that day,
  19,907 for a player + market no book quoted that day.
- Expected by the grade: 23 + 5 games on 11-14 (book_quotes shard) + the 11-15 and 11-16 slates (not yet quoted),
  about 40-45 games. The `other` group at 30 s or younger (11 of 23 games now) is likely to stay `insufficient`.

## Result `[2026-11-17 15:39Z (9:39 AM CST)]` -- the hypothesis HOLDS: no primary test passes; the engine is WORSE than fresh books on every prop group

Run once on the fleet, read-only, at nice 19, with refresh-worker's environment, from the kit `C:\tmp\nlpg_grade_1117\` (an export of `f3d30ac4d`), the registered grader (blob `9a73f03f1fa0`) and experts module (blob `8119d924d5a9`) both checked against the pins first. Readiness READY at 15:31Z (9:31 AM CST) (all 45 logged games in `player_logs.csv`); the run took 333 s at 594 MB peak, rc 0. 45 games graded (box score 45, 0 duplicates) and 365,924 rows, every opined row: 0 pushes dropped (no final landed on its line), and every other ROWS count is 0 (no player missing from the box, no row outside the window, none decided at its tick, none without a quote age or team side). 1,438 rows seen in two props files were counted once. Every opinion is a 100-draw re-sim (`sims` 100 on all 365,924).

### The twelve registered tests

d = engine Brier minus books Brier; negative means the engine was better.

| group | quote age | games | rows | engine | books | d | 95% interval | family-wise interval | MC noise | status |
|---|---|---|---|---|---|---|---|---|---|---|
| points | <= 30 s | 45 | 1,688 | 0.2967 | 0.2490 | +0.0477 | +0.0330..+0.0628 | +0.0264..+0.0698 | 0.0021 | no_edge |
| points | <= 120 s | 45 | 14,952 | 0.2854 | 0.2483 | +0.0371 | +0.0276..+0.0466 | +0.0233..+0.0508 | 0.0021 | no_edge |
| rebounds | <= 30 s | 43 | 1,197 | 0.2705 | 0.2486 | +0.0219 | +0.0050..+0.0397 | -0.0018..+0.0483 | 0.0021 | no_edge |
| rebounds | <= 120 s | 45 | 9,713 | 0.2637 | 0.2454 | +0.0183 | +0.0068..+0.0301 | +0.0017..+0.0357 | 0.0021 | no_edge |
| assists | <= 30 s | 43 | 827 | 0.2821 | 0.2512 | +0.0309 | +0.0124..+0.0491 | +0.0042..+0.0573 | 0.0021 | no_edge |
| assists | <= 120 s | 45 | 6,865 | 0.2663 | 0.2419 | +0.0244 | +0.0122..+0.0367 | +0.0063..+0.0422 | 0.0021 | no_edge |
| threes | <= 30 s | 44 | 945 | 0.2600 | 0.2342 | +0.0258 | +0.0135..+0.0384 | +0.0088..+0.0439 | 0.0022 | no_edge |
| threes | <= 120 s | 45 | 7,492 | 0.2504 | 0.2310 | +0.0194 | +0.0104..+0.0282 | +0.0064..+0.0322 | 0.0022 | no_edge |
| combos | <= 30 s | 41 | 3,155 | 0.2971 | 0.2492 | +0.0479 | +0.0336..+0.0614 | +0.0263..+0.0676 | 0.0021 | no_edge |
| combos | <= 120 s | 45 | 34,623 | 0.2880 | 0.2488 | +0.0393 | +0.0295..+0.0488 | +0.0249..+0.0528 | 0.0021 | no_edge |
| other | <= 30 s | 22 | 81 | 0.1940 | 0.1558 | +0.0381 | +0.0075..+0.0714 | -0.0061..+0.0897 | 0.0014 | insufficient |
| other | <= 120 s | 45 | 1,621 | 0.1814 | 0.1514 | +0.0299 | +0.0119..+0.0490 | +0.0043..+0.0588 | 0.0014 | no_edge |

Nothing passes. Eleven tests are `no_edge` and one, other at <= 30 s (22 games), is `insufficient`. The engine is not merely level with the books: d is positive in all twelve cells (+0.018 to +0.039 at <= 120 s), and all twelve 95% intervals lie wholly above 0. Against quotes two minutes old or younger, the books' de-vigged median is the better forecast of every prop group.

### Beside it (not decisions)

**By disjoint quote age**, d with its 95% interval (bold where the interval is clear of 0, either side):

| group | 0-30 s | 30-120 s | 120-300 s | 300-900 s |
|---|---|---|---|---|
| points | **+0.0471 (+0.033..+0.062)** | **+0.0359 (+0.026..+0.045)** | **+0.0285 (+0.019..+0.038)** | +0.0078 (-0.002..+0.017) |
| rebounds | **+0.0226 (+0.006..+0.041)** | **+0.0176 (+0.007..+0.029)** | **+0.0123 (+0.003..+0.021)** | -0.0055 (-0.015..+0.004) |
| assists | **+0.0312 (+0.013..+0.049)** | **+0.0236 (+0.011..+0.036)** | **+0.0150 (+0.004..+0.026)** | -0.0071 (-0.019..+0.005) |
| threes | **+0.0258 (+0.013..+0.039)** | **+0.0185 (+0.010..+0.027)** | **+0.0124 (+0.005..+0.020)** | -0.0019 (-0.009..+0.005) |
| combos | **+0.0474 (+0.033..+0.061)** | **+0.0386 (+0.029..+0.048)** | **+0.0317 (+0.022..+0.042)** | **+0.0141 (+0.004..+0.024)** |
| other | **+0.0381 (+0.007..+0.071)** | **+0.0287 (+0.010..+0.048)** | **+0.0171 (+0.001..+0.033)** | **+0.0111 (+0.000..+0.022)** |

**Every group pooled:** <= 30 s: 45 games, 7,893 rows, d +0.0394 (+0.0296..+0.0489); <= 120 s: 45 games, 75,266 rows, d +0.0326 (+0.0254..+0.0394).

**By clock bucket** (percent of regulation elapsed), at <= 120 s, all groups:

| clock | games | rows | d | 95% interval |
|---|---|---|---|---|
| 0-25 | 45 | 19,742 | +0.0444 | +0.0345..+0.0544 |
| 25-50 | 45 | 25,710 | +0.0372 | +0.0275..+0.0467 |
| 50-75 | 45 | 22,541 | +0.0216 | +0.0144..+0.0288 |
| 75-95 | 44 | 6,920 | +0.0187 | +0.0081..+0.0296 |
| 95-100 | 20 | 268 | +0.0163 | -0.0571..+0.0957 |
| ot | 3 | 85 | +0.0167 | -0.0106..+0.0498 |

**Claimed vs realised edge** where the engine and books differ by 5 pp or more, betting the engine's side at the books' fair (realised with its 95% interval):

| group | <= 120 s: rows, claimed, realised | all ages: rows, claimed, realised |
|---|---|---|
| points | 11,961, 18.7 pp, +0.6 pp (-2.1..+3.3) | 60,435, 20.3 pp, +5.7 pp (+3.3..+8.0) |
| rebounds | 7,867, 18.1 pp, +4.0 pp (+0.8..+7.2) | 30,733, 19.6 pp, +7.5 pp (+5.1..+9.8) |
| assists | 5,281, 16.6 pp, +0.6 pp (-3.2..+4.4) | 20,166, 18.0 pp, +5.5 pp (+2.4..+8.6) |
| threes | 5,315, 13.8 pp, -0.8 pp (-4.2..+2.7) | 16,389, 14.4 pp, +1.9 pp (-1.0..+4.8) |
| combos | 28,349, 19.9 pp, +1.3 pp (-1.2..+3.9) | 167,268, 21.4 pp, +5.6 pp (+3.4..+7.8) |
| other | 1,134, 16.7 pp, -0.1 pp (-5.1..+4.9) | 5,262, 16.2 pp, +3.0 pp (-1.1..+7.0) |

### What it says

1. **No edge against fresh books; the registered verdict.** No test passes, so the hypothesis holds and no quote-age ceiling is supported for the Decision Engine's M2 / M3: the stat-progress expert does not beat the books on any NBA prop group at 30 s or at 120 s. It is worse, by 0.018-0.039 Brier at <= 120 s, with 95% half-widths of 0.009-0.019.
2. **This sample shows no stale-quote edge, so the instrument's power is not shown here.** Unlike college halves, no quote-age bucket finds the engine better: at 300-900 s d is points +0.008, rebounds -0.005, assists -0.007, threes -0.002, combos +0.014, other +0.011; none of those intervals is clear of 0 below, and combos and other are still clear of 0 ABOVE. The grader's planted-edge positive control (all twelve PASS) is the evidence it can see an edge; this data contains none to see. The verdict does not rest on that: the cells are not near 0 but well above it.
3. **The gap shrinks with quote age, as hypothesised, but never turns.** In every group d falls monotonically from 0-30 s to 300-900 s, so the books' advantage decays as their quote ages, the same direction as `#780`; on props it only reaches parity.
4. **The engine's gaps are over-confidence.** Where it differs from the books by 5 pp or more it claims 13.8-19.9 pp and realises -0.8 to +4.0 pp at <= 120 s (only rebounds' interval is clear of 0). Even at all ages it realises only 13-38% of the claim. The d by clock is worst early in the game (+0.044 at 0-25%) and smallest late, where little is left to forecast.
5. **Monte Carlo noise explains little of it.** The 100-draw re-sim adds 0.0014-0.0022 Brier in every cell, about 4-12% of d. A noiseless re-sim would still be worse than the books in every cell.

**Limits:** six nights (2026-11-11..16), 45 games, NBA only, a 100-draw re-sim; the secondary readings above are many, at nominal 95%, and are not evidence. The registered population is the expert as registered, whose quote index matched players by the board's identity fold: lane `prop-expert-name-key` later measured that this skipped seven players the books spell differently (e.g. Herb / Herbert Jones), so those players' lines are outside this grade.
