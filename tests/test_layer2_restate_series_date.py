"""Lane `layer2-restate-series-date`: a card takes its game state from ITS OWN date's chip.

`_refresh_layer2_live_state` indexed every requested date's chips by team pair,
first indexed wins, and looked cards up by the pair alone. An MLB series plays
the same pair on consecutive days, so tomorrow's game took TODAY's chip. Seen
on the served board 2026-09-21 ~22:25Z: TOR @ BAL for 09-22 read `market_state
live` while 09-21's TOR @ BAL was live, and the serve-time re-gate then set it
`dead` because a pregame price fails the live rules.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline.intelligence_state as state_module
from syndicate.features.shared import game_chip_scoreboard

TODAY, TOMORROW = "2026-09-21", "2026-09-22"


def _chip(sport, away, home, state):
    return {"sport": sport, "state": state, "away": {"name": away}, "home": {"name": home}}


def _card(sport, away, home, game_date):
    return {
        "sport": sport,
        "away_team": away,
        "home_team": home,
        "game_date": game_date,
        "market_state": "pregame",
        "lane": "pregame",
        "is_live": False,
    }


@pytest.fixture
def chips_by_date(monkeypatch):
    """The scoreboard, per requested date. No worker-published chips."""
    table: dict[str, list] = {}
    monkeypatch.setattr(state_module, "read_game_chips", lambda _date: None)
    monkeypatch.setattr(game_chip_scoreboard, "build_game_chips", lambda date, _sports: list(table.get(str(date), [])))
    return table


def _restate(cards, dates):
    return state_module._refresh_layer2_live_state(cards, dates, attach_actual=False)


@pytest.mark.parametrize("dates", [[TODAY, TOMORROW], [TOMORROW, TODAY]])
def test_tomorrows_series_game_does_not_take_todays_live_chip(chips_by_date, dates):
    chips_by_date[TODAY] = [_chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "live")]
    chips_by_date[TOMORROW] = [_chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "pregame")]
    today = _card("mlb", "Toronto Blue Jays", "Baltimore Orioles", TODAY)
    tomorrow = _card("mlb", "Toronto Blue Jays", "Baltimore Orioles", TOMORROW)

    restated = _restate([today, tomorrow], dates)

    # Reachability: today's card IS restated, so a fix that restates nothing cannot pass.
    assert restated == 1
    assert today["market_state"] == "live" and today["lane"] == "live" and today["is_live"] is True
    assert tomorrow["market_state"] == "pregame" and tomorrow["lane"] == "pregame" and tomorrow["is_live"] is False


def test_tomorrows_series_game_does_not_take_todays_final(chips_by_date):
    chips_by_date[TODAY] = [_chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "final")]
    chips_by_date[TOMORROW] = [_chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "pregame")]
    today = _card("mlb", "Toronto Blue Jays", "Baltimore Orioles", TODAY)
    tomorrow = _card("mlb", "Toronto Blue Jays", "Baltimore Orioles", TOMORROW)

    _restate([today, tomorrow], [TODAY, TOMORROW])

    assert today["market_state"] == "final"
    assert tomorrow["market_state"] == "pregame" and tomorrow["lane"] == "pregame"


def test_a_series_card_with_no_chip_for_its_own_date_is_left_alone(chips_by_date):
    """Tomorrow's scoreboard not fetched (or empty): today's chip must not fill the gap."""
    chips_by_date[TODAY] = [_chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "live")]
    tomorrow = _card("mlb", "Toronto Blue Jays", "Baltimore Orioles", TOMORROW)

    assert _restate([tomorrow], [TODAY, TOMORROW]) == 0
    assert tomorrow["market_state"] == "pregame"


def test_football_still_joins_an_adjacent_scoreboard_date(chips_by_date):
    """Football chips live on ESPN's date; a pair cannot repeat on adjacent days, so
    an adjacent date's chip is still that game and must keep restating it."""
    chips_by_date[TOMORROW] = [_chip("nfl", "New York Jets", "Detroit Lions", "live")]
    card = _card("nfl", "New York Jets", "Detroit Lions", TODAY)

    assert _restate([card], [TODAY, TOMORROW]) == 1
    assert card["market_state"] == "live"


def test_mlb_does_not_join_an_adjacent_scoreboard_date(chips_by_date):
    chips_by_date[TOMORROW] = [_chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "live")]
    card = _card("mlb", "Toronto Blue Jays", "Baltimore Orioles", TODAY)

    assert _restate([card], [TODAY, TOMORROW]) == 0
    assert card["market_state"] == "pregame"


def test_an_undated_card_is_restated_only_when_its_pair_is_unambiguous(chips_by_date):
    chips_by_date[TODAY] = [
        _chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "live"),
        _chip("mlb", "New York Yankees", "Boston Red Sox", "live"),
    ]
    chips_by_date[TOMORROW] = [_chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "pregame")]
    series = _card("mlb", "Toronto Blue Jays", "Baltimore Orioles", None)
    single = _card("mlb", "New York Yankees", "Boston Red Sox", None)

    assert _restate([series, single], [TODAY, TOMORROW]) == 1
    assert single["market_state"] == "live"
    assert series["market_state"] == "pregame", "two dates carry this pair: unknown must not pick one"


def test_the_date_comes_from_commence_time_when_game_date_is_absent(chips_by_date):
    chips_by_date[TODAY] = [_chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "live")]
    chips_by_date[TOMORROW] = [_chip("mlb", "Toronto Blue Jays", "Baltimore Orioles", "pregame")]
    card = _card("mlb", "Toronto Blue Jays", "Baltimore Orioles", None)
    card["commence_time"] = "2026-09-22T22:36:00Z"  # 17:36 CDT on 09-22

    _restate([card], [TODAY, TOMORROW])
    assert card["market_state"] == "pregame"
