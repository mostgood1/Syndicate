"""`prop_evidence.common.name_key_loose` never drops the FIRST token as a generational suffix, todo #743 (d) (lane
`nhl-v-initial-name-key`).

NHL publishes first initials ("V. Trocheck"), and the lone "v" was dropped as the roman numeral V, so `initial_key`
read "trocheck" while the board's "Vincent Trocheck" read "v trocheck": every V-initial player missed the game log in
SGP leg grading and in the hit-rate pool. Real suffixes still drop when they follow the first token."""
from __future__ import annotations

import pytest

from syndicate.features.nhl import sgp_pool as nhl
from syndicate.features.shared.prop_evidence import common as C


@pytest.mark.parametrize("name", ["V. Trocheck", "Vincent Trocheck", "V Trocheck", "Vincent  Trocheck"])
def test_a_v_initial_keeps_its_initial(name):
    assert C.initial_key(name) == "v trocheck"


def test_the_v_initial_log_name_meets_the_board_name():
    assert C.initial_key("V. Trocheck") == C.initial_key("Vincent Trocheck")
    assert C.initial_key("V. Arvidsson") == C.initial_key("Viktor Arvidsson") == "v arvidsson"
    assert C.name_key_loose("V. Trocheck") == "v trocheck"


@pytest.mark.parametrize("name, loose", [
    ("Kenneth Walker III", "kenneth walker"),
    ("Odell Beckham Jr.", "odell beckham"),
    ("Ken Griffey Sr", "ken griffey"),
    ("Vladimir Guerrero Jr.", "vladimir guerrero"),
    ("Marvin Harrison Jr", "marvin harrison"),
    ("Robert Griffin II", "robert griffin"),
    ("Some Name IV", "some name"),
    ("Some Name V", "some name"),          # a trailing V is still the numeral
    ("V. Name V", "v name"),               # leading initial kept, trailing numeral dropped
    ("John V. Smith", "john smith"),       # a MIDDLE V drops as before: only the first token changed
])
def test_real_suffixes_still_drop(name, loose):
    assert C.name_key_loose(name) == loose


def test_initial_key_on_a_suffixed_name_is_unchanged():
    assert C.initial_key("Kenneth Walker III") == "k walker"
    assert C.initial_key("Vladimir Guerrero Jr.") == "v guerrero"


def test_names_match_is_unchanged_for_full_names_and_keeps_the_v_initial_form():
    assert C.names_match("Kenneth Walker III", "Kenneth Walker")
    assert C.names_match("V. Trocheck", "V Trocheck")
    assert C.names_match("John V. Smith", "John Smith")
    # The one names_match change: "V. Trocheck" no longer meets a bare "Trocheck", as no other initial-form name does.
    assert not C.names_match("V. Trocheck", "Trocheck")
    assert not C.names_match("B. Burns", "Burns")


def test_nhl_game_log_resolves_a_v_initial_player_by_name_and_team():
    """The SGP grading path (`sgp_pool.GameLog.resolve` / `leg_player_id`): the log row says "V. Trocheck", the leg the
    board's full name. Before the fix the log was keyed "trocheck" and the leg "v trocheck": 0 hits, leg pending."""
    rows = [{"player_id": "8476389", "gamePk": "2025020100", "timeOnIce": "18:02", "team": "NYR",
             "player": "V. Trocheck", "date": "2026-10-20T23:00:00Z", "shots": "3"}]
    log = nhl.GameLog(rows)
    assert log.resolve("Vincent Trocheck", ["NYR", "BOS"]) == "8476389"
    assert nhl.leg_player_id(log, {"player": "Vincent Trocheck", "team": "New York Rangers"}) == "8476389"
