"""The NCAAB in-play odds lane (user 2026-11-02, "Build it now"): NBA's 240 s live
lane for college basketball -- one bulk call for live full-game prices plus half
lines for started games only, launched only while a D1 game is live.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


NOW = dt.datetime(2026, 11, 3, 1, 0, tzinfo=dt.timezone.utc)


class _Adapter:
    def __init__(self, commence: dict[str, dt.datetime]):
        self.commence = commence
        self.calls: list[tuple] = []

    def iter_current_odds_expanded(self, *, markets, date_iso, bookmakers=None):
        self.calls.append(("bulk", markets, date_iso))
        return [{"event_id": eid, "commence_time": ct, "period": "full_game", "market": "totals"} for eid, ct in self.commence.items()]

    def iter_event_odds(self, event_id, *, markets, bookmakers=None, fallback_full_game=True):
        self.calls.append(("event", event_id, markets, fallback_full_game))
        return [{"event_id": event_id, "period": "2h", "market": "totals"}]


def test_in_play_pull_keeps_started_games_only_and_prices_their_halves():
    module = _load("ncaab_odds_inplay", "scripts/refresh_ncaab_odds_history.py")
    adapter = _Adapter({
        "early": NOW - dt.timedelta(minutes=20),    # first half: both halves
        "late": NOW - dt.timedelta(minutes=100),    # second half: h2 only
        "soon": NOW + dt.timedelta(minutes=10),     # not tipped: no row, no call
        "over": NOW - dt.timedelta(hours=4),        # long over: no row, no call
    })
    rows = module._fetch_in_play_rows(adapter=adapter, markets="h2h,spreads,totals,spreads_h1,totals_h1,spreads_h2,totals_h2", bookmakers=None, now=NOW)
    assert adapter.calls[0] == ("bulk", "h2h,spreads,totals", None)
    per_event = {c[1]: c for c in adapter.calls if c[0] == "event"}
    assert set(per_event) == {"early", "late"}
    assert per_event["early"][2] == "spreads_h1,totals_h1,spreads_h2,totals_h2"
    assert per_event["late"][2] == "spreads_h2,totals_h2"
    assert all(c[3] is False for c in per_event.values())
    assert {r["event_id"] for r in rows} == {"early", "late"}


def test_in_play_main_writes_its_own_csv_and_never_the_slate_one(tmp_path, monkeypatch):
    module = _load("ncaab_odds_inplay_main", "scripts/refresh_ncaab_odds_history.py")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "data_root"))
    started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)

    class _Client(_Adapter):
        def __init__(self, region="us", api_key=None):
            super().__init__({"live": started})

    monkeypatch.setattr(module, "_load_source_adapter", lambda root: _Client)
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["x", "--date", "2026-11-02", "--out-dir", str(out), "--in-play-only"])
    assert module.main() == 0
    assert (out / "odds_2026-11-02_inplay.csv").exists()
    assert not (out / "odds_2026-11-02.csv").exists()


def test_scope_turns_the_forced_ncaab_live_run_into_in_play_only(monkeypatch):
    ros = _load("ros_ncaab_inplay", "scripts/refresh_odds_sources.py")
    monkeypatch.delenv("SYNDICATE_NCAAB_IN_PLAY_ONLY", raising=False)
    monkeypatch.delenv("SYNDICATE_NBA_IN_PLAY_ONLY", raising=False)

    def ns(**kw):
        base = {"phase": "live", "force_refresh": True, "force_refresh_sports": "ncaab"}
        base.update(kw)
        return argparse.Namespace(**base)

    assert ros._in_play_only_scope(ns(), "ncaab") is True
    assert ros._in_play_only_scope(ns(phase="pregame"), "ncaab") is False
    assert ros._in_play_only_scope(ns(force_refresh=False), "ncaab") is False   # the shared sweep stays full-slate
    assert ros._in_play_only_scope(ns(), "soccer") is False
    monkeypatch.setenv("SYNDICATE_NCAAB_IN_PLAY_ONLY", "0")
    assert ros._in_play_only_scope(ns(), "ncaab") is False
    step = ros.RefreshStep(name="ncaab_odds_history_snapshot", phases=("live",), cwd=REPO,
                           command=("python", "scripts/refresh_ncaab_odds_history.py", "--date", "2026-11-02"))
    assert "--in-play-only" in ros._step_command_with_mode(step, "fast", force_refresh=True, in_play_only=True)
    assert "--in-play-only" not in ros._step_command_with_mode(step, "fast", force_refresh=False, in_play_only=True)


def _slate(tmp_path, games):
    path = tmp_path / "ncaab_source" / "data" / "scoreboard" / "scoreboard_2026-11-02.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"games": games}), encoding="utf-8")


def test_live_game_count_reads_the_slate(tmp_path, monkeypatch):
    from syndicate.features.ncaab import inplay_lane

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    now = dt.datetime(2026, 11, 2, 20, 0, tzinfo=dt.timezone.utc)
    _slate(tmp_path, [
        {"start_time_utc": "2026-11-02T19:00Z", "live_state": {"in_progress": True}},
        {"start_time_utc": "2026-11-02T19:30Z", "live_state": {"in_progress": False, "final": False}},  # tipped, slate behind
        {"start_time_utc": "2026-11-02T17:00Z", "live_state": {"final": True}},
        {"start_time_utc": "2026-11-02T23:00Z", "live_state": {}},
    ])
    assert inplay_lane.ncaab_live_game_count("2026-11-02", now=now) == 2


def test_launcher_fires_only_with_a_live_game_and_respects_the_interval(tmp_path, monkeypatch):
    from syndicate.features.ncaab import inplay_lane

    monkeypatch.setattr(inplay_lane, "central_today_iso", lambda: "2026-11-02")
    store: dict[str, dict] = {}
    monkeypatch.setattr(inplay_lane, "read_json_file", lambda path: store.get(str(path)))
    monkeypatch.setattr(inplay_lane, "write_json_file", lambda path, payload: store.__setitem__(str(path), payload))
    launches: list[dict] = []
    monkeypatch.setattr(inplay_lane, "launch_refresh_run", lambda **kw: launches.append(kw) or {"runStamp": "r1"})

    monkeypatch.setattr(inplay_lane, "ncaab_live_game_count", lambda d: 0)
    assert inplay_lane.launch_autorun_ncaab_live_refresh() is None and not launches

    monkeypatch.setattr(inplay_lane, "ncaab_live_game_count", lambda d: 3)
    assert inplay_lane.launch_autorun_ncaab_live_refresh()["live_games"] == 3
    assert launches[0]["sports"] == "ncaab" and launches[0]["phase"] == "live"
    assert launches[0]["force_refresh"] is True and launches[0]["force_refresh_sports"] == "ncaab"
    assert launches[0]["lane"] == "live-odds-worker-ncaab-live"
    assert inplay_lane.launch_autorun_ncaab_live_refresh() is None and len(launches) == 1   # inside 240 s

    monkeypatch.setenv("SYNDICATE_ENABLE_NCAAB_LIVE_REFRESH_AUTORUN", "0")
    store.clear()
    assert inplay_lane.launch_autorun_ncaab_live_refresh() is None and len(launches) == 1


def test_contention_keeps_the_old_epoch_so_the_next_tick_retries(monkeypatch):
    from syndicate.features.ncaab import inplay_lane
    from syndicate.features.shared.ops_refresh import RefreshRunRefused

    monkeypatch.setattr(inplay_lane, "central_today_iso", lambda: "2026-11-02")
    monkeypatch.setattr(inplay_lane, "ncaab_live_game_count", lambda d: 1)
    store: dict[str, dict] = {}
    monkeypatch.setattr(inplay_lane, "read_json_file", lambda path: store.get(str(path)))
    monkeypatch.setattr(inplay_lane, "write_json_file", lambda path, payload: store.__setitem__(str(path), payload))

    def refuse(**kw):
        raise RefreshRunRefused("a refresh run is already active")

    monkeypatch.setattr(inplay_lane, "launch_refresh_run", refuse)
    assert inplay_lane.launch_autorun_ncaab_live_refresh() is None
    status = next(iter(store.values()))
    assert "epoch" not in status and status["reported"] is False
