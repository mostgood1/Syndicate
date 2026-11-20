# Layer 2 Games Rail: the always-on monitor (runbook)

**The user said, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward".** The rail monitor runs every day without asking. Each day it opens itself, reads through the slate, and closes itself (grade, summary, page). Lane `layer2-rail-monitor`; worktree `C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a`.

Rules carried from the lane (never relax them):
- Read-only on the fleet, nice 19. ASK THE USER before loading anything or killing any process.
- Never use Render. Production is http://127.0.0.1:10000.
- Every line is its own decision: no band or market gates. A weak slice is evidence for per-line calibration.
- Never chain `git add` and `git commit`. Run `git merge --ff-only origin/main` before committing.
- Report in Central time. Quote the user's words exactly. Never relay my own button labels as decisions.
- Loads belong to the lane that built the change. I relay the user's words; I don't load.

## Daily schedule (CST)

| when | step |
|---|---|
| 10:30 AM (cron) | **DAY START**: morning upkeep, the day's findings file with a PRE-REGISTERED block, the lane STATUS, reading 1 |
| until 5:30 PM | readings every 30-40 min (sooner if anomalies) |
| 5:30 PM to the last game | readings every 20-25 min (the evening board and live odds) |
| last game final | **NIGHTLY CLOSE**: grade, summary, page, checkpoint. Then no wakeup until the next 10:30 AM cron |

If the slate's first game is later than 12 PM, reading 1 can be the slate check and the loop can sleep until ~30 min before it.

## DAY START (date D = today CT)

1. **Clock and inputs:**
   - `ReadNotifications`;
   - fleet head and recent loads (`wsl -- bash /mnt/c/tmp/railmon/fstate2.sh | head -6`, plus `git show origin/main:.syndicate/deploys.md` entries since the last close);
   - read `.syndicate/state.md` and lanes;
   - `git merge --ff-only origin/main`.
2. **Morning upkeep (dashboard history):**
   - Scorecard results: `wsl -- nice -n 19 python3 /mnt/c/tmp/railmon/dash/perf_series.py > C:\tmp\railmon\dash\perf_series_raw.json`.
   - Suggested set: `wsl -- nice -n 19 python3 /mnt/c/tmp/railmon/dash/sug_series.py > C:\tmp\railmon\dash\sug_raw.json` (refreshed daily at 7:15 AM by its task).
   - `py -3 C:\tmp\railmon\dash\perf_build.py`.
   - Cheat sheets: `wsl -- nice -n 19 python3 /mnt/c/tmp/railmon/dash/cs_series.py > C:\tmp\railmon\dash\cs_raw.json`, then split into `cheat_sections.json` / `cheat_history.json` (see `d4_start_notes.md`).
   - Upload the changed files as assets and update `datasets/board_results`, `cheat_sections` and `cheat_history`, each pinned by `if_version`. If a version is unknown, read it first with `ArtifactData get`.
3. **Findings file** `.syndicate/findings_<D>_layer2_rail_monitor.md`:
   - a header with the user's always-on quote and the starting state (fleet head; what loaded since the last close, from deploys.md);
   - a **PRE-REGISTERED block written before the day's first game**, with the standing predictions below plus any day-specific ones for new loads. The population is games commencing after the pre-registration push time (POP_START, UTC).
   - Commit and push before the first game.
4. **Lane STATUS:** rewrite the `- STATUS ...` line of `layer2-rail-monitor` in `.syndicate/lanes.md` with the safe pattern:
   - strip and re-add a trailing `\r`;
   - assert no lone `\r`;
   - write a `.tmp` file, then `os.replace` with a retry loop.
   - Example: `C:\tmp\railmon\d4status_close.py`.
5. **Dashboard day reset:** new readings go to `C:\tmp\railmon\dash\rows_<D>.jsonl` via `--day <D>`; the dashboard's Readings dataset shows the current day.
6. **Reading 1** (full page), then the loop.

### Standing predictions (carry each day; grade at the close)

- **P1:** 0 rail-card contradictions ("ours" across the flagged line at model P > 0.5). The card fix has been live since 11-18 10:59 PM.
- **P2 (board cadence):** over 5:30-10:30 PM, today-board publication gap median <= 600 s and no gap > 1,800 s.
  - Until #850's memory fix or the split rollback loads, expect the memory-guard recycles (11-18: 7) and report them.
- **P3:** first-reading flags hit at or below their fair (the 11-18 result was within noise; keep collecting).
- **P4:** long-shot flags (book fair < 0.40) hit at most fair + 2 pp. This is evidence for per-line calibration (#847), never a gate.
- **P5 (report):** NCAAB calibrated live full totals: hit vs fair, the side mix, and the flagged lines' over share.
- **P6:** 0 pregame NCAAB / WNCAAB totals flags (BC-048).
- Add P7 / P8+ for whatever loaded since the last close, copying the owner's registered prediction.

## EACH READING (N = the day's next number)

From the worktree, in parallel:
- the probe `py -3 scripts/layer2_rail_monitor_probe.py [--no-page] --log-minutes 40 > /c/tmp/railmon/d<D>r<N>_probe.txt` (full page every 4th reading);
- `wsl -- nice -n 19 python3 /mnt/c/tmp/railmon/dash/d4metrics.py <prev Z> <D> > /c/tmp/railmon/dash/m_<D>_<N>.json`;
- `wsl -- nice -n 19 bash /mnt/c/tmp/railmon/d4mem.sh <prev Z>` (`[board_process]`, `RECYCLE_EXIT`, `MEMORY_GUARD_ABORT`, fleet head).

Then:
- `py -3 C:\tmp\railmon\dash\dash_update.py row --n N --day <D> --probe ... --metrics ... --dir <newest readings dir> --note "..."`, THEN `py -3 dash_update.py build --day <D>`. **Always build before uploading.**
- Upload `readings.json` (and `findings.json` / `loads.json` / `levers.json` if changed), then update the datasets, pinned by `if_version`.
- Check:
  - flags: false, missed, dark;
  - P1 (`ours_contradictions`) and #824 (`ours_below_points`);
  - the score floor (`floor_violations`, owned reading R-A) and, while NCAAB is live, the #844 sampler (R-B);
  - on NHL days, the NHL timeout watcher `p838_watch.py <prev Z>` (R-E);
  - `live_games_no_model`: live games whose full-game rail rows carry no live model at all (I-29, added 11-19). A game can lack a model before its first re-sim, so confirm on the next reading. If it persists, `lgb.py <sport> <since>` shows the join's `withheld_by_reason`;
  - P6;
  - overlay gaps over 360 s and stale web merges;
  - board publication gaps and the memory guard;
  - sweeps refused;
  - NHL odds child age over 600 s;
  - team cards;
  - new fleet loads (add them to `loads.json`).
- Hunt improvements: each gets evidence plus an owner. Unowned large ones get a session card (at most 3 a turn).
- Write `C:\tmp\railmon\d<D>r<N>_block.md` FIRST, append it to the findings file, verify it landed, then commit and push with the conflict-safe loop:

  ```
  for i in 1 2 3 4; do git fetch -q origin; if ! git rebase -q origin/main; then git rebase --abort; echo REBASE_CONFLICT; break; fi; if git push -q origin HEAD:main 2>/dev/null; then echo pushed; break; fi; sleep 3; done
  ```

- Then `ScheduleWakeup` for the next reading.

## OWNED READINGS (handed over 11-19 by lane ncaab-total-overprojection; the user said "Yes, consolidate")

These two readings now belong to this monitor. The lane's findings: `.syndicate/findings_2026-11-16_ncaab_total_overprojection.md` and `.syndicate/findings_2026-11-18_college_quote_age_text_max.md`.

**R-A. I-17 score floor (`d78a448c4`).**
- What it measures: college (NCAAB / WNCAAB) full-game totals rows on the live rail with `live_total_basis: calibrated` whose `live_total` is below the points already scored (chip home + away).
- Built into every reading: `dash_update.py row` writes `floor_calibrated_rows`, `floor_violations` and up to 3 `floor_examples`.
- Prediction: **0 violations** once the refresh-worker PARENT has `d78a448c4`, i.e. after the memory-guard session's full down/up (planned 11-19 11:15 AM to noon; confirm it in deploys.md and add it to `loads.json`). Before that restart, violations are expected (11-18 r16: 11 of 262).
- If any appear after the restart: send the game, the row's line, side and quote age, and the score to lane `ncaab-total-overprojection` (append to its findings file; message its session only if it is still open).

**R-B. #844 newest-stamp-by-time (`25a5e480d`, default off; CHANGE D in the 11-24 2:15 AM betting-change batch).**
- Instrument: `C:\tmp\railmon\p844_grid_sample.py` (a copy of `C:\tmp\ncal816\p844_grid_sample.py`). Wrapper, NCAAB then NBA, appending to `C:\tmp\railmon\p844_<D>.jsonl`:
  `wsl -- nice -n 19 bash /mnt/c/tmp/railmon/p844.sh <D>`
  It prints `rows`, `venue_rows`, `p1_sportsbook_newest`, `h2h`, `h2h_row_fresh`, `h2h_cell_fresh`, `mismatch`.
- **11-19 evening (baseline):** run at every reading while NCAAB is live. Expected: `mismatch` > 0, and `h2h_row_fresh` well below `h2h_cell_fresh`.
- **11-24 evening (only if CHANGE D loaded in the window; check deploys.md):** grade
  - P1: `p1_sportsbook_newest` > 0;
  - P2: `h2h_row_fresh / h2h` >= 70% across the evening's samples, close to `h2h_cell_fresh`;
  - P3: NBA / NHL grids unchanged (`nba` mismatch 0 on both nights);
  - P4: NCAAB `stale_quote` refusals per build fall versus 11-19.
- Write the verdict to `findings_2026-11-18_college_quote_age_text_max.md`, a deploys.md READING entry, and todo #844.

**R-C. Suggested-set coverage check (from the archived session local_fbe07d8c).** The one-off scheduled task `suggested-set-coverage-1120` runs Fri 11-20 at 7:45 AM CST. At the 11-20 DAY START, read its run result (`list_task_runs`) and put the outcome in that day's findings file.

**R-D. #851: the Polymarket slate sweep runs off the live-odds main loop (`8f0d73a2e`, default off; CHANGE E, droppable, of the 11-24 2:15 AM batch task `nfl-level-refit-load-1120`).** Taken over 11-19 from session local_73a5d2dd (lane `polymarket-slate-off-odds-loop`). The user answered "Yes, take it" to "Should the monitor take #851's 11-24 reading so its session can be archived?".
- First check deploys.md for the 11-24 batch: did CHANGE E load (`LIVE_ODDS_WORKER__SYNDICATE_POLYMARKET_SLATE_MAIN_LOOP_BACKGROUND=1` in `local_production.env`, then a drained full down/up)? If E did not load, there is no reading; it waits for the 12-08 window.
- The window is the first live evening after the load: 00-05Z on UTC date 2026-11-25 (11-24, 6-11 PM CST). Read it after 05:00Z (11 PM CST):
  `wsl -- bash -c "cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p851_loopstages.py 2026-11-25"`
  - The reader is the lane's `C:\tmp\w1124_851\loopstages.py` with the window taken from argv, plus P2 and P4 lines; it is rebuilt by `make_p851.py`.
  - Baseline, reproduced exactly on 11-19 for 11-16..11-19: 482 iterations, p50 100 s, p90 299 s, 138 over 180 s, 117 slow iterations carrying a slate write. Output: `C:\tmp\railmon\p851_baseline_1116_1119.txt`.
- Predictions, registered by the lane before the build (todo #851):
  - P1: iteration p90 <= 200 s (was 299 s), and <= 12% of iterations over 180 s (was 29%);
  - P2: odds-sweep attempt gap p90 <= 200 s (the `#851 P2` lines; NCAAB was p90 299 s);
  - P3: slate write gap p50 within 173 s +-20% (139-208 s);
  - P4: 0 `POLYMARKET_ARTIFACT_STALE`;
  - P5: 0 slow iterations (post > 120 s) where the slate is the larger part (was 117).
- Each is PREDICTED, FALSIFIED or NEITHER. Name any restart in the window (it CONFOUNDS the reading). Write the verdict to the lane `polymarket-slate-off-odds-loop`, a deploys.md READING entry, and todo #851.

**R-E. #838 slow-NHL-API case (lane `odds-lane-sport-deadline`, OPEN, goal not met until this is read).** Taken over 11-19 from session local_73a5d2dd (handover on main `ab4877f6e`; the user's "keep it open" from 11-19 still stands).
- **Trigger:** the first NHL odds rebuild that hits its time limit (900 s). That is a manifest step `nhl_live_generation` / `nhl_pregame_generation` with `timed_out: true`, or `data/nhl_source/data/processed/.nhl_live_generation_timeout_<date>.json` on the fleet. Before 11-19 none had happened: 11-18 6-11 PM had 8 of 8 rebuilds OK, at 169-299 s. The stats cache (`59fbefc71`) may make a timeout rare.
- **Watch at every reading on a day with NHL:**
  `wsl -- bash -c "cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p838_watch.py <prev Z>"`
  It prints `nhl_steps`, `nhl_timed_out` (with the run, step, start and seconds), `markers` and `cooldown_lines`. Test from 11-18 00Z: 67 steps, 0 timed out.
- **When it fires,** grade the window around the timeout with the lane's reader:
  `wsl -- bash -c "cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/odds_lane_838/livewin.py <W0> <W1> <slate>"`
  `puckdrop.py` and `gap0022.py` are beside it. The checks:
  - the longest live odds run <= 1,200 s;
  - `lane_busy` refusals <= 50% of `ODDS_SWEEP_LAUNCHED` attempts (11-17 baseline: 23 of 26);
  - after the timeout, NHL sweeps run fast-only for 1,800 s (`NHL_LIVE_GENERATION_COOLDOWN`, the fallback);
  - in-game NHL rows are not stuck at 0-5 for longer than one hold;
  - NHL odds age <= ~1,200 s, **measured from the actual first puck drop** (the ESPN state flip in `C:\tmp\inplay_<date>\espn.jsonl`), not the scheduled start. The owner's 11-18 reading got this wrong; see the deploys.md correction at 2026-11-19 14:15Z.
- **Write the verdict** to the lane `odds-lane-sport-deadline`, a deploys.md READING entry, and todo #838. A MET verdict closes the lane's goal; closing the lane is the user's call.

**R-F. #850 repeat evening (lane `board-split-memory-guard`, session local_d0f83044; 11-19 reading recorded on main `c09c4e835`, verdict P1 NEITHER / P2 PREDICTED / P3 PREDICTED, CONFOUNDED by the slate).**
- Owed: the same §5 thresholds (`.syndicate/findings_2026-11-18_board_split_memory_guard.md` §5) on the next evening that has:
  - at least **33 live NCAAB+NBA+NHL+NFL games at 7 PM CST** (count the live chips by sport at the ~7 PM reading);
  - **no refresh-worker restart, drain or deploy in 5-10 PM**.
  Fri 11-20 and Sat 11-21 look likely.
- How: after 10 PM, run `wsl -- bash -c "cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p7count.py <D>T23:00:00 <D+1>T04:00:00"`, with the window in UTC. Grade each part:
  - P1: `MEMORY_GUARD_ABORT` <= 1 every hour and <= 3 total; falsified if > 2 in an hour or > 6 total.
  - P2: <= 2 exits, all rc 75; falsified on any rc -6 or `Fatal Python error`.
  - P3: longest `BOARD_BUILD_TIMING` gap <= 900 s; falsified if > 1,200 s.
  Also record the exploratory numbers: parent and child RSS, and `held=transient_jobs` post-build checks.
- Write it in the day's findings, send the numbers to local_d0f83044 (or its lane if the session is gone), then drop this item.

## NIGHTLY CLOSE

1. The probe shows 0 live games. **Fetch day D's finals by date:**
   `curl -s "http://127.0.0.1:10000/api/board/game-chips?sports=mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,wncaab,soccer&date=<D>" -o C:\tmp\railmon\final_<D>\chips.json`.
   After midnight the probe's own chips roll to D+1.
2. **Grade:**
   `py -3 C:\tmp\railmon\grade_day.py C:\tmp\railmon\final_<D>\chips.json --day <D> --pop-start <POP_START> --json C:\tmp\railmon\grade_<D>_out.json`.
3. `py -3 C:\tmp\railmon\dash\perf_build.py` (it picks up `grade_<D>_out.json`), then upload `rail_results.json` and update `datasets/rail_results`.
4. **Daily summary** in the findings file:
   - the grade table and verdicts (P1-P6, plus day-specific);
   - anomalies;
   - loads;
   - sessions and improvements;
   - open user decisions.
5. **Page** "Rail Watch, <Day Mon D>":
   - copy `C:\tmp\railmon\build_page_1118.py` plus `page_1118_body.html`;
   - write the body by hand from the summary;
   - the chart data comes from `rows_<D>.jsonl`;
   - publish with the Artifact tool (icon chart), linking the live dashboard.
6. **Checkpoint:** a log entry in `.syndicate/log/<date>.md`, the lane STATUS, then commit and push. **Do not ask about tomorrow: the monitor is always on.** Schedule nothing; the 10:30 AM cron starts the next day.

## Where things are

- **Repo backup of this runbook and scripts:** `scripts/rail_monitor/` on main.
- **Live dashboard:** https://claude.ai/artifact/HoJ2n52ewHZnVDbN2LpxaJ. It is a Dashboard type; the datasets are uploaded JSON files.
  - Datasets: `readings`, `findings`, `loads`, `rail_results`, `board_results`, `cheat_sections`, `cheat_history`, `levers`.
  - Page code is in `files/index.html` (source `C:\tmp\railmon\dash\index.html`). Re-read the stored copy before changing it.
- **Notes from 11-18:** `C:\tmp\railmon\d4_start_notes.md`.
- **Day pages:** 11-17 HBPdAGfJxCjGcAF76iNx2f; 11-18 ESGaWMYhR7JH6EWfeqiViY.
- **Open user decisions (11-19):** the board-split rollback vs #850's memory fix (local_d0f83044); closing the NHL props lane (local_ce6ce550).
