# Findings 2026-11-28 — sim-form-regression: the prop projections do NOT follow recent form too far; their gap to the LINE is mostly noise

Lane `sim-form-regression` (the engine follow-up to todo `#862`; proposal 1 of
`findings_2026-11-27_cheat_sheet_optimization.md` section 8). Session 9abb92a5. Read-only:
no engine code, artifact or fleet setting changed. Times US Central.

**Verdict.** The pre-registered test FALSIFIES the reading that the NBA, NFL and NCAAF projections
follow a player's recent form further than his outcomes do (H-A), in all three sports and both windows.
The rival holds (H-B): the projection's distance from the line is 50-90% noise, and the actual lands most
of the way back to the line. Section 8's slope by "L10 hit rate at the line" ranks rows on a statistic
that contains the LINE. That is the artefact `learnings.md` 2026-10-19 (UEFA) names.
**No form-shrink was built**, as the falsification rule required. A fitted line anchor would flatten
section 8's table and improve Brier, but it does not improve ROI. Whether to build it is the user's
decision (below).

## What the numbers rest on

- **Substrate: fleet.** The official cheat sheets on the fleet data root:
  - files: `~/syndicate-prod/data/cheatsheets/<sport>/<date>.json` + `.reconciled.json`;
  - read through the fleet checkout `4bfaa108a` (`cheat_sheets`, `review_cheat_sheets`);
  - run 10:18-10:19 CST at nice 19 (45 s).
- **Population.** It is section 8's engine-read population: every official sheet's two-sided primary
  rows (rules 5), graded, 10-15..11-27. That is **13,010 rows, the same count as section 8.**
  - Rows usable for the decomposition need a projection, a line, an actual, an over/under side and 8+
    form10 values.
  - NBA: 2,636 fit / 2,181 holdout (124 / 107 games).
  - NFL: 1,128 / 709 (57 / 31 games).
  - NCAAF: 991 / 582 (163 / 97 games).
  - NHL, the control: 1,136 / 603 (187 / 103 games).
- **It reproduces section 8 to the decimal** on this subset: NBA holdout +20.6 / +6.7 / -5.7 / -16.1.
- **Windows:** fit 10-15..11-12 (29 dates), holdout 11-13..11-27 (15 dates).
- **Intervals:** 95%, bootstrap by game.
- **Kit (durable):** `C:\SyndicateProd\research\sim_form_regression_2026-11-28\`.
  - On the fleet: `extract_rows.py` + `run_extract.sh`.
  - On Windows (`py -3`): `decomp.py`, `arms.py`, `sens.py`, run over `rows.jsonl` (sha256 `47afd37ffde160e4…`).
  - Outputs: `*_out.txt`.

## Where the projections come from (traced in code, `checkout` at origin/main `0d7be042d`)

The constants in the fleet's `nba_prop_calibration.json` were NOT read; they live only on the fleet.

- **NBA: a sim, then a calibration toward the season average.**
  - Chain: `refresh_nba_oddsapi_props.py:3195` → `basketball_props_smart_sim._smart_sim_run_date_local`
    (:5496) → `orchestrator/smart_sim.simulate_smart_game` (:1169) → `apply_nba_prop_calibration`
    (`basketball_props_smart_sim.py:4690`).
  - Artifact: `smart_sim_<d>_<H>_<A>.json` → `cards_sim_detail_<d>.json`. Read by
    `nba_projections.load_nba_prop_projections` (:112) and set at `:338` (`prop_ladders[stat].mean`).
  - Per-minute rate weights (`basketball_props_smart_sim.py:3762-3766`): R21 0.50, R10 0.23, R5 0.12,
    ONNX 0.15. The "prior" is itself the last 21 days (`basketball_props_onnx.py:121`).
  - Minutes weights: about 48% L5, 29% L10, 14% L3, 10% last game (`smart_sim.py:999`).
  - Then `mean = b·(sim minutes × shrunk rate) + (1-b)·season-to-date average`
    (`nba_prop_calibration.py:417-421`).
  - No switch sets the recency weights.
- **NFL: no sim and no recency weighting.**
  - The mean is `statistics.fmean` over every current-season game before the week
    (`nfl/player_stats.py:706`, `:745`). Below 2 games it uses the whole prior season.
  - Then a game-context multiplier (`nfl/props.py:857`).
  - Artifact: `nfl_prop_projections_{season}_wk{week}.json`. Read by `shared/nfl_prop_projections.py:418`.
- **NCAAF: no sim and no recency weighting.**
  - The mean is `(n·x̄ + K·μ0)/(n+K)` over equally weighted games (`ncaaf/prop_projections.py:572`).
    The prior `μ0` is the prior season and a role bucket.
  - Read at `:1160`.
  - The constants were chosen, not fitted (`:31`, `:131`).

So two of the three engines have no recency weight to shrink.

## The test (pre-registered in `lanes.md`, pushed `e2baffeae` at 10:21 CST, before the decomposition ran)

Per row:
- `a` = actual, `p` = the sheet's projection, `l` = line, `L = max(l, 1)`, `f10` = mean of form10.
- The error `e = (a-p)/L`, oriented to the over.
- The regressors: `x_f = (f10-p)/L` (form against the projection; no line in it) and `x_l = (l-p)/L`.
- Model: `e ~ c + b_f·x_f + b_l·x_l`, per sport and window. Regressors are winsorised at ±1.5 (results
  are unchanged unwinsorised).

**H-A (form over-weighted)** needs `b_f < 0` beyond noise in BOTH windows. **H-B (the line carries what the
projection lacks)** needs `b_l > 0` beyond noise.

| sport | b_f fit | b_f holdout | b_l fit | b_l holdout |
|---|---|---|---|---|
| NBA | +0.15 [-0.02, +0.31] | -0.07 [-0.43, +0.32] | **+0.54** [+0.41, +0.69] | **+0.59** [+0.35, +0.81] |
| NFL | +0.28 [+0.04, +0.59] | +0.18 [-0.15, +0.53] | **+0.80** [+0.60, +0.96] | **+0.75** [+0.47, +0.96] |
| NCAAF | +0.54 [+0.15, +0.84] | +0.16 [-0.62, +0.68] | **+0.50** [+0.28, +0.72] | **+0.76** [+0.47, +1.02] |
| NHL (control) | +0.26 [+0.08, +0.44] | +0.35 [+0.02, +0.66] | +0.30 [+0.05, +0.54] | +0.31 [+0.01, +0.57] |

## Result 1 — H-A is falsified in NBA, NFL and NCAAF

- **`b_f` is never negative beyond noise in either window.** In the fit window it is POSITIVE beyond noise in
  NFL and NCAAF, and in NHL. Holding the projection and the line fixed, a player whose recent games sit
  above his projection comes in ABOVE it.
- **Ranked by the predictor being judged, the slope points the other way.** By quartile of `x_f` (cuts fitted
  per sport on the fit window), the fit-window error rises:
  - NBA -7.7% → +10.8%;
  - NFL -35.0% → +28.4%;
  - NCAAF -16.6% → +12.9%;
  - NHL -5.5% → +11.8%.
  - In the holdout there is no stable form slope.
  - So the projection follows form LESS than the outcomes did in the fit window, not more.
- **The section-8 fix, built in its linear form, fails.** `p + k·(f10-p)` was fitted on the fit window, and k
  comes out POSITIVE in every sport: move TOWARD form (NBA +0.39, NFL +0.63, NCAAF +0.60). Applied to the
  holdout:
  - section 8's table steepens: the 0.7-1.0 bucket goes from -20.8% to -23.8%;
  - Brier worsens: NFL +0.0042 [+0.0002, +0.0080].
- **Robust.**
  - With L5 in place of L10, pooled `b_f` is never below 0 beyond noise.
  - Unwinsorised, the same.
  - Per market (raw units), the one exception is holdout-only: NBA points, `b_f` -0.72 [-1.21, -0.22]
    against fit -0.13 [-0.41, +0.17]. It fails the both-windows bar, and it is noted here, not acted on.

## Result 2 — H-B holds: the projection's gap to the line is mostly noise

- **`b_l` is 0.5-0.8 in NBA, NFL and NCAAF in both windows, every interval above 0.** The actual lands about
  that share of the way from the projection back to the line. NHL is 0.3, so its projection keeps more
  of its own view, and NHL has no section-8 slope.
- **Per market (raw units, fit / holdout)**, roughly no information beyond the line (`b_l` ≈ 1):
  - NBA points 0.97 / 1.13;
  - NBA points+rebounds 0.92 / 0.92;
  - NBA rebounds 0.70 / 1.04;
  - NFL receiving yards 0.81 / 1.31;
  - NFL rushing yards 1.32 / 1.15.

  About half:
  - NBA PRA 0.59 / 0.79;
  - NBA threes 0.28 / 0.56;
  - NCAAF receptions 0.49 / 0.56;
  - NCAAF receiving yards 0.77 / 0.61.
- **Why section 8 saw "form."** A side its player cleared in 7+ of his last 10 is a side whose LINE sits below
  his recent games. His projection tracks his games, not the line, so it sits above the line too. The
  actual lands near the line, and the projection looks too high. The ranking variable contains the line,
  so it selects the rows where the market sits away from the projection. `learnings.md` 2026-10-19:
  *"a calibration/bias claim needs deciles ranked by the PREDICTOR BEING JUDGED."*
- **Ranked by the projection's OWN gap to the line, `(p-l)/L`, the same shape appears with no form in it.**
  Holdout, by quartile:
  - NBA +27.6% / +10.4% / +3.9% / -6.3%;
  - NFL +32.2% → -27.8%;
  - NCAAF +16.8% → -39.2%.
- **The line arm flattens section 8's holdout table.** The arm is `p + g·(l-p)`, with `g` fitted per sport on the
  fit window: NBA 0.61, NFL 0.88, NCAAF 0.47, NHL 0.34.

| holdout, L10 on the row's side | 0-0.3 | 0.3-0.5 | 0.5-0.7 | 0.7-1.0 |
|---|---|---|---|---|
| NBA+NFL+NCAAF, as served | +20.0% [+8.2, +31.9] | +1.7% | -8.8% [-12.6, -5.2] | **-20.8%** [-26.9, -14.0] |
| NBA+NFL+NCAAF, line arm | +6.1% [-5.7, +18.2] | -1.8% | -2.6% [-6.0, +0.9] | **-3.1%** [-8.9, +3.5] |
| NBA, as served / line arm | +20.6% / +7.3% | +6.7% / +1.3% | -5.7% / -3.0% | -16.1% / -5.9% [-14.1, +1.2] |
| NFL, as served / line arm | - | -18.0% / -15.4% | -15.2% / +0.2% | -27.6% / +2.5% |
| NCAAF, as served / line arm | +9.8% / -4.0% (n16) | -5.8% / -4.2% | -12.3% / -4.6% | -21.1% / -5.0% |

**The line arm is NOT the pre-registered fix.** It was chosen after the decomposition was read, though it
is fitted on the fit window only. Against the bar written for a built fix:
- it meets (1) the 0.7-1.0 bucket moves at least halfway to 0;
- it meets (2) the spread halves;
- it meets (4) Brier does not worsen;
- it **misses part of (3)**: NFL's `x_f`-ranked top quartile worsens, holdout +11.8% → +26.2% (n151, wide).
  Anchored to the line, NFL's projection leaves more of form's information unused.
- **It biases the MEAN low in football.** Mean `(a-p)/L` as served against the line arm:
  - NFL fit -0.3% [-5.5, +5.2] → +9.3% [+4.5, +14.1];
  - NFL holdout +1.0% → +10.1% [+2.2, +19.1];
  - NCAAF fit +4.0% → +9.3% [+3.7, +14.7].

  A prop line sits near the MEDIAN of a right-skewed stat (yards), so pulling a mean toward it moves it
  below the mean. The Brier gain stands, because the side probability lives at the line. But an anchor
  that should be built is an anchor on the probability, or on a median with the skew kept. It is not
  this naive pull of the mean.

## The betting read (holdout)

The probability is a Normal at each arm's mean, with sigma per (sport, market) taken from that arm's own
fit-window residuals. This compares the MEANS like for like. It is not the served probability: NBA serves
ladder probabilities plus a book blend, and NFL serves a Normal/log-normal blend.

| | n | Brier market | as served | line arm | line - as served |
|---|---|---|---|---|---|
| NBA | 2,181 | 0.2463 | 0.2571 | 0.2500 | **-0.0071** [-0.0111, -0.0033] |
| NFL | 709 | 0.2466 | 0.2773 | 0.2515 | **-0.0259** [-0.0346, -0.0161] |
| NCAAF | 582 | 0.2485 | 0.2670 | 0.2556 | **-0.0114** [-0.0170, -0.0055] |
| NHL | 603 | 0.2394 | 0.2442 | 0.2428 | -0.0013 [-0.0043, +0.0013] |

- **The line arm is still worse than the market in every sport.** The projection carries no measurable
  information beyond the price. That matches `[nba-model-skill-2025-26]` (2026-10-05) and
  `[nfl-model-accuracy-backtest]`.
- **The sim-backed side (edge >= 5%) does NOT improve.** ROI at the best price:
  - pooled: as served -6.2% [-11.6, -0.7] on 1,746 bets; line arm -7.0% [-13.7, -0.3] on 897;
  - NBA: -0.3% (836) vs -4.5% (420);
  - NFL: -13.3% (506) vs -8.3% (131);
  - NCAAF: -9.8% (404) vs -9.6% (346).
- **A uniform shrink toward the line never flips a side and never reorders a sport's rows.** It only shrinks the
  gap, so about half the sim-backed rows fall under the 5% bar.

## What this teaches the engines (for the owners; none of these files is held by this lane)

1. **Do not shrink recent form.** The data does not support it in any of the three sports. The football engines
   have no recency weight to shrink.
2. **The lever is the information the line has and the projection lacks.** Candidates from the trace:
   - **NBA: minutes and teammate availability.**
     - In 2025-26 the sim's minutes bias was -3.67, with MAE 6.64 against 5.27 for the last 5
       (`[nba-model-skill-2025-26]`).
     - Minutes weight L5 at about 48%.
     - Points carry `b_l` ≈ 1.
     - Owners: `basketball-scenario-calibration`, `nba-lineup-pools`.
   - **NFL: no usage decomposition.** There is no target or snap-share step.
     - The game-context multiplier may be inert pregame. **This is an inference from code, NOT verified:**
       `nfl_game_context_multiplier` (`props.py:568`) needs the player's team for the target week, which
       comes from play-by-play. It is not stamped on the artifact, so the artifact cannot show whether it
       fired. A `model_engine_standard` §1 population check is owed.
   - **NCAAF: receptions stand in for targets,** and the shrink constants are unfitted.
3. **NBA level drift since 11-13:** the projection is low by 8.1% [+5.0, +11.2] of the line on average in the
   holdout, pooled across markets (fit window +1.8% [-0.9, +4.8]).
   - The lines show the same offset: +8.4% with the line arm.
   - So it is not a drift of the projection alone against the market. It is the actual running above both.
     That fits the mean-vs-median point above.

## Decision owed (the user's) — a fitted line anchor, default-off

- **What it is:** a shrink of the sim's view toward the line, by a per-sport (or per-market) trust weight `g`,
  behind a default-off flag. It is applied to the side PROBABILITY or to a median, because the naive pull
  of the mean biases football's mean low (above).
  - Where it lands decides who reads it. On the mean or median, that is every prop-projection reader:
    cheat-sheet Sim vs the line, the board's `projected`, and `layer2_board._sim_direction_contradiction`
    (:2271). On the probability, it is the model-probability readers: EV, verdicts and stakes.
  - Either way it is a **betting change** (window-gated; the next window is 12-08 2-7 AM CST).
  - The design must be measured again on the SERVED probability, not on this Normal approximation.
- **For it:**
  - The board's numbers would be honest: Brier is better beyond noise in all three sports.
  - Section 8's table flattens.
- **Against it:**
  - No ROI gain.
  - The sim-backed set halves.
  - The "sim" becomes 47-88% the market, which is hard to present as the sim's own view (user 2026-10-15,
    "if i tout our sim...").
  - In markets where `b_l` ≈ 1 (NBA points, NFL yards), a per-market anchor would leave the sim no edge
    to show. In effect that withholds those markets from Sim vs the line, which the every-line rule makes
    a person's call, never a fit's.
- **The alternative:** hand item 2 (the inputs) to the engine owners and build nothing here.

## Not proposed

Any market, side or sport exclusion.
