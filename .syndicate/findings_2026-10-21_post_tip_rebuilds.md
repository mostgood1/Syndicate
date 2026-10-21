# Basketball SmartSims rebuilt after tip: measured, and frozen at tip (lane `freeze-nba-pregame-sims`, todo `#720`)

Session d07b749c, 2026-10-21. Started from session 51e096f1 on a lead from lane `nba-current-rosters` (session
8e69dd3f). That lane saw all three 10-20 sims rewritten at 6:56-6:57 PM CT, after BOS@DET and PHI@NYK had tipped.

## Substrate

The production data root on the fleet (`/home/amyn/syndicate-prod/data`), read-only:
- the props refresh logs `<league>_source/logs/syndicate_refresh_oddsapi_props_<D>.log`, NBA 10-02..10-23 and WNBA
  09-30..10-23;
- `predictions_<D>.csv`, `game_odds_<D>.csv`, `schedule_*.csv`;
- the surviving sim JSONs and `engine_inputs/` mtimes.

Script: `scripts/basketball_posttip_rebuilds.py` (main). Every log timestamp is UTC. A build is bounded by the last
timestamp before its `before_simulation` line and the first timestamp after it. **Counts rest on the logs as they
are now. A log only exists for a date that ran.**

## 1. The count

| league | builds | games built | builds after tip | games with one |
|---|---|---|---|---|
| NBA | 145 | 74 | **10** | **7** |
| WNBA | 60 | 14 | 1 | 1 |

- **Since engine-input persistence began (10-10), NBA had 6 post-tip builds on 4 games:**
  - 10-15 NYK_TOR at tip +2.5 min;
  - 10-20 DET_BOS at +295 and +548 min;
  - 10-20 NYK_PHI at +55 and +308 min;
  - 10-20 SAS_OKC at +158 min.
- Each rewrote `engine_inputs/<D>/<H>_<A>.pkl`. `live_resim.load_engine_inputs` reads that file again on every tick
  (`syndicate/features/nba/live_resim.py:901`), so the live re-sim's inputs changed mid-game.
- The surviving 10-20 files are the 11:07-11:09 PM CT rebuilds, made after all three games had ended. The "pregame"
  sim that grading reads for 10-20 was therefore built post-game.
- WNBA 10-04 ATL_NYL, +142 min: no reuse line was logged. It was a missing or player-less file, or the live-odds-worker
  targeted trigger; which one is not recorded.

## 2. Which inputs differed

- **Exclusions: 8 of 10** (`SMART_SIM_REUSE_STALE_EXCLUSIONS`).
- **Calibration stamp: 2 of 10.** Both were 10-04, the day the NBA prop calibration was enabled (`NBA_SIM_STALE
  have=None`).
- **Odds anchor: 0.** The reuse checks never compare odds. Every rebuild of a date also read the same anchor:
  `game_odds_2026-10-20.csv` and `predictions_2026-10-20.csv` were written 10-19 1:01 AM CT and never again, and the
  10-21 files were written 10-19 3:04 AM CT. (See §5: the anchor is a ~D-1 line.)
- **Roster pool: 0.** The pool check went live 10-21 7:43 AM CT and no game has tipped since. It can now trigger
  rebuilds as well: at 11:19 AM CT today the full refresh rebuilt 11 of 11 sims for a missing pool stamp, then 8 of 11
  again on exclusion drift.

**The post-tip exclusion changes are churn, not news.**
- 10-20: the 11:07 PM CT rebuild reversed every player change that the 6:54 PM CT rebuild had made on DET_BOS and
  NYK_PHI: BOS Bilodeau `-` then `+`, DET's three two-way players `+` then `-`, NYK Hukporti `-` then `+`, PHI Bona `+`
  then `-`.
- 10-08: BOS Sam Hauser was excluded at +21 min and re-admitted at +175 min.
- Box-score minutes for these players were NOT checked: `boxscores_history.csv` has no rows for these game ids.

## 3. Decision (user, AskUserQuestion, 2026-10-21 ~11:40 AM CT)

- **Policy: "Freeze at tip (Recommended)".** The alternatives offered were "rebuild live inputs only" and "keep
  current behaviour".
- **Switch: "On by default, kill switch".** The alternatives offered were "shadow first" and "off by default".

## 4. The change (aaa988a8)

`syndicate/features/shared/smart_sim_tip_freeze.py` and one block in `_smart_sim_run_date_local`'s per-game loop.
The block sits after `force_this_game` and before the force-unlink and the reuse checks.

- **The rule.** An existing sim with players is kept when its rebuild would finish at or after tip, projected as
  `now + (queued jobs + 1) x 90 s`. 90 s sits above the measured per-job p90 of 70 s (NBA, n_sims=100; median 47 s).
- **Why the queue counts.** Jobs run in home-team alphabetical order, not in tip order. On 10-21 the earliest tip
  (WAS_MIL, 6:00 PM CT) is the last of 11 in the queue.
- **Tip sources, first hit wins:**
  1. The predictions row. Its `commence_time` is empty for games whose UTC date is the next day: 6 of 11 on 10-21.
  2. `game_odds_<D>.csv` for the same teams.
  3. `schedule_*.csv` (`date_est`, tricodes, `datetime_utc`).
- **Not frozen:**
  - `overwrite=True` (every research or backfill caller passes it, and it deletes the date before the loop);
  - a missing or player-less sim (built, logged `built_after_tip=1`);
  - an unknown tip (rebuilt, logged `tip=unknown`).
- **Switch `SYNDICATE_SMART_SIM_TIP_FREEZE`:** absent or `on` = freeze; `shadow` = log only; `off`/`0`/`false`/`no` =
  disabled.
- **Tests.** `tests/test_smart_sim_tip_freeze.py`, 12 tests. Reachability first: off != on on the real loop for WNBA,
  for NBA (the 10-20 shape) and for the targeted trigger. The neighbouring reuse, roster, predictions, anchor,
  stand-in and WNBA reuse suites (136 tests) pass.
- **Replay on production.** The decision was run at each logged batch's decision time and queue position, over every
  build in the logs. It keeps **10/10** NBA and **1/1** WNBA post-tip builds and freezes **0 of 193** pre-tip builds.

## 5. Found on the way, not acted on

1. **The NBA SmartSim's market anchor is a ~D-1 line.** `game_odds_<D>.csv` and `predictions_<D>.csv` are written once,
   in the D-1 early-morning run, and never again. 10-21's sims, including today's 11:19 AM CT rebuilds, anchor to the
   10-19 3:04 AM CT line (`market_anchor.total_w` 0.7, `margin_w` 0.95), and 10-20's sims to the 10-19 1:01 AM CT line
   (DET_BOS -1.5 / 222.5, ~37 h before tip). Whether the closing line would sharpen the sim is unmeasured. That is an
   engine-input question for its own lane.
2. **Jobs queue in alphabetical order, not tip order.** Ordering them by tip would let the earliest games take a late
   scratch closer to tip under the freeze. Job seeds were not checked for order dependence.
3. **Exclusion churn pregame.** Today the full refresh at 11:19 AM CT rebuilt 8 of 11 sims on exclusion drift alone.
   Several drift entries look like name-keying noise (`NIC CLAXTON` and `NICOLAS CLAXTON` both present;
   `JOHNNY WAY FURPHY` vs `JOHNNY FURPHY`). Under the freeze this costs compute only, never a mid-game rewrite.

## 6. Owed

- Fleet ff past aaa988a8: a user decision. The props refresh is a per-run subprocess, so no restart is needed.
- Verification on the first NBA slate after the ff:
  - the props log shows `SMART_SIM_TIP_FREEZE ... frozen=1` for tipped games;
  - `python scripts/basketball_posttip_rebuilds.py --data-root /home/amyn/syndicate-prod/data --since <D>` counts 0
    `after_tip` builds for the slate;
  - each tipped game's `engine_inputs/<D>/*.pkl` mtime stays at or before its tip.
