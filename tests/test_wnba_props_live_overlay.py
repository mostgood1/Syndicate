from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.wnba import props as wnba_props


class WnbaPropsLiveTeamContextTests(unittest.TestCase):
    def test_returns_empty_when_no_games_are_live(self) -> None:
        with patch.object(
            wnba_props,
            "build_cards_page_context",
            return_value={
                "games": [
                    {"event_id": "evt-1", "away": {"abbr": "NYL"}, "home": {"abbr": "LAS"}, "status": "Scheduled"},
                    {"event_id": "evt-2", "away": {"abbr": "CHI"}, "home": {"abbr": "CON"}, "status": "Final"},
                ]
            },
        ):
            self.assertEqual(wnba_props._live_team_context("2026-07-27"), {})

    def test_maps_both_teams_of_a_live_game_to_the_same_event_id(self) -> None:
        with patch.object(
            wnba_props,
            "build_cards_page_context",
            return_value={
                "games": [
                    {"event_id": "evt-1", "away": {"abbr": "NYL"}, "home": {"abbr": "LAS"}, "status": "Live"},
                    {"event_id": "evt-2", "away": {"abbr": "CHI"}, "home": {"abbr": "CON"}, "status": "Scheduled"},
                ]
            },
        ):
            live_teams = wnba_props._live_team_context("2026-07-27")

        self.assertEqual(set(live_teams.keys()), {"NYL", "LAS"})
        self.assertEqual(live_teams["NYL"], {"event_id": "evt-1", "opponent_tri": "LAS"})
        self.assertEqual(live_teams["LAS"], {"event_id": "evt-1", "opponent_tri": "NYL"})

    def test_swallows_exceptions_and_returns_empty(self) -> None:
        with patch.object(wnba_props, "build_cards_page_context", side_effect=RuntimeError("boom")):
            self.assertEqual(wnba_props._live_team_context("2026-07-27"), {})


class WnbaLivePropCardsTests(unittest.TestCase):
    def test_only_surfaces_rows_with_a_real_live_edge(self) -> None:
        live_teams = {"NYL": {"event_id": "evt-1", "opponent_tri": "LAS"}, "LAS": {"event_id": "evt-1", "opponent_tri": "NYL"}}
        with patch.object(
            wnba_props,
            "build_live_player_lens_payload",
            return_value={
                "games": [
                    {
                        "event_id": "evt-1",
                        "rows": [
                            {
                                "player": "Breanna Stewart",
                                "team_tri": "NYL",
                                "stat": "pts",
                                "line_live": 17.5,
                                "live_projection": 23.0,
                                "live_edge": 5.5,
                                "price_over": -112,
                                "actual": 12,
                                "book": "FanDuel",
                                "ev_side": "OVER",
                            },
                            {
                                # No live edge -- model and line agree, not an opportunity.
                                "player": "Someone Else",
                                "team_tri": "LAS",
                                "stat": "reb",
                                "line_live": 6.5,
                                "live_projection": 6.5,
                                "live_edge": 0.0,
                                "ev_side": None,
                            },
                        ],
                    }
                ]
            },
        ):
            cards = wnba_props._live_prop_cards("2026-07-27", live_teams, limit=12)

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertIn("Breanna Stewart", card["title"])
        self.assertIn("Over", card["title"])
        self.assertEqual(card["eyebrow"], "Live")
        self.assertIn("NYL", card["meta"])
        self.assertIn("LAS", card["meta"])

    def test_returns_empty_when_no_live_event_ids(self) -> None:
        self.assertEqual(wnba_props._live_prop_cards("2026-07-27", {}, limit=12), [])

    def test_swallows_exceptions_and_returns_empty(self) -> None:
        live_teams = {"NYL": {"event_id": "evt-1", "opponent_tri": "LAS"}}
        with patch.object(wnba_props, "build_live_player_lens_payload", side_effect=RuntimeError("boom")):
            self.assertEqual(wnba_props._live_prop_cards("2026-07-27", live_teams, limit=12), [])


class WnbaPropsPageContextLiveOverlayTests(unittest.TestCase):
    def test_pregame_rows_for_a_live_team_are_dropped_in_favor_of_live_cards(self) -> None:
        # Regression for the pregame-only gap this session found: before this
        # change, build_props_page_context served the pregame recommendation
        # slate unconditionally regardless of game state, so a live game's
        # props never reflected the live score/line at all.
        summary = {
            "ok": True,
            "date": "2026-07-27",
            "data": [
                {
                    "player": "Breanna Stewart",
                    "team": "New York Liberty",
                    "team_tricode": "NYL",
                    "opponent": "Las Vegas Aces",
                    "tier": "High",
                    "top_play": {"market": "pts", "side": "over", "line": 20.5, "price": -110, "ev_pct": 10.0},
                },
                {
                    "player": "A'ja Wilson",
                    "team": "Las Vegas Aces",
                    "team_tricode": "LVA",
                    "opponent": "Chicago Sky",
                    "tier": "High",
                    "top_play": {"market": "pts", "side": "over", "line": 24.5, "price": -110, "ev_pct": 12.0},
                },
            ],
        }
        with patch.object(wnba_props, "central_today_iso", return_value="2026-07-27"), patch.object(
            wnba_props, "_resolve_top_by_game_source_path", return_value="props.json"
        ), patch.object(wnba_props, "_load_props_recommendations_summary", return_value=summary), patch.object(
            wnba_props, "available_dates", return_value=["2026-07-27"]
        ), patch.object(
            wnba_props,
            "_live_team_context",
            return_value={"NYL": {"event_id": "evt-1", "opponent_tri": "LAS"}},
        ), patch.object(
            wnba_props,
            "_live_prop_cards",
            return_value=[{"title": "Breanna Stewart Over 23.0 Points", "eyebrow": "Live", "badge": "Live edge 5.5", "meta": "NYL vs LAS", "metrics": [], "summary": "live", "list_items": []}],
        ):
            context = wnba_props.build_props_page_context("2026-07-27")

        cards = context.get("rank_cards") or []
        titles = [card.get("title") for card in cards]
        live_card = next((card for card in cards if "Breanna Stewart" in str(card.get("title"))), None)
        self.assertIsNotNone(live_card)
        self.assertEqual(live_card.get("eyebrow"), "Live")
        # A'ja Wilson's game is still pregame, so her pregame card survives untouched.
        self.assertTrue(any("A'ja Wilson" in title for title in titles))
        # The live card comes first.
        self.assertIn("Breanna Stewart", titles[0])

    def test_no_live_games_leaves_pregame_board_unchanged(self) -> None:
        summary = {
            "ok": True,
            "date": "2026-07-27",
            "data": [
                {
                    "player": "A'ja Wilson",
                    "team": "Las Vegas Aces",
                    "team_tricode": "LVA",
                    "opponent": "Chicago Sky",
                    "tier": "High",
                    "top_play": {"market": "pts", "side": "over", "line": 24.5, "price": -110, "ev_pct": 12.0},
                }
            ],
        }
        with patch.object(wnba_props, "central_today_iso", return_value="2026-07-27"), patch.object(
            wnba_props, "_resolve_top_by_game_source_path", return_value="props.json"
        ), patch.object(wnba_props, "_load_props_recommendations_summary", return_value=summary), patch.object(
            wnba_props, "available_dates", return_value=["2026-07-27"]
        ), patch.object(wnba_props, "_live_team_context", return_value={}), patch.object(
            wnba_props, "_live_prop_cards"
        ) as live_cards_fn:
            context = wnba_props.build_props_page_context("2026-07-27")

        live_cards_fn.assert_not_called()
        titles = [card.get("title") for card in context.get("rank_cards") or []]
        self.assertTrue(any("A'ja Wilson" in title for title in titles))

    def test_historical_date_never_checks_live_state(self) -> None:
        # Only "today" can plausibly have a live game -- a past date should
        # never pay for a live-state lookup at all.
        summary = {"ok": True, "date": "2026-06-01", "data": []}
        with patch.object(wnba_props, "central_today_iso", return_value="2026-07-27"), patch.object(
            wnba_props, "_resolve_top_by_game_source_path", return_value="props.json"
        ), patch.object(wnba_props, "_load_props_recommendations_summary", return_value=summary), patch.object(
            wnba_props, "available_dates", return_value=["2026-06-01"]
        ), patch.object(wnba_props, "_live_team_context") as live_team_fn:
            wnba_props.build_props_page_context("2026-06-01")

        live_team_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
