"""Lane G of `plan_2026-08-14_ui.md` — soccer's card shows its own data or nothing.

Every case here was measured on production `/soccer/epl/cards` (EPL Coventry @
Arsenal) on 2026-08-15 before it was fixed, and the numbers in the docstrings
are those readings, not illustrations.

The tests assert the RULE rather than the sport: soccer is simply the sport
that publishes no `sim.periods` and no `prop_recommendations`, so it is the one
where an MLB-shaped slot renders empty. A sport that starts publishing either
gets its panel back with no change here — which is what the "and the panel
comes back" cases pin.
"""
from __future__ import annotations

import unittest

from syndicate.features.shared.game_board_contract import (
    NULL_PLACEHOLDER,
    _build_lens_rows,
    _build_prop_status_rows,
    _normalize_game,
)

SUMMARY = (
    "Projected Coventry City 0.8 @ Arsenal 2.5 (total 3.2). "
    "Win prob: Arsenal 77.3% / Draw 14.0% / Coventry City 8.7%."
)


def _soccer_game(**overrides):
    """A game shaped like soccer's: a three-way sim, no periods, no props."""
    game = {
        "gamePk": "epl-cov-ars",
        "away": {"abbr": "COV", "name": "Coventry City", "href": "/soccer/epl/team/coventry-city"},
        "home": {"abbr": "ARS", "name": "Arsenal", "href": "/soccer/epl/team/arsenal"},
        "summary": SUMMARY,
        "detail": "EPL",
        "status": "Pregame",
        "sim": {
            "score": {"away_mean": 0.8, "home_mean": 2.5},
            "win_probability": {"home": 0.773, "draw": 0.14, "away": 0.087},
        },
        "panels": [
            {
                "eyebrow": "Top prop signals",
                "title": "Anytime scorer / shots leaders",
                "body": "Highest anytime-goalscorer probability players from the simulated player-props pass.",
                "items": [
                    "Kai Havertz (Arsenal) | Anytime scorer 25.8% | xShots 1.2",
                    "Viktor Gyokeres (Arsenal) | Anytime scorer 24.6% | xShots 1.2",
                    "Gabriel Jesus (Arsenal) | Anytime scorer 18.8% | xShots 1.1",
                ],
            },
        ],
    }
    game.update(overrides)
    return game


class LensSuppressionTests(unittest.TestCase):
    """G3 — the MLB-shaped game-lens slot with no soccer data behind it."""

    def test_stand_in_period_row_is_marked_synthesized(self) -> None:
        rows = _normalize_game(_soccer_game())["shared_period_rows"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_synthesized"])

    def test_lens_rows_drop_a_stand_in_that_only_restates_the_summary(self) -> None:
        # Production: a 582px "Period odds and game lens" panel whose headline
        # was the ribbon's sentence verbatim, whose subcopy was "EPL" (already
        # the Slate context), and whose only number was the home win already
        # in the tiles and in the bar.
        normalized = _normalize_game(_soccer_game())
        self.assertEqual(normalized["shared_lens_rows"], [])

    def test_the_probability_row_survives_the_lens_suppression(self) -> None:
        # The stand-in row is where soccer's three-way bar comes from (Lane F,
        # `932a1f71`). Suppressing the LENS must not take the draw with it.
        normalized = _normalize_game(_soccer_game())
        prob_rows = normalized["shared_probability_rows"]
        self.assertEqual(len(prob_rows), 1)
        self.assertAlmostEqual(prob_rows[0]["home_pct"], 77.3, places=1)
        self.assertAlmostEqual(prob_rows[0]["draw_pct"], 14.0, places=1)
        self.assertAlmostEqual(prob_rows[0]["away_pct"], 8.7, places=1)

    def test_a_stand_in_with_a_real_market_keeps_its_lens(self) -> None:
        # Gate on content, not on sport. `Spread` is what the fallback row
        # reads for `market`, so this game has something the card does not
        # already show and the panel is correct to render.
        game = _soccer_game(metrics=[{"label": "Spread", "value": "ARS -1.5"}])
        normalized = _normalize_game(game)
        self.assertEqual(len(normalized["shared_lens_rows"]), 1)

    def test_real_periods_are_always_lens_rows(self) -> None:
        game = _soccer_game(
            sim={
                "score": {"away_mean": 0.8, "home_mean": 2.5},
                "periods": {
                    "h1": {"away_mean": 0.3, "home_mean": 1.1, "p_home_win": 0.7},
                    "h2": {"away_mean": 0.5, "home_mean": 1.4, "p_home_win": 0.8},
                },
            },
        )
        rows = _normalize_game(game)["shared_lens_rows"]
        self.assertGreaterEqual(len(rows), 2)
        self.assertFalse(any(row.get("is_synthesized") for row in rows))

    def test_lens_rows_helper_keeps_a_stand_in_whose_main_is_not_the_summary(self) -> None:
        rows = [{"is_synthesized": True, "main": "COV 0.8 - ARS 2.5",
                 "market": NULL_PLACEHOLDER, "best_edge": NULL_PLACEHOLDER}]
        self.assertEqual(_build_lens_rows({"summary": SUMMARY}, rows), rows)


class TotalRowTests(unittest.TestCase):
    """G3 — the zero-bin distribution bar captioned with the competition name."""

    def test_a_total_row_with_no_projected_total_is_not_emitted(self) -> None:
        # Production rendered a full-width empty track labelled "Full Game"
        # and captioned "EPL" -- the caption being the stand-in row's
        # `subtitle`, i.e. `game.detail`, which is not a total at all.
        self.assertEqual(_normalize_game(_soccer_game())["shared_total_rows"], [])

    def test_a_real_projected_total_still_gets_its_bar(self) -> None:
        game = _soccer_game(
            sim={
                "score": {"away_mean": 0.8, "home_mean": 2.5},
                "periods": {"h1": {"away_mean": 0.3, "home_mean": 1.1}},
            },
        )
        rows = _normalize_game(game)["shared_total_rows"]
        self.assertTrue(rows)
        self.assertTrue(all(row["bins"] for row in rows))


class RepeatedCopyTests(unittest.TestCase):
    """G2 — one sentence, once."""

    def test_panel_items_do_not_each_restate_the_panel_body(self) -> None:
        # Production: a 3-item panel printed its body three times down Top
        # Plays, and the projected-score sentence appeared 6x on the card.
        rows = _normalize_game(_soccer_game())["shared_top_play_rows"]
        self.assertTrue(rows)
        bodies = [row["detail"] for row in rows]
        self.assertNotIn(
            "Highest anytime-goalscorer probability players from the simulated player-props pass.",
            bodies,
        )

    def test_a_keyed_item_splits_into_name_and_detail(self) -> None:
        game = _soccer_game(
            panels=[{
                "eyebrow": "Sim", "title": "Match projection", "body": SUMMARY,
                "items": ["Projected score: Coventry City 0.8 - Arsenal 2.5", "Simulations: 150"],
            }],
        )
        rows = _normalize_game(game)["shared_top_play_rows"]
        self.assertEqual(rows[0]["name"], "Projected score")
        self.assertEqual(rows[0]["detail"], "Coventry City 0.8 - Arsenal 2.5")
        self.assertEqual(rows[1]["name"], "Simulations")
        self.assertEqual(rows[1]["detail"], "150")

    def test_the_summary_is_not_reachable_through_the_top_play_rows(self) -> None:
        # The falsification test this lane wrote down: if the sentence still
        # arrives through a top-play row, the fix is in the wrong layer.
        rows = _normalize_game(_soccer_game())["shared_top_play_rows"]
        self.assertNotIn(SUMMARY, [row["detail"] for row in rows])
        self.assertNotIn(SUMMARY, [row["name"] for row in rows])


class PropStatusTests(unittest.TestCase):
    """G2 sibling — the props panel rendered the same five rows twice."""

    def test_panel_scraped_prop_rows_get_no_status_table(self) -> None:
        normalized = _normalize_game(_soccer_game())
        self.assertTrue(normalized["shared_prop_rows"])
        self.assertEqual(normalized["shared_prop_status_rows"], [])

    def test_real_prop_recommendations_keep_their_status_table(self) -> None:
        game = _soccer_game(
            prop_recommendations={
                "home": [{"player": "Kai Havertz", "display_pick": "Anytime scorer",
                          "tier": "A", "market": "anytime_scorer"}],
            },
        )
        normalized = _normalize_game(game)
        self.assertEqual(len(normalized["shared_prop_status_rows"]), 1)
        self.assertEqual(normalized["shared_prop_status_rows"][0]["value"], "A")

    def test_status_helper_filters_on_the_synthesized_flag_alone(self) -> None:
        rows = [{"name": "a", "is_synthesized": True}, {"name": "b"}]
        self.assertEqual(_build_prop_status_rows(rows), [{"name": "b"}])


class RenderedCardTests(unittest.TestCase):
    """The template half. Colour and layout need a browser (see
    `scripts/ui_layout_probe.py`); what is assertable here is which regions
    the card decides to emit at all."""

    def setUp(self) -> None:
        from syndicate.app import create_app

        self.app = create_app()
        self.app.config.update(TESTING=True)

    def _render(self, game: dict) -> str:
        with self.app.test_request_context("/"):
            from flask import render_template

            return render_template("shared/_game_card_generic.html", game=_normalize_game(game))

    @staticmethod
    def _panel(html: str, panel_id: str) -> str:
        # `cards-panel-card--overview-main` is used by the props panel too, so
        # "the lens is gone" has to be asserted inside the game panel or it
        # passes on the wrong element.
        return html.split(f'data-panel-id="{panel_id}"', 1)[1].split("</section>", 1)[0]

    def test_no_lens_panel_and_no_status_table_for_a_soccer_shaped_game(self) -> None:
        html = self._render(_soccer_game())
        game_panel = self._panel(html, "game")
        self.assertNotIn("cards-panel-card--overview-main", game_panel)
        self.assertNotIn("cards-live-lens-grid", game_panel)
        self.assertIn("cards-overview-grid--single", game_panel)
        self.assertNotIn("Official props status", html)
        # And the sentence that started this lane appears once.
        self.assertEqual(html.count(SUMMARY), 1)

    def test_the_three_way_bar_still_renders(self) -> None:
        html = self._render(_soccer_game())
        self.assertIn("cards-prob-bar--three-way", html)
        self.assertIn("cards-prob-draw", html)

    def test_only_one_empty_state_when_a_game_has_nothing(self) -> None:
        # The audit's NFL finding: the props panel shipped TWO
        # `.cards-empty-copy` blocks totalling 349 chars. One panel, one
        # message.
        html = self._render({"gamePk": "x", "away": {"abbr": "A", "name": "A"},
                             "home": {"abbr": "H", "name": "H"}, "status": "Scheduled"})
        props = html.split('data-panel-id="props"', 1)[1].split("</section>", 1)[0]
        self.assertEqual(props.count("cards-empty-copy"), 1)

    def test_a_sport_with_real_periods_keeps_its_lens_panel(self) -> None:
        game = _soccer_game(
            sim={
                "score": {"away_mean": 0.8, "home_mean": 2.5},
                "periods": {
                    "h1": {"away_mean": 0.3, "home_mean": 1.1, "p_home_win": 0.7},
                    "h2": {"away_mean": 0.5, "home_mean": 1.4, "p_home_win": 0.8},
                },
            },
        )
        game_panel = self._panel(self._render(game), "game")
        self.assertIn("cards-panel-card--overview-main", game_panel)
        self.assertIn("cards-live-lens-grid", game_panel)
        self.assertNotIn("cards-overview-grid--single", game_panel)

    def test_a_team_name_with_an_href_is_an_anchor_carrying_the_card_class(self) -> None:
        # The G1 defect was that this anchor had no colour rule, so it fell
        # through to the user-agent default (rgb(0, 0, 238), underlined). The
        # rule now lives in `dense_cards.css` keyed on `a.cards-head-team-name`,
        # so the markup has to keep producing exactly that selector.
        html = self._render(_soccer_game())
        self.assertIn('<a class="cards-head-team-name" href="/soccer/epl/team/arsenal"', html)


if __name__ == "__main__":  # pragma: no cover - convenience.
    unittest.main()
