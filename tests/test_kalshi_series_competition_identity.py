"""A Kalshi series for ANOTHER COMPETITION never pairs with our board's games.

Lane kalshi-series-competition-identity, 2026-10-20. The catalogue gives a
series the soccer sport when its name CONTAINS a competition token
(`KXSERIEAWGAME` contains `SERIEA`) or its title STARTS WITH a competition name
('Bundesliga Basketball Game'). Women's clubs share their men's clubs' names, so
the event resolver then put Serie A Femminile contracts on men's Serie A games:
an offline replay of this join on the fleet's 09-30..10-19 data had 70% of
`KXSERIEAWGAME`'s decision instants more than 10pp off the sportsbook fair.

Every series name below is read from Kalshi's `/series` catalogue (2026-10-20).
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_catalogue as cat
from syndicate.features.shared.kalshi_board_join import (
    REASON_SERIES_COMPETITION,
    join_kalshi_to_board,
    series_competition_verdict,
    soccer_competition_for_series,
)

DATE = "2026-10-25"


def _market(ticker, series, title):
    return {
        "ticker": ticker,
        "series": series,
        "title": title,
        "yes_american": -150,
        "no_american": 120,
        "yes_probability": 0.6,
        "no_probability": 0.45,
    }


def _rows(sport, away, home):
    return [
        {
            "sport": sport,
            "event_id": "evt-1",
            "market": "h2h",
            "away_team": away,
            "home_team": home,
            "side": side,
            "line": None,
            "segment": "full",
            "model_edge_pct": 2.0,
            "quote": {"bookmaker": "book", "price": 100},
        }
        for side in ("home", "away", "draw")
    ]


@pytest.fixture
def game_lines(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    # KXBBLGAME and KXMLBBGAME reach a sport only through discovery, as they do
    # on the fleet; registered here and removed after.
    monkeypatch.setitem(cat._DISCOVERED, "KXBBLGAME", "soccer")
    monkeypatch.setitem(cat._DISCOVERED, "KXMLBBGAME", "mlb")


# (series, ticker, title, board away, board home). Each one PAIRED with the men's
# game before the gate -- measured on the pre-fix join with the same rows.
_OTHER_COMPETITION = [
    ("KXSERIEAWGAME", "KXSERIEAWGAME-26OCT25JUVROM-JUV", "Juventus wins", "Roma", "Juventus"),
    ("KXEREDIVISIEWGAME", "KXEREDIVISIEWGAME-26OCT25AJAPSV-AJA", "Ajax wins", "PSV Eindhoven", "Ajax"),
    ("KXBBLGAME", "KXBBLGAME-26OCT25FCBHSV-FCB", "Bayern Munich wins", "Hamburger SV", "Bayern Munich"),
    ("KXUCLWGAME", "KXUCLWGAME-26OCT25BARCHE-BAR", "Barcelona wins", "Chelsea", "Barcelona"),
]


def test_the_mens_serie_a_series_still_pairs_control_arm(game_lines):
    """The gate is per series. Without this, a refusal of everything would pass
    every test below."""
    report = join_kalshi_to_board(
        [_market("KXSERIEAGAME-26OCT25JUVROM-JUV", "KXSERIEAGAME", "Juventus wins")],
        _rows("soccer", "Roma", "Juventus"),
        selected_date=DATE,
    )
    assert len(report["matches"]) == 1, report["reasons"]
    assert REASON_SERIES_COMPETITION not in report["reasons"]
    assert report["competition_refused_by_series"] == {}


@pytest.mark.parametrize("series,ticker,title,away,home", _OTHER_COMPETITION)
def test_another_competitions_series_refuses_by_name_on_the_mens_game(
    game_lines, series, ticker, title, away, home
):
    report = join_kalshi_to_board(
        [_market(ticker, series, title)], _rows("soccer", away, home), selected_date=DATE
    )
    assert report["matches"] == [], report["matches"]
    assert report["reasons"] == {REASON_SERIES_COMPETITION: 1}, report["reasons"]
    assert report["competition_refused_by_series"] == {
        series: {"as": "unrecognised_soccer_competition", "n": 1}
    }


def test_a_non_soccer_series_filed_under_mlb_refuses(game_lines):
    """`MLB` is a substring of `KXMLBBGAME` (Mobile Legends Bang Bang)."""
    report = join_kalshi_to_board(
        [_market("KXMLBBGAME-26OCT25NYYBOS-NYY", "KXMLBBGAME", "New York Yankees wins")],
        [dict(r, sport="mlb") for r in _rows("mlb", "Boston Red Sox", "New York Yankees")[:2]],
        selected_date=DATE,
    )
    assert report["matches"] == []
    assert report["competition_refused_by_series"] == {
        "KXMLBBGAME": {"as": "mobile_legends_esports", "n": 1}
    }


# Soccer series in Kalshi's catalogue, 2026-10-20, whose family IS a board league.
_BOARD_COMPETITION = {
    "KXSERIEAGAME": "serie_a", "KXSERIEASPREAD": "serie_a", "KXSERIEATOTAL": "serie_a",
    "KXSERIEA1H": "serie_a", "KXSERIEA2HTOTAL": "serie_a", "KXSERIEATEAMTOTAL": "serie_a",
    "KXEPLGAME": "epl", "KXEPL1HSPREAD": "epl", "KXEPL1HTOTAL": "epl", "KXEPL2H": "epl",
    "KXLALIGAGAME": "la_liga", "KXLALIGA2H": "la_liga", "KXLALIGA1HTOTAL": "la_liga",
    # `2H` is the SECOND HALF here, not Bundesliga 2.
    "KXBUNDESLIGAGAME": "bundesliga", "KXBUNDESLIGA2H": "bundesliga",
    "KXBUNDESLIGA2HSPREAD": "bundesliga", "KXBUNDESLIGA1H": "bundesliga",
    "KXLIGUE1GAME": "ligue_1", "KXLIGUE11H": "ligue_1", "KXLIGUE12HTOTAL": "ligue_1",
    "KXMLSGAME": "mls", "KXMLSSPREAD": "mls", "KXMLSTOTAL": "mls",
    "KXEREDIVISIEGAME": "eredivisie", "KXEREDIVISIESPREAD": "eredivisie",
    "KXEFLCHAMPIONSHIPGAME": "championship", "KXEFLCHAMPIONSHIP1HTOTAL": "championship",
    "KXBELGIANPLGAME": "belgian_pro_league", "KXBELGIANPLTOTAL": "belgian_pro_league",
    "KXUCLGAME": "ucl", "KXUCL1H": "ucl", "KXUCLTEAMTOTAL": "ucl",
    "KXUELGAME": "uel", "KXUELTOTAL": "uel", "KXUECLGAME": "uecl", "KXUECLSPREAD": "uecl",
    "KXLALIGABTTS": "la_liga", "KXEPL1HBTTS": "epl", "KXSERIEACORNERS": "serie_a",
}


# Every soccer series the FLEET captured into `venue_odds/kalshi__soccer__*.json`,
# 2026-09 .. 2026-11-03 (read 2026-10-20, 37 series; no `SYNDICATE_KALSHI_SERIES`
# override on either worker). The gate's whole production effect is the four
# named here -- it is not a market-wide exclusion.
_FLEET_CAPTURED = (
    "KXBBLGAME KXBELGIANPLGAME KXBUNDESLIGA1H KXBUNDESLIGA2GAME KXBUNDESLIGAGAME "
    "KXBUNDESLIGASPREAD KXBUNDESLIGATOTAL KXEPL1HSPREAD KXEPL1HTOTAL KXEREDIVISIEGAME "
    "KXEREDIVISIESPREAD KXEREDIVISIETOTAL KXEREDIVISIEWGAME KXLALIGA1H KXLALIGAGAME "
    "KXLALIGASPREAD KXLALIGATOTAL KXLIGUE11H KXLIGUE1GAME KXLIGUE1SPREAD KXLIGUE1TOTAL "
    "KXMLSSPREAD KXMLSTOTAL KXSERIEA1H KXSERIEAGAME KXSERIEASPREAD KXSERIEATOTAL "
    "KXSERIEAWGAME KXUCL1H KXUCLGAME KXUCLSPREAD KXUECLGAME KXUECLSPREAD KXUECLTOTAL "
    "KXUELGAME KXUELSPREAD KXUELTOTAL"
).split()


def test_of_the_fleets_captured_soccer_series_exactly_the_other_competitions_refuse():
    refused = sorted(s for s in _FLEET_CAPTURED if series_competition_verdict(s, "soccer"))
    assert len(_FLEET_CAPTURED) == 37
    assert refused == ["KXBBLGAME", "KXBUNDESLIGA2GAME", "KXEREDIVISIEWGAME", "KXSERIEAWGAME"]

# ...and every catalogue series the catalogue calls soccer that is NOT one: women's,
# basketball, second tiers, another country's league, an all-star game.
_NOT_A_BOARD_COMPETITION = [
    "KXSERIEAWGAME", "KXEREDIVISIEWGAME", "KXBUNDESLIGAWGAME", "KXBUNDESLIGAWSPREAD",
    "KXBUNDESLIGAWTOTAL", "KXUCLWGAME", "KXUCLWSPREAD", "KXUCLWTOTAL",
    "KXBBLGAME", "KXBBSERIEAGAME", "KXBBSERIEASPREAD", "KXBBSERIEATOTAL",
    "KXBBSERIEA2GAME", "KXBBWSERIEAGAME",
    "KXBUNDESLIGA2GAME", "KXBUNDESLIGA2SPREAD", "KXBUNDESLIGA2TOTAL",
    "KXLALIGA2GAME", "KXLALIGA2SPREAD", "KXLALIGA2TOTAL",
    "KXUAEPLGAME", "KXUAEPLSPREAD", "KXUAEPLTOTAL",
    "KXMLSASTGAME", "KXMLSASTSPREAD", "KXMLSASTTOTAL",
]


@pytest.mark.parametrize("series,league", sorted(_BOARD_COMPETITION.items()))
def test_a_board_competition_series_maps_to_exactly_its_league(series, league):
    assert soccer_competition_for_series(series) == league
    assert series_competition_verdict(series, "soccer") is None


@pytest.mark.parametrize("series", _NOT_A_BOARD_COMPETITION)
def test_another_competition_never_maps_to_the_league_it_contains(series):
    assert soccer_competition_for_series(series) is None
    assert series_competition_verdict(series, "soccer") == "unrecognised_soccer_competition"


def test_every_competition_is_a_league_the_board_models():
    from syndicate.features.shared.kalshi_board_join import _SOCCER_COMPETITION_BY_FAMILY
    from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES

    assert set(_SOCCER_COMPETITION_BY_FAMILY.values()) <= set(LEAGUE_DISPLAY_NAMES)


def test_college_baseball_is_refused_but_a_basketball_tournament_is_not():
    """Exact names: `KXNCAABBIG10` is the Big Ten MEN'S BASKETBALL tournament."""
    assert series_competition_verdict("KXNCAABBGAME", "ncaab") == "college_baseball"
    assert series_competition_verdict("KXNCAABBIG10", "ncaab") is None
    assert series_competition_verdict("KXNCAABGAME", "ncaab") is None
    assert series_competition_verdict("KXMLBGAME", "mlb") is None
