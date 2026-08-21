"""The live per-player projection: its endpoints, and its refusals.

ENDPOINTS FIRST. A projection that does not reduce to the pregame number at
tip-off and to the actual stat at the buzzer is wrong in the middle too, and
those two cases are the only ones with a known right answer.

THE REFUSALS ARE THE OTHER HALF. `#475` measured what happens without a pregame
anchor -- 12 points two minutes in projects a 240-point final, "a 75-point error
against a 165 line, published as a real number the over/under probability was
then derived from". This estimator declines rather than extrapolating, and
`test_refuses_without_a_pregame_anchor` is what keeps that true.
"""
from __future__ import annotations

import unittest

from syndicate.features.shared.wnba_live_prop_projection import (
    REASON_NO_LIVE_LINE,
    REASON_NO_PREGAME_ANCHOR,
    REASON_NO_PROJECTED_MINUTES,
    project_live_player_stat,
)


class EndpointTests(unittest.TestCase):
    """The two cases whose answer is known exactly."""

    def test_at_tipoff_it_IS_the_pregame_projection(self) -> None:
        out = project_live_player_stat(
            current_stat=0.0, minutes_played=0.0, pregame_stat=18.0, pregame_minutes=30.0
        )
        self.assertAlmostEqual(out["projected"], 18.0, places=6)
        self.assertEqual(out["blend_weight"], 0.0)

    def test_at_the_buzzer_it_IS_the_actual_stat(self) -> None:
        out = project_live_player_stat(
            current_stat=23.0, minutes_played=30.0, pregame_stat=18.0, pregame_minutes=30.0
        )
        self.assertAlmostEqual(out["projected"], 23.0, places=6)
        self.assertEqual(out["minutes_remaining"], 0.0)

    def test_the_clock_caps_the_remainder(self) -> None:
        """A starter projected 32 who has played 8 cannot play 24 more when 10
        remain. Without the cap, a late capture inflates every projection."""
        capped = project_live_player_stat(
            current_stat=10.0, minutes_played=8.0, pregame_stat=16.0, pregame_minutes=32.0,
            game_minutes_remaining=10.0,
        )
        uncapped = project_live_player_stat(
            current_stat=10.0, minutes_played=8.0, pregame_stat=16.0, pregame_minutes=32.0,
        )
        self.assertEqual(capped["minutes_remaining"], 10.0)
        self.assertEqual(uncapped["minutes_remaining"], 24.0)
        self.assertLess(capped["projected"], uncapped["projected"])


class BlendTests(unittest.TestCase):
    def test_a_hot_start_moves_the_projection_but_does_not_own_it(self) -> None:
        """6 points in 9 minutes is a 26-point pace. The projection must be
        pulled UP from the 12-point anchor and stay far BELOW the pace."""
        out = project_live_player_stat(
            current_stat=6.0, minutes_played=9.0, pregame_stat=12.0, pregame_minutes=30.0
        )
        self.assertGreater(out["projected"], 12.0, "a hot start must move it up")
        self.assertLess(out["projected"], 20.0, "it must not chase a 26-point pace")
        self.assertAlmostEqual(out["blend_weight"], 0.3, places=4)

    def test_a_cold_start_moves_it_down_symmetrically(self) -> None:
        out = project_live_player_stat(
            current_stat=0.0, minutes_played=9.0, pregame_stat=12.0, pregame_minutes=30.0
        )
        self.assertLess(out["projected"], 12.0)
        self.assertGreater(out["projected"], 0.0, "a scoreless nine minutes is not a zero final")

    def test_weight_rises_with_minutes_played(self) -> None:
        weights = [
            project_live_player_stat(
                current_stat=4.0, minutes_played=m, pregame_stat=12.0, pregame_minutes=30.0
            )["blend_weight"]
            for m in (3.0, 12.0, 24.0, 30.0)
        ]
        self.assertEqual(weights, sorted(weights))
        self.assertEqual(weights[-1], 1.0)


class RefusalTests(unittest.TestCase):
    def test_refuses_without_a_pregame_anchor(self) -> None:
        """THE GUARD. `#475`'s 240-point total came from exactly this input."""
        out = project_live_player_stat(
            current_stat=12.0, minutes_played=2.0, pregame_stat=None, pregame_minutes=30.0
        )
        self.assertIsNone(out["projected"], "a live rate alone must not be extrapolated")
        self.assertEqual(out["unavailable_reason"], REASON_NO_PREGAME_ANCHOR)

    def test_an_anchor_with_no_minutes_is_its_own_reason(self) -> None:
        out = project_live_player_stat(
            current_stat=4.0, minutes_played=6.0, pregame_stat=12.0, pregame_minutes=None
        )
        self.assertIsNone(out["projected"])
        self.assertEqual(out["unavailable_reason"], REASON_NO_PROJECTED_MINUTES)

    def test_a_player_with_no_live_line_is_refused_by_name(self) -> None:
        for current, played in ((None, 5.0), (5.0, None), (5.0, -1.0)):
            with self.subTest(current=current, played=played):
                out = project_live_player_stat(
                    current_stat=current, minutes_played=played,
                    pregame_stat=12.0, pregame_minutes=30.0,
                )
                self.assertIsNone(out["projected"])
                self.assertEqual(out["unavailable_reason"], REASON_NO_LIVE_LINE)

    def test_it_never_returns_a_bare_None(self) -> None:
        """An absent verdict is how 'refused' becomes 'not considered'."""
        out = project_live_player_stat(
            current_stat=None, minutes_played=None, pregame_stat=None, pregame_minutes=None
        )
        self.assertIsInstance(out, dict)
        self.assertIn("projected", out)
        self.assertIsNotNone(out["unavailable_reason"])

    def test_it_publishes_a_projection_and_NEVER_a_probability(self) -> None:
        """Pricing needs a measured interval and this estimator has none.

        If a probability or edge key ever appears here, someone has routed
        around both `prob_interval_swamps_edge` and
        `analytic_estimator_never_backtested_for_this_market` at once.
        """
        out = project_live_player_stat(
            current_stat=6.0, minutes_played=9.0, pregame_stat=12.0, pregame_minutes=30.0
        )
        for banned in ("prob", "probability", "p_over", "edge", "edge_pp", "priceable"):
            self.assertNotIn(banned, out)


class ParsingTests(unittest.TestCase):
    def test_minutes_arrive_as_strings_from_espn(self) -> None:
        out = project_live_player_stat(
            current_stat="6", minutes_played="9", pregame_stat="12", pregame_minutes="30"
        )
        self.assertIsNotNone(out["projected"])
        self.assertEqual(out["minutes_played"], 9.0)

    def test_a_clock_style_minutes_value_is_parsed_not_dropped(self) -> None:
        out = project_live_player_stat(
            current_stat=6.0, minutes_played="9:30", pregame_stat=12.0, pregame_minutes=30.0
        )
        self.assertAlmostEqual(out["minutes_played"], 9.5, places=6)

    def test_junk_declines_rather_than_raising(self) -> None:
        for bad in ("", "  ", "n/a", float("nan"), True):
            with self.subTest(bad=bad):
                out = project_live_player_stat(
                    current_stat=bad, minutes_played=9.0,
                    pregame_stat=12.0, pregame_minutes=30.0,
                )
                self.assertEqual(out["unavailable_reason"], REASON_NO_LIVE_LINE)


if __name__ == "__main__":
    unittest.main()
