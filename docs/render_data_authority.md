# Render Data Authority

Render's mounted disk is the runtime source of truth for Syndicate data.

## Required layout

The web and worker services mount the persistent data disk at `/opt/render/project/data`. Runtime reads should resolve from that disk first.

Required root structure:

- `/opt/render/project/data/mlb_source`
- `/opt/render/project/data/nba_source`
- `/opt/render/project/data/wnba_source`
- `/opt/render/project/data/nhl_source`
- `/opt/render/project/data/nfl_source`
- `/opt/render/project/data/ncaaf_source`
- `/opt/render/project/data/ncaab_source`
- `/opt/render/project/data/reports`

Required sport data roots:

- MLB: `/opt/render/project/data/mlb_source/source_artifacts/data`
- NBA: `/opt/render/project/data/nba_source/source_artifacts/data`
- WNBA: `/opt/render/project/data/wnba_source/source_artifacts/data`
- NHL: `/opt/render/project/data/nhl_source/source_artifacts/data`
- NFL: `/opt/render/project/data/nfl_source/source_artifacts`
- NCAAF: `/opt/render/project/data/ncaaf_source/source_artifacts`
- NCAAB: `/opt/render/project/data/ncaab_source/source_artifacts`

## Resolution order

Code should follow this order when choosing data roots:

1. Explicit sport-specific env var, for example `SYNDICATE_MLB_SOURCE_ROOT`.
2. `SYNDICATE_DATA_ROOT/<sport>` on Render.
3. Repo-local fallback only when not running with strict hosted storage.

## Render env contract

`render.yaml` is the canonical contract for Render. It must keep these env vars aligned with the mounted disk:

- `SYNDICATE_DATA_ROOT=/opt/render/project/data`
- `SYNDICATE_MLB_SOURCE_ROOT=/opt/render/project/data/mlb_source`
- `SYNDICATE_NBA_SOURCE_ROOT=/opt/render/project/data/nba_source`
- `SYNDICATE_NBA_ARTIFACT_ROOT=/opt/render/project/data/nba_source/source_artifacts`
- `SYNDICATE_NHL_SOURCE_ROOT=/opt/render/project/data/nhl_source`
- `SYNDICATE_NFL_SOURCE_ROOT=/opt/render/project/data/nfl_source`
- `SYNDICATE_NCAAF_SOURCE_ROOT=/opt/render/project/data/ncaaf_source`
- `SYNDICATE_NCAAB_SOURCE_ROOT=/opt/render/project/data/ncaab_source`
- `SYNDICATE_WNBA_SOURCE_ROOT=/opt/render/project/data/wnba_source`

Sport-specific live-lens and betting roots should point at the same mounted disk family, not at `/opt/render/project/src/...`.

## Compatibility rules

- NBA and WNBA source-app fallback is a compatibility path, not the normal Render data path.
- On Render, fallback should remain disabled unless explicitly required for a recovery workflow.
- Repo-local mirrors are acceptable only as a non-Render fallback.

## Odds control plane and intelligence

The intelligence layer reads persisted refresh state, the shared odds control plane, and the sport data roots above. The odds control plane should follow this precedence:

1. Shared odds-history under `reports/odds_control_plane/odds_history/<sport>`.
2. The mounted data disk family for that sport under `SYNDICATE_DATA_ROOT`.
3. No repo-checkout odds-history fallback on Render.

That means the intelligence endpoints are Render-scoped for reads, but they are not a separate data-root system. They consume the same mounted disk contract as the odds runner and refresh pipeline.

## Related code

- [render.yaml](../render.yaml)
- [shared source-root helpers](../syndicate/features/shared/source_roots.py)
- [bootstrap data root](../scripts/bootstrap_data_root.py)
