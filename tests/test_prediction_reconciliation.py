from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from syndicate.features.prediction_ledger import record_prediction
from syndicate.features.prediction_ledger import record_result
from syndicate.features.prediction_reconciliation import pending_prediction_dates
from syndicate.features.prediction_reconciliation import reconcile_prediction_results_for_date


class PredictionReconciliationTests(unittest.TestCase):
    def test_reconcile_prediction_results_for_date_records_settled_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path = root / "prediction_ledger.json"
            result_root = root / "data"
            result_path = result_root / "nba_source" / "data" / "processed" / "recon_props_2026-06-07.csv"
            result_path.parent.mkdir(parents=True, exist_ok=True)

            with result_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["player", "market", "result", "actual", "line", "closing_line", "odds", "payout"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "player": "Jane Doe",
                        "market": "points",
                        "result": "win",
                        "actual": "24",
                        "line": "20.5",
                        "closing_line": "21.5",
                        "odds": "-110",
                        "payout": "0.9091",
                    }
                )

            record_prediction(
                sport="nba",
                market="points",
                selection="Jane Doe over 20.5",
                odds=-110,
                implied_probability=0.5238,
                model_probability=0.61,
                edge=0.0862,
                confidence=67.0,
                signals={"signal_contributions": {"usage": 0.2}},
                features_snapshot={
                    "selected_date": "2026-06-07",
                    "player_name": "Jane Doe",
                    "line": 20.5,
                },
                timestamp="2026-06-07T12:00:00Z",
                prediction_id="pred-1",
                ledger_path=ledger_path,
            )

            payload = reconcile_prediction_results_for_date("2026-06-07", ledger_path=ledger_path, result_roots=[result_root])

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["resolved"], 1)
            self.assertEqual(payload["summary"]["predictions"], 1)

            second_payload = reconcile_prediction_results_for_date("2026-06-07", ledger_path=ledger_path, result_roots=[result_root])
            self.assertEqual(second_payload["summary"]["resolved"], 0)

            saved = ledger_path.read_text(encoding="utf-8")
            self.assertEqual(saved.count('"prediction_id": "pred-1"'), 1)

    def test_features_snapshot_pick_takes_priority_over_selection_text(self) -> None:
        # Confirmed live 2026-07-30: a straight prop bet's `selection` field
        # is the PLAYER'S NAME ("Troy Melton"), never the wagered Over/Under
        # side -- the bet-slip write-path fix stamps the real side into
        # features_snapshot.pick instead, and _row_outcome must prefer it
        # over parsing selection text (which would never contain "over"/
        # "under" for a straight prop bet in the first place).
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path = root / "prediction_ledger.json"
            result_root = root / "data"
            result_path = result_root / "mlb_source" / "reconciliation" / "props_actuals_2026-07-23.csv"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            with result_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sport", "market", "player", "selection", "actual", "line"])
                writer.writeheader()
                writer.writerow({"sport": "mlb", "market": "Pitcher Outs Recorded", "player": "Troy Melton", "selection": "Troy Melton", "actual": "19.0", "line": "17.5"})

            record_prediction(
                sport="mlb",
                market="Pitcher Outs Recorded",
                selection="Troy Melton",
                odds=-120,
                stake=50.0,
                features_snapshot={"pick": "Over", "line": 17.5},
                timestamp="2026-07-23T18:00:00Z",
                prediction_id="pred-pick",
                ledger_path=ledger_path,
            )

            payload = reconcile_prediction_results_for_date("2026-07-23", ledger_path=ledger_path, result_roots=[result_root])
            self.assertEqual(payload["summary"]["resolved"], 1)
            self.assertEqual(payload["predictions"][0]["result"]["outcome"], "win")

    def test_legacy_predictions_without_features_snapshot_pick_still_settle(self) -> None:
        # Predictions logged before the write-path fix have no
        # features_snapshot.pick at all -- the old selection-text heuristic
        # must keep working for them unchanged.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path = root / "prediction_ledger.json"
            result_root = root / "data"
            result_path = result_root / "nba_source" / "data" / "processed" / "recon_props_2026-06-08.csv"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            with result_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["player", "market", "actual", "line"])
                writer.writeheader()
                writer.writerow({"player": "Jane Doe", "market": "points", "actual": "24", "line": "20.5"})

            record_prediction(
                sport="nba",
                market="points",
                selection="Jane Doe over 20.5",
                odds=-110,
                timestamp="2026-06-08T12:00:00Z",
                prediction_id="pred-legacy",
                ledger_path=ledger_path,
            )

            payload = reconcile_prediction_results_for_date("2026-06-08", ledger_path=ledger_path, result_roots=[result_root])
            self.assertEqual(payload["summary"]["resolved"], 1)
            self.assertEqual(payload["predictions"][0]["result"]["outcome"], "win")


class PendingPredictionDatesTests(unittest.TestCase):
    def test_empty_ledger_returns_no_dates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "prediction_ledger.json"
            self.assertEqual(pending_prediction_dates(ledger_path=ledger_path), [])

    def test_settled_predictions_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "prediction_ledger.json"
            record_prediction(
                sport="mlb",
                market="hits",
                selection="Player A",
                timestamp="2026-06-01T12:00:00Z",
                prediction_id="settled-1",
                ledger_path=ledger_path,
            )
            record_result(prediction_id="settled-1", outcome="win", ledger_path=ledger_path)
            self.assertEqual(pending_prediction_dates(ledger_path=ledger_path), [])

    def test_mixed_ledger_returns_only_dates_with_a_pending_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "prediction_ledger.json"
            record_prediction(
                sport="mlb",
                market="hits",
                selection="Player A",
                timestamp="2026-06-01T12:00:00Z",
                prediction_id="settled-1",
                ledger_path=ledger_path,
            )
            record_result(prediction_id="settled-1", outcome="win", ledger_path=ledger_path)
            record_prediction(
                sport="mlb",
                market="outs",
                selection="Player B",
                timestamp="2026-06-02T12:00:00Z",
                prediction_id="pending-1",
                ledger_path=ledger_path,
            )
            record_prediction(
                sport="mlb",
                market="runs",
                selection="Player C",
                timestamp="2026-05-20T12:00:00Z",
                prediction_id="pending-2",
                ledger_path=ledger_path,
            )
            self.assertEqual(
                pending_prediction_dates(ledger_path=ledger_path),
                ["2026-05-20", "2026-06-02"],
            )
