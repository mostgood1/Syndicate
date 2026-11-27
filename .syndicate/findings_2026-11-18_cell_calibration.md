# Per-cell calibrated model probability, used everywhere (todo #847, lane `cell-calibration-847`)

Opened 11-18 7:13 PM CST from the program's P1 (`.syndicate/findings_2026-11-18_product_optimization_program.md`
§2, §3.2 P1, §5). Times are Central. Substrate: the fleet's disk (`~/syndicate-prod/data`, read-only, `nice -n 19`)
and `http://127.0.0.1:10000`. Never the git `data/` mirror.

## 1. Pre-registration (committed BEFORE any k is fitted or any held-out number is read)

### 1.1 The rule (what gets served)

- **The transform, per line:** `logit p' = logit fair + k_cell · (logit p_model − logit fair)`.
  `fair` is the line's own de-vigged fair for its side; `p_model` is the probability the surface already shows.
  k = 1 leaves the line exactly as today; k = 0 would be the fair (never served, see the floor).
- **The cell** is the daily optimizer's `sport|market|segment|phase`, built for a board row by
  `optimizer_overlay.cell_of_row` (the same function rank and stake already use). Alternate lines keep their own
  market (`totals_alt`), as the optimizer grades them.
- **Where k comes from:** the optimizer's own per-game sums (`model_scorecard_optimizer_state.json`,
  `games[*].cal[cell] = [rows, Σd², Σd·r]`, d = p_model − p_market, r = y − p_market). Over the fit window
  (the optimizer's 28 days before the fit date):
  1. Per cell: w*, its game-bootstrap 95% CI and the optimizer's verdict, from `daily_optimizer.fit_calibration`
     itself (BH q 0.10 over eligible cells, every leave-one-date-out w* < 1, CI upper < 1, >= 60 games / 5 dates).
  2. **Partial pooling per sport × market:** within each `sport|market` group (its cells are segment × phase),
     the group prior mean is the data-weighted w* of the group (Σ Σd·r / Σ Σd²); the between-cell variance τ² is
     DerSimonian–Laird over the group's cells, with each cell's se = (CI upper − CI lower) / 3.92. A cell's
     posterior is the normal-normal precision-weighted mean of its own w* and the group mean, with posterior sd
     sqrt(1 / (1/se² + 1/τ²)). A group of one cell, or τ² undefined, is not pooled (posterior = the cell).
     - **AMENDMENT 11-18 7:17 PM CST (`f33c606c7`, 01:17Z), before any fit or held-out read:** the formula above treats the group mean
       as known, so at τ² = 0 it gives sd 0 and the served "CI upper" would be the bare group mean. The posterior
       variance therefore also carries the group mean's own uncertainty (Morris):
       `var = 1/(1/se² + 1/τ²) + B² · V_g`, with B = se²/(se² + τ²) the cell's shrinkage and
       V_g = 1 / Σ_group (1/se_i²). At τ² = 0: posterior = group mean, variance V_g.
  3. **Served k = clip(posterior mean + 1.96 · posterior sd, K_FLOOR = 0.10, 1.0)** — the CI UPPER, the optimizer's
     own convention ("the smallest shrink the evidence supports") — on a cell whose OWN verdict is
     `overconfident`. Every other cell is not served (k = 1, the line as today).
- **No k above 1.** Under-confident cells (the cheat sheets' NBA props k 1.68) are left raw: amplifying needs its
  own test (w* CI lower > 1), not built here.
- **K_FLOOR 0.10 > 0, so no cell is zeroed.** A line keeps 10% or more of its own disagreement with the fair.
- **Never one global k.** There is no all-sports term anywhere in the rule.
- **Fit floors (dates excluded from the fit):**
  - NBA: games dated before 2026-11-19 (I-25: duplicated history inflated Elo in every NBA row before 11-18 3:02 PM
    CST; 11-18's own rows were first sighted before the fix, so the first clean slate is 11-19).
  - NCAAB / WNCAAB `totals*`: games dated before 2026-11-17 (#816 calibrates those rows upstream since its load
    11-17 00:04Z, so their k is a RESIDUAL on #816's number and must be fitted on #816's number only).
  - Everything else: the optimizer's window floor only.
- **Known biases left in (recorded, not filtered):** #844 (college live quotes read stale until it loads), I-24
  (big-5 soccer on frozen Understat since 11-03), #816's raw pregame fallback (NCAAB pregame totals cells).

### 1.2 The four uses, each behind its own switch (absent = off; on/1/true/yes enables)

| use | switch | what moves | betting change |
|---|---|---|---|
| (a) | `SYNDICATE_CELL_CALIBRATION_RAIL` | the Games Rail's ≥ 3 pp MODEL ≠ LINE test reads `p'` instead of the raw live probability | no (display) |
| (b) | `SYNDICATE_CELL_CALIBRATION_DISPLAY` | the board's shown model numbers: the Sim probability and the model EV at the price, `p'·decimal − 1` | no (display) |
| (c) | `SYNDICATE_CELL_CALIBRATION_RANK_STAKE` | rank and stake: a served cell's optimizer factor may go below the 0.5 floor, to its served k (never below K_FLOOR) | **yes**; default-off; 12-08 window at the earliest |
| (d) | `SYNDICATE_CELL_CALIBRATION_LIVE_PROB` | `cell_calibration.live_probability` + `live_std_err`, called from `live_gameline_join._cell_calibrate` after #816's step in `price_distribution_market` and before the edge in `price_moneyline`; the cell is passed from `attach_live_gamelines` (`live_cell=(sport, market, segment)`). College totals are skipped (#816). The verdict carries `live_cell_calibration` + `model_prob_cell_uncalibrated`, and `_apply_verdict` copies the stamp onto the projection so (a) never applies twice. The analytic WNBA path is not wired (no served WNBA cell) | `test_d_*` (6), incl. both real pricers off != on and the `_apply_verdict` -> rail hand-off; 1,664 tests pass across the 76 files that import the live join | **yes** | **WIRED on main, default-off** (LOAN of `live_gameline_join.py` from `live-player-exit-gate`, user "Yes, take the loan", 11-18 8:32 PM CST); 12-08 window at the earliest; predictions §4.2 |

**What (b) does NOT fix, stated before it is judged:** the board's EV column is MARKET EV (the price against the
de-vigged consensus fair, `ev_vs_fair_pct`), and the suggested set's +3.41% promise vs −3.02% realised is on that
market EV (pass A recomputes it as price vs fair; fair slope −0.60). A calibrated MODEL probability does not move it.
That gap is T1 (`ev_lb`, lane `decision-policy-paper`). (b) is judged on the model probability it shows (H-B below),
never on A-5's gap.

### 1.3 Hypotheses and held-out tests (each test uses only dates AFTER its own fit)

- **H-S (scorecard, time split, readable now):** fit the table on the optimizer state's games dated before
  2026-11-11 (window 10-14..11-10); grade on games dated 11-11..11-17. Metric: Brier of the served p' minus Brier of
  the raw model, per row, from the sums (`(k²−1)·Σd² − 2(k−1)·Σd·r` over rows; the LINEAR twin of the logit
  transform, which is what the sums support). Pooled over served cells; 95% CI by game bootstrap (2,000, seeded).
  - **Passes if** the pooled ΔBrier CI upper < 0 AND at least two thirds of served cells with >= 20 held-out games
    have ΔBrier < 0.
  - **Secondary (reported, not a pass condition):** served vs today's overlay factor (max(0.5, unpooled CI upper));
    the pooled posterior MEAN instead of the CI upper; the unpooled CI upper.
- **H-R (rail flags, time split, readable now):** fit the table on games dated before 2026-11-15 (window
  10-18..11-14); apply it, in the exact logit form, to pass C's 1,120 decided rail flags (11-15..11-17,
  `C_rail_rows.jsonl`: first sighting per chip × market × segment × side, live). A flag maps to the cell
  `sport|market|segment|live`.
  - **CORRECTION 11-18 7:20 PM CST (`2743c3b99`, 01:20Z), before any fit:** the line above first said `market(+_alt)`. Pass C's `alt`
    field is NOT the `_alt` market: `C_rail_build.py:116-120` sets it when the flagged line differs from the main
    line at that reading, and the raw flag records (`C:	mp
ailmon
eadingslags.jsonl`) carry only the rail's
    family market (`liveRailMarketKey` folds `totals_alt` into `totals`). So the cell uses the family market. Effect
    on what can be served: none found in the cell list — the optimizer's state has no college `*_alt` live cell (its
    live cells are `full` segment only), and every NBA cell is floored. Interval flags (h1, h2, q*) have no live
    cell, so they stay raw (gain 0, still flagged).
  - **Passes if** the mean log-likelihood gain of p' over the raw model is > 0 with game-clustered CI lower > 0.
  - **Gate check (a pass condition):** every served cell with >= 30 raw held-out flags keeps >= 1 flag under the
    calibrated test. A cell kept at 0 is a gate, and the rule is REJECTED for use (a) — with no refit on these dates.
  - Reported: flags kept per cell and per day; hit minus p' of the kept flags (target within ±3 pp); hit vs fair.
- **H-F (forward, the shipped table):** the table fitted on the 11-18 cron's state (games through 11-17) is frozen
  in the findings at the commit that lands it. Graded on games dated 11-19..11-25 from the cron state of 11-26
  (Thu 11-26, after 5:30 AM CST), with the H-S metric and pass rule. NBA cells enter H-F only if a later table
  serves them; the frozen table serves none (no NBA game on or after 11-19 is in its fit).
- **Falsified if:** H-S or H-R fails its pass rule. A failure is recorded here as the result; the rule is not tuned
  on the held-out dates and re-graded on them.

### 1.4 What (c) and (d) must predict before they land (filled in §4 before landing, not after)

Rows/day and cells moved, the factor distribution, Brier per row and the stake or probability shift, each from the
frozen table and a fleet replay, with the reading that would refute each prediction.

## 2. Results of the pre-registered held-out tests (read 11-18 7:22 PM CST (H-S) and 7:23 PM CST (H-R), once each, 2,000 resamples; the pre-registration was on main at 7:15 PM CST, `941874243`)

Substrate: a read-only copy of the fleet's `model_scorecard_optimizer_state.json` (written 11-18 05:36 CST; 2,417
games, 35 dates 10-14..11-17) and pass C's `C:\tmp\optprog\C_rail_rows.jsonl`. Script: `scripts/fit_cell_calibration.py`
(`grade` / `rail`), outputs in the session scratchpad (`HS_grade.json`, `HR_rail.json`).

### 2.1 H-S (scorecard rows, fit 10-14..11-10, graded 11-11..11-17): **PASSES**

- Fit: 1,414 games / 28 dates; **43 cells served** (NBA floored out; college totals floored out; NCAAF, NHL, NCAAB
  spreads live, soccer and others validated).
- Held-out: **ΔBrier −0.0062 per row [−0.0102, −0.0021]** (served p′ minus raw model), 23,564 rows / 367 games /
  7 dates, 29 served cells with held-out rows. **22 of 29 cells improve** (bar: 2/3 = 19.3).
- Secondary (reported, not a pass condition), same rows:

  | variant | ΔBrier per row | 95% CI | cells better |
  |---|---|---|---|
  | served (pooled CI upper, floor 0.10) | −0.00621 | [−0.01021, −0.00209] | 22 / 29 |
  | today's overlay factor (max(0.5, own CI upper)) | −0.00526 | [−0.00774, −0.00278] | 22 / 29 |
  | pooled posterior mean | −0.00570 | [−0.01019, −0.00123] | 19 / 29 |
  | unpooled CI upper, floor 0.10 | −0.00623 | [−0.00978, −0.00259] | 22 / 29 |

  Pooling did not add accuracy over the unpooled CI upper here (−0.00621 vs −0.00623); it is kept because it was
  registered and because it steadies thin cells (it moved no held-out number by more than its noise).
- Cells that got worse held-out (7): NCAAF spreads live (+0.0128/row, 61 games) and pregame (+0.0065, 66), NCAAF
  passing yards (+0.0016), spreads q4 (+0.0035), h2h q1/q4 (+0.0028/+0.0021), NHL h2h pregame (+0.0064, 51 games).
  NCAAF spreads full live/pregame share one pooled k 0.303 (τ² 0 in the group).

### 2.2 H-R (rail flags 11-15..11-17, table fit 10-18..11-14): **FAILS**

- 1,120 decided flags / 175 games / 3 dates. **Log-likelihood gain of p′ over the raw model +0.0010 per flag
  [−0.0030, +0.0051]**: the CI includes 0, so the pass rule fails.
- **Gate check: passes** (0 served cells with >= 30 raw flags kept at 0). NCAAF totals live kept 0 of 7 (k 0.10),
  under the 30-flag bar.
- **Why it fails: coverage, not a wrong sign.** Only **182 of 1,120 flags (16%)** sit in a cell the table serves
  (NCAAB spreads full live 169, NCAAF 13). The rest are, by the registered rule:
  - NBA, 298 flags (every segment): floored until games on or after 11-19 (I-25);
  - NCAAB / WNCAAB full-game totals, 435: floored until 11-17 (#816 calibrates them upstream; a residual k needs
    post-#816 dates);
  - college interval flags (h1 / h2), 147: the optimizer has no live interval cell, so they stay raw;
  - 58 in cells not validated in the window (NCAAB h2h 36, NHL spreads 5, WNCAAB h2h 4 / spreads 4, NCAAF h2h 3,
    NFL h2h 3, NHL h2h 3). (Recounted from `HR_rail.json` per cell; 182 + 298 + 435 + 147 + 58 = 1,120.)
- Reported (not pass conditions): flags kept 1,003 of 1,120 (11-15 471/506, 11-16 240/257, 11-17 292/357); kept
  flags hit **−10.1 pp below p′** [−14.1, −6.3] and +1.1 vs fair [−2.8, +4.8]; all flags −9.05 below the raw model
  [−12.6, −5.4] and −8.06 below p′ [−11.5, −4.4]. Within the 182 served-cell flags alone (post hoc):
  +0.0062 nats/flag vs raw [−0.018, +0.031], +0.0037 vs fair [−0.008, +0.015].
- **Consequence, as registered:** use (a) does not show a held-out gain on these dates, so loading (a) is not
  recommended on this evidence. It is still built behind its switch (it is display, and inert off); its grade is
  re-run forward once NBA and post-#816 college-totals cells reach the sample floor (60 games / 5 dates). No refit
  on 11-15..11-17.
- Pass C's +0.024 nats/flag out of sample was a k fitted ON rail flags (two dates, test the third), including
  NCAAB totals and NBA. This rule takes k from the scorecard population and excludes those two cells by design, so
  the two numbers answer different questions.

## 3. What is built (on main, every switch absent = off)

| use | switch | code | test (off != on) | betting change | state |
|---|---|---|---|---|---|
| table | none (written daily; read only by a switched-on consumer) | `scripts/publish_model_scorecard.py` writes `reports/model_scorecard/model_cell_calibration.json` beside the optimizer outputs, from the same 28-day window; its own try (a failure never costs the optimizer) | `test_the_cron_writes_the_table_beside_the_optimizer_and_not_when_it_is_off` | no | on main; reaches the fleet only with an ff (the cron is a fresh process each run) |
| (a) | `SYNDICATE_CELL_CALIBRATION_RAIL` | `layer2_board._live_projection_columns` stamps `live_model_probability_cal` / `live_cal_k` / `live_cal_cell` beside the raw number; `live_rail_rows.ROW_FIELDS` carries them; `intelligence.html` `liveRowGap` computes the >= 3 pp gap from the calibrated number (the callout still shows the raw sim %) | `test_a_*` (4) + node check of `liveRowGap` (raw gap 20.0 -> 3.0 at p' 0.53) | no (display) | built; **NOT recommended to load: H-R failed (§2.2)** |
| (b) | `SYNDICATE_CELL_CALIBRATION_DISPLAY` | `layer2_board._layer2_board_columns` stamps `model_probability_cal`, `model_ev_cal_pct` (the model EV at p′ and the best price), `cal_k`, `cal_cell`; the blotter's Sim cell shows p′ with "cal." and the raw sim in its tooltip; the EV cell's tooltip adds the calibrated model EV. `confidenceValue`, sorting and the chart-agreement check are untouched; the EV column (market EV) is unchanged | `test_b_*` | no (display) | built; H-S passed (§2.1); the user's call to load |
| (c) | `SYNDICATE_CELL_CALIBRATION_RANK_STAKE` | `optimizer_overlay.factor_for_row`: a cell whose k < 0.5 uses k (floor 0.10) instead of the 0.5 floor; rank (`_apply_skill_reliability`) and stake (`_sizing_skill_factor`) both read it. The overlay's kill switch still kills it | `test_c_*` (3) | **yes** | on main default-off; 12-08 window at the earliest; predictions §4.1 |
| (d) | `SYNDICATE_CELL_CALIBRATION_LIVE_PROB` | `cell_calibration.live_probability(...)`: the per-cell transform for a live game line's model probability, skipping #816's college totals; the caller must set `projection["live_cell_calibration"]` so (a) never applies twice | `test_d_*`, `test_a_rail_never_calibrates_a_live_probability_that_d_already_calibrated` | **yes** | **function on main, NOT WIRED**: its one call site is in `live_gameline_join.price_distribution_market` / `price_moneyline`, which lane-guard lists under `live-player-exit-gate`; wiring needs a loan (user decision, as `ncaab-total-overprojection`'s was) |

- Cost: the daily fit is one more `fit_calibration` pass (2,000 resamples) over the floored window: 24 s on this
  desktop for 1,711 games, once a day inside the 11:30Z cron.
- Not built, on purpose: no k above 1 (cheat-sheet NBA props k 1.68 stay raw); the cheat sheets' "Sim vs the line"
  (P9, `cheat-sheet-section-optimization`) can read the same table later; the card view's confidence bar.
- `portfolio_commit._sizing_skill_factor`'s docstring ("composite floor SKILL_FLOOR x 0.5 = 0.25x") is true only with
  (c) off. With (c) on the composite floor is SKILL_FLOOR x 0.10.

## 4. The frozen table for H-F, and the predictions for (c) and (d)

**Frozen table** (fit on the 11-18 cron state: 1,711 games / 28 dates, 10-21..11-17; `fit_cell_calibration.py fit
--today 2026-11-18`, 2,000 resamples). H-F grades exactly these k on games dated 11-19..11-25 from the cron state of
Thu 11-26 (after 5:30 AM CST), with H-S's metric and pass rule. 41 served cells; NBA 0 and college totals 0 by the
floors.

| cell | k | own w* | own 95% CI | today's overlay factor | games / dates |
|---|---|---|---|---|---|
| `ncaab|spreads|full|live` | 0.345 | 0.13528 | [-0.0779, 0.34699] | 0.5 | 602 / 16 |
| `ncaaf|h2h|h1|pregame` | 0.560 | 0.21232 | [-0.53143, 0.93899] | 0.93899 | 202 / 20 |
| `ncaaf|h2h|h2|pregame` | 0.518 | 0.03103 | [-0.62517, 0.67945] | 0.67945 | 201 / 18 |
| `ncaaf|h2h|q2|pregame` | 0.515 | -0.23398 | [-1.04677, 0.61738] | 0.61738 | 208 / 20 |
| `ncaaf|receiving yards|full|pregame` | 0.510 | 0.28292 | [0.06072, 0.51481] | 0.51481 | 171 / 20 |
| `ncaaf|receptions|full|pregame` | 0.629 | 0.37495 | [0.12068, 0.62836] | 0.62836 | 161 / 20 |
| `ncaaf|rushing yards|full|pregame` | 0.204 | -0.08127 | [-0.35579, 0.21482] | 0.5 | 172 / 20 |
| `ncaaf|spreads|full|live` | 0.365 | 0.25333 | [-0.0258, 0.534] | 0.534 | 216 / 19 |
| `ncaaf|spreads|full|pregame` | 0.365 | 0.08307 | [-0.40296, 0.55042] | 0.55042 | 238 / 20 |
| `ncaaf|spreads|h1|pregame` | 0.365 | -0.28879 | [-0.9677, 0.42206] | 0.5 | 240 / 20 |
| `ncaaf|spreads|h2|pregame` | 0.365 | 0.17939 | [-0.38312, 0.75129] | 0.75129 | 239 / 20 |
| `ncaaf|spreads|q1|pregame` | 0.365 | 0.15266 | [-0.64455, 0.97563] | 0.97563 | 240 / 20 |
| `ncaaf|spreads|q2|pregame` | 0.365 | -0.21101 | [-1.04716, 0.65334] | 0.65334 | 240 / 20 |
| `ncaaf|totals|full|live` | 0.100 | -0.24212 | [-0.4742, -0.00556] | 0.5 | 220 / 19 |
| `ncaaf|totals|full|pregame` | 0.100 | -0.04592 | [-0.3459, 0.24694] | 0.5 | 231 / 20 |
| `ncaaf|totals|h1|pregame` | 0.100 | -0.04296 | [-0.43004, 0.36737] | 0.5 | 239 / 20 |
| `ncaaf|totals|h2|pregame` | 0.100 | -0.0636 | [-0.53397, 0.39197] | 0.5 | 236 / 20 |
| `ncaaf|totals|q1|pregame` | 0.100 | 0.2747 | [-0.2983, 0.81174] | 0.81174 | 240 / 20 |
| `ncaaf|totals|q2|pregame` | 0.100 | -0.18583 | [-0.6796, 0.3208] | 0.5 | 239 / 20 |
| `ncaaf|totals|q3|pregame` | 0.100 | 0.33119 | [-0.21581, 0.83225] | 0.83225 | 239 / 20 |
| `ncaaf|totals|q4|pregame` | 0.100 | 0.18105 | [-0.39192, 0.68766] | 0.68766 | 240 / 20 |
| `nhl|assists|full|pregame` | 0.100 | -0.18853 | [-0.43783, 0.05708] | 0.5 | 192 / 28 |
| `nhl|goals|full|pregame` | 0.601 | 0.20671 | [-0.18957, 0.598] | 0.598 | 192 / 28 |
| `nhl|points|full|pregame` | 0.251 | -0.04678 | [-0.35493, 0.23974] | 0.5 | 192 / 28 |
| `nhl|saves|full|pregame` | 0.642 | 0.21291 | [-0.22186, 0.63551] | 0.63551 | 175 / 28 |
| `nhl|sog|full|pregame` | 0.338 | 0.18056 | [0.0225, 0.33738] | 0.5 | 192 / 28 |
| `soccer|btts|full|pregame` | 0.310 | -0.68678 | [-1.66225, 0.33093] | 0.5 | 311 / 15 |
| `soccer|h2h|full|live` | 0.175 | -0.34874 | [-0.86799, 0.186] | 0.5 | 199 / 17 |
| `soccer|h2h|full|pregame` | 0.175 | -0.09298 | [-0.67561, 0.54909] | 0.54909 | 153 / 13 |
| `soccer|player_first_goal_scorer|full|pregame` | 0.831 | 0.76785 | [0.70381, 0.8301] | 0.8301 | 229 / 15 |
| `soccer|player_goal_scorer_anytime|full|live` | 0.676 | 0.53324 | [0.40511, 0.66255] | 0.66255 | 231 / 15 |
| `soccer|player_goal_scorer_anytime|full|pregame` | 0.948 | 0.84473 | [0.72503, 0.95173] | 0.95173 | 228 / 14 |
| `soccer|player_last_goal_scorer|full|pregame` | 0.784 | 0.71392 | [0.64237, 0.78317] | 0.78317 | 211 / 15 |
| `soccer|player_shots_on_target|full|live` | 0.910 | 0.7592 | [0.62318, 0.89879] | 0.89879 | 237 / 15 |
| `soccer|player_shots|full|live` | 0.912 | 0.77329 | [0.63066, 0.92287] | 0.92287 | 237 / 15 |
| `soccer|player_shots|full|pregame` | 0.913 | 0.86674 | [0.76198, 0.97351] | 0.97351 | 239 / 15 |
| `soccer|spreads|full|live` | 0.578 | 0.3805 | [0.16967, 0.58179] | 0.58179 | 298 / 17 |
| `soccer|spreads|full|pregame` | 0.100 | -0.48807 | [-0.95798, 0.00904] | 0.5 | 330 / 17 |
| `soccer|totals|full|live` | 0.461 | 0.24897 | [-0.02587, 0.52462] | 0.52462 | 297 / 16 |
| `soccer|totals|full|pregame` | 0.461 | 0.05348 | [-0.53664, 0.58988] | 0.58988 | 330 / 17 |
| `wncaab|spreads|full|live` | 0.956 | 0.39067 | [-0.18621, 0.94413] | 0.94413 | 108 / 15 |

### 4.1 (c) rank and stake below the floor — predictions (for a 12-08 load, written 11-18 before any load)

- **What moves:** the 25 frozen cells with k < 0.5 (above, k 0.10-0.461). They carried ~2,484 graded rows/day in
  the window (69,544 rows / 28 days). Every other cell keeps today's factor.
- **P-c1, reachability (first board build after the load):** at least one Layer 2 score in those cells carries
  `optimizer_factor` < 0.5 (e.g. an NCAAB live spread at 0.345). Before the load the count is 0, because 0.5 is the
  floor. Refuted by 0 such rows on a slate with NCAAB live spreads.
- **P-c2, rails:** 0 rows with `optimizer_factor` < 0.10, and 0 rows removed from the board by it (the board's row
  count per sport is unchanged by the switch; the factor multiplies the score only).
- **P-c3, stake:** paper orders in those cells keep being placed (> 0 per day in each cell that had > 0 the week
  before), at a smaller model edge (the sizing edge × k / 0.5). A cell whose staked orders drop to 0 for 3 slates is
  a gate, and (c) is reverted.
- **P-c4, money:** no detectable change in two weeks (A-3: ≤ $6.9/day paper, CI [−$5.2, +$19.0]; live ≈ $0). It is
  shipped for honesty of rank and stake, not for money.
- **What it does NOT change:** any probability, so no Brier reading applies to (c). The held-out Brier gain of the
  same k over the 0.5 floor (H-S: served −0.00621 vs today's overlay −0.00526 per row) belongs to (b) and (d).

### 4.2 (d) the shared live probability — predictions (for whenever it is wired and loaded; written 11-18)

- **What moves:** 7 frozen live game-line cells, with their window rows/day: NCAAB spreads 0.345 (234), NCAAF
  spreads 0.365 (160), NCAAF totals 0.10 (225), soccer h2h 0.175 (12.5), soccer spreads 0.578 (61), soccer totals
  0.461 (59), WNCAAB spreads 0.956 (34). NBA (floored) and college totals (#816) do not move.
- **P-d1, reachability:** on the first live slate after the load, live rows in those cells carry the
  `live_cell_calibration` stamp and an edge about k × their raw edge (NCAAB spread: a raw +10 pp reads about +3.5).
- ~~**P-d2, the precision gate does more of the work:** priceable live rows per build in NCAAB / NCAAF spreads and
  NCAAF totals fall by at least half, but at least one per evening slate stays priceable in each (else it is a gate,
  and (d) is reverted).~~
- **P-d2 REVISED 11-18 8:43 PM CST, at wiring and before any load.** The wiring carries the gate's error through
  the transform, as #816 does: the sim's error times the slope, plus k's own fit error. So the edge and its error
  shrink together, and the gate's verdict mostly does not move. The original P-d2 assumed an unscaled error.
  - **New prediction:** priceable live rows per build in the moved cells fall by LESS than a third. The fall comes
    only from the fit-error term (largest at k 0.10, NCAAF totals). The main effect is the edge itself: the median
    |edge_pp| of priceable rows in those cells falls by about (1 − k).
  - **Gate rule kept:** at least one row per evening slate stays priceable in each moved cell. Otherwise (d) is
    reverted.
  - **Refuted if:** priceable rows fall by half or more in NCAAB spreads, or the median |edge| ratio is outside
    k ± 0.15 in any moved cell with >= 30 priceable rows.
- **P-d3, accuracy:** on graded live rows of those cells, Brier vs the raw live probability improves (H-S's sign,
  forward), and the rail flags in them hit within ±3 pp of the probability shown.
- **P-d4, money:** live orders in those cells fall in count; no detectable P&L change in two weeks.

## 5. H-F (forward grade of the frozen 11-18 table, read 2026-11-26 10:01 PM CST)

Read ONCE, by the pre-registered rule of §1.3, with no refit and no other date range. **Result: H-F PASSES.**

**Why it was read in the evening.** The scheduled task `cell-calibration-847-hf-grade-1126` tried four times (7:09-8:09 AM CST), and every attempt failed at the API with ENOTFOUND. The host had no DNS from about 12:00 AM to 11:05 AM CST. The task then disabled itself. The user said "no you do it" (about 9:55 PM CST), so a session started from the coordinating session (e32fef1a) ran the task's stored prompt as written. No attempt had got past the API: before this write, origin/main had no §5 and no H-F commit.

**Substrate.** A read-only copy (`nice -n 19 cat`) of the fleet's
`~/syndicate-prod/data/reports/model_scorecard/model_scorecard_optimizer_state.json`:
- mtime 2026-11-26 05:39:40 CST, after the 05:30 bar, so the freshness check passed;
- 61,915,207 B, the same size as the fleet file;
- 2,872 games over 35 dates, 10-22..11-25.

The table is `.syndicate/findings_2026-11-18_cell_calibration_frozen_table.json`: 41 cells, fit on 10-21..11-17 (1,711 games / 28 dates), committed in `9d6b96399` and unchanged since. The command:
`py -3 scripts/fit_cell_calibration.py grade --state <copy> --table <frozen table> --from 2026-11-19 --to 2026-11-25 --json-out HF_grade.json`.
The bootstrap draws 2,000 game resamples, seeded. The copy and output sit in that session's scratchpad (`state_20261126.json`, `HF_grade.json`).

### 5.1 Coverage per date (games in the state; games and rows in a served cell)

| date | games | by sport | served games | served rows |
|---|---|---|---|---|
| 11-19 | 66 | ncaab 29, wncaab 17, nhl 12, nba 4, soccer 2, ncaaf 1, nfl 1 | 52 | 2,873 |
| 11-20 | 77 | ncaab 51, nba 9, wncaab 7, ncaaf 6, soccer 4 | 60 | 2,497 |
| 11-21 | 184 | ncaaf 58, ncaab 51, soccer 49, nhl 14, nba 6, wncaab 6 | 168 | 17,189 |
| 11-22 | 103 | ncaab 38, soccer 28, wncaab 14, nfl 11, nba 7, nhl 5 | 64 | 5,609 |
| 11-23 | 74 | ncaab 34, wncaab 18, nba 10, nhl 7, soccer 4, nfl 1 | 41 | 2,205 |
| 11-24 | 122 | ncaab 78, wncaab 20, soccer 18, nba 3, ncaaf 2, nhl 1 | 91 | 1,857 |
| 11-25 | 27 | soccer 13, wncaab 14 | 10 | 142 |
| **total** | **653** | | **486** | **32,372** |

11-25 is not empty, but it is thin: 27 games, soccer and WNCAAB only. It is graded as it stands.

### 5.2 The grade (the script's `served.pass`)

- **ΔBrier per row, served p′ minus the raw model: −0.006815, 95% CI [−0.009606, −0.004426].** The CI upper is below 0.
  - 32,372 rows / 486 games / 7 dates (11-19..11-25), out of 653 held-out games.
- **Cells: 38 of 41 eligible cells have ΔBrier < 0.** The bar is two thirds, 27.3 of 41.
  - All 41 served cells have held-out rows (`cells_with_held_out` 41).
  - All 41 have at least 20 held-out games (`eligible_cells` 41). The smallest is `soccer|h2h|full|pregame`, with 28 games.
- **PASS.** Both conditions hold.
- **Compared with H-S** (§2.1, a table fit before 11-11 and graded on 11-11..11-17): −0.0062 [−0.0102, −0.0021], with 22 of 29 cells better. The forward read on the shipped table agrees in sign and size.
- **Cells that got worse (3).** All three are NCAAF spreads pregame, at the pooled k 0.365 (τ² 0 in the group):
  - `ncaaf|spreads|q1|pregame` +0.002592 per row (274 rows / 63 games);
  - `ncaaf|spreads|h1|pregame` +0.001800 (410 rows / 63 games);
  - `ncaaf|spreads|full|pregame` +0.001152 (284 rows / 52 games).

  NCAAF spreads full pregame was also worse in H-S (+0.0065, 66 games). It is now worse in both held-out reads. Its live sibling `ncaaf|spreads|full|live`, worse in H-S (+0.0128), improved here (−0.013091, 768 rows / 61 games).
- **Largest gains:**
  - `ncaaf|totals|q3|pregame` −0.048217 (202 rows / 63 games);
  - `ncaaf|rushing yards|full|pregame` −0.036487 (1,574 / 45);
  - `ncaaf|totals|h1|pregame` −0.023038 (468 / 61);
  - `ncaaf|totals|q1|pregame` −0.019946 (228 / 63);
  - `ncaaf|totals|full|live` −0.019472 (1,636 / 63).

  The highest-volume live cell, `ncaab|spreads|full|live` (k 0.345), gained little: −0.000885 (2,514 rows / 230 games).
- **What the pass covers.** It grades the probability that (b) shows and (d) would use. It is not a money reading, and it says nothing about the rail test (a), which is H-R and failed on coverage (§2.2). Nothing is loaded:
  - loading (b) (display, not a betting change) is the user's call;
  - (c) and (d) are betting changes, so they wait for a betting-change window and the user's call.

### 5.3 Readiness for the H-R re-run (step 4: not a grade, and `rail` was not run)

`fit_cell_calibration.py fit --state <same copy> --today 2026-11-26` fits on 10-29..11-25 (2,152 games / 28 dates) and serves 43 cells.
- **`nba|*|live`: none served.** Since the I-25 floor (games on or after 11-19), NBA live cells reach at most 39 games / 6 dates (eight player markets and `nba|totals|full|live`). `nba|spreads|full|live` has 37 and `nba|h2h|full|live` 3. All are under the 60-game floor.
- **`ncaab|totals*`: 3 cells served, all PREGAME,** at the pooled k 0.272 (τ² 0):
  - `ncaab|totals|full|pregame` 369 games / 8 dates;
  - `ncaab|totals|h1|pregame` 383 games / 8 dates;
  - `ncaab|totals|h2|pregame` 237 games / 8 dates.

  No college-totals LIVE cell is served. `ncaab|totals|full|live` has 193 games / 8 dates since 11-17, which is past the sample floor, but this fit does not serve it.
- **`wncaab|totals*`: none served.** `wncaab|totals|full|live` has 45 games / 3 dates.
- **So H-R is NOT runnable to any new coverage yet.** The flags it lacked (NBA live 298, college full-game totals live 435 of 1,120) still fall in unserved cells. The re-run stays in todo #847 for the optimization program.

## 6. (b) QUEUED FOR THE 12-08 WINDOW (written 2026-11-26 10:25 PM CST, before any load)

**User decision:** "load (b) in the next window". The user typed it about 10:12 PM CST 11-26, in session 77184c63, after the H-F PASS. The next window is Tue 12-08, 2-7 AM CST (08:00-13:00Z). (b) is display only, not a betting change, so the window is the user's choice of timing, not the rule's.

**The load.** One GLOBAL line in `~/syndicate-prod/local_production.env`, `SYNDICATE_CELL_CALIBRATION_DISPLAY=on`, carried by the window's drained full down/up.
- It is GLOBAL, like #861's key, because the same function, `layer2_board._layer2_board_columns`, builds the cards on whichever role builds them.
- Code is `75a787964`, absent = off.
- Preflight: `--betting-change no`. The deploys.md entry says `- betting change: no`.

**Fleet state, read 10:19-10:22 PM CST 11-26 (read-only, nice 19):**
- Fleet HEAD `30b2be76e` carries (b)'s code (`75a787964`) and #861's (`d25f49964`).
- The daily table `reports/model_scorecard/model_cell_calibration.json` exists: 43 cells, generated 11-26 11:30Z, expires 11-29 11:30Z (72 h). It is the same 43-cell fit as §5.3.
- The key is absent from `local_production.env` and from all three roles' env (`local_production.py env --role`: refresh-worker 254 lines, web 145, live-odds-worker 224; 0 `SYNDICATE_CELL_CALIBRATION_*`, 0 `SYNDICATE_LAYER2_ONE_MODEL_NUMBER`).

**Kit** (`C:\tmp\w1208_cellcal_b\`):
- `kit_env_b.sh check | apply | restore <backup>` (sha256 `78fc20afeaa9a8d1`): appends exactly one line, idempotent, backs up first and keeps mode 600.
- `kit_selftest_b.sh`: PASS 11-26 10:21 PM CST on a dummy file; the real file was untouched.
- After-load reader: `read_after_load_b.py` (sha256 `f37c3a6a387e3ba6`; rc 0 MET / 1 violated / 2 blind / 3 not loaded).

### 6.1 What (b) calibrates, traced 11-26 (read this before loading it without #861)

- **H-F graded k on the scorecard's model number.** That is `p_model = fair + model_edge_pct/100` (`model_scorecard.py:34`; d = p_model − p_market).
- **(b) calibrates the card's shown model number.** That is `model_prob` in `_layer2_board_columns`, AFTER #861's substitution (`layer2_board.py:5464-5469`, then `:5507-5509`).
  - **#861 on:** a pregame card's number is `model_probability_cal` = fair + model edge, the number H-F graded.
  - **#861 off:** it is the served projection number, `_model_prob_for_side`.
  - **Live cards:** the served live number either way (#861 leaves live rows alone).
- **Measured on the served board** (04:24Z 11-27, snapshot 03:44:46Z): 323 of 1,948 eligible cards with a model edge (16.6%) show a Win% more than 0.5 pp off fair + model edge. That is how often (b) with #861 off would calibrate a number H-F did not grade. #861's own 11-24 reading was 1,594 of 3,567 pregame cards.
- **So (b) is queued to ride WITH #861** (`SYNDICATE_LAYER2_ONE_MODEL_NUMBER=on`, queued for 12-08 by the user on 11-24). If #861 is dropped, (b) is HELD with it: the user decided 11-27 ~10:19 AM CST (§6.5).
- **This corrects the re-rank's line** "H-F graded exactly the probability (b) shows" (`findings_2026-11-18_product_optimization_program.md` §12.5). That holds for pregame cards only with #861 on.
- **(b) serves the DAILY table, not the frozen one.** The cells served on 12-08 are the 12-08 cron's fit. Cells that joined after the frozen 11-18 table rest only on their own window's validation, not on H-F. One example: `ncaab|totals|full|pregame`, `h1` and `h2` at k 0.272 (97 eligible cards in the BEFORE reading).

### 6.2 Readers of the fields (b) adds (grep on main 11-26)

- (b) adds four card fields: `model_probability_cal`, `cal_k`, `cal_cell`, `model_ev_cal_pct`.
- Their only reader is `intelligence.html`: the blotter's Sim cell (`:5339`) and the EV tooltip (`:5144`). No Python module reads them from a card. So nothing ranks, admits, sizes or records on them, and (b) is not a betting change.
- **Naming hazard (not a bug today).** `model_probability_cal` also names a different number on SHORTLIST rows: the pricing seam's fair + model edge (`layer2_board.py:2814-2832`, copied onto the candidate at `:3565`). `decision_record._model` (`:680`), `cheat_sheets.game_line_check` (`:392`) and `scripts/surface_consistency_check.py` (`:132`) read the shortlist field, and none of them reads a card. A future reader that takes `model_probability_cal` from a CARD with (b) on gets p′, not fair + edge.

### 6.3 Predictions (pre-registered here, before any load; judged by `read_after_load_b.py` on the first board build after the up)

- **BEFORE** (04:24Z 11-27, board snapshot 03:44:46Z, night slate, pregame only): 0 cards stamped. 4,720 cards carry a Win% and a fair, and 1,977 of them sit in a served cell (NHL pregame 787, soccer pregame 738, NCAAF pregame 355, NCAAB pregame 97).
- **P-b1, reachability:** the first board build after the up stamps `cal_cell` on cards in served cells. The count is > 0 on any board that has such cards (0 before). Refuted by 0 stamped while eligible > 0.
- **P-b2, exact transform:** on every stamped card:
  - `model_probability_cal` = sigmoid(logit fair + cal_k (logit Win% − logit fair)), within 2e-4;
  - `cal_k` = the table's k for `cal_cell`, within 1e-4.

  So Win% (`confidence`) stays the raw number and p′ sits beside it. Refuted by any card off either tolerance.
- **P-b3, served cells only:** every `cal_cell` is in the fleet's table and equals the card's own cell. Refuted by any card outside.
- **P-b4, model EV:** `model_ev_cal_pct` = `expected_value_pct(price, p′)`, within 0.01. Refuted by any card off.
- **P-b5, coverage:** eligible cards left unstamped are at most 1% of eligible.
- **P-b6, nothing else moves:** no bet, rank, admission or EV column changes. Covered by the off != on tests (`test_b_*`) and the reader trace in §6.2; no fleet reading separates it, because the shortlist does not read the card. The betting-change gate's count does not restart (`--betting-change no`).
- **Reported, not judged:** the median |p′ − Win%| in pp per sport|phase, and how many stamped cards carry #861's `model_probability_basis = model_edge`. With #861 on, that should be every stamped pregame card.

### 6.4 Owed

- Before the window:
  - the 12-08 batch (not built on 11-26) carries the kit;
  - put #861's condition to the user if #861 is dropped. DONE 11-27 ~10:19 AM CST: held with #861 (§6.5).
- After the up: run `read_after_load_b.py` on the first build (rc 0 = MET) and record the result here and in deploys.md.
- A forward accuracy read of the SHOWN number: H-F's metric and pass rule on games 12-08..12-21, with the 12-08 table frozen at load, read 12-22. It is not scheduled; the user's call.

### 6.5 Decision: (b) is held with #861 (written 2026-11-27 10:20 AM CST)

- **User decision:** "Hold (b) with it", typed 11-27 ~10:19 AM CST in session 77184c63, answering "If #861 drops out of 12-08, should (b) wait for it?"
- **So (b) loads only on a drained up that also loads `SYNDICATE_LAYER2_ONE_MODEL_NUMBER=on`.** If the 12-08 batch drops #861, it drops (b) too, and (b) waits for whichever window or drained up loads #861. (b) is not a betting change, so it does not itself need a window; #861 is one.
- **Why:** H-F's evidence is for fair + model edge. Without #861, 323 of 1,948 eligible cards (16.6%, 04:24Z 11-27) would show a calibrated number H-F never graded, under a label that implies it was. (b) is display only, so waiting forgoes no bets.
- **Not changed:** no fleet load, env, claim or scheduled task.

## 7. (c) AND (d) QUEUED FOR THE 12-08 WINDOW (written 2026-11-27 10:40 AM CST, before any load)

**User decision:** "Queue both", typed ~10:19 AM CST 11-27 in session e32fef1a, answering "should #847 (c) and (d) go into the 12-08 window? Queue both, only (d), or neither?" (relayed word for word by that session). It approves the QUEUE only: each load still needs the user's final yes in the window (Tue 12-08, 2-7 AM CST, 08:00-13:00Z). **Both are BETTING changes** (`--betting-change yes`; `betting_change.py add --kind yes` at the load).

**The loads**, GLOBAL lines in `~/syndicate-prod/local_production.env`, carried by the window's drained full down/up. Absent = off; code on main and on the fleet (HEAD `8455f25c0` carries both):
- (c) `SYNDICATE_CELL_CALIBRATION_RANK_STAKE=on`: `optimizer_overlay.factor_for_row` (code `75a787964`); rank and the stake's `_sizing_skill_factor` both read it.
- (d) `SYNDICATE_CELL_CALIBRATION_LIVE_PROB=on`: `live_gameline_join._cell_calibrate` (wired `8acee817d`), called in `price_distribution_market` (:1686) and `price_moneyline` (:2006).

**Fleet, read-only 11-27 10:2x AM CST (nice 19, key presence only):** 0 lines of either key in `local_production.env`, and 0 on every role (`local_production.py env --role`: refresh-worker 254 lines, web 145, live-odds-worker 224). The daily table is present: 42 cells, generated 11-27 11:30Z, expires 11-30 11:30Z, window 10-30..11-26 (2,250 games / 28 dates).

**Kit** (`C:\tmp\w1208_cellcal_cd\`):
- `kit_env_cd.sh check | apply c | apply d | apply both | restore <backup>` (sha256 `b1413796cc74dfe0`). It appends one line per key, is idempotent, backs up first and keeps mode 600. It prints presence and counts only, never a value.
- `kit_selftest_cd.sh` (sha256 `0ac24863ab36dd0e`): PASS 11-27 10:28 AM CST on a dummy file that also carries (b)'s key, because both kits write the same file on 12-08. It checks: apply c and apply d each add ONE key; apply both is idempotent; (b)'s line is untouched; restore is exact; a bad argument returns rc 2 without writing; the real file is untouched.
- After-load reader `read_after_load_cd.py --use c|d|both [--date]` (sha256 `352ac728e34faacf`; rc 0 MET / 1 violated / 2 blind / 3 not loaded). (c) is read on the served board; (d) on the book grids, `<sport>_source/data/book_grid/book_grid_<date>.json` `rows[].live_gameline`. The served board does not carry `live_gameline`, even with row diagnostics on, and `live_gameline_ledger` records no (d) stamp (see 7.4).

### 7.1 Which table production serves at the load: the DAILY one; it cannot be frozen without code

- Both uses read `reports/model_scorecard/model_cell_calibration.json` under the data root (`cell_calibration.TABLE_PATH`). No env key points them elsewhere, and `validate_table` refuses an expired file (72 h). The frozen 11-18 table expired 11-21. Serving it would take a code change, which this task may not push. It would also break the module's own rule: "a dead cron degrades to the raw model, never to a frozen table".
- The cron rewrites the table at about 11:30Z (5:30 AM CST), inside the window. A load before then serves the 12-07 fit, and the 12-08 fit replaces it within 600 s (`CHECK_INTERVAL_SECONDS`). After that, a new fit serves every morning.
- **Drift measured, frozen 11-18 against the daily fit of 11-27:**
  - Cells: 41 against 42. Three left: `ncaaf|spreads|h2|pregame`, `ncaaf|spreads|q1|pregame`, `soccer|player_shots|full|pregame`. Four joined: `ncaab|totals|full|pregame`, `ncaab|totals|h1|pregame` and `ncaab|totals|h2|pregame` at k 0.348 (442 / 459 / 284 games over 10 dates), and `soccer|player_shots_on_target|full|pregame` at 0.973.
  - 29 of the 38 shared cells moved by more than 0.0005, and the cells with k < 0.5 went from 25 to 19. The NCAAF spreads cells went 0.365 -> 0.519, which takes them out of (c). Soccer totals went 0.461 -> 0.625 and soccer btts 0.310 -> 0.565, both out of (c) as well. Soccer spreads pregame went 0.100 -> 0.214, NHL points 0.251 -> 0.330, NCAAB live spreads 0.345 -> 0.324.
- **Decision: the predictions are RESTATED against the table served at the load (7.3), not frozen.** The reader reads the served table and records its `generated_at`. No cell is changed from the H-F result. The 3 NCAAF pregame spread cells that graded worse in H-F are not carved out: in today's fit they sit at 0.519, and neither (c) nor (d) touches them.
- **What H-F does not cover:** H-F graded the frozen k. A cell that joined the daily fit after 11-18 rests only on its own window's validation. Today that is the 3 NCAAB totals pregame cells, which (c) would move (82 cards in the BEFORE reading, k 0.348).

### 7.2 (d) and the NCAAF live totals loads queued for 12-08 (#835 + #852, #859 on top): they move the SAME cells

- **§4.2 is right, and "(d) skips college totals" is right only for basketball.** The skip is `cell_calibration._LIVE_PROB_SKIP = (("ncaab", "wncaab"), "totals")` (`cell_calibration.py:320`, applied at :340): #816's basketball college totals. `_cell_calibrate`'s docstring line "a college total (#816 owns those)" (`live_gameline_join.py:1880-1881`) means #816's, not NCAAF's. So (d) MOVES `ncaaf|totals|full|live` (k 0.100, frozen and 11-27) and `ncaaf|spreads|full|live` (0.365 frozen, 0.519 on 11-27).
- **The NCAAF keys move the same rows upstream of (d):**
  - #835: `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION=on` anchors and widens the live total draws (`ncaaf/live_total_dispersion.calibrate_snapshot_totals`, in the NCAAF tick, `run_refresh_worker.py:2901`). `SYNDICATE_LIVE_TOTALS_PROB_SCALE_NCAAF=1` takes the join's NCAAF totals k from 2.48 to 1.
  - #852 (damping) and #859 (end game) change the live re-sim's margins and totals (`ncaaf/live_resim.py:967-970`), so they reach both (d) NCAAF cells.
  - (d) runs after all of them in `price_distribution_market`: after #780's scale and #816's step, at :1686.
- **Not only confounded: on NCAAF live totals, (d) would correct the same over-confidence twice.** (d)'s k 0.10 is a residual fitted on today's NCAAF live total: the raw draw times #780's 2.48, calibration slope 0.41 in #835's findings. With #835 on, the number (d) shrinks is already calibrated (slope about 0.94). This is the hazard #835's own docstring names for #780's k. The daily fit would keep reading mostly pre-#835 rows for up to 28 days.
- **(c) reaches the same cell:** `ncaaf|totals|full|live` (k 0.10 < 0.5), where rank and stake would go from the 0.5 floor to at most 0.10.
- **Options, the user's call (NOT decided here):**
  - (i) load (d) in a window without the NCAAF pair;
  - (ii) load both and accept a double correction on NCAAF live totals (not recommended);
  - (iii) before 12-08, land a default-off code change that skips `ncaaf|totals` in (d) while #835's switch is on, as #816's skip does. That is code, outside this task.

  The NCAAF regular season is over by 12-08; what is left live is Army-Navy and the bowls.

### 7.3 Predictions RESTATED against the served table (pre-registered here, before any load)

**(c), judged by `read_after_load_cd.py --use c` on the first board build after the up:**
- **BEFORE** (board 15:31:18Z 11-27, table 11-27 11:30Z): 0 of 6,387 cards carry an `optimizer_factor` below 0.5. 1,002 cards sit in 15 of the 19 k < 0.5 cells: NHL 410, NCAAF 373, soccer 136, NCAAB 83.
- The 19 cells today:
  - NCAAB: `ncaab|spreads|full|live` 0.324; `ncaab|totals|full/h1/h2|pregame` 0.348.
  - NCAAF: `ncaaf|rushing yards|full|pregame` 0.162; `ncaaf|totals|full|live` 0.100; `ncaaf|totals|full/h1/h2/q1/q2/q3/q4|pregame` 0.100.
  - NHL: `nhl|assists|full|pregame` 0.100; `nhl|points|full|pregame` 0.330; `nhl|sog|full|pregame` 0.355.
  - Soccer: `soccer|h2h|full|live` and `soccer|h2h|full|pregame` 0.173; `soccer|spreads|full|pregame` 0.214.

  Two cells sit above the floor today and would fall furthest: NCAAF totals q1 / q4 pregame, at overlay factors 0.667 / 0.793, would drop to about 0.10.
- **P-c1, reachability:** more than 0 cards below 0.5 on a board that has eligible cards. Refuted by 0.
- **P-c2, rails:** 0 cards with a factor below 0.10, and 0 cards OUTSIDE a k < 0.5 cell below 0.5.
- **P-c-rule:** on eligible cards the factor lies in [0.10, the cell's k] (stake scale ≤ 1), with at most 1% of eligible cards off it.
- **P-c3 and P-c4 stand as in §4.1**, judged on the cells served at the load. P-c3: staked orders per cell stay above 0 per day, and a cell at 0 for 3 slates reverts (c). P-c4: no detectable money change in two weeks. Both are multi-day readings, not in the reader.

**(d), judged by `read_after_load_cd.py --use d --date <board date>` DURING the first live slate after the up.** The grid's last write after midnight carries few live rows.
- **BEFORE** (book grids of 11-26, last written 06:01Z 11-27): 20 rows carry a live verdict. 10 are eligible, all `ncaab|spreads|full|live` and all priceable. 0 are stamped.
- The 7 live game-line cells today: NCAAB spreads 0.324, NCAAF spreads 0.519, NCAAF totals 0.100, soccer h2h 0.173, soccer spreads 0.660, soccer totals 0.625, WNCAAB spreads 0.829.
- **P-d1, reachability:** more than 0 stamped rows when eligible rows exist. Refuted by 0 stamped while eligible > 0.
- **P-d-exact,** on every stamped row:
  - the transform holds within 1e-6 (raw = `model_prob_cell_uncalibrated`, m = `market_prob`);
  - k equals the table's k within 1e-4;
  - `edge_pp` = 100 (p' − m) within 0.011;
  - the stamp's cell is served and is the row's own cell;
  - no ncaab / wncaab total is stamped.
- **P-d-cov:** at most 1% of eligible rows are left unstamped.
- **P-d2 (the 11-18 revision kept):** the median |edge| ratio lies within k ± 0.15 in each cell with at least 30 priceable stamped rows. The fall in priceable rows (under a third) needs the same slate's BEFORE and is reported only.
- **P-d3 and P-d4 stand as in §4.2.**
- **On NCAAF live cells, nothing here separates (d) from the NCAAF pair if both load (7.2).** The reader reports NCAAF totals' `prob_scale` (2.48 today, 1.0 with #835's pair) and `total_calibration`, so a reader can at least see which loaded.

### 7.4 Traced 11-27, NOT addressed in §1-§4: weigh before the final yes

- **(d)'s edge meets the optimizer factor on the stake.** `portfolio_commit._sizing_model_edge` = `model_edge_pct` × `_sizing_skill_factor`, and that factor includes `optimizer_overlay.factor_for_row` (`portfolio_commit.py:330-355, 405-413`). With (d) on, a live row's edge is already shrunk by about k. The optimizer factor, fitted on the unshrunk number, multiplies it again: by today's 0.5 floor, or by k with (c) on.
  - Example, NCAAB live spreads (k 0.324): a raw +10 pp becomes about +3.2 under (d), so about 1.6 at the stake with (c) off and about 1.0 with (c) on.
  - Not measured in money. I did not trace end to end which live orders size through this path.
- **Feedback not traced:** after (d) loads, the scorecard may grade the CALIBRATED live edge. If it does, the daily fit sees an already-calibrated number, and the k of those cells drifts toward 1 over the 28-day window. Neither the table nor the optimizer knows which number it was fitted on.
- **Instrument gap:** `live_gameline_ledger` (the series the live model is judged on) records the priced `model_home_win_prob` and #816's `model_home_win_prob_uncalibrated`. It does NOT record (d)'s `live_cell_calibration` or `model_prob_cell_uncalibrated`, so after (d) loads that series changes estimator with no marker. Fixing it is code (a ledger field) for before the load. It is not done here.

### 7.5 Owed

- Before the window:
  - the 12-08 batch (not built on 11-27) carries `kit_env_cd.sh`;
  - the user's final yes for each use;
  - the user's call on 7.2 (the NCAAF overlap) and on 7.4 (composition, feedback, ledger marker).
- After the up:
  - run `--use c` on the first board build, and `--use d` during the first live slate;
  - record both results here and in deploys.md (`- betting change: yes`, plus `betting_change.py add --kind yes --loaded-at <role pick-up>`);
  - P-c3 / P-d3 / P-d4 over the following slates.

## 8. (d)'s three fixes BUILT on a branch, NOT pushed (written 2026-11-27 12:50 PM CST, before any load)

**User decision:** session e32fef1a asked at about 12:15 PM CST 11-27: "Fix (d) before 12-08, and keep (c) queued as it is?" The user answered "Yes, fix (d) first" (relayed word for word by that session). This approves building and testing the three fixes only. **The push is NOT approved, and nothing loads.** If the fixes are on main and tested before 12-08, (d) loads then; otherwise it waits for 12-22. (c) stays queued as it is.

- **Code:** branch `cell-calibration-847d-fixes`, commit `2f19ebde5` (local; pinned `refs/keep/cell-calibration-847d-fixes-2f19ebde5`), parent `15fd2b5d5`. Lane `cell-calibration-847d-fixes`.
  - `syndicate/features/shared/optimizer_overlay.py` +122..136 (fix 1, in `factor_for_row`).
  - `syndicate/features/shared/cell_calibration.py`:
    - +281..306: the marker note, and the new `live_prob_stamp_of` (fix 1);
    - +345..372: the new `ncaaf_live_total_owned_by_835` (fix 2);
    - +380..381 and +395..396: the docstring line and the skip in `live_probability`;
    - +439..442: the skip in `rank_stake_factor`.
  - `syndicate/features/shared/live_gameline_ledger.py` +324..353 (`_cell_cal_fields`) and +556..557 (its one `build_records` entry). This is section-scoped beside `ncaab-total-overprojection`'s claim, and the invariant check reads the two sections as disjoint.
  - `tests/test_cell_calibration_847d_fixes.py` (NEW, 19 tests).
- **Tests:**
  - The 19 new tests pass. They drive the real join, stake, rank and ledger with off != on per fix.
  - The targeted suites pass, **121 of 121**: the new file, `test_cell_calibration`, `test_optimizer_overlay`, and `test_live_gameline_ledger` with its `_allowlist`, `_caps` and `_display_rows` files.
- **Byte-identical to main with every key absent.** An A/B ran main's three modules and the branch's on the same inputs, in two processes. The inputs were 6 rows (4 distribution rows, 1 moneyline, 1 pregame) through the real `price_distribution_market` / `price_moneyline` and `_apply_verdict`. The outputs compared were the rows, `factor_for_row`, `_sizing_skill_factor`, `_sizing_model_edge`, the rank's `_apply_skill_reliability`, `build_records`, `rank_stake_factor` and `live_probability`.
  - **Identical** with: all keys absent; (c) on alone; #835 on alone; (a)+(b) on.
  - **Different, as intended, with (d) on:**
    - stamped rows' overlay factor goes 0.5 -> 1.0, in rank, skill and edge;
    - the records gain `cell_cal` and `model_home_win_prob_cell_uncalibrated`;
    - with #835 on too, the NCAAF total row is left unstamped.

### 8.1 The stake trace 7.4 left open: live-money in-play orders do NOT size through `portfolio_commit`

- **Measured:** the fleet's `/api/portfolio/live` per `on` date, 10-30..11-27, had 1,666 live-money orders. 372 of them were submitted after their game's `commence_time`.
  - **All 372 are the Kalshi in-game entries module's** (`inplay_entries_live`: `ingame:` position keys; sizing `inplay_order_dollars` 302, unset 70).
  - That rule is market-only: the median no-vig fair of at least 3 fresh books, against the Kalshi ask. It reads no model number, so (d) cannot reach it.
- **The code agrees.** Portfolio entries are refused at or after kickoff on both venues:
  - Kalshi: `execute_portfolio.py:925`, `SYNDICATE_EXECUTION_KALSHI_PREGAME_ONLY` (absent = on). Only a `fair_source == "in_game"` position is exempt, and nothing sets one today.
  - Polymarket: `polymarket_us_orders._refuse_after_commence`.
  - Fleet live-odds-worker logs, 11-25 17:19Z .. 11-27 18:28Z: 7 `REFUSED_AFTER_COMMENCE` (all `game_started`, Kalshi: ncaab totals 2, nba totals_alt 4, 1 unlabelled) and 0 `AFTER_COMMENCE_IN_GAME_FAIR`. None of the 7 is in a cell (d) serves.
  - No other live-money path reads the live model number. Checked: `execute_portfolio`, `inplay_entries_*`, the Polymarket and Kalshi order modules, `position_marks`, `live_player_exit_hold`.
- **So (d)'s double shrink reaches the board's live RANK, the PAPER books' in-play stakes and the decision records, not live money.** Paper commits never pass the executor's commence refusal. The NCAAF end-game findings' "LIVE SIDE-MARKET CHECK" counted 683 of 695 paper in-play NCAAF side bets carrying a sim edge, against 2 of 32 live ones.
  - Fix 1 was still built, in `factor_for_row`. That one function feeds rank and stake, so they stay one factor, the documented invariant. It governs those surfaces and any future in-game-fair entry.
  - **Whether it is needed is the user's call at the push.**
- **For the 12-08 plan:** by CLAUDE.md's definition ("changes which live bets are placed, sized, held or exited"), (d) changes no live-money order today. This entry does not reclassify it: (d) stays queued as a betting change, the way it was decided. If the user reclassifies it, (d) leaves the window rule. That is the user's call.

### 8.2 What each fix does, and what it leaves

1. **No second calibration shrink** (`factor_for_row` + `cell_calibration.live_prob_stamp_of`).
   - A row whose projection carries (d)'s `live_cell_calibration` stamp takes neither `edge_shrink` nor (c)'s k.
     - Its factor is `stake_scale` alone, floored at 0.5. The shortfall of the cell's published bets is other evidence, so it stays.
     - A stamp counts only with a real-number k in [0.10, 1]. A missing, malformed or string k keeps the shrink (8 cases tested).
   - Worked example, NCAAB live spreads (k 0.324): a raw +10 pp edge (0.60 against 0.50) becomes about +3.3 pp under (d).
     - On main it is then sized at about 1.6 pp (x 0.5), or about 1.1 pp with (c) on (x 0.324).
     - With the fix it is sized at about 3.3 pp: (d)'s shrink, once. All three are before the registry's skill term, which every case shares.
2. **NCAAF live totals left to #835** (`cell_calibration.ncaaf_live_total_owned_by_835`).
   - While `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION` is on (#835's own predicate, `live_total_dispersion.enabled`, all spellings), (d)'s `live_probability` and (c)'s `rank_stake_factor` skip `ncaaf|totals*|full|live`.
   - **Full game only**, because #835 rewrites only the full-game `totalRunsDist`, never a `segments` block. NCAAF spreads live (k 0.519) stay (d)'s. The pregame NCAAF totals cells (k 0.10) stay (c)'s: #835 is live-only.
   - With #835 off, both behave exactly as on main. #835's switch is never read while (c) and (d) are off (tested).
   - **The skip assumes #835's key reaches every role that runs (c) or (d).** It does as queued: GLOBAL in `local_production.env` (`kit_env_ncaaf.sh`). A `ROLE__` scoping of it would break that.
   - **Left, pre-existing (neither (c) nor (d) causes it):**
     - with the skip, the cell's rank and stake keep the optimizer's own `edge_shrink`, 0.5 today;
     - that 0.5 was fitted on pre-#835 numbers (the 11-27 table: post_mean −0.164, the edge anti-predicting there);
     - it keeps acting on #835's calibrated totals until the 28-day window refits on them.
     - Weigh it with the NCAAF pair.
3. **The ledger marker** (`live_gameline_ledger._cell_cal_fields`).
   - When (d) moved a row, the record carries `cell_cal` {cell, k, k_sd, version} and `model_home_win_prob_cell_uncalibrated` (the engine's number before (d)) beside the priced `model_home_win_prob`.
   - The keys are ABSENT, not null, when (d) did not act. So `v` stays 7 and `record_key` / `_moved` are untouched: the key's presence is the marker. Filter on `"cell_cal" in record`, never on `v`.
   - Refusal records never carry it: their observed number is the raw segment probability.
   - **Every existing reader is unaffected by the new keys.** 50 modules and scripts reference the ledger, and a scan found none that iterates or compares a record's key set, or writes it with a fixed-field `DictWriter`.
   - **Once (d) LOADS, two engine-number fitters read (d)'s number on its cells. They are not in this lane: follow-ups.**
     - `scripts/live_totals_width_fit.engine_prob` (#780's scale fit) falls through to `model_home_win_prob` on a record whose `prob_scale` is 1 and that carries no #816 field. That is (d)'s number on a stamped totals row, for example soccer totals live (k 0.625).
     - `college_basketball/total_prob_calibration` (#816's refit) is NOT affected: (d) skips college basketball totals.
     - With the new field, each can read `model_home_win_prob_cell_uncalibrated` first.

### 8.3 Item 4, traced (no fix): after (d) loads, the daily fit grades (d)'s own number, and k drifts toward 1

- **The path:**
  - The scorecard grades `p_model = fair_probability + model_edge_pct / 100` (`scripts/bucket_search.py:564-566`).
  - It reads the opportunity recorder's `me` = the board row's `model_edge_pct` (`opportunity_population_ledger.py:199`).
  - On a live row that is `projection.edge_vs_market_pct` (`layer2_board._model_edge_for`), set from the live verdict's `edge_pp` (`live_gameline_join._apply_verdict`), which is (d)'s calibrated edge when (d) is on.
  - `daily_optimizer.accumulate` (d = p_model − p_market) feeds both the optimizer's w* and `cell_calibration.fit_table`. The recorder stores no (d) marker, so neither can tell which number it was fitted on.
- **Consequence, first-order arithmetic, NOT measured.** A calibrated row's d is about k x its raw d, so the window's w* becomes
  `w0 (1 − f + k f) / (1 − f + k² f)`
  with f the window share graded on (d)'s number, and the CI widens as 1 / sqrt(Σd²).
  - Over the 28-day window the served k rises, then reaches 1, and the cell leaves the table. (d) stops acting there, the raw number returns, and the next windows refit it back down: a cycle of about one window.
  - From the 11-27 table's post_mean and post_sd, the served k at f = 0.25 / 0.50 / 0.75 / 1.00:

    | cell | f = 0.25 | 0.50 | 0.75 | 1.00 |
    |---|---|---|---|---|
    | NCAAB spreads live | 0.36 | 0.41 | 0.53 | 1.00 |
    | NCAAF spreads | 0.56 | 0.63 | 0.75 | 1.00 |
    | soccer h2h | 0.22 | 0.30 | 0.46 | 1.00 |
    | soccer spreads | 0.71 | 0.77 | 0.86 | 1.00 |
    | soccer totals | 0.67 | 0.74 | 0.83 | 1.00 |
    | WNCAAB spreads | 0.86 | 0.90 | 0.95 | 1.00 |

    NCAAF live totals stay at the 0.10 floor (post_mean below 0).
  - The optimizer's own `edge_shrink` on those cells drifts the same way. With fix 1 it no longer acts on stamped rows.
- **Precedent and options, for the user (no fix here):**
  - #816 handled its upstream calibration with a fit floor (`MARKET_FIT_FLOORS`) and a residual k. That works for #816 because its calibration is a separate fixed fit. For (d), the table IS the calibration, so a residual k served on the raw number undoes it.
  - Options:
    - (i) record the uncalibrated live edge on the board row, and let the recorder and the grader use it for the fit, as #816's refit reads the engine's number;
    - (ii) compose: served k = k at the load x residual w, with a fit floor at the load date;
    - (iii) exclude (d)-served live cells from the refit after the load, holding their k. Against the module's own rule that a dead cron degrades to raw, not to a frozen table.
  - Each is code and a user decision. Until then, the drift starts at the first graded slate after the load.

### 8.4 The predictions that change (7.3 restated; the rest of 7.3 stands)

These hold only if the fixes' code is LOADED with (d). If (d) loads at 12-08 without them, 7.3 stands as written. With #835 also on, 7.2's double correction is live, and the reader reports it.

- **(c)**, with the fixes loaded:
  - **P-c-fix1:** with (d) loaded too, the cards of the (d)-served live cells leave (c)'s ELIGIBLE set. Today those are `ncaab|spreads|full|live`, `soccer|h2h|full|live`, and `ncaaf|totals|full|live` unless #835 is on.
    - A stamped card's factor is `stake_scale` (>= 0.5); an unstamped one in the same cell is still (c)'s.
    - Served cards carry no projection (0 of 6,307 cards 11-27), so the reader cannot tell them apart. It judges only the rails there (factor in [0.10, 1]) and reports below / at-or-above 0.5.
    - 11-27: 33 such cards.
  - **P-c-fix2:** with #835 on, `ncaaf|totals|full|live` leaves ELIGIBLE, and every card in it has a factor >= 0.5 (the optimizer's own). 11-27: 26 cards.
  - **ELIGIBLE today** (board snapshot 17:55:53Z 11-27, read 18:45Z, table 11-27 11:30Z): 950 cards with both fixes active. Fix 1 set aside 33 cards in (d)-served live cells, some in cells (c) never served. Fix 2 set aside 26 NCAAF live-total cards. 7.3's 1,002 was an earlier board.
  - P-c1, P-c2 and P-c-rule stand on the remaining eligible cards.
- **(d)**, with the fixes loaded:
  - **P-d-exact gains:** with #835 on, no `ncaaf|totals*|full|live` row is stamped (`P-d_ncaaf_total_not_skipped_under_835`). Those rows also leave ELIGIBLE (P-d-cov).
  - **P-d-ledger (new):** stamped grid rows > 0 implies records carrying `cell_cal` > 0 in the same sports' ledger files for the date. Every such record is well formed: a cell, k in [0.10, 1], and `model_home_win_prob_cell_uncalibrated` in (0, 1).
  - P-d1, P-d-cov, P-d2, P-d3 and P-d4 stand.
- **Reader:** `C:\tmp\w1208_cellcal_cd\read_after_load_cd.py`, now sha256 `9cc79568409135a5`. The pre-fix version is kept as `read_after_load_cd.pre_fixes_352ac728.py`.
  - It now REQUIRES `--fixes yes|no` and `--ncaaf-835 on|off`, and `--d-loaded yes|no` with `--use c`. An unknown is refused, rc 2, never assumed.
  - Checked on the fleet 11-27: no flags gives rc 2; every flag combination gives rc 3, NOT LOADED (c: 0 cards below 0.5; d: 0 stamped of 10 eligible).
- **Kit:** `kit_env_cd.sh` is unchanged. Its keys and its apply / restore do not depend on the fixes.

### 8.5 Owed

- **The push** of `2f19ebde5` to main: the user's own yes, through session e32fef1a.
  - Before the push, re-run the targeted suites on a fresh rebase.
  - After it, (d) still needs the 12-08 window's final yes, and the fixes must be LOADED with it: a fleet ff of the SHA that carries them, then the drained up.
- **The user's calls:**
  - whether fix 1 is needed (8.1);
  - the NCAAF optimizer 0.5 under #835 (8.2, item 2);
  - the fit feedback, options (i)-(iii) (8.3);
  - the two engine-number fitters (8.2, item 3).
- **After the load:** the reader with the flags stated, recorded here and in deploys.md.

### 8.6 #835 on with (c) and (d) absent is a no-op (added 2026-11-27 1:30 PM CST)

Session e32fef1a narrowed the inertness condition: each fix must be inert whenever the (c) and (d) keys are absent, WHATEVER #835's key says, because #835 may load on 12-08 without (c) or (d).
- **A/B against main's three modules: byte-identical** with #835 on alone, spelled `1`, with (a)+(b) on, and with (c) and (d) set `off`.
- **Pinned on the branch:** `test_fix2_835_alone_changes_nothing_while_c_and_d_are_absent`, for on / 1 / true / yes. With #835 on, these equal #835 off: rows, verdicts, `factor_for_row`, `build_records`, `rank_stake_factor` and `live_probability`. 23 of 23 in the file pass.
- **The branch head to push is now `6c28e52c4`** (pinned `refs/keep/cell-calibration-847d-fixes-head`). It is `2f19ebde5` plus that one test. NOT pushed.

### 8.7 The fixes are on main (added 2026-11-27 2:35 PM CST)

**The user pushed them:** "yes, push it", typed in this session about 2:30 PM CST 11-27.
- **On main as `a15d94bbc` + `d381a806a`** (pushed `3231ee493..d381a806a`). These are `2f19ebde5` and `6c28e52c4` rebased onto newer main; neither newer main commit touched these files. Patch-id `07359e3f` matches the tested diff exactly.
- **Re-checked on the rebase before the push.**
  - 125 targeted tests pass: the 23 in `test_cell_calibration_847d_fixes.py` plus the cell-calibration, optimizer-overlay and live-gameline-ledger files.
  - A/B against main's three modules is byte-identical in seven cases: all keys absent; (c) on; (a)+(b) on; #835 on; #835 spelled `1`; #835 with (a)+(b); and #835 with (c)/(d) set `off`.
  - With (d) on, only the intended diff appears.
  - The 125 were re-run on the pushed head; all pass.
- **Nothing loaded.** No fleet ff, env edit, restart or scheduled task.
  - The next ff of `~/Syndicate` carries these commits, but they are inert while the (c) and (d) keys are absent, whatever #835's key says (§8.6).
  - So this is not a betting change until (c) or (d) is switched on.
- **The 12-08 plan:** the fixes are on main and tested before 12-08, so (d) can load in that window. It is still the user's call at the window.
  - The window's ff must reach at least `d381a806a`.
  - Run the after-load reader with `--fixes yes`.
- **Still the user's calls** (§8.3 to §8.5): whether fix 1 is needed, NCAAF's optimizer 0.5, fit-feedback options (i) to (iii), and the engine-number fitters.

## 9. The fit fix (8.3 option (i)) BUILT on a branch, NOT pushed (written 2026-11-27 3:30 PM CST, before any load)

**User decision:** "Yes, both". Typed in coordinator session e32fef1a at about 2:25 PM CST 11-27, answering "Push the (d) fixes, with the fit fix built before (d) loads?". The first half shipped as `a15d94bbc` + `d381a806a` (8.7). This approves building and testing the fit fix; the code push needs the user's own yes. Lane `cell-calibration-847d-fit-fix`.

### 9.1 What it does

Branch `cell-calibration-847d-fit-fix`: `8e771a40c` + `a449d9b3e` (head, pinned `refs/keep/cell-calibration-847d-fit-fix-head`), cut from main `d3e7ec69c`, which carries the three fixes. Line ranges below are new-file lines.

- **Pricer** (`live_gameline_join`):
  - `_keep_cell_uncalibrated_edge` (+1906..1953), called from the distribution pricer (+1686, +1690) and the moneyline pricer (+2056, +2060).
  - On a verdict (d) moved, `edge_pp_cell_uncalibrated` is the edge without (d), EXACTLY as that pricer produced it before (d). The distribution pricer rounds to 2 places; the moneyline pricer does not.
  - It is None where the uncalibrated number misses its own precision bar, using the error from before (d) and the moneyline's `min_edge_pp` floor. So the refit's population is the one it had before (d), not a larger or smaller one.
- **Projection** (`_apply_verdict`, +3169..3174 and +3245..3250):
  - `edge_vs_market_pct_cell_uncalibrated`, plus `live_model_prob_cell_uncalibrated` on distribution rows, where the live probability is published.
  - Set whatever (d)'s own gate decided.
  - Blanked by the certainty refusal, exactly as the edge is.
- **Candidate** (`layer2_board`):
  - `_cell_uncalibrated_model_edge` (+2732..2765) puts the uncalibrated projection through the same `_model_edge_for` the served edge goes through: side, sign, the plausibility test on the uncalibrated probability. Then it goes through the pricing seam `_calibrate_model_edge`.
  - The result is `model_edge_pct_cell_uncalibrated`, beside `model_edge_pct` (+3594..3596). A row whose raw 0.9 the plausibility test refuses, while (d)'s 0.66 passes, records None, as it recorded no edge before (d).
- **Recorder** (`opportunity_population_ledger`, +177..182 and +233..238): the field becomes `mu`, only on such a record.
- **Store** (`model_scorecard.strip_record`, +132..146): keeps `mu` whenever it is present, None included.
  - **FOUND on the way: without this the fit copy NEVER fires in production.** The cron stores every record through `KEEP_FIELDS`, a fixed list that drops None values (`merge_board_date` → `strip_record`, then `grade_pending` grades the stored records).
  - Every unit test that calls `wrap_grade` directly would still pass. A test now runs the cron's own path, and it fails with this change removed (checked).
- **Refit** (`daily_optimizer`, +270..405):
  - `fit_records` + `wrap_grade` grade a fit copy (`me` := `mu`), ONLY when a record of the game carries `mu`. Grading picks its sighting by key and time, never by `me`, so both passes grade the same rows.
  - `accumulate(..., fit_graded)` takes the calibration sums from that copy. Those sums are the only input of `fit_calibration` (w*, `edge_shrink`), `cell_calibration.fit_table` (k) and `held_out_brier`.
  - The betting bands keep the served `p_model`: model EV, pnl, and so `stake_scale`.
  - `fit_mu` (`a449d9b3e`) is the number of records refit on `mu`, written only on such a game. It is the one trace in the published state that the copy fired; the sums alone cannot show it.
- **The grader is untouched.** `bucket_search.grade_population` is digested into `publish_model_scorecard.grader_signature`, so editing it would reset every scorecard, optimizer and sim-gap state, even with all keys absent. The second pass therefore lives in the optimizer's wrapper.
  - Cost: one extra grading pass per game that has a (d) record. It also re-runs that game's prop settlers, as the existing model-basis pass already does.
- **#780** (`scripts/live_totals_width_fit.fit_prob`, +17..31 docstring, +188..194):
  - It reads `model_home_win_prob_cell_uncalibrated` AFTER `_unscaled` and `_uncalibrated`, NOT first. The pricer applies k, then #816, then (d), so the number before (d) is after k. Read first, it would fit k on numbers k already tempered: the 11-24 false confirmation.
  - The number before (d) is the engine's number exactly where neither k nor #816 moved the row, and that is where it is read.
  - A `cell_cal` row with no number beside it is dropped as `no_engine_probability`. `recorded` still reads the recorded number.

### 9.2 Tests and the A/B

- **Tests:** 17 new in `tests/test_cell_calibration_847d_fit.py`, at Idle. Targeted runs: 549 pass (plus 34 subtests) on the branch head, across the new file plus
  - `test_cell_calibration`, `_847d_fixes`, `test_daily_optimizer`, `test_bucket_search`, `test_layer2_board`, `test_layer2_projection_carry`;
  - `test_live_gameline_{join,ledger,edge_basis,point_estimate,publish_switch,analytic_pricing}`, `test_live_gameline_ledger_{allowlist,caps,display_rows}`;
  - `test_live_totals_width_fit_source`, `test_opportunity_population_ledger`, `test_optimizer_overlay`, `test_model_scorecard`, `test_publish_model_scorecard{,_seasons}`, `test_sim_gap_ev_study`, `test_grade_suggested_set`.
- **Reachability through the REAL chain (off != on):**
  - The chain: join → `build_layer2_rows` → `population_record` → `merge_board_date` / `strip_record` → `grade_pending` → `wrap_grade` → `commit` → `fit_table`.
  - With (d) on, the committed calibration sums EQUAL the (d)-off sums exactly, and `fit_table`'s diagnostics are equal.
  - Without the fit copy, the same graded rows give different sums. Without the `strip_record` change, the cron's sums differ.
  - #780's `fit_prob` through the real ledger reads the same number with (d) on and off, while the recorded number moves.
- **A/B against origin/main's six changed modules** (`live_gameline_join`, `layer2_board`, `opportunity_population_ledger`, `daily_optimizer`, `model_scorecard`, and the #780 script):
  - Set-up: loaded under their real names in a separate process, 6 fixtures. They are NHL totals four ways (priced, even, plausibility-refused, a pregame certainty), NCAAF live totals, and NHL h2h.
  - Every stage was compared: verdict, row, candidates, records, stored records, the cron's state and committed sums, `fit_table`, the ledger, and `fit_prob`.
  - **Byte-identical in 8 cases:** all keys absent; (c) on; (a)+(b) on; #835 on; #835 spelled `1`; #835 with (a)+(b); #835 with (c)/(d) set `off`; #835 with (c) on. The ledger's wall-clock `recorded_at` was pinned.
  - **(d) on:** only the intended fields differ. Main's refit w* MOVES (h2h 4.06 → 13.27, totals 5.01 → 3.63 on these fixtures); the branch's stays at its (d)-off value.

### 9.3 Question 2: what the published scorecard grades

**The scorecard's accuracy keeps grading the SERVED number.** `wrap_grade` returns `grade`'s own rows, and `msc.grade_pending` / `build_scorecard` and the measured-bucket overlay read those.
- What fits on the number from before (d): the optimizer report's calibration block (w*, `brier_model_minus_market`, `edge_shrink`) and the cell table. On a (d)-served cell, that block now describes the number from before (d), because that block IS the fit.
- What keeps the served number: the optimizer's model-EV bands and `stake_scale`, because they measure what was promised and paid.

### 9.4 Every other fitter that reads a live model number (step 4)

Surveyed by a read-only agent and spot-checked by hand. "Reachable" means (d) could move its input.

| what | where it fits / reads | output used at runtime? | reachable by (d)? | done |
|---|---|---|---|---|
| optimizer w*, `edge_shrink` | `daily_optimizer.fit_calibration` 434+, from `accumulate`'s `cal` | yes: `optimizer_overlay` (rank and stake) | yes | **fixed** (reads the fit copy) |
| cell table k | `cell_calibration.fit_table` 563+, same `cal` | yes: (a)-(d) | yes | **fixed** |
| `stake_scale` | `daily_optimizer.stake_scales` 521+, bands over PUBLISHED rows (served model EV) | yes: `optimizer_overlay` | yes | no fix: it measures the served promise against what it paid, and fix 1 applies it to exactly those rows. No self-reference |
| #780 width k | `scripts/live_totals_width_fit.py fit_prob` 170+ (ledger) | by hand into `_TOTALS/SPREADS_PROB_SCALE*` | yes | **fixed** |
| measured-bucket-skill overlay | `model_scorecard.evaluate_ids` 409-488 / `overlay_payload` 678-707. It reads p_model (`bucket_search.py:563-566`) and `me` for the disagreement and direction bands (`measured_bucket_skill.py:163,175-183`) | yes: `skill_overlay.active_table` → `layer2_board._apply_skill_reliability`. `SYNDICATE_SKILL_OVERLAY`, absent = on | yes | no fix: it scores the number the board RANKS (its buckets carry the phase), and it never touches k, so it cannot undo (d). Caveat: for one 28-day window after the load, its live buckets mix pre-(d) and (d) rows |
| staked-probability profile | `scripts/fit_staked_probability.py:167-172`: execution-ledger orders' `model_edge_pct`, paper and live, no in-play filter | yes: `portfolio_commit.sizing_inputs_with_provenance` 817-842, no switch. **It exists on the fleet**: one cell, `ncaaf\|spreads\|full\|regular`, β 0, market only, written 10-22 (read 11-27) | yes, through PAPER in-play orders (paper commits never meet the commence refusal, 8.1). Kalshi in-play orders carry no `model_edge_pct` (`inplay_entries_live.py:366` sets none) | **not fixed: user decision**. The fix is the field on orders: candidate → `portfolio_commit` (contested by two open lanes) → `execute_portfolio.py:278` → `execution_ledger`. The fitter is manual (`--write`), so nothing refits it unattended |
| pricing-seam curves | `scripts/fit_probability_calibration.py:120,140`, the same orders | behind `SYNDICATE_PRICING_CALIBRATION`. The fleet has only `mlb_source/calibration/probability_calibration.json` (10-12) | yes, the same way | **not fixed: user decision** (the same order-path fix; manual, dry run by default) |
| live skill notes | `measured_market_skill` constants (269-312, 454-470, 624-655), measured by hand from the ledger's `model_home_win_prob` → `projection_skill.live_skill_note` | yes: the category factor, and `decision_record` w_model | a re-measurement would read (d)'s number | no code. A re-measurement must say which number it grades: the ledger now has both |
| #816 college live totals | `total_prob_calibration.live_fit_rows` 275-304 | yes | **no**: (d) skips ncaab/wncaab totals | none |
| #780 anchor replays | `replay_nba_live_{margin,total}_anchor.py` | by hand | **no**: they price without `live_cell` | none |
| sim-gap study | `sim_gap_ev_study` (trust w, slope) | report only | `me` yes; `mp` no: it reads the PREGAME `model_prob_over` (`layer2_board.py:2918`), which the live join never writes | none. After the load it grades the served number; `mu` is in the stored records if wanted |

**Graders that (d) moves (report or display only; no fit applied):**
- `grade_suggested_set` (daily, reports): no fit.
- `score_ranking_backtest`: its fits read `fp` and `px` only.
- `live_gameline_score`: display on `/api/board/book-grid`.
- The ledger studies (`live_totals_grade`, `live_gameline_age_grade`, `live_moneyline_gap`, `bucket_*`).
- `inplay_fair_score` → `inplay_scoreboard` (NBA `model_home_win_prob` as the `nba_resim` fair).
- `engine_experts.live_resim_expert` → `join_reproduction` (624-629). It unwinds #780 through `_unscaled` but not (d), so after the load every (d)-moved row reads as a parity MISMATCH. Flagged, not fixed.

**Out of (d)'s reach:** pregame-only fits (`prop_fair_side_lean`, `fair_price_eval`, `s7_prop_model_edge`), and market or price only (`min_ev_tuner`, `fit_decision_policy_z`, `syndicate_fair_fit`, `capital_ladder_calibration`, `live_cell_gate`, #835's constants).

### 9.5 Predictions restated (8.3 and 8.4)

- **With the fit fix loaded together with (d), 8.3's drift does not happen.**
  - The refit's sums on a (d)-served cell are the sums it would have had with (d) off, so the served k moves only with the data, not toward 1 by construction.
  - 8.3's table (served k at f = 0.25..1.00) describes (d) WITHOUT the fit fix only.
- **New, read by the reader (with `--fit-fix yes`):**
  - **P-d-fit-grid:** every stamped grid row carries `edge_pp_cell_uncalibrated` (None allowed), and a numeric one equals 100 (raw − m) within 0.011.
  - **P-d-fit-recorder:** stamped grid rows > 0 implies records carrying `mu` > 0 in the same sports' population files for the date.
  - **REPORTED, the day after:** optimizer-state games with `fit_mu` > 0. They appear only once the next day's cron has graded and committed the date.
- **P-c and P-d:** 8.4 stands. The fit fix changes nothing served: it adds fields, and changes only what the refit reads.
- **If (d) loads with the fixes but WITHOUT the fit fix,** 8.3 stands: k drifts toward 1 over about one window, starting at the first graded slate.

### 9.6 Reader and kit

- **Reader:** `C:\tmp\w1208_cellcal_cd\read_after_load_cd.py`, now sha256 `e2c5f370e16d1d27`. The previous version is kept as `read_after_load_cd.pre_fitfix_9cc79568.py`.
  - It now REQUIRES `--fit-fix yes|no` with `--use d|both`, and refuses `--fit-fix yes` without `--fixes yes` (rc 2). `--opt-state` adds the `fit_mu` reading.
  - Run on the fleet 11-27 (`--fixes yes --ncaaf-835 off --fit-fix yes --use both --opt-state`): rc 3, NOT LOADED. (c): 0 cards below 0.5. (d): 0 stamped of 137 eligible. Optimizer state: 2,973 games, 0 with `fit_mu`. With no flag: rc 2.
- **Kit:** `kit_env_cd.sh` is unchanged. Its keys do not depend on the fixes.

### 9.7 Owed, and what changes the 12-08 plan

- **The code push** of `8e771a40c` + `a449d9b3e` needs the user's own yes. Before it: a fresh rebase and the targeted tests re-run. It is inert with the (c)/(d) keys absent whatever #835 says (9.2), so it can land outside a window.
  - (d) loads 12-08 only if the fit fix is on main and tested by then; otherwise 12-22 (the coordinator's terms).
  - The 12-08 ff must reach the fit fix's main SHA, and the reader runs with `--fit-fix yes`.
- **User decisions:**
  - the order-path fitters (the staked profile is live on the fleet), table rows 6 and 7;
  - the pricing-seam hazard: `layer2_board._UPSTREAM_CALIBRATION_KEYS` lacks `live_cell_calibration`, so with `SYNDICATE_PRICING_CALIBRATION` on, a (d)-moved edge gets a second curve, the same class as fix 1. The key's value was not read;
  - #830's forward test: its flags are `|edge_pp| >= 3`, so (d) loading mid-window changes the C6 (NBA) population, and C2-NCAAF's while #835 is off;
  - `join_reproduction`'s false mismatches;
  - the bucket overlay's one mixed window.
- **Still open from 8.3-8.5:** whether fix 1 is needed, NCAAF's optimizer 0.5 under #835, and the 11-27 table's drift (7.3).

### 9.8 The fit fix is on main (added 2026-11-27 4:40 PM CST)

**The user pushed it.** "Yes, push it", typed by the user in this session (77184c63) at about 4:30 PM CST 11-27, answering "Push the fit fix to main?". The user typed the same words in coordinator session e32fef1a at about 4:28 PM CST; the coordinator relayed them.
- **On main as `86fd3e943` + `d3ec5b72e`**, pushed `e569f2f9e..d3ec5b72e` at about 4:37 PM CST. These are the tested `8e771a40c` + `a449d9b3e`, rebased three times as main moved.
  - 12 main commits landed after the branch was cut from `d3e7ec69c`; two were this lane's own ledger commits. None touched the fix's code files or their graders. They touched cheat sheets, CLV, paper settlement, rail-monitor scripts, picks pages and ledger files. No tested module imports `clv_join`, `order_clv`, `paper_settlement` or `cheat_sheets`.
  - Patch-id `fe38d34a` was the same on every rebase and equals the tested diff's.
- **Re-checked before the push.**
  - All 549 targeted tests pass, plus 34 subtests, on the first rebased head `f8b7c8431`. That is the same 24-file set as 9.2.
  - The A/B against main's six modules was re-run on that head. All eight (c)/(d)-off cases are byte-identical, the same as 9.2:
    - all keys absent;
    - (c) on;
    - (a)+(b) on;
    - #835 on;
    - #835 spelled `1`;
    - #835 with (a)+(b);
    - #835 with (c)/(d) set `off`;
    - #835 with (c) on.
  - With (d) on, alone or with #835, the diff is the intended one. Each rebased output equals its pre-rebase output byte for byte, main side and branch side both.
  - The 549 are re-run on the pushed head `d3ec5b72e`; the result is in the lane STATUS.
- **Nothing loaded.** No fleet ff, env edit, restart, claim, scheduled task or `SYNDICATE_CELL_CALIBRATION_*` key.
  - The next ff of `~/Syndicate` carries these commits. They are inert while the (c) and (d) keys are absent, whatever #835 says, so this is not a betting change until (d) is switched on.
- **The pricing-seam hazard (9.7), read by the coordinator read-only on 11-27:**
  - `SYNDICATE_PRICING_CALIBRATION` is on in all three roles, set GLOBAL in `local_production.env`.
  - The fleet's only profile is `mlb_source`'s (`mlb-market-shrink-2026-10-12`), so today the seam leaves every (d) cell's edge unchanged.
  - The fix, adding `live_cell_calibration` to `_UPSTREAM_CALIBRATION_KEYS`, is small and inert. It is owed before a non-MLB profile is published, and it is not in this push.
- **The 12-08 plan:** the fit fix is on main and tested before 12-08, so (d) can load in that window. Loading it is still the user's own yes at the window.
  - The window's ff must reach at least `d3ec5b72e`. That covers the (d) fixes, `d381a806a`, as well.
  - Run the after-load reader with `--fixes yes --fit-fix yes`. The reader pins no SHA, so it needs no change.
- **Lane overlap:** lane `soccer-live-lane-age-ceiling`, opened at `e569f2f9e` just before this push, claims sections of `live_gameline_join.py`: the lane-age table, `max_lane_age_seconds`, its switch and the row loop's lane verdicts. The fit fix's sections are the two pricers, `_keep_cell_uncalibrated_edge` and `_apply_verdict`, so the sections do not overlap. That lane builds on top of this push.
- **Still the user's calls** (9.7):
  - the order-path fitters (the staked profile is live);
  - #830's flag population;
  - `join_reproduction`'s false mismatches;
  - the bucket overlay's mixed window;
  - whether fix 1 is needed;
  - NCAAF's optimizer 0.5;
  - the 11-27 table's drift.
