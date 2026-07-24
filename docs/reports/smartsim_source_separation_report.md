# SmartSim Production Integration Phase 2A: Source Separation Execution Report

- Date: 2026-07-16
- Scope: NCAAF UI-facing labeling only. **No SmartSim simulation logic, NFL profile, NCAAF profile, blend formulas, or projection calculations were modified.**
- Approved naming executed: Legacy football engine → **"Enhanced Totals Engine"**; SmartSim 2.0 → unchanged; Blend → **"Consensus Projection"** (constant added, not yet surfaced anywhere — see below).
- Reference: `smartsim_blend_trial_plan.md` (the audit and naming decision this execution implements).

## Task 1-3: What Changed

| File | Nature of change |
| --- | --- |
| `syndicate/features/ncaaf/smartsim2_projection.py` | Added `LEGACY_ENGINE_SOURCE_LABEL = "Enhanced Totals Engine"` and `CONSENSUS_SOURCE_LABEL = "Consensus Projection"` constants alongside the existing `SMARTSIM2_SOURCE_LABEL`; updated the module docstring to describe the completed rename (past tense, historical reference only). |
| `syndicate/features/ncaaf/cards.py` | 14 string-literal sites renamed: `source_label`, summary text ("... favors ...", "... projects ..."), panel eyebrows/details, `"SmartSim tier"` sub-labels → `"Enhanced Totals Engine tier"`, page `source_title`/`source_path`, empty-state copy, header-stat source value. |
| `syndicate/features/ncaaf/picks.py` | 10 sites: card title, eyebrows, summary text, empty-state copy, `intro_body`, `source_path`/`source_title`, warning-panel body. |
| `syndicate/features/ncaaf/live_lens.py` | 9 sites: rank-card eyebrow/meta/note, warning-panel title/body, `intro_body`, `source_path`/`source_title`, header-stat source fallback, empty-state body. |
| `syndicate/features/ncaaf/game_detail.py` | 7 sites: missing-card `status`/`summary`/panel body, header meta prefix ("SmartSim Game Hub" → "NCAAF Game Hub", with the actual engine name now carried by the already-renamed `source_label` value that follows it), `source_title`/`source_path` (×2), `intro_body`. |
| `syndicate/templates/shared/_game_card_ncaaf.html` | 4 sites: `<strong>SmartSim</strong>` → `<strong>Enhanced Totals Engine</strong>`; `<strong>SmartSim Reasons</strong>` → `<strong>Enhanced Totals Engine Reasons</strong>`; fallback copy; the static `<span>SmartSim</span>` category label (paired with the dynamic `source_label` value beneath it) → `<span>Source</span>`, since the dynamic value now correctly carries the engine's actual name and repeating "SmartSim" as a static category label above it would itself be a new ambiguity. |
| `tests/test_ncaaf_cards_local.py`, `tests/test_ncaaf_picks_local.py`, `tests/test_ncaaf_live_lens_local.py`, `tests/test_ncaaf_smartsim2_shadow.py` | Updated exact-string assertions and fixture data to match the new labels (these tests were correctly asserting the *old* strings; updating them is expected, not a regression). |

**Not changed, by design**: `smartsim2_blend.py` (blend formulas/weights — confirmed empty diff), any file under `syndicate/features/football/sim_engine/smartsim2/` (the simulator and both calibration profiles), the `source_kind: "smartsim_runtime"` internal contract value (an API/contract string asserted directly by tests, not display text — renaming it would violate "preserve existing APIs"), and the `smartsim_reasons` dict key name / `data-panel-id="smartsim-reasons"` template attribute (internal identifiers, not rendered text).

## Task 2/7: No Football Ambiguity Remains

Full-repo search for the literal string `"SmartSim runtime"` after this pass: **zero live occurrences.** The only remaining match is a single historical, past-tense mention in `smartsim2_projection.py`'s module docstring, documenting what the legacy label used to be — not a live ambiguity. Confirmed by direct grep across `syndicate/` and `scripts/`.

## Task 2/9: Basketball SmartSim Systems — Confirmed Untouched

Per `git diff --stat` against `HEAD`, the following files (identified in the Phase 2 audit as a wholly separate, unrelated system) show **zero changes**: `syndicate/features/shared/basketball_props_smart_sim.py`, `syndicate/features/wnba/cards.py`, `syndicate/features/nba/cards.py`, `syndicate/static/wnba/cards-parity.js`, `syndicate/static/nba/cards_source.js`. The generic, sport-agnostic `_game_card_generic.html` (used by MLB and the shared board template) was also left untouched — its `SmartSim` kicker is unrelated to either football engine and out of scope per the audit.

## Task 5-6: Preservation Checks

- **Projection values**: unchanged. Only string-literal labels were edited; every numeric field (`home_points`, `away_points`, `total_points`, `spread_label`'s computed margin, `win_probability`) is produced by the exact same code path as before.
- **Existing APIs**: unchanged. No dict key was renamed, added-as-replacement, or removed; `source_kind` values (`"smartsim_runtime"`, `"artifact_backed"`) are untouched.
- **Existing artifact schemas**: unchanged. `smartsim2_projections_{season}_wk{week}.csv`'s column set (`PROJECTION_CSV_COLUMNS`) was not touched.
- **Explicit source attribution**: the three approved names now exist as single-source-of-truth constants (`LEGACY_ENGINE_SOURCE_LABEL`, `SMARTSIM2_SOURCE_LABEL`, `CONSENSUS_SOURCE_LABEL`) in one file, imported everywhere they're used, rather than duplicated string literals — reducing the risk of a future partial rename. Note: `CONSENSUS_SOURCE_LABEL` is defined but **not yet referenced anywhere** — no UI surface currently renders a blend/consensus value (that is Blend Trial Stage 1/2 work, out of scope for this execution pass, which was UI-*relabeling* only).

## Verification

- Full existing NCAAF test suite (23 tests across `cards`, `picks`, `live_lens`, and the shadow-mode integration) passes with updated expectations reflecting the new names — 0 unexpected failures.
- Broader `ncaaf`/`smartsim2` suite: 87 passed, 7 failed — the same 7 failures present before this phase began, all previously confirmed (Phase 1 report) to touch files entirely absent from this or any prior phase's diff (`test_archives.py`, `test_ncaaf_refresh_runner.py`, `test_ops.py`, and the one pre-existing `test_smartsim2_calibrated_drive_simulator.py` stochastic flake). No new failures introduced.
- `smartsim2_blend.py` diff against `HEAD`: empty — confirms zero blend-formula changes.

## Task 9: Explicit Answers

### Which files changed?

Six: `syndicate/features/ncaaf/{cards,picks,live_lens,game_detail,smartsim2_projection}.py` and `syndicate/templates/shared/_game_card_ncaaf.html`, plus four test files updated to match (`test_ncaaf_cards_local.py`, `test_ncaaf_picks_local.py`, `test_ncaaf_live_lens_local.py`, `test_ncaaf_smartsim2_shadow.py`).

### Which labels changed?

Every user-facing occurrence of "SmartSim"/"SmartSim runtime" referring to the legacy predicted-totals engine (~44 sites cataloged in the Phase 2 audit) now reads "Enhanced Totals Engine." SmartSim 2.0's own labels were not touched. A `CONSENSUS_SOURCE_LABEL = "Consensus Projection"` constant was added for future use but is not yet rendered anywhere.

### Were any calculations modified?

No. Verified three ways: (1) every edit was a string-literal replacement, confirmed by direct review of each diff hunk; (2) `smartsim2_blend.py` — the file containing all blend math — has an empty diff against `HEAD`; (3) the full test suite's non-string assertions (numeric projections, blend thresholds, fallback behavior) all pass unchanged.

### Are basketball SmartSim systems untouched?

Yes, confirmed by `git diff --stat` showing zero changes to any of the five basketball-related files identified in the Phase 2 audit.

### Is Blend Trial now unblocked?

**Yes, for Stage 1.** The rename that `smartsim_blend_trial_plan.md` identified as the sole blocker before Stage 1 (an internal-only diagnostic view) is complete: football projection labeling is now unambiguous everywhere it currently renders. Stage 2 (a public-facing three-way comparison) additionally needs the `projection_sources` contract and UI work the trial plan described — not part of this execution pass, which was scoped to labeling only.

## Final Verdict

**Source Separation Complete.**

A user viewing any current NCAAF surface (cards, picks, live lens, game hub) now sees "Enhanced Totals Engine" wherever the legacy model's projection is labeled, and would see "SmartSim 2.0" if and when its shadow fields are ever surfaced (they are not, today — Phase 1 kept them internal-only, unchanged by this pass). No surface can currently display an ambiguous "SmartSim" that could refer to either system. This clears the blocker `smartsim_blend_trial_plan.md` named as the prerequisite for Blend Trial Stage 1.
