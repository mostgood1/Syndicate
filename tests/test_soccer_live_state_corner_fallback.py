# -*- coding: utf-8 -*-
"""`espn_live_state.build_live_state`: corners so far from the box score ONLY for an in-progress match whose
commentary carries no corner events (Belgian Pro League: 0 of 554 box corners in commentary, 2026-09-17).

The fixtures mirror a real ESPN summary's shape, checked against a cached Belgian summary before writing:
`boxscore.teams[*]` carries `homeAway` and a `wonCorners` stat with `displayValue` only, and the match state
is `header.competitions[0].status.type.state`.
"""
import pytest

from syndicate.features.soccer.ingestion.espn_live_state import build_live_state

HOME, AWAY = "Club Brugge", "Anderlecht"


def _summary(state="in", box=(4, 2), corner_events=(), with_box=True):
    competitors = [{"homeAway": "home", "score": "1", "team": {"id": "1", "displayName": HOME}},
                   {"homeAway": "away", "score": "0", "team": {"id": "2", "displayName": AWAY}}]
    summary = {
        "header": {"competitions": [{"status": {"type": {"state": state}}, "competitors": competitors}]},
        "keyEvents": [],
        "rosters": [],
        "commentary": [{"play": {"type": {"type": "corner-awarded"}, "team": {"displayName": team},
                                 "clock": {"value": clock}}} for team, clock in corner_events],
    }
    if with_box:
        summary["boxscore"] = {"teams": [
            {"homeAway": "home", "team": {"displayName": HOME},
             "statistics": [{"name": "wonCorners", "displayValue": str(box[0]), "label": "Corner Kicks"}]},
            {"homeAway": "away", "team": {"displayName": AWAY},
             "statistics": [{"name": "wonCorners", "displayValue": str(box[1]), "label": "Corner Kicks"}]},
        ]}
    return summary


def _state(summary, minute=60):
    return build_live_state(summary, event_id="401900001", home_team=HOME, away_team=AWAY, as_of_seconds=minute * 60.0)


def test_an_in_progress_match_with_no_commentary_corners_reads_the_box():
    state = _state(_summary(state="in", box=(4, 2)))
    assert (state["home_corners_so_far"], state["away_corners_so_far"]) == (4, 2)
    assert state["corners_source"] == "box_fallback"


def test_a_completed_match_replayed_at_a_cutoff_never_reads_the_box():
    """The box of a finished match is its FINAL total: reading it at 60' would put the future in a backtest."""
    state = _state(_summary(state="post", box=(9, 3)))
    assert (state["home_corners_so_far"], state["away_corners_so_far"]) == (0, 0)
    assert state["corners_source"] == "commentary_empty"


def test_commentary_with_corners_is_used_and_never_mixed_with_the_box():
    state = _state(_summary(state="in", box=(5, 5), corner_events=[(HOME, 600.0), (HOME, 1500.0), (HOME, 4000.0)]))
    # 2, not 3: the 4000 s corner is after the 60' cutoff, and the box's 5/5 is never consulted
    assert (state["home_corners_so_far"], state["away_corners_so_far"]) == (2, 0)
    assert state["corners_source"] == "commentary"


def test_commentary_corners_respect_the_cutoff():
    state = _state(_summary(state="in", corner_events=[(HOME, 600.0), (AWAY, 4000.0)]), minute=30)
    assert (state["home_corners_so_far"], state["away_corners_so_far"]) == (1, 0)


@pytest.mark.parametrize("kwargs", [
    {"state": "in", "box": (0, 0)},          # nothing taken yet: 0 is the truth, not a gap
    {"state": "in", "with_box": False},      # no box at all: nothing to fall back to
    {"state": "pre", "box": (0, 0)},
])
def test_no_usable_box_leaves_zero_and_says_why(kwargs):
    state = _state(_summary(**kwargs))
    assert (state["home_corners_so_far"], state["away_corners_so_far"]) == (0, 0)
    assert state["corners_source"] == "commentary_empty"
