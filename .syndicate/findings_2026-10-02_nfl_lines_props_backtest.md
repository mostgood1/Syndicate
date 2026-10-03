# NFL game lines + player props backtest (as-of) — 2026-10-02

Lane `nfl-lines-props-backtest` (session 05b01a84). Measurement only: no deploy, no board change.
Harness `scripts/backtest_nfl_lines_props.py` (commit `b2f0ab3b`), same method and table shape as the
NHL props backtest (lane `nhl-player-props-projection`) and the NCAAF twin (lane `ncaaf-lines-props-backtest`).

**Status: COMPLETE** (props 2023-2026 wk2; game lines 2022-2025 + 2026 wks 1-3, 1,135 games simulated
as-of). Full machine-readable outputs, not committed (scratch):
- `C:\tmp\nflbt\final\nfl_lines_props_backtest.{json,md}` (game lines + diagnosis);
- `C:\tmp\nflbt\props5\...` (props + diagnosis).

Reproduce with the commands in the script docstring against a root built as in section 3.

**Game lines in one line:** the sim beats a naive baseline on margin and moneyline but loses to the
close in every market. Its spread/total cover probabilities are worse than a coin flip, because they
are overconfident about disagreements with the line that carry no information (sections 2, 2d).

## 0. Verdict up front

> **USER DECISION 2026-10-02 (~7:05 PM CT, relayed by the NCAAF backtest session and checked against
> the standing rule `feedback_every_line_its_own_decision`, first set 2026-09-22):** "every line is its
> own decision. we should have a model that is accurate that then helps inform each decision". This
> task prompt's rule ("a market earns a probability/edge on the board only if it beats the baseline AND
> the book") was a MARKET-WIDE EXCLUSION and is WITHDRAWN. **This file delivers no gate list and
> recommends no mean-only or probability-withheld market.** The backtest is the DIAGNOSIS: for each
> market that loses, section 7 says WHY, with evidence, and which model change would make it accurate,
> ranked by measured out-of-sample impact. Per-line decisions stay with per-line scoring. The first
> push of this file (`29c7d0c4`) said "nothing earns a probability or edge on the board". That wording
> was wrong by this rule, and this session should have caught it at the start: the rule was in
> MEMORY.md.

**No NFL player-prop market beats BOTH the player's own as-of average AND the de-vigged book. Not one,
in any season.** Every continuous market except interceptions is significantly WORSE than the book on
Brier and log-loss in the pooled 2023-2025 sample. Interceptions shows NO DIFFERENCE, which is not a win.
The lane's hypothesis holds for props, as a statement about the MODEL's accuracy, not as a reason to
hide a market. It matches `measured_market_skill.py` (8 NFL prop entries, all `VERDICT_LOSES`, which
already lower ranking reliability per line and exclude nothing). This run REPLICATES that on the
SHIPPED model, with game-clustered CIs, adds log-loss, and covers 2023 + 2025 + 2026.

Anytime TD is **not** a candidate. Its shrinkage beats the player's raw average by a wide margin. It
still loses to the book's YES price **before** that price is de-vigged, in every historical season.

## 1. What the harness grades, and why the numbers are production's

- **Game lines:** `generate_smartsim2_nfl_projections.build_projection` is CALLED, with 300 seeds, over
  plays before the game's week, under the fleet refresh-worker's NFL env as READ 2026-10-02 from
  `/proc/<pid>/environ` (keys only):
  - `SYNDICATE_NFL_PPG_RATINGS=1`
  - `SYNDICATE_FOOTBALL_SEGMENT_DISTRIBUTIONS=1`
  - every other NFL model knob ABSENT, so code defaults apply: K=4 prior blend, level shrink 0.3, no
    diff correction, no drive priors, no blowout damping.

  The harness refuses to run if any other knob is set.

  **Fidelity: it reproduces production's own `smartsim2_projections_2026_wk4.csv` (written by the fleet
  2026-10-01 21:54Z) EXACTLY.** 16/16 games, every numeric field diff 0.0 (scores, margin, total, both
  sds, win rate), `rating_source` identical. Fleet code `5566d4ba` and `origin/main` carry no diff in
  the NFL model files.
- **Props:** the computed branch of `nfl_props_rows_for_week` is CALLED:
  `resolve_player_id_with_prior` → team check → `player_rate_with_prior` / `anytime_td_rate_with_prior`
  → `nfl_game_context_multiplier` → `_nfl_prop_model_probability`.

  **Selfcheck:** the harness writes one week in the production CSV contract and production returns
  the same probability for every (player, market, line). 0 mismatches over 8,976 rows:
  - 2024 wk5: 4,414 rows
  - 2025 wk12: 2,649 rows
  - 2026 wk2: 1,913 rows
- **Note on `scripts/backtest_nfl_props.py` (claimed by OPEN lane `layer2-triad-alignment`, NOT edited
  here):** its `_rate_from_log` does not apply production's zero-week imputation (`player_rate`,
  `SYNDICATE_NFL_PROP_ZERO_GAMES` absent = ON). It no longer grades the served estimator. This harness
  calls `player_rate` directly. Owed to that lane, not fixed here.

### A defect in my own first run, recorded because the selfcheck did NOT catch it

The first props run had the game-context multiplier at **exactly 1.0 on 100% of rows**. The cause was
the scratch root:

- It had no `upcoming_recs_*.csv`.
- `default_nfl_source_root()` probes for that unrelated file (the `#441` family) and fell through to a
  non-existent `source_artifacts/`.
- So `game_context()` read no schedule.

The production-equivalence selfcheck **still passed**, because harness and production code read the
same mis-resolved root. **An equivalence check proves the CODE matches. It says nothing about whether
the ENVIRONMENT matches.**

On the fleet, `nfl_source/` carries the `upcoming_recs` files, so production's multiplier IS live.

The harness now refuses to run when `game_context()` resolves nothing, and the reported numbers are
from the corrected run. Context is now non-1.0 on ~87% of historical rows. The rest:
- rushing_attempts and anytime_td sit at (0, 0) BY DESIGN.
- The 2026 week-2 rows are 1.0 by design: a player needs 2 prior weeks.

## 2. Game lines: production's sim, as-of, 1,135 games (2022-2025 complete + 2026 wks 1-3)

**Population:** every completed REG game with a projection and a two-sided nflverse close.

- **Drops:** 3 ML ties, 32 spread pushes, 8 total pushes.
- **Baseline (as-of league rates):**
  - margin = league mean home margin;
  - total = league mean total;
  - P(home win) / P(home cover) / P(over) = league rates.

  All of these use the prior season plus this season before the game's week.
- **Book:** proportional de-vig of the nflverse closing ML, spread juice and total juice.

### 2a. 2022-2025 pooled (1,087 games, 72 weeks)

| market | n | model | baseline | book | model − baseline [CI] | model − book [CI] |
|---|---|---|---|---|---|---|
| margin, MAE | 1,087 | 9.99 | 10.71 | 9.49 | **−0.73 [−1.01, −0.45] better** | +0.49 [+0.31, +0.67] worse |
| total, MAE | 1,087 | 10.66 | 10.74 | 10.19 | −0.08 [−0.29, +0.11] no diff | +0.47 [+0.25, +0.71] worse |
| moneyline, Brier | 1,084 | 0.2258 | 0.2486 | 0.2105 | **−0.0228 [−0.0310, −0.0145] better** | +0.0154 [+0.0093, +0.0206] worse |
| spread cover, Brier | 1,058 | 0.2613 | 0.2506 | 0.2498 | +0.0107 [+0.0049, +0.0170] **worse** | +0.0114 [+0.0057, +0.0178] worse |
| total over, Brier | 1,079 | 0.2693 | 0.2500 | 0.2501 | +0.0193 [+0.0103, +0.0285] **worse** | +0.0192 [+0.0105, +0.0277] worse |

**Log-loss vs the book: worse in all three markets.**

| market | dLogLoss model − book [CI] |
|---|---|
| moneyline | +0.035 [+0.022, +0.047] |
| spread | +0.025 [+0.012, +0.038] |
| total | +0.044 [+0.025, +0.063] |

**EV-bet ROI at the close.**

| market | ROI [CI] | bets |
|---|---|---|
| moneyline | −10.8% [−19.5, −2.0] | 919 |
| spread | −2.6% [−8.5, +4.0] | 869 |
| total | −3.6% [−9.8, +2.7] | 960 |

What the table says:

- The sim carries real signal: it beats the naive baseline on margin MAE and on moneyline Brier.
- It loses to the close in every market.
- **Its spread-cover and total-over probabilities are worse than the league-rate baseline**, which is
  a near coin flip. So the probability layer subtracts value that the margin mean has.

Per season, model vs book (dBrier):

| market | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| moneyline | worse | worse | worse | worse |
| spread | no diff | worse | no diff | worse |
| total | worse | worse | no diff | worse |

Margin MAE vs book is worse in 2023, 2024 and 2025; in 2022 it is +0.30 [−0.04, +0.66].

**Consistency with settled work:** the 2025 margin MAE here is 10.45 vs close 9.72. The refusal audit
had 10.495 vs 9.722 on the same season. Same answer, now from the production sim at 300 seeds rather
than the linear rating differential.

### 2b. 2026 in-season (48 games, weeks 1-3)

| market | model | book | model − book [CI] |
|---|---|---|---|
| margin MAE | 11.64 | 10.41 | +1.23 [+0.38, +2.12] |
| total MAE | 12.22 | 11.10 | +1.12 [+0.07, +2.22] |
| moneyline Brier | 0.2586 | 0.2327 | +0.026 [−0.007, +0.059] |
| spread Brier | 0.2933 | 0.2482 | +0.045 [+0.017, +0.077] |
| total Brier | 0.2895 | 0.2500 | +0.039 [−0.000, +0.078] |

- EV-bet ROI on spreads: −36.0% [−65.4, −6.1], 39 bets.
- **These numbers are the CURRENT code re-run as-of, not what the board served in weeks 1-3.** Those
  served files were lost with Render's disk. The fleet copies are the 2026-08-01 preseason backfill.
  Served wk1 was graded on 2026-09-14 (margin 12.59 vs 10.80).

### 2c. Segment lines (1H / 2H / quarters)

**Not gradable.**

- **Prices:** NFL segment prices exist on the fleet (`tracking/book_quotes`, h1/h2/q1-q4 for
  spreads/totals/h2h) only for games commencing 2026-10-02. That is the week-4 Thursday game, which is
  in no as-of results input yet.
- **Projections:** `smartsim2_segment_distributions_2026_wk4/5.json` exist, but no board consumer
  prices NFL segments. Only NCAAF has a segment join.
- **Result:** 0 completed games carry both a projection and a price, so the population is empty.
- **When it becomes gradable:** after week 4 completes, if the capture continues and a consumer
  exists.

## 2d. Game-line diagnosis: WHY each market loses

Every model change is fitted on 2022-2024 and scored on 2025, and again on 2026 wks 1-3, through
`shared/football_cards.cover_probability` (the board's own function).

| market (2025 holdout) | Brier gap | Murphy reliability / resolution, model | same, book | corr(mean, actual): model / close line | gap closed: scale_sd (k) | shift_mean | market-anchored (w) |
|---|---|---|---|---|---|---|---|
| spread cover | 0.0225 | **0.0348** / 0.0125 | 0.0069 / 0.0073 | 0.36 / 0.50 | 81.9% (k = 4.0, grid edge) | −1.8% | 93.3% (w = 0.9) |
| total over | 0.0200 | **0.0319** / 0.0118 | 0.0138 / 0.0129 | 0.13 / 0.30 | 93.9% (k = 4.0, grid edge) | 6.0% | 101.8% (w = 0.9) |
| moneyline | 0.0137 | 0.0061 / **0.0306** | 0.0033 / **0.0369** | 0.36 / 0.50 | −6.3% | −3.5% | 86.1% (w = 1.0) |

2026 wks 1-3 agree, more sharply:
- corr(model margin, actual) 0.08 vs the line's 0.31.
- corr(model total, actual) 0.02 vs the line's 0.46.

**Spread and total: the cover probability is OVERCONFIDENT about disagreements with the line that carry
no information.**
- The sim's own sd matches the spread of actual around its mean (sd ratio 1.00 margin, 0.84 total).
- Its probability AT THE LINE is far too sure. Fitted k runs to the grid edge (4.0), which is a
  probability of ≈ 0.5, i.e. the book's.
- **The cover probability adds nothing the close does not already contain.** Any disagreement it
  expresses is, on average, noise.

**Moneyline: the reverse.**
- Well calibrated (reliability 0.006), but RESOLUTION-deficient: 0.031 vs 0.037. It ranks teams less
  well than the market.
- Recalibration cannot close it; widening makes it worse (−6%). This is the same signature as
  2026-09-08's live-gameline finding.

**Bias: small.**
- Margin: actual − mean = +1.1 in 2025, i.e. home teams under-projected by ~1 point.
- Total: +2.1 in 2025, i.e. totals under-projected after the 0.3 level shrink.
- Shifting closes ≤ 6%. Bias is not the problem.

### Ranked model changes, game lines

| # | change | measured on 2025 holdout | caveat |
|---|---|---|---|
| 1 | **Price the spread/total cover from a predictive distribution that includes the RATING's uncertainty, not only the sim's game-to-game spread.** sd_pred = sqrt(sd_sim² + var(mean error)). The fitted k ≥ 4 says var(mean error) dominates. | closes 82% (spread), 94% (total) of the gap; 2026: 76%, 82% | A probability near 0.5 is the honest answer while the ratings carry no information beyond the close. It removes false confidence, not the gap's cause. Calibrated-engine rule: re-measure after. |
| 2 | **Better ratings: the information the close has.** Ceiling (market-anchored mean) is 86-100% in all three markets. Candidates: QB / key-player availability (injury ingestion exists, but the in-sim injury adjustment HURT, `36cd8a5c`); roster changes; early-season priors (K=4 already shipped). | ceiling only | The rating differential's corr with margin is 0.36 vs the close's 0.50 (2025), and 0.08 vs 0.31 in 2026. This is the binding constraint for the moneyline, where recalibration does nothing. |
| 3 | Remove the residual level bias (+1.1 home margin, +2.1 total in 2025) | ≤ 6% | low value |

## 2e. Coverage for game lines

Every season's intersection is complete:
- 2022: 271 games, 18 weeks.
- 2023-2025: 272 games, 18 weeks each.
- 2026: 48 games, weeks 1-3.

Each needs final scores, pbp, a two-sided close and a projection. Sources:
- **pbp 2026, schedules and closes:** fleet. The closes are nflverse `schedules_games.csv`.
- **pbp 2021-2025:** checkout mirror, plus the nflverse fetch for 2021.

## 3. Coverage: per family, and the intersection each result rests on

| season | final scores (games/wks) | pbp (games/wks) | nflverse close, two-sided ML/spread/total | prop quotes (games/wks) | PROPS INTERSECTION |
|---|---|---|---|---|---|
| 2023 | 272 / 18 | 272 / 18 | 272 / 272 / 272 | 131 / 17 (wk9 absent; ~half the games per week) | **131 games, 17 wks** |
| 2024 | 272 / 18 | 272 / 18 | 272 / 272 / 272 | 235 / 18 | **235 games, 18 wks** |
| 2025 | 272 / 18 | 272 / 18 | 272 / 272 / 272 | 226 / 18 | **226 games, 18 wks** |
| 2026 | 48 / wks 1-3 | 48 / wks 1-3 | 48 / 48 / 48 | **16 / wk 2 only** | **16 games, 1 wk** |

Substrate, per family (substrate-rule):

- **render / fleet (production):**
  - `pbp_2026.csv` (written 2026-10-01 20:46Z)
  - `schedules_games.csv` (21:00Z)
  - `schedule_2026.csv`
  - `smartsim2_projections_2026_wk4.csv`
  - `upcoming_recs_*` (root marker only)

  All were copied 2026-10-02 ~22:39Z with sha256 in `C:\tmp\nflbt\root\nfl_source\FLEET_PROVENANCE.txt`.
- **checkout (untracked mirror in the primary tree):**
  - pbp 2022-2025 (nflverse, re-derivable).
  - prop quotes 2023-2025: `tracking/book_quotes/<s>_wk<N>.jsonl`, OddsAPI HISTORICAL snapshots at
    kickoff-10min, per `backfill_nfl_historical_props.py --offset-minutes 10`. An immutable external
    archive, so the checkout copy is the archive.
- **2026 in-season prop odds are the weakest family:**
  - Render's disk was never exported after the 2026-09-30 billing suspension.
  - The fleet was seeded from git, where every 2026 props CSV is a stub (fleet `wk1` = 6 bytes).
  - The ONLY surviving 2026 capture is the primary tree's untracked `oddsapi_player_props_2026_wk1.csv`
    (mtime 09-29). **It holds WEEK 2** (games 09-18..09-22Z), so it is the NFL-week-self-pins-to-1
    defect in a file name. Its capture time is not recorded; it is treated as pregame because every
    Sunday game is present.
  - **Weeks 1 and 3 of 2026 have no surviving prop prices anywhere.**
- 2022 is excluded:
  - Props: the OddsAPI historical archive starts 2023-05.
  - Game lines: production's K=4 prior-season blend touches EVERY 2022 week, so 2022 needs
    `pbp_2021`. It was fetched 2026-10-02 ~23:15Z on the user's instruction, with the production
    fetcher `scripts/fetch_nfl_pbp.py --season 2021 --only-season` (nflverse release, 47,651 REG
    plays), into the scratch root only. **2022 IS included for game lines.** It is still excluded for
    props (no prices).

## 4. Player props — results

Population: quoted (player, market, game) rows where the player resolves, passes production's team
check, has an as-of rate, and appears in the game's pbp.

Drops, counted (all seasons):
| reason | rows |
|---|---|
| player unresolved (mostly anytime-TD quotes on defenders and others absent from pbp; production refuses them too) | 11,952 |
| no pbp line for the player in the game (void: DNP is indistinguishable from played-and-zero in pbp) | 3,554 |
| player on the wrong team (refused) | 1,552 |
| no model rate | 1,186 |
| player team unknown (refused) | 912 |
| one-sided rows excluded | 849 |

Resolved: 32,038 of 51,194 player-market-games.

Book probability = proportional de-vig of ONE book's over/under. Rows are per book. CIs are 95%,
game-clustered bootstrap (1,000 reps).

### 4a. Historical 2023-2025 pooled (593 games, 53 weeks)

Probability vs the de-vigged book (positive dBrier = model worse):

| market | rows | games | Brier model | Brier book | dBrier model−book [CI] | dLogLoss model−book [CI] | EV-bet ROI [CI] | vs book |
|---|---|---|---|---|---|---|---|---|
| passing_yards | 13,492 | 583 | 0.2754 | 0.2396 | +0.0358 [+0.0270, +0.0465] | +0.1350 [+0.0976, +0.1785] | −12.6% [−18.3, −6.8] | WORSE |
| passing_attempts | 6,798 | 577 | 0.2793 | 0.2499 | +0.0295 [+0.0192, +0.0399] | +0.1017 [+0.0673, +0.1390] | −7.4% [−13.6, −1.4] | WORSE |
| passing_tds | 8,779 | 585 | 0.2381 | 0.2318 | +0.0063 [+0.0016, +0.0112] | +0.0139 [+0.0039, +0.0244] | −3.8% [−10.4, +3.0] | WORSE |
| rushing_yards | 26,634 | 588 | 0.2667 | 0.2415 | +0.0253 [+0.0199, +0.0308] | +0.0856 [+0.0670, +0.1047] | −4.7% [−8.2, −1.6] | WORSE |
| rushing_attempts | 9,863 | 581 | 0.2692 | 0.2479 | +0.0213 [+0.0145, +0.0292] | +0.0791 [+0.0551, +0.1049] | −1.7% [−6.1, +2.6] | WORSE |
| receptions | 43,091 | 589 | 0.2611 | 0.2384 | +0.0227 [+0.0184, +0.0270] | +0.0709 [+0.0576, +0.0833] | −5.8% [−8.7, −3.0] | WORSE |
| receiving_yards | 59,290 | 590 | 0.2633 | 0.2403 | +0.0230 [+0.0190, +0.0266] | +0.0756 [+0.0637, +0.0877] | −5.6% [−8.4, −2.8] | WORSE |
| interceptions | 6,557 | 584 | 0.2442 | 0.2412 | +0.0030 [−0.0001, +0.0059] | +0.0061 [−0.0004, +0.0120] | −7.1% [−15.0, +0.5] | NO DIFFERENCE |

Point accuracy, one row per (player, market, game). The baseline is the player's own as-of average =
production's estimator with the context multiplier OFF. **For NFL, "model vs own average" therefore
measures exactly one thing: the game-context term.**

| market | n | MAE model | MAE own-avg | dMAE vs own-avg [CI] | MAE book line | dMAE vs book line [CI] | dMAE vs last-4 avg [CI] |
|---|---|---|---|---|---|---|---|
| passing_yards | 1,110 | 65.30 | 65.70 | **−0.39 [−0.80, −0.02]** | 55.66 | +9.54 [+7.49, +11.75] | −2.19 [−3.81, −0.50] |
| passing_attempts | 1,092 | 8.12 | 8.17 | −0.05 [−0.12, +0.02] | 6.94 | +1.15 [+0.87, +1.45] | −0.12 [−0.31, +0.07] |
| passing_tds | 1,115 | 0.934 | 0.939 | −0.006 [−0.012, +0.000] | 0.933 | +0.001 [−0.024, +0.027] | −0.045 [−0.065, −0.023] |
| rushing_yards | 2,951 | 19.68 | 19.78 | −0.11 [−0.21, +0.00] | 17.91 | +1.86 [+1.46, +2.30] | −0.68 [−1.02, −0.35] |
| rushing_attempts | 2,383 | 3.40 | 3.40 | 0 (no context term by design) | 3.00 | +0.40 [+0.31, +0.49] | −0.01 [−0.08, +0.05] |
| receptions | 5,840 | 1.596 | 1.597 | −0.002 [−0.004, +0.000] | 1.529 | +0.068 [+0.047, +0.086] | −0.031 [−0.051, −0.011] |
| receiving_yards | 6,173 | 21.11 | 21.15 | −0.04 [−0.08, +0.01] | 19.76 | +1.38 [+1.14, +1.60] | −0.90 [−1.15, −0.64] |
| interceptions | 1,107 | 0.712 | 0.713 | −0.001 [−0.004, +0.002] | 0.694 | +0.018 [−0.003, +0.037] | −0.005 [−0.020, +0.011] |

What this table says:

- **The book line is a better point forecast than the model in 6 of 8 markets** (CI excludes 0).
  passing_tds and interceptions are ties.
- **The context term is real but tiny.**
  - Point: significant only for passing_yards (−0.39 yards).
  - Probability, vs own average:

    | market | dBrier vs own-avg [CI] |
    |---|---|
    | passing_yards | −0.0027 [−0.0045, −0.0008] |
    | passing_tds | −0.0014 [−0.0023, −0.0006] |

    Others are inside noise.
  - The gap to the book is ~10x larger than anything the context term closes.
- **Season-to-date beats last-4** in 5 of 8 markets, and is never worse. A more "recent" average is not
  the missing ingredient.
- **The model is biased LOW on every yardage market** (pooled bias −12.6 passing, −2.2 rushing, −3.0
  receiving yards). Pre-registered prior: `findings_2026-09-28_nfl_mean_bias.md` says the estimator is
  unbiased over all players and the apparent over-prediction there is selection. **On the QUOTED
  population the sign is the opposite (under-prediction).** That is the same mechanism, selection, in
  the other direction: books list players whose role is rising. Not chased here.

Per season, vs the book (dBrier verdict):

| market | 2023 (132 g) | 2024 (235 g) | 2025 (226 g) |
|---|---|---|---|
| passing_yards | WORSE | WORSE | WORSE |
| passing_attempts | no diff | WORSE | WORSE |
| passing_tds | no diff | no diff | WORSE |
| rushing_yards | WORSE | WORSE | WORSE |
| rushing_attempts | WORSE | WORSE | WORSE |
| receptions | WORSE | WORSE | WORSE |
| receiving_yards | WORSE | WORSE | WORSE |
| interceptions | no diff | WORSE | no diff |

Consistency with the one prior measurement (`log/2026-09-29.md`, 2024, scratch scripts, model version
unverified): receiving_yards +0.0226 there vs **+0.0240** here (2024, shipped model). It is the same
answer, now on the shipped code.

### 4b. Anytime TD (one-sided)

Only 385 rows (2023, 58 games) carry a NO price; 2024, 2025 and 2026 have none. So the book comparison
uses the YES price **with its vig still in it**. That overstates P(score) and should make the BOOK look
worse.

| group | rows | games | Brier model (shrunk rate) | Brier own raw avg | dBrier model−own [CI] | Brier book (vig-INCLUSIVE) | LogLoss model / book |
|---|---|---|---|---|---|---|---|
| 2023 | 15,882 | 132 | 0.1635 | 0.1824 | −0.0189 [−0.0248, −0.0135] | 0.1552 | 0.5045 / 0.4806 |
| 2024 | 24,549 | 235 | 0.1674 | 0.1923 | −0.0248 [−0.0294, −0.0200] | 0.1613 | 0.5144 / 0.4952 |
| 2025 | 26,964 | 226 | 0.1659 | 0.1951 | −0.0292 [−0.0348, −0.0237] | 0.1544 | 0.5106 / 0.4781 |
| **2023-25 pooled** | **67,395** | **593** | **0.1659** | **0.1910** | **−0.0252 [−0.0284, −0.0219]** | **0.1571** | **0.5106 / 0.4849** |
| 2026 wk2 | 1,720 | 16 | 0.1435 | 0.1591 | −0.0156 [−0.0275, −0.0038] | 0.1469 | 0.4583 / 0.4645 |

On the 385 de-viggable 2023 rows: model vs de-vigged book dBrier **+0.0119 [+0.0037, +0.0209]**, worse.

- **`#471`'s shrinkage is validated again:** it beats the player's raw own rate in every season.
- **It loses to even the vig-inclusive book price in every historical season**, so de-vigging cannot
  rescue it. Paired, game-clustered, model minus vig-inclusive book:

  | group | dBrier [CI] | dLogLoss [CI] |
  |---|---|---|
  | 2023 | +0.0083 [+0.0047, +0.0120] | +0.0239 [+0.0142, +0.0337] |
  | 2024 | +0.0062 [+0.0033, +0.0091] | +0.0192 [+0.0117, +0.0269] |
  | 2025 | +0.0115 [+0.0086, +0.0143] | +0.0326 [+0.0238, +0.0405] |
  | **pooled** | **+0.0088 [+0.0069, +0.0106]** | **+0.0257 [+0.0205, +0.0308]** |
- 2026 wk2 (16 games): dBrier −0.0034 [−0.0127, +0.0059], NO DIFFERENCE. That is one week, not a
  reversal.

### 4c. 2026 in-season (week 2 only: 16 games)

| market | rows | dBrier model−book [CI] | verdict |
|---|---|---|---|
| receptions | 442 | +0.0498 [+0.0179, +0.0854] | WORSE |
| receiving_yards | 563 | +0.0401 [+0.0148, +0.0692] | WORSE |
| passing_yards | 184 | +0.0455 [−0.0213, +0.1201] | no diff |
| passing_attempts | 97 | +0.0205 [−0.0485, +0.0948] | no diff |
| passing_tds | 171 | +0.0321 [−0.0071, +0.0832] | no diff |
| rushing_yards | 304 | +0.0020 [−0.0349, +0.0515] | no diff |
| rushing_attempts | 58 | +0.0840 [−0.0167, +0.1789] | no diff |
| interceptions | 94 | +0.0101 [−0.0139, +0.0286] | no diff |

Every point estimate is on the model-worse side. 16 games cannot clear a CI for most markets. This is
NOT a 2026 verdict; it is one week. Weeks 1 and 3 are unrecoverable (section 3).

## 5. What the daily scorecard covers, and what it misses

`run_weekly_backtests.py` re-runs `backtest_nfl_props.py` on Mondays. `_summ_nfl_props` keeps:
- MAE vs a CONSTANT per-market mean;
- synthetic-ladder Brier vs actual;
- an always-empty real-market section.

It has no book price, no de-vig, no CI, no own-average baseline, no anytime-TD-vs-price, and no game
lines at all. It also grades a rate function that has drifted from production (section 1). **It cannot
produce the verdict in this file.** This harness can, in ~15 min for props.

## 7. Props diagnosis: WHY each market loses, and what would make it accurate

**Method.** Each candidate model change is FITTED on 2023-2024 and SCORED on held-out 2025 and on 2026
wk2, through production's own `_nfl_prop_model_probability` on the same rows. "Gap closed" is the
share of the model-minus-book Brier gap removed on the held-out rows. The arms:

- `shift_mean`: add the fitted bias to the mean.
- `scale_sd`: multiply the spread by a fitted k, grid 0.4..4.0. The first grid (0.7..2.0) put k at its
  edge in 5 markets, so it was widened and re-run.
- `shift_and_scale`: both of the above.
- `market_anchored_mean`: mean' = (1−w)·mean + w·book line, w fitted. This is the CEILING on what
  information the model's inputs lack, NOT a recommendation to copy the book.

Plus a Murphy split of Brier (10 equal-count bins). The table below is the 2025 holdout. On 2026 wk2 (16
games), the spread result replicates for receptions (62.6% closed at k=3.0) and receiving yards (57.7%
at k=2.5). The other 2026 markets have n < 200 and wide CIs; all 2026 numbers are in the JSON.

| market | n (2025) | Brier gap vs book | Murphy reliability: model / book | bias, actual−mean (% of mean) | gap closed: scale_sd (k) | shift_mean | shift+scale | market-anchored (w) |
|---|---|---|---|---|---|---|---|---|
| receiving_yards | 15,148 | 0.0302 | 0.0294 / 0.0001 | +1.96 (6.3%) | **55.8% (k=2.5)** | −1.2% | **71.9%** | 69.1% (w=0.8) |
| receptions | 14,126 | 0.0254 | 0.0226 / 0.0009 | +0.15 (5.1%) | **73.7% (k=3.0)** | 0.5% | **74.9%** | 71.2% (w=0.8) |
| rushing_yards | 7,376 | 0.0243 | 0.0257 / 0.0008 | +2.64 (8.3%) | 29.0% (k=2.0) | −4.9% | 39.4% | **89.0% (w=0.9)** |
| rushing_attempts | 3,805 | 0.0192 | 0.0186 / 0.0016 | +0.70 (8.8%) | 27.1% (k=2.0) | 10.3% | 53.8% | **87.2% (w=1.0)** |
| passing_yards | 3,195 | 0.0451 | 0.0498 / 0.0033 | +12.98 (6.1%) | 20.0% (k=1.75) | 12.2% | 35.8% | **97.0% (w=1.0)** |
| passing_attempts | 2,739 | 0.0281 | 0.0384 / 0.0082 | +1.98 (6.1%) | 3.3% | 20.5% | 31.7% | **85.8% (w=1.0)** |
| passing_tds (Poisson) | 3,189 | 0.0091 | 0.0086 / 0.0015 | +0.06 (4.4%) | n/a (no spread) | **17.6%** | 17.6% | 6.6% |
| interceptions (Poisson) | 2,356 | 0.0015 (CI spans 0) | 0.0037 / 0.0033 | +0.09 | n/a | 0.8% | 0.8% | −30% |
| anytime_td | 26,964 | 0.0115 vs vig-INCLUSIVE yes price | 0.0024 / 0.0008 | mean p 0.265 vs observed 0.223 | — | recalibration ×0.95 closes 9% | — | — |

### What the evidence says, market by market

1. **It is a RELIABILITY failure, not a resolution one, in every continuous market.** The model's
   Murphy reliability term is 10-300x the book's. Its resolution is at or above the book's: receiving
   yards 0.0012 vs 0.0003, rushing yards 0.0022 vs 0.0004. This is the OPPOSITE of the 2026-09-08
   game-line finding (resolution deficit, recalibration hopeless). **Here a calibration-type change CAN
   close most of the gap, and does out of sample.**
2. **Receptions / receiving yards: the predictive spread at the line is 2.5-3x too narrow.** Widening
   alone closes 56-74% on 2025 AND 57-63% on 2026 wk2, with k fitted on 2023-24. The mean barely
   matters: shift_mean does ~0%. This is the 2026-09-28 `[nfl-prop-distribution-too-narrow]` finding
   (spread 0.21-0.65x of plausible), now measured as Brier closed on a holdout. Note also
   `sd_ratio_model/empirical` ≈ 0.9: the model's sd matches the spread of actual around its mean
   OVERALL. What is too narrow is the uncertainty about the MEAN, at the price where the model
   disagrees with the line. The predictive sd must carry estimation error in the rate (role/usage
   drift), not only game-to-game noise.
3. **Rushing / passing volume (rushing_yards, rushing_attempts, passing_yards, passing_attempts): the
   MEAN is missing information.** Anchoring the mean on the line closes 86-97%, and at w = 0.9-1.0 the
   residual vs the book is inside noise for passing_yards (+0.0014 [−0.0007, +0.0032]) and
   rushing_yards (+0.0027 [−0.0011, +0.0064]). Widening closes only 20-29%.
   - What the book has that a season-to-date rate does not: role and usage changes, depth chart,
     injuries (own and teammates'), game script, opponent.
   - QB volume is also biased LOW on the quoted population, by +13.0 yards and +2.0 attempts (6%).
     shift_mean closes 12-21%.
4. **passing_tds: a bias problem.** The Poisson rate is under-projected by 0.12 TDs on the quoted
   population, and the shift closes 18%. The distribution family is right; 2026-09-28 already measured
   Poisson dispersion at 0.925.
5. **interceptions: at parity.** The gap is not significant in any season. No change needed.
6. **anytime TD: a RESOLUTION deficit.** The model's resolution is 0.0096 vs the book's 0.0189 in
   2025, so it discriminates scorers about half as well as the book. It is also mis-levelled (mean p
   0.265 vs 0.223 observed), but recalibration closes only 9%.
   - Needed: information, i.e. red-zone / goal-line role and the team's implied total.
   - The game-context term ships at (0, 0) for this market because its alpha was fitted on the raw
     rate, not the shrunk one (`props.py` comment). Re-fitting it against the shrunk estimator is
     already owed and is the cheapest first step.

### Ranked model changes (by measured out-of-sample Brier closed, weighted by market volume)

| # | change | markets | measured on 2025 holdout | cost / caveat |
|---|---|---|---|---|
| 1 | **Widen the predictive spread to carry rate uncertainty:** sd' = k·sd, k≈2.5-3 for receptions/receiving yards, ≈2 for rushing, ≈1.75 for passing yards. Better: an explicit sd = sqrt(sd_game² + var(rate estimate)) | receptions, receiving_yards (102,381 of 174,504 = 59% of continuous-market rows, 2023-25); partial elsewhere | 56-74% of the gap closed (receptions, receiving); 20-29% (rushing, passing yards) | k is a fitted MECHANISM on a calibrated engine: `model_engine_standard.md` requires re-fitting `_COVER_PROBABILITY_BLEND_WEIGHT` and the spread-shrinkage k on top of it, then a re-measure. It interacts with 09-28's `SPREAD_SHRINKAGE_K=6`, which pulls the other way. |
| 2 | **Give the mean the inputs the line carries:** snap/route/target share and carries trend; depth chart and injury status (the NFL injury and depth-chart ingestion autoruns already exist, `[nfl-data-ingestion-autoruns]`); teammate-out usage redistribution | rushing_*, passing_* most; all continuous | ceiling 86-97% (anchored arm) | Real modelling work. The anchored arm is the ceiling, not the result. Using the line itself as a prior is a legitimate pregame input and would close most of it, but it removes the model's independence by construction. That trade-off is a user decision. |
| 3 | **De-bias the QB volume mean on the quoted population:** +2.0 attempts, +13 yards, +0.12 TDs on 2025 | passing_yards, passing_attempts, passing_tds | 12-21% | Find the cause before shifting: suspect the zero-week imputation's QB floor (`_QB_PASSING_ATTEMPTS_FLOOR`) and early-exit games pulling the season average down. A blind shift is the "fit the number, not the mechanism" trap. |
| 4 | **Anytime TD: re-fit the game-context alpha against the shrunk estimator, then add red-zone role** | anytime_td | recalibration alone 9%; the rest is resolution | Owed already (props.py comment on `_NFL_GAME_CONTEXT_PARAMS`). |
| — | interceptions | — | at parity | nothing |

## 6. Disposition (no board change made, no deploy)

- Per the user decision at the top: no market is withheld, made mean-only, or gated. The board keeps
  showing every line. The fix is to make the model accurate (section 7). Each line's own scoring
  (fee-net EV, price quality, the measured-skill reliability term) decides what it does.
- The open question this does NOT answer: the 09-28 diagnosis says the residual is a
  distribution-family problem. This file says the MEAN already loses to the book line by 4-17% of MAE in 6
  markets (receptions 4%, receiving yards 7%, rushing yards 9%, rushing attempts 12%, passing
  attempts 15%, passing yards 17%). A better distribution cannot fix a worse centre.
