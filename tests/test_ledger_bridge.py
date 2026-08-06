"""#216 -- the ledger bridge, and parlay settlement rules.

Two ledgers exist and /portfolio reads only one (stated in a code comment at
syndicate/blueprints/intelligence.py). Both settlement autoruns are enabled and
production still showed settled_count 0 on five tracked bets, one of which is a
4-leg cross-sport parlay that reconciliation structurally cannot settle -- it has
no single market to match on.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from syndicate.features.prediction_ledger import load_all_predictions, record_prediction
from syndicate.features.shared.ledger_bridge import bridge_settled_results, settle_parlay_outcome


def _record(rid: str, outcome: str, **extra) -> dict:
    return {"recommendation_id": rid, "result": {"outcome": outcome, **extra}}


class ParlayRuleTests(unittest.TestCase):
    """Bookmaker rules, not a simplification. Each of these is a real settlement
    case that a naive all-legs-decided check gets wrong."""

    def _legs(self, *ids: str) -> list[dict]:
        return [{"recommendation_id": rid} for rid in ids]

    def test_one_losing_leg_settles_the_parlay_immediately(self) -> None:
        """Decided the moment one leg loses. Waiting for the other three -- which
        may never grade -- would leave a dead bet pending forever."""
        index = {"a": {"outcome": "loss"}}
        self.assertEqual(settle_parlay_outcome(self._legs("a", "b", "c"), index), "loss")

    def test_all_legs_must_win_for_the_parlay_to_win(self) -> None:
        index = {"a": {"outcome": "win"}, "b": {"outcome": "win"}}
        self.assertIsNone(settle_parlay_outcome(self._legs("a", "b", "c"), index),
                          "an ungraded third leg must not be treated as a win")
        index["c"] = {"outcome": "win"}
        self.assertEqual(settle_parlay_outcome(self._legs("a", "b", "c"), index), "win")

    def test_a_pushed_leg_drops_out_rather_than_losing_the_parlay(self) -> None:
        index = {"a": {"outcome": "win"}, "b": {"outcome": "push"}, "c": {"outcome": "win"}}
        self.assertEqual(settle_parlay_outcome(self._legs("a", "b", "c"), index), "win")

    def test_all_legs_pushing_returns_the_stake_rather_than_winning(self) -> None:
        index = {"a": {"outcome": "push"}, "b": {"outcome": "void"}}
        self.assertEqual(settle_parlay_outcome(self._legs("a", "b"), index), "push")

    def test_undecided_stays_undecided(self) -> None:
        self.assertIsNone(settle_parlay_outcome(self._legs("a", "b"), {}))
        self.assertIsNone(settle_parlay_outcome([], {"a": {"outcome": "win"}}))


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "prediction_ledger.json"

    def test_straight_bet_settles_with_clv_from_the_bet_time_quote(self) -> None:
        record = record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-140, stake=100,
            features_snapshot={"recommendation_id": "reco_1"},
            quote={"bookmaker": "fanduel", "price": -140},
            ledger_path=self.ledger,
        )
        summary = bridge_settled_results(
            evaluation_records=[_record("reco_1", "win", closing_price=-160)],
            ledger_path=self.ledger,
        )
        self.assertEqual(summary["straight_settled"], 1)
        stored = next(item for item in load_all_predictions(ledger_path=self.ledger) if item["id"] == record["id"])
        self.assertEqual(stored["result"]["outcome"], "win")
        # -140 struck, -160 close: the market moved toward us.
        self.assertGreater(stored["result"]["clv_pct"], 0)
        self.assertAlmostEqual(stored["result"]["pnl"], 100 * 100 / 140, places=4)

    def test_parlay_settles_and_pnl_uses_the_stored_combined_price(self) -> None:
        record = record_prediction(
            sport="multi", market="parlay", selection="4-leg parlay",
            odds=1118.0, stake=25, bet_type="parlay",
            legs=[{"recommendation_id": "r1"}, {"recommendation_id": "r2"}],
            ledger_path=self.ledger,
        )
        summary = bridge_settled_results(
            evaluation_records=[_record("r1", "win"), _record("r2", "win")],
            ledger_path=self.ledger,
        )
        self.assertEqual(summary["parlays_settled"], 1)
        stored = next(item for item in load_all_predictions(ledger_path=self.ledger) if item["id"] == record["id"])
        self.assertEqual(stored["result"]["outcome"], "win")
        # +1118 on 25 units, from the parlay's OWN stored price -- not a product
        # recomputed from legs, which would drift from what the book actually
        # offered.
        self.assertAlmostEqual(stored["result"]["pnl"], 25 * 11.18, places=4)
        # A parlay has no single closing price, so CLV must stay unset rather
        # than being invented from one arbitrary leg.
        self.assertIsNone(stored["result"]["clv_pct"])

    def test_a_losing_leg_settles_the_parlay_as_a_loss_for_the_full_stake(self) -> None:
        record = record_prediction(
            sport="multi", market="parlay", selection="2-leg", odds=300, stake=40, bet_type="parlay",
            legs=[{"recommendation_id": "r1"}, {"recommendation_id": "r2"}],
            ledger_path=self.ledger,
        )
        bridge_settled_results(
            evaluation_records=[_record("r1", "loss")], ledger_path=self.ledger
        )
        stored = next(item for item in load_all_predictions(ledger_path=self.ledger) if item["id"] == record["id"])
        self.assertEqual(stored["result"]["outcome"], "loss")
        self.assertEqual(stored["result"]["pnl"], -40.0)

    def test_bridging_is_idempotent(self) -> None:
        record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-110, stake=10,
            features_snapshot={"recommendation_id": "reco_1"}, ledger_path=self.ledger,
        )
        records = [_record("reco_1", "win")]
        first = bridge_settled_results(evaluation_records=records, ledger_path=self.ledger)
        second = bridge_settled_results(evaluation_records=records, ledger_path=self.ledger)
        self.assertEqual(first["straight_settled"], 1)
        self.assertEqual(second["straight_settled"], 0, "re-running must not double-settle")

    def test_unmatched_predictions_are_skipped_not_settled(self) -> None:
        record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-110, stake=10,
            features_snapshot={"recommendation_id": "reco_unknown"}, ledger_path=self.ledger,
        )
        summary = bridge_settled_results(
            evaluation_records=[_record("reco_other", "win")], ledger_path=self.ledger
        )
        self.assertEqual(summary["straight_settled"], 0)
        self.assertEqual(summary["skipped"], 1)

    def test_a_broken_evaluation_record_cannot_take_the_bridge_down(self) -> None:
        record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-110, stake=10,
            features_snapshot={"recommendation_id": "reco_1"}, ledger_path=self.ledger,
        )
        summary = bridge_settled_results(
            evaluation_records=[None, "nonsense", {"no_id": True}, _record("reco_1", "win")],
            ledger_path=self.ledger,
        )
        self.assertEqual(summary["straight_settled"], 1)


if __name__ == "__main__":
    unittest.main()
