# FINDINGS -- the board's SUGGESTED set graded as its own set, daily: coverage, results, and the comparison

Lane `layer2-suggested-grader`, session ab77b427, started from the rail monitor's group. The user asked the rail
monitor on 11-18 (~5:05 PM CST): "are we tracking recomendations and success of recomendations on the rail? can we
incorporate layer 2 board performance and suggested opportunities performance? We should have a lot of history to
look at for this as well". They then said "Yes, start it" to this work.

**Read-only on the fleet**, apart from this lane's own new output folder (`reports/suggested_set/`). Nothing was
loaded and nothing was restarted; no env change, no deploy, no odds fetch. The scripts ran at nice 19 under the fleet
venv, from this lane's worktree. Times are US Central (CST, UTC-6).

## Answer

**Over the latest 28-day window (kickoffs 10-21..11-17, regular season, all sports), the suggested set lost 3.0% per
bet: -3.02% [-5.56, -0.51], 11,748 bets / 1,338 games, hit 47.3%, -354.36 units.** The board promised +3.41% market
EV on those same bets, so it realised 6.4 points below its promise. Counting each alt ladder once, it is -1.8%
(9,186 ladders).

- **Suggested beats the whole board and the published set, and trails the staked set.**
  - The scorecard over the same window, all sports without the postseason sports (MLB, WNBA): whole board -10.69%
    (1,751,057 bets), published -5.87% (935,367), staked +2.69% (9,810).
  - Suggested sits between published and staked. It is not a like-for-like step to staked (§5).
- **Its interval excludes 0 for the first time from 11-15** (-2.91% [-5.66, -0.42]). It drifted down from -0.6% /
  -0.8% on the 11-04..11-06 windows.
- **The pre-registered hypothesis is FALSIFIED as written** (§4).
  - Pooled, it holds narrowly: suggested -3.02%, published -5.87%, and the interval stops at -5.56.
  - Two sports with >= 60 games are falsifying slices: NBA -3.20% vs published -1.16%, and NCAAB -8.95% vs -4.66%.
- **Where it loses** (§3; read these as lines to fix, never sports or markets to withhold):
  - NBA live, alt totals and alt spreads. 93% of NBA's suggested bets are live.
  - NCAAB live game lines.
  - NHL live.
- **About half the board's suggested lines are not in this grade at all** (§2): the recorder writes only a line's
  first sighting per board date.

**The grader is on main** (`scripts/grade_suggested_set.py`, 20 tests). **The results are on the fleet** at
`~/syndicate-prod/data/reports/suggested_set/suggested_set_latest.json`.

**UPDATE 11-18 ~11:00 PM CST (user "Yes, go ahead"): both loads are done.**
- The daily refresh runs as Windows task `SyndicateSuggestedSet`, 7:15 AM CT, first run 11-19. Its test run at
  10:57 PM gave result 0 and `rc=0` in 33 s (§6).
- The recorder's `#sg` record (§2, §7) has been live since **04:46:47Z (10:46 PM CST)** (`deploys.md`
  2026-11-19 04:46:22Z).
  - The first build on it wrote 103 suggested-sighting records.
  - So from the 11-19 run on, this grade sees every line the board suggests, not only those suggested at first
    sight. Earlier days keep the blind spot.

## 1. Where `suggested` is recorded, and since when (fleet, read 11-18 5:49 PM CST)

| family (fleet data root) | carries the flag? | dates | what one entry is |
|---|---|---|---|
| `reports/intelligence/opportunity_population/` (recorder, field `sg`) | **yes** | board dates 10-13..11-19 | a line's FIRST sighting per (board date, phase) |
| `reports/intelligence/decision_records/<date>.json.gz` (`board_suggested`) | yes | 10-23..11-19 (28 dates) | the day's LAST build only (5-255 suggested lines per day) |
| `decision_records/<date>.pregame_lines.jsonl.gz` | **no** (its slim sections drop it) | 11-10..11-19 | first/last pregame record per line |
| `decision_records/<date>.agreement.jsonl` | per-build summaries only | 10-23..11-19 | one line per build |
| `reports/intelligence/clv_openings/` | **no** (0 lines in every file) | 09-30..11-19 | a published line's opening |

Recorder detail, `sg` by board date:
- 10-10..10-12: absent on every record (before the flag existed).
- 10-13: 30 true / 10,744 false / 27,007 absent (written before the 16:49Z load).
- 10-14: 43 true / 24,241 false / 21,841 absent.
- 10-15..11-19: present on every record.
- 13,030 `sg=true` records over 10-13..11-19: NBA 8,897, NCAAF 959, NHL 856, NCAAB 821, NFL 665, soccer 652, WNBA 128,
  MLB 35, WNCAAB 15.
- **Every one of the 13,030 ranks on the market** (`eb = market_fair`). That is the flag's rule (market EV >= +2%
  against a two-sided fair). So the optimizer's "predicted (model) EV", which counts model-ranked rows only, is empty
  for this set by construction. 4,973 of the 13,030 (38%) carry a sim edge; §4 reports the sim's EV on those.

**Intersection.** The two families that carry the flag overlap on 10-23..11-19 (28 dates). The decision records hold
one build per day, so they cannot say when a line was first suggested. **Every graded number rests on the recorder
alone.**

The cheat sheets' "Syndicate picks" section consumes the board cards' `suggested` (pregame, main line, priced
-250..+250) and is graded by the cheat-sheet reconcile. It is a subset, and it is not used here.

## 2. The recorder's blind spot: about half the suggested lines (measured)

The recorder writes a line once per (board date, phase), at its first sighting that day (`seen_key`, the `#live`
suffix). A line that turns suggested at a LATER build of the same day is already recorded with `sg=false`, and is not
written again. Each day's last build in the decision records is a second view of the flag, so it measures the gap.

Lines suggested at each day's last build, looked up in the recorder (any board date, same phase):

| | lines | `sg=true` in the recorder | `sg=false` only | not recorded |
|---|---|---|---|---|
| 10-23..11-17 (closed days) | 610 | **304 (49.8%)** | 304 (49.8%) | 2 (0.3%) |
| 11-18 (open: the next board date may still record it) | 235 | 9 | 226 | 0 |
| 11-19 (open) | 11 | 3 | 8 | 0 |

Days vary widely: 11-05 46 of 47 captured, 11-03 27 of 31, but 11-10 4 of 28 (24 of them live) and 11-13 7 of 32.

**So the graded set is "lines already suggested when the board first saw them that day", about half of what the
board suggests.** Lines that turn suggested later in the day are missing, and they may differ: a price that drifts
into +2%, or a fair that moves. The scorecard's STAKED set has no such gap, because the paper book stakes from every
build. The fix is a recorder change (§6).

Script: `C:\tmp\sgset_1118\gap.py`, output `gap.json`.

## 3. Results (fleet hand runs 11-18, 5:59-6:07 PM CST; read-only except `reports/suggested_set/`)

**What the grade rests on.**
- The recorder, board dates 10-13..11-19: 528 parts, 3,118,816 records, 13,030 `sg=true`, 12,900 identities.
- Graded: 12,655 (98.1%).
- Not graded: 245 -- not yet played 125, DNP void 54, push 52, NHL name 6, no chip match 5, final score
  unparseable 3.
  - 148 of them are retried daily: kickoff within 7 days, including all 125 not yet played.
  - 97 are final.
- Kickoff dates graded: 10-13..11-17 (36 dates). No team names were missing (`names_lent` 0).

**Reproduction first.** The new grader re-ran the 11-02 grade (files 10-17..11-01, today 11-02, no state) and
reproduced it exactly:
- pooled regular season 5,353 bets / 551 games, -1.1% [-5.1, +3.0] (11-02: -1.1% [-5.2, +3.0]);
- every sport to 0.1 point;
- 5,505 graded (11-02: 5,505).

**Latest 28-day window (day 11-18 = kickoffs 10-21..11-17), by sport:**

| sport (phase) | bets / games | hit | ROI per bet [95% by game] | ladders once | market EV promised | sim EV (rows) | sim rows' ROI |
|---|---|---|---|---|---|---|---|
| **All, regular season** | 11,748 / 1,338 | 47.3% | **-3.02% [-5.56, -0.51]** | -1.8% (9,186) | +3.41% | +3.18% (4,477) | -2.53% |
| NBA | 8,622 / 206 | 47.4% | **-3.20% [-6.32, -0.30]** | -1.7% (6,272) | +3.42% | +3.18% (3,288) | -3.02% |
| NCAAB | 799 / 458 | 44.7% | **-8.95% [-15.96, -1.86]** | -10.1% (745) | +3.38% | -0.77% (197) | +5.12% |
| NCAAF | 589 / 216 | 52.6% | +5.81% [-2.98, +14.73] | +5.6% (558) | +3.55% | +1.76% (233) | -5.12% |
| NHL | 714 / 183 | 50.7% | -1.84% [-9.72, +6.03] | -1.6% (711) | +3.31% | +4.47% (597) | -0.81% |
| NFL | 527 / 57 | 47.2% | -2.61% [-12.92, +7.97] | -1.8% (509) | +3.38% | +5.82% (104) | -8.77% |
| Soccer | 497 / 218 | 40.0% | -2.92% [-18.82, +12.41] | +1.5% (391) | +3.41% | +4.11% (58) | +3.21% |
| MLB (postseason) | 17 / 5 | 58.8% | +4.14% [-55.1, +50.7] | -2.1% | +3.59% | | |
| WNBA (postseason) | 87 / 5 | 42.5% | +33.47% [-34.6, +95.6] | +47.4% | +3.50% | | |
| WNCAAB (no phase calendar) | 15 / 14 | 73.3% | +29.54% [-12.8, +73.3] | | +3.32% | | |

- Predicted (model) EV is empty in every row: every suggested record ranks on the market (§1).
- The sim priced 38% of the rows. Where it did, its EV agreed with the market (+3.18% overall), and those rows lost
  as much as the rest (-2.53%).

**Pregame vs live (same window).** Read these as lines to fix (PRIME DIRECTIVE), never as a cut:

| | live | pregame |
|---|---|---|
| NBA | 8,046 / 206, -3.07% [-6.24, +0.02] | 576 / 170, -4.94% [-15.06, +5.83] |
| NCAAB | 759 / 445, **-10.49% [-17.44, -2.99]** | 40 / 39, +20.35% |
| NHL | 105 / 72, **-19.14% [-36.48, -1.86]** | 609 / 177, +1.15% [-7.57, +9.56] |
| NCAAF | 411 / 187, +5.81% | 178 / 125, +5.80% |
| NFL | 412 / 57, -2.41% | 115 / 50, -3.33% |
| Soccer | 281 / 161, -11.18% [-26.17, +5.90] | 216 / 126, +7.83% [-17.74, +36.24] |

**Markets with >= 100 bets, or an interval that excludes 0 (same window):**
- NBA totals_alt 1,552 bets / 183 games, -7.44% [-16.97, +2.75]; ladders once -6.85% (528 ladders).
- NBA spreads_alt 1,472 / 190, -3.83% [-11.96, +4.46]; ladders once +1.89% (656).
- NBA rebounds 791 / 198, +5.92% [-1.92, +13.93].
- NBA points 962 / 201, -1.34%.
- NBA rebounds+assists 492 / 178, -6.59%.
- NBA spreads 345 / 167, -6.81%.
- NBA totals 337 / 162, +4.83%.
- NBA h2h 148 / 101, -9.66%.
- NCAAB totals 412 / 309, **-9.14% [-18.82, -0.31]**.
- NCAAB spreads 298 / 233, -9.53% [-21.03, +1.87].
- Soccer alternate corners 296 / 137, -14.81% [-34.42, +6.03].
- NCAAF spreads 247 / 149, +6.24%.
- NCAAF h2h 146 / 114, +9.95%.
- NHL assists 241 / 130, -9.43%.
- NHL points 226 / 123, +5.43%.
- NFL interceptions 20 / 17, -48.22% [-82.05, -1.45].

**The 28-day window by run day, regular season, all sports** (suggested; scorecard sets without MLB / WNBA):

| day | suggested | published | staked | whole board |
|---|---|---|---|---|
| 10-21 | -1.15% (701 / 173) | -13.72% | +1.12% | -17.25% |
| 10-28 | -3.61% [-8.99, +1.90] (3,217 / 391) | -10.98% | +2.48% | -14.58% |
| 11-04 | -0.74% [-4.41, +3.19] (6,235 / 709) | -9.07% | +1.92% | -13.37% |
| 11-11 | -2.59% [-5.44, +0.34] (9,352 / 1,120) | -7.72% | +3.83% | -12.62% |
| 11-15 | -2.91% [-5.66, **-0.42**] (10,795 / 1,251) | -6.52% | +2.75% | -11.40% |
| 11-18 | -3.02% [-5.56, -0.51] (11,748 / 1,338) | -5.87% | +2.69% | -10.69% |

By kickoff date, regular season: 11-07..11-10 were -6.7%, -10.1%, -11.6% and -9.0%. 11-09 was -11.64%
[-21.2, -4.1] (331 bets / 30 games).

## 4. The pre-registered hypothesis, judged

Registered in the lane before any number was read: suggested ROI per bet HIGHER than published over the same 28-day
windows, in each sport with >= 60 graded games; pooled, the suggested interval lies above the published point
estimate.

- **Pooled (day 11-18): holds, narrowly.** Suggested -3.02% [-5.56, -0.51] vs published -5.87%. The interval clears
  it by 0.31 points.
  - The two sets are not built alike. Published is 56% NBA and its market EV is -4.39%. Suggested is 73% NBA, at
    +3.41%.
- **Per sport: FALSIFIED.**

| sport | suggested games | suggested | published | |
|---|---|---|---|---|
| NBA | 206 | -3.20% | -1.16% | falsifying |
| NCAAB | 458 | -8.95% | -4.66% | falsifying |
| NCAAF | 216 | +5.81% | -4.48% | holds |
| NHL | 183 | -1.84% | -11.47% | holds |
| Soccer | 218 | -2.92% | -34.80% | holds |
| NFL | 57 | -2.61% | -5.29% | below the 60-game bar |

**What NBA says.** NBA's published lines carried -3.98% market EV and realised -1.16%: 2.8 points better than the
price-vs-fair said. Its suggested lines carried +3.42% and realised -3.20%: 6.6 points worse. The +2% market-EV flag
picks the NBA lines where the board's fair is most wrong, and 93% of them are live. That is a lead about the fair on
individual live and alt lines, not a reason to stop suggesting NBA. It also matches what the 11-02 grade saw on a
smaller window: NBA -2.1% per bet.

## 5. Why staked is not "suggested, but staked"

The paper book stakes only suggested rows, yet the scorecard's staked set reads +2.69% and this set -3.02%. The two
sets differ on five counts, so the gap is not a measurement of the portfolio's selection:
1. **Population:** staked comes from every build; this set only from first-of-day sightings (§2's missing half).
2. **Price:** staked is graded at the fill; this set at the recorded price of the first suggested sighting.
3. **Settlement:** staked is graded by the execution ledger's outcome; this set by the scorecard's grader.
4. **Weighting:** staked counts one unit per order under the alt-ladder stake cap; this set one unit per rung.
   Ladders once moves the set from -3.02% to -1.8%.
5. **Window:** staked is keyed on the order's board date (`selected_date`, today included); this set on the kickoff
   date.

Which of these carries the 5.7 points is not measured here. §2's recorder change removes (1). Joining the orders to
these rows would separate (2)-(4).

## 6. The output, and how it should be refreshed (the user's call)

**Files** (`~/syndicate-prod/data/reports/suggested_set/`; nothing reads them for betting):
- `suggested_set_latest.json` (3.0 MB), plus a dated copy `suggested_set_<YYYYMMDD>.json` (kept 14 days).
- `suggested_set_state.json` (7.7 MB): graded rows by identity.

**Row shape.** Each row is the rail monitor's board-results row plus fields:
- `id, day, sport, set ("Suggested by the board"), bets, games, roi_pct, predicted_ev_pct, market_ev_pct`;
- `sport_key, season_phase, scope (sport | all | market | state), market, state, window (28d | 1d), window_first,
  window_last`;
- `wins, hit_pct, units, roi_ci95_lo_pct, roi_ci95_hi_pct, ladders, ladder_roi_pct, model_bets, model_roi_pct,
  sim_ev_pct, sim_bets, sim_roi_pct, market_ev_bets`.

A sport's regular-season 28-day row has the monitor's own id, `<day>|<sport>|Suggested by the board`. On 11-18 there
are 4,945 rows: 28d (sport 302, all 36, market 2,467, state 587) and 1d (sport 175, all 36, market 1,025, state 317).
A row's `games` is the set's own games; the monitor's other sets carry the sport's window total.

**Cost, measured on the fleet:**
- First run (empty state): ~4 min.
- An incremental run (state loaded, everything reused, 148 retried): 21-24 s wall and 323 MB peak RSS.
- Reads: the recorder scan, the public scoreboard on web (127.0.0.1:10000) once per new kickoff date, and
  statsapi / ESPN / NHL box scores for newly settled games (the scorecard's own sources). **0 OddsAPI calls.**
- Two consecutive runs give identical intervals. Games are put in a fixed order before the seeded bootstrap; an
  earlier run differed by 0.1 point before that fix.

**LOADED 11-18 10:57 PM CST (user "Yes, go ahead"): option A.**
- **The task:** `SyndicateSuggestedSet`, daily at 7:15 AM local, Interactive / Limited, priority 7, 1 h limit, start
  when available. It runs `conhost.exe --headless wsl.exe -d Ubuntu-24.04 -- bash
  /mnt/c/SyndicateProd/suggested_set/run_suggested_set.sh`, a copy of `scripts/run_suggested_set_daily.sh`.
- **The script:** it runs the grader from `~/Syndicate` at nice 19 with `--cache-dir ~/.cache/syndicate_suggested_set`
  (seeded from the hand runs' cache).
  - It logs `=== start <UTC> head=<sha>` and `=== end <UTC> rc=<n>` to `~/syndicate-prod/logs/suggested_set.log`.
  - It exits with the grader's code, so the task's result is the grader's exit.
- **Why a script file and not the inline command below.** The first test ran the inline form, and its `$(...)` and
  `$rc` expanded at the wsl.exe hop: `head=` and `rc=` came out empty, so a failed grade would still have read result 0.
- **Test run 04:57:49Z..04:58:22Z:** `head=199d6c529`, `rc=0`, task result 0, the same 4,945 rows and day-11-18
  numbers as the 6:07 PM hand run.

The options as they were put to the user:
- **A. A scheduled read (recommended).** A Windows task `SyndicateSuggestedSet` at ~7:15 AM CT, after the 5:30 AM CT
  scorecard. It has the same shape as `SyndicateCheatSheetPicks`:
  `conhost.exe --headless wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/Syndicate && nice -n 19
  ~/.venvs/syndicate/bin/python scripts/grade_suggested_set.py --data-root /home/amyn/syndicate-prod/data --write
  --cache-dir ~/.cache/syndicate_suggested_set >> ~/syndicate-prod/logs/suggested_set.log 2>&1"`.
  It needs the script in the fleet checkout, i.e. a fleet ff. An ff ships all of main; it is a deploy under the
  guard, though this script itself is not a betting change.
- **B. A hook in the scorecard cron** behind a `--suggested on|off` switch. Not recommended. It couples a reporting
  job to the scorecard's publish path, which refuses on its own failures, and it adds the same ~25 s there.

## 7. Follow-ups

- **BUILT 2026-11-18 (user "Yes, go ahead"):** `199d6c529`, on main, default ON, off switch
  `SYNDICATE_OPPORTUNITY_POPULATION_SUGGESTED_SIGHTING=off`. 4 new tests, plus 291 tests of the recorder's readers.
  **LOADED 04:46:47Z 11-19 (10:46 PM CST 11-18):** a fleet ff `a3104a5b6 -> 199d6c529` at 04:46:22Z, then a TERM of
  the board CHILD only, under a drain.
  - The recorder runs only in `pipeline.board_build_process --serve`; the refresh-worker parent was not restarted.
  - 13 of 13 POPULATION lines read `suggested_sighting=on`, and `suggested_pending` summed to 95.
  - 103 `sg=true` records and 103 `#sg` sidecar keys on disk.
  - `deploys.md` entry 2026-11-19 04:46:22Z. The original plan follows.
- **The recorder's missing half (§2).** In `opportunity_population_ledger.record_population`, write a second record
  the first time a line is seen suggested on a board date, under a `#sg` sidecar suffix, the way `#live` works.
  - Every earliest-sighting reader keeps its row, because the new record is later. So the scorecard, the optimizer
    and `grade_population` are unchanged.
  - This grade would pick the record up with no change.
  - It costs a few hundred records a day. It is worker code, so loading it needs a refresh-worker restart, which is
    the user's call. It is not a betting change.
- **NBA live and alt lines, NCAAB live game lines, NHL live (§3, §4).** The flag selects lines whose realised return
  is far below their price-vs-fair. That points at the fair on those individual lines.
- **The staked gap (§5).** Join the paper orders to these rows.

**Todo `#846` is NOT written.** `docs/ai_context/todo.md` is claimed by the OPEN lane `wnba-native-live-cutover`
(guard source origin/main@9e233a9c), and lane-guard blocks a cross-lane edit. The three owed items above are this
entry, for whoever can write it: (1) the daily refresh, (2) the recorder `#sg` record, (3) the orders join. The
entry was to be `#846`, checked free in both todo files at about 6:11 PM CST. **(1) and (2) are DONE as of 11-18
~11:00 PM CST.** **CORRECTION (11:00 PM CST):** `#846` has since been taken, by lane `product-optimization-program`
(the ranked lever table, which already lists this suggested set as an input). So (3), the orders join, and the
per-line follow-ups above are owed here with no todo number of their own.

## Scripts and outputs

- Grader: `scripts/grade_suggested_set.py`, tests `tests/test_grade_suggested_set.py` (20).
  `score_ranking_backtest.graded_row` now also carries `k`, `p_market`, `p_model` and `price`.
- Coverage, blind spot and comparison (read-only, scratch): `C:\tmp\sgset_1118\coverage.py` / `coverage.json`,
  `gap.py` / `gap.json`, `compare.py` / `compare.json`, `ebcheck.py`.
- Logs: `repro.log` (5:57 PM), `full.log` (6:03 PM), `incr.log` (the last run, 6:07 PM; its outputs are the ones
  on the fleet).

## 8. Coverage after the #sg fix (reading 2026-11-20)

Scheduled task `suggested-set-coverage-1120`, read-only, run 11-20 ~7:45 AM CST. Command (nice 19, on the fleet):
`gap_coverage.py /home/amyn/Syndicate /mnt/c/SyndicateProd/suggested_set/gap_after_fix_20261120.json`. The recorder
held 723 keys, 424 of them `sg=true`.

**Pre-registered bar (board date 2026-11-19 only).** Share = recorder_sg_true / suggested at the day's last build:
MET: share >= 95%, and not_recorded <= 1. PARTIAL: share 80-95%. NOT MET: share < 80%.

**Verdict: MET.** 2026-11-19: 28 of 28 suggested lines have an `sg=true` record (100%); 0 sg_false_only, 0
not_recorded (phases: 25 pregame, 3 live).

| board date | suggested | sg_true | sg_false_only | not_recorded | share |
|---|---|---|---|---|---|
| 2026-11-19 (first full day on the fix) | 28 | 28 | 0 | 0 | 100% |
| 2026-11-18 (partial day; builds before 04:46:47Z 11-19 ran old code) | 22 | 22 | 0 | 0 | 100% |
| 10-23..11-17, pre-fix (section 2, `gap_before_fix_20261118.json`) | 610 | 304 | | | 49.8% |
| 10-23..11-17, same window re-read today | 610 | 305 | 303 | 2 | 50.0% |

The pre-fix window does not move (305 of 610 today vs 304 of 610 on 11-18), as expected: the fix writes no
history. 11-20 (111 of 111) and 11-21 (28 of 28) are open board dates, not judged.

**Closed-day check.** The 11-19 decision record's mtime is 2026-11-20 05:52:20Z (11:52 PM CST 11-19), which is
8 minutes BEFORE the 06:00Z bound the check named. It had not changed by 13:46Z, so no build wrote to that date
after midnight CST; I read the day as closed, but say so here because the stated check did not pass literally.

**Step 2 diagnosis:** not run (MET).

**11-20 7:15 AM grade run** (`~/syndicate-prod/logs/suggested_set.log`): `=== start 2026-11-20T13:15:01Z
head=38c3a6905` / `=== end 2026-11-20T13:15:48Z rc=0`; `START today_central=2026-11-20`, 556 files
2026-10-13..2026-11-21. `LATEST 2026-11-20|all|Suggested by the board`: 14,661 bets / 1,418 games, ROI -1.68%
[-3.96, +0.53], market EV 3.42%.
