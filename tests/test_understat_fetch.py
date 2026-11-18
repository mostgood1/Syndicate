"""Understat outage guard (lane `understat-fetch-failures`, 2026-11-18).

MEASURED FIRST. From 2026-11-03 2:54 PM CST every understat.com URL answers
HTTP 200 with the same 26,719-byte "We will come back soon" HTML page -- from
the fleet and from another network. Before that the name did not resolve and
connections timed out (11-01 6:34 PM .. 11-03 3:06 PM CST). The big-5
`soccer_<league>_history_current` / `_players` steps met that as
`requests.JSONDecodeError` and `playersData not available` on every soccer run:
5,152 of 5,152 steps failed in 800 runs (fleet manifests 11-10..11-20).

What is pinned here:

* OFF (`SYNDICATE_UNDERSTAT_OUTAGE_GUARD=0`) is today's code path, byte for
  byte in behaviour: the same exception classes the fleet's stderr tails show,
  two requests per players step, no marker. ON names the outage instead. The
  off != on test drives the fetcher with the REAL refresh step's command line,
  so it proves the guard is reachable from production's entrypoint.
* A step that cannot fetch STILL FAILS (non-zero exit, named last line) -- the
  guard saves requests, it never turns an outage into a green step.
* The cooldown sends no request, and a probe after it recovers on its own.

The maintenance page below is a trimmed stand-in with the same shape as the one
served (doctype, errors.css, title, one sentence), not a copy of it.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest
import requests

from syndicate.features.soccer.ingestion import player_history
from syndicate.features.soccer.ingestion.player_history import UNDERSTAT_OUTAGE_COOLDOWN_SECONDS
from syndicate.features.soccer.ingestion.player_history import UNDERSTAT_OUTAGE_GUARD_ENV
from syndicate.features.soccer.ingestion.player_history import UnderstatUnavailable
from syndicate.features.soccer.ingestion.player_history import understat_outage_guard_enabled

REPO_ROOT = Path(__file__).resolve().parents[1]

MAINTENANCE_HTML = (
    "<!DOCTYPE html>\n<html>\n    <head>\n\t\t<title>Understat.com</title>\n"
    '        <meta charset="UTF-8" />\n'
    '        <link href="/css/errors.css" rel="stylesheet" media="screen">\n'
    "    </head>\n    <body class=\"theme-dark\">\n"
    "        <div class=\"error\"><h1>We will come back soon</h1></div>\n"
    "    </body>\n</html>\n"
)

LEAGUE_DATA = {
    "teams": {
        "83": {
            "id": "83",
            "title": "Arsenal",
            "history": [
                {
                    "h_a": "h", "xG": 1.9, "xGA": 0.6, "npxG": 1.9, "npxGA": 0.6,
                    "ppda": {"att": 220, "def": 24}, "ppda_allowed": {"att": 160, "def": 20},
                    "deep": 11, "deep_allowed": 3, "scored": 2, "missed": 0,
                    "xpts": 2.5, "result": "w", "date": "2026-11-08 15:00:00", "wins": 1,
                    "draws": 0, "loses": 0, "pts": 3, "npxGD": 1.3,
                }
            ],
        }
    },
    "players": [
        {
            "id": "1", "player_name": "A Forward", "games": "11", "time": "900", "goals": "6",
            "xG": "5.5", "assists": "2", "xA": "1.9", "shots": "30", "key_passes": "12",
            "yellow_cards": "1", "red_cards": "0", "position": "F S", "team_title": "Arsenal",
            "npg": "6", "npxG": "5.5", "xGChain": "7", "xGBuildup": "2",
        }
    ],
    "dates": [],
}


def _response(url: str, *, status: int = 200, body: str = "", content_type: str = "text/html") -> requests.Response:
    """A REAL `requests.Response`, so `.json()` raises the same
    `requests.exceptions.JSONDecodeError` the fleet's stderr tails show."""
    response = requests.models.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    response.headers["content-type"] = content_type
    response.encoding = "utf-8"
    response.url = url
    response.request = requests.Request("GET", url).prepare()
    return response


class FakeUnderstat:
    """Stands in for `requests.get` inside player_history. Counts every request."""

    def __init__(self, mode: str = "maintenance") -> None:
        self.mode = mode
        self.calls: list[str] = []

    def __call__(self, url, timeout=None, headers=None, **_kwargs):
        self.calls.append(url)
        if self.mode == "maintenance":
            return _response(url, body=MAINTENANCE_HTML)
        if self.mode == "connect_timeout":
            raise requests.exceptions.ConnectTimeout(f"HTTPSConnectionPool(host='understat.com'): {url}")
        if self.mode == "http_503":
            return _response(url, status=503, body="<html>busy</html>")
        if self.mode == "http_404":
            return _response(url, status=404, body="<html>no such league</html>")
        if self.mode == "up":
            return _response(url, body=json.dumps(LEAGUE_DATA), content_type="application/json")
        raise AssertionError(self.mode)


@pytest.fixture(autouse=True)
def _guard_default(monkeypatch):
    """Every test starts from the production default (env absent = ON)."""
    monkeypatch.delenv(UNDERSTAT_OUTAGE_GUARD_ENV, raising=False)


@pytest.fixture
def understat(monkeypatch):
    fake = FakeUnderstat()
    monkeypatch.setattr(player_history.requests, "get", fake)
    return fake


@pytest.fixture
def fetcher():
    spec = importlib.util.spec_from_file_location(
        "_fetch_soccer_history_local_understat", REPO_ROOT / "scripts" / "fetch_soccer_history_local.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def orchestrator():
    spec = importlib.util.spec_from_file_location("ros_under_test_understat", REPO_ROOT / "scripts" / "refresh_odds_sources.py")
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: the module defines frozen dataclasses.
    sys.modules["ros_under_test_understat"] = module
    spec.loader.exec_module(module)
    return module


def _step_argv(orchestrator, monkeypatch, soccer_root: Path, league: str, kind: str) -> list[str]:
    """argv of the REAL producer step, as refresh_odds_sources would run it."""
    monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", "1")
    season = int(orchestrator.soccer_default_season(league))
    start, _end = orchestrator.soccer_season_date_range(league, season)
    monkeypatch.setattr(orchestrator, "central_today", lambda: start + _dt.timedelta(days=60))
    if kind == "teams":
        step = orchestrator._soccer_current_history_step(league, soccer_root, "python")
    else:
        step = orchestrator._soccer_players_step(league, soccer_root, "python")
    assert step is not None, f"the {kind} step must be due for an absent file"
    command = list(step.command)
    assert command[1] == "scripts/fetch_soccer_history_local.py"
    return command[2:]


def _run_main(fetcher, monkeypatch, argv: list[str]):
    monkeypatch.setattr(sys, "argv", ["fetch_soccer_history_local.py", *argv])
    return fetcher.main()


def _marker(soccer_root: Path) -> dict:
    return json.loads((soccer_root / "_understat_status.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [(None, True), ("", True), ("1", True), ("on", True),
                                            ("0", False), ("false", False), ("off", False), ("NO", False)])
def test_guard_is_on_unless_switched_off(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(UNDERSTAT_OUTAGE_GUARD_ENV, raising=False)
    else:
        monkeypatch.setenv(UNDERSTAT_OUTAGE_GUARD_ENV, value)
    assert understat_outage_guard_enabled() is expected


# ---------------------------------------------------------------------------
# off != on, through the real step command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["teams", "players"])
def test_OFF_differs_from_ON_on_the_maintenance_page_through_the_real_step_command(
    orchestrator, fetcher, understat, monkeypatch, tmp_path, kind
):
    """The reachability test. Same page, same argv (the producer step's own),
    two outcomes. OFF must fail exactly as the fleet's manifests show; ON must
    name the outage. Both must FAIL."""
    soccer_root = tmp_path / "soccer_source"
    argv = _step_argv(orchestrator, monkeypatch, soccer_root, "epl", kind)

    # OFF: today's failure, today's request count, no marker.
    monkeypatch.setenv(UNDERSTAT_OUTAGE_GUARD_ENV, "0")
    if kind == "teams":
        with pytest.raises(requests.exceptions.JSONDecodeError):
            _run_main(fetcher, monkeypatch, argv)
        assert len(understat.calls) == 1
    else:
        with pytest.raises(ValueError, match="playersData not available for https://understat.com/league/EPL/"):
            _run_main(fetcher, monkeypatch, argv)
        assert len(understat.calls) == 2, "OFF asks getLeagueData, then the legacy league page"
        assert "/getLeagueData/EPL/" in understat.calls[0] and "/league/EPL/" in understat.calls[1]
    assert not (soccer_root / "_understat_status.json").exists()

    # ON: one request, a named non-zero exit, a marker.
    understat.calls.clear()
    monkeypatch.delenv(UNDERSTAT_OUTAGE_GUARD_ENV, raising=False)
    with pytest.raises(SystemExit) as exc_info:
        _run_main(fetcher, monkeypatch, argv)
    message = str(exc_info.value.code)
    assert message.startswith(f"UNDERSTAT_UNAVAILABLE league=epl kind={kind} season=")
    assert "reason=non_json" in message
    assert "We will come back soon" in message
    assert "content_type='text/html'" in message
    assert len(understat.calls) == 1, "ON must not ask the legacy page on the same host"
    marker = _marker(soccer_root)
    assert marker["state"] == "down" and marker["probes"] == 1 and marker["last_reason"] == "non_json"


def test_the_failed_step_exits_NON_ZERO_with_the_name_as_its_last_line(fetcher, understat, monkeypatch, tmp_path):
    """What the manifest keeps is `return_code` and `stderr_tail`. A SystemExit
    with a string exits 1 and prints the string last."""
    out_dir = tmp_path / "soccer_source" / "epl" / "team_history"
    with pytest.raises(SystemExit) as exc_info:
        _run_main(fetcher, monkeypatch, ["--league", "epl", "--kind", "teams", "--seasons", "2026", "--out-dir", str(out_dir)])
    code = exc_info.value.code
    assert isinstance(code, str) and code  # Python exits 1 for a string code
    assert code.splitlines()[-1].startswith("UNDERSTAT_UNAVAILABLE")
    assert not (out_dir / "teams_2026.csv").exists(), "nothing may be written from an outage"


def test_an_existing_file_is_KEPT_through_an_outage(fetcher, understat, monkeypatch, tmp_path):
    out_dir = tmp_path / "soccer_source" / "epl" / "players"
    out_dir.mkdir(parents=True)
    (out_dir / "players_2026.csv").write_text("player_id,player_name\nunderstat_1,A\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="previous file is KEPT"):
        _run_main(fetcher, monkeypatch, ["--league", "epl", "--kind", "players", "--seasons", "2026", "--out-dir", str(out_dir)])
    assert (out_dir / "players_2026.csv").read_text(encoding="utf-8").startswith("player_id,player_name")


# ---------------------------------------------------------------------------
# The cooldown
# ---------------------------------------------------------------------------


def test_after_a_failed_probe_EVERY_league_fails_WITHOUT_a_request(fetcher, understat, monkeypatch, tmp_path):
    """One host-wide marker: an outage is site-wide. The other leagues and the
    other kind exit non-zero, named `cooldown`, and send nothing."""
    soccer_root = tmp_path / "soccer_source"
    with pytest.raises(SystemExit):
        _run_main(fetcher, monkeypatch, ["--league", "epl", "--kind", "teams", "--seasons", "2026",
                                         "--out-dir", str(soccer_root / "epl" / "team_history")])
    assert len(understat.calls) == 1
    for league in ("la_liga", "bundesliga", "serie_a", "ligue_1"):
        for kind, sub in (("teams", "team_history"), ("players", "players")):
            with pytest.raises(SystemExit) as exc_info:
                _run_main(fetcher, monkeypatch, ["--league", league, "--kind", kind, "--seasons", "2026",
                                                 "--out-dir", str(soccer_root / league / sub)])
            message = str(exc_info.value.code)
            assert f"league={league} kind={kind}" in message
            assert "reason=cooldown" in message and "no_request_sent" in message
            assert "last_reason=non_json" in message
    assert len(understat.calls) == 1, "the cooldown must send no request"
    assert _marker(soccer_root)["probes"] == 1


def test_a_probe_after_the_cooldown_that_still_fails_keeps_down_since(fetcher, understat, monkeypatch, tmp_path):
    soccer_root = tmp_path / "soccer_source"
    argv = ["--league", "epl", "--kind", "teams", "--seasons", "2026", "--out-dir", str(soccer_root / "epl" / "team_history")]
    with pytest.raises(SystemExit):
        _run_main(fetcher, monkeypatch, argv)
    first = _marker(soccer_root)
    later = player_history._clock() + UNDERSTAT_OUTAGE_COOLDOWN_SECONDS + 5
    monkeypatch.setattr(player_history, "_clock", lambda: later)
    with pytest.raises(SystemExit, match="reason=non_json"):
        _run_main(fetcher, monkeypatch, argv)
    second = _marker(soccer_root)
    assert len(understat.calls) == 2
    assert second["probes"] == 2 and second["down_since"] == first["down_since"]
    assert second["last_probe_epoch"] == later


def test_a_probe_after_the_cooldown_that_gets_JSON_writes_the_file_and_clears_the_outage(
    fetcher, understat, monkeypatch, tmp_path
):
    """Recovery needs no human: the first JSON after the cooldown is a normal run."""
    soccer_root = tmp_path / "soccer_source"
    teams_dir = soccer_root / "epl" / "team_history"
    with pytest.raises(SystemExit):
        _run_main(fetcher, monkeypatch, ["--league", "epl", "--kind", "teams", "--seasons", "2026", "--out-dir", str(teams_dir)])
    down_since = _marker(soccer_root)["down_since"]

    understat.mode = "up"
    later = player_history._clock() + UNDERSTAT_OUTAGE_COOLDOWN_SECONDS + 5
    monkeypatch.setattr(player_history, "_clock", lambda: later)
    assert _run_main(fetcher, monkeypatch, ["--league", "epl", "--kind", "teams", "--seasons", "2026", "--out-dir", str(teams_dir)]) == 0
    assert "2026-11-08" in (teams_dir / "teams_2026.csv").read_text(encoding="utf-8")
    marker = _marker(soccer_root)
    assert marker["state"] == "up"
    assert marker["last_outage"]["down_since"] == down_since and marker["last_outage"]["probes"] == 1

    # Up: the next league fetches at once, no cooldown left behind.
    players_dir = soccer_root / "la_liga" / "players"
    assert _run_main(fetcher, monkeypatch, ["--league", "la_liga", "--kind", "players", "--seasons", "2026", "--out-dir", str(players_dir)]) == 0
    assert (players_dir / "players_2026.csv").exists()
    assert len(understat.calls) == 3


def test_an_unreadable_marker_does_not_block_a_probe(fetcher, understat, monkeypatch, tmp_path):
    """Unknown is not down."""
    soccer_root = tmp_path / "soccer_source"
    soccer_root.mkdir(parents=True)
    (soccer_root / "_understat_status.json").write_text("{not json", encoding="utf-8")
    understat.mode = "up"
    assert _run_main(fetcher, monkeypatch, ["--league", "epl", "--kind", "teams", "--seasons", "2026",
                                            "--out-dir", str(soccer_root / "epl" / "team_history")]) == 0
    assert len(understat.calls) == 1
    assert _marker(soccer_root)["state"] == "up"


def test_OFF_ignores_an_existing_down_marker(fetcher, understat, monkeypatch, tmp_path):
    """OFF is today's code: it neither reads nor writes the marker."""
    soccer_root = tmp_path / "soccer_source"
    with pytest.raises(SystemExit):
        _run_main(fetcher, monkeypatch, ["--league", "epl", "--kind", "teams", "--seasons", "2026",
                                         "--out-dir", str(soccer_root / "epl" / "team_history")])
    before = (soccer_root / "_understat_status.json").read_text(encoding="utf-8")
    monkeypatch.setenv(UNDERSTAT_OUTAGE_GUARD_ENV, "off")
    understat.mode = "up"
    assert _run_main(fetcher, monkeypatch, ["--league", "epl", "--kind", "teams", "--seasons", "2026",
                                            "--out-dir", str(soccer_root / "epl" / "team_history")]) == 0
    assert len(understat.calls) == 2, "OFF probes regardless of the cooldown"
    assert (soccer_root / "_understat_status.json").read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# What counts as an outage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode,reason", [("connect_timeout", "unreachable"), ("http_503", "http_503")])
def test_connection_failures_and_5xx_are_outages(understat, monkeypatch, tmp_path, mode, reason):
    understat.mode = mode
    status_path = tmp_path / "_understat_status.json"
    with pytest.raises(UnderstatUnavailable) as exc_info:
        player_history.fetch_understat_league_data("epl", 2026, status_path=status_path)
    assert exc_info.value.reason == reason
    if mode == "connect_timeout":
        assert "error=ConnectTimeout" in exc_info.value.summary()
    assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "down"


def test_a_404_is_a_wrong_url_not_an_outage(understat, tmp_path):
    """A wrong league key or season must not silence the other leagues for an hour."""
    understat.mode = "http_404"
    status_path = tmp_path / "_understat_status.json"
    with pytest.raises(requests.exceptions.HTTPError):
        player_history.fetch_understat_league_data("epl", 2026, status_path=status_path)
    assert not status_path.exists()


def test_without_a_status_path_there_is_no_cooldown_but_the_outage_is_still_named(understat):
    for _ in range(2):
        with pytest.raises(UnderstatUnavailable, match="reason=non_json"):
            player_history.fetch_understat_league_data("epl", 2026)
    assert len(understat.calls) == 2


# ---------------------------------------------------------------------------
# The marker lives where every role reads the data
# ---------------------------------------------------------------------------


def test_both_producer_steps_share_ONE_marker_in_the_soccer_data_root(orchestrator, fetcher, monkeypatch, tmp_path):
    soccer_root = tmp_path / "soccer_source"
    paths = set()
    for league in ("epl", "serie_a"):
        for kind in ("teams", "players"):
            argv = _step_argv(orchestrator, monkeypatch, soccer_root, league, kind)
            out_dir = Path(argv[argv.index("--out-dir") + 1])
            paths.add(fetcher.understat_status_path(out_dir))
    assert paths == {(soccer_root / "_understat_status.json").resolve()}
