"""NCAAF first-half TOTALS are executable on Kalshi; the winner and spread are NOT.

Measured 2026-09-06: 24 of 200 Layer 2 shortlist rows were `segment=h1` (15
`totals`, 8 `spreads`, 1 `h2h`, all ncaaf, EV to 5.14%) and NOT ONE could
resolve a venue ticker, because `sport_for_series("KXNCAAF1HTOTAL")` returned
None and `classify_market` refused at the first gate with `unmapped_series`.
Production was printing `TITLE KXNCAAF1HTOTAL :: 'Over 6.5 1H points scored'`
every tick while nothing downstream could read it -- the same two-gate shape
`mlb-first5-kalshi-execution` found for `KXMLBF5TOTAL`.

THE FIRST FOUR TESTS FAIL AGAINST UNPATCHED CODE. That is deliberate: a suite
that only ever sees green cannot tell a working registration from a table that
was never read. The scope tests below them fail if someone LATER widens the
registration without arguing for it, which is the other direction this can rot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import kalshi_board_join as kbj  # noqa: E402
from syndicate.features.shared import kalshi_catalogue as kc  # noqa: E402

# The literal title production emits, not a paraphrase -- a guessed title is how
# a registration passes its own test and fails on the venue.
REAL_TITLE = "Over 6.5 1H points scored"
REAL_TICKER = "KXNCAAF1HTOTAL-26SEP07SMUFSU-7"


def _classify(ticker: str, title: str) -> dict:
    series = ticker.split("-")[0]
    return kc.classify_market(
        {"ticker": ticker, "title": title, "series": series, "event_ticker": series}
    )


def test_the_total_series_is_MAPPED_to_ncaaf():
    """Gate one. This returned None and refused everything downstream."""
    assert kc.sport_for_series("KXNCAAF1HTOTAL") == "ncaaf"


def test_the_total_series_carries_the_h1_SEGMENT():
    """Gate two. An unmapped series defaults to `full`, which is precisely how a
    segment contract came to pair with a whole-game board row."""
    assert kc.segment_for_series("KXNCAAF1HTOTAL") == "h1"


def test_the_REAL_production_title_classifies():
    """Reachability before correctness: the registration is worthless if the
    title Kalshi actually sends does not parse."""
    out = _classify(REAL_TICKER, REAL_TITLE)
    assert out.get("status") == "ok", out
    assert out.get("sport") == "ncaaf", out
    assert out.get("line") == pytest.approx(6.5), out
    assert out.get("side") == "over", out


def test_the_FUSED_and_SPLIT_spellings_key_identically():
    """The second gap that shipped MLB inert. `classify_market` yields the fused
    `totals_h1`; the board stores `market='totals'` + `segment='h1'`. If these
    key differently the index lookup misses BEFORE any guard runs, and a guard
    cannot create a pairing the index never produced."""
    fused = kbj._row_market({"sport": "ncaaf", "market": "totals_h1"})
    split = kbj._row_market({"sport": "ncaaf", "market": "totals", "segment": "h1"})
    assert fused == split == "totals", (fused, split)


@pytest.mark.parametrize("series", ["KXNCAAF1H", "KXNCAAF1HSPREAD"])
def test_the_winner_and_spread_are_NOT_tradeable(series):
    """THE SCOPE DECISION, pinned so widening it has to be deliberate.

    `KXNCAAF1H` ('TCU wins the 1st half') and `KXNCAAF1HSPREAD` are declined by
    `recognised_unpriceable_title` upstream of the registry, so registering them
    would not help anyway -- and the spread is the risk class `KXMLBF5SPREAD` is
    excluded for: a Kalshi spread states a MARGIN where the board writes a
    HANDICAP, the defect that put 11 orders on the club they were fading.
    """
    assert kc.sport_for_series(series) is None


@pytest.mark.parametrize("series", ["KXNCAAF1H", "KXNCAAF1HSPREAD"])
def test_the_untradeable_series_RESOLVE_TO_NONE_WHICH_IS_THE_REFUSAL(series):
    """`None` IS the protection, and I had this exactly backwards at first.

    My first patch added all three to `_SERIES_SEGMENT` reasoning that it
    "teaches the guard what they are". It does the opposite: an unmapped series
    carrying a segment marker is REFUSED, and listing it in that table is an
    affirmative statement that we trade it, which REMOVES the refusal.
    `test_kalshi_segment_marker_shape.py` caught it -- `KXNCAAF1HSPREAD` sits in
    its `SEGMENT_SPELLINGS` refuse-list, and my change made it resolve to `h1`.

    So the correct assertion is None, and mapping either of these later must be
    a deliberate act that also updates that file's `mapped` allowlist.
    """
    assert kc.segment_for_series(series) is None


def test_the_winner_title_is_still_DECLINED_by_name():
    """If someone removes the decline without registering a board market, this
    catches it: the refusal must stay a considered decline, not become a silent
    pairing."""
    out = _classify("KXNCAAF1H-26SEP07SMUFSU-TCU", "TCU wins the 1st half")
    assert out.get("status") == "refused", out


def test_the_whole_game_series_is_UNCHANGED():
    """Additive. `KXNCAAFTOTAL` is the whole game and must not acquire a segment
    -- a regression here would repoint every existing NCAAF total."""
    assert kc.sport_for_series("KXNCAAFTOTAL") == "ncaaf"
    assert kc.segment_for_series("KXNCAAFTOTAL") == "full"


def test_a_first_half_contract_does_not_key_onto_a_whole_game_row():
    """The money question, stated as a key comparison: an h1 contract and a
    full-game row must not produce the same identity."""
    h1 = kbj._row_market({"sport": "ncaaf", "market": "totals_h1"})
    full = kbj._row_market({"sport": "ncaaf", "market": "totals"})
    assert h1 == full == "totals"
    # ...which is WHY the segment must be carried separately, and is.
    assert kc.segment_for_series("KXNCAAF1HTOTAL") != kc.segment_for_series("KXNCAAFTOTAL")
