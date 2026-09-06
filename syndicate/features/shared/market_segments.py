"""Interval/segment vocabulary and OddsAPI market-key mapping, for every sport.

WHY THIS IS SHARED RATHER THAN PER-FETCHER. MLB already had segment capture --
`first1`/`first3`/`first5`, and it is the reason `/mlb/market-board` can show F1
prices at all. But its mapping lives inside `fetch_mlb_oddsapi_local.py` as a
literal dict, so every other sport got `segment="full"` by default and no way to
ask for anything else. Measured on production 2026-08-11:

    mlb      segment = full, first1, first3, first5
    wnba     segment = full          <- 395 rows, one segment
    soccer   segment = full
    nfl      segment = full

A second bespoke map in the basketball fetcher would have made that permanent,
which is `#329` in its first life: six per-sport implementations of one idea and
two sports with nothing.

THE VOCABULARY IS NOT UNIFORM ACROSS SPORTS, AND MUST NOT BE
------------------------------------------------------------
Sports are segmented differently and flattening them would invent intervals that
do not exist:

    baseball     first1 / first3 / first5      innings, not periods
    basketball   q1..q4 + h1 / h2              NBA and WNBA play quarters
    ncaab        h1 / h2 ONLY                  college basketball plays HALVES;
                                               asking for q1 returns nothing and
                                               spends a credit finding out
    football     q1..q4 + h1 / h2
    hockey       p1 / p2 / p3                  periods, and there are three

So the map is per sport, declared in one place, with the sport's own names.
`full` is universal and always present.

COST IS THE REASON THIS IS OPT-IN PER CALL
------------------------------------------
Each segment market is a distinct OddsAPI market key on a per-event request.
Asking for h2h+spreads+totals across q1..q4+h1+h2 is **18 additional keys per
event**, on top of the full-game three. That is not free and it is why
`segment_market_keys()` takes an explicit list rather than defaulting to
everything: the caller decides how deep to go, and the T-window (`#16`/`#17`)
decides when.
"""

from __future__ import annotations

from typing import Iterable, Mapping

# Canonical segment names per sport. `full` is implicit everywhere and is not
# listed -- it needs no market-key suffix.
SPORT_SEGMENTS: Mapping[str, tuple[str, ...]] = {
    "mlb": ("first1", "first3", "first5"),
    "nba": ("q1", "q2", "q3", "q4", "h1", "h2"),
    "wnba": ("q1", "q2", "q3", "q4", "h1", "h2"),
    # Halves only. College basketball does not play quarters, so a q1 request is
    # a credit spent to be told nothing exists.
    "ncaab": ("h1", "h2"),
    "nfl": ("q1", "q2", "q3", "q4", "h1", "h2"),
    "ncaaf": ("q1", "q2", "q3", "q4", "h1", "h2"),
    "nhl": ("p1", "p2", "p3"),
    "soccer": ("h1", "h2"),
}

# How each segment is spelled in an OddsAPI market key suffix.
_SUFFIX: Mapping[str, str] = {
    "first1": "1st_1_innings",
    "first3": "1st_3_innings",
    "first5": "1st_5_innings",
    "q1": "q1", "q2": "q2", "q3": "q3", "q4": "q4",
    "h1": "h1", "h2": "h2",
    "p1": "p1", "p2": "p2", "p3": "p3",
}

# The game markets worth requesting per segment, and the canonical market name
# each maps to. `alternate_*` is kept because alt lines are where segment
# coverage is thickest -- MLB's own capture carries `totals_alt`/`spreads_alt`
# per segment and the board shows them.
_MARKET_BASES: Mapping[str, str] = {
    "h2h": "h2h",
    # THREE-WAY, and it is not optional. A partial interval can end level --
    # five innings, a quarter, a half -- so books quote win/draw/lose on it.
    # Omitting this dropped 3 of MLB's 18 working segment keys, caught by
    # diffing the shared map against the bespoke one it replaces rather than by
    # reasoning about which markets "should" exist.
    "h2h_3_way": "h2h_3_way",
    "spreads": "spreads",
    "totals": "totals",
    "alternate_spreads": "spreads_alt",
    "alternate_totals": "totals_alt",
}


def segments_for_sport(sport: str) -> tuple[str, ...]:
    return tuple(SPORT_SEGMENTS.get(str(sport or "").strip().lower(), ()))


def segment_market_keys(
    sport: str,
    *,
    segments: Iterable[str] | None = None,
    bases: Iterable[str] | None = None,
) -> dict[str, tuple[str, str]]:
    """OddsAPI market key -> (segment, canonical market).

    The inverse of what a fetcher needs twice: the keys to REQUEST, and the map
    to tag each returned market with once it arrives. Returning one dict keeps
    those from drifting -- a fetcher that requests `totals_q1` and then fails to
    recognise it writes the quotes under `full`, which is worse than not asking,
    because the board then shows a first-quarter total as a full-game line.
    """
    slug = str(sport or "").strip().lower()
    wanted = tuple(segments) if segments is not None else segments_for_sport(slug)
    known = set(segments_for_sport(slug))
    use_bases = tuple(bases) if bases is not None else tuple(_MARKET_BASES)
    out: dict[str, tuple[str, str]] = {}
    for seg in wanted:
        # An unknown segment for this sport is DROPPED, not guessed at. Asking
        # NCAAB for q1 must not silently become h1.
        if seg not in known:
            continue
        suffix = _SUFFIX.get(seg)
        if not suffix:
            continue
        for base in use_bases:
            canonical = _MARKET_BASES.get(base)
            if not canonical:
                continue
            out[f"{base}_{suffix}"] = (seg, canonical)
    return out


def full_game_market_keys(bases: Iterable[str] | None = None) -> dict[str, tuple[str, str]]:
    """The unsegmented keys, in the same shape, so callers merge one dict."""
    use_bases = tuple(bases) if bases is not None else tuple(_MARKET_BASES)
    return {base: ("full", _MARKET_BASES[base]) for base in use_bases if base in _MARKET_BASES}


def split_segment_market_key(sport: str, market_key: object) -> tuple[str, str] | None:
    """`totals_1st_5_innings` -> `("first5", "totals")`. None if not segmented.

    THE INVERSE OF `segment_market_keys`, AND BUILT FROM IT rather than from a
    second table. `_SUFFIX` and `_MARKET_BASES` already encode the split; a
    parallel parser here would be the drift `segment_market_keys`' own docstring
    warns about ("a fetcher that requests `totals_q1` and then fails to
    recognise it writes the quotes under `full`").

    WHY IT EXISTS. Two vocabularies name the same bet and only one of them is
    the board's. A fetcher REQUESTS `totals_1st_5_innings`; the board stores
    what came back as `market='totals'` plus `segment='first5'`, because that is
    the pair this function's forward twin returns. Anything that produces the
    suffixed spelling and then has to meet a board row -- the Kalshi join does,
    via `classify_market` -- needs the split, or it keys on a market name the
    board has never used and the lookup misses BEFORE any segment check runs.

    `None` means "not a segment key for this sport", which is different from
    `("full", key)`: the caller must be able to leave a market it does not
    recognise exactly as it found it. Returning `full` here would be the
    papering-over `normalize_segment` explicitly refuses to do.
    """
    key = str(market_key or "").strip().lower()
    if not key:
        return None
    return segment_market_keys(sport).get(key)


#: The ALTERNATE-LINE spelling of a market -> the main-line one. Derived from
#: `_MARKET_BASES` rather than written out, so adding an `alternate_*` base
#: there cannot leave a second table behind to drift.
_ALT_TO_BASE: Mapping[str, str] = {
    _MARKET_BASES[f"alternate_{base}"]: _MARKET_BASES[base]
    for base in ("totals", "spreads")
    if f"alternate_{base}" in _MARKET_BASES and base in _MARKET_BASES
}


def base_market_for_alternate(market: object) -> str | None:
    """`totals_alt` -> `totals`. None when the market is not an alternate.

    WHAT THE `_alt` SUFFIX MEANS, because the answer decides whether collapsing
    it is a correction or a defect. `alternate_totals` is OddsAPI's market for
    THE SAME BET AT NON-MAIN LINES. A row `totals_alt / 4.5 / over` and a row
    `totals / 4.5 / over`, same event and same segment, are one wager priced by
    two feeds. The suffix names WHICH FEED, not what was bet.

    THAT IS NOT TRUE OF THE OTHER TWO DISTINCTIONS THIS JOIN GUARDS, and the
    difference is the entire safety argument for collapsing here and nowhere
    else. A `first3` row against a full-game contract is a different PORTION of
    the game ($7.08, 2026-08-28). A Kalshi spread states a MARGIN where the
    board writes a HANDICAP, so pairing on magnitude backs the opposite CLUB
    (11 orders, 2026-08-26). Those pair genuinely different wagers and must keep
    refusing. This one does not, so refusing it only costs coverage: measured
    2026-09-06, 6 of 8 `first5` `spreads_alt` rows sat exactly on Kalshi's only
    two F5 spread strikes while the 3 main-line rows sat at 0.5/0.5/1.0, so the
    series could not execute at all.

    `None` rather than echoing the input, so a caller can tell "not an
    alternate" from "an alternate that collapsed to itself" and leave the former
    exactly as it found it.
    """
    key = str(market or "").strip().lower()
    if not key:
        return None
    return _ALT_TO_BASE.get(key)


def normalize_segment(value: object) -> str:
    """Empty/None/unknown -> `full`.

    `full` is the honest default ONLY here, at the point where a missing suffix
    genuinely means the whole game. It must not be used to paper over a segment
    key the caller failed to recognise -- see `segment_market_keys`.
    """
    text = str(value or "").strip().lower()
    return text or "full"
