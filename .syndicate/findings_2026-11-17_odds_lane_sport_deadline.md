# Findings — the live odds lane held 30 min by one sport (lane `odds-lane-sport-deadline`)

Opened Tue 11-17 ~8:30 PM CST from the rail monitor's I-22 (`findings_2026-11-17_layer2_rail_monitor.md`,
readings 13-15). Hypothesis written into the lane (`1f4b262da`) before any test. All fleet reads were read-only,
`nice -n 19`, at `~/syndicate-prod`. Times are UTC with Central in brackets where it matters.

## Hypothesis results

### H1 (the run) — CONFIRMED
- live-odds-worker env: `SYNDICATE_SERIAL_SPORT_REFRESH=true` (read from `/proc/52087/environ`, 02:37Z). The sports
  in a live run go one at a time in `--sports` order (`nba,nhl,[nfl,]ncaaf,ncaab,wncaab`).
- One run-wide step timeout, `_DEFAULT_REFRESH_STEP_TIMEOUT_SECONDS = 1800`, and no per-sport one.
- A `TimeoutExpired` is NOT a failed step: `_run_command` re-raises it, nothing in `_run_sport_refresh` or
  `_build_summary` catches it, and `main` writes an error JSON and exits 1. `--continue-on-error` (default True)
  never applies.
- The failed run's manifest (`migration_runs/2026-11-17/odds_refresh_20261118_012111/odds_refresh.json`) is
  **831 bytes**: `ok False`, `returnCode 1`, the error, no `results`. NBA ran first and finished, and its result is
  gone; NCAAF / NCAAB / WNCAAB never ran in that run.

### H2 (the child) — CONFIRMED in mechanism, CORRECTED in the endpoint
- **Mode:** the hung children ran `--mode full` (generation due). The 02:25Z child's cmdline had no `--mode`, and
  the due-check reads `predictions_<date>.csv` age. Predictions were last written 00:53:10Z (6:53 PM) for 11-17 and
  00:57:16Z for 11-18. A generation that times out writes none, so **every following live sweep was due again**:
  01:21Z, 01:54Z, 02:25Z and ~02:48Z each ran full mode and hung. The loop sustains itself.
- **Where it stalls (02:25Z child, pid 138879):** the odds were done in ~1 min (scoreboard 02:25:46Z, team odds
  02:25:51Z, props 02:26:11Z, both dates by 02:26:38Z). In-season team xG and season inputs were written by
  02:26:43Z. Then nothing was written for 10+ min. That stage is `collect_slate_inputs`, the per-team lineup
  collection (`hockeysim/ingestion/collect.py`). The child sat at 1.7% CPU: main thread in
  `poll_schedule_timeout`, one HTTPS socket to 104.16.145.251 with a request out and no response for ~10-20 s at
  each look. py-spy could not attach (`ptrace_scope=1`; not escalated).
- **The endpoint is the NHL STATS REST API, not api-web.** `api.nhle.com` and `api-web.nhle.com` resolve to the
  SAME Cloudflare pair (104.16.144.251 / .145.251), so the IP cannot tell them apart. The rail monitor's
  "api-web" was an inference from the IP. Per slate team, `collect_slate_inputs` makes:
  - 1 roster call and 1-2 club-schedule calls on api-web (measured: roster 0.19 s);
  - **6 stats-REST calls** with `limit=-1`: `special_teams_toi` (timeonice, gameType 2 and 3, this season) and
    `onice_goals` (goalsForAgainst, gameType 2 and 3, this season AND last season). None of them is cached.
  - The client is `NhlWebIngestClient`: urllib, 30 s timeout per call, no total deadline. A failed call returns
    `{}` and the caller falls back.
- **Stats-REST latency measured 02:38-02:44Z (7 calls):**

  | call | first byte |
  |---|---|
  | timeonice MTL 2025-26 gt2 | 28.2 s (200) |
  | timeonice TOR 2026-27 gt2 | 29.6 s (200) |
  | timeonice TOR 2026-27 gt3 | 44.1 s (200, **21 bytes = empty: no playoffs yet**) |
  | goalsForAgainst TOR 2026-27 gt2 | 26.6 s (200) |
  | goalsForAgainst TOR 2025-26 gt3 | 21.8 s (**520**) |
  | timeonice BOS 2026-27 gt2 | 5.3 s (**520**) |
  | goalsForAgainst MTL 2025-26 gt2 | 1.2 s (200, cached at the CDN) |

  That is 5 of 7 calls slower than 20 s or failing. Slates: 11-17 has 11 games and 11-18 has 3 (`--days-ahead 1`),
  so 28 teams × 6 = **168 stats calls**. At ~25-30 s each that is ~4,200-5,000 s, far past 1,800.
- **The earlier long runs were NHL too.** Every live run with an NHL step over 300 s tonight was a full
  generation:

  | run (UTC) | run length | NHL step |
  |---|---|---|
  | 23:36Z | 771 s | 621 s full |
  | 00:14Z | 445 s | 423 s full |
  | 00:48Z | 578 s | 540 s full |
  | 01:21Z | 1,929 s | TIMEOUT |
  | 01:54Z | 1,817 s | TIMEOUT |
  | 02:25Z | (hung) | full |
  | ~02:48Z | (hung) | full |

  Every live run with a FAST NHL step was 72-164 s.
- **History, 11-13..11-18, both manifest shapes (8,187 manifests, 475 live runs with NHL):**
  - live NHL step, fast: n=413, p50 46 s, p90 56, max 89;
  - live NHL step, full: n=60, p50 351 s, p90 545, max 987;
  - all phases, full: n=300, p50 254 s, p90 450, p99 753, max 987.

  The only NHL timeouts in those 6 days are tonight's. The earlier three `TimeoutExpired`s were
  `refresh_nba_oddsapi_props.py` at ~05:00Z.

### Cost, measured from `logs/live-odds-worker.log`
Each LAUNCHED line is an attempt; the refusals are a subset of the attempts.

| window (UTC) | attempts | refused `lane_busy` |
|---|---|---|
| 22:00-00:00 | 42 | 9 (21%) |
| 00:00-01:21 | 37 | 18 (49%) |
| 01:21-03:02 | 26 | **23 (88%)** |

- Each lane holder's run_stamp maps to its manifest: every refusal series after 23:36Z sits inside an NHL
  full-mode run.
- NHL team odds were 868 s old at 03:02Z.

## The fix (on main behind `SYNDICATE_ODDS_LANE_STEP_DEADLINE`, absent = ON)
1. **A timeout is a failed step** (`_run_command` → `_timed_out_step_result`). The run carries on to the next
   sport; the result carries `status timeout` and an 800-char stdout tail.
   - The tail matters: the NHL runner prints one line per stage, so the next hang names its stage.
   - `_run_step_process` now keeps the killed child's output on the exception, as `subprocess.run` does.
2. **Per-step and per-sport deadlines.**
   - `RefreshStep.timeout_seconds` sets a step's own deadline, tightened under the run-wide one.
   - `SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS__<SPORT>` sets a deadline for every step of one sport. It is absent
     everywhere, so nothing changes until someone sets it.
3. **NHL live generation is split off.** When generation is due in a live sweep:
   - `nhl_oddsapi_refresh` runs `--mode fast` (odds only, ~46 s) in NHL's normal turn;
   - the new `nhl_live_generation` (`--mode generate`: generation without odds collection, so **zero added
     OddsAPI calls**) is `deferred`, so it runs after EVERY sport's odds;
   - its deadline is `SYNDICATE_NHL_LIVE_GENERATION_DEADLINE_SECONDS`, default 900. That would have cut 1 of the
     60 live full steps measured (987 s).
4. **Cooldown after a generation timeout.** The step writes
   `nhl_source/data/processed/.nhl_live_generation_timeout_<date>.json`. `_nhl_live_generation_due` returns False
   for one generation cadence after it (`SYNDICATE_NHL_LIVE_FULL_GENERATION_SECONDS`, 1,800 s), so the sweeps in
   between refresh NHL odds fast instead of re-entering a stalled generation.
5. `off` restores today exactly: a timeout raises, NHL runs one full step inline, and the marker is ignored.
   Tests pin both.

**Tests:** `tests/test_refresh_odds_sport_deadline.py` (26) runs the REAL `_build_summary` over real child
processes. Reachability: with the same run-wide 2 s timeout, ON leaves the next sport run and the hung sport
`timed_out`; OFF raises `TimeoutExpired` and the next sport never runs. Deferral order is checked on vs. off, and
so are the marker, the cooldown, `--mode generate` making no collection call, and the per-sport env.
`test_nhl_live_sweep_mode.py` and one test in `test_refresh_odds_sources.py` are pinned to `off` (they encode
today's shape). The related suite passed: 96 of 96, plus the adjacent files (see the lane).

## Load: a fleet fast-forward, NOT a TERM
`refresh_odds_sources.py` and `refresh_nhl_oddsapi.py` are run by both workers ONLY as fresh child processes per
sweep. The one in-process import is web's `/api/ops` plan endpoint (`ops_refresh.build_refresh_plan`), a dry-run
listing. So an ff of `~/Syndicate` reaches the next live sweep with no restart.
- The ff also ships every other commit on main up to the SHA: child scripts change at once, and in-process code
  at each role's next restart. Tonight that includes the 1:10 AM CST refresh-worker TERM, which was planned to load
  `3920a2d4d`.

## PRE-REGISTERED PREDICTION (written 11-17 ~9:10 PM CST, before any load)
For the first live window after the load with the NHL stats API as slow as tonight (stats calls >= 20 s or 520).
Readings from `logs/live-odds-worker.log` and `migration_runs/*/odds_refresh_*`:
1. **Max live odds run length <= 1,200 s.** That is the 900 s generation deadline plus the other sports' steps;
   baseline tonight is 1,929 s and 1,817 s, and two runs are still hung. No `TimeoutExpired` error manifests: a
   generation timeout shows as a `nhl_live_generation` step with `timed_out: true`, inside a run that carries every
   sport's result.
2. **`lane_busy` refusals <= 50% of attempts** in the slow-API window, against tonight's 88% (23 of 26). At worst
   each 30-min cooldown cycle holds the lane for one 900 s attempt. With a healthy API the share stays at the
   22:00-00:00Z baseline (21%), because a healthy generation (p50 351 s) still runs once per cadence. The change
   bounds the bad case; it does not speed up the good one.
3. **`NHL_LIVE_GENERATION_COOLDOWN` lines** on the sweeps after a generation timeout. Those sweeps' NHL step is
   `--mode fast` and 40-90 s.
4. **NHL team odds age** (`nhl_source/data/odds/team/date=<d>/oddsapi.csv` mtime) never exceeds ~1,200 s during
   live NHL games, against ~1,800 s+ tonight. NHL in-play overlay rows do not sit at 0-5 for longer than one
   generation hold (~15-20 min). Before tonight's 01:21Z they sat that way for 26+ min.
5. **NOT predicted to improve: NHL predictions freshness while the stats API is slow.** Each attempt still hits
   the 900 s deadline, because the 168 uncached stats calls do not fit. That is the follow-up (below).

Falsified if a live run exceeds 1,200 s with the switch on, or a run dies `TimeoutExpired` with sports unrun, or
the refused share stays above 50% in a window where the NHL generation is timing out.

## Follow-up (not this lane): the NHL generation's stats-REST calls
Per team per run, 6 uncached `limit=-1` stats-REST calls (above):
- 2 are **this season's playoffs (gameType 3) in November**: always empty, measured 44 s;
- 2 are **last season's** finished, immutable reports;
- the 2 current-season reports change only when the team finishes a game.

Fetching these once and caching them, validated against the finished game ids the usage window already reads,
would cut ~168 calls per generation to ~0-12. The data is identical, so the model output is unchanged. That would
make full generation fast on healthy nights and possible on slow ones.

## Baseline addendum (rail monitor reading 16, 8:37 PM CST, relayed 11-17 ~9:40 PM CST)
Prediction 4's in-play baseline: NHL in-play overlay rows were 0-16 for 02:06-02:37Z, except **600 at
02:26-02:29Z**, right after the 02:24Z timeout freed the lane. Sweeps 02:06-02:37Z: 7 launched, 6 refused
`lane_busy`. So NHL in-play rows track the lane being free, which is the mechanism this fix bounds.

## Pregame extension (2026-11-18 ~9:50 AM CST, user "Yes, build it")
**On main `cdab875d5`, NOT LOADED.** Hypothesis H3 and predictions P1-P6 were written into the lane block
(`b74546351`) before the build.

- **Why.** A pregame sweep still ran NHL's full step inline: odds and generation, under only the 1,800 s
  run-wide timeout, with no cooldown. Pregame sweeps with NHL launch about every 31 min (wrapper launch gaps
  p50 1,850 s), so a stats-API stall before puck drop could hold the lane on every one.
- **Change.** The switch is `SYNDICATE_NHL_PREGAME_GENERATION_SPLIT`, absent = ON. It also needs
  `SYNDICATE_ODDS_LANE_STEP_DEADLINE` on.
  - A pregame sweep runs `nhl_oddsapi_refresh --mode fast` in NHL's turn.
  - `nhl_pregame_generation` (`--mode generate`, 0 OddsAPI calls) runs after every sport, deferred, with its
    own 900 s deadline (`SYNDICATE_NHL_PREGAME_GENERATION_DEADLINE_SECONDS`).
  - A timeout writes the SAME per-date marker as live. Pregame and live sweeps inside one cadence
    (`SYNDICATE_NHL_LIVE_FULL_GENERATION_SECONDS`, 1,800 s) then run NHL odds only and log
    `NHL_PREGAME_GENERATION_COOLDOWN` / `NHL_LIVE_GENERATION_COOLDOWN`.
  - Pregame always generates outside a cooldown, as before. `--phase all` is unchanged; `off` restores the
    inline full step.
- **Baseline, fleet manifests 11-13..11-18 (read 15:30Z):**

  | measure | value |
  |---|---|
  | pregame full NHL steps | 258: 184 wrapper (p50 218 s, p90 372 s, max 532 s) + 74 direct (p50 331 s, max 807 s) |
  | over 900 s / timed out | 0 / 0 |
  | ok | 255 of 258 |
  | live `--mode fast` NHL steps | 482, p50 44-46 s, max 89 s |

  So the 900 s deadline cuts no measured healthy pregame generation.
- **Tests.** 17 new cases in `tests/test_refresh_odds_sport_deadline.py`; 16 fail on main's code, and the
  `--phase all` pin passes on both.
  - The `off != on` reachability test runs the REAL `_build_nhl_steps` through the real run loop (commands
    swapped for loggers): ON = fast odds, the next sport, then generation; OFF = one full step in NHL's turn.
  - A hung pregame generation dies at its deadline, the next sport keeps its result, the marker is written,
    and the next pregame and live builds are odds-only.
  - 51 targeted + 78 neighbouring tests pass.
- **Prediction** (lane block H3): see P1-P6 there.
- **Measured, not fixed here: soccer holds the pregame lane longest.**
  - 54 of 184 pregame wrapper runs with NHL ran over 900 s, and 7 over 1,800 s. In 51 of the 54, soccer was
    the longest sport: up to 2,763 s in run `odds_refresh_20261117_182727` (2,983 s in all).
  - No single soccer step went over 900 s. Of 271 runs per league step, the worst step's p90 was 206 s and its
    max 855 s (`soccer_championship_artifacts`). The hold is the SUM over leagues.
  - So a per-step deadline cannot bound it, and this lane's goal ("no single sport ... for 30 min") is not met
    for soccer.
