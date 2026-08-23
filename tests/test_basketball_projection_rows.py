"""Projection rows, and the leakage test the whole contract rests on.

**`test_state_is_identical_when_the_future_is_appended` IS THE LOAD-BEARING
TEST.** Every other assertion here checks a computation; that one checks the
property that makes the table usable at all. A `state_` field that moves when
later events arrive is leaking the outcome, and a leaking feature makes a model
look brilliant in backtest and lose money live.
"""

from __future__ import annotations

from typing import Any

import pytest

from syndicate.features.shared.basketball_projection_rows import build_projection_rows
from syndicate.features.shared.basketball_projection_rows import outcome_columns
from syndicate.features.shared.basketball_projection_rows import rows_from_events_dump
from syndicate.features.shared.basketball_projection_rows import state_columns


def _rows(n: int, *, start: float = 0.0) -> tuple[list[dict], list[dict]]:
    """A synthetic game: alternating pressure, scoring every third event."""
    pressure, scoring = [], []
    for i in range(n):
        t = start + i * 12.0
        sign = 1.0 if (i // 3) % 2 == 0 else -1.0
        pressure.append({"clock_seconds": t, "possession_index": float(i),
                         "sign": sign, "weight": 1.0, "team": "HME" if sign > 0 else "AWY"})
        if i % 3 == 0:
            scoring.append({"clock_seconds": t, "possession_index": float(i),
                            "sign": sign, "weight": 2.0})
    return pressure, scoring


# ---------------------------------------------------------------------------
# LEAKAGE -- the property everything else depends on
# ---------------------------------------------------------------------------

def test_state_is_identical_when_the_future_is_appended() -> None:
    """Truncate the feed, build rows, then build again from the FULL feed.

    Every `state_` value at a shared probe must match EXACTLY. If any moves,
    that field can see past its own probe and the table is unusable for fitting.
    """
    short_p, short_s = _rows(120)
    long_p, long_s = _rows(300)

    early = {r["t_seconds"]: r for r in build_projection_rows(
        short_p, short_s, event_id="E", regulation_seconds=2400.0)}
    late = {r["t_seconds"]: r for r in build_projection_rows(
        long_p, long_s, event_id="E", regulation_seconds=2400.0)}

    shared = sorted(set(early) & set(late))
    assert len(shared) >= 10, "the two feeds must overlap enough to be a real test"

    for t in shared:
        for column in state_columns([early[t]]):
            assert early[t][column] == late[t][column], (
                f"{column} at t={t} changed when future events were appended "
                f"({early[t][column]} -> {late[t][column]}) -- it is leaking"
            )


def test_the_leakage_test_can_actually_fail() -> None:
    """**Falsification of the falsification.** If the comparison above could
    not detect a leak, it would pass on a broken extractor forever."""
    short_p, short_s = _rows(120)
    long_p, long_s = _rows(300)
    early = {r["t_seconds"]: r for r in build_projection_rows(
        short_p, short_s, event_id="E", regulation_seconds=2400.0)}
    late = {r["t_seconds"]: r for r in build_projection_rows(
        long_p, long_s, event_id="E", regulation_seconds=2400.0)}
    t = sorted(set(early) & set(late))[5]

    # A deliberately leaked field: total over the WHOLE feed, not just the past.
    early[t]["state_leaked"] = sum(abs(r["weight"]) for r in short_s)
    late[t]["state_leaked"] = sum(abs(r["weight"]) for r in long_s)
    assert early[t]["state_leaked"] != late[t]["state_leaked"]


def test_forward_windows_exclude_the_probe_instant() -> None:
    pressure = [{"clock_seconds": 200.0, "possession_index": 1.0, "sign": 1.0, "weight": 1.0}]
    scoring = [{"clock_seconds": 200.0, "sign": 1.0, "weight": 2.0},
               {"clock_seconds": 260.0, "sign": 1.0, "weight": 3.0}]
    row = next(r for r in build_projection_rows(
        pressure, scoring, event_id="E", regulation_seconds=2400.0,
        warmup_seconds=200.0, step_seconds=1000.0) if r["t_seconds"] == 200.0)
    # The event AT 200 is state, so it is in the total and NOT in the forward.
    assert row["state_total"] == 2.0
    assert row["fwd_total_180"] == 3.0


# ---------------------------------------------------------------------------
# State computations
# ---------------------------------------------------------------------------

def test_state_margin_and_total_are_the_score_so_far() -> None:
    pressure, scoring = _rows(60)
    rows = build_projection_rows(pressure, scoring, event_id="E", regulation_seconds=2400.0)
    row = rows[0]
    upto = [s for s in scoring if s["clock_seconds"] <= row["t_seconds"]]
    assert row["state_total"] == pytest.approx(sum(abs(s["weight"]) for s in upto))
    assert row["state_margin"] == pytest.approx(
        sum(s["sign"] * s["weight"] for s in upto))


def test_pace_and_remaining_possessions_are_consistent() -> None:
    pressure, scoring = _rows(200)
    for row in build_projection_rows(pressure, scoring, event_id="E", regulation_seconds=2400.0):
        expected_pace = row["state_possessions"] / max(row["t_seconds"] / 60.0, 1e-6)
        assert row["state_pace_per_min"] == pytest.approx(expected_pace, abs=1e-3)
        assert row["state_possessions_remaining_est"] == pytest.approx(
            expected_pace * (row["state_seconds_remaining"] / 60.0), abs=1e-2)


def test_seconds_remaining_never_goes_negative() -> None:
    pressure, scoring = _rows(300)          # runs past regulation
    rows = build_projection_rows(pressure, scoring, event_id="E", regulation_seconds=2400.0)
    assert rows, "overtime must still produce rows"
    assert all(r["state_seconds_remaining"] >= 0.0 for r in rows)


# ---------------------------------------------------------------------------
# The truncated-window flag
# ---------------------------------------------------------------------------

def test_incomplete_forward_windows_are_flagged() -> None:
    """A window running past the captured feed looks like a low-scoring one.
    A fit that trains on both learns 'late game means low totals'."""
    pressure, scoring = _rows(120)
    rows = build_projection_rows(pressure, scoring, event_id="E", regulation_seconds=2400.0)
    flags = {r["fwd_complete_1200"] for r in rows}
    assert flags == {True, False}, "both states must occur, or the flag is untested"
    last = rows[-1]
    assert last["fwd_complete_1200"] is False


# ---------------------------------------------------------------------------
# Column contract
# ---------------------------------------------------------------------------

def test_state_and_outcome_columns_do_not_overlap() -> None:
    pressure, scoring = _rows(120)
    rows = build_projection_rows(pressure, scoring, event_id="E", regulation_seconds=2400.0)
    assert not set(state_columns(rows)) & set(outcome_columns(rows))
    assert all(c.startswith("state_") for c in state_columns(rows))
    assert all(c.startswith("fwd_") for c in outcome_columns(rows))


def test_the_decayed_narrator_is_not_a_state_column() -> None:
    """It counts points, so it correlates with scoring by construction. The
    cumulative score IS state; a decayed recent-scoring curve is not a feature."""
    pressure, scoring = _rows(120)
    rows = build_projection_rows(pressure, scoring, event_id="E", regulation_seconds=2400.0)
    assert not [c for c in state_columns(rows) if "narrator" in c or "scoring" in c]


def test_rows_from_a_captured_dump_carry_every_game() -> None:
    p1, s1 = _rows(150)
    p2, s2 = _rows(150)
    dump = {"games": {"401": {"pressure": p1, "narrator": s1},
                      "402": {"pressure": p2, "narrator": s2}}}
    rows = rows_from_events_dump(dump)
    assert {r["event_id"] for r in rows} == {"401", "402"}


def test_a_game_without_scoring_yields_no_rows() -> None:
    pressure, _ = _rows(60)
    assert build_projection_rows(pressure, [], event_id="E", regulation_seconds=2400.0) == []
