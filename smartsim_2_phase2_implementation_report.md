# SmartSim 2.0 Phase 2 Implementation Report

## Summary

Phase 2 replaces the SmartSim 2.0 drive heuristic with a calibrated prior layer derived from the existing football feature stack.

The current projection engine, NCAAF cards, picks, live lens, and publication surfaces were not modified.

## What Files Were Created

- [syndicate/features/football/sim_engine/smartsim2/drive_priors.py](syndicate/features/football/sim_engine/smartsim2/drive_priors.py)
- [tests/test_smartsim2_drive_priors.py](tests/test_smartsim2_drive_priors.py)
- [tests/test_smartsim2_calibrated_drive_simulator.py](tests/test_smartsim2_calibrated_drive_simulator.py)
- [smartsim_2_phase2_implementation_report.md](smartsim_2_phase2_implementation_report.md)

## What Files Were Modified

- [syndicate/features/football/sim_engine/smartsim2/contracts.py](syndicate/features/football/sim_engine/smartsim2/contracts.py)
- [syndicate/features/football/sim_engine/smartsim2/possession_state.py](syndicate/features/football/sim_engine/smartsim2/possession_state.py)
- [syndicate/features/football/sim_engine/smartsim2/drive_simulator.py](syndicate/features/football/sim_engine/smartsim2/drive_simulator.py)
- [syndicate/features/football/sim_engine/smartsim2/__init__.py](syndicate/features/football/sim_engine/smartsim2/__init__.py)

## What Interfaces Were Added

- `DrivePriorProfile`
- `build_drive_priors()`
- `drive_outcome_distribution()`
- `SimulationOutput` alias preserved in the SmartSim 2.0 contract module

## Which Football Features Now Influence Simulation?

Phase 2 now uses priors derived from:

- offensive EPA and success rate
- defensive EPA and success rate allowed
- pace / seconds per play
- red-zone efficiency
- explosive-play rate
- player usage
- market totals, spreads, model probability, confidence, and edge
- returning production
- coach continuity
- transfer impact / volatility

These features now influence drive success, turnover risk, explosive-play chance, scoring probability, punt probability, and expected drive length.

## How Are Possession Outcomes Calibrated?

Possession outcomes are now chosen from a calibrated drive-outcome distribution built from football priors plus the current possession state.

The simulator now adjusts:

- touchdown likelihood in scoring range and red-zone states
- field-goal likelihood in shorter-field states
- turnover risk on long-yardage or high-pressure possessions
- punt likelihood when drives stall or start deep
- turnover-on-downs likelihood when drive success drops and field position is poor

## Which Phase 1 Heuristics Remain?

The following remain simplified:

- field-position evolution is still coarse and not play-by-play
- clock consumption is still modeled as a prior-based estimate rather than a full snap-level clock model
- overtime remains a minimal fallback
- live game-state forecasting is not yet wired in

## What Remains Before Field-Position Modeling?

The next step is to move from drive-level priors to richer field-position transitions:

- play-by-play or chunk-play field progression
- red-zone compression rules by spot on the field
- turnover return location modeling
- punt and kickoff spot modeling
- down-and-distance transition logic after each play

## Validation

Phase 2 validation confirms that changing football inputs changes simulation output:

- stronger offensive priors raise drive success and scoring frequency
- weaker defensive priors lower turnover pressure
- input changes alter possession outcomes in the drive simulator

Focused unittest coverage passed for the new priors and calibrated drive simulator slices.