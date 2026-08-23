"""Interval-final projection: the shrinking horizon, and the truth it is scored on.

The distinguishing property against `basketball_projection_rows` is that the
horizon ENDS AT THE BUZZER rather than running a fixed length. Most of this file
pins that, because getting it wrong produces a model that answers a question no
book prices.
"""

from __future__ import annotations

from typing import Any

import pytest

from syndicate.features.shared.basketball_interval_projection import period_bounds
from syndicate.features.shared.basketball_interval_projection import project_interval


def _rows(n: int = 240):
    pressure, scoring = [], []
    for i in range(n):
        t = i * 10.0
        sign = 1.0 if (i // 5) % 2 == 0 else -1.0
        pressure.append({"clock_seconds": t, "possession_index": i * 0.7,
                         "sign": sign, "weight": 1.0})
        if i % 3 == 0:
            scoring.append({"clock_seconds": t, "sign": sign, "weight": 2.0})
    return pressure, scoring


# ---------------------------------------------------------------------------
# The shrinking horizon
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("t,period,left", [
    (0.0, 1, 600.0), (300.0, 1, 300.0), (599.0, 1, 1.0),
    (600.0, 2, 600.0), (1250.0, 3, 550.0), (2399.0, 4, 1.0),
])
def test_period_bounds_track_the_wnba_clock(t, period, left) -> None:
    p, _, l = period_bounds("wnba", t)
    assert (p, l) == (period, left)


def test_overtime_folds_into_the_last_regulation_period() -> None:
    """A wrong period index is worse than a coarse one. OT is rare and its
    length differs, so it is folded rather than modelled."""
    p, _, left = period_bounds("wnba", 2500.0)
    assert p == 4 and left == 0.0


def test_the_horizon_ends_at_the_buzzer_not_a_fixed_length() -> None:
    """**THE WHOLE POINT.** A fixed 600s horizon spills into the next period at
    every probe after tip; a quarter bet asks for THIS period's final."""
    pressure, scoring = _rows()
    early = project_interval(pressure, scoring, 60.0, league_code="wnba")
    late = project_interval(pressure, scoring, 540.0, league_code="wnba")
    assert early["state_seconds_left_in_period"] == 540.0
    assert late["state_seconds_left_in_period"] == 60.0
    assert late["state_seconds_left_in_period"] < early["state_seconds_left_in_period"]


def test_at_the_buzzer_there_is_nothing_to_project() -> None:
    pressure, scoring = _rows()
    assert project_interval(pressure, scoring, 600.0 * 5, league_code="wnba") is None


# ---------------------------------------------------------------------------
# State and truth
# ---------------------------------------------------------------------------

def test_period_total_counts_only_this_period() -> None:
    """Points from earlier periods must not inflate the current one -- that
    would make a Q3 projection look like a game total."""
    pressure, scoring = _rows()
    row = project_interval(pressure, scoring, 1200.0 + 300.0, league_code="wnba")
    assert row["period"] == 3
    period_start = 1200.0
    expected = sum(abs(r["weight"]) for r in scoring
                   if period_start < r["clock_seconds"] <= 1500.0)
    assert row["state_period_total_so_far"] == pytest.approx(expected)


def test_truth_is_the_rest_of_this_period_only() -> None:
    pressure, scoring = _rows()
    probe = 300.0
    row = project_interval(pressure, scoring, probe, league_code="wnba")
    expected = sum(abs(r["weight"]) for r in scoring
                   if probe < r["clock_seconds"] <= 600.0)
    assert row["true_rest_total"] == pytest.approx(expected)


def test_the_probe_instant_is_state_not_outcome() -> None:
    """Same leak guard as everywhere else: an event AT the probe is what we
    know, and counting it as future makes the projection look prescient."""
    pressure = [{"clock_seconds": 300.0, "possession_index": 20.0, "sign": 1.0, "weight": 1.0}]
    scoring = [{"clock_seconds": 300.0, "sign": 1.0, "weight": 2.0},
               {"clock_seconds": 400.0, "sign": 1.0, "weight": 3.0}]
    row = project_interval(pressure, scoring, 300.0, league_code="wnba")
    assert row["state_period_total_so_far"] == 2.0
    assert row["true_rest_total"] == 3.0


def test_period_final_is_state_plus_rest() -> None:
    pressure, scoring = _rows()
    row = project_interval(pressure, scoring, 420.0, league_code="wnba")
    assert row["true_period_total"] == pytest.approx(
        row["state_period_total_so_far"] + row["true_rest_total"])
    assert row["proj_period_total"] == pytest.approx(
        row["state_period_total_so_far"] + row["proj_rest_total"])


def test_the_projection_shrinks_toward_zero_as_the_buzzer_nears() -> None:
    """Not a claim about accuracy -- a claim about ARITHMETIC. Fewer seconds
    left means fewer possessions left means fewer points available."""
    pressure, scoring = _rows()
    values = [project_interval(pressure, scoring, t, league_code="wnba")["proj_rest_total"]
              for t in (60.0, 300.0, 540.0)]
    assert values[0] > values[1] > values[2]


def test_an_empty_feed_projects_nothing() -> None:
    assert project_interval([], [], 300.0) is None
    assert project_interval(_rows()[0], [], 300.0) is None
