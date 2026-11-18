"""Understat outage guard (lane `understat-fetch-failures`, 2026-11-18).

MEASURED FIRST. From 2026-11-03 2:54 PM CST every understat.com URL answers
HTTP 200 with the same 26,719-byte "We will come back soon" HTML page -- from
the fleet and from another network. Before that the name did not resolve and
connections timed out (11-01 6:34 PM .. 11-03 3:06 PM CST). The big-5
`soccer_<league>_history_current` / `_players` steps met that as
`requests.JSONDecodeError` and `playersData not available` on every soccer run:
5,152 of 5,152 steps failed in 800 runs (fleet manifests 11-10..11-20).

TWO SWITCHES, split on the betting-change question (`.syndicate/betting_change_
windows.md`):

* NAMING (`SYNDICATE_UNDERSTAT_OUTAGE_GUARD`, absent = ON) names the outage and
  records it, and must send EXACTLY OFF's requests and write EXACTLY OFF's files
  under every response -- `test_NAMING_writes_exactly_what_OFF_writes` is what
  makes "not a betting change" a tested claim rather than an argument.
* COOLDOWN (`SYNDICATE_UNDERSTAT_OUTAGE_COOLDOWN`, absent = OFF) sends no
  request for an hour after a failed probe and skips the legacy page. It can
  change the sim's inputs (a lagged refresh on recovery), so it is default-off.

Both have an off != on test, and the naming one drives the fetcher with the REAL
refresh step's command line. A step that cannot fetch STILL FAILS (non-zero
exit, named last line) under every switch setting.

The maintenance page below is a trimmed stand-in with the same shape as the one
served (doctype, errors.css, title, one sentence), not a copy of it.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import requests

from syndicate.features.soccer.ingestion import player_history
from syndicate.features.soccer.ingestion.player_history import UNDERSTAT_OUTAGE_COOLDOWN_ENV
from syndicate.features.soccer.ingestion.player_history import UNDERSTAT_OUTAGE_COOLDOWN_SECONDS
from syndicate.features.soccer.ingestion.player_history import UNDERSTAT_OUTAGE_GUARD_ENV
from syndicate.features.soccer.ingestion.player_history import UnderstatUnavailable
from syndicate.features.soccer.ingestion.player_history import understat_outage_cooldown_enabled
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

PLAYERS = [
    {
        "id": "1", "player_name": "A Forward", "games": "11", "time": "900", "goals": "6",
        "xG": "5.5", "assists": "2", "xA": "1.9", "shots": "30", "key_passes": "12",
        "yellow_cards": "1", "red_cards": "0", "position": "F S", "team_title": "Arsenal",
        "npg": "6", "npxG": "5.5", "xGChain": "7", "xGBuildup": "2",
    }
]

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
    "players": PLAYERS,
    "dates": [],
}

#: A legacy league page that still embeds playersData, escaped the way the
#: page did (`\x22` for quotes, decoded by `unicode_escape`).
LEGACY_PAGE_WITH_PLAYERS = (
    "<html><script>var playersData = JSON.parse('"
    + json.dumps(PLAYERS).replace('"', "\\x22")
    + "');</script></html>"
)


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
        legacy = "/league/" in url
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
        if self.mode == "legacy_only":
            # getLeagueData unavailable, but the legacy page still carries playersData.
            return _response(url, body=LEGACY_PAGE_WITH_PLAYERS if legacy else MAINTENANCE_HTML)
        if self.mode == "json_without_players":
            if legacy:
                return _response(url, body=LEGACY_PAGE_WITH_PLAYERS)
            return _response(url, body=json.dumps({"teams": {}, "players": []}), content_type="application/json")
        raise AssertionError(self.mode)


@pytest.fixture(autouse=True)
def _switch_defaults(monkeypatch):
    """Every test starts from the production defaults (both env keys absent:
    naming ON, cooldown OFF)."""
    monkeypatch.delenv(UNDERSTAT_OUTAGE_GUARD_ENV, raising=False)
    monkeypatch.delenv(UNDERSTAT_OUTAGE_COOLDOWN_ENV, raising=False)


@pytest.fixture
def understat(monkeypatch):
    fake = FakeUnderstat()
    monkeypatch.setattr(player_history.requests, "get", fake)
    return fake


@pytest.fixture
def cooldown_on(monkeypatch):
    monkeypatch.setenv(UNDERSTAT_OUTAGE_COOLDOWN_ENV, "1")


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


def _argv(soccer_root: Path, league: str, kind: str) -> list[str]:
    sub = {"teams": "team_history", "players": "players"}[kind]
    return ["--league", league, "--kind", kind, "--seasons", "2026", "--out-dir", str(soccer_root / league / sub)]


def _run_main(fetcher, monkeypatch, argv: list[str]):
    monkeypatch.setattr(sys, "argv", ["fetch_soccer_history_local.py", *argv])
    return fetcher.main()


def _marker(soccer_root: Path) -> dict:
    return json.loads((soccer_root / "_understat_status.json").read_text(encoding="utf-8"))


def _later(seconds: float = UNDERSTAT_OUTAGE_COOLDOWN_SECONDS + 5) -> float:
    return player_history._clock() + seconds


# ---------------------------------------------------------------------------
# The switches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [(None, True), ("", True), ("1", True), ("on", True),
                                            ("0", False), ("false", False), ("off", False), ("NO", False)])
def test_naming_is_on_unless_switched_off(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(UNDERSTAT_OUTAGE_GUARD_ENV, raising=False)
    else:
        monkeypatch.setenv(UNDERSTAT_OUTAGE_GUARD_ENV, value)
    assert understat_outage_guard_enabled() is expected


@pytest.mark.parametrize("cooldown,guard,expected", [(None, None, False), ("", None, False), ("0", None, False),
                                                     ("1", None, True), ("on", None, True), ("YES", None, True),
                                                     ("1", "0", False)])
def test_cooldown_is_OFF_unless_switched_on_and_never_without_naming(monkeypatch, cooldown, guard, expected):
    for key, value in ((UNDERSTAT_OUTAGE_COOLDOWN_ENV, cooldown), (UNDERSTAT_OUTAGE_GUARD_ENV, guard)):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    assert understat_outage_cooldown_enabled() is expected


# ---------------------------------------------------------------------------
# NAMING: off != on through the real step command, and EQUAL in what it writes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["teams", "players"])
def test_OFF_differs_from_NAMING_on_the_maintenance_page_through_the_real_step_command(
    orchestrator, fetcher, understat, monkeypatch, tmp_path, kind
):
    """The reachability test. Same page, same argv (the producer step's own),
    two outcomes: OFF fails exactly as the fleet's manifests show; the default
    (naming) names the outage. Both FAIL, and both send the same requests."""
    soccer_root = tmp_path / "soccer_source"
    argv = _step_argv(orchestrator, monkeypatch, soccer_root, "epl", kind)

    monkeypatch.setenv(UNDERSTAT_OUTAGE_GUARD_ENV, "0")
    if kind == "teams":
        with pytest.raises(requests.exceptions.JSONDecodeError):
            _run_main(fetcher, monkeypatch, argv)
    else:
        with pytest.raises(ValueError, match="playersData not available for https://understat.com/league/EPL/"):
            _run_main(fetcher, monkeypatch, argv)
    off_calls = list(understat.calls)
    assert len(off_calls) == (1 if kind == "teams" else 2)
    assert not (soccer_root / "_understat_status.json").exists()

    understat.calls.clear()
    monkeypatch.delenv(UNDERSTAT_OUTAGE_GUARD_ENV, raising=False)
    with pytest.raises(SystemExit) as exc_info:
        _run_main(fetcher, monkeypatch, argv)
    message = str(exc_info.value.code)
    assert message.startswith(f"UNDERSTAT_UNAVAILABLE league=epl kind={kind} season=")
    assert "reason=non_json" in message and "We will come back soon" in message
    assert "content_type='text/html'" in message
    if kind == "players":
        assert "legacy_page=https://understat.com/league/EPL/" in message and "legacy_error=ValueError" in message
    assert understat.calls == off_calls, "naming must send exactly OFF's requests"
    marker = _marker(soccer_root)
    assert marker["state"] == "down" and marker["probes"] == 1 and marker["last_reason"] == "non_json"


_ALL_MODES = ["maintenance", "connect_timeout", "http_503", "http_404", "up", "legacy_only", "json_without_players"]


def _outcome(fetcher, understat, monkeypatch, soccer_root: Path, kind: str):
    understat.calls.clear()
    try:
        rc = _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", kind))
        failed = False
    except (SystemExit, Exception) as exc:  # noqa: BLE001 -- the TYPE is allowed to differ, the outcome is not
        rc, failed = exc, True
    sub = {"teams": "team_history", "players": "players"}[kind]
    written = soccer_root / "epl" / sub / f"{kind}_2026.csv"
    content = written.read_bytes() if written.exists() else None
    return failed, list(understat.calls), content, rc


@pytest.mark.parametrize("kind", ["teams", "players"])
@pytest.mark.parametrize("mode", _ALL_MODES)
def test_NAMING_writes_exactly_what_OFF_writes(fetcher, understat, monkeypatch, tmp_path, mode, kind):
    """THE "NOT A BETTING CHANGE" CLAIM, TESTED. Under every response Understat
    can give -- maintenance page, connect timeout, 5xx, 404, healthy, a legacy
    page that still carries playersData, JSON without players -- the default
    switch setting sends the same requests and writes the same bytes as OFF,
    and fails exactly when OFF fails. Only a failure's name may differ."""
    understat.mode = mode
    monkeypatch.setenv(UNDERSTAT_OUTAGE_GUARD_ENV, "0")
    off = _outcome(fetcher, understat, monkeypatch, tmp_path / "off" / "soccer_source", kind)
    monkeypatch.delenv(UNDERSTAT_OUTAGE_GUARD_ENV, raising=False)
    on = _outcome(fetcher, understat, monkeypatch, tmp_path / "on" / "soccer_source", kind)
    assert on[0] == off[0], f"fails={on[0]} vs OFF {off[0]} ({on[3]!r} / {off[3]!r})"
    assert on[1] == off[1], "different requests"
    assert on[2] == off[2], "different file content"
    # The fixture can write: a healthy JSON, or (players only -- teams have no
    # legacy page) a legacy page that still carries playersData.
    if mode == "up" or (mode in ("legacy_only", "json_without_players") and kind == "players"):
        assert not on[0] and on[2] is not None, "a healthy response must still write"


def test_the_failed_step_exits_NON_ZERO_with_the_name_as_its_last_line(fetcher, understat, monkeypatch, tmp_path):
    """What the manifest keeps is `return_code` and `stderr_tail`. A SystemExit
    with a string exits 1 and prints the string last."""
    soccer_root = tmp_path / "soccer_source"
    with pytest.raises(SystemExit) as exc_info:
        _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams"))
    code = exc_info.value.code
    assert isinstance(code, str) and code  # Python exits 1 for a string code
    assert code.splitlines()[-1].startswith("UNDERSTAT_UNAVAILABLE")
    assert not (soccer_root / "epl" / "team_history" / "teams_2026.csv").exists(), "nothing may be written from an outage"


def test_an_existing_file_is_KEPT_through_an_outage(fetcher, understat, monkeypatch, tmp_path):
    out_dir = tmp_path / "soccer_source" / "epl" / "players"
    out_dir.mkdir(parents=True)
    (out_dir / "players_2026.csv").write_text("player_id,player_name\nunderstat_1,A\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="previous file is KEPT"):
        _run_main(fetcher, monkeypatch, _argv(tmp_path / "soccer_source", "epl", "players"))
    assert (out_dir / "players_2026.csv").read_text(encoding="utf-8").startswith("player_id,player_name")


def test_naming_alone_has_NO_cooldown_every_run_probes(fetcher, understat, monkeypatch, tmp_path):
    """Default switches: the marker is a RECORD (probes counts the requests), not a gate."""
    soccer_root = tmp_path / "soccer_source"
    for _ in range(3):
        with pytest.raises(SystemExit, match="reason=non_json"):
            _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams"))
    assert len(understat.calls) == 3
    assert _marker(soccer_root)["probes"] == 3


# ---------------------------------------------------------------------------
# COOLDOWN (default OFF): off != on, then its behaviour
# ---------------------------------------------------------------------------


def test_COOLDOWN_off_differs_from_on(fetcher, understat, monkeypatch, tmp_path):
    """Second reachability test: with a fresh failed probe on the marker, OFF
    probes again; ON sends nothing and names the cooldown."""
    soccer_root = tmp_path / "soccer_source"
    with pytest.raises(SystemExit):
        _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams"))
    assert len(understat.calls) == 1
    with pytest.raises(SystemExit, match="reason=non_json"):
        _run_main(fetcher, monkeypatch, _argv(soccer_root, "la_liga", "teams"))
    assert len(understat.calls) == 2, "cooldown OFF: the second league probes"
    monkeypatch.setenv(UNDERSTAT_OUTAGE_COOLDOWN_ENV, "1")
    with pytest.raises(SystemExit, match="reason=cooldown.*no_request_sent"):
        _run_main(fetcher, monkeypatch, _argv(soccer_root, "serie_a", "teams"))
    assert len(understat.calls) == 2, "cooldown ON: no request"


def test_with_cooldown_players_skips_the_legacy_page(fetcher, understat, monkeypatch, tmp_path, cooldown_on):
    with pytest.raises(SystemExit) as exc_info:
        _run_main(fetcher, monkeypatch, _argv(tmp_path / "soccer_source", "epl", "players"))
    assert len(understat.calls) == 1 and "/getLeagueData/" in understat.calls[0]
    assert "legacy_page" not in str(exc_info.value.code)


def test_after_a_failed_probe_EVERY_league_fails_WITHOUT_a_request(fetcher, understat, monkeypatch, tmp_path, cooldown_on):
    """One host-wide marker: an outage is site-wide. The other leagues and the
    other kind exit non-zero, named `cooldown`, and send nothing."""
    soccer_root = tmp_path / "soccer_source"
    with pytest.raises(SystemExit):
        _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams"))
    assert len(understat.calls) == 1
    for league in ("la_liga", "bundesliga", "serie_a", "ligue_1"):
        for kind in ("teams", "players"):
            with pytest.raises(SystemExit) as exc_info:
                _run_main(fetcher, monkeypatch, _argv(soccer_root, league, kind))
            message = str(exc_info.value.code)
            assert f"league={league} kind={kind}" in message
            assert "reason=cooldown" in message and "no_request_sent" in message
            assert "last_reason=non_json" in message
    assert len(understat.calls) == 1, "the cooldown must send no request"
    assert _marker(soccer_root)["probes"] == 1


def test_a_probe_after_the_cooldown_that_still_fails_keeps_down_since(fetcher, understat, monkeypatch, tmp_path, cooldown_on):
    soccer_root = tmp_path / "soccer_source"
    with pytest.raises(SystemExit):
        _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams"))
    first = _marker(soccer_root)
    later = _later()
    monkeypatch.setattr(player_history, "_clock", lambda: later)
    with pytest.raises(SystemExit, match="reason=non_json"):
        _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams"))
    second = _marker(soccer_root)
    assert len(understat.calls) == 2
    assert second["probes"] == 2 and second["down_since"] == first["down_since"]
    assert second["last_probe_epoch"] == later


def test_a_probe_after_the_cooldown_that_gets_JSON_writes_the_file_and_clears_the_outage(
    fetcher, understat, monkeypatch, tmp_path, cooldown_on
):
    """Recovery needs no human: the first JSON after the cooldown is a normal run."""
    soccer_root = tmp_path / "soccer_source"
    with pytest.raises(SystemExit):
        _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams"))
    down_since = _marker(soccer_root)["down_since"]

    understat.mode = "up"
    later = _later()
    monkeypatch.setattr(player_history, "_clock", lambda: later)
    assert _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams")) == 0
    assert "2026-11-08" in (soccer_root / "epl" / "team_history" / "teams_2026.csv").read_text(encoding="utf-8")
    marker = _marker(soccer_root)
    assert marker["state"] == "up"
    assert marker["last_outage"]["down_since"] == down_since and marker["last_outage"]["probes"] == 1

    # Up: the next league fetches at once, no cooldown left behind.
    assert _run_main(fetcher, monkeypatch, _argv(soccer_root, "la_liga", "players")) == 0
    assert (soccer_root / "la_liga" / "players" / "players_2026.csv").exists()
    assert len(understat.calls) == 3


def test_an_unreadable_marker_does_not_block_a_probe(fetcher, understat, monkeypatch, tmp_path, cooldown_on):
    """Unknown is not down."""
    soccer_root = tmp_path / "soccer_source"
    soccer_root.mkdir(parents=True)
    (soccer_root / "_understat_status.json").write_text("{not json", encoding="utf-8")
    understat.mode = "up"
    assert _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams")) == 0
    assert len(understat.calls) == 1
    assert _marker(soccer_root)["state"] == "up"


def test_OFF_ignores_an_existing_down_marker(fetcher, understat, monkeypatch, tmp_path, cooldown_on):
    """Naming OFF is today's code: it neither reads nor writes the marker, even
    with the cooldown key set."""
    soccer_root = tmp_path / "soccer_source"
    with pytest.raises(SystemExit):
        _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams"))
    before = (soccer_root / "_understat_status.json").read_text(encoding="utf-8")
    monkeypatch.setenv(UNDERSTAT_OUTAGE_GUARD_ENV, "off")
    understat.mode = "up"
    assert _run_main(fetcher, monkeypatch, _argv(soccer_root, "epl", "teams")) == 0
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
    """A wrong league key or season is not an outage, and is not recorded as one."""
    understat.mode = "http_404"
    status_path = tmp_path / "_understat_status.json"
    with pytest.raises(requests.exceptions.HTTPError):
        player_history.fetch_understat_league_data("epl", 2026, status_path=status_path)
    assert not status_path.exists()


def test_without_a_status_path_there_is_no_marker_but_the_outage_is_still_named(understat, cooldown_on):
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
