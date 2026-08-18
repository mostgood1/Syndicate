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


# --------------------------------------------------------------------------
# game shape (lane `game-shape-capture`)
# --------------------------------------------------------------------------
#
# Same discipline as the consumer tests above: asserting the field is SET would
# only prove presence. What has to be true is that the shape contract actually
# parses the stamped state, so these read the values back through
# `shared/game_shape.py` rather than checking for a non-null key.


def _situation_event(event_id, away, home, **situation):
    event = _event(event_id, away, home, "in", period=3, clock="8:05",
                   away_score="14", home_score="17")
    event["competitions"][0]["situation"] = situation
    return event


def test_live_card_carries_a_parsed_game_shape():
    index = {"401873275": _state_from_event(
        _event("401873275", "GB", "PIT", "in", period=3, clock="8:05",
               away_score="14", home_score="17"))}
    cards = [_card("401873275", "GB", "PIT")]
    attach_nfl_live_game_state(cards, index)

    shape = cards[0]["live_state"]["game_shape"]
    assert shape["valid"] is True
    assert shape["sport"] == "nfl"
    assert shape["period"] == 3
    # 2 completed 15-minute quarters + 6:55 elapsed in the third.
    assert shape["elapsed_minutes"] == round(30.0 + (15.0 - (8 + 5 / 60)), 4)
    assert shape["home_margin"] == 3.0
    assert shape["bucket"] == "third_quarter|one_score"


def test_the_discarded_situation_block_now_reaches_the_shape():
    """Down/distance/field position were in the payload and thrown away.

    This is the whole point of the capture change -- it costs no extra fetch,
    it stops discarding what the scoreboard already returns.
    """
    index = {"401873275": _state_from_event(
        _situation_event("401873275", "GB", "PIT",
                         down=3, distance=7, yardLine=12, possession="PIT"))}
    cards = [_card("401873275", "GB", "PIT")]
    attach_nfl_live_game_state(cards, index)

    shape = cards[0]["live_state"]["game_shape"]
    assert shape["situation_available"] is True
    assert shape["down"] == 3
    assert shape["distance"] == 7
    assert shape["yard_line"] == 12
    assert shape["possession_team"] == "PIT"
    assert shape["red_zone"] is True


def test_a_finished_game_carries_no_stale_situation():
    """A `situation` on a completed game is a feed artefact.

    Storing it would render "3rd and 7" on a game that ended hours ago -- the
    same class of defect as the 0-0 placeholder score on a pregame card.
    """
    event = _event("401873275", "GB", "PIT", "post", completed=True, period=4,
                   away_score="20", home_score="17")
    event["competitions"][0]["situation"] = {"down": 3, "distance": 7, "yardLine": 12}
    state = _state_from_event(event)
    assert state["situation"] is None

    cards = [_card("401873275", "GB", "PIT")]
    attach_nfl_live_game_state(cards, {"401873275": state})
    shape = cards[0]["live_state"]["game_shape"]
    assert shape["situation_available"] is False
    assert shape.get("red_zone") is None
    assert shape["final"] is True


def test_absent_situation_does_not_read_as_not_in_the_red_zone():
    """Unknown must not default onto the permissive branch."""
    index = {"401873275": _state_from_event(
        _event("401873275", "GB", "PIT", "in", period=1, clock="7:53"))}
    cards = [_card("401873275", "GB", "PIT")]
    attach_nfl_live_game_state(cards, index)
    shape = cards[0]["live_state"]["game_shape"]
    assert shape["situation_available"] is False
    assert shape.get("red_zone") is None
    assert shape.get("down") is None


def test_shape_is_present_but_invalid_on_a_pregame_card_rather_than_fabricated():
    """A scheduled game has no period and no score, by design upstream.

    The shape must say so (`valid: False`) instead of inventing a 0-0 first
    quarter -- otherwise every pregame card would land in the `first_half|one_score`
    bucket and pollute the denominator.
    """
    index = {"401873275": _state_from_event(
        _event("401873275", "GB", "PIT", "pre"))}
    cards = [_card("401873275", "GB", "PIT")]
    attach_nfl_live_game_state(cards, index)
    shape = cards[0]["live_state"]["game_shape"]
    assert shape["valid"] is False
    assert shape["bucket"] == "unknown"
