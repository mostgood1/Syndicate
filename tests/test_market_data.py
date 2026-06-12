from __future__ import annotations

import unittest

from syndicate.features.market_data import build_market_data


class MarketDataTests(unittest.TestCase):
    def test_build_market_data_prefers_odds_history(self) -> None:
        payload = build_market_data(
            {
                "opening_line": 6.5,
                "current_line": 7.0,
                "odds_history": {
                    "history": [
                        {"timestamp": "2026-06-11T12:00:00Z", "line": 6.5, "movement": "flat", "source_path": "a.json"},
                        {"timestamp": "2026-06-11T13:00:00Z", "line": 7.0, "movement": "up", "source_path": "b.json"},
                    ]
                },
            }
        )

        self.assertEqual(payload["opening_line"], 6.5)
        self.assertEqual(payload["current_line"], 7.0)
        self.assertEqual(len(payload["movement_history"]), 2)
        self.assertEqual(payload["movement_history"][1]["movement"], "up")
        self.assertEqual(payload["movement_history"][1]["timestamp"], "2026-06-11T13:00:00Z")


if __name__ == "__main__":
    unittest.main()