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
3. NBA is now an active artifact-backed migration with cards, picks, props, live-lens, accuracy and recap lanes, season betting-card routes, and a stored-date archive under the MLB-shaped public contract.
4. WNBA is now an active artifact-backed migration with cards, picks, props, live-lens, local audit and accuracy payloads, and a stored-date archive lane.
5. NHL is now an active artifact-backed migration with cards, a game drill-in, ranked picks, live-lens and accuracy pages, props reconciliation and props-lines surfaces, and a stored-date archive lane.
6. NFL is now a near-completion artifact-backed weekly module with cards, a game drill-in, grouped weekly picks, a read-only live-lens monitor, a weekly archive lane, and a season betting-card companion.
7. NCAAF is now an artifact-backed weekly module with cards, a game drill-in, picks, a read-only live-lens monitor, a weekly archive lane, and a season betting-card companion, while NCAAB has moved into a mirror-first college basketball lane with cards, a first game drill-in, a read-only live-lens board, a season review page, a historical betting-card companion, and a results archive.

## Current layered scorecard

The migration now needs to be tracked across three layers, not one.

1. Frontend parity: whether the real cards, game, live-lens, archive, and hub families behave like the source product under Syndicate routes.
2. Artifact maturity: whether Syndicate can run those surfaces from mirrored local artifacts instead of sibling-repo reads or source-app execution.
3. Sim and analytics substrate: whether the underlying sim outputs, live analytics, and evaluation bundles are expressed as stable Syndicate-owned contracts instead of source-owned route proxies or narrow processed exports.

Current readout:

| Sport | Frontend parity | Artifact maturity | Sim/analytics substrate | Primary posture |
| --- | --- | --- | --- | --- |
| MLB | Strong | Owned local | Strong | fully local reference contract |
| NBA | Strong | Strong | Moderate | protected artifact-backed mirror-first contract |
| WNBA | Strong | Strong | Moderate | protected artifact-backed mirror-first contract |
| NHL | Strong | Strong | Moderate | protected artifact-backed mirror-first contract |
| NFL | Strong for weekly module | Strong | Moderate-to-weak | protected artifact-backed weekly contract |
| NCAAF | Strong for weekly module | Strong | Moderate-to-weak | protected artifact-backed weekly contract |
| NCAAB | Strong | Strong | Moderate | protected artifact-backed mirror-first college basketball contract |

The key planning rule is that visible parity and runtime independence should now be tracked separately. The major remaining gap is no longer route coverage for most sports; it is deeper owned generation and hosted publication/runtime proof for the artifact-backed contracts.

## Priority sequence

1. Keep MLB stable as the fully local reference contract and avoid regressing its owned refresh/runtime path.
2. Finish the remaining deeper generator seams for NBA and WNBA, where runtime fallback is already gone but lower-level event or position helpers still trail full local ownership.
3. Keep NHL, NFL, NCAAF, and NCAAB stable on their protected artifact-backed contracts while proving the hosted worker, state, and bundle publication architecture.
4. Treat NFL and NCAAF deeper sim-engine work as likely overhaul projects rather than normal follow-on migration tasks.

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
7. Add an ownership or source-independence score to the module tracker so the app distinguishes surface parity from runtime dependency on external source repos.
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