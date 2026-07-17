# SmartSim Production Integration Phase 4: Policy Revision Implementation Report

- Date: 2026-07-16
- Scope: NCAAF, one surgical behavioral change. **SmartSim 2.0 simulation logic, both calibration profiles, the blend weights, and the total-point blend policy were all left untouched.**
- References: `smartsim_decision_policy_report.md`, `smartsim_ensemble_evaluation_report.md`.

## Task 1-5: The Change

**Located**: `syndicate/features/ncaaf/smartsim2_blend.py`, function `compute_blend()`, one line:

```python
# Before:
margin = blend_margin(engine_margin, smartsim_margin) if margin_blend_applies else engine_margin
# After:
margin = blend_margin(engine_margin, smartsim_margin) if margin_blend_applies else smartsim_margin
```

That is the entire behavioral diff. Everything else in the function — the situational-margin resolution (market margin preferred, engine margin as fallback), the `< LARGE_MISMATCH_MARGIN_THRESHOLD` gate and its 10.0 value, the `blend_margin()`/`blend_total()` helper functions, `MARGIN_WEIGHT_ENGINE`/`MARGIN_WEIGHT_SMARTSIM`, `TOTAL_WEIGHT_ENGINE`/`TOTAL_WEIGHT_SMARTSIM`/`SMARTSIM_TOTAL_BIAS`, and the `BlendResult` dataclass shape — is byte-identical to before this change.

- **Ordinary disagreements preserved**: the `margin_blend_applies` branch (fixed-weight blend) is untouched; verified by test.
- **Total-point policy preserved**: `blend_total()` was not touched at all, and is called identically regardless of the margin path taken; verified by test.
- **Only the large-mismatch margin branch changed**: `engine_margin` → `smartsim_margin` in the `else` branch, exactly as approved.

## Task 6: Documentation Added

Both the module docstring and the `compute_blend()` docstring were updated in place to explain the revision: what changed, why (citing the 23.5%/76.5% finding), what did *not* change, and that `BlendResult.margin_blended`'s meaning is preserved (True = blend used, False = a single raw source used unblended) even though which raw source backs the `False` case flipped.

## Task 7: Regression Tests Added

New file `tests/test_ncaaf_smartsim2_policy_revision.py` (13 tests, all passing):

| Group | Covers |
| --- | --- |
| `ConstantsUnchangedTests` | Margin weights, total weights + bias, and both thresholds are exactly their pre-revision values — a permanent guard against this change silently growing scope. |
| `LargeMismatchMarginTests` | Positive and negative large mismatches now resolve to SmartSim's margin; the boundary (exactly at the threshold, and just under it) behaves per the pre-existing strict-inequality rule; the market-reference gate still governs *whether* the exception fires (only *which* system it returns changed). |
| `OrdinaryDisagreementUnchangedTests` | Below-threshold disagreement and below-threshold agreement both still use the original fixed-weight blend, unchanged. |
| `TotalsUnchangedTests` | Total is blended identically regardless of how large the margin mismatch is, and `blend_total()`'s output matches a hand-computed value using the documented, unchanged weights. |

Also updated one pre-existing test (`test_blend_skips_margin_above_mismatch_threshold` in `tests/test_ncaaf_smartsim2_shadow.py`) that asserted the old Engine-first behavior — renamed and corrected to assert the new, approved SmartSim-first outcome, with a comment explaining why.

**Full suite**: 126 passed (113 before this phase + 13 new), same 7 pre-existing/unrelated failures as every prior phase (traced to files entirely outside this diff — `test_archives.py`, `test_ncaaf_refresh_runner.py`, `test_ops.py`, and the one pre-existing stochastic flake in `test_smartsim2_calibrated_drive_simulator.py`). Zero new failures. `git diff --stat` against `HEAD` for everything under `syndicate/features/football/` (the simulator and both calibration profiles) is empty — confirmed untouched.

## Task 9: Explicit Answers

### Which files changed?

Two: `syndicate/features/ncaaf/smartsim2_blend.py` (the one-line behavioral change plus documentation) and `tests/test_ncaaf_smartsim2_shadow.py` (one pre-existing test corrected to match the new, approved behavior). Plus one new file: `tests/test_ncaaf_smartsim2_policy_revision.py`.

### Were blend weights altered?

No. `MARGIN_WEIGHT_ENGINE` (0.395), `MARGIN_WEIGHT_SMARTSIM` (0.605), `TOTAL_WEIGHT_ENGINE` (0.114), `TOTAL_WEIGHT_SMARTSIM` (0.886), and `SMARTSIM_TOTAL_BIAS` (6.11) are all unchanged — confirmed by a dedicated, permanent regression test (`ConstantsUnchangedTests`), not just asserted in prose.

### Were totals altered?

No. `blend_total()` was not edited, is called unconditionally regardless of which margin branch fires, and its output was verified byte-identical to a hand-computed value using the documented weights and bias correction.

### Was the revision implemented exactly as approved?

Yes. The approved change was "reverse the large-mismatch margin exception from Engine-first to SmartSim-first" — nothing more. The implementation touches exactly that one branch of one function; the threshold, the reference-margin resolution logic, the weights, and the total policy are all identical to before.

## Final Verdict

**Policy Revision Complete.**

The only behavioral change in this codebase is the large-mismatch margin exception now returning SmartSim's margin instead of the Engine's — exactly the scope approved in `smartsim_decision_policy_report.md`, backed by 13 new regression tests plus one corrected pre-existing test, with the full test suite green apart from the same pre-existing, unrelated failures present before this phase began.
