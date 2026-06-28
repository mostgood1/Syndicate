# Render Data Authority

Render's mounted disk is the runtime source of truth for Syndicate write paths and worker-owned refresh jobs. The web service can read from the checked-in repo data tree when it does not need to mutate hosted state.

## Required layout

The worker service mounts the persistent data disk at `/opt/render/project/data`. Runtime reads on the web service should resolve from the repo-local `data/` tree unless a hosted override is explicitly supplied.

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

`render.yaml` is the canonical contract for Render. It must keep the worker env vars aligned with the mounted disk, while the web service can stay repo-local for read paths:

- Worker-only: `SYNDICATE_DATA_ROOT=/opt/render/project/data`
- Worker-only: `SYNDICATE_MLB_SOURCE_ROOT=/opt/render/project/data/mlb_source`
- Worker-only: `SYNDICATE_NBA_SOURCE_ROOT=/opt/render/project/data/nba_source`
- Worker-only: `SYNDICATE_NBA_ARTIFACT_ROOT=/opt/render/project/data/nba_source/source_artifacts`
- Worker-only: `SYNDICATE_NHL_SOURCE_ROOT=/opt/render/project/data/nhl_source`
- Worker-only: `SYNDICATE_NFL_SOURCE_ROOT=/opt/render/project/data/nfl_source`
- Worker-only: `SYNDICATE_NCAAF_SOURCE_ROOT=/opt/render/project/data/ncaaf_source`
- Worker-only: `SYNDICATE_NCAAB_SOURCE_ROOT=/opt/render/project/data/ncaab_source`
- Worker-only: `SYNDICATE_WNBA_SOURCE_ROOT=/opt/render/project/data/wnba_source`

Sport-specific live-lens and betting roots should point at the same mounted disk family on the worker, while the web service may point at the repo-local `data/` tree for read-only serving.

## Compatibility rules

- NBA and WNBA source-app fallback is a compatibility path, not the normal Render data path.
- On Render, fallback should remain disabled unless explicitly required for a recovery workflow.
- Repo-local mirrors are acceptable only as a non-Render fallback.

## WNBA artifact identity requirements

- Every WNBA game artifact, home payload, live-state row, and prop row must carry a stable `event_id`.
- When a source payload only exposes a matchup id or game id alias, normalize it to the same `event_id` contract before the payload leaves the WNBA feature layer.
- Do not use a row index or other transient placeholder as the canonical WNBA game identifier.
- WNBA timestamps and date selection logic must be normalized to Central time for request routing, artifact selection, and display so UTC boundaries do not split a single slate across two dates.
- If a payload cannot be associated with an `event_id`, it should be treated as incomplete rather than silently re-keyed or merged under a synthetic id.

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
