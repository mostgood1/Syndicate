# MLB `prop_player_not_in_boxscore` is correct voiding — 2026-09-28

Lane `mlb-prop-grading-player-match`, session 249f998b. READ-ONLY against production; no code
changed, no deploy.

## Method

1. Pulled the MLB population parts the `model-scorecard` cron reads
   (`reports/intelligence/<POPULATION_SUBDIR>/<date>__mlb__partNNN.jsonl` via
   `/api/ops/artifacts/stream`, the cron's own `WebReader` + `fetch_board_date`) for board dates
   2026-09-14, 09-20, 09-25, 09-26.
2. Ran them through the cron's own `bucket_search.grade_population` with the real
   `MlbPropGrader.settle` wrapped to record every prop row's outcome. **The reproduction matches
   production exactly**: 09-25 `prop_player_not_in_boxscore` 1,099 and 09-26 827 locally, the
   same two numbers in production's `scorecard_state.json.gz` `ungraded` table.
3. For every `player_not_in_boxscore` row, re-found the game with the grader's own
   `_final_game`, then searched BOTH teams' `players` in the StatsAPI `/game/<pk>/boxscore` under a
   loose spelling (accents folded, punctuation dropped, `jr/sr/ii/iii/iv` dropped) and, failing
   that, surname + first initial.

## Result — the hypothesis ("mostly name misses") is FALSE

Sample: 200 rows, `random.seed(20260928)`, over the 4 dates: **193 true DNPs (96.5%)** —
186 on the box roster but did not bat, 6 did not pitch, 1 absent under any spelling.
Whole population of the 4 dates, 2,882 rows:

| class | rows | share |
|---|---:|---:|
| on the box roster, did not bat | 2,648 | 91.9% |
| on the box roster, did not pitch | 40 | 1.4% |
| absent under any spelling (not active that day) | 44 | 1.5% |
| **name miss** | **150** | **5.2%** |

"Did not bat" is a real DNP, not a reader gap: across the 55 box scores the 4 dates touched,
every non-pitcher with empty `stats.batting` has `gameStatus.isOnBench: True` and no
`battingOrder` (376 of 376), and every non-pitcher with a `battingOrder` has batting stats
(1,165 of 1,165). No third combination occurs. The 44 absent rows are 3
players (Bryce Eldridge SF 09-20, Blaze Alexander BAL 09-20, Andrew Vaughn MIL 09-26), each
missing from their own team's active list in that game's box score.

Why so many: books post props before lineups, and the recorder records every priced side, so
bench players' props land in the population. Books void them. So must the grader.

**The 5.2% of name misses is TWO players**, and nothing else:
- `leonardo bernal` (odds feed) vs `Leo Bernal` (StatsAPI) — 91 rows
- `rafael flores` (odds feed) vs `Rafael Flores Jr.` (StatsAPI) — 59 rows

`cards._normalize_live_name` already folds accents; it keeps punctuation and suffixes, and
`cards._market_name_variants` knows 5 first-name aliases (chris/jeff/matt/mike/nick).

## `prop_no_commence_time` — producer found, already fixed

Every one of these rows is a PROP record whose `ct` is None while other sightings of the SAME
event carry one (09-20: 175 of 175 rows, 5 events; 09-14: 442 of 442, 10 events). Producer:
undated Polymarket venue quotes blanked a prop row's `commence_time` in the book grid —
fixed in `0b5518ab`, verified live on refresh-worker `48376cc1` 2026-09-22 15:48:56Z (`69c210d0`).
Production's `ungraded` table agrees: the reason appears on 09-14..09-22 only and is **0 on
every date 09-23..09-27**. The 1,278 are history that leaves the 28d window by 2026-10-20.
Recovering them would mean lending `ct` across sightings in `grade_population` (the grader
already lends team names that way) — a CORE change that resets every sport's scorecard history
for a pile that no longer grows. Not done.

## A gap found on the way — the MLB grader signature does not cover the name match

`scripts/publish_model_scorecard.py` `grader_signature` hashes
`MlbPropGrader.settle` + `MlbPropGrader.final_score` only. `player_actual`, `_final_game`,
`match_game`, and the `cards` name helpers they call are NOT hashed, so a change to the name
match (the exact fix above) would NOT reset MLB history — it would silently pool two grader
versions, which `model_scorecard.py`'s "NO POOLING ACROSS GRADER VERSIONS" forbids. Any fix to
the two names must add those functions to the digest in the same change.
