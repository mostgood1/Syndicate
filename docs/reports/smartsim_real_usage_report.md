# SmartSim Real-Usage Monitoring Report

- Date: 2026-07-16
- Scope: NCAAF. **SmartSim 2.0 simulation logic, both calibration profiles, the blend formulas, the decision policy, and trial access controls were not modified.** Confirmed by an empty `git diff --stat` against `HEAD` for `syndicate/features/football/` and `syndicate/features/ncaaf/smartsim2_blend.py`, and by inspecting this phase's own diff to `cards.py` line-by-line: the only changes are a `default_ncaaf_source_root()` import and three `data_root = ...` path-resolution lines — the trial-gating functions (`_public_trial_master_enabled`, `_public_trial_visible_for_request`, `_env_list`) are byte-identical to before this phase.
- References: `smartsim_expanded_trial_execution_report.md`, `smartsim_monitoring_phase2_report.md`.

## A Real Gap Found and Fixed Before This Phase's Monitoring Could Mean Anything

Before starting the monitoring tasks below, the user flagged that this mechanism would need to be "wired into the self-contained Render environment" to ever produce real usage data. Investigating confirmed a genuine, pre-existing defect: `cards.py`'s Enhanced Totals Engine CSV lookup, the SmartSim 2.0 projection lookup, and this project's own `smartsim2_trial_monitoring.py`/`smartsim2_performance_tracking.py` logs all resolved their data directory as a **hardcoded path relative to the source file** (`Path(__file__).resolve().parents[3] / "data" / "ncaaf_source" / "data"`), rather than through `sources.py`'s existing `default_ncaaf_source_root()` helper, which is the env-var-aware (`SYNDICATE_NCAAF_SOURCE_ROOT`) mechanism every other NCAAF data path in this codebase already uses. Render mounts a persistent disk separately from the code checkout (confirmed in `render.yaml`), so the hardcoded pattern would very likely not resolve to the correct, persistent location once actually deployed there — meaning trial content and monitoring data could silently fail to work or fail to survive a redeploy in production, independent of anything about SmartSim's forecasting quality.

With the user's approval, this was fixed as a bounded, additive change:

| File | Change |
| --- | --- |
| `syndicate/features/ncaaf/cards.py` | `_prediction_rows()`, `_prediction_source_path()`, `_smartsim2_projection_index()` now resolve `data_root` via `default_ncaaf_source_root() / "data"` instead of a hardcoded path |
| `syndicate/features/ncaaf/smartsim2_trial_monitoring.py` | `MONITORING_LOG_PATH` now built from `default_ncaaf_source_root()` |
| `syndicate/features/ncaaf/smartsim2_performance_tracking.py` | `PERFORMANCE_LOG_PATH` now built from `default_ncaaf_source_root()` |
| `scripts/generate_smartsim2_ncaaf_projections.py`, `scripts/backfill_smartsim2_performance.py`, `scripts/fetch_cfbd_lines.py`, `scripts/expand_smartsim2_trial_cohort.py`, `scripts/validate_smartsim2_expanded_trial.py` | Same fix applied to every hardcoded `DATA_ROOT`/`COHORT_PATH`/`TRUTH_PATH`/`ENGINE_CSV_PATH`/`--out-dir` default |

**Verified, not just asserted**: with no environment variable set (the local dev case), every fixed constant resolves to the exact same path as before (confirmed by printing `MONITORING_LOG_PATH`/`PERFORMANCE_LOG_PATH` before and after — unchanged). With `SYNDICATE_NCAAF_SOURCE_ROOT` set to a Render-style path, the same constants correctly repoint there. The full scoped regression suite (91 tests) and a re-run of the expanded-trial validation script (access control, publication-gate parity, monitoring) both passed identically before and after the fix — this was a pure path-resolution correction, zero behavioral change locally.

**What this does not do**: it does not touch `render.yaml`, set any environment variable on the live Render service, or trigger a deploy — per the user's explicit choice of "fix the code now, don't touch Render." It also does not address whether SmartSim 2.0 projection *generation* (a ~6-8 minute CPU job per week, likely meant to run on a worker service, separate from the web service that serves pages) is wired into whatever cross-service artifact-publishing mechanism the rest of this app already uses for MLB/WNBA data — that is a separate, larger question this phase did not attempt to resolve, and is flagged as an open item below.

## Tasks 1-2/4: Monitoring, Token Usage, and Operational Metrics (Validation Exercise)

**Same disclosure as every prior trial report**: there is still no live, publicly-deployed instance of this app with real external user traffic. Everything below is a validation exercise — real HTTP requests through the actual Flask app and real code paths, run by this script, not organic clicks from real people. Real trial participation requires distributing tokens to actual people against an actually-deployed (and, per the fix above, correctly-wired) instance, which remains a step outside this session.

Exercised: `/ncaaf/cards` and `/ncaaf/picks`, across weeks 1/5/8/10, with one sample token from each of the 5 cohort tiers (internal, trusted_tester, power_user, extended_internal, opt_in_beta) — 40 requests total.

| Metric | Value |
| --- | --- |
| Active trial users (cohort size) | 38 tokens provisioned (10 original + 28 from Tier 4/5) |
| Real distinct human users observed | **0** — unchanged from every prior report; this remains the honest limitation |
| Page views generated (this exercise) | 40 requests → 40 new monitoring records |
| `/ncaaf/cards` avg. projection availability | 4.69% (varies by week — weeks with fewer SmartSim-covered games in the top-16 slice pull this down) |
| `/ncaaf/cards` avg. visibility rate | 4.69% |
| `/ncaaf/picks` avg. projection availability | 10.41% |
| `/ncaaf/picks` avg. visibility rate | 10.41% |
| Fallback rate (both routes) | **0.0%** |
| Rendering issues found | **None** |

**Token usage / unique users**: this project's monitoring log (`smartsim2_trial_monitoring.py`) records aggregate route-level stats per page view, not which specific cohort token generated it — a gap already disclosed in `smartsim_expanded_trial_plan.md`'s monitoring-coverage review and still unbuilt. The "38 active users" figure above is the provisioned cohort size, not a measurement of distinct real usage; there is currently no way to distinguish "one tester hit reload 40 times" from "40 different testers each hit it once" from the logs alone.

## Task 2 (Task 3 note): Which Projection Source Receives Attention

There is no per-source attention/click tracking built into this app — when trial content renders, all three sources (Enhanced Totals Engine, SmartSim 2.0, Consensus Projection) are shown together in the same panel/list, so "which source a user views" cannot currently be measured at anything finer than "did the trial panel render at all." This is a real, disclosed limitation, not a number this report can honestly produce. What can be said: the panel's own layout (Phase 3's design) presents all three with equal visual weight, so there is no structural bias toward one source over another in what's rendered — any future attention-tracking would need actual instrumentation (e.g., scroll depth, click events) that doesn't exist today.

## Task 3: Usage Pattern Exposure (Disagreement / Large-Mismatch / Conference Games)

Computed from the real, full-season backtest (`smartsim2_performance_tracking.py`, 752 games) restricted to the four weeks exercised in this validation (1, 5, 8, 10 — 209 games):

| Category | Share of exercised-week games |
| --- | --- |
| Side disagreement | 39.7% |
| Large mismatch | 40.2% |
| Total disagreement | 39.7% |
| Conference games | 69.4% |

This describes what a trial user *would* encounter across the weeks this exercise touched — a substantial minority-to-plurality of disagreement/mismatch games, consistent with every prior phase's finding that these are common, not rare, situations. It is not a measurement of what real users actually looked at (see Task 2 above), since no real users exist yet.

## Task 7: Re-Run Performance Monitoring on Newly Completed Games

Checked the historical truth snapshot (`data/ncaaf_source/historical_truth/games_2025.json.gz`) for any games beyond the 752 already captured in Phase 2: **none found**. The 2025 season's `seasonType` breakdown is 100% `"regular"` (888 total games, all weeks 1-16 including conference championship week), with zero postseason/bowl entries in this dataset. Phase 2's full-season backtest already covers every completed, joinable game available. Re-running `detect_drift()` against the unchanged 752-game log (a sanity check, not new data) reconfirms all three checks **not flagged** — performance, calibration, and policy drift all remain absent, exactly as Phase 2 found.

## Task 6/8: Explicit Answers

### Are trial users using SmartSim?

No real trial users exist yet to answer this about. The cohort has grown to 38 provisioned tokens (Tier 4/5 added in the prior phase), and — as of this phase — the mechanism is now actually deployable to the real Render environment (the path-resolution fix above), which it was not confirmed to be before. But no token has been distributed to an actual person and used outside this session's own validation scripts.

### Which projection source receives the most attention?

Cannot be measured — no per-source attention tracking exists (see Task 2). All three sources render with equal visual weight whenever the trial panel is shown.

### Are disagreement games generating interest?

Cannot be measured for the same reason — "interest" implies real user engagement signals (time on page, clicks, return visits) that this app does not currently instrument. What is known: disagreement/mismatch games are common (39.7-40.2% of games in the weeks checked), so real users, once they exist, will regularly encounter them.

### Are operational metrics still healthy?

Yes. Fallback rate 0.0% across both routes tested, zero rendering issues, publication-gate parity already reconfirmed in the prior phase, and the newly-fixed path resolution makes the whole mechanism deployable to Render for the first time without changing any locally-observed behavior (91/91 scoped tests still pass).

## Task 9: Rollout Sufficiency

**Not yet sufficient to justify expanding further or beginning production rollout planning.** The single fact that has been true in every report on this mechanism, across five prior phases, remains true here: zero real people have used this feature. Growing the token count (Phase before this one) and fixing the Render path-resolution gap (this phase) are both real, necessary steps toward that happening — but neither one *is* real usage. Beginning production rollout planning on the strength of a fully-synthetic validation history, no matter how clean, would skip the one thing every prior report has said is the actual blocker.

## Final Verdict

**Continue Trial.**

Not "Expand Trial" — the cohort was already expanded last phase and hasn't yet generated a single real usage data point to justify going further. Not "Begin Production Rollout Planning" — that would require real trial evidence this report still does not have. "Continue Trial" here specifically means: the mechanism is now Render-deployable (new this phase), the cohort is provisioned (38 tokens, prior phase), and the honest next step is distributing those tokens to real people against a real deployment and letting genuine usage finally accumulate — not another round of synthetic validation, which has now demonstrated the same clean result five times in a row.
