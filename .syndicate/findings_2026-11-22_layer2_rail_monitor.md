# 2026-11-22: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

Slate day 11-22 (the slate day rolls at 5 AM CST). Lean mode: the Claude-free Windows task `SyndicateRailWatch` writes the readings to `C:\tmp\railmon\dash\rows_2026-11-22.jsonl` and the Rail Watch page. This file holds the owned readings and the nightly close's summary.

## Fleet-watcher flag: no live NFL game carries a live model, R8-R9 (12:23 and 12:43 PM CST); read-only

local_379fd729 flagged the whole 12 PM NFL slate, marked URGENT. At R9, 6 games were `resimmed_no_row_model`: ARI@KC, MIA@BUF, NO@CHI, PIT@PHI, TB@DET, TEN@DAL. BAL@CAR was `degenerate_ratings`. At R8, PIT@PHI and TB@DET were `uninformative_probability`.

**Verdict: not a defect. The label came from my helper; the join is behaving by design. Nothing to load.** Diagnosed 12:59-1:06 PM CST.

- **The NFL re-sim publishes no total or margin distribution ON PURPOSE.** See `syndicate/features/nfl/live_resim.py:714-718` (since `f9506b267`, 09-28): lane `nfl-live-distribution-grade` graded NFL live margins a FAIL (worst powered bucket 0.4290 vs `#499`'s 0.150), and totals could not be measured.
  - Without a distribution, the join withholds every NFL live total and spread. It still records the means (rows carry `live_total`), so they are scored without being priced. This is the same class as NHL live totals.
  - **Measured over the saved readings, 238 of them across 8 days; NFL was live on 11-15, 11-17, 11-20 and 11-22:**
    - full-game NFL totals/spreads: 0 of 1,151 rows modelled;
    - segment rows: 0 of 1,048;
    - full-game moneyline: 48 of 69.
  - The moneyline misses are spread across games and days. Before 11-21 they cannot be attributed, because the reasons map only exists since then.
- **The full-game moneyline IS priced.**
  - R9 (18:43:02Z): 5 of 5 re-simmed games that had a full-game moneyline row in the read carried the model. ARI@KC was 0.941 at -15000, MIA@BUF 0.879 at -2780, NO@CHI 0.687 at -670, PIT@PHI 0.730 at -185, TEN@DAL 0.816 at -636. TB@DET had no full-game moneyline row in that read.
  - R8: TEN@DAL and ARI@KC carried the model; MIA@BUF and NO@CHI had no full-game moneyline row. PIT@PHI's row had none because the snapshot refused the game (`uninformative_probability`, early in the game).
- **The helper defect.** `p29_orient.py` and `dash_update.py` counted full-game totals/spreads as NFL's "priced" rows. A re-simmed NFL game therefore always read `resimmed_no_row_model` (3+ priced rows, none modelled), which the runbook calls a join defect.
  - **Fixed** in both files with one rule, `counts_as_priced`: NFL counts its full-game moneyline only, and NHL its puck lines only (unchanged).
  - Replaying R9 through the fixed `dash_update.py` (throwaway rows file, deleted afterwards) leaves only BAL@CAR (`degenerate_ratings`, lane `nfl-rating-units`) among NFL games.
  - R10 (1:03 PM, the first live tick on the fix) lists no NFL game. Every NFL full-game moneyline row in that read carried the model (ARI@KC, MIA@BUF, NO@CHI, TEN@DAL ×2). BAL@CAR had no moneyline row in that read.
- **Known blind spot.** An NFL game with no full-game moneyline row in a read drops off the no-model list, and that includes a game the snapshot refused. The rail is a cut, so a moneyline row is not always in it.
- **Not** the event id or orientation (every snapshot entry is `direct`), and not the 11-24 TD-level refit.
- The read-only NFL seeds and card probe (session d7e91c58, 12:30-1:15 PM) was not duplicated. I read only the saved Rail Watch readings and the tick's own orient output.
- Backups: `scripts/rail_monitor/{p29_orient.py,dash_update.py,RUNBOOK.md}`.

## Fleet-watcher flag: R21 (4:43 PM CST) gave "unknown" for two NCAAB games; read-only

local_379fd729 flagged Maryland-Eastern Shore @ IUPUI and UC Irvine @ Loyola Marymount: `unknown` at R21, `orientation_reversed` (I-29) at R20. **Verdict: `p29_orient.py` failed for the whole R21 tick, a one-off; cause not recorded.** Diagnosed 4:59-5:04 PM CST.

- `extra_2026-11-22.jsonl` R21 has `orient` empty and no `orient_auto_1122_21.txt` was written. That is `rc29 != 0` or empty output, which makes every no-model game `unknown` in `dash_update.py`.
- `tick.py` discarded p29's rc and stderr, so the cause is unknowable after the fact.
- **The evidence:**
  - p29's live-rail GET never reached `web.log`. R20's did (22:23:55.613Z, 397 KB, 61 ms); at R21 the only live-rail GETs were the probe's three (22:43:09-22:43:30Z).
  - `web.log` 22:43-22:46Z has no worker, boot, exit, timeout or error line.
  - p7count (WSL, just before) and ps (WSL, just after) both succeeded in the same tick.
  - The tick took 33 s from the metrics file (22:44:13.9Z) to its log line (22:44:47Z). At R20 the same steps took about 1.6 s. Something inside the p29 call spent about 30 s, which matches the helper's own 30 s urlopen timeout, but the request never showing in `web.log` is not explained.
  - A by-hand rerun at 23:00:28Z: rc 0, 0.35 s, 22 lines.
- **Fix (Claude-free monitor file only, no fleet change):** `tick.py` now logs `p29 rc=... <secs> <stderr tail>` on a failure and retries once. The retry is one live-rail GET plus snapshot reads, all read-only.
  - Edited and compiled at 23:00:43Z. R22 (23:03Z) ran on it, needed no retry, and read both games `orientation_reversed` again.
  - Next time the tick log will say why.
- New reader: `web_liverail_reqs.py <lo> <hi>`, every live-rail GET in `web.log` with status, bytes, agent and ms.
- Backups: `scripts/rail_monitor/{railwatch_tick.py,web_liverail_reqs.py}`.

## Fleet-watcher flag: R24 (5:43 PM CST) overlay_gap_max_s 1,098 s; read-only

local_379fd729 flagged an 18-minute live overlay gap: R24 `overlay_gap_max_s` 1,098 and `overlay_gaps_over_360` 1, where R21-R23 read 117-141 s. **Verdict: not a stall. The gap was soccer's idle time between two MLS matches, and `d4metrics.py` counted it as a gap. The metric is fixed.** Diagnosed 5:58-6:04 PM CST.

- **The gap is soccer's alone,** 23:23:51Z to 23:42:09Z (`overlay_gap_max_sport: soccer`). Every other sport's overlay published throughout 23:20-23:45Z, with gaps up to 108 s (NFL), 105 s (NHL) and 82 s (NCAAB) (`overlay_lines.py`).
- **The earlier MLS match went final about 23:22Z.**
  - Soccer `rows_inplay` was 50 at 23:22:33Z and 0 at 23:23:51Z, the last line before the gap.
  - MLS `final_cached=1` at 23:25:08Z.
  - `SOCCER_LIVE_AUTORUN_LAUNCHED in_play=mls` ran every ~2 min to 23:21:57Z, then stopped. That is correct: `_soccer_in_play_leagues` (`run_live_odds_refresh_worker.py:794`) found no MLS game in play.
- **Charlotte FC @ Chicago Fire is listed for 23:30:00Z (`commence_time`) but kicked off about 23:41Z.** MLS's own `live_state_2026-11-22.json` read 20' at 00:01:01Z.
  - `FIXTURE_CADENCE sport=soccer league=mls due:live_now` fired from 23:24:42Z, because the schedule had the match due.
  - The live state held no in-play game until kickoff, so nothing launched.
- **The refresh launched again at 23:42:01Z.** The overlay had 7 soccer rows at 23:42:09Z and 270 at 23:42:48Z, about a minute after kickoff.
- **Not** the live-odds-worker self-recycle (22:58Z, 25 min before), not `low_headroom`, and not the evening board cost (I-20).
- **Fix (Claude-free monitor file only, no fleet change):**
  - `d4metrics.py` sends a gap that STARTS at a `rows_inplay=0` overlay line to the new `overlay_idle_gap_max_s` / `_sport`. A gap after a line with rows in play still counts in `overlay_gap_max_s` / `overlay_gaps_over_360`, because that is a stall.
  - Replaying the R24 window: `overlay_gap_max_s` 108 (NFL), `overlay_gaps_over_360` 0, soccer idle 1,098.
  - Live from R25 (6:03 PM), which read `overlay_gap_max_s` 122 (NHL), `overlay_gaps_over_360` 0, and no idle gap.
- **What the fix could hide.** If an overlay ever publishes `rows_inplay=0` while a game IS in play (for example a soccer live refresh that fails at kickoff), the gap after it now reads as idle. Seeing that is the soccer lens and autorun counters' job, not this metric's.
- New readers: `overlay_lines.py <sport> <lo> <hi>`, `soccer_live_window.py <lo> <hi>` and `soccer_live_state_peek.py <league> <date>`.
- Backups: `scripts/rail_monitor/{d4metrics.py,overlay_lines.py,soccer_live_window.py,soccer_live_state_peek.py,RUNBOOK.md}`.

## Fleet-watcher flag: R27 (6:43 PM CST) ours_contradictions=1, NCAAB Rice @ Lamar u167.5 p=0.69, ours 167.7; read-only

**Verdict: a skew artefact, not a contradiction. The counter now tells the two apart.** Diagnosed 6:58-7:01 PM CST.

- **The flagged u167.5 row's OWN `live_total` is 167.69**, the number the card shows as OURS. The probability and the mean therefore come from one distribution. Its sibling rows on the same total read P(over 165.5) 0.72, P(over 166.5) 0.68, P(over 167.5) 0.31 and P(under 167.5) 0.69.
- That is a right-skewed end game. The chip read H2 0:00 at 85-81 (166 scored); the re-sim's state was a little earlier. Most sims finish at or below 167, and a tail runs well above it, the shape of an extra-period branch. This is the non-defect the counter's own comment already named ("a late tie"), as with 11-20's Niagara @ Delaware St.
- These full-game rows carry `live_total_basis: None` (not calibrated). That is not checked here and is the I-17 owner's question if it matters.
- **Why not p vs 0.5 or a median, as asked:** every counted flag already has p > 0.5, so p vs 0.5 counts nothing, and no median is published on the card or the row.
- **The rule that separates the cases:** is OURS the flagged row's own total? The real defect this counter exists for (11-18 reading 13) was the card taking OURS from ANOTHER row, 152-249 s older.
- **Fix (`dash_update.py`, monitor file only):**
  - A flag whose OURS equals the flagged row's own `live_total` (within 0.05) goes to `ours_skew_consistent` / `_list`, not to `ours_contradictions`. A mismatched OURS still counts.
  - Replays into a throwaway rows file, deleted afterwards:
    - R27: 0 contradictions, 1 skew-consistent (Rice @ Lamar, own 167.69).
    - 11-18 00:40:35Z: still the 2 real ones (Chattanooga @ Winthrop OURS 156.0, Coppin St @ La Salle 146.0) and 0 skew-consistent.
  - Compiled at 01:00:07Z, before the 7:03 PM tick. R28 (7:03 PM) ran on it cleanly, with 0 contradictions and 0 skew-consistent.
- Backups: `scripts/rail_monitor/{dash_update.py,RUNBOOK.md}`.
