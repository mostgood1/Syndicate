from __future__ import annotations

import unittest

from syndicate.features.intelligence import _candidate_odds_history_context
from syndicate.features.intelligence import _enrich_candidates_with_odds_history
from syndicate.features.intelligence import build_pick_card_view
from syndicate.features.intelligence import score_candidate


class IntelligenceOddsHistoryTests(unittest.TestCase):
    def test_candidate_movement_is_attached_and_rendered(self) -> None:
        candidate = {
            "sport_slug": "nhl",
            "sport": "NHL",
            "matchup": "Away @ Home",
            "market": "Total",
            "pick": "Over 6.5",
            "name": "Away @ Home Over 6.5",
            "line": 7.0,
            "odds": "-110",
            "market_data": {"opening_line": 6.5, "current_line": 7.0, "movement_history": []},
        }
        odds_history = {
            "markets": {
                "matchup=Away @ Home|market=total|selection=over": {
                    "last_line": 7.0,
                    "previous_line": 6.5,
                    "delta": 0.5,
                    "movement": "up",
                    "percent_change": 7.6923076923,
                    "last_updated": "2026-06-11T12:00:00Z",
                    "history": [
                        {"current_line": 6.5, "movement": "flat"},
                        {"current_line": 7.0, "movement": "up"},
                    ],
                }
            }
        }

        enriched = _enrich_candidates_with_odds_history([candidate], {"nhl": odds_history})[0]
        movement_context = _candidate_odds_history_context(enriched, odds_history)
        self.assertEqual(movement_context["trend"], "up")
        self.assertEqual(movement_context["delta"], 0.5)
        self.assertEqual(movement_context["recent_movement_trend"], "up")
        self.assertAlmostEqual(movement_context["percent_change"], 7.6923076923, places=6)
        self.assertEqual(movement_context["last_updated"], "2026-06-11T12:00:00Z")

        self.assertEqual(enriched["movement"]["trend"], "up")
        self.assertEqual(enriched["movement"]["delta"], 0.5)
        self.assertEqual(enriched["movement"]["recent_movement_trend"], "up")
        self.assertAlmostEqual(enriched["movement"]["percent_change"], 7.6923076923, places=6)
        self.assertEqual(enriched["last_updated"], "2026-06-11T12:00:00Z")

        scored = score_candidate(enriched, preferences={})

        self.assertIn("movement", scored)
        self.assertEqual(scored["movement"]["delta"], 0.5)
        self.assertEqual(scored["movement"]["trend"], "up")

        card = build_pick_card_view(scored)
        self.assertEqual(card["movement"]["trend"], "up")
        self.assertEqual(card["movement"]["delta_display"], "+0.5")
        self.assertEqual(card["movement"]["last_updated"], "2026-06-11T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
