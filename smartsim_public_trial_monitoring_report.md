# SmartSim Public Trial Operations: Monitoring Report

- Date: 2026-07-16
- Scope: NCAAF. **No simulator behavior, calibration profile, or blend formula was modified** — confirmed by an empty `git diff` against `HEAD` for `smartsim2_blend.py` and everything under `syndicate/features/football/`.
- References: `smartsim_public_trial_report.md`, `smartsim_blend_trial_report.md`, `smartsim_ensemble_evaluation_report.md`.

## Important Scoping Note, Stated Up Front

**There is no live, publicly-deployed instance of this app with real external user traffic in this environment.** This report is honest about which parts of it reflect that reality and which don't:

- **Genuine, real**: the cohort definition and token provisioning, the monitoring instrumentation itself, and — most importantly — the divergence/disagreement analysis, which runs on the actual CFBD-backed SmartSim 2.0 projections and actual Enhanced Totals Engine predictions for real games (the same week-1 2025 artifact validated in Phase 2B/3).
- **Synthetic, clearly labeled as such**: the "page views" used to exercise and validate the monitoring pipeline were driven by Flask's test client simulating one request per cohort member, not organic clicks from real people. This is a **validation exercise proving the operational mechanism works**, not a report of real usage patterns. Nothing in this document should be read as "users did X" — no user has used this yet.

## Task 1-3: Trial Cohort and Access

### Cohort definition

| Role | Count | Rationale |
| --- | --- | --- |
| Internal users | 3 | Engineering/product staff with the most context to catch correctness issues before any wider audience sees them. |
| Trusted testers | 5 | A slightly larger, still-controlled group for feedback on presentation and framing, without full public exposure. |
| Power users | 2 | The audience most likely to notice and react to a new projection source appearing on pages they already visit frequently. |

No specific real individuals are named here — this is a role-based cohort structure and a set of provisioned, usable tokens; populating actual names against these slots is an operational step for whoever runs the real trial, not something to fabricate in this report.

### Tokens generated

10 cryptographically random tokens (`secrets.token_urlsafe(18)`), one per cohort slot, stored in `data/ncaaf_source/data/smartsim2_trial_cohort.json` — **gitignored** (matches `data/*_source/data/`), since these are credentials and must not be committed. That file is the operational roster; this report does not reproduce the tokens themselves.

### Access enabled

`SMARTSIM_PUBLIC_TRIAL_ENABLED=1` with `SMARTSIM_PUBLIC_TRIAL_TOKENS` set to exactly the 10 cohort tokens. Verified (real check, via `client.get(...)` real HTTP requests, not mocks):

- All 10 cohort tokens granted trial content on `/ncaaf/cards` and `/ncaaf/picks` (20/20).
- A sample of 2 cohort members granted trial content on `/ncaaf/game/<id>` for a real in-scope game (2/2).
- A request with no token and a request with a fabricated, non-cohort token were both correctly denied trial content (2/2 rejections held).
- All requests returned HTTP 200 regardless of grant/deny outcome — denial means "show the normal page," never an error.

## Task 4: Captured Metrics (Synthetic Validation Run)

36 page-view records logged via the new `smartsim2_trial_monitoring.py` instrumentation during the cohort-access validation exercise described above:

| Route | Views logged | Avg. projection availability | Avg. SmartSim 2.0 / blend visibility | Fallback rate |
| --- | --- | --- | --- | --- |
| `/ncaaf/cards` | 22 | 18.75% | 14.49% (diluted by 2 intentional rejection-check views) | 0.0% |
| `/ncaaf/picks` | 10 | 33.33% | 33.33% (all 10 were granted-access views) | 0.0% |
| `/ncaaf/game/<id>` | 4 | 100% (only requests for in-scope games were logged — see below) | 75% (3 of 4 granted, 1 intentional rejection check) | 0.0% |

**Projection availability** (18.75% on cards, 33.33% on picks) reflects the same, already-documented FBS-vs-FBS scope boundary from every prior phase — most of a week's schedule sits outside SmartSim's calibrated scope, so most games never carry a SmartSim 2.0 projection regardless of trial access. **Fallback rate of 0.0% across all routes** means zero games were in a broken/partial state (SmartSim 2.0 available without engine data, or a trial-visible request that failed to resolve availability correctly) — every game was cleanly either fully in scope or fully out of scope.

One data-quality note caught and corrected during this exercise: the game-detail page only logs a monitoring record when a real game (with a real scoreboard) is found for the requested `gamePk` — an initial verification attempt used a `gamePk` not present in the current top-16 cards view (a pre-existing page limitation unrelated to trial access) and correctly produced no record and no trial content, rather than a false result.

## Task 5-6: Disagreement Monitoring and Notable Divergences (Real Data, 47 Games)

Computed directly from the real week-1 2025 projections (the same artifact validated in Phase 2B/3) across all 47 games with all three sources available:

| Metric | Value |
| --- | --- |
| Average margin gap (Engine vs. SmartSim 2.0) | 9.15 points |
| Median margin gap | 8.0 points |
| Average total gap | 8.63 points |
| Median total gap | 8.6 points |
| Games where the large-mismatch rule kept Consensus margin engine-only | 20 / 47 (42.6%) |
| **Games where SmartSim 2.0 favors the opposite side from the Engine** | **13 / 47 (27.7%)** |

### Notable divergences

**Largest margin disagreements** (Engine sees a blowout, SmartSim 2.0 sees a near-toss-up or the other way): New Mexico @ Michigan (23.2-point gap — the same game flagged in Phase 2B/3), Boise State @ South Florida (22.5), App State @ Charlotte (19.6), Colorado State @ Washington (16.7), Alabama @ Florida State (16.5).

**Largest total disagreements**: Nebraska @ Cincinnati stands out — Engine projects a defensive game (42.5 total), SmartSim 2.0 projects a shootout (61.3), an 18.8-point gap, with Consensus landing at 53.8 (blended, since total always blends regardless of margin size). Auburn @ Baylor and UTSA @ Texas A&M also show total gaps above 15 points.

**Side-disagreement games worth a human look** (not just close calls near zero): UNLV @ Sam Houston (Engine +13.4 home, SmartSim 2.0 −2.1) and Miami (OH) @ Wisconsin (Engine +8.7, SmartSim 2.0 −1.0) are the two cases where both systems show a real, non-trivial lean in opposite directions, rather than one system being near a toss-up.

This pattern — real, substantial disagreement concentrated in roughly a quarter of games, with the large-mismatch rule correctly suppressing the blend where the engine is confident — is consistent with everything documented in `smartsim_ensemble_evaluation_report.md`: SmartSim 2.0's value is in the independent signal it carries precisely where the two systems disagree, not in universal agreement.

## Task 8: Explicit Answers

### Were any production issues observed?

None. Every request (cohort-granted and rejection-check alike) returned HTTP 200. The full regression suite passed at the same 113/120 rate as before this session's changes (7 pre-existing, unrelated failures traced to files outside every prior phase's diff, unchanged again here).

### Were any projection artifacts missing?

No — the week-1 2025 SmartSim 2.0 artifact (generated in Phase 2B) was used as-is and required no regeneration. Games outside FBS-vs-FBS scope correctly have no artifact entry, which is expected scope behavior, not a missing-artifact defect.

### Were any fallbacks triggered?

Zero unexpected fallbacks (0.0% fallback rate on every route in the monitoring log — meaning no game was ever in a broken/partial state). The large-mismatch margin fallback (engine-only Consensus margin) fired correctly on 20/47 real games, exactly per its designed threshold, not a failure.

### Were users able to access trial features reliably?

For the synthetic validation exercise: yes, 100% — every one of the 10 cohort tokens worked correctly on every route tested, and every non-cohort request was correctly denied. **This has not yet been demonstrated with real users**, which is the honest limitation of operating in an environment with no live traffic; the mechanism is proven, real-world reliability under organic use is not yet evidenced.

### Is SmartSim ready for expanded access?

Not yet, and this report's own data explains why: 27.7% of real games show the two systems favoring opposite sides, and the average disagreement (9.15 margin points, 8.63 total points) is large enough that a wider audience seeing this without a real usage/feedback period first would be premature. The mechanism is operationally sound; the underlying forecasting question (how well does Consensus perform against real outcomes for real users) still needs the walk-forward-ratings work flagged since `smartsim_production_integration_plan.md`, unchanged by this phase.

## Rollout Recommendation

**Continue trial.** Not expand, not roll to production, not roll back:

- **Not rollback**: zero production issues, zero unexpected fallbacks, publication gates unaffected (per Phase 2B/3), full reversibility already proven.
- **Not expand yet**: the cohort as defined (10 slots) has not yet had a chance to generate real usage data — expanding before any real feedback exists would skip the entire point of a controlled trial.
- **Not production rollout**: the 27.7% side-disagreement rate and the still-open walk-forward-ratings gap are exactly the kind of open questions a trial period exists to inform, and no real-user evidence yet exists to answer them.
- **Continue trial**: distribute the real cohort tokens (from `data/ncaaf_source/data/smartsim2_trial_cohort.json`) to actual named participants, let genuine usage accumulate over at least one real game week, and re-run this monitoring analysis against real (not test-client-simulated) traffic before revisiting this recommendation.

## Final Verdict

**Trial Healthy.**

The operational infrastructure — cohort access, monitoring capture, disagreement analysis — is confirmed working correctly end-to-end with zero defects found. This verdict describes the trial *mechanism's* health, not a claim about real-user outcomes, which this phase correctly does not yet have the data to assess.
