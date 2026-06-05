from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.features.intelligence import _build_parlays
from syndicate.features.intelligence import _candidate_market_fit
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
                            "team_pace_signal": 1.08,
                            "usage_rate_advanced": 1.14,
                            "shot_profile_advanced": 1.06,
                            "minutes_role_advanced": 1.03,
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
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertIn("market_fit_score", first_row)
        self.assertEqual(first_row.get("analysis_shape"), "nba_usage_creation")
        self.assertEqual(first_row.get("pace_signal"), 1.08)
        self.assertEqual(first_row.get("usage_signal"), 1.14)
        self.assertEqual(first_row.get("shot_profile_signal"), 1.06)
        self.assertIn("why", first_row)

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
                            "question": "Explain the best WNBA matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "wnba_matchups")
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("analysis_shape"), "wnba_role_pressure")
        self.assertEqual(first_row.get("team_environment_signal"), 1.12)
        self.assertEqual(first_row.get("possession_profile_signal"), 1.05)
        self.assertEqual(first_row.get("matchup_pressure_signal"), 1.09)

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