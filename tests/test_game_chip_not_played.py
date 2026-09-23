"""A postponed MLB game was served as FINAL, because MLB says it is.

Measured on production 2026-09-23: TOR @ BAL, gamePk 824785. StatsAPI reported
`detailedState: "Postponed"`, `codedGameState: "D"` and **`abstractGameState:
"Final"`**; the chip served `state: "final"`, `status_token: "FINAL"`, with
`start_time_utc: 2026-09-23T17:35:00+00:00` -- a game that had "finished" and
starts tomorrow, because it had been rescheduled into the next day's split
doubleheader.

The existing 0-0 guard already knew something was wrong (it stamped
`level_final_impossible_for_sport` and nulled the score) but named the wrong
cause and let the FINAL token through. `codedGameState` is the discriminating
field and nothing read it.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.game_chip_scoreboard import build_game_chip

# The production shape, field for field.
POSTPONED = {
    "gamePk": "824785",
    "away": {"abbr": "TOR", "name": "Toronto Blue Jays", "score": "0"},
    "home": {"abbr": "BAL", "name": "Baltimore Orioles", "score": "0"},
    "start_time_utc": "2026-09-23T17:35:00+00:00",
    "status": {"abstract": "Final", "detailed": "Postponed", "codedGameState": "D"},
}


def _chip(**overrides):
    game = dict(POSTPONED)
    game["status"] = dict(POSTPONED["status"], **overrides.pop("status", {}))
    game.update(overrides)
    return build_game_chip("mlb", game)


def test_a_postponed_game_is_not_final():
    chip = _chip()
    assert chip["state"] != "final"
    assert chip["status_token"] != "FINAL"


def test_a_postponed_game_says_so():
    chip = _chip()
    assert (chip["state"], chip["status_token"]) == ("postponed", "PPD")


@pytest.mark.parametrize("coded, state", [("D", "postponed"), ("C", "cancelled"), ("U", "suspended")])
def test_every_non_playing_coded_state_gets_its_own_label(coded, state):
    # `abstractGameState` is "Final" for all three; only the coded state tells
    # them apart, and each must stay distinguishable from a real final.
    chip = _chip(status={"codedGameState": coded, "detailed": state.title()})
    assert chip["state"] == state
    assert chip["status_token"] != "FINAL"


def test_the_coded_state_wins_without_any_helpful_text():
    # The ONLY signal is the code: abstract says Final and nothing says why.
    chip = _chip(status={"abstract": "Final", "detailed": "Final", "codedGameState": "D"})
    assert chip["state"] == "postponed"


def test_the_text_is_enough_when_no_code_is_passed():
    # Not every provider forwards `codedGameState`; the detailed text carries it.
    game = dict(POSTPONED, status={"abstract": "Final", "detailed": "Postponed"})
    assert build_game_chip("mlb", game)["state"] == "postponed"


def test_the_score_reason_names_the_postponement():
    # Not `pregame_placeholder`, which would claim the game is still coming --
    # true only of a DIFFERENT game on another date.
    chip = _chip()
    assert chip["score_suppressed"] == "game_postponed"
    assert chip["away"]["score"] is None and chip["home"]["score"] is None


def test_an_ordinary_final_is_untouched():
    game = {
        "gamePk": "823543",
        "away": {"abbr": "TB", "name": "Tampa Bay Rays", "score": "0"},
        "home": {"abbr": "NYY", "name": "New York Yankees", "score": "2"},
        "start_time_utc": "2026-09-22T17:05:00+00:00",
        "status": {"abstract": "Final", "detailed": "Final", "codedGameState": "F"},
    }
    chip = build_game_chip("mlb", game)
    assert (chip["state"], chip["status_token"]) == ("final", "FINAL")
    assert chip["home"]["score"] == "2"


def test_an_ordinary_live_game_is_untouched():
    game = {
        "gamePk": "823494",
        "away": {"abbr": "TB", "name": "Tampa Bay Rays", "score": "1"},
        "home": {"abbr": "NYY", "name": "New York Yankees", "score": "3"},
        "start_time_utc": "2026-09-22T23:05:00+00:00",
        "status": {"abstract": "Live", "detailed": "In Progress", "codedGameState": "I"},
    }
    assert build_game_chip("mlb", game)["state"] == "live"


def test_a_postponed_game_is_neither_live_nor_final_to_the_gates():
    # Every downstream gate tests `live`/`in_progress` or `final` explicitly,
    # so the new value must fall through all of them.
    state = _chip()["state"]
    assert state not in {"live", "in_progress", "final", "pregame"}
