"""`#343` — one interval vocabulary for every sport.

MLB had segment capture (first1/first3/first5) via a literal dict inside its own
fetcher; every other sport got `segment="full"` by default and no way to ask for
anything else. Measured on production 2026-08-11: mlb carried 4 segments,
wnba/soccer/nfl carried 1.
"""

from __future__ import annotations

import pathlib
import re

from syndicate.features.shared.market_segments import (
    full_game_market_keys,
    normalize_segment,
    segment_market_keys,
    segments_for_sport,
)

_MLB_FETCHER = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fetch_mlb_oddsapi_local.py"


def _mlb_bespoke_segment_map() -> dict[str, tuple[str, str]]:
    src = _MLB_FETCHER.read_text(encoding="utf-8")
    block = re.search(r"segment_market_map = \{(.*?)\n    \}", src, re.S).group(1)
    pairs = re.finditer(r'"([^"]+)":\s*\("([^"]+)",\s*"([^"]+)"\)', block)
    return {m.group(1): (m.group(2), m.group(3)) for m in pairs if m.group(2) != "full"}


def test_wnba_gets_quarters_and_halves():
    assert segments_for_sport("wnba") == ("q1", "q2", "q3", "q4", "h1", "h2")
    keys = segment_market_keys("wnba")
    assert keys["h2h_q1"] == ("q1", "h2h")
    assert keys["totals_q3"] == ("q3", "totals")
    assert keys["spreads_h2"] == ("h2", "spreads")
    assert keys["alternate_totals_q4"] == ("q4", "totals_alt")


def test_ncaab_is_halves_only_because_it_plays_halves():
    # College basketball has no quarters. Asking for q1 is a credit spent to be
    # told nothing exists, so the vocabulary must not offer it.
    assert segments_for_sport("ncaab") == ("h1", "h2")
    keys = segment_market_keys("ncaab")
    assert "h2h_h1" in keys
    assert not any(k.endswith(("_q1", "_q2", "_q3", "_q4")) for k in keys)


def test_an_unknown_segment_for_a_sport_is_dropped_not_guessed():
    # Asking NCAAB for q1 must not silently become h1.
    keys = segment_market_keys("ncaab", segments=["q1", "h1"])
    assert "h2h_h1" in keys
    assert not any("_q1" in k for k in keys)


def test_each_sport_keeps_its_own_interval_names():
    # Flattening these would invent intervals that do not exist.
    assert segments_for_sport("mlb") == ("first1", "first3", "first5")
    assert segments_for_sport("nhl") == ("p1", "p2", "p3")
    assert segments_for_sport("soccer") == ("h1", "h2")
    assert segment_market_keys("mlb")["totals_1st_5_innings"] == ("first5", "totals")
    assert segment_market_keys("nhl")["h2h_p2"] == ("p2", "h2h")


def test_the_shared_map_reproduces_mlbs_working_capture_exactly():
    """The regression that matters.

    MLB's segment capture already works in production, so a shared map replacing
    it must be a SUPERSET, not an approximation. Diffing against the bespoke dict
    caught 3 missing `h2h_3_way_*` keys that no amount of reasoning about "which
    markets should exist" would have surfaced -- a partial interval can end
    level, so books quote win/draw/lose on it.
    """
    bespoke = _mlb_bespoke_segment_map()
    shared = segment_market_keys("mlb")
    assert bespoke, "MLB's bespoke map failed to parse -- the guard is blind, not passing"
    missing = sorted(set(bespoke) - set(shared))
    assert not missing, f"shared map drops working MLB keys: {missing}"
    for key, value in bespoke.items():
        assert shared[key] == value, (key, value, shared[key])


def test_request_and_tag_come_from_one_map():
    # A fetcher that requests totals_q1 and then fails to recognise it writes the
    # quotes under `full` -- a first-quarter total shown as a full-game line,
    # which is worse than not asking at all.
    for market_key, (segment, canonical) in segment_market_keys("nfl").items():
        assert market_key.endswith(segment)
        assert canonical in {"h2h", "h2h_3_way", "spreads", "totals", "spreads_alt", "totals_alt"}


def test_full_game_keys_share_the_shape_so_callers_merge_one_dict():
    full = full_game_market_keys()
    assert full["h2h"] == ("full", "h2h")
    assert full["alternate_totals"] == ("full", "totals_alt")
    merged = {**full, **segment_market_keys("wnba")}
    assert merged["h2h"] == ("full", "h2h")
    assert merged["h2h_q1"] == ("q1", "h2h")


def test_normalize_only_defaults_a_genuinely_absent_suffix():
    assert normalize_segment(None) == "full"
    assert normalize_segment("") == "full"
    assert normalize_segment("q1") == "q1"


def test_a_sport_with_no_declared_segments_asks_for_nothing():
    assert segments_for_sport("cricket") == ()
    assert segment_market_keys("cricket") == {}
