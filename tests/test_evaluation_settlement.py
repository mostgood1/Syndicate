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
                # total_recommendation_records/already_resolved_records exist so an
                # autorun cycle that settles nothing (e.g. everything already
                # resolved) is distinguishable from one where the ledger has no
                # records at all for that date -- both otherwise read as
                # pending=0/matched=0 from the status file alone.
                self.assertEqual(summary["total_recommendation_records"], 2)
                self.assertEqual(summary["already_resolved_records"], 0)

                records = _iter_record_payloads(ledger_path=ledger_path)
                settled_lookup = {r.get("recommendation_id"): r for r in records if r.get("record_type") == "recommendation"}
                self.assertEqual(settled_lookup[matched_rec["recommendation_id"]]["result"], "win")
                self.assertEqual(settled_lookup[unmatched_rec["recommendation_id"]]["result"], "pending")

                metrics = compute_metrics(ledger_path=ledger_path, sport="wnba")
                self.assertEqual(metrics["settled_count"], 1)

                # A second call against the same already-settled date reports
                # already_resolved_records=1 (the previously-settled record) and
                # pending=1 (the still-unmatched one) -- not pending=0 for
                # everything, which is what a broken/never-populated ledger
                # would also report.
                with patch.object(evaluation_settlement, "_graded_rows_for_date", return_value=fixture_rows):
                    second_summary = settle_ledger_for_date("2026-06-08", sport="wnba", ledger_path=ledger_path)
                self.assertEqual(second_summary["pending"], 1)
                self.assertEqual(second_summary["matched"], 0)
                self.assertEqual(second_summary["total_recommendation_records"], 2)
                self.assertEqual(second_summary["already_resolved_records"], 1)

    def test_settle_ledger_for_dates_totals_do_not_double_count_ledger_records_across_sports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
                self._make_pending_recommendation(
                    ledger_path,
                    sport="mlb",
                    recommendation={"market": "hitter_home_runs", "selection": "Over 0.5", "player": "Aaron Judge", "team": "NYY", "line": 0.5},
                )
                self._make_pending_recommendation(
                    ledger_path,
                    sport="wnba",
                    recommendation={"market": "total", "selection": "Over", "home": "Aces", "away": "Sky", "line": 165.5},
                )
                with patch.object(evaluation_settlement, "_graded_rows_for_date", return_value=[]):
                    result = evaluation_settlement.settle_ledger_for_dates(
                        ["2026-06-08"], sports=["mlb", "wnba"], ledger_path=ledger_path
                    )

                # Both settle_ledger_for_date calls read the SAME date-scoped
                # chunk file (one record per sport in it here), so summing a
                # sport-scoped counter across both calls must equal 2, not the
                # unfiltered per-call total_ledger_records (which would double
                # to 4 if summed the same way).
                self.assertEqual(result["totals"]["total_recommendation_records"], 2)

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
        # "Supported" is now driven by graded_outcomes.GRADED_OUTCOME_GRADERS
        # (has a registered grader) rather than a hardcoded allowlist, so a
        # sport with no grader at all (not one whose grader is a documented
        # []-returning stub, like soccer/ncaab -- those ARE registered and
        # take the empty-graded-rows path instead) is what exercises this.
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            summary = settle_ledger_for_date("2026-06-08", sport="esports", ledger_path=ledger_path)
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
