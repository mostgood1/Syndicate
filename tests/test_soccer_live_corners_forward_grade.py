# -*- coding: utf-8 -*-
"""scripts/soccer_season_audit/live_corners_forward_grade.py -- H32's grader.

The end-to-end test runs first: a synthetic harvest plus ESPN finals must come out graded, with the funnel
showing every stage. A grader whose join silently produces zero is the failure this file exists to catch.
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "soccer_season_audit"))

import live_corners_forward_grade as g  # noqa: E402

TODAY = dt.date(2026, 9, 20)


def _row(event, minute, published, sim, generated_at, basis=g.LIVE_BASIS, league="epl", state="applied", source="history"):
    half = 1 if minute < 45 else 2
    remaining = (45 - minute) * 60.0 if half == 1 else (90 - minute) * 60.0
    row = {"league": league, "event_id": event, "generated_at": generated_at, "half": half, "clock_remaining": remaining,
           "corners_basis": basis, "projected_total_corners": published, "sim_projected_total_corners": sim}
    if source == "history":
        row["live_corners_state"] = state
    else:
        row["live_corners"] = {"state": state}
    return row


def _espn(home_corners, away_corners, completed=True):
    return {
        "header": {"competitions": [{
            "date": "2026-09-19T14:00Z",
            "status": {"type": {"name": "STATUS_FULL_TIME" if completed else "STATUS_POSTPONED", "completed": completed}},
            "competitors": [{"homeAway": "home", "score": "1", "team": {"id": "1", "displayName": "Home"}},
                            {"homeAway": "away", "score": "0", "team": {"id": "2", "displayName": "Away"}}]}]},
        "boxscore": {"teams": [
            {"team": {"id": "1"}, "statistics": [{"name": "wonCorners", "displayValue": str(home_corners)}]},
            {"team": {"id": "2"}, "statistics": [{"name": "wonCorners", "displayValue": str(away_corners)}]}]},
        "rosters": [],
    }


def _write(tmp_path, rows, finals):
    harvest, cache = tmp_path / "harvest", tmp_path / "cache"
    harvest.mkdir()
    (cache / "espn").mkdir(parents=True)
    with open(harvest / "live_projections_2026-09-19.jsonl", "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    for (league, event), (hc, ac) in finals.items():
        (cache / "espn" / f"{league}__{event}.json").write_text(json.dumps(_espn(hc, ac)), encoding="utf-8")
    return harvest, cache


# ---------------------------------------------------------------------------- end to end first

def test_a_harvest_with_finals_is_graded_through_every_stage(tmp_path):
    rows = [
        _row("m1", 25, 10.0, 12.0, "t1"), _row("m1", 35, 10.2, 12.5, "t2"),      # 20-40: the LATER one counts
        _row("m1", 50, 10.4, 12.0, "t3"), _row("m1", 70, 10.6, 11.5, "t4"),
        _row("m2", 30, 9.0, 8.0, "t5"),
    ]
    harvest, cache = _write(tmp_path, rows, {("epl", "m1"): (6, 4), ("epl", "m2"): (5, 4)})
    report = g.grade(harvest, cache, TODAY)
    assert report["funnel"]["snapshots"] == 5 and report["funnel"]["eligible"] == 5
    assert report["funnel"]["matches_graded"] == 2
    assert report["matches"] == 2 and report["snapshots_graded"] == 4       # m1 x3 buckets + m2 x1
    # m1 final 10: published errors 0.2/0.4/0.6 against sim 2.5/2.0/1.5, so published is better there
    assert report["per_bucket"]["20-40"]["n"] == 2
    assert report["verdict"] == "WATCHING"                                  # 2 matches, before 11-15


def test_a_match_without_an_espn_final_is_not_graded(tmp_path):
    harvest, cache = _write(tmp_path, [_row("m1", 30, 10.0, 12.0, "t1")], {})
    report = g.grade(harvest, cache, TODAY)
    assert report["funnel"]["matches_with_an_eligible_snapshot"] == 1
    assert report["funnel"].get("matches_graded", 0) == 0 and report["matches"] == 0


# ---------------------------------------------------------------------------- population rules

def test_only_the_new_basis_with_a_kept_sim_value_is_eligible():
    rows = [_row("a", 30, 10.0, 12.0, "t1", basis="sim"),
            _row("b", 30, 10.0, None, "t1"),
            _row("c", 30, 10.0, 12.0, "t1")]
    chosen, funnel = g.pick_snapshots(rows)
    assert list(chosen) == [("epl", "c")] and funnel["eligible"] == 1


def test_the_last_snapshot_in_each_bucket_wins_and_out_of_window_minutes_are_ignored():
    rows = [_row("m", 10, 1.0, 1.0, "t0"),                  # before 20': no bucket
            _row("m", 21, 2.0, 2.0, "t1"), _row("m", 39, 3.0, 3.0, "t2"),
            _row("m", 85, 9.0, 9.0, "t9")]                  # after 80': no bucket
    chosen, funnel = g.pick_snapshots(rows)
    assert chosen[("epl", "m")][(20.0, 40.0)]["projected_total_corners"] == 3.0
    assert set(chosen[("epl", "m")]) == {(20.0, 40.0)}
    assert funnel["in_a_bucket"] == 2


@pytest.mark.parametrize("minute,bucket", [(19.99, None), (20.0, (20.0, 40.0)), (40.0, (40.0, 60.0)),
                                           (79.9, (60.0, 80.0)), (80.0, (60.0, 80.0)), (80.5, None)])
def test_bucket_edges(minute, bucket):
    assert g.bucket_of(minute) == bucket


def test_elapsed_minutes_reads_half_and_clock():
    assert g.elapsed_minutes({"half": 1, "clock_remaining": 15 * 60}) == pytest.approx(30.0)
    assert g.elapsed_minutes({"half": 2, "clock_remaining": 30 * 60}) == pytest.approx(60.0)
    assert g.elapsed_minutes({"half": None}) is None


def test_the_audit_state_is_read_from_either_row_shape_and_reported():
    rows = [_row("m", 30, 10.0, 12.0, "t1", state="no_pregame_estimate", source="live"),
            _row("n", 30, 10.0, 12.0, "t1", state="applied", source="history")]
    _, funnel = g.pick_snapshots(rows)
    assert funnel["audit_no_pregame_estimate"] == 1


# ---------------------------------------------------------------------------- verdict

@pytest.mark.parametrize("n,hi,today,expected", [
    (99, -0.5, dt.date(2026, 11, 14), "WATCHING"),
    (99, -0.5, dt.date(2026, 11, 15), "INSUFFICIENT"),
    (100, -0.01, dt.date(2026, 10, 1), "MET"),
    (100, 0.0, dt.date(2026, 10, 1), "FALSIFIED"),            # a CI touching zero is not MET
    (100, float("nan"), dt.date(2026, 10, 1), "FALSIFIED"),
])
def test_verdict(n, hi, today, expected):
    assert g.verdict(n, hi, today) == expected


def test_the_bootstrap_clusters_by_match():
    point, (lo, hi) = g.paired_boot([[-1.0, -1.0, -1.0]] * 10)
    assert point == pytest.approx(-1.0) and lo == pytest.approx(-1.0) and hi == pytest.approx(-1.0)
