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

## Fleet-watcher flag: R36 (9:43 PM CST) score floor, Tenn-Martin @ Utah Valley u152.5; read-only

The flag: "total 152.5 < 153 scored, age 104.9". It asked whether the row was shown, recommended or bet, and whether the age caused it. **Verdict: shown only, never recommended or bet. Score timing between two chip feeds, not the age.** Diagnosed 9:58-10:08 PM CST.

- **Shown only, as a book line.** The row was betrivers u152.5 at -265, with one book quoting.
  - The live-rail read (grid `03:42:28Z`) carried `live_model_probability` 0.5008, `live_total` 152.5 (calibrated) and `model_edge_pct` None.
  - In `query.json` its edge was **-6.6 pp, against the under**. It was not on the shortlist, and the card's total edge was u162.5.
  - The next grid (`03:43:20Z`, in `rail.json`) carried no model on that row.
- **Not bet.** The live book (`/api/portfolio/live?on=all&show=all`, ops token) holds 0 orders for event `4564c6b6...` or Utah Valley. New reader: `live_bets_for.py <substr>`.
- **The age is not the cause.** 104.9 s is the BOOK QUOTE's `book_age_seconds`, which `floor_examples` prints and the floor never uses.
- **The cause is the grid's score.**
  - `college_calibrated_total` returns P(over t) = 1 below the points it is given (`live_gameline_join.py:1418`), so its answer cannot fall below that score. It returned 152.5, so the 03:42:28Z grid saw at most 152.
  - The chip the rail read had 76-77 = 153 (OT 1:31), from the chip artifact published `03:41:32Z`, 56 s BEFORE that grid.
  - The grid's score comes from refresh-worker's own chip build, not that artifact: `board_enrichment.attach_game_state` → `build_game_chips`, a 30 s cache served up to 300 s stale while another build is in flight (`game_chip_scoreboard.py:33,62`).
  - So the floor and #824 act on a score that can be a minute old. Here that was harmless, since the row had no edge. It is a lead for the I-17 / #824 owner if that matters on end games, not a guard defect.
- **Rate:** 23 violations in 7,964 calibrated rows (0.29%), in 4 of 237 readings over 11-15..11-22: 11-20 R32 (14) and R33 (7), 11-21 R13 (1), 11-22 R36 (1).
- Runbook P8 note extended: a grid newer than the chip artifact can still hold an older score.

## Fleet-watcher flag: overlay gaps R32 785 s / R34 809 s / R36 667 s (8:23-9:43 PM CST); read-only

The question: which sport, and did it have rows in play? **Verdict: soccer, with 31-64 rows in play, a REAL stall of one match. Real Salt Lake @ Vancouver Whitecaps (MLS, kickoff 01:30Z / 7:30 PM CST, final 2-0) was filed under the NEXT UTC date.** Diagnosed 10:00-10:09 PM CST.

- **The grid and the live machinery used different dates.**
  - The book grid holds the match in `soccer_source/data/book_grid/book_grid_2026-11-23.json` (473 rows, `commence_time` 2026-11-23T01:30:00Z).
  - Its live state and the live autorun stayed on 11-22: `SOCCER_LIVE_AUTORUN_LAUNCHED date=2026-11-22 ... in_play=mls` ran every ~2 min until 03:33:28Z.
- **(a) Its rows refreshed only when the 11-23 grid rebuilt.** The soccer `date=2026-11-23` overlay published at 01:48, 02:03, 02:16, 02:30, 02:45, 02:58, 03:12 and 03:28, then 03:39 (`rows_inplay=0`, final). The gaps were 613-962 s with 31-64 rows in play.
  - The `date=2026-11-22` soccer overlay stopped at 01:53:33Z (`rows_inplay=1`).
  - R35's 144 s hid the 962 s gap (03:12:08 → 03:28:10), which spans two windows.
- **(b) No live model for the whole match.** All 9 `LIVE_GAMELINE_BUILD sport=soccer date=2026-11-23` lines (01:48-03:39Z) read `index=0 considered=0`: the live index for that date was empty.
- **(c) Never on the live rail.** The rail reads only the slate day's overlay (`read_inplay_overlay_cards(date_str)`, `book_grid_artifact.py:1270`). The R36 live-rail read had `soccer: stale_6573s`, stale since 01:53Z.
- **Not bet:** 0 live-book orders for event `78c0145b...` or a Vancouver 01:30Z match.
- **Not** the R25 idle-gap change: every one of these gaps starts at a line with rows in play, so they counted as stalls, correctly.
- **Whose:** a fix is production code, and it is a betting change, because it would put a live model on these matches. It needs a window and the user's yes. No open lane covers it; routed to the fleet-watcher. Related: 11-21's chipless MLS rows for the same two late matches (the MLS team-card LEAD, findings 11-21 line 284).
- **Monitor fix (`d4metrics.py`, monitor file only):**
  - Overlay gaps are keyed on sport AND date, since each overlay file is one of each; keying on sport alone interleaved the 11-22 and 11-23 soccer lines.
  - New outputs: `overlay_gap_max_date`, and `overlay_offdate_inplay` (sport@date of in-play overlay rows off the slate day).
  - Replays:
    - R34 window: 809 s soccer 2026-11-23, `{soccer@2026-11-23: 37}`.
    - R36: 667 s, 31.
    - R35: 144 s NFL, with `soccer@2026-11-23: 39`.
- New readers: `grid_lines_for.py <sport> <date> <lo> <hi>`, `grid_game_states.py <sport> <date>`, `overlay_file_peek.py <sport> <date>`, `live_bets_for.py <substr>`.
- Backups: `scripts/rail_monitor/{d4metrics.py,grid_lines_for.py,grid_game_states.py,overlay_file_peek.py,live_bets_for.py,RUNBOOK.md}`.

## DAILY SUMMARY — Sun 11-22 (day 8), closed 1:05 AM CST 11-23

45 readings by the Windows task, 10:03 AM to 12:43 AM CST, every 20 min, 0 failed ticks (`railwatch\tick.log`). POP_START 16:00Z. Flags are graded on their first sighting against the finals by date (`C:\tmp\railmon\grade_2026-11-22_out.json`). The grade ran while San José St @ Loyola Chicago (11 PM tip) was still live. That game carried no model all night (I-29 below), so it has no flags to grade.

### The grade

| bucket | flags | games | W-L-P | hit | fair | hit − fair, 90% CI (game-clustered) |
|---|---|---|---|---|---|---|
| **ALL** | 363 | 59 | 189-174-0 | **0.521** | 0.474 | [+0.004, +0.094] |
| P3 first reading: yes | 60 | 31 | 34-26 | 0.567 | 0.486 | [−0.037, +0.196] |
| P4 fair < 0.40 | 50 | 11 | 6-44 | 0.120 | 0.216 | [−0.158, −0.021] |
| P5 NCAAB full totals | 78 | 28 | 48-30 | 0.615 | 0.504 | [−0.003, +0.226] |
| sport: NCAAB | 173 | 29 | 104-69 | 0.601 | 0.510 | [+0.015, +0.171] |
| **sport: NBA** | 141 | 7 | 55-86 | **0.390** | 0.410 | [−0.050, +0.007] |
| sport: soccer | 22 | 9 | 14-8 | 0.636 | 0.520 | [−0.049, +0.337] |
| sport: WNCAAB | 19 | 7 | 10-9 | 0.526 | 0.500 | [−0.186, +0.238] |

- **The flags beat their fair price for the 5th day in a row (11-18 to 11-22), and today the CI clears 0.** The model's mean p was 0.587 against a 0.521 hit, so it is again ~7 pp over-confident on its own side (#847).
- **NCAAB carried the day** (0.601 vs 0.510, CI clear of 0).
- **NBA was under fair for the 5th day** (0.390 vs 0.410, 7 games; the CI crosses 0 by 0.7 pp). Its long shots went 2-20 (S4 tail).
- **Long shots lost more often than their own price said** (0.120 vs 0.216, CI below 0). P4 only caps them at fair + 2 pp, so it is MET, but these flags did worse than the market's price, not just no better.
- 16 flags were not graded: 7 had no chip, 4 had no probability, 1 had an unmatched team, and 4 were early (before POP_START).

### Pre-registered verdicts (standing P1-P6, P8)

| # | prediction | result | verdict |
|---|---|---|---|
| P1 | 0 rail-card contradictions | 3 counted (R19, R26, R27), all before the 7:01 PM counter fix. All three replay as skew-consistent: OURS is the flagged row's own total (Troy @ Nicholls u155.5 156.6 vs 156.635; Rice @ Lamar u164.5 164.9 vs 164.87, u167.5 167.7 vs 167.69). 0 at R28-R45 | **MET** under the fixed rule |
| P2 | board publication gap median ≤ 600 s, none > 1,800 s, 5:30-10:30 PM | 54 publications, median **317 s**, max 724 s, 3 over 600 s (`p2_boardpub.py`) | **MET** (11-21: 25 publications, median 657 s) |
| P3 | first-reading flags at or below fair | 0.567 vs 0.486, CI [−0.037, +0.196] | **within noise** (above, not significant, as on 11-19 to 11-21) |
| P4 | long shots (fair < 0.40) at most fair + 2 pp | 0.120 vs 0.216 | **MET** (and below fair, CI clear) |
| P5 | report NCAAB calibrated live full totals | 78 / 28 games, 0.615 vs 0.504; under 54 (0.593) / over 24 (0.667); the flagged lines went over 38 of 78 | report |
| P6 | 0 pregame NCAAB / WNCAAB totals flags | 0 at all 45 readings | **MET** |
| P8 | score floor: 0 college calibrated full totals below the score | 1 row of 1,311 at R36 (9:43 PM): Tenn-Martin @ Utah Valley u152.5, shown only, never bet | **NOT MET as written; timing, not the floor.** The price grid's own chip score lagged the rail's chip by ≥ 56 s (block above) |

### What the day found

Each item has its block above:
- **NFL "no live model" at 12:23-12:43 PM was the helper's label, not a defect.** NFL prices its full-game moneyline only, by design (`nfl/live_resim.py:714`). The helpers now count only that row as priced.
- **R21's "unknown" games** came from a one-off helper failure. `tick.py` now logs the reason and retries once.
- **R24's 1,098 s overlay gap** was soccer's idle time between two MLS matches. The metric now counts it apart.
- **R27's contradiction** was a skewed end game; the counter now tells the two apart.
- **R36's score floor** was score timing (P8 above).
- **R32-R36's soccer overlay gaps were a REAL stall.** Real Salt Lake @ Vancouver (MLS, 7:30 PM CST) was filed under the 11-23 date. It refreshed every 13-16 min, had no live model all match and never reached the live rail. Not bet. A fix is a betting change and was routed to the fleet-watcher.
- **I-29 hit 16 college games, up from 3 on 11-21.** 14 of 46 NCAAB and 2 of 13 WNCAAB games had their teams the other way round from the re-sim, and **none of the 16 ever carried a live model**. Examples: Butler @ Nebraska (7 readings), New Mexico St @ Robert Morris (7), Cal Baptist @ Portland (6). Why so many today was not checked. Change G (the I-29 fix) is in the 11-24 batch, so this is its size on a busy day.
- **Other games with no live model, as unique games:**
  - NCAAB `not_in_resim` at tip-off: 11 (most are the reversed games' other spelling);
  - NHL `in_intermission`: 5;
  - NFL `uninformative_probability`: 4 and `degenerate_ratings`: 2;
  - NCAAB / WNCAAB `pbp_score_mismatch`: 3 / 1;
  - key player out: 1 NBA (Utah, Jaxson Hayes) and 1 NFL (Minnesota, Kirk Cousins), both #814 by design.
- **One NCAAB game ran past midnight CT** (San José St @ Loyola Chicago). At the roll the live rail and the chips switched to 11-23 (`central_today_iso()`, `intelligence.py:3628`). From 12:03 AM the rail showed 0 NCAAB rows while the 11-23 overlay held the game on and off (`rows_inplay` 0-14). It was reversed (no model) and has 0 orders, so only book rows were lost. This is the midnight family (#792 / #782), not a new defect.
- **LEAD, now 3 slates old: MLS playoff team cards.** Each match has chip count 0 and rows with no chip:
  - 11-22: CIN @ NSH, CLT @ CHI and RSL @ VAN;
  - 11-23 from 12:03 AM: LAF @ STL, row keys `lafc` / `st. louis city sc`.
  Not diagnosed. A naming split between the chip and the odds rows is still the first suspect.
- 0 false and 0 missed flags at every reading; dark rows at most 2.

### Owned readings

- **R-F #850 did not qualify:** 10 core live games at 7:03 PM (threshold 33), so nothing was sent to local_d0f83044. For context, on the same parent since the 4:37 AM reset:
  - 9 refusals at the P1 stage (1/2/3/3 an hour);
  - 1 exit (rc 75, `heavy_build_refused`, 9:09 PM);
  - longest build gap 724 s;
  - parent RSS 8-10 PM p50 1,974 MB (n 6, 1,950-2,056).
  So the refusals came on a light Sunday too.
- **R-B / R-D / R-G:** 11-24, only if their changes load (one-shot crons exist).

### Loads (11-22 slate)

- **4:37 AM:** refresh-worker parent reset (#850), no code change. Betting change no.
- Nothing else: all 45 readings ran on `b07e80882`, and deploys.md has only readings after 4:37 AM.

### Open user decisions

- **The 11-24 window batch:** #860 (the St. Louis Blues NHL join) and change G (I-29, 16 games today) each take your yes then. The fleet-watcher keeps the queue.
- **The late soccer date split** (RSL @ Vancouver had no live model or rail): a fix would be a betting change. It is routed to the fleet-watcher, and no lane holds it yet.
- **The soccer live lens fix** (11-21, options (a)-(d)): open, not requested.
- **#850's next lever** comes through local_d0f83044.
