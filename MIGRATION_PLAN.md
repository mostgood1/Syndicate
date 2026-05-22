# Syndicate Migration Plan

## Guiding principles

- You are not building seven apps in one UI.
- You are building one app with seven feature modules.
- MLB is the reference design and interaction model for the first implementation pass.
- In-season sports reach full completion before off-season or overhaul-heavy backend work expands scope.
- NFL and NCAAF should mirror MLB fully at the frontend layer now, but deeper sim-engine overhaul work stays deferred until after NCAAB.
- NCAAB is the first post in-season full-completion target because its model, live-lens, and sim stack are already mature.
- After migrating each sport, immediately extract shared logic into a shared layer before migrating the next sport.
- Existing sport apps stay functional until Syndicate is complete.

## Current track

1. Shared Syndicate shell is in place.
2. MLB is the phase-1 complete reference module with cards, live-lens, a daily archive, season betting-card surfaces, and aligned shared rank-board API transport across its main ranked modules.
3. NBA is an active source-backed migration with cards, picks, live-lens, season betting-card routes, and a stored-date archive under the MLB-shaped public contract.
4. WNBA is an active shared-board migration with a stored-date archive lane.
5. NHL is an active source-backed migration with cards, a game drill-in, ranked picks, a live-lens board, and a stored-date archive lane.
6. NFL currently sits in a frontend-parity lane: cards, a game drill-in, grouped weekly picks, a season betting-card companion, explicit missing-week empty states, and source-style picks API aliases are the visible target, while deeper sim-engine overhaul stays deferred.
7. NCAAF is in the same frontend-parity lane with artifact-backed weekly cards, a game drill-in, picks, and a season betting-card companion, while NCAAB remains the next full-completion target with source-backed cards, a first game drill-in, a read-only live-lens board, a season review page, a historical betting-card companion, and a results archive.

## Current layered scorecard

The migration now needs to be tracked across three layers, not one.

1. Frontend parity: whether the real cards, game, live-lens, archive, and hub families behave like the source product under Syndicate routes.
2. Artifact maturity: whether Syndicate can run those surfaces from mirrored local artifacts instead of sibling-repo reads or source-app execution.
3. Sim and analytics substrate: whether the underlying sim outputs, live analytics, and evaluation bundles are expressed as stable Syndicate-owned contracts instead of source-owned route proxies or narrow processed exports.

Current readout:

| Sport | Frontend parity | Artifact maturity | Sim/analytics substrate | Primary posture |
| --- | --- | --- | --- | --- |
| MLB | Strong | Strong but partial | Moderate | mirror-first reference contract |
| NBA | Strong | Moderate | Moderate-to-weak | mirror-backed with source parity glue |
| WNBA | Good | Moderate | Weak-to-moderate | mirror-backed with source API proxy |
| NHL | Good | Moderate | Moderate | mirror-first processed artifacts plus source live contract reuse |
| NFL | Good for weekly module | Moderate but narrow | Weak | narrow mirror-backed weekly contract |
| NCAAF | Honest weekly artifact surface | Moderate but narrow | Weak | summary-first weekly mirror contract |
| NCAAB | Good surface coverage | Weak-to-moderate | Weak | mixed mirror plus subprocess source-app API calls |

The key planning rule is that a module can be visually coherent before it is operationally independent. For sequencing, full operational completion now means: in-season sports first, then NCAAB, then NFL and NCAAF backend depth.

## Priority sequence

1. Finish the active in-season sports to full completion across frontend parity, artifact maturity, and sim or analytics ownership.
2. Move next to NCAAB and remove its remaining source-app dependency so its mature model, live-lens, and sim stack are fully owned under Syndicate contracts.
3. Hold NFL and NCAAF deeper backend work until last, except for mirroring MLB's frontend representation as completely and honestly as possible.
4. Treat NFL and NCAAF sim-engine work as likely overhaul projects rather than normal follow-on migration tasks.

## Phase-1 completion rubric

A module is "phase-1 complete" only when all of the following are true for its real source-backed scope:

1. The hub launches the module's primary real workflow from stored or live source-backed dates or weeks.
2. Core navigation preserves the same season/date/week identity across hub, cards, ranked boards, drill-ins, archive lanes, and betting-card companions where those surfaces exist.
3. Shared transport is stable for the module's active surfaces: `game_board_v1` for cards or game views, and rank-board transport parity for ranked or archive views.
4. The home tracker, README, and migration plan all describe the same visible surfaces honestly.
5. The focused regression suite covers the module's active launchers and navigation contracts well enough to catch obvious parity regressions.

Phase-1 complete does not mean the source app is fully retired. It means the current agreed Syndicate scope for that module is coherent, honest, and regression-covered.

## Near-term detailed queue

1. MLB: close the remaining lower-layer gaps so the reference module is also the first fully complete module across frontend, artifacts, and analytics ownership.
2. NBA: tighten live-lens, season betting-card, archive, and analytics families until the full in-season workflow is operationally complete instead of just surface-complete.
3. WNBA: do the same, especially around live game and prop analytics contracts that still lean on source proxies.
4. NHL: complete the in-season contract across cards, props, archive, live-lens, and required sim or evaluation artifacts.
5. NCAAB: queue immediately behind the in-season sports and harden the settled-date workflow across season review, historical betting-card, results archive, and live-lens entrypoints.
6. NFL and NCAAF: keep frontend mirroring honest and MLB-shaped, but defer deeper backend and sim-engine expansion until the post-NCAAB phase.

## Next 10 execution tasks

1. Expand MLB mirror breadth from current-date strength into broader historical daily, live, sim, and evaluation families so MLB becomes the first truly full-completion module.
2. Normalize NBA live analytics families away from source-proxy dependence and toward mirror-backed or persisted artifact-backed contracts.
3. Normalize WNBA live analytics families the same way, especially for live game and prop audit surfaces.
4. Deepen NHL artifact coverage and document the minimum sim and evaluation families required for full cards, props, archive, and live-lens parity.
5. Define a cross-sport mirrored artifact manifest schema that records raw inputs, processed board artifacts, sim outputs, live-support artifacts, evaluation bundles, and fallback state per run.
6. Add migration-gate checks that fail when source-app fallback is exercised for surfaces that are supposed to be mirror-backed, so progress is measured by shrinking dependency, not just by page availability.
7. Add an ownership or source-independence score to the module tracker so the app distinguishes surface parity from runtime dependency on sibling repos.
8. Remove NCAAB source-app dependency from normal operation by expanding mirror coverage until the active cards, game, live-lens, and results families no longer need subprocess API fallback.
9. Bring NFL to full MLB-style frontend representation without committing yet to a deeper sim-engine overhaul.
10. Bring NCAAF to full MLB-style frontend representation without committing yet to a deeper sim-engine overhaul.

## Near-term build order

1. Finish MLB, NBA, WNBA, and NHL as the in-season full-completion group, using MLB as the reference contract and extracting only the abstractions already proven across that group.
2. Keep MLB stable as the reference board and live-lens contract while the remaining in-season modules close their artifact and analytics gaps.
3. Move next to NCAAB and eliminate the remaining source-app dependency from its settled-date, live-lens, and results workflows.
4. After NCAAB, bring NFL and NCAAF up to full MLB-style frontend representation everywhere their source products warrant it.
5. Only then plan the deeper NFL and NCAAF sim-engine overhaul work as a separate final phase.

## Current implementation rule

Every sport migration must leave the codebase in a more reusable state than before. No sport should be fully copied in and left as an isolated island if its reusable patterns can already be extracted.

An additional rule now applies: do not treat route parity as the end of the migration. A surface is only strategically complete when its required artifacts and its sim or analytics dependencies are also under an explicit Syndicate-owned contract.

For sequencing, however, that full-completion standard is applied in this order: in-season sports first, NCAAB second, NFL and NCAAF backend overhaul last.