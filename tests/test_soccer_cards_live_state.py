"""Soccer publishes a STRUCTURED liveness signal, so a kicked-off match stops
reading `pregame`.

WHY THIS FILE EXISTS. Measured on production 2026-08-16 18:03Z: the soccer
Layer 1 board reported `live: 0` while **14 matches were past kickoff and 12
carried a real score**, and **45 rows served a bettable edge on a game in play
or already finished** -- among them a `totals 2.5` on GRO @ ADO, which had ended
4-1 nearly eight hours earlier. `live_edge_policy` keys on `game.state` and
`pregame` is its PERMISSIVE branch, so a match stuck there never has its edge
withheld.

Root cause, dumped from the real provider rather than guessed: soccer's game
dict gave the liveness readers nothing structured to read. `status` was a
display STRING, and `live_state` / `gameState` / `status_badge` were absent, so
`game_chip_scoreboard._game_flags` returned `(False, False)` for **all 90**
soccer chips while MLB returned 9 live of 15.

THESE TESTS GO THROUGH THE REAL CALL PATH -- `_match_to_game` into
`build_game_chip` -- and not through `_live_state_block` alone. That is
deliberate and it is the lesson from this same session: a helper verified with
arguments you supplied yourself proves the FUNCTION, never that production
reaches it. Asserting on the chip is asserting on what the board consumes.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.game_board_contract import _infer_live_state
from syndicate.features.shared.game_chip_scoreboard import build_game_chip, _game_flags
from syndicate.features.soccer.cards import _match_to_game, _unsimulated_game


def _match(status_state: str) -> dict:
    """A match shaped like the provider's, differing only in `status_state`."""
    return {
        "event_id": "evt-1",
        "date": "2026-08-16",
        "kickoff": "2026-08-16T10:15:00Z",
        "status_state": status_state,
        "matchup": {"home_team": "ADO Den Haag", "away_team": "FC Groningen"},
        "live_home_score": 1,
        "live_away_score": 4,
    }


def _fixture(status_state: str) -> dict:
    return {
        "home_team": "ADO Den Haag",
        "away_team": "FC Groningen",
        "date": "2026-08-16T10:15:00Z",
        "status_state": status_state,
    }


@pytest.mark.parametrize(
    "status_state,expected_state",
    [("pre", "pregame"), ("in", "live"), ("post", "final")],
)
def test_chip_state_follows_status_state(status_state, expected_state):
    """The end-to-end assertion: provider status -> the chip the board reads."""
    game = _match_to_game(_match(status_state), league="eredivisie", week=1, season=2026)
    chip = build_game_chip("soccer", game)
    assert chip["state"] == expected_state


def test_the_finished_match_that_was_serving_an_edge_is_no_longer_pregame():
    """GRO @ ADO, the concrete production case, 4-1 and eight hours old.

    `pregame` is what let `live_edge_policy` release an edge on a settled
    `totals 2.5`. Anything that is NOT pregame closes that path, so the
    assertion is written against the harmful value rather than for a
    particular replacement.
    """
    game = _match_to_game(_match("post"), league="eredivisie", week=1, season=2026)
    chip = build_game_chip("soccer", game)
    assert chip["state"] != "pregame"
    assert chip["status_token"] == "FINAL"


@pytest.mark.parametrize("status_state", ["in", "post"])
def test_both_liveness_readers_agree(status_state):
    """Two consumers read this, and a fix for one is not a fix for the other.

    `_game_flags` decides the chip's state; `_infer_live_state` sets
    `shared_is_live` on the board contract. They are separate functions in
    separate modules and both were blind to soccer.
    """
    game = _match_to_game(_match(status_state), league="eredivisie", week=1, season=2026)
    is_live, is_final = _game_flags(game)
    assert is_live == (status_state == "in")
    assert is_final == (status_state == "post")
    assert _infer_live_state(game) == (status_state == "in")


def test_unsimulated_placeholder_also_reports_state():
    """The placeholder is the MORE dangerous producer to leave unfixed.

    Its summary ends "has not been simulated yet" and its panel says "on the
    real schedule for <date>" -- and `_infer_live_state`'s `final_tokens`
    contains "scheduled", so an unsimulated fixture that HAS kicked off was
    being pinned not-live by its own placeholder wording. An unsimulated match
    is still a real match that can start and finish.
    """
    for status_state, expected in (("in", "live"), ("post", "final"), ("pre", "pregame")):
        game = _unsimulated_game(_fixture(status_state), league="eredivisie", week=1, season=2026)
        assert build_game_chip("soccer", game)["state"] == expected, status_state


def test_no_text_status_is_smuggled_into_the_haystack():
    """`_game_flags` folds `live_state["status"]` into a substring search.

    Emitting a display string there would reintroduce the prose-matching this
    change exists to replace -- and `"Final"` / `"Live"` are exactly the tokens
    it scans for, so a label would look like it worked while still being a
    guess.
    """
    game = _match_to_game(_match("in"), league="eredivisie", week=1, season=2026)
    assert set(game["live_state"]) == {"in_progress", "final"}


def test_unknown_status_state_is_not_live_and_not_final():
    """An unrecognised value must fall to pregame, not to a permissive guess.

    This is the one direction where the old behaviour was right: with no
    signal, `pregame` is the honest answer for a fixture that has not started.
    The bug was never the default -- it was that a KNOWN `in`/`post` could not
    reach it.
    """
    game = _match_to_game(_match("weird-new-value"), league="eredivisie", week=1, season=2026)
    assert game["live_state"] == {"in_progress": False, "final": False}
    assert build_game_chip("soccer", game)["state"] == "pregame"
