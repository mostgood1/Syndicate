# SmartSim Production Integration Phase 2B: Internal Blend Trial Report

- Date: 2026-07-16
- Scope: NCAAF, internal-only diagnostic visibility. **No SmartSim simulation logic, NFL profile, or NCAAF calibration profile was modified.**
- References: `smartsim_shadow_mode_report.md`, `smartsim_ensemble_evaluation_report.md`, `smartsim_production_integration_plan.md`, `smartsim_source_separation_report.md`.

## What Was Built

### 1. `projection_sources` contract (Task 1-2)

Added to the scoreboard dict at the same `_runtime_scoreboard_projection()` seam Phase 1 used, structured exactly as specified:

```python
scoreboard["projection_sources"] = {
    "enhanced_totals_engine": {"label": "Enhanced Totals Engine", "home_points": ..., "away_points": ..., "margin": ..., "total": ...},
    "smartsim2": {"label": "SmartSim 2.0 (shadow)", "home_points": ..., "away_points": ..., "margin": ..., "total": ..., "available": True},
    "consensus_projection": {"label": "Consensus Projection", "margin": ..., "total": ..., "margin_blended": bool, "total_blended": bool},
}
```

All three surface margin, total, and source label as required; `enhanced_totals_engine`/`smartsim2` additionally carry home/away points, matching the contract design in `smartsim_blend_trial_plan.md`.

### 2. Weighted blend method (Task 4)

Unchanged from `smartsim_ensemble_evaluation_report.md` / the existing `smartsim2_blend.compute_blend()` (correlation-derived fixed weights, SmartSim total-bias correction, large-mismatch margin exception). **`smartsim2_blend.py` was not touched in this phase** — confirmed by an empty `git diff` against `HEAD` for that file.

### 3. Diagnostic-only visibility (Task 5)

New `_blend_trial_diagnostics_enabled()` gate in `cards.py`, reading the `SMARTSIM_BLEND_TRIAL_DIAGNOSTICS` environment variable (accepts `1`/`true`/`yes`, case-insensitive; anything else, including unset, is off). Deliberately an environment variable rather than a query parameter or header — it cannot be triggered by an external HTTP request, only by whoever controls the server process. `projection_sources` is only attached to the scoreboard when this returns `True`; otherwise the key is entirely absent, byte-identical to Phase 1 behavior.

**Rendering**: `_game_card_ncaaf.html` gained one new section, gated on `scoreboard.projection_sources`, labeled "Internal diagnostic -- not publicly visible" — this template is shared by both the cards page and the game-detail page (`card_variant == 'ncaaf_main'` routes both through it). The picks page uses a different, generic rank-card template with no `_game_card_ncaaf.html` dependency, so its diagnostic surfacing was added via `_diagnostic_source_list_items()` in `picks.py`, which appends clearly-labeled diagnostic lines to the card's existing, already-generic `list_items` list — no template change needed there.

## Task 3/6: Preservation Checks

- **Existing published projection fields**: unchanged. Verified both by unit test (`test_existing_fields_unchanged_when_no_projection_available`, `test_additive_fields_present_when_projection_available` from Phase 1, still passing) and by a fresh diagnostics-on-vs-off comparison this phase (below).
- **Publication gates unaffected**: built the cards context twice for the same week — once with diagnostics off, once on — and compared every game's `coverage_score`, `publication_status`, and `publication_priority`. **Identical in all 16 rendered cards.** Diagnostics visibility has zero effect on which games publish or how they're prioritized.

## Task 7-8: Verification and Trial Artifact

**Trial artifact**: generated `smartsim2_projections_2025_wk1.csv` — season 2025, week 1, which is the app's own current default (`/ncaaf/cards` with no explicit week parameter resolves to week 1 today; confirmed directly via `_selected_week()` in a request context). 300 seeds/game, unmodified `NCAAF_CALIBRATION_PROFILE`. Runtime: 481.1 seconds (~8.0 minutes) for 47 games (14,100 total simulated games) — consistent with the per-game cost established in Phase 1.

**Coverage**: of 197 schedule rows with complete engine predictions (out of 248 raw schedule rows spanning all divisions), 47 matched to a real FBS-vs-FBS game and received a SmartSim 2.0 projection; the remaining 150 are legitimately out of SmartSim's scope (other divisions), the same scope boundary documented in Phase 1. **Zero partial-fallback cases**: every one of the 47 in-scope games that got a SmartSim 2.0 projection also had complete engine data, so all 47 produced a full three-way `projection_sources` block — 0 games had SmartSim 2.0 data but missing engine data (or vice versa).

**Rendering verification** (real HTTP round-trip via Flask's test client, diagnostics enabled):

| Page | Route | Status | Diagnostic content present? |
| --- | --- | --- | --- |
| Cards | `GET /ncaaf/cards?week=1` | 200 | Yes ("Blend Trial: Source Comparison" section rendered) |
| Picks | `GET /ncaaf/picks?week=1` | 200 | Yes ("Internal diagnostic" list items rendered) |
| Game detail | `GET /ncaaf/game/1_New_Mexico_Michigan?week=1` | 200 | Yes (same shared template section rendered) |

Sample rendered comparison (New Mexico @ Michigan, Week 1 2025):

| Source | Margin | Total |
| --- | --- | --- |
| Enhanced Totals Engine | 23.55 | 53.20 |
| SmartSim 2.0 (shadow) | 0.39 | 58.33 |
| Consensus Projection | 23.55 (engine-only — margin exceeds the large-mismatch threshold) | 52.33 (blended, bias-corrected) |

This example also incidentally exercises the large-mismatch rule correctly in production data: the engine's 23.55-point margin is well above the 10-point threshold, so Consensus correctly falls back to the engine's own margin unblended, while total still blends per the "always blend total" rule — exactly as specified in `smartsim_production_integration_plan.md`.

**Diagnostics-off verification** (same three routes, env var unset — the production default): all three returned 200 with **zero** occurrence of "Blend Trial" or "Internal diagnostic" anywhere in the rendered HTML. Confirms the feature is completely inert unless explicitly enabled.

## Task 10: Explicit Answers

### Did all games render successfully?

Yes. All 16 cards on the default cards-page view, all 12 picks-page cards, and the sampled game-detail page rendered with HTTP 200 and no exceptions, both with diagnostics on and off.

### Were all three sources available?

For every game within SmartSim 2.0's scope: yes, 47/47 (100%). For games outside that scope (150 of 197, other divisions), only the Enhanced Totals Engine source is available — expected and unchanged from Phase 1, not a defect.

### Were any fallbacks triggered?

Two kinds, both expected and by design, not failures: (1) the scope fallback — 150 games fell back to engine-only because they're outside SmartSim's FBS-vs-FBS calibration scope; (2) the large-mismatch margin fallback — at least one sampled game (New Mexico @ Michigan) had its Consensus margin fall back to the engine's own value because the projected margin exceeded the 10-point threshold, exactly per the conditional rule in `smartsim_production_integration_plan.md`. Zero *unexpected* fallbacks: no game had a partial/inconsistent state (SmartSim available without engine data or vice versa).

### Did any UI regressions appear?

No. Full existing test suite: 94 passed (87 from before this phase, plus 7 new diagnostic-specific tests), same 7 pre-existing/unrelated failures as every prior phase (traced to files entirely outside this diff). Diagnostics-off HTTP checks confirm zero visible change to any of the three pages relative to Phase 2A's already-verified state.

### Is Stage 3 production rollout now unblocked?

**Not yet — this trial validates Stage 1, not Stage 3.** Stage 2 (a public-facing version of this same comparison, for a limited slice of games/users) and its own monitoring period per `smartsim_blend_trial_plan.md` still sit between here and Stage 3. What this phase does establish: the underlying data pipeline, blend computation, and rendering path all work correctly end-to-end on a real current-week artifact with zero regressions — the technical foundation Stage 2 would build on is now proven, not just designed.

## Final Verdict

**Blend Trial Successful.**

Internal users can now view Enhanced Totals Engine, SmartSim 2.0, and Consensus Projection side-by-side for every supported NCAAF game (47/47 in scope, 0 partial states) on all three targeted surfaces (cards, picks, game detail), with zero impact on production outputs — confirmed by identical publication-gate decisions and zero diagnostic leakage with the feature flag off. The trial met every item in its success criteria.
