"""Lane `nhl-compact-card-start-time`: NHL chips carry a start time and live detail.

Measured on production 2026-09-22 17:0xZ: every NHL chip on
`/api/board/game-chips?sport=nhl` read `start_time_utc: None`,
`status_token: None` and `game_key` "1".."10" (a row index), so the Layer 2
Games rail showed a bare "NHL PREGAME" where every other sport shows
"MLB · 5:35P CT". The NHL card game comes from `predictions_<date>.csv`, which
carries only `date`. The live overlay (`_apply_nhl_live_scores`) already reads
the NHL schedule -- id, `startTimeUTC`, state, period, clock -- and dropped the
start on the way (the id stays the card's: other NHL rows join on it). These run the real overlay and the real chip
builder over the production shapes.
"""

from __future__ import annotations

import pytest

from syndicate.blueprints import home
from syndicate.features.shared.game_chip_scoreboard import build_game_chip

DATE = "2026-09-22"


def _card_game():
    # Shape of `/nhl/api/cards?date=2026-09-22` games[0] (fields the chip reads).
    return {
        "gamePk": "1",
        "away_tri": "CBJ",
        "away_name": "Columbus Blue Jackets",
        "home_tri": "BUF",
        "home_name": "Buffalo Sabres",
        "away": {"abbr": "CBJ", "name": "Columbus Blue Jackets"},
        "home": {"abbr": "BUF", "name": "Buffalo Sabres"},
        "status": "Scheduled",
        "detail": "Scheduled",
        "gameType": "NHL",
        "odds": {"commence_time": DATE, "sportsbook": None},
    }


def _schedule_row(state="FUT", period=None, clock=None, away_goals=None, home_goals=None):
    # Shape of `NhlWebClient.scoreboard_day("2026-09-22")` for CBJ @ BUF.
    return {
        "gamePk": 2026010024,
        "gameDate": "2026-09-22T23:00:00Z",
        "away": "Columbus Blue Jackets",
        "home": "Buffalo Sabres",
        "away_abbr": "CBJ",
        "home_abbr": "BUF",
        "away_goals": away_goals,
        "home_goals": home_goals,
        "gameState": state,
        "period": period,
        "clock": clock,
    }


@pytest.fixture
def schedule(monkeypatch):
    def _install(*rows):
        from syndicate import local_nhl_odds

        monkeypatch.setattr(home, "central_today_iso", lambda: DATE)
        monkeypatch.setattr(local_nhl_odds.NhlWebClient, "scoreboard_day", lambda self, date: list(rows))

    return _install


def _chip(schedule_rows, schedule):
    schedule(*schedule_rows)
    games = home._apply_nhl_live_scores([_card_game()], DATE)
    return build_game_chip("nhl", games[0])


def test_a_pregame_nhl_chip_shows_its_start_time(schedule):
    chip = _chip([_schedule_row()], schedule)
    assert chip["state"] == "pregame"
    assert chip["start_time_utc"] == "2026-09-22T23:00:00+00:00"
    assert chip["status_token"] == "6:00P CT"


def test_a_live_nhl_chip_shows_period_clock_and_score(schedule):
    chip = _chip([_schedule_row(state="LIVE", period=2, clock="10:21", away_goals=1, home_goals=2)], schedule)
    assert chip["state"] == "live"
    assert chip["status_token"] == "P2 10:21"
    assert (chip["away"]["score"], chip["home"]["score"]) == ("1", "2")
    assert chip["start_time_utc"] == "2026-09-22T23:00:00+00:00"


def test_a_placeholder_midnight_is_not_taken_for_a_start(schedule):
    # `scoreboard_day` writes f"{date}T00:00:00Z" when the API has no start.
    chip = _chip([dict(_schedule_row(), gameDate="2026-09-22T00:00:00Z")], schedule)
    assert chip["start_time_utc"] is None


def test_the_scoreboard_client_names_team_abbreviations(monkeypatch):
    from syndicate.local_nhl_odds import NhlWebClient

    payload = {"gameWeek": [{"date": DATE, "games": [{
        "id": 2026010024, "startTimeUTC": "2026-09-22T23:00:00Z", "gameState": "FUT",
        "awayTeam": {"abbrev": "CBJ", "placeName": {"default": "Columbus"}, "commonName": {"default": "Blue Jackets"}},
        "homeTeam": {"abbrev": "BUF", "placeName": {"default": "Buffalo"}, "commonName": {"default": "Sabres"}},
    }]}]}
    monkeypatch.setattr(NhlWebClient, "_get", lambda self, path: payload)
    row = NhlWebClient().scoreboard_day(DATE)[0]
    assert (row["away_abbr"], row["home_abbr"]) == ("CBJ", "BUF")
    assert row["gameDate"] == "2026-09-22T23:00:00Z"
