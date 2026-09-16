"""NHL is admitted to the sweep calendar from its 2026 preseason (09-19), not only October.

Lane nhl-season-readiness, user decision 2026-09-16. The gate matters because the sweep
uses `_active_sports_for_date` whenever `SYNDICATE_LIVE_ODDS_REFRESH_SPORTS` is unset, so a
date outside NHL's window drops NHL whatever `SYNDICATE_ACTIVE_SPORTS` says.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.ops_refresh import _active_sports_for_date


def _sports(date_str: str) -> list[str]:
    return _active_sports_for_date(date_str).split(",")


@pytest.mark.parametrize("date_str", ["2026-09-19", "2026-09-20", "2026-09-30", "2026-10-01", "2027-01-15", "2027-06-30"])
def test_nhl_is_active_from_preseason_through_june(date_str):
    assert "nhl" in _sports(date_str)


@pytest.mark.parametrize("date_str", ["2026-07-01", "2026-08-31", "2026-09-01", "2026-09-18"])
def test_nhl_is_inactive_before_preseason(date_str):
    assert "nhl" not in _sports(date_str)


def test_the_boundary_is_exactly_september_19():
    assert "nhl" not in _sports("2026-09-18")
    assert "nhl" in _sports("2026-09-19")


def test_no_other_sport_changes_across_the_boundary():
    before = set(_sports("2026-09-18")) - {"nhl"}
    after = set(_sports("2026-09-19")) - {"nhl"}
    assert before == after
