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

    def test_mlb_market_board_page_uses_shared_template_and_correct_endpoint(self) -> None:
        response = self.client.get("/mlb/market-board?date=2026-07-23")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("shared/board_cards.css", html)
        self.assertIn("shared/bet_slip.js", html)
        self.assertIn('data-api-endpoint="/mlb/api/market-board?date=2026-07-23"', html)
        self.assertIn('data-sport-slug="mlb"', html)
        self.assertIn('data-selected-date="2026-07-23"', html)
        self.assertIn('id="bet-slip-panel"', html)
        self.assertIn('id="board-game-groups"', html)

    def test_mlb_market_board_page_carries_the_full_toolbar(self) -> None:
        # Nav/filter parity pass 2026-07-24: same upper toolbar (sport/state/
        # market/view tabs, prop-type multiselect) and mini game-card strip
        # as the curated Layer 2 board, not just the same card styling.
        response = self.client.get("/mlb/market-board?date=2026-07-23")
        html = response.get_data(as_text=True)
        for element_id in (
            "board-sport-tabs",
            "board-state-tabs",
            "board-market-tabs",
            "board-view-tabs",
            "board-prop-type-tabs",
            "board-game-cards",
            "board-summary-strip",
        ):
            self.assertIn(f'id="{element_id}"', html, element_id)

    def test_nba_market_board_page_uses_shared_template_and_correct_endpoint(self) -> None:
        response = self.client.get("/nba/market-board?date=2026-07-23")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-api-endpoint="/nba/api/market-board?date=2026-07-23"', html)
        self.assertIn('data-sport-slug="nba"', html)

    def test_wnba_market_board_page_uses_shared_template_and_correct_endpoint(self) -> None:
        response = self.client.get("/wnba/market-board?date=2026-07-23")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-api-endpoint="/wnba/api/market-board?date=2026-07-23"', html)
        self.assertIn('data-sport-slug="wnba"', html)

    def test_soccer_mls_market_board_page_uses_shared_template_and_correct_endpoint(self) -> None:
        # Soccer's route is league-scoped (/soccer/<league>/market-board),
        # not a top-level /soccer/market-board like the other sports -- MLS
        # prioritized first since it has games sooner than WNBA.
        response = self.client.get("/soccer/mls/market-board?date=2026-07-23")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-api-endpoint="/soccer/mls/api/market-board?date=2026-07-23"', html)
        self.assertIn('data-sport-slug="mls"', html)
        self.assertIn('data-selected-date="2026-07-23"', html)

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
