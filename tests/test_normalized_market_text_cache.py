"""`_normalized_market_text`: precompiled + memoized. `[2026-08-29]`

WHY EQUIVALENCE IS THE MAIN TEST. This function is the join key between
candidates and odds history. A behaviour change here does not crash -- it
silently stops matching, which is the failure this repo has chased repeatedly
(the 2026-08-04 "Endy Rodriguez" case is in its own docstring). So the primary
test re-implements the ORIGINAL body verbatim and asserts the new one agrees,
over accents, possessives, the 3pm aliases, and junk.

The performance defect it fixes, measured on refresh-worker `6625b5e6` at
16:47:55Z over one soccer `_consume_sport`: 39,281,743 calls, 713.5s cumulative,
with 238,477,602 `re._compile` entries because the patterns were strings.
"""

from __future__ import annotations

import re
import unicodedata

import pytest

from syndicate.features import intelligence as I


def _original(value) -> str:
    """The pre-2026-08-29 implementation, verbatim."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    lowered = text.lower()
    lowered = re.sub(r"([a-z0-9])['’]s\b", r"\1", lowered)
    lowered = re.sub(r"\b3\s*pt\s*m\b", " 3pm ", lowered)
    lowered = re.sub(r"\b3\s*point\s*makes?\b", " 3pm ", lowered)
    lowered = re.sub(r"\bthree\s+point\s+makes?\b", " 3pm ", lowered)
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    return re.sub(r"\s+", " ", normalized)


CASES = [
    None, "", "   ", 0, 123, 4.5, True,
    "Endy Rodríguez", "Nasim Nuñez", "Luis Díaz", "Vitória de Guimarães",
    "Sint-Truidense", "Union St.-Gilloise", "Royal Charleroi SC",
    "Player's points", "Player’s points", "PLAYER'S POINTS",
    "3 pt m", "3pt m", "3 point makes", "3 point make", "three point makes",
    "Three  Point   Make", "3PTM",
    "Over 2.5 Goals", "Both Teams To Score", "alternate_totals_corners",
    "h2h", "spreads", "totals", "  mixed   CASE  and\tTABS \n",
    "!!!@@@###", "a1b2c3", "José Mourinho's team", "Anytime Goalscorer",
    "Sacramento State @ Eastern Michigan", "tsc-cfb-sacst-emich-2026-08-29",
]


@pytest.mark.parametrize("value", CASES)
def test_matches_the_original_implementation(value):
    assert I._normalized_market_text(value) == _original(value)


def test_the_curly_apostrophe_is_still_handled():
    """The original class was ['’] with a literal U+2019; the compiled pattern
    spells it \u2019. Same character or the possessive strip silently stops."""
    assert I._normalized_market_text("Player’s") == I._normalized_market_text("Player's")
    assert I._normalized_market_text("Player’s") == "player"


def test_accent_folding_still_joins_to_ascii_keys():
    """The 2026-08-04 regression this function's docstring records."""
    assert I._normalized_market_text("Endy Rodríguez") == "endy rodriguez"
    assert I._normalized_market_text("Nasim Nuñez") == "nasim nunez"


def test_none_and_falsey_collapse_to_empty():
    for value in (None, "", 0, False):
        assert I._normalized_market_text(value) == ""


def test_it_is_actually_memoized(monkeypatch):
    """OFF != ON, on the thing that mattered: 39M calls became a dict hit."""
    I._normalized_market_text_cached.cache_clear()
    before = I._normalized_market_text_cached.cache_info()
    for _ in range(500):
        I._normalized_market_text("Both Teams To Score")
    info = I._normalized_market_text_cached.cache_info()
    assert info.misses - before.misses == 1, info
    assert info.hits >= 499, info


def test_the_cache_is_bounded():
    """Unbounded is not an option in a 4GiB process with an OOM history."""
    assert I._normalized_market_text_cached.cache_info().maxsize == 65536


def test_distinct_inputs_do_not_collide():
    seen = {}
    for value in CASES:
        out = I._normalized_market_text(value)
        seen.setdefault(out, set()).add(_original(value))
    for out, originals in seen.items():
        assert originals == {out}, f"{out} collided with {originals}"
