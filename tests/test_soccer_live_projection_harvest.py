# -*- coding: utf-8 -*-
"""scripts/soccer_season_audit/harvest_live_projections.py -- H32's evidence capture.

The point of this file: the harvest must be idempotent (same tick twice, one row) and must keep BOTH arms,
because H32 grades the published corners against the sim's kept values from the SAME snapshot. It must also
capture nothing when a date's matches have finished, which is the measured reason the harvest cannot be a
once-a-day job (2026-09-17 22:01:52Z: `games: []` 45 minutes after full time).
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "soccer_season_audit"))

import harvest_live_projections as h  # noqa: E402


def _payload(generated_at="2026-09-18T18:30:00+00:00", games=True, clock="60'"):
    if not games:
        return {"league": "epl", "date": "2026-09-18", "generated_at": generated_at, "games": {}, "match_box": {"1": {"final": True}}}
    return {
        "league": "epl", "date": "2026-09-18", "generated_at": generated_at,
        "games": {"401999001": {
            "event_id": "401999001", "home_team": "Arsenal", "away_team": "Chelsea",
            "status_display_clock": clock, "half": 2, "clock_remaining": 1800.0,
            "score_home": 1, "score_away": 1, "home_corners_so_far": 4, "away_corners_so_far": 3,
            "live_corners": {"basis": "prekickoff_pace_v1", "state": "applied", "share_remaining": 0.373,
                             "pregame_total": 10.2, "so_far": 7, "sim_total": 11.9, "published_total": 10.8},
            "projection": {"corners_basis": "prekickoff_pace_v1", "projected_total_corners": 10.8,
                           "projected_home_corners": 5.9, "projected_away_corners": 4.9,
                           "sim_projected_total_corners": 11.9, "sim_projected_home_corners": 6.4,
                           "sim_projected_away_corners": 5.5, "projected_final_total": 2.8},
        }},
    }


def test_a_snapshot_keeps_both_arms_and_the_audit():
    rows = h.snapshot_rows(_payload())
    assert len(rows) == 1
    row = rows[0]
    assert row["league"] == "epl" and row["event_id"] == "401999001"
    assert row["projected_total_corners"] == 10.8 and row["sim_projected_total_corners"] == 11.9
    assert row["live_corners"]["state"] == "applied"
    assert row["home_corners_so_far"] == 4 and row["clock_remaining"] == 1800.0
    assert row["projected_final_total"] == 2.8          # the goals arm H30 said to leave alone


def test_the_same_tick_twice_appends_once_and_a_new_tick_appends(tmp_path):
    path = tmp_path / "live_projections_2026-09-18.jsonl"
    rows = h.snapshot_rows(_payload())
    assert h.append_rows(path, rows) == 1
    assert h.append_rows(path, rows) == 0                                  # idempotent on re-run
    later = h.snapshot_rows(_payload(generated_at="2026-09-18T18:45:00+00:00", clock="75'"))
    assert h.append_rows(path, later) == 1
    lines = [json.loads(l) for l in io.open(path, encoding="utf-8").read().splitlines()]
    assert len(lines) == 2
    assert {l["generated_at"] for l in lines} == {"2026-09-18T18:30:00+00:00", "2026-09-18T18:45:00+00:00"}


def test_a_finished_date_yields_no_rows_which_is_why_this_is_not_a_daily_job():
    assert h.snapshot_rows(_payload(games=False)) == []


def test_a_half_written_last_line_does_not_lose_the_file(tmp_path):
    path = tmp_path / "live_projections_2026-09-18.jsonl"
    h.append_rows(path, h.snapshot_rows(_payload()))
    with io.open(path, "a", encoding="utf-8") as handle:
        handle.write('{"league": "epl", "event_id": "trunc')       # a crash mid-write
    assert h.append_rows(path, h.snapshot_rows(_payload())) == 0    # the good row is still recognised
    later = h.snapshot_rows(_payload(generated_at="2026-09-18T19:00:00+00:00"))
    assert h.append_rows(path, later) == 1


def test_default_dates_cover_the_utc_rollover():
    dates = h.default_dates()
    assert len(dates) == 2 and dates[0] < dates[1]
