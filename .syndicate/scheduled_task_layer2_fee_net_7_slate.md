# Scheduled task — `layer2-fee-net-7-slate-reading-0929`

**One-time, 2026-09-29 10:00 CDT.** Discharges the `verify (OWED)` that the
fee-net score deploy wrote into `.syndicate/deploys.md` on 2026-09-21:

> fee-net CLV of the served top-K vs the pre-deploy baseline over >= 7 finished
> slates, same slates paired (`scripts/score_ranking_backtest.py`); paper-order
> ROI by venue after 09-21.

Created by session `dc70079c` 2026-09-22, no lane. Read-only: **this task never
deploys and never changes an env var.**

## Why 09-29 and not 09-28

The window is seven *calendar* slates, and there are two routes to the contrast
with different start dates:

- **CLV route** (the one §6 of `findings_2026-09-21_layer2_score_outcomes.md`
  used): recompute production `blended_score` over the `clv_openings` ledger,
  both with and without the fee-net value term, and pair within each
  (date x sport) slate. Works from **09-21**, because it recomputes both scores
  from the openings rather than reading a stamped one.
- **Recorder route**: re-rank the graded priced population using `n2` (fee-net
  EV), `fb` (fee basis) and `bk` (bookmaker). Those fields only exist from
  **2026-09-22T00:12:34Z** (`053ddd9e`, live 19:12 CDT 09-21), so 09-21 cannot
  supply a counterfactual pair on this route.

Firing the morning after 09-28 gives **8 slates on the CLV route and 7 on the
recorder route**, so neither is short. Firing on 09-28 would leave the recorder
route at 6 and the task would have to defer itself.

## The pre-registered estimate this is testing out of sample

From `findings_2026-09-21_layer2_score_outcomes.md` §6, dataset B, paired over 82
slates, in fee-net CLV points, top-K per (date x sport) with <= 3 rows per game:

| contrast | top 10 | top 25 |
|---|---|---|
| **today's score with fee-net EV − today's score** | **+0.79 [+0.27, +1.29]** | **+0.71 [+0.40, +1.04]** |
| fee-net EV x reliability (no sim) − today | +0.71 [+0.13, +1.29] | +0.62 [+0.28, +0.98] |
| score_v2 (Kelly) − fee-net EV x reliability | -0.01 [-0.66, +0.69] | -0.18 [-0.50, +0.16] |

That is an IN-SAMPLE fit on 09-01..09-20. **The whole point of this reading is
that the same contrast has never been run on data the choice was not made on.**

## Verdict rule — write it down before looking

Primary, on the **top 25**:

- **MET** — paired mean is positive and its 95% interval excludes 0.
- **INCONCLUSIVE** — interval spans 0. Say so; do not read the point estimate as
  a result, and do not quietly switch to the top 10 because it looks better.
- **NOT MET** — mean is negative and the interval excludes 0. That is a real
  finding: say it plainly and file a lead for reverting `SYNDICATE_SCORE_FEE_NET`.

Report the top 10 beside it as a secondary, never instead of it.

**Report the number of slates the result actually rests on**, per route, and the
per-family date coverage if any join was needed (CLAUDE.md's coverage rule — the
09-21 reading rested on 14 games and said so).

## Also owed by the same deploy, and part of this reading

1. **Paper-order ROI by venue after 09-21** — `/api/portfolio/paper?date=<d>` per
   date, split sportsbook vs exchange (`paper` vs `paper:kalshi` / `paper:polymarket`
   in the `venue` field). The claim under test: the >5.27%-stated-EV bucket that
   lost **-26.7% ROI [-46.3, -5.9]** is now refused, so it should be EMPTY after
   00:12:34Z 09-22. An empty bucket is the expected result; confirm it is empty
   rather than reporting no rows as a null.
2. **The Kalshi half of the venue ceiling is still OWED** as of 2026-09-22 13:23 CDT
   — that reading held on n=8, all Polymarket, with zero Kalshi live orders since
   the deploy. If any Kalshi live order exists by 09-29, check it carries
   `ev_pct <= 5.263` and is positive after the venue fee, and discharge it here.
3. **`score_v2` is NOT being decided here.** Its gate is todo `#679` step 5 — 14+
   days of recorder grading from 09-22, decided per sport (soccer +3.00, NCAAF
   -2.71 at the top 10 in sample). That window closes ~2026-10-06. Report `s2`
   vs `sc` as a running tally only.

## How to run it — the traps this cost a session to find

**The primary checkout is ~1,200 commits behind `origin/main` and the two scripts
this needs do not exist in it.** Work from a snapshot, not the primary tree:

```powershell
cd C:\Users\tempadmin\OneDrive\Coding\Syndicate
git fetch origin
git archive --format=tar -o C:\tmp\l2win.tar origin/main scripts syndicate pipeline requirements.txt
mkdir C:\tmp\l2win; tar -x -f C:\tmp\l2win.tar -C C:\tmp\l2win
copy .env C:\tmp\l2win\.env
```

- **Do NOT pipe `git archive` through PowerShell** — it corrupts the tar
  ("Unrecognized archive format"). Write it to a file first, as above.
- **Copy the NCAAF team registry into the snapshot or NCAAF is silently dropped.**
  `git archive` excludes `data/`, so `ncaaf_team_registry_snapshot.csv` is absent
  and every NCAAF row falls out as `extra_team_unresolved` (24,829 rows on the
  09-14..09-21 run). It is git-tracked, so just copy it:

  ```powershell
  $reg = "data\ncaaf_source\source_artifacts\data\processed\team_registry"
  mkdir C:\tmp\l2win\$reg -Force
  copy $reg\ncaaf_team_registry_snapshot.csv C:\tmp\l2win\$reg\
  copy $reg\ncaaf_team_registry.csv C:\tmp\l2win\$reg\
  ```

  This matters far more for this window than it did for 09-21: 09-26 and 09-27
  are a full NCAAF Saturday and Sunday, and NCAAF is the sport where the Kelly
  re-rank went the WRONG way in sample.

Then pull and grade:

```powershell
cd C:\tmp\l2win
py -3 scripts/score_ranking_backtest.py pull --start 2026-09-14 --end 2026-09-28 `
    --out C:/tmp/l2score/graded_0929.jsonl --cache C:/tmp/l2score/cache
```

- `--cache C:/tmp/l2score/cache` reuses the parts already pulled for 09-14..09-21;
  only new dates go over the wire. The 09-14..09-21 pull took 6m31s cold.
- `scripts/score_ranking_analysis.py` is a **library, not a CLI** — import it and
  use `usable`, `served_equivalent`, `bet_window`, `break_even`, `summarize`.
- **Bootstrap over GAMES, never rows** (row-level inference was measured to
  inflate significance ~7x in this repo).

## Two things the 2026-09-22 dry run found — fold these into the run

Measured by this task's tool pre-approval dry run, 2026-09-22 16:25-16:29 CDT,
which exercised every command shape in the section above against live data.

1. **`origin/main` MOVES UNDER YOU MID-RUN. Pin the SHA.** The dry run read
   `ebd17ee2` at its first step and `44e09175` a few minutes later — **89 commits
   landed on `main` that day** from parallel sessions. So: capture
   `git rev-parse origin/main` **once**, build the snapshot from that exact SHA
   (`git archive --format=tar -o <tar> <SHA> scripts syndicate pipeline ...`), and
   quote that SHA in the findings file. Never re-read `origin/main` later in the
   run and assume it is the tree you measured. Everything read for this reading —
   the briefs, the prior findings, the scripts — must come from the one pinned SHA.
2. **`rows=1` is NOT a size control on `/api/ops/clv/report`.** With `rows=1` the
   MLB request still returned **1,074,201 bytes**, and `/api/portfolio/paper?date=<d>`
   returned **2,281,659 bytes**. Budget for multi-megabyte responses per
   (date, sport) — this reading fans out over ~7 dates x ~6 sports — and write each to a file
   rather than holding several in memory.
3. **The NCAAF registry copy is confirmed load-bearing, not a precaution.** On the
   dry run's single-day window NCAAF contributed **2,334 of 16,505 records**.
   Skipping the copy does not error; it silently removes a sport.

## Four facts about the data that will otherwise be re-derived wrong

1. **The recorder file date is the SIGHTING date, not the kickoff date.** A row
   first seen on 09-20 for a 09-21 game lives in the 09-20 file. Grading by file
   date undercounts a day badly — the 09-21 file alone held 3 MLB games' worth of
   first sightings. Use the graded row's `date` field (the grader's Central
   kickoff date) and pull a window that starts well before the one being read.
2. **The recorder keeps the FIRST sighting per identity per phase.** The score it
   stamped is the score at first sighting, not the score the row held when it was
   at the top of the board.
3. **`kickoff >= today` is dropped as `not_yet`.** That is correct and expected;
   it is tomorrow's board sitting in today's file, not a failure.
4. **The fee-net term only moves rows priced at a fee venue** — 315 rows at the
   deploy reading, 158 of 1,837 at 00:16:57Z. For ~90% of the board the two
   scores are identical, so the paired difference is a small-support contrast by
   construction. Report how many rows actually differed between the two rankings;
   if that number is near zero the contrast is unmeasurable, not negative.

## Where the result goes

1. Append the measurement to `.syndicate/deploys.md` as the READING owed by the
   2026-09-21 21:43:55Z / 23:0xZ entries, naming the verdict, the slate count and
   the working. Append only — `git diff --numstat` must show **0 deletions**.
2. Write `.syndicate/findings_2026-09-29_layer2_fee_net_out_of_sample.md`.
3. Update the `[layer2-score-outcomes]` subject in `.syndicate/state_layer2.md`
   — that subject currently says the verification is owed, and it is the one
   place a future session will look.
4. If the verdict is NOT MET, file a lead; do not revert anything yourself
   (`SYNDICATE_SCORE_FEE_NET` is a refresh-worker env var, and changing it is a
   deploy behind two locks and a user decision).

## Prior art to read first

- `.syndicate/findings_2026-09-21_layer2_score_outcomes.md` — the in-sample study.
- `.syndicate/findings_2026-09-22_layer2_board_0921_reading.md` — the 09-21 slate,
  and why one day could not grade this.
- `.syndicate/state_layer2.md` `[layer2-score-outcomes]`.
