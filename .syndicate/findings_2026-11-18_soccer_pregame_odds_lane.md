# Soccer's long PREGAME holds: whose lane, why, and the per-sport bound `[2026-11-18, lane soccer-pregame-odds-lane, session 9383ef18]`

**Question (from the starting session's brief, after the user's "start the soccer pregame odds lane session too"):** why does
soccer hold the live-odds-worker's live odds lane for up to ~46 min in PREGAME sweeps, and fix it per sport behind a switch.

**Answer: the premise is false.** Soccer does not hold the live odds lane. The ~46-min soccer holds are on
**refresh-worker's own lane**: its hourly look-ahead (`warm_next_day_slate`) re-simulates every soccer fixture in the
next 7 days, because it inherits refresh-worker's `SYNDICATE_SOCCER_SIM_HORIZON_DAYS=7`, a value set for the weekly
autorun's unit list. Fixed per sport behind `SYNDICATE_SOCCER_LOOKAHEAD_DATE_ANCHOR`: a future-dated pregame run simulates
only its own date. The live lane's pregame holds are NHL's, and the fix for those (`cdab875d5`, lane
`odds-lane-sport-deadline`) was loaded at 9:56 AM CST 11-18 (a fleet ff, while this lane was measuring). Every refusal
counted below predates it.

All readings are read-only, from the fleet at `nice 19`. The window is runs launched 11-13..11-18 (UTC stamp) from
`~/syndicate-prod/data/reports/migration_runs/*/odds_refresh_*/` and `~/syndicate-prod/logs/{live-odds-worker,refresh-worker}.log*`.
Times are Central (CST = UTC-6). The scripts are in `C:\tmp\soccerlane\` (census.py, refusals.py, h1.py, h2.py, h3.py,
weekly.py, weekly2.py, predict.py).

## 1. Whose lane: the premise, tested

- **Lane attribution.** Each run's lane comes from `refresh_job_status.json` `latestPath`
  (`refresh_status_latest__<lane>.json`). The lane keys are per role: `SYNDICATE_REFRESH_LANE`
  (`scripts/fleet_role_spec.json`) is `live-odds-worker` / `refresh-worker` / `web`, with
  `SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES=true`. Two roles never share a mutex.
- **The 184-run sample mixed two lanes.** Reproduced as wrapper-shape pregame runs including NHL: **172**, of which
  **88 are refresh-worker and 84 are live-odds-worker.** The difference from 184 is the window boundary: launch stamp
  here, directory date there.
  - The 66 runs over 900 s are **all refresh-worker**.
  - The live-odds-worker runs: **0 over 900 s**, max 711 s.
- **Pregame runs that include soccer, by lane:**

  | lane | runs | run hold p50 / p90 / max (s) | soccer p50 / max (s) | soccer artifacts scope |
  |---|---|---|---|---|
  | live-odds-worker | 5 | 393 / 711 / 711 | 155 / 191 | week, horizon 1 |
  | live-odds-worker-soccer-pregame | 164 | 176 / 294 / 528 | 163 / 467 | week, horizon 1 |
  | refresh-worker | 89 | 1,206 / 1,828 / 3,035 | 928 / 2,766 | **week, horizon 7** (860 of 861 steps) |

- **Who held the live odds lane when a sweep was refused.**
  - live-odds-worker printed **430** `REFRESH_LAUNCH_REFUSED reason=lane_busy` from 11-14 10:35 AM to 11-18 9:22 AM CST
    (`[ops_refresh]` lines; the holder's `run_stamp` was joined to the census).
  - The holders: **169 NHL-led pregame runs, 256 non-pregame runs** (live sweeps refused by live sweeps, which is the
    mutex working), 5 others, and **0 soccer-led runs.**
- **The worst run** (`odds_refresh_20261117_182727`, 12:27 PM CST 11-17, 3,035 s with 2,766 s of it soccer) is a
  refresh-worker run:
  - `MLB_SIM_TICK {"lookAhead": {"date": "2026-11-18", "launched": true, "reason": "warm_next_day_slate", ...}}`;
  - its status file is `refresh_status_latest__refresh-worker.json`.

## 2. Why it is long: one date's work times seven

- **The launcher** is `live_refresh_loop._launch_look_ahead_refresh`, on refresh-worker.
  - It launches `phase=pregame` for `selected_date + 1`, with every sport, hourly
    (`SYNDICATE_LOOK_AHEAD_INTERVAL_SECONDS`, default 3,600 s), whenever the loop sees nothing live.
  - Soccer is last in the sport order, so the other sports' look-ahead is not delayed by it.
- **The scope.**
  - `_soccer_artifact_scope_args` week-scopes from TODAY: `--week W --season S --horizon-days $SYNDICATE_SOCCER_SIM_HORIZON_DAYS`.
    `--date` is not passed, so `build_soccer_artifacts.py` takes its horizon from the child's own today.
  - refresh-worker's env has `=7`, while live-odds-worker's has the code default of 1.
  - The 7 exists for the weekly autorun: `run_refresh_worker.py:598` enumerates its league-date units over 7 days.
  - **The look-ahead inherits it by accident.**
- **H1: CONFIRMED.**
  - **Cost per match:** over 391 league steps from runs launched 12:00-7:59 AM CST (uncontended), seconds =
    **1.6 + 16.04 × matches simulated**. Across all 87 runs, seconds per match is p10 15.8, p50 17.1, p90 33.3.
  - **Matches in the 7-day window** (from the `SOCCER_CONFIRMED_LINEUPS` markers): 6 (11-13) → 36 → 48 → 50 → 58 → 62
    (11-18), as the first weekend after the international break entered the window.
  - **Daytime, not evenings.** The slow runs (25-45 s per match) were all launched 8 AM-6 PM CST, which points to
    host contention: the fleet shares the machine with the daytime work. Night runs sit at 15-17 s per match.
  - **A normal week can be worse than this one (expected, not measured).** An 8-date window can hold two Saturdays
    plus a midweek round, so it can hold more matches than the 62 seen here.

## 3. What it costs, and what it does not

- **The live odds lane: nothing** (section 1).
- **H2 (day-2 look-ahead starved by soccer): FALSIFIED as a soccer cost.**
  - Day-2 look-ahead outcomes 11-13..11-18: **84 of 89 attempts refused `lane_busy`**, 5 launched.
  - The refusals land **p50 165 s, p90 245 s after the day-1 launch** (74 of 84 within 4 min). That is before
    soccer, which starts after about 200 s of other sports.
  - `_look_ahead_decision_day2` stamps its marker BEFORE launching, so a refused day-2 waits a full 3,600 s, and
    lands one tick after the next day-1 launch again. **A phase lock that a 0-s soccer would not fix.** Lead below.
- **H3 (redundant work): CONFIRMED.**
  - **The look-ahead's soccer sims:** 0.85 / 1.85 / 2.85 / **4.65 / 5.59** / 2.97 sim-hours per CST day,
    11-13..11-18 (11-18 is a part day). That is **61%** of refresh-worker's soccer sim time.
  - **The owner of days 2-7, the weekly autorun:**
    - one league-date unit per launch, every 14,400 s;
    - 610 runs, 11.72 sim-hours in the same window;
    - at launch, a unit's `last_success_age_s` is p50 14,862 s and p90 17,146 s, max 23,982 s, with 0 of 587 over
      twice the interval. **Healthy, and barely delayed** by the look-ahead's holds.
  - **Today and tomorrow** are covered by the live-odds-worker soccer-pregame lane every 2,700 s (horizon 1).
  - **So the look-ahead re-simulates, hourly, the files two dedicated producers already own.** Fixtures 2-7 days out
    do not move hour to hour: market anchoring is off by decision, and confirmed XIs arrive in the last minutes.
- **OddsAPI: not measured.** The look-ahead's soccer odds and props steps also re-fetch what the soccer-pregame lane
  fetches, but the quota ledger has no per-role attribution. The fix adds and removes no step, so its OddsAPI calls
  are unchanged: **0 added**.

## 4. The fix (on main, behind a switch, NOT loaded)

`scripts/refresh_odds_sources.py`. This lane BORROWS the soccer functions from lane `odds-lane-sport-deadline` (a LOAN
recorded in its `Files:` line); none of that lane's NHL, deadline or run-loop code is touched.

- **The switch:** `SYNDICATE_SOCCER_LOOKAHEAD_DATE_ANCHOR`. Absent = ON; `off`/`0`/`false`/`no` = today's command,
  byte for byte.
- **The predicate:** `_soccer_lookahead_anchor_date(args)`. It returns the run's date when the run is PREGAME, its
  `--date` is after Central today, and it has no `--soccer-date`.
  - On the fleet that is exactly the look-ahead: 86 of 86 future-dated soccer pregame runs, and 0 of 170 runs on any
    other lane, which all launch for today.
  - The weekly autorun pins `--soccer-date`, and a pin always wins.
- **The scope:** `_soccer_artifact_scope_args(..., anchor_date=D)` returns
  `--week <week of D> --season S --horizon-days 0 --date D`.
  - `default_week(reference_date=D)` resolves D's own matchweek, which the unanchored scope cannot reach.
  - `week_dates_within_horizon` then returns `[D]` or `[]`. For `[]` the build exits 0 ("nothing to simulate") and
    writes nothing: **no empty artifact and no new date-index entry.**
  - An unresolvable week falls back to `--date <run date>`, the same fallback the unanchored scope takes.
- **The marker:** `SOCCER_LOOKAHEAD_DATE_ANCHOR date=<D> ...` on the child's stderr.
- **Loading:** `refresh_odds_sources.py` is run as a fresh child per sweep, so a fleet fast-forward loads it. **No role
  restart.**
- **Tests:** `tests/test_soccer_pregame_odds_lane.py`, 26 cases. **23 fail on main's previous code**; the 3 that pass
  either way are the no-harm checks (today-dated runs unchanged, pinned units unchanged, step list and order unchanged).
  - **The reachability test drives the real `_build_summary` over the real soccer registry entry in dry-run.** ON gives
    `--week 15 --horizon-days 0 --date 2026-11-19`; OFF gives `--week 14 --horizon-days 7`. `off != on`.

## 5. Prediction (pre-registered in the lane block before the build, `af0d41f05`)

**Backtest of the change over the 86 baseline look-ahead runs** (same runs, the anchored per-league cost from the
fitted model):

| | p50 | p90 | max | over 1,800 s |
|---|---|---|---|---|
| soccer seconds, actual | 933 | 1,465 | 2,766 | 5 |
| soccer seconds, backtest | 167 | 227 | 471 | 0 |
| run hold, actual | 1,201 | 1,828 | 3,035 | 10 |
| run hold, backtest | 412 | 650 | 951 | 0 |

The backtest window is unusually light: most of its target dates fell in the international break, with 0 fixtures.

**Target dates ahead**, from the 11-18 9:06 AM CST run's markers (current-week view; D's own week may add more):

| target date | fixtures listed |
|---|---|
| 11-19 | 2 |
| 11-20 | 4 |
| 11-21 | ≥ 27 |
| 11-22 | ≥ 12 |

**The pre-registered predictions** (verbatim in the lane block):

- **P1 (reachability):** every refresh-worker look-ahead run carries `--horizon-days 0 --date <run date>`; no other
  lane's soccer command changes.
- **P2 (per run):** soccer artifact seconds ≤ 16 × fixtures(D) + 30 (night launches), ≤ 2.5× that by day.
  - Targets 11-19 / 11-20: ≤ 130 s, and run hold ≤ 600 s.
- **P3 (first 48 h):** look-ahead run hold p50 ≤ 600 s, and 0 runs over 1,800 s.
- **P4 (no coverage loss):** the weekly autorun's `last_success_age_s` p90 stays ≤ 18,900 s, and tomorrow's served
  soccer board rows do not fall.
- **P5 (CPU):** look-ahead soccer sim-hours ≤ 1.0 per CST day.
- **Not predicted:** any change in live-odds-worker `lane_busy`.

## 6. Leads (noticed, not followed)

- **Day-2 look-ahead phase lock.** Day 2 was refused 84 of 89 times. It stamps its marker before launching, and day 2
  tries 1-4 min after day 1 launches. A refused launch could leave the marker unstamped, as the loop's pregame markers
  do with `_rewind_pregame_sport_sweep_epochs`. Owner: whoever takes `live_refresh_loop`'s look-ahead.
- **Understat is failing.** Every recent look-ahead run fails `soccer_<big5>_history_current` and
  `soccer_<big5>_players` with rc 1 (45 of 45 failing-step records in the last 40 runs of 11-18). The errors are
  `ValueError: playersData not available for https://understat.com/league/EPL/2026` and a JSON decode error.
  - So the soccer sport result is `ok: False` on every look-ahead run. The 5 big leagues' current-season player and
    team history is not refreshing from this path.
- **A 1,800 s NBA/college pregame run on the live odds lane at about 12:01 AM CST:** `odds_refresh_20261114_060144`,
  `_20261115_060044` and `_20261118_060115` (`nba,ncaab,wncaab`). Each ran exactly 1,800 s, rc 1, with no step
  results. The step timeout escaped; all three predate the `2ae0c646a` load.
  - It holds the live lane 30 min at the hour a late NBA game is still live. For lane `odds-lane-sport-deadline`.

## 7. Load and first reading `[2026-11-18 12:15 PM CST]`

- **Loaded:** fleet ff `59fbefc71` -> `640c6d4fd` at 17:58:30Z (11:58 AM CST), no restart (deploys.md entry of that time).
  - refresh-worker's preflight held 26 times for its in-flight board build. The CLEAR came on live-odds-worker, as the 16:33Z ff did.
- **First look-ahead on the new code** (`odds_refresh_20261118_180720`, launched 12:07 PM CST, target 11-19):
  - **P1 MET:** every soccer sim/picks step carried `--week <its own week> --horizon-days 0 --date 2026-11-19`.
  - **P2 MET:** soccer sims took 45 s for the 2 matches on 11-19, against a bound of 62 s.
  - **Run hold:** 386 s, against 1,326-2,444 s for today's six earlier look-ahead runs.
- **Other soccer producers unchanged:** a weekly unit after the ff kept its pinned `--date 2026-11-22`.
- **The marker line is not readable:** `odds_refresh.stderr.txt` keeps only the first 32 KB plus a tail. Read the step
  commands instead.
- **Owed:** P3-P5 over 48 h. The first Saturday-target run (launched 11-20, target 11-21, at least 27 fixtures listed)
  is the real test of P2's bound.

## 8. 48-hour reading (P1-P5) `[2026-11-20 12:47 PM CST, scheduled task soccer-lookahead-anchor-reading-1120]`

Read-only, nice 19: `scripts/read_soccer_lookahead_anchor.py --out C:\tmp\soccerlane\p3p5_result.json`, window
11-18 17:58:30Z .. 11-20 17:58:30Z (11:58 AM CST 11-18 .. 11:58 AM CST 11-20). 35 refresh-worker look-ahead runs
(pregame, run date > CST launch day).

- **P1 NOT MET: 34 of 35 anchored.** The miss is `odds_refresh_20261120_055209`: launched 05:52:09Z (11:52 PM CST
  11-19) by `MLB_SIM_TICK lookAhead warm_next_day_slate`, run date 2026-11-20, every soccer step `--week N --season 2026
  --horizon-days 7` (the old scope). Its stderr has 0 `SOCCER_LOOKAHEAD_DATE_ANCHOR` lines. Its soccer `_artifacts` steps
  started 06:03:41Z..06:21:13Z, i.e. after CST midnight, when `central_today()` = the run's own date, so
  `_soccer_lookahead_anchor_date` would see "not future". That fits a midnight-crossing gap (the check is evaluated when
  the soccer steps are built, not at launch). NOT MEASURED: when the step list was actually built. Second clause: 623
  other soccer runs carried their own `--date` scopes (sample 11-19..11-27); the reader did not flag a change, but it did
  not diff them against pre-fix commands either.
- **P2: 30 of 35 within bound.** Misses:
  - `055209` (the unanchored run): 1,072 s for 4 matches, bound 235 s.
  - Saturday target (11-21, 49 matches, night bound 814 s): `080116` 871 s (+7%), `100149` 843 s (+4%), `110209` 815 s
    (+0.1%). The other five Saturday-target runs were within bound (753-1,000 s; two daytime, bound 2,035 s).
  - Sunday target (11-22, 28 matches): `120329` 520 s vs 478 s (+9%).
  - Read as: the 16 s/match + 30 s slope holds within 10% on the first heavy dates; the slope is slightly low at 49 matches.
- **P3: p50 MET, max NOT MET.** n=35, p50 385 s (bound 600; baseline 1,201), p90 1,264 s, max 1,853 s, 1 over 1,800 s
  (bound 0; baseline 10 of 86). The one is the unanchored `055209`. Anchored max 1,449 s (Saturday target, 49 matches).
  The miss is 3% over 1,800 s, inside the 25% falsification margin.
- **P4 MET:** weekly autorun `SOCCER_UNIT_LAUNCHED last_success_age_s` n=369, p50 14,589 s, p90 18,173 s (bound 18,900),
  max 25,703 s. Note: p90 is 1,027 s above the pre-fix 17,146 s baseline; within the bound, cause not investigated.
- **P5 MET on n=1 full day:** look-ahead soccer sim-hours 11-19 = 0.68 h (bound 1.0; baseline 4.65 / 5.59 h). Partial days:
  11-18 (from 11:58 AM) 0.13 h; **11-20 (to 11:58 AM) already 2.26 h** -- eight runs targeting the 49-match Saturday at
  ~750-1,000 s each. 11-20 will finish well over 1.0 h. The bound was set on a light-slate assumption; on a heavy-slate
  day an hourly date-anchored look-ahead still costs ~13-15 min of soccer per run.
- **Against the pre-registered falsification rule:** P1 failed (1 of 35), so the prediction set is FALSIFIED as written.
  The effect is still large: p50 run hold 1,201 -> 385 s, runs over 1,800 s 10 of 86 -> 1 of 35 (the unanchored one).
- **Leads (not followed, read-only run):** (a) evaluate the anchor at launch, or compare with the run's launch day, so a
  look-ahead launched before CST midnight stays anchored; (b) heavy-slate cost: hourly re-sims of the same 49-match date
  are 8+ runs x ~14 min; a per-date "already simulated this hour/odds unchanged" skip would bound P5 on weekends.
