# Simulation System (Syndicate)

## Purpose
Run sports simulations and attach the outputs to cards, live-lens, intelligence, and evaluation surfaces.

## Daily Update Reference

The generated latest daily-update simulation contract at [reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json](../../reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json) is the canonical cross-sport reference for source mode, freshness, and source paths during sim-engine debugging.

## Canonical Map
Use [simulation_engine_map.md](simulation_engine_map.md) for the current per-sport engine map, input contracts, fallback behavior, and consistency gaps.

## Adapter Design
Use [simulation_adapter_design.md](simulation_adapter_design.md) for the unified adapter contract and rollout plan.

## Implementation Surface
The initial shared adapter implementation lives in [syndicate/features/shared/simulation_adapter.py](../../syndicate/features/shared/simulation_adapter.py).

The runtime attachment point for sport board payloads is [syndicate/features/shared/game_board_contract.py](../../syndicate/features/shared/game_board_contract.py).

The intelligence candidate scoring path also uses [syndicate/features/shared/simulation_adapter.py](../../syndicate/features/shared/simulation_adapter.py) to build the engine input payload.

## Core Rule
Syndicate currently has one generic Monte Carlo engine and several sport-specific data adapters. Most inconsistency comes from the adapters, not the simulator math.