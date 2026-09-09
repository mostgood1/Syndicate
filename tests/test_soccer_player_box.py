"""The soccer card's REAL per-player box score, and the chip that labels it.

Two defects are covered here, and they are the same defect seen from two
sides.

1. The per-player actuals were parsed and thrown away.
   ``espn_lineups.extract_match_player_rows`` has always yielded real goals,
   assists, shots and shots on target with a real starter flag, and
   ``espn_match_events.compute_minutes_played`` has always turned the same
   payload's ``keyEvents`` into exact minutes. ``build_match_box`` carried
   neither through, so soccer's box tab showed the sim's per-player
   projection and no per-player counterpart for what actually happened.

2. The chip beside it asked the wrong question.
   ``_game_card_generic.html`` rendered ``'Live' if live_state else 'Sim'``
   -- a property of the REQUEST, not of the table. A finished match's real,
   recorded box score was therefore labelled "Sim", and a live match's
   simulated squad projections were labelled "Live". Both directions are
   the same failure: a reader cannot tell a recorded number from a
   projected one.
"""

from __future__ import annotations

import io
import re
import unittest

import jinja2

from syndicate.features.soccer import cards
from syndicate.features.soccer.ingestion.espn_match_box import (
    build_match_box,
    extract_player_box,
    summary_clock_seconds,
)

_GENERIC_CARD = "syndicate/templates/shared/_game_card_generic.html"


def _player(
    player_id: str,
    name: str,
    *,
    starter: bool,
    position: str = "Midfielder",
    shots: float = 0.0,
    sot: float = 0.0,
    goals: float = 0.0,
    assists: float = 0.0,
) -> dict:
    return {
        "starter": starter,
        "subbedIn": not starter,
        "athlete": {"id": player_id, "displayName": name},
        "position": {"name": position},
        "stats": [
            {"name": "totalShots", "value": shots},
            {"name": "shotsOnTarget", "value": sot},
            {"name": "totalGoals", "value": goals},
            {"name": "goalAssists", "value": assists},
        ],
    }


def _final_summary() -> dict:
    """A finished match: rosters, a substitution, a goal, team stats.

    Shapes mirror a real ESPN ``summary`` response -- ``rosters`` for the
    per-player rows, raw ``keyEvents`` (parsed by ``extract_key_events``),
    ``boxscore.teams`` for team totals.
    """
    return {
        "header": {
            "competitions": [
                {
                    "status": {"clock": 5400.0, "displayClock": "90'", "type": {"state": "post"}},
                    "competitors": [
                        {"homeAway": "home", "linescores": [{"displayValue": "1"}, {"displayValue": "1"}]},
                        {"homeAway": "away", "linescores": [{"displayValue": "0"}, {"displayValue": "0"}]},
                    ],
                }
            ]
        },
        "rosters": [
            {
                "homeAway": "home",
                "team": {"displayName": "LA Galaxy"},
                "roster": [
                    _player("1", "Home Keeper", starter=True, position="Goalkeeper"),
                    _player("2", "Home Striker", starter=True, position="Forward", shots=4, sot=2, goals=1),
                    _player("3", "Home Sub", starter=False, shots=1, assists=1),
                    _player("4", "Unused Sub", starter=False),
                ],
            },
            {
                "homeAway": "away",
                "team": {"displayName": "LAFC"},
                "roster": [
                    _player("5", "Away Winger", starter=True, position="Forward", shots=3, sot=1),
                ],
            },
        ],
        "keyEvents": [
            {
                "type": {"text": "Goal", "type": "goal"},
                "period": {"number": 1},
                "clock": {"value": 1500.0, "displayValue": "25'"},
                "team": {"displayName": "LA Galaxy"},
                "participants": [{"athlete": {"id": "2", "displayName": "Home Striker"}}],
            },
            {
                "type": {"text": "Substitution", "type": "substitution"},
                "period": {"number": 2},
                "clock": {"value": 3600.0, "displayValue": "60'"},
                "team": {"displayName": "LA Galaxy"},
                "participants": [
                    {"athlete": {"id": "3", "displayName": "Home Sub"}},
                    {"athlete": {"id": "2", "displayName": "Home Striker"}},
                ],
            },
        ],
        "boxscore": {
            "teams": [
                {
                    "homeAway": "home",
                    "team": {"displayName": "LA Galaxy"},
                    "statistics": [{"name": "totalShots", "displayValue": "12"}],
                },
                {
                    "homeAway": "away",
                    "team": {"displayName": "LAFC"},
                    "statistics": [{"name": "totalShots", "displayValue": "7"}],
                },
            ]
        },
    }


def _pre_match_summary() -> dict:
    """A fixture that has not kicked off: no rosters, no events, no box."""
    return {
        "header": {
            "competitions": [
                {"status": {"clock": 0.0, "displayClock": "0'", "type": {"state": "pre"}}, "competitors": []}
            ]
        }
    }


class PlayerBoxExtractionTests(unittest.TestCase):
    def test_rows_map_from_a_realistic_summary(self) -> None:
        box = extract_player_box(_final_summary(), event_id="evt1")
        self.assertEqual(sorted(box), ["away", "home"])
        self.assertEqual(box["home"]["team"], "LA Galaxy")
        by_name = {row["player_name"]: row for row in box["home"]["players"]}
        striker = by_name["Home Striker"]
        self.assertEqual(striker["goals"], 1.0)
        self.assertEqual(striker["shots"], 4.0)
        self.assertEqual(striker["shots_on_target"], 2.0)
        self.assertTrue(striker["starter"])
        self.assertEqual(by_name["Home Sub"]["assists"], 1.0)
        self.assertFalse(by_name["Home Sub"]["starter"])

    def test_minutes_are_computed_for_a_substituted_player(self) -> None:
        """The sub came on at 60'. The player he replaced came off at 60'.
        Neither played 90 -- and the unused substitute did not play at all,
        which is a different fact from playing zero minutes."""
        box = extract_player_box(_final_summary(), event_id="evt1")
        by_name = {row["player_name"]: row for row in box["home"]["players"]}
        self.assertEqual(by_name["Home Striker"]["minutes"], 60.0)
        self.assertEqual(by_name["Home Sub"]["minutes"], 30.0)
        self.assertEqual(by_name["Home Keeper"]["minutes"], 90.0)
        self.assertIsNone(by_name["Unused Sub"]["minutes"])
        self.assertFalse(by_name["Unused Sub"]["appeared"])

    def test_a_live_clock_cuts_minutes_at_the_current_minute(self) -> None:
        """Minutes on an in-progress match must not read 90. A starter 25
        minutes in has played 25 -- printing the nominal full-time default
        would put a projected-looking number in an actuals column."""
        summary = _final_summary()
        summary["header"]["competitions"][0]["status"] = {"clock": 1500.0, "type": {"state": "in"}}
        summary["keyEvents"] = [summary["keyEvents"][0]]  # goal only, no sub yet
        self.assertEqual(summary_clock_seconds(summary), 1500.0)
        box = extract_player_box(summary, event_id="evt1")
        by_name = {row["player_name"]: row for row in box["home"]["players"]}
        self.assertEqual(by_name["Home Keeper"]["minutes"], 25.0)

    def test_a_pre_match_summary_yields_no_player_rows(self) -> None:
        self.assertEqual(extract_player_box(_pre_match_summary(), event_id="evt1"), {})

    def test_build_match_box_carries_players_through(self) -> None:
        """The regression this fixes: the rows were parsed and then dropped
        by `build_match_box`, which is the only writer the card reads."""
        record = build_match_box(_final_summary(), event_id="evt1")
        self.assertIn("players", record)
        self.assertEqual(len(record["players"]["home"]["players"]), 4)
        self.assertEqual(record["clock_seconds"], 5400.0)


class PlayerBoxSectionTests(unittest.TestCase):
    def _sections(self, state: str, *, final: bool):
        box = build_match_box(_final_summary(), event_id="evt1")
        return cards._match_box_sections(
            box, away_abbr="LAFC", home_abbr="LAG", final=final, state=state
        )

    def test_final_renders_a_player_table_per_side(self) -> None:
        titles = [section["title"] for section in self._sections("post", final=True)]
        self.assertEqual(titles, ["Goals", "Match stats", "LAFC player box", "LAG player box"])

    def test_the_player_table_holds_recorded_values_only(self) -> None:
        sections = self._sections("post", final=True)
        home = next(s for s in sections if s["title"] == "LAG player box")
        self.assertEqual(home["columns"], ["Player", "Pos", "Role", "Min", "G", "A", "Sh", "SOT"])
        self.assertEqual(home["kind"], "actual")
        # Starters first, then by minutes. The unused sub is not a row.
        self.assertEqual([row[0] for row in home["table_rows"]], ["Home Keeper", "Home Striker", "Home Sub"])
        striker = next(row for row in home["table_rows"] if row[0] == "Home Striker")
        self.assertEqual(striker[2:], ["XI", "60", "1", "0", "4", "2"])
        self.assertIn("did not appear", home["body"])
        self.assertIn("not projected", home["body"])

    def test_pre_match_yields_no_actuals_section_at_all(self) -> None:
        """Not an empty actuals table -- no actuals table. An empty actuals
        panel beside a populated projection panel invites reading the
        projection as the result."""
        box = build_match_box(_final_summary(), event_id="evt1")
        self.assertEqual(
            cards._match_box_sections(box, away_abbr="LAFC", home_abbr="LAG", final=False, state="pre"),
            [],
        )

    def test_a_missing_summary_degrades_to_a_stated_empty_state(self) -> None:
        for state, final in (("in", False), ("post", True)):
            with self.subTest(state=state):
                sections = cards._match_box_sections(
                    None, away_abbr="LAFC", home_abbr="LAG", final=final, state=state
                )
                self.assertEqual(len(sections), 1)
                self.assertEqual(sections[0]["title"], "Player box")
                self.assertEqual(sections[0]["kind"], "actual")
                self.assertIn("No match-feed summary", sections[0]["body"])
                self.assertFalse(sections[0].get("table_rows"))

    def test_a_summary_without_rosters_says_so_rather_than_rendering_a_blank_grid(self) -> None:
        box = build_match_box(_final_summary(), event_id="evt1")
        box["players"] = {}
        sections = cards._match_box_sections(
            box, away_abbr="LAFC", home_abbr="LAG", final=False, state="in"
        )
        stated = sections[-1]
        self.assertEqual(stated["title"], "Player box")
        self.assertIn("has not published lineups", stated["body"])

    def test_an_in_progress_box_states_the_minute_it_was_read_at(self) -> None:
        summary = _final_summary()
        summary["header"]["competitions"][0]["status"] = {"clock": 1500.0, "type": {"state": "in"}}
        box = build_match_box(summary, event_id="evt1")
        sections = cards._match_box_sections(
            box, away_abbr="LAFC", home_abbr="LAG", final=False, state="in"
        )
        home = next(s for s in sections if s["title"] == "LAG player box")
        self.assertIn("As of 25'", home["body"])


class BoxChipLabelTests(unittest.TestCase):
    """The chip must describe the SECTION, never the presence of a live-state
    object. Rendered through the template's own expression, extracted from the
    file, so this test fails if the template regresses."""

    @classmethod
    def setUpClass(cls) -> None:
        src = io.open(_GENERIC_CARD, encoding="utf-8").read()
        match = re.search(r'<span class="cards-chip">(\{\{ section\.chip.*?\}\})</span>', src)
        assert match, "the box-section chip expression is not in the generic card template"
        cls.expression = jinja2.Environment(autoescape=True).from_string(match.group(1))

    def _chip(self, section: dict, *, live_state) -> str:
        return self.expression.render(section=section, live_state=live_state)

    def test_a_finished_match_box_is_not_labelled_sim(self) -> None:
        """THE BUG. A settled match has no live-state object, so the old
        expression labelled its real, recorded box score "Sim"."""
        box = build_match_box(_final_summary(), event_id="evt1")
        sections = cards._match_box_sections(
            box, away_abbr="LAFC", home_abbr="LAG", final=True, state="post"
        )
        for section in sections:
            with self.subTest(title=section["title"]):
                self.assertEqual(self._chip(section, live_state=None), "Final box")

    def test_a_live_match_box_reads_live_box(self) -> None:
        box = build_match_box(_final_summary(), event_id="evt1")
        sections = cards._match_box_sections(
            box, away_abbr="LAFC", home_abbr="LAG", final=False, state="in"
        )
        for section in sections:
            with self.subTest(title=section["title"]):
                self.assertEqual(self._chip(section, live_state={"state": "in"}), "Live box")

    def test_projections_read_sim_even_while_the_match_is_live(self) -> None:
        """The mirror-image bug: with a live-state object attached, the sim's
        squad projections were chipped "Live"."""
        sections = cards._squad_box_sections(
            squad_props=[
                {
                    "side": "home",
                    "player_name": "Home Striker",
                    "position": "Forward",
                    "expected_shots": 2.4,
                    "expected_shots_on_target": 1.1,
                    "anytime_scorer_probability": 0.31,
                    "expected_minutes_share": 0.9,
                }
            ],
            prop_picks={},
            away_team="LAFC",
            home_team="LA Galaxy",
            away_abbr="LAFC",
            home_abbr="LAG",
            live_state={"state": "in"},
        )
        for section in sections:
            with self.subTest(title=section["title"]):
                self.assertEqual(section["kind"], "projection")
                self.assertEqual(self._chip(section, live_state={"state": "in"}), "Sim")

    def test_pre_match_projections_read_sim(self) -> None:
        sections = cards._squad_box_sections(
            squad_props=[],
            prop_picks={},
            away_team="LAFC",
            home_team="LA Galaxy",
            away_abbr="LAFC",
            home_abbr="LAG",
            live_state=None,
        )
        # No published props at all -> no sections; the card's own empty state
        # covers it. With props, the chip is "Sim" whatever the live state.
        self.assertEqual(sections, [])

    def test_actual_and_projection_titles_never_collide(self) -> None:
        """On screen the two panels must be tellable apart by title alone, not
        only by chip."""
        box = build_match_box(_final_summary(), event_id="evt1")
        actual = {
            s["title"]
            for s in cards._match_box_sections(
                box, away_abbr="LAFC", home_abbr="LAG", final=True, state="post"
            )
        }
        projected = {"LAFC squad projections", "LAG squad projections"}
        self.assertEqual(actual & projected, set())


if __name__ == "__main__":
    unittest.main()
