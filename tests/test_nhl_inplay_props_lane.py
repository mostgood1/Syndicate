"""NHL's in-play player-prop pull on its own clock (lane nhl-inplay-props-drop).

Measured 2026-11-17: NHL live props rode only the shared live sweep (median capture gap 335 s) while the
overlay keeps a live row for 300 s, so 33 of 76 NHL overlay builds carried no props. These tests pin:
off != on (absent launches nothing), the liveness gate, one child at a time with a kill, one call per
LIVE game and no fallback, the sweep's own markets, the capture-thread hook, and that the pull's rows
refresh each line's last-seen stamp, which is what the overlay's window reads.
"""
from __future__ import annotations

import importlib.util
import inspect
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)  # 7:00 PM CST 11-17

from syndicate.features.nhl import inplay_props_lane as lane  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    lane.reset_for_tests()
    monkeypatch.delenv(lane.ENABLE_ENV, raising=False)
    monkeypatch.delenv(lane.INTERVAL_ENV, raising=False)
    monkeypatch.delenv(lane.TIMEOUT_ENV, raising=False)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    yield
    lane.reset_for_tests()


def _scoreboard(tmp_path: Path, date_iso: str, games: list[tuple[str, datetime]]) -> None:
    path = tmp_path / "nhl_source" / "data" / "odds" / "games" / f"date={date_iso}" / "scoreboard.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["gamePk,gameDate,home,away,gameState"]
    for i, (state, start) in enumerate(games):
        lines.append(f"{i},{start.strftime('%Y-%m-%dT%H:%M:%SZ')},H{i},A{i},{state}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _Proc:
    def __init__(self, pid: int = 4242):
        self.pid = pid
        self.rc = None
        self.killed = False

    def poll(self):
        return self.rc

    def kill(self):
        self.killed = True


class _Popen:
    def __init__(self):
        self.calls: list[tuple[list[str], dict]] = []
        self.procs: list[_Proc] = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        proc = _Proc(pid=4242 + len(self.procs))
        self.procs.append(proc)
        return proc


# --- off != on ---------------------------------------------------------------------------------


def test_absent_means_off_and_launches_nothing_even_with_a_live_game(tmp_path):
    _scoreboard(tmp_path, "2026-11-17", [("LIVE", NOW - timedelta(minutes=40))])
    popen = _Popen()
    assert lane.nhl_inplay_props_enabled() is False
    assert lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen) is None
    assert popen.calls == [], "absent means OFF: this lane spends OddsAPI credits"


def test_on_launches_the_pull_for_the_live_slate(monkeypatch, tmp_path):
    _scoreboard(tmp_path, "2026-11-17", [("LIVE", NOW - timedelta(minutes=40)), ("FUT", NOW + timedelta(hours=2))])
    monkeypatch.setenv(lane.ENABLE_ENV, "1")
    popen = _Popen()
    out = lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen)
    assert out is not None and out["date"] == "2026-11-17" and out["live_games"] == 1
    command, kwargs = popen.calls[0]
    assert "refresh_nhl_inplay_props.py" in " ".join(command)
    assert command[command.index("--date") + 1] == "2026-11-17"
    assert kwargs["cwd"] == str(lane._REPO_ROOT)


# --- one child at a time, the interval, the kill ---------------------------------------------------


def test_one_child_at_a_time_then_the_interval_gates_the_next(monkeypatch, tmp_path):
    _scoreboard(tmp_path, "2026-11-17", [("CRIT", NOW - timedelta(hours=2))])
    monkeypatch.setenv(lane.ENABLE_ENV, "on")
    popen = _Popen()
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(lane.time, "time", lambda: clock["t"])
    assert lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen) is not None
    clock["t"] += 200  # past the 120 s interval, but the child is still running
    assert lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen) is None
    assert len(popen.calls) == 1
    popen.procs[0].rc = 0  # the pull finished
    clock["t"] = 1_000_000.0 + 60  # finished, but inside the interval
    assert lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen) is None
    clock["t"] = 1_000_000.0 + 121
    assert lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen) is not None
    assert len(popen.calls) == 2


def test_a_pull_past_its_timeout_is_killed_and_the_lane_moves_on(monkeypatch, tmp_path, capsys):
    _scoreboard(tmp_path, "2026-11-17", [("LIVE", NOW - timedelta(minutes=10))])
    monkeypatch.setenv(lane.ENABLE_ENV, "1")
    monkeypatch.setenv(lane.TIMEOUT_ENV, "30")
    popen = _Popen()
    mono = {"t": 50.0}
    monkeypatch.setattr(lane.time, "monotonic", lambda: mono["t"])
    lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen)
    mono["t"] += 31
    lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen)
    assert popen.procs[0].killed is True
    assert "NHL_INPLAY_PROPS_TIMEOUT" in capsys.readouterr().out
    assert lane._CHILD is None


def test_interval_and_timeout_floors(monkeypatch):
    monkeypatch.setenv(lane.INTERVAL_ENV, "5")
    assert lane.nhl_inplay_props_interval_seconds() == 60
    monkeypatch.setenv(lane.INTERVAL_ENV, "junk")
    assert lane.nhl_inplay_props_interval_seconds() == 120
    monkeypatch.delenv(lane.INTERVAL_ENV)
    assert lane.nhl_inplay_props_interval_seconds() == 120
    assert lane.nhl_inplay_props_timeout_seconds() == 90


# --- the liveness gate -------------------------------------------------------------------------------


def test_live_game_count_reads_the_sweeps_scoreboard(tmp_path):
    _scoreboard(tmp_path, "2026-11-17", [
        ("LIVE", NOW - timedelta(minutes=30)),   # counts
        ("CRIT", NOW - timedelta(hours=2, minutes=40)),  # counts
        ("FINAL", NOW - timedelta(hours=1)),     # done
        ("OFF", NOW - timedelta(hours=3)),       # done
        ("FUT", NOW - timedelta(minutes=5)),     # stale scoreboard, start passed: counts
        ("PRE", NOW + timedelta(minutes=20)),    # not started
        ("LIVE", NOW - timedelta(hours=5)),      # a stale LIVE far past any game length: does not
    ])
    assert lane.nhl_live_game_count("2026-11-17", now=NOW) == 3


def test_no_scoreboard_and_no_live_game_launch_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv(lane.ENABLE_ENV, "1")
    popen = _Popen()
    assert lane.nhl_live_game_count("2026-11-17", now=NOW) == 0
    assert lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen) is None
    _scoreboard(tmp_path, "2026-11-17", [("FINAL", NOW - timedelta(hours=1)), ("FUT", NOW + timedelta(hours=1))])
    assert lane.launch_autorun_nhl_inplay_props(now=NOW, popen=popen) is None
    assert popen.calls == []


def test_a_game_still_live_after_midnight_central_pulls_the_previous_date(monkeypatch, tmp_path):
    after_midnight = datetime(2026, 11, 18, 6, 20, tzinfo=timezone.utc)  # 00:20 CST 11-18
    _scoreboard(tmp_path, "2026-11-17", [("LIVE", after_midnight - timedelta(hours=2, minutes=50))])
    monkeypatch.setenv(lane.ENABLE_ENV, "1")
    popen = _Popen()
    out = lane.launch_autorun_nhl_inplay_props(now=after_midnight, popen=popen)
    assert out is not None and out["date"] == "2026-11-17"


# --- the pull ----------------------------------------------------------------------------------------

_EVENT = {
    "id": "ev-live",
    "commence_time": "2026-11-18T00:10:00Z",
    "home_team": "Boston Bruins",
    "away_team": "Los Angeles Kings",
    "bookmakers": [
        {"key": "draftkings", "markets": [
            {"key": "player_shots_on_goal", "outcomes": [
                {"name": "Over", "description": "David Pastrnak", "point": 3.5, "price": -120},
                {"name": "Under", "description": "David Pastrnak", "point": 3.5, "price": 100},
            ]},
            {"key": "player_total_saves", "outcomes": [
                {"name": "Over", "description": "Jeremy Swayman", "point": 27.5, "price": -110},
            ]},
            {"key": "h2h", "outcomes": [{"name": "Boston Bruins", "price": -150}]},  # not a prop: skipped
            {"key": "player_goals", "outcomes": [{"name": "Over", "description": "", "point": 0.5, "price": 200}]},
        ]},
    ],
}


def test_parse_keeps_the_sweeps_row_shape_and_grid_codes():
    rows = lane.parse_prop_event(_EVENT, date="2026-11-17", collected_at="2026-11-18T01:00:00Z")
    assert [(r["market"], r["player"], r["side"], r["line"], r["odds"]) for r in rows] == [
        ("SOG", "David Pastrnak", "OVER", 3.5, -120),
        ("SOG", "David Pastrnak", "UNDER", 3.5, 100),
        ("SAVES", "Jeremy Swayman", "OVER", 27.5, -110),
    ]
    assert {r["book"] for r in rows} == {"draftkings"} and {r["event_id"] for r in rows} == {"ev-live"}
    assert all(r["commence_time"] == "2026-11-18T00:10:00Z" for r in rows)


class _Client:
    def __init__(self, events):
        self.events = events
        self.list_calls = []
        self.odds_calls = []

    def list_events(self, sport, *, commence_from_iso=None, commence_to_iso=None):
        self.list_calls.append((sport, commence_from_iso, commence_to_iso))
        return (list(self.events) if sport == "icehockey_nhl" else []), {}

    def event_odds(self, sport, event_id, *, markets, regions="us", bookmakers=None):
        self.odds_calls.append((sport, event_id, markets, regions, bookmakers))
        return dict(_EVENT, id=event_id), {"x-requests-last": "5"}


def _load_pull():
    spec = importlib.util.spec_from_file_location("nhl_inplay_props_pull", REPO / "scripts" / "refresh_nhl_inplay_props.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["nhl_inplay_props_pull"] = module
    spec.loader.exec_module(module)
    return module


def test_the_pull_fetches_live_games_once_each_with_the_sweeps_markets_and_books(monkeypatch):
    monkeypatch.delenv("PROPS_ODDSAPI_BOOKMAKERS", raising=False)
    from syndicate import local_nhl_odds

    pull = _load_pull()
    client = _Client([
        {"id": "ev-live", "commence_time": "2026-11-18T00:10:00Z"},
        {"id": "ev-soon", "commence_time": "2026-11-18T03:10:00Z"},   # not started: no call
        {"id": "ev-old", "commence_time": "2026-11-17T19:00:00Z"},    # > 4 h: no call
    ])
    appended = []
    summary = pull.pull("2026-11-17", now=NOW, client=client,
                        append=lambda frame, *, date, kind: appended.append((len(frame), date, kind)) or {"by_game_date": {"2026-11-17": len(frame)}})
    assert [c[1] for c in client.odds_calls] == ["ev-live"], "one call per LIVE game, no fallback retries"
    sport, _, markets, regions, books = client.odds_calls[0]
    assert markets == ",".join(lane.NHL_INPLAY_PROP_MARKETS) and regions == "us"
    assert books == local_nhl_odds.NHL_PROP_BOOKMAKERS
    assert appended == [(3, "2026-11-17", "prop")]
    assert summary["events_live"] == 1 and summary["rows"] == 3 and summary["credits"] == 5.0
    # `/events` asked for games that started in the last 4 h, up to now.
    _, frm, to = client.list_calls[0]
    assert frm == "2026-11-17T21:00:00Z" and to == "2026-11-18T01:00:00Z"


def test_a_failed_game_never_costs_the_others_and_nothing_is_appended_when_empty():
    pull = _load_pull()

    class _Failing(_Client):
        def event_odds(self, sport, event_id, **kw):
            self.odds_calls.append((sport, event_id))
            raise RuntimeError("TheOddsAPI request failed (500)")

    client = _Failing([{"id": "a", "commence_time": "2026-11-18T00:10:00Z"}])
    appended = []
    summary = pull.pull("2026-11-17", now=NOW, client=client, append=lambda *a, **k: appended.append(1))
    assert appended == [] and summary["rows"] == 0 and summary["errors"]


def test_the_market_list_is_the_sweeps_own():
    """Drift guard: the live pull asks for exactly the sweep's prop markets, filed under the same codes."""
    from syndicate import local_nhl_odds

    source = inspect.getsource(local_nhl_odds.collect_oddsapi_props)
    requested = re.search(r'markets = "([^"]+)"', source).group(1)
    assert requested == ",".join(lane.NHL_INPLAY_PROP_MARKETS)
    for key, code in lane.NHL_INPLAY_PROP_MARKETS.items():
        assert re.search(rf'"{key}": "{code}"', source), f"{key} -> {code} is not the sweep's mapping"


# --- the hook: the capture thread reaches the launcher ----------------------------------------------


@pytest.fixture(scope="module")
def worker():
    path = REPO / "scripts" / "run_live_odds_refresh_worker.py"
    spec = importlib.util.spec_from_file_location("test_nhl_inplay_props_worker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _quiet_other_lanes(worker, monkeypatch):
    for name in ("_launch_autorun_wnba_live_refresh", "_launch_autorun_ncaaf_lines_refresh",
                 "_launch_autorun_soccer_live_refresh", "_launch_autorun_nba_live_refresh",
                 "_launch_autorun_nfl_lines_refresh"):
        monkeypatch.setattr(worker, name, lambda: None)
    from syndicate.features.ncaab import inplay_lane as college

    monkeypatch.setattr(college, "launch_autorun_ncaab_live_refresh", lambda *a, **k: None)
    monkeypatch.setattr(college, "launch_autorun_wncaab_live_refresh", lambda *a, **k: None)


def test_the_capture_thread_reaches_the_nhl_launcher(worker, monkeypatch):
    _quiet_other_lanes(worker, monkeypatch)
    calls = []
    monkeypatch.setattr(lane, "launch_autorun_nhl_inplay_props", lambda: calls.append("nhl"))
    worker._launch_inplay_capture_autoruns("thread")
    assert calls == ["nhl"]


def test_an_nhl_failure_is_logged_and_costs_no_other_lane(worker, monkeypatch, capsys):
    _quiet_other_lanes(worker, monkeypatch)
    ran = []
    monkeypatch.setattr(worker, "_launch_autorun_nfl_lines_refresh", lambda: ran.append("nfl"))
    monkeypatch.setattr(lane, "launch_autorun_nhl_inplay_props", lambda: (_ for _ in ()).throw(RuntimeError("nhl boom")))
    worker._launch_inplay_capture_autoruns("loop")
    assert ran == ["nfl"]
    assert "NHL_INPLAY_PROPS_AUTORUN_ERROR source=loop RuntimeError: nhl boom" in capsys.readouterr().out


# --- the effect: each line's last-seen stamp moves, which is what the overlay's 300 s reads ----------


def test_the_pulls_rows_refresh_each_lines_last_seen_through_the_sweeps_writer(monkeypatch, tmp_path):
    """off != on at the stamp the window reads: an unchanged price seen again gets a NEW last-seen."""
    import pandas as pd

    from syndicate import local_nhl_odds
    from syndicate.features.shared import odds_book_quotes as obq

    stamps = iter(["2026-11-18T00:50:00Z", "2026-11-18T00:58:00Z"])
    monkeypatch.setattr(local_nhl_odds, "_utc_now_iso", lambda: next(stamps))
    rows = lane.parse_prop_event(_EVENT, date="2026-11-17", collected_at="x")
    local_nhl_odds._append_nhl_book_quotes(pd.DataFrame(rows), date="2026-11-17", kind="prop")
    first = obq.read_quote_last_seen("nhl", "2026-11-17")
    assert len(first) == 3 and set(first.values()) == {"2026-11-18T00:50:00Z"}
    # The same prices, seen again by the next pull: every line's stamp moves to the new look.
    local_nhl_odds._append_nhl_book_quotes(pd.DataFrame(rows), date="2026-11-17", kind="prop")
    second = obq.read_quote_last_seen("nhl", "2026-11-17")
    assert set(second) == set(first) and set(second.values()) == {"2026-11-18T00:58:00Z"}
