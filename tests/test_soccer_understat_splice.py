"""The Understat-outage splice: goals-as-xG rows for big-5 matches the frozen Understat history does not hold.

Lane `understat-fallback-backtest` (2026-11-18). `SYNDICATE_SOCCER_UNDERSTAT_SPLICE` is OFF unless "1"/"true"/
"on"/"yes" (a betting change: it loads only in a betting-change window). The reachability test (off != on, through
the REAL `_load_team_ratings`) comes first, per the model engine standard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import build_soccer_artifacts as bsa

ENV = "SYNDICATE_SOCCER_UNDERSTAT_SPLICE"


def _understat_rows() -> list[dict]:
    rows = []
    # Two seasons of Understat rows; the newest ends 2026-10-31 (the outage).
    for i, day in enumerate(("2026-10-04", "2026-10-18", "2026-10-31")):
        rows += [
            {"league": "epl", "season": 2026, "team": "Manchester United", "match_index": i, "date": f"{day} 15:00:00",
             "home_away": "h", "xg_for": 1.0, "xg_against": 1.0, "ppda": 10.0, "goals_for": 1.0, "goals_against": 1.0, "points": 1.0},
            {"league": "epl", "season": 2026, "team": "Wolverhampton Wanderers", "match_index": i, "date": f"{day} 15:00:00",
             "home_away": "a", "xg_for": 1.0, "xg_against": 1.0, "ppda": 12.0, "goals_for": 1.0, "goals_against": 1.0, "points": 1.0},
        ]
    return rows


def _schedule(matches: list[dict]) -> dict:
    return {"league": "epl", "season": 2026, "matches": matches}


def _match(day: str, home: str, away: str, hs: str | None, as_: str | None, state: str = "post") -> dict:
    return {"event_id": f"{day}{home}", "date": f"{day}T15:00Z", "home_team": home, "away_team": away,
            "home_score": hs, "away_score": as_, "status_state": state}


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    th = tmp_path / "epl" / "team_history"
    th.mkdir(parents=True)
    pd.DataFrame(_understat_rows()).to_csv(th / "teams_2026.csv", index=False)
    sched = tmp_path / "epl" / "api" / "schedule"
    sched.mkdir(parents=True)
    (sched / "schedule_2026.json").write_text(json.dumps(_schedule([
        _match("2026-10-31", "Manchester United", "Wolves", "1", "1"),          # already in Understat -> covered
        _match("2026-11-08", "Man United", "Wolves", "4", "0"),                 # the outage: spliced
        _match("2026-11-22", "Wolves", "Man United", None, None, state="pre"),  # not played -> never spliced
        _match("2026-11-09", "Nonexistent FC", "Wolves", "2", "2"),            # unresolvable club -> skipped
    ])), encoding="utf-8")
    return tmp_path


def _ratings(root: Path, monkeypatch, value: str | None, as_of: str = "2026-11-20") -> dict:
    if value is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, value)
    monkeypatch.delenv("SYNDICATE_SOCCER_RATING_V2", raising=False)
    return bsa._load_team_ratings("epl", root, as_of)


def test_reachability_off_is_not_on(root, monkeypatch):
    """off != on through the real loader -- the check that catches an inert switch."""
    off = _ratings(root, monkeypatch, None)
    on = _ratings(root, monkeypatch, "1")
    assert off != on
    assert on["Manchester United"]["matches"] == off["Manchester United"]["matches"] + 1
    assert on["Manchester United"]["attack_rating"] > off["Manchester United"]["attack_rating"]
    assert on["Wolverhampton Wanderers"]["defense_rating"] < off["Wolverhampton Wanderers"]["defense_rating"]


@pytest.mark.parametrize("value", [None, "", "0", "off", "false", "no", "garbage"])
def test_absent_or_falsy_is_todays_code(root, monkeypatch, value):
    rows = pd.read_csv(root / "epl" / "team_history" / "teams_2026.csv").to_dict("records")
    expected = bsa.compute_team_ratings(rows, as_of="2026-11-20", window=45)
    assert _ratings(root, monkeypatch, value) == expected


@pytest.mark.parametrize("value", ["1", "true", "on", "yes", " ON "])
def test_truthy_values_switch_it_on(root, monkeypatch, value):
    assert _ratings(root, monkeypatch, value)["Manchester United"]["matches"] == 4.0


def test_spliced_rows_carry_only_the_understat_field_set(root):
    rows = pd.read_csv(root / "epl" / "team_history" / "teams_2026.csv").to_dict("records")
    spliced = bsa._understat_splice_rows("epl", root, rows, "2026-11-20")
    assert len(spliced) == 2  # one match, one row per club
    for row in spliced:
        assert set(row) == {"league", "season", "team", "date", "home_away", "xg_for", "xg_against",
                            "goals_for", "goals_against", "points", "source"}
        assert row["source"] == "espn_goals_splice"
    by_team = {r["team"]: r for r in spliced}
    # ESPN names resolve to Understat's through production's matcher.
    assert by_team["Manchester United"]["xg_for"] == 4.0 and by_team["Manchester United"]["points"] == 3.0
    assert by_team["Wolverhampton Wanderers"]["xg_against"] == 4.0 and by_team["Wolverhampton Wanderers"]["points"] == 0.0


def test_no_new_metric_reaches_the_engine(root, monkeypatch):
    """Shots/corners/possession must not appear: they would be a new mechanism, measured on nothing."""
    on = _ratings(root, monkeypatch, "1")
    for key in ("shots_per_match", "shots_allowed_per_match", "corners_per_match", "possession_share", "clean_sheet_rate"):
        assert key not in on["Manchester United"]
    # ppda stays the Understat rows' mean (spliced rows carry none).
    assert on["Manchester United"]["ppda"] == 10.0


def test_a_match_understat_already_holds_is_not_spliced_twice(root):
    rows = pd.read_csv(root / "epl" / "team_history" / "teams_2026.csv").to_dict("records")
    days = {r["date"] for r in bsa._understat_splice_rows("epl", root, rows, "2026-11-20")}
    assert days == {"2026-11-08"}


def test_nothing_on_or_after_the_build_date_is_spliced(root):
    rows = pd.read_csv(root / "epl" / "team_history" / "teams_2026.csv").to_dict("records")
    assert bsa._understat_splice_rows("epl", root, rows, "2026-11-08") == []


def test_when_understat_returns_the_splice_adds_nothing(root):
    rows = pd.read_csv(root / "epl" / "team_history" / "teams_2026.csv").to_dict("records")
    rows += [
        {"league": "epl", "season": 2026, "team": "Manchester United", "date": "2026-11-08 15:00:00", "home_away": "h",
         "xg_for": 2.5, "xg_against": 0.4, "ppda": 9.0, "goals_for": 4.0, "goals_against": 0.0, "points": 3.0},
        {"league": "epl", "season": 2026, "team": "Wolverhampton Wanderers", "date": "2026-11-08 15:00:00", "home_away": "a",
         "xg_for": 0.4, "xg_against": 2.5, "ppda": 14.0, "goals_for": 0.0, "goals_against": 4.0, "points": 0.0},
    ]
    assert bsa._understat_splice_rows("epl", root, rows, "2026-11-20") == []


def test_a_missing_schedule_is_a_no_op(tmp_path, monkeypatch):
    th = tmp_path / "epl" / "team_history"
    th.mkdir(parents=True)
    pd.DataFrame(_understat_rows()).to_csv(th / "teams_2026.csv", index=False)
    assert _ratings(tmp_path, monkeypatch, "1") == _ratings(tmp_path, monkeypatch, None)


def test_goals_rated_leagues_ignore_the_switch(tmp_path, monkeypatch):
    hist = tmp_path / "eredivisie" / "history"
    hist.mkdir(parents=True)
    pd.DataFrame([
        {"league": "eredivisie", "season": 2026, "match_id": "x", "date": "01/10/2026", "home_team": "Ajax",
         "away_team": "PSV", "home_goals": 2, "away_goals": 1},
    ]).to_csv(hist / "matches_2026.csv", index=False)
    monkeypatch.setenv(ENV, "1")
    on = bsa._load_team_ratings("eredivisie", tmp_path, "2026-11-20")
    monkeypatch.delenv(ENV)
    assert on == bsa._load_team_ratings("eredivisie", tmp_path, "2026-11-20")
