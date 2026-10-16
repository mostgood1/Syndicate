# NHL lineups dress players the collector holds OUT — measured, then removed (lane `nhl-lineup-status`, 2026-10-16)

User 2026-10-16: "proceed with recommendations on 3" — removal only, measured first. Survey gap #1
(`findings_2026-10-16_absence_handling_survey.md`). Times US Central. **[measured]** = read on the fleet's production
disk (read-only, worktree code on PYTHONPATH); **[code]** = read in the repo; **[test]** = shown by a unit test.
Measured and implemented by a worker agent in its own worktree; reviewed, landed and tested on main by session
9e18a0e7 (106 passed, 1 skipped over the new test file and the four existing files that import collect.py).

## 1. Measurement — `scripts/measure_nhl_lineup_status.py` (production's own state, matching and as-of code)

- **Dressed** = has a `line_slot`, or is the goalie named in `starting_goalies_<date>.csv`.
- **Build time** = min(lineups file mtime, the team's puck drop). The fleet rewrites today's file until ~11:40 PM, so
  for a finished date the file is post-game (its window inputs are unchanged; its book `must_dress` set and roster
  can change). The 10-16 pre-game file shows the same defect.
- **Status** = the collector state replayed BY ESPN ID, deduped by team + name; events are never read as news.
  Replay reproduces the state file exactly (133/133) [measured].
- **Scratches** = the latest gameinfo record at or before build time. **Played** = TOI > 0 in the cached api-web
  boxscore (all 118 games of 2026-27 cached; 0 fetched). **Matcher positive control: 1,084 of 1,084 found.**
- **Prop rows** = distinct book x market x line rows first seen before puck drop (a lower bound — the file is rewritten).

**Coverage:** 10-13..10-15 (29 games, 58 team-games, regular season, all final). 10-07..10-12 (37 games) precede the
collector's first capture (10-13 2:29 PM CT) and are reported `before_collection`, never as zero. 10-16 pending.

| date | games | ESPN Out/IR/Susp dressed | played | prop rows | scratch dressed | played | held OUT, team played | played | DTD held | played |
|---|---|---|---|---|---|---|---|---|---|---|
| 10-13 | 16 | 19 | 0 | 12 | 17 | 1 | 123 | 0 | 0 | 0 |
| 10-14 | 2 | 3 | 0 | 1 | 2 | 0 | 17 | 0 | 2 | 0 |
| 10-15 | 11 | 10 | 0 | 5 | 11 | 1 | 88 | 0 | 0 | 0 |
| **total** | 29 | **32** | **0** | 18 | 30 | 2 | **228** | **0** | 2 | 0 |

- **Reverse risk:** the collector's OUT was right in 228 of 228 player-games (203 of 203 three hours before puck drop).
- **Scratches:** 144 of 146 posted scratches sat out; both misses were list flips in the last 30 minutes
  (SJS 10-13 S. Dickinson listed 9:51 PM, replaced 10:11 PM; BUF 10-15 D. Gilbert listed 5:51 PM, reverted 6:11 PM).
- **Day-To-Day:** too small to confirm or refute (10 held DTD three hours out, 1 played; most turned Out by puck
  drop). DTD stays dressed, as specified.
- **Who:** 8 of the 32 were on IR (Gourde since 09-28, Demidov since 10-06), 1 suspended (Nazar); game-day Outs
  included Makar (4 prop rows), Dahlin (D1), Matheson (D1), Buchnevich (L1).
- **10-16 (pending):** Granlund (ANA, L1) and N. Roy (COL, L4) dressed while Out in the 2:44 PM file.

## 2. Decision

The falsification test did not fire (dressed-OUT players played 0 of 32; the collector's OUT right 228/228).
Removal implemented for ESPN Out / IR / LTIR / Suspension (`news_availability.availability_status`, the board
flag's own rule) and posted scratches (NHL id). DTD stays dressed. The only redistribution is the existing slot
re-sort. Switch `SYNDICATE_NHL_LINEUP_STATUS` (absent = ON; `off` disables, printed).

## 3. Pipeline trace

`run_refresh_worker.py` -> `run_refresh_odds_job.py:707` -> `refresh_odds_sources.py:1031-1041`
(`refresh_nhl_oddsapi.py --days-ahead 1`; live sweeps `--mode fast` unless generation is due, `:1045`, ~every 30 min)
-> `refresh_nhl_oddsapi.py:516` `_run_owned_generation` -> `:567` `collect_slate_inputs` -> `collect.py`
`SlateAvailability.load` (`lineup_availability.py` `load`; `news_root_for`: root.parent/news, then
`data_root()/news`; `slate_games` puck drops from the scoreboard) -> roster filter -> `availability.apply` (as of
min(now, puck drop); `injuries_at`: the state file, or the change log replayed; `dedupe_state`; `scratches_at`;
`match_records`; `match_scratches`; `removal_status`; prints `[nhl_lineup_status]`) -> `infer_lines` (a removed
player cannot be forced back by `_book_listed_ids`, which only returns ids still in `usage`) -> prints
`NHL_LINEUP_STATUS` -> writes `lineups`, `roster_snapshot`, `starting_goalies` and `lineup_exclusions_<date>.json`
-> `build_nhl_artifacts.py` reads lineups (`loaders.load_lineups`); `_match_lines_to_game` leaves a removed
player's lines unprojected. No reuse flag: every pregame sweep rebuilds the lineups.

## 4. Tests, dry run, verification

- `tests/test_nhl_lineup_status.py` (57 tests incl. the off-vs-on REACHABILITY test) [test].
- Dry run of the real collector over the fleet's 10-16 data (`write=False`, 22 free api-web calls): 7 players
  removed; ANA's slots re-sorted; COL left with 11 dressed forwards — the engine fills a short line from the forward
  pool (`engine.py:936-958`), which is the removal-only design.
- **Verify after the fleet ff:** (1) the log shows `NHL_LINEUP_STATUS date=<today> ... feeds={'state_file:ok': N}`
  — any `absent` / `stale` / `NOT APPLIED` is a failure; (2) `lineup_exclusions_<date>.json` next to
  `lineups_<date>.csv`; (3) `nice -n 19 python scripts/measure_nhl_lineup_status.py --data-root
  /home/amyn/syndicate-prod/data --dates <first post-ff date> --lead-minutes 0 --gate` exits 0 (on today's pre-fix
  files it returned FAIL with 7 rows); (4) re-run for 10-16 tomorrow to settle Granlund and Roy.

**UNVERIFIED / follow-ups outside this lane:** `news/**` and `lineup_exclusions_*.json` are in no artifact
allowlist; `nhl_sim_input_checklist.py` does not gate this feed; how often lineups rebuild in the last hour before
puck drop; interaction with NHL calibrations fitted on lineups that included these players; 3 dates only.
