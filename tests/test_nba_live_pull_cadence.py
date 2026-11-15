"""#811 (lane nba-live-pull-60s; user "now do the same for NBA live pulls", after #810 did it for college): while an NBA
game is live the in-play lane launches every 60 s (was 240 s), and the fetcher's props clock keeps the expensive full pass
-- every prop and quarter/half market, ~49 credits a game -- on 240 s. The pulls between make one bulk /odds call per
sport key for the full-game lines alone (3 credits) and replace only those three markets in the day's snapshot.

Measured 11-15 before the change: NBA's any-pull gap ran ~245 s, because the lane was NBA's only live look.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
NOW = pd.Timestamp("2026-11-16T01:00:00Z")
LIVE_START = "2026-11-16T00:40:00Z"
PREGAME_START = "2026-11-16T02:00:00Z"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fetch = _load("fetch_bball_props_cadence_811", "scripts/fetch_basketball_oddsapi_props_local.py")


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    for key in ("SYNDICATE_NBA_IN_PLAY_PROPS_INTERVAL_SECONDS", "SYNDICATE_WNBA_IN_PLAY_PROPS_INTERVAL_SECONDS",
                "SYNDICATE_NBA_LIVE_REFRESH_INTERVAL_SECONDS"):
        monkeypatch.delenv(key, raising=False)


def _event(eid, start):
    return {"id": eid, "commence_time": start, "home_team": "Home", "away_team": "Away"}


def _market(key, outcomes):
    return {"key": key, "last_update": "2026-11-16T00:59:00Z", "outcomes": outcomes}


def _game_lines(price):
    return [_market("h2h", [{"name": "Home", "price": price}, {"name": "Away", "price": -price}]),
            _market("spreads", [{"name": "Home", "point": -3.5, "price": -110}, {"name": "Away", "point": 3.5, "price": -110}]),
            _market("totals", [{"name": "Over", "point": 220.5, "price": -110}, {"name": "Under", "point": 220.5, "price": -110}])]


class FakeOddsApi:
    """/events, per-event /markets + /odds (the full pass), and the bulk /sports/{key}/odds (the lines-only pull)."""

    def __init__(self, events, *, bulk_fails=False):
        self.events = events
        self.bulk_fails = bulk_fails
        self.calls: list[tuple[str, dict]] = []
        self.bulk_price = 150

    def __call__(self, url, params):
        path = urlparse(url).path
        self.calls.append((path, dict(params)))
        if path.endswith("/events"):
            sport_key = path.split("/sports/")[1].split("/")[0]
            return _Resp([e for e in self.events if e.get("sport_key", "basketball_nba") == sport_key])
        if "/events/" in path and path.endswith("/markets"):
            return _Resp({"bookmakers": [{"markets": [{"key": k} for k in
                                                       ("player_points", "h2h", "spreads", "totals", "spreads_q1")]}]})
        if "/events/" in path and path.endswith("/odds"):
            eid = path.split("/events/")[1].split("/")[0]
            event = next(e for e in self.events if e["id"] == eid)
            markets = _game_lines(120) + [
                _market("spreads_q1", [{"name": "Home", "point": -1.5, "price": -105}, {"name": "Away", "point": 1.5, "price": -115}]),
                _market("player_points", [{"name": "Over", "description": "Star", "point": 25.5, "price": -110}])]
            return _Resp({**event, "bookmakers": [{"key": "draftkings", "title": "DK", "markets": markets}]})
        if path.endswith("/odds"):
            if self.bulk_fails:
                raise fetch.requests.HTTPError(f"422 Client Error for url: {url}?apiKey={params.get('apiKey')}")
            sport_key = path.split("/sports/")[1].split("/")[0]
            return _Resp([{**e, "bookmakers": [{"key": "draftkings", "title": "DK", "markets": _game_lines(self.bulk_price)}]}
                          for e in self.events if e.get("sport_key", "basketball_nba") == sport_key])
        raise AssertionError(f"unexpected call {path}")

    def per_event_odds(self):
        return [p for p, _ in self.calls if "/events/" in p and p.endswith("/odds")]

    def bulk(self):
        return [(p, q) for p, q in self.calls if p.endswith("/odds") and "/events/" not in p]


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def api(monkeypatch):
    fake = FakeOddsApi([_event("live", LIVE_START), _event("pregame", PREGAME_START)])
    monkeypatch.setattr(fetch, "_get", fake)
    monkeypatch.setattr(fetch, "league_sport_keys", lambda league: ("basketball_nba",))
    return fake


def _kw(**extra):
    return dict(api_key="k", league="nba", date_str="2026-11-15", regions="us", bookmakers=None,
                markets=["player_points"], in_play_only=True, now=NOW, **extra)


# --- the lane's cadence -------------------------------------------------------------------------------------

def test_the_nba_lane_launches_every_60_s_and_the_env_key_still_wins(monkeypatch):
    worker = _load("nba_live_worker_cadence_811", "scripts/run_live_odds_refresh_worker.py")
    assert worker._nba_live_refresh_interval_seconds() == 60
    monkeypatch.setenv("SYNDICATE_NBA_LIVE_REFRESH_INTERVAL_SECONDS", "240")    # off != on: the old cadence, one key away
    assert worker._nba_live_refresh_interval_seconds() == 240
    monkeypatch.setenv("SYNDICATE_NBA_LIVE_REFRESH_INTERVAL_SECONDS", "30")     # the 60 s floor is unchanged
    assert worker._nba_live_refresh_interval_seconds() == 60
    monkeypatch.setenv("SYNDICATE_NBA_LIVE_REFRESH_INTERVAL_SECONDS", "garbage")
    assert worker._nba_live_refresh_interval_seconds() == 60


# --- the lines-only pull ------------------------------------------------------------------------------------

def test_a_lines_only_pull_is_one_bulk_call_for_the_three_game_markets_and_the_live_game_only(api):
    df = fetch.fetch_player_props_current(**_kw(pregame_last={}, lines_only=True))
    assert api.per_event_odds() == [] and not any(p.endswith("/markets") for p, _ in api.calls)
    (path, params), = api.bulk()
    assert path.endswith("/sports/basketball_nba/odds") and params["markets"] == "h2h,spreads,totals"
    assert params["oddsFormat"] == "american"
    # the pregame game rides in the bulk response but is not kept, and a due pregame game waits for the full pass
    assert set(df["event_id"]) == {"live"} and set(df["market"]) == {"h2h", "spreads", "totals"}


def test_the_full_pass_is_unchanged_when_lines_only_is_off(api):
    df = fetch.fetch_player_props_current(**_kw(pregame_last={}))
    assert api.bulk() == []                                                         # off != on
    assert sorted(api.per_event_odds()) == ["/v4/sports/basketball_nba/events/live/odds",
                                            "/v4/sports/basketball_nba/events/pregame/odds"]
    assert {"player_points", "spreads_q1", "h2h"} <= set(df["market"])


def test_one_bulk_call_per_sport_key_that_has_a_live_game(monkeypatch):
    fake = FakeOddsApi([{**_event("reg", LIVE_START), "sport_key": "basketball_nba"},
                        {**_event("pre", LIVE_START), "sport_key": "basketball_nba_preseason"},
                        {**_event("later", PREGAME_START), "sport_key": "basketball_nba_preseason"}])
    monkeypatch.setattr(fetch, "_get", fake)
    monkeypatch.setattr(fetch, "league_sport_keys", lambda league: ("basketball_nba", "basketball_nba_preseason"))
    df = fetch.fetch_player_props_current(**_kw(lines_only=True))
    assert sorted(p for p, _ in fake.bulk()) == ["/v4/sports/basketball_nba/odds", "/v4/sports/basketball_nba_preseason/odds"]
    assert set(df["event_id"]) == {"reg", "pre"}
    fake.events = [_event("later", PREGAME_START)]                                  # nothing live: no paid call at all
    fake.calls.clear()
    assert fetch.fetch_player_props_current(**_kw(lines_only=True)).empty and fake.bulk() == []


def test_a_failed_bulk_call_returns_nothing_and_never_prints_the_key(monkeypatch, capsys):
    fake = FakeOddsApi([_event("live", LIVE_START)], bulk_fails=True)
    monkeypatch.setattr(fetch, "_get", fake)
    monkeypatch.setattr(fetch, "league_sport_keys", lambda league: ("basketball_nba",))
    assert fetch.fetch_player_props_current(**{**_kw(lines_only=True), "api_key": "SECRETKEY123"}).empty
    out = capsys.readouterr().out
    assert "IN_PLAY_GAME_LINES_FAILED sport_key=basketball_nba HTTPError" in out and "SECRETKEY123" not in out


# --- the merge ----------------------------------------------------------------------------------------------

def test_the_lines_merge_replaces_only_the_three_game_markets_of_the_events_that_came_back():
    existing = pd.DataFrame([
        {"event_id": "live", "market": "h2h", "price": 100},
        {"event_id": "live", "market": "spreads", "price": -110},
        {"event_id": "live", "market": "spreads_q1", "price": -105},
        {"event_id": "live", "market": "player_points", "price": -120},
        {"event_id": "quiet", "market": "h2h", "price": 200},     # live, but its bulk row did not come back
        {"event_id": "other", "market": "totals", "price": -115},
    ])
    fresh = pd.DataFrame([{"event_id": "live", "market": "h2h", "price": 150}])
    merged = fetch.merge_in_play_game_lines(existing, fresh)
    live = merged[merged.event_id == "live"].set_index("market")["price"].to_dict()
    # a book that dropped its spread loses the stale row, as a full pass would drop it; props and segments are kept
    assert live == {"h2h": 150, "spreads_q1": -105, "player_points": -120}
    assert merged[merged.event_id == "quiet"]["price"].tolist() == [200]
    assert merged[merged.event_id == "other"]["price"].tolist() == [-115]
    assert fetch.merge_in_play_game_lines(None, fresh).equals(fresh)


# --- the props clock ----------------------------------------------------------------------------------------

def test_the_clock_is_due_with_no_record_and_after_240_s_less_the_slack(tmp_path):
    out = tmp_path / "props.csv"
    assert fetch.in_play_props_due("nba", out, NOW) == (True, None)
    fetch._write_props_clock(out, NOW)
    assert fetch.in_play_props_due("nba", out, NOW + pd.Timedelta(seconds=60)) == (False, 60.0)
    assert fetch.in_play_props_due("nba", out, NOW + pd.Timedelta(seconds=225))[0] is True    # 225 + 20 >= 240
    assert fetch.in_play_props_due("nba", out, NOW - pd.Timedelta(seconds=30))[0] is True     # a clock in the future
    fetch._props_clock_path(out).write_text("not json", encoding="utf-8")
    assert fetch.in_play_props_due("nba", out, NOW)[0] is True                                 # unreadable


def test_zero_turns_the_clock_off(tmp_path, monkeypatch):
    out = tmp_path / "props.csv"
    fetch._write_props_clock(out, NOW)
    monkeypatch.setenv("SYNDICATE_NBA_IN_PLAY_PROPS_INTERVAL_SECONDS", "0")
    assert fetch.in_play_props_due("nba", out, NOW + pd.Timedelta(seconds=1)) == (True, None)
    monkeypatch.setenv("SYNDICATE_NBA_IN_PLAY_PROPS_INTERVAL_SECONDS", "garbage")
    assert fetch.in_play_props_due("nba", out, NOW + pd.Timedelta(seconds=1))[0] is False    # back to 240


# --- main(): the lane's run ---------------------------------------------------------------------------------

@pytest.fixture
def run(tmp_path, monkeypatch, api):
    out = tmp_path / "odds_nba_player_props_2026-11-15.csv"
    appended: list[pd.DataFrame] = []
    clock = {"now": NOW}
    monkeypatch.setenv("ODDS_API_KEY", "k")
    monkeypatch.setattr(fetch, "_load_env", lambda: None)
    monkeypatch.setattr(fetch, "_append_basketball_book_quotes", lambda **kw: appended.append(kw["df"]))
    monkeypatch.setattr(fetch, "_utc_now", lambda: clock["now"])

    def _run(offset_s, *extra):
        clock["now"] = NOW + pd.Timedelta(seconds=offset_s)
        return fetch.main(["--league", "nba", "--date", "2026-11-15", "--out", str(out), "--in-play-only", *extra])

    _run.out, _run.appended, _run.api = out, appended, api
    return _run


def test_a_60_s_lane_takes_the_full_pass_every_240_s_and_game_lines_every_pull(run):
    full_at = []
    for offset in (0, 60, 120, 180, 240, 300):
        before = len(run.api.per_event_odds())
        assert run(offset) == 0
        if len(run.api.per_event_odds()) > before:
            full_at.append(offset)
    assert full_at == [0, 240]
    assert len(run.api.bulk()) == 4                                                  # 60, 120, 180, 300
    snap = pd.read_csv(run.out)
    live = snap[snap.event_id == "live"]
    # the props and quarter line from the 240 s pass are still there after the 300 s lines-only pull
    assert {"player_points", "spreads_q1"} <= set(live["market"])
    assert live[live.market == "h2h"]["price"].abs().tolist() == [150, 150]         # the bulk pull's price
    assert len(live[live.market == "spreads"]) == 2                                  # replaced, never duplicated
    # each lines-only pull appended exactly the three game markets to the quote log
    assert [set(df["market"]) for df in run.appended[1:4]] == [{"h2h", "spreads", "totals"}] * 3
    stamp = fetch._read_props_clock(run.out)
    assert stamp == NOW + pd.Timedelta(seconds=240)


def test_the_clock_off_makes_every_pull_a_full_pass(run, monkeypatch):
    monkeypatch.setenv("SYNDICATE_NBA_IN_PLAY_PROPS_INTERVAL_SECONDS", "0")
    for offset in (0, 60, 120):
        assert run(offset) == 0
    assert run.api.bulk() == [] and len([p for p in run.api.per_event_odds() if "/live/" in p]) == 3


def test_a_lines_only_pull_leaves_the_pregame_record_alone(run):
    assert run(0) == 0                                                                 # full: records the pregame pull
    record_path = fetch._pregame_pulls_path(run.out)
    before = record_path.read_bytes()
    assert run(60) == 0
    assert record_path.read_bytes() == before


def test_a_full_pass_with_no_started_game_does_not_start_the_clock(run):
    run.api.events = [_event("pregame", PREGAME_START)]
    assert run(0) == 0
    assert fetch._read_props_clock(run.out) is None
    # so the game's first pull after tip is a full one
    run.api.events = [_event("pregame", "2026-11-16T01:00:30Z")]
    run.api.calls.clear()
    assert run(60) == 0
    assert run.api.per_event_odds() == ["/v4/sports/basketball_nba/events/pregame/odds"]


def test_a_failed_lines_only_pull_keeps_the_snapshot_and_the_clock(run):
    assert run(0) == 0
    before, stamp = run.out.read_bytes(), fetch._read_props_clock(run.out)
    run.api.bulk_fails = True
    assert run(60) == 0
    assert run.out.read_bytes() == before and fetch._read_props_clock(run.out) == stamp


def test_a_pull_without_in_play_only_never_reads_or_writes_the_clock(run, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("props clock touched")

    monkeypatch.setattr(fetch, "_read_props_clock", _boom)
    monkeypatch.setattr(fetch, "_write_props_clock", _boom)
    assert fetch.main(["--league", "nba", "--date", "2026-11-15", "--out", str(run.out)]) == 0
    assert run.api.bulk() == []
