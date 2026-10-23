"""NBA in-play pulls fetch only the games in play and merge them (lane `nba-inplay-only-pulls`, 2026-10-21).

10-20: 73 forced NBA live pulls (6:18-11:22 PM CT), each fetching every game left on the date at ~49 credits a game.
`--in-play-only` fetches only games that started within the window and keeps every other game's rows in the snapshot.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


fetch = _load("fetch_bball_props_inplay_test", "scripts/fetch_basketball_oddsapi_props_local.py")
NOW = pd.Timestamp("2026-10-21T01:00:00Z")


def _ev(eid, start):
    return {"id": eid, "commence_time": start, "home_team": f"H{eid}", "away_team": f"A{eid}"}


def test_in_play_is_started_within_the_window_never_pregame_or_long_finished():
    events = [_ev("live", "2026-10-21T00:10:00Z"), _ev("pregame", "2026-10-21T01:30:00Z"),
              _ev("old", "2026-10-20T20:30:00Z"), _ev("tipping", "2026-10-21T01:00:00Z")]
    assert [e["id"] for e in fetch.in_play_events(events, NOW)] == ["live", "tipping"]


def test_the_window_is_three_hours_so_a_finished_game_drops_out():
    # 10-21: a 4 h window kept finished games OddsAPI still listed (8:47 PM 8 fetched vs 6 live)
    assert fetch.IN_PLAY_WINDOW_HOURS == 3.0
    events = [_ev("ot", "2026-10-20T22:05:00Z"), _ev("finished", "2026-10-20T21:30:00Z")]   # 2h55 and 3h30 before NOW
    assert [e["id"] for e in fetch.in_play_events(events, NOW)] == ["ot"]


def test_merge_replaces_only_the_events_that_came_back():
    existing = pd.DataFrame([{"event_id": "a", "price": -110}, {"event_id": "a", "price": -115},
                             {"event_id": "b", "price": 120}])
    fresh = pd.DataFrame([{"event_id": "a", "price": -200}])
    merged = fetch.merge_in_play_rows(existing, fresh)
    assert sorted(merged["event_id"]) == ["a", "b"] and merged[merged.event_id == "a"]["price"].tolist() == [-200]
    assert fetch.merge_in_play_rows(None, fresh).equals(fresh)


def test_the_fetch_asks_odds_only_for_games_in_play(monkeypatch):
    calls = []

    class Resp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    events = [_ev("live", "2026-10-21T00:10:00Z"), _ev("pregame", "2026-10-21T01:30:00Z")]

    def fake_get(url, params):
        calls.append(url)
        if url.endswith("/events"):
            return Resp(events)
        if url.endswith("/markets"):
            return Resp({"bookmakers": [{"markets": [{"key": "player_points"}]}]})
        eid = url.split("/events/")[1].split("/")[0]
        return Resp({"id": eid, "commence_time": "x", "home_team": "H", "away_team": "A", "bookmakers": [
            {"key": "dk", "title": "DK", "markets": [{"key": "player_points", "outcomes": [
                {"name": "Over", "description": "P", "point": 10.5, "price": -110}]}]}]})

    monkeypatch.setattr(fetch, "_get", fake_get)
    monkeypatch.setattr(fetch, "league_sport_keys", lambda league: ("basketball_nba",))
    df = fetch.fetch_player_props_current(api_key="k", league="nba", date_str="2026-10-20", regions="us",
                                          bookmakers=None, markets=["player_points"], in_play_only=True, now=NOW)
    assert not any("/events/pregame/" in u for u in calls)              # off != on: the pregame game is never asked
    assert any("/events/live/odds" in u for u in calls) and set(df["event_id"]) == {"live"}
    calls.clear()
    fetch.fetch_player_props_current(api_key="k", league="nba", date_str="2026-10-20", regions="us",
                                     bookmakers=None, markets=["player_points"], in_play_only=False, now=NOW)
    assert any("/events/pregame/" in u for u in calls)


def test_main_merges_into_the_snapshot_and_appends_quotes_for_the_fresh_rows_only(tmp_path, monkeypatch):
    out = tmp_path / "props.csv"
    pd.DataFrame([{"event_id": "a", "price": -110}, {"event_id": "b", "price": 120}]).to_csv(out, index=False)
    fresh = pd.DataFrame([{"event_id": "a", "price": -300}])
    appended = []
    monkeypatch.setenv("ODDS_API_KEY", "k")
    monkeypatch.setattr(fetch, "_load_env", lambda: None)
    monkeypatch.setattr(fetch, "fetch_player_props_current", lambda **kw: fresh if kw["in_play_only"] else None)
    monkeypatch.setattr(fetch, "_append_basketball_book_quotes", lambda **kw: appended.append(len(kw["df"])))
    assert fetch.main(["--league", "nba", "--date", "2026-10-20", "--out", str(out), "--in-play-only"]) == 0
    got = pd.read_csv(out)
    assert sorted(got["event_id"]) == ["a", "b"] and got[got.event_id == "a"]["price"].tolist() == [-300]
    assert appended == [1]
    # nothing in play: the snapshot is left exactly as it was (never the full-pull fallbacks)
    before = out.read_bytes()
    monkeypatch.setattr(fetch, "fetch_player_props_current", lambda **kw: pd.DataFrame())
    assert fetch.main(["--league", "nba", "--date", "2026-10-20", "--out", str(out), "--in-play-only"]) == 0
    assert out.read_bytes() == before


def test_only_the_forced_nba_live_run_is_in_play_only(monkeypatch):
    ros = _load("refresh_odds_sources_inplay_test", "scripts/refresh_odds_sources.py")
    monkeypatch.delenv("SYNDICATE_NBA_IN_PLAY_ONLY", raising=False)

    def ns(**kw):
        base = {"phase": "live", "force_refresh": True, "force_refresh_sports": "nba"}
        return argparse.Namespace(**{**base, **kw})

    assert ros._in_play_only_scope(ns(), "nba") is True
    assert ros._in_play_only_scope(ns(phase="pregame"), "nba") is False
    assert ros._in_play_only_scope(ns(phase="all"), "nba") is False
    assert ros._in_play_only_scope(ns(force_refresh=False), "nba") is False          # the shared sweep
    assert ros._in_play_only_scope(ns(force_refresh_sports="wnba"), "nba") is False
    assert ros._in_play_only_scope(ns(), "wnba") is False
    monkeypatch.setenv("SYNDICATE_NBA_IN_PLAY_ONLY", "0")
    assert ros._in_play_only_scope(ns(), "nba") is False
    step = ros.RefreshStep(name="nba_oddsapi_props_job", phases=("live",), cwd=ROOT,
                           command=("py", "scripts/refresh_nba_oddsapi_props.py", "--date", "d"), description="")
    assert ros._step_command_with_mode(step, "fast", force_refresh=True, in_play_only=True)[-1] == "--in-play-only"
    assert "--in-play-only" not in ros._step_command_with_mode(step, "fast", force_refresh=True)
    assert "--in-play-only" not in ros._step_command_with_mode(step, "fast", force_refresh=False, in_play_only=True)


def test_the_nba_refresh_passes_it_to_the_fetcher():
    nba = _load("refresh_nba_props_inplay_test", "scripts/refresh_nba_oddsapi_props.py")
    args = nba._owned_snapshot_cli_args(date_str="d", out_path=Path("o.csv"), regions="us", bookmakers="", markets="",
                                        in_play_only=True)
    assert args[-1] == "--in-play-only"
    assert "--in-play-only" not in nba._owned_snapshot_cli_args(date_str="d", out_path=Path("o.csv"), regions="us",
                                                                bookmakers="", markets="")
    source = (ROOT / "scripts" / "refresh_nba_oddsapi_props.py").read_text(encoding="utf-8")
    assert "in_play_only=bool(args.in_play_only)" in source and "in_play_only=in_play_only," in source


def test_pregame_games_are_due_every_30_minutes_while_others_are_live():
    # 10-23: from CHI @ MIL's 3:10 PM CT tip every NBA props pull was in-play only, and DET @ MIA (7:10 PM) carried 4
    # board rows at 6:22 PM. A not-yet-started game is now due when it was never pulled or pulled 30+ minutes ago.
    assert fetch.PREGAME_REFRESH_MINUTES == 30.0
    events = [_ev("live", "2026-10-21T00:10:00Z"), _ev("never", "2026-10-21T02:00:00Z"),
              _ev("stale", "2026-10-21T02:30:00Z"), _ev("fresh", "2026-10-21T03:00:00Z")]
    last = {"stale": "2026-10-21T00:30:00+00:00", "fresh": "2026-10-21T00:50:00+00:00"}   # 30 and 10 min before NOW
    assert [e["id"] for e in fetch.upcoming_events_due(events, NOW, last)] == ["never", "stale"]


def _fake_odds_api(calls):
    class Resp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    events = [_ev("live", "2026-10-21T00:10:00Z"), _ev("pregame", "2026-10-21T01:30:00Z")]

    def fake_get(url, params):
        calls.append(url)
        if url.endswith("/events"):
            return Resp(events)
        if url.endswith("/markets"):
            return Resp({"bookmakers": [{"markets": [{"key": "player_points"}]}]})
        eid = url.split("/events/")[1].split("/")[0]
        start = next(e["commence_time"] for e in events if e["id"] == eid)
        return Resp({"id": eid, "commence_time": start, "home_team": "H", "away_team": "A", "bookmakers": [
            {"key": "dk", "title": "DK", "markets": [{"key": "player_points", "outcomes": [
                {"name": "Over", "description": "P", "point": 10.5, "price": -110}]}]}]})

    return fake_get


def test_the_in_play_pull_takes_a_due_pregame_game_and_records_it(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch, "_get", _fake_odds_api(calls))
    monkeypatch.setattr(fetch, "league_sport_keys", lambda league: ("basketball_nba",))
    kw = dict(api_key="k", league="nba", date_str="2026-10-20", regions="us", bookmakers=None,
              markets=["player_points"], in_play_only=True, now=NOW)
    # Reachability: no pull record (None) is the old in-play-only pull -- the pregame game is never asked.
    assert set(fetch.fetch_player_props_current(**kw)["event_id"]) == {"live"}
    assert not any("/events/pregame/" in u for u in calls)
    # A record (even empty) also takes the due pregame game; pulled 10 min ago it waits.
    calls.clear()
    assert set(fetch.fetch_player_props_current(**kw, pregame_last={})["event_id"]) == {"live", "pregame"}
    calls.clear()
    recent = {"pregame": (NOW - pd.Timedelta(minutes=10)).isoformat()}
    assert set(fetch.fetch_player_props_current(**kw, pregame_last=recent)["event_id"]) == {"live"}
    assert not any("/events/pregame/" in u for u in calls)

    # main: the record beside the snapshot gets the pregame game, never the live one; the next pull skips it.
    out = tmp_path / "props.csv"
    pd.DataFrame([{"event_id": "live", "commence_time": "2026-10-21T00:10:00Z", "price": -110}]).to_csv(out, index=False)
    monkeypatch.setenv("ODDS_API_KEY", "k")
    monkeypatch.setattr(fetch, "_load_env", lambda: None)
    monkeypatch.setattr(fetch, "_append_basketball_book_quotes", lambda **kw: None)
    monkeypatch.setattr(fetch, "_utc_now", lambda: NOW)
    calls.clear()
    assert fetch.main(["--league", "nba", "--date", "2026-10-20", "--out", str(out), "--in-play-only"]) == 0
    record = fetch.json.loads(fetch._pregame_pulls_path(out).read_text())
    assert set(record) == {"pregame"} and pd.Timestamp(record["pregame"]) == NOW
    assert sorted(set(pd.read_csv(out)["event_id"])) == ["live", "pregame"]
    calls.clear()
    assert fetch.main(["--league", "nba", "--date", "2026-10-20", "--out", str(out), "--in-play-only"]) == 0
    assert not any("/events/pregame/" in u for u in calls)                      # pulled at NOW: not due again yet
