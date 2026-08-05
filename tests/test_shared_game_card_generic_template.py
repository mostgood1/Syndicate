"""Coverage for the Tier 1 fix to syndicate/templates/shared/_game_card_generic.html:
a game whose builder attached real `panels` (e.g. NFL preseason's
_game_from_preseason_projection, NCAAB's cards.py) now gets a Details tab
and panel section instead of the payload being silently dropped -- gated
so every OTHER game shape (no `panels`, or an empty list) renders exactly
as before.
"""

from __future__ import annotations

import unittest

from syndicate.app import create_app


def _base_game(**overrides) -> dict:
    game = {
        "gamePk": "g1",
        "away": {"abbr": "CAR", "name": "Carolina Panthers"},
        "home": {"abbr": "ARI", "name": "Arizona Cardinals"},
        "href": "/nfl/game/g1",
        "href_label": "Open game detail",
        "status": "Hall of Fame Weekend",
        "detail": "SmartSim 2.0 (preseason)",
        "summary": "Test summary",
        "metrics": [],
        # Every real game reaching this template has already gone through
        # game_board_contract.py's _normalize_game (which always sets
        # market_tiles via .setdefault(...)) -- match that real contract
        # here rather than a bare raw game dict, since the template assumes
        # market_tiles is always at least an empty list.
        "market_tiles": [],
    }
    game.update(overrides)
    return game


class GameCardGenericPanelsTabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.app.config.update(TESTING=True)

    def _render(self, game: dict) -> str:
        with self.app.test_request_context("/"):
            from flask import render_template

            return render_template("shared/_game_card_generic.html", game=game)

    def test_details_tab_and_panel_appear_when_panels_present(self) -> None:
        game = _base_game(
            panels=[
                {
                    "eyebrow": "Real depth chart",
                    "title": "Carolina Panthers likely snap leaders",
                    "body": "Real depth-chart context, informational only.",
                    "items": ["Bryce Young (QB, depth 1)"],
                }
            ]
        )
        html = self._render(game)
        self.assertIn('data-tab-target="panels"', html)
        self.assertIn(">Details<", html)
        self.assertIn('data-panel-id="panels"', html)
        self.assertIn("Carolina Panthers likely snap leaders", html)
        self.assertIn("Bryce Young (QB, depth 1)", html)

    def test_no_details_tab_when_panels_key_is_absent(self) -> None:
        game = _base_game()
        html = self._render(game)
        self.assertNotIn('data-tab-target="panels"', html)
        self.assertNotIn('data-panel-id="panels"', html)

    def test_no_details_tab_when_panels_is_an_empty_list(self) -> None:
        # NFL's regular-season/preseason snapshot-bundle path, and every
        # other sport that hasn't attached panels yet, must render exactly
        # as before -- an empty list is falsy in Jinja, same as absent.
        game = _base_game(panels=[])
        html = self._render(game)
        self.assertNotIn('data-tab-target="panels"', html)
        self.assertNotIn('data-panel-id="panels"', html)

    def test_other_tabs_are_unaffected_either_way(self) -> None:
        for game in (_base_game(), _base_game(panels=[{"eyebrow": "E", "title": "T", "body": "B", "items": []}])):
            html = self._render(game)
            self.assertIn('data-tab-target="game"', html)
            self.assertIn('data-tab-target="boxscore"', html)
            self.assertIn('data-tab-target="props"', html)


if __name__ == "__main__":
    unittest.main()
