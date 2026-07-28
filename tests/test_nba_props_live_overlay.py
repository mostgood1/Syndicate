from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.nba import props as nba_props


class NbaPropsLiveTeamContextTests(unittest.TestCase):
    def test_returns_empty_when_no_games_are_live(self) -> None:
        with patch.object(
            nba_props,
            "build_cards_page_context",
            return_value={
                "games": [
                    {"event_id": "evt-1", "away": {"abbr": "BOS"}, "home": {"abbr": "NYK"}, "status": "Scheduled"},
                    {"event_id": "evt-2", "away": {"abbr": "LAL"}, "home": {"abbr": "GSW"}, "status": "Final"},
                ]
            },
        ):
            self.assertEqual(nba_props._live_team_context("2026-07-27"), {})

    def test_maps_both_teams_of_a_live_game_to_the_same_event_id(self) -> None:
        with patch.object(
            nba_props,
            "build_cards_page_context",
            return_value={
                "games": [
                    {"event_id": "evt-1", "away": {"abbr": "BOS"}, "home": {"abbr": "NYK"}, "status": "Live"},
                    {"event_id": "evt-2", "away": {"abbr": "LAL"}, "home": {"abbr": "GSW"}, "status": "Scheduled"},
                ]
            },
        ):
            live_teams = nba_props._live_team_context("2026-07-27")

        self.assertEqual(set(live_teams.keys()), {"BOS", "NYK"})
        self.assertEqual(live_teams["BOS"], {"event_id": "evt-1", "opponent_tri": "NYK"})
        self.assertEqual(live_teams["NYK"], {"event_id": "evt-1", "opponent_tri": "BOS"})

    def test_swallows_exceptions_and_returns_empty(self) -> None:
        with patch.object(nba_props, "build_cards_page_context", side_effect=RuntimeError("boom")):
            self.assertEqual(nba_props._live_team_context("2026-07-27"), {})


class NbaLivePropCardsTests(unittest.TestCase):
    def test_only_surfaces_rows_with_a_real_live_edge(self) -> None:
        live_teams = {"BOS": {"event_id": "evt-1", "opponent_tri": "NYK"}, "NYK": {"event_id": "evt-1", "opponent_tri": "BOS"}}
        with patch.object(
            nba_props,
            "build_live_player_lens_payload",
            return_value={
                "games": [
                    {
                        "event_id": "evt-1",
                        "rows": [
                            {
                                "player": "Jayson Tatum",
                                "team_tri": "BOS",
                                "stat": "pts",
                                "line_live": 27.5,
                                "live_projection": 33.0,
                                "live_edge": 5.5,
                                "price_over": -112,
                                "actual": 14,
                                "book": "FanDuel",
                                "ev_side": "OVER",
                            },
                            {
                                "player": "Someone Else",
                                "team_tri": "NYK",
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
            cards = nba_props._live_prop_cards("2026-07-27", live_teams, limit=12)

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertIn("Jayson Tatum", card["title"])
        self.assertIn("Over", card["title"])
        self.assertEqual(card["eyebrow"], "Live")
        self.assertIn("BOS", card["meta"])
        self.assertIn("NYK", card["meta"])

    def test_team_filter_excludes_non_matching_rows(self) -> None:
        live_teams = {"BOS": {"event_id": "evt-1", "opponent_tri": "NYK"}, "NYK": {"event_id": "evt-1", "opponent_tri": "BOS"}}
        with patch.object(
            nba_props,
            "build_live_player_lens_payload",
            return_value={
                "games": [
                    {
                        "event_id": "evt-1",
                        "rows": [
                            {"player": "Jayson Tatum", "team_tri": "BOS", "stat": "pts", "line_live": 27.5, "live_projection": 33.0, "live_edge": 5.5, "ev_side": "OVER"},
                            {"player": "Jalen Brunson", "team_tri": "NYK", "stat": "pts", "line_live": 24.5, "live_projection": 30.0, "live_edge": 5.5, "ev_side": "OVER"},
                        ],
                    }
                ]
            },
        ):
            cards = nba_props._live_prop_cards("2026-07-27", live_teams, limit=12, filters={"team": "NYK"})

        self.assertEqual(len(cards), 1)
        self.assertIn("Jalen Brunson", cards[0]["title"])

    def test_returns_empty_when_no_live_event_ids(self) -> None:
        self.assertEqual(nba_props._live_prop_cards("2026-07-27", {}, limit=12), [])

    def test_swallows_exceptions_and_returns_empty(self) -> None:
        live_teams = {"BOS": {"event_id": "evt-1", "opponent_tri": "NYK"}}
        with patch.object(nba_props, "build_live_player_lens_payload", side_effect=RuntimeError("boom")):
            self.assertEqual(nba_props._live_prop_cards("2026-07-27", live_teams, limit=12), [])


class NbaPropsPageContextLiveOverlayTests(unittest.TestCase):
    def test_pregame_rows_for_a_live_team_are_dropped_in_favor_of_live_cards_unfiltered(self) -> None:
        summary = {
            "ok": True,
            "date": "2026-07-27",
            "data": [
                {
                    "player": "Jayson Tatum",
                    "team": "Boston Celtics",
                    "team_tricode": "BOS",
                    "opponent": "New York Knicks",
                    "tier": "High",
                    "top_play": {"market": "pts", "side": "over", "line": 27.5, "price": -110, "ev_pct": 10.0},
                },
                {
                    "player": "LeBron James",
                    "team": "Los Angeles Lakers",
                    "team_tricode": "LAL",
                    "opponent": "Golden State Warriors",
                    "tier": "High",
                    "top_play": {"market": "pts", "side": "over", "line": 25.5, "price": -110, "ev_pct": 12.0},
                },
            ],
        }
        with patch.object(nba_props, "central_today_iso", return_value="2026-07-27"), patch.object(
            nba_props, "processed_path", return_value="props.json"
        ), patch.object(nba_props, "load_json", return_value=summary), patch.object(
            nba_props, "available_dates", return_value=["2026-07-27"]
        ), patch.object(
            nba_props,
            "_live_team_context",
            return_value={"BOS": {"event_id": "evt-1", "opponent_tri": "NYK"}},
        ), patch.object(
            nba_props,
            "_live_prop_cards",
            return_value=[{"title": "Jayson Tatum Over 33.0 Points", "eyebrow": "Live", "badge": "Live edge 5.5", "meta": "BOS vs NYK", "metrics": [], "summary": "live", "list_items": [], "href": None, "href_label": None}],
        ):
            context = nba_props.build_props_page_context("2026-07-27")

        cards = context.get("rank_cards") or []
        titles = [card.get("title") for card in cards]
        live_card = next((card for card in cards if "Jayson Tatum" in str(card.get("title"))), None)
        self.assertIsNotNone(live_card)
        self.assertEqual(live_card.get("eyebrow"), "Live")
        self.assertTrue(any("LeBron James" in title for title in titles))
        self.assertIn("Jayson Tatum", titles[0])

    def test_no_live_games_leaves_pregame_board_unchanged(self) -> None:
        summary = {
            "ok": True,
            "date": "2026-07-27",
            "data": [
                {
                    "player": "LeBron James",
                    "team": "Los Angeles Lakers",
                    "team_tricode": "LAL",
                    "opponent": "Golden State Warriors",
                    "tier": "High",
                    "top_play": {"market": "pts", "side": "over", "line": 25.5, "price": -110, "ev_pct": 12.0},
                }
            ],
        }
        with patch.object(nba_props, "central_today_iso", return_value="2026-07-27"), patch.object(
            nba_props, "processed_path", return_value="props.json"
        ), patch.object(nba_props, "load_json", return_value=summary), patch.object(
            nba_props, "available_dates", return_value=["2026-07-27"]
        ), patch.object(nba_props, "_live_team_context", return_value={}), patch.object(
            nba_props, "_live_prop_cards"
        ) as live_cards_fn:
            context = nba_props.build_props_page_context("2026-07-27")

        live_cards_fn.assert_not_called()
        titles = [card.get("title") for card in context.get("rank_cards") or []]
        self.assertTrue(any("LeBron James" in title for title in titles))

    def test_historical_date_never_checks_live_state(self) -> None:
        summary = {"ok": True, "date": "2026-06-01", "data": []}
        with patch.object(nba_props, "central_today_iso", return_value="2026-07-27"), patch.object(
            nba_props, "processed_path", return_value="props.json"
        ), patch.object(nba_props, "load_json", return_value=summary), patch.object(
            nba_props, "available_dates", return_value=["2026-06-01"]
        ), patch.object(nba_props, "_live_team_context") as live_team_fn:
            nba_props.build_props_page_context("2026-06-01")

        live_team_fn.assert_not_called()

    def test_filtered_view_prepends_matching_live_cards(self) -> None:
        # When a team/player/market filter is active, build_props_page_context
        # takes a different code path (custom rank-card assembly instead of
        # build_top_props_page_context) -- confirm the live overlay applies
        # there too, not just the unfiltered default view.
        summary = {
            "ok": True,
            "date": "2026-07-27",
            "data": [
                {
                    "player": "Jayson Tatum",
                    "team": "Boston Celtics",
                    "team_tricode": "BOS",
                    "opponent": "New York Knicks",
                    "tier": "High",
                    "top_play": {"market": "pts", "side": "over", "line": 27.5, "price": -110, "ev_pct": 10.0},
                }
            ],
        }
        with patch.object(nba_props, "central_today_iso", return_value="2026-07-27"), patch.object(
            nba_props, "processed_path", return_value="props.json"
        ), patch.object(nba_props, "load_json", return_value=summary), patch.object(
            nba_props, "available_dates", return_value=["2026-07-27"]
        ), patch.object(
            nba_props,
            "_live_team_context",
            return_value={"BOS": {"event_id": "evt-1", "opponent_tri": "NYK"}},
        ), patch.object(
            nba_props,
            "_live_prop_cards",
            return_value=[{"title": "Jayson Tatum Over 33.0 Points", "eyebrow": "Live", "badge": "Live edge 5.5", "meta": "BOS vs NYK", "metrics": [], "summary": "live", "list_items": [], "href": None, "href_label": None}],
        ):
            context = nba_props.build_props_page_context("2026-07-27", filters={"team": "BOS"})

        titles = [card.get("title") for card in context.get("rank_cards") or []]
        self.assertIn("Jayson Tatum", titles[0])


if __name__ == "__main__":
    unittest.main()
