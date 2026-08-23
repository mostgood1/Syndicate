"""The halftime-reads-as-Final defect, and the substring collisions behind it.

**REACHABILITY FIRST.** `model_engine_standard.md` requires `off != on` before
correctness, and the equivalent here is showing that the OLD matcher and the NEW
one disagree on the exact string that broke. A test suite that only asserts the
fixed behaviour cannot tell a working fix from a no-op.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.status_text import BASKETBALL_LIVE_TOKENS
from syndicate.features.shared.status_text import HOCKEY_LIVE_TOKENS
from syndicate.features.shared.status_text import HOCKEY_TERMINAL_TOKENS
from syndicate.features.shared.status_text import TERMINAL_TOKENS
from syndicate.features.shared.status_text import looks_live_status_text
from syndicate.features.shared.status_text import looks_terminal_status_text


def _old_substring_match(text: str, tokens) -> bool:
    """The matcher as it shipped: `token in text`. Kept to prove the fix bites."""
    lowered = str(text or "").strip().lower()
    return any(token in lowered for token in tokens) if lowered else False


# ---------------------------------------------------------------------------
# REACHABILITY -- the old and new matchers must DISAGREE, or nothing was fixed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,tokens,label",
    [
        ("Halftime", TERMINAL_TOKENS, 'basketball "ft" inside "hal[ft]ime"'),
        ("Playoff Game", HOCKEY_TERMINAL_TOKENS, 'hockey "off" inside "play[off]"'),
        ("Season Opener", HOCKEY_LIVE_TOKENS, 'hockey "so" inside "sea[so]n"'),
    ],
)
def test_old_matcher_fires_and_new_one_does_not(text, tokens, label) -> None:
    """Each of these was a real false positive under substring matching."""
    assert _old_substring_match(text, tokens) is True, f"{label}: old must fire"
    assert looks_terminal_status_text(text, tokens=tokens) is False, (
        f"{label}: new must not"
    )


# ---------------------------------------------------------------------------
# THE REPORTED BUG
# ---------------------------------------------------------------------------

def test_halftime_is_live_and_not_terminal() -> None:
    """The whole defect, in one assertion pair.

    A WNBA game at halftime was displayed as **Final** on a live slate. Both
    checks fired on `"Halftime"` -- the live one correctly, the terminal one on
    `"ft"` inside `"hal-ft-ime"` -- and `if is_final: live = False` resolved the
    contradiction the wrong way.
    """
    assert looks_live_status_text("Halftime", tokens=BASKETBALL_LIVE_TOKENS) is True
    assert looks_terminal_status_text("Halftime", tokens=TERMINAL_TOKENS) is False


def test_the_2026_08_17_final_ot_fix_still_works() -> None:
    """**THIS FIX MUST NOT UNDO THE ONE BEFORE IT.**

    `"Final/OT"` was a finished game published as in-progress indefinitely,
    which cost a live edge tier on a settled game. It matches BOTH lists -- `ot`
    is a whole word because `/` is a non-word character -- so the precedence
    rule still has the contradiction it needs to resolve.
    """
    assert looks_live_status_text("Final/OT", tokens=BASKETBALL_LIVE_TOKENS) is True
    assert looks_terminal_status_text("Final/OT", tokens=TERMINAL_TOKENS) is True


# ---------------------------------------------------------------------------
# The real ESPN strings, both directions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Final", "FT", "Full Time", "Postponed",
                                  "Cancelled", "Suspended", "Final/OT"])
def test_genuinely_terminal_text_still_reads_terminal(text) -> None:
    assert looks_terminal_status_text(text, tokens=TERMINAL_TOKENS) is True


@pytest.mark.parametrize("text", ["Halftime", "Q3 5:23", "Q1 10:00", "Live",
                                  "In Progress"])
def test_genuinely_live_text_still_reads_live(text) -> None:
    assert looks_live_status_text(text, tokens=BASKETBALL_LIVE_TOKENS) is True


@pytest.mark.parametrize("text", ["Halftime", "Q3 5:23", "End of 2nd Quarter",
                                  "3rd Quarter", "Scheduled", ""])
def test_nothing_in_play_reads_terminal(text) -> None:
    assert looks_terminal_status_text(text, tokens=TERMINAL_TOKENS) is False


# ---------------------------------------------------------------------------
# Every sport's own wrapper, so a delegation that got missed is caught
# ---------------------------------------------------------------------------

def test_wnba_wrapper_no_longer_calls_halftime_final() -> None:
    from syndicate.features.wnba.cards import _looks_live_status_text
    from syndicate.features.wnba.cards import _looks_terminal_status_text

    assert _looks_live_status_text("Halftime") is True
    assert _looks_terminal_status_text("Halftime") is False
    assert _looks_terminal_status_text("Final") is True


def test_nba_wrapper_carries_the_same_fix() -> None:
    """NBA carried the same bad token, MASKED rather than absent.

    Its matcher pair was byte-identical to WNBA's, `"ft"` included, but
    `nba/cards.py` never got the 2026-08-17 `if is_final: live = False`
    precedence line -- so `if live: is_final = False` still rescued halftime and
    NBA rendered "Live". The collision was latent, and adding that precedence
    (which NBA will want, for the same `Final/OT` reason) would have activated
    it mid-season. Fixed at the token level so it cannot.
    """
    from syndicate.features.nba.cards import _looks_live_status_text
    from syndicate.features.nba.cards import _looks_terminal_status_text

    assert _looks_live_status_text("Halftime") is True
    assert _looks_terminal_status_text("Halftime") is False
    assert _looks_terminal_status_text("Final") is True


def test_home_board_wrapper_carries_the_same_fix() -> None:
    from syndicate.blueprints.home import _looks_terminal_status_text

    assert _looks_terminal_status_text("Halftime") is False
    assert _looks_terminal_status_text("Final") is True


def test_nhl_wrapper_stops_calling_a_playoff_game_over() -> None:
    from syndicate.features.nhl.cards import _looks_live_status_text
    from syndicate.features.nhl.cards import _looks_terminal_status_text

    assert _looks_terminal_status_text("Playoff Game") is False
    assert _looks_terminal_status_text("Final") is True
    assert _looks_live_status_text("1st Period") is True
    assert _looks_live_status_text("OT") is True


# ---------------------------------------------------------------------------
# Matching mechanics
# ---------------------------------------------------------------------------

def test_multi_word_tokens_keep_their_space_literal() -> None:
    assert looks_terminal_status_text("Full Time", tokens=("full time",)) is True
    assert looks_terminal_status_text("fulltime", tokens=("full time",)) is False


def test_empty_and_none_are_neither_live_nor_terminal() -> None:
    assert looks_live_status_text("", tokens=BASKETBALL_LIVE_TOKENS) is False
    assert looks_live_status_text(None, tokens=BASKETBALL_LIVE_TOKENS) is False
    assert looks_terminal_status_text("", tokens=TERMINAL_TOKENS) is False


def test_multiple_values_are_joined_before_matching() -> None:
    assert looks_terminal_status_text("Halftime", "Final", tokens=TERMINAL_TOKENS) is True
    assert looks_terminal_status_text("Halftime", "Q3", tokens=TERMINAL_TOKENS) is False
