"""Board publication: price gate + adjusted-score ranking wiring.

Covers the 2026-08-02 fixes: (1) unpriced candidates are flagged and never
occupy top_opportunities slots (confirmed live: 12 NFL cards published with
odds/edge/EV all blank); (2) recommendation_engine.rank_recommendations'
adjusted_score is attached during the pool build and preferred by the
ranking key -- before this the sophisticated ranker had zero production
callers and the served board ranked on edge x confidence alone; (3) the
evaluation-record load feeding the ranker is windowed and skips oversized
chunk files (the historical ledger contains multi-GB chunks).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from pipeline.intelligence_state import IntelligenceStateService
from pipeline.intelligence_state import _candidate_has_price
from syndicate.features.intelligence import _candidate_betting_rank_key
from syndicate.features.shared import intelligence_evaluation


class CandidateHasPriceTests(unittest.TestCase):
    def test_numeric_odds_are_priced(self) -> None:
        self.assertTrue(_candidate_has_price({"odds": -110}))
        self.assertTrue(_candidate_has_price({"odds": 145.0}))

    def test_text_odds_are_priced(self) -> None:
        self.assertTrue(_candidate_has_price({"odds": "-110"}))
        self.assertTrue(_candidate_has_price({"odds": "+225"}))

    def test_placeholder_odds_are_unpriced(self) -> None:
        self.assertFalse(_candidate_has_price({"odds": "-"}))
        self.assertFalse(_candidate_has_price({"odds": ""}))
        self.assertFalse(_candidate_has_price({"odds": None}))
        self.assertFalse(_candidate_has_price({}))
        self.assertFalse(_candidate_has_price({"odds": True}))


class RankKeyPrefersAdjustedScoreTests(unittest.TestCase):
    def test_adjusted_score_outranks_bare_score(self) -> None:
        weaker = {"score": 10.0, "adjusted_score": 1.0, "confidence": 0.6}
        stronger = {"score": 5.0, "adjusted_score": 8.0, "confidence": 0.6}
        ordered = sorted([weaker, stronger], key=_candidate_betting_rank_key, reverse=True)
        self.assertIs(ordered[0], stronger)

    def test_missing_adjusted_score_falls_back_to_score(self) -> None:
        high_score = {"score": 9.0, "confidence": 0.6}
        low_score = {"score": 2.0, "confidence": 0.6}
        ordered = sorted([low_score, high_score], key=_candidate_betting_rank_key, reverse=True)
        self.assertIs(ordered[0], high_score)


class LoadRecentEvaluationRecordsTests(unittest.TestCase):
    def test_windowed_read_skips_oversized_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "evaluation_ledger.jsonl"
            chunk_root = Path(tmp) / "evaluation_ledger_chunks"
            chunk_root.mkdir()
            today = date.today()
            recent_token = (today - timedelta(days=1)).isoformat()
            oversized_token = (today - timedelta(days=2)).isoformat()
            stale_token = (today - timedelta(days=45)).isoformat()
            (chunk_root / f"{recent_token}.jsonl").write_text(
                json.dumps({"record_id": "small-1"}) + "\n" + json.dumps({"record_id": "small-2"}) + "\n",
                encoding="utf-8",
            )
            # "Oversized" relative to the tiny ceiling passed below -- stands
            # in for the real multi-GB chunks.
            (chunk_root / f"{oversized_token}.jsonl").write_text(
                json.dumps({"record_id": "huge", "payload": "x" * 500}) + "\n",
                encoding="utf-8",
            )
            (chunk_root / f"{stale_token}.jsonl").write_text(
                json.dumps({"record_id": "stale"}) + "\n",
                encoding="utf-8",
            )
            with patch.object(intelligence_evaluation, "_is_chunked_ledger_path", return_value=True):
                records = intelligence_evaluation.load_recent_evaluation_records(
                    days=14, ledger_path=ledger_path, max_chunk_bytes=200
                )
        record_ids = sorted(record.get("record_id") for record in records)
        self.assertEqual(record_ids, ["small-1", "small-2"])


class AttachAdjustedScoresTests(unittest.TestCase):
    def test_scores_merge_back_by_candidate_id(self) -> None:
        pool = [
            {"candidate_id": "a", "score": 4.0, "odds": "-110"},
            {"candidate_id": "b", "score": 6.0, "odds": "+120"},
            {"candidate_id": "c", "score": 2.0, "odds": "-105"},
        ]
        ranked_rows = [
            {"candidate_id": "a", "adjusted_score": 12.5, "decision_strategy": "balanced", "performance_multiplier": 1.0},
            {"candidate_id": "b", "adjusted_score": 3.25, "decision_strategy": "balanced", "performance_multiplier": 1.0},
            # "c" dropped by the internal filter -- must stay un-annotated.
        ]
        with patch("syndicate.features.intelligence.rank_candidates", return_value=ranked_rows), patch(
            "syndicate.features.shared.intelligence_evaluation.load_recent_evaluation_records", return_value=[]
        ):
            IntelligenceStateService._attach_adjusted_scores(pool)
        self.assertEqual(pool[0]["adjusted_score"], 12.5)
        self.assertEqual(pool[1]["adjusted_score"], 3.25)
        self.assertNotIn("adjusted_score", pool[2])
        # Annotation only: original fields untouched.
        self.assertEqual(pool[0]["score"], 4.0)
        self.assertEqual(pool[0]["odds"], "-110")

    def test_failure_is_swallowed(self) -> None:
        pool = [{"candidate_id": "a", "score": 4.0}]
        with patch(
            "syndicate.features.intelligence.rank_candidates", side_effect=RuntimeError("boom")
        ), patch(
            "syndicate.features.shared.intelligence_evaluation.load_recent_evaluation_records", return_value=[]
        ):
            IntelligenceStateService._attach_adjusted_scores(pool)
        self.assertNotIn("adjusted_score", pool[0])

    def test_rejected_candidates_are_forwarded_to_the_shadow_ledger(self) -> None:
        # 2026-08-04 (learning-loop Stage 2's deferred other half): this is
        # the one place on the live board-build path that sees both halves
        # of a ranking pass in the same call, so it's the natural hook for
        # shadow-recording what filter_candidates turned away.
        pool = [{"candidate_id": "a", "score": 4.0, "odds": "-110"}]

        def fake_rank_candidates(candidates, *, evaluation_records=None, rejected_sink=None):
            if rejected_sink is not None:
                rejected_sink.append({"candidate_id": "rejected-1", "sport_slug": "mlb", "_shadow_rejection_reason": "edge_below_threshold"})
            return []

        with patch("syndicate.features.intelligence.rank_candidates", side_effect=fake_rank_candidates), patch(
            "syndicate.features.shared.intelligence_evaluation.load_recent_evaluation_records", return_value=[]
        ), patch("syndicate.features.shared.shadow_candidate_ledger.record_shadow_candidates") as mocked_record:
            mocked_record.return_value = {"ok": True, "skipped": False, "sampled": 1}
            IntelligenceStateService._attach_adjusted_scores(pool, "2026-08-04")

        mocked_record.assert_called_once()
        call_args, call_kwargs = mocked_record.call_args
        self.assertEqual(call_args[0][0]["candidate_id"], "rejected-1")
        self.assertEqual(call_kwargs["selected_date"], "2026-08-04")

    def test_no_rejected_candidates_never_calls_the_shadow_ledger(self) -> None:
        pool = [{"candidate_id": "a", "score": 4.0}]
        with patch(
            "syndicate.features.intelligence.rank_candidates", return_value=[]
        ), patch(
            "syndicate.features.shared.intelligence_evaluation.load_recent_evaluation_records", return_value=[]
        ), patch("syndicate.features.shared.shadow_candidate_ledger.record_shadow_candidates") as mocked_record:
            IntelligenceStateService._attach_adjusted_scores(pool, "2026-08-04")
        mocked_record.assert_not_called()

    def test_shadow_ledger_failure_does_not_break_score_attachment(self) -> None:
        pool = [{"candidate_id": "a", "score": 4.0}]

        def fake_rank_candidates(candidates, *, evaluation_records=None, rejected_sink=None):
            if rejected_sink is not None:
                rejected_sink.append({"candidate_id": "rejected-1", "sport_slug": "mlb"})
            return [{"candidate_id": "a", "adjusted_score": 9.0}]

        with patch("syndicate.features.intelligence.rank_candidates", side_effect=fake_rank_candidates), patch(
            "syndicate.features.shared.intelligence_evaluation.load_recent_evaluation_records", return_value=[]
        ), patch(
            "syndicate.features.shared.shadow_candidate_ledger.record_shadow_candidates",
            side_effect=RuntimeError("boom"),
        ):
            IntelligenceStateService._attach_adjusted_scores(pool, "2026-08-04")
        self.assertEqual(pool[0]["adjusted_score"], 9.0)


if __name__ == "__main__":
    unittest.main()
