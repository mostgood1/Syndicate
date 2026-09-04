"""Kalshi's doubleheader suffix resolves to the right game, or to nothing.

MEASURED ON PRODUCTION 2026-09-04, before the fix:

    DETCLE     -> ambiguous   both games of the doubleheader produce this blob
    DETCLEG1   -> no_match    the suffix was not parsed at all
    DETCLEG2   -> no_match
    ATHSEA     -> ok

`KXMLBF5SPREAD-26SEP041915DETCLEG2-DET3` and its game-1 twin were sitting in
`KALSHI_UNMATCHED.unmatched_events` for exactly this reason. Kalshi hands us the
discriminator; we were throwing it away and then refusing the market for being
ambiguous. Both halves of every doubleheader were invisible to the order path --
moneyline, first-five, totals and spreads alike -- in September, which is
makeup-game season.

The retry is sited AFTER the as-is match fails, so it can only ADD resolutions.
`test_a_blob_that_already_matched_is_untouched` is what pins that.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.kalshi_catalogue import (  # noqa: E402
    _game_number_of,
    _split_doubleheader,
    match_event_blob,
)


def _dh_games():
    return [
        {"away_team": "Detroit Tigers", "home_team": "Cleveland Guardians",
         "event_id": "g1", "game_number": 1, "away_code": "DET", "home_code": "CLE"},
        {"away_team": "Detroit Tigers", "home_team": "Cleveland Guardians",
         "event_id": "g2", "game_number": 2, "away_code": "DET", "home_code": "CLE"},
        {"away_team": "Athletics", "home_team": "Seattle Mariners",
         "event_id": "g3", "away_code": "ATH", "home_code": "SEA"},
    ]


# --- the fix -----------------------------------------------------------------


def test_each_half_of_a_doubleheader_resolves_to_its_own_game():
    games = _dh_games()
    first = match_event_blob("DETCLEG1", games, sport="mlb")
    second = match_event_blob("DETCLEG2", games, sport="mlb")
    assert first["status"] == "ok" and first["event_id"] == "g1"
    assert second["status"] == "ok" and second["event_id"] == "g2"
    assert first["event_id"] != second["event_id"], (
        "the whole point is that the two halves are DIFFERENT games")
    assert first["doubleheader_game"] == 1 and second["doubleheader_game"] == 2


def test_the_bare_pair_is_still_ambiguous():
    """WITHOUT the suffix we genuinely cannot tell, and a coin flip between two
    real games is worse than no bet because it looks like a bet."""
    got = match_event_blob("DETCLE", _dh_games(), sport="mlb")
    assert got["status"] == "ambiguous"
    assert got.get("count") == 2


def test_a_game_number_we_do_not_hold_is_REFUSED_not_guessed():
    """`retry` on the base may well be usable; accepting it would pair "game 3"
    with whichever game we happen to hold."""
    got = match_event_blob("DETCLEG3", _dh_games(), sport="mlb")
    assert got["status"] == "no_match"
    assert "doubleheader_game_3" in got["reason"]


def test_a_blob_that_already_matched_is_untouched():
    """The retry runs only after the as-is match finds nothing, so this can only
    ADD resolutions. A single game with no `game_number` still resolves."""
    got = match_event_blob("ATHSEA", _dh_games(), sport="mlb")
    assert got["status"] == "ok" and got["event_id"] == "g3"
    assert "doubleheader_game" not in got


def test_a_suffixed_blob_still_resolves_when_only_one_game_exists(
):
    """A doubleheader contract whose partner game is not on our board: the one
    we DO hold must carry the matching number, or it is refused."""
    only_second = [g for g in _dh_games() if g.get("game_number") == 2]
    assert match_event_blob("DETCLEG2", only_second, sport="mlb")["status"] == "ok"
    assert match_event_blob("DETCLEG1", only_second, sport="mlb")["status"] == "no_match"


def test_a_game_with_no_number_does_not_absorb_a_suffixed_blob():
    """`None` is not 1. A feed that omits the field does not know, and reading
    it as game one pairs the second game's contract with the first game."""
    unnumbered = [{"away_team": "Detroit Tigers", "home_team": "Cleveland Guardians",
                   "event_id": "gX", "away_code": "DET", "home_code": "CLE"}]
    assert match_event_blob("DETCLEG1", unnumbered, sport="mlb")["status"] == "no_match"


# --- the parsers -------------------------------------------------------------


def test_split_doubleheader_reads_the_suffix():
    assert _split_doubleheader("DETCLEG2") == ("DETCLE", 2)
    assert _split_doubleheader("DETCLEG1") == ("DETCLE", 1)


def test_split_doubleheader_refuses_shapes_that_are_not_one():
    assert _split_doubleheader("ATHSEA") == (None, None)
    assert _split_doubleheader("") == (None, None)
    assert _split_doubleheader("DETCLEG0") == (None, None), "games are numbered from 1"
    assert _split_doubleheader("DETCLEG12") == (None, None), "one digit, within a day"
    assert _split_doubleheader("ABCG1") == (None, None), "needs 4+ leading letters"


def test_game_number_reads_either_spelling_and_rejects_nonsense():
    assert _game_number_of({"game_number": 2}) == 2
    assert _game_number_of({"gameNumber": "1"}) == 1
    assert _game_number_of({}) is None
    assert _game_number_of({"game_number": None}) is None
    assert _game_number_of({"game_number": "not-a-number"}) is None
    assert _game_number_of({"game_number": True}) is None, (
        "a bool is not a game number, and True == 1 would silently become game one")
