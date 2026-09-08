"""Per-period actuals for segment settlement: the helper, and the pollers that
now persist what it reads.

WHY THESE ARE WRITTEN AGAINST THE PRODUCER AS WELL AS THE HELPER. A grader
that can read `home_linescores` is inert if nothing writes the field -- the
"26 input fields the simulation reads and nothing feeds" shape
`model_engine_standard.md` exists to prevent. So the NFL and NCAAF pollers'
`_game_from_event`, the soccer summary reader and the soccer finals publisher
are each asserted to EMIT the field, on the ESPN shapes verified 2026-09-08:

    scoreboard (NFL 401772830, NCAAF 401858438)
        linescores = [{"value": 7.0, "displayValue": "7", "period": 1}, ...]
    soccer scoreboard (EPL 401879317)
        linescores = null                      <- nothing to read here
    soccer SUMMARY header, same match
        linescores = [{"displayValue": "3"}, {"displayValue": "1"}]

The overtime rule is pinned in both directions: `h2` INCLUDES overtime and
`q4` does not, because that is the convention the orders were priced under.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import segment_actuals as sa


# ---------------------------------------------------------------------------
# 1. The score pair
# ---------------------------------------------------------------------------

HOME = [7, 10, 3, 4, 6]   # q1..q4 + OT
AWAY = [0, 7, 7, 3, 0]


def test_h1_is_the_first_two_periods():
    assert sa.segment_score_pair("nfl", "h1", home_linescores=HOME, away_linescores=AWAY) == (17, 7)


def test_q1_is_the_first_period_alone():
    assert sa.segment_score_pair("ncaaf", "q1", home_linescores=HOME, away_linescores=AWAY) == (7, 0)


def test_h2_INCLUDES_overtime_and_q4_does_NOT():
    """The sportsbook convention: second-half lines settle on everything after
    the half, fourth-quarter lines on the fourth quarter alone. Grading h2 as
    q3+q4 would settle a second-half over as LOST on a game decided in OT."""
    assert sa.segment_score_pair("nfl", "h2", home_linescores=HOME, away_linescores=AWAY) == (13, 10)
    assert sa.segment_score_pair("nfl", "q4", home_linescores=HOME, away_linescores=AWAY) == (4, 3)


def test_soccer_halves_are_periods_1_and_2():
    assert sa.segment_score_pair("soccer", "h1", home_linescores=[2, 1], away_linescores=[1, 0]) == (2, 1)
    assert sa.segment_score_pair("soccer", "h2", home_linescores=[2, 1], away_linescores=[1, 0]) == (1, 0)


def test_a_segment_the_sport_does_not_play_is_none():
    assert sa.segment_score_pair("nfl", "first5", home_linescores=HOME, away_linescores=AWAY) is None
    assert sa.segment_score_pair("soccer", "q1", home_linescores=[1, 1], away_linescores=[0, 0]) is None


def test_one_side_missing_refuses_both_together():
    """A first-half total with the away half missing must not read as a shutout."""
    assert sa.segment_score_pair("nfl", "h1", home_linescores=HOME, away_linescores=None) is None


def test_a_partial_segment_in_play_is_a_current_value():
    """h1 in the first quarter: q2 has not happened, and the running value is q1."""
    assert sa.segment_score_pair("nfl", "h1", home_linescores=[7], away_linescores=[3]) == (7, 3)


def test_a_hole_in_the_middle_of_a_segment_refuses():
    """A None at period 1 with period 2 present is a feed defect, not a zero."""
    assert sa.segment_score_pair("nfl", "h1", home_linescores=[None, 10], away_linescores=[0, 7]) is None


# ---------------------------------------------------------------------------
# 2. Finality is the SEGMENT's, not the game's
# ---------------------------------------------------------------------------


def test_q1_closes_when_period_2_begins():
    assert sa.segment_is_final("nfl", "q1", game_final=False, period=2) is True
    assert sa.segment_is_final("nfl", "q1", game_final=False, period=1) is False


def test_h1_closes_at_halftime_even_though_espn_still_says_period_2():
    assert sa.segment_is_final("ncaaf", "h1", game_final=False, period=2) is False
    assert sa.segment_is_final("ncaaf", "h1", game_final=False, period=2, halftime=True) is True


def test_h2_closes_ONLY_with_the_game_because_it_includes_overtime():
    assert sa.segment_is_final("nfl", "h2", game_final=False, period=5) is False
    assert sa.segment_is_final("nfl", "h2", game_final=True, period=5) is True


def test_q4_closes_when_overtime_begins():
    assert sa.segment_is_final("nfl", "q4", game_final=False, period=5) is True


def test_soccer_h1_closes_in_the_second_half():
    assert sa.segment_is_final("soccer", "h1", game_final=False, period=2) is True
    assert sa.segment_is_final("soccer", "h1", game_final=False, period=1) is False


# ---------------------------------------------------------------------------
# 3. `segment_actuals` on a captured record
# ---------------------------------------------------------------------------


def _record(**over):
    row = {
        "home_score": 30, "away_score": 17,
        "home_linescores": HOME, "away_linescores": AWAY,
        "period": 5, "in_progress": False, "final": True, "status": "Final/OT",
    }
    row.update(over)
    return row


def test_a_final_game_answers_every_segment():
    out = sa.segment_actuals("nfl", "h1", _record())
    assert out == {"home_score": 17, "away_score": 7, "is_final": True, "started": True}


def test_MISSING_linescores_refuse_BY_NAME_and_never_fall_back_to_the_game_score():
    """The whole reason this module exists. A capture written before the field
    shipped carries the full-game score and nothing per period; the answer is
    a named refusal, not `home_score + away_score`."""
    out = sa.segment_actuals("nfl", "h1", _record(home_linescores=None, away_linescores=None))
    assert out == {"unavailable_reason": "segment_actual_unavailable:h1"}


def test_an_unsupported_segment_refuses_by_its_own_name():
    out = sa.segment_actuals("nfl", "first5", _record())
    assert out == {"unavailable_reason": "unsupported_segment:first5"}


def test_a_segment_that_has_not_begun_is_NOT_STARTED_rather_than_refused():
    """Fourth quarter in the first: not unanswerable, not yet asked."""
    out = sa.segment_actuals(
        "nfl", "q4",
        _record(home_linescores=[7], away_linescores=[0], period=1, in_progress=True, final=False, status="Q1 8:05"),
    )
    assert out["started"] is False
    assert out.get("unavailable_reason") is None


def test_an_in_play_first_half_is_a_value_and_not_final():
    out = sa.segment_actuals(
        "nfl", "h1",
        _record(home_linescores=[7, 3], away_linescores=[0, 7], period=2, in_progress=True, final=False, status="Q2 3:12"),
    )
    assert out == {"home_score": 10, "away_score": 7, "is_final": False, "started": True}


def test_halftime_status_text_closes_the_first_half():
    out = sa.segment_actuals(
        "ncaaf", "h1",
        _record(home_linescores=[7, 3], away_linescores=[0, 7], period=2, in_progress=True, final=False, status="Halftime"),
    )
    assert out["is_final"] is True


# ---------------------------------------------------------------------------
# 4. Reading ESPN's two linescore shapes
# ---------------------------------------------------------------------------


def test_the_scoreboard_shape_is_placed_by_period():
    row = {"linescores": [
        {"value": 7.0, "displayValue": "7", "period": 1},
        {"value": 3.0, "displayValue": "3", "period": 2},
    ]}
    assert sa.linescores_from_competitor(row) == [7, 3]


def test_the_soccer_summary_shape_has_no_period_and_relies_on_order():
    row = {"linescores": [{"displayValue": "3"}, {"displayValue": "1"}]}
    assert sa.linescores_from_competitor(row) == [3, 1]


def test_a_skipped_period_leaves_a_hole_instead_of_shifting_later_periods_left():
    row = {"linescores": [{"value": 7, "period": 1}, {"value": 14, "period": 3}]}
    assert sa.linescores_from_competitor(row) == [7, None, 14]


def test_null_linescores_read_as_NOT_PROVIDED_not_as_empty():
    assert sa.linescores_from_competitor({"linescores": None}) is None
    assert sa.linescores_from_competitor({}) is None


# ---------------------------------------------------------------------------
# 5. The producers -- the half that makes the helper reachable
# ---------------------------------------------------------------------------


def _football_event(state="post", completed=True, period=4):
    return {
        "id": "401772830",
        "date": "2025-09-07T17:00Z",
        "status": {"period": period, "type": {"state": state, "completed": completed, "shortDetail": "Final"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": "20", "team": {"displayName": "Atlanta Falcons", "abbreviation": "ATL"},
             "linescores": [{"value": 7.0, "period": 1}, {"value": 3.0, "period": 2}, {"value": 3.0, "period": 3}, {"value": 7.0, "period": 4}]},
            {"homeAway": "away", "score": "23", "team": {"displayName": "Tampa Bay Buccaneers", "abbreviation": "TB"},
             "linescores": [{"value": 0.0, "period": 1}, {"value": 10.0, "period": 2}, {"value": 7.0, "period": 3}, {"value": 6.0, "period": 4}]},
        ]}],
    }


@pytest.mark.parametrize("module_name", ["scripts.poll_nfl_live_state", "scripts.poll_ncaaf_live_state"])
def test_the_football_pollers_PERSIST_linescores_for_a_played_game(module_name):
    import importlib

    game = importlib.import_module(module_name)._game_from_event(_football_event())

    assert game["home_linescores"] == [7, 3, 3, 7]
    assert game["away_linescores"] == [0, 10, 7, 6]
    # And the helper reads what the poller wrote, end to end.
    assert sa.segment_actuals("nfl", "h1", game)["home_score"] == 10


def test_the_nfl_poller_persists_the_current_period():
    from scripts.poll_nfl_live_state import _game_from_event

    assert _game_from_event(_football_event(state="in", completed=False, period=2))["period"] == 2


@pytest.mark.parametrize("module_name", ["scripts.poll_nfl_live_state", "scripts.poll_ncaaf_live_state"])
def test_a_pregame_event_carries_NO_linescores_not_a_list_of_zeros(module_name):
    """Same gate as the score: a placeholder must not settle a pregame under."""
    import importlib

    game = importlib.import_module(module_name)._game_from_event(_football_event(state="pre", completed=False, period=0))

    assert game["home_linescores"] is None and game["away_linescores"] is None


def test_the_soccer_summary_reader_takes_the_halves_from_the_header():
    from syndicate.features.soccer.ingestion.espn_match_box import build_match_box, extract_linescores

    summary = {"header": {"competitions": [{"competitors": [
        {"homeAway": "away", "team": {"abbreviation": "BHA"}, "linescores": [{"displayValue": "1"}, {"displayValue": "2"}]},
        {"homeAway": "home", "team": {"abbreviation": "CHE"}, "linescores": [{"displayValue": "3"}, {"displayValue": "1"}]},
    ]}]}}

    # Keyed off `homeAway`, never list order: away is listed first here.
    assert extract_linescores(summary) == {"home": [3, 1], "away": [1, 2]}
    box = build_match_box(summary, event_id="401879317")
    assert box["home_linescores"] == [3, 1] and box["away_linescores"] == [1, 2]


def test_a_summary_without_a_header_yields_None_not_an_empty_half():
    from syndicate.features.soccer.ingestion.espn_match_box import build_match_box

    box = build_match_box({}, event_id="x")
    assert box["home_linescores"] is None and box["away_linescores"] is None


def test_the_soccer_finals_publisher_carries_linescores_across_the_service_boundary(tmp_path):
    """`_finished_matches` is what refresh-worker can see. Six scalars became
    eight; a box cached before the field existed publishes None."""
    from scripts.poll_soccer_live_state import _finished_matches

    league_dir = tmp_path / "epl" / "api" / "live_state"
    league_dir.mkdir(parents=True)
    (league_dir / "live_state_2026-08-30.json").write_text(json.dumps({
        "match_box": {
            "401879317": {"home_team": "Chelsea", "away_team": "Brighton", "score_home": "4", "score_away": "3",
                          "status_state": "post", "final": True,
                          "home_linescores": [3, 1], "away_linescores": [1, 2]},
            "401879315": {"home_team": "Leeds", "away_team": "Brentford", "score_home": "1", "score_away": "1",
                          "status_state": "post", "final": True},
        }
    }), encoding="utf-8")

    finals = {row["event_id"]: row for row in _finished_matches(["epl"], "2026-08-30", source_root=tmp_path)}

    assert finals["401879317"]["home_linescores"] == [3, 1]
    assert finals["401879317"]["away_linescores"] == [1, 2]
    assert finals["401879315"]["home_linescores"] is None


def test_the_soccer_linescore_fields_never_raise():
    from scripts.poll_soccer_live_state import _linescore_fields

    assert _linescore_fields(None) == {"home_linescores": None, "away_linescores": None}
    assert _linescore_fields({"header": "not-a-dict"}) == {"home_linescores": None, "away_linescores": None}
