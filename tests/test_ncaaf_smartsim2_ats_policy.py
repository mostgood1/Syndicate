"""Regression coverage for the ATS Policy Implementation.

smartsim_betting_policy_report.md found that a disagreement-triggered ATS
rule (Engine's margin by default; SmartSim's margin when the two sources
pick opposite sides) beat every other candidate tested -- plain Engine-only,
plain SmartSim-only, the pre-Phase-4 mechanism, and Phase 4 itself -- in
every category on 752 real games. This module supersedes
tests/test_ncaaf_smartsim2_policy_revision.py (removed), which pinned down
Phase 4's now-replaced large-mismatch-magnitude mechanism; these tests pin
down the new one instead.

Three things this file exists to guarantee:
1. Agreement games use Engine's margin, unblended, regardless of magnitude.
2. Disagreement games use SmartSim's margin, unblended, regardless of magnitude.
3. Totals are completely unaffected -- ``blend_total()`` and its weights are
   untouched, and total behavior does not depend on the margin decision at all.
"""

from __future__ import annotations

import unittest

from syndicate.features.ncaaf.smartsim2_blend import LARGE_MISMATCH_MARGIN_THRESHOLD
from syndicate.features.ncaaf.smartsim2_blend import MARGIN_WEIGHT_ENGINE
from syndicate.features.ncaaf.smartsim2_blend import MARGIN_WEIGHT_SMARTSIM
from syndicate.features.ncaaf.smartsim2_blend import SMARTSIM_TOTAL_BIAS
from syndicate.features.ncaaf.smartsim2_blend import TOTAL_WEIGHT_ENGINE
from syndicate.features.ncaaf.smartsim2_blend import TOTAL_WEIGHT_SMARTSIM
from syndicate.features.ncaaf.smartsim2_blend import blend_total
from syndicate.features.ncaaf.smartsim2_blend import compute_blend


class AgreementGamesUseEngineMarginTests(unittest.TestCase):
    """Task 6: regression coverage for agreement games."""

    def test_both_positive_uses_engine_margin(self) -> None:
        result = compute_blend(engine_margin=4.0, smartsim_margin=6.0, engine_total=50.0, smartsim_total=60.0)
        self.assertFalse(result.smartsim_margin_used)
        self.assertEqual(result.margin, 4.0)

    def test_both_negative_uses_engine_margin(self) -> None:
        result = compute_blend(engine_margin=-4.0, smartsim_margin=-6.0, engine_total=50.0, smartsim_total=60.0)
        self.assertFalse(result.smartsim_margin_used)
        self.assertEqual(result.margin, -4.0)

    def test_agreement_at_large_magnitude_still_uses_engine_margin(self) -> None:
        # A magnitude well past the old large-mismatch threshold must not
        # change the outcome -- only side disagreement does, under this policy.
        result = compute_blend(
            engine_margin=LARGE_MISMATCH_MARGIN_THRESHOLD + 20.0,
            smartsim_margin=2.0,
            engine_total=50.0,
            smartsim_total=60.0,
        )
        self.assertFalse(result.smartsim_margin_used)
        self.assertEqual(result.margin, LARGE_MISMATCH_MARGIN_THRESHOLD + 20.0)

    def test_smartsim_margin_of_zero_counts_as_negative_side_no_disagreement(self) -> None:
        # sign is computed as `> 0`, so a zero SmartSim margin is treated as
        # the "away" side, same as any negative margin -- documented, not hidden.
        result = compute_blend(engine_margin=-3.0, smartsim_margin=0.0, engine_total=50.0, smartsim_total=60.0)
        self.assertFalse(result.smartsim_margin_used)
        self.assertEqual(result.margin, -3.0)


class DisagreementGamesUseSmartsimMarginTests(unittest.TestCase):
    """Task 6: regression coverage for disagreement games."""

    def test_engine_positive_smartsim_negative_uses_smartsim_margin(self) -> None:
        result = compute_blend(engine_margin=7.0, smartsim_margin=-3.0, engine_total=50.0, smartsim_total=60.0)
        self.assertTrue(result.smartsim_margin_used)
        self.assertEqual(result.margin, -3.0)

    def test_engine_negative_smartsim_positive_uses_smartsim_margin(self) -> None:
        result = compute_blend(engine_margin=-7.0, smartsim_margin=3.0, engine_total=50.0, smartsim_total=60.0)
        self.assertTrue(result.smartsim_margin_used)
        self.assertEqual(result.margin, 3.0)

    def test_disagreement_at_small_magnitude_still_uses_smartsim_margin(self) -> None:
        # A small, non-"mismatch" magnitude must still trigger the override --
        # this is the core of "remove ATS dependence on large-mismatch logic."
        result = compute_blend(engine_margin=0.5, smartsim_margin=-0.5, engine_total=50.0, smartsim_total=60.0)
        self.assertTrue(result.smartsim_margin_used)
        self.assertEqual(result.margin, -0.5)

    def test_disagreement_at_large_magnitude_uses_smartsim_margin(self) -> None:
        result = compute_blend(
            engine_margin=LARGE_MISMATCH_MARGIN_THRESHOLD + 10.0,
            smartsim_margin=-1.0,
            engine_total=50.0,
            smartsim_total=60.0,
        )
        self.assertTrue(result.smartsim_margin_used)
        self.assertEqual(result.margin, -1.0)


class TotalsUnchangedTests(unittest.TestCase):
    """Task 2/6: regression coverage that totals are completely unaffected."""

    def test_total_weights_and_bias_unchanged(self) -> None:
        self.assertEqual(TOTAL_WEIGHT_ENGINE, 0.114)
        self.assertEqual(TOTAL_WEIGHT_SMARTSIM, 0.886)
        self.assertEqual(SMARTSIM_TOTAL_BIAS, 6.11)

    def test_margin_weights_retained_unmodified_even_though_unused_by_compute_blend(self) -> None:
        # Do not modify: Blend weights. These are retained at their original
        # values -- compute_blend() simply no longer reads them.
        self.assertEqual(MARGIN_WEIGHT_ENGINE, 0.395)
        self.assertEqual(MARGIN_WEIGHT_SMARTSIM, 0.605)

    def test_total_always_blended_regardless_of_margin_agreement_or_disagreement(self) -> None:
        for engine_margin, smartsim_margin in [(1.0, 1.0), (25.0, 0.5), (-30.0, 2.0), (5.0, -5.0)]:
            with self.subTest(engine_margin=engine_margin, smartsim_margin=smartsim_margin):
                result = compute_blend(
                    engine_margin=engine_margin, smartsim_margin=smartsim_margin,
                    engine_total=50.0, smartsim_total=60.0,
                )
                self.assertTrue(result.total_blended)
                self.assertAlmostEqual(result.total, blend_total(50.0, 60.0))

    def test_total_formula_unchanged_from_pre_implementation(self) -> None:
        expected = TOTAL_WEIGHT_ENGINE * 50.0 + TOTAL_WEIGHT_SMARTSIM * (60.0 - SMARTSIM_TOTAL_BIAS)
        self.assertAlmostEqual(blend_total(50.0, 60.0), expected)

    def test_total_does_not_depend_on_which_margin_source_was_used(self) -> None:
        agreement = compute_blend(engine_margin=4.0, smartsim_margin=6.0, engine_total=50.0, smartsim_total=60.0)
        disagreement = compute_blend(engine_margin=4.0, smartsim_margin=-6.0, engine_total=50.0, smartsim_total=60.0)
        self.assertEqual(agreement.total, disagreement.total)


if __name__ == "__main__":
    unittest.main()
