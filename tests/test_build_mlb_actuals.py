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


# ---------------------------------------------------------------------------
# `#639`: the writer must not destroy a real artifact.
#
# It used to open its output `"w"` before knowing whether there were any rows,
# so a zero-row result truncated `props_actuals_<date>.csv` to a bare header.
# Hourly, over a lookback window, that destroyed the graded actuals for every
# date whose `daily_top_props` input had aged off the worker's disk -- 7 of the
# 12 dates in the window on 2026-09-02, while a local replay of one of them on
# production's own bytes produced 1,123 resolved rows.
#
# These pin the DISTINCTION, not just the fix: "input absent" and "input
# present, graded to zero" must stay separable, or the fix only moves the
# 403-vs-404 collapse somewhere new.
# ---------------------------------------------------------------------------

DATE = "2026-06-15"
EXISTING_ROWS = "sport,market,player,selection,actual,line" + chr(10) + "mlb,Strikeouts,A,A,7,5.5" + chr(10)


class ActualsWriterDoesNotDestroyTests(unittest.TestCase):
    def _tree(self, tmp_path: Path) -> Path:
        output = tmp_path / "mlb_source" / "reconciliation" / f"props_actuals_{DATE}.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(EXISTING_ROWS, encoding="utf-8")
        return output

    def test_absent_input_refuses_and_leaves_the_existing_file_untouched(self) -> None:
        """THE REGRESSION. Before the fix this truncated the file to a header."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output = self._tree(tmp_path)
            before = output.read_bytes()

            with patch("scripts.build_mlb_actuals.load_json_file", return_value=None):
                result = write_mlb_actuals_for_date(DATE, output_root=tmp_path)

            self.assertFalse(result["written"])
            self.assertEqual(result["skipped_reason"], "input_absent")
            self.assertFalse(result["summary"]["top_props_present"])
            self.assertEqual(output.read_bytes(), before)

    def test_present_but_unreadable_is_its_own_reason(self) -> None:
        """Present-but-corrupt is a third fact and gets its own token."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output = self._tree(tmp_path)
            before = output.read_bytes()
            corrupt = tmp_path / "top_props.json"
            corrupt.write_text("{not json", encoding="utf-8")

            with patch("scripts.build_mlb_actuals.load_json_file", return_value=None), patch(
                "scripts.build_mlb_actuals.daily_top_props_path", return_value=corrupt
            ):
                result = write_mlb_actuals_for_date(DATE, output_root=tmp_path)

            self.assertEqual(result["skipped_reason"], "input_unreadable")
            self.assertTrue(result["summary"]["top_props_present"])
            self.assertFalse(result["summary"]["top_props_readable"])
            self.assertEqual(output.read_bytes(), before)

    def test_present_input_with_zero_rows_refuses_to_overwrite_a_real_file(self) -> None:
        """The same destruction by another route: the input is there and grades
        to nothing, but an existing non-empty answer must not be replaced."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output = self._tree(tmp_path)
            before = output.read_bytes()

            with patch("scripts.build_mlb_actuals.load_json_file", return_value={"groups": {}}):
                result = write_mlb_actuals_for_date(DATE, output_root=tmp_path)

            self.assertFalse(result["written"])
            self.assertEqual(result["skipped_reason"], "refused_empty_overwrite")
            self.assertTrue(result["summary"]["top_props_present"])
            self.assertEqual(result["summary"]["top_props_rows"], 0)
            self.assertEqual(output.read_bytes(), before)

    def test_the_override_is_available_and_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output = self._tree(tmp_path)

            with patch("scripts.build_mlb_actuals.load_json_file", return_value={"groups": {}}):
                result = write_mlb_actuals_for_date(DATE, output_root=tmp_path, allow_empty_overwrite=True)

            self.assertTrue(result["written"])
            self.assertNotIn("Strikeouts", output.read_text(encoding="utf-8"))

    def test_zero_rows_still_writes_when_there_is_nothing_to_destroy(self) -> None:
        """The guard protects an EXISTING answer. With no prior file an empty
        result is legitimate to record -- refusing here would make a quiet day
        indistinguishable from a broken one in the other direction."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch("scripts.build_mlb_actuals.load_json_file", return_value={"groups": {}}):
                result = write_mlb_actuals_for_date(DATE, output_root=tmp_path)

            self.assertTrue(result["written"])
            self.assertIsNone(result["skipped_reason"])
            self.assertTrue(Path(result["output_path"]).is_file())

    def test_a_refusal_does_not_create_the_output_directory(self) -> None:
        """A refusal that still touches the path is not a refusal."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch("scripts.build_mlb_actuals.load_json_file", return_value=None):
                result = write_mlb_actuals_for_date(DATE, output_root=tmp_path)

            self.assertEqual(result["skipped_reason"], "input_absent")
            self.assertFalse((tmp_path / "mlb_source" / "reconciliation").exists())

    def test_the_summary_stays_small_enough_to_survive_log_truncation(self) -> None:
        """The worker logs this dict for ~12 dates and the Render logs API
        truncates the message at ~1,200 chars -- reading the visible prefix of
        that truncated line is how `#639` was first mis-diagnosed."""
        import json as _json

        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.build_mlb_actuals.load_json_file", return_value=FAKE_TOP_PROPS), patch(
                "scripts.build_mlb_actuals.load_final_feed", return_value=FAKE_FEED
            ):
                result = write_mlb_actuals_for_date(DATE, output_root=Path(tmp))

        encoded = _json.dumps(result["summary"], sort_keys=True)
        self.assertLess(len(encoded), 240, "a 12-date tick must stay readable before truncation")
        self.assertNotIn("/", encoded, "no paths in the per-date summary")


if __name__ == "__main__":
    unittest.main()
