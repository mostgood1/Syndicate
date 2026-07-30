from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.features.prediction_ledger import delete_prediction
from syndicate.features.prediction_ledger import get_performance_summary
from syndicate.features.prediction_ledger import load_all_predictions
from syndicate.features.prediction_ledger import record_prediction
from syndicate.features.prediction_ledger import record_result


class PredictionLedgerStakeAndParlayTests(unittest.TestCase):
    def test_record_prediction_round_trips_stake_bet_type_and_legs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "prediction_ledger.json"
            legs = [
                {"sport": "nba", "market": "moneyline", "selection": "Lakers ML", "odds": -120},
                {"sport": "wnba", "market": "spread", "selection": "Liberty -4.5", "odds": -110},
            ]
            record = record_prediction(
                sport="multi",
                market="parlay",
                selection="2-leg parlay",
                odds=250,
                stake=25.0,
                bet_type="parlay",
                legs=legs,
                ledger_path=ledger_path,
            )

            self.assertEqual(record["stake"], 25.0)
            self.assertEqual(record["bet_type"], "parlay")
            self.assertEqual(record["legs"], legs)

            predictions = load_all_predictions(ledger_path=ledger_path)
            self.assertEqual(len(predictions), 1)
            self.assertEqual(predictions[0]["stake"], 25.0)
            self.assertEqual(predictions[0]["bet_type"], "parlay")
            self.assertEqual(predictions[0]["legs"], legs)

    def test_record_prediction_defaults_bet_type_to_straight_without_legs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "prediction_ledger.json"
            record = record_prediction(
                sport="nba",
                market="moneyline",
                selection="Lakers ML",
                odds=-120,
                stake=10.0,
                ledger_path=ledger_path,
            )

        self.assertEqual(record["bet_type"], "straight")
        self.assertIsNone(record["legs"])
        self.assertEqual(record["stake"], 10.0)

    def test_existing_callers_without_stake_still_work_unchanged(self) -> None:
        # record_prediction's original call site (intelligence.py's
        # auto-recording at candidate-generation time) never passes
        # stake/bet_type/legs -- this must keep behaving exactly as before.
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "prediction_ledger.json"
            record = record_prediction(
                sport="mlb",
                market="total",
                selection="Over 8.5",
                odds=-110,
                edge=0.04,
                ledger_path=ledger_path,
            )

        self.assertIsNone(record["stake"])
        self.assertEqual(record["bet_type"], "straight")
        self.assertIsNone(record["legs"])

    def test_roi_uses_real_stake_when_present_instead_of_defaulting_to_one_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "prediction_ledger.json"
            record = record_prediction(
                sport="nba", market="moneyline", selection="Lakers ML", odds=-120, stake=50.0, ledger_path=ledger_path
            )
            record_result(prediction_id=record["id"], outcome="win", pnl=41.67, ledger_path=ledger_path)

            summary = get_performance_summary(ledger_path=ledger_path)

        # 41.67 pnl / 50.0 stake, not / 1.0 default.
        self.assertAlmostEqual(summary["roi"], 41.67 / 50.0, places=4)

    def test_parlay_record_does_not_break_breakdown_by_sport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "prediction_ledger.json"
            record_prediction(
                sport="nba", market="moneyline", selection="Lakers ML", odds=-120, stake=10.0, ledger_path=ledger_path
            )
            record_prediction(
                sport="multi",
                market="parlay",
                selection="2-leg parlay",
                odds=250,
                stake=25.0,
                bet_type="parlay",
                legs=[{"sport": "nba", "market": "moneyline", "selection": "Lakers ML"}],
                ledger_path=ledger_path,
            )

            summary = get_performance_summary(ledger_path=ledger_path)

        self.assertEqual(summary["total_bets"], 2)
        self.assertIn("nba", summary["by_sport"])
        self.assertIn("multi", summary["by_sport"])
        self.assertEqual(summary["by_sport"]["multi"]["predictions"], 1)


class PortfolioBetsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self._tmp_dir.name) / "prediction_ledger.json"
        self._ledger_path_patcher = patch(
            "syndicate.features.prediction_ledger._default_ledger_path",
            return_value=self.ledger_path,
        )
        self._ledger_path_patcher.start()
        app = create_app()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def tearDown(self) -> None:
        self._ledger_path_patcher.stop()
        self._tmp_dir.cleanup()

    def test_posting_a_straight_bet_is_readable_back_via_load_all_predictions(self) -> None:
        response = self.client.post(
            "/api/portfolio/bets",
            json={
                "sport": "nba",
                "market": "moneyline",
                "selection": "Lakers ML",
                "odds": -120,
                "stake": 20.0,
                "recommendation_id": "reco_abc123",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body["bet"]["stake"], 20.0)
        self.assertEqual(body["bet"]["bet_type"], "straight")

        predictions = load_all_predictions(ledger_path=self.ledger_path)
        self.assertEqual(len(predictions), 1)
        self.assertEqual(predictions[0]["selection"], "Lakers ML")
        self.assertEqual(predictions[0]["features_snapshot"].get("recommendation_id"), "reco_abc123")

    def test_posting_a_parlay_is_readable_back_via_load_all_predictions(self) -> None:
        legs = [
            {"sport": "nba", "market": "moneyline", "selection": "Lakers ML", "odds": -120},
            {"sport": "wnba", "market": "spread", "selection": "Liberty -4.5", "odds": -110},
        ]
        response = self.client.post(
            "/api/portfolio/bets",
            json={"bet_type": "parlay", "legs": legs, "odds": 250, "stake": 15.0},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body["bet"]["bet_type"], "parlay")
        self.assertEqual(body["bet"]["legs"], legs)

        predictions = load_all_predictions(ledger_path=self.ledger_path)
        self.assertEqual(len(predictions), 1)
        self.assertEqual(predictions[0]["sport"], "multi")
        self.assertEqual(predictions[0]["market"], "parlay")
        self.assertEqual(predictions[0]["legs"], legs)

    def test_parlay_without_legs_returns_400(self) -> None:
        response = self.client.post("/api/portfolio/bets", json={"bet_type": "parlay", "odds": 250, "stake": 15.0})
        self.assertEqual(response.status_code, 400)

    def test_straight_bet_missing_required_fields_returns_400(self) -> None:
        response = self.client.post("/api/portfolio/bets", json={"stake": 10.0})
        self.assertEqual(response.status_code, 400)

    def test_pick_line_event_id_and_game_date_round_trip_into_features_snapshot(self) -> None:
        # #147 follow-up: the bet slip previously dropped the wagered side
        # and line entirely -- a straight prop bet's `selection` is the
        # player's name, not the Over/Under pick, so without this a settled
        # prop could never be graded even once real actual/line data
        # existed for it.
        response = self.client.post(
            "/api/portfolio/bets",
            json={
                "sport": "mlb",
                "market": "Pitcher Outs Recorded",
                "selection": "Troy Melton",
                "odds": -120,
                "stake": 50.0,
                "pick": "Over",
                "line": 17.5,
                "event_id": "824247",
                "game_date": "2026-07-23",
            },
        )
        self.assertEqual(response.status_code, 200)
        predictions = load_all_predictions(ledger_path=self.ledger_path)
        self.assertEqual(len(predictions), 1)
        snapshot = predictions[0]["features_snapshot"]
        self.assertEqual(snapshot.get("pick"), "Over")
        self.assertEqual(snapshot.get("line"), 17.5)
        self.assertEqual(snapshot.get("event_id"), "824247")
        self.assertEqual(snapshot.get("game_date"), "2026-07-23")

    def test_bet_without_new_fields_still_has_no_stray_keys_in_features_snapshot(self) -> None:
        response = self.client.post(
            "/api/portfolio/bets",
            json={"sport": "nba", "market": "moneyline", "selection": "Lakers ML", "odds": -120, "stake": 20.0},
        )
        self.assertEqual(response.status_code, 200)
        predictions = load_all_predictions(ledger_path=self.ledger_path)
        self.assertIsNone(predictions[0].get("features_snapshot") or None)

    def test_delete_route_removes_the_prediction_and_its_result(self) -> None:
        record = record_prediction(
            sport="mlb", market="hits", selection="Player A", odds=-110, stake=10.0, ledger_path=self.ledger_path
        )
        record_result(prediction_id=record["id"], outcome="win", pnl=9.09, ledger_path=self.ledger_path)

        response = self.client.post(f"/portfolio/bets/{record['id']}/delete")
        self.assertEqual(response.status_code, 303)

        predictions = load_all_predictions(ledger_path=self.ledger_path)
        self.assertEqual(predictions, [])

    def test_delete_route_with_unknown_id_still_redirects_cleanly(self) -> None:
        response = self.client.post("/portfolio/bets/does-not-exist/delete")
        self.assertEqual(response.status_code, 303)


class DeletePredictionTests(unittest.TestCase):
    def test_removes_prediction_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "prediction_ledger.json"
            record = record_prediction(
                sport="mlb", market="hits", selection="Player A", odds=-110, stake=10.0, ledger_path=ledger_path
            )
            record_result(prediction_id=record["id"], outcome="loss", pnl=-10.0, ledger_path=ledger_path)

            removed = delete_prediction(record["id"], ledger_path=ledger_path)

            self.assertTrue(removed)
            predictions = load_all_predictions(ledger_path=ledger_path)
            self.assertEqual(predictions, [])

    def test_unknown_id_returns_false_and_leaves_ledger_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "prediction_ledger.json"
            record_prediction(sport="mlb", market="hits", selection="Player A", ledger_path=ledger_path)

            removed = delete_prediction("does-not-exist", ledger_path=ledger_path)

            self.assertFalse(removed)
            self.assertEqual(len(load_all_predictions(ledger_path=ledger_path)), 1)

    def test_empty_prediction_id_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "prediction_ledger.json"
            self.assertFalse(delete_prediction("", ledger_path=ledger_path))
            self.assertFalse(delete_prediction(None, ledger_path=ledger_path))


if __name__ == "__main__":
    unittest.main()
