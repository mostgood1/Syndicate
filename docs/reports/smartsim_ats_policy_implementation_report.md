# SmartSim ATS Policy Implementation Report

- Date: 2026-07-16
- Scope: NCAAF, one surgical behavioral change to margin/ATS decision logic. **SmartSim 2.0 simulation logic, both calibration profiles, total-point policies, and Consensus total calculations were all left untouched.**
- References: `smartsim_betting_policy_report.md`, `smartsim_betting_performance_report.md`.

## Task 1: Locating the Current ATS Decision Logic

`syndicate/features/ncaaf/smartsim2_blend.py`, function `compute_blend()`, was the single place margin (the number that drives every ATS pick) was decided. Before this change it ran a two-branch policy: a fixed-weight blend (`0.395 × Engine + 0.605 × SmartSim`) below a large-mismatch threshold, and SmartSim's raw margin above it (the Phase 4 revision). `smartsim_betting_policy_report.md` found this mechanism's real ATS effect was either negative (vs. the pre-Phase-4 version) or, on the real 752-game dataset, **completely indistinguishable from having no override at all** — and identified a disagreement-triggered rule that beat every alternative in every category tested.

## Policy Implemented

```
ATS margin:
    Engine's margin, by default.
    If sign(Engine's margin) != sign(SmartSim's margin) -> use SmartSim's margin instead.

Totals: unchanged. blend_total() runs unconditionally, exactly as before.
```

## Task 2/3: What Was Preserved

- **Total prediction behavior**: `blend_total()`, `TOTAL_WEIGHT_ENGINE` (0.114), `TOTAL_WEIGHT_SMARTSIM` (0.886), and `SMARTSIM_TOTAL_BIAS` (6.11) are byte-identical to before this change — confirmed both by an empty diff on that function and by re-running the full 752-game backtest: totals win%/ROI for all three sources (Engine 52.28%/-0.19%, SmartSim 51.47%/-1.73%, Consensus 57.10%/+9.02%) match `smartsim_betting_performance_report.md` to the decimal.
- **SmartSim 2.0 simulation behavior**: nothing under `syndicate/features/football/` was touched — confirmed by an empty `git diff --stat` against `HEAD` for that entire directory. This implementation only changes how two already-produced numbers (Engine's margin, SmartSim's margin) are chosen between; it does not touch how either number is produced.
- **Blend weights**: `MARGIN_WEIGHT_ENGINE` (0.395), `MARGIN_WEIGHT_SMARTSIM` (0.605), and `LARGE_MISMATCH_MARGIN_THRESHOLD` (10.0) are retained at their exact original values — `compute_blend()` simply no longer reads them for its margin decision. They remain because other code still depends on them: `blend_margin()` (kept for historical/counterfactual reference, e.g. the comparisons in `smartsim_betting_policy_report.md`) and `smartsim2_performance_tracking.py`'s independent `large_mismatch` reporting category, which is unaffected by this change and continues to use `LARGE_MISMATCH_MARGIN_THRESHOLD` exactly as before.

## Task 4/5: What Changed

`compute_blend()`'s margin logic:

```python
# Before:
situational_margin = reference_margin_for_situation if reference_margin_for_situation is not None else engine_margin
magnitude = abs(situational_margin)
margin_blend_applies = magnitude < LARGE_MISMATCH_MARGIN_THRESHOLD
margin = blend_margin(engine_margin, smartsim_margin) if margin_blend_applies else smartsim_margin

# After:
side_disagreement = (engine_margin > 0) != (smartsim_margin > 0)
margin = smartsim_margin if side_disagreement else engine_margin
```

The `reference_margin_for_situation` parameter (the market-margin input that drove the large-mismatch gate) was removed from `compute_blend()`'s signature entirely — the new policy needs only `engine_margin` and `smartsim_margin` to decide. This is a literal implementation of Task 5 ("remove ATS dependence on large-mismatch logic"): magnitude, market reference, and the fixed-weight blend all no longer factor into the margin decision at all.

`BlendResult.margin_blended` was renamed to `BlendResult.smartsim_margin_used` — under the old policy this field meant "was the fixed-weight blend applied" (True) vs. "was a single raw source used" (False); under the new policy margin is *never* a weighted blend, so that old meaning would be permanently `False` and useless. The new field accurately reports which raw source backs the returned margin, which is the meaningful question under this policy.

### Files changed

| File | Change |
| --- | --- |
| `syndicate/features/ncaaf/smartsim2_blend.py` | `compute_blend()` rewritten (disagreement-triggered margin); `reference_margin_for_situation` parameter removed; `BlendResult.margin_blended` → `smartsim_margin_used`; module/function docstrings updated. `blend_margin()`, `blend_total()`, and every weight/threshold constant retained unmodified. |
| `syndicate/features/ncaaf/cards.py` | `_attach_smartsim2_shadow_fields()`'s now-unused `market_home_margin` parameter removed (it was never actually passed a real value by any caller); its `compute_blend()` call site updated to match the new signature; `result.margin_blended` → `result.smartsim_margin_used` at both read sites (the `blend_margin_applied` scoreboard key and the `projection_sources.consensus_projection.margin_blended` diagnostic key — both key *names* kept stable for minimal external footprint, only their source updated). |
| `syndicate/features/ncaaf/smartsim2_performance_tracking.py` | `build_game_performance_record()`'s `compute_blend()` call updated (no longer passes `reference_margin_for_situation`); `GamePerformanceRecord.consensus_margin_blended` → `consensus_used_smartsim_margin`; the independent `large_mismatch`/`situational_margin` reporting logic is **unchanged** (still computed directly from `market_margin`/`engine_margin`, exactly as before — it no longer feeds the blend, but it never needed to change itself). |
| `tests/test_ncaaf_smartsim2_shadow.py`, `tests/test_ncaaf_smartsim2_performance_tracking.py`, `tests/test_ncaaf_smartsim2_betting_performance.py` | Updated assertions/fixtures to match the new policy and renamed fields (see Task 6). |
| `tests/test_ncaaf_smartsim2_policy_revision.py` | **Removed.** This file existed solely to pin down Phase 4's now-replaced large-mismatch mechanism; keeping it would mean asserting behavior that no longer exists. |
| `tests/test_ncaaf_smartsim2_ats_policy.py` | **New.** The dedicated regression file for this policy (see Task 6). |
| `data/ncaaf_source/data/smartsim2_performance_log.jsonl` | Regenerated (752 games, same source data, same join methodology) so recorded `consensus_margin`/`consensus_used_smartsim_margin` values reflect the new policy going forward. |

## Task 6: Regression Tests

`tests/test_ncaaf_smartsim2_ats_policy.py` (13 tests, all passing):

| Group | Covers |
| --- | --- |
| `AgreementGamesUseEngineMarginTests` | Both-positive and both-negative agreement use Engine's margin; agreement at a magnitude far past the old large-mismatch threshold still uses Engine's margin (proving magnitude no longer matters); the `> 0` sign convention's zero-margin edge case is documented by test, not left implicit. |
| `DisagreementGamesUseSmartsimMarginTests` | Both disagreement directions use SmartSim's margin; disagreement at a *small* magnitude still triggers the override (the core of "remove large-mismatch dependence" — the old policy would never have overridden here); disagreement at a large magnitude also still works. |
| `TotalsUnchangedTests` | Weight/bias constants (both margin and total) are unchanged from their original values; total is blended identically regardless of margin agreement or disagreement; the total formula matches a hand-computed value; total does not depend on which margin source was used. |

Plus updates to existing coverage: `tests/test_ncaaf_smartsim2_shadow.py` (14 tests) now asserts the new agreement/disagreement margin behavior instead of magnitude-threshold behavior; `tests/test_ncaaf_smartsim2_performance_tracking.py` (30 tests) now asserts that `large_mismatch` is a pure reporting category independent of the consensus margin decision (explicitly testing the case that most clearly demonstrates the change: a large-mismatch game *with agreement* now uses Engine's margin, whereas the old policy would have used SmartSim's regardless of agreement).

**Full scoped suite**: 111 passed, 4 subtests passed (`test_ncaaf_smartsim2_shadow.py`, `test_ncaaf_public_trial.py`, `test_ncaaf_smartsim2_trial_monitoring.py`, `test_ncaaf_smartsim2_ats_policy.py`, `test_ncaaf_smartsim2_performance_tracking.py`, `test_ncaaf_smartsim2_betting_performance.py`, `test_ncaaf_cards_local.py`, `test_ncaaf_picks_local.py`, `test_ncaaf_live_lens_local.py`). Zero failures.

## Verification Against the Real 752-Game Dataset

The performance log was regenerated under the new policy and re-graded:

| | ATS win% / ROI (before → after this implementation) | Totals win% / ROI (unchanged, verification) |
| --- | --- | --- |
| Engine | 53.14% / +1.44% (unaffected — Engine's own picks never changed) | 52.28% / -0.19% |
| SmartSim | 51.54% / -1.61% (unaffected — SmartSim's own picks never changed) | 51.47% / -1.73% |
| **Consensus** | 50.73% / -3.14% → **55.94% / +6.80%** | 57.10% / +9.02% (byte-identical to the prior report) |

Consensus's ATS record moved from the *worst* of the three sources to the *best*, by a wide margin — exactly matching the disagreement-triggered candidate's projected performance in `smartsim_betting_policy_report.md` (which was computed as a counterfactual from the same data before this implementation existed). `consensus_used_smartsim_margin` is `True` for exactly 326 games — precisely the count of `side_disagreement=True` games, confirming the override fires exactly when and only when designed to.

## Task 8: Explicit Answers

### Which files changed?

Three production files (`smartsim2_blend.py`, `cards.py`, `smartsim2_performance_tracking.py`), one regenerated data artifact (the performance log), three updated test files, one new test file, and one removed test file (superseded, not merely stale). Full list in the Task 4/5 table above.

### Were totals touched?

No. `blend_total()`'s code is byte-identical, its weight/bias constants are unchanged, and a full re-grade of all 752 real games against the closing lines produced win%/ROI figures matching `smartsim_betting_performance_report.md` exactly. The only totals-adjacent change is that `consensus_margin_blended` (a field name, not a value or behavior) was renamed to `consensus_used_smartsim_margin` — the total fields (`consensus_total`, `total_blended`) were not touched.

### Was SmartSim touched?

No. `git diff --stat` against `HEAD` for `syndicate/features/football/` (SmartSim 2.0's simulation code and both calibration profiles) is empty. This implementation only changes which of SmartSim's and the Engine's *already-produced* margin numbers is selected for the ATS pick — it does not change how either number is computed.

### Was ATS behavior changed only as approved?

Yes. The approved policy was "Engine by default; SmartSim's side when the two disagree" — that is the entirety of the new `compute_blend()` margin logic, with nothing else added. The large-mismatch magnitude check and the fixed-weight blend formula were removed from the decision path exactly as directed by Task 5, and verified removed by test (agreement at large magnitude still uses Engine; disagreement at small magnitude still uses SmartSim — the opposite of what the old policy would have done in both cases).

## Final Verdict

**ATS Policy Implemented.**

The disagreement-triggered ATS override is live in `compute_blend()`, totals are verified untouched (both by code diff and by re-grading all 752 real games), SmartSim 2.0 and both calibration profiles are verified untouched, and the full scoped regression suite (111 tests) passes with the new, dedicated policy test file in place. Re-grading the real dataset under the new code confirms the exact result the reassessment predicted: Consensus ATS moves from the worst-performing source (-3.14% ROI) to the best (+6.80% ROI), with totals unchanged at +9.02% ROI.
