"""The live NFL card says who has the ball and where, in ESPN's own words (lane `nfl-live-card-situation`).

Before: `attach_nfl_live_game_state` put ESPN's `situation` only into the game shape, so the card's
`live_detail` fell back to the shape and printed ESPN's team ID ("33 ball") and the raw `yardLine`, which
ESPN measures from the HOME team's goal line ("at 98" for BAL at the LAC 2). And the shape's `red_zone`
read that home-frame number as distance-to-goal: wrong on 13 of 66 MNF reads, while ESPN's own
`isRedZone` was right on all 66.

Every situation below is a real ESPN read of LAC (away, id 24) @ BAL (home, id 33) on MNF 2026-11-16
(`C:\\tmp\\livegrade\\nfl813\\out\\mnf_reads.jsonl`), driven through the real parser, the real attach,
and the board's own chip wrapper -- not a stub of any of them.
"""

from __future__ import annotations

import copy

from syndicate.features.nfl.live_game_state import _state_from_event, attach_nfl_live_game_state
from syndicate.features.shared.game_chip_detail import live_detail
from syndicate.features.shared.game_chip_scoreboard import _chip_live_detail
from syndicate.features.shared.game_shape import football_game_shape

EVENT_ID = "401873065"

# BAL has the ball at its OWN 10. yardLine 10 -- the old rule called this the red zone.
HOME_BACKED_UP = {"possession": "33", "down": 1, "distance": 10, "yardLine": 10, "possessionText": "BAL 10",
                  "downDistanceText": "1st & 10 at BAL 10", "shortDownDistanceText": "1st & 10",
                  "isRedZone": False, "homeTimeouts": 3, "awayTimeouts": 3}
# BAL, first and goal at the LAC 2. yardLine 98 -- the old rule missed it.
HOME_GOAL_TO_GO = {"possession": "33", "down": 1, "distance": 2, "yardLine": 98, "possessionText": "LAC 2",
                   "downDistanceText": "1st & Goal at LAC 2", "shortDownDistanceText": "1st & Goal",
                   "isRedZone": True, "homeTimeouts": 3, "awayTimeouts": 3}
# LAC at its own 48. yardLine 52.
AWAY_MIDFIELD = {"possession": "24", "down": 1, "distance": 10, "yardLine": 52, "possessionText": "LAC 48",
                 "downDistanceText": "1st & 10 at LAC 48", "shortDownDistanceText": "1st & 10",
                 "isRedZone": False, "homeTimeouts": 3, "awayTimeouts": 3}
# LAC, fourth and 4 at the BAL 20. yardLine 20 -- both rules agree here.
AWAY_RED_ZONE = {"possession": "24", "down": 4, "distance": 4, "yardLine": 20, "possessionText": "BAL 20",
                 "downDistanceText": "4th & 4 at BAL 20", "shortDownDistanceText": "4th & 4",
                 "isRedZone": True, "homeTimeouts": 3, "awayTimeouts": 3}
# Between plays: no down, no text, possession still named.
AWAY_BETWEEN_PLAYS = {"possession": "24", "down": -1, "distance": 0, "yardLine": 65, "possessionText": None,
                      "downDistanceText": None, "shortDownDistanceText": None, "isRedZone": True,
                      "homeTimeouts": 3, "awayTimeouts": 3}
# A read with no possession named.
NO_POSSESSION = {"possession": None, "down": 1, "distance": 10, "yardLine": 20, "possessionText": "BAL 20",
                 "downDistanceText": "1st & 10 at BAL 20", "shortDownDistanceText": "1st & 10",
                 "isRedZone": False, "homeTimeouts": 3, "awayTimeouts": 2}


def _event(situation, *, state="in", completed=False):
    event = {
        "id": EVENT_ID,
        "date": "2026-11-17T01:15Z",
        "status": {"period": 2, "displayClock": "13:21",
                   "type": {"state": state, "completed": completed, "shortDetail": "13:21 - 2nd",
                            "detail": "13:21 - 2nd"}},
        "competitions": [{
            "competitors": [
                {"homeAway": "away", "score": "7", "team": {"id": "24", "abbreviation": "LAC"}},
                {"homeAway": "home", "score": "10", "team": {"id": "33", "abbreviation": "BAL"}},
            ],
        }],
    }
    if situation is not None:
        situation = dict(situation)
        situation["lastPlay"] = {"id": "1", "text": "a long play description the card never shows"}
        event["competitions"][0]["situation"] = situation
    return event


def _card():
    return {"gamePk": EVENT_ID, "away": {"abbr": "LAC", "name": "Los Angeles Chargers"},
            "home": {"abbr": "BAL", "name": "Baltimore Ravens"}, "status": "Week 11"}


def _attached(situation, **kw):
    card = _card()
    attach_nfl_live_game_state([card], {EVENT_ID: _state_from_event(_event(situation, **kw))})
    return card


# ---- the attach carries the situation and the side ----------------------------------------------------

def test_a_live_game_carries_espns_situation_and_the_side():
    live = _attached(HOME_GOAL_TO_GO)["live_state"]
    assert live["possession_side"] == "home"
    assert live["espn_situation"]["downDistanceText"] == "1st & Goal at LAC 2"
    assert live["espn_situation"]["isRedZone"] is True
    assert _attached(AWAY_MIDFIELD)["live_state"]["possession_side"] == "away"


def test_lastplay_is_not_shipped_on_the_card():
    assert "lastPlay" not in _attached(HOME_GOAL_TO_GO)["live_state"]["espn_situation"]


def test_no_possession_named_means_no_side_never_a_guess():
    live = _attached(NO_POSSESSION)["live_state"]
    assert "possession_side" not in live
    assert live["espn_situation"]["downDistanceText"] == "1st & 10 at BAL 20"


def test_an_unmatched_possession_id_means_no_side():
    live = _attached(dict(HOME_GOAL_TO_GO, possession="99"))["live_state"]
    assert "possession_side" not in live


def test_no_situation_or_a_final_adds_neither_key():
    for card in (_attached(None),
                 _attached(HOME_GOAL_TO_GO, state="post", completed=True)):
        live = card["live_state"]
        assert "espn_situation" not in live and "possession_side" not in live


# ---- the card line ------------------------------------------------------------------------------------

LABELS = {"home": "BAL", "away": "LAC"}


def test_the_card_says_who_has_it_and_where_in_espns_words():
    assert live_detail("nfl", _attached(HOME_GOAL_TO_GO), None, LABELS) == "BAL ball · 1st & Goal at LAC 2 · red zone"
    assert live_detail("nfl", _attached(HOME_BACKED_UP), None, LABELS) == "BAL ball · 1st & 10 at BAL 10"
    assert live_detail("nfl", _attached(AWAY_MIDFIELD), None, LABELS) == "LAC ball · 1st & 10 at LAC 48"
    assert live_detail("nfl", _attached(AWAY_RED_ZONE), None, LABELS) == "LAC ball · 4th & 4 at BAL 20 · red zone"


def test_the_served_chip_is_that_line_up_to_its_40_character_cap():
    """The board's wrapper labels the sides from the card and cuts at `_SITUATION_MAX_CHARS` (40), for every
    sport. A 41-character goal-to-go line loses its last letter there -- pinned here, not fixed in this lane."""
    assert _chip_live_detail("nfl", _attached(AWAY_RED_ZONE)) == "LAC ball · 4th & 4 at BAL 20 · red zone"
    assert _chip_live_detail("nfl", _attached(HOME_GOAL_TO_GO)) == "BAL ball · 1st & Goal at LAC 2 · red zone"[:40]


def test_the_card_never_shows_the_team_id_or_the_home_frame_number():
    for situation in (HOME_GOAL_TO_GO, HOME_BACKED_UP, AWAY_MIDFIELD, AWAY_RED_ZONE):
        text = live_detail("nfl", _attached(situation), None, LABELS)
        assert "33" not in text and "24" not in text, text
        assert f"at {situation['yardLine']}" not in text, text


def test_between_plays_still_says_who_has_it():
    assert live_detail("nfl", _attached(AWAY_BETWEEN_PLAYS), None, LABELS) == "LAC ball · red zone"


def test_off_is_not_on_without_the_keys_the_card_fell_back_to_the_id():
    """The defect this lane fixes, reproduced by removing exactly the two keys it adds."""
    card = _attached(HOME_GOAL_TO_GO)
    before = copy.deepcopy(card)
    before["live_state"].pop("espn_situation")
    before["live_state"].pop("possession_side")
    assert _chip_live_detail("nfl", before) == "33 ball · 1st & 2 · at 98"
    assert _chip_live_detail("nfl", card).startswith("BAL ball · 1st & Goal at LAC 2")


# ---- the shape's red zone is ESPN's flag --------------------------------------------------------------

def _shape(situation):
    return football_game_shape({"period": 2, "clock": "13:21", "home_pts": 10, "away_pts": 7,
                                "in_progress": True}, sport="nfl", situation=situation)


def test_red_zone_follows_isredzone_where_the_home_frame_number_misled():
    assert _shape(HOME_BACKED_UP)["red_zone"] is False      # yardLine 10: the old rule said True
    assert _shape(HOME_GOAL_TO_GO)["red_zone"] is True      # yardLine 98: the old rule said None
    assert _shape(AWAY_RED_ZONE)["red_zone"] is True
    assert _shape(AWAY_MIDFIELD)["red_zone"] is False


def test_red_zone_is_none_when_espn_did_not_say():
    no_flag = {k: v for k, v in HOME_BACKED_UP.items() if k != "isRedZone"}
    assert _shape(no_flag)["red_zone"] is None
    assert _shape(dict(HOME_BACKED_UP, isRedZone="yes"))["red_zone"] is None
    assert _shape(None).get("red_zone") is None


def test_the_attached_shape_agrees_with_espn_on_all_six_reads():
    for situation in (HOME_BACKED_UP, HOME_GOAL_TO_GO, AWAY_MIDFIELD, AWAY_RED_ZONE, AWAY_BETWEEN_PLAYS,
                      NO_POSSESSION):
        shape = _attached(situation)["live_state"]["game_shape"]
        assert shape["red_zone"] is situation["isRedZone"], situation
