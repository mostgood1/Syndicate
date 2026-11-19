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
     - **AMENDMENT 11-18 7:35 PM CST, before any fit or held-out read:** the formula above treats the group mean
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
  `sport|market(+_alt)|segment|live`.
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
