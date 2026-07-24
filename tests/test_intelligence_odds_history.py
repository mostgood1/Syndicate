from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.intelligence import _build_odds_history_player_index
from syndicate.features.intelligence import _candidate_odds_history_context
from syndicate.features.intelligence import _enrich_candidates_with_odds_history
from syndicate.features.intelligence import _load_odds_history_payload_for_sport
from syndicate.features.intelligence import build_pick_card_view
from syndicate.features.intelligence import score_candidate
from syndicate.features.shared import refresh_state_store


class IntelligenceOddsHistoryTests(unittest.TestCase):
    def test_mlb_odds_history_prefers_shared_control_plane_history(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ",
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            shared_history_path = Path(tmp_dir) / "reports" / "odds_control_plane" / "odds_history" / "mlb" / "2026-07-05.json"
            shared_history_path.parent.mkdir(parents=True, exist_ok=True)
            refresh_state_store.write_json_file(
                shared_history_path,
                {
                    "date": "2026-07-05",
                    "history_limit": 50,
                    "markets": {
                        "home_team=Home|away_team=Away|market=h2h|bookmaker=draftkings": {
                            "last_line": -140.0,
                            "previous_line": -140.0,
                            "delta": 0.0,
                            "movement": "flat",
                            "history": [],
                        }
                    },
                },
            )

            payload = _load_odds_history_payload_for_sport("mlb", "2026-07-05")

        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("date"), "2026-07-05")
        self.assertIn("markets", payload)

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
        movement_context = _candidate_odds_history_context(enriched, _build_odds_history_player_index(odds_history))
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
