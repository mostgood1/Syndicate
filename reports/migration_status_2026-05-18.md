# Syndicate Migration Status - 2026-05-18

## Current Readout

Syndicate is no longer just a shell of sport launchers. MLB, NBA, NHL, WNBA, NFL, NCAAF, and NCAAB all have cards-first routes under the shared shell, and the daily orchestration path now reaches every current migration target, including NCAAB.

The migration is not finished. The remaining gap is mostly below the page surface: several sports are still backed by route-shaped or curated artifacts rather than a fully mirrored local copy of the underlying raw data, simulation outputs, and historical evaluation artifacts.

## What Is Done

### Shared app and routing
- Cards-first sport roots are in place across all migrated sports.
- Shared hubs, archive lanes, and module navigation exist for every current sport module.
- Shared refresh wrappers now include MLB, NBA, NHL, WNBA, NFL, NCAAF, and NCAAB.
- `unified_daily_update.ps1` exists as the all-sports source-update-first entrypoint.

### Sport-by-sport status
- MLB: reference module for cards, game detail, live lens, archive, season review, betting card, and props-adjacent boards.
- NBA: cards, picks, prop ladders, live-lens family, betting-card family, and archive are all live in Syndicate.
- NHL: cards, picks, live lens, archive, betting card, and a first props pulse are present.
- WNBA: cards, picks, props, live lens, archive, and betting card are present.
- NFL: cards, game drill-in, grouped picks, live lens, archive, and betting card are present from mirrored source snapshots.
- NCAAF: weekly cards, picks, live lens monitor, archive, and betting card are present from stored weekly artifacts.
- NCAAB: mirror-first targeted API payload export now exists for display dates, schedule dates, results dates, recommendations, results-by-date, live state, live lines, and live-lens tuning.
- NCAAB: selected-date raw outputs mirror now exports bounded underlying artifacts as well, including predictions, odds, live snapshot summaries, live-lens accuracy files, and sim outputs, plus a small config bundle and manifest.

### Validation completed
- NCAAB targeted mirror export runs successfully for a requested date.
- Syndicate reads mirrored NCAAB payloads directly through the local mirror-first loader.
- NCAAB raw outputs manifest now materializes alongside the API mirror and was validated on `2026-04-06` with 31 date-scoped files and 9 config artifacts.
- `refresh_and_gate.ps1` runs successfully for the NCAAB-only path when regression tests are skipped.
- Browser parity smoke passes after the latest home-page and live-lens changes.

## What Is Partially Done

### NCAAB migration
- The NCAAB UI contract is now mirror-backed first.
- A bounded slice of the deeper NCAAB source artifact surface is now mirrored into Syndicate under `data/ncaab_source/raw_outputs`.
- Full raw parity is still incomplete because only selected-date artifacts and a curated config bundle are mirrored, not the entire historical outputs tree.
- Source-app fallback still exists in `syndicate/features/ncaab/sources.py` as a safety net.

### Mirror completeness
- MLB mirror coverage is strong but still partial relative to the full source repo artifact surface.
- NBA, NHL, and WNBA are functionally migrated at the page level, but not every raw sim, live, recon, or evaluation artifact family is mirrored in a uniform way.
- NFL and NCAAF are closer to stable artifact-backed contracts, but props parity and deeper raw-data mirroring remain open.

## Main Remaining Work

### 1. Full raw artifact mirroring
The largest migration task still open is moving from page-ready or route-ready payloads to complete local source mirrors wherever practical.

Priority order:
1. NCAAB source outputs and sim/eval artifacts
2. MLB full daily/live/sim artifact mirror completeness
3. NBA/NHL/WNBA deeper raw artifact parity
4. Cross-sport manifest conventions for mirrored artifact families

### 2. Sim engine and evaluation parity
The user suspicion is correct: Syndicate still needs more of the actual data and sim-engine piping, not just final rendered route payloads.

Still missing or incomplete across one or more sports:
- raw simulation artifacts
- richer live-lens source artifacts
- settled evaluation bundles
- reconciliation outputs
- versioned manifests that describe what was mirrored for a given run

### 3. Props parity across sports
Not every sport has a fully migrated first-class props lane.

Current state:
- strong: MLB, NBA, WNBA
- partial: NHL
- missing or placeholder: NFL, NCAAF, NCAAB

### 4. Home page as real daily board
The home page now behaves more like a real slate launcher, but it is still a lightweight route board built from cached metadata and module links.

Still open if desired:
- per-sport game counts from actual daily slate artifacts
- per-sport prop counts from stored props artifacts
- stronger live detection than date-based heuristics
- richer compact game summaries without pulling heavy live-lens payloads on the home route

## Live Lens on Render

## What was improved today
- MLB live-lens HTML routes no longer preload the full live-lens report on the server just to render the shell.
- The browser now loads the shell first and fetches the API payload separately.
- MLB live-lens API routes now return a dedicated lean payload instead of the full shared game-board contract, dropping duplicated fields the page never reads.
- NCAAB source fallback cache retention was reduced to avoid large fallback payload accumulation on long-lived workers.
- NCAAB mirror refresh now also exports a bounded `raw_outputs` bundle for the selected date, with a separate manifest and config set.
- The home page now stays on lightweight cached metadata instead of calling heavy cards or live-lens builders.

## What still needs to happen
The main Render memory risk is still in heavy live-lens or cards API payload construction, especially where a full report or large day artifact is loaded at once.

Priority follow-ups:
1. Add chunked or lazy detail loading for MLB live-lens game panels if Render profiling still shows pressure after the API trim.
2. Audit MLB cards payload construction for avoidable whole-day multi-loads.
3. Add short TTL caching around repeated lightweight directory scans only, not around large live payloads.
4. Keep live-lens HTML routes shell-first across sports so only the API path does heavy lifting.
5. Prefer mirror-backed file reads over subprocess-backed source calls wherever possible.

## Current Recommendation

The migration should now move from route parity into artifact parity.

Best next sequence:
1. Expand NCAAB raw outputs mirroring from the current bounded selected-date bundle toward fuller parity, then remove more source-app fallback.
2. Complete MLB raw artifact mirror coverage, especially live-lens and daily sim families.
3. Define a cross-sport mirrored artifact manifest contract.
4. Add missing props-family migrations for NFL, NCAAF, and NCAAB.
5. Profile live-lens API response sizes on Render and trim the largest payloads first.
