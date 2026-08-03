"""Evaluation-ledger bloat fixes (2026-08-02 end-to-end assessment).

Historical records embedded the FULL query response (board_contract cards,
recommendations, top_opportunities, parlays -- measured 479KB of a 512KB
record) plus every sport's full artifact manifest into every ledger record,
producing 2.0-2.7GB single-day chunk files that no consumer could safely
read. These tests pin the fixes: persist-time response slimming, the slim
manifest summary, the oversized-chunk read guard, and the compaction
script's line rewriter.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.compact_evaluation_ledger import _compact_record_line
from syndicate.features.shared import intelligence_evaluation


_HEAVY_RECORD = {
    "record_type": "recommendation",
    "recommendation_id": "reco_abc123",
    "recommendation": {"sport": "mlb", "market": "moneyline", "selection": "NYY ML", "line": None},
    "query": {"question": "top edges today", "selected_date": "2026-08-01"},
    "response": {
        "ok": True,
        "selected_date": "2026-08-01",
        "candidate_count": 42,
        "top_opportunities": [{"name": f"cand-{i}", "blob": "x" * 200} for i in range(20)],
        "recommendations": [{"name": f"cand-{i}"} for i in range(20)],
        "board_contract": {"cards": [{"title": f"card-{i}"} for i in range(20)]},
        "parlays": [{"legs": ["a", "b"]}],
    },
    "result": "pending",
}


class SlimResponseForPersistTests(unittest.TestCase):
    def test_persisted_response_keeps_provenance_only(self) -> None:
        slimmed = intelligence_evaluation._slim_record_response_for_persist(_HEAVY_RECORD)
        response = slimmed["response"]
        self.assertEqual(response["selected_date"], "2026-08-01")
        self.assertEqual(response["candidate_count"], 42)
        self.assertNotIn("top_opportunities", response)
        self.assertNotIn("board_contract", response)
        self.assertNotIn("recommendations", response)
        # The original record is not mutated, and the per-candidate data
        # settlement needs stays intact.
        self.assertIn("top_opportunities", _HEAVY_RECORD["response"])
        self.assertEqual(slimmed["recommendation"]["selection"], "NYY ML")

    def test_record_without_response_passes_through(self) -> None:
        record = {"record_type": "recommendation", "recommendation_id": "reco_x"}
        self.assertEqual(intelligence_evaluation._slim_record_response_for_persist(record), record)

    def test_append_writes_slimmed_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # A non-default path uses the flat (non-chunked) branch -- the
            # slimming must apply there too.
            ledger_path = Path(tmp) / "ledger.jsonl"
            intelligence_evaluation._append_evaluation_ledger_record(ledger_path, _HEAVY_RECORD)
            written = json.loads(ledger_path.read_text(encoding="utf-8").strip())
        self.assertNotIn("top_opportunities", written["response"])
        self.assertEqual(written["response"]["selected_date"], "2026-08-01")


class ArtifactManifestSummarySlimTests(unittest.TestCase):
    def test_summary_drops_per_artifact_lists(self) -> None:
        fake_manifest = type(
            "FakeManifest",
            (),
            {
                "to_dict": lambda self: {
                    "sport_slug": "mlb",
                    "selected_date": "2026-08-01",
                    "status": "complete",
                    "predictions": [{"path": f"p{i}"} for i in range(500)],
                    "edges": [{"path": f"e{i}"} for i in range(500)],
                    "counts": {"predictions": 500, "edges": 500, "recommendations": 0, "live_data": 0},
                },
            },
        )()
        with patch.object(intelligence_evaluation, "load_artifact_manifests", return_value=[fake_manifest]):
            summary = intelligence_evaluation._artifact_manifest_summary(selected_date="2026-08-01", sport="mlb")
        row = summary["sport_manifests"][0]
        self.assertEqual(row["sport_slug"], "mlb")
        self.assertEqual(row["counts"]["predictions"], 500)
        self.assertNotIn("predictions", row)
        self.assertNotIn("edges", row)


class OversizedChunkGuardTests(unittest.TestCase):
    def test_full_history_load_skips_oversized_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "ledger.jsonl"
            chunk_root = Path(tmp) / "ledger_chunks"
            chunk_root.mkdir()
            (chunk_root / "2026-08-01.jsonl").write_text(json.dumps({"record_id": "ok"}) + "\n", encoding="utf-8")
            (chunk_root / "2026-08-02.jsonl").write_text(json.dumps({"record_id": "huge", "blob": "x" * 4000}) + "\n", encoding="utf-8")
            with patch.object(intelligence_evaluation, "_ledger_max_chunk_bytes", return_value=1000):
                records = intelligence_evaluation._load_chunked_ledger_records(ledger_path)
        self.assertEqual([record["record_id"] for record in records], ["ok"])


class CompactRecordLineTests(unittest.TestCase):
    def test_heavy_record_line_is_rewritten(self) -> None:
        line = json.dumps(_HEAVY_RECORD)
        compacted, changed = _compact_record_line(line)
        self.assertTrue(changed)
        payload = json.loads(compacted)
        self.assertNotIn("top_opportunities", payload["response"])
        self.assertEqual(payload["response"]["selected_date"], "2026-08-01")
        self.assertEqual(payload["recommendation"]["selection"], "NYY ML")
        self.assertLess(len(compacted), len(line))

    def test_already_slim_record_round_trips_unchanged(self) -> None:
        record = {
            "record_type": "recommendation",
            "recommendation_id": "reco_x",
            "response": {"selected_date": "2026-08-01", "ok": True},
        }
        line = json.dumps(record)
        compacted, changed = _compact_record_line(line)
        self.assertFalse(changed)
        self.assertEqual(compacted, line)

    def test_unparseable_line_passes_through(self) -> None:
        line = "{not json"
        compacted, changed = _compact_record_line(line)
        self.assertFalse(changed)
        self.assertEqual(compacted, line)

    def test_nested_prediction_and_raw_containers_are_slimmed(self) -> None:
        # Bundle-shaped rows nest a full record under "prediction", and
        # RecommendationRecord stashes raw={"prediction": ...} -- confirmed
        # 2026-08-02: after top-level slimming alone, a record still carried
        # a 1.5MB nested prediction subtree.
        record = {
            "record_type": "recommendation",
            "recommendation_id": "reco_nested",
            "prediction": {
                "response": dict(_HEAVY_RECORD["response"]),
                "artifact_metadata": {
                    "sport": "mlb",
                    "manifest_summary": {
                        "sport_manifests": [
                            {"sport_slug": "mlb", "predictions": [{"path": f"p{i}"} for i in range(50)]}
                        ]
                    },
                },
            },
            "raw": {"prediction": {"response": dict(_HEAVY_RECORD["response"])}},
            "recommendations": [{"response": dict(_HEAVY_RECORD["response"])}],
        }
        line = json.dumps(record)
        compacted, changed = _compact_record_line(line)
        self.assertTrue(changed)
        payload = json.loads(compacted)
        self.assertNotIn("top_opportunities", payload["prediction"]["response"])
        self.assertNotIn("predictions", payload["prediction"]["artifact_metadata"]["manifest_summary"]["sport_manifests"][0])
        self.assertNotIn("top_opportunities", payload["raw"]["prediction"]["response"])
        self.assertNotIn("top_opportunities", payload["recommendations"][0]["response"])


if __name__ == "__main__":
    unittest.main()
