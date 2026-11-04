"""Kalshi men's college basketball pairs with the NCAAB board (todo #755 (b),
lane ncaab-kalshi-pairing).

Kalshi spells the sport `NCAAMB` and the catalogue's sport token is `NCAAB`, so
no men's game series ever had a sport: measured 2026-11-01, `VENUE_REPRICE_KEYS`
had 802 of 802 NCAAB keys unmatched. Three things are covered here:

  1. REGISTRATION. `KXNCAAMBGAME` / `KXNCAAMBSPREAD` / `KXNCAAMBTOTAL` by name,
     and nothing else: the ~80 other `KXNCAAMB*` series are futures.
  2. SCHOOL NAMES. 272 of 282 Kalshi names resolved through the D1 registry on
     2026-11-03; nine of the ten misses are Kalshi spellings ("Miami (FL)",
     "New Orleans"), mapped explicitly. The tenth is not Division I.
  3. CAPTURE. NCAAB game lines reach the quote log: 0 exchange rows in 194,619
     NCAAB quotes (11-02..11-04), so there is no OddsAPI copy to collide with.

Every ticker and title below is real, read 2026-11-03 from Kalshi's public
listing. The board names are the fleet shortlist's own (OddsAPI spellings).
Measured the same day, read-only on the fleet: 45 of 98 NCAAB shortlist rows on
11-03 paired, 17 of 19 games; the other two carried only a total at a line
Kalshi does not list.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_catalogue as cat
from syndicate.features.shared.kalshi_board_join import join_kalshi_to_board
from syndicate.features.shared.odds_book_quotes import sport_allows_game_line_capture

_SERIES = ("KXNCAAMBGAME", "KXNCAAMBSPREAD", "KXNCAAMBTOTAL")


@pytest.fixture(autouse=True)
def _game_lines_on(monkeypatch):
    """Game lines are priced only behind `SYNDICATE_KALSHI_GAME_LINES`. It is on
    for refresh-worker: the 2026-11-03 fleet read, run under that service's
    environment, matched NCAAB moneylines, spreads and totals."""
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")

# North Dakota St. at Saint Mary's, 2026-11-04.
_NDSU_SMC = {
    "event_id": "evt-ndsu-smc",
    "sport": "ncaab",
    "away_team": "North Dakota St Bison",
    "home_team": "Saint Mary's Gaels",
}
# New Orleans at LSU, 2026-11-03. Kalshi's "New Orleans" is the registry's
# "LSU New Orleans", so this game pairs only through the spelling table.
_UNO_LSU = {
    "event_id": "evt-uno-lsu",
    "sport": "ncaab",
    "away_team": "New Orleans Privateers",
    "home_team": "LSU Tigers",
}


def _kalshi(ticker, title, yes=-150, no=120):
    return {
        "ticker": ticker,
        "series": ticker.split("-", 1)[0],
        "event_ticker": "-".join(ticker.split("-")[:2]),
        "title": title,
        "yes_american": yes,
        "no_american": no,
        "yes_probability": 0.6,
        "no_probability": 0.45,
    }


def _row(game, market, side, line=None):
    return dict(game, market=market, side=side, line=line, segment="full",
                quote={"bookmaker": "draftkings", "price": -110})


_NDSU_SMC_MARKETS = [
    _kalshi("KXNCAAMBGAME-26NOV04NDSUSMC-SMC", "Saint Mary's wins", yes=-733, no=500),
    _kalshi("KXNCAAMBGAME-26NOV04NDSUSMC-NDSU", "North Dakota St. wins", yes=600, no=-900),
    _kalshi("KXNCAAMBSPREAD-26NOV04NDSUSMC-SMC13", "Saint Mary's wins by over 12.5 points",
            yes=-110, no=-110),
    _kalshi("KXNCAAMBTOTAL-26NOV04NDSUSMC-150", "Full Game: Over 149.5 points scored",
            yes=-127, no=-144),
]

_UNO_LSU_MARKETS = [
    _kalshi("KXNCAAMBGAME-26NOV03UNOLSU-LSU", "LSU wins", yes=-5000, no=2000),
    _kalshi("KXNCAAMBGAME-26NOV03UNOLSU-UNO", "New Orleans wins", yes=2000, no=-5000),
    _kalshi("KXNCAAMBSPREAD-26NOV03UNOLSU-LSU27", "LSU wins by over 26.5 points",
            yes=-120, no=108),
]


# ---------------------------------------------------------------------------
# 1. Registration: by name, the full-game series only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("series", _SERIES)
def test_each_series_is_registered_as_a_full_game_ncaab_series(series):
    assert cat.sport_for_series(series) == "ncaab"
    assert cat.segment_for_series(series) == "full"


@pytest.mark.parametrize("market,expected", [
    (_NDSU_SMC_MARKETS[0], ("h2h", None, "yes")),
    (_NDSU_SMC_MARKETS[2], ("spreads", 12.5, "over")),
    (_NDSU_SMC_MARKETS[3], ("totals", 149.5, "over")),
])
def test_a_real_title_from_each_series_classifies(market, expected):
    verdict = cat.classify_market(market)
    assert verdict["status"] == "ok", verdict
    assert verdict["sport"] == "ncaab"
    assert (verdict["market"], verdict.get("line"), verdict["side"]) == expected


def test_OFF_IS_NOT_ON_without_the_registry_line_the_market_is_refused(monkeypatch):
    monkeypatch.delitem(cat.SERIES_SPORT, "KXNCAAMBGAME")
    verdict = cat.classify_market(_NDSU_SMC_MARKETS[0])
    assert verdict["status"] == "refused"
    assert verdict["reason"] == cat.REASON_UNMAPPED_SERIES


def test_the_kalshi_spelling_is_still_not_a_sport_token():
    """By name, not by token: `NCAAMB` as a token would hand discovery the
    futures series below. The control shows discovery itself works."""
    assert cat.sport_for_ticker("KXNCAAMBGAME") is None
    futures = {
        "KXNCAAMBWINS": "Men's College Basketball Win Totals",
        "KXNCAAMBACC": "ACC Conference Tournament",
        "KXNCAAMBAPRANK": "Men's College Basketball AP Poll",
    }
    assert cat.auto_game_series_from_catalogue(futures) == {}
    assert all(cat.sport_for_series(s) is None for s in futures)
    assert cat.auto_game_series_from_catalogue({"KXNBAGAME": "Pro Basketball Game"}) == {"KXNBAGAME": "nba"}


def test_the_first_half_winner_stays_refused():
    """`KXNCAAMB1H` carries a tie leg and has no board market; it must not read
    as a full-game series."""
    assert cat.sport_for_series("KXNCAAMB1H") is None
    assert cat.segment_for_series("KXNCAAMB1H") != "full"


# ---------------------------------------------------------------------------
# 2. The join pairs each series with the board's own rows
# ---------------------------------------------------------------------------


def _join(markets, rows, date):
    return join_kalshi_to_board(markets, rows, selected_date=date)


def test_moneyline_spread_and_total_each_pair_with_the_right_row():
    rows = [
        _row(_NDSU_SMC, "h2h", "home"),
        _row(_NDSU_SMC, "spreads", "home", -12.5),
        _row(_NDSU_SMC, "totals", "over", 149.5),
        _row(_NDSU_SMC, "totals", "under", 149.5),
    ]
    report = _join(_NDSU_SMC_MARKETS, rows, "2026-11-04")
    got = sorted((m["market"], m["board_side"], m.get("line"), m["ticker"], m["kalshi_side"])
                 for m in report["matches"])
    assert got == [
        ("h2h", "home", None, "KXNCAAMBGAME-26NOV04NDSUSMC-SMC", "yes"),
        ("spreads", "home", -12.5, "KXNCAAMBSPREAD-26NOV04NDSUSMC-SMC13", "yes"),
        ("totals", "over", 149.5, "KXNCAAMBTOTAL-26NOV04NDSUSMC-150", "yes"),
        ("totals", "under", 149.5, "KXNCAAMBTOTAL-26NOV04NDSUSMC-150", "no"),
    ], report.get("reasons")
    assert {m["board_event_id"] for m in report["matches"]} == {"evt-ndsu-smc"}


def test_the_underdog_side_of_a_spread_takes_NOs_price():
    """'LSU wins by over 26.5' is LSU -26.5; the board's New Orleans +26.5 is
    the other side of that contract, so it is priced at NO."""
    report = _join(_UNO_LSU_MARKETS, [_row(_UNO_LSU, "spreads", "away", 26.5)], "2026-11-03")
    assert [(m["ticker"], m["kalshi_side"], m["kalshi_american"]) for m in report["matches"]] == [
        ("KXNCAAMBSPREAD-26NOV03UNOLSU-LSU27", "no", 108.0)]


def test_a_market_for_another_date_does_not_pair():
    """The slate gate: an 11-04 contract against the 11-03 board."""
    report = _join(_NDSU_SMC_MARKETS, [_row(_NDSU_SMC, "h2h", "home")], "2026-11-03")
    assert report["matched"] == 0


def test_OFF_IS_NOT_ON_the_join_matches_nothing_without_the_registry(monkeypatch):
    for series in _SERIES:
        monkeypatch.delitem(cat.SERIES_SPORT, series)
    rows = [_row(_NDSU_SMC, "h2h", "home"), _row(_NDSU_SMC, "totals", "over", 149.5)]
    assert _join(_NDSU_SMC_MARKETS, rows, "2026-11-04")["matched"] == 0


# ---------------------------------------------------------------------------
# 3. Kalshi's school spellings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kalshi,school", sorted(cat._KALSHI_COLLEGE_BASKETBALL_SPELLINGS.items()))
def test_each_kalshi_spelling_resolves_to_its_registry_school(kalshi, school):
    from syndicate.features.shared.team_aliases import chip_join_key

    target = chip_join_key("ncaab", school)
    assert target, f"{school!r} is no longer a registry school"
    assert chip_join_key("ncaab", kalshi) is None, f"{kalshi!r} now resolves directly; drop it"
    assert cat.club_key("ncaab", kalshi) == target


@pytest.mark.parametrize("kalshi,board", [
    ("Miami (FL)", "Miami Hurricanes"),
    ("New Orleans", "New Orleans Privateers"),
    ("Nicholls St.", "Nicholls Colonels"),
    ("Tennessee-Martin", "UT Martin Skyhawks"),
    ("University at Albany", "UAlbany Great Danes"),
])
def test_kalshis_spelling_and_the_boards_spelling_are_one_school(kalshi, board):
    assert cat.club_key("ncaab", kalshi) == cat.club_key("ncaab", board) is not None


def test_the_two_miamis_stay_apart():
    assert cat.club_key("ncaab", "Miami (FL)") != cat.club_key("ncaab", "Miami (OH)")
    assert cat.club_key("ncaab", "Miami (OH)") == cat.club_key("ncaab", "Miami (OH) RedHawks")


def test_a_school_outside_division_one_stays_unresolved():
    assert cat.club_key("ncaab", "Bethesda") is None


def test_the_table_is_college_basketball_only():
    """Shared with `wncaab` since 2026-11-04 (`tests/test_kalshi_wncaab_pairing.py`)."""
    assert cat.club_key("ncaaf", "Tennessee-Martin") != cat.club_key("ncaab", "Tennessee-Martin")


def test_OFF_IS_NOT_ON_without_the_spelling_the_game_does_not_pair(monkeypatch):
    rows = [_row(_UNO_LSU, "spreads", "away", 26.5)]
    assert _join(_UNO_LSU_MARKETS, rows, "2026-11-03")["matched"] == 1
    monkeypatch.delitem(cat._KALSHI_COLLEGE_BASKETBALL_SPELLINGS, "New Orleans")
    assert _join(_UNO_LSU_MARKETS, rows, "2026-11-03")["matched"] == 0


# ---------------------------------------------------------------------------
# 4. The capture writes NCAAB game lines
# ---------------------------------------------------------------------------


def _capture(monkeypatch, matches, board_rows, *, date="2026-11-04"):
    from pipeline import kalshi_odds_refresh as k
    import syndicate.features.shared.odds_book_quotes as obq

    seen: list[dict] = []

    def fake_append(*, sport, date_str, rows, captured_at, publish=True, extra=None):
        seen.append({"sport": sport, "date_str": date_str, "rows": list(rows)})
        return {"appended": len(list(rows))}

    monkeypatch.setattr(obq, "append_book_quotes", fake_append)
    k._capture_kalshi_quotes({"matches": matches}, board_rows, selected_date=date)
    return seen


def _game_match(**over):
    match = {"ticker": "KXNCAAMBGAME-26NOV04NDSUSMC-SMC", "series": "KXNCAAMBGAME",
             "market": "h2h", "player_name": None, "line": None, "board_side": "home",
             "kalshi_side": "yes", "kalshi_american": -733, "board_event_id": "evt-ndsu-smc",
             "game_line": True}
    match.update(over)
    return match


def test_an_ncaab_game_line_reaches_the_writer(monkeypatch):
    assert sport_allows_game_line_capture("ncaab")
    seen = _capture(monkeypatch, [_game_match()], [dict(_NDSU_SMC)])
    assert [(s["sport"], s["date_str"]) for s in seen] == [("ncaab", "2026-11-04")]
    row = seen[0]["rows"][0]
    assert (row["kind"], row["market"], row["selection"], row["bookmaker"]) == ("game", "h2h", "home", "kalshi")
    assert row["home_team"] == "Saint Mary's Gaels"


def test_OFF_IS_NOT_ON_without_the_capture_line_it_is_dropped(monkeypatch):
    import syndicate.features.shared.odds_book_quotes as obq

    monkeypatch.setattr(obq, "_GAME_LINE_CAPTURE_SPORTS", frozenset({"soccer", "nhl"}))
    assert _capture(monkeypatch, [_game_match()], [dict(_NDSU_SMC)]) == []
