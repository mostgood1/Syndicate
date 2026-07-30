from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import syndicate.features.shared.intelligence_evaluation as intelligence_evaluation
from syndicate.features.shared.intelligence_evaluation import _iter_record_payloads
from syndicate.features.shared.intelligence_evaluation import compute_metrics
from syndicate.features.shared.intelligence_evaluation import record_prediction
from syndicate.features.shared.intelligence_evaluation import record_recommendation

import syndicate.features.shared.evaluation_settlement as evaluation_settlement
from syndicate.features.shared.evaluation_settlement import match_graded_row
from syndicate.features.shared.evaluation_settlement import settle_ledger_for_date


class MatchGradedRowTests(unittest.TestCase):
    def test_matches_on_shared_tokens_and_agreeing_market(self) -> None:
        record = {
            "recommendation": {
                "market": "hitter_home_runs",
                "selection": "Over 0.5",
                "player": "Aaron Judge",
                "team": "NYY",
                "line": 0.5,
            }
        }
        rows = [
            {"market": "hitter_hits", "selection": "Over 1.5", "player": "Aaron Judge", "team": "NYY", "line": 1.5, "result": "loss"},
            {"market": "hitter_home_runs", "selection": "Over 0.5", "player": "Aaron Judge", "team": "NYY", "line": 0.5, "result": "win"},
        ]
        matched = match_graded_row(record, rows)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["result"], "win")

    def test_market_mismatch_is_skipped(self) -> None:
        record = {"recommendation": {"market": "totals", "selection": "Over", "home": "Aces", "away": "Sky", "line": 165.5}}
        rows = [
            {"market": "ml", "selection": "Aces", "home": "Aces", "away": "Sky", "line": None, "result": "win"},
            {"market": "total", "selection": "Over", "home": "Aces", "away": "Sky", "line": 165.5, "result": "win"},
        ]
        matched = match_graded_row(record, rows)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["market"], "total")

    def test_no_shared_tokens_returns_none(self) -> None:
        record = {"recommendation": {"market": "totals", "selection": "Over", "home": "Aces", "away": "Sky", "line": 165.5}}
        rows = [{"market": "total", "selection": "Under", "home": "Liberty", "away": "Mercury", "line": 150.0, "result": "win"}]
        self.assertIsNone(match_graded_row(record, rows))


class SettleLedgerForDateTests(unittest.TestCase):
    def _make_pending_recommendation(self, ledger_path: Path, *, sport: str, recommendation: dict) -> dict:
        prediction = record_prediction(
            query={"question": f"{sport} test", "selected_date": "2026-06-08", "sport": sport},
            response={"selected_date": "2026-06-08", "recommendations": []},
            persist=True,
            ledger_path=ledger_path,
        )
        return record_recommendation(
            prediction_record=prediction,
            recommendation=recommendation,
            persist=True,
            ledger_path=ledger_path,
        )

    def test_settles_matched_pending_records_and_leaves_unmatched_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
                matched_rec = self._make_pending_recommendation(
                    ledger_path,
                    sport="wnba",
                    recommendation={"market": "total", "selection": "Over", "home": "Aces", "away": "Sky", "line": 165.5, "model_probability": 0.58},
                )
                unmatched_rec = self._make_pending_recommendation(
                    ledger_path,
                    sport="wnba",
                    recommendation={"market": "total", "selection": "Over", "home": "Liberty", "away": "Mercury", "line": 158.0, "model_probability": 0.55},
                )

                fixture_rows = [
                    {"sport": "wnba", "market": "total", "selection": "Over", "home": "Aces", "away": "Sky", "line": 165.5, "actual": 171.0, "odds": -110, "result": "win"},
                ]
                with patch.object(evaluation_settlement, "_graded_rows_for_date", return_value=fixture_rows):
                    summary = settle_ledger_for_date("2026-06-08", sport="wnba", ledger_path=ledger_path)

                self.assertEqual(summary["pending"], 2)
                self.assertEqual(summary["matched"], 1)
                self.assertEqual(summary["settled"], 1)
                self.assertEqual(summary["unmatched"], 1)

                records = _iter_record_payloads(ledger_path=ledger_path)
                settled_lookup = {r.get("recommendation_id"): r for r in records if r.get("record_type") == "recommendation"}
                self.assertEqual(settled_lookup[matched_rec["recommendation_id"]]["result"], "win")
                self.assertEqual(settled_lookup[unmatched_rec["recommendation_id"]]["result"], "pending")

                metrics = compute_metrics(ledger_path=ledger_path, sport="wnba")
                self.assertEqual(metrics["settled_count"], 1)

    def test_dry_run_reports_matches_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
                self._make_pending_recommendation(
                    ledger_path,
                    sport="mlb",
                    recommendation={"market": "hitter_home_runs", "selection": "Over 0.5", "player": "Aaron Judge", "team": "NYY", "line": 0.5},
                )
                fixture_rows = [
                    {"sport": "mlb", "market": "hitter_home_runs", "selection": "Over 0.5", "player": "Aaron Judge", "team": "NYY", "line": 0.5, "odds": "-120", "result": "win"},
                ]
                with patch.object(evaluation_settlement, "_graded_rows_for_date", return_value=fixture_rows):
                    summary = settle_ledger_for_date("2026-06-08", sport="mlb", ledger_path=ledger_path, dry_run=True)

                self.assertEqual(summary["matched"], 1)
                self.assertEqual(summary["settled"], 0)
                self.assertEqual(summary["would_settle"], 1)

                records = _iter_record_payloads(ledger_path=ledger_path)
                recommendation_records = [r for r in records if r.get("record_type") == "recommendation"]
                self.assertEqual(recommendation_records[0]["result"], "pending")

    def test_unsupported_sport_is_a_safe_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            summary = settle_ledger_for_date("2026-06-08", sport="nhl", ledger_path=ledger_path)
            self.assertEqual(summary["pending"], 0)
            self.assertIn("note", summary)

    def test_no_chunk_file_for_date_is_a_safe_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            summary = settle_ledger_for_date("2026-01-01", sport="mlb", ledger_path=ledger_path)
            self.assertEqual(summary["pending"], 0)
            self.assertEqual(summary["settled"], 0)


if __name__ == "__main__":
    unittest.main()
