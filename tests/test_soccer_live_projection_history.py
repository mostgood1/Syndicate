# -*- coding: utf-8 -*-
"""syndicate/features/soccer/features/live_projection_history.py -- the durable capture for H32.

The load-bearing test is `test_a_finished_match_keeps_its_rows_after_it_leaves_games`: the whole reason this
exists is that `games` drops a match minutes after full time and the old artifact kept nothing (measured
2026-09-17 22:01:52Z, `games: []` with two completed matches).
"""
import pytest

from syndicate.features.soccer.features import live_projection_history as hist


def _game(total=10.8, sim=11.9, clock="60'", state="applied"):
    return {
        "status_display_clock": clock, "half": 2, "clock_remaining": 1800.0,
        "score_home": 1, "score_away": 1, "home_corners_so_far": 4, "away_corners_so_far": 3,
        "home_shots_so_far": 11, "away_shots_so_far": 6,
        "home_shots_on_target_so_far": 5, "away_shots_on_target_so_far": 2,
        "live_corners": {"state": state, "share_remaining": 0.373, "pregame_total": 10.2},
        "projection": {"corners_basis": "prekickoff_pace_v1", "projected_total_corners": total,
                       "projected_home_corners": 5.9, "projected_away_corners": 4.9,
                       "sim_projected_total_corners": sim, "sim_projected_home_corners": 6.4,
                       "sim_projected_away_corners": 5.5, "projected_final_total": 2.8},
    }


def test_a_row_carries_both_arms_the_clock_and_the_audit_state():
    row = hist.history_row(_game(), "2026-09-18T18:30:00+00:00")
    assert row["generated_at"] == "2026-09-18T18:30:00+00:00"
    assert row["projected_total_corners"] == 10.8 and row["sim_projected_total_corners"] == 11.9
    assert row["corners_basis"] == "prekickoff_pace_v1" and row["live_corners_state"] == "applied"
    assert row["home_corners_so_far"] == 4 and row["status_display_clock"] == "60'"
    assert row["projected_final_total"] == 2.8
    assert row["share_remaining"] == 0.373 and row["pregame_total"] == 10.2


def test_successive_ticks_accumulate():
    first = hist.merge_history(None, {"m1": _game(total=10.8)}, "2026-09-18T18:30:00+00:00")
    second = hist.merge_history(first, {"m1": _game(total=10.4, clock="75'")}, "2026-09-18T18:45:00+00:00")
    assert [r["projected_total_corners"] for r in second["m1"]] == [10.8, 10.4]
    assert [r["status_display_clock"] for r in second["m1"]] == ["60'", "75'"]


def test_a_finished_match_keeps_its_rows_after_it_leaves_games():
    earlier = hist.merge_history(None, {"finished": _game(), "ongoing": _game()}, "2026-09-18T18:30:00+00:00")
    later = hist.merge_history(earlier, {"ongoing": _game(clock="80'")}, "2026-09-18T19:30:00+00:00")
    assert len(later["finished"]) == 1                      # kept, though it is no longer in play
    assert len(later["ongoing"]) == 2


def test_the_same_tick_twice_does_not_duplicate_a_row():
    once = hist.merge_history(None, {"m1": _game()}, "2026-09-18T18:30:00+00:00")
    twice = hist.merge_history(once, {"m1": _game()}, "2026-09-18T18:30:00+00:00")
    assert len(twice["m1"]) == 1


def test_the_cap_drops_the_oldest_rows():
    history = None
    for minute in range(10):
        history = hist.merge_history(history, {"m1": _game(total=minute)}, f"2026-09-18T18:{minute:02d}:00+00:00", max_rows=4)
    assert len(history["m1"]) == 4
    assert [r["projected_total_corners"] for r in history["m1"]] == [6, 7, 8, 9]


def test_prior_rows_survive_a_cap_change_and_junk_is_dropped():
    previous = {"m1": [{"generated_at": "x"}, "not a row", 7], "m2": "not a list"}
    merged = hist.merge_history(previous, {}, "2026-09-18T18:30:00+00:00")
    assert merged["m1"] == [{"generated_at": "x"}]
    assert "m2" not in merged


@pytest.mark.parametrize("payload,expected", [
    ({"projection_history": {"m": []}}, {"m": []}),
    ({"projection_history": "nonsense"}, None),
    ({}, None),
    ("not a payload", None),
])
def test_history_from_payload_is_defensive(payload, expected):
    assert hist.history_from_payload(payload) == expected


def test_a_row_carries_the_shot_counts_for_the_lane_that_asked_for_them():
    """`soccer-shot-on-target-definition` needs these per tick: at full time the served box drops to rows: []
    (measured 21:28:49Z), so the counts are unreadable within the hour. On-target is a LOWER BOUND on ESPN's
    figure (exact on 39 of 48 team-matches, short on 9, never over) and must not be read as the box score."""
    row = hist.history_row(_game(), "2026-09-18T18:30:00+00:00")
    assert row["home_shots_so_far"] == 11 and row["away_shots_so_far"] == 6
    assert row["home_shots_on_target_so_far"] == 5 and row["away_shots_on_target_so_far"] == 2


def test_a_game_missing_the_shot_fields_still_produces_a_row():
    sparse = {"status_display_clock": "45'", "projection": {"corners_basis": "sim"}}
    row = hist.history_row(sparse, "2026-09-18T18:30:00+00:00")
    assert row["home_shots_so_far"] is None and row["corners_basis"] == "sim"
