"""Lane `basketball-native-live-state` (P2): the dated rotation-stints producer and its consolidated tables."""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from scripts import build_basketball_rotation_stints as producer
from scripts import verify_basketball_rotation_stints as verifier
from syndicate.features.shared import artifact_publisher
from tests.basketball_pbp_fixtures import AWAY, HOME, full_nba_game

DAY = dt.date(2026, 1, 15)
TODAY = dt.date(2026, 1, 20)


def _board(*events):
    return {"events": [
        {"id": eid, "season": {"year": 2026, "type": stype},
         "competitions": [{"status": {"type": {"state": state, "completed": state == "post", "name": name}}, "competitors": []}]}
        for eid, state, name, stype in events
    ]}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_NBA_SOURCE_ROOT", raising=False)
    return tmp_path


def _box_minutes():
    return {"h1": 42, "h6": 6, "h2": 24, "h7": 24, "h3": 48, "h4": 48, "h5": 48,
            "a1": 48, "a2": 48, "a3": 48, "a4": 48, "a5": 43, "a6": 5}


def _build(root, *, board=None, summary=None):
    summary = summary or full_nba_game().summary(minutes=_box_minutes(), pf={"h3": 1})
    board = board or _board(("999", "post", "STATUS_FINAL", 2))
    return producer.build_date("nba", DAY, fetch_scoreboard=lambda *_: board, fetch_summary=lambda *_: summary, rate=0, today=TODAY)


def test_build_date_writes_dated_tables_and_checks(root):
    entry = _build(root)
    assert entry["status"] == "done" and entry["games"] == 1 and entry["score_match"] == 1
    base = root / "nba_source" / "data" / "processed" / "rotation_stints"
    for name in ("stints", "player_stints", "games", "player_checks", "pair_minutes"):
        assert (base / f"{name}_2026-01-15.csv").is_file(), name
    assert (base / "play_context_2026-01-15.parquet").is_file()
    stints = pd.read_csv(base / "stints_2026-01-15.csv", dtype={"lineup_player_ids": str})
    # the columns the smart sim's history reader requires, plus the vendored builder's
    assert {"team", "duration_sec", "lineup_player_ids", "date", "start_sec", "end_sec", "period", "game_id", "event_id"} <= set(stints.columns)
    assert set(stints["season_type"]) == {"regular"} and set(stints["team"]) == {"GSW", "NYK"}  # ESPN GS/NY folded
    assert stints.groupby("team")["duration_sec"].sum().to_dict() == {"GSW": 2880.0, "NYK": 2880.0}
    checks = pd.read_csv(base / "player_checks_2026-01-15.csv")
    assert checks["within_1"].all() and (checks["box_pf"] == checks["pbp_pf"]).all()
    assert len(list((root / "nba_source" / "data" / "processed" / "pbp_events" / "2026").glob("999.jsonl.gz"))) == 1


def test_date_with_a_game_in_progress_is_left_incomplete_until_stale(root):
    board = _board(("999", "post", "STATUS_FINAL", 2), ("998", "pre", "STATUS_SCHEDULED", 2))
    assert _build(root, board=board)["status"] == "incomplete"
    later = producer.build_date("nba", DAY, fetch_scoreboard=lambda *_: board, fetch_summary=lambda *_: full_nba_game().summary(),
                                rate=0, today=DAY + dt.timedelta(days=producer.STALE_PENDING_DAYS))
    assert later["status"] == "done" and later["stale_pending"] == 1


def test_game_without_play_by_play_is_reported_not_matched(root):
    summary = full_nba_game().summary()
    summary["plays"] = []
    entry = _build(root, summary=summary)
    assert entry["status"] == "done" and entry["no_plays"] == 1
    report = verifier.grade("nba")
    assert report["no_pbp_n"] == 1 and report["totals"].get("games", 0) == 0


def test_history_parquet_and_phase_tables(root):
    _build(root)
    out = producer.rebuild_history("nba")
    processed = root / "nba_source" / "data" / "processed"
    csv_hist = pd.read_csv(processed / "rotation_stints_history.csv", dtype={"lineup_player_ids": str})
    pq_hist = pd.read_parquet(processed / "rotation_stints_history.parquet")
    assert len(csv_hist) == len(pq_hist) == out["rows"] > 0
    assert out["phase_tables"] == {"rotation_stints_2026_regular.csv": out["rows"]}
    assert (processed / "pair_minutes_history.parquet").is_file() and out["pair_rows"] > 0
    ctx = pd.read_parquet(processed / "play_context_history.parquet")
    assert {"home_lineup_player_ids", "away_lineup_player_ids", "participant1_id", "points_attempted"} <= set(ctx.columns)
    assert ctx["home_lineup_player_ids"].str.count(";").eq(4).all()


def test_rebuild_replaces_a_vendored_parquet_rather_than_appending(root):
    processed = root / "nba_source" / "data" / "processed"
    processed.mkdir(parents=True)
    stale = pd.DataFrame([{"team": "GSW", "start_sec": 0, "end_sec": 100, "duration_sec": 100, "lineup_player_ids": "x;y;z;w;v",
                           "period": 1, "date": "2026-01-15", "game_id": "0022500001", "event_id": "999"}])
    stale.to_parquet(processed / "rotation_stints_history.parquet", index=False)
    _build(root)
    producer.rebuild_history("nba")
    hist = pd.read_parquet(processed / "rotation_stints_history.parquet")
    assert "x;y;z;w;v" not in set(hist["lineup_player_ids"])


def test_incremental_run_skips_done_dates(root, monkeypatch):
    calls = []

    def fake_build(league, day, **kwargs):
        calls.append(day)
        return {"status": "done", "games": 0}

    monkeypatch.setattr(producer, "build_date", fake_build)
    monkeypatch.setattr(producer, "rebuild_history", lambda league: {"rows": 0})
    producer.run_league("nba", seasons=None, start=DAY, end=DAY + dt.timedelta(days=2), full=False, rate=0, max_games=None, today=TODAY)
    producer.run_league("nba", seasons=None, start=DAY, end=DAY + dt.timedelta(days=3), full=False, rate=0, max_games=None, today=TODAY)
    assert calls == [DAY, DAY + dt.timedelta(days=1), DAY + dt.timedelta(days=2), DAY + dt.timedelta(days=3)]


def test_current_season_windows():
    assert producer.current_season("nba", dt.date(2026, 10, 9)) == 2027  # 2026-27 preseason
    assert producer.current_season("nba", dt.date(2026, 8, 1)) == 2026  # offseason: most recent
    assert producer.current_season("wnba", dt.date(2026, 10, 9)) == 2026
    assert producer.current_season("ncaab", dt.date(2026, 10, 9)) == 2026
    assert producer.current_season("ncaab", dt.date(2026, 11, 20)) == 2027


def test_verifier_gates(root):
    _build(root)
    report = verifier.grade("nba")
    assert report["gates"] == {"score_all_match": True, "minutes_within_1_ge_95pct": True}
    assert report["totals"]["player_games"] == len(HOME) + len(AWAY) - 3  # h8, a7, a8: DNP, never on the floor


@pytest.mark.parametrize("path", [
    "nba_source/data/processed/rotation_stints/stints_2026-01-15.csv",
    "wnba_source/data/processed/rotation_stints/play_context_2026-09-01.parquet",
    "ncaab_source/data/processed/rotation_stints_history.parquet",
    "nba_source/data/processed/rotation_stints_2026_regular.csv",
    "nba_source/data/processed/live_state/2026-10-09/401908940.json",
    "nba_source/data/processed/live_state/2026-10-09/401908940.ticks.jsonl",
])
def test_outputs_are_allowlisted(path):
    assert artifact_publisher.is_hot_artifact_relative_path(path)


def test_event_logs_are_export_only():
    path = "nba_source/data/processed/pbp_events/2026/401859967.jsonl.gz"
    assert artifact_publisher.is_export_only_artifact_relative_path(path)
    assert not artifact_publisher.is_hot_artifact_relative_path(path)


def test_scheduled_job_registered():
    from scripts import local_production

    job = next(j for j in local_production.SCHEDULED_JOBS if j.name == "basketball-rotation-stints")
    assert job.argv == ("scripts/build_basketball_rotation_stints.py",) and (job.hour, job.minute) == (11, 45)


def test_vendored_rotations_step_is_gone():
    for name in ("scripts/refresh_nba_oddsapi_props.py", "scripts/refresh_wnba_oddsapi_props.py"):
        text = open(name, encoding="utf-8").read()
        assert '(["update-rotations-espn-history"' not in text, name


def test_module_imports_nothing_vendored():
    import ast

    for name in ("syndicate/features/shared/basketball_pbp.py", "syndicate/features/shared/basketball_live_state.py",
                 "scripts/build_basketball_rotation_stints.py", "scripts/capture_basketball_live_state.py"):
        tree = ast.parse(open(name, encoding="utf-8").read())
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in mods if "vendor" in m or "nba_betting" in m or "wnba_betting" in m], name
