# NBA games simmed after the day's sim index was written carry no pregame projection — findings `[2026-11-10, lane nba-sim-index-missing-games, session 2ba5509d, todo #778]`

**Status: fix on main, NOT LOADED.** The fleet runs `c468657e5`. Found while waiting for #775's served reading,
which this blocks.

## 1. Symptom (served, read-only, ~19:50Z 11-10)

Served `POST /api/intelligence/query`, `response.ranked_all`, NBA prop rows `[rows, sim_projection, model_edge_pct]`:

| game | served |
|---|---|
| BOS@PHI | 70, 64, 64 |
| LAC@PHX | 53, 0, 0 |
| MIA@UTA | 91, 0, 0 |
| MIL@NYK | 43, 0, 0 |
| OKC@POR | 75, 0, 0 |
| ORL@SAC | 81, 0, 0 |

So 343 of 413 served NBA prop rows carried no model projection or edge. `game_chip_intervals` read all 6 games
(`nba:pregame_sim=6`); only the prop join was short.

## 2. Cause (measured)

- `nba_projections.load_nba_prop_projections` reads ONLY `cards_sim_detail_<D>.json` (D-1..D+1).
- `cards_sim_detail_2026-11-10.json` was written **11-09 06:03Z** with **1 game (BOS@PHI)**.
- live-odds-worker's NBA props refresh (`data/nba_source/logs/syndicate_refresh_oddsapi_props_2026-11-10.log`) re-simmed
  the slate at 16:52, 17:26, 19:00 and 19:31Z. All 6 `smart_sim_2026-11-10_*.json` are newer than the index file.
- `_export_cards_sim_detail_snapshot` (`scripts/refresh_nba_oddsapi_props.py`) calls `_copy_existing_processed_artifact`
  first. At the caller (`_run_refresh_via_cli`), `processed_root = source_root/data/processed`, so source and
  destination are the same path, and it returns the existing file. `_build_cards_sim_detail_from_local_smart_sim`
  never runs again for a date that already has a file.
- **Falsification run** (copies of the fleet's 11-10 files, `C:/tmp/nbaname/replay_778.py export`):
  - fleet code: 1 -> 1 game;
  - fixed code: 1 -> 6 games, the existing BOS@PHI entry unchanged.

Earlier slates, read 11-10 (games simmed but absent from the file):

| slate | missing | file written |
|---|---|---|
| 10-30 | 8 of 10 | 10-29 15:16Z |
| 11-04 | 9 of 14 | 11-03 10:05Z |
| 11-06 | 5 of 9 | 11-05 22:06Z |
| 11-10 | 5 of 6 | 11-09 06:03Z |

Every complete slate checked (10-31, 11-01, 11-02, 11-05, 11-07, 11-08, 11-09) had its file written early the SAME day.

## 3. Fix

`_merge_missing_cards_sim_detail_games`, called from `_export_cards_sim_detail_snapshot` when a file already exists:
- adds every game that has a smart_sim file but no entry, built by the same `_build_cards_sim_detail_from_local_smart_sim`;
- leaves every existing entry exactly as it is, even when a newer sim exists for that game;
- does not rewrite a complete file, so its mtime is unchanged;
- treats a game as present in either home/away orientation;
- leaves an unreadable file alone;
- writes atomically (tmp + `os.replace`); a merge that raises leaves the pre-fix behaviour (logged `CARDS_SIM_DETAIL_MISSING_GAMES_FAILED`);
- prints `[refresh_nba_oddsapi_props] CARDS_SIM_DETAIL_MISSING_GAMES_ADDED date= games_before= added= games_after= added_games=`
  into the NBA refresh run log. **Corrected 2026-11-11:** the print reached no fleet log, because the script's stdout does not go to the run log; only `_append_log` lines do. `63e56dbb4` also writes it via `_append_log`. The adding branch itself ran on 11-11 at 06:03Z: 5 -> 10 games.

Tests: `tests/test_nba_cards_sim_detail_missing_games.py` (8), including an OFF arm (the pre-fix path leaves 1 game), a failed
merge falling back to the pre-fix behaviour, and reachability into `load_nba_prop_projections` (the added game's players absent OFF, present ON).

## 4. Replay (fleet data, fleet join code `c468657e5`, current file vs merged file)

Book grid for 11-10, NBA prop rows `[rows, projection, probability, edge]` (`replay_778.py price`):

| game | current file | merged file |
|---|---|---|
| BOS@PHI | 393, 372, 372, 371 | 393, 372, 372, 371 (unchanged) |
| LAC@PHX | 358, 0, 0, 0 | 358, 347, 347, 344 |
| MIA@UTA | 445, 0, 0, 0 | 445, 389, 389, 389 |
| MIL@NYK | 317, 0, 0, 0 | 317, 271, 271, 266 |
| OKC@POR | 430, 0, 0, 0 | 430, 410, 410, 410 |
| ORL@SAC | 364, 0, 0, 0 | 364, 347, 347, 347 |
| **total** | **2,307, 372, 372, 371** | **2,307, 2,136, 2,136, 2,127** |

"Derrick Jones" (#775): 19 rows, stamped 0 -> 19, edge 0 -> 16.

## 5. Expected change on the fleet, stated BEFORE any fleet change

- **Tonight, if the file is rebuilt** (a one-off run of the fixed export, or the first NBA refresh after the code
  loads):
  - the file goes from 1 game to 6;
  - book-grid NBA prop rows with a model edge go from ~371 to ~2,100 of ~2,300;
  - BOS@PHI's rows do not change.
- **Served Layer 2 board:** priced NBA prop rows on the 5 games go from 0 to the subset that ranks.
  - These rows can now rank on a model edge, be suggested, and reach the venue plan. That means **live money on 5
    more NBA games' props tonight.**
  - #775's split players on those games (Derrick Jones) gain their edge too.
- **Log:** the NBA refresh run log shows
  `CARDS_SIM_DETAIL_MISSING_GAMES_ADDED date=2026-11-10 games_before=1 added=5 games_after=6` once.
  - After that, the line is absent until a new game is simmed.
- **A complete slate:** nothing changes. The file is not rewritten.
- **Roles:** the export runs inside `scripts/refresh_nba_oddsapi_props.py`, a fresh subprocess per run
  (`refresh_odds_sources.py` -> `subprocess`).
  - A fleet ff loads it at the next NBA props refresh. No role restart is needed for this file.
  - The ff carries every unloaded commit on main between the fleet's SHA and this one, so the ride-along check
    decides whether a ff is possible.

## 6. Not done / not claimed

- **Games already in the file still do not follow later re-sims** (late scratches, new odds anchors). A file written
  early the same day keeps its morning sims all day while the props refresh re-sims every ~30 min. Following re-sims
  is a different change, with its own risk: the fleet also rewrites a started game's pregame sim mid-game, e.g.
  `smart_sim_2026-11-09_DAL_IND.json` at 11-10 01:04Z. Not done here.
- The WNBA twin (`refresh_wnba_oddsapi_props.py::_export_cards_sim_detail_snapshot`) has a different guard: it rebuilds
  unless the file has "quarter content". It is off-season, so nothing was measured and nothing was changed.
