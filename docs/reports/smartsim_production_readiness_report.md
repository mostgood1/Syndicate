# SmartSim Production Readiness Review

- Date: 2026-07-16
- Scope: NCAAF, pure audit — **no code was modified.** SmartSim 2.0 simulation logic, both calibration profiles, the ATS policy, and the total-point policy are all confirmed unchanged from `smartsim_ats_policy_implementation_report.md` (verified below, not just asserted).
- References: `smartsim_ats_policy_implementation_report.md`, `smartsim_betting_performance_report.md`, `smartsim_monitoring_phase2_report.md`.

## Task 1: Inventory of Every SmartSim Decision Path Affecting Picks

| Decision path | Where | What it does |
| --- | --- | --- |
| `compute_blend()` | `smartsim2_blend.py` | The only place margin (ATS) and total (Consensus) values are decided: Engine's margin by default, SmartSim's on side disagreement; total always blended (unchanged). |
| `_attach_smartsim2_shadow_fields()` → `compute_blend()` | `cards.py` | Called once per game, for every route below, whenever a SmartSim 2.0 projection exists for that game. |
| `/ncaaf/cards` | `cards.py::build_smartsim_cards_page_context()` | Builds each game's scoreboard via `_runtime_scoreboard_projection()`, which calls the above. |
| `/ncaaf/game/<id>` | `game_detail.py::build_game_detail_page_context()` | Reuses `build_smartsim_cards_page_context()` — same decision path, filtered to one game. |
| `/ncaaf/picks` | `picks.py::_runtime_pick_cards()` | Calls `cards._runtime_scoreboard_projection()` directly — same decision path. |
| `/ncaaf/live-lens` | `live_lens.py` | **Not a decision path.** Verified: only imports `LEGACY_ENGINE_SOURCE_LABEL` for display text; never calls `compute_blend()` or attaches shadow fields. |
| Visibility gating | `cards.py`: `_public_trial_master_enabled()`, `_public_trial_visible_for_request()`, `_blend_trial_diagnostics_enabled()` | Controls whether the three-way comparison is *rendered* into a page. Does not affect whether `compute_blend()` runs or what it returns. |
| Monitoring | `smartsim2_trial_monitoring.py::record_trial_page_view()` (live, called from all three routes above), `smartsim2_performance_tracking.py` (offline analysis, not in the request path) | Observes, never decides. |
| Offline generation | `scripts/generate_smartsim2_ncaaf_projections.py` | Produces the artifact `_smartsim2_projection_index()` reads. Not in the live request path. |

**The most important architectural fact this inventory surfaces**: on every route above, the primary, universally-displayed `spread_label`/`source_label` (what every user, trial participant or not, actually sees as "the pick") is computed from the Enhanced Totals Engine's own row data **before** `_attach_smartsim2_shadow_fields()` ever runs — confirmed by reading the code: `spread_label` is set at `cards.py:371` from the Engine's raw margin, and `_attach_smartsim2_shadow_fields()` (called afterward) only *adds* new keys to the scoreboard dict, never overwrites `spread_label` or `source_label`. **SmartSim 2.0 and Consensus Projection do not influence any pick a real user is currently shown, trial or otherwise — full stop.** They exist purely as an additive, three-way comparison panel, itself gated behind the trial-visibility mechanism, on top of an unchanged primary pick.

## Task 2: Verify ATS Policy Implementation

Re-read `compute_blend()` directly (not from memory) and re-ran the dedicated test suite:

```python
side_disagreement = (engine_margin > 0) != (smartsim_margin > 0)
margin = smartsim_margin if side_disagreement else engine_margin
```

Matches `smartsim_ats_policy_implementation_report.md` exactly. `tests/test_ncaaf_smartsim2_ats_policy.py` (13 tests: agreement at every magnitude uses Engine; disagreement at every magnitude, including small ones far below the old large-mismatch threshold, uses SmartSim) passes, along with the full scoped suite (**111 passed, 4 subtests passed**, zero failures).

## Task 3: Verify Total-Point Consensus Policy

`blend_total()` is byte-identical to every prior phase: `0.114 × Engine + 0.886 × (SmartSim − 6.11)`, unconditional, no exception. Re-ran the full 752-game backtest: Consensus totals win%/ROI (57.10% / +9.02%) match `smartsim_betting_performance_report.md` to the decimal — confirming no drift between what the report claims and what the shipped code actually produces.

## Task 4: Verify Monitoring Coverage

| Capability | Status |
| --- | --- |
| Real-game backtested betting performance (ATS + totals, MAE/RMSE/correlation, win%/ROI/units) | ✅ Operational, 752-game log, regenerated under the current ATS policy |
| Rolling-window / season-to-date trend tracking | ✅ Operational (`rolling_windows()`, `summarize_season_to_date()`) |
| Automated drift detection | ✅ Operational, re-run for this review: **performance, calibration, and policy drift all not flagged** |
| Page-view telemetry (availability/visibility/fallback rate) | ✅ Operational, mechanism validated (never exercised by a real user — see Task 7) |
| **A monitoring gap found during this review**: `detect_drift()`'s `policy_drift` check still measures the *old* large-mismatch-and-side-disagreement subset's straight-up *accuracy* gap — a holdover from the Phase 4 policy this system no longer runs. It is harmless (still a valid, informative number) but it no longer monitors the thing that actually drives picks today. **There is currently no drift check on the new ATS policy's own subject — side-disagreement ATS ROI over time.** | ⚠️ Gap, not a defect |

## Task 5: Verify Rollback Capability

Two different things can be "rolled back," and they have different mechanisms:

1. **Trial-visibility exposure** (whether the three-way comparison panel renders at all): instant, config-only — unset `SMARTSIM_PUBLIC_TRIAL_ENABLED` and every trial-gated request reverts to showing nothing extra, confirmed still working (`_public_trial_master_enabled()` defaults to `False` with no env var set, verified directly this review).
2. **The ATS/total policy itself** (what `compute_blend()` computes): **no runtime kill switch exists.** There is no environment variable that reverts `compute_blend()` to a prior formula — the only rollback path is a code-level revert (e.g., `git revert`) plus a redeploy. This is low-risk *today* only because of the Task 1 finding: Consensus doesn't drive any real user's pick yet. It would be a real gap the day Consensus is ever promoted to be the primary displayed projection, and is worth building before that happens, not after.
3. **The largest rollback fact of all**: `git status` shows **93 uncommitted changes** and `git log` shows no NCAAF/SmartSim2-related commits in this repository's history at all. Every file this entire project has built or modified — the truth layer, the calibration profile, the blend module, the trial infrastructure, every test, every report — exists only in this local working tree. It has never been pushed to `origin/main`, and `render.yaml` (checked directly, zero matches) has no SmartSim-related environment variables configured at all. **"Rollback" of anything described in this whole project's reports is currently a no-op, because none of it has ever been deployed.**

## Task 6: Quantified Expected Betting Impact (Current Policies, 752 Real Games)

| Bet type | Source | Win % | ROI % | Units (752 games) |
| --- | --- | --- | --- | --- |
| ATS | Engine alone | 53.14% | +1.44% | +10.82 |
| ATS | Consensus (current policy) | **55.94%** | **+6.80%** | **+50.91** |
| Totals | Consensus (unchanged policy) | **57.10%** | **+9.02%** | **+67.27** |

If both bet types were played on every game at 1 unit each (1,504 total bets), the combined net is **+118.18 units, ~7.86% blended ROI** — the clearest single number this review can offer for "what would betting on Consensus's current picks have been worth" on the real, already-completed 2025 season. This is a backtested, not a forward-looking, guarantee — the standard caveat applies (see Task 7).

By category (side disagreement, the ATS policy's specific trigger condition): 56.44% win / +7.75% ROI — the policy's single strongest, most-targeted segment, exactly as designed.

## Task 7: Remaining Blockers

1. **Not deployed, not committed.** The largest blocker by far (Task 5). Every number in this report describes code sitting in an uncommitted local working tree, not a running system.
2. **Zero real user usage, ever.** Every trial-related report in this entire project, without exception, has disclosed this. It remains true. The trial mechanism is provisioned (38 tokens) and mechanically validated, but no real person has used it.
3. **Consensus does not drive any real pick today** (Task 1) — even once deployed, this review's own numbers describe what *would* happen if Consensus became the primary pick, not what is currently happening to any user.
4. **No runtime kill switch for the blend formula itself** (Task 5) — only trial-panel visibility is instantly reversible; the policy computation is not.
5. **Walk-forward-ratings limitation**, disclosed since the original production-integration plan and unchanged: SmartSim 2.0's projections use season-aggregate CFBD PPA ratings, not ratings as they stood before each individual game.
6. **No real per-bet price data.** Every ROI figure in this and the prior betting report assumes flat -110 on both sides; real bet-slip prices were never collected.
7. **The `policy_drift` monitoring gap** (Task 4) — no drift check currently targets the metric that actually matters for the live ATS policy (side-disagreement ATS ROI stability).
8. Totals blend weights (0.114/0.886/6.11) were calibrated on an original 103-game sample and have not been formally re-validated against the now-752-game sample — performance remains strong (+9.02% ROI, no drift detected), so this is a lower-priority watch item, not an active concern.

## Task 9: Explicit Answers

### Is SmartSim ready to influence picks?

**Not yet, and the reason is more fundamental than any statistic in this report.** The betting numbers are genuinely good (Consensus ATS +6.80% ROI, Totals +9.02% ROI, both consistent, both drift-checked). But "ready to influence picks" requires two things neither of which is true today: the code would need to be committed and deployed (it is not — Task 5), and Consensus would need to actually drive the primary displayed pick rather than exist as an opt-in comparison panel behind a trial gate (it does not — Task 1). SmartSim is ready to be *trusted as a signal*, evidenced across six phases of increasingly rigorous real-data validation; it is not yet ready to *replace or drive* what a real user is shown.

### What risks remain?

Listed in full in Task 7. The two structural ones — no deployment and no real usage — are not new; every report in this project has said so. The two new ones this review surfaces are architectural: Consensus's strictly-additive, never-primary role (a safety property today, but means all this validation hasn't touched a real pick yet) and the absence of a runtime kill switch for the blend formula specifically (fine while Consensus is non-primary, a real gap the moment it isn't).

### What monitoring is still required?

Everything already built, kept running continuously: `summarize_performance()`, `rolling_windows()`, `summarize_season_to_date()`, and `detect_drift()` from `smartsim2_performance_tracking.py`; `summarize_betting_performance()` from `smartsim2_betting_performance.py` for ATS/totals ROI specifically; page-view telemetry once real usage exists. New, recommended by this review: a drift check on side-disagreement ATS ROI specifically (the actual mechanism the current policy runs on), replacing or supplementing the now-stale large-mismatch-accuracy check.

### What conditions would trigger rollback?

Same evidence-based triggers established in `smartsim_expanded_trial_plan.md` (any of the three `detect_drift()` checks firing, availability regression, publication-gate mismatch, rendering defects) — none currently firing — plus one new one this review adds: if the recommended side-disagreement ATS ROI drift check (once built) shows the policy's real-world ROI diverging materially from the backtested +6.80%/+7.75% figures.

## Final Verdict

**Additional Validation Required.**

Not because the forecasting or betting evidence is weak — it is the strongest and most consistent evidence this entire project has produced, across a full season, multiple independent drift checks, and now a real betting-ROI framework, not just accuracy statistics. The verdict is "Additional Validation" because production readiness is a claim about a deployed, real system influencing real picks, and today there is no deployed system at all: nothing here has been committed to git, nothing is wired into Render, and even once it is, Consensus is architected to remain an additive comparison panel rather than the primary pick. The next validation this project needs is not another backtest — it is committing this work, deploying it, and observing what happens when Consensus is actually shown to and used by a real person for the first time.
