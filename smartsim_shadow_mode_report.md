# SmartSim 2.0 Production Integration — Phase 1 (Shadow Mode) Report

- Date: 2026-07-16
- Scope: NCAAF. **SmartSim 2.0 calibration was not modified** — `NCAAF_CALIBRATION_PROFILE` was imported and used exactly as shipped. No NFL or NCAAF profile parameters were touched.
- References: `smartsim_production_integration_plan.md`, `smartsim_integration_assessment.md`, `smartsim_ensemble_evaluation_report.md`.

## What Was Built

| Task | Delivered |
| --- | --- |
| 1. Rename legacy "SmartSim runtime" references | **Deliberately narrowed — see "Naming Decision" below.** |
| 2. Introduce SmartSim 2.0 as a distinct source | `SMARTSIM2_SOURCE_LABEL = "SmartSim 2.0 (shadow)"` in `syndicate/features/ncaaf/smartsim2_projection.py` — unambiguously different from the legacy `"SmartSim runtime"` string. |
| 3. `SmartSimNcaafProjection` contract | `syndicate/features/ncaaf/smartsim2_projection.py` — frozen dataclass matching the plan exactly, plus CSV read/write helpers. |
| 4. Standalone artifact | `syndicate/features/ncaaf/smartsim2_blend.py` implements the weighted-blend formula from `smartsim_ensemble_evaluation_report.md` (fixed correlation-derived weights, SmartSim total bias correction, the toss-up/large-mismatch conditional rule from `smartsim_production_integration_plan.md`). |
| 5. `scripts/generate_smartsim2_ncaaf_projections.py` | New CLI batch job. Reads the legacy engine's own weekly schedule, resolves CFBD season-PPA team ratings, runs `simulate_game` 300 seeds/game via the unmodified `NCAAF_CALIBRATION_PROFILE`, writes `data/ncaaf_source/data/smartsim2_projections_{season}_wk{week}.csv`. |
| 6. Integration at `_runtime_scoreboard_projection()` | Additive-only: new `_smartsim2_projection_index()` cached loader + `_attach_smartsim2_shadow_fields()` helper add `smartsim2_*`/`blend_*` keys to the returned dict; every pre-existing key (`home_points`, `away_points`, `total_points`, `spread_label`, `win_probability`, `source_label`, `kickoff`, `venue`) is untouched. |
| Tests | `tests/test_ncaaf_smartsim2_shadow.py` (7 new tests): fallback behavior, additive-field correctness, blend threshold logic. |

### Naming decision: Task 1 was intentionally narrowed to avoid violating this phase's own success criterion

`smartsim_production_integration_plan.md` flagged that the legacy engine's user-facing branding already uses "SmartSim" (`source_label: "SmartSim runtime"`, function names like `build_smartsim_cards_page_context`, and the rendered summary text "SmartSim projects..."). Investigating the full rename surface for this phase revealed it is **larger than one string**: the same `"SmartSim runtime"` label and a hardcoded `<strong>SmartSim</strong>` heading are rendered by **three** features (`cards.py`, `picks.py`, `live_lens.py`) and **two** templates (`_game_card_ncaaf.html` and the live-lens template), all consuming the identical `_runtime_scoreboard_projection()` seam. Renaming the actual rendered strings would be a real, visible UI text change — directly contradicting this phase's stated success criterion ("SmartSim operates inside the Syndicate pipeline without affecting production outputs") and the explicit "no user-visible output changes" directive.

**Resolution taken**: the legacy engine's existing strings were left completely untouched (confirmed unchanged — see verification below). Disambiguation was achieved entirely on the SmartSim 2.0 side: the new `SMARTSIM2_SOURCE_LABEL` constant, new dataclass, new artifact filename, and new dict keys (`smartsim2_*`, `blend_*`) are all clearly and separately named, and none of them are read by any existing template (verified — see below), so they cannot collide with or be mistaken for the legacy label anywhere in today's UI. **The actual legacy-string rename remains an open follow-up**, to be done as its own dedicated, visible-change-approved pass — not silently bundled into a phase whose entire point is to be invisible.

## Verification: Zero User-Visible Output Change

- Confirmed the `scoreboard` dict returned by `_runtime_scoreboard_projection()` is never dumped generically (no `scoreboard.items()` iteration, no `tojson` serialization of the whole card) anywhere in `syndicate/templates/` — every consumer reads specific named fields, so new keys are inert to rendering.
- Full existing NCAAF suite (`test_ncaaf_cards_local.py`, `test_ncaaf_picks_local.py`, `test_ncaaf_live_lens_local.py` — 16 tests spanning all three consuming features) passes **unchanged**, including exact-string assertions like `context["games"][0]["detail"] == "SmartSim runtime"` and `"SmartSim projects Sam Houston" in ... ["summary"]`.
- New tests explicitly assert the legacy fields (`home_points`, `away_points`, `total_points`, `source_label`) are byte-identical whether or not a SmartSim 2.0 projection is available for a game.

## Task 7: Captured Per-Game (Week 8, 2025 — a week not used in either prior backtest report)

59 real FBS-vs-FBS games captured with all four values — engine projection, SmartSim 2.0 projection, weighted blend, and market line — every one of the 300-seed simulations succeeding. Sample:

| Matchup | Engine (H-A) | SmartSim (H-A) | Blend margin | Blend total | Market margin | Market total |
| --- | --- | --- | --- | --- | --- | --- |
| New Mexico State @ Liberty | 39.4-21.5 | 29.6-27.9 | 8.0 | 58.7 | +10.8 | 48.2 |
| Arkansas State @ South Alabama | 29.4-32.3 | 29.7-29.0 | -0.7 | 60.0 | +8.5 | 57.3 |
| Florida Int'l @ Western Kentucky | 38.3-22.1 | 29.5-27.7 | 8.4 | 60.7 | +9.8 | 55.5 |
| Delaware @ Jacksonville State | 26.4-17.5 | 30.0-29.2 | 4.9 | 50.7 | -2.8 | 55.7 |
| UTEP @ Sam Houston | 36.6-16.5 | 26.6-25.6 | 9.2 | 52.9 | -3.5 | 46.8 |

(Full 59-game capture available in the disposable analysis script used to produce this table; not committed, per this project's established tmp-file convention.)

## Task 9: Operational Metrics

| Metric | Result |
| --- | --- |
| **Pipeline runtime** | 307-362 seconds (two independent runs) for 59 games × 300 seeds = 17,700 total simulated games. ~5-6 minutes/week — confirms the production plan's estimate and its conclusion that this must run as an offline batch job, never inline in a request. |
| **Artifact generation success** | 2/2 runs completed without error; artifact written both times; both runs produced identical output (see reproducibility check below). |
| **Fallback rate — within SmartSim's intended scope (FBS-vs-FBS)** | **0%** (59/59 games in scope received a real SmartSim 2.0 projection). |
| **Fallback rate — against the legacy engine's full weekly schedule (all divisions)** | 80.0% (236/295) — **this is a scope boundary, not a defect.** The legacy engine's own prediction artifact covers every college football division (FBS, FCS, D2, D3, NAIA); SmartSim 2.0 (and its calibration) is FBS-vs-FBS only, per the historical truth layer. Of the 236 "no SmartSim 2.0 match" rows, manual inspection confirms every single one is a genuine non-FBS-vs-FBS game (e.g., "Trine University @ Olivet College," a D3 matchup) — none were lost to a team-name-matching failure. One additional row (Lafayette @ Oregon State) was correctly excluded as FBS-vs-FCS, exactly matching the historical truth layer's own filtering rule. |
| **Missing-data rate (engine side)** | 0% — all 295 scheduled games (all divisions) had complete `predicted_home_points`/`predicted_away_points`/`predicted_total_points`. |
| **Missing-data rate (market side, within SmartSim's scope)** | 0% — all 59 in-scope games had real CFBD market lines. (Market coverage outside FBS-vs-FBS is much sparser, as expected — small-college games rarely have betting lines — but that is outside SmartSim's scope regardless.) |
| **Reproducibility** | Two independent full-week generation runs produced **byte-identical output** on every field except the `generated_at` timestamp (verified by direct diff of both CSVs). |

## Task 10: Explicit Answers

### Can SmartSim run every week unattended?

**Yes, for FBS-vs-FBS games — with one caveat.** The pipeline completed cleanly twice with zero errors, zero manual intervention, and 100% coverage within its intended scope. The caveat: this run used **season-long CFBD PPA ratings** (the same disclosed lookahead-bias proxy from `smartsim_integration_assessment.md`), not the walk-forward rating source the production plan calls out as an open item. Weekly unattended operation at scale still needs that walk-forward rating pipeline built — today's job would need to be re-pointed at whatever rating source replaces it, not re-architected.

### Are outputs stable?

**Yes.** Bit-for-bit reproducible across independent runs of the same week (confirmed by diff, not merely asserted) — a direct consequence of SmartSim 2.0's existing seeded-determinism guarantee (established in earlier phases) surviving unchanged through this new integration layer.

### Is the projection artifact complete?

**Yes, within its defined scope.** Every FBS-vs-FBS game on the legacy engine's own schedule received a projection; the only omissions are games genuinely outside that scope (other divisions, or the one correctly-excluded FBS-vs-FCS game). "Complete" here means complete relative to the artifact's own documented scope, not relative to the legacy engine's much broader multi-division schedule — those are two different, and both correctly satisfied, definitions.

### Are there any operational blockers?

**One real blocker, one disclosed limitation, no new blockers introduced by this phase's own work:**

1. **Real blocker (pre-existing, not introduced here): the legacy engine's own test suite has 6 pre-existing failures** (`test_archives.py`, `test_ncaaf_refresh_runner.py`, `test_ops.py`) unrelated to anything in this phase — confirmed by checking that none of the failing tests' underlying files (`scripts/refresh_ncaaf_oddsapi.py`, `syndicate/features/shared/ops_refresh.py`) appear anywhere in this phase's diff against `HEAD`. These are a separate, pre-existing issue for a different investigation, not a shadow-mode regression.
2. **Disclosed limitation (not a blocker for Phase 1, but for full production rollout): walk-forward team ratings are not yet built** — this phase reused the season-aggregate PPA proxy already disclosed in `smartsim_integration_assessment.md`. Shadow mode does not need this fixed (nothing user-facing depends on it yet), but any phase that turns the blend on for real users does.
3. **Not a blocker, but a real cost to plan for**: the ~5-6 minute-per-week batch runtime multiplies by however many leagues/seasons run this in parallel; fine for one NCAAF week at a time, worth knowing before scheduling.

## Final Verdict

**Shadow Mode Ready.**

The integration operates end-to-end — real schedule in, real simulation, real artifact out, real (unmodified) blend math available — with zero measured impact on any currently-published output, confirmed both by full existing-test-suite pass-through and by direct inspection of the template-consumption layer. The one real blocker found (6 pre-existing, unrelated test failures) predates this work and does not gate it. The one open item that matters before this graduates past shadow mode (walk-forward ratings) was already flagged in the production plan and is unchanged by today's findings — this phase's job was to prove the pipeline runs cleanly in parallel with production, and it does.
