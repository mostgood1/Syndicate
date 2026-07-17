# SmartSim Expanded Trial Planning

- Date: 2026-07-16
- Scope: NCAAF, planning only. **No code was written or modified in this phase.** SmartSim 2.0 simulation logic, both calibration profiles, the blend formulas, and the decision policy are untouched — this document proposes how to widen access to the *existing* public-trial mechanism (`SMARTSIM_PUBLIC_TRIAL_ENABLED` / `SMARTSIM_PUBLIC_TRIAL_TOKENS` / `SMARTSIM_PUBLIC_TRIAL_IP_ALLOWLIST`, all built in Phase 3 and unchanged since), not to build a new one.
- References: `smartsim_monitoring_phase2_report.md`, `smartsim_public_trial_monitoring_report.md`, `smartsim_decision_policy_report.md`, `smartsim_public_trial_report.md`, `smartsim_blend_trial_plan.md`.

## Grounding: What "Expanded Trial" Means in This Codebase, Concretely

This app has no user-account or login system (`app.py` and `syndicate/` were checked for this — none exists). "Eligibility" therefore is not a database-level user tier; it is **who is handed a trial token or whitelisted IP**, exactly the same two mechanisms Phase 3 built and Phase 3's monitoring report exercised. Expanding the trial means: (1) growing `smartsim2_trial_cohort.json`'s roster and the `SMARTSIM_PUBLIC_TRIAL_TOKENS` value it feeds, and/or (2) widening `SMARTSIM_PUBLIC_TRIAL_IP_ALLOWLIST`. No new gating code, route, or template is required — the existing `_public_trial_visible_for_request()` gate in `cards.py` already supports an arbitrary-size allowlist with no code path that scales with cohort size.

## Task 1: Expanded-Trial Eligibility

Proposed next-tier cohort, built on top of the existing 10-slot roster (3 internal / 5 trusted tester / 2 power user — all still active, unchanged):

| Tier | Proposed size | Eligibility criteria | Mechanism |
| --- | --- | --- | --- |
| Existing cohort (unchanged) | 10 | Already active since Phase 3/public-trial-operations | Named tokens in `smartsim2_trial_cohort.json` |
| **Tier 4 — extended internal** | +5-10 | Any internal staff with product/engineering context, not just the original 3 — same rationale as the original internal tier, wider net | New named tokens, same file |
| **Tier 5 — opt-in beta** | +15-25 | Self-selected users who explicitly ask for early access (e.g., in response to a changelog note) rather than being algorithmically selected — self-selection matters because these users are choosing to see an experimental, sometimes-disagreeing second projection, not being surprised by one | New named tokens, same file |
| **Office/VPN IP range** | N/A (IP-based) | Optional, only if there's a stable internal network egress IP — same IP-allowlist mechanism Phase 3 already built | `SMARTSIM_PUBLIC_TRIAL_IP_ALLOWLIST` |

**Explicit exclusion criteria** (do not grant a token to): anyone who would treat the "Model Comparison" panel as a replacement for the Enhanced Totals Engine's standard number rather than a supplementary, sometimes-disagreeing preview — `smartsim_public_trial_monitoring_report.md` measured a 27.7% side-disagreement rate on real week-1 games, which is a feature of what the trial is testing, not a defect, but it does mean a token should come with the explanatory framing already built into the trial panel (Phase 3's "shown alongside our standard projection, not in place of it" copy), not be handed out silently.

**Sizing rationale**: roughly 3x the current cohort (10 → 30-45), not 10x. Phase 2's monitoring found zero drift across 752 backtested games, which supports *some* widening, but every prior trial-related report in this project has flagged the same open item — no real user has ever actually used this mechanism yet, only test-client-simulated requests and offline backtests. A moderate step is the right size to finally generate that missing real-usage data point without making a rollback (if needed) disruptive to a very large audience.

## Task 2: Estimated Operational Impact

| Dimension | Impact of expansion | Why |
| --- | --- | --- |
| SmartSim 2.0 compute (projection generation) | **None** | Projections are generated once per week per game (`scripts/generate_smartsim2_ncaaf_projections.py`, ~300 seeds/game, run offline), independent of how many people view them. Trial audience size has zero effect on this job's cost or schedule. |
| Per-request compute | **Negligible** | `_public_trial_visible_for_request()` is a frozenset membership check against the token/IP allowlist — O(1) regardless of whether the allowlist has 10 or 45 entries. |
| CFBD API usage | **None** | Market lines and PPA ratings are fetched offline during generation/backfill, not per page view. Expanding the trial audience triggers zero additional CFBD calls. |
| Monitoring log volume | **Linear, small** | `smartsim2_trial_monitoring.py` appends one JSONL line per page view. Going from 10 to ~40 potential viewers scales this proportionally, but the format is already lightweight (a handful of floats and strings per line) — no infrastructure change needed. |
| Support / user-confusion load | **The main real cost** | More people seeing a documented ~28% side-disagreement rate means more chances for a confused "why do these disagree" question. This is a people/communication cost, not a technical one, and is the primary reason this plan proposes a moderate (not maximal) expansion. |
| Rollback cost | **Unchanged — still instant** | Unsetting `SMARTSIM_PUBLIC_TRIAL_ENABLED` still kills the feature for everyone in one step regardless of cohort size, exactly as documented in Phase 3. Expanding the cohort does not add any new rollback step. |

**Bottom line**: expanding this specific trial has essentially zero infrastructure/compute cost. The entire operational impact is human (support/communication load), not systems load — a materially different risk profile than, say, expanding a feature that scales API costs or compute with audience size.

## Task 3: Monitoring Coverage Review

| Capability | Status | Source |
| --- | --- | --- |
| Real-game backtested accuracy (MAE/RMSE/correlation/side accuracy, by source) | ✅ In place, full season (752 games) | `smartsim2_performance_tracking.py` (Phase 1/2) |
| Rolling-window and season-to-date trend tracking | ✅ In place | `smartsim2_performance_tracking.py` (Phase 2: `rolling_windows()`, `summarize_season_to_date()`) |
| Automated drift detection (performance/calibration/policy) | ✅ In place | `smartsim2_performance_tracking.py` (Phase 2: `detect_drift()`) |
| Page-view telemetry (availability rate, visibility rate, fallback rate) | ✅ In place, mechanism validated | `smartsim2_trial_monitoring.py` (Phase 3/public-trial-operations) |
| Real (non-test-client) usage data | ❌ **Still the open gap** | No real user has ever accessed this feature — every prior report on this mechanism says so explicitly, and it remains true today |
| Per-cohort-member usage tracking (which token was used, how often) | ❌ Not built | `smartsim2_trial_monitoring.py` logs aggregate route-level stats, not which specific token/cohort member generated a given page view |
| Correlation between real usage and real-game accuracy (did trial users see the games where SmartSim was right or wrong more often) | ❌ Not built | Would require joining trial-monitoring page views to the performance-tracking game log by (season, week, game) — technically straightforward, not implemented |

**Assessment**: the *forecasting-accuracy* side of monitoring is now genuinely strong (a full season, drift-checked, three ways). The *usage* side of monitoring is exactly as far along as it was in Phase 3 — proven to work mechanically, never exercised by a real person. Expanding the cohort is partly *in service of* closing this second gap; it should not be delayed further waiting for a data point that can only be generated by actually letting more real people in.

## Task 4: Rollout Safeguards

1. **Stage the increase, don't jump straight to full size.** Add Tier 4 (extended internal) first, let at least one real game week pass, confirm no support friction, then add Tier 5 (opt-in beta) — mirrors the original Stage 0→1→2→3 staging from `smartsim_blend_trial_plan.md`, applied one level down (within Stage 2, not jumping to Stage 3).
2. **Keep the master switch as the single kill point.** No change to this — `SMARTSIM_PUBLIC_TRIAL_ENABLED=0` still removes the feature for the entire expanded cohort in one step.
3. **Re-run `detect_drift()` against accumulating real-trial-period games at each stage boundary**, not just once at the end of a season. Phase 2 built this to run over any date range; use it as an active gate, not a one-time report.
4. **Repeat the Phase 3 publication-gate parity check after each cohort increase** — build the same week's page context with and without the expanded trial flags active and diff every game's `coverage_score`/`publication_status`, exactly as Phase 3 did once. This is cheap and has caught nothing broken so far, which is itself worth reconfirming each time the audience grows.
5. **Ship the "shown alongside, not instead of" explanatory framing to every new tier**, not just the original cohort — this is already built (Phase 3's trial panel copy), it just needs to reach new tokens' recipients as part of onboarding them, which is a distribution/communication step, not a code change.
6. **No change to out-of-scope-game behavior.** Games outside SmartSim's FBS-vs-FBS calibration scope must continue to show Engine-only, unaffected by trial-audience size — already true today (verified every phase), just re-stated as an explicit invariant the expansion must not disturb.

## Task 5: Rollback Criteria

Any one of the following should trigger reverting to the current 10-token cohort (or fully disabling the master switch, for the most severe items):

| Trigger | Threshold | Action |
| --- | --- | --- |
| `detect_drift()` flags **performance_drift** on real trial-period data | Any source's side accuracy or margin MAE crosses the existing review thresholds (`PERFORMANCE_DRIFT_ACCURACY_POINTS_THRESHOLD=8.0` pts, `PERFORMANCE_DRIFT_MAE_THRESHOLD=2.0`) between pre-expansion and post-expansion samples | Revert to prior cohort size; investigate before re-expanding |
| `detect_drift()` flags **calibration_drift** | SmartSim's raw total bias moves ≥`CALIBRATION_DRIFT_BIAS_POINTS_THRESHOLD=2.0` points from the 6.11 baseline `blend_total()` assumes | Revert; flag for a calibration review (recalibration itself is out of scope for any trial-stage decision) |
| `detect_drift()` flags **policy_drift** | The large-mismatch/side-disagreement SmartSim-vs-Engine accuracy gap narrows or reverses by ≥`POLICY_DRIFT_ACCURACY_POINTS_THRESHOLD=15.0` points | Revert; this would call the Phase 4 policy revision itself into question, a materially bigger issue than trial sizing |
| SmartSim in-scope availability rate regresses | Drops below the 100% baseline established in Phase 1/3 monitoring | Revert; something upstream (generation job, artifact path) broke |
| Publication-gate parity check fails | Any game's `coverage_score`/`publication_status` differs between trial-on and trial-off contexts | Revert immediately; this is a correctness bug, not a trial-sizing judgment call |
| Rendering defect | Wrong label, stale value, or a Consensus number shown for an out-of-scope game | Revert immediately, same as above |
| Real user confusion/complaints | A documented pattern of confusion specifically about source disagreement, not resolved by the existing explanatory framing | Pause further tier additions (does not necessarily require reverting the current tier), revisit the framing/copy first |

All of these are **config-reversible** (unset an env var or shrink the token list), not a code redeploy — consistent with every prior phase's rollback design.

## Task 7: Explicit Answers

### Is SmartSim ready for broader exposure?

For a **moderate, staged widening of the existing controlled trial** — yes. Phase 2's full-season backtest (752 games) found Consensus and SmartSim both outperforming the Engine on the metrics that matter, zero drift on any of three independent checks, and the large-mismatch policy revision holding up (and strengthening) across the season. For **unrestricted production rollout** — no, not yet, for the same reason every prior report on this mechanism has given: no real user has ever actually used this feature. All evidence to date is backtested-historical or test-client-synthetic. Expanding the trial is precisely how that gap gets closed; skipping straight to production rollout would not.

### What risks remain?

1. **No real-usage evidence yet** — the single largest, most consistently disclosed gap since Phase 3. A moderate expansion is designed to finally produce it.
2. **Walk-forward-ratings limitation** — SmartSim's projections still use season-aggregate CFBD PPA ratings rather than ratings as they stood before each game, a disclosed limitation since the original production-integration plan, unaffected by trial size.
3. **~28% side-disagreement rate is real and will be seen by more people** — not a defect, but the explanatory framing needs to actually reach every new token recipient, or a wider audience could read normal model disagreement as a bug.
4. **Support/communication load scales with cohort size** — the one cost dimension that isn't near-zero (see Task 2).
5. **High-total vs. low-total asymmetry** (Phase 2 finding: SmartSim's total edge concentrates in high-total games, Engine's in low-total games) — Consensus handles both well today, but this is a pattern worth continued watching as more real games accumulate, not yet actionable.

### What metrics should continue to be monitored?

Everything already built, run continuously rather than as one-off reports: `summarize_performance()` (overall + all category breakdowns), `rolling_windows()` at 50/100-game granularity, `summarize_season_to_date()`, and `detect_drift()`'s three checks — all from `smartsim2_performance_tracking.py` — plus the page-view telemetry already in `smartsim2_trial_monitoring.py` (availability/visibility/fallback rate), now finally exercised against real rather than synthetic traffic as the cohort grows.

### What conditions would trigger rollback?

Listed in full in Task 5 above; summarized, the two categories are (a) **correctness regressions** — availability drop, publication-gate mismatch, rendering defects — which should trigger immediate, full rollback regardless of trial stage, and (b) **evidence-based drift** — any of the three `detect_drift()` checks firing on real trial-period data — which should trigger reverting to the prior, smaller cohort size while the cause is investigated, without necessarily killing the trial mechanism entirely.

## Task 8: Rollout Recommendation

**Expand Trial** — specifically, a moderate, staged widening (roughly 10 → 30-45 tokens across the two new tiers defined in Task 1), not an unrestricted production rollout. This matches `smartsim_monitoring_phase2_report.md`'s own rollout recommendation and is sized to finally generate real-usage data without making a rollback, if one becomes necessary, disruptive to a large audience.

## Final Verdict

**Expand Trial.**

The forecasting evidence has been strong and stable since Phase 2 (752 real games, zero drift on three independent checks, the Phase 4 policy revision still justified and if anything more so in the season's second half). The one thing that has never changed across every trial-related report in this project is that no real person has used this feature yet — and that gap can only be closed by growing the audience, carefully and reversibly, not by waiting for more backtested evidence that a bigger sample size can no longer meaningfully add to.
