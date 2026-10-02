"""Lane `layer2-freshness-1h` (2026-10-02).

Reachability first (`model_engine_standard.md`): each test proves the new code
path is TAKEN, not only that its output looks right.
"""
from __future__ import annotations

import pytest

from pipeline import layer2_shortlist as shortlist


@pytest.fixture
def attach_calls(monkeypatch):
    """Record every date `attach_projections` is asked to join."""
    from syndicate.features.shared import board_enrichment

    calls: list[str] = []

    def fake_attach(grid, *, sport, selected_date):
        calls.append(selected_date)
        return {"rows_considered": len(grid), "rows_with_projection": 0}

    monkeypatch.setattr(board_enrichment, "attach_projections", fake_attach)
    return calls


def test_single_date_sport_also_joins_tomorrows_rows(attach_calls):
    # The measured case: NHL's window is [selected_date], but the grid carries a
    # 10-03 game. Before the fix only 2026-10-02 was joined.
    grid = [
        {"commence_time": "2026-10-02T23:00:00Z"},
        {"commence_time": "2026-10-03T23:00:00Z"},
    ]
    shortlist._attach_projections_over_window(
        grid, sport="nhl", selected_date="2026-10-02", window_dates=["2026-10-02"]
    )
    assert attach_calls == ["2026-10-02", "2026-10-03"]


def test_kickoff_date_is_central_not_utc():
    # 01:00Z on 10-03 is 8pm CT on 10-02 -- the 10-02 slate, not 10-03's.
    grid = [{"commence_time": "2026-10-03T01:00:00Z"}]
    assert shortlist._row_kickoff_dates(grid, "2026-10-02") == ["2026-10-02"]


def test_kickoff_dates_are_bounded_to_the_horizon():
    grid = [
        {"commence_time": "2026-09-30T18:00:00Z"},  # before the slate
        {"commence_time": "2026-10-04T18:00:00Z"},  # inside
        {"commence_time": "2026-10-20T18:00:00Z"},  # far past the horizon
        {"commence_time": "not a date"},
        {},
        "not a row",
    ]
    assert shortlist._row_kickoff_dates(grid, "2026-10-02") == ["2026-10-04"]


def test_self_windowing_sport_is_still_joined_once(attach_calls):
    # Soccer's own join spans its window; extra passes would only re-inflate the
    # counters `_SELF_WINDOWING_PROJECTION_SPORTS` exists to protect.
    grid = [{"commence_time": "2026-10-03T14:00:00Z"}]
    shortlist._attach_projections_over_window(
        grid, sport="soccer", selected_date="2026-10-02", window_dates=["2026-10-02", "2026-10-03"]
    )
    assert attach_calls == ["2026-10-02"]
