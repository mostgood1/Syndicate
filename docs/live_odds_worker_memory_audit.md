# Live Odds Worker Memory Audit

## Purpose
This audit documents the instrumentation added to prove whether the restart/OOM condition is caused by parent-process RSS only or by the full process tree / container memory footprint.

## What Now Logs
- `scripts/refresh_odds_sources.py`
  - `PROCESS_TREE_MEMORY` and `CONTAINER_MEMORY` at startup and exit
  - memory around each sport subprocess launch
  - serial mode when `SYNDICATE_SERIAL_SPORT_REFRESH=1`
- `scripts/run_live_odds_refresh_worker.py`
  - worker startup and exit memory snapshots
- `scripts/refresh_wnba_oddsapi_props.py`
  - memory before and after SmartSim
  - memory before and after export
  - SmartSim worker count and executor type
- `syndicate/features/shared/basketball_props_features.py`
  - DataFrame snapshots at major feature-frame boundaries
- `syndicate/features/shared/basketball_props_onnx.py`
  - DataFrame snapshots for player-history and priors frames
- `syndicate/features/shared/basketball_props_edges.py`
  - DataFrame snapshot after odds/prediction merge
- `syndicate/features/shared/basketball_props_recommendations.py`
  - DataFrame snapshot for the final recommendation frame
- `syndicate/features/wnba/cards.py`
  - runtime memory checkpoints around source cards, live state, live player lens, and live lines payload construction

## How To Reproduce
1. Run the odds refresh with serial sport execution enabled.
2. Compare the logged process-tree RSS against the container memory snapshot.
3. Repeat with concurrent sport execution disabled and then enabled again.
4. For WNBA, compare the memory trace across:
   - before SmartSim
   - after SmartSim
   - before export
   - after export

## Interpretation
- If parent RSS stays stable while `CONTAINER_MEMORY` or `tree_rss_mb` climbs, the failure is below the parent process and likely comes from child processes or cumulative pandas work.
- If both stay low, the OOM is likely external to the measured refresh path.
- If the spike happens only during SmartSim, the process pool is the controlling amplifier.
- If the spike happens before SmartSim, the issue is in the data-frame construction / merge pipeline.

## Kill Switch
Set `SYNDICATE_SERIAL_SPORT_REFRESH=1` to force sequential sport refreshes and reduce concurrent process pressure during diagnosis.
