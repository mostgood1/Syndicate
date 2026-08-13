"""Tests for NFL card game state (`nfl-day-of-game` lane, 2026-08-13).

THE DEFECT THESE PIN. On the live preseason slate, DET @ CIN carried 117 live
in-game market rows with 1.3-minute-fresh odds while every NFL surface
reported `state=pregame`, because the NFL cards carry no `live_state` and
`game_chip_scoreboard._game_flags` therefore reads `(False, False)` for every
game, forever.

THE POINT OF THE CONSUMER TESTS BELOW. Asserting that
`attach_nfl_live_game_state` sets a field would only prove the field is set --
that is exactly the "presence is not reachability" failure the ledger records
five instances of. What has to be true is that the REAL consumers flip, so
those are called directly with the stamped card:

    game_board_contract._infer_live_state   -> shared_is_live on the card
    game_chip_scoreboard._game_flags        -> chip state -> board by_state
    game_chip_scoreboard.build_game_chip    -> state/status_token/score
    publication_adapter._shared_game_state  -> shared_game_state block

A test that stubs those out would pass against the broken code.
"""

from __future__ import annotations

import pytest

from syndicate.features.nfl.live_game_state import (
    SEASONTYPE_PRESEASON,
    attach_nfl_live_game_state,
    _state_from_event,
)


def _event(event_id, away, home, state, *, completed=False, period=0, clock="0:00", away_score="0", home_score="0", date="2026-08-13T23:00Z"):
    return {
        "id": event_id,
        "date": date,
        "status": {
            "period": period,
            "displayClock": clock,
            "type": {"state": state, "completed": completed, "shortDetail": f"{clock} - {period}", "detail": f"{clock} - {period}"},
        },
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "away", "score": away_score, "team": {"abbreviation": away}},
                    {"homeAway": "home", "score": home_score, "team": {"abbreviation": home}},
                ]
            }
        ],
    }


def _card(game_pk, away, home):
    """The shape `_game_from_preseason_projection` actually returns -- `status`
    is a plain STRING and there is no live_state, which is the whole defect."""
    return {
        "gamePk": game_pk,
        "away": {"abbr": away, "name": f"{away} club"},
        "home": {"abbr": home, "name": f"{home} club"},
        "status": "Preseason Week 1",
        "detail": "SmartSim 2.0 (preseason)",
        "summary": "SmartSim 2.0 projects ...",
    }


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def test_live_event_parses_as_in_progress_with_period_and_clock():
    state = _state_from_event(_event("401873275", "GB", "PIT", "in", period=1, clock="7:53", away_score="3", home_score="0"))
    assert state["in_progress"] is True
    assert state["final"] is False
    assert state["period"] == 1
    assert state["clock"] == "7:53"
    assert state["away_pts"] == 3
    assert state["home_pts"] == 0


def test_pregame_event_reports_no_placeholder_score():
    # ESPN sends "0"/"0" for a game that has not kicked off. Emitting it would
    # put 0-0 on every pregame card.
    state = _state_from_event(_event("401873273", "IND", "NE", "pre"))
    assert state["in_progress"] is False
    assert state["final"] is False
    assert state["away_pts"] is None
    assert state["home_pts"] is None
    assert state["clock"] == ""


def test_final_is_detected_from_state_post_even_without_completed_flag():
    # Both signals are read, not just `completed` -- a finished game that
    # arrives with only `state=post` must not keep rendering as live.
    state = _state_from_event(_event("401873272", "DET", "CIN", "post", completed=False, period=4, away_score="17", home_score="20"))
    assert state["final"] is True
    assert state["in_progress"] is False
    assert state["away_pts"] == 17 and state["home_pts"] == 20


def test_start_time_is_carried_so_a_week_scoped_board_can_say_which_game_is_tonight():
    state = _state_from_event(_event("401873640", "ARI", "LV", "pre", date="2026-08-14T00:00Z"))
    assert state["start_time"] == "2026-08-14T00:00Z"


# --------------------------------------------------------------------------
# stamping, and the safety property
# --------------------------------------------------------------------------


def test_absent_game_is_left_completely_untouched():
    """Unknown must not default permissive. A card ESPN does not know about
    keeps exactly what it had -- no live_state, no invented pregame."""
    cards = [_card("999999", "AAA", "BBB")]
    coverage = attach_nfl_live_game_state(cards, {"401873275": _state_from_event(_event("401873275", "GB", "PIT", "in", period=1, clock="7:53"))})
    assert "live_state" not in cards[0]
    assert coverage["matched"] == 0


def test_empty_index_stamps_nothing_and_says_so():
    """A scoreboard outage must degrade to today's behaviour, not to a
    confident wrong state."""
    cards = [_card("401873275", "GB", "PIT")]
    coverage = attach_nfl_live_game_state(cards, {})
    assert "live_state" not in cards[0]
    assert coverage == {"matched": 0, "live": 0, "final": 0, "games": 1, "index": 0}


def test_coverage_separates_matched_from_live():
    """`matched=6, live=0` (join worked, all pregame) and `matched=0` (join
    found nothing) produce the same board and are different defects."""
    index = {"401873273": _state_from_event(_event("401873273", "IND", "NE", "pre"))}
    coverage = attach_nfl_live_game_state([_card("401873273", "IND", "NE")], index)
    assert coverage["matched"] == 1
    assert coverage["live"] == 0 and coverage["final"] == 0


def test_falls_back_to_team_pair_when_game_pk_is_not_an_espn_id():
    raw = _state_from_event(_event("401873275", "GB", "PIT", "in", period=2, clock="1:12"))
    index = {"401873275": raw, "GB@PIT": raw}
    cards = [_card("some-other-id", "GB", "PIT")]
    coverage = attach_nfl_live_game_state(cards, index)
    assert coverage["matched"] == 1
    assert cards[0]["live_state"]["in_progress"] is True


# --------------------------------------------------------------------------
# THE CONSUMERS. These are the tests that prove the fix reaches the board.
# --------------------------------------------------------------------------


def _stamped_live_card():
    cards = [_card("401873275", "GB", "PIT")]
    index = {"401873275": _state_from_event(_event("401873275", "GB", "PIT", "in", period=1, clock="7:53", away_score="3", home_score="0"))}
    attach_nfl_live_game_state(cards, index)
    return cards[0]


def _stamped_final_card():
    cards = [_card("401873272", "DET", "CIN")]
    index = {"401873272": _state_from_event(_event("401873272", "DET", "CIN", "post", completed=True, period=4, away_score="17", home_score="20"))}
    attach_nfl_live_game_state(cards, index)
    return cards[0]


def test_board_contract_infer_live_state_now_returns_true():
    from syndicate.features.shared.game_board_contract import _infer_live_state

    assert _infer_live_state(_stamped_live_card()) is True
    # Control: the UNSTAMPED card is what production serves today, and it must
    # still read False -- otherwise this test proves nothing about the change.
    assert _infer_live_state(_card("401873275", "GB", "PIT")) is False


def test_game_chip_flags_now_detect_live_and_final():
    from syndicate.features.shared.game_chip_scoreboard import _game_flags

    assert _game_flags(_stamped_live_card()) == (True, False)
    assert _game_flags(_stamped_final_card()) == (False, True)
    # The pre-fix control, which is the reading measured in production.
    assert _game_flags(_card("401873275", "GB", "PIT")) == (False, False)


def test_game_chip_carries_state_score_and_a_football_status_token():
    from syndicate.features.shared.game_chip_scoreboard import build_game_chip

    chip = build_game_chip("nfl", _stamped_live_card())
    assert chip["state"] == "live"
    assert chip["status_token"] == "Q1 7:53"
    assert chip["away"]["score"] == "3"
    assert chip["home"]["score"] == "0"
    assert chip["leader"] == "away"

    final_chip = build_game_chip("nfl", _stamped_final_card())
    assert final_chip["state"] == "final"
    assert final_chip["status_token"] == "FINAL"
    assert final_chip["leader"] == "home"


def test_unstamped_chip_still_reports_pregame_so_the_control_is_real():
    from syndicate.features.shared.game_chip_scoreboard import build_game_chip

    chip = build_game_chip("nfl", _card("401873275", "GB", "PIT"))
    assert chip["state"] == "pregame"
    assert chip["away"]["score"] is None


def test_publication_adapter_shared_game_state_reflects_live():
    from syndicate.features.shared.publication_adapter import _shared_game_state

    block = _shared_game_state(_stamped_live_card())
    assert block["live"] is True
    assert block["final"] is False
    assert block["period"] == 1
    assert block["clock"] == "7:53"

    final_block = _shared_game_state(_stamped_final_card())
    assert final_block["final"] is True
    assert final_block["live"] is False


@pytest.mark.parametrize("seasontype", [SEASONTYPE_PRESEASON])
def test_index_is_keyed_by_both_event_id_and_team_pair(seasontype, monkeypatch):
    import syndicate.features.nfl.live_game_state as mod

    payload = {"events": [_event("401873275", "GB", "PIT", "in", period=1, clock="7:53")]}
    monkeypatch.setattr(mod, "_fetch_scoreboard", lambda *a, **k: payload)
    mod._cache.clear()
    index = mod.nfl_game_state_index(2026, 2, seasontype=seasontype)
    assert "401873275" in index
    assert "GB@PIT" in index
    assert index["401873275"]["in_progress"] is True


def test_fetch_failure_yields_empty_index_not_an_exception(monkeypatch):
    import syndicate.features.nfl.live_game_state as mod

    monkeypatch.setattr(mod, "_fetch_scoreboard", lambda *a, **k: None)
    mod._cache.clear()
    assert mod.nfl_game_state_index(2026, 2, seasontype=SEASONTYPE_PRESEASON) == {}
