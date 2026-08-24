"""The canonical club key that lets a chip and a board row join.

Reported 2026-08-24: La Liga compact cards showed team names that did not match
the rest of the board. Measured on the real chips for that week, 9 of 13
fixtures joined and 4 did not -- all four were "Athletic Bilbao" vs "Athletic
Club" and "Real Racing Club de Santander" vs "Racing Santander".

Those are not spelling differences. `#365`'s browser-side normalisation handles
accents, punctuation and club-type affixes; it cannot handle two different
NAMES for one club, and widening it until it could means dropping a city
qualifier -- which collapses Manchester United into Manchester City.

So both sides of the join now carry `canonical_team`'s answer, computed on the
server where the alias map already lives.
"""

from __future__ import annotations

from syndicate.features.shared.game_chip_scoreboard import _side_key
from syndicate.features.shared.layer2_board import _canonical_team_key
from syndicate.features.shared.team_aliases import canonical_team


ODDS_FEED_SPELLING = "Athletic Bilbao"
ARTIFACT_SPELLING = "Athletic Club"


def test_the_two_spellings_that_broke_the_cards_resolve_to_one_name():
    assert canonical_team("soccer", ODDS_FEED_SPELLING) == canonical_team("soccer", ARTIFACT_SPELLING)
    assert canonical_team("soccer", "Real Racing Club de Santander") == canonical_team(
        "soccer", "Racing Santander"
    )


def test_the_chip_side_and_the_row_side_agree():
    """The whole point: two feeds, two spellings, ONE key.

    Asserted across the pair rather than against a literal, because the
    canonical string itself is the alias map's business and may change; what
    must never change is that both sides land on the same value.
    """
    chip_key = _side_key("soccer", {"home": {"name": ARTIFACT_SPELLING}}, "home")
    row_key = _canonical_team_key("soccer", ODDS_FEED_SPELLING)
    assert chip_key is not None
    assert chip_key == row_key


def test_a_club_the_map_cannot_resolve_yields_none_rather_than_a_guess():
    """A wrong key is worse than no key -- it attaches one game to another.

    None is the honest answer and the browser's existing indexes still apply,
    so an unknown club degrades to exactly the behaviour it had before.
    """
    assert _canonical_team_key("soccer", "Definitely Not A Real Club") is None
    assert _side_key("soccer", {"home": {"name": "Definitely Not A Real Club"}}, "home") is None


def test_a_missing_name_is_not_an_error():
    assert _canonical_team_key("soccer", "") is None
    assert _canonical_team_key("", "Barcelona") is None
    assert _side_key("soccer", {}, "home") is None


def test_the_key_never_raises_and_takes_out_the_scoreboard():
    """This feeds a DISPLAY join. It must degrade, never propagate.

    `build_game_chips` builds the whole strip for every sport in one pass, so
    an exception here would blank the scoreboard for all of them over one
    unresolvable club name.
    """
    assert _side_key("soccer", {"home": None}, "home") is None
    assert _canonical_team_key("soccer", None) is None  # type: ignore[arg-type]


def test_it_is_stamped_on_a_real_chip():
    """Wiring, not just the helper.

    `#444`'s standing lesson is that a producer returning a value does not make
    it reach anyone -- payload assemblers are explicit key lists. This asserts
    the key is actually IN the chip dict.
    """
    from syndicate.features.shared.game_chip_scoreboard import build_game_chip

    chip = build_game_chip(
        "soccer",
        {
            "event_id": "1",
            "league": "la_liga",
            "away": {"name": "Sevilla", "abbr": "SEV"},
            "home": {"name": ARTIFACT_SPELLING, "abbr": "ATH"},
        },
    )
    assert chip["away"]["key"] == canonical_team("soccer", "Sevilla")
    assert chip["home"]["key"] == canonical_team("soccer", ODDS_FEED_SPELLING)
