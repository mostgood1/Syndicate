# SmartSim 2.0 Phase 5 Calibration Architecture

## Status

Design only. No code is modified in this phase.

References:

- [smartsim_2_phase1_implementation_report.md](smartsim_2_phase1_implementation_report.md)
- [smartsim_2_phase2_implementation_report.md](smartsim_2_phase2_implementation_report.md)
- [smartsim_2_phase3_state_engine_design.md](smartsim_2_phase3_state_engine_design.md)
- Current SmartSim 2.0 kernel implementation in [syndicate/features/football/sim_engine/smartsim2/](syndicate/features/football/sim_engine/smartsim2/)

## Phase 5 Objective

Phase 4 made SmartSim 2.0 behaviorally football-like by adding play-state context, a situation model, and football-aware play weighting.

Phase 5 makes the simulator statistically realistic.

The goal is not to add more football logic first. The goal is to calibrate the existing state engine so its simulated drive, scoring, and game distributions resemble historical football.

## What Phase 5 Must Calibrate

Phase 5 should calibrate at the drive, possession, quarter, and game layers.

### 1. Drive Length

Calibration target:

- plays per drive
- seconds per drive
- yards per drive
- drive-start to drive-end field position change
- first-down conversion rate by down and distance bucket

Why it matters:

Drive length is the clearest signal that the play engine, clock model, and fourth-down behavior are jointly realistic.

### 2. Scoring Rate

Calibration target:

- points per drive
- scoring drives per game
- scoring rate by field position band
- scoring rate by score differential band

Why it matters:

A football-like simulator can still be wrong if it scores too often or too rarely relative to possession volume.

### 3. Touchdown Rate

Calibration target:

- touchdowns per drive
- touchdowns by red-zone entry
- touchdowns by goal-to-go state
- touchdowns by quarter and game script

Why it matters:

Touchdowns are the highest-leverage scoring event and must be calibrated separately from field goals.

### 4. Field Goal Rate

Calibration target:

- field-goal attempts per drive
- made-field-goal rate by kick distance band
- field-goal attempt rate by field position and down
- red-zone field-goal conversion rate

Why it matters:

The current simulator uses field-goal logic that is plausible but not yet anchored to real attempt/make frequencies.

### 5. Turnover Rate

Calibration target:

- turnovers per drive
- interceptions versus fumbles if the data supports the split
- turnover rate by down, distance, and field position
- turnover rate in pressure situations

Why it matters:

Turnover frequency strongly affects both scoring and field-position distributions.

### 6. Punt Rate

Calibration target:

- punt rate by down and field position
- punt rate on fourth down by yard-line band
- net field-position effect after punts

Why it matters:

Punt rate is one of the most important controls on drive length and game totals.

### 7. Quarter Scoring

Calibration target:

- points by quarter
- scoring drives by quarter
- late-game scoring frequency
- end-of-half and end-of-game scoring behavior

Why it matters:

Even if overall game totals are correct, a broken time model will still produce the wrong quarter shape.

### 8. Game Totals

Calibration target:

- final game totals
- margin distribution
- over/under calibration across totals buckets
- game total distribution tails

Why it matters:

Game totals are the top-line statistical check for whether all lower-level distributions compose correctly.

## Benchmark Datasets

Phase 5 should use multiple historical benchmark layers instead of a single dataset.

### Required Benchmarks

1. Play-by-play data
- Down, distance, yardline, play result, clock, quarter, score differential
- Needed for play-type, situation, and drive-length calibration

2. Drive summaries
- Drive start and end, plays, yards, time consumed, score outcome, turnover, punt, and FG outcomes
- Needed for drive-level distribution fitting

3. Game summaries
- Final score, quarter scores, total points, possession counts, margin
- Needed for game-total and quarter-scoring validation

4. Team-level season aggregates
- Pace, scoring, scoring defense, turnover rates, punt rates, and red-zone rates
- Needed for stratified calibration and holdout validation

5. Situation splits
- Red zone
- Goal-to-go
- Two-minute drill
- Four-minute offense
- Fourth down
- Long-yardage snaps
- Backed-up territory

6. Optional play-quality features if available
- EPA
- success rate
- explosive rate
- red-zone efficiency
- pressure or sack rates
- special-teams field-position splits

### Recommended Historical Sources

- NCAA play-by-play archives
- season-level drive charts
- gamebooks or play logs
- internal football feature artifacts already used by SmartSim priors
- team-season summaries for cross-checking calibration by season and conference

### Dataset Split Strategy

Use at least three splits:

- calibration set: fit the simulator
- validation set: tune thresholds and weights
- holdout set: final realism check

A time-based split is preferred so the simulator is evaluated on future seasons or later weeks it did not fit on.

## Calibration Metrics

Phase 5 should not use a single score.
It should use a metric stack that measures distribution shape, event frequency, and situation-level realism.

### Event-Rate Metrics

- absolute error for drive length, points per drive, turnover rate, punt rate, FG rate, and TD rate
- relative error for rare events such as turnovers and touchdowns
- bucketed error by field-position and situation class

### Distribution Metrics

- mean absolute error for averages
- quantile error for drive length, scoring, and game totals
- Kolmogorov-Smirnov distance for continuous outputs such as drive length and total points
- Wasserstein distance for score and drive-length distributions
- chi-square or log-loss for discrete outcome buckets

### Situation Metrics

- red-zone touchdown rate error
- goal-to-go scoring rate error
- fourth-down decision distribution error
- two-minute drill scoring rate error
- four-minute offense clock-burn error

### Correlation and Shape Metrics

- score margin versus total points correlation
- drive length versus scoring outcome correlation
- field position versus scoring probability correlation
- quarter scoring shape versus historical quarter shape

### Calibration Diagnostics

- reliability curves for scoring probabilities if the simulator emits probability-like outputs
- observed-versus-expected plots by bucket
- residual analysis by season, team strength, and game state

## Simulator Evaluation Pipeline

Phase 5 should introduce a repeatable evaluation pipeline that can run after every kernel change.

### Step 1: Build Benchmark Snapshots

- Load historical game, drive, and play data
- Normalize field-position conventions and clock conventions
- Map source events to the SmartSim contract vocabulary
- Build grouped benchmark tables by season, team, and situation class

### Step 2: Run Monte Carlo Simulations

- Simulate many games per benchmark input
- Use multiple random seeds per game to estimate variance
- Preserve the same input state for a fair comparison

### Step 3: Aggregate Simulator Outputs

- Summarize drive, quarter, and game distributions
- Compute scenario slices for red zone, goal-to-go, fourth down, and clock states
- Compare mean, median, quantiles, and tail behavior

### Step 4: Score Against Benchmarks

- Measure event-rate errors
- Measure distribution distances
- Measure situation-specific discrepancies
- Track calibration drift by season, team type, and game script

### Step 5: Rank Failure Modes

- Identify the largest deltas first
- Determine whether the mismatch comes from play weights, clock burn, fourth-down logic, or field-position transitions
- Separate structural defects from simple parameter drift

### Step 6: Tune and Re-run

- Tune one layer at a time
- Re-run the same benchmark slice after every tuning change
- Promote only changes that improve holdout realism without breaking existing contract tests

## What Should Be Calibrated First?

Calibrate in this order:

1. Punt rate and fourth-down behavior
2. Drive length and clock consumption
3. Field-goal attempt rate and field-goal make rate
4. Touchdown rate in red-zone and goal-to-go situations
5. Turnover rate by down, distance, and field position
6. Quarter scoring shape
7. Game totals and margin distribution

This order is intentional.

Punt and fourth-down decisions control possession count and field position.
Drive length and clock consume then determine how many possessions exist.
Scoring rates sit on top of that possession structure.
Game totals should be tuned last because they are an aggregate outcome, not the first control point.

## Which Phase 4 Assumptions Should Be Tuned First?

Phase 4 added useful football logic, but several assumptions are still heuristic and should be tuned before any deeper model refactor.

### First tuning targets

- red-zone touchdown and field-goal weights
- field-goal range thresholds
- two-minute drill and four-minute offense thresholds
- fourth-down punt versus field-goal decision behavior
- clock-consumption multipliers for gain, sack, turnover, and field-goal outcomes
- backed-up-territory penalty on aggressive play calling

### Why these first

These assumptions directly control possession count, scoring frequency, and game totals.
If they are wrong, later calibration layers will only fit the wrong shape more precisely.

### Later tuning targets

- turnover return spot modeling
- punt net-field-position modeling
- down-and-distance-specific gain distributions
- score-differential game-script effects
- team-specific situational adjustments

## Which Current Outputs Are Most Likely Unrealistic?

The most likely unrealistic outputs are the outputs that depend on the current heuristics most heavily.

### Most likely unrealistic now

- drive length
- punt frequency on fourth down
- field-goal attempt frequency in marginal field position
- touchdown frequency in red-zone and goal-to-go sequences
- quarter-scoring distribution
- total points distribution

### Why these are likely off

The current kernel already has play-state structure, but the play weights, clock burn, and fourth-down decisions are still rule-driven heuristics rather than fitted parameters.

### Less likely to be the first problem

- basic possession state transitions
- seed determinism
- contract shape
- score bookkeeping

Those are already covered by the current tests and are less likely to be the first realism defect.

## What Data Is Required?

At minimum, Phase 5 needs:

- historical play-by-play with down, distance, field position, quarter, clock, and result
- drive summaries with plays, yards, time, and outcome
- game summaries with quarter scores and final totals
- team-season context for pace, scoring, and red-zone rates
- situation labels or enough raw state to derive them

If available, also include:

- fourth-down decision data
- special teams field-position data
- turnover return yards and spots
- timeouts and end-of-half state
- opponent-adjusted team metrics

## How Do We Measure Simulator Quality?

Simulator quality should be measured at three levels.

### 1. Contract correctness

- outputs remain structurally valid
- seed stability holds
- possession and drive logs are internally consistent

### 2. Statistical realism

- event rates match historical benchmarks
- distribution shape matches historical benchmarks
- situation splits match historical benchmarks
- quarter and game totals match historical benchmarks

### 3. Predictive usefulness

- the simulator preserves ranking order across strong and weak teams
- calibration improves over the Phase 4 heuristic baseline
- holdout error improves without collapsing diversity or variance

A simulator is not good because it can produce one realistic game.
It is good when its repeated simulated seasons and slates reproduce the historical shape of real football.

## Recommended Phase 5 Deliverables

Phase 5 should produce:

1. A benchmark loader for historical play, drive, and game data
2. A calibration scorer for event rates and distributions
3. A Monte Carlo evaluation runner
4. A holdout report for simulator realism
5. Parameter tuning hooks for the current SmartSim 2.0 play and drive layers
6. Regression tests that lock the calibrated contract shape in place

## Exit Criteria For Phase 5

Phase 5 is complete when:

- drive length matches historical drive-length distributions within an acceptable tolerance
- scoring, touchdown, field goal, punt, and turnover rates are close to benchmark ranges
- quarter scoring and total points are not materially biased
- holdout performance is stable across seasons or team groups
- the current kernel remains deterministic and contract-compatible

## Bottom Line

Phase 4 made SmartSim 2.0 look like football.

Phase 5 should make it behave like football statistically.

The first calibration pass should focus on fourth-down behavior, punt rate, drive length, and clock consumption, because those drive almost every downstream distribution. Once possession volume is right, scoring, quarter shape, and totals become much easier to calibrate correctly.
