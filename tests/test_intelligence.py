from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.features.intelligence import _query_preferences


def _sample_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nba",
            "name": "NBA",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Jayson Tatum Over 28.5",
                            "market": "PTS",
                            "pick": "Over 28.5",
                            "matchup": "BOS at NYK",
                            "projected": 31.8,
                            "line": 28.5,
                            "odds": "+102",
                            "confidence": "63%",
                            "edge": "+5.4%",
                            "writeup": "Projection is clearing the number with usage and minutes support.",
                            "display_pills": ["Line 28.5", "Odds +102", "Sim% 63%"],
                            "href": "/nba/prop-ladders?date=2026-06-04",
                        }
                    ],
                },
                "live": {
                    "title": "Top Live Props",
                    "items": [
                        {
                            "name": "Donovan Mitchell Over 4.5 3PM",
                            "market": "3PM",
                            "pick": "Over 4.5",
                            "matchup": "CLE at IND",
                            "projected": 4.9,
                            "live_projection": 5.8,
                            "actual": 3,
                            "line": 4.5,
                            "odds": "+118",
                            "confidence": "61%",
                            "edge": "+4.1%",
                            "writeup": "The live model is still above the book after the in-game adjustment.",
                            "display_pills": ["Line 4.5", "Odds +118", "Live Proj 5.8"],
                            "is_live": True,
                            "href": "/nba/season/2026/live-lens?date=2026-06-04",
                        }
                    ],
                },
                "compact": {"items": []},
            },
            "dashboard_games": [
                {
                    "matchup": "MIN at DAL",
                    "summary": "Model makes the total short by a couple of points.",
                    "betting": {
                        "total": 217.5,
                        "over_ev": 3.8,
                        "p_total_over": 0.58,
                    },
                    "href": "/nba/cards?date=2026-06-04",
                    "href_label": "Open game",
                }
            ],
        }
    ]


def _sample_overview_with_secondary_sport() -> list[dict[str, object]]:
    rows = _sample_overview()
    rows.append(
        {
            "slug": "wnba",
            "name": "WNBA",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "A'ja Wilson Over 24.5",
                            "market": "PTS",
                            "pick": "Over 24.5",
                            "matchup": "LVA at SEA",
                            "projected": 28.1,
                            "line": 24.5,
                            "odds": "+102",
                            "confidence": "63%",
                            "edge": "+5.4%",
                            "writeup": "Projection is clearing the number with stable volume.",
                            "display_pills": ["Line 24.5", "Odds +102", "Sim% 63%"],
                            "href": "/wnba/prop-ladders?date=2026-06-04",
                        }
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    )
    return rows


class IntelligenceBlueprintTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_query_preferences_parses_exact_parlay_leg_count(self) -> None:
        preferences = _query_preferences("Build me a four-leg parlay from the best NBA edges")

        self.assertEqual(preferences.get("intent"), "parlay")
        self.assertEqual(preferences.get("parlay_leg_min"), 4)
        self.assertEqual(preferences.get("parlay_leg_max"), 4)

    def test_query_preferences_parses_parlay_leg_range(self) -> None:
        preferences = _query_preferences("Build a 2 to 5 leg parlay from the best live edges")

        self.assertEqual(preferences.get("parlay_leg_min"), 2)
        self.assertEqual(preferences.get("parlay_leg_max"), 5)

    def test_query_preferences_parses_parlay_structure_risk_and_correlation(self) -> None:
        preferences = _query_preferences("Build a same game round robin with low correlation and aggressive cross-sport upside")

        self.assertEqual(preferences.get("parlay_type"), "round_robin")
        self.assertTrue(preferences.get("cross_sport_required"))
        self.assertEqual(preferences.get("risk_profile"), "aggressive")
        self.assertEqual(preferences.get("correlation_tolerance"), "low")
        self.assertEqual(preferences.get("round_robin_unit"), 2)

    def test_intelligence_query_returns_ranked_recommendations_and_parlays(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Build a two-leg parlay from the best live and pregame NBA edges",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get("ok"))
        result = payload.get("response") or {}
        self.assertEqual(result.get("selected_date"), "2026-06-04")
        self.assertEqual(result.get("headline"), "The Syndicate parlay builder")
        self.assertGreaterEqual(len(result.get("recommendations") or []), 2)
        self.assertGreaterEqual(len(result.get("parlays") or []), 1)
        first = (result.get("recommendations") or [])[0]
        self.assertIn("rationale", first)
        self.assertIn(first.get("candidate_type"), {"prop", "game"})
        self.assertIn("Advanced drivers in play", first.get("rationale") or "")
        self.assertTrue(first.get("advanced_inputs"))
        self.assertIn("readiness_gate", result)
        self.assertIn("parsed_request", result)
        self.assertTrue(first.get("advanced_ready"))
        self.assertIsNotNone(first.get("decimal_odds"))
        self.assertIsNotNone(first.get("implied_probability"))

        first_parlay = (result.get("parlays") or [])[0]
        self.assertIsNotNone(first_parlay.get("combined_odds"))
        self.assertIsNotNone(first_parlay.get("combined_decimal_odds"))
        self.assertIsNotNone(first_parlay.get("combined_implied_probability"))
        parsed_request = result.get("parsed_request") or {}
        self.assertTrue(parsed_request.get("chips"))

    def test_intelligence_query_prioritizes_ready_advanced_inputs(self) -> None:
        advanced_by_sport = {
            "nba": [
                {
                    "label": "Team advanced stats",
                    "metrics": ["Pace", "Offensive rating", "Shot profile"],
                    "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                    "exists": True,
                    "tracked": True,
                    "inside_repo": True,
                }
            ],
            "wnba": [
                {
                    "label": "Team environment and pace layer",
                    "metrics": ["Pace", "Team environment"],
                    "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
                    "exists": False,
                    "tracked": False,
                    "inside_repo": True,
                }
            ],
        }
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_overview_with_secondary_sport()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", side_effect=lambda sport, tracked: advanced_by_sport.get(sport.get("slug"), [])):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Give me the best pregame props across NBA and WNBA",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertGreaterEqual(len(recommendations), 2)
        self.assertEqual(recommendations[0].get("sport_slug"), "nba")
        self.assertTrue(recommendations[0].get("advanced_ready"))
        self.assertEqual(recommendations[1].get("advanced_readiness"), "blocked")
        self.assertTrue(recommendations[1].get("missing_advanced_inputs"))
        self.assertIn("missing or unpublished", recommendations[1].get("rationale") or "")

    def test_intelligence_query_excludes_props_for_final_games(self) -> None:
        overview = _sample_overview()
        live_items = (((overview[0].get("home_rails") or {}).get("live") or {}).get("items") or [])
        live_items.insert(
            0,
            {
                "name": "Jalen Brunson Over 6.5 Assists",
                "market": "AST",
                "pick": "Over 6.5",
                "matchup": "BOS at NYK",
                "projected": 7.4,
                "live_projection": 7.1,
                "actual": 6,
                "line": 6.5,
                "odds": "+110",
                "confidence": "62%",
                "edge": "+4.0%",
                "writeup": "This should be filtered because the game is over.",
                "display_pills": ["Line 6.5", "Odds +110", "Live Proj 7.1"],
                "is_live": True,
                "status_display": "102-99 | Final",
                "status_context": "102-99 | Final",
                "href": "/nba/season/2026/live-lens?date=2026-06-04",
            },
        )
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Show me the best live NBA props",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        recommendation_names = [item.get("name") for item in (result.get("recommendations") or [])]
        self.assertNotIn("Jalen Brunson Over 6.5 Assists", recommendation_names)
        self.assertIn("Donovan Mitchell Over 4.5 3PM", recommendation_names)

    def test_intelligence_query_supports_plus_money_only_filter(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Give me the best NBA props plus money only",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertTrue(all((item.get("american_odds") or 0) >= 100 for item in recommendations))

    def test_intelligence_query_supports_target_parlay_odds_range(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Build me a two-leg parlay between +300 and +500 from the best NBA edges",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        for parlay in parlays:
            combined_odds = str(parlay.get("combined_odds") or "")
            self.assertTrue(combined_odds.startswith("+"))
            self.assertGreaterEqual(int(combined_odds), 300)
            self.assertLessEqual(int(combined_odds), 500)

    def test_intelligence_query_supports_four_leg_parlays(self) -> None:
        overview = [
            {
                "slug": "nba",
                "name": "NBA",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Tatum Over 28.5",
                                "market": "PTS",
                                "pick": "Over 28.5",
                                "matchup": "BOS at NYK",
                                "projected": 31.8,
                                "line": 28.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+5.4%",
                                "writeup": "Projection clears the number.",
                                "display_pills": ["Line 28.5", "Odds +102"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Brown Over 6.5 Reb",
                                "market": "REB",
                                "pick": "Over 6.5",
                                "matchup": "MIA at PHI",
                                "projected": 7.9,
                                "line": 6.5,
                                "odds": "+108",
                                "confidence": "61%",
                                "edge": "+4.0%",
                                "writeup": "Rebounding spot is favorable.",
                                "display_pills": ["Line 6.5", "Odds +108"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Booker Over 7.5 Ast",
                                "market": "AST",
                                "pick": "Over 7.5",
                                "matchup": "PHX at SAC",
                                "projected": 8.6,
                                "line": 7.5,
                                "odds": "+104",
                                "confidence": "60%",
                                "edge": "+3.6%",
                                "writeup": "Primary handler workload supports the over.",
                                "display_pills": ["Line 7.5", "Odds +104"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                        ],
                    },
                    "live": {
                        "title": "Top Live Props",
                        "items": [
                            {
                                "name": "Mitchell Over 4.5 3PM",
                                "market": "3PM",
                                "pick": "Over 4.5",
                                "matchup": "CLE at IND",
                                "projected": 4.9,
                                "live_projection": 5.8,
                                "actual": 3,
                                "line": 4.5,
                                "odds": "+118",
                                "confidence": "61%",
                                "edge": "+4.1%",
                                "writeup": "Live model still clears the line.",
                                "display_pills": ["Line 4.5", "Odds +118", "Live Proj 5.8"],
                                "is_live": True,
                                "href": "/nba/season/2026/live-lens?date=2026-06-04",
                            }
                        ],
                    },
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Build me a four-leg parlay from the best NBA edges",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        self.assertTrue(all(len(parlay.get("legs") or []) == 4 for parlay in parlays))
        self.assertTrue(all(str(parlay.get("label") or "").startswith("4-leg") for parlay in parlays))

    def test_intelligence_query_supports_cross_sport_parlays(self) -> None:
        advanced_by_sport = {
            "nba": [
                {
                    "label": "Team advanced stats",
                    "metrics": ["Pace", "Offensive rating"],
                    "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                    "exists": True,
                    "tracked": True,
                    "inside_repo": True,
                }
            ],
            "wnba": [
                {
                    "label": "Team environment and pace layer",
                    "metrics": ["Pace", "Team environment"],
                    "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
                    "exists": True,
                    "tracked": True,
                    "inside_repo": True,
                }
            ],
        }
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_overview_with_secondary_sport()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", side_effect=lambda sport, tracked: advanced_by_sport.get(sport.get("slug"), [])):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Build me a cross-sport two-leg parlay across NBA and WNBA",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("cross_sport") for parlay in parlays))
        self.assertTrue(all(len(set(leg.get("sport_slug") for leg in (parlay.get("legs") or []))) > 1 for parlay in parlays))
        self.assertTrue(any("Cross-sport" in chip for chip in ((result.get("parsed_request") or {}).get("chips") or [])))

    def test_intelligence_query_supports_same_game_parlays(self) -> None:
        overview = [
            {
                "slug": "nba",
                "name": "NBA",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Tatum Over 28.5",
                                "market": "PTS",
                                "pick": "Over 28.5",
                                "matchup": "BOS at NYK",
                                "projected": 31.8,
                                "line": 28.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+5.4%",
                                "writeup": "Projection clears the number.",
                                "display_pills": ["Line 28.5", "Odds +102"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Brunson Over 6.5 Ast",
                                "market": "AST",
                                "pick": "Over 6.5",
                                "matchup": "BOS at NYK",
                                "projected": 7.8,
                                "line": 6.5,
                                "odds": "+106",
                                "confidence": "61%",
                                "edge": "+4.2%",
                                "writeup": "Primary handler usage is intact.",
                                "display_pills": ["Line 6.5", "Odds +106"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Holiday Over 2.5 3PM",
                                "market": "3PM",
                                "pick": "Over 2.5",
                                "matchup": "BOS at NYK",
                                "projected": 3.3,
                                "line": 2.5,
                                "odds": "+112",
                                "confidence": "60%",
                                "edge": "+3.8%",
                                "writeup": "Spot-up volume is there.",
                                "display_pills": ["Line 2.5", "Odds +112"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Build me a same game three-leg parlay from the best NBA edges",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("parlay_type") == "same_game" for parlay in parlays))
        self.assertTrue(all(len(set(leg.get("matchup") for leg in (parlay.get("legs") or []))) == 1 for parlay in parlays))

    def test_intelligence_query_supports_round_robin_parlays(self) -> None:
        overview = [
            {
                "slug": "nba",
                "name": "NBA",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Tatum Over 28.5",
                                "market": "PTS",
                                "pick": "Over 28.5",
                                "matchup": "BOS at NYK",
                                "projected": 31.8,
                                "line": 28.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+5.4%",
                                "writeup": "Projection clears the number.",
                                "display_pills": ["Line 28.5", "Odds +102"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Brown Over 6.5 Reb",
                                "market": "REB",
                                "pick": "Over 6.5",
                                "matchup": "MIA at PHI",
                                "projected": 7.9,
                                "line": 6.5,
                                "odds": "+108",
                                "confidence": "61%",
                                "edge": "+4.0%",
                                "writeup": "Rebounding spot is favorable.",
                                "display_pills": ["Line 6.5", "Odds +108"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Booker Over 7.5 Ast",
                                "market": "AST",
                                "pick": "Over 7.5",
                                "matchup": "PHX at SAC",
                                "projected": 8.6,
                                "line": 7.5,
                                "odds": "+104",
                                "confidence": "60%",
                                "edge": "+3.6%",
                                "writeup": "Primary handler workload supports the over.",
                                "display_pills": ["Line 7.5", "Odds +104"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Edwards Over 3.5 3PM",
                                "market": "3PM",
                                "pick": "Over 3.5",
                                "matchup": "MIN at DAL",
                                "projected": 4.4,
                                "line": 3.5,
                                "odds": "+110",
                                "confidence": "60%",
                                "edge": "+3.9%",
                                "writeup": "Volume holds in a fast environment.",
                                "display_pills": ["Line 3.5", "Odds +110"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Build me a four-leg round robin from the best NBA edges",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("parlay_type") == "round_robin" for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_unit") == 2 for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_group_size") == 4 for parlay in parlays))
        self.assertTrue(all(str(parlay.get("label") or "").startswith("Round robin") for parlay in parlays))

    def test_intelligence_query_requires_question(self) -> None:
        response = self.client.post("/api/intelligence/query", json={"date": "2026-06-04"})

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload.get("ok"))

    def test_intelligence_status_reports_tracked_artifacts(self) -> None:
        status_overview = [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
            }
        ]
        tracked_paths = {
            "data/mlb_source/data/live_lens/live_lens_report_2026_06_04.json",
            "data/mlb_source/data/live_lens/live_lens_2026_06_04.jsonl",
        }
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=status_overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=tracked_paths):
                response = self.client.get("/api/intelligence/status?date=2026-06-04")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get("ok"))
        sports = payload.get("sports") or []
        self.assertEqual(len(sports), 1)
        artifacts = sports[0].get("artifacts") or []
        self.assertTrue(any(item.get("tracked") for item in artifacts))
        advanced_inputs = sports[0].get("advanced_inputs") or []
        self.assertTrue(advanced_inputs)
        self.assertIn("metrics", advanced_inputs[0])
        self.assertIn("readiness_gate", payload)
        self.assertIn("advanced_gate", sports[0])
        self.assertIn("publish_missing_inputs", sports[0].get("advanced_gate") or {})

    def test_intelligence_page_renders_embedded_console(self) -> None:
        with patch(
            "syndicate.blueprints.intelligence.build_intelligence_status",
            return_value={
                "selected_date": "2026-06-04",
                "sports": [],
                "tracked_summary": {"tracked_ok": 0, "tracked_total": 0},
                "advanced_summary": {"tracked_ok": 0, "tracked_total": 0},
                "readiness_gate": {"ready": False, "ready_sports": [], "partial_sports": [], "blocked_sports": [], "inactive_sports": []},
            },
        ):
            response = self.client.get("/intelligence?date=2026-06-04")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="intel-query-form"', body)
        self.assertIn('/api/intelligence/query', body)
        self.assertIn('Advanced artifact status', body)
        self.assertIn('Ask The Syndicate for best bets, live angles, or parlays', body)