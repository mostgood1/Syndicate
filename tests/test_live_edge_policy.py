"""`#340`: every sport must answer "may this row carry an edge?" identically.

The defect these pin: on 2026-08-10 a live WNBA game served **128 of 128
projected rows with an `edge_vs_line`** while MLB suppressed all 862 of its live
rows, because the rule lived in `prop_projections` and `soccer_projections` as
two copies and WNBA never got one. The board showed edges on a live game that its
own logic, one sport over, called meaningless.

The cross-sport test is the load-bearing one. Per-sport tests would all have
passed while the sports disagreed with each other.
"""

from __future__ import annotations

import unittest

from syndicate.features.shared.live_edge_policy import (
    LIVE_OR_DONE_STATES,
    live_edge_unavailable_reason,
)


def _row(state):
    return {"game": {"state": state}} if state is not None else {"game": {}}


class LiveEdgePolicyTests(unittest.TestCase):
    def test_live_and_finished_states_suppress(self):
        for state in ("live", "in_progress", "final", "completed"):
            with self.subTest(state=state):
                reason = live_edge_unavailable_reason(_row(state))
                self.assertIsNotNone(reason)
                self.assertIn(state, reason)

    def test_a_finished_game_is_not_treated_as_safe_again(self):
        # Easy to get backwards: "the game is over so the model is comparable".
        # A settled or pulled market is worse to price against, not better.
        self.assertIn("final", LIVE_OR_DONE_STATES)
        self.assertIn("completed", LIVE_OR_DONE_STATES)

    def test_pregame_allows_an_edge(self):
        for state in ("pregame", "scheduled", "PREGAME"):
            with self.subTest(state=state):
                self.assertIsNone(live_edge_unavailable_reason(_row(state)))

    def test_unknown_state_allows_the_edge_deliberately(self):
        # Documented choice, not an oversight. Suppressing unknown state would
        # blank the edge column on exactly the days the game-state join
        # degrades -- turning an enrichment gap into a total loss of the board's
        # purpose. The failure guarded against is a LIVE game ranking, and
        # liveness is something the board positively knows.
        for row in ({}, {"game": {}}, {"game": None}, {"game": {"state": ""}}):
            with self.subTest(row=row):
                self.assertIsNone(live_edge_unavailable_reason(row))


class EverySportSuppressesLiveEdgesTests(unittest.TestCase):
    """THE regression test. Each sport emits its own edge field; all must go."""

    def test_wnba_suppresses_edge_vs_line_on_a_live_game(self):
        from syndicate.features.shared.wnba_projections import (
            WnbaProjectionIndex,
            attach_wnba_projections,
        )

        index = WnbaProjectionIndex(by_player={"rhyne howard": {"ast": 3.69}}, players=1)

        def build(state):
            return {
                "kind": "prop",
                "market": "player_assists",
                "player_name": "Rhyne Howard",
                "line": 3.5,
                "game": {"state": state},
            }

        pregame = build("pregame")
        live = build("live")
        attach_wnba_projections([pregame], index)
        attach_wnba_projections([live], index)

        # Pregame keeps its edge...
        self.assertEqual(pregame["projection"]["edge_vs_line"], 0.19)
        # ...live loses it, and says why.
        self.assertIsNone(live["projection"]["edge_vs_line"])
        self.assertIn("live", live["projection"]["edge_unavailable_reason"])
        # The PROJECTION itself survives in both: withholding the edge is not
        # the same as hiding the model.
        self.assertEqual(live["projection"]["projected"], 3.69)

    def test_the_rule_exists_in_exactly_one_place(self):
        # The defect was three copies-minus-one. If a sport ever inlines the
        # sentence again, this fails and points at why.
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "syndicate"
        needle = "cannot be priced against a live market"
        owners = [
            path
            for path in root.rglob("*.py")
            if needle in path.read_text(encoding="utf-8", errors="ignore")
        ]
        self.assertEqual(
            [p.name for p in owners],
            ["live_edge_policy.py"],
            "the live-edge rule must live only in live_edge_policy.py",
        )

    def test_every_projection_module_routes_through_the_policy(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "syndicate" / "features" / "shared"
        for name in ("prop_projections.py", "soccer_projections.py", "wnba_projections.py"):
            with self.subTest(module=name):
                text = (root / name).read_text(encoding="utf-8")
                self.assertIn("live_edge_unavailable_reason", text)


if __name__ == "__main__":
    unittest.main()
