# Syndicate Render Parity Assessment (2026-05-28)

## Scope
- Compared Syndicate Render web route families against solo Render site surfaces in NFL-Betting, NCAAB, and NCAAFCompare.
- Reviewed Syndicate runtime route contracts from blueprints and parity/gate scripts.
- Reviewed data-root and mirror path resolution for all sport modules.
- Reviewed live-lens data dependencies and failure behavior.

## Inputs Reviewed
- Syndicate Render blueprint: render.yaml
- Syndicate route contracts: syndicate/blueprints/*.py
- Syndicate source loaders: syndicate/features/*/sources.py
- Syndicate parity checks: scripts/browser_parity_smoke.py, scripts/migration_gate.py, scripts/module_tracker_snapshot.py, scripts/audit_migration.py
- Solo Render configs: NFL-Betting/render.yaml, NCAAB/render.yaml, NCAAFCompare/render.yaml

## Render Endpoint Parity (Syndicate)
Syndicate already exposes MLB-shaped parity surfaces per sport module:
- Cards
- Game detail
- Live lens
- Archive
- Picks and/or props (sport-dependent)
- Season betting-card lane
- Hub

Primary evidence:
- scripts/browser_parity_smoke.py includes source and shared-board checks for MLB/NBA/NHL/WNBA plus shared board checks for NFL/NCAAF/NCAAB.
- scripts/migration_gate.py enforces protected runtime contracts and source-shell checks.
- scripts/module_tracker_snapshot.py tracks parity gap counts by module against MLB reference surfaces.

## Required Data Contracts By Module

### MLB
- Root expected under mlb_source/data
- Key families:
  - daily summaries and ladders
  - snapshots
  - sims
  - live_lens reports
  - season eval and betting-card payloads
- Live lens depends on date-scoped live_lens artifacts and market/snapshot support.

### NBA
- Root expected under nba_source/(source_artifacts)/data/processed
- Key families:
  - recommendations_slate_*.json
  - game_cards_*.csv
  - cards_sim_detail_*.json
  - live_snapshots/*.jsonl
  - live_lens tuning and accuracy payloads
  - season betting-card manifests/day payloads
- Live lens depends on live_state, live_lines, live_player_boxscore, live_player_lens, live_pbp_stats, and tuning payloads.

### NHL
- Root expected under nhl_source/data
- Key families:
  - processed recommendations/predictions
  - odds games scoreboard snapshots
  - props lines snapshots
- Live lens and accuracy depend on local processed and scoreboard/odds snapshots.

### NFL
- Root expected under nfl_source
- Key families:
  - upcoming_recs_<season>_wk<week>.csv
  - optional publish snapshots
  - current_week.json
- Live lens uses weekly mirror snapshots and route wrappers.

### WNBA
- Root expected under wnba_source/(source_artifacts)/data/processed
- Key families:
  - game cards/recommendations
  - live_snapshots
  - live lens tuning and accuracy payloads
  - props/live audit payloads

### NCAAF
- Root expected under ncaaf_source/data
- Key families:
  - recommendations_summary/index.json and week payloads
- Live lens is a read-only weekly monitor over mirrored artifacts.

### NCAAB
- Root expected under ncaab_source/api
- Key families:
  - cards/recommendations/results/date indexes
  - live_state/live_lines/live_lens_tuning mirror payloads
- Live lens behavior is explicitly mirror-first with structured missing-payload error responses.

## Live Lens Requirements Summary
- All modules require date- or week-scoped mirror artifacts to avoid empty/live-unavailable behavior.
- NCAAB explicitly returns structured "mirror unavailable" payloads when live artifacts are missing.
- MLB/NBA/WNBA/NHL live lens routes rely on local mirrored snapshot families and tuning/calibration artifacts.

## Parity Gap Found
The main Render parity gap was storage-root selection:
- Several module source resolvers defaulted to repo-local data paths (under src/data/...) unless sport-specific env vars were set.
- Render disk was mounted at /opt/render/project/data, but web loaders were not uniformly preferring that disk-backed mirror root.

Impact:
- Behavior could drift from solo sites after deploy/restart because runtime reads might hit repo-seeded artifacts instead of persistent-disk artifacts.

## Fixes Applied

### 1) Disk-first source root resolution
- Updated shared resolver to prefer SYNDICATE_DATA_ROOT/<sport> before repo fallback.
- File: syndicate/features/shared/source_roots.py

### 2) MLB disk-first fallback
- Updated MLB source root resolver to prefer SYNDICATE_DATA_ROOT/mlb_source and choose first existing root.
- File: syndicate/features/mlb/sources.py

### 3) NFL disk-first fallback
- Updated NFL source root resolver to prefer SYNDICATE_DATA_ROOT/nfl_source and choose first existing root.
- File: syndicate/features/nfl/sources.py

### 4) Render env wiring for all sport module roots
- Added explicit per-sport root env vars on web service:
  - SYNDICATE_MLB_SOURCE_ROOT
  - SYNDICATE_NBA_ARTIFACT_ROOT
  - SYNDICATE_NHL_SOURCE_ROOT
  - SYNDICATE_NFL_SOURCE_ROOT
  - SYNDICATE_WNBA_SOURCE_ROOT
  - SYNDICATE_NCAAF_SOURCE_ROOT
  - SYNDICATE_NCAAB_SOURCE_ROOT
- File: render.yaml

## Result
Syndicate Render web pages are now wired to read from persistent disk-backed mirrors first, which aligns runtime behavior with solo-site persistence expectations and improves route parity stability for cards, archives, and live-lens surfaces.

## Remaining Risks (Not Blockers For Web-Page Parity)
- Cron refresh jobs still run source-mode enqueue flows; if source-generation ownership remains partial for certain sports, refresh completeness may still vary by sport.
- This assessment focused on runtime parity and disk wiring; full historical content parity still depends on mirror freshness and artifact generation cadence.
