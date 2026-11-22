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
