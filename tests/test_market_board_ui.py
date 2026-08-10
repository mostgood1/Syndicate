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


if __name__ == "__main__":
    unittest.main()
