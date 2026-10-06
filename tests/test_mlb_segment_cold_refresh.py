"""Cold MLB events still get their segment/alternate set every interval, not never.

Lane `mlb-segment-cold-refresh` (2026-10-06): event scoping skipped the per-event segment
fetch for any confirmed-pregame game more than 75 min out, so today's first1/3/5 lines were
last refreshed by the next-day lookahead -- 20.9 h stale at 16:48Z, 97 MLB stale-quote rows.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mlb_fetch_segment_cold_under_test", REPO_ROOT / "scripts" / "fetch_mlb_oddsapi_local.py"
)
mlb_fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mlb_fetch)

_EVENTS = [
    {"id": "e1", "home_team": "Atlanta Braves", "away_team": "Los Angeles Dodgers", "commence_time": "2099-10-06T22:00:00Z"},
    {"id": "e2", "home_team": "San Diego Padres", "away_team": "Milwaukee Brewers", "commence_time": "2099-10-07T01:30:00Z"},
]


def _book(event, markets):
    return [{"key": "fanduel", "title": "FanDuel", "markets": [
        {"key": m, "outcomes": [{"name": event["home_team"], "price": -120}, {"name": event["away_team"], "price": 100}]}
        for m in markets]}]


@pytest.fixture
def harness(monkeypatch, tmp_path):
    per_event_calls: list[str] = []

    def _http_get(url, params, timeout=30):
        if url.endswith("/odds") and "/events/" not in url:
            return [dict(e, bookmakers=_book(e, ["h2h", "spreads", "totals"])) for e in _EVENTS], {}
        event_id = url.split("/events/")[1].split("/")[0]
        per_event_calls.append(event_id)
        event = next(e for e in _EVENTS if e["id"] == event_id)
        return {"bookmakers": _book(event, ["totals_1st_5_innings"])}, {}

    status = {
        (mlb_fetch._normalize_matchup_team(e["away_team"]), mlb_fetch._normalize_matchup_team(e["home_team"])): {
            "abstract": "Preview", "detailed": "Scheduled", "commence": e["commence_time"]}
        for e in _EVENTS
    }
    monkeypatch.setattr(mlb_fetch, "_http_get", _http_get)
    monkeypatch.setattr(mlb_fetch, "_event_scoping_enabled", lambda: True)
    monkeypatch.setattr(mlb_fetch, "_load_mlb_status_by_matchup", lambda d: status)
    monkeypatch.setattr(mlb_fetch, "_props_event_cache_path", lambda d, k: tmp_path / f"cache_{k}_{d}.json")

    def run():
        per_event_calls.clear()
        out = mlb_fetch.fetch_live_game_lines_for_date("KEY", "2099-10-06", events=list(_EVENTS))
        return list(per_event_calls), out["meta"]["event_scoping"]

    return run


def test_cold_events_get_their_segments_when_the_interval_is_due(harness, monkeypatch):
    monkeypatch.delenv("SYNDICATE_ODDS_SEGMENT_COLD_INTERVAL_SECONDS", raising=False)
    calls, scoping = harness()
    assert sorted(calls) == ["e1", "e2"]
    assert scoping["cold_segment_refreshed"] == 2
    assert scoping["reduced_tier_events"] == 2


def test_a_second_sweep_inside_the_interval_fetches_nothing_per_event(harness, monkeypatch):
    monkeypatch.delenv("SYNDICATE_ODDS_SEGMENT_COLD_INTERVAL_SECONDS", raising=False)
    harness()
    calls, scoping = harness()
    assert calls == []
    assert scoping["cold_segment_refreshed"] == 0


def test_off_is_not_on_interval_zero_restores_the_old_skip(harness, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ODDS_SEGMENT_COLD_INTERVAL_SECONDS", "0")
    calls, scoping = harness()
    assert calls == []
    assert scoping["cold_segment_refreshed"] == 0


def test_refresh_due_logic():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 10, 6, 17, 0, tzinfo=timezone.utc)
    due = mlb_fetch._segment_refresh_due
    assert due(None, now=now, interval_seconds=3000) is True
    assert due({"fetched_at": (now - timedelta(seconds=100)).isoformat()}, now=now, interval_seconds=3000) is False
    assert due({"fetched_at": (now - timedelta(seconds=3100)).isoformat()}, now=now, interval_seconds=3000) is True
    assert due(None, now=now, interval_seconds=0) is False
