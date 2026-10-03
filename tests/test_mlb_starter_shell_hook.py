"""The SHELLED hook in `_select_pitcher_v2` (lane mlb-starter-length).

Same Phase 5 pair as `test_mlb_starter_leash_tunable.py`, whose toy-roster
harness this reuses: (1) absent knobs are byte-identical, (2) the engine
actually reads them, and in the right direction. A third check proves this pair
discriminates: the same harness at production's start/weight must move the
early-exit share, or the "no change" half could be passing on a dead seam.
"""
from __future__ import annotations

import unittest

from tests.test_mlb_starter_leash_tunable import starter_outs

PROD_LIKE = {"starter_hook_add_pitches": -13, "starter_hook_stamina_excess_weight": 0.75,
             "starter_quality_hook_weight": 1.0}


def _with(**kw):
    return {**PROD_LIKE, **kw}


def _share_le9(outs):
    return sum(1 for o in outs if o <= 9) / len(outs)


class NoBehaviourChangeTests(unittest.TestCase):
    def test_absent_knobs_are_byte_identical_to_explicit_defaults(self) -> None:
        self.assertEqual(starter_outs(PROD_LIKE),
                         starter_outs(_with(starter_shell_runs_start=99, starter_shell_runs_weight=0.0)))

    def test_a_threshold_nobody_reaches_is_a_no_op_whatever_the_weight(self) -> None:
        self.assertEqual(starter_outs(PROD_LIKE),
                         starter_outs(_with(starter_shell_runs_start=99, starter_shell_runs_weight=5.0)))


class ReachabilityTests(unittest.TestCase):
    def test_the_engine_reads_the_shell_knobs(self) -> None:
        self.assertNotEqual(starter_outs(PROD_LIKE),
                            starter_outs(_with(starter_shell_runs_start=2, starter_shell_runs_weight=2.0)))

    def test_a_shelled_starter_leaves_earlier(self) -> None:
        base = starter_outs(PROD_LIKE, n=120)
        shelled = starter_outs(_with(starter_shell_runs_start=2, starter_shell_runs_weight=2.0), n=120)
        self.assertLess(sum(shelled) / len(shelled), sum(base) / len(base))
        self.assertGreater(_share_le9(shelled), _share_le9(base))

    def test_the_threshold_alone_breaks_the_leash(self) -> None:
        # weight 0: no logit push, but reaching the threshold must still let the
        # pitch-count hook act inside the five-inning leash.
        self.assertNotEqual(starter_outs(PROD_LIKE),
                            starter_outs(_with(starter_shell_runs_start=2, starter_shell_runs_weight=0.0)))

    def test_junk_values_fall_back_to_the_no_op(self) -> None:
        self.assertEqual(starter_outs(PROD_LIKE),
                         starter_outs(_with(starter_shell_runs_start="x", starter_shell_runs_weight=None)))


if __name__ == "__main__":
    unittest.main()
