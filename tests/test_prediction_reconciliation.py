from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from syndicate.features.prediction_ledger import record_prediction
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
