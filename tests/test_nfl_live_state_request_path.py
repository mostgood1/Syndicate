"""NFL game state and player boxes make NO ESPN call inside a web request (lane `nfl-request-path-espn`, 2026-11-27).

THE INCIDENT. Web fetched ESPN's NFL scoreboard and per-game summaries inside requests: 40
`operation=nfl_espn_game_state_fetch` and 35 `operation=nfl_espn_player_box_fetch` lines on 11-27 between
00:00Z and 16:39Z, mostly from past-date `/api/board/game-chips` builds. When the host's network is down
each GET stalls in DNS inside the request (game-chips requests took 61-113 s on 11-26).

THE FIX. The workers, which already fetch both for the current week outside any request, keep what they
fetch: a worker record (keyvalue on the fleet) and, once a week or a game is final, a disk archive. Inside a
web request the readers read those and never fetch. Outside a request nothing is read differently.

The ESPN call is caught at the NETWORK layer (`urllib.request.urlopen`), not at a helper, so a fetch by any
route fails these tests. Reachability first: with `SYNDICATE_REQUEST_PATH_ESPN_FETCH=on`, the same request
DOES fetch (off != on).
"""

from __future__ import annotations

import io
import json
import urllib.request
from typing import Any

import pytest
from flask import Flask

from syndicate.features.nfl import live_game_state as lgs
from syndicate.features.nfl import live_player_box as lpb

SEASON, WEEK = 2026, 8
_APP = Flask(__name__)

# conftest's `_no_live_espn_calls_in_tests` stubs `_fetch_scoreboard` for every test. These tests catch
# ESPN one layer lower, at `urlopen`, so they put the real function back (captured at import, before any
# fixture runs) and stub the socket instead.
_REAL_FETCH_SCOREBOARD = lgs._fetch_scoreboard


def _event(event_id: str, away: str, home: str, *, final: bool, away_score: str = "17", home_score: str = "24") -> dict[str, Any]:
    state = "post" if final else "in"
    return {
        "id": event_id,
        "date": "2026-10-25T17:00Z",
        "status": {"period": 4, "displayClock": "0:00" if final else "8:05",
                   "type": {"state": state, "completed": final, "shortDetail": "Final" if final else "8:05 - 4th"}},
        "competitions": [{"competitors": [
            {"homeAway": "away", "score": away_score, "team": {"abbreviation": away, "id": "1"},
             "linescores": [{"value": 7, "period": 1}, {"value": 10, "period": 2}]},
            {"homeAway": "home", "score": home_score, "team": {"abbreviation": home, "id": "2"},
             "linescores": [{"value": 14, "period": 1}, {"value": 10, "period": 2}]},
        ]}],
    }


def _summary(name: str = "Drake Maye", team: str = "NE") -> dict[str, Any]:
    return {"boxscore": {"players": [{"team": {"abbreviation": team}, "statistics": [
        {"name": "passing", "keys": ["completions/passingAttempts", "passingYards", "passingTouchdowns"],
         "athletes": [{"athlete": {"id": "9", "displayName": name}, "stats": ["23/33", "281", "2"]}]},
    ]}]}}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Filesystem backend under conftest's per-test reports root; every module cache and archive set empty."""
    monkeypatch.delenv("SYNDICATE_REQUEST_PATH_ESPN_FETCH", raising=False)
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "filesystem")
    monkeypatch.setattr(lgs, "_fetch_scoreboard", _REAL_FETCH_SCOREBOARD)

    def _clear():
        with lgs._cache_lock:
            lgs._cache.clear()
        with lgs._archived_lock:
            lgs._archived_weeks.clear()
        with lpb._cache_lock:
            lpb._cache.clear()
        with lpb._archived_lock:
            lpb._archived_events.clear()

    _clear()
    yield
    _clear()


def _espn(monkeypatch, *, events: list[dict[str, Any]] | None = None, summary: dict[str, Any] | None = None) -> dict[str, int]:
    """A network-layer ESPN stand-in that counts every call and answers the given payloads."""
    calls = {"scoreboard": 0, "summary": 0}

    def fake_urlopen(request, *_args, **_kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "/scoreboard" in url:
            calls["scoreboard"] += 1
            if events is None:
                raise OSError("ESPN is unreachable in this test")
            return _Response(json.dumps({"events": events}).encode("utf-8"))
        calls["summary"] += 1
        if summary is None:
            raise OSError("ESPN is unreachable in this test")
        return _Response(json.dumps(summary).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def _index_in_a_request() -> dict[str, dict[str, Any]]:
    with _APP.test_request_context("/api/board/game-chips?date=2026-10-25&sports=nfl"):
        return lgs.nfl_game_state_index(SEASON, WEEK, seasontype=lgs.SEASONTYPE_REGULAR)


def _boxes_in_a_request(events: list[tuple[str, bool]]) -> dict[str, list[dict[str, Any]]]:
    with _APP.test_request_context("/api/board/game-chips?date=2026-10-25&sports=nfl"):
        return lpb.nfl_player_box_index(events)


def _clear_caches() -> None:
    with lgs._cache_lock:
        lgs._cache.clear()
    with lpb._cache_lock:
        lpb._cache.clear()


# --------------------------------------------------------------------------- game state


def test_off_is_not_on_the_switch_brings_the_request_path_fetch_back(monkeypatch, capfd):
    """REACHABILITY. With nothing stored the request makes no ESPN call; switched on, it does."""
    calls = _espn(monkeypatch, events=[_event("401", "NE", "SEA", final=True)])

    assert _index_in_a_request() == {}
    assert calls["scoreboard"] == 0
    assert "NFL_GAME_STATE_REQUEST_NO_FETCH season=2026 seasontype=2 week=8" in capfd.readouterr().out

    monkeypatch.setenv("SYNDICATE_REQUEST_PATH_ESPN_FETCH", "on")
    index = _index_in_a_request()
    assert calls["scoreboard"] == 1, "the switch must restore the request-path fetch"
    assert index["401"]["home_pts"] == 24


def test_a_request_that_fetches_with_the_switch_on_writes_nothing(monkeypatch):
    _espn(monkeypatch, events=[_event("401", "NE", "SEA", final=True)])
    monkeypatch.setenv("SYNDICATE_REQUEST_PATH_ESPN_FETCH", "on")
    _index_in_a_request()
    assert not lgs.record_path(SEASON, 2, WEEK).exists()
    assert not lgs.final_archive_path(SEASON, 2, WEEK).exists()


def test_the_worker_fetch_is_kept_and_a_request_serves_it_with_no_espn_call(monkeypatch, capfd):
    """A worker (no request context) fetches as before and writes the record; the web then reads it."""
    calls = _espn(monkeypatch, events=[_event("401", "NE", "SEA", final=False, away_score="7", home_score="3")])

    worker_index = lgs.nfl_game_state_index(SEASON, WEEK, seasontype=lgs.SEASONTYPE_REGULAR)
    assert calls["scoreboard"] == 1 and worker_index["401"]["in_progress"] is True
    assert lgs.record_path(SEASON, 2, WEEK).exists()
    assert not lgs.final_archive_path(SEASON, 2, WEEK).exists(), "a moving week is never archived"

    _clear_caches()
    capfd.readouterr()
    index = _index_in_a_request()
    assert calls["scoreboard"] == 1, "the request must not fetch"
    assert set(index) == set(worker_index)
    assert index["401"]["away_pts"] == 7 and index["NE@SEA"]["clock"] == "8:05"
    assert "NFL_GAME_STATE_FROM_WORKER season=2026 seasontype=2 week=8 games=1" in capfd.readouterr().out


def test_an_all_final_week_is_archived_and_served_from_disk_after_the_record_is_gone(monkeypatch, capfd):
    calls = _espn(monkeypatch, events=[_event("401", "NE", "SEA", final=True), _event("402", "DAL", "NYG", final=True)])
    lgs.nfl_game_state_index(SEASON, WEEK, seasontype=lgs.SEASONTYPE_REGULAR)
    assert lgs.final_archive_path(SEASON, 2, WEEK).exists()

    lgs.record_path(SEASON, 2, WEEK).unlink()  # the keyvalue record lost (a Redis restart, say)
    _clear_caches()
    capfd.readouterr()
    index = _index_in_a_request()
    assert calls["scoreboard"] == 1
    assert index["402"]["final"] is True and index["DAL@NYG"]["home_pts"] == 24
    assert "NFL_GAME_STATE_FROM_ARCHIVE season=2026 seasontype=2 week=8 games=2" in capfd.readouterr().out


def test_an_archive_holding_an_unfinished_game_is_refused(monkeypatch):
    """An archive must never pin a moving week; with no record the request then knows nothing, and does not fetch."""
    calls = _espn(monkeypatch, events=None)
    path = lgs.final_archive_path(SEASON, 2, WEEK)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"games": [{"event_id": "401", "away_abbr": "NE", "home_abbr": "SEA", "final": True},
                                          {"event_id": "402", "away_abbr": "DAL", "home_abbr": "NYG", "final": False}]}))
    assert _index_in_a_request() == {}
    assert calls["scoreboard"] == 0


def test_an_archived_final_score_reaches_the_card(monkeypatch):
    """What the grader needs from a past date: the card carries the final score, read with no ESPN call."""
    calls = _espn(monkeypatch, events=[_event("401", "NE", "SEA", final=True)])
    lgs.nfl_game_state_index(SEASON, WEEK, seasontype=lgs.SEASONTYPE_REGULAR)
    lgs.record_path(SEASON, 2, WEEK).unlink()
    _clear_caches()

    card = {"gamePk": "2026_08_NE_SEA", "away": {"abbr": "NE"}, "home": {"abbr": "SEA"}, "status": "Week 8"}
    coverage = lgs.attach_nfl_live_game_state([card], _index_in_a_request())
    assert calls["scoreboard"] == 1
    assert coverage["final"] == 1
    assert card["away"]["score"] == 17 and card["home"]["score"] == 24
    assert card["live_state"]["final"] is True and card["status"] == "Final"


def test_the_backfill_writes_only_the_archive(monkeypatch):
    import scripts.backfill_nfl_final_archives as backfill

    _espn(monkeypatch, events=[_event("401", "NE", "SEA", final=True)], summary=_summary())
    result = backfill.backfill_week(SEASON, 2, WEEK, pause=0)
    assert result["archived"] is True and result["boxes_archived"] == 1
    assert lgs.final_archive_path(SEASON, 2, WEEK).exists() and lpb.final_archive_path("401").exists()
    assert not lgs.record_path(SEASON, 2, WEEK).exists() and not lpb.record_path("401").exists()


def test_the_backfill_never_archives_a_week_still_moving(monkeypatch):
    import scripts.backfill_nfl_final_archives as backfill

    calls = _espn(monkeypatch, events=[_event("401", "NE", "SEA", final=True), _event("402", "DAL", "NYG", final=False)],
                  summary=_summary())
    result = backfill.backfill_week(SEASON, 2, WEEK, pause=0)
    assert result["archived"] is False
    assert not lgs.final_archive_path(SEASON, 2, WEEK).exists()
    assert calls["summary"] == 0


def test_the_week_file_name_carries_no_date_token_so_the_store_gives_it_no_ttl():
    from syndicate.features.shared import refresh_state_store as store

    for week in (1, 10, 12, 18):
        assert store._default_keyvalue_ttl_seconds(lgs.record_path(2026, 2, week)) is None
    assert store._default_keyvalue_ttl_seconds(lpb.record_path("401772030")) is None


# --------------------------------------------------------------------------- player box


def test_player_box_off_is_not_on(monkeypatch, capfd):
    calls = _espn(monkeypatch, summary=_summary())

    assert _boxes_in_a_request([("401", True)]) == {}
    assert calls["summary"] == 0
    assert "NFL_PLAYER_BOX_REQUEST_NO_FETCH requested=1 archive=0 worker=0 absent=1" in capfd.readouterr().out

    monkeypatch.setenv("SYNDICATE_REQUEST_PATH_ESPN_FETCH", "on")
    boxes = _boxes_in_a_request([("401", True)])
    assert calls["summary"] == 1, "the switch must restore the request-path fetch"
    assert boxes["401"][0]["pass_yards"] == 281.0
    assert not lpb.record_path("401").exists(), "a request never writes"


def test_a_worker_box_read_is_kept_and_served_to_a_request(monkeypatch):
    calls = _espn(monkeypatch, summary=_summary())

    worker = lpb.nfl_player_box_index([("401", False), ("402", True)])
    assert calls["summary"] == 2
    assert lpb.record_path("401").exists() and lpb.record_path("402").exists()
    assert not lpb.final_archive_path("401").exists(), "a live box is never archived"
    assert lpb.final_archive_path("402").exists()

    _clear_caches()
    lpb.record_path("402").unlink()  # the final box survives the record's loss
    boxes = _boxes_in_a_request([("401", False), ("402", True), ("403", False)])
    assert calls["summary"] == 2, "the request must not fetch"
    assert boxes == {"401": worker["401"], "402": worker["402"]}
    assert "403" not in boxes, "an unread box stays absent, never an empty list"


def test_a_failed_worker_read_writes_nothing(monkeypatch):
    _espn(monkeypatch, summary=None)
    assert lpb.nfl_player_box_index([("401", True)]) == {}
    assert not lpb.record_path("401").exists() and not lpb.final_archive_path("401").exists()
