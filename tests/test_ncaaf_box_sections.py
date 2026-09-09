"""Tests for the NCAAF card's real box score.

THE DEFECT THESE EXIST FOR WAS NOT A WRONG NUMBER. The box-score tab rendered
the shared contract's "Box score unavailable" placeholder for the whole 2026
preseason while every NCAAF test passed, because nothing asserted what the tab
CONTAINED. So the assertions here are about the rendered content and about the
four states being DISTINGUISHABLE, not about a key existing.

Two of them are deliberately negative:

  * `test_player_box_refuses_last_seasons_rows` -- the tracked CFBD snapshot is
    2025-only, and printing those rows under a 2026 game would be a fabricated
    box score that looks entirely plausible.
  * `test_overtime_binning_matches_segment_actuals` -- the OT column is checked
    against `segment_actuals` itself rather than against a hand-written
    expectation, so a future change to football's `h2` convention breaks this
    test instead of silently making the card disagree with the grader.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf import cards as ncaaf_cards  # noqa: E402
from syndicate.features.ncaaf.live_game_state import attach_ncaaf_live_game_state  # noqa: E402
from syndicate.features.shared import segment_actuals  # noqa: E402


def _card(**live_state) -> dict:
    game = {
        "gamePk": "1_Away_Home",
        "away": {"abbr": "AWY", "name": "Away State", "logo_url": "https://a.espncdn.com/i/teamlogos/ncaa/500/11.png"},
        "home": {"abbr": "HOM", "name": "Home State", "logo_url": "https://a.espncdn.com/i/teamlogos/ncaa/500/22.png"},
        "status": "Week 1",
        "ncaaf_card": {"scoreboard": {"away_points": 24.4, "home_points": 27.1, "source_label": "SmartSim 2.0"}},
    }
    if live_state:
        game["live_state"] = dict(live_state)
    return game


def _section(game: dict, title: str, *, season: int = 2026, week: int = 1) -> dict:
    sections = ncaaf_cards._ncaaf_box_sections(game, season=season, week=week)
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
        ["AWY", "7", "3", "0", "7", "17"],
        ["HOM", "0", "10", "7", "7", "24"],
    ]
    assert section["body"] == "Final."
    # The card-level chip fallback reads `shared_is_live`, which is FALSE on a
    # completed game -- so without a per-section chip a real final box score is
    # labelled "Sim" in the panel header.
    assert section["chip"] == "Final"


def test_overtime_gets_one_column_and_the_totals_still_add_up():
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
    assert section["columns"] == ["Team", "Q1", "Q2", "Q3", "Q4", "OT", "T"]
    # Both overtime periods collapse into the single OT cell: 7+7 and 7+4.
    assert section["table_rows"] == [
        ["AWY", "7", "7", "7", "9", "14", "44"],
        ["HOM", "10", "7", "0", "13", "11", "41"],
    ]
    assert "overtime" in section["body"].lower()


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
        "ncaaf",
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
    assert segment_actuals.segment_periods("ncaaf", "h2") == (3, 4, None)


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
    assert section["table_rows"] == [
        ["AWY", "7", "3", "—", "—", "10"],
        ["HOM", "7", "—", "—", "—", "7"],
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
    assert section["table_rows"][0] == ["AWY", "7", "—", "0", "7", "14"]


def test_pregame_states_why_rather_than_rendering_an_empty_grid():
    game = _card(in_progress=False, final=False, status="Sat 12:00 PM ET")
    section = _section(game, "Live / final box")
    assert "columns" not in section and "table_rows" not in section
    assert section["rows"] == []
    assert "kicks off" in section["body"]
    assert "Sat 12:00 PM ET" in section["body"]
    assert section["chip"] == "Pregame"


def test_started_without_published_periods_says_so():
    game = _card(in_progress=True, final=False, status="1st Quarter", period=1)
    section = _section(game, "Live / final box")
    assert "table_rows" not in section
    assert "per-quarter" in section["body"]


def test_missing_live_state_is_a_missing_reading_not_a_zero_zero_game():
    section = _section(_card(), "Live / final box")
    assert "table_rows" not in section
    assert "not been read" in section["body"]
    assert "0-0" in section["body"]
    assert section["chip"] == "No reading"


# --------------------------------------------------------------------------
# Section two: the player box, and the stale snapshot
# --------------------------------------------------------------------------


def test_player_box_refuses_last_seasons_rows(monkeypatch):
    """A 2025 row must never appear under a 2026 game."""
    last_season = (
        {
            "week": 1,
            "team": "Home State",
            "player_name": "Somebody From Last Year",
            "passing_yards": 300.0,
            "rushing_yards": 0.0,
            "receiving_yards": 0.0,
            "anytime_td": 3.0,
        },
    )

    def _rows(season: int, week: int):
        return last_season if season == 2025 else ()

    monkeypatch.setattr(ncaaf_cards, "_ncaaf_player_rows_for_week", _rows)
    section = _section(_card(), "Player box", season=2026, week=1)
    assert "table_rows" not in section
    assert section["rows"] == []
    assert "2026" in section["body"]
    assert "2025" in section["body"]
    assert "Somebody From Last Year" not in section["body"]


def test_player_box_renders_when_the_season_actually_has_rows(monkeypatch):
    monkeypatch.setattr(
        ncaaf_cards,
        "_ncaaf_player_rows_for_week",
        lambda season, week: (
            {
                "week": week,
                "team": "Home State",
                "player_name": "Real Quarterback",
                "passing_yards": 312.0,
                "rushing_yards": 18.0,
                "receiving_yards": 0.0,
                "anytime_td": 1.0,
            },
            {
                "week": week,
                "team": "Away State",
                "player_name": "Real Receiver",
                "passing_yards": 0.0,
                "rushing_yards": 0.0,
                "receiving_yards": 104.0,
                "anytime_td": 1.0,
            },
            {
                "week": week,
                "team": "Some Other School",
                "player_name": "Not In This Game",
                "passing_yards": 999.0,
                "rushing_yards": 0.0,
                "receiving_yards": 0.0,
                "anytime_td": 0.0,
            },
        ),
    )
    section = _section(_card(), "Player box", season=2026, week=1)
    assert section["columns"] == ["Player", "Tm", "Pass yds", "Rush yds", "Rec yds", "TD"]
    names = [row[0] for row in section["table_rows"]]
    assert names == ["Real Quarterback", "Real Receiver"]
    assert section["table_rows"][0] == ["Real Quarterback", "HOM", "312", "18", "0", "1"]


# --------------------------------------------------------------------------
# Wiring: the sim box survives, the contract keeps our sections, nothing raises
# --------------------------------------------------------------------------


def test_live_box_does_not_delete_the_sim_box():
    game = _card(final=True, in_progress=False, status="Final", away_pts=17, home_pts=24,
                 away_linescores=[7, 3, 0, 7], home_linescores=[0, 10, 7, 7])
    titles = [s["title"] for s in ncaaf_cards._ncaaf_box_sections(game, season=2026, week=1)]
    assert titles == ["Live / final box", "Sim box", "Player box"]


def test_linescores_are_carried_onto_the_card_by_the_live_state_join():
    game = _card()
    index = {
        "11@22": {
            "away_id": "11",
            "home_id": "22",
            "in_progress": False,
            "final": True,
            "status": "Final",
            "away_score": 17,
            "home_score": 24,
            "away_linescores": [7, 3, 0, 7],
            "home_linescores": [0, 10, 7, 7],
        }
    }
    coverage = attach_ncaaf_live_game_state([game], index)
    assert coverage["matched"] == 1
    assert game["live_state"]["away_linescores"] == [7, 3, 0, 7]
    assert game["live_state"]["home_linescores"] == [0, 10, 7, 7]


def test_absent_live_state_artifact_still_stamps_a_box_and_never_raises(monkeypatch):
    """The whole live-state read failing must cost the eyebrow, not the tab."""

    def _boom(*args, **kwargs):
        raise RuntimeError("live state artifact absent")

    monkeypatch.setattr(
        "syndicate.features.ncaaf.live_game_state.ncaaf_game_state_index", _boom
    )
    games = [_card()]
    ncaaf_cards._attach_live_state(games, 2026, 1)
    sections = games[0]["shared_box_sections"]
    assert [s["title"] for s in sections] == ["Live / final box", "Sim box", "Player box"]
    assert "not been read" in sections[0]["body"]


def test_shared_contract_keeps_the_ncaaf_sections():
    """`_normalize_game` must not overwrite a sport-supplied list.

    Without this the whole lane is inert: the placeholder would come straight
    back on the next board build and nothing else would look different.
    """
    from syndicate.features.shared.game_board_contract import apply_game_board_contract

    game = _card(final=True, in_progress=False, status="Final", away_pts=17, home_pts=24,
                 away_linescores=[7, 3, 0, 7], home_linescores=[0, 10, 7, 7])
    game["shared_box_sections"] = ncaaf_cards._ncaaf_box_sections(game, season=2026, week=1)
    context = apply_game_board_contract(
        {"date": "Week 1", "games": [game]}, sport="ncaaf", module="cards"
    )
    served = context["games"][0]["shared_box_sections"]
    assert [s["title"] for s in served] == ["Live / final box", "Sim box", "Player box"]
    assert "Box score unavailable" not in [s["title"] for s in served]
