"""Interval totals show their OWN interval's score in the Actual column (lane `layer2-live-segment-actuals`).

Before: a live q2 / h1 total rendered a dash, and the only score on the card was
the full-game chip score. `_segment_score_for_row` stamps the row's interval
score from the chip's per-period line score; `_game_total_actual` reads it, and
never falls back to the game score for an interval row.
"""
from __future__ import annotations

from syndicate.features.shared.board_enrichment import _segment_score_for_row
from syndicate.features.shared.layer2_board import _live_projection_columns


def _chip(state: str, away: list, home: list) -> dict:
    return {"state": state, "linescore": {"kind": "periods", "labels": [str(i + 1) for i in range(len(home))],
                                          "away": away, "home": home}}


def _row(sport: str, segment: str, market: str = "totals") -> dict:
    return {"sport": sport, "kind": "game", "market": market, "segment": segment}


def test_football_quarter_and_half_scores_are_their_own() -> None:
    chip = _chip("live", away=[7, 3, 0], home=[0, 10, 6])   # third quarter under way
    assert _segment_score_for_row("nfl", _row("nfl", "q2"), chip) == {"segment": "q2", "home": 10, "away": 3, "is_final": True}
    assert _segment_score_for_row("nfl", _row("nfl", "h1"), chip) == {"segment": "h1", "home": 10, "away": 10, "is_final": True}
    q3 = _segment_score_for_row("ncaaf", _row("ncaaf", "q3"), chip)
    assert q3 == {"segment": "q3", "home": 6, "away": 0, "is_final": False}


def test_unstarted_unsupported_and_full_segments_stamp_nothing() -> None:
    chip = _chip("live", away=[7], home=[0])
    assert _segment_score_for_row("nfl", _row("nfl", "q4"), chip) is None      # not started
    assert _segment_score_for_row("nfl", _row("nfl", "full"), chip) is None    # full game is not a segment
    assert _segment_score_for_row("nhl", _row("nhl", "p1"), chip) is None      # sport not in segment_periods
    assert _segment_score_for_row("nfl", _row("nfl", "q1"), {"state": "pregame"}) is None


def test_soccer_first_half() -> None:
    chip = _chip("live", away=[1, 0], home=[2, 1])
    assert _segment_score_for_row("soccer", _row("soccer", "h1"), chip)["home"] == 2


def test_actual_column_reads_the_interval_never_the_game() -> None:
    q2 = {**_row("nfl", "q2"), "projection": {},
          "game": {"state": "live", "home_score": "16", "away_score": "10",
                   "segment_score": {"segment": "q2", "home": 10, "away": 3, "is_final": True}}}
    assert _live_projection_columns(q2)["actual"] == 13.0      # q2 points, not the game's 26
    no_stamp = {**_row("nfl", "q2"), "projection": {}, "game": {"state": "live", "home_score": "16", "away_score": "10"}}
    assert "actual" not in _live_projection_columns(no_stamp)  # absent stays absent
    full = {**_row("nfl", "full"), "projection": {}, "game": {"state": "live", "home_score": "16", "away_score": "10"}}
    assert _live_projection_columns(full)["actual"] == 26.0
    pregame = {**_row("nfl", "full"), "projection": {}, "game": {"state": "pregame", "home_score": None, "away_score": None}}
    assert "actual" not in _live_projection_columns(pregame)
    spread = {**_row("nfl", "q2", market="spreads"), "projection": {}, "game": q2["game"]}
    assert "actual" not in _live_projection_columns(spread)   # totals only


def test_prop_join_actual_still_wins() -> None:
    row = {**_row("nfl", "full"), "projection": {"actual_so_far": 3.0},
           "game": {"state": "live", "home_score": "16", "away_score": "10"}}
    assert _live_projection_columns(row)["actual"] == 3.0
