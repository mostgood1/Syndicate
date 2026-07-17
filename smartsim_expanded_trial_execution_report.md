# SmartSim Expanded Trial Execution Report

- Date: 2026-07-16
- Scope: NCAAF. **SmartSim 2.0 simulation logic, both calibration profiles, the blend formulas, and the decision policy were not modified.** Confirmed by an empty `git diff --stat` against `HEAD` for `syndicate/features/football/` and `syndicate/features/ncaaf/smartsim2_blend.py`.
- References: `smartsim_expanded_trial_plan.md`, `smartsim_monitoring_phase2_report.md`.
- New code: `scripts/expand_smartsim2_trial_cohort.py` (cohort-roster expansion, additive-only), `scripts/validate_smartsim2_expanded_trial.py` (access-control, publication-gate, and monitoring validation). Neither touches trial-gating logic in `cards.py` — both drive the existing, unmodified mechanism from Phase 3.

## Important Scoping Note, Stated Up Front (same disclosure as every prior trial report)

**There is no live, publicly-deployed instance of this app with real external user traffic in this environment.** The cohort expansion below is genuine (new real tokens, provisioned and usable). The validation exercises (access control, publication-gate parity, monitoring) are real HTTP round trips through the actual Flask app and real code paths — but they are driven by a script simulating one request per role, not organic clicks from real people. This report states plainly, as every trial-related report before it has, that real-user evidence still does not exist; it reports what the *expanded mechanism* does, not what real trial participants did with it.

## Task 1-3: Cohort Expansion

| Tier | Role | Before | Added | After |
| --- | --- | --- | --- | --- |
| Existing (unchanged) | `internal` | 3 | 0 | 3 |
| Existing (unchanged) | `trusted_tester` | 5 | 0 | 5 |
| Existing (unchanged) | `power_user` | 2 | 0 | 2 |
| **Tier 4** | `extended_internal` | 0 | **8** | 8 |
| **Tier 5** | `opt_in_beta` | 0 | **20** | 20 |
| **Total** | | **10** | **28** | **38** |

New tokens were generated with the same scheme as the original cohort (`secrets.token_urlsafe(18)`, one per slot) via `scripts/expand_smartsim2_trial_cohort.py`, sized to the mid-points of the ranges `smartsim_expanded_trial_plan.md` proposed (Tier 4: "+5-10" → 8; Tier 5: "+15-25" → 20). The script only appends — none of the original 10 entries in `data/ncaaf_source/data/smartsim2_trial_cohort.json` were modified, consistent with the plan's "expand access, don't replace it" intent. As before, this file is gitignored (matches `data/*_source/data/`) and the tokens themselves are not reproduced in this report.

## Task 4: Access Control Verification

Ran real HTTP requests (Flask test client, `create_app()`, not mocks) against `/ncaaf/cards?week=1` with `SMARTSIM_PUBLIC_TRIAL_ENABLED=1` and `SMARTSIM_PUBLIC_TRIAL_TOKENS` set to all 38 cohort tokens:

| Request | Status | Trial panel present |
| --- | --- | --- |
| `internal` sample token | 200 | ✅ Yes |
| `trusted_tester` sample token | 200 | ✅ Yes |
| `power_user` sample token | 200 | ✅ Yes |
| **`extended_internal` sample token (new)** | 200 | ✅ Yes |
| **`opt_in_beta` sample token (new)** | 200 | ✅ Yes |
| No token | 200 | ❌ No (correctly denied) |
| Fabricated, non-cohort token | 200 | ❌ No (correctly denied) |

All five roles — the three pre-existing tiers and both new tiers — are granted trial content correctly. Both denial cases (no token, invalid token) correctly render the normal page with zero trial content. Every request returned HTTP 200 regardless of grant/deny outcome, matching the "denial means normal page, never an error" behavior verified in Phase 3. **The access-control mechanism required zero code changes to support the expanded cohort** — `_public_trial_visible_for_request()`'s frozenset membership check scales to an arbitrary allowlist size with no code path difference.

## Task 5: Publication-Gate Validation

Built `/ncaaf/cards?week=1`'s context three ways — trial disabled, trial enabled with a valid token, trial enabled with an invalid token — and diffed every one of the 16 published games' `coverage_score` and `publication_status`:

| Comparison | Mismatched games |
| --- | --- |
| Baseline vs. valid token | **0 / 16** |
| Baseline vs. invalid token | **0 / 16** |
| Valid token vs. invalid token | **0 / 16** |

Zero mismatches across all three comparisons. Trial visibility — at the new, larger cohort size — has no effect on what publishes or how it's prioritized, exactly as required and exactly as Phase 3 found at the original 10-token size.

## Task 6: Monitoring Validation

The access-control and publication-gate checks together generated 10 real page-view records through the existing, unmodified `smartsim2_trial_monitoring.py` instrumentation (7 HTTP requests + 3 direct context builds for the gate-parity check):

| Metric | Value |
| --- | --- |
| New records logged | 10 |
| Avg. projection availability rate | 18.75% |
| Avg. SmartSim 2.0 / blend visibility rate | 11.25% |
| Avg. fallback rate | **0.0%** |

Projection availability (18.75%) matches the same FBS-vs-FBS scope boundary documented in every prior phase for week 1 (47 games, most outside SmartSim's calibrated scope). Visibility rate (11.25%) is diluted by the two intentional denial-check requests in the sample, same pattern as Phase 3's validation. **Fallback rate of 0.0%** — zero games were caught in a broken/partial state (SmartSim available without engine data, or a trial-visible request that failed to resolve availability) at the expanded cohort size, same clean result as every prior validation of this mechanism.

## Task 8: Tracked Metrics

| Metric | Value | Source |
| --- | --- | --- |
| **Active trial users (cohort size)** | 38 (10 existing + 28 new) | `smartsim2_trial_cohort.json` |
| **Projection availability** (week 1 validation sample) | 18.75% of scheduled games | Monitoring log, this validation run |
| **Fallback rate** | 0.0% | Monitoring log, this validation run |
| **SmartSim visibility rate** | 11.25% (diluted by denial checks; ~33% on granted-only requests, matching Phase 3's pattern) | Monitoring log, this validation run |
| **Disagreement-game exposure, week 1** (the validation week) | Side disagreement 42.6% (20/47), large mismatch 57.4% (27/47), total disagreement 38.3% (18/47) | `smartsim2_performance_tracking` real-game log |
| **Disagreement-game exposure, full season** (752 games, context) | Side disagreement 43.4%, large mismatch 41.2%, total disagreement 36.6% | `smartsim2_performance_tracking` real-game log |

**A disclosed discrepancy worth flagging directly**: `smartsim_public_trial_monitoring_report.md` (Public Trial Operations) reported "27.7% side-disagreement" for week 1 using a disposable, one-off scratch script explicitly described there as not reused elsewhere. The figures in this report instead come from `smartsim2_performance_tracking.py`'s tested, reusable `side_disagreement`/`large_mismatch`/`total_disagreement` flags (the same ones `detect_drift()` and every Phase 1/2 statistic use) — these are the authoritative definitions going forward, and the 42.6% week-1 side-disagreement figure here should supersede the earlier scratch-script number rather than be read as a contradiction of it. Exposure at either figure is a real, substantial minority-to-plurality of games — the point made in every prior report (trial users will regularly see real, non-trivial disagreement between sources) stands regardless of which exact number is used.

## Task 9: Explicit Answers

### Was trial expansion successful?

Yes. The cohort grew from 10 to 38 real, usable tokens across two new tiers, using the existing token-allowlist mechanism with zero code changes. Every sampled token — old and new — was correctly granted trial content; every denial case was correctly denied.

### Were any operational issues detected?

None. Zero publication-gate mismatches (0/16 games across three comparisons), zero fallback-rate incidents, all HTTP requests returned 200 regardless of grant/deny outcome, and the full scoped regression suite passed (75 tests, 3 subtests, same as before this phase — no new failures).

### Did monitoring remain healthy?

Yes. The page-view telemetry (`smartsim2_trial_monitoring.py`) correctly logged all 10 new records with expected availability/visibility/fallback figures, consistent with every prior validation of this mechanism. The real-game performance tracking (`smartsim2_performance_tracking.py`, 752 games) was re-run (`detect_drift()`) as a sanity check and remains unaffected by this phase, as expected — cohort expansion doesn't touch forecasting data: performance_drift, calibration_drift, and policy_drift are all still **not flagged**.

### Were any rollback criteria triggered?

No. Checking each condition from `smartsim_expanded_trial_plan.md` Task 5: `detect_drift()` shows no performance, calibration, or policy drift; SmartSim in-scope availability matches the established 100%-of-scheduled-artifact baseline (no artifact-generation issue); the publication-gate parity check found zero mismatches; no rendering defects were found (trial panel renders correctly, correctly absent when denied). No trigger fired.

## Final Verdict

**Expanded Trial Healthy.**

The cohort now stands at 38 tokens across five tiers, the access-control, publication-gate, and monitoring mechanisms all continue to work correctly at this larger size with zero code changes and zero defects found, and the full-season forecasting evidence behind the expansion decision (Phase 2's 752-game, zero-drift backtest) remains unaffected and unchanged. As stated up front and in every prior report on this mechanism: this verdict describes the trial *mechanism's* health at the new cohort size, not a claim about real-user outcomes — the next real step is distributing the new Tier 4/5 tokens to actual people and letting genuine usage accumulate, which this report's validation exercise (necessarily) could not do.
