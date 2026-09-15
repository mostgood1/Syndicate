"""Tests for `scripts/check_fotmob_join_coverage.py`, the ESPN->FotMob respelling detector.

FotMob rows come from the listing FotMob actually served for 2026-09-12
(`tests/fixtures/fotmob_matches_20260912.json`), flattened by the real
`fotmob_shots.matches_for_date` over a stubbed `_get`. ESPN events are shaped
exactly like `espn_lineups.fetch_events` output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_fotmob_join_coverage as checker
from syndicate.features.soccer.ingestion import fotmob_shots

_FIXTURE_0912 = Path(__file__).parent / "fixtures" / "fotmob_matches_20260912.json"


@pytest.fixture
def fotmob_0912(monkeypatch):
    payload = json.loads(_FIXTURE_0912.read_text(encoding="utf-8"))

    def fake_get(url: str):
        return payload if url.endswith("date=20260912") else {"leagues": []}

    monkeypatch.setattr(fotmob_shots, "_get", fake_get)
    return fotmob_shots.matches_for_date


def _espn(events_by_league, calls=None):
    def fetch(league, *, date_windows, statuses=None, timeout=20):
        if calls is not None:
            calls.append((league, list(date_windows), statuses))
        return [dict(e) for e in events_by_league.get(league, [])]
    return fetch


def _event(event_id, home, away, kickoff="2026-09-12T16:30Z", state="pre"):
    return {"event_id": event_id, "date": kickoff, "status_state": state, "home_team": home, "away_team": away}


def test_all_resolved_exits_zero_and_asks_espn_for_the_pollers_single_date(fotmob_0912):
    calls = []
    espn = _espn({
        "bundesliga": [_event("e1", "FC Cologne", "Werder Bremen")],
        "belgian_pro_league": [_event("e2", "Waasland-Beveren", "Sint-Truidense")],
    }, calls)
    report = checker.check(["2026-09-12"], ["bundesliga", "belgian_pro_league"], espn_fetch=espn, fotmob_fetch=fotmob_0912)
    assert report["exit_code"] == 0
    assert (report["resolved"], report["fixtures"]) == (2, 2)
    # Production's input path: the poller's single-date window, not a range.
    assert [c[1] for c in calls] == [["20260912"], ["20260912"]]


def test_a_respelling_exits_one_and_shows_fotmobs_unclaimed_fixture(fotmob_0912):
    # "1. FC Cologne" is a plausible ESPN respelling that neither the alias key
    # ("fc cologne"), the strict pass nor the loose pass bridges.
    espn = _espn({"bundesliga": [_event("e1", "1. FC Cologne", "Werder Bremen")]})
    report = checker.check(["2026-09-12"], ["bundesliga"], espn_fetch=espn, fotmob_fetch=fotmob_0912)
    assert report["exit_code"] == 1
    assert len(report["unresolved"]) == 1
    miss = report["unresolved"][0]
    assert (miss["espn_home"], miss["espn_away"]) == ("1. FC Cologne", "Werder Bremen")
    unclaimed = {(c["home"], c["away"]) for c in miss["fotmob_unclaimed_in_league_window"]}
    assert ("1. FC Köln", "Werder Bremen") in unclaimed


def test_a_resolved_fixture_is_not_offered_as_an_unclaimed_candidate(fotmob_0912):
    espn = _espn({"bundesliga": [
        _event("e1", "1. FC Cologne", "Werder Bremen"),
        _event("e2", "Augsburg", "Bayer Leverkusen"),
    ]})
    report = checker.check(["2026-09-12"], ["bundesliga"], espn_fetch=espn, fotmob_fetch=fotmob_0912)
    unclaimed = {c["match_id"] for c in report["unresolved"][0]["fotmob_unclaimed_in_league_window"]}
    assert 5881161 not in unclaimed, "Augsburg v Leverkusen resolved, so it is not a candidate"
    assert 5881164 in unclaimed


def test_an_espn_fetch_failure_is_unknown_not_clear(fotmob_0912):
    def espn(league, *, date_windows, statuses=None, timeout=20):
        raise RuntimeError("simulated ESPN 503")

    report = checker.check(["2026-09-12"], ["bundesliga"], espn_fetch=espn, fotmob_fetch=fotmob_0912)
    assert report["exit_code"] == 2
    assert report["unknown"][0]["source"] == "espn"
    assert report["fixtures"] == 0


def test_a_fotmob_fetch_failure_is_unknown_not_a_respelling():
    # The resolver swallows fetch errors into None; the checker must not report
    # that as an unresolved fixture.
    def fotmob(_compact):
        raise RuntimeError("simulated FotMob timeout")

    espn = _espn({"bundesliga": [_event("e1", "FC Cologne", "Werder Bremen")]})
    report = checker.check(["2026-09-12"], ["bundesliga"], espn_fetch=espn, fotmob_fetch=fotmob)
    assert report["exit_code"] == 2
    assert report["unresolved"] == []
    assert report["unknown"][0]["source"] == "fotmob"


def test_an_unresolved_fixture_outranks_unknown_elsewhere(fotmob_0912):
    def espn(league, *, date_windows, statuses=None, timeout=20):
        if league == "mls":
            raise RuntimeError("simulated ESPN 503")
        return [_event("e1", "1. FC Cologne", "Werder Bremen")]

    report = checker.check(["2026-09-12"], ["bundesliga", "mls"], espn_fetch=espn, fotmob_fetch=fotmob_0912)
    assert report["exit_code"] == 1
    assert len(report["unresolved"]) == 1 and len(report["unknown"]) == 1


def test_main_refuses_an_untracked_league():
    assert checker.main(["--start", "2026-09-12", "--days", "1", "--leagues", "not_a_league"]) == 2
