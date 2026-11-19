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
| (d) | `SYNDICATE_CELL_CALIBRATION_LIVE_PROB` | the shared live probability (live game lines), except the college totals #816 already calibrates | **yes**; default-off; 12-08 window at the earliest |

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
- **P-d2, the precision gate does more of the work:** priceable live rows per build in NCAAB / NCAAF spreads and
  NCAAF totals fall by at least half, but at least one per evening slate stays priceable in each (else it is a gate,
  and (d) is reverted).
- **P-d3, accuracy:** on graded live rows of those cells, Brier vs the raw live probability improves (H-S's sign,
  forward), and the rail flags in them hit within ±3 pp of the probability shown.
- **P-d4, money:** live orders in those cells fall in count; no detectable P&L change in two weeks.
