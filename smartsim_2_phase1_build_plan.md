# SmartSim 2.0 Phase 1 Build Plan

## Status

Design only. No simulator code is implemented in this phase.

Reference architecture:

- [smartsim_2_possession_simulation_architecture.md](smartsim_2_possession_simulation_architecture.md)

## Phase 1 Goal

Create the minimum viable possession simulator kernel so SmartSim 2.0 can coexist with the current projection engine.

Phase 1 does not replace the current score-projection path. It introduces a new simulator kernel that can run beside it and later become the stateful foundation for drives, quarters, and full game state.

## What Changes First

The first code added should be the new SmartSim 2.0 contracts and state machines, not the existing projection engine.

Add the new kernel under the football simulation package:

- `syndicate/features/football/sim_engine/smartsim2/__init__.py`
- `syndicate/features/football/sim_engine/smartsim2/contracts.py`
- `syndicate/features/football/sim_engine/smartsim2/possession_engine.py`
- `syndicate/features/football/sim_engine/smartsim2/drive_engine.py`
- `syndicate/features/football/sim_engine/smartsim2/game_state_engine.py`
- `syndicate/features/football/sim_engine/smartsim2/runtime.py`

Add the first test slice beside it:

- `tests/test_smartsim2_possession_engine.py`
- `tests/test_smartsim2_drive_engine.py`
- `tests/test_smartsim2_game_state_engine.py`
- `tests/test_smartsim2_runtime.py`

## Files That Can Remain Unchanged In Phase 1

The current feature-generation and projection stack should stay intact for this phase.

Core files that remain unchanged:

- `syndicate/features/simulation_engine.py`
- `syndicate/features/shared/simulation_adapter.py`
- `syndicate/features/shared/daily_update_simulation_contract.py`
- `syndicate/features/shared/game_board_contract.py`
- `syndicate/features/football/contracts.py`
- `syndicate/features/football/adapters.py`
- `syndicate/features/football/sim_engine/football_core.py`
- `syndicate/features/football/sim_engine/nfl_adapter.py`
- `syndicate/features/football/sim_engine/ncaaf_adapter.py`
- `syndicate/features/football/features/loaders.py`
- `syndicate/features/football/features/team_metrics.py`
- `syndicate/features/football/features/advanced_metrics.py`
- `syndicate/features/football/features/matchups.py`
- `syndicate/features/football/features/pace_features.py`
- `syndicate/features/football/features/market_features.py`
- `syndicate/features/football/features/player_usage.py`
- `syndicate/features/ncaaf/cards.py`
- `syndicate/features/ncaaf/game_detail.py`
- `syndicate/features/ncaaf/live_lens.py`
- `syndicate/features/ncaaf/picks.py`
- `syndicate/blueprints/ncaaf.py`
- `tests/test_simulation_engine.py`
- `tests/test_simulation_adapter.py`
- `tests/test_football_sim_engine.py`
- `tests/test_ncaaf_cards_local.py`
- `tests/test_ncaaf_live_lens_local.py`
- `tests/test_ncaaf_picks_local.py`

This is the explicit non-goal line for Phase 1: do not modify existing football model calculations or current board routes.

## Phase 1 Interface Design

### 1. Possession State

The possession kernel should operate on a single normalized state object.

Required fields:

- `possession_owner`
- `field_position`
- `down`
- `distance`
- `clock`
- `quarter`

Recommended supporting fields:

- `game_clock_seconds`
- `drive_index`
- `possession_index`
- `score_home`
- `score_away`
- `score_diff`
- `yardline_side`
- `red_zone`
- `is_goal_to_go`
- `timeout_state`
- `game_script`

### 2. Possession Outcomes

Phase 1 should support a small closed outcome set.

Required outcomes:

- touchdown
- field goal
- punt
- turnover
- turnover on downs

Recommended Phase 1 supplemental outcomes:

- drive stall
- end-of-quarter stop
- end-of-half stop

### 3. Drive Loop

The drive loop should consume a possession state and emit one or more state transitions until a terminal drive outcome occurs.

Drive loop responsibilities:

- sample initial field position
- advance down and distance
- reduce clock based on pace and play sequence
- resolve drive-ending events
- emit the terminal possession outcome

Drive loop minimum outputs:

- drive result
- play count
- yards gained
- clock consumed
- next possession owner

### 4. Game Loop

The game loop should repeatedly invoke the possession loop until a terminal game condition is reached.

Game loop responsibilities:

- initialize the first possession
- alternate possession ownership
- apply quarter transitions
- apply halftime transitions
- stop at end of regulation unless overtime is explicitly added later

Game loop minimum outputs:

- possession log
- drive log
- quarter log
- final score
- final win probability estimate
- final spread estimate
- final total estimate

### 5. Simulator Output Contract

The Phase 1 output contract should be additive and replayable.

Required output fields:

- `simulation_kind`: `smartsim2_possession`
- `seed`
- `input_state`
- `possession_log`
- `drive_log`
- `quarter_log`
- `final_score`
- `win_probability`
- `spread`
- `total`
- `distribution_summary`
- `compatibility_summary`

Recommended compatibility fields:

- `projected_final_score`
- `projected_spread`
- `projected_total`
- `feature_generation_payload`

The compatibility fields exist so the current projection engine can remain the feature-generation layer while the new kernel matures.

## Exact Phase 1 Interfaces

New interfaces required in `syndicate/features/football/sim_engine/smartsim2/contracts.py`:

- `PossessionState`
- `PossessionOutcome`
- `PossessionStepResult`
- `DriveState`
- `DriveResult`
- `QuarterState`
- `QuarterResult`
- `GameState`
- `GameResult`
- `SmartSim2SimulationInput`
- `SmartSim2SimulationOutput`

New engine entrypoints required in the new runtime package:

- `build_initial_possession_state(...)`
- `simulate_possession(...)`
- `simulate_drive(...)`
- `simulate_quarter(...)`
- `simulate_game(...)`
- `run_smartsim2_simulation(...)`

## What Code Gets Added First

The first implementation order should be:

1. Add the contracts file with the state and result dataclasses or enums.
2. Add the possession engine with a deterministic transition function.
3. Add the drive engine that loops until a terminal drive outcome.
4. Add the game-state engine that chains possessions into a game.
5. Add the runtime facade that exposes one callable entrypoint.
6. Add focused tests for state transitions, terminal outcomes, and deterministic seeds.

## What Existing Code Is Reused

Reuse without changing behavior:

- current NCAAF weekly summary / SmartSim card generation
- current football feature loaders
- current football team, player, pace, market, and advanced metric builders
- current `SimulationEngine` projection path as the compatibility layer
- current shared simulation adapter and board contract wrappers
- current NCAAF board, game detail, live-lens, and picks routes

Why reuse matters:

- the current engine already generates the projection-facing contract
- the new kernel should consume those outputs as priors, not replace them in Phase 1
- preserving the existing stack avoids breaking the current feature-generation layer while the simulator is still being validated

## What Must Be Rebuilt

Phase 1 does not rebuild the whole stack, but it does introduce a new stateful core.

Rebuild only these simulation primitives:

- possession state transitions
- drive state transitions
- game clock advancement
- quarter transitions
- possession outcome sampling

Do not rebuild yet:

- current football feature builders
- current NCAAF card contract
- current board routes
- current projection math

## First Runnable Milestone

The first runnable milestone is a deterministic possession simulator that can:

1. Take one NCAAF game context.
2. Initialize a possession state.
3. Simulate one possession and one drive terminal outcome.
4. Repeat through an entire game loop using a fixed seed.
5. Emit possession, drive, quarter, and final-game logs.
6. Produce a final score distribution while leaving the current projection engine untouched.

That milestone is the minimum viable possession-by-possession simulator.

## Phase 1 Validation Plan

Phase 1 should be validated with unit tests only.

Required validation coverage:

- possession state initialization
- possession terminal outcomes
- drive termination and clock consumption
- quarter advancement
- game termination at regulation
- seed stability / deterministic replay
- output contract shape
- coexistence with the current projection-layer contract

Suggested pass criteria:

- the new simulator returns a stable output contract for the same seed
- the current projection engine still passes its existing tests unchanged
- the new kernel can be imported and run without any route or board wiring

## Shortest Path Summary

The shortest path is to add a new football simulator kernel beside the current projection engine, then let the existing engine continue acting as the feature-generation layer.

In order:

1. contracts
2. possession engine
3. drive engine
4. game loop
5. runtime facade
6. tests

That keeps SmartSim 2.0 additive, testable, and safe to coexist with the current production contract.