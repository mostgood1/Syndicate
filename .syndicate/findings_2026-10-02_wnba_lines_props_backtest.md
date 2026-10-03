# FINDINGS — WNBA game lines and player props, as-of backtest vs a naive baseline AND the de-vigged book

**Lane** `wnba-lines-props-backtest`, session `39b666bb-e708-4edf-bfe5-3dda419e3589`. **Date** 2026-10-02/03.
**Harness** `scripts/backtest_wnba_lines_props.py` (+ `tests/test_backtest_wnba_lines_props.py`, 10 pass).
**Method** mirrors lane `nhl-player-props-projection` (`scripts/backtest_nhl_props.py`, 0f25d513): same tables, same
game-clustered bootstrap (2,000 reps), every input AS-OF. **No deploy, no board change.**

> **FRAMING — USER DECISION, recorded 2026-10-02 (relayed by the NCAAF backtest session, verified against the user's
> own words in memory `feedback-every-line-its-own-decision`):** *"every line is its own decision. we should have a
> model that is accurate that then helps inform each decision."* The task prompt asked for a market-level **gate list**
> (probability/edge only for markets that beat the baseline AND the book). **That is a market-wide exclusion and is
> not delivered.** Every number below is a DIAGNOSIS: which reference the model beats, WHY it misses, and the model
> change that would fix it, ranked. Per-market skill is evidence for a per-line edge weight / skill-registry
> multiplier, never a switch.

---

## 0. Headline

1. **Nothing WNBA models pregame beats the de-vigged book on any market**, regular season, 331 games. One cell of
   213 labelled cells beats both baseline and book — fewer than chance — and it does not reproduce (section 6).
2. **The 08-31 "moneyline asset" was the market's discrimination, not the sim's.** Re-measured against the BOOK on
   the same rows (the 08-31 comparator was climatology): served sim AUC **0.790 vs book 0.825**, Brier **0.185 vs
   0.173** (n=119). Today's code (as-of re-run, 331 games): AUC **0.770 vs 0.763**, dBrier **+0.0011 [−0.0043,
   +0.0061]** — a tie, because the sim is **95% the market spread by construction** (pre-sim market anchor). The raw
   ridge model alone is **worse** than the book: AUC 0.676 vs 0.763, dBrier **+0.029 [+0.013, +0.044]**.
3. **Every player-prop market is worse than the player's own as-of average AND worse than the book**, on both the
   served artifacts and today's code. Three measured causes: **minutes under-projected by −2.96 per player**
   (starters most), **distributions 1.39–1.58× too narrow** (80% intervals cover 58–73%), and **per-minute rates
   whose departures from the player's average are ~80% noise** (signal slope 0.16–0.27).
4. **The board's season of spreads/totals (−9.68%, n=105) was never significant**: CI **[−29.2%, +8.8%]**. The
   number reproduces 08-31 exactly; the CI is new.
5. **Production instruments**: the weekly WNBA backtest refuses for two reasons (lost Render artifacts, and an ESPN
   tri-code join that matches 0 games even when a projection exists); the daily scorecard grades **0 pregame WNBA
   cells** — all 49 WNBA cells are live-phase and 4 have any games.

---

## 1. Substrates, coverage and the intersection each result rests on

Render is suspended (2026-09-30) and its disks were not exported (user decision, `local_production_runbook.md`), so
production's own pregame WNBA artifacts for most of 2026 no longer exist. Two arms, never pooled:

| arm | what it is | substrate | games (reg / playoff) |
|---|---|---|---|
| **served** | production's artifacts AS STORED | Render pulls saved by sessions a1e40980 (`/api/ops/artifacts/export`, read 2026-09-19), 4a583d41 (09-17), the git mirror's Syndicate root (05-29..06-14), the fleet (09-30..10-01) | **119 / 2** on 44 dates |
| **as-of re-run** | TODAY's production path re-run per date on a scratch copy, every history input truncated to games strictly before D | fleet code `9a7f0d2f`, fleet data copied to `~/wnba_bt/pristine` (fleet disk read-only); a local run is evidence about the CODE, not the deployment (`[substrate-rule]`) | **331 / 9** on 116 dates |

Per-family coverage over the 116 scored dates (2026-05-08..10-01):

| family | dates | games | substrate |
|---|---|---|---|
| finals + quarter linescores | 116 | 340 | ESPN public scoreboard, fetched 2026-10-02 |
| player box scores (actuals, as-of averages) | 113 | 331 | fleet `boxscores_<d>.csv`; team sums = ESPN finals on **331/331** |
| book (pregame) | 116 | 340 | **OddsAPI historical, tip −60 min, fetched 2026-10-02 — 94,458 credits, user-approved**; 340/340 events matched |
| as-of predictions / SmartSim | 116 / 116 | 340 / 340 | re-run, 0 failed dates |
| served SmartSim / game_cards | 44 / 44 | 122 | as above; 5 sims had no final match |

**Gaps, stated:** 9 games (05-25..05-28) have no box score → no prop rows. Double-double / triple-double are quoted
**one-sided (Yes only)** by every book in the snapshot (6,790 / 1,117 one-sided quotes), so they cannot be de-vigged
and are unmeasured vs the book. H2 spreads/totals are not offered. Playoffs are **9 games** and every playoff cell is
`insufficient` (min_n 30). The git mirror's vendor root (`source_artifacts`) was excluded throughout
(`[wnba-two-artifact-roots]`).

**What the re-run is NOT:** the code is today's, not the SHA production ran per date; the ridge/ONNX weights are a
single 2026-05-25 commit fit on ~867 pre-2026 games (never retrained in production); pregame injuries, expected
minutes, rotation/lineup history and `league_status` are absent — as they were for most of production's season — and
each falls back as production does. `home_court_advantage.json`, `lineup_*.parquet`, `team_period_shares.csv` and
`team_advanced_stats_*` were removed because each is fit on the full season.

---

## 2. Game lines

### 2a. As-of re-run (today's code), regular season, 331 games / 112 dates

Point accuracy (naive baseline = HCA + half the as-of net-rating difference; total = mean of the four as-of PF/PA):

| market | n | bias | MAE model | MAE team baseline | dMAE vs team [95% CI] | MAE book line | dMAE vs book [CI] |
|---|---|---|---|---|---|---|---|
| full margin (anchored sim) | 307 | −0.60 | 9.770 | 10.531 | **−0.761 [−1.272, −0.282]** | 9.808 | −0.038 [−0.154, +0.079] |
| full total (anchored sim) | 307 | −2.00 | 14.857 | 15.339 | **−0.482 [−0.816, −0.122]** | 14.604 | +0.253 [−0.030, +0.529] |
| full margin, **raw ridge** | 307 | −1.69 | 10.897 | 10.531 | +0.366 [−0.063, +0.819] | 9.808 | **+1.089 [+0.559, +1.606]** |
| full total, **raw ridge** | 307 | **−8.22** | 16.963 | 15.339 | **+1.625 [+0.785, +2.467]** | 14.604 | **+2.359 [+1.378, +3.260]** |

Probability vs the de-vigged book (same rows, pushes excluded):

| market | n | Brier model | Brier book | dBrier [95% CI] | note |
|---|---|---|---|---|---|
| full ML (sim) | 331 | 0.1981 | 0.1970 | +0.0011 [−0.0043, +0.0061] | AUC 0.770 vs 0.763 |
| full ML (raw ridge) | 331 | 0.2263 | 0.1970 | **+0.0293 [+0.0134, +0.0441]** | AUC 0.676 vs 0.763 |
| full spread | 328 | 0.2500 | 0.2503 | −0.0003 [−0.0039, +0.0029] | |
| full total | 330 | 0.2545 | 0.2499 | +0.0046 [−0.0020, +0.0110] | |
| H1 ML / spread / total | 319 / 331 / 330 | 0.2177 / 0.2496 / 0.2582 | 0.2120 / 0.2498 / 0.2504 | +0.0057 [+0.0004, +0.0105] / −0.0001 / +0.0078 [−0.0032, +0.0188] | |
| Q1 ML / spread / total | 315 / 330 / 330 | 0.2326 / 0.2524 / 0.2504 | 0.2298 / 0.2501 / 0.2492 | all CIs straddle 0 | |
| **Q2 total** | 330 | 0.2627 | 0.2501 | **+0.0126 [+0.0042, +0.0213]** | |
| **Q3 total** | 330 | 0.2637 | 0.2506 | **+0.0131 [+0.0046, +0.0211]** | |
| Q4 ML / spread / total | 316 / 326 / 326 | 0.2421 / 0.2495 / 0.2545 | 0.2454 / 0.2511 / 0.2503 | all CIs straddle 0 | |

Since 09-01 (the slice 08-31 could not see; 30 games): sim ML AUC 0.867 vs book 0.860, dBrier +0.0048 [−0.0075,
+0.0178]; spread +0.0055 [−0.0057, +0.0170]; total +0.0061 [−0.0131, +0.0256]. Same picture.

### 2b. Served (production as stored), regular season, 119 games / 42 dates

| market | n | Brier model | Brier book | dBrier [CI] | |
|---|---|---|---|---|---|
| full ML | 119 | 0.1852 | 0.1734 | +0.0118 [−0.0106, +0.0371] | AUC 0.790 vs **0.825** |
| full spread | 118 | 0.2887 | 0.2500 | +0.0387 [−0.0043, +0.0818] | |
| full total | 118 | 0.3192 | 0.2499 | **+0.0693 [+0.0234, +0.1129]** | served total bias **+11.07** (May +45, Jun +15.6, Aug +6.0) |

Before 08-19 (80 games) the served sim was worse than the book on ML (+0.032 [+0.002, +0.062]), spread (+0.084) and
total (+0.093). Its margin MAE was 14.29 vs book 8.59.

### 2c. WHY the game lines miss (as-of re-run, 331 games)

- **The anchor makes the sim the market.** `_apply_market_anchor_local`: margin = 0.95 × market + 0.05 × model;
  total = 0.70 × market + 0.30 × model. Anchored margin MAE **9.79** against book **9.85**; raw model **10.96**.
- **And the raw model has nothing to add.** Slope of (actual − book) on (raw model − book): **margin 0.073, total
  −0.036**. Its departures from the line are noise, so lowering the anchor today would make the board WORSE. The
  anchor is hiding the model, not suppressing an edge.
- **Total level.** The raw ridge model sits at ~166 against 2026's 174: bias **−8.22** over 307 games. It predicts the
  pre-2026 scoring environment it was trained on. `calibration_totals` (lane `wnba-game-total-level`, 10-01) corrects
  the level inside the sim (anchored bias −2.0). The ridge's own `predictions_<D>.csv` total is still off by −8.
- **Period totals.** Q2 and Q3 totals are worse than the book (+0.013, both CIs exclude 0) while Q1/Q4 are not. This
  is a quarter-split problem in the sim's period shares.
- **Expansion clubs (TOR, POR)** are no worse for the model than for the book in the re-run (margin MAE 10.07 vs
  10.09, n=85). In the served arm they were (15.47 vs 8.91, n=32), so today's code fixed that, through the anchor.
- **Inputs absent all season:** pregame injuries (`raw/injuries.csv` holds only 10-01..10-02), expected minutes and
  rotation history (only from 09-17/09-30). The book prices those; the model cannot.

---

## 3. Player props

Priced markets (OddsAPI, two-sided): points, rebounds, assists, threes, PRA, PR, PA, RA. Blocks, steals and turnovers
are **not priced**. DD/TD are one-sided only (section 1).

### 3a. As-of re-run (today's SmartSim, the board's own ladder method), regular season, 331 games

| market | n | bias | MAE model | MAE own avg | dMAE vs own avg [CI] | book n | Brier model / book / own-avg normal | dBrier vs book [CI] |
|---|---|---|---|---|---|---|---|---|
| points | 4,618 | −1.51 | 4.740 | 4.436 | **+0.304 [+0.225, +0.380]** | 2,866 | 0.3006 / 0.2495 / 0.2659 | **+0.051 [+0.042, +0.060]** |
| rebounds | 4,618 | −0.42 | 1.911 | 1.795 | **+0.116 [+0.087, +0.147]** | 2,448 | 0.2888 / 0.2441 / 0.2560 | **+0.045 [+0.036, +0.054]** |
| assists | 4,618 | −0.54 | 1.409 | 1.312 | **+0.097 [+0.073, +0.122]** | 1,804 | 0.3029 / 0.2483 / 0.2545 | **+0.055 [+0.042, +0.067]** |
| threes | 4,618 | −0.02 | 0.857 | 0.802 | **+0.055 [+0.045, +0.065]** | 1,852 | 0.2545 / 0.2417 / 0.2513 | **+0.013 [+0.006, +0.020]** |
| PRA | 4,618 | −2.48 | 6.282 | 5.767 | **+0.516 [+0.412, +0.616]** | 2,023 | 0.3391 / 0.2497 / 0.2662 | **+0.089 [+0.077, +0.103]** |
| PR | 4,618 | −1.93 | 5.738 | 5.295 | **+0.443 [+0.351, +0.532]** | 2,308 | 0.3225 / 0.2501 / 0.2665 | **+0.072 [+0.061, +0.084]** |
| PA | 4,618 | −2.06 | 5.306 | 4.902 | **+0.404 [+0.308, +0.495]** | 1,817 | 0.3244 / 0.2498 / 0.2650 | **+0.075 [+0.062, +0.087]** |
| RA | 4,618 | −0.97 | 2.598 | 2.476 | **+0.123 [+0.082, +0.161]** | 1,478 | 0.3072 / 0.2491 / 0.2557 | **+0.058 [+0.045, +0.072]** |

The props **ridge mean on its own** (`pred_*`, before SmartSim overwrites it; 5,685 rows) is indistinguishable from the
player's own average: points +0.047 [+0.001, +0.092], rebounds +0.017 [−0.004, +0.038], assists +0.010 [−0.004,
+0.024], PRA +0.035 [−0.033, +0.106]. **The sim makes the mean worse than the model it starts from.**

Since 09-01 (30 games) and playoffs (9 games) say the same: points dMAE +0.427 [+0.170, +0.690] / +0.513 [+0.216,
+0.808]; PRA +0.825 / +0.758.

### 3b. Served (production as stored), 119 games

All eight markets are worse than own average (points +0.517 [+0.389, +0.647], PRA +0.696) and worse than the book
(points dBrier +0.064, rebounds +0.081, PRA +0.075). **The 08-19..10-01 zero-filled-features window (`#477`, 64/140
props features) is NOT visible in the served sim's props**: points dMAE +0.574 before 08-19 vs +0.412 after, rebounds
+0.293 vs +0.346. The served prop mean came from SmartSim, which was already worse than the average before the
features went slim. `0417e1c9` fixed a real defect in the ridge, but it was not the binding one on the board.

### 3c. WHY the props miss (as-of re-run, 4,618 player-games), and how much each cause costs

| cause | evidence | size |
|---|---|---|
| **1. Minutes under-projected** | sim `min_mean` bias **−2.96 min/player** (own-avg −0.09); minutes MAE 5.22 vs 4.66. Worst for starters: points bias **−3.65** for 25+ min players (own avg −1.86) | Substituting ACTUAL minutes into the sim's own rate cuts points bias **−1.51 → −0.27** and MAE 4.74 → 4.00. Minutes are most of the bias |
| **2. Distributions too narrow** | residual sd / sim sd: points **1.39**, reb **1.41**, ast **1.45**, threes 1.23, PRA **1.58**; 80% intervals cover **67% / 69% / 73% / 84% / 58%** | The main Brier gap to the book. Combos are worst: component draws are not correlated the way real games are |
| **3. Per-minute rates are noisy** | slope of (actual − own avg) on (sim − own avg): points **0.17**, reb **0.22**, ast **0.16**, threes **0.27**, PRA **0.21**. Served: 0.01–0.07 | Even with actual minutes, the sim rate's MAE (4.00) is worse than the player's own as-of rate (3.73). ~80% of each departure from the average is noise |
| 4. Inputs the book has | no pregame injuries, expected minutes or rotations for most of the season | Not separable here; it shows up as cause 1 |

The **own-average normal** (the player's mean, with sd from their own as-of history) also loses to the book: points
0.2659 vs 0.2495. Getting the mean right is therefore necessary but not sufficient. The book holds information
(injury and minutes news) that no as-of history has.

---

## 4. Re-measuring the 2026-08-31 assessment — what changed

| 08-31 claim | re-measured | verdict |
|---|---|---|
| "ML sim is the best pregame asset, AUC 0.7631, Brier skill +16.5%" (vs **climatology**) | vs the **book** on the same rows: served AUC 0.790 / book **0.825**; as-of 0.770 / 0.763, dBrier +0.0011 [−0.004, +0.006]; raw ridge worse than the book (+0.029, CI excludes 0) | **OVERTURNED.** The discrimination belongs to the market. Climatology was the wrong comparator; the 09-19 re-measure (ML −0.036 log-loss, 1.1 SE) pointed the same way |
| "board spreads/totals lose, −9.68% (n=105)" | reproduced exactly: 50-55, −9.68%, **CI [−29.2%, +8.8%]**; ATS −10.6% [−36.7, +19.2], TOTAL −8.8% [−33.1, +13.1] | **Not significant.** The point estimate stands; "lose" was never established |
| "props break-even, +3.32%" | served prop P(over) is worse than the book on every market (dBrier +0.036..+0.081) | The prob was never informative; break-even ROI was the vig-adjusted coin |
| "sim totals are a strictly worse estimator than the line" | served: yes (MAE 18.4 vs 13.2, bias +11.1). Today's code: total MAE 14.86 vs book 14.60, dMAE +0.25 [−0.03, +0.53] | **Fixed in level** (totals calibration + anchor). The model now equals the line rather than beating it |
| ML recs: 2 of 466 | both on the **vendor root**; 0 on the Syndicate root. Since 08-31 on the fleet: 12 picks on 09-30..10-02, ATS 3 / props 9 (3 unpriced "OVER −") / ML 0 / TOTAL 0 | Totals withholding is in force; ML is still never chosen |
| "every confidence field is anti-informative" | consistent: sim ladder P(over) is overconfident by 1.4–1.6× in sd | Same root cause (section 3c, cause 2) |

---

## 5. The recommendation-mix question, answered per line

The board should not route volume by market ("more ML, fewer spreads"). Every line is its own decision. What the
measurement says about any **single line**:

- **Game lines.** The model's fair price is the market's fair price plus noise. ML Brier tie; spreads −0.0003; totals
  +0.0046. A per-line edge `p_model − p_fair` on a WNBA game line therefore carries **no measured information**: the
  raw model's departures from the line have slope 0.07 / −0.04. Until the game model changes, the per-line edge
  weight for WNBA game lines should be ~0 in the skill registry. That is a SCORE term, not a switch: a line can still
  rank on price quality, fee-net EV against the fair, and venue. The old ML-vs-ATS question dissolves: no game
  market has a model edge to route volume toward.
- **Props.** The ladder P(over) is overconfident, and its mean is biased low by minutes, so a per-line edge is
  systematically wrong-signed toward UNDERs on starters: model-mean minus book line, points **−1.83** (own average
  −0.04), PRA **−3.86** (own average −0.50). Disagreement ≥5pp bets on points ran 2,388 at hit 49.4%, ROI **−5.7% [−9.5%, −1.6%]**; PRA −7.4%
  [−12.0%, −2.8%]; PR −6.3%. Per line, the edge weight should be ~0 until fixes 1–2 below land. Assists (+1.9%) and
  threes (+3.4%) are CI-straddling, not a signal.

---

## 6. The one cell that beat both — not a finding

Served sim, regular season **08-19..09-30** (39 games / 13 dates), full-game spread: dBrier **−0.053 [−0.089,
−0.014]**, margin MAE 9.71 vs book 11.32. Three reasons it is not a finding:
1. It is **1 of 213** labelled cells; at a one-sided 2.5% rate ~5 are expected by chance.
2. The window overlaps the late-August stretch that **generated** the 08-31 hypothesis (its "last 14 days", AUC 0.84),
   so it is not out of sample.
3. Today's code on the same 64-game window shows **nothing**: +0.0009 [−0.0069, +0.0083].
It is worth one pre-registered test only if someone rebuilds the un-anchored August code state; otherwise drop it.

---

## 7. Model fixes, ranked by expected impact

| # | fix | target metric and expected size | engine-standard note |
|---|---|---|---|
| 1 | **Widen prop distributions per stat, and correlate the combo draws.** Scale sim dispersion by measured residual/sd (pts 1.39, reb 1.41, ast 1.45, threes 1.23), fit out of sample; build PR/PA/PRA from correlated draws, not independent ones | Brier gap to the book: currently +0.013..+0.089. Expected to close most of the way to own-avg-normal (0.255–0.266); not past the book | gate on LINE-LEVEL calibration over the published ladder, not interval coverage (learnings 2026-09-28) |
| 2 | **Fix sim minutes.** Feed `pregame_expected_minutes` / rotation history for every date (they now exist from 09-17/09-30), and calibrate sim `min_mean` to the player's as-of minutes where they are absent | Points bias −1.51 → ~−0.3 at oracle minutes; MAE 4.74 → toward 4.0; starters' −3.65 bias is the largest single error | inputs must be disk-backed and allowlisted; a roster/feature REBUILD is needed or it is silently ignored |
| 3 | **Shrink the sim's per-minute rate toward the player's own rate** (signal slope 0.16–0.27 ⇒ weight ~0.2 on the departure), fit on regular season, held out on playoffs | Removes the noise that makes the sim worse than its own ridge input | mechanism vs estimator: re-fit after #1/#2, not before |
| 4 | **Retrain the game ridge on 2025–26 with an expansion-club treatment** (weights are a single 2026-05-25 commit on ~867 pre-2026 games; total bias −8.2) | Raw ML Brier +0.029 vs book → target ≤ 0; raw total bias −8 → 0 | reachability test before correctness |
| 5 | **Only then revisit the market anchor.** It should lower only where the RAW model's departures from the line show slope > 0 out of sample | Today slope 0.07/−0.04, so lowering it would hurt | — |
| 6 | **Quarter split for Q2/Q3 totals** (+0.013 Brier vs book, both CIs exclude 0) | Period shares | — |
| 7 | **Pregame injury input** for every date (`raw/injuries.csv` holds 2 days) | Not separable in this data | — |

---

## 8. Instruments: what production measures for WNBA today

- **Weekly WNBA backtest (`scripts/backtest_wnba_projection.py`, the `wnba_projection` job) REFUSES**, reproduced on
  the fleet 2026-10-02 with `--limit 30`: *"dates with no projection artifact: 27 … games joined to a final: 0"*.
  Two independent causes:
  1. It reads `wnba_source/data/processed/game_cards_<D>.csv` (Syndicate root) via `/api/ops/artifacts/stream`. The
     fleet has that file only for 09-30..10-02, and the Render-era copies were not exported.
  2. **Its ESPN join matches on tri-codes, and ESPN's differ for five clubs**: `GS/LV/LA/NY/CONN` vs Syndicate's
     `GSV/LVA/LAS/NYL/CON`. Every game involving them joins 0, which covered all 3 fleet dates.
  The checked-in `tests/fixtures/weekly_backtests/wnba_projection_refused.stdout.txt` shows the refusal shape, not
  the cause. This harness maps the codes (`ESPN_TO_SYND`). The weekly script was not edited (not in this lane's
  files); it is a one-line fix for its owner.
- **Daily scorecard (`daily-accuracy` / `model_scorecard_20261002`)**: WNBA has 49 cells per window, **all
  `phase=live`**. 4 have games (2 games, 2 dates, 1,593 graded rows); **0 pregame cells**. It cannot see any of
  sections 2–3. The recorder's population starts 2026-09-14, and WNBA reaches it only through live Layer-2 rows.
- **`/wnba/api/market-accuracy`**: 09-24 reads 0 because `recommendations_2026-09-24.csv` was Render-only. 10-01
  grades 2 resolved of 9 bets.
- **`/api/ops/clv/report?sport=wnba`**: `openings 1267, resolved 0`. WNBA CLV is still never resolved.

---

## 9. Live (separate; never pooled with the pregame numbers)

- **Fleet live-prop grader** (`/wnba/api/live-player-props-lens-accuracy`, 09-30..10-02): **68 settled, 46-20-2**,
  all against a **pregame** line (`line_age: unknown` on 66/68). By period: **Q1 30-18-2 (62.5%, n=50)**, Q2 8-2, Q3
  2-0, Q4 5-0, OT 1-0. The clock-leakage shape of `[wnba-live-edge-is-leakage]` is still present. The Q1 cell is
  ~1.4 SE above the −110 breakeven: **not significant**. The endpoint itself says "CANNOT ASSESS clock leakage".
- **f72b42fd (live line grid)** and the 09-28 NegBin remainder: **the clean 09-29 points reading was never taken**
  (Render suspended 09-30 06:37Z; lane `live-props-model-probability` ORPHANED). It is still owed.
- **Scorecard live cells**: 4 WNBA cells with 1 game each (points 0.2115 vs 0.2393, threes 0.1485 vs 0.2010,
  rebounds 0.2697 vs 0.2364). n=1 game; quote nothing from them.

---

## 10. Reproduce

```
# ground truth + book (Windows)
py -3 C:/tmp/wnba_bt/fetch_espn.py                                   # ESPN scoreboards 05-01..10-02
wsl -e python3 /mnt/c/tmp/wnba_bt/backfill_odds.py                     # OddsAPI historical, tip-60min (94,458 credits)
# as-of re-run (WSL, scratch copy; never the fleet disk)
python scripts/backtest_wnba_lines_props.py game --espn-dir ... --odds-dir ... --pristine ~/wnba_bt/pristine \
    --scratch ~/wnba_bt/scratch/game --archive ~/wnba_bt/archive --code ~/wnba_bt/code
python scripts/backtest_wnba_lines_props.py sim  ... --worker K --workers 6 --n-sims 500
# score
python scripts/backtest_wnba_lines_props.py --espn-dir ... --box-dir ... --odds-dir ... \
    --asof-archive ~/wnba_bt/archive --served served=/mnt/c/tmp/wnba_bt/served --out ~/wnba_bt/report_final --n-boot 2000
```

Full report: `C:/tmp/wnba_bt/report_final/report.{md,json}` (279 KB; every segment, window and reliability table).
