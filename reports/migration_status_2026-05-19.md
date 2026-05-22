# Syndicate Migration Status - 2026-05-19

## Executive readout

Syndicate is materially ahead on visible module coverage, solid but uneven on mirrored artifact ingestion, and still early on true sim-engine plus advanced-analytics ownership.

The execution priority should now be explicit: complete the active in-season sports end to end first, move next to NCAAB because its underlying model and live stack are already mature, and leave NFL/NCAAF deeper backend work for last apart from frontend representation parity.

The practical distinction is important:

- Frontend and route-family migration is real.
- Artifact-backed operation is partly real, but not yet unified.
- Sim-engine and advanced-analytics migration is still mostly source-owned, with Syndicate acting as the consumer and orchestrator rather than the primary producer.

This report turns the migration into a hard scorecard by sport and by layer so planning can move from "which routes exist" to "which runtime/data dependencies still sit outside Syndicate."

## Layer definitions

- Frontend parity: page families, navigation identity, live-lens behavior, and visible board parity under Syndicate routes.
- Artifact maturity: how much of the sport's required daily/live/historical data is mirrored into Syndicate and usable without source-app execution.
- Sim and analytics substrate: how much of the sport's sim-engine outputs, live analytics, eval bundles, and advanced supporting artifacts are owned by a stable local Syndicate contract rather than source-app APIs or thin processed exports.
- Ownership posture: whether Syndicate is primarily mirror-first, fallback-heavy, or still source-app/API-backed.

## Scorecard

| Sport | Frontend parity | Artifact maturity | Sim/analytics substrate | Ownership posture | Readout |
| --- | --- | --- | --- | --- | --- |
| MLB | Strong | Strong but partial | Moderate | Mirror-first, source-fallback per file | Best overall module and best current source-artifact contract; still not a full historical raw mirror. |
| NBA | Strong | Moderate | Moderate-to-weak | Mirror-backed plus source API/subprocess glue for parity slices | Page family is strong, but deeper live analytics and some season-family behavior are still source-owned. |
| WNBA | Good and improving | Moderate | Weak-to-moderate | Mirror-backed plus source API proxy | Good visible parity, but live analytics and richer underlying contracts still come from the source app. |
| NHL | Good | Moderate | Moderate | Mirror-first for processed artifacts, source-backed live contract reuse | Strong live contract reuse, but underlying sim/eval families are still sport-specific and not normalized cross-sport. |
| NFL | Good for weekly module | Moderate but narrow | Weak | Mirror-first for narrow weekly files | Coherent weekly module family, but deeper live, props, and evaluation substrate is not yet migrated. |
| NCAAF | Honest artifact-backed weekly surface | Moderate but narrow | Weak | Mirror-first for summaries, fallback to sibling repo | Good honest weekly shell, but off-season and summary-centric rather than a deep migrated analytics stack. |
| NCAAB | Good surface coverage | Weak-to-moderate | Weak | Mixed mirror plus subprocess source-app API calls | Route and page family is credible, but the least migration-safe ingestion model is still here. |

## What is genuinely complete

### Frontend/module family layer

These modules are effectively at or near the MLB-shaped reference surface for the current phase:

- MLB
- NBA
- NHL
- WNBA
- NCAAB

The latest module tracker already records zero reference-surface gaps for NBA, NHL, WNBA, and NCAAB, while NFL and NCAAF still carry explicit missing-reference-surface counts.

### Shared orchestration layer

The repo now has a real all-sports source-update-first entrypoint:

- `scripts/unified_daily_update.ps1`

That is an important transition point. Syndicate is no longer only a manual browser/UI migration project. It now has the skeleton of a true cross-sport operational pipeline.

## Recommended delivery order

1. In-season sports first: MLB, NBA, WNBA, and NHL should reach full completion across visible surfaces, mirrored artifacts, and the live or sim analytics they depend on.
2. NCAAB second: it is the next best full-completion candidate because the underlying model, live lens, and sim engine are already comparatively mature even though Syndicate still has source fallback to remove.
3. NFL and NCAAF third: mirror MLB's frontend representation fully, but treat deeper backend completion as a separate final-phase overhaul effort rather than current-line migration work.

## What is only partially complete

### Artifact contract migration

The current audit still shows multiple ingestion models coexisting:

- mirror-first file contracts for MLB, NBA, WNBA, NHL, NFL, and NCAAF
- sibling-repo fallback when mirrored files are missing
- subprocess source-app API calls for NCAAB

That means the artifact layer is operational, but not yet unified.

### Sim-engine and advanced analytics migration

Syndicate consumes many sim outputs already, but it usually does not own the production contract for them.

Examples:

- NBA and WNBA read processed `cards_sim_detail_*` and related recommendation artifacts, but several live analytics families still proxy source APIs.
- NHL consumes `predictions_sim_*` and `props_boxscores_sim_*`, but that remains a sport-specific file family rather than a generalized substrate contract.
- MLB has the strongest sim/report artifact surface, especially with live-lens reports and season betting artifacts, but still relies on source-owned generation and partial mirror breadth.
- NCAAB still depends on source-app execution for live state, live lines, live tuning, and recommendations whenever mirrored files are insufficient.

## Current maturity by layer

### 1. Frontend parity

Estimated status: high.

Reasoning:

- the shared tracker and plan align on real module surfaces
- source-backed cards/live-lens families exist for the active in-season modules
- home-board/live-card parity still needs iteration, but the main module surfaces are real rather than placeholder shells

### 2. Artifact maturity

Estimated status: medium.

Reasoning:

- mirrors exist for most sports
- the new unified updater can drive source updates and refresh/gate
- mirror depth is inconsistent across sports
- NCAAB is still not a stable mirror-only consumer
- no universal mirrored manifest contract spans all sports with the same semantics

### 3. Sim and advanced analytics substrate

Estimated status: low-to-medium.

Reasoning:

- Syndicate renders source-produced sim outputs more than it owns them
- advanced live analytics families are still often source-proxy-based
- the repo has not yet normalized a cross-sport contract for live analytics, eval bundles, reconciliation outputs, or model manifests

## Hard blockers to full migration

### 1. NCAAB still has the weakest ingestion model

`syndicate/features/ncaab/sources.py` still shells into the source app and calls Flask test-client routes when mirror files are missing or unavailable.

That is the clearest sign that Syndicate does not yet own the NCAAB contract.

### 2. No single cross-sport artifact manifest standard

The current sports expose different artifact families with different assumptions:

- MLB: rich daily/live/season files
- NBA/WNBA: processed card/recommendation/sim files
- NHL: processed predictions and props sim CSVs
- NFL/NCAAF: narrow weekly summary slices
- NCAAB: route-backed mirror plus bounded raw output export

Syndicate still lacks one normalized artifact-manifest vocabulary that says, for any run:

- which raw inputs were mirrored
- which sim outputs were mirrored
- which eval/reconciliation outputs were mirrored
- which live-support artifacts were mirrored
- which surfaces still require source fallback

### 3. Advanced analytics surfaces are still source-owned more often than artifact-owned

This is especially true in:

- NBA season/live analytics families
- WNBA live analytics and audit families
- NCAAB live and settled analytics payloads

## Next 10 highest-value engineering tasks

1. Expand MLB mirroring from strong current-date coverage to broader historical daily/live/sim/eval coverage so it becomes the first true full-completion reference contract.
2. Normalize NBA live analytics families away from source-proxy dependence and toward mirror-backed or persisted artifact-backed contracts.
3. Normalize WNBA live analytics families the same way, especially for live game and prop audit surfaces.
4. Deepen NHL mirror coverage and document which sim/eval files are required for full game, props, and archive parity instead of only current route needs.
5. Define a cross-sport mirrored artifact manifest schema covering raw inputs, processed board artifacts, sim outputs, live-support artifacts, evaluation bundles, and fallback state.
6. Add explicit migration-gate checks for "source-app fallback still exercised" so progress is measured by shrinking runtime dependency on sibling repos, not just by page availability.
7. Add a per-sport ownership score to the module tracker so the app distinguishes surface parity from source independence.
8. Remove NCAAB source-app dependency for the active surface family by expanding mirror coverage until `syndicate/features/ncaab/sources.py` no longer needs subprocess API fallback for normal operation.
9. Bring NFL to full MLB-style frontend representation while explicitly deferring its deeper sim-engine overhaul.
10. Bring NCAAF to full MLB-style frontend representation while explicitly deferring its deeper sim-engine overhaul.

## Recommendation

The plan should now treat the migration as a three-layer program:

1. keep frontend parity stable
2. drive every sport to mirror-first artifact sufficiency
3. migrate the sim and advanced-analytics substrate from source-owned generation/route proxies into explicit Syndicate-owned contracts

That shift in framing is the clearest way to avoid declaring modules "done" too early just because the routes render.
