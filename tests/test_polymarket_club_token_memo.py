"""`_club_token_names` is memoised for strings and must answer exactly as before.

Lane `web-restart-healthz` 2026-10-07: py-spy had the board's `portfolio_commit` (normally
10-50 s) 8+ minutes inside this pure function, re-folding the same club names for every
token x fixture on every row.
"""

from __future__ import annotations

import itertools

from syndicate.features.shared import polymarket_board_join as pbj

CLUBS = ["Alavés", "1899 Hoffenheim", "Manchester City", "Manchester United", "Paris Saint Germain",
         "West Ham United", "Real Racing Club de Santander", "Crystal Palace", "Vitória SC", "CF Montréal",
         "Union St.-Gilloise", "Kansas City Chiefs", "", "  ", "A"]
TOKENS = ["ala", "hof", "mnc", "mci", "psg", "whu", "rrc", "cry", "vit", "mon", "uni", "kc", "kan", "a", "", "MAN", "st",
          "ham", "par", "x"]


def test_memo_equals_the_uncached_function_everywhere():
    pbj._club_token_names_cached.cache_clear()
    for token, club in itertools.product(TOKENS, CLUBS):
        expected = pbj._club_token_names_uncached(token, club)
        assert pbj._club_token_names(token, club) == expected, (token, club)
        assert pbj._club_token_names(token, club) == expected, (token, club)   # served from the memo


def test_the_documented_cases_still_hold():
    assert pbj._club_token_names("ala", "Alavés")
    assert pbj._club_token_names("hof", "1899 Hoffenheim")
    assert not pbj._club_token_names("mnc", "Manchester City")
    assert pbj._club_token_names("psg", "Paris Saint Germain")


def test_non_strings_bypass_the_memo():
    assert pbj._club_token_names(None, "Alavés") is False
    assert pbj._club_token_names(12, "12 Club") == pbj._club_token_names_uncached(12, "12 Club")
