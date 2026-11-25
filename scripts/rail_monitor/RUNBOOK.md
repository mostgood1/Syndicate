# Layer 2 Games Rail: the always-on monitor (runbook)

**The user said, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward".** The rail monitor runs every day without asking. Each day it opens itself, reads through the slate, and closes itself (grade, summary, page). Lane `layer2-rail-monitor`; worktree `C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a`.

Rules carried from the lane (never relax them):
- Read-only on the fleet, nice 19. ASK THE USER before loading anything or killing any process.
- Never use Render. Production is http://127.0.0.1:10000.
- Every line is its own decision: no band or market gates. A weak slice is evidence for per-line calibration.
- Never chain `git add` and `git commit`. Run `git merge --ff-only origin/main` before committing.
- Report in Central time. Quote the user's words exactly. Never relay my own button labels as decisions.
- Loads belong to the lane that built the change. I relay the user's words; I don't load.

## LEAN MODE (from 11-20; supersedes the schedule below)

The user asked on 11-20 to "make this dashboard self contained so it doesnt use up ccredits". The answers: "Nightly close only" and "Page on the fleet app".

- **Readings, without Claude:** the Windows task `SyndicateRailWatch` runs `pythonw C:\tmp\railmon\railwatch\tick.py` every 20 min, 10:03 AM to 2:03 AM CST (Interactive, priority 7, IgnoreNew, 15-min limit).
  - Each tick is read-only: the probe (`--no-page`), `d4metrics.py`, `p7count.py`, `p29_orient.py` and `ps` of the refresh-worker processes.
  - Each tick writes: a row to `dash\rows_<D>.jsonl` (via `dash_update.py`); `railwatch\extra_<D>.jsonl` (memory guard, process RSS, college games' orientation); a log line to `railwatch\tick.log`.
  - It then renders `railwatch\index.html` and copies it to `~/syndicate-prod/data/reports/rail_watch/index.html`.
  - It drops `query.json` (~23 MB) from reading dirs after 6 h, and whole reading dirs after 10 days.
  - The slate day D rolls at 5 AM CST. Run it by hand with `py -3 C:\tmp\railmon\railwatch\tick.py --force` (or `--render-only`).
- **The page:** open `C:\tmp\railmon\railwatch\index.html` on this PC.
  - The fleet route (a small web route serving the data-root copy, LAN-reachable) lands and deploys AFTER the 11-24 2:15 AM window batch. Its ride-along gate STOPS the batch on any "(c) changes what a role does" commit, so the route must not be on main before the batch runs.
  - The claude.ai dashboard (HoJ2n52ewHZnVDbN2LpxaJ) is frozen at 11-19.
- **Claude, once a night:** the session cron `NIGHTLY CLOSE (lean)` at ~12:47 AM CST. Its steps:
  - check the tick log;
  - finals by date; `grade_day.py --pop-start <D>T16:00`; `perf_build.py` and a `tick.py --render-only`;
  - P1-P6/P8 from the day's rows, P2 from the log with `wsl -- bash -c "cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p2_boardpub.py <D>T23:30 <D+1>T04:30"`. Do not use `d4metrics` for this: after midnight its tail read under-covers the evening and still says `log_window_covered: true` (11-20: 9 builds and 0 sweeps, against 47 publications and 126 sweep launches);
  - when P8 (score floor) is non-zero, look at the chip's `status_token` and `intervals.final`. A re-sim whose own final total sits below the chip's score is older than that score: timing, not the floor (11-20: all 21 rows were in the last 40 s of regulation) A price grid's score can also lag the chip the rail reads: refresh-worker builds its own chips (30 s cache, up to 300 s stale while another build runs), so a grid NEWER than the chip artifact can still hold an older score (11-22 R36 Tenn-Martin @ Utah Valley: grid 03:42:28Z saw <=152, chip published 03:41:32Z had 153). `floor_examples`' age is the BOOK QUOTE's, not the model's. Whether such a row was bet: `live_bets_for.py <event_id|team>` (Windows py -3, ops token, never printed);
  - grade with output to a file, never through `| Select-Object -First N`. Cutting the pipe killed `grade_day.py` before it wrote its JSON (11-20: a 0-byte file);
  - the owned readings due that night (R-A..R-F);
  - a short summary in the findings file and a log line, then commit and push.
  - No day page, no claude.ai uploads, no wakeups. Renew the cron before its 7-day expiry. **The current cron 02eeea6d was created 11-20 17:16Z and expires 11-27 17:16Z: re-create it (same prompt, `47 0 * * *`) at the 11-26 close (D = 11-25).**
  - **#851 P6 sweep counts (night 2 on 11-21, then 11-24):** count on the exact quota-read window with `wsl -- bash -c "cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p851_sweepcount.py <lo> <hi>"`, where lo and hi are the two `read_at` values without the Z. Append to that night's findings file, as on 11-20.
  - **R-F's qualifier:** count the live chips by sport (`state == "live"`) in the ~7 PM reading dir's `chips.json`. The 11-20 evening was borderline (26 at 7:03 PM, 37 at 7:23 PM); its owner decides.
- **Still Claude-driven one-shots:** R-D P6 quota reads (6 PM and 11 PM CST, 11-20, 11-21 and 11-24) and R-F's parent-floor read (9:04 AM 11-21).

## Daily schedule (CST) — the full mode, used 11-15..11-19

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
  - P1 (`ours_contradictions`) and #824 (`ours_below_points`). From 11-22 7:03 PM (R28), a flag whose card OURS equals the flagged row's OWN `live_total` (within 0.05) is counted in `ours_skew_consistent`, not as a contradiction. There the mean and p come from one distribution, and a skewed end game puts them on opposite sides of the line (R27 Rice @ Lamar u167.5 p=0.69, mean 167.69). An OURS taken from another row (11-18's real defect) still counts. From 11-25 4:32 PM (after R20), a flag whose OURS is the chip's live re-sim final while the flagged row's own `live_total` sits on the flagged side is counted in `ours_resim_tick` (two ticks of one re-sim, see the section at the end), not as a contradiction;
  - the score floor (`floor_violations`, owned reading R-A) and, while NCAAB is live, the #844 sampler (R-B);
  - (R-E's NHL timeout watcher is retired as of 11-20);
  - `live_games_no_model`: live games whose full-game rail rows carry no live model at all (I-29, added 11-19). A game can lack a model before its first re-sim, so confirm on the next reading. From the 11-21 2:03 PM tick on, each row also carries `live_games_no_model_reasons` {game: reason} and `live_games_no_model_detail`, from `p29_orient.py` (now every sport with a per-game snapshot: ncaab, wncaab, nba, ncaaf, nhl, nfl, and soccer's live lens). For `not_in_resim`, the detail gives the snapshot's `generatedAt`, so a game that started after the snapshot shows as such. At 2:06 PM 11-21 the soccer lens was 21 min old and held only MLS and Eredivisie, while 7 European games were live. If that persists, the lens has stopped refreshing. **The cause (diagnosed 11-21; findings "Why the soccer live lens stalls at kickoff"):**
    - It is live-odds-worker's soccer lens memory gate (`LIVE_LENS_TICK_DIAG sport=soccer reason=low_headroom`), on the role's summed process-tree RSS against 3,072 MB.
    - It trips when the soccer live odds refresh stacks 2-3 runs at once, which happens with 5+ leagues in play, so at the European kickoffs.
    - To read it again: `soccer_gate_test.py <since_utc>` and `soccer_run_vs_leagues.py <date>`, both run in WSL from `~/syndicate-prod`. Deliberate fail-closed reasons (`key_player_out`, `game_final`, `regulation_over`, `in_intermission`) need no diagnosis. `orientation_reversed` is I-29. `resimmed_no_row_model` (3+ priced rows, none with a model) is a join defect. From 3:05 PM 11-21, 1-2 rows are labelled `resimmed_few_priced_rows` instead, because the join's per-line withholds explain them: a stale quote, or no distribution for that line (11-21 2:23 PM: Wake Forest @ Georgia Tech, 1 priced row). The page (full live rail) can list games the row (the probe's cut) does not. From 11-21 7:23 PM, NHL totals are left out of the priced rule; they are refused at the join by design, with no total distribution. From 11-22 1:03 PM (R10), NFL counts its full-game moneyline ONLY. NFL live totals and spreads are withheld by design: the re-sim publishes no total or margin distribution (`nfl/live_resim.py:714`, lane `nfl-live-distribution-grade`). 0 of 1,151 full-game NFL totals/spreads rows were modelled across the saved readings 11-15..11-22. The rule lives in `counts_as_priced` in both `p29_orient.py` and `dash_update.py`. An NFL game with no full-game moneyline row in a read drops off the list, including a `degenerate_ratings` refusal (BAL@CAR at R10). `no_snapshot_for_sport` was renamed `sport_absent_from_helper_read`: the helper's own rail read held no game of that sport, and its `{"rail": ...}` line says what that read held. A St. Louis Blues game never joins its live lane ("St. Louis" in the lens vs "St Louis" in the odds; findings 11-21 flag 4). That is known; do not re-flag it. From 11-22 6:03 PM (R25), `overlay_gap_max_s` and `overlay_gaps_over_360` leave out a sport's IDLE time: a gap that starts at a `rows_inplay=0` overlay line goes to `overlay_idle_gap_max_s` instead. R24's soccer 1,098 s was MLS between matches, one final about 23:22Z and the next kicking off about 23:41Z against a listed 23:30Z. To read a gap: `overlay_lines.py <sport> <lo> <hi>`, `soccer_live_window.py <lo> <hi>` (autorun launches and fixture cadence) and `soccer_live_state_peek.py <league> <date>` (the game clock), all in WSL from `~/syndicate-prod`. From 11-22 10:09 PM, overlay gaps are keyed on sport AND date (one overlay file each), the max gap names its date (`overlay_gap_max_date`), and `overlay_offdate_inplay` lists any sport@date OTHER than the slate day that published rows in play. The live rail reads only the slate day's overlay, so those rows never reach it. 11-22 R32-R36: Real Salt Lake @ Vancouver (MLS, 01:30Z kickoff) sat in the 11-23 grid, rebuilt every 13-16 min, with no live model (`LIVE_GAMELINE_BUILD ... index=0 considered=0`) and off the rail, while the 2-min autorun served 11-22. A gap spanning two windows is counted in neither (R35's 144 hid 962 s), so read `overlay_offdate_inplay` too. Readers: `grid_lines_for.py <sport> <date> <lo> <hi>`, `grid_game_states.py <sport> <date>`, `overlay_file_peek.py <sport> <date>`. `not_in_resim` may be the helper's own name miss, so check it. The fleet-watcher filters on this map.
  - `dark_rows` (from 11-21 3:03 PM: `dark_rows_detail`, the probe's sample of up to 6). A dark row would flag, but its quote age at pricing plus its price-grid age is over 300 s, so the flag is withheld. `reason`:
    - `board_cadence`: the row has no `price_grid_generated_at` (h2h, quarter-ball soccer lines, some alt / half lines), so it is aged from the board build (`grid_age_s` == `board_built_age_s`). It goes dark whenever the board is about 4 min old. 11-21 R14/R15: 12 of 12.
    - `grid_stale`: a grid-priced row whose grid is 300 s or more old. That is a cadence fault; look at `gridcad.py`.
    - `cadence_edge`: a grid-priced row whose quote was already 1-2 min old. If it persists, `lgb.py <sport> <since>` shows the join's `withheld_by_reason`. NCAAF has no `_LIVE_RESIM_TICK` line: its refusal counts are in refresh-worker's `NCAAF_LIVE_RESIM` summary, and per game in the `ncaaf_live_lens.json` keyvalue (`ncaaf_resim_peek.py <team> ...` prints `liveResimRefusal` and `playersOut`; 11-21: 3 of 3 dark NCAAF games were `key_player_out`);
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
- **INTERIM 11-25 1:10 AM CST (main `117737f83`):** D loaded. P1 PREDICTED on one sample (7 of 9), P4 NEITHER (`C:\tmp\railmon\p844_p4.py`; NCAAB stale share flat 37.4% -> 37.0%). P2/P3 OWED: the lean tick never ran the sampler on 11-24, so `tick.py` now runs `p844.sh <day>` at every tick for days <= 2026-11-26. **At the 11-25 close:** grade P2 (sum `h2h_row_fresh` / `h2h` over NCAAB samples with h2h > 0, beside `h2h_cell_fresh`; 11-19 baseline 31.2% vs 80.1%, mismatch 304 over 22 samples) and P3 (NBA mismatch 0) from `C:\tmp\railmon\p844_2026-11-25.jsonl`, then write the deploys.md READING ("- betting change: no"), the todo #844 verdict and the findings READING's final section.
- **11-24 evening (only if CHANGE D loaded in the window; check deploys.md):** grade
  - P1: `p1_sportsbook_newest` > 0;
  - P2: `h2h_row_fresh / h2h` >= 70% across the evening's samples, close to `h2h_cell_fresh`;
  - P3: NBA / NHL grids unchanged (`nba` mismatch 0 on both nights);
  - P4: NCAAB `stale_quote` refusals per build fall versus 11-19.
- Write the verdict to `findings_2026-11-18_college_quote_age_text_max.md`, a deploys.md READING entry, and todo #844.

**R-C. Suggested-set coverage check (from the archived session local_fbe07d8c).** The one-off scheduled task `suggested-set-coverage-1120` runs Fri 11-20 at 7:45 AM CST. At the 11-20 DAY START, read its run result (`list_task_runs`) and put the outcome in that day's findings file.

**R-D. #851: the Polymarket slate sweep runs off the live-odds main loop (`8f0d73a2e`, default off; CHANGE E, droppable, of the 11-24 2:15 AM batch task `nfl-level-refit-load-1120`).** Taken over 11-19 from session local_73a5d2dd (lane `polymarket-slate-off-odds-loop`). The user answered "Yes, take it" to "Should the monitor take #851's 11-24 reading so its session can be archived?".
- **DONE 11-24 11:00 PM CST: P1-P6 ALL PREDICTED** (main `c021089b3`, deploys.md 2026-11-25 05:00Z READING entry; lane closed). The nightly close skips R-D.
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
  - **P6 (OddsAPI credits), added 11-20 by local_73a5d2dd:** credits per hour over 00-05Z rise by no more than 30% against the baseline nights.
    - The user typed "Keep it in" to "Keep #851 in the 11-24 batch with that OddsAPI cost?" (~9:45 AM CST 11-20, recorded on main `e08a97034`).
    - The cost estimate is ~+24% evening sweeps, an upper bound of +0.24-0.4M credits a month. The month stays <= ~4.3M of the 5M cap; at 15:29Z 11-20 the projection was 3.94M for 30 days.
    - Method: `py -3 C:\tmp\railmon\p851_quota.py <label>` (run from the worktree) reads `quota.latest.used` from `/api/ops/oddsapi/quota` and appends to `C:\tmp\railmon\p851_quota.jsonl`. Read at 00:00Z and 05:00Z; credits per hour = delta / hours between reads.
    - Also report credits per lane sweep (ODDS_SWEEP_LAUNCHED in the window, from `p851_loopstages.py`), because slate size moves the raw rate.
    - Baseline: the 11-20 and 11-21 evenings. One-shot crons read at 6 PM and 11 PM CST both nights, and at 6 PM and 11 PM on 11-24.
- Each is PREDICTED, FALSIFIED or NEITHER. Name any restart in the window (it CONFOUNDS the reading). Write the verdict to the lane `polymarket-slate-off-odds-loop`, a deploys.md READING entry, and todo #851.

**R-E: RETIRED 11-20.** Lane `odds-lane-sport-deadline` closed with its goal NOT MET, because the slow-API case was never seen (main `c6d5d5d9c`, todo #838). The user said "yes to items 2 and 5", relayed by the fleet-watcher local_379fd729; item 2 was the close. Across 5,244 odds runs (11-18 13:47Z to 11-20 16:04Z), 0 steps hit a time limit, and the longest of 121 NHL rebuilds took 413 s against 900 s. No further watching. The original text follows for reference.

**R-E (historical). #838 slow-NHL-API case (lane `odds-lane-sport-deadline`).** Taken over 11-19 from session local_73a5d2dd (handover on main `ab4877f6e`; the user's "keep it open" from 11-19 still stands).
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

**R-F. DONE 11-25 1:10 AM CST: 11-24 qualified (38 core live at 7:03 PM, no refresh-worker restart 5-10 PM); P1/P2/P3 PREDICTED on change J's first evening; written to the lane's findings §20 (main `117737f83`). Dropped from the nightly close.** **#850 repeat evening (lane `board-split-memory-guard`, session local_d0f83044; 11-19 reading recorded on main `c09c4e835`, verdict P1 NEITHER / P2 PREDICTED / P3 PREDICTED, CONFOUNDED by the slate).**
- Owed: the same §5 thresholds (`.syndicate/findings_2026-11-18_board_split_memory_guard.md` §5) on the next evening that has:
  - at least **33 live NCAAB+NBA+NHL+NFL games at 7 PM CST** (count the live chips by sport at the ~7 PM reading);
  - **no refresh-worker restart, drain or deploy in 5-10 PM**.
  Fri 11-20 and Sat 11-21 look likely.
- How: after 10 PM, run `wsl -- bash -c "cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p7count.py <D>T23:00:00 <D+1>T04:00:00"`, with the window in UTC. Grade each part:
  - P1: `MEMORY_GUARD_ABORT` <= 1 every hour and <= 3 total; falsified if > 2 in an hour or > 6 total. Count `stage=pre_source_state_fingerprint` only, the `#850 P1` line of `p7count.py`. Its first total counts every stage (11-20: 15 vs 13).
  - P2: <= 2 exits, all rc 75; falsified on any rc -6 or `Fatal Python error`.
  - P3: longest `BOARD_BUILD_TIMING` gap <= 900 s; falsified if > 1,200 s.
  Also record the exploratory numbers: parent and child RSS, and `held=transient_jobs` post-build checks.
- **Exploratory, added 11-20 by the owner (findings §8, main `553c4bd3a`; it decides the next lever):**
  - parent (`run_refresh_worker.py`) RSS p50 at ~9 PM CST (take `ps` at the 8:45 / 9:10 / 9:35 PM readings);
  - parent RSS at ~9 AM CST the next morning (the floor). A one-shot cron takes it on 11-21.
  - `p7count.py` now prints `POST_BUILD_CHECK by held reason` and `BOARD_PROCESS_RECYCLE by reason`; report both, including any `reason=post_build_headroom`.
  - The owner's expectation, written before the evening: the pair crosses the line on its own, the post-build recycle fires (rc 75), and P2's "<= 2 recycles" is at risk.
  - If the 11-21 floor is >= 0.5 GB above 1,610 MB (the 11-20 9:28 AM floor), the parent ratchet is multi-day, and the owner puts a parent reset to the user.
  - State so far (11-20 9:30 AM): since the 17:00Z 11-19 load there have been 12 refusals, 1 exit (rc 75, 11:58 PM CST, after a refusal streak) and 0 real fatal errors (the 04:33Z "Fatal Python error" hits were grep command lines quoted in `ALL_PROCESS_MEMORY`). `held=transient_jobs` 11 of 11. Parent 1.65 GB.
- **11-23 parent reset** (session local_b98a3f85, deploys.md `## 2026-11-23T10:17:25Z`, bb05fdd59): the parent was at 1,789 MB p50 and got a claimed refresh-worker TERM at 4:17:25 AM CST; the new pid is 4109821 at 599-662 MB. That is outside 5-10 PM, so it does not disqualify 11-23. But if 11-23 qualifies, it is a FIRST evening on a fresh parent, not a repeat evening: say so beside the verdict.
- Write it in the day's findings, send the numbers to local_d0f83044 (or its lane if the session is gone), then drop this item. **local_d0f83044 was ARCHIVED 11-24 ~1:00 AM CST** (user "archive the optimizer and memory-guard sessions"), so a qualifying evening's numbers go to lane `board-split-memory-guard` (its findings file), not a message. 11-23 did not qualify (18 core live at 7:03 PM); parent 8-10 PM p50 1,994 MB on a 4:17 AM reset, the same evening level as 11-22.

**R-H. #860 St. Louis live join (CHANGE M of the 11-24 batch; user "Yes, add it" 11-23 8:07 AM CST, lane `nhl-live-join-stl-alias`).** M LOADED 11-24. No Blues game on 11-24; the first is STL @ NYI, 6:00 PM CT 11-25. A one-shot session cron (5c525964) runs the kit at 7:07 PM CST 11-25. If the batch loaded M (read its deploys.md entry), then at the first live St. Louis Blues game run `wsl -- bash /mnt/c/tmp/w1124_stl/kit_after_up_stl.sh` at nice 19. MET: St. Louis reads N of N moneyline + puck-line rows with a live model, like every other live NHL game (0 of 1 on 11-21). Write the result in the lane and the day's findings. On MET, closing the lane is the user's call. If the batch dropped M, it waits for 12-08.

**R-I. The monitor's page copy (main `bbbbb4b3f`, 11-23 ~2:30 PM CST; asked by session local_15f2d5e2 "Fix evening-MLS UTC/CT date split").** Until bbbbb4b3f, `--no-page` reused `readings\served.html` forever: the tick ran an 11-19 11:00 PM page copy for four days, so EVERY reading 11-20..11-23 (until the primary tree picked up bbbbb4b3f) ran 11-19 rail code. Say so in the 11-23 findings beside any rail verdict from those days. The runner also now keeps a list per canonical and exact chip key and picks on start, like the page (3983309ce). At the 11-23 close, check: (1) the primary tree holds bbbbb4b3f (`git -C C:\Users\tempadmin\Coding\Syndicate merge-base --is-ancestor bbbbb4b3f HEAD`); (2) the tick's newest probe summary shows `page_age_min` <= 60 and `page_fetch_error` null; (3) LAFC @ St. Louis City SC (401933728, 7 PM CST 11-23) was NOT in `chipless` once (1) held. A tick failing with "served page predates the list canonical index" means the refetch failed: read `page_fetch_error`. **Measured 11-23:** the 2:23 PM CST tick failed (rc 1, no rail.json) because the auto-ff landed bbbbb4b3f mid-run (old probe in memory, new runner, 11-19 page), a one-off. The user then said "fast-forward the primary tree now" (a5637a517 -> d845fe345, 2:28 PM). The 2:43 PM tick (20261123T204302Z) MET (1)-(3): page refetched 12.7 s, page_age_min 0.0, 88 cards, 0 chip-less, det1/det3 0, LAFC card on 401933728. Put the one failed tick in the 11-23 findings.

**R-J. 11-23 evening soccer overlay gaps (fleet-watcher flag R32 750 s / R34 711 s, 2 gaps).** Diagnosed 11-23 ~9:45 PM CST with `C:\tmp\railmon\diag_1123_soccer_gap.sh` and `diag_1123_soccer_gap2.sh` (both read-only, nice 19). Verdict: NOT the low-headroom refusals. All 42 refusals 00:00-03:30Z are live-odds-worker LIVE_LENS_TICK_DIAG (19 soccer), and refresh-worker, which builds the overlay, logged 0. It IS the evening-MLS UTC/CT split. LAFC @ St. Louis City (401933728, 01:15Z kickoff) has its in-play rows in the soccer **2026-11-24** file, rebuilt every 711-877 s (02:03..03:21Z, rows 63 -> 31). The 11-23 file rebuilt every 2-3 min. R34's second gap is the 11-23 file (449 s, 03:03:55 -> 03:11:24Z). Cost: at 9:23 PM the rail's LAFC card (live, 90'+10') showed 2 live rows and 1 market. Handed to lane evening-utc-date-split (session local_15f2d5e2), with the question whether change O moves these overlay rows onto the slate day. In the 11-23 findings, say that windows reading 0 gaps had the same cadence (window aliasing: one build per window). **Answered 11-23 ~9:50 PM CST by local_15f2d5e2:** change O moves the overlay too (verified on main: `_build_book_grid_artifact` reads `book_quotes_path(sport, date_str)`, and the overlay is written for the same `date_str`, book_grid_artifact.py:563-564 and :862). Their pre-registered P-E3 says Rail Watch's overlay_offdate_inplay stays empty.

**R-K. DONE 11-25 1:10 AM CST: P-E3 MET** (8 of 8 windows 02:43Z..05:03Z with `overlay_offdate_inplay` {}, gaps 73-141 s; HOU @ SJ card 2-5 live rows; sent to local_15f2d5e2, delivered; main `117737f83`). **P-E3 reading for change O, at the 11-24 close (Nov 25 12:55 AM, D = 2026-11-24).** If the batch loaded O (read its deploys.md entry), the first crossing match is HOU @ SJ (MLS, 9:00-11:00 PM CST 11-24 = 03:00-05:00Z 11-25). Read `overlay_offdate_inplay` in every `C:\tmp\railmon\dash\m_auto_1124_*.json` whose `start` is 02:40Z..05:20Z 11-25. MET = no `soccer@2026-11-25` key in any of them. Also note the rail card's live row count from those readings' `rail.json` (LAFC on 11-23 had 2). Tell session local_15f2d5e2 the result either way, with the files read. A non-empty key falsifies P-E3. If the batch dropped O, tell them that instead.

**R-G. #853 shared board copy for web: the first-evening reading (CHANGE F of the 11-24 batch; not a betting change).** Taken over 11-20 from session local_a5513c97 (since archived). The user's words: "Rail monitor takes it". Predictions are in `.syndicate/findings_2026-11-19_board_read_cold_share.md`, main `cd5c28556`.
- **DONE 11-24 11:20 PM CST: LOAD CHECK MET; P1-P4 PREDICTED, P5 FALSIFIED, P6 WATCH** (confounded by the 15:57Z GC revert; main `53cac5dd9`). #857 is unblocked for the next drained down/up.
- **Run after 11 PM CST 11-24**, only if deploys.md shows CHANGE F loaded. A one-shot cron does it at 11:20 PM:
  `wsl -- bash -c "cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p853/p853_readout.py 2026-11-23T23:00:00 2026-11-24T05:00:00 2026-11-24T23:00:00 2026-11-25T05:00:00"`
  (copies in `C:\tmp\railmon\p853\`, repo `scripts/rail_monitor/p853_readout.py` + `coldread_attrib.py`). It prints the load check, the confound check and P1-P6 verdicts.
- **The predictions:**
  - P1: cold share <= 25% (falsified > 30%);
  - P2: new-worker first reads <= 20% (> 25%);
  - P3: fresh-worker penalty in AFTER <= 1,500 ms (> 2,500 ms);
  - P4: adopted copy load p50 <= 1.5 s (> 2.5 s);
  - P5: builds per hour <= 0.75x baseline (> 0.9x);
  - P6 SAFETY: recycles per hour <= 1.3x AND anon p50 at recycle <= 1.1x. Both above = ROLL BACK (switch off at the next down/up); one above = WATCH.
- Dry run 11-20 on two pre-load evenings: VOID as expected. Baseline cold share 58.8% / 58.5%; recycles 15.2 / 16.7 per hour.
- **Where it goes:** the findings file above (a READING section), a deploys.md READING entry, and todo #853.
- **Related decision, not the monitor's:** #857 (raise web's worker recycle limit to 1,500 MB, measured on main `e47f83987`), recommended to load after #853's first evening. It is the user's call.
  - **ANSWERED 11-25 ~10:10 AM CST:** "Next scheduled restart". It rides the 12-08 window's drained down/up (none is scheduled before it); fleet-watcher told; main 3c1890cec. Do not re-ask. Do not list it under Open user decisions.

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

## d4metrics quiet overlay gaps (11-25, fleet-watcher flag R8)
- R8 (12:23 PM CT 11-25) counted wncaab 1,009 s (18:04:49 -> 18:21:38Z) as a stall. It was idle. Navy @ Iowa and Texas Southern @ Vermont (~16:03Z tips) went final ~18:05Z, and Stetson @ Robert Morris tipped 18:21Z. The overlay prints NO line when a build has no fresh in-play rows and its last publish had no cards, so no rows_inplay=0 line marked the idle. The grid built wncaab 3 times inside the gap, each with considered=0.
- From 12:46 PM CT 11-25, `dash\d4metrics.py` counts such a gap as QUIET when the previous line had cards=0 and every LIVE_GAMELINE_BUILD for that sport/date inside the gap considered 0. It goes to `overlay_idle_gap_max_s` and `overlay_quiet_over_360_by_sport`, not to `overlay_gaps_over_360`. If no build ran inside the gap, or a build had live rows, it still counts as a stall.
- Tested on 5 synthetic cases (`C:\tmp\railmon\d4test\`) and on 10 past stall windows rebuilt from the rotated logs (11-21..11-25). Every count matched the old metric except 11-25 R8. Backup `dash\d4metrics.py.bak_1125`. R8's recorded row is unchanged.

## dash_update re-sim tick flags (11-25, fleet-watcher flag R20)
- R20 (4:23 PM CT 11-25) counted `ncaab Liberty Flames @ Princeton Tigers o134.5 p=0.59 ours 134.3` as a contradiction. It is a display mismatch on the card, not a model fault. An uncalibrated total's card OURS is the chip's live re-sim `intervals.final.total` (`intelligence.html` liveRailSummary, the PROJ box), while p is the flagged row's own `live_model_probability`. The row's own `live_total` was 137.74, on the over side. The two are ticks of ONE re-sim, not two models: on that game the row equalled the chip at R17 (144.495 / 144.5) and R19 (145.98 / 146.0). The grid built at 22:22:25Z had joined the previous re-sim (137.74, so p 0.59), and the chip carried the re-sim stamped 22:22:28Z (134.3, after an H2 scoring drought: 20 points in 8:47).
- From 4:32 PM CT 11-25, `dash\dash_update.py` puts such a flag in `ours_resim_tick` / `_list`. The rule: OURS equals the chip's live re-sim final (within 0.05), the flagged row's own total is on the flagged side, and own differs from OURS. The list names both stamps. Anything else across the line still counts in `ours_contradictions`. The classification is now `classify_ours()`, and argparse sits under `__main__` so tests can import it.
- Tested over all 390 saved readings (`C:\tmp\railmon\d17test\regress.py`). With `split_resim=False` it reproduces every recorded row since R28 11-22. The 27 older differences are exactly the pre-R28 skew split. The split moves 11 of 1,483 college total flags (0.7%, 10 readings, 11-15..11-25) and nothing else. 20 contradictions remain, mostly before the 11-18 fix. Backup `dash\dash_update.py.bak_1125b`. R20's recorded row is unchanged.
- The card itself still pairs p from one tick with OURS from the next. LEAD 2 (11-20 findings) was never put to the user. A display-only fix would make a flagged total's OURS the flagged row's own `live_total`, at the cost of OURS leading or trailing the PROJ box by one tick.
