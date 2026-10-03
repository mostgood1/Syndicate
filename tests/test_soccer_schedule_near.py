"""Soccer schedule: near-window merge between full rebuilds (lane `layer2-freshness-1h`).

MEASURED 2026-10-02 on the local fleet (soccer pregame run 20261002_223521):
schedule steps were 1,327 of the run's 1,416 seconds -- every league's FULL
season, ~15 ESPN windows each, on every run -- against 11s of odds. The run held
the refresh lane ~24 min, refusing every other sport's sweep while it ran.

What must survive the shortcut is what a match day changes: `status_state` (a
postponement voids the card -- `sources.py`, 2026-09-17) and scores.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest

from scripts import build_soccer_schedule as bss
from scripts import refresh_odds_sources as ros

LEAGUE, SEASON = "epl", 2026
TODAY = date(2026, 10, 2)


def _row(eid, day, status="pre", home="A", away="B", hs=None, as_=None):
    return {"event_id": eid, "date": f"{day}T14:00Z", "home_team": home, "away_team": away,
            "home_score": hs, "away_score": as_, "status_state": status}


@pytest.fixture
def fetched(monkeypatch):
    calls: list[list[str]] = []
    reply: list[dict] = []

    def fake(league, *, date_windows, **_):
        calls.append(list(date_windows))
        return list(reply)

    monkeypatch.setattr(bss, "fetch_events", fake)
    return calls, reply


def _write_prior(root, matches, **extra):
    path = bss.schedule_file(root, LEAGUE, SEASON)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"league": LEAGUE, "season": SEASON, **extra,
                                "matches": [dict(m, week=99) for m in matches]}), encoding="utf-8")
    return path


def test_near_refetches_one_window_and_merges_by_event_id(tmp_path, fetched):
    calls, reply = fetched
    _write_prior(tmp_path, [
        _row("1", "2026-08-16", "post", hs=2, as_=1),   # long past: kept untouched
        _row("2", "2026-10-03", "pre"),                 # in window: postponed today
        _row("3", "2026-12-01", "pre"),                 # far ahead: kept untouched
    ], generated_at="2026-10-02T12:00:00+00:00", full_generated_at="2026-10-02T12:00:00+00:00")
    reply[:] = [_row("2", "2026-10-03", "void"), _row("4", "2026-10-04", "pre", home="C", away="D")]

    out = bss.build_schedule_near(LEAGUE, SEASON, out_root=tmp_path, today=TODAY)

    assert calls == [["20260930-20261009"]], "exactly ONE ESPN window, around today"
    by_id = {m["event_id"]: m for m in out["matches"]}
    assert by_id["2"]["status_state"] == "void", "the postponement reaches the file"
    assert by_id["1"]["home_score"] == 2 and by_id["3"]["status_state"] == "pre"
    assert "4" in by_id and out["match_count"] == 4
    assert all(m["week"] != 99 for m in out["matches"]), "matchweeks recomputed, not carried"
    assert out["build_mode"] == "near" and out["near_window"] == "20260930-20261009"
    assert out["full_generated_at"] == "2026-10-02T12:00:00+00:00", "the full-build clock is carried"
    on_disk = json.loads(bss.schedule_file(tmp_path, LEAGUE, SEASON).read_text(encoding="utf-8"))
    assert on_disk["match_count"] == 4


def test_near_with_no_prior_file_is_a_full_build(tmp_path, fetched):
    calls, reply = fetched
    reply[:] = [_row("1", "2026-10-03")]
    out = bss.build_schedule_near(LEAGUE, SEASON, out_root=tmp_path, today=TODAY)
    assert len(calls) == 1 and len(calls[0]) > 1, "every season window, as a full build fetches"
    assert out["build_mode"] == "full" and out["full_generated_at"] == out["generated_at"]


def test_near_outside_the_season_writes_nothing(tmp_path, fetched, monkeypatch):
    calls, _ = fetched
    path = _write_prior(tmp_path, [_row("1", "2026-08-16")])
    before = path.read_bytes()
    monkeypatch.setattr(bss, "season_date_range", lambda league, season: (date(2026, 8, 1), date(2026, 8, 31)))
    bss.build_schedule_near(LEAGUE, SEASON, out_root=tmp_path, today=TODAY)
    assert calls == [] and path.read_bytes() == before


# ---------------------------------------------------------------------------
# The caller: full while the last FULL build is stale or unknown, else --near.
# ---------------------------------------------------------------------------


@pytest.fixture
def step_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ros, "soccer_default_season", lambda league: SEASON)
    monkeypatch.delenv("SYNDICATE_SOCCER_SCHEDULE_FULL_REBUILD_SECONDS", raising=False)
    return tmp_path


def _stamp(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _is_near(step):
    return "--near" in step.command


def test_reachability_a_recent_full_build_makes_the_step_near(step_root):
    _write_prior(step_root, [_row("1", "2026-10-03")], full_generated_at=_stamp(1))
    assert _is_near(ros._soccer_schedule_step(LEAGUE, step_root, "python")) is True
    _write_prior(step_root, [_row("1", "2026-10-03")], full_generated_at=_stamp(7))
    assert _is_near(ros._soccer_schedule_step(LEAGUE, step_root, "python")) is False


def test_a_pre_near_file_ages_from_generated_at(step_root):
    _write_prior(step_root, [_row("1", "2026-10-03")], generated_at=_stamp(1))
    assert _is_near(ros._soccer_schedule_step(LEAGUE, step_root, "python")) is True


def test_unknown_age_is_a_full_build(step_root):
    assert _is_near(ros._soccer_schedule_step(LEAGUE, step_root, "python")) is False  # no file
    path = bss.schedule_file(step_root, LEAGUE, SEASON)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert _is_near(ros._soccer_schedule_step(LEAGUE, step_root, "python")) is False


def test_zero_restores_a_full_build_every_run(step_root, monkeypatch):
    _write_prior(step_root, [_row("1", "2026-10-03")], full_generated_at=_stamp(1))
    monkeypatch.setenv("SYNDICATE_SOCCER_SCHEDULE_FULL_REBUILD_SECONDS", "0")
    assert _is_near(ros._soccer_schedule_step(LEAGUE, step_root, "python")) is False


def test_the_step_keeps_its_name_and_phase(step_root):
    step = ros._soccer_schedule_step(LEAGUE, step_root, "python")
    assert step.name == "soccer_epl_schedule" and step.phases == ("pregame",)


# ---------------------------------------------------------------------------
# Staggered full rebuilds: at most one league per run, the stalest due one.
# ---------------------------------------------------------------------------


def _league_file(root, league, hours_ago):
    path = bss.schedule_file(root, league, SEASON)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"matches": [_row("1", "2026-10-03")], "full_generated_at": _stamp(hours_ago)}),
                    encoding="utf-8")


def test_reachability_only_the_stalest_due_league_rebuilds_in_full(step_root, monkeypatch):
    monkeypatch.delenv("SYNDICATE_SOCCER_SCHEDULE_FULL_REBUILDS_PER_RUN", raising=False)
    for league, hours in (("epl", 7), ("mls", 9), ("la_liga", 6.5), ("serie_a", 1)):
        _league_file(step_root, league, hours)
    leagues = ["epl", "mls", "la_liga", "serie_a"]
    assert ros._soccer_schedule_full_rebuild_leagues(leagues, step_root) == {"mls"}
    full = ros._soccer_schedule_full_rebuild_leagues(leagues, step_root)
    near = {lg: _is_near(ros._soccer_schedule_step(lg, step_root, "python", allow_full=lg in full)) for lg in leagues}
    assert near == {"epl": True, "mls": False, "la_liga": True, "serie_a": True}, "stale but not its turn -> near"


def test_unknown_age_is_the_stalest(step_root):
    _league_file(step_root, "mls", 9)
    assert ros._soccer_schedule_full_rebuild_leagues(["mls", "epl"], step_root) == {"epl"}  # epl has no file


def test_nothing_due_means_no_full_rebuild(step_root):
    _league_file(step_root, "epl", 1)
    assert ros._soccer_schedule_full_rebuild_leagues(["epl"], step_root) == set()


def test_a_zero_limit_restores_every_due_league(step_root, monkeypatch):
    for league, hours in (("epl", 7), ("mls", 9), ("serie_a", 1)):
        _league_file(step_root, league, hours)
    monkeypatch.setenv("SYNDICATE_SOCCER_SCHEDULE_FULL_REBUILDS_PER_RUN", "0")
    assert ros._soccer_schedule_full_rebuild_leagues(["epl", "mls", "serie_a"], step_root) == {"epl", "mls"}
