from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app


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
        self.assertGreaterEqual(len(result.get("recommendations") or []), 2)
        self.assertGreaterEqual(len(result.get("parlays") or []), 1)
        first = (result.get("recommendations") or [])[0]
        self.assertIn("rationale", first)
        self.assertIn(first.get("candidate_type"), {"prop", "game"})
        self.assertIn("Advanced drivers in play", first.get("rationale") or "")
        self.assertTrue(first.get("advanced_inputs"))
        self.assertIn("readiness_gate", result)
        self.assertTrue(first.get("advanced_ready"))

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