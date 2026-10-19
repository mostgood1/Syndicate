"""The NBA fetch-schedule writes the season in play (lane nba-schedule-current-season, user request 2026-10-14).

cdn.nba.com answers 403 to this host, so the vendored command always took the local fallback and rewrote the previous
season's schedule_2025_26.* (fleet: 2024-10-22..2026-04-12, empty statuses). The port (EDITS in
scripts/port_basketball_source_cli.py) now:
  * falls back to stats.nba.com ScheduleLeagueV2 for the current season, rebuilt into the CDN payload shape;
  * writes schedule_<season>.{csv,json} as well as the schedule_2025_26.* alias the vendored readers open by name;
  * filters a day on date_est (the ET game date) -- the vendored date_utc-first order returned day D+1's games
    (fleet A/B: predict-date 10-20 built an 11-game slate, none of the opener's 3).
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _stats_frame():
    rows = []
    for gid, day, utc_day, status, label, home, away in (
        ("0012600009", "2026-10-03", "2026-10-03", 3, "Preseason", "LAL", "GSW"),
        ("0022600001", "2026-10-20", "2026-10-20", 1, "", "DET", "BOS"),
        ("0022600004", "2026-10-21", "2026-10-21", 1, "", "MIA", "MIN"),
    ):
        rows.append({
            "leagueId": "00", "seasonYear": "2026-27", "gameDate": f"{day[5:7]}/{day[8:]}/{day[:4]} 00:00:00", "gameId": gid,
            "gameStatus": status, "gameStatusText": "Final" if status == 3 else "7:00 pm ET",
            "gameDateEst": f"{day}T00:00:00Z", "gameTimeEst": "1900-01-01T19:00:00Z", "gameDateTimeEst": f"{day}T19:00:00Z",
            "gameDateUTC": f"{utc_day}T04:00:00Z", "gameTimeUTC": "1900-01-01T23:00:00Z", "gameDateTimeUTC": f"{day}T23:00:00Z",
            "gameLabel": label, "gameSubtype": "", "arenaName": "Arena", "arenaCity": "City", "arenaState": "ST",
            "homeTeam_teamId": 1, "homeTeam_teamTricode": home, "homeTeam_teamCity": "Home", "homeTeam_teamName": "Team",
            "awayTeam_teamId": 2, "awayTeam_teamTricode": away, "awayTeam_teamCity": "Away", "awayTeam_teamName": "Team",
            "nationalBroadcasters_0_broadcasterDisplay": "NBC",
        })
    return pd.DataFrame(rows)


@pytest.fixture()
def schedule_mod(monkeypatch):
    from syndicate.features.nba.source_cli import schedule

    calls = []

    class FakeEndpoint:
        def __init__(self, league_id, season, timeout):
            calls.append(season)

        def get_data_frames(self):
            return [_stats_frame()]

    fake = types.ModuleType("nba_api.stats.endpoints.scheduleleaguev2")
    fake.ScheduleLeagueV2 = FakeEndpoint
    monkeypatch.setitem(sys.modules, "nba_api.stats.endpoints.scheduleleaguev2", fake)
    monkeypatch.setattr(schedule, "_STATS_SCHEDULE_CACHE", {})
    monkeypatch.setattr(schedule, "_request_schedule_payload", lambda: (_ for _ in ()).throw(RuntimeError("403")))
    monkeypatch.setattr(schedule, "_load_local_schedule_fallback", lambda *a, **k: pytest.fail("the local fallback must not run"))
    schedule._test_calls = calls
    return schedule


def test_current_season():
    from syndicate.features.nba.source_cli.schedule import _current_nba_season

    assert _current_nba_season(dt.date(2026, 10, 14)) == "2026-27"
    assert _current_nba_season(dt.date(2027, 3, 1)) == "2026-27"
    assert _current_nba_season(dt.date(2027, 7, 1)) == "2027-28"


def test_a_cdn_refusal_falls_back_to_stats_nba_for_the_current_season(schedule_mod):
    df = schedule_mod.fetch_schedule_2025_26()
    assert schedule_mod._test_calls == [schedule_mod._current_nba_season()]
    assert set(df["season_year"]) == {"2026-27"} and len(df) == 3
    opener = df[df["game_id"] == "0022600001"].iloc[0]
    assert (opener["home_tricode"], opener["away_tricode"], str(opener["date_est"])) == ("DET", "BOS", "2026-10-20")
    assert opener["broadcasters_national"] == "NBC"
    assert sorted(df["game_status"].tolist()) == [1, 1, 3]
    schedule_mod.fetch_schedule_2025_26()
    assert len(schedule_mod._test_calls) == 1  # one stats request per process


def test_fetch_schedule_writes_the_season_name_and_the_alias(schedule_mod, tmp_path, monkeypatch):
    from click.testing import CliRunner
    from syndicate.features.nba.source_cli import cli

    monkeypatch.setattr(cli, "paths", types.SimpleNamespace(data_processed=tmp_path))
    monkeypatch.setattr(cli, "fetch_schedule_2025_26", schedule_mod.fetch_schedule_2025_26)
    result = CliRunner().invoke(cli.cli, ["fetch-schedule"])
    assert result.exit_code == 0, result.output
    for name in ("schedule_2026_27.csv", "schedule_2026_27.json", "schedule_2025_26.csv", "schedule_2025_26.json"):
        assert (tmp_path / name).is_file(), name
    alias = json.loads((tmp_path / "schedule_2025_26.json").read_text(encoding="utf-8"))
    assert {g["game_id"] for g in alias} == {"0012600009", "0022600001", "0022600004"}
    assert pd.read_csv(tmp_path / "schedule_2026_27.csv", dtype=str)["season_year"].unique().tolist() == ["2026-27"]


def test_a_day_is_the_et_game_date_not_the_next_one(schedule_mod, monkeypatch):
    from syndicate.features.nba.source_cli import cli

    monkeypatch.setattr(cli, "fetch_schedule_2025_26", schedule_mod.fetch_schedule_2025_26)
    day = cli._load_schedule_day("2026-10-20")
    assert day["game_id"].tolist() == ["0022600001"]
