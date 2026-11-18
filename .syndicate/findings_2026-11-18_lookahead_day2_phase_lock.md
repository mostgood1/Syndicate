# Findings 2026-11-18: refresh-worker's day-2 look-ahead is phase-locked out by its own day-1 run (todo #842)

Lane `lookahead-day2-phase-lock`, session f9057c3a. Lead from `#840` (lane `soccer-pregame-odds-lane`).
Substrate: **fleet**. The sources are the refresh-worker role logs (`~/syndicate-prod/logs/refresh-worker.log{,.1..5}`),
the run manifests (`~/syndicate-prod/data/reports/migration_runs/*/odds_refresh_<stamp>/`), file mtimes on
`~/syndicate-prod/data`, `/proc/<pid>/environ` of refresh-worker (pid 152916, commit `2ae0c646a`), and
`/api/ops/oddsapi/quota`. All reads were read-only, at `nice 19`, from 12:55 to 1:45 PM CST on 11-18. Scripts are in
`C:\tmp\la2_f905\` (`extract.py`, `analyze.py`, `outliers.py`, `runs.py`, `runs_an.py`, `d2files.py`,
`quota_sampler.py`).

## 1. What day 2 is

`live_refresh_loop._run_mlb_sim_tick` runs on refresh-worker on every main-loop tick (p50 gap 38.0 s, p90 87 s). It
makes two look-ahead decisions:

- **day 1** (`_look_ahead_decision`) targets today+1;
- **day 2** (`_look_ahead_decision_day2`) targets today+2.

Each one, while no tracked sport is live, launches a `phase=pregame` `refresh_odds_sources.py` run of every sport
(nba, nhl, nfl, ncaaf, ncaab, wncaab, soccer). It launches at most once per `SYNDICATE_LOOK_AHEAD_INTERVAL_SECONDS`
(3,600 s), on refresh-worker's own refresh lane (`SYNDICATE_REFRESH_LANE=refresh-worker`). That lane is a per-role
mutex: `ops_refresh._assert_no_active_refresh_run` raises `RefreshLaneBusy`.

The env of the process that runs it (pid 152916) has `SYNDICATE_LOOK_AHEAD_ENABLED=true`, `_48H_ENABLED` absent
(= on), `_INTERVAL_SECONDS=3600` and `SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES=true`.

## 2. Measured: the refusals and their holders

The window is 11-10 11:14 PM to 11-18 12:55 PM CST (7.6 days), 11,935 `[refresh_worker] MLB_SIM_TICK` lines and 121
`REFRESH_LAUNCH_REFUSED` lines.

| outcome per tick | day 1 (`lookAhead`) | day 2 (`lookAheadDay2`) |
|---|---|---|
| launched | 121 | 12 |
| refused `lane_busy` | 6 | **115** |
| `day1_launched_this_tick` | n/a | 121 |
| `within_check_interval` | 9,265 | 9,144 |
| `sport_currently_live` | 2,543 | 2,543 |

- **Day 2 was refused on 115 of 127 attempts (90.6%).** Since 11-13 00:00 CST it was refused 86 of 91 times, which
  agrees with the brief's 84 of 89 (its window ended earlier).
- **Who held the lane:** all 121 refusals were on lane `refresh-worker`, and every one came at a look-ahead tick. The
  holder is the refusal's `run_stamp` joined to the launching tick:
  - **day 2:** 114 of 115 refusals were held by the same hour's DAY-1 look-ahead run. The other 1 was held by a
    weekly soccer autorun unit.
  - **day 1:** 5 of its 6 refusals were held by the weekly soccer autorun (per-league units such as
    `--soccer-leagues bundesliga --soccer-date 2026-11-21`), and 1 by a day-1 run.
- **Timing:** a day-2 refusal came p10 64 s, p50 165 s, p90 311 s after that hour's day-1 launch (96 of 115 within
  240 s).
- **A refusal costs a full interval:** 108 of 114 refused day-2 attempts were next tried at least 3,600 s later. The
  other 6 are 3 Central date rolls (the target date changes, so the marker no longer matches) and 3 tick-jitter cases
  at 3,594-3,599 s. The marker is stamped before the launch, so the refusal leaves it stamped.

## 3. The mechanism (confirmed in code and data)

1. `_look_ahead_decision_day2` writes `last_look_ahead_check_day2` (`launched=True`) and returns `launch=True`
   (`live_refresh_loop.py`, the day-2 decision).
2. `_launch_look_ahead_refresh` calls `launch_refresh_run`, which raises `RefreshLaneBusy`, a `ValueError`. The
   launcher swallows it into `skipped: true`.
3. The marker stays, so day 2 is next due 3,600 s after its stamp. Day 1 is also due 3,600 s after its own stamp, a
   few ticks EARLIER, so day 1 relaunches first. Its new run holds the lane when day 2 comes due. The offset between
   the two stamps keeps itself in place: **a phase lock.**
4. **It breaks only when a day-1 run is shorter than the offset.** On 11-11, day-1 runs took p50 390 s, the offset was
   ~490-700 s, and day 2 launched 7 of 18 times. On 11-12 to 11-18 day-1 runs grew (p50 428 → 672 → 892 → 1,238 →
   1,299 → 1,322 → 1,356 s) as the 7-day soccer horizon filled. Day 2 then launched only when day 1 itself was knocked
   out (11-14, 11-16, 11-17, 11-18: launches 3,696-3,828 s after the previous day-1 launch).
5. **The soccer date anchor (`640c6d4fd`, loaded 11:58 AM CST 11-18) does NOT break it.** The first day-1 run after it
   took 386 s, but the offset today is ~165-220 s. Live: day 1 launched at 12:07:20 PM, and day 2 was refused at
   12:10:59 PM, held by that run (`20261118_180720`).
6. **Live, 1:02-1:11 PM CST.** A weekly soccer autorun unit (EPL, `20261118_190234`) refused DAY 1 at 1:08:30 PM, and
   day 1 lost its hour. Day 2 then launched at 1:11:22 PM (`20261118_191122`). This is the pattern H1(c) predicted. My
   narrower prediction, "day 2 refused around 1:10 PM", was wrong for this hour: day 1 was refused first.

The hypotheses, falsifiers and their status are in the lane block:

- H1 (stamp-before-launch phase lock): **CONFIRMED**.
- H2 (a different holder): **FALSIFIED** for day 2 (114 of 115 refusals were held by day-1 runs). It is true for
  day 1's own 6 refusals: 5 were the soccer autorun.

## 4. What day 2 warms, and who reads today+2 (the value question)

Files for 11-20 on the fleet disk, compared with the 11-18 4:06-4:27 AM CST day-2 run window (`d2files.py`).

**Written only by the day-2 run (at D-2):**

- **NCAAB:** `raw_outputs/by_date/<D>/odds_<D>.csv` (311 KB), `tracking/book_quotes/<D>.jsonl` (1.4 MB) +
  state + heartbeat, and the opening + movement-signal CSVs. NCAAB `book_quotes/2026-11-20` was rewritten again at
  1:13 PM by the 1:11 PM day-2 run.
- **NFL:** the opening + movement-signal CSVs for 11-20 (Thursday Night Football).
- **Soccer:** opening + movement-signal CSVs (game odds and player props), and per-league `props/<D>.csv` +
  `game_markets_<D>.json`. `game_markets` is ~the same size for every date (EPL 618-621 KB for 11-18/19/20), so it is
  largely the league's whole upcoming set.
- `odds_events/<D>.jsonl` (13 MB): the odds lifecycle that `odds_lifecycle.load_recent_odds_events` feeds into a
  7-day line-history index.
- **NBA:** props for D+2 (43 B = header only; books had not posted them) and `game_cards_<D>.csv` (1 B).
- **NHL:** `smart_sim_<D>_bundle.json` (1.4 KB). Lineups, goalies and predictions for 11-20 were written at
  12:13 PM by another producer.

**Not dependent on day 2:**

- The board keeps rows beyond tomorrow only for soccer (6-day delta), NFL (4) and NCAAF (2):
  `layer2_board._sport_horizon_days`, `slate_window_days`. NBA, NHL, NCAAB and WNCAAB keep 1.
- For those three sports, other producers write today+2's inputs:
  - soccer `book_quotes/2026-11-20` at 12:21 PM and recommendations for 11-21..11-23 at 11:16 AM-1:09 PM (the
    weekly autorun);
  - NCAAF `book_quotes/2026-11-20` at 12:59 PM;
  - NFL is week-scoped.
- **No board-seated D+2 row was found that depends on a day-2-only file.**

**Known downside (fixed):** `#721` (`[nba-sim-anchor-refresh]`). A D-2 look-ahead NBA predictions file became the
NBA SmartSim's market anchor ("written 10-19 3:04 AM CT, ~63 h before tip"). It is now refreshed at reuse.

**So day 2's value is an EARLIER odds snapshot**, not anything served. In order:

1. NCAAB lines and quotes a day earlier;
2. opening/movement baselines one day earlier for every sport;
3. an earlier point in the 7-day line history.

None of these is a correctness input to a served D+2 row today. **Worth little, but not nothing.** Whether to restore
it or retire it is the user's call (section 7).

## 5. What it costs

- **Lane time:**
  - a day-1 run is 386 s now (after the soccer anchor);
  - a day-2 run should be about the same: its soccer step simulates only its own date's fixtures, and 11-11's seven
    day-2 runs took p50 360 s;
  - restoring day 2 adds ~6-10 min of refresh-worker lane per idle hour (the 1:11 PM day-2 run took 615 s in daytime
    contention);
  - total look-ahead lane hold would be ~13 min/idle hour, against 20-40 min/hour from day 1 alone on 11-13..11-18,
    when the weekly soccer autorun was healthy (unit age at launch p90 17,146 s against a 14,400 s interval,
    `[soccer-lookahead-horizon]`).
- **Idle hours:** look-aheads run only while nothing tracked is live. Day-1 launches were 10-18 per Central day, so
  day 2 would launch about as often.
- **OddsAPI:** the fleet burns 5,054 credits/h, projected 3,639,008 per 30 days against the 5M cap (72.8%; quota read
  1:04 PM CST). The cost of ONE look-ahead run is not recorded per caller anywhere. I measured it on the live 1:11 PM
  day-2 run: **≈ 950-1,070 credits per run** (section 8). Restoring day 2 hourly adds ~0.3-0.57M credits per 30 days.

## 6. The fix (on main, default OFF)

`SYNDICATE_LOOK_AHEAD_LANE_WAIT` (absent / anything else = off = today's behaviour exactly; `1`/`true`/`yes`/`on` =
on), in `live_refresh_loop.py`. It touches only the look-ahead functions and the `lookAhead`/`lookAheadDay2` call site.

**When on:**

- **A due look-ahead whose lane is busy WAITS** (`reason: lane_busy_wait`):
  - it writes no stamp and fetches no schedule;
  - it attempts no launch, so it prints no refusal line;
  - the only cost is one read-only `is_refresh_run_active()` per tick;
  - it launches on the first tick the lane is free.

  The stamp is still written only at launch, so each day launches **at most once per interval**. That is the launch
  rate day 2 was designed for, and it adds no OddsAPI calls beyond it.
- **A launch the mutex still refuses `lane_busy`** (the check is read-only and can race) is re-armed to retry in 300 s
  (`markerRewound`, `retryInSeconds`), not a full interval.
- **Any other refusal** (`state_unconfirmed`, a launch error) keeps the full-interval stamp, so an unreadable lane is
  never retried every tick.
- **Day 1 is decided first in the tick.** When both are due and the lane frees, day 1 wins.
- **Day 1 gets the same wait:** a day 1 that comes due while day 2 (or a soccer autorun unit) holds the lane launches
  minutes later, not an hour later. Day 1 lost 6 hours in 7.6 days this way, plus 1:08 PM today.

**Additive in both modes:** `_launch_look_ahead_refresh`'s refusal dict carries `reasonCode` (`lane_busy` /
`state_unconfirmed`). This is a log field only.

**Tests:** `tests/test_lookahead_day2_phase_lock.py`, 7 tests. They drive the REAL `_run_mlb_sim_tick` tick by tick on
a fake clock (38 s ticks, 386 s runs), with the real marker files on the test's reports root and one fake lane that
refuses like `ops_refresh`.

- Off reproduces the fleet's lock: 6 h gives day 1 6 launches, day 2 0 launches and 6 refusals, each inside the same
  hour's day-1 run, each ≥3,600 s apart, and 0 lane checks.
- On gives day 2 6 launches, 0 refusals, each on the first tick after the day-1 run ends, ≥3,600 s apart, and exactly
  one schedule fetch per launch.
- Off != on on the same tick sequence: 0 vs 2 day-2 launches in 2 h.
- A 3,400 s day-2 run delays day 1 by <300 s.
- A racing refusal retries in 300 s (≤2 refusals).
- `state_unconfirmed` keeps the full interval.

40 existing look-ahead / sim-tick / run-tick tests pass. The full-file `tests/test_live_refresh_loop.py` result is in
section 8.

## 7. Betting-change class and the load

- **The code load (switch absent) is `betting change: no`.** It changes nothing except the added `reasonCode` log
  field.
  - It is in-process refresh-worker code, so it loads at the next refresh-worker restart: a role TERM under a claim
    and a preflight CLEAR, right after a board save (`learnings.md` 2026-10-07).
  - No dedicated restart is needed. The code can ride whichever refresh-worker restart comes next, because it does
    nothing until switched on.
- **Switching it on is classified `betting change: YES` (conservative)**, for two reasons:
  - it changes WHEN D+1 inputs are written: day 1 loses minutes instead of an hour when it collides, and NBA/NHL/
    NCAAB/WNCAAB keep tomorrow on the board;
  - it adds D+2 writes for sports the board seats two days out (soccer, NFL, NCAAF picks and markets), and a D-2
    write has changed an engine anchor before (`#721`).

  So it loads only in a betting-change window. The first is **Tue 11-24, 2-7 AM CST**
  (`.syndicate/betting_change_windows.md`).
  - **The mechanics:** set `REFRESH_WORKER__SYNDICATE_LOOK_AHEAD_LANE_WAIT=on` in `~/syndicate-prod/local_production.env`,
    then run a drained full `down` + `Start-ScheduledTask SyndicateLocalProduction`, with the claims and a joint
    CLEAR.
  - The switch is env, built only at `up`.
- **The user's choice**, as put to the user:
  - **(a) restore day 2:** switch on in the 11-24 window. This also fixes day 1's lost hours;
  - **(b) fix day 1 only, retire day 2:** switch on and set `REFRESH_WORKER__SYNDICATE_LOOK_AHEAD_48H_ENABLED=false`
    in the same window. This removes ~15 refusal lines a day and the occasional unplanned day-2 run, and frees the
    lane for the soccer autorun;
  - **(c) leave both as they are.** Day 2 stays mostly locked out and runs only when day 1 is knocked out.

## 8. OddsAPI cost of one day-2 run (measured), and the full-file test result

**Method.**

- `quota_sampler.py` read `/api/ops/oddsapi/quota` every 20 s from 1:05 PM CST.
- The fleet-wide `used` counter and the per-sport credit counters were differenced per sample.
- Each delta was lined up with the 1:11:22 PM day-2 run's own step start and finish times (`d2_steps.json`, from its
  `odds_refresh.json`). The run is `20261118_191122`, date 11-20, 1:11:24-1:21:39 PM, 615 s.

**Background (no look-ahead running)** is about 20 credits/min:

- NCAAB 3-7 + WNCAAB 3 every 20 s;
- NCAAF 9 + NFL 6 about every 2 min;
- 1:18-1:25 PM read 0-15 credits per 20 s.

**The day-2 run's own spikes** line up with its steps:

| sport | credits | when (CST) |
|---|---|---|
| NHL | ~40 | 1:12:19-1:13:19 |
| NFL | 124 | 1:13:19 |
| NCAAF | ~32 | 1:13:39 |
| NCAAB + WNCAAB | ~10 above background | |
| soccer | 742 | 1:16:21-1:17:41 |
| NBA | 0 | |

- The soccer burst matches the run's 13 `soccer_*_odds` steps (1:16:03-1:16:33) and 13 `soccer_*_props` steps
  (1:16:33-1:17:32) to the sample.
- A further NFL 51 + 67 at 1:15:00-1:15:20 fell after the run's NFL step had finished (1:13:22). Its attribution is
  uncertain.

**One day-2 run ≈ 950-1,070 credits, ~75% of it soccer** (n = 1 run, daytime, D+2 a Thursday). A day-2 run on a
weekend date may cost more (more soccer events with props).

**What restoring day 2 costs:**

- day 2 would launch about once per idle hour, 10-18 a day (day-1 launches per day 11-11..11-18);
- that adds about 10-19k credits/day, or **0.3-0.57M per 30 days**;
- on top of the 1:04 PM projection of 3.64M, that is about **4.0-4.2M, 80-84% of the 5M cap**;
- today the locked-out day 2 already runs ~1 a day (5 launches 11-13..11-18), ~1k credits a day.

**Fleet-wide context:** a burst of ~730 soccer credits at 1:09:18-1:11:18 PM was NOT this run. Day 1 had just been
refused, and the lane held a weekly soccer autorun unit. Another producer spends soccer credits in bursts too.

**Other notes:**

- **Day-2 run lane time:** this run took 615 s (daytime contention; soccer 405 s of it). 11-11's seven took p50 360 s.
- **NHL odds for D+2:** `nhl_oddsapi_refresh` exited rc 1 in both recent day-2 runs (4:06 AM and 1:11 PM; day-1 runs
  rc 0). No error text was retained (`odds_refresh.stderr.txt` keeps 32 KB + tail). This is a lead, not chased.
- **Tests:** full `tests/test_live_refresh_loop.py`: **227 passed, 13 subtests passed** (332 s) with the fix in place.

## 9. Recommendation (the user decides)

**My recommendation is (b): switch on and retire day 2.**

- The value of day 2 is an earlier odds snapshot that no served row depends on.
- Restoring it costs ~0.3-0.57M OddsAPI credits a month (+6-11 points of the cap) and ~6-10 min of refresh-worker lane
  per idle hour.
- The switch still fixes day 1, which today loses an hour each time the weekly soccer autorun holds the lane.

**Choose (a)** if the earlier D-2 lines matter to the profit learning program, for example opening-to-close movement
studies.

**A cheaper middle option is NOT built:** a separate, longer day-2 interval (e.g. every 6 h ≈ 3-4k credits/day). It
would need its own switch.
