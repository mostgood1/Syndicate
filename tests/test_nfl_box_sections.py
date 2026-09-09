"""Tests for the NFL card's real box score.

THE DEFECT THESE EXIST FOR WAS NOT A WRONG NUMBER. NFL's box-score tab served
the shared contract's GENERIC derivation -- at best a two-row "Final score"
beside a two-row "Sim game box", no quarter scoring anywhere -- while every NFL
test passed, because nothing asserted what the tab CONTAINED. So the assertions
here are about rendered content and about the four states being
DISTINGUISHABLE, not about a key existing.

Two are deliberately about correspondence rather than a value:

  * `test_overtime_binning_matches_segment_actuals` -- the OT column is checked
    against `segment_actuals` itself rather than against a hand-written number,
    so a future change to football's `h2` convention breaks this test instead
    of silently making the card disagree with the grader that settles the bet.
  * `test_every_section_names_its_own_chip` -- the template's card-level
    fallback is `'Live' if shared_is_live else 'Sim'`, and `shared_is_live` is
    FALSE on a completed game. A section that does not name its own chip has a
    real, finished box score labelled "Sim". NCAAF and soccer both shipped that
    bug; this is the assertion that keeps NFL from re-acquiring it.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import cards as nfl_cards  # noqa: E402
from syndicate.features.nfl.live_game_state import _state_from_event  # noqa: E402
from syndicate.features.nfl.live_game_state import attach_nfl_live_game_state  # noqa: E402
from syndicate.features.shared import segment_actuals  # noqa: E402


def _card(**live_state) -> dict:
    game = {
        "gamePk": "401872656",
        "card_variant": "nfl_main",
        "away": {"abbr": "NE", "name": "New England Patriots"},
        "home": {"abbr": "SEA", "name": "Seattle Seahawks"},
        "status": "Week 1",
        "nfl_card": {
            "scoreboard": {"away_points": 21.6, "home_points": 24.3, "source_label": "SmartSim 2.0"}
        },
    }
    if live_state:
        game["live_state"] = dict(live_state)
    return game


def _section(game: dict, title: str, *, season: int = 2026, week: int = 1) -> dict:
    sections = nfl_cards._nfl_box_sections(game, season=season, week=week)
    matches = [s for s in sections if s["title"] == title]
    assert matches, f"no {title!r} section in {[s['title'] for s in sections]}"
    return matches[0]


# --------------------------------------------------------------------------
# Section one: the quarter linescore
# --------------------------------------------------------------------------


def test_final_regulation_linescore_maps_to_the_grid():
    game = _card(
        final=True,
        in_progress=False,
        status="Final",
        away_pts=17,
        home_pts=24,
        away_linescores=[7, 3, 0, 7],
        home_linescores=[0, 10, 7, 7],
    )
    section = _section(game, "Live / final box")
    assert section["columns"] == ["Team", "Q1", "Q2", "Q3", "Q4", "T"]
    assert section["table_rows"] == [
        ["NE", "7", "3", "0", "7", "17"],
        ["SEA", "0", "10", "7", "7", "24"],
    ]
    assert section["body"] == "Final."
    assert section["chip"] == "Final"


def test_overtime_gets_one_column_and_the_totals_still_add_up():
    game = _card(
        final=True,
        in_progress=False,
        status="Final/OT",
        away_pts=30,
        home_pts=33,
        away_linescores=[7, 7, 3, 10, 3],
        home_linescores=[10, 0, 7, 10, 6],
    )
    section = _section(game, "Live / final box")
    assert section["columns"] == ["Team", "Q1", "Q2", "Q3", "Q4", "OT", "T"]
    assert section["table_rows"] == [
        ["NE", "7", "7", "3", "10", "3", "30"],
        ["SEA", "10", "0", "7", "10", "6", "33"],
    ]
    assert "overtime" in section["body"].lower()
    # ESPN's "Final/OT" carries more than "Final" and is therefore kept.
    assert "Final/OT" in section["body"]


def test_multiple_overtime_periods_collapse_into_the_one_column():
    game = _card(
        final=True,
        in_progress=False,
        status="Final/2OT",
        away_pts=44,
        home_pts=41,
        away_linescores=[7, 7, 7, 9, 7, 7],
        home_linescores=[10, 7, 0, 13, 7, 4],
    )
    section = _section(game, "Live / final box")
    assert section["table_rows"] == [
        ["NE", "7", "7", "7", "9", "14", "44"],
        ["SEA", "10", "7", "0", "13", "11", "41"],
    ]


def test_overtime_binning_matches_segment_actuals():
    """Q3 + Q4 + OT on the card == what `segment_actuals` grades as `h2`.

    The card must not invent a second definition of "second half". If football
    `h2` ever stops being `(3, 4, None)`, this fails here rather than quietly
    on a card someone compares against a settled second-half bet.
    """
    away = [7, 7, 7, 9, 7, 7]
    home = [10, 7, 0, 13, 7, 4]
    game = _card(
        final=True,
        in_progress=False,
        status="Final/2OT",
        away_pts=sum(away),
        home_pts=sum(home),
        away_linescores=away,
        home_linescores=home,
    )
    section = _section(game, "Live / final box")
    index = {name: pos for pos, name in enumerate(section["columns"])}
    graded = segment_actuals.segment_actuals(
        "nfl",
        "h2",
        {
            "home_linescores": home,
            "away_linescores": away,
            "final": True,
            "in_progress": False,
        },
    )
    for row, side in zip(section["table_rows"], ("away", "home")):
        card_h2 = int(row[index["Q3"]]) + int(row[index["Q4"]]) + int(row[index["OT"]])
        assert card_h2 == graded[f"{side}_score"], side
    # And the convention itself, pinned so a change to it is visible here.
    assert segment_actuals.segment_periods("nfl", "h2") == (3, 4, None)


def test_in_progress_shows_played_quarters_and_marks_the_rest():
    game = _card(
        in_progress=True,
        final=False,
        status="2nd Quarter",
        period=2,
        clock="4:12",
        away_pts=10,
        home_pts=7,
        away_linescores=[7, 3],
        home_linescores=[7],
    )
    section = _section(game, "Live / final box")
    assert section["columns"] == ["Team", "Q1", "Q2", "Q3", "Q4", "T"]
    # NEVER BLANK for an unplayed quarter -- a blank cell reads as "zero".
    assert section["table_rows"] == [
        ["NE", "7", "3", "—", "—", "10"],
        ["SEA", "7", "—", "—", "—", "7"],
    ]
    assert "In progress" in section["body"]
    assert "4:12" in section["body"]
    assert section["chip"] == "Live"


def test_a_hole_in_the_linescore_is_not_rendered_as_zero():
    game = _card(
        final=True,
        in_progress=False,
        status="Final",
        away_pts=14,
        home_pts=7,
        away_linescores=[7, None, 0, 7],
        home_linescores=[0, 7, 0, 0],
    )
    section = _section(game, "Live / final box")
    assert section["table_rows"][0] == ["NE", "7", "—", "0", "7", "14"]


def test_pregame_states_why_rather_than_rendering_an_empty_grid():
    game = _card(in_progress=False, final=False, status="9/9 - 8:20 PM EDT")
    section = _section(game, "Live / final box")
    assert "columns" not in section and "table_rows" not in section
    assert section["rows"] == []
    assert "kicks off" in section["body"]
    assert "9/9 - 8:20 PM EDT" in section["body"]
    assert section["chip"] == "Pregame"


def test_started_without_published_periods_says_so():
    game = _card(in_progress=True, final=False, status="1st Quarter", period=1)
    section = _section(game, "Live / final box")
    assert "table_rows" not in section
    assert "per-quarter" in section["body"]
    assert section["chip"] == "Live"


def test_missing_live_state_is_a_missing_reading_not_a_zero_zero_game():
    section = _section(_card(), "Live / final box")
    assert "table_rows" not in section
    assert "not been read" in section["body"]
    assert "0-0" in section["body"]
    assert section["chip"] == "No reading"


# --------------------------------------------------------------------------
# The chip, in all four states -- the bug both sibling sports shipped
# --------------------------------------------------------------------------


def test_every_section_names_its_own_chip():
    """No section may fall through to the template's card-level fallback.

    `_game_card_ncaaf.html` renders
    `section.chip if section.chip else ('Live' if live_state else 'Sim')`,
    where `live_state` is `shared_is_live` -- false once a game is FINAL. A
    chipless section therefore labels a real completed box score "Sim".
    """
    for game in (
        _card(),
        _card(in_progress=False, final=False, status="9/9 - 8:20 PM EDT"),
        _card(in_progress=True, final=False, status="2nd Quarter", period=2,
              away_pts=10, home_pts=7, away_linescores=[7, 3], home_linescores=[7]),
        _card(final=True, in_progress=False, status="Final", away_pts=17, home_pts=24,
              away_linescores=[7, 3, 0, 7], home_linescores=[0, 10, 7, 7]),
    ):
        for section in nfl_cards._nfl_box_sections(game, season=2026, week=1):
            assert section.get("chip"), (section["title"], game.get("live_state"))


def test_chip_reads_the_content_not_the_request():
    """Pregame / live / final each get their own label, and Sim stays Sim."""
    pregame = _card(in_progress=False, final=False, status="9/9 - 8:20 PM EDT")
    live = _card(in_progress=True, final=False, status="2nd Quarter", period=2,
                 away_pts=10, home_pts=7, away_linescores=[7, 3], home_linescores=[7])
    final = _card(final=True, in_progress=False, status="Final", away_pts=17, home_pts=24,
                  away_linescores=[7, 3, 0, 7], home_linescores=[0, 10, 7, 7])
    assert _section(pregame, "Live / final box")["chip"] == "Pregame"
    assert _section(live, "Live / final box")["chip"] == "Live"
    assert _section(final, "Live / final box")["chip"] == "Final"
    # And the projection is chipped Sim even while the game is LIVE -- the
    # other direction of the same bug, which is how soccer shipped it.
    assert _section(live, "Sim box")["chip"] == "Sim"
    assert _section(final, "Sim box")["chip"] == "Sim"


# --------------------------------------------------------------------------
# The producer: linescores must survive the ESPN read and the join
# --------------------------------------------------------------------------


def _espn_event(state: str, *, completed: bool, linescores: bool) -> dict:
    def _side(side: str, abbr: str, score: str, values: list[int]) -> dict:
        row = {"homeAway": side, "team": {"abbreviation": abbr}, "score": score}
        if linescores:
            row["linescores"] = [
                {"value": float(v), "displayValue": str(v), "period": i}
                for i, v in enumerate(values, start=1)
            ]
        return row

    return {
        "id": "401872656",
        "date": "2026-09-10T00:20Z",
        "status": {
            "period": 4,
            "displayClock": "0:00",
            "type": {"state": state, "completed": completed, "shortDetail": "Final"},
        },
        "competitions": [
            {
                "competitors": [
                    _side("away", "NE", "17", [7, 3, 0, 7]),
                    _side("home", "SEA", "24", [0, 10, 7, 7]),
                ]
            }
        ],
    }


def test_espn_scoreboard_linescores_are_read_rather_than_dropped():
    """The NCAAF root cause, checked on NFL's own reader.

    `competitors[].linescores[]` was in this payload the whole time and
    `_state_from_event` copied out only the aggregate score.
    """
    state = _state_from_event(_espn_event("post", completed=True, linescores=True))
    assert state["away_linescores"] == [7, 3, 0, 7]
    assert state["home_linescores"] == [0, 10, 7, 7]


def test_pregame_event_carries_no_linescores_at_all():
    """`None`, not `[]`. An empty list downstream reads as 'played, scored 0'."""
    state = _state_from_event(_espn_event("pre", completed=False, linescores=False))
    assert state["away_linescores"] is None
    assert state["home_linescores"] is None


def test_linescores_are_carried_onto_the_card_by_the_live_state_join():
    game = _card()
    index = {
        "401872656": {
            "event_id": "401872656",
            "away_abbr": "NE",
            "home_abbr": "SEA",
            "in_progress": False,
            "final": True,
            "status": "Final",
            "away_pts": 17,
            "home_pts": 24,
            "away_linescores": [7, 3, 0, 7],
            "home_linescores": [0, 10, 7, 7],
        }
    }
    coverage = attach_nfl_live_game_state([game], index)
    assert coverage["matched"] == 1
    assert game["live_state"]["away_linescores"] == [7, 3, 0, 7]
    assert game["live_state"]["home_linescores"] == [0, 10, 7, 7]


def test_join_never_invents_an_empty_linescore_on_a_pregame_card():
    game = _card()
    index = {
        "401872656": {
            "event_id": "401872656",
            "away_abbr": "NE",
            "home_abbr": "SEA",
            "in_progress": False,
            "final": False,
            "status": "9/9 - 8:20 PM EDT",
            "away_linescores": None,
            "home_linescores": None,
        }
    }
    attach_nfl_live_game_state([game], index)
    assert "away_linescores" not in game["live_state"]
    assert "home_linescores" not in game["live_state"]


# --------------------------------------------------------------------------
# Wiring: the sim box survives, the contract keeps our sections, nothing raises
# --------------------------------------------------------------------------


def test_live_box_does_not_delete_the_sim_box():
    game = _card(final=True, in_progress=False, status="Final", away_pts=17, home_pts=24,
                 away_linescores=[7, 3, 0, 7], home_linescores=[0, 10, 7, 7])
    titles = [s["title"] for s in nfl_cards._nfl_box_sections(game, season=2026, week=1)]
    # The TEAM-level "Sim box" survives the per-player projection panels that
    # were added beside it -- the same rule one level down: adding player
    # detail must not delete the team projection other surfaces quote.
    assert titles[:3] == ["Live / final box", "Sim box", "Player box"]
    assert titles[3:], "the sim player projection panel(s) went missing"


def test_attach_stamps_every_card_including_one_with_no_reading():
    games = [_card(), _card(final=True, in_progress=False, status="Final", away_pts=17,
                            home_pts=24, away_linescores=[7, 3, 0, 7],
                            home_linescores=[0, 10, 7, 7])]
    assert nfl_cards.attach_nfl_box_sections(games, 2026, 1) == 2
    assert "not been read" in games[0]["shared_box_sections"][0]["body"]
    assert games[1]["shared_box_sections"][0]["table_rows"]


def test_a_broken_card_never_costs_the_board(monkeypatch):
    """A box must never take the slate down -- one bad card, the rest stamped."""

    def _boom(game, *, season, week):
        if game.get("gamePk") == "boom":
            raise RuntimeError("bad card")
        return [{"title": "Live / final box", "chip": "No reading", "body": "", "rows": []}]

    monkeypatch.setattr(nfl_cards, "_nfl_box_sections", _boom)
    good = _card()
    bad = _card()
    bad["gamePk"] = "boom"
    assert nfl_cards.attach_nfl_box_sections([bad, good], 2026, 1) == 1
    assert "shared_box_sections" not in bad
    assert good["shared_box_sections"]


def test_shared_contract_keeps_the_nfl_sections():
    """`_normalize_game` must not overwrite a sport-supplied list.

    Without this the whole lane is inert: the generic two-row derivation would
    come straight back on the next board build and nothing would look different.
    """
    from syndicate.features.shared.game_board_contract import apply_game_board_contract

    game = _card(final=True, in_progress=False, status="Final", away_pts=17, home_pts=24,
                 away_linescores=[7, 3, 0, 7], home_linescores=[0, 10, 7, 7])
    game["shared_box_sections"] = nfl_cards._nfl_box_sections(game, season=2026, week=1)
    context = apply_game_board_contract(
        {"date": "2026 Week 1", "games": [game]}, sport="nfl", module="cards"
    )
    served = context["games"][0]["shared_box_sections"]
    titles = [s["title"] for s in served]
    assert titles[:3] == ["Live / final box", "Sim box", "Player box"]
    # Whatever state the projection artifact is in on this machine, its
    # panel(s) must survive the contract too.
    assert titles[3:]
    assert served[0]["table_rows"][0] == ["NE", "7", "3", "0", "7", "17"]


# --------------------------------------------------------------------------
# Section three: real player lines off the game feed
# --------------------------------------------------------------------------


def _summary(groups_by_team: dict) -> dict:
    return {
        "boxscore": {
            "teams": [],
            "players": [
                {"team": {"abbreviation": abbr}, "statistics": groups}
                for abbr, groups in groups_by_team.items()
            ],
        }
    }


_PASSING = ["completions/passingAttempts", "passingYards", "yardsPerPassAttempt",
            "passingTouchdowns", "interceptions"]
_RUSHING = ["rushingAttempts", "rushingYards", "yardsPerRushAttempt", "rushingTouchdowns"]
_RECEIVING = ["receptions", "receivingYards", "yardsPerReception", "receivingTouchdowns"]


def _real_shaped_summary() -> dict:
    """The shape ESPN actually returns -- verified on event 401873297."""
    return _summary(
        {
            "SEA": [
                {"name": "passing", "keys": _PASSING, "labels": ["C/ATT", "YDS", "AVG", "TD", "INT"],
                 "athletes": [{"athlete": {"id": "1", "displayName": "Drew Lock"},
                               "stats": ["12/14", "103", "7.4", "1", "0"]}]},
                {"name": "rushing", "keys": _RUSHING, "labels": ["CAR", "YDS", "AVG", "TD"],
                 "athletes": [
                     {"athlete": {"id": "1", "displayName": "Drew Lock"}, "stats": ["2", "8", "4.0", "0"]},
                     {"athlete": {"id": "2", "displayName": "Jacardia Wright"},
                      "stats": ["8", "81", "10.1", "1"]},
                 ]},
                {"name": "receiving", "keys": _RECEIVING, "labels": ["REC", "YDS", "AVG", "TD"],
                 "athletes": [
                     {"athlete": {"id": "2", "displayName": "Jacardia Wright"},
                      "stats": ["1", "12", "12.0", "0"]},
                     {"athlete": {"id": "3", "displayName": "Elijah Arroyo"},
                      "stats": ["2", "50", "25.0", "1"]},
                 ]},
                {"name": "defensive", "keys": ["totalTackles", "soloTackles", "sacks"],
                 "labels": ["TOT", "SOLO", "SACKS"],
                 "athletes": [{"athlete": {"id": "9", "displayName": "A Linebacker"},
                               "stats": ["10", "2", "0"]}]},
            ],
            "NE": [
                {"name": "passing", "keys": _PASSING, "labels": ["C/ATT", "YDS", "AVG", "TD", "INT"],
                 "athletes": [{"athlete": {"id": "4", "displayName": "A Quarterback"},
                               "stats": ["9/17", "69", "4.1", "0", "1"]}]},
            ],
        }
    )


def test_player_rows_merge_the_three_groups_per_athlete():
    from syndicate.features.nfl.live_player_box import player_rows_from_summary

    rows = {r["player_name"]: r for r in player_rows_from_summary(_real_shaped_summary())}
    assert rows["Drew Lock"]["pass_yards"] == 103.0
    assert rows["Drew Lock"]["pass_td"] == 1.0
    # The SAME athlete's rushing line merges in rather than becoming a 2nd row.
    assert rows["Drew Lock"]["rush_yards"] == 8.0
    assert rows["Jacardia Wright"]["rush_yards"] == 81.0
    assert rows["Jacardia Wright"]["rec_yards"] == 12.0
    assert rows["Jacardia Wright"]["td_scored"] == 1.0
    assert rows["Jacardia Wright"]["team_abbr"] == "SEA"
    # A defensive-only line has no cell in this grid and is dropped, not zeroed
    # into a row that would push a real skill player off the table.
    assert "A Linebacker" not in rows


def test_a_passing_touchdown_is_not_counted_as_an_anytime_touchdown():
    """It is the SAME score as its receiver's; summing all three double-counts."""
    from syndicate.features.nfl.live_player_box import player_rows_from_summary

    rows = {r["player_name"]: r for r in player_rows_from_summary(_real_shaped_summary())}
    assert rows["Drew Lock"]["td_scored"] == 0.0
    assert rows["Elijah Arroyo"]["td_scored"] == 1.0


def test_stats_are_read_by_key_position_not_by_label():
    """`labels` are display strings; `keys` name the stat. One source, in order."""
    from syndicate.features.nfl.live_player_box import player_rows_from_summary

    payload = _summary(
        {
            "SEA": [
                {
                    "name": "rushing",
                    "keys": _RUSHING,
                    "labels": ["WHATEVER", "THESE", "SAY", "NOW"],
                    "athletes": [
                        {"athlete": {"id": "7", "displayName": "Runner"},
                         "stats": ["9", "77", "8.6", "2"]}
                    ],
                }
            ]
        }
    )
    row = player_rows_from_summary(payload)[0]
    assert row["rush_yards"] == 77.0 and row["td_scored"] == 2.0


def test_a_summary_with_no_player_block_is_none_not_empty():
    """`None` = never read. `[]` = read, nobody has a line. Different states."""
    from syndicate.features.nfl.live_player_box import player_rows_from_summary

    assert player_rows_from_summary(None) is None
    assert player_rows_from_summary({}) is None
    # ESPN posts `boxscore.teams` before `boxscore.players` on a fresh kickoff.
    assert player_rows_from_summary({"boxscore": {"teams": []}}) is None
    assert player_rows_from_summary({"boxscore": {"teams": [], "players": []}}) == []


def _started(final: bool, **extra) -> dict:
    return _card(
        final=final,
        in_progress=not final,
        status="Final" if final else "2nd Quarter",
        event_id="401872656",
        away_pts=17,
        home_pts=24,
        away_linescores=[7, 3, 0, 7] if final else [7, 3],
        home_linescores=[0, 10, 7, 7] if final else [7],
        **extra,
    )


def test_player_box_renders_the_real_lines_on_a_final_game():
    from syndicate.features.nfl.live_player_box import player_rows_from_summary

    game = _started(final=True)
    game["live_player_box"] = player_rows_from_summary(_real_shaped_summary())
    section = _section(game, "Player box")
    assert section["columns"] == [
        "Player", "Tm", "Pass yds", "Pass TD", "Rush yds", "Rec yds", "TD scored"
    ]
    assert section["table_rows"][0] == ["Drew Lock", "SEA", "103", "1", "8", "0", "0"]
    names = [row[0] for row in section["table_rows"]]
    assert names == ["Drew Lock", "Jacardia Wright", "A Quarterback", "Elijah Arroyo"]
    assert section["chip"] == "Final"


def test_a_live_game_says_the_lines_are_as_of_a_moment():
    from syndicate.features.nfl.live_player_box import player_rows_from_summary

    game = _started(final=False, period=2, clock="4:12")
    game["live_player_box"] = player_rows_from_summary(_real_shaped_summary())
    section = _section(game, "Player box")
    assert section["chip"] == "Live"
    assert "AS OF" in section["body"]
    assert "4:12" in section["body"]


def test_pregame_player_box_states_it_and_refuses_the_lagging_artifact():
    game = _card(in_progress=False, final=False, status="9/9 - 8:20 PM EDT")
    section = _section(game, "Player box")
    assert "table_rows" not in section
    assert "has not kicked off" in section["body"]
    assert "pbp_2026.csv" in section["body"]
    assert section["chip"] == "Pregame"


def test_a_missing_summary_degrades_to_a_stated_state_not_an_empty_table():
    """Started, but the fetch never answered -- say so, substitute nothing."""
    section = _section(_started(final=True), "Player box")
    assert "table_rows" not in section
    assert "could not be read" in section["body"]
    assert "substituted" in section["body"]
    assert section["chip"] == "Not read"


def test_read_but_empty_is_said_differently_from_never_read():
    game = _started(final=False, period=1, clock="12:44")
    game["live_player_box"] = []
    section = _section(game, "Player box")
    assert "has not published a player box" in section["body"]
    assert section["chip"] == "Live"


def test_no_live_state_at_all_is_a_missing_reading():
    section = _section(_card(), "Player box")
    assert "missing reading" in section["body"]
    assert section["chip"] == "No reading"


def test_only_started_games_are_ever_fetched(monkeypatch):
    """A Thursday board must cost ZERO summary calls."""
    calls: list = []

    def _index(events):
        events = list(events)
        calls.append(events)
        return {event_id: [] for event_id, _ in events}

    monkeypatch.setattr(
        "syndicate.features.nfl.live_player_box.nfl_player_box_index", _index
    )
    pregame = _card(in_progress=False, final=False, status="9/9 - 8:20 PM EDT",
                    event_id="401872657")
    coverage = nfl_cards.attach_nfl_player_box([pregame, _card()], season=2026, week=1)
    assert calls == []
    assert coverage == {"requested": 0, "read": 0, "games": 2}

    started = _started(final=True)
    coverage = nfl_cards.attach_nfl_player_box([pregame, started], season=2026, week=1)
    assert calls == [[("401872656", True)]]
    assert coverage["requested"] == 1 and coverage["read"] == 1
    assert "live_player_box" not in pregame


def test_a_failing_fetch_never_costs_the_board(monkeypatch):
    def _boom(events):
        raise RuntimeError("espn unreachable")

    monkeypatch.setattr(
        "syndicate.features.nfl.live_player_box.nfl_player_box_index", _boom
    )
    started = _started(final=True)
    coverage = nfl_cards.attach_nfl_player_box([started], season=2026, week=1)
    assert coverage == {"requested": 1, "read": 0, "games": 1}
    assert "live_player_box" not in started
    # And the section still renders, saying what is missing.
    section = _section(started, "Player box")
    assert "could not be read" in section["body"]


def test_the_event_id_survives_the_live_state_join():
    """NFL's `gamePk` is nflverse-shaped, so the ESPN id has to be carried."""
    game = _card()
    game["gamePk"] = "2026_01_NE_SEA"
    index = {
        "NE@SEA": {
            "event_id": "401872656",
            "away_abbr": "NE",
            "home_abbr": "SEA",
            "in_progress": True,
            "final": False,
            "status": "2nd Quarter",
            "away_pts": 10,
            "home_pts": 7,
            "away_linescores": [7, 3],
            "home_linescores": [7],
        }
    }
    attach_nfl_live_game_state([game], index)
    assert game["live_state"]["event_id"] == "401872656"
