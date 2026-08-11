from __future__ import annotations

import unittest

from syndicate.app import create_app


class MarketBoardUiParityTests(unittest.TestCase):
    """UI-parity pass 2026-07-24: all three sports' Layer 1 market-board
    pages now render through the same shared/market_board.html template
    (card/badge/bet-slip visual language extracted from intelligence.html,
    the curated Layer 2 board) instead of each having its own bespoke page.
    """

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    # REWRITTEN 2026-08-10 for `#329`. These asserted the LEGACY page's contract
    # -- `data-api-endpoint="/<sport>/api/market-board"`, the board-*-tabs ids,
    # `board-game-groups`. All eight sports now render the shared Layer 1 board.
    #
    # The old assertions are not merely stale: an earlier attempt at this swap
    # was REVERTED because these very tests caught that it removed the bet slip
    # from six sports. So the replacements below assert the thing that actually
    # mattered -- the slip survives -- rather than the markup that carried it.

    SWAPPED_SPORTS = ("mlb", "nba", "wnba", "nfl", "ncaaf", "nhl", "ncaab", "soccer")

    def test_every_sport_market_board_renders_the_shared_layer1_board(self) -> None:
        for slug in self.SWAPPED_SPORTS:
            with self.subTest(sport=slug):
                response = self.client.get(f"/{slug}/market-board?date=2026-07-23")
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn("/api/board/layer1", html)
                self.assertIn('id="l1-body"', html)

    def test_nhl_and_ncaab_have_a_board_at_all(self) -> None:
        # Both returned 404 on production 2026-08-10 while /api/board/book-grid
        # served them by parameter. Out of season the board renders empty WITH A
        # REASON (`#296`), which is a different answer from "no such page".
        for slug in ("nhl", "ncaab"):
            with self.subTest(sport=slug):
                self.assertEqual(self.client.get(f"/{slug}/market-board").status_code, 200)

    def test_the_bet_slip_survived_the_swap(self) -> None:
        # THE REGRESSION THIS FILE ALREADY CAUGHT ONCE. The first swap attempt
        # dropped the slip; it was reverted rather than shipped. A board you can
        # only read is not parity with a board you can stage a pick from.
        for slug in self.SWAPPED_SPORTS:
            with self.subTest(sport=slug):
                html = self.client.get(f"/{slug}/market-board?date=2026-07-23").get_data(as_text=True)
                self.assertIn('id="bet-slip-panel"', html, f"{slug} lost the bet-slip panel")
                self.assertIn("shared/bet_slip.js", html, f"{slug} lost the bet-slip script")
                self.assertIn("wireSlipButtons", html, f"{slug} never re-wires slip buttons after render")

    def test_the_board_keeps_its_filter_toolbar(self) -> None:
        html = self.client.get("/mlb/market-board?date=2026-07-23").get_data(as_text=True)
        for element_id in ("l1-views", "l1-markets", "l1-leagues", "l1-sport", "l1-date", "l1-window"):
            self.assertIn(f'id="{element_id}"', html, element_id)
        # Date navigation and the route back to cards were on the legacy toolbar
        # and are load-bearing, not decoration.
        self.assertIn("Back to Cards", html)

    def test_soccer_per_league_board_preselects_its_league(self) -> None:
        # The per-league URL is linked from the soccer hub. It now renders the
        # shared board filtered rather than a seventh bespoke builder -- possible
        # only because `#330` made the pivot carry `league` at all.
        html = self.client.get("/soccer/mls/market-board?date=2026-07-23").get_data(as_text=True)
        self.assertIn("/api/board/layer1", html)
        self.assertIn('league: "mls"', html)

    def test_soccer_mls_api_market_board_returns_json(self) -> None:
        response = self.client.get("/soccer/mls/api/market-board?date=2026-07-23")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["league"], "mls")
        self.assertEqual(payload["date"], "2026-07-23")
        self.assertIn("games", payload)

    def test_market_board_pages_carry_the_site_nav_shell(self) -> None:
        # Confirms these pages now extend shared/base.html (site nav/logo)
        # instead of being standalone documents, per the "feel exactly like
        # the homepage board" requirement.
        response = self.client.get("/mlb/market-board?date=2026-07-23")
        html = response.get_data(as_text=True)
        self.assertIn("syndicate-nav", html)
        self.assertIn(">Betting Board<", html)

    def test_all_three_static_assets_are_servable(self) -> None:
        for asset in ("board_cards.css", "bet_slip.js", "market_board.js"):
            response = self.client.get(f"/static/shared/{asset}")
            self.assertEqual(response.status_code, 200, asset)

    def test_the_board_exposes_segment_as_its_own_dimension(self) -> None:
        # F1/F3/F5/Full for h2h and totals. Measured on the 2026-08-09 MLB slate:
        # h2h is 15 full + 15 first5 + 15 first3 + 15 first1, so a single "h2h"
        # tab was three-quarters a different bet wearing the same label.
        # book_grid.html already treats segment as its own group for this reason.
        html = self.client.get("/mlb/market-board?date=2026-08-09").get_data(as_text=True)
        self.assertIn('id="l1-segments"', html)
        self.assertIn("renderSegments", html)
        # The friendly labels, so a row reads F5 rather than the raw `first5`.
        for token in ("Full game", "F1", "F3", "F5"):
            self.assertIn(token, html, token)

    def test_segment_filter_is_hidden_when_there_is_only_one(self) -> None:
        # A pregame board carries Full only for most of the day -- F1/F3/F5 are
        # fetched inside the T-window (#16/#17 cost control). One segment is not
        # a choice, so the strip must collapse rather than show a dead tab.
        html = self.client.get("/mlb/market-board?date=2026-08-10").get_data(as_text=True)
        self.assertIn("if (keys.length < 2)", html)

    def test_the_board_refreshes_itself(self) -> None:
        # A REGRESSION THIS SUITE MISSED ONCE. The legacy board polled every 60s
        # (market_board.js: setInterval(loadGameChips, 60000)); the swap to the
        # shared board dropped it, so a live board sat frozen until someone
        # pressed Refresh. On a live board that is not staleness, it is wrong --
        # the pregame/live split exists precisely because games MOVE between
        # views while you are watching.
        html = self.client.get("/mlb/market-board?date=2026-08-10").get_data(as_text=True)
        self.assertIn("setInterval", html)
        self.assertIn("REFRESH_MS", html)
        # Only while visible, matching the old board's guard -- a backgrounded
        # tab polling all night is load nobody reads.
        self.assertIn("document.hidden", html)
        self.assertIn("visibilitychange", html)


    def test_the_edge_column_handles_both_projection_contracts(self) -> None:
        # MLB emits `edge_vs_market_pct` (a percentage against no-vig fair).
        # WNBA emits `edge_vs_line` (distance from the line in the MARKET'S OWN
        # units -- 0.19 rebounds, not 0.19%), because its model ships means and
        # not a distribution. board_enrichment documents the split as deliberate.
        #
        # Measured on production 2026-08-11: edge_vs_market_pct was null on
        # 267/267 WNBA projections while edge_vs_line was populated on all 267.
        # This column read only the former, so every WNBA edge rendered as a dash
        # on a board whose projections were entirely present.
        html = self.client.get("/wnba/market-board?date=2026-08-10").get_data(as_text=True)
        self.assertIn("edge_vs_market_pct", html)
        self.assertIn("edge_vs_line", html)

    def test_the_two_edge_units_are_never_conflated(self) -> None:
        # Rendering the points value with a % suffix would be worse than the
        # dash it replaced: a wrong number that looks right.
        html = self.client.get("/mlb/market-board?date=2026-08-10").get_data(as_text=True)
        self.assertIn('edgeUnit = "pct"', html)
        self.assertIn('edgeUnit = "line"', html)
        self.assertIn("vs line", html)

    def test_an_explained_dash_is_distinguishable_from_an_absent_one(self) -> None:
        # An edge suppressed because the game is live is a different fact from
        # no projection at all. edge_unavailable_reason carries the first.
        html = self.client.get("/mlb/market-board?date=2026-08-10").get_data(as_text=True)
        self.assertIn("edge_unavailable_reason", html)
        self.assertIn("probability_unavailable_reason", html)


if __name__ == "__main__":
    unittest.main()
