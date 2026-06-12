from __future__ import annotations

import unittest

from syndicate.features.shared.odds_framework import normalize_odds_entry
from syndicate.features.shared.odds_framework import rank_normalized_odds_entries


class OddsFrameworkTests(unittest.TestCase):
    def test_normalize_odds_entry_uses_shared_schema(self) -> None:
        entry = normalize_odds_entry(
            row={
                "event_id": "game-1",
                "market": "total",
                "selection": "over",
                "line": 7.0,
                "odds": -110,
                "model_probability": 0.58,
                "market_probability": 0.50,
                "confidence": 0.72,
            },
            sport="nhl",
            market_key="event_id=game-1|market=total|selection=over",
            timestamp="2026-06-11T12:00:00Z",
            source_path="data/nhl_source/tracking/odds_history.json",
        )

        self.assertEqual(entry["schema_version"], 1)
        self.assertEqual(entry["sport"], "nhl")
        self.assertEqual(entry["event_id"], "game-1")
        self.assertAlmostEqual(entry["edge"], 0.08, places=6)
        self.assertAlmostEqual(entry["confidence"], 0.72, places=6)
        self.assertAlmostEqual(entry["rank_score"], 0.0896, places=6)
        self.assertEqual(entry["timestamp"], "2026-06-11T12:00:00Z")

    def test_rank_normalized_odds_entries_orders_best_first(self) -> None:
        ranked = rank_normalized_odds_entries(
            [
                {"market_key": "a", "edge": 0.03, "confidence": 0.4, "rank_score": 0.042},
                {"market_key": "b", "edge": 0.09, "confidence": 0.6, "rank_score": 0.144},
                {"market_key": "c", "edge": 0.05, "confidence": 0.9, "rank_score": 0.095},
            ]
        )

        self.assertEqual([item["market_key"] for item in ranked], ["b", "c", "a"])
        self.assertEqual([item["rank"] for item in ranked], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()