from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints.home import _game_bet_candidates_from_game
from syndicate.features.intelligence import _build_parlays
from syndicate.features.intelligence import _candidate_summary
from syndicate.features.intelligence import _collect_candidates
from syndicate.features.intelligence import _parlay_matches_preferences
from syndicate.features.intelligence import _parlay_rank_score
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
                            "odds_refreshed_at": "2026-06-04T16:03:08Z",
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
                    "generatedAt": "2026-06-04T15:55:00Z",
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


def _sample_mlb_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "mlb",
            "name": "MLB",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Aaron Judge Over 0.5 Home Runs",
                            "market": "Hitter Home Runs",
                            "pick": "Over 0.5",
                            "matchup": "NYY at BOS",
                            "projected": 0.64,
                            "line": 0.5,
                            "odds": "+310",
                            "confidence": "27%",
                            "edge": "+3.2%",
                            "writeup": "Barrel rate and park lift the HR ceiling.",
                            "display_pills": ["Line 0.5", "Odds +310"],
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                        {
                            "name": "Chris Sale Over 7.5 Strikeouts",
                            "market": "Pitcher Strikeouts",
                            "pick": "Over 7.5",
                            "matchup": "ATL at NYM",
                            "projected": 8.4,
                            "line": 7.5,
                            "odds": "+102",
                            "confidence": "61%",
                            "edge": "+4.8%",
                            "writeup": "Whiff-heavy matchup keeps the strikeout ceiling in play.",
                            "display_pills": ["Line 7.5", "Odds +102"],
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                        {
                            "name": "Freddie Freeman Over 1.5 Total Bases",
                            "market": "Hitter Total Bases",
                            "pick": "Over 1.5",
                            "matchup": "LAD at SD",
                            "projected": 2.1,
                            "line": 1.5,
                            "odds": "+115",
                            "confidence": "58%",
                            "edge": "+3.6%",
                            "writeup": "Contact quality and lineup spot support extra-base upside.",
                            "display_pills": ["Line 1.5", "Odds +115"],
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


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
        preferences = _query_preferences("Build a same game round robin with low correlation and aggressive cross-sport upside, $100 bankroll, and max 20% exposure")

        self.assertEqual(preferences.get("parlay_type"), "round_robin")
        self.assertTrue(preferences.get("cross_sport_required"))
        self.assertEqual(preferences.get("risk_profile"), "aggressive")
        self.assertEqual(preferences.get("correlation_tolerance"), "low")
        self.assertTrue(preferences.get("correlation_explicit"))
        self.assertEqual(preferences.get("round_robin_unit"), 2)
        self.assertEqual(preferences.get("bankroll_amount"), 100)
        self.assertEqual(preferences.get("max_exposure_pct"), 20)

    def test_query_preferences_parses_explicit_medium_correlation(self) -> None:
        preferences = _query_preferences("Build me a same game parlay with medium correlation")

        self.assertEqual(preferences.get("correlation_tolerance"), "medium")
        self.assertTrue(preferences.get("correlation_explicit"))

    def test_query_preferences_parses_market_focus_and_live_parlay_timing(self) -> None:
        strikeout_preferences = _query_preferences("Who are the top 3 strikeout targets for today?")

        self.assertEqual(strikeout_preferences.get("requested_sports"), ["mlb"])
        self.assertEqual(strikeout_preferences.get("requested_markets"), ["strikeouts"])
        self.assertTrue(strikeout_preferences.get("include_props"))
        self.assertFalse(strikeout_preferences.get("include_games"))
        self.assertEqual(strikeout_preferences.get("limit"), 3)

        live_ml_preferences = _query_preferences("Build me a live ML parlay")

        self.assertEqual(live_ml_preferences.get("intent"), "parlay")
        self.assertTrue(live_ml_preferences.get("include_games"))
        self.assertTrue(live_ml_preferences.get("live_only"))
        self.assertFalse(live_ml_preferences.get("pregame_only"))
        self.assertEqual(live_ml_preferences.get("requested_markets"), ["moneyline"])

    def test_collect_candidates_filters_to_requested_market_focus(self) -> None:
        preferences = _query_preferences("Who are the top 3 strikeout targets for today?")

        candidates = _collect_candidates(_sample_mlb_overview(), preferences)

        self.assertTrue(candidates)
        self.assertTrue(all("strikeout" in str(candidate.get("market") or "").lower() for candidate in candidates))

    def test_intelligence_query_returns_market_specific_board(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast quality",
                "metrics": ["Whiff rate", "Pitch mix", "Opponent K rate"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Who are the top 3 strikeout targets for today?",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        self.assertEqual(result.get("headline"), "The Syndicate strikeouts board")
        parsed_request = result.get("parsed_request") or {}
        self.assertIn("Strikeouts", parsed_request.get("requested_markets") or [])
        self.assertIn("Strikeouts", parsed_request.get("chips") or [])
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertTrue(all("strikeout" in str(item.get("market") or "").lower() for item in recommendations))

    def test_intelligence_query_ranks_strikeout_targets_by_market_shape(self) -> None:
        overview = [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Tarik Skubal Over 6.5 Strikeouts",
                                "market": "Pitcher Strikeouts",
                                "pick": "Over 6.5",
                                "matchup": "DET at CLE",
                                "projected": 8.9,
                                "line": 6.5,
                                "odds": "+105",
                                "confidence": "58%",
                                "edge": "+2.1%",
                                "writeup": "Projection gap is carrying the ceiling.",
                                "display_pills": ["Line 6.5", "Odds +105"],
                                "href": "/mlb/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Spencer Strider Over 7.5 Strikeouts",
                                "market": "Pitcher Strikeouts",
                                "pick": "Over 7.5",
                                "matchup": "ATL at NYM",
                                "projected": 8.0,
                                "line": 7.5,
                                "odds": "+102",
                                "confidence": "66%",
                                "edge": "+5.4%",
                                "writeup": "Still a good strikeout spot, but the book is tighter.",
                                "display_pills": ["Line 7.5", "Odds +102"],
                                "href": "/mlb/prop-ladders?date=2026-06-04",
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
                "label": "Statcast quality",
                "metrics": ["Whiff rate", "Pitch mix", "Opponent K rate"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
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
                            "question": "Who are the top 2 strikeout targets for today?",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertEqual(len(recommendations), 2)
        self.assertEqual(recommendations[0].get("name"), "Tarik Skubal Over 6.5 Strikeouts")
        self.assertEqual(recommendations[1].get("name"), "Spencer Strider Over 7.5 Strikeouts")
        self.assertEqual(recommendations[0].get("market_key"), "strikeouts")
        self.assertEqual(recommendations[0].get("market_shape"), "volume_prop")
        self.assertIn("Projection gap", recommendations[0].get("market_fit_note") or "")
        self.assertIn("shape volume prop", recommendations[0].get("market_fit_note") or "")

    def test_intelligence_query_infers_nonhardcoded_market_from_candidate_pool(self) -> None:
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
                                "name": "Tyrese Haliburton Over 2.5 Turnovers",
                                "market": "Turnovers",
                                "pick": "Over 2.5",
                                "matchup": "IND at CLE",
                                "projected": 3.4,
                                "line": 2.5,
                                "odds": "+112",
                                "confidence": "60%",
                                "edge": "+4.1%",
                                "writeup": "Ball pressure keeps the turnover count elevated.",
                                "display_pills": ["Line 2.5", "Odds +112"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Jayson Tatum Over 28.5 Points",
                                "market": "PTS",
                                "pick": "Over 28.5",
                                "matchup": "BOS at NYK",
                                "projected": 31.8,
                                "line": 28.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+5.4%",
                                "writeup": "Projection is clearing the number with usage and minutes support.",
                                "display_pills": ["Line 28.5", "Odds +102"],
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
                "metrics": ["Pace", "Offensive rating", "Turnover pressure"],
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
                            "question": "Show me the best turnovers props today",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        self.assertEqual(result.get("headline"), "The Syndicate turnovers board")
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual(parsed_request.get("requested_markets"), ["Turnovers"])
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertTrue(all(str(item.get("market") or "").lower() == "turnovers" for item in recommendations))
        self.assertEqual(recommendations[0].get("market_key"), "turnovers")
        self.assertEqual(recommendations[0].get("market_shape"), "volume_prop")
        self.assertIn("Projection gap", recommendations[0].get("market_fit_note") or "")

    def test_intelligence_query_assigns_counting_shape_for_points_market(self) -> None:
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
                            "question": "Show me the best points props today",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].get("market_key"), "points")
        self.assertEqual(recommendations[0].get("market_shape"), "counting_prop")
        self.assertIn("shape counting prop", recommendations[0].get("market_fit_note") or "")

    def test_build_parlays_limits_standard_leg_count_for_tight_exposure_caps(self) -> None:
        preferences = _query_preferences(
            "Build an aggressive 2 to 3 leg parlay from the best NBA edges with a $100 bankroll and max 3% exposure"
        )
        candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "pick": "Over 28.5",
                "name": "Tatum Over 28.5",
                "surface_title": "Pregame props",
                "odds": "+125",
                "score": 88.0,
                "market_context": {"decimal_odds": 2.25, "american_odds": 125, "implied_probability": 44.44},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "MIA at PHI",
                "market": "REB",
                "pick": "Over 7.5",
                "name": "Adebayo Over 7.5",
                "surface_title": "Pregame props",
                "odds": "+130",
                "score": 86.0,
                "market_context": {"decimal_odds": 2.3, "american_odds": 130, "implied_probability": 43.48},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "MIN at DAL",
                "market": "AST",
                "pick": "Over 6.5",
                "name": "Edwards Over 6.5",
                "surface_title": "Pregame props",
                "odds": "+135",
                "score": 84.0,
                "market_context": {"decimal_odds": 2.35, "american_odds": 135, "implied_probability": 42.55},
            },
        ]

        parlays = _build_parlays(candidates, limit=5, preferences=preferences)

        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("leg_count") == 2 for parlay in parlays))
        self.assertTrue(all(parlay.get("suggested_total_exposure") == 3.0 for parlay in parlays))

    def test_build_parlays_uses_market_fit_for_market_constrained_ranking(self) -> None:
        preferences = _query_preferences("Build me a two-leg turnovers parlay")
        candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "IND at CLE",
                "market": "Turnovers",
                "pick": "Over 2.5",
                "name": "Haliburton Over 2.5 Turnovers",
                "surface_title": "Pregame props",
                "odds": "+112",
                "score": 82.0,
                "market_fit": {"market_key": "turnovers", "market_label": "Turnovers", "market_shape": "volume_prop", "market_fit_score": 15.0},
                "market_context": {"decimal_odds": 2.12, "american_odds": 112, "implied_probability": 47.17},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "Turnovers",
                "pick": "Over 3.5",
                "name": "Brunson Over 3.5 Turnovers",
                "surface_title": "Pregame props",
                "odds": "+108",
                "score": 81.5,
                "market_fit": {"market_key": "turnovers", "market_label": "Turnovers", "market_shape": "volume_prop", "market_fit_score": 14.0},
                "market_context": {"decimal_odds": 2.08, "american_odds": 108, "implied_probability": 48.08},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "PHX at SAC",
                "market": "Turnovers",
                "pick": "Over 2.5",
                "name": "Booker Over 2.5 Turnovers",
                "surface_title": "Pregame props",
                "odds": "+106",
                "score": 88.0,
                "market_fit": {"market_key": "turnovers", "market_label": "Turnovers", "market_shape": "volume_prop", "market_fit_score": 4.0},
                "market_context": {"decimal_odds": 2.06, "american_odds": 106, "implied_probability": 48.54},
            },
        ]

        parlays = _build_parlays(candidates, limit=3, preferences=preferences)

        self.assertTrue(parlays)
        first_parlay = parlays[0]
        self.assertEqual(first_parlay.get("market_labels"), ["Turnovers"])
        self.assertEqual(first_parlay.get("market_shapes"), ["volume_prop"])
        self.assertGreater(first_parlay.get("combined_market_fit_score") or 0.0, 10.0)
        leg_names = [leg.get("name") for leg in (first_parlay.get("legs") or [])]
        self.assertIn("Haliburton Over 2.5 Turnovers", leg_names)
        self.assertIn("Brunson Over 3.5 Turnovers", leg_names)

    def test_low_correlation_same_game_rejects_duplicate_market_shapes(self) -> None:
        preferences = _query_preferences("Build me a same game three-leg parlay with low correlation")
        legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "AST",
                "market_shape": "counting_prop",
                "pick": "Over 6.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
            },
        )

        self.assertFalse(_parlay_matches_preferences(legs, preferences))

    def test_low_correlation_round_robin_rejects_duplicate_market_shapes(self) -> None:
        preferences = _query_preferences("Build me a four-leg round robin with low correlation")
        legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "MIA at PHI",
                "market": "AST",
                "market_shape": "counting_prop",
                "pick": "Over 6.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "PHX at SAC",
                "market": "Turnovers",
                "market_shape": "volume_prop",
                "pick": "Over 2.5",
            },
        )

        self.assertFalse(_parlay_matches_preferences(legs, preferences))

    def test_explicit_medium_correlation_rejects_three_of_same_shape(self) -> None:
        preferences = _query_preferences("Build me a same game three-leg parlay with medium correlation")
        legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "AST",
                "market_shape": "counting_prop",
                "pick": "Over 6.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
            },
        )

        self.assertFalse(_parlay_matches_preferences(legs, preferences))

    def test_explicit_medium_correlation_allows_three_volume_props(self) -> None:
        preferences = _query_preferences("Build me a same game three-leg parlay with medium correlation")
        legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Pitcher Strikeouts",
                "market_shape": "volume_prop",
                "pick": "Over 7.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
            },
        )

        self.assertTrue(_parlay_matches_preferences(legs, preferences))

    def test_explicit_medium_correlation_rejects_two_game_markets(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        legs = (
            {
                "candidate_type": "game",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "Moneyline",
                "market_shape": "game_market",
                "pick": "BOS ML",
            },
            {
                "candidate_type": "game",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "Spread",
                "market_shape": "game_market",
                "pick": "BOS -4.5",
            },
        )

        self.assertFalse(_parlay_matches_preferences(legs, preferences))

    def test_explicit_medium_correlation_is_sport_aware_for_volume_props(self) -> None:
        preferences = _query_preferences("Build me a same game three-leg parlay with medium correlation")
        nba_legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "Turnovers",
                "market_shape": "volume_prop",
                "pick": "Over 2.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "Steals",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "Blocks",
                "market_shape": "volume_prop",
                "pick": "Over 0.5",
            },
        )
        mlb_legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Pitcher Strikeouts",
                "market_shape": "volume_prop",
                "pick": "Over 7.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
            },
        )

        self.assertFalse(_parlay_matches_preferences(nba_legs, preferences))
        self.assertTrue(_parlay_matches_preferences(mlb_legs, preferences))

    def test_explicit_medium_correlation_is_market_key_aware_within_mlb_volume_props(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        mlb_strikeout_legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Pitcher Strikeouts",
                "market_key": "strikeouts",
                "market_shape": "volume_prop",
                "pick": "Over 7.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Pitcher Strikeouts",
                "market_key": "strikeouts",
                "market_shape": "volume_prop",
                "pick": "Over 6.5",
            },
        )
        mlb_total_bases_legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5 alt",
            },
        )

        self.assertTrue(_parlay_matches_preferences(mlb_strikeout_legs, preferences))
        self.assertFalse(_parlay_matches_preferences(mlb_total_bases_legs, preferences))

    def test_explicit_medium_correlation_blocks_points_assists_pair_but_allows_points_threes(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        points_assists_legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "AST",
                "market_key": "assists",
                "market_shape": "counting_prop",
                "pick": "Over 6.5",
            },
        )
        points_threes_legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
            },
        )

        self.assertFalse(_parlay_matches_preferences(points_assists_legs, preferences))
        self.assertTrue(_parlay_matches_preferences(points_threes_legs, preferences))

    def test_build_parlays_applies_soft_pair_penalty_to_allowed_same_game_pairs(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Tatum Over 28.5",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "REB",
                "market_key": "rebounds",
                "market_shape": "counting_prop",
                "pick": "Over 8.5",
                "name": "Tatum Over 8.5 Reb",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "rebounds", "market_label": "Rebounds", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Tatum Over 2.5 3PM",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        parlays = _build_parlays(candidates, limit=3, preferences=preferences)

        self.assertTrue(parlays)
        parlay_by_keys = {
            tuple(sorted(leg.get("market_key") for leg in (parlay.get("legs") or []))): parlay
            for parlay in parlays
        }
        clean_parlay = parlay_by_keys[("rebounds", "threes")]
        lighter_penalty_parlay = parlay_by_keys[("points", "threes")]
        heavier_penalty_parlay = parlay_by_keys[("points", "rebounds")]

        self.assertEqual(tuple(sorted(leg.get("market_key") for leg in (parlays[0].get("legs") or []))), ("rebounds", "threes"))
        self.assertEqual(clean_parlay.get("pair_correlation_penalty"), 0.0)
        self.assertEqual(lighter_penalty_parlay.get("pair_correlation_penalty"), 1.5)
        self.assertEqual(heavier_penalty_parlay.get("pair_correlation_penalty"), 3.0)
        self.assertIn("Points + Threes correlation penalty 1.5", lighter_penalty_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(lighter_penalty_parlay, preferences),
            _parlay_rank_score(heavier_penalty_parlay, preferences),
        )

    def test_build_parlays_scales_pair_penalty_for_live_same_game_pairs(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        pregame_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Tatum Over 28.5",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Tatum Over 2.5 3PM",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        live_candidates = [
            {
                **candidate,
                "surface_title": "Top Live Props",
                "is_live": True,
            }
            for candidate in pregame_candidates
        ]

        pregame_parlay = _build_parlays(pregame_candidates, limit=1, preferences=preferences)[0]
        live_parlay = _build_parlays(live_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(pregame_parlay.get("pair_correlation_penalty"), 1.5)
        self.assertEqual(live_parlay.get("pair_correlation_penalty"), 2.25)
        self.assertIn("Points + Threes live correlation penalty 2.25", live_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(pregame_parlay, preferences),
            _parlay_rank_score(live_parlay, preferences),
        )

    def test_build_parlays_discount_pair_penalty_for_opposing_directions(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_direction_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Tatum Over 28.5",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Tatum Over 2.5 3PM",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        opposing_direction_candidates = [
            same_direction_candidates[0],
            {
                **same_direction_candidates[1],
                "pick": "Under 2.5",
                "name": "Tatum Under 2.5 3PM",
            },
        ]

        same_direction_parlay = _build_parlays(same_direction_candidates, limit=1, preferences=preferences)[0]
        opposing_direction_parlay = _build_parlays(opposing_direction_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_direction_parlay.get("pair_correlation_penalty"), 1.5)
        self.assertEqual(opposing_direction_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertIn("opposing directions correlation penalty 0.98", opposing_direction_parlay.get("rationale") or "")
        self.assertEqual((opposing_direction_parlay.get("legs") or [])[0].get("selection_direction"), 1)
        self.assertEqual((opposing_direction_parlay.get("legs") or [])[1].get("selection_direction"), -1)
        self.assertGreater(
            _parlay_rank_score(opposing_direction_parlay, preferences),
            _parlay_rank_score(same_direction_parlay, preferences),
        )

    def test_build_parlays_discount_pair_penalty_for_different_players(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_player_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Jayson Tatum Over 28.5",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jayson Tatum Over 2.5 3PM",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        different_player_candidates = [
            same_player_candidates[0],
            {
                **same_player_candidates[1],
                "name": "Jaylen Brown Over 2.5 3PM",
            },
        ]

        same_player_parlay = _build_parlays(same_player_candidates, limit=1, preferences=preferences)[0]
        different_player_parlay = _build_parlays(different_player_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_player_parlay.get("pair_correlation_penalty"), 1.5)
        self.assertEqual(different_player_parlay.get("pair_correlation_penalty"), 1.12)
        self.assertIn("different players correlation penalty 1.12", different_player_parlay.get("rationale") or "")
        self.assertEqual((same_player_parlay.get("legs") or [])[0].get("subject_key"), "jayson tatum")
        self.assertEqual((same_player_parlay.get("legs") or [])[1].get("subject_key"), "jayson tatum")
        self.assertEqual((different_player_parlay.get("legs") or [])[1].get("subject_key"), "jaylen brown")
        self.assertGreater(
            _parlay_rank_score(different_player_parlay, preferences),
            _parlay_rank_score(same_player_parlay, preferences),
        )

    def test_build_parlays_discount_pair_penalty_for_opposing_team_players(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Jayson Tatum Over 28.5",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jaylen Brown Over 2.5 3PM",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        opposing_team_candidates = [
            same_team_candidates[0],
            {
                **same_team_candidates[1],
                "name": "Jalen Brunson Over 2.5 3PM",
                "team": "NYK",
            },
        ]

        same_team_parlay = _build_parlays(same_team_candidates, limit=1, preferences=preferences)[0]
        opposing_team_parlay = _build_parlays(opposing_team_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_parlay.get("pair_correlation_penalty"), 1.3)
        self.assertEqual(opposing_team_parlay.get("pair_correlation_penalty"), 0.77)
        self.assertIn("shared usage script + different players + same team correlation penalty 1.3", same_team_parlay.get("rationale") or "")
        self.assertIn("shared usage script + different players + opposing teams correlation penalty 0.77", opposing_team_parlay.get("rationale") or "")
        self.assertEqual((same_team_parlay.get("legs") or [])[0].get("team_key"), "bos")
        self.assertEqual((same_team_parlay.get("legs") or [])[1].get("team_key"), "bos")
        self.assertEqual((opposing_team_parlay.get("legs") or [])[1].get("team_key"), "nyk")
        self.assertGreater(
            _parlay_rank_score(opposing_team_parlay, preferences),
            _parlay_rank_score(same_team_parlay, preferences),
        )

    def test_build_parlays_use_market_specific_same_team_penalty(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Jayson Tatum Over 28.5",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jaylen Brown Over 2.5 3PM",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        same_team_parlay = _build_parlays(same_team_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_parlay.get("pair_correlation_penalty"), 1.3)
        self.assertIn("shared usage script + different players + same team correlation penalty 1.3", same_team_parlay.get("rationale") or "")
        self.assertEqual((same_team_parlay.get("legs") or [])[0].get("team_key"), "bos")
        self.assertEqual((same_team_parlay.get("legs") or [])[1].get("team_key"), "bos")

    def test_build_parlays_keep_same_team_points_rebounds_tighter_than_points_threes(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_points_rebounds_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Jayson Tatum Over 28.5",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "REB",
                "market_key": "rebounds",
                "market_shape": "counting_prop",
                "pick": "Over 8.5",
                "name": "Jaylen Brown Over 8.5 Reb",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "rebounds", "market_label": "Rebounds", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_points_threes_candidates = [
            same_team_points_rebounds_candidates[0],
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jaylen Brown Over 2.5 3PM",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        same_team_points_rebounds_parlay = _build_parlays(same_team_points_rebounds_candidates, limit=1, preferences=preferences)[0]
        same_team_points_threes_parlay = _build_parlays(same_team_points_threes_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_points_rebounds_parlay.get("pair_correlation_penalty"), 2.64)
        self.assertEqual(same_team_points_threes_parlay.get("pair_correlation_penalty"), 1.3)
        self.assertIn("shared usage/possession script + different players + same team correlation penalty 2.64", same_team_points_rebounds_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(same_team_points_threes_parlay, preferences),
            _parlay_rank_score(same_team_points_rebounds_parlay, preferences),
        )

    def test_build_parlays_give_same_team_assists_rebounds_a_dedicated_penalty(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_assists_rebounds_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "AST",
                "market_key": "assists",
                "market_shape": "counting_prop",
                "pick": "Over 6.5",
                "name": "Jayson Tatum Over 6.5 Ast",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "assists", "market_label": "Assists", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "REB",
                "market_key": "rebounds",
                "market_shape": "counting_prop",
                "pick": "Over 8.5",
                "name": "Jaylen Brown Over 8.5 Reb",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "rebounds", "market_label": "Rebounds", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_points_threes_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Jayson Tatum Over 28.5",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jaylen Brown Over 2.5 3PM",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        same_team_assists_rebounds_parlay = _build_parlays(same_team_assists_rebounds_candidates, limit=1, preferences=preferences)[0]
        same_team_points_threes_parlay = _build_parlays(same_team_points_threes_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_assists_rebounds_parlay.get("pair_correlation_penalty"), 1.29)
        self.assertEqual(same_team_points_threes_parlay.get("pair_correlation_penalty"), 1.3)
        self.assertIn("Assists + Rebounds shared usage/possession script + different players + same team correlation penalty 1.29", same_team_assists_rebounds_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(same_team_assists_rebounds_parlay, preferences),
            _parlay_rank_score(same_team_points_threes_parlay, preferences),
        )

    def test_build_parlays_apply_script_cluster_fallback_to_same_team_assists_threes(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_assists_threes_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "AST",
                "market_key": "assists",
                "market_shape": "counting_prop",
                "pick": "Over 6.5",
                "name": "Jayson Tatum Over 6.5 Ast",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "assists", "market_label": "Assists", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jaylen Brown Over 2.5 3PM",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_points_threes_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Jayson Tatum Over 28.5",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jaylen Brown Over 2.5 3PM",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        same_team_assists_threes_parlay = _build_parlays(same_team_assists_threes_candidates, limit=1, preferences=preferences)[0]
        same_team_points_threes_parlay = _build_parlays(same_team_points_threes_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_assists_threes_parlay.get("pair_correlation_penalty"), 0.9)
        self.assertEqual(same_team_points_threes_parlay.get("pair_correlation_penalty"), 1.3)
        self.assertIn("shared usage script + different players correlation penalty 0.9", same_team_assists_threes_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(same_team_assists_threes_parlay, preferences),
            _parlay_rank_score(same_team_points_threes_parlay, preferences),
        )

    def test_build_parlays_apply_possession_script_fallback_to_same_team_rebounds_blocks(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_rebounds_blocks_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "REB",
                "market_key": "rebounds",
                "market_shape": "counting_prop",
                "pick": "Over 8.5",
                "name": "Jayson Tatum Over 8.5 Reb",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "rebounds", "market_label": "Rebounds", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "BLK",
                "market_key": "blocks",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Jaylen Brown Over 1.5 Blk",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "blocks", "market_label": "Blocks", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        clean_pair_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "REB",
                "market_key": "rebounds",
                "market_shape": "counting_prop",
                "pick": "Over 8.5",
                "name": "Jayson Tatum Over 8.5 Reb",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "rebounds", "market_label": "Rebounds", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jaylen Brown Over 2.5 3PM",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        same_team_rebounds_blocks_parlay = _build_parlays(same_team_rebounds_blocks_candidates, limit=1, preferences=preferences)[0]
        clean_pair_parlay = _build_parlays(clean_pair_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_rebounds_blocks_parlay.get("pair_correlation_penalty"), 0.75)
        self.assertEqual(clean_pair_parlay.get("pair_correlation_penalty"), 0.0)
        self.assertIn("shared possession script + different players correlation penalty 0.75", same_team_rebounds_blocks_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(clean_pair_parlay, preferences),
            _parlay_rank_score(same_team_rebounds_blocks_parlay, preferences),
        )

    def test_build_parlays_apply_nhl_usage_script_fallback_to_shots_goals(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        nhl_usage_pair_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "SOG",
                "market_key": "shots",
                "market_shape": "volume_prop",
                "pick": "Over 3.5",
                "name": "David Pastrnak Over 3.5 SOG",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "shots", "market_label": "Shots", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "GOAL",
                "market_key": "goals",
                "market_shape": "volume_prop",
                "pick": "Over 0.5",
                "name": "Brad Marchand Over 0.5 Goal",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "goals", "market_label": "Goals", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        clean_pair_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "SOG",
                "market_key": "shots",
                "market_shape": "volume_prop",
                "pick": "Over 3.5",
                "name": "David Pastrnak Over 3.5 SOG",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "shots", "market_label": "Shots", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "SAVE",
                "market_key": "saves",
                "market_shape": "volume_prop",
                "pick": "Over 25.5",
                "name": "Igor Shesterkin Over 25.5 Saves",
                "team": "NYR",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "saves", "market_label": "Saves", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        nhl_usage_pair_parlay = _build_parlays(nhl_usage_pair_candidates, limit=1, preferences=preferences)[0]
        clean_pair_parlay = _build_parlays(clean_pair_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(nhl_usage_pair_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertEqual(clean_pair_parlay.get("pair_correlation_penalty"), 0.0)
        self.assertIn("Shots + Goals different players + same team correlation penalty 0.98", nhl_usage_pair_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(clean_pair_parlay, preferences),
            _parlay_rank_score(nhl_usage_pair_parlay, preferences),
        )

    def test_build_parlays_apply_team_context_to_nhl_usage_pairs(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "SOG",
                "market_key": "shots",
                "market_shape": "volume_prop",
                "pick": "Over 3.5",
                "name": "David Pastrnak Over 3.5 SOG",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "shots", "market_label": "Shots", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "Goals",
                "market_key": "goals",
                "market_shape": "volume_prop",
                "pick": "Over 0.5",
                "name": "Brad Marchand Over 0.5 Goals",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "goals", "market_label": "Goals", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        opposing_team_candidates = [
            same_team_candidates[0],
            {
                **same_team_candidates[1],
                "name": "Artemi Panarin Over 0.5 Goals",
                "team": "NYR",
            },
        ]

        same_team_parlay = _build_parlays(same_team_candidates, limit=1, preferences=preferences)[0]
        opposing_team_parlay = _build_parlays(opposing_team_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertEqual(opposing_team_parlay.get("pair_correlation_penalty"), 0.56)
        self.assertIn("Shots + Goals different players + same team correlation penalty 0.98", same_team_parlay.get("rationale") or "")
        self.assertIn("Shots + Goals different players + opposing teams correlation penalty 0.56", opposing_team_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(opposing_team_parlay, preferences),
            _parlay_rank_score(same_team_parlay, preferences),
        )

    def test_build_parlays_keep_nhl_shots_goals_tighter_than_shots_assists(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_shots_goals_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "SOG",
                "market_key": "shots",
                "market_shape": "volume_prop",
                "pick": "Over 3.5",
                "name": "David Pastrnak Over 3.5 SOG",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "shots", "market_label": "Shots", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "Goals",
                "market_key": "goals",
                "market_shape": "volume_prop",
                "pick": "Over 0.5",
                "name": "Brad Marchand Over 0.5 Goals",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "goals", "market_label": "Goals", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_shots_assists_candidates = [
            same_team_shots_goals_candidates[0],
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "Assists",
                "market_key": "assists",
                "market_shape": "counting_prop",
                "pick": "Over 0.5",
                "name": "Brad Marchand Over 0.5 Assists",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "assists", "market_label": "Assists", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        shots_goals_parlay = _build_parlays(same_team_shots_goals_candidates, limit=1, preferences=preferences)[0]
        shots_assists_parlay = _build_parlays(same_team_shots_assists_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(shots_goals_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertEqual(shots_assists_parlay.get("pair_correlation_penalty"), 0.87)
        self.assertIn("Shots + Goals different players + same team correlation penalty 0.98", shots_goals_parlay.get("rationale") or "")
        self.assertIn("Shots + Assists different players + same team correlation penalty 0.87", shots_assists_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(shots_assists_parlay, preferences),
            _parlay_rank_score(shots_goals_parlay, preferences),
        )

    def test_build_parlays_keep_nhl_goals_assists_tighter_than_shots_assists(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_shots_assists_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "SOG",
                "market_key": "shots",
                "market_shape": "volume_prop",
                "pick": "Over 3.5",
                "name": "David Pastrnak Over 3.5 SOG",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "shots", "market_label": "Shots", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "Assists",
                "market_key": "assists",
                "market_shape": "counting_prop",
                "pick": "Over 0.5",
                "name": "Brad Marchand Over 0.5 Assists",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "assists", "market_label": "Assists", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_goals_assists_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NHL",
                "sport_slug": "nhl",
                "matchup": "NYR at BOS",
                "market": "Goals",
                "market_key": "goals",
                "market_shape": "volume_prop",
                "pick": "Over 0.5",
                "name": "Brad Marchand Over 0.5 Goals",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "goals", "market_label": "Goals", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
            {
                **same_team_shots_assists_candidates[1],
                "name": "Charlie McAvoy Over 0.5 Assists",
            },
        ]

        shots_assists_parlay = _build_parlays(same_team_shots_assists_candidates, limit=1, preferences=preferences)[0]
        goals_assists_parlay = _build_parlays(same_team_goals_assists_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(shots_assists_parlay.get("pair_correlation_penalty"), 0.87)
        self.assertEqual(goals_assists_parlay.get("pair_correlation_penalty"), 0.91)
        self.assertIn("Shots + Assists different players + same team correlation penalty 0.87", shots_assists_parlay.get("rationale") or "")
        self.assertIn("Goals + Assists different players + same team correlation penalty 0.91", goals_assists_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(shots_assists_parlay, preferences),
            _parlay_rank_score(goals_assists_parlay, preferences),
        )

    def test_build_parlays_apply_mlb_batter_production_fallback_to_hits_total_bases(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        mlb_batter_pair_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_key": "hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Ronald Acuna Jr. Over 1.5 Hits",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "hits", "market_label": "Hits", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Austin Riley Over 1.5 Total Bases",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "total_bases", "market_label": "Total bases", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        clean_pair_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Pitcher Strikeouts",
                "market_key": "strikeouts",
                "market_shape": "volume_prop",
                "pick": "Over 7.5",
                "name": "Spencer Strider Over 7.5 Strikeouts",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "strikeouts", "market_label": "Strikeouts", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_key": "hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Francisco Lindor Over 1.5 Hits",
                "team": "NYM",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "hits", "market_label": "Hits", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        mlb_batter_pair_parlay = _build_parlays(mlb_batter_pair_candidates, limit=1, preferences=preferences)[0]
        clean_pair_parlay = _build_parlays(clean_pair_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(mlb_batter_pair_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertEqual(clean_pair_parlay.get("pair_correlation_penalty"), 0.0)
        self.assertIn("Hits + Total bases different players + same team correlation penalty 0.79", mlb_batter_pair_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(clean_pair_parlay, preferences),
            _parlay_rank_score(mlb_batter_pair_parlay, preferences),
        )

    def test_build_parlays_discount_mlb_batter_production_pair_penalty_for_opposing_directions(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_direction_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_key": "hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Ronald Acuna Jr. Over 1.5 Hits",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "hits", "market_label": "Hits", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Austin Riley Over 1.5 Total Bases",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "total_bases", "market_label": "Total bases", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        opposing_direction_candidates = [
            same_direction_candidates[0],
            {
                **same_direction_candidates[1],
                "pick": "Under 1.5",
                "name": "Austin Riley Under 1.5 Total Bases",
            },
        ]

        same_direction_parlay = _build_parlays(same_direction_candidates, limit=1, preferences=preferences)[0]
        opposing_direction_parlay = _build_parlays(opposing_direction_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_direction_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertEqual(opposing_direction_parlay.get("pair_correlation_penalty"), 0.35)
        self.assertIn("Hits + Total bases opposing directions + different players + same team correlation penalty 0.35", opposing_direction_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(opposing_direction_parlay, preferences),
            _parlay_rank_score(same_direction_parlay, preferences),
        )

    def test_build_parlays_apply_team_context_to_mlb_batter_production_pairs(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_key": "hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Ronald Acuna Jr. Over 1.5 Hits",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "hits", "market_label": "Hits", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Austin Riley Over 1.5 Total Bases",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "total_bases", "market_label": "Total bases", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        opposing_team_candidates = [
            same_team_candidates[0],
            {
                **same_team_candidates[1],
                "name": "Francisco Lindor Over 1.5 Total Bases",
                "team": "NYM",
            },
        ]

        same_team_parlay = _build_parlays(same_team_candidates, limit=1, preferences=preferences)[0]
        opposing_team_parlay = _build_parlays(opposing_team_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertEqual(opposing_team_parlay.get("pair_correlation_penalty"), 0.45)
        self.assertIn("Hits + Total bases different players + same team correlation penalty 0.79", same_team_parlay.get("rationale") or "")
        self.assertIn("Hits + Total bases different players + opposing teams correlation penalty 0.45", opposing_team_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(opposing_team_parlay, preferences),
            _parlay_rank_score(same_team_parlay, preferences),
        )

    def test_build_parlays_keep_mlb_home_runs_rbi_tighter_than_hits_total_bases(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_hits_total_bases_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_key": "hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Ronald Acuna Jr. Over 1.5 Hits",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "hits", "market_label": "Hits", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Austin Riley Over 1.5 Total Bases",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "total_bases", "market_label": "Total bases", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_home_runs_rbi_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Home Runs",
                "market_key": "home_runs",
                "market_shape": "binary_ceiling_prop",
                "pick": "Over 0.5",
                "name": "Matt Olson Over 0.5 Home Runs",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+210",
                "score": 84.0,
                "market_fit": {"market_key": "home_runs", "market_label": "Home runs", "market_shape": "binary_ceiling_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 3.10, "american_odds": 210, "implied_probability": 32.26},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "RBI",
                "market_key": "rbi",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Marcell Ozuna Over 1.5 RBI",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+145",
                "score": 84.0,
                "market_fit": {"market_key": "rbi", "market_label": "RBI", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.45, "american_odds": 145, "implied_probability": 40.82},
            },
        ]

        hits_total_bases_parlay = _build_parlays(same_team_hits_total_bases_candidates, limit=1, preferences=preferences)[0]
        home_runs_rbi_parlay = _build_parlays(same_team_home_runs_rbi_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(hits_total_bases_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertEqual(home_runs_rbi_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertIn("Hits + Total bases different players + same team correlation penalty 0.79", hits_total_bases_parlay.get("rationale") or "")
        self.assertIn("Home runs + RBI different players + same team correlation penalty 0.98", home_runs_rbi_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(hits_total_bases_parlay, preferences),
            _parlay_rank_score(home_runs_rbi_parlay, preferences),
        )

    def test_build_parlays_keep_mlb_home_runs_total_bases_tighter_than_hits_total_bases(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_hits_total_bases_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_key": "hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Ronald Acuna Jr. Over 1.5 Hits",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "hits", "market_label": "Hits", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Austin Riley Over 1.5 Total Bases",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "total_bases", "market_label": "Total bases", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_home_runs_total_bases_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Home Runs",
                "market_key": "home_runs",
                "market_shape": "binary_ceiling_prop",
                "pick": "Over 0.5",
                "name": "Matt Olson Over 0.5 Home Runs",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+210",
                "score": 84.0,
                "market_fit": {"market_key": "home_runs", "market_label": "Home runs", "market_shape": "binary_ceiling_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 3.10, "american_odds": 210, "implied_probability": 32.26},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Austin Riley Over 1.5 Total Bases",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "total_bases", "market_label": "Total bases", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        hits_total_bases_parlay = _build_parlays(same_team_hits_total_bases_candidates, limit=1, preferences=preferences)[0]
        home_runs_total_bases_parlay = _build_parlays(same_team_home_runs_total_bases_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(hits_total_bases_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertEqual(home_runs_total_bases_parlay.get("pair_correlation_penalty"), 1.06)
        self.assertIn("Hits + Total bases different players + same team correlation penalty 0.79", hits_total_bases_parlay.get("rationale") or "")
        self.assertIn("Home runs + Total bases different players + same team correlation penalty 1.06", home_runs_total_bases_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(hits_total_bases_parlay, preferences),
            _parlay_rank_score(home_runs_total_bases_parlay, preferences),
        )

    def test_build_parlays_keep_mlb_hits_rbi_tighter_than_hits_total_bases(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_hits_total_bases_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_key": "hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Ronald Acuna Jr. Over 1.5 Hits",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "hits", "market_label": "Hits", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Austin Riley Over 1.5 Total Bases",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "total_bases", "market_label": "Total bases", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_hits_rbi_candidates = [
            same_team_hits_total_bases_candidates[0],
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "RBI",
                "market_key": "rbi",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Marcell Ozuna Over 1.5 RBI",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+145",
                "score": 84.0,
                "market_fit": {"market_key": "rbi", "market_label": "RBI", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.45, "american_odds": 145, "implied_probability": 40.82},
            },
        ]

        hits_total_bases_parlay = _build_parlays(same_team_hits_total_bases_candidates, limit=1, preferences=preferences)[0]
        hits_rbi_parlay = _build_parlays(same_team_hits_rbi_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(hits_total_bases_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertEqual(hits_rbi_parlay.get("pair_correlation_penalty"), 0.91)
        self.assertIn("Hits + Total bases different players + same team correlation penalty 0.79", hits_total_bases_parlay.get("rationale") or "")
        self.assertIn("Hits + RBI different players + same team correlation penalty 0.91", hits_rbi_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(hits_total_bases_parlay, preferences),
            _parlay_rank_score(hits_rbi_parlay, preferences),
        )

    def test_build_parlays_keep_mlb_home_runs_hits_tighter_than_hits_total_bases(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_hits_total_bases_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_key": "hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Ronald Acuna Jr. Over 1.5 Hits",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "hits", "market_label": "Hits", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Austin Riley Over 1.5 Total Bases",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "total_bases", "market_label": "Total bases", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_home_runs_hits_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Home Runs",
                "market_key": "home_runs",
                "market_shape": "binary_ceiling_prop",
                "pick": "Over 0.5",
                "name": "Matt Olson Over 0.5 Home Runs",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+210",
                "score": 84.0,
                "market_fit": {"market_key": "home_runs", "market_label": "Home runs", "market_shape": "binary_ceiling_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 3.10, "american_odds": 210, "implied_probability": 32.26},
            },
            {
                **same_team_hits_total_bases_candidates[0],
            },
        ]

        hits_total_bases_parlay = _build_parlays(same_team_hits_total_bases_candidates, limit=1, preferences=preferences)[0]
        home_runs_hits_parlay = _build_parlays(same_team_home_runs_hits_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(hits_total_bases_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertEqual(home_runs_hits_parlay.get("pair_correlation_penalty"), 0.94)
        self.assertIn("Hits + Total bases different players + same team correlation penalty 0.79", hits_total_bases_parlay.get("rationale") or "")
        self.assertIn("Home runs + Hits different players + same team correlation penalty 0.94", home_runs_hits_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(hits_total_bases_parlay, preferences),
            _parlay_rank_score(home_runs_hits_parlay, preferences),
        )

    def test_build_parlays_keep_mlb_total_bases_rbi_tighter_than_hits_total_bases(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_hits_total_bases_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hits",
                "market_key": "hits",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Ronald Acuna Jr. Over 1.5 Hits",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "hits", "market_label": "Hits", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "Hitter Total Bases",
                "market_key": "total_bases",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Austin Riley Over 1.5 Total Bases",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "total_bases", "market_label": "Total bases", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_total_bases_rbi_candidates = [
            same_team_hits_total_bases_candidates[1],
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "matchup": "ATL at NYM",
                "market": "RBI",
                "market_key": "rbi",
                "market_shape": "volume_prop",
                "pick": "Over 1.5",
                "name": "Marcell Ozuna Over 1.5 RBI",
                "team": "ATL",
                "surface_title": "Pregame props",
                "odds": "+145",
                "score": 84.0,
                "market_fit": {"market_key": "rbi", "market_label": "RBI", "market_shape": "volume_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.45, "american_odds": 145, "implied_probability": 40.82},
            },
        ]

        hits_total_bases_parlay = _build_parlays(same_team_hits_total_bases_candidates, limit=1, preferences=preferences)[0]
        total_bases_rbi_parlay = _build_parlays(same_team_total_bases_rbi_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(hits_total_bases_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertEqual(total_bases_rbi_parlay.get("pair_correlation_penalty"), 0.94)
        self.assertIn("Hits + Total bases different players + same team correlation penalty 0.79", hits_total_bases_parlay.get("rationale") or "")
        self.assertIn("Total bases + RBI different players + same team correlation penalty 0.94", total_bases_rbi_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(hits_total_bases_parlay, preferences),
            _parlay_rank_score(total_bases_rbi_parlay, preferences),
        )

    def test_build_parlays_apply_nfl_production_fallback_to_passing_receiving_yards(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        nfl_production_pair_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Passing Yards",
                "market_key": "passing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 274.5",
                "name": "Josh Allen Over 274.5 Passing Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "passing_yards", "market_label": "Passing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Receiving Yards",
                "market_key": "receiving_yards",
                "market_shape": "counting_prop",
                "pick": "Over 84.5",
                "name": "Stefon Diggs Over 84.5 Receiving Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "receiving_yards", "market_label": "Receiving yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        clean_pair_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Passing Yards",
                "market_key": "passing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 274.5",
                "name": "Josh Allen Over 274.5 Passing Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "passing_yards", "market_label": "Passing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "game",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Moneyline",
                "market_key": "moneyline",
                "market_shape": "game_market",
                "pick": "BUF ML",
                "name": "BUF ML",
                "team": "BUF",
                "surface_title": "Pregame board",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "moneyline", "market_label": "Moneyline", "market_shape": "game_market", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        nfl_production_pair_parlay = _build_parlays(nfl_production_pair_candidates, limit=1, preferences=preferences)[0]
        clean_pair_parlay = _build_parlays(clean_pair_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(nfl_production_pair_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertEqual(clean_pair_parlay.get("pair_correlation_penalty"), 0.0)
        self.assertIn("Passing yards + Receiving yards different players + same team correlation penalty 0.98", nfl_production_pair_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(clean_pair_parlay, preferences),
            _parlay_rank_score(nfl_production_pair_parlay, preferences),
        )

    def test_build_parlays_apply_team_context_to_nfl_production_pairs(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Passing Yards",
                "market_key": "passing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 274.5",
                "name": "Josh Allen Over 274.5 Passing Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "passing_yards", "market_label": "Passing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Receiving Yards",
                "market_key": "receiving_yards",
                "market_shape": "counting_prop",
                "pick": "Over 84.5",
                "name": "Stefon Diggs Over 84.5 Receiving Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "receiving_yards", "market_label": "Receiving yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        opposing_team_candidates = [
            same_team_candidates[0],
            {
                **same_team_candidates[1],
                "name": "Travis Kelce Over 84.5 Receiving Yards",
                "team": "KC",
            },
        ]

        same_team_parlay = _build_parlays(same_team_candidates, limit=1, preferences=preferences)[0]
        opposing_team_parlay = _build_parlays(opposing_team_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertEqual(opposing_team_parlay.get("pair_correlation_penalty"), 0.56)
        self.assertIn("Passing yards + Receiving yards different players + same team correlation penalty 0.98", same_team_parlay.get("rationale") or "")
        self.assertIn("Passing yards + Receiving yards different players + opposing teams correlation penalty 0.56", opposing_team_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(opposing_team_parlay, preferences),
            _parlay_rank_score(same_team_parlay, preferences),
        )

    def test_build_parlays_discount_football_production_pair_penalty_for_opposing_directions(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_direction_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Passing Yards",
                "market_key": "passing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 274.5",
                "name": "Josh Allen Over 274.5 Passing Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "passing_yards", "market_label": "Passing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Receiving Yards",
                "market_key": "receiving_yards",
                "market_shape": "counting_prop",
                "pick": "Over 84.5",
                "name": "Stefon Diggs Over 84.5 Receiving Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "receiving_yards", "market_label": "Receiving yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        opposing_direction_candidates = [
            same_direction_candidates[0],
            {
                **same_direction_candidates[1],
                "pick": "Under 84.5",
                "name": "Stefon Diggs Under 84.5 Receiving Yards",
            },
        ]

        same_direction_parlay = _build_parlays(same_direction_candidates, limit=1, preferences=preferences)[0]
        opposing_direction_parlay = _build_parlays(opposing_direction_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_direction_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertEqual(opposing_direction_parlay.get("pair_correlation_penalty"), 0.44)
        self.assertIn("Passing yards + Receiving yards opposing directions + different players + same team correlation penalty 0.44", opposing_direction_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(opposing_direction_parlay, preferences),
            _parlay_rank_score(same_direction_parlay, preferences),
        )

    def test_build_parlays_expose_pair_correlation_breakdown_factors(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        candidates = [
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Passing Yards",
                "market_key": "passing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 274.5",
                "name": "Josh Allen Over 274.5 Passing Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "passing_yards", "market_label": "Passing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Receiving Yards",
                "market_key": "receiving_yards",
                "market_shape": "counting_prop",
                "pick": "Under 84.5",
                "name": "Stefon Diggs Under 84.5 Receiving Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "receiving_yards", "market_label": "Receiving yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        parlay = _build_parlays(candidates, limit=1, preferences=preferences)[0]
        breakdown = parlay.get("pair_correlation_breakdown") or []

        self.assertEqual(parlay.get("pair_correlation_penalty"), 0.44)
        self.assertEqual(len(breakdown), 1)
        self.assertEqual(breakdown[0].get("market_keys"), ["passing_yards", "receiving_yards"])
        self.assertEqual(breakdown[0].get("pair_penalty"), 0.44)
        self.assertEqual(
            breakdown[0].get("feature_profile"),
            {
                "penalty_source": "market_pair",
                "same_game": True,
                "team_relationship": "same_team",
                "subject_relationship": "different_players",
                "direction_relationship": "opposing_directions",
                "market_keys": ["passing_yards", "receiving_yards"],
                "script_cluster_pair": ["football_production", "football_production"],
                "script_context": None,
            },
        )
        factor_kinds = [factor.get("kind") for factor in (breakdown[0].get("factors") or [])]
        self.assertEqual(
            factor_kinds,
            ["base_pair_penalty", "direction_multiplier", "subject_multiplier", "team_multiplier"],
        )
        self.assertEqual((breakdown[0].get("factors") or [])[0].get("source"), "market_pair")
        self.assertEqual((breakdown[0].get("factors") or [])[0].get("value"), 1.25)
        self.assertEqual((breakdown[0].get("factors") or [])[1].get("multiplier"), 0.45)
        self.assertEqual((breakdown[0].get("factors") or [])[1].get("context"), "opposing directions")
        self.assertEqual((breakdown[0].get("factors") or [])[2].get("multiplier"), 0.75)
        self.assertEqual((breakdown[0].get("factors") or [])[3].get("multiplier"), 1.05)

    def test_build_parlays_keep_nfl_passing_receiving_tighter_than_rushing_receiving(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_passing_receiving_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Passing Yards",
                "market_key": "passing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 274.5",
                "name": "Josh Allen Over 274.5 Passing Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "passing_yards", "market_label": "Passing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Receiving Yards",
                "market_key": "receiving_yards",
                "market_shape": "counting_prop",
                "pick": "Over 84.5",
                "name": "Stefon Diggs Over 84.5 Receiving Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "receiving_yards", "market_label": "Receiving yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_rushing_receiving_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Rushing Yards",
                "market_key": "rushing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 62.5",
                "name": "James Cook Over 62.5 Rushing Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "rushing_yards", "market_label": "Rushing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                **same_team_passing_receiving_candidates[1],
            },
        ]

        passing_receiving_parlay = _build_parlays(same_team_passing_receiving_candidates, limit=1, preferences=preferences)[0]
        rushing_receiving_parlay = _build_parlays(same_team_rushing_receiving_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(passing_receiving_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertEqual(rushing_receiving_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertIn("Passing yards + Receiving yards different players + same team correlation penalty 0.98", passing_receiving_parlay.get("rationale") or "")
        self.assertIn("Rushing yards + Receiving yards different players + same team correlation penalty 0.79", rushing_receiving_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(rushing_receiving_parlay, preferences),
            _parlay_rank_score(passing_receiving_parlay, preferences),
        )

    def test_build_parlays_keep_nfl_passing_touchdowns_tighter_than_rushing_receiving(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_rushing_receiving_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Rushing Yards",
                "market_key": "rushing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 62.5",
                "name": "James Cook Over 62.5 Rushing Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "rushing_yards", "market_label": "Rushing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Receiving Yards",
                "market_key": "receiving_yards",
                "market_shape": "counting_prop",
                "pick": "Over 84.5",
                "name": "Stefon Diggs Over 84.5 Receiving Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "receiving_yards", "market_label": "Receiving yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        same_team_passing_touchdowns_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Passing Yards",
                "market_key": "passing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 274.5",
                "name": "Josh Allen Over 274.5 Passing Yards",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "passing_yards", "market_label": "Passing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NFL",
                "sport_slug": "nfl",
                "matchup": "BUF at KC",
                "market": "Touchdowns",
                "market_key": "touchdowns",
                "market_shape": "binary_ceiling_prop",
                "pick": "Over 0.5",
                "name": "James Cook Over 0.5 Touchdowns",
                "team": "BUF",
                "surface_title": "Pregame props",
                "odds": "+110",
                "score": 84.0,
                "market_fit": {"market_key": "touchdowns", "market_label": "Touchdowns", "market_shape": "binary_ceiling_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.10, "american_odds": 110, "implied_probability": 47.62},
            },
        ]

        rushing_receiving_parlay = _build_parlays(same_team_rushing_receiving_candidates, limit=1, preferences=preferences)[0]
        passing_touchdowns_parlay = _build_parlays(same_team_passing_touchdowns_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(rushing_receiving_parlay.get("pair_correlation_penalty"), 0.79)
        self.assertEqual(passing_touchdowns_parlay.get("pair_correlation_penalty"), 1.02)
        self.assertIn("Rushing yards + Receiving yards different players + same team correlation penalty 0.79", rushing_receiving_parlay.get("rationale") or "")
        self.assertIn("Passing yards + Touchdowns different players + same team correlation penalty 1.02", passing_touchdowns_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(rushing_receiving_parlay, preferences),
            _parlay_rank_score(passing_touchdowns_parlay, preferences),
        )

    def test_build_parlays_apply_ncaaf_production_fallback_to_passing_receiving_yards(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        ncaaf_production_pair_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NCAAF",
                "sport_slug": "ncaaf",
                "matchup": "Texas at Oklahoma",
                "market": "Passing Yards",
                "market_key": "passing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 284.5",
                "name": "Quinn Ewers Over 284.5 Passing Yards",
                "team": "Texas",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "passing_yards", "market_label": "Passing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NCAAF",
                "sport_slug": "ncaaf",
                "matchup": "Texas at Oklahoma",
                "market": "Receiving Yards",
                "market_key": "receiving_yards",
                "market_shape": "counting_prop",
                "pick": "Over 88.5",
                "name": "Matthew Golden Over 88.5 Receiving Yards",
                "team": "Texas",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "receiving_yards", "market_label": "Receiving yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]
        clean_pair_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NCAAF",
                "sport_slug": "ncaaf",
                "matchup": "Texas at Oklahoma",
                "market": "Passing Yards",
                "market_key": "passing_yards",
                "market_shape": "counting_prop",
                "pick": "Over 284.5",
                "name": "Quinn Ewers Over 284.5 Passing Yards",
                "team": "Texas",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "passing_yards", "market_label": "Passing yards", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "game",
                "sport": "NCAAF",
                "sport_slug": "ncaaf",
                "matchup": "Texas at Oklahoma",
                "market": "Moneyline",
                "market_key": "moneyline",
                "market_shape": "game_market",
                "pick": "Texas ML",
                "name": "Texas ML",
                "team": "Texas",
                "surface_title": "Pregame board",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "moneyline", "market_label": "Moneyline", "market_shape": "game_market", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        ncaaf_production_pair_parlay = _build_parlays(ncaaf_production_pair_candidates, limit=1, preferences=preferences)[0]
        clean_pair_parlay = _build_parlays(clean_pair_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(ncaaf_production_pair_parlay.get("pair_correlation_penalty"), 0.98)
        self.assertEqual(clean_pair_parlay.get("pair_correlation_penalty"), 0.0)
        self.assertIn("Passing yards + Receiving yards different players + same team correlation penalty 0.98", ncaaf_production_pair_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(clean_pair_parlay, preferences),
            _parlay_rank_score(ncaaf_production_pair_parlay, preferences),
        )

    def test_build_parlays_use_market_specific_opposing_team_discount(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        opposing_team_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Jayson Tatum Over 28.5",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jalen Brunson Over 2.5 3PM",
                "team": "NYK",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        opposing_team_parlay = _build_parlays(opposing_team_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(opposing_team_parlay.get("pair_correlation_penalty"), 0.77)
        self.assertIn("shared usage script + different players + opposing teams correlation penalty 0.77", opposing_team_parlay.get("rationale") or "")

    def test_build_parlays_blend_script_cluster_into_explicit_same_team_points_threes(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        same_team_candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Jayson Tatum Over 28.5",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Jaylen Brown Over 2.5 3PM",
                "team": "BOS",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        same_team_parlay = _build_parlays(same_team_candidates, limit=1, preferences=preferences)[0]

        self.assertEqual(same_team_parlay.get("pair_correlation_penalty"), 1.3)
        self.assertIn("shared usage script + different players + same team correlation penalty 1.3", same_team_parlay.get("rationale") or "")
        self.assertEqual((same_team_parlay.get("legs") or [])[0].get("team_key"), "bos")
        self.assertEqual((same_team_parlay.get("legs") or [])[1].get("team_key"), "bos")

    def test_default_medium_allows_existing_same_game_shape_stack(self) -> None:
        preferences = _query_preferences("Build me a same game three-leg parlay")
        legs = (
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "AST",
                "market_shape": "counting_prop",
                "pick": "Over 6.5",
            },
            {
                "candidate_type": "prop",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
            },
        )

        self.assertTrue(_parlay_matches_preferences(legs, preferences))

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
                            "question": "Build a two-leg parlay from the best live and pregame NBA edges with a $100 bankroll and max 20% exposure",
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
        recommendations = result.get("recommendations") or []
        live_recommendation = next((item for item in recommendations if item.get("is_live")), None)
        self.assertIsNotNone(live_recommendation)
        self.assertEqual(live_recommendation.get("odds_refreshed_at"), "2026-06-04T16:03:08Z")
        self.assertEqual(live_recommendation.get("freshness_label"), "Updated 11:03 AM CT")
        self.assertIn("Board freshness: Updated 11:03 AM CT.", live_recommendation.get("rationale") or "")

        first_parlay = (result.get("parlays") or [])[0]
        self.assertIsNotNone(first_parlay.get("combined_odds"))
        self.assertIsNotNone(first_parlay.get("combined_decimal_odds"))
        self.assertIsNotNone(first_parlay.get("combined_implied_probability"))
        parsed_request = result.get("parsed_request") or {}
        self.assertTrue(parsed_request.get("chips"))
        self.assertIn("$100 bankroll", parsed_request.get("chips") or [])
        self.assertIn("Max 20% exposure", parsed_request.get("chips") or [])
        self.assertEqual(first_parlay.get("bankroll_amount"), 100)
        self.assertEqual(first_parlay.get("max_exposure_pct"), 20)
        self.assertEqual(first_parlay.get("suggested_stake"), 20.0)
        self.assertEqual(first_parlay.get("suggested_total_exposure"), 20.0)
        self.assertEqual(first_parlay.get("exposure_cap_amount"), 20.0)
        self.assertEqual(first_parlay.get("exposure_cap_source"), "requested_exposure_cap")
        self.assertIn("Suggested stake $20.00 respects the requested exposure cap.", first_parlay.get("rationale") or "")

    def test_game_candidate_summary_exposes_freshness(self) -> None:
        sport = _sample_overview()[0]
        game = (sport.get("dashboard_games") or [])[0]

        candidates = _game_bet_candidates_from_game(sport, game, fallback_epoch=0.0)

        self.assertTrue(candidates)
        candidate = dict(candidates[0])
        candidate["candidate_type"] = "game"

        summary = _candidate_summary(candidate)

        self.assertEqual(summary.get("odds_refreshed_at"), "2026-06-04T15:55:00Z")
        self.assertEqual(summary.get("freshness_label"), "Updated 10:55 AM CT")
        self.assertIn("Board freshness: Updated 10:55 AM CT.", summary.get("rationale") or "")

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
                            "question": "Build me a four-leg round robin from the best NBA edges with a $120 bankroll and max 25% exposure",
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
        self.assertTrue(all(parlay.get("suggested_total_exposure") == 30.0 for parlay in parlays))
        self.assertTrue(all(parlay.get("suggested_stake") == 5.0 for parlay in parlays))
        self.assertTrue(all(parlay.get("exposure_cap_source") == "requested_exposure_cap" for parlay in parlays))
        self.assertTrue(all("Suggested stake $5.00 per ticket keeps the full set within a $30.00 exposure cap." in (parlay.get("rationale") or "") for parlay in parlays))

    def test_intelligence_query_trims_round_robin_anchor_for_tight_exposure_caps(self) -> None:
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
                            "question": "Build me a four-leg round robin from the best NBA edges with a $100 bankroll and max 5% exposure",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("parlay_type") == "round_robin" for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_group_size") == 3 for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_unit") == 2 for parlay in parlays))
        self.assertEqual(len(parlays), 3)
        self.assertTrue(all(parlay.get("suggested_total_exposure") == 5.0 for parlay in parlays))
        self.assertTrue(all(parlay.get("suggested_stake") == 1.67 for parlay in parlays))

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