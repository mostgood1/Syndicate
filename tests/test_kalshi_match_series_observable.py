"""Which SERIES a segment board row matched is a READING, not an inference.

THE SCENARIO IS REAL, taken from production 2026-09-06. A live first5 row
(MIL@CIN, totals, over 4.5) priced at `kalshi 0.870` against a 7-book consensus
of `0.4926`. Kalshi lists BOTH contracts for that game at that strike:

    KXMLBTOTAL-26SEP061210MILCIN-5     "Over 4.5 runs scored"
    KXMLBF5TOTAL-26SEP061210MILCIN-5   "First 5 innings: Over 4.5 runs"

and `_row_market()` strips the segment on purpose, so both key as
`(event, 'totals', 4.5)`. Nobody could say which one priced the row: board rows
carry no `venue_ticker` and the join emitted no match record. These tests make
the answer readable, and they use the ACTUAL tickers and titles rather than
invented ones -- a fixture that paraphrases the venue is how a join passes its
own test and fails on the wire.

`segment_refused_series` exists because `segment_matched_series` alone cannot
tell "the guard worked" from "no segment row was present". That null was read
three different ways in one day.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.kalshi_board_join import (  # noqa: E402
    join_kalshi_to_board,
)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _game_lines_on(monkeypatch):
    """The join is gated behind `SYNDICATE_KALSHI_GAME_LINES`, which reads `1` in
    production and is unset under pytest. Without this every case below refuses
    `game_lines_disabled` and the suite goes green while testing nothing -- the
    exact vacuous-pass shape these tests exist to rule out."""
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")


EVENT = "mil-cin-2026-09-06"

FULL_GAME_CONTRACT = {
    "ticker": "KXMLBTOTAL-26SEP061210MILCIN-5",
    "series": "KXMLBTOTAL",
    "series_ticker": "KXMLBTOTAL",
    "title": "Over 4.5 runs scored",
    "event_ticker": "KXMLBTOTAL-26SEP061210MILCIN",
    # -669 american == ~0.870 implied: the number production actually showed
    "yes_american": -669,
    "no_american": 569,
    "yes_probability": 0.870,
    "no_probability": 0.130,
    "status": "active",
}

FIRST5_CONTRACT = {
    "ticker": "KXMLBF5TOTAL-26SEP061210MILCIN-5",
    "series": "KXMLBF5TOTAL",
    "series_ticker": "KXMLBF5TOTAL",
    "title": "First 5 innings: Over 4.5 runs",
    "event_ticker": "KXMLBF5TOTAL-26SEP061210MILCIN",
    "yes_american": 103,
    "no_american": -123,
    "yes_probability": 0.492,
    "no_probability": 0.508,
    "status": "active",
}


def _first5_row():
    return {
        "sport": "mlb",
        "kind": "game_line",
        "event_id": EVENT,
        "market": "totals",
        "segment": "first5",
        "line": 4.5,
        "side": "over",
        "home_team": "Cincinnati Reds",
        "away_team": "Milwaukee Brewers",
        "quote": {"price": 103},
    }


def _join(markets, rows):
    return join_kalshi_to_board(kalshi_markets=markets, board_rows=rows)


def test_the_join_reports_both_counters_even_when_EMPTY():
    """An absent key and a zero count are the same silence that made this
    unanswerable. Both must be present on every return."""
    out = _join([], [])
    assert out["segment_matched_series"] == {}
    assert out["segment_refused_series"] == {}


def test_a_first5_row_against_the_FULL_GAME_contract_is_REFUSED_and_NAMED():
    """The mismatch case. `_segments_agree` computes `first5 == full` -> False,
    so this must refuse -- and the refusal must say WHICH series it refused,
    which is the whole point of the instrument."""
    out = _join([FULL_GAME_CONTRACT], [_first5_row()])
    assert out["segment_matched_series"] == {}, out["segment_matched_series"]
    assert "first5->KXMLBTOTAL" in out["segment_refused_series"], (
        "the refusal did not name the series it refused: %r"
        % out["segment_refused_series"])


def test_a_first5_row_against_the_FIRST5_contract_is_MATCHED_and_NAMED():
    """off != on. If refusal were unconditional the test above would pass while
    the join was broken, so the accepting case has to be exercised too."""
    out = _join([FIRST5_CONTRACT], [_first5_row()])
    assert "first5->KXMLBF5TOTAL" in out["segment_matched_series"], (
        "a first5 row did not record a match against its own series: matched=%r "
        "refused=%r" % (out["segment_matched_series"], out["segment_refused_series"]))


def test_BOTH_contracts_present_is_the_production_case_and_only_one_may_match():
    """The actual 2026-09-06 board state: both contracts live, same game, same
    strike. Exactly one may match, and the instrument must say which."""
    out = _join([FULL_GAME_CONTRACT, FIRST5_CONTRACT], [_first5_row()])
    matched = out["segment_matched_series"]
    assert list(matched) == ["first5->KXMLBF5TOTAL"], (
        "with both contracts present the first5 row matched %r -- if this names "
        "KXMLBTOTAL then a guard that provably computes False is being bypassed"
        % matched)


def test_a_FULL_GAME_row_is_not_counted_as_a_segment():
    """Whole-game rows are the overwhelming majority; counting them would bury
    the signal this exists to surface."""
    row = _first5_row()
    row["segment"] = "full"
    out = _join([FULL_GAME_CONTRACT], [row])
    assert out["segment_matched_series"] == {}
    assert out["segment_refused_series"] == {}


def test_the_counters_do_not_change_MATCHING_behaviour():
    """Instrumentation only. `matched` must be identical to what the join
    produced before, so a regression here is visible as a count change."""
    out = _join([FIRST5_CONTRACT], [_first5_row()])
    assert out["matched"] == 1
    out_refused = _join([FULL_GAME_CONTRACT], [_first5_row()])
    assert out_refused["matched"] == 0
