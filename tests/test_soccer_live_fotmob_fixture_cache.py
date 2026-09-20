# -*- coding: utf-8 -*-
"""One tick, three FotMob fixture fetches -- not three per in-play match.

`resolve_fotmob_match_id` fetches `matches_for_date` for the date and both
neighbours on EVERY call and caches nothing, and `poll_league` calls it once per
in-play match, so a 12-match tick made 36 fetches of 3 distinct bodies. FotMob
was 15% of a tick when the loop was profiled (lane `soccer-live-loop-cost`).

These tests drive the real `poll_league` / `poll_active_leagues_for_tick` -- the
CALL SITE, not the resolver in isolation -- because the thing being changed is
which object the poller hands the resolver.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import poll_soccer_live_state as poller  # noqa: E402
from syndicate.features.soccer.features.live_lens import LiveMatchProjection  # noqa: E402
from syndicate.features.soccer.ingestion import fotmob_match_id  # noqa: E402
from syndicate.features.soccer.ingestion import fotmob_momentum  # noqa: E402

DATE = "2026-09-20"
LEAGUES = {
    "la_liga": (87, "ESP", [("Real Madrid", "Sevilla", 4100001), ("Girona", "Getafe", 4100002),
                            ("Osasuna", "Celta Vigo", 4100003)]),
    "epl": (47, "ENG", [("Arsenal", "Liverpool", 4700001), ("Everton", "Brentford", 4700002),
                        ("Fulham", "Burnley", 4700003)]),
}


class NeverStores(dict):
    """A fixture cache that forgets: the pre-change fetch volume, on purpose."""

    def __setitem__(self, key, value):
        return None


def _projection():
    return LiveMatchProjection(
        simulations=10, home_win_probability=0.7, draw_probability=0.2, away_win_probability=0.1,
        projected_final_home_goals=2.0, projected_final_away_goals=0.7, projected_final_total=2.7,
        over_2_5_probability=0.5, both_teams_scored_probability=0.4,
        projected_home_corners=9.0, projected_away_corners=5.0, projected_total_corners=14.0,
        home_red_card_applied=False, away_red_card_applied=False, scoreline_probabilities={"2-0": 0.3})


def _fixture_rows() -> list[dict[str, Any]]:
    rows = []
    for slug, (primary, ccode, matches) in LEAGUES.items():
        for home, away, match_id in matches:
            rows.append({"match_id": match_id, "league_id": primary, "league_primary_id": primary,
                         "league": slug, "ccode": ccode, "home": home, "away": away})
    return rows


def _events(league: str) -> list[dict[str, Any]]:
    return [{"event_id": f"{league}-{n}", "home_team": home, "away_team": away,
             "status_display_clock": "60'", "status_period": 2, "status_detail": "2nd Half"}
            for n, (home, away, _) in enumerate(LEAGUES[league][2])]


def _live_state(_summary=None, **kwargs):
    return {"event_id": kwargs.get("event_id"), "home_team": kwargs.get("home_team"),
            "away_team": kwargs.get("away_team"), "half": 2, "clock_remaining": 1800.0,
            "score_home": 1, "score_away": 0, "home_red_cards": 0, "away_red_cards": 0,
            "home_shots_so_far": 8, "away_shots_so_far": 4, "home_shots_on_target_so_far": 3,
            "away_shots_on_target_so_far": 1, "home_corners_so_far": 5, "away_corners_so_far": 2,
            "player_stats": {}}


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Everything the poller needs except the two FotMob calls under test."""
    monkeypatch.setenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", "off")
    monkeypatch.setattr(poller, "active_leagues_for_date", lambda *a, **k: list(LEAGUES))
    monkeypatch.setattr(poller, "fetch_match_summary", lambda *a, **k: {})
    monkeypatch.setattr(poller, "build_live_state", _live_state)
    monkeypatch.setattr(poller, "_load_team_ratings", lambda *a, **k: {})
    monkeypatch.setattr(poller, "_fill_promoted", lambda *a, **k: None)
    monkeypatch.setattr(poller, "_load_player_rows", lambda *a, **k: [])
    monkeypatch.setattr(poller, "_rating_for", lambda *a, **k: {"attack_rating": 0.0, "defense_rating": 0.0})
    monkeypatch.setattr(poller, "simulate_live_paths", lambda *a, **k: None)
    monkeypatch.setattr(poller, "project_live_match", lambda *a, **k: _projection())
    monkeypatch.setattr(poller, "goal_in_window_probability", lambda *a, **k: 0.1)
    monkeypatch.setattr(poller, "project_live_player_props", lambda *a, **k: [])
    monkeypatch.setattr(poller, "_build_match_boxes", lambda *a, **k: {})

    # The live series is a separate FotMob call and must NOT be cached: counted
    # here so a test can say so.
    details: list[int] = []

    def _get(url: str) -> dict[str, Any]:
        details.append(int(url.rsplit("=", 1)[1]))
        return {"content": {"momentum": {"main": {"data": [
            {"minute": 10, "value": 12.0}, {"minute": 20, "value": -30.0}]}}}}

    monkeypatch.setattr(fotmob_momentum, "_get", _get)

    dates: list[str] = []

    def _matches_for_date(date_compact: str) -> list[dict[str, Any]]:
        dates.append(date_compact)
        return _fixture_rows()

    monkeypatch.setattr(poller, "matches_for_date", _matches_for_date)

    # NOTHING MAY BYPASS THE MEMO. `resolve_fotmob_match_id` defaults `_fetch` to
    # its OWN module-level `matches_for_date`, so a poller that stopped passing
    # the memo would still resolve -- over the network, invisibly to the counter
    # above. This records that path instead of leaving it open, and the tests
    # assert it stays empty.
    bypass: list[str] = []

    def _bypassed(date_compact: str) -> list[dict[str, Any]]:
        bypass.append(date_compact)
        return _fixture_rows()

    monkeypatch.setattr(fotmob_match_id, "matches_for_date", _bypassed)
    return tmp_path / "source", tmp_path / "out", dates, details, bypass


def _served(out_root: Path, league: str) -> dict[str, Any]:
    import json
    path = out_root / league / "api" / "live_state" / f"live_state_{DATE}.json"
    return json.loads(path.read_text(encoding="utf-8"))["games"]


def test_one_tick_fetches_each_fotmob_date_once_across_every_league(monkeypatch, wired):
    source_root, out_root, dates, details, bypass = wired
    monkeypatch.setattr(poller, "fetch_events", lambda league, *a, **k: _events(league))

    poller.poll_active_leagues_for_tick(DATE, source_root=source_root, out_root=out_root, simulations=5)

    served = {**_served(out_root, "la_liga"), **_served(out_root, "epl")}
    assert len(served) == 6, sorted(served)
    # Three dates: the match date and both neighbours, once each for the tick.
    assert len(dates) == 3, dates
    assert len(set(dates)) == 3, dates
    assert bypass == [], bypass                # every fetch went through the memo
    # The live series is per match and is NOT cached.
    assert sorted(details) == sorted(m[2] for spec in LEAGUES.values() for m in spec[2])
    assert all(game["momentum"]["supported"] for game in served.values())


def test_more_matches_do_not_mean_more_fixture_fetches(monkeypatch, wired):
    source_root, out_root, dates, details, bypass = wired
    monkeypatch.setattr(poller, "fetch_events", lambda league, *a, **k: _events(league)[:1])

    poller.poll_active_leagues_for_tick(DATE, source_root=source_root, out_root=out_root, simulations=5)

    assert len(details) == 2, details          # one match per league
    assert len(dates) == 3, dates              # the same three fetches as for six matches
    assert bypass == [], bypass


def test_without_the_memo_it_is_three_fetches_per_match_and_the_same_games(monkeypatch, wired):
    """The falsification, and the number this change removes.

    Defeating the cache must restore the pre-change volume AND leave the served
    games byte for byte identical -- a cache that changed an id or a series would
    not be a cache.
    """
    source_root, out_root, dates, details, bypass = wired
    monkeypatch.setattr(poller, "fetch_events", lambda league, *a, **k: _events(league))

    poller.poll_active_leagues_for_tick(DATE, source_root=source_root, out_root=out_root, simulations=5)
    cached_games = {**_served(out_root, "la_liga"), **_served(out_root, "epl")}
    cached_dates = list(dates)

    dates.clear()
    details.clear()
    for league in LEAGUES:
        poller.poll_league(league, DATE, source_root=source_root, out_root=out_root,
                           simulations=5, fixture_cache=NeverStores())
    uncached_games = {**_served(out_root, "la_liga"), **_served(out_root, "epl")}

    assert len(cached_dates) == 3
    assert len(dates) == 18, len(dates)        # 3 dates x 6 matches, the old volume
    assert uncached_games == cached_games


def test_a_failed_fixture_fetch_is_not_remembered_as_an_answer(monkeypatch, wired):
    """A cached exception would turn one transient FotMob failure into a whole
    tick with no momentum. The failure is not stored, so the next match retries.
    """
    source_root, out_root, dates, details, bypass = wired
    monkeypatch.setattr(poller, "fetch_events", lambda league, *a, **k: _events("la_liga")[:2]
                        if league == "la_liga" else [])

    calls = {"n": 0}
    rows = _fixture_rows()

    def _flaky(date_compact: str) -> list[dict[str, Any]]:
        dates.append(date_compact)
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("fotmob timed out")
        return rows

    monkeypatch.setattr(poller, "matches_for_date", _flaky)

    poller.poll_active_leagues_for_tick(DATE, source_root=source_root, out_root=out_root, simulations=5)

    served = _served(out_root, "la_liga")
    momentum = [game["momentum"]["supported"] for game in served.values()]
    assert momentum.count(False) == 1 and momentum.count(True) == 1, served
