"""Unit tests for `historical_truth.faceoff_segment_effect` — the segment-level (not
season-aggregate) validation of `_faceoff_multipliers`: does winning a real faceoff produce a
real, measurable shot-generation edge in the seconds immediately following that specific draw?
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_segment_effect import (
    compute_post_faceoff_shots,
    summarize_post_faceoff_shots,
)

HOME_ID, AWAY_ID = 13, 16


def _mmss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _faceoff(owner_id, seconds, period=1, situation="1551"):
    return {"typeDescKey": "faceoff", "situationCode": situation,
            "periodDescriptor": {"number": period}, "timeInPeriod": _mmss(seconds),
            "details": {"eventOwnerTeamId": owner_id}}


def _shot(owner_id, seconds, period=1, situation="1551", kind="shot-on-goal"):
    return {"typeDescKey": kind, "situationCode": situation,
            "periodDescriptor": {"number": period}, "timeInPeriod": _mmss(seconds),
            "details": {"eventOwnerTeamId": owner_id}}


def _payload(plays):
    return {"id": 1, "plays": plays}


def test_shot_by_winner_within_window_counts_as_winner_shot():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(HOME_ID, 5),
    ]), window_seconds=15)
    assert rec.n_faceoffs == 1
    assert rec.winner_shots == 1
    assert rec.other_shots == 0


def test_shot_by_loser_within_window_counts_as_other_shot():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(AWAY_ID, 5),
    ]), window_seconds=15)
    assert rec.winner_shots == 0
    assert rec.other_shots == 1


def test_shot_after_window_is_not_counted():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(HOME_ID, 20),  # outside a 15s window
    ]), window_seconds=15)
    assert rec.winner_shots == 0
    assert rec.other_shots == 0


def test_window_truncates_at_the_next_faceoff_not_double_counted():
    """A shot between two close-together draws must attribute to the SECOND draw's window only,
    not the first's (whose window is truncated to end exactly where the second draw starts)."""
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _faceoff(AWAY_ID, 10),   # second draw only 10s after the first -- truncates draw 1's window
        _shot(HOME_ID, 12),      # 2s after the SECOND draw, not the first
    ]), window_seconds=15)
    assert rec.n_faceoffs == 2
    # The shot at t=12 is after draw 1's truncated window (ends at t=10) so NOT counted there;
    # it's 2s into draw 2's window (AWAY won draw 2), so it's an "other" shot for draw 2.
    assert rec.winner_shots == 0
    assert rec.other_shots == 1


def test_window_seconds_total_reflects_truncation():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _faceoff(AWAY_ID, 10),
    ]), window_seconds=15)
    # draw 1's window truncates to 10s (ends at draw 2); draw 2's window is the full 15s
    # (nothing truncates it in this fixture).
    assert rec.window_seconds_total == pytest.approx(10.0 + 15.0)


def test_non_ev_faceoff_is_excluded_entirely():
    """A power-play-strength faceoff (unequal skaters) must not be counted as a draw, and must
    not act as a window boundary for a nearby EV draw either."""
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0, situation="1551"),
        _faceoff(AWAY_ID, 5, situation="1451"),   # PP-strength -- excluded
        _shot(HOME_ID, 8, situation="1551"),
    ]), window_seconds=15)
    assert rec.n_faceoffs == 1  # only the EV draw counts
    assert rec.winner_shots == 1  # the shot at t=8 still falls in draw 1's (untruncated) window


def test_non_ev_shot_is_excluded():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(HOME_ID, 5, situation="1451"),  # PP-strength shot -- excluded
    ]), window_seconds=15)
    assert rec.winner_shots == 0
    assert rec.other_shots == 0


def test_window_capped_at_period_end():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 1195),  # 5s left in the period; a 15s window would overrun it
    ]), window_seconds=15)
    assert rec.window_seconds_total == pytest.approx(5.0)


def test_missing_plays_returns_none():
    assert compute_post_faceoff_shots({"id": 1}) is None


def test_not_a_dict_returns_none():
    assert compute_post_faceoff_shots(None) is None


def test_goal_events_count_as_shots():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(HOME_ID, 5, kind="goal"),
    ]), window_seconds=15)
    assert rec.winner_shots == 1


def test_summary_aggregates_across_games():
    recs = [
        compute_post_faceoff_shots(_payload([_faceoff(HOME_ID, 0), _shot(HOME_ID, 5)]), window_seconds=15),
        compute_post_faceoff_shots(_payload([_faceoff(HOME_ID, 0), _shot(AWAY_ID, 5)]), window_seconds=15),
    ]
    summary = summarize_post_faceoff_shots(recs)
    assert summary.n_games == 2
    assert summary.n_faceoffs == 2
    assert summary.winner_shots == 1
    assert summary.other_shots == 1
    assert summary.winner_share == pytest.approx(0.5)


def test_summary_empty_is_zeroed_not_a_crash():
    summary = summarize_post_faceoff_shots([])
    assert summary.n_games == 0
    assert summary.winner_share == 0.0
