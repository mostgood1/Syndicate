"""Soccer player match log: producer rows + the prop-evidence merge (lane intelligence-evidence-coverage, 2026-10-08)."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_soccer_player_match_log", Path(__file__).resolve().parents[1] / "scripts" / "build_soccer_player_match_log.py"
)
log = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(log)


def test_match_rows_keep_players_who_entered_with_date_and_opponent(monkeypatch):
    import syndicate.features.soccer.ingestion.espn_lineups as L
    import syndicate.features.soccer.ingestion.espn_match_events as E

    rows = [
        {"team": "Arsenal", "side": "home", "player_id": "1", "player_name": "Bukayo Saka", "position": "F", "starter": True,
         "total_shots": 3.0, "shots_on_target": 1.0, "total_goals": 1.0, "goal_assists": 0.0},
        {"team": "Arsenal", "side": "home", "player_id": "2", "player_name": "Unused Sub", "position": "M", "starter": False,
         "total_shots": 0.0, "shots_on_target": 0.0, "total_goals": 0.0, "goal_assists": 0.0},
        {"team": "Coventry City", "side": "away", "player_id": "3", "player_name": "Away Guy", "position": "D", "starter": True,
         "total_shots": 1.0, "shots_on_target": 0.0, "total_goals": 0.0, "goal_assists": 0.0},
    ]
    monkeypatch.setattr(L, "extract_match_player_rows", lambda summary, event_id: rows)
    monkeypatch.setattr(E, "extract_key_events", lambda summary: [])
    monkeypatch.setattr(E, "compute_minutes_played", lambda events, rows: {"1": 67.3, "3": 90.0})
    out = log.match_rows("epl", 2026, {"event_id": "9", "date": "2026-08-21T19:00Z"}, {})
    assert [(r["player_name"], r["opponent"], r["date"], r["minutes"]) for r in out] == [
        ("Bukayo Saka", "Coventry City", "2026-08-21", 67.3), ("Away Guy", "Arsenal", "2026-08-21", 90.0)]


def _write_log(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=log.FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in log.FIELDS})


def test_merge_adds_log_games_before_the_match_only_and_keeps_live_boxes(tmp_path, monkeypatch):
    from syndicate.features.shared.prop_evidence import soccer as S
    from syndicate.features.shared.prop_evidence.contract import PropSubject

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    base = {"league": "epl", "season": 2026, "team": "Arsenal", "side": "home", "player_id": "1", "player_name": "Bukayo Saka",
            "starter": 1, "minutes": 90, "shots_on_target": 1}
    _write_log(tmp_path / "soccer_source" / "epl" / "history" / "player_match_log_2026.csv", [
        dict(base, date="2026-08-21", event_id="a", opponent="Coventry City"),
        dict(base, date="2026-09-01", event_id="b", opponent="Chelsea", shots_on_target=0),
        dict(base, date="2026-09-20", event_id="c", opponent="Chelsea", shots_on_target=2),  # also in a live box
        dict(base, date="2026-10-04", event_id="d", opponent="Chelsea", shots_on_target=3),  # the match itself: excluded
        dict(base, date="2026-08-30", event_id="e", player_id="77", team="Fulham", opponent="Leeds"),  # namesake elsewhere
    ])
    ctx = S.Resolved(league="epl", match_date="2026-10-04", team="Arsenal", opponent="Chelsea",
                     entry={"player_name": "Bukayo Saka"})
    subject = PropSubject.from_board_row({"sport": "soccer", "kind": "prop", "player_name": "Bukayo Saka",
                                          "market": "player_shots_on_target", "line": 0.5, "side": "over",
                                          "home_team": "Arsenal", "away_team": "Chelsea"}, selected_date="2026-10-04")
    live = S.BoxScan(files=1, files_with_player_box=1, appearances=[
        {"date": "2026-09-20", "opponent": "Chelsea", "venue": "home", "shots_on_target": 2.0, "source": "live"}])
    scan = S.merge_match_log(live, ctx, subject)
    assert [g["date"] for g in scan.appearances] == ["2026-09-20", "2026-09-01", "2026-08-21"]
    assert scan.appearances[0]["source"] == "live" and scan.match_log_games == 2
    assert S.merge_match_log(None, ctx, subject).match_log_games == 3  # no live boxes at all: the log stands alone


def test_a_live_boxed_team_date_is_never_filled_from_the_log(tmp_path, monkeypatch):
    """15:31Z 2026-10-08: a log line on a date the live box called 'not in roster' reached _environment and raised."""
    from syndicate.features.shared.prop_evidence import soccer as S
    from syndicate.features.shared.prop_evidence.contract import PropSubject

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    base = {"league": "epl", "season": 2026, "team": "Arsenal", "side": "home", "player_id": "1", "player_name": "Bukayo Saka",
            "starter": 1, "minutes": 90, "shots_on_target": 1}
    _write_log(tmp_path / "soccer_source" / "epl" / "history" / "player_match_log_2026.csv", [
        dict(base, date="2026-09-20", event_id="x", opponent="Chelsea"), dict(base, date="2026-09-01", event_id="y", opponent="Spurs")])
    ctx = S.Resolved(league="epl", match_date="2026-10-04", team="Arsenal", opponent="Chelsea", entry={"player_name": "Bukayo Saka"})
    subject = PropSubject.from_board_row({"sport": "soccer", "kind": "prop", "player_name": "Bukayo Saka",
                                          "market": "player_shots_on_target", "line": 0.5, "side": "over",
                                          "home_team": "Arsenal", "away_team": "Chelsea"}, selected_date="2026-10-04")
    live = S.BoxScan(files=1, files_with_player_box=1, team_matches=[{"date": "2026-09-20", "event_id": "x", "opponent": "Chelsea"}],
                     not_in_roster=[{"date": "2026-09-20", "event_id": "x", "opponent": "Chelsea"}])
    scan = S.merge_match_log(live, ctx, subject)
    assert [g["date"] for g in scan.appearances] == ["2026-09-01"] and scan.appearances[0]["event_id"] == "y"


def test_scan_windows_skip_a_settled_season_and_start_near_the_newest_match():
    import datetime as dt

    today = dt.date(2026, 10, 8)
    logged = [{"date": "2026-09-20"}, {"date": "2026-10-04"}]
    # a finished European season with a file: nothing to walk (it took 1,255 s to re-walk them all on 2026-10-08)
    assert log.windows_to_scan("epl", 2025, logged, today=today, full=False) == []
    # the current season: from three days before the newest logged match, through today
    assert log.windows_to_scan("epl", 2026, logged, today=today, full=False) == ["20261001-20261008"]
    # --full, or a first run with no file, walks the whole season to date
    assert log.windows_to_scan("epl", 2025, logged, today=today, full=True)[0] == "20250801-20250815"
    assert log.windows_to_scan("epl", 2026, [], today=today, full=False)[0] == "20260801-20260815"
    # a calendar-year league's season still in progress is never "settled"
    assert log.windows_to_scan("mls", 2026, [{"date": "2026-10-05"}], today=today, full=False) == ["20261002-20261008"]
