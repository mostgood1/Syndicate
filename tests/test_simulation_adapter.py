from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.shared.simulation_adapter import SPORT_ADAPTERS
from syndicate.features.shared.simulation_adapter import build_unified_simulation_adapter


class UnifiedSimulationAdapterTests(unittest.TestCase):
    def test_all_registered_sports_normalize_to_shared_shape(self) -> None:
        fake_context = {
            "date": "2026-06-22",
            "requested_date": "2026-06-22",
            "source_title": "Fake source title",
            "source_path": "/tmp/fake-source",
            "lookahead_applied": False,
            "games": [
                {
                    "gamePk": "game-1",
                    "event_id": "401000001",
                    "away_tri": "AWY",
                    "home_tri": "HME",
                    "away": {"abbr": "AWY", "score": 101},
                    "home": {"abbr": "HME", "score": 103},
                    "status": "Scheduled",
                    "detail": "Scheduled",
                    "summary": "Example game",
                    "betting": {"market": "spread", "edge": 0.12},
                    "sim": {
                        "score": {"away_mean": 100.5, "home_mean": 104.5},
                        "players": {"home": [{"player": "Home Player", "pts_mean": 21.2}], "away": [{"player": "Away Player", "pts_mean": 19.8}]},
                    },
                    "live_state": {"status": "Scheduled", "final": False},
                }
            ],
        }

        for sport in SPORT_ADAPTERS:
            with self.subTest(sport=sport), patch.dict(
                "syndicate.features.shared.simulation_adapter.SPORT_ADAPTERS",
                {sport: lambda *args, **kwargs: fake_context},
                clear=False,
            ):
                selection = 3 if sport in {"nfl", "ncaaf"} else "2026-06-22"
                payload = build_unified_simulation_adapter(sport, selection, season=2026)

            self.assertEqual(payload["sport"], sport)
            self.assertEqual(payload["game_count"], 1)
            self.assertEqual(payload["selection"]["kind"], "week" if sport in {"nfl", "ncaaf"} else "date")
            self.assertEqual(payload["games"][0]["game_id"], "game-1")
            self.assertEqual(payload["games"][0]["event_id"], "401000001")
            self.assertIn("engine_context", payload["games"][0])
            self.assertIn("source_paths", payload)

    def test_adapter_uses_current_day_freshness_for_date_sports(self) -> None:
        fake_context = {
            "date": "2026-06-22",
            "requested_date": "2026-06-22",
            "source_title": "WNBA live scoreboard supplement",
            "games": [],
        }

        with patch.dict(
            "syndicate.features.shared.simulation_adapter.SPORT_ADAPTERS",
            {"wnba": lambda *args, **kwargs: fake_context},
            clear=False,
        ), patch("syndicate.features.shared.simulation_adapter.central_today_iso", return_value="2026-06-22"):
            payload = build_unified_simulation_adapter("wnba", "2026-06-22")

        self.assertTrue(payload["freshness"]["is_current_day"])
        self.assertEqual(payload["source_mode"], "live_supplement")

    def test_mlb_adapter_preserves_advanced_page_and_game_inputs(self) -> None:
        fake_context = {
            "date": "2026-06-22",
            "requested_date": "2026-06-22",
            "source_title": "MLB daily summary",
            "source_path": "/tmp/mlb-source",
            "workflow": {
                "name": "ui-daily",
                "mode": "daily_update",
            },
            "lineup_health": {
                "path": "data/mlb_source/data/daily/lineups.json",
                "healthy": True,
            },
            "hr_targets_shelf": {
                "href": "/mlb/hr-targets?date=2026-06-22",
                "row_count": 2,
            },
            "marketAvailability": {
                "gameLines": {"available": True},
                "pitcherProps": {"available": True},
                "hitterProps": {"available": True},
            },
            "games": [
                {
                    "gamePk": "game-mlb-1",
                    "event_id": "401000001",
                    "away_tri": "AWY",
                    "home_tri": "HME",
                    "away": {"abbr": "AWY", "score": 4},
                    "home": {"abbr": "HME", "score": 5},
                    "status": "Final",
                    "detail": "Final",
                    "summary": "Example MLB game",
                    "betting": {"market": "moneyline", "edge": 0.14},
                    "sim": {
                        "score": {"away_mean": 4.2, "home_mean": 5.1},
                        "players": {"home": [{"player": "Home Batter", "pts_mean": 2.1}], "away": [{"player": "Away Batter", "pts_mean": 1.8}]},
                    },
                    "live_state": {"status": "Final", "final": True},
                    "run_projection_rows": [{"label": "Q1", "value": 1.0}],
                    "segment_overview_cards": [{"title": "First 5", "value": "Edge"}],
                    "first1BetSignal": {"market": "first1", "value": 0.31},
                    "gameLens": [{"label": "Live lens"}],
                    "markets": {"moneyline": {"market": "ML"}},
                    "props": [{"market": "hitter_props"}],
                    "liveProps": [{"market": "pitcher_props"}],
                }
            ],
        }

        with patch.dict(
            "syndicate.features.shared.simulation_adapter.SPORT_ADAPTERS",
            {"mlb": lambda *args, **kwargs: fake_context},
            clear=False,
        ):
            payload = build_unified_simulation_adapter("mlb", "2026-06-22")

        game = payload["games"][0]
        advanced = game["inputs"]["advanced"]

        self.assertEqual(payload["source_mode"], "artifact_primary")
        self.assertTrue(payload["advanced"]["available"])
        self.assertEqual(payload["advanced"]["page"]["workflow"]["mode"], "daily_update")
        self.assertTrue(payload["advanced"]["page"]["lineup_health"]["healthy"])
        self.assertEqual(payload["advanced"]["page"]["hr_targets_shelf"]["row_count"], 2)
        self.assertTrue(payload["advanced"]["page"]["marketAvailability"]["gameLines"]["available"])
        self.assertEqual(advanced["page"]["workflow"]["mode"], "daily_update")
        self.assertEqual(advanced["game"]["first1BetSignal"]["market"], "first1")
        self.assertEqual(advanced["game"]["segment_overview_cards"][0]["title"], "First 5")
        self.assertIn("advanced", game["engine_context"]["matchup_modifiers"])
        self.assertEqual(game["advanced"]["game"]["first1BetSignal"]["market"], "first1")
        self.assertIn("advanced", game["display"])


if __name__ == "__main__":
    unittest.main()