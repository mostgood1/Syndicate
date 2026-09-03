"""The two defects that made `backtest_soccer_anchor_vs_outcomes` lie, locked in.

Both produced a PLAUSIBLE WRONG ANSWER before they were caught, which is why
they are tests and not comments. Neither is exotic; both are the sort of thing
that reads as reasonable data hygiene.

1. **GRADING POPULATION.** The first version skipped (player, match) rows whose
   realized shot count was 0, on the reasoning that a 0 for an unused substitute
   is an availability fact rather than a prediction error. That is selection on
   the DEPENDENT VARIABLE. It kept **42 of 197 rows (a 79% cut)**, left every
   survivor with `realized >= 1`, and did so on a test of whether anchoring
   RAISES projections. Corrected, the same measurement went n=42 -> n=6,486 at
   full scale and the MAE moved 0.98 -> 0.52.

2. **CLUSTERING.** Every player in a match receives the SAME anchor shift, so
   player rows are not independent observations. The player-level sign test read
   **p = 0.0027 against its own t of -1.28** -- and when those two disagree the
   disagreement is the diagnosis, not a lucky finding.

A third invariant is asserted because it is the one that makes the headline
number honest: the reported statistic must be MATCH-clustered, and a difference
that is consistent in DIRECTION but vanishing in MAGNITUDE has to be reportable
as exactly that.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    """Import the script by path -- `scripts/` is not a package."""
    path = REPO_ROOT / "scripts" / "backtest_soccer_anchor_vs_outcomes.py"
    spec = importlib.util.spec_from_file_location("backtest_soccer_anchor_vs_outcomes", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load()


class GradingPopulationTests(unittest.TestCase):
    """`grade` must keep every predicted player in a match with a live feed."""

    def _rows(self):
        return [
            {"match_id": "m1", "player": "shooter", "base": 1.4, "anchored": 1.5},
            {"match_id": "m1", "player": "blank", "base": 0.9, "anchored": 1.1},
            {"match_id": "m1", "player": "sub", "base": 0.2, "anchored": 0.3},
        ]

    def test_players_who_took_no_shots_are_GRADED_at_zero_not_dropped(self) -> None:
        """THE ORIGINAL DEFECT. Dropping these selects on the outcome."""
        actuals = {"m1": {"shots": {"shooter": 3}, "events": 11}}

        graded, dropped = MOD.grade(self._rows(), actuals)

        self.assertEqual(len(graded), 3, "every predicted player must be graded")
        self.assertEqual(dropped, 0)
        by_player = {g["player"]: g["realized"] for g in graded}
        self.assertEqual(by_player, {"shooter": 3, "blank": 0, "sub": 0})

    def test_the_graded_set_is_NOT_conditioned_on_a_positive_outcome(self) -> None:
        """The signature of the bug: every surviving row having realized >= 1."""
        actuals = {"m1": {"shots": {"shooter": 2}, "events": 9}}

        graded, _dropped = MOD.grade(self._rows(), actuals)

        self.assertTrue(any(g["realized"] == 0 for g in graded),
                        "a zero-outcome row must survive grading")
        self.assertFalse(all(g["realized"] >= 1 for g in graded))

    def test_a_match_with_an_EMPTY_feed_is_dropped_rather_than_graded_as_zeros(self) -> None:
        """`events == 0` is unknowable, not "nobody shot". Grading it as zeros
        would invent outcomes for every player in the match."""
        graded, dropped = MOD.grade(self._rows(), {"m1": {"shots": {}, "events": 0}})

        self.assertEqual(graded, [])
        self.assertEqual(dropped, 3)

    def test_a_match_with_NO_feed_at_all_is_dropped(self) -> None:
        graded, dropped = MOD.grade(self._rows(), {})

        self.assertEqual(graded, [])
        self.assertEqual(dropped, 3)


class MatchClusteringTests(unittest.TestCase):
    """`report` must cluster on the match, and must expose the effect size."""

    @staticmethod
    def _match(match_id, n, base, anchored, realized):
        return [{"match_id": match_id, "player": f"{match_id}_p{i}",
                 "base": base, "anchored": anchored, "realized": realized}
                for i in range(n)]

    def test_the_clustering_unit_is_the_MATCH_not_the_player(self) -> None:
        """40 correlated player rows from 2 matches are 2 observations."""
        graded = self._match("m1", 20, 1.0, 1.2, 1) + self._match("m2", 20, 1.0, 0.8, 1)

        out = MOD.report(graded)

        self.assertEqual(out["rows"], 40)
        self.assertEqual(out["matches"], 2, "the unit of independence is the match")
        self.assertEqual(len(out["match_deltas"]), 2)

    def test_the_player_level_p_value_is_LABELLED_inflated(self) -> None:
        """It is published, but never as the headline -- the key name says so."""
        graded = self._match("m1", 12, 1.0, 1.3, 1) + self._match("m2", 12, 1.0, 1.3, 1)

        out = MOD.report(graded)

        self.assertIn("row_sign_test_p_INFLATED", out)
        self.assertIn("match_sign_test_p", out)

    def test_a_consistent_but_VANISHING_effect_is_reportable_as_both(self) -> None:
        """The real result: worse in most matches, by an amount inside the noise.
        Direction and magnitude are different findings and both must survive."""
        # realized 1.5 against a base of 1.0 gives BOTH arms a real error (0.5),
        # so the comparison is about which is closer -- not, as a first draft of
        # this fixture had it, two arms equidistant from the outcome and
        # therefore both "worse".
        graded = []
        for i in range(9):                       # anchored very slightly worse
            graded += self._match(f"w{i}", 3, 1.0, 0.998, 1.5)
        for i in range(1):                       # one match the other way
            graded += self._match(f"b{i}", 3, 1.0, 1.002, 1.5)

        out = MOD.report(graded)

        self.assertEqual(out["matches"], 10)
        self.assertEqual(out["match_wins"], 1, "direction: anchored worse in 9/10")
        self.assertLess(abs(out["match_mean_delta"]), 0.01, "magnitude: negligible")
        self.assertLess(out["anchored_mae"] - out["base_mae"], 0.01)
        self.assertGreater(out["anchored_mae"], out["base_mae"])

    def test_sign_test_is_two_sided_and_symmetric(self) -> None:
        self.assertAlmostEqual(MOD.sign_test(9, 10), MOD.sign_test(1, 10))
        self.assertAlmostEqual(MOD.sign_test(5, 10), 1.0)
        self.assertLess(MOD.sign_test(10, 10), 0.01)


class PriceAndNameHandlingTests(unittest.TestCase):

    def test_a_price_inside_the_american_gap_is_REFUSED(self) -> None:
        """Coercing it would manufacture a probability."""
        self.assertIsNone(MOD.american_to_prob(50))
        self.assertIsNone(MOD.american_to_prob(-99))
        self.assertIsNone(MOD.american_to_prob("not a price"))
        self.assertAlmostEqual(MOD.american_to_prob(-200), 200 / 300)
        self.assertAlmostEqual(MOD.american_to_prob(100), 0.5)

    def test_accent_folding_joins_the_same_player(self) -> None:
        """Raw equality matched 18 of 37 shooters and looked like thin data."""
        self.assertEqual(MOD.fold("Álvaro Morata"), MOD.fold("Alvaro Morata"))
        self.assertEqual(MOD.fold("  Kylian Mbappé "), "kylian mbappe")


if __name__ == "__main__":
    unittest.main()
