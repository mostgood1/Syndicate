"""Regression tests for the Lane E card-UI defects (plan_2026-08-14_ui.md).

Each test here corresponds to something that was measured broken in
production on 2026-08-14, not to a hypothetical. The load-bearing one is
`test_every_tab_addresses_a_panel`: NCAAF's rail pointed at a panel id that
did not exist, so returning to the default tab collapsed the card to its
187px header strip. That defect was invisible to every existing test because
it only appears in the RELATIONSHIP between two attributes, which is exactly
the kind of thing a rendered-string assertion misses.

The layout half of the lane (horizontal overflow, mobile stacking, touch
targets) is not testable here -- it needs a real layout engine. It is covered
by `scripts/ui_layout_probe.py`, which is runnable and reproduces the audit's
numbers.
"""

from __future__ import annotations

import re
import unittest

from syndicate.app import create_app
from syndicate.features.ncaaf.cards import _format_kickoff_label


TAB_RE = re.compile(r'data-tab-target="([^"]+)"')
PANEL_RE = re.compile(r'data-panel-id="([^"]+)"')


def _generic_game(**overrides) -> dict:
    game = {
        "gamePk": "g1",
        "away": {"abbr": "CAR", "name": "Carolina Panthers"},
        "home": {"abbr": "ARI", "name": "Arizona Cardinals"},
        "status": "Scheduled",
        "summary": "Test summary",
        "metrics": [],
        "market_tiles": [],
    }
    game.update(overrides)
    return game


def _ncaaf_game(**card_overrides) -> dict:
    ncaaf_card = {
        "summary": {
            "coverage_score": 0.5,
            "coverage_tier": "B",
            "publication_status": "publishable",
            "publication_ready": True,
            "ready_label": "Publishable",
            "tier_badges": [],
        },
        "teams": {
            "away": {"school_name": "North Carolina", "conference": "ACC"},
            "home": {"school_name": "TCU", "conference": "Big 12"},
        },
        "scoreboard": {
            "home_points": "30.9",
            "away_points": "27.0",
            "total_points": "57.9",
            "spread_label": "TCU by 3.9",
            "win_probability": "61.3%",
            "source_label": "SmartSim 2.0",
            "kickoff": "2026-08-29T16:00:00.000Z",
            "kickoff_label": "Sat Aug 29, 11:00 AM CDT",
            "venue": "Aviva Stadium",
        },
        "scoreboard_header": {"away": {}, "home": {}},
        "context_sections": [],
        "team_context": {"summary": "ctx", "items": []},
    }
    ncaaf_card.update(card_overrides)
    return {
        "gamePk": "1_North_Carolina_TCU",
        "away": {"abbr": "NC", "name": "North Carolina"},
        "home": {"abbr": "TCU", "name": "TCU"},
        "status": "Week 1",
        "summary": "Test summary",
        "metrics": [],
        "market_tiles": [],
        "panels": [],
        "ncaaf_card": ncaaf_card,
    }


class TabPanelContractTests(unittest.TestCase):
    """A tab's target and its panel's id are one namespace."""

    def setUp(self) -> None:
        self.app = create_app()
        self.app.config.update(TESTING=True)

    def _render(self, template: str, game: dict) -> str:
        with self.app.test_request_context("/"):
            from flask import render_template

            return render_template(template, game=game)

    def _assert_tabs_and_panels_agree(self, html: str) -> tuple[set[str], set[str]]:
        tabs = set(TAB_RE.findall(html))
        panels = set(PANEL_RE.findall(html))
        self.assertTrue(tabs, "card rendered no tabs at all")
        # A tab with no panel blanks the card when clicked; a panel with no tab
        # is markup no user can reach. Both were live on NCAAF.
        self.assertEqual(set(), tabs - panels, f"tabs addressing a panel that does not exist: {tabs - panels}")
        self.assertEqual(set(), panels - tabs, f"panels no tab can reach: {panels - tabs}")
        return tabs, panels

    def test_every_tab_addresses_a_panel_ncaaf(self) -> None:
        html = self._render("shared/_game_card_ncaaf.html", _ncaaf_game())
        tabs, _ = self._assert_tabs_and_panels_agree(html)
        # The specific regression: the default tab used to target "game" while
        # the default panel was "identity".
        self.assertIn("identity", tabs)
        self.assertNotIn("game", tabs)
        self.assertIn("coverage", tabs)

    def test_conditional_ncaaf_panels_get_a_tab(self) -> None:
        game = _ncaaf_game()
        game["ncaaf_card"]["scoreboard"]["projection_sources"] = {
            "enhanced_totals_engine": {"label": "Engine", "margin": 1, "total": 2},
            "smartsim2": {"label": "SmartSim", "margin": 1, "total": 2},
            "consensus_projection": {"label": "Consensus", "margin": 1, "total": 2},
        }
        game["ncaaf_card"]["scoreboard"]["projection_sources_mode"] = "public_trial"
        game["smartsim_reasons"] = {"lead": "why", "items": [{"label": "a", "value": "b", "detail": "c"}]}
        html = self._render("shared/_game_card_ncaaf.html", game)
        tabs, _ = self._assert_tabs_and_panels_agree(html)
        self.assertIn("blend-trial-public", tabs)
        self.assertIn("smartsim-reasons", tabs)

    def test_every_tab_addresses_a_panel_generic(self) -> None:
        self._assert_tabs_and_panels_agree(self._render("shared/_game_card_generic.html", _generic_game()))

    def test_every_tab_addresses_a_panel_generic_with_details(self) -> None:
        game = _generic_game(panels=[{"eyebrow": "e", "title": "t", "body": "b", "items": []}])
        tabs, _ = self._assert_tabs_and_panels_agree(self._render("shared/_game_card_generic.html", game))
        self.assertIn("panels", tabs)

    def test_tabs_carry_the_aria_tab_pattern(self) -> None:
        html = self._render("shared/_game_card_generic.html", _generic_game())
        self.assertIn('role="tablist"', html)
        self.assertIn('role="tab"', html)
        self.assertIn('role="tabpanel"', html)
        # aria-controls must point at an id that exists, or a screen reader
        # follows it into nothing.
        for target in re.findall(r'aria-controls="([^"]+)"', html):
            self.assertIn(f'id="{target}"', html)


class KickoffLabelTests(unittest.TestCase):
    """Raw ISO timestamps were reaching the NCAAF card."""

    def test_iso_utc_becomes_a_central_display_string(self) -> None:
        self.assertEqual(
            "Sat Aug 29, 11:00 AM CDT",
            _format_kickoff_label("2026-08-29T16:00:00.000Z"),
        )

    def test_midnight_utc_lands_on_the_previous_central_day(self) -> None:
        # The trap documented in features/shared/timezone.py: a 7pm Central
        # kickoff is 00:00 UTC the NEXT calendar day.
        self.assertEqual("Fri Aug 28, 7:00 PM CDT", _format_kickoff_label("2026-08-29T00:00:00Z"))

    def test_unparseable_and_empty_values_are_passed_through_not_faked(self) -> None:
        self.assertEqual("", _format_kickoff_label(None))
        self.assertEqual("", _format_kickoff_label("   "))
        self.assertEqual("Kickoff unavailable", _format_kickoff_label("Kickoff unavailable"))

    def test_the_raw_kickoff_field_is_left_alone_for_downstream_parsing(self) -> None:
        # ncaaf/betting_card.py calls datetime.fromisoformat on scoreboard
        # ["kickoff"]; formatting in place would have broken its day grouping.
        from syndicate.features.ncaaf.betting_card import _kickoff_date_and_label

        date_key, _ = _kickoff_date_and_label("2026-08-29T16:00:00.000Z")
        self.assertEqual("2026-08-29", date_key)


class ControlLinkDeduplicationTests(unittest.TestCase):
    """A destination is offered once per page, not once per partial."""

    def setUp(self) -> None:
        self.app = create_app()
        self.app.config.update(TESTING=True)

    def _render_controls(self, links: list[dict], control_links: list[dict]) -> str:
        with self.app.test_request_context("/"):
            from flask import render_template

            return render_template(
                "shared/_date_controls.html",
                action="/nfl/cards",
                prev_href="/nfl/cards?week=0",
                next_href="/nfl/cards?week=2",
                date_value="1",
                links=links,
                cards_control_links=control_links,
                show_home_link=False,
            )

    def test_a_control_link_duplicating_a_module_link_is_dropped(self) -> None:
        html = self._render_controls(
            links=[{"label": "Cards", "href": "/nfl/cards"}, {"label": "Picks", "href": "/nfl/picks"}],
            control_links=[{"label": "Picks", "href": "/nfl/picks?week=1"}],
        )
        self.assertEqual(1, html.count(">Picks<"))

    def test_a_control_link_with_no_module_counterpart_survives(self) -> None:
        html = self._render_controls(
            links=[{"label": "Cards", "href": "/nfl/cards"}],
            control_links=[{"label": "HR targets", "href": "/mlb/hr-targets"}],
        )
        self.assertIn(">HR targets<", html)

    def test_matching_ignores_case_and_padding(self) -> None:
        html = self._render_controls(
            links=[{"label": "Live Lens", "href": "/nfl/live-lens"}],
            control_links=[{"label": " live lens ", "href": "/nfl/live-lens?week=1"}],
        )
        # The control link is the only thing on the page carrying `week=1`;
        # its absence is what proves the label match was case/padding tolerant.
        self.assertNotIn("week=1", html)
        self.assertIn("Live Lens", html)


if __name__ == "__main__":
    unittest.main()
