"""`_attach_live_state` reads the ESPN date a night kickoff is filed under.

THE DEFECT (production, 2026-09-10). FAMU @ MIA kicked off at 2026-09-11T00:00Z
(8 PM ET, 09-10). ESPN files it under 20260910. The NCAAF chip/card live-state
index was built for `_ncaaf_week_kickoff_dates`, the UTC dates of `startDate`,
which were ('2026-09-11', '2026-09-12', '2026-09-13') for week 2. So the 09-10
record was never read, and the scoreboard chip read `pregame` with no score for
the whole game, although the poller's record had it in progress under `50@2390`.

The ids were never the problem: the registry maps Florida A&M to 50 and Miami to
2390, which are ESPN's ids, and the logo URLs carry them. The date was.

REACHABILITY FIRST (`model_engine_standard.md` §4.3): the index below answers
ONLY for 09-10, exactly like production's record. With the old date set the chip
stays pregame; with the new one it goes live.
"""

from __future__ import annotations

import pytest

from syndicate.features.ncaaf import cards as C

SCHEDULE = [
    # Thursday night, alone on its Eastern date. The case that failed.
    {"week": 2, "awayTeam": "Florida A&M", "homeTeam": "Miami", "startDate": "2026-09-11T00:00:00.000Z"},
    {"week": 2, "awayTeam": "Rutgers", "homeTeam": "Boston College", "startDate": "2026-09-11T23:30:00.000Z"},
    {"week": 2, "awayTeam": "Oklahoma", "homeTeam": "Michigan", "startDate": "2026-09-12T16:00:00.000Z"},
    # Small hours Eastern: ESPN files it under the PREVIOUS day.
    {"week": 2, "awayTeam": "New Mexico State", "homeTeam": "Hawai'i", "startDate": "2026-09-13T04:00:00.000Z"},
    {"week": 3, "awayTeam": "Other", "homeTeam": "Week", "startDate": "2026-09-17T00:00:00.000Z"},
]


@pytest.fixture(autouse=True)
def _schedule(monkeypatch):
    monkeypatch.setattr(C, "load_games_season", lambda season: list(SCHEDULE))
    C._ncaaf_week_kickoff_dates.cache_clear()
    C._ncaaf_week_espn_capture_dates.cache_clear()
    yield
    C._ncaaf_week_kickoff_dates.cache_clear()
    C._ncaaf_week_espn_capture_dates.cache_clear()


def test_the_utc_helper_is_unchanged_and_misses_the_espn_date():
    """The quote-shard helper keeps its meaning; this is why it can't be the join's."""
    assert C._ncaaf_week_kickoff_dates(2026, 2) == ("2026-09-11", "2026-09-12", "2026-09-13")


def test_capture_dates_add_the_eastern_date_and_keep_every_utc_one():
    dates = C._ncaaf_week_espn_capture_dates(2026, 2)
    assert "2026-09-10" in dates                      # FAMU @ MIA's ESPN date
    assert set(C._ncaaf_week_kickoff_dates(2026, 2)) <= set(dates)
    assert "2026-09-12" in dates                      # NMSU @ Hawai'i: 00:00 ET -> previous day
    assert not any(d >= "2026-09-16" for d in dates)  # week 3 is not pulled in


def _famu_game():
    return {
        "gamePk": "2_Florida_A&M_Miami",
        "status": "Week 2",
        "startTime": "2026-09-11T00:00:00.000Z",
        "away": {"abbr": "FAMU", "name": "Florida A&M",
                 "logo_url": "https://a.espncdn.com/i/teamlogos/ncaa/500/50.png"},
        "home": {"abbr": "MIA", "name": "Miami",
                 "logo_url": "https://a.espncdn.com/i/teamlogos/ncaa/500/2390.png"},
    }


def _index_only_for_0910(requested):
    def fake_index(dates, sources=None):
        requested.append(tuple(dates))
        if "2026-09-10" in tuple(dates):
            return {"50@2390": {"in_progress": True, "final": False, "status": "2nd Quarter",
                                "period": 2, "clock": "8:27", "away_score": 0, "home_score": 21,
                                "start_time": "2026-09-11T00:00Z"}}
        return {}
    return fake_index


def test_a_night_kickoff_chip_goes_live_off_the_record_filed_under_its_eastern_date(monkeypatch):
    requested: list = []
    monkeypatch.setattr(
        "syndicate.features.ncaaf.live_game_state.ncaaf_game_state_index", _index_only_for_0910(requested)
    )
    games = [_famu_game()]
    C._attach_live_state(games, 2026, 2)

    assert any("2026-09-10" in dates for dates in requested), requested
    assert games[0]["live_state"]["in_progress"] is True

    from syndicate.features.shared.game_chip_scoreboard import build_game_chip

    chip = build_game_chip("ncaaf", games[0])
    assert chip["state"] == "live"
    assert str(chip["home"]["score"]) in {"21", "21.0"}


def test_off_the_utc_date_set_alone_the_same_game_stays_pregame(monkeypatch):
    """off != on: the defect, reproduced by feeding the join the OLD date set."""
    requested: list = []
    monkeypatch.setattr(
        "syndicate.features.ncaaf.live_game_state.ncaaf_game_state_index", _index_only_for_0910(requested)
    )
    monkeypatch.setattr(C, "_ncaaf_week_espn_capture_dates", C._ncaaf_week_kickoff_dates)
    games = [_famu_game()]
    C._attach_live_state(games, 2026, 2)

    assert "live_state" not in games[0]

    from syndicate.features.shared.game_chip_scoreboard import build_game_chip

    assert build_game_chip("ncaaf", games[0])["state"] == "pregame"
