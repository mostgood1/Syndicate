# Soccer RATING V2 through the real SoccerSim: the do-no-harm gate before shipping (lane `soccer-team-strength`) — 2026-10-19

Lane `soccer-team-strength`, session e44b3e73. The user decided at 2026-10-19 ~21:0xZ to ship the stage-1 rating
changes ("ship the rating changes"). Stage 1 measured them on a linear Poisson link, not on the engine. Stage 4 has
just shown that a map fit on that link (the draw term) did NOT port to the sim, so before shipping the ratings
this file runs them through the engine itself.

## 1. PRE-REGISTRATION (committed BEFORE any sim is run)

- **Code under test:** `RatingV2` in `syndicate/features/soccer/features/loaders.py`, wired through
  `build_soccer_artifacts._rating_v2` (recency half-life 40, current-season blend c 40, shrinkage n0 5 toward
  0 / the per-league fitted promoted prior). Before the A/B, an identity check must show that this production
  code reproduces the research code's cumulative arm (`soccer_team_strength_experiments.variant_features` with
  `CUM_CFG`) to within 2e-4, or nothing runs.
- **Harness:** `scripts/backtest_soccer_h2h_calibration.py`, which re-sims each match day through the real
  `SoccerSim` with ratings as of that day. Two arms on the SAME code commit, differing only in `--rating-v2`:
  - **v1** (the shipped rating);
  - **v2**.
  - Both arms: the 8 V2 leagues (epl, la_liga, bundesliga, serie_a, ligue_1, eredivisie, primeira_liga,
    belgian_pro_league), `--since 2025-07-01` (season 2025-26 plus 2026-27 to date), `--min-prior-matches 10`,
    `--simulations 300`, `--source-root` = the primary tree's `data/soccer_source`, `--fd-close-dir
    C:/tmp/soccer-lpb/fd2526`, `PYTHONHASHSEED=0`, Idle priority.
  - Eligibility depends only on each side's row count, which V2 does not change, so both arms score the same
    matches. This is checked, and the run is void if the match sets differ.
  - `min-prior 10` makes the v1 arm exactly production: the few-match gate fires below 10 and the harness
    applies no gate. It also means the promoted-club half of V2 is NOT exercised here; stage 1 measured that
    part separately (PROMOTED −0.0116, CI spanning 0).
- **Primary:** Δ = LL(v2) − LL(v1), per-match 1X2 log loss against the outcome, paired, 95% CI from 2,000
  bootstrap resamples over matches (seed 699).
- **Ship rule (do no harm):**
  - **SHIP** if the point estimate is below 0;
  - **HOLD** (do not ship; report to the user) if it is ≥ 0.
  - With about 2,000 matches the CI is expected to span 0 either way. Stage 1 already supplies the precision
    (27,285 matches); this run checks only that the sign transfers through the engine.
- **Secondary (no verdict):** Brier; per league; mean log loss of each arm against the close; top-decile
  favourites by the close and by each arm's own probability; spread sd of p(home) − p(away).

## 2. Identity check

**PASSED, exactly.** On every 40th FULL match of stage 1's population (8 leagues, 2014-2026), production's
`compute_team_ratings(..., v2=RatingV2(promoted_prior=<that season's fitted prior>))` was compared with the
research `variant_features(CUM_CFG)` on 1,620 sides; the max error was **0.0**. Fill-ins for unrated sides went
through `rating_from_raw(prior)`.

Six matches were set aside, all of them EPL / Serie A etc. played in July 2020 (the COVID-extended 2019-20 season):

- research takes the current season from the football-data file label (2019);
- production takes it from the date (`season_label`: July → 2020).
- For FUTURE fixtures the two agree. The difference only touches a season that runs past June 30.

Hermetic tests: `tests/test_soccer_rating_v2.py` (9), plus the existing gate / fill / as-of suites (32 in total,
all passing).

## 3. Results

**RUNNING since 2026-10-19 22:47:57Z** at Idle priority. Outputs: `C:/tmp/team-strength/v2sim/{v1,v2}.jsonl`
(append + resume, so a killed run restarts where it stopped) and `.summary.json`. Measured throughput on the shared
machine is about 1.2 (v1) and 0.6 (v2) matches a minute, so the expected finish is 1-2 days. **By user decision
2026-10-19, the full registered population runs; V2 stays OFF until it finishes.**

To resume after a kill: re-run each arm's command below. `--append-dump` skips the matches already written.

    PYTHONHASHSEED=0 SYNDICATE_SOCCER_RATING_V2=<0|1> python scripts/backtest_soccer_h2h_calibration.py       --leagues epl,la_liga,bundesliga,serie_a,ligue_1,eredivisie,primeira_liga,belgian_pro_league --since 2025-07-01       --min-prior-matches 10 --simulations 300 --source-root <primary>/data/soccer_source       --fd-close-dir C:/tmp/soccer-lpb/fd2526 --dump-matches C:/tmp/team-strength/v2sim/<arm>.jsonl --append-dump       --out C:/tmp/team-strength/v2sim/<arm>.summary.json [--rating-v2 for the v2 arm]

Run it at Idle priority: wrap it in `psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)`.

**On a SHIP verdict:**
1. Flip `_rating_v2`'s default to ON (`scripts/build_soccer_artifacts.py`) and fix the default test.
2. Land on main.
3. Fast-forward the fleet to that exact SHA, under a refresh-worker claim, after the ride-along check (the fleet
   was 65 commits behind main on 2026-10-19).
4. Verify: `rating_model = v2_h40_c40_n5` appears in a newly built `recommendations_<date>.json` for an EPL date.
   The builder is a per-run child job and loads from disk, so no refresh-worker restart is needed. The live
   poller's `_fill_promoted` loads at the next live-odds-worker restart.
5. Record the measurement in `deploys.md`.

## 4. Deviations

- **1. (before the run, `73ba5d79`).** `_rating_v2` was made OFF by default (ON only with
  `SYNDICATE_SOCCER_RATING_V2=1`), so that pushing the code to main could not ship it ahead of this gate. The v2
  arm ran with the env set to 1 and the v1 arm with it set to 0. The code under test is otherwise unchanged
  (`839b9f1b`).
