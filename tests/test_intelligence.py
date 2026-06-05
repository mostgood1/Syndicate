from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.features.intelligence import _advanced_signals_from_item
from syndicate.features.intelligence import _advanced_input_rows_for_sport
from syndicate.features.intelligence import _advanced_signals_from_item
from syndicate.features.intelligence import _build_parlays
from syndicate.features.intelligence import _candidate_advanced_signal_score
from syndicate.features.intelligence import _basketball_source_summary_score
from syndicate.features.intelligence import _candidate_market_fit
from syndicate.features.intelligence import _parlay_matches_preferences
from syndicate.features.intelligence import _parlay_rank_score
from syndicate.features.intelligence import _query_preferences
from syndicate.features.intelligence import run_intelligence_query


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
                            "team_pace_signal": 1.08,
                            "usage_rate_advanced": 1.14,
                            "shot_profile_advanced": 1.06,
                            "minutes_role_advanced": 1.03,
                            "projected": 31.8,
                            "line": 28.5,
                            "odds": "+102",
                            "confidence": "63%",
                            "edge": "+5.4%",
                            "basketball_summary": "Recent form is already clearing this number with a last-five average of 31.2. The last-10 sample is still above this number at 30.1, so the over is not just riding a short heater. Last game landed at 33.0, which keeps the most recent touch well above the book.",
                            "why_explain": "Projected minutes (36.0) sit above his last-10 workload (34.0), which strengthens the volume path.",
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
                            "team_pace_signal": 1.08,
                            "usage_rate_advanced": 1.14,
                            "shot_profile_advanced": 1.06,
                            "minutes_role_advanced": 1.03,
                            "projected": 4.9,
                            "live_projection": 5.8,
                            "actual": 3,
                            "line": 4.5,
                            "odds": "+118",
                            "confidence": "61%",
                            "edge": "+4.1%",
                            "basketball_summary": "Recent form is already clearing this number with a last-five average of 5.1. The last-10 sample is still above this number at 4.8, so the over is not just riding a short heater. Last game landed at 6.0, which keeps the recent shot volume above the book.",
                            "why_explain": "Projected minutes (35.0) sit above his last-10 workload (33.0), which strengthens the volume path.",
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
                            "team_environment_advanced": 1.12,
                            "possession_profile_advanced": 1.05,
                            "matchup_pressure_advanced": 1.09,
                            "rotation_pressure_advanced": 1.03,
                            "live_shift_advanced": 1.01,
                            "projected": 28.1,
                            "line": 24.5,
                            "odds": "+102",
                            "confidence": "63%",
                            "edge": "+5.4%",
                            "basketball_summary": "Recent form is already clearing this number with a last-five average of 28.4. The last-10 sample is still above this number at 26.8, so the over is not just riding a short heater. Last game landed at 29.0, which keeps the most recent result on the right side of the number.",
                            "why_explain": "Projected minutes (34.0) sit above his last-10 workload (31.5), which strengthens the volume path.",
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


def _sample_mlb_statcast_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "mlb",
            "name": "MLB",
            "context_label": "2026-06-05",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Aaron Judge Over 0.5 Home Runs",
                            "market": "HR",
                            "pick": "Over 0.5",
                            "matchup": "NYY at BOS",
                            "batter_id": 608324,
                            "opponent_pitcher_id": 605400,
                            "projected": 0.68,
                            "line": 0.5,
                            "odds": "+118",
                            "confidence": "57%",
                            "edge": "+2.4%",
                            "writeup": "Power shape is trending up.",
                            "display_pills": ["Line 0.5", "Odds +118"],
                            "batter_statcast_hr_mult": 1.24,
                            "pitcher_statcast_hr_mult": 1.09,
                            "bvp_history_source": "derived_statcast",
                            "href": "/mlb/props?date=2026-06-05",
                        },
                        {
                            "name": "Mookie Betts Over 1.5 Hits",
                            "market": "Hits",
                            "pick": "Over 1.5",
                            "matchup": "LAD at SF",
                            "batter_id": 605141,
                            "opponent_pitcher_id": 657277,
                            "projected": 1.64,
                            "line": 1.5,
                            "odds": "+118",
                            "confidence": "57%",
                            "edge": "+2.4%",
                            "writeup": "Contact quality is steady.",
                            "display_pills": ["Line 1.5", "Odds +118"],
                            "batter_statcast_inplay_mult": 1.01,
                            "pitcher_statcast_inplay_mult": 1.0,
                            "href": "/mlb/props?date=2026-06-05",
                        },
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_mlb_market_overview() -> list[dict[str, object]]:
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
                            "batter_id": 592450,
                            "opponent_pitcher_id": 519242,
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
                            "batter_id": 518692,
                            "opponent_pitcher_id": 543037,
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


def _sample_mlb_risk_overview() -> list[dict[str, object]]:
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
                            "name": "Freddie Freeman Over 1.5 Total Bases",
                            "market": "Hitter Total Bases",
                            "pick": "Over 1.5",
                            "matchup": "LAD at SD",
                            "projected": 2.0,
                            "line": 1.5,
                            "odds": "-135",
                            "confidence": "64%",
                            "edge": "+2.5%",
                            "score": 88.0,
                            "writeup": "High-contact shape and lineup spot support the floor.",
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                        {
                            "name": "Aaron Judge Over 0.5 Home Runs",
                            "market": "Hitter Home Runs",
                            "pick": "Over 0.5",
                            "matchup": "NYY at BOS",
                            "projected": 0.62,
                            "line": 0.5,
                            "odds": "+320",
                            "confidence": "38%",
                            "edge": "+12.8%",
                            "score": 87.0,
                            "writeup": "Barrel rate and pull-side lift create the ceiling case.",
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


def _sample_mlb_compare_overview() -> list[dict[str, object]]:
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
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                        {
                            "name": "Shohei Ohtani Over 0.5 Home Runs",
                            "market": "Hitter Home Runs",
                            "pick": "Over 0.5",
                            "matchup": "LAD at SD",
                            "projected": 0.58,
                            "line": 0.5,
                            "odds": "+295",
                            "confidence": "25%",
                            "edge": "+2.7%",
                            "writeup": "Pulled-air damage and lift support the HR path.",
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
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                    ],
                },
                "live": {
                    "title": "Top Live Props",
                    "items": [
                        {
                            "name": "Aaron Judge Over 1.5 Hits",
                            "market": "Hits",
                            "pick": "Over 1.5",
                            "matchup": "NYY at BOS",
                            "projected": 1.8,
                            "live_projection": 2.0,
                            "actual": 1,
                            "line": 1.5,
                            "odds": "+125",
                            "confidence": "57%",
                            "edge": "+4.1%",
                            "writeup": "Live contact shape still favors another knock.",
                            "is_live": True,
                            "href": "/mlb/live-lens?date=2026-06-04",
                        },
                        {
                            "name": "Mookie Betts Over 1.5 Hits",
                            "market": "Hits",
                            "pick": "Over 1.5",
                            "matchup": "LAD at SD",
                            "projected": 1.7,
                            "live_projection": 1.9,
                            "actual": 1,
                            "line": 1.5,
                            "odds": "+118",
                            "confidence": "55%",
                            "edge": "+3.4%",
                            "writeup": "Ball-in-play quality is still carrying the lane.",
                            "is_live": True,
                            "href": "/mlb/live-lens?date=2026-06-04",
                        },
                    ],
                },
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_nfl_market_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nfl",
            "name": "NFL",
            "context_label": "2026-09-10",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "CeeDee Lamb Over 86.5 Receiving Yards",
                            "market": "Receiving Yards",
                            "pick": "Over 86.5",
                            "matchup": "DAL at PHI",
                            "off_epa_advanced": 1.11,
                            "target_share_advanced": 0.29,
                            "pass_rate_advanced": 1.07,
                            "air_yards_advanced": 1.13,
                            "projected": 94.1,
                            "line": 86.5,
                            "odds": "+105",
                            "confidence": "61%",
                            "edge": "+4.4%",
                            "writeup": "Target share and matchup support the receiving ceiling.",
                            "display_pills": ["Line 86.5", "Odds +105"],
                            "href": "/nfl/props?date=2026-09-10",
                        }
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_nhl_market_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nhl",
            "name": "NHL",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {"title": "Pregame props", "items": []},
                "live": {
                    "title": "Top Live Props",
                    "items": [
                        {
                            "name": "Nathan MacKinnon Over 4.5 Shots",
                            "market": "Shots",
                            "pick": "Over 4.5",
                            "matchup": "COL at EDM",
                            "projected": 5.2,
                            "live_projection": 5.8,
                            "actual": 3,
                            "line": 4.5,
                            "odds": "+110",
                            "confidence": "60%",
                            "edge": "+3.7%",
                            "writeup": "Volume is holding even after the live move.",
                            "display_pills": ["Line 4.5", "Odds +110", "Live Proj 5.8"],
                            "is_live": True,
                            "href": "/nhl/live?date=2026-06-04",
                        }
                    ],
                },
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
        preferences = _query_preferences("Build a same game round robin with low correlation and aggressive cross-sport upside")

        self.assertEqual(preferences.get("parlay_type"), "round_robin")
        self.assertTrue(preferences.get("cross_sport_required"))
        self.assertEqual(preferences.get("risk_profile"), "aggressive")
        self.assertEqual(preferences.get("correlation_tolerance"), "low")
        self.assertEqual(preferences.get("round_robin_unit"), 2)

    def test_query_preferences_parses_market_focus_and_bankroll_controls(self) -> None:
        preferences = _query_preferences("Build me a live ML parlay with medium correlation, $100 bankroll, and max 20% exposure")

        self.assertEqual(preferences.get("intent"), "parlay")
        self.assertTrue(preferences.get("live_only"))
        self.assertFalse(preferences.get("pregame_only"))
        self.assertEqual(preferences.get("requested_markets"), ["moneyline"])
        self.assertEqual(preferences.get("correlation_tolerance"), "medium")
        self.assertTrue(preferences.get("correlation_explicit"))
        self.assertEqual(preferences.get("bankroll_amount"), 100)
        self.assertEqual(preferences.get("max_exposure_pct"), 20)

    def test_query_preferences_infers_baseball_market_focus(self) -> None:
        preferences = _query_preferences("Who are the top 3 strikeout targets for today?")

        self.assertEqual(preferences.get("requested_sports"), ["mlb"])
        self.assertEqual(preferences.get("requested_markets"), ["strikeouts"])
        self.assertTrue(preferences.get("include_props"))
        self.assertFalse(preferences.get("include_games"))
        self.assertEqual(preferences.get("limit"), 3)

    def test_query_preferences_extracts_requested_date(self) -> None:
        preferences = _query_preferences("Who are the top 3 strikeout targets for 20260604?")

        self.assertEqual(preferences.get("requested_date"), "2026-06-04")

    def test_run_intelligence_query_uses_question_date_when_date_not_passed(self) -> None:
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_market_overview()) as build_overview:
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    result = run_intelligence_query("Who are the top 3 strikeout targets for 2026-06-04?")

        self.assertEqual(result.get("selected_date"), "2026-06-04")
        build_overview.assert_called_once()
        self.assertEqual(build_overview.call_args.kwargs.get("selected_date"), "2026-06-04")

    def test_query_preferences_does_not_infer_nba_from_wnba_token(self) -> None:
        preferences = _query_preferences("Explain the best WNBA matchup targets today with a table and chart.")

        self.assertEqual(preferences.get("requested_sports"), ["wnba"])

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

        first_parlay = (result.get("parlays") or [])[0]
        self.assertIsNotNone(first_parlay.get("combined_odds"))
        self.assertIsNotNone(first_parlay.get("combined_decimal_odds"))
        self.assertIsNotNone(first_parlay.get("combined_implied_probability"))
        self.assertEqual(first_parlay.get("bankroll_amount"), 100)
        self.assertEqual(first_parlay.get("max_exposure_pct"), 20)
        self.assertEqual(first_parlay.get("suggested_stake"), 20.0)
        self.assertEqual(first_parlay.get("suggested_total_exposure"), 20.0)
        self.assertEqual(first_parlay.get("exposure_cap_amount"), 20.0)
        self.assertEqual(first_parlay.get("exposure_cap_source"), "requested_exposure_cap")
        self.assertIn("Suggested stake $20.00 respects the requested exposure cap.", first_parlay.get("rationale") or "")
        parsed_request = result.get("parsed_request") or {}
        self.assertTrue(parsed_request.get("chips"))
        self.assertIn("$100 bankroll", parsed_request.get("chips") or [])
        self.assertIn("Max 20% exposure", parsed_request.get("chips") or [])

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

    def test_intelligence_query_surfaces_direct_statcast_signals(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Pitch mix"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_statcast_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Give me the best MLB props using Statcast data",
                            "date": "2026-06-05",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        result = payload.get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertGreaterEqual(len(recommendations), 2)
        first = recommendations[0]
        self.assertEqual(first.get("market"), "HR")
        self.assertTrue(first.get("advanced_signals"))
        self.assertIn("batter_statcast_hr_mult", {item.get("key") for item in first.get("advanced_signals") or []})
        self.assertIn("Candidate-level advanced signals", first.get("rationale") or "")
        self.assertGreater(float(first.get("advanced_signal_score") or 0.0), 0.0)

    def test_intelligence_query_builds_home_run_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Pitch mix"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_statcast_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "What are the best home run matchups today and why? Build a top 10 table and chart.",
                            "date": "2026-06-05",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        result = payload.get("response") or {}
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual((result.get("analysis_views") or {}).get("focus"), "mlb_home_runs")
        self.assertEqual(parsed_request.get("intent"), "best_bets")
        self.assertEqual((result.get("analysis_views") or {}).get("table", {}).get("title"), "Top 10 likely HR targets")
        self.assertTrue((result.get("analysis_views") or {}).get("table", {}).get("rows"))
        self.assertTrue((result.get("analysis_views") or {}).get("chart", {}).get("rows"))
        first_row = ((result.get("analysis_views") or {}).get("table", {}).get("rows") or [])[0]
        self.assertIn("batter_hr_mult", first_row)
        self.assertIn("pitcher_hr_mult", first_row)
        self.assertIn("why", first_row)

    def test_intelligence_query_uses_mlb_hr_artifact_candidates_when_home_rails_are_empty(self) -> None:
        overview = [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-06-05",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {"title": "Pregame props", "items": []},
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        hr_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "surface_key": "pregame",
                "surface_title": "HR targets",
                "name": "Aaron Judge",
                "market": "Home Runs",
                "market_key": "home_runs",
                "pick": "Over 0.5",
                "matchup": "NYY at BOS",
                "line": "0.5",
                "odds": "-",
                "projected": "-",
                "confidence": "24.1%",
                "edge": "-",
                "score": 91.0,
                "href": "/mlb/hr-targets?date=2026-06-05",
                "href_label": "Open HR board",
                "writeup": "Expected opportunity is strong and the handedness split is favorable.",
                "display_pills": ["HR Prob 24.1%", "Support 67"],
                "advanced_signals": [
                    {"key": "batter_statcast_hr_mult", "label": "Batter Statcast home-run multiplier", "value": 1.24},
                    {"key": "pitcher_statcast_hr_mult", "label": "Pitcher Statcast home-run multiplier", "value": 1.11},
                ],
                "batter_id": 608324,
                "opponent_pitcher_id": 605400,
            }
        ]
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Pitch mix"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence._mlb_home_run_candidates_from_artifact", return_value=hr_candidates):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "question": "What are the best home run matchups today and why? Build a top 10 table and chart.",
                                "date": "2026-06-05",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        self.assertEqual(result.get("headline"), "The Syndicate home runs board")
        self.assertTrue(result.get("recommendations"))
        self.assertEqual((result.get("recommendations") or [])[0].get("sport_slug"), "mlb")
        self.assertEqual(((result.get("analysis_views") or {}).get("table") or {}).get("rows")[0].get("player"), "Aaron Judge")

    def test_intelligence_query_builds_nba_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Usage", "Shot profile"],
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
                            "question": "Explain the best NBA matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "nba_matchups")
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))
        self.assertTrue((analysis_views.get("chart") or {}).get("rows"))
        self.assertIn("last_game_delta_signal", (analysis_views.get("chart") or {}).get("series") or [])
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertIn("market_fit_score", first_row)
        self.assertEqual(first_row.get("analysis_shape"), "nba_usage_creation")
        self.assertEqual(first_row.get("pace_signal"), 1.08)
        self.assertEqual(first_row.get("usage_signal"), 1.14)
        self.assertEqual(first_row.get("shot_profile_signal"), 1.06)
        self.assertGreater(first_row.get("last5_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last10_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last_game_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("workload_delta_signal") or 0.0, 0.0)
        self.assertIn("why", first_row)
        concrete_nba_writeups = {
            "Projection is clearing the number with usage and minutes support.",
            "The live model is still above the book after the in-game adjustment.",
        }
        self.assertTrue(any(text in (first_row.get("why") or "") for text in concrete_nba_writeups))
        self.assertTrue(any(text in ((result.get("recommendations") or [])[0].get("rationale") or "") for text in concrete_nba_writeups))

    def test_intelligence_query_builds_wnba_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Team environment and pace layer",
                "metrics": ["Team environment", "Possession profile", "Matchup pressure"],
                "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_overview_with_secondary_sport()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Explain the top 2 WNBA matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                            "limit": 2,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        parsed_request = result.get("parsed_request") or {}
        recommendations = result.get("recommendations") or []
        self.assertEqual(analysis_views.get("focus"), "wnba_matchups")
        self.assertEqual(parsed_request.get("sports"), ["WNBA"])
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))
        self.assertIn("last_game_delta_signal", (analysis_views.get("chart") or {}).get("series") or [])
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].get("sport_slug"), "wnba")
        self.assertEqual(first_row.get("analysis_shape"), "wnba_role_pressure")
        self.assertEqual(first_row.get("team_environment_signal"), 1.12)
        self.assertEqual(first_row.get("possession_profile_signal"), 1.05)
        self.assertEqual(first_row.get("matchup_pressure_signal"), 1.09)
        self.assertGreater(first_row.get("last5_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last10_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last_game_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("workload_delta_signal") or 0.0, 0.0)
        self.assertIn("Projection is clearing the number with stable volume.", first_row.get("why") or "")
        self.assertIn("Projection is clearing the number with stable volume.", recommendations[0].get("rationale") or "")

    def test_intelligence_query_uses_basketball_source_summary_without_writeup(self) -> None:
        overview = _sample_overview_with_secondary_sport()
        wnba_item = ((((overview[1].get("home_rails") or {}).get("pregame") or {}).get("items") or [])[0])
        wnba_item.pop("writeup", None)
        wnba_item["basketball_summary"] = "Source matchup summary says the volume is stable and the defense is yielding clean looks."
        wnba_item["why_explain"] = "Primary creator workload remains intact in this matchup."
        wnba_item["basketball_reasons"] = [
            "Opponent is allowing efficient pull-up attempts.",
            "Projected role remains unchanged.",
        ]
        advanced_rows = [
            {
                "label": "Team environment and pace layer",
                "metrics": ["Team environment", "Possession profile", "Matchup pressure"],
                "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
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
                            "question": "Explain the top 2 WNBA matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                            "limit": 2,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        first_recommendation = (result.get("recommendations") or [])[0]
        self.assertIn("Source matchup summary says the volume is stable", first_row.get("why") or "")
        self.assertIn("Source matchup summary says the volume is stable", first_recommendation.get("rationale") or "")

    def test_intelligence_query_builds_ncaab_analysis_views(self) -> None:
        overview = [
            {
                "slug": "ncaab",
                "name": "NCAAB",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Braden Smith Over 15.5 PA",
                                "market": "PA",
                                "pick": "Over 15.5",
                                "matchup": "PUR at ILL",
                                "tempo_bucket_advanced": 1.07,
                                "volatility_advanced": 1.03,
                                "minutes_role_advanced": 1.05,
                                "projected": 18.4,
                                "line": 15.5,
                                "odds": "+101",
                                "confidence": "61%",
                                "edge": "+4.0%",
                                "basketball_summary": "Recent form is already clearing this number with a last-five average of 18.8. The last-10 sample is still above this number at 17.9, so the over is not just riding a short heater. Last game landed at 19.0, which keeps the most recent touch above the book.",
                                "why_explain": "Projected minutes (36.0) sit above his last-10 workload (33.5), which strengthens the volume path.",
                                "writeup": "Projection is clearing the number in a stable role.",
                                "href": "/ncaab/prop-ladders?date=2026-06-04",
                            }
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
                "label": "College pace and volatility layer",
                "metrics": ["Tempo", "Volatility", "Role"],
                "path": "data/ncaab_source/data/processed/recommendations_2026-06-04.json",
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
                            "question": "Explain the best NCAAB matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "ncaab_matchups")
        self.assertIn("last_game_delta_signal", (analysis_views.get("chart") or {}).get("series") or [])
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("analysis_shape"), "ncaab_tempo_volatility")
        self.assertEqual(first_row.get("tempo_bucket_signal"), 1.07)
        self.assertEqual(first_row.get("volatility_signal"), 1.03)
        self.assertGreater(first_row.get("last5_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last10_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last_game_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("workload_delta_signal") or 0.0, 0.0)
        self.assertIn("Projection is clearing the number in a stable role.", first_row.get("why") or "")

    def test_basketball_market_fit_scoring_diverges_by_league(self) -> None:
        market_context = {
            "american_odds": 102,
            "decimal_odds": 2.02,
            "implied_probability": 49.5,
            "model_probability": 63.0,
            "price_edge_pct": 13.5,
        }
        shared_fields = {
            "candidate_type": "prop",
            "market": "PTS",
            "pick": "Over 24.5",
            "line": 24.5,
            "projected": 28.1,
            "odds": "+102",
            "confidence": "63%",
            "edge": "+5.4%",
        }

        nba_fit = _candidate_market_fit(
            {
                **shared_fields,
                "sport_slug": "nba",
                "name": "Jayson Tatum Over 24.5",
            },
            market_context,
        )
        wnba_fit = _candidate_market_fit(
            {
                **shared_fields,
                "sport_slug": "wnba",
                "name": "A'ja Wilson Over 24.5",
            },
            market_context,
        )

        self.assertEqual(nba_fit.get("market_shape"), "counting_prop")
        self.assertEqual(wnba_fit.get("market_shape"), "counting_prop")
        self.assertEqual(nba_fit.get("market_shape_detail"), "nba_usage_creation")
        self.assertEqual(wnba_fit.get("market_shape_detail"), "wnba_role_pressure")
        self.assertGreater(nba_fit.get("market_fit_score") or 0.0, wnba_fit.get("market_fit_score") or 0.0)
        self.assertIn("nba usage creation", nba_fit.get("market_fit_note") or "")
        self.assertIn("wnba role pressure", wnba_fit.get("market_fit_note") or "")

    def test_advanced_signal_score_handles_share_based_metrics(self) -> None:
        item = ((
            (_sample_nfl_market_overview()[0].get("home_rails") or {}).get("pregame") or {}
        ).get("items") or [])[0]
        signals = _advanced_signals_from_item(item)

        self.assertIn("target_share_advanced", {signal.get("key") for signal in signals})
        score = _candidate_advanced_signal_score(
            {
                "market": item.get("market"),
                "pick": item.get("pick"),
                "name": item.get("name"),
                "advanced_signals": signals,
            }
        )

        self.assertGreater(score, 0.0)

    def test_basketball_source_summary_score_is_direction_aware(self) -> None:
        over_score = _basketball_source_summary_score(
            {
                "candidate_type": "prop",
                "sport_slug": "wnba",
                "pick": "Over 18.5",
                "line": 18.5,
                "summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater.",
            }
        )
        under_score = _basketball_source_summary_score(
            {
                "candidate_type": "prop",
                "sport_slug": "wnba",
                "pick": "Over 18.5",
                "line": 18.5,
                "summary": "Recent form has stayed below this line with a last-five average of 12.6. The last-10 sample is holding under this line at 9.0, which supports the lower-volume case.",
            }
        )

        self.assertGreater(over_score, 0.0)
        self.assertLess(under_score, 0.0)

    def test_advanced_signals_extract_basketball_summary_deltas(self) -> None:
        signals = _advanced_signals_from_item(
            {
                "line": 18.5,
                "basketball_summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater.",
                "why_explain": "Projected minutes (32.0) sit above his last-10 workload (30.0), which strengthens the volume path.",
            }
        )

        signal_keys = {signal.get("key") for signal in signals}
        self.assertIn("basketball_last5_delta", signal_keys)
        self.assertIn("basketball_last10_delta", signal_keys)
        self.assertIn("basketball_minutes_workload_delta", signal_keys)

    def test_advanced_signal_score_handles_basketball_summary_deltas(self) -> None:
        signals = _advanced_signals_from_item(
            {
                "line": 18.5,
                "basketball_summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater.",
            }
        )

        score = _candidate_advanced_signal_score(
            {
                "market": "PA",
                "pick": "Over 18.5",
                "name": "Chelsea Gray Over 18.5 PA",
                "advanced_signals": signals,
            }
        )

        self.assertGreater(score, 0.0)

    def test_intelligence_query_ranks_basketball_candidates_using_source_summary(self) -> None:
        overview = [
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
                                "name": "Chelsea Gray Over 18.5 PA",
                                "market": "PA",
                                "pick": "Over 18.5",
                                "matchup": "LVA at SEA",
                                "team_environment_advanced": 1.05,
                                "possession_profile_advanced": 1.03,
                                "matchup_pressure_advanced": 1.04,
                                "projected": 18.9,
                                "line": 18.5,
                                "odds": "+102",
                                "confidence": "60%",
                                "edge": "+3.0%",
                                "basketball_summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater.",
                                "href": "/wnba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Jackie Young Over 13.5 RA",
                                "market": "RA",
                                "pick": "Over 13.5",
                                "matchup": "LVA at SEA",
                                "team_environment_advanced": 1.05,
                                "possession_profile_advanced": 1.03,
                                "matchup_pressure_advanced": 1.04,
                                "projected": 13.9,
                                "line": 13.5,
                                "odds": "+102",
                                "confidence": "60%",
                                "edge": "+3.0%",
                                "basketball_summary": "Recent form has stayed below this line with a last-five average of 12.6. The last-10 sample is holding under this line at 9.0, which supports the lower-volume case.",
                                "href": "/wnba/prop-ladders?date=2026-06-04",
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
                "label": "Team environment and pace layer",
                "metrics": ["Team environment", "Possession profile", "Matchup pressure"],
                "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
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
                            "question": "Explain the top 2 WNBA matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                            "limit": 2,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertEqual(len(recommendations), 2)
        self.assertEqual(recommendations[0].get("name"), "Chelsea Gray Over 18.5 PA")
        self.assertGreater(float(recommendations[0].get("source_summary_score") or 0.0), 0.0)
        self.assertLess(float(recommendations[1].get("source_summary_score") or 0.0), 0.0)

    def test_advanced_input_rows_include_basketball_pbp_recap(self) -> None:
        rows = _advanced_input_rows_for_sport(
            {
                "slug": "nba",
                "name": "NBA",
                "context_label": "2026-05-28",
            },
            set(),
        )

        pbp_row = next((row for row in rows if row.get("label") == "Play-by-play live recap"), None)
        self.assertIsNotNone(pbp_row)
        self.assertTrue((pbp_row or {}).get("exists"))
        self.assertIn("Recent scoring run", (pbp_row or {}).get("metrics") or [])

    def test_advanced_input_rows_include_ncaab_pbp_recap(self) -> None:
        rows = _advanced_input_rows_for_sport(
            {
                "slug": "ncaab",
                "name": "NCAAB",
                "context_label": "2026-04-06",
            },
            set(),
        )

        pbp_row = next((row for row in rows if row.get("label") == "Play-by-play derived live recap"), None)
        self.assertIsNotNone(pbp_row)
        self.assertTrue((pbp_row or {}).get("exists"))
        self.assertIn("Points per possession", (pbp_row or {}).get("metrics") or [])

    def test_intelligence_query_builds_football_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Weekly recommendation snapshot",
                "metrics": ["EPA", "Pace", "Target share"],
                "path": "data/nfl_source/data/processed/recommendations_2026_wk1.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_nfl_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Explain the best NFL receiving yards targets today with a table and chart.",
                            "date": "2026-09-10",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "football_markets")
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("market_label"), "Receiving yards")
        self.assertEqual(first_row.get("off_epa_signal"), 1.11)
        self.assertEqual(first_row.get("target_share_signal"), 0.29)
        self.assertEqual(first_row.get("pass_rate_signal"), 1.07)

    def test_intelligence_query_builds_hockey_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Props recommendation layer",
                "metrics": ["Shot volume", "Game state", "Market depth"],
                "path": "data/nhl_source/data/processed/props_recommendations_2026-06-04.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_nhl_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Explain the best live NHL shots targets with a table and chart.",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "hockey_props")
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))

    def test_intelligence_query_builds_mlb_strikeout_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Whiff shape", "Pitch mix", "xwOBA"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        statcast_payload = {
            "meta": {"generated_at": "2026-06-04T10:00:00Z"},
            "batters": {
                "592450": {
                    "overall": {"xwoba": 0.301},
                    "mult_overall": {"k": 1.19},
                }
            },
            "pitchers": {
                "519242": {
                    "overall": {"xwoba": 0.284},
                    "mult_overall": {"k": 1.27},
                    "pitch_mix": {"FF": 0.46, "SL": 0.31, "CH": 0.15},
                }
            },
        }
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence._mlb_statcast_feature_payload", return_value=statcast_payload):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "question": "Explain the best MLB strikeout matchups today with a table and chart.",
                                "date": "2026-06-04",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "mlb_props")
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("market_key"), "strikeouts")
        self.assertEqual(first_row.get("pitcher_k_mult"), 1.27)
        self.assertEqual(first_row.get("batter_k_mult"), 1.19)
        self.assertIn("pitch mix", first_row.get("why") or "")

    def test_intelligence_query_builds_mlb_total_bases_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Exit velocity", "Hard-hit rate", "xwOBA"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        statcast_payload = {
            "meta": {"generated_at": "2026-06-04T10:00:00Z"},
            "batters": {
                "518692": {
                    "overall": {"ev_mean": 92.8, "hardhit_rate": 0.487, "xwoba": 0.391},
                    "mult_overall": {"inplay": 1.14},
                }
            },
            "pitchers": {
                "543037": {
                    "overall": {"xwoba": 0.347},
                    "mult_overall": {"inplay": 1.08},
                    "pitch_mix": {"SI": 0.37, "SL": 0.29, "CH": 0.18},
                }
            },
        }
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence._mlb_statcast_feature_payload", return_value=statcast_payload):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "question": "Explain the best MLB total bases targets today with a table and chart.",
                                "date": "2026-06-04",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "mlb_props")
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("market_key"), "total_bases")
        self.assertEqual(first_row.get("batter_inplay_mult"), 1.14)
        self.assertEqual(first_row.get("pitcher_inplay_mult"), 1.08)
        self.assertEqual(first_row.get("batter_hardhit_rate"), 48.7)
        self.assertIn("in-play mult", first_row.get("why") or "")

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
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_market_overview()):
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

    def test_query_preferences_treats_high_confidence_as_conservative(self) -> None:
        preferences = _query_preferences("Show me the highest confidence live MLB props today")

        self.assertEqual(preferences.get("risk_profile"), "conservative")
        self.assertTrue(preferences.get("live_only"))
        self.assertEqual(preferences.get("requested_sports"), ["mlb"])

    def test_intelligence_query_prioritizes_conservative_non_parlay_props(self) -> None:
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_risk_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Show me the highest confidence MLB props today",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].get("name"), "Freddie Freeman Over 1.5 Total Bases")
        self.assertEqual((result.get("parsed_request") or {}).get("risk_profile"), "conservative")

    def test_intelligence_query_prioritizes_aggressive_non_parlay_props(self) -> None:
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_risk_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Show me the highest-upside MLB props today",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].get("name"), "Aaron Judge Over 0.5 Home Runs")
        self.assertEqual((result.get("parsed_request") or {}).get("risk_profile"), "aggressive")

    def test_intelligence_query_builds_subject_comparison_view(self) -> None:
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_compare_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Compare Judge vs Ohtani home run outlook today",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        self.assertIn("Judge", result.get("headline") or "")
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual(parsed_request.get("requested_subjects"), ["Aaron Judge", "Shohei Ohtani"])
        recommendations = result.get("recommendations") or []
        self.assertEqual(len(recommendations), 2)
        self.assertEqual({item.get("subject_key") for item in recommendations}, {"aaron judge", "shohei ohtani"})
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "subject_comparison")
        table_rows = ((analysis_views.get("table") or {}).get("rows") or [])
        self.assertEqual(len(table_rows), 2)
        self.assertEqual([row.get("subject") for row in table_rows], ["Aaron Judge", "Shohei Ohtani"])

    def test_intelligence_query_filters_live_props_to_requested_subject(self) -> None:
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_compare_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Show me the best live props for Judge right now",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual(parsed_request.get("requested_subjects"), ["Aaron Judge"])
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertTrue(all(item.get("subject_key") == "aaron judge" for item in recommendations))
        self.assertTrue(all(item.get("is_live") for item in recommendations))

    def test_intelligence_query_uses_mlb_top_props_artifact_for_requested_pitcher_subject(self) -> None:
        overview = _sample_mlb_market_overview()
        overview[0]["context_label"] = "2026-06-05"

        def _mock_mlb_load_json_file(path):
            text = str(path).replace("\\", "/").lower()
            if text.endswith("daily/top_props/daily_top_props_2026_06_05.json"):
                return {
                    "groups": {
                        "pitcher": {
                            "sections": [
                                {
                                    "stat": "strikeouts",
                                    "rows": [
                                        {
                                            "stat": "strikeouts",
                                            "statLabel": "Strikeouts",
                                            "group": "pitcher",
                                            "ownerId": 687064,
                                            "ownerName": "Brandon Young",
                                            "playerName": "Brandon Young",
                                            "team": "BAL",
                                            "opponent": "TOR",
                                            "matchup": "BAL @ TOR",
                                            "mean": 5.327,
                                            "line": 3.5,
                                            "marketLine": 3.5,
                                            "selection": "over",
                                            "selectionLabel": "Over",
                                            "simProb": 0.819,
                                            "marketProb": 0.5665,
                                            "rawEdge": 0.2525,
                                            "odds": -155,
                                            "rank": 3,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            if text.endswith("daily/snapshots/2026-06-05/oddsapi_pitcher_props_2026_06_05.json"):
                return {
                    "pitcher_props": {
                        "brandon young": {
                            "strikeouts": {
                                "line": 4.5,
                                "over_odds": "+124",
                                "under_odds": "-166",
                                "alternates": [{"line": 3.5, "over_odds": "-170", "under_odds": "+130"}],
                            }
                        }
                    }
                }
            return {}

        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    with patch("syndicate.features.intelligence.mlb_load_json_file", side_effect=_mock_mlb_load_json_file):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "question": "What is Brandon Young strikeouts projection today?",
                                "date": "2026-06-05",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual(parsed_request.get("requested_subjects"), ["Brandon Young"])
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].get("subject_key"), "brandon young")
        self.assertEqual(recommendations[0].get("projected"), "5.3")
        self.assertEqual(recommendations[0].get("line"), "4.5")
        self.assertEqual(recommendations[0].get("odds"), "+124")
        self.assertIn("Projection 5.3 versus line 4.5", recommendations[0].get("rationale") or "")

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

    def test_build_parlays_trims_round_robin_anchor_for_tight_exposure_caps(self) -> None:
        preferences = _query_preferences(
            "Build me a four-leg round robin from the best NBA edges with a $100 bankroll and max 5% exposure"
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
                "odds": "+102",
                "score": 88.0,
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "MIA at PHI",
                "market": "REB",
                "pick": "Over 6.5",
                "name": "Brown Over 6.5 Reb",
                "surface_title": "Pregame props",
                "odds": "+108",
                "score": 86.0,
                "market_context": {"decimal_odds": 2.08, "american_odds": 108, "implied_probability": 48.08},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "PHX at SAC",
                "market": "AST",
                "pick": "Over 7.5",
                "name": "Booker Over 7.5 Ast",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 85.0,
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "MIN at DAL",
                "market": "3PM",
                "pick": "Over 3.5",
                "name": "Edwards Over 3.5 3PM",
                "surface_title": "Pregame props",
                "odds": "+110",
                "score": 84.0,
                "market_context": {"decimal_odds": 2.1, "american_odds": 110, "implied_probability": 47.62},
            },
        ]

        parlays = _build_parlays(candidates, limit=5, preferences=preferences)

        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("parlay_type") == "round_robin" for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_group_size") == 3 for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_unit") == 2 for parlay in parlays))
        self.assertEqual(len(parlays), 3)
        self.assertTrue(all(parlay.get("suggested_total_exposure") == 5.0 for parlay in parlays))
        self.assertTrue(all(parlay.get("suggested_stake") == 1.67 for parlay in parlays))

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
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "PTS", "market_shape": "counting_prop", "pick": "Over 28.5"},
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "AST", "market_shape": "counting_prop", "pick": "Over 6.5"},
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "3PM", "market_shape": "counting_prop", "pick": "Over 2.5"},
        )

        self.assertFalse(_parlay_matches_preferences(legs, preferences))

    def test_explicit_medium_correlation_allows_three_mlb_volume_props(self) -> None:
        preferences = _query_preferences("Build me a same game three-leg parlay with medium correlation")
        legs = (
            {"candidate_type": "prop", "sport_slug": "mlb", "matchup": "ATL at NYM", "market": "Pitcher Strikeouts", "market_shape": "volume_prop", "pick": "Over 7.5"},
            {"candidate_type": "prop", "sport_slug": "mlb", "matchup": "ATL at NYM", "market": "Hitter Total Bases", "market_shape": "volume_prop", "pick": "Over 1.5"},
            {"candidate_type": "prop", "sport_slug": "mlb", "matchup": "ATL at NYM", "market": "Hits", "market_shape": "volume_prop", "pick": "Over 1.5"},
        )

        self.assertTrue(_parlay_matches_preferences(legs, preferences))

    def test_explicit_medium_correlation_blocks_points_assists_pair_but_allows_points_threes(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        points_assists_legs = (
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "PTS", "market_key": "points", "market_shape": "counting_prop", "pick": "Over 28.5"},
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "AST", "market_key": "assists", "market_shape": "counting_prop", "pick": "Over 6.5"},
        )
        points_threes_legs = (
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "PTS", "market_key": "points", "market_shape": "counting_prop", "pick": "Over 28.5"},
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "3PM", "market_key": "threes", "market_shape": "counting_prop", "pick": "Over 2.5"},
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

    def test_intelligence_query_surfaces_raw_statcast_profile_context(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Pitch mix"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        statcast_payload = {
            "meta": {"generated_at": "2026-06-05T10:00:00Z"},
            "batters": {
                "608324": {
                    "overall": {
                        "ev_mean": 94.2,
                        "barrel_rate": 0.182,
                        "hr_per_bip": 0.091,
                        "xwoba": 0.422,
                        "pulled_air_rate": 0.211,
                    },
                    "mult_overall": {"hr": 1.28},
                }
            },
            "pitchers": {
                "605400": {
                    "overall": {
                        "ev_mean": 90.4,
                        "barrel_rate": 0.101,
                        "hardhit_rate": 0.428,
                        "hr_per_bip": 0.067,
                        "xwoba": 0.344,
                    },
                    "mult_overall": {"hr": 1.11},
                    "pitch_mix": {"FF": 0.47, "SL": 0.31, "CH": 0.14},
                }
            },
        }
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_mlb_statcast_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence._mlb_statcast_feature_payload", return_value=statcast_payload):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "question": "What are the best home run matchups today and why?",
                                "date": "2026-06-05",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        result = payload.get("response") or {}
        first = ((result.get("recommendations") or [])[0])
        self.assertIn("Raw Statcast context", first.get("rationale") or "")
        profile = first.get("mlb_statcast_profile") or {}
        self.assertEqual((profile.get("batter") or {}).get("ev_mean"), 94.2)
        self.assertEqual((profile.get("pitcher") or {}).get("hr_mult"), 1.11)
        first_row = ((result.get("analysis_views") or {}).get("table", {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("barrel_rate"), 18.2)
        self.assertEqual(first_row.get("pitcher_hr_per_bip_allowed"), 6.7)

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

    def test_mlb_live_prop_rows_do_not_depend_on_home_game_live_gate(self) -> None:
        from syndicate.blueprints.home import _load_home_live_prop_items

        scheduled_home_games = [
            {
                "away": {"abbr": "NYY", "name": "Yankees"},
                "home": {"abbr": "BOS", "name": "Red Sox"},
                "status": {"abstract": "Scheduled", "detailed": "7:10 PM ET"},
                "detail": "7:10 PM ET",
            }
        ]
        live_lens_games = [
            {
                "gamePk": 123,
                "away": {"abbr": "NYY", "name": "Yankees"},
                "home": {"abbr": "BOS", "name": "Red Sox"},
                "status": {"abstract": "Scheduled", "detailed": "7:10 PM ET"},
                "detail": "7:10 PM ET",
                "href": "/mlb/live-lens?date=2026-06-05",
                "liveProps": [
                    {
                        "playerName": "Aaron Judge",
                        "playerId": 592450,
                        "playerPhoto": "https://example.com/judge.png",
                        "marketLabel": "Hits",
                        "selection": "over",
                        "line": 1.5,
                        "estimatedWinProb": 0.61,
                        "modelMean": 1.9,
                        "liveProjection": 2.1,
                        "odds": "+110",
                    }
                ],
            }
        ]

        with patch("syndicate.features.mlb.live_lens.build_live_lens_page_context", return_value={"games": live_lens_games}):
            rows = _load_home_live_prop_items(
                "mlb",
                context_label="2026-06-05",
                home_games=scheduled_home_games,
                is_active_today=True,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("name"), "Aaron Judge")
        self.assertTrue(rows[0].get("is_live"))
        self.assertEqual(rows[0].get("href"), "/mlb/live-lens?date=2026-06-05")

    def test_mlb_pregame_rows_include_extra_pitcher_props(self) -> None:
        from syndicate.blueprints.home import _pregame_prop_rows_from_mlb_recommendations

        payload = {
            123: {
                "markets": {
                    "pitcherProps": [],
                    "extraPitcherProps": [
                        {
                            "pitcher_name": "Zebby Matthews",
                            "pitcher_id": 700001,
                            "prop": "strikeouts",
                            "market_line": 5.5,
                            "selection": "over",
                            "model_prob_over": 0.58,
                            "projection": 6.2,
                            "odds": "+130",
                            "edge": 0.061,
                            "away_abbr": "MIN",
                            "home_abbr": "SEA",
                        }
                    ],
                    "hitterProps": [],
                    "extraHitterProps": [],
                },
                "away": {"abbr": "MIN", "team_id": 142},
                "home": {"abbr": "SEA", "team_id": 136},
            }
        }

        with patch("syndicate.features.mlb.cards._cards_recommendation_payload_by_game", return_value=payload):
            rows = _pregame_prop_rows_from_mlb_recommendations(
                "2026-06-05",
                limit=18,
                fallback_href="/mlb/cards?date=2026-06-05",
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("name"), "Zebby Matthews")
        self.assertEqual(rows[0].get("market"), "Pitcher Strikeouts")
        self.assertEqual(rows[0].get("pick"), "OVER")

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
        self.assertTrue(sports)
        mlb_row = next((row for row in sports if row.get("slug") == "mlb"), None)
        self.assertIsNotNone(mlb_row)
        artifacts = (mlb_row or {}).get("artifacts") or []
        self.assertTrue(any(item.get("tracked") for item in artifacts))
        advanced_inputs = (mlb_row or {}).get("advanced_inputs") or []
        self.assertTrue(advanced_inputs)
        self.assertIn("metrics", advanced_inputs[0])
        self.assertIn("readiness_gate", payload)
        self.assertIn("advanced_gate", mlb_row or {})
        self.assertIn("publish_missing_inputs", (mlb_row or {}).get("advanced_gate") or {})

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
        self.assertIn('View data coverage page', body)
        self.assertIn('Prompt The Syndicate', body)