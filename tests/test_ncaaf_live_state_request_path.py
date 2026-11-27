"""NCAAF live state makes NO ESPN call inside a web request (lane `game-chips-request-path-espn`, 2026-11-27).

THE INCIDENT. The 8:15 AM play-cards grader asks `/api/board/game-chips` for every date since 10-16. A past
date has no published chip artifact, so web builds the chips inline, and NCAAF's live record lives in the
keyvalue store under a 10-day TTL: for any older date `ncaaf_game_state_index` found nothing and fetched
ESPN for each date of the week, serially, inside the request. On 11-26 the host's network was down, every
GET stalled in DNS, and those requests took 61-113 s; one outlived a worker's recycle and got it timed out.

THE FIX. The producer also writes a date whose games are all final to a disk archive with no TTL, the
reader reads it, and inside a web request the fallback never fetches: a stale live record is served, and
with nothing at all the date is state unknown. Outside a request (the workers) nothing changes.

The ESPN call is caught at the NETWORK layer (`urllib.request.urlopen`), not at a helper, so a fetch by any
route fails these tests. Reachability first: with `SYNDICATE_REQUEST_PATH_ESPN_FETCH=on`, the same request
DOES fetch (off != on).
"""

from __future__ import annotations

import time
import urllib.request
from typing import Any

import pytest
from flask import Flask

import scripts.poll_ncaaf_live_state as poller
from syndicate.features.ncaaf import live_game_state as lgs

DATE = "2026-10-17"  # a Saturday more than ten days back: its live record has aged out

_APP = Flask(__name__)


def _final_game(away: str, home: str) -> dict[str, Any]:
    return {"away_id": away, "home_id": home, "away_score": 17, "home_score": 24, "final": True, "in_progress": False}


def _live_game(away: str, home: str) -> dict[str, Any]:
    return {"away_id": away, "home_id": home, "away_score": 7, "home_score": 3, "final": False, "in_progress": True}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("SYNDICATE_REQUEST_PATH_ESPN_FETCH", raising=False)
    monkeypatch.delenv("SYNDICATE_NCAAF_LIVE_STATE_MAX_AGE_SECONDS", raising=False)
    with lgs._cache_lock:
        lgs._cache.clear()
    yield
    with lgs._cache_lock:
        lgs._cache.clear()


def _stores(monkeypatch, *, live: Any = None, archive: Any = None) -> dict[str, int]:
    """Path-aware store stub, and a network-layer ESPN counter that answers an empty scoreboard."""
    calls = {"espn": 0}

    def fake_read(path):
        return archive if "live_state_final" in str(path) else live

    def fake_urlopen(*_args, **_kwargs):
        calls["espn"] += 1
        raise OSError("ESPN is unreachable in this test")

    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.read_json_file", fake_read)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def _index_in_a_request(dates=(DATE,)):
    sources: dict[str, str] = {}
    with _APP.test_request_context("/api/board/game-chips?date=" + DATE):
        index = lgs.ncaaf_game_state_index(list(dates), sources=sources)
    return index, sources


def test_off_is_not_on_the_switch_brings_the_request_path_fetch_back(monkeypatch):
    """REACHABILITY. With no record and no archive, the request makes no ESPN call; switched on, it does."""
    calls = _stores(monkeypatch, live=None, archive=None)
    index, sources = _index_in_a_request()
    assert calls["espn"] == 0
    assert index == {}
    assert sources == {DATE: "none"}

    monkeypatch.setenv("SYNDICATE_REQUEST_PATH_ESPN_FETCH", "on")
    index, sources = _index_in_a_request()
    assert calls["espn"] == 1, "the switch must restore the request-path fetch"
    assert sources == {DATE: "fetch"}


def test_an_aged_out_date_is_read_from_the_final_archive_with_no_espn_call(monkeypatch):
    archive = {"date": DATE, "fetched_at": time.time() - 40 * 86400,
               "games": [_final_game("153", "2628"), _final_game("99", "100")]}
    calls = _stores(monkeypatch, live=None, archive=archive)

    index, sources = _index_in_a_request()

    assert calls["espn"] == 0
    assert sources == {DATE: "archive"}
    assert set(index) == {"153@2628", "99@100"}
    assert index["153@2628"]["home_score"] == 24 and index["153@2628"]["final"] is True


def test_the_archive_serves_the_workers_too_so_they_stop_refetching_settled_dates(monkeypatch):
    archive = {"date": DATE, "games": [_final_game("1", "2")]}
    calls = _stores(monkeypatch, live=None, archive=archive)
    sources: dict[str, str] = {}
    index = lgs.ncaaf_game_state_index([DATE], sources=sources)  # no request context: a worker
    assert calls["espn"] == 0
    assert sources == {DATE: "archive"} and "1@2" in index


def test_an_archive_holding_an_unfinished_game_is_refused(monkeypatch, capfd):
    """An archive must never pin a moving date; in a request that leaves the date unknown, not fetched."""
    archive = {"date": DATE, "games": [_final_game("1", "2"), _live_game("3", "4")]}
    calls = _stores(monkeypatch, live=None, archive=archive)
    index, sources = _index_in_a_request()
    assert calls["espn"] == 0
    assert index == {} and sources == {DATE: "none"}
    assert "NCAAF_LIVE_STATE_REQUEST_NO_FETCH" in capfd.readouterr().out


def test_an_empty_archived_date_is_a_complete_answer(monkeypatch):
    calls = _stores(monkeypatch, live=None, archive={"date": DATE, "games": []})
    index, sources = _index_in_a_request()
    assert calls["espn"] == 0 and index == {} and sources == {DATE: "archive"}


def test_in_a_request_a_stale_live_record_is_served_rather_than_refetched(monkeypatch, capfd):
    stale = {"date": DATE, "fetched_at": time.time() - 10_000, "games": [_live_game("1", "2")]}
    calls = _stores(monkeypatch, live=stale, archive=None)

    index, sources = _index_in_a_request()

    assert calls["espn"] == 0
    assert sources == {DATE: "stale_worker"}
    assert index["1@2"]["in_progress"] is True
    assert "NCAAF_LIVE_STATE_RECORD_STALE_SERVED" in capfd.readouterr().out


def test_outside_a_request_the_workers_still_fetch_a_stale_live_date(monkeypatch):
    """The workers' behaviour is unchanged: there a stale moving record still falls back to ESPN."""
    stale = {"date": DATE, "fetched_at": time.time() - 10_000, "games": [_live_game("1", "2")]}
    calls = _stores(monkeypatch, live=stale, archive=None)
    sources: dict[str, str] = {}
    lgs.ncaaf_game_state_index([DATE], sources=sources)
    assert calls["espn"] == 1 and sources == {DATE: "fetch"}


def test_a_fresh_live_record_still_wins_over_the_archive(monkeypatch):
    live = {"date": DATE, "fetched_at": time.time(), "games": [_live_game("1", "2")]}
    archive = {"date": DATE, "games": [_final_game("1", "2")]}
    calls = _stores(monkeypatch, live=live, archive=archive)
    index, sources = _index_in_a_request()
    assert calls["espn"] == 0 and sources == {DATE: "worker"}
    assert index["1@2"]["in_progress"] is True


def test_a_week_of_aged_out_dates_makes_no_espn_call_in_a_request(monkeypatch):
    """The 11-26 shape: a past week's build asked for 6-10 dates and fetched each one."""
    dates = ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"]
    calls = _stores(monkeypatch, live=None, archive=None)
    index, sources = _index_in_a_request(dates)
    assert calls["espn"] == 0
    assert sources == {d: "none" for d in dates}


# --- the producer ------------------------------------------------------------------------------------------


def _event(event_id: str, away: str, home: str, *, final: bool) -> dict[str, Any]:
    state = "post" if final else "in"
    return {
        "id": event_id,
        "status": {"period": 4, "displayClock": "0:00" if final else "5:12",
                   "type": {"state": state, "completed": final, "description": "Final" if final else "In Progress"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": home, "displayName": f"Home {home}", "abbreviation": f"H{home}",
                                          "location": f"Home {home}"}, "score": "24"},
            {"homeAway": "away", "team": {"id": away, "displayName": f"Away {away}", "abbreviation": f"A{away}",
                                          "location": f"Away {away}"}, "score": "17"},
        ]}],
    }


def _capture_writes(monkeypatch, events) -> list[tuple[str, dict]]:
    writes: list[tuple[str, dict]] = []
    monkeypatch.setattr(poller, "_fetch_scoreboard", lambda iso: {"events": list(events)})
    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.write_json_file",
                        lambda path, payload: writes.append((str(path), dict(payload))))
    return writes


def test_archivable_is_settled_dates_only():
    assert poller.archivable({"date": "2026-10-17", "games": [{"final": True}, {"final": True}]})
    assert not poller.archivable({"date": "2026-10-17", "games": [{"final": True}, {"final": False}]})
    assert poller.archivable({"date": "2026-10-17", "games": []}, today="2026-11-27")
    assert not poller.archivable({"date": "2026-11-27", "games": []}, today="2026-11-27")
    assert not poller.archivable({"date": "2026-10-17"})


def test_the_poller_archives_an_all_final_date_beside_the_live_record(monkeypatch):
    writes = _capture_writes(monkeypatch, [_event("1", "153", "2628", final=True)])
    result = poller.poll_ncaaf_live_state(DATE)
    paths = [p for p, _ in writes]
    assert any("live_state" in p and "live_state_final" not in p for p in paths), paths
    assert any(p.endswith(f"live_state_final_{DATE}.json") for p in paths), paths
    assert result["archived"] is True


def test_the_poller_does_not_archive_a_moving_date(monkeypatch):
    writes = _capture_writes(monkeypatch, [_event("1", "153", "2628", final=True), _event("2", "3", "4", final=False)])
    result = poller.poll_ncaaf_live_state(DATE)
    assert not any("live_state_final" in p for p, _ in writes)
    assert result["archived"] is False


def test_archive_only_never_writes_the_keyvalue_live_record(monkeypatch):
    writes = _capture_writes(monkeypatch, [_event("1", "153", "2628", final=True)])
    poller.poll_ncaaf_live_state(DATE, archive_only=True)
    assert [p for p, _ in writes] == [str(poller.final_archive_path(DATE))]


def test_what_the_poller_archives_is_what_the_reader_accepts(monkeypatch):
    """The seam between two files: a shape change on either side must fail here."""
    writes = _capture_writes(monkeypatch, [_event("1", "153", "2628", final=True)])
    poller.poll_ncaaf_live_state(DATE)
    archived = next(payload for path, payload in writes if "live_state_final" in path)
    calls = _stores(monkeypatch, live=None, archive=archived)
    index, sources = _index_in_a_request()
    assert calls["espn"] == 0 and sources == {DATE: "archive"}
    assert index["153@2628"]["final"] is True


def test_the_archive_path_goes_to_disk_while_the_live_record_stays_in_keyvalue(monkeypatch):
    """Under the fleet's keyvalue backend the archive must be a FILE: Redis would give it the 10-day TTL back."""
    from syndicate.features.shared import refresh_state_store as store

    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "keyvalue")
    assert store._keyvalue_backed(poller.live_state_path(DATE)) is True
    assert store._keyvalue_backed(poller.final_archive_path(DATE)) is False
