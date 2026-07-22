from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.portfolio_summary import build_portfolio_summary
from syndicate.features.prediction_ledger import record_prediction


class PortfolioSummaryStakeAndParlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self._tmp_dir.name) / "prediction_ledger.json"
        self._ledger_path_patcher = patch(
            "syndicate.features.prediction_ledger._default_ledger_path",
            return_value=self.ledger_path,
        )
        self._ledger_path_patcher.start()

    def tearDown(self) -> None:
        self._ledger_path_patcher.stop()
        self._tmp_dir.cleanup()

    def test_straight_position_row_carries_stake_and_placed_bet_text(self) -> None:
        record_prediction(
            sport="nba", market="Moneyline", selection="Lakers ML", odds=-120, stake=20.0, ledger_path=self.ledger_path
        )

        summary = build_portfolio_summary()

        self.assertEqual(len(summary["positions"]), 1)
        position = summary["positions"][0]
        self.assertEqual(position["stake"], 20.0)
        self.assertEqual(position["bet_type"], "straight")
        self.assertIsNone(position["legs"])
        self.assertEqual(position["placed_bet"], "Lakers ML (Moneyline)")

    def test_parlay_position_row_carries_legs_and_placed_bet_text(self) -> None:
        legs = [
            {"sport": "nba", "market": "moneyline", "selection": "Lakers ML"},
            {"sport": "wnba", "market": "spread", "selection": "Liberty -4.5"},
        ]
        record_prediction(
            sport="multi",
            market="parlay",
            selection="2-leg parlay",
            odds=250,
            stake=15.0,
            bet_type="parlay",
            legs=legs,
            ledger_path=self.ledger_path,
        )

        summary = build_portfolio_summary()

        position = summary["positions"][0]
        self.assertEqual(position["bet_type"], "parlay")
        self.assertEqual(position["legs"], legs)
        self.assertEqual(position["placed_bet"], "Parlay (2 legs)")

    def test_exposure_by_sport_only_counts_pending_positions(self) -> None:
        pending_id = record_prediction(
            sport="nba", market="Moneyline", selection="Lakers ML", odds=-120, stake=20.0, ledger_path=self.ledger_path
        )["id"]
        record_prediction(
            sport="wnba", market="Total", selection="Over 162.5", odds=-110, stake=30.0, ledger_path=self.ledger_path
        )
        from syndicate.features.prediction_ledger import record_result

        record_result(prediction_id=pending_id, outcome="win", pnl=16.67, ledger_path=self.ledger_path)

        summary = build_portfolio_summary()
        exposure = {row["sport"]: row["stake"] for row in summary["exposure_by_sport"]}

        # nba is settled (win) -- no longer open exposure; wnba is still pending.
        self.assertNotIn("nba", exposure)
        self.assertEqual(exposure.get("wnba"), 30.0)

    def test_exposure_by_sport_defaults_to_one_unit_when_stake_missing(self) -> None:
        record_prediction(sport="mlb", market="Total", selection="Over 8.5", odds=-110, ledger_path=self.ledger_path)

        summary = build_portfolio_summary()
        exposure = {row["sport"]: row["stake"] for row in summary["exposure_by_sport"]}

        self.assertEqual(exposure.get("mlb"), 1.0)


if __name__ == "__main__":
    unittest.main()
