# SmartSim Production Integration Phase 2: Source Separation and Blend Trial Plan

- Date: 2026-07-16
- Scope: NCAAF. **Nothing in this document has been implemented.** This is a planning/audit deliverable — no SmartSim 2.0 simulation logic, no NFL or NCAAF calibration parameters, and no application code were modified to produce it.
- References: `smartsim_shadow_mode_report.md`, `smartsim_production_integration_plan.md`, `smartsim_ensemble_evaluation_report.md`, `smartsim_integration_assessment.md`.

## Tasks 1-2: Source Naming Audit

### Method

Repo-wide search for every occurrence of "SmartSim" across `syndicate/`, `scripts/`, and `templates/`, then read each hit in context to determine which of three systems it refers to. This surfaced a **materially larger rename surface than Phase 1 addressed** — Phase 1 (shadow mode) only touched `cards.py`, and even there only added new fields; it never renamed the legacy label. This audit finds the same "SmartSim runtime" ambiguity in three more NCAAF-specific files Phase 1 did not examine (`picks.py`, `live_lens.py`, `game_detail.py`) plus a fourth, NCAAF-specific template.

### Category A: Legacy Projection Engine ("SmartSim runtime") — must be renamed

| File | Occurrences | Nature |
| --- | --- | --- |
| `syndicate/features/ncaaf/cards.py` | 14 | `source_label: "SmartSim runtime"`, summary text ("SmartSim projects...", "SmartSim favors..."), panel eyebrows, `"SmartSim tier"` sub-labels, page `source_title`/`source_path`, empty-state copy |
| `syndicate/features/ncaaf/picks.py` | 10 | Card title ("...SmartSim candidate"), eyebrows, summary text, page-level `source_title`/`source_path`/`intro_body` |
| `syndicate/features/ncaaf/live_lens.py` | 9 | Eyebrows, fallback `meta`/note text, page title/body, `source_title`/`source_path`, empty-state copy |
| `syndicate/features/ncaaf/game_detail.py` | 7 | `status`/`summary` for missing cards, `"SmartSim Game Hub"` header, `source_title`/`source_path`, `intro_body` |
| `syndicate/templates/shared/_game_card_ncaaf.html` | 4 | Hardcoded `<strong>SmartSim</strong>` / `<strong>SmartSim Reasons</strong>` headings, fallback copy, `<span>SmartSim</span>` label |

**All ~44 occurrences above refer to the same thing**: the pre-existing predicted-totals model (reads `college_football_schedule_2025_predicted_totals_enhanced*.csv`). None of them refer to SmartSim 2.0 (the Football Core simulator). This is the "largest remaining blocker" the task context names, and it is larger than Phase 1's own investigation found — Phase 1 only inspected `cards.py`.

### Category B: SmartSim 2.0 (Football Core) — already correctly namespaced

| File | Nature |
| --- | --- |
| `syndicate/features/ncaaf/smartsim2_projection.py` | `SMARTSIM2_SOURCE_LABEL = "SmartSim 2.0 (shadow)"`, `SmartSimNcaafProjection` dataclass, docstrings |
| `syndicate/features/ncaaf/smartsim2_blend.py` | Docstrings, blend-constant comments |
| `syndicate/features/ncaaf/cards.py` (Phase 1 additions only) | `_smartsim2_projection_index`, `_attach_smartsim2_shadow_fields`, `smartsim2_*` dict keys |
| `syndicate/features/football/sim_engine/smartsim2/**` | The simulator itself — out of scope for this document (not modified) |

No renaming needed here — this is the naming *target* everything in Category A should become unambiguous relative to, not something to change itself.

### Category C: Shared / Ambiguous — a third, unrelated system exists

This audit found something not anticipated by either prior phase: **"SmartSim" is also the existing brand name of a completely separate NBA/WNBA player-props simulator**, unrelated to football:

| File | Nature |
| --- | --- |
| `syndicate/features/shared/basketball_props_smart_sim.py` | `SmartSimConfigLocal` class, `_build_smart_sim_config_local()` — NBA/WNBA props simulation, no football connection |
| `syndicate/features/wnba/cards.py`, `syndicate/features/nba/cards.py` | "SmartSim detail artifacts provide player-level median/mean expectation" |
| `syndicate/static/wnba/cards-parity.js`, `syndicate/static/nba/cards_source.js` | Front-end references to the same basketball system |
| `syndicate/templates/shared/_game_card_generic.html` | `<div class="cards-table-kicker">SmartSim</div>` — used by `mlb/cards.html` and the shared `game_cards_board.html`; a generic, sport-agnostic dashboard label, not tied to any specific engine |

**Recommendation: do not touch Category C in this rollout.** Renaming it would expand scope from "prepare NCAAF's blend trial" to "rebrand simulation terminology across the entire product" — a different, much larger initiative with its own stakeholders (basketball props). It is flagged here only so that whoever picks the final name for the football side chooses something that does not collide with the basketball system's existing "SmartSim" usage either (see naming strategy below).

Also found: internal code comments (`live_refresh_loop.py:694`, `refresh_odds_sources.py:941,968`) mentioning "SmartSim" — these are operational/pipeline comments, never rendered to a user, and don't need to change for this rollout.

### Coverage note: "reports" and "exports"

No dedicated user-facing "reports" route exists for NCAAF today (checked every `@ncaaf_bp` route — `/hub`, `/cards`, `/game/<id>`, `/archive`, `/picks`, `/live-lens`, `/season/<season>/betting-card`, and their `/api/*` twins; no `/reports` or `/export` route exists). The closest things are: (1) the internal engineering markdown reports (`smartsim_*.md`), which are already correctly disambiguated and not user-facing product surfaces; (2) the `/api/*` JSON endpoints, which serve as the de facto "export" surface — they return the identical dict fields the HTML pages render, so the same rename applies to them automatically once the underlying Python source strings change.

## Task 4: Final Naming Strategy

| System | Proposed name | Rationale |
| --- | --- | --- |
| Legacy projection engine | **"Enhanced Totals Engine"** | Traceable to its actual data source (`college_football_schedule_2025_predicted_totals_enhanced*.csv`) rather than an arbitrary new term — reads as authentic, not invented. Does not collide with the basketball "SmartSim" system (Category C) or SmartSim 2.0. |
| Football Core simulator | **"SmartSim 2.0"** (unchanged) | Already established across four prior reports and the Phase 1 implementation; changing it now would create the exact churn this plan is trying to prevent. |
| Blended output | **"Consensus Projection"** | A standard forecasting term for a combination of independent models; clearly distinct from both source names, and honest about what it is (a combination, not a third independent engine). |

Internal code constants to introduce alongside the eventual rename (not yet added, per the "planning only" scope of this document): `LEGACY_ENGINE_SOURCE_LABEL = "Enhanced Totals Engine"` and `CONSENSUS_SOURCE_LABEL = "Consensus Projection"`, living next to the existing `SMARTSIM2_SOURCE_LABEL` in `smartsim2_projection.py` so all three names are defined in one place.

## Task 5: UI Surfaces Impacted

| Surface | Route(s) | Impacted by rename | Impacted by Blend Trial mode |
| --- | --- | --- | --- |
| Cards | `/ncaaf/cards`, `/ncaaf/api/cards` | Yes (`cards.py`, `_game_card_ncaaf.html`) | Yes |
| Picks | `/ncaaf/picks`, `/ncaaf/api/picks`, `/ncaaf/season/<season>/betting-card` (+ API) | Yes (`picks.py`) | Yes |
| Game Hub / detail | `/ncaaf/game/<id>`, `/ncaaf/api/game/<id>`, `/ncaaf/hub` | Yes (`game_detail.py`) | Yes |
| Live lens | `/ncaaf/live-lens`, `/ncaaf/api/live-lens` | Yes (`live_lens.py`) | Yes |
| Exports (JSON API) | All `/ncaaf/api/*` above | Yes (same underlying fields) | Yes |
| Archive | `/ncaaf/archive`, `/ncaaf/api/archive` | Needs verification — uses a different (summary-artifact) path per `test_archives.py`; not confirmed to render the runtime `source_label` at all. Flagged as an open item, not assumed safe. |
| Reports | — | N/A — no dedicated NCAAF reports route exists (see audit note above) | N/A |

## Task 6: Blend Trial Mode Design

**Requirement recap**: existing engine remains visible, SmartSim remains visible, blended values are visible, no hidden overrides.

This rules out the simplest-looking implementation — silently swapping the single `home_points`/`away_points`/`spread_label` values a card displays today for the blended ones. That would be a hidden override by definition, even though Phase 1's additive fields already carry everything needed to do it. Instead:

**Data contract**: the scoreboard dict gains three clearly-labeled sub-objects instead of one implicit set of fields:

```python
{
    # existing top-level fields unchanged for backward compatibility
    "home_points": ..., "away_points": ..., ...,

    # new, explicit three-way breakdown for Blend Trial surfaces
    "projection_sources": {
        "engine": {"label": "Enhanced Totals Engine", "home": ..., "away": ..., "total": ..., "spread_label": ...},
        "smartsim2": {"label": "SmartSim 2.0", "home": ..., "away": ..., "total": ..., "margin": ..., "available": bool},
        "consensus": {"label": "Consensus Projection", "home": ..., "away": ..., "total": ..., "margin": ..., "margin_blended": bool, "total_blended": bool},
    },
}
```

**UI treatment**: a three-row (or three-column) comparison directly on the existing card/picks/game-hub layouts — not a replacement of the current single-number display, an addition to it. Each row carries its own label (the three names from Task 4), so a user sees exactly which system produced which number and that they can differ. When SmartSim 2.0 has no projection for a game (out-of-scope division), the `smartsim2` and `consensus` rows are omitted entirely for that card — the existing engine-only row is what displays, which is already true today and requires no change.

**Why this satisfies "no hidden overrides"**: the engine's own number is never replaced, edited, or hidden behind a different label — it keeps its existing field name and its existing value. The blend is additive and separately labeled, exactly like Phase 1's backend integration was, just now surfaced instead of kept internal.

## Task 7: Rollout Stages

| Stage | Description | Status |
| --- | --- | --- |
| **Stage 0 — Internal only** | Additive shadow fields computed and captured, nothing rendered. | **Complete** (`smartsim_shadow_mode_report.md`). |
| **Stage 1 — Shadow + diagnostics** | An internal-only view (gated by an env flag or an `?internal=1`-style query param checked server-side, never shipped to the public template) renders the full three-way comparison for engineering/QA review across a full week's slate, using real data, before any public user sees it. | **Not started.** Next concrete step. |
| **Stage 2 — Blend visible** | The rename (Task 1-4) ships, and the three-way comparison (Task 6) goes live for a **limited** slice — e.g., one conference or a fixed percentage of games/users — with monitoring active. | Blocked on Stage 1 sign-off and the rename landing. |
| **Stage 3 — Production blend** | Consensus Projection is the default headline number for every game inside SmartSim's scope (FBS-vs-FBS), full monitoring, engine-only fallback preserved for out-of-scope games exactly as today. | Blocked on a clean Stage 2 trial period per the rollback conditions below. |

## Task 9: Explicit Answers

### What must be renamed?

Every Category A occurrence: ~44 strings across `cards.py`, `picks.py`, `live_lens.py`, `game_detail.py`, and `_game_card_ncaaf.html` — all instances of "SmartSim"/"SmartSim runtime" that refer to the legacy predicted-totals engine, renamed to "Enhanced Totals Engine" (Task 4). Category B (SmartSim 2.0's own code) needs no change. Category C (basketball props, generic template) is explicitly out of scope for this rollout.

### What is safe to expose?

The three labeled rows described in Task 6 — engine, SmartSim 2.0, and Consensus margin/total/scores — plus SmartSim 2.0's `home_win_rate` as a supplementary, clearly-labeled data point (flagged as unvalidated per the production plan, same caveat as before).

### What should remain internal?

Unchanged from the production integration plan: blend weights and the total-bias constant, `margin_stdev`/`total_stdev` (Monte Carlo consistency), `seeds_used`, `profile_name`, `rating_source`. None of these are decision-useful to an end user and all remain purely diagnostic.

### What metrics should be monitored?

All of the production plan's monitoring items (rolling backtest, availability/fallback rate, disagreement monitor, publication-gate impact) remain in force, plus two new ones specific to a *visible* trial: (1) a manual QA pass over the Stage 1 diagnostic view's full rendered output before any public exposure — verifying labels, fallback behavior, and out-of-scope-game omission all look correct with real data, not just unit-test fixtures; (2) once Stage 2 begins, tracking whether the Consensus number's live (not backtest) accuracy tracks what `smartsim_ensemble_evaluation_report.md` predicted, since a live trial is the first out-of-backtest validation this system will have had.

### What are the rollback conditions?

Any of the following should trigger an immediate revert to the previous stage (config/flag-driven, not a code redeploy, since the rename and blend-visibility should be built behind a toggle from the start): the in-scope SmartSim availability rate drops below its Phase 1 baseline (100% on the one week tested — any material regression is a signal something upstream broke); the disagreement monitor shows an abnormal spike inconsistent with the backtest's documented segment behavior; the publication-gate coverage check shows an unexpected before/after regression; or any rendering defect is found in the three-way display (wrong label, stale value, a Consensus number shown for an out-of-scope game that shouldn't have one).

## Task 10: Final Verdict

**Additional Preparation Required.**

Not a rejection — the underlying pipeline (Stage 0) is confirmed solid per `smartsim_shadow_mode_report.md`, and this document closes out the planning work Phase 2 was scoped to produce. But the rollout's own stated success criterion — "a user-visible SmartSim rollout can occur without ambiguity between the legacy engine and SmartSim 2.0" — is not yet met, because the rename this document audits has not been executed, and this audit found the rename surface to be **larger** than previously known (four files, not one; a template, not just Python strings; and a third, unrelated "SmartSim" system that must be actively avoided when finalizing names). The concrete blockers before Stage 1 can start: (1) implement the rename across the five files/template in Category A, (2) add the three-way `projection_sources` contract from Task 6, (3) build the internal-only Stage 1 diagnostic view. None of this requires touching SmartSim 2.0 or any calibration parameter — it is entirely legacy-engine-side and additive Syndicate-side work, consistent with every constraint this phase was given.
