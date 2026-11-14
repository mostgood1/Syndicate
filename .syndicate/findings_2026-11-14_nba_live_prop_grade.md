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
