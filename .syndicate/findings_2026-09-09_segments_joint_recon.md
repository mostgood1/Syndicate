# FINDINGS — Step 3 "Segments and the joint": what the audit got wrong

`[2026-09-09, lane segments-joint-v1, three code agents + four live production reads]`

The Engine Room Audit's recommendation 3 read: *"persist per-sim vectors; MLB
first1/3/5 + rest-of-game from the live MC; football drive conversion fitted then
1H distributions + NCAAF live dists; NHL periods; first SGP/ladder fair-value vs
Kalshi rungs (paper)."* Four of those five clauses were written without knowing
what production already does. Corrected below, with the reading that settles each.

## 1. MLB segments are ALREADY priced off distributions — the clause is DONE

The sim publishes `sim.segments.{full,first1,first3,first5}`, each carrying
`total_runs_dist` and `run_margin_dist` histograms plus win/tie probabilities
(`vendor/mlb_bettingv2/tools/daily_update.py:4673-4691`), and
`syndicate/features/shared/prop_projections.py:887-942` walks those histograms to
price segment totals and spreads. This is not a point estimate compared to a line;
it is the distribution evaluated at the threshold.

**Served-board reading, 2026-09-09, `/api/board/layer2-shortlist?sport=mlb`, 200 rows:**

| segment | rows WITH `model_edge_pct` | rows without |
|---|---|---|
| first1 | 30 | 1 |
| first3 | 67 | 6 |
| first5 | 35 | 0 |
| full   | 49 | 12 |

139 of 200 served MLB rows are segment rows and 132 of them carry a model edge.
**Do not write a package to "add MLB segment pricing".** What is actually missing
is narrower: `first1` and `first3` have no LIVE source (only `first5` does, via
`live_mc_first5`, `syndicate/features/shared/live_gameline_join.py:262`;
`live_mc.py:104-105` has no first1/first3), and per-INNING detail is collapsed.

## 2. The MLB joint EXISTS and is populated in production

`sim.joint` carries a packed Spearman lower triangle: **153 labels, 11,628
entries, `scale` 1000, `n` 1000, `clamped` 0**, over 29 players plus the eight
segment-score dimensions (`team|full|away`, `team|first1|home`, `team|first3|*`,
`team|first5|*`). Read live from
`mlb_source/source_artifacts/data/daily/sims/2026-09-09/sim_9_COL_at_NYY_pk823497_g1.json`
(401,578 B). Producer `sim_engine/joint_outcomes.py:117-126`, `:283-304`; emitted
`daily_update.py:4703-4714`; consumer `syndicate/features/mlb/sim_joint_correlation.py`.

A Gaussian-copula conversion from rank correlation of COUNTS to correlation of
THRESHOLDED indicators already exists too
(`syndicate/features/mlb/threshold_correlation.py:1-52`, `rho_gauss = 2 sin(pi
rho_S/6)`), measured on 6,396 leg pairs, where raw `rho_S` overstated dependence
1.5-1.9x. **The joint is not missing. What is missing is that parlay pricing does
not use it as a joint**: `syndicate/features/intelligence_parlay_runtime.py:124-164`
interpolates between independence and the Frechet bound by AVERAGE pairwise
correlation, capped at 0.25, and its own comment says "NOT A COPULA" (`:148`).

## 3. MLB ladders are already distributional — and Kalshi has no integrity gate

`syndicate/features/mlb/ladders_build.py:208-252` `_dist_ladder` emits the full
cumulative `P(X >= total)` from the sim outcome histogram, one rung per outcome,
with a certainty refusal at `:179-200`. Every MLB prop market maps to a `*_dist`
histogram (`:88-132`).

The gap is on the venue side and it is asymmetric:
`syndicate/features/shared/polymarket_board_join.py:2445-2485` groups rungs, sorts
by line, asserts monotonicity at tolerance 0.02, and condemns the whole ladder on
violation. **Kalshi has no such check** — `monoton` matches nothing in
`kalshi_board_join.py`. And **nothing anywhere selects a rung**: the execution
ledger takes the `line` it is handed (`execution_ledger.py`, `portfolio_commit.py`
have no rung/alt-line selection).

## 4. Football: the sim ALREADY resolves quarters and the writer throws them away

`syndicate/features/football/sim_engine/smartsim2/game_simulator.py:101` loops
quarters, `:119-128` records per-quarter points and drive/possession counts, and
`:187` returns `quarter_log`. **`scripts/generate_smartsim2_nfl_projections.py:769-771`
keeps only `output.final_score`.** The persisted artifact is 8 scalars per game
(`syndicate/features/nfl/smartsim2_projection.py:33-49`) — no distribution of any
kind, not even the full-game margin histogram.

So h1 rows are market-only by an EXPLICIT guard, not by omission:
`nfl_game_projections.py:367-369` and `ncaaf/game_projections.py:374-376` skip any
row whose segment is not `full`, counted as `non_full_segment_rows` /
`rows_non_full_segment`, and `portfolio_commit.py:472` then refuses
`no_model_edge_pct`. Every h1 row we capture is unsizable.

The same seam appears in NCAAF live: `syndicate/features/ncaaf/live_resim.py:419`
re-runs the real engine mid-game and collects margins at `:422`, then
`build_game_lens` (`:492-495`) says the lane "deliberately does not carry"
`marginDist`. **The distribution is computed and discarded** — and it is exactly
the object MLB's segment pricer consumes.

**The credibility caveat that must gate any football half pricing:** drive rates
are hand-tuned constants, not fitted (`drive_priors.py:343`, `:366-371`, `:384`,
`:454`; profile scalars `calibration_profile.py:123-150`). Measured truth over
**53,548 real NCAAF drives** already sits in
`scripts/calibrate_ncaaf_drive_structure.py:38-58` (TD 0.264, FG 0.100, punt
0.351, turnover 0.109, downs 0.073, 5.77 plays/drive, 165.4 s/drive, 23.65
possessions/game), and the sim misses it by **+27% plays/drive, +12% s/drive,
-15% possessions/game**, with totals over-dispersed ~2.17x market. Half scoring is
MORE sensitive to drive count than full-game scoring is, so a half distribution
derived from these rates inherits a larger error than the full-game numbers do.

## 5. NHL periods should NOT be built yet — there is no denominator

Per-period lambdas exist and are persisted as MEANS
(`hockeysim/projection.py:58` `period_shares = (0.2924, 0.3478, 0.3598)`;
`artifacts.py:59-64` write `period{1,2,3}_{home,away}_proj`), but no per-period
outcome distribution is emitted. Two facts make period pricing premature:

- Market anchoring reaches the periods and **rescales the level only**
  (`market_anchoring.py:165`, `:196-199`); the P1/P2/P3 SHAPE is three fixed
  constants. A period edge would be mostly the anchor plus a constant.
- **NHL is absent from `segment_actuals.SEGMENT_PERIODS`** (`:263-266`) and no
  `bet_status_nhl.py` exists. An NHL `p1` order refuses `unsupported_segment`.
  Capture would outrun grading, which `learnings.md` forbids.

Gradeable today: NFL and NCAAF `q1-q4`/`h1`/`h2` (h2 includes OT by the `None`
sentinel), soccer `h1`/`h2`, MLB `first1/3/5`, WNBA quarters and halves.

## 6. The largest measured lever ships display-only

`syndicate/features/shared/venue_basis_edge.py` prices exchange against book
consensus NET OF FEE, with a fee model verified on 18/18 real fills
(`venue_fees.py:399-527`, quadratic `rate * C * P * (1-P)`). It is **`servable`
False for every row and unscored against realised results** (`:31-34`), and where
`fee_multiplier` is absent it assumes the full rate and stamps
`fee_is_upper_bound` (`:49-52`). Audit recommendation 6 calls venue-hold routing
the largest measured lever on file (+8.48pp gross, MLB prop unders). It is built,
inert, and unmeasured.

## What this changes about the plan

Step 3 is not a modelling problem. Four of its five clauses are **writer seams and
guards** over machinery that already exists, and one (NHL) should not be built at
all until a resolver exists. The work is: persist what is computed, gate what is
persisted, measure before publishing, and use the joint as a joint.

Corrections owed to the audit artifact's sections 04-08 and to recommendation 3.

## 7. THE FOOTBALL QUARTER DIMENSION IS THE LEAST-CALIBRATED PART OF THE MODEL, and a prior recalibration made it worse

`[added 2026-09-09, from `docs/reports/smartsim_2_nfl_truth_recalibration_report.md`, dated 2026-07-15]`

This was not in the original recon and it changes what S4 has to prove. NFL's
smartsim2 WAS recalibrated against measured truth -- 17,677 real drives over 816
regular-season games, nflverse PBP 2023-2025 -- and the report's own table shows
game-level metrics improving while the PER-QUARTER dimension did not:

| metric | truth | sim before | sim recalibrated | normalized error before -> after |
|---|---|---|---|---|
| possessions/game | 21.66 | 20.55 | **21.69** | 0.051 -> **0.001** |
| drive_length_seconds | 166.2 | 178.8 | **169.6** | 0.075 -> **0.020** |
| game_totals | 45.13 | 43.48 | 44.15 | 0.036 -> **0.022** |
| punt_rate | 35.1% | 42.4% | 37.2% | 0.208 -> **0.059** |
| touchdown_rate | 22.0% | 25.6% | 23.5% | 0.165 -> **0.068** |
| quarter_1_scoring | 8.82 | 9.04 | 9.38 | 0.025 -> **0.063 WORSE** |
| quarter_2_scoring | 13.91 | 11.76 | 12.44 | 0.155 -> 0.106 |
| quarter_3_scoring | 9.26 | 10.32 | 10.32 | 0.115 -> **0.115 UNCHANGED** |
| quarter_4_scoring | 12.86 | 12.17 | 11.89 | 0.053 -> **0.075 WORSE** |
| drive_length_plays | 5.93 | 6.90 | 6.62 | 0.164 -> 0.117 |

**Three of the four quarters got worse or stood still while every game-level
metric improved.** After recalibration the worst-fitting metrics in the whole
table are `drive_length_plays` (0.117), `quarter_3_scoring` (0.115) and
`quarter_2_scoring` (0.106) -- i.e. the drive-count term and the quarter split,
which are exactly the two things a half or quarter price depends on.

**Why this matters more than it looks.** The model engine standard already warns
that adding a mechanism to a calibrated engine requires re-fitting what was
absorbing it. This is the same failure from the other direction: a fit optimised
on game-level aggregates bought its improvement partly OUT OF the quarter split,
and nothing in the process objected, because per-quarter error was reported but
not treated as a target.

**Consequences, and they are directional:**
- S4's gate is not "grade the halves and see". The quarter dimension is
  KNOWN-WEAK with numbers already on file, so a half distribution built on it
  starts from a measured deficit rather than an unknown one.
- Any future football calibration MUST score per-quarter scoring as a first-class
  objective, not as a diagnostic printed underneath the real ones. S4a's brief
  carries that requirement explicitly.
- NCAAF has had NO drive-structure fit at all (`scripts/calibrate_ncaaf_drive_structure.py`:
  plays/drive +27%, seconds/drive +12%, possessions/game -15% against 53,548
  real drives), so it is BOTH uncalibrated on structure AND unmeasured on
  quarters. Lane `s4a-ncaaf-drive-fit` is fitting it under the rule above and is
  instructed to recommend AGAINST flipping if the fit trades quarters for
  structure.

## 8. CORRECTION — the NCAAF drive-structure numbers in section 4 and section 7 describe the IN-SOURCE DEFAULT, not production

`[2026-09-09, from lane `s4a-ncaaf-drive-fit`, commit `462ccde4`]`

Sections 4 and 7 quote the NCAAF sim as missing truth by **+27% plays/drive,
+12% seconds/drive, -15% possessions/game**. Those figures come from
`scripts/calibrate_ncaaf_drive_structure.py`'s docstring and they are correct
about the IN-SOURCE DEFAULT PROFILE. **They are not what production runs, and
this file asserted them as the current state. That was wrong.**

NCAAF's live profile is a PROMOTED ARTIFACT, `data/calibration/ncaaf_profile.json`
(`ncaaf-goal-line-refit-1`, promoted 2026-08-27). Measured against it:

| metric | vs in-source default | **vs the live artifact** |
|---|---|---|
| plays per drive | +25% | **+9.1%** |
| seconds per drive | +12% | **-3.2%** |
| possessions per game | -15% | **-3.0%** |
| structure score | 12.8% | **4.2%** |

**So the gap S4a was scoped to close was already largely closed**, by a lane that
promoted an artifact rather than editing the source constants.

### HOW THE WRONG BASELINE SURVIVED FOUR SWEEP ROUNDS, which is the durable lesson

`scripts/session_worktree.py` EXCLUDES `data/` by design -- 34,690 of 37,745
tracked files, and a lossy mirror that is never evidence about production. So in
a session worktree the promoted profile artifact is ABSENT, and
`load_versioned_profile` **falls back to the in-source default SILENTLY**. Four
sweep rounds ran against that fallback and were internally consistent the whole
time; an unrelated test failure is what exposed it.

This is the `absent != off` trap wearing different clothes: absent artifact did
not mean "no profile", it meant "a DIFFERENT profile, unannounced". A calibration
harness that cannot tell you which baseline it just measured is not a harness.

Guards now in place (`462ccde4`): the harness prints profile source and version on
every run with a `!!!` block when the artifact is missing, and a declared variant
carries its base version and **raises** on mismatch rather than proceeding.

### Two measurement defects found and fixed before any fit was trusted

- **`missed_field_goal` was being counted as `field_goal`** by substring match.
  Split correctly: made FG **8.3% vs 10.0% truth**, missed FG **6.7% vs 3.1%** --
  the sim misses more than twice as many field goals as reality, which the merged
  bucket hid entirely.
- **Outcome quality was never scored while fitting.** The harness now scores
  PRIMARY (structure), SECONDARY (game total, four quarters, h1/h2) and TERTIARY
  (outcome mix), with a pre-stated gate rejecting any candidate that moves a
  quarter by more than 0.05.

### The recommendation is DO NOT FLIP, and the reason generalises

The best candidate (`s4a_drive_fit_v1`, FG distance penalty 0.022 -> 0.014, red-zone
TD weight 0.58 -> 0.80) improves the outcome mix 26.79% -> 16.02% and q1/q2/q3,
but **regresses q4 from -2.0% to +3.5%** and buys nothing on structure.

Decisively: **at SAMPLED ratings -- what production actually simulates -- the fit
reverses.** Outcome quality goes 5.33% -> 6.94% and game totals 52.43 -> 54.53
against truth 53.35. The live profile is already right there and the fit
overshoots.

**The systemic finding, which is bigger than this package: every NCAAF
calibration to date was scored at rating 0.0.** Production does not simulate
rating-0.0 teams. Any calibration conclusion drawn that way -- including the
artifact's own field-goal choices, all made against the merged made/missed
bucket -- is owed a re-derivation at realistic ratings before it is trusted.
