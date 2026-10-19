"""A next-day board keeps its whole Central day (lane `layer2-next-day-horizon`).

Measured 2026-10-19 17:41 CT: the 10-20 board had been built at 22:39Z, before 00:00Z. It carried BOS @ DET (19:00Z) and
PHI @ NYK (23:00Z) and dropped OKC @ SAS (01:30Z 10-21 = 8:30 PM CT 10-20), although the 10-20 quote shard held 3,820
quotes for that game. `_within_horizon` counted UTC days from the build's wall clock (10-19), so the gap read as 2 days.
The 2 PM CT day-ahead cheat sheet reads that board, so it lost every evening game of the next day.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pipeline.layer2_shortlist import _date_start_central
from syndicate.features.shared.layer2_board import select_shortlist

_SEQ = itertools.count()
BUILT = datetime(2026, 10, 19, 22, 39, tzinfo=timezone.utc)          # 5:39 PM CT 10-19
TOMORROW = _date_start_central("2026-10-20")


def _cand(start, score=10.0):
    return {"sport": "nba", "kind": "prop", "market": "player_points", "event_id": f"evt{next(_SEQ)}",
            "commence_time": start, "score": {"score": score}}


def _rows():
    return [_cand("2026-10-20T19:00:00Z"), _cand("2026-10-20T23:00:00Z"), _cand("2026-10-21T01:30:00Z")]


def test_the_anchor_is_midnight_central_of_the_boards_day():
    assert TOMORROW == datetime(2026, 10, 20, tzinfo=ZoneInfo("America/Chicago"))
    assert TOMORROW.astimezone(timezone.utc).isoformat() == "2026-10-20T05:00:00+00:00"
    assert _date_start_central("not a date") is None


def test_unanchored_the_late_game_is_dropped_as_the_measurement_showed():
    result = select_shortlist(_rows(), now=BUILT)
    assert result["rows_beyond_horizon"] == 1
    assert sorted(r["commence_time"] for r in result["rows"]) == ["2026-10-20T19:00:00Z", "2026-10-20T23:00:00Z"]


def test_anchored_at_the_boards_own_date_every_game_of_that_central_day_stays():
    result = select_shortlist(_rows(), now=BUILT, horizon_anchor=TOMORROW)
    assert result["rows_beyond_horizon"] == 0 and len(result["rows"]) == 3


def test_today_and_earlier_boards_are_unchanged():
    # The wall clock is later than today's midnight, so the anchor cannot move a today build.
    today = _date_start_central("2026-10-19")
    rows = _rows() + [_cand("2026-10-22T00:00:00Z")]
    plain = select_shortlist(rows, now=BUILT)
    anchored = select_shortlist(rows, now=BUILT, horizon_anchor=today)
    assert plain["rows_beyond_horizon"] == anchored["rows_beyond_horizon"] == 2
    assert [r["event_id"] for r in plain["rows"]] == [r["event_id"] for r in anchored["rows"]]


def test_the_anchor_never_admits_a_day_past_the_boards_own_horizon():
    result = select_shortlist(_rows() + [_cand("2026-10-22T23:00:00Z")], now=BUILT, horizon_anchor=TOMORROW)
    assert result["rows_beyond_horizon"] == 1                        # 10-22 is two days past 10-20
