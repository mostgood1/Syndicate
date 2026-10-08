"""Every page shows the same site menu `[user 2026-10-08, lane layer2-board-ui-redesign]`.

Before this the site had two hand-written copies of the menu: `base.html`'s had
Portfolio and `_standalone_app_header.html`'s did not, so ~40 sport pages were
missing it. Both now call `shared/_site_nav.html`'s macro; these tests pin that
the two headers render the same labels in the same order, and that the two
modules that rendered no menu at all now render one.
"""

from __future__ import annotations

import re
import unittest

from flask import render_template_string

from syndicate.app import app

CANONICAL = [
    "Home", "The Syndicate", "Betting Board", "Portfolio",
    "MLB", "NBA", "NHL", "NFL", "WNBA", "NCAAF", "NCAAB", "Soccer",
]


def _labels(html: str, link_class: str) -> list[str]:
    return re.findall(r'<a class="' + re.escape(link_class) + r'[^"]*"[^>]*>([^<]+)</a>', html)


class SiteNavTests(unittest.TestCase):
    def _render(self, source: str, path: str = "/mlb", **ctx) -> str:
        with app.test_request_context(path):
            return render_template_string(source, **ctx)

    def test_base_header_menu_is_canonical(self) -> None:
        html = self._render('{% extends "shared/base.html" %}')
        self.assertEqual(_labels(html, "cards-nav-pill"), CANONICAL)

    def test_standalone_header_menu_is_canonical(self) -> None:
        html = self._render('{% include "shared/_standalone_app_header.html" %}', active_sport_slug="mlb")
        self.assertEqual(_labels(html, "standalone-app-header__link"), CANONICAL)

    def test_both_headers_mark_the_same_page_active(self) -> None:
        base = self._render('{% extends "shared/base.html" %}', path="/portfolio")
        standalone = self._render('{% include "shared/_standalone_app_header.html" %}', path="/portfolio")
        self.assertIn('cards-nav-pill--active" href="/portfolio"', base)
        self.assertIn('standalone-app-header__link--active" href="/portfolio"', standalone)

    def test_the_board_highlights_home(self) -> None:
        for path in ("/", "/intelligence"):
            html = self._render('{% extends "shared/base.html" %}', path=path)
            self.assertIn('cards-nav-pill--active" href="/"', html, path)

    def test_date_is_kept_on_date_scoped_links(self) -> None:
        html = self._render('{% include "shared/_standalone_app_header.html" %}', path="/nhl?date=2026-10-08")
        self.assertIn('href="/market-board?date=2026-10-08"', html)
        self.assertIn('href="/nhl?date=2026-10-08"', html)
        self.assertIn('href="/portfolio"', html)

    def test_preseason_and_live_lens_pages_render_a_menu(self) -> None:
        from syndicate.features.shared.game_board_contract import apply_game_board_contract

        ctx = apply_game_board_contract({"games": []}, sport="nfl", module="preseason_cards")
        self.assertTrue(ctx["show_standalone_cards_header"])
        source = open("syndicate/features/mlb/live_lens.py", encoding="utf-8").read()
        self.assertIn('base["show_app_header"] = True', source)


if __name__ == "__main__":
    unittest.main()
