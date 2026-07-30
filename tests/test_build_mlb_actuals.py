from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_mlb_actuals import build_mlb_actuals_for_date
from scripts.build_mlb_actuals import write_mlb_actuals_for_date
from syndicate.features.prediction_ledger import record_prediction
from syndicate.features.prediction_reconciliation import reconcile_prediction_results_for_date


FAKE_TOP_PROPS = {
    "groups": {
        "g1": {
            "sections": [
                {
                    "stat": "outs",
                    "label": "Outs Recorded",
                    "rows": [
                        {
                            "ownerName": "Test Pitcher",
                            "group": "pitcher",
                            "stat": "outs",
                            "statLabel": "Outs Recorded",
                            "gamePk": 999001,
                            "marketLine": 17.5,
                            "ownerId": 111,
                        }
                    ],
                },
                {
                    "stat": "hits_runs_rbis",
                    "label": "Hits + Runs + RBIs",
                    "rows": [
                        {
                            "ownerName": "Test Hitter",
                            "group": "hitter",
                            "stat": "hits_runs_rbis",
                            "statLabel": "Hits + Runs + RBIs",
                            "gamePk": 999001,
                            "marketLine": 1.5,
                            "ownerId": 222,
                        }
                    ],
                },
            ]
        }
    }
}

FAKE_FEED = {
    "liveData": {
        "boxscore": {
            "teams": {
                "away": {
                    "players": {
                        "ID111": {
                            "person": {"id": 111, "fullName": "Test Pitcher"},
                            "stats": {"pitching": {"inningsPitched": "6.1"}},
                        }
                    }
                },
                "home": {
                    "players": {
                        "ID222": {
                            "person": {"id": 222, "fullName": "Test Hitter"},
                            "stats": {"batting": {"hits": 2, "runs": 1, "rbi": 1}},
                        }
                    }
                },
            }
        }
    }
}


class BuildMlbActualsTests(unittest.TestCase):
    def test_resolves_pitcher_outs_and_combined_hitter_stat(self) -> None:
        with patch("scripts.build_mlb_actuals.load_json_file", return_value=FAKE_TOP_PROPS), patch(
            "scripts.build_mlb_actuals.load_final_feed", return_value=FAKE_FEED
        ):
            result = build_mlb_actuals_for_date("2026-07-23")

        self.assertEqual(result["summary"]["resolved"], 2)
        rows_by_player = {row["player"]: row for row in result["rows"]}
        self.assertEqual(rows_by_player["Test Pitcher"]["market"], "Pitcher Outs Recorded")
        self.assertEqual(rows_by_player["Test Pitcher"]["actual"], 19.0)  # 6.1 IP -> 6*3 + 1
        self.assertEqual(rows_by_player["Test Hitter"]["market"], "Hits + Runs + RBIs")
        self.assertEqual(rows_by_player["Test Hitter"]["actual"], 4.0)  # 2 hits + 1 run + 1 rbi

    def test_missing_feed_skips_the_row_rather_than_fabricating(self) -> None:
        with patch("scripts.build_mlb_actuals.load_json_file", return_value=FAKE_TOP_PROPS), patch(
            "scripts.build_mlb_actuals.load_final_feed", return_value=None
        ):
            result = build_mlb_actuals_for_date("2026-07-23")

        self.assertEqual(result["summary"]["resolved"], 0)
        self.assertEqual(result["summary"]["skipped_no_feed"], 2)
        self.assertEqual(result["rows"], [])

    def test_output_feeds_the_real_reconciliation_matcher_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_path = tmp_path / "prediction_ledger.json"

            with patch("scripts.build_mlb_actuals.load_json_file", return_value=FAKE_TOP_PROPS), patch(
                "scripts.build_mlb_actuals.load_final_feed", return_value=FAKE_FEED
            ):
                write_result = write_mlb_actuals_for_date("2026-07-23", output_root=tmp_path)

            output_path = Path(write_result["output_path"])
            self.assertTrue(output_path.name.endswith(".csv"))
            self.assertTrue(output_path.is_file())

            record_prediction(
                sport="mlb",
                market="Pitcher Outs Recorded",
                selection="Test Pitcher",
                odds=-120,
                stake=50.0,
                features_snapshot={"pick": "Over", "line": 17.5},
                timestamp="2026-07-23T18:00:00Z",
                ledger_path=ledger_path,
            )

            payload = reconcile_prediction_results_for_date("2026-07-23", ledger_path=ledger_path, result_roots=[tmp_path])
            self.assertEqual(payload["summary"]["resolved"], 1)
            self.assertEqual(payload["predictions"][0]["result"]["outcome"], "win")


if __name__ == "__main__":
    unittest.main()
