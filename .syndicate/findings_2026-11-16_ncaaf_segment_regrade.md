# NCAAF segment re-grade, weeks 12-14 (the first weeks the sim archive covers) — PRE-REGISTRATION (todo #805 + #807)

Written 2026-11-16 ~4:45 PM CST, before any week-12 game is played and before any data below is read.
User: "re-grade NCAAF segments too after three weeks" (2026-11-16, right after the NFL re-grade was registered in
`.syndicate/findings_2026-11-16_nfl_segment_regrade_808.md`). Run date: **Monday 2026-12-07, 10:00 AM CST**, after
championship Saturday 12-05, by a scheduled task.

## Why this re-grade, and what is different from #805

- #805's grade (`.syndicate/findings_2026-11-14_ncaaf_segment_skill.md`, 161 games, weeks 5-10) is what the board
  ranks on today (`measured_market_skill`, loaded 2026-11-14 23:32Z):
  - totals **+0.0230 [+0.0115, +0.0349], loses**, rank x0.769;
  - spreads **+0.0080 [+0.0010, +0.0153], loses**, x0.981;
  - h2h +0.0057 [-0.0012, +0.0131], parity, x1.0.
- **It could see only the Saturday late slates.** The week's sim file was rewritten through the week. Only a file
  written before kickoff was gradable, so 3,485 of 6,467 quoted markets were refused (`sidecar_written_after_kickoff`).
- **#807 now keeps every write** (`<SYNDICATE_DATA_ROOT>/sim_history/ncaaf/`, on the fleet since the 2026-11-15
  01:44:01Z ff). Each game can be priced off the last write before its kickoff, which is the file the board was
  serving. Weeknight and early-Saturday games become gradable for the first time.
- **Coverage starts at week 12.** Read 2026-11-16 22:32Z, the archive holds two pairs:
  - `wk11.20261115T164612Z`, written after every week-11 game, so week 11 stays ungradable;
  - `wk12.20261116T062636Z`.
  Weeks 12, 13 and 14 (Saturdays 11-21, 11-28 and championship 12-05) are the first fully covered weeks.
- **The engine is unchanged.**
  - NCAAF has priced on `data/calibration/ncaaf_profile.json` version **`ncaaf-goal-line-refit-1`** since
    2026-08-27 (`600a753af`), before #805's first graded week. Read 2026-11-16 22:4xZ:
    - the fleet checkout (`dac4d49f8`) carries that version;
    - no fleet role sets `SYNDICATE_CALIBRATION_PROFILE_DIR` or `SYNDICATE_CALIBRATION_PROFILE_PATH_*`, in the
      render_env snapshots, `local_production.env` or the running processes.
  - #808's switches stay OFF for NCAAF ("no clean held-out"), and tonight's profile load is NFL-only.
  - The NFL re-grade's line "NCAAF ... its profile stays OFF" means those switches, not this profile.
  - #805's registry load changed rank only, never a probability.
  - This re-grade is therefore an out-of-sample test of #805's verdicts on the same engine, over a wider
    population.

## Population

NCAAF 2026 games kicking off **2026-11-17 00:00Z .. 2026-12-06 12:00Z**. A game is graded if it has all four of:
- (a) a pregame h1/h2/q1-q4 totals/spreads/h2h quote (`captured_at < commence_time`) in the fleet's date files
  `ncaaf_source/tracking/book_quotes/2026-11-16.jsonl.gz .. 2026-12-06.jsonl.gz`;
- (b) a sim block through production's bridge, from the LAST kept or current write strictly before kickoff
  (`--archive`);
- (c) a final ESPN college-football linescore for that game id;
- (d) **the same NCAAF profile over the whole window:** `ncaaf-goal-line-refit-1`, with no
  `SYNDICATE_CALIBRATION_PROFILE_DIR` or `_PATH_*` key on any fleet role.
  - Evidence: `git log` of `data/calibration/ncaaf_profile.json` on main and on the fleet checkout, and the fleet
    ff records in `.syndicate/deploys.md` over the window.
  - If the profile changes in the window, the games priced from writes before and after the change are reported
    apart and never pooled.
  - G1 then takes the `ncaaf-goal-line-refit-1` games only.

The window is set by kickoff, not by week number. The generator's week numbering for championship week does not
matter: the bridge's own rule (a pair whose ESPN event is dated within a day of kickoff) picks the week.

**Archive integrity.** In the role logs over the window, count `sim_history_kept=`, `unchanged` and
`sim_history_error=` per week. A week with any `sim_history_error=` is excluded BY NAME, because a missed write would
hand its games an older write than the board served. If the logs no longer cover the whole window, say so; the
week is then graded, with the gap stated.

**Expected size** (not a target): the wk11 write held 67 games, so about 65 a week plus about 10 championship games,
roughly 140 simmed games. The count-only run sets the real number.

## Method

Unchanged from #805, with `--archive`:
- Grader `scripts/ncaaf_segment_skill.py` at blob **`97b450918eee`** (on main since `281c809a6`). It imports
  `scripts/nfl_segment_skill.py` at blob **`020cb082b5a9`** unchanged.
- **If either blob differs on main at run time,** run the registered blobs (`git show <blob>`) and report the diff.
- Library code (the bridge, `probability_above`, `segment_actuals`) is origin/main at run time, which is production's
  own. Report any change to those modules since `281c809a6`.
- Market: each book's last pregame two-sided pair, de-vigged proportionally; the consensus (modal) line.
- Model: production's `probability_above` over the write's histogram.
- Unit: game x segment x market. Families: totals, spreads, h2h, each pooled over h1/h2/q1-q4.
- dBrier = Brier(model) - Brier(market); 95% CI by game-clustered bootstrap, 2,000 reps, **seed 804** (the
  registered default).
- Verdict: loses if the CI's lower bound > 0, beats if its upper bound < 0, else parity (stated with n).
- `established_loss_rel` = max(0, CI lower) / Brier(market), as #805's registry rule.
- Order: `--count-only` first (it reads no box), record the population, then the grade.
- PYTHONHASHSEED=0, Idle priority.

## Gates

**G1 — the verdict of record: weeks 12-14 alone.** Per family, dBrier, CI, verdict and `established_loss_rel`.
- #805's weeks 5-10 numbers are reported beside it.
- A pooled weeks 5-14 figure is reported too, as descriptive only. The two populations differ by construction (late
  Saturday only vs all slates), so the pool is not the verdict.

**G2 — was #805's population representative?** Reported, not gated. Split the graded games in two:
- A: kickoff after the week's LAST write, which #805's as-of rule would also have kept;
- B: the rest, gradable only through the archive (weeknight and early-Saturday games).
Report per-family dBrier for A and B, and B - A with a game-clustered bootstrap CI (2,000 reps, seed 807).

**G3 — engine read, reported, not gated.** Per segment: sim mean vs actual, the PIT outer-20% share, and quarter
shares (sim vs actual), beside #805's.

## Predictions, registered now

| # | prediction |
|---|---|
| P1 | G1 totals: **loses** (the CI's lower bound > 0), with the point estimate within ±0.015 of #805's +0.0230. |
| P2 | G1 spreads: the point estimate > 0 (verdict loses or parity). |
| P3 | G1 h2h: parity. |
| P4 | G1 totals: the model's calibration slope (logit fit beside the market) stays below 0.3, as #805's −0.03. |
| P5 | G2: no family's B - A CI excludes 0. |
| P6 | G3: the sim's q2 share is below the actual and its q3 share above (#808's shape, with #808's switches OFF for NCAAF). |

**Falsification of #805's registry verdicts:** a G1 family reads parity or better where #805 read loses, or loses
where #805 read parity.

## What the result is allowed to change

- **Nothing is changed by the run itself.** The run writes results here, plus the todo, the log and a deploys.md
  READING.
- **G1's figures are the candidate registry update** for the 18 `("ncaaf", ..., pregame)` entries in
  `measured_market_skill`. That is a code change and a load, the #805 recipe: a fleet ff, a claimed and drained
  refresh-worker TERM, and reload-web. The user decides after the read.
- **If P5 fails** (B differs from A), #805's verdict rested on an unrepresentative slice. That goes to the user with
  the G1 numbers.
- **Out of scope:** an NCAAF profile, meaning #808's switches on NCAAF. That arm belongs to lane
  `football-scenario-calibration`, and nothing here grades it.

## Data (copied read-only from the fleet at run time, never written back)

- Quotes: `~/syndicate-prod/data/ncaaf_source/tracking/book_quotes/2026-11-16.jsonl.gz .. 2026-12-06.jsonl.gz`
  (the date files only, not the `*_wk*.jsonl` files).
- Current writes: `~/syndicate-prod/data/ncaaf_source/data/smartsim2_{projections,segment_distributions}_2026_wk*.{csv,json}`.
- Kept writes: `~/syndicate-prod/data/sim_history/ncaaf/` (all files).
- Linescores: ESPN, cached to `linescores.json` in the run directory.
- Run directory: `C:\tmp\ncaaf_seg_regrade\`, a new one. `C:\tmp\ncaaf_seg\` stays #805's.
