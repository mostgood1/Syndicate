from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared.odds_lifecycle import _candidate_market_id
from syndicate.features.shared.odds_lifecycle import _resolve_market_state_across_shards
from syndicate.features.shared.odds_lifecycle import build_market_features
from syndicate.features.shared.odds_lifecycle import build_market_history_view


def _write_shard(root: Path, *, sport: str, shard_key: str, market_id: str, history: list[dict]) -> None:
    path = root / "odds_control_plane" / "odds_history" / sport / f"{shard_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "sport": sport,
        "shard_key": shard_key,
        "markets": {market_id: {"history": history, "last_line": history[-1]["current_line"] if history else None}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class OddsLifecycleShardMergeTests(unittest.TestCase):
    def test_resolve_market_state_across_shards_merges_opening_and_closing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False
        ):
            reports_root = Path(tmp_dir) / "reports"
            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-07",
                market_id="market-x",
                history=[{"current_line": -3.0, "captured_at": "2026-06-07T10:00:00Z", "event_type": "open"}],
            )
            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-08",
                market_id="market-x",
                history=[{"current_line": -3.5, "captured_at": "2026-06-08T18:00:00Z", "event_type": "close"}],
            )

            merged = _resolve_market_state_across_shards(sport="mlb", market_id="market-x", shard_key="2026-06-08", shard_lookback=1)
            self.assertIsNotNone(merged)
            history = merged["history"]
            self.assertEqual(len(history), 2)
            self.assertEqual({entry["event_type"] for entry in history}, {"open", "close"})

            no_lookback = _resolve_market_state_across_shards(sport="mlb", market_id="market-x", shard_key="2026-06-08", shard_lookback=0)
            self.assertEqual(len(no_lookback["history"]), 1)
            self.assertEqual(no_lookback["history"][0]["event_type"], "close")

    def test_build_market_history_view_uses_candidate_date_to_merge_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False
        ):
            reports_root = Path(tmp_dir) / "reports"
            candidate = {
                "sport": "mlb",
                "event_id": "Away@Home",
                "market_type": "spread",
                "entity": "Home",
                "line": -3.5,
                "date": "2026-06-08",
            }
            market_id = _candidate_market_id(candidate, sport="mlb")
            self.assertIsNotNone(market_id)

            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-07",
                market_id=market_id,
                history=[{"current_line": -3.0, "captured_at": "2026-06-07T10:00:00Z", "event_type": "open"}],
            )
            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-08",
                market_id=market_id,
                history=[{"current_line": -3.5, "captured_at": "2026-06-08T18:00:00Z", "event_type": "close"}],
            )

            view = build_market_history_view(candidate, sport="mlb")
            self.assertEqual(view["opening_line"], -3.0)
            self.assertEqual(view["closing_line"], -3.5)
            self.assertEqual(view["history_points"], 2)

            features = build_market_features(candidate, sport="mlb")
            self.assertEqual(features["opening_line"], -3.0)
            self.assertEqual(features["closing_line"], -3.5)


if __name__ == "__main__":
    unittest.main()
