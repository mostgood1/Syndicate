"""Kalshi women's college basketball pairs with the WNCAAB board (todo #755,
lane wncaab-kalshi-pairing).

The `NCAAWB` sport token (lane wncaab-module, 2026-11-02) already let discovery
fetch Kalshi's women's moneylines and spreads. Measured 2026-11-04 on the fleet,
five gaps stood between those markets and a priced board row:

  1. TOTALS. `KXNCAAWBTOTAL`'s series title has no game-market tail, so it was
     never discovered, and `market_keys._TOTAL_UNIT` had no `wncaab`, so its
     "points" refused anyway: 189 of 189 open, `stat_not_in_market_vocabulary`.
  2. JOIN ROWS. Women's rows reach no Layer 2 shortlist (cand=34, all `dead`),
     and `venue_odds_loop._GRID_SPORTS` left `wncaab` out, so the coverage join
     never held a women's game. JOIN_EVENTS 03:33Z: `IDSTBYU` unmatched while
     Idaho State @ BYU sat on the 11-03 grid.
  3. SCHOOL NAMES. 284 of 295 open names resolved; the men's spelling table
     already covered six of the misses and now serves both leagues.
  4. CAPTURE. 0 exchange rows in 8,483 WNCAAB quotes (11-02..11-05).
  5. FUTURES. The token also admitted `KXNCAAWBWINS`: 30 markets, all
     `unreadable_title`, fetched every rotation.

Every ticker and title below is real, read 2026-11-04 from Kalshi's public
listing; board names are OddsAPI's. Read-only on the fleet with this code, all
18 games on the 11-03 women's grid resolved to a Kalshi event.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_catalogue as cat
from syndicate.features.shared import market_keys
from syndicate.features.shared.kalshi_board_join import join_kalshi_to_board
from syndicate.features.shared.odds_book_quotes import sport_allows_game_line_capture

_SERIES = ("KXNCAAWBGAME", "KXNCAAWBSPREAD", "KXNCAAWBTOTAL")


@pytest.fixture(autouse=True)
def _game_lines_on(monkeypatch):
    """Game lines are priced only behind `SYNDICATE_KALSHI_GAME_LINES`, which is
    on for refresh-worker."""
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")


# Campbell at NC State, 2026-11-04. Kalshi's "North Carolina St." is the
# registry's "NC State", so this game pairs only through the spelling table.
_CAMP_NCST = {
    "event_id": "evt-camp-ncst",
    "sport": "wncaab",
    "away_team": "Campbell Fighting Camels",
    "home_team": "NC State Wolfpack",
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


_CAMP_NCST_MARKETS = [
    _kalshi("KXNCAAWBGAME-26NOV04CAMPNCST-NCST", "North Carolina St. wins", yes=-1400, no=900),
    _kalshi("KXNCAAWBGAME-26NOV04CAMPNCST-CAMP", "Campbell wins", yes=900, no=-1400),
    _kalshi("KXNCAAWBSPREAD-26NOV04CAMPNCST-NCST27", "North Carolina St. wins by over 26.5 points",
            yes=-105, no=-115),
    _kalshi("KXNCAAWBTOTAL-26NOV04CAMPNCST-136", "Full Game: Over 135.5 points scored",
            yes=-120, no=-110),
]
_STANFORD_ML = _kalshi("KXNCAAWBGAME-26NOV04SMCSTAN-STAN", "Stanford wins")


# ---------------------------------------------------------------------------
# 1. Registration and totals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("series", _SERIES)
def test_each_series_is_registered_as_a_full_game_wncaab_series(series):
    assert cat.SERIES_SPORT[series] == "wncaab"
    assert cat.sport_for_series(series) == "wncaab"
    assert cat.segment_for_series(series) == "full"


@pytest.mark.parametrize("market,expected", [
    (_STANFORD_ML, ("h2h", None, "yes")),
    (_CAMP_NCST_MARKETS[2], ("spreads", 26.5, "over")),
    (_CAMP_NCST_MARKETS[3], ("totals", 135.5, "over")),
])
def test_a_real_title_from_each_series_classifies(market, expected):
    verdict = cat.classify_market(market)
    assert verdict["status"] == "ok", verdict
    assert verdict["sport"] == "wncaab"
    assert (verdict["market"], verdict.get("line"), verdict["side"]) == expected


def test_OFF_IS_NOT_ON_without_the_scoring_unit_a_total_refuses(monkeypatch):
    monkeypatch.delitem(market_keys._TOTAL_UNIT, "wncaab")
    verdict = cat.classify_market(_CAMP_NCST_MARKETS[3])
    assert verdict["status"] == "refused"
    assert verdict["reason"] == cat.REASON_UNMAPPED_STAT
    assert verdict["detail"] == "Full Game points scored"


def test_the_total_was_never_discovered_by_title():
    """Why it is registered by name: discovery reads the series title's tail."""
    assert cat.auto_game_series_from_catalogue(
        {"KXNCAAWBTOTAL": "Women's College Basketball Total Points"}) == {}


def test_win_totals_are_evicted_and_the_game_series_is_still_discovered():
    titles = {
        "KXNCAAWBWINS": "Women's College Basketball Win Totals",
        "KXNCAAWBGAME": "Women's College Basketball Game",
    }
    assert cat.auto_game_series_from_catalogue(titles) == {"KXNCAAWBGAME": "wncaab"}


def test_OFF_IS_NOT_ON_without_the_eviction_win_totals_are_fetched(monkeypatch):
    monkeypatch.delitem(cat.SERIES_OUT_OF_SCOPE, "KXNCAAWBWINS")
    assert cat.auto_game_series_from_catalogue(
        {"KXNCAAWBWINS": "Women's College Basketball Win Totals"}) == {"KXNCAAWBWINS": "wncaab"}


@pytest.mark.parametrize("series", ["KXNCAAWB1H", "KXNCAAWB1Q", "KXNCAAWB2HTOTAL", "KXNCAAWB4QSPREAD"])
def test_quarter_and_half_series_stay_refused(series):
    """Full game only: none of these is registered, and their segment is not `full`."""
    assert series not in cat.SERIES_SPORT
    assert cat.segment_for_series(series) != "full"


# ---------------------------------------------------------------------------
# 2. The join pairs each series with the board's own rows
# ---------------------------------------------------------------------------


def _join(markets, rows, date):
    return join_kalshi_to_board(markets, rows, selected_date=date)


def test_moneyline_spread_and_total_each_pair_with_the_right_row():
    rows = [
        _row(_CAMP_NCST, "h2h", "home"),
        _row(_CAMP_NCST, "spreads", "home", -26.5),
        _row(_CAMP_NCST, "totals", "over", 135.5),
        _row(_CAMP_NCST, "totals", "under", 135.5),
    ]
    report = _join(_CAMP_NCST_MARKETS, rows, "2026-11-04")
    got = sorted((m["market"], m["board_side"], m.get("line"), m["ticker"], m["kalshi_side"])
                 for m in report["matches"])
    assert got == [
        ("h2h", "home", None, "KXNCAAWBGAME-26NOV04CAMPNCST-NCST", "yes"),
        ("spreads", "home", -26.5, "KXNCAAWBSPREAD-26NOV04CAMPNCST-NCST27", "yes"),
        ("totals", "over", 135.5, "KXNCAAWBTOTAL-26NOV04CAMPNCST-136", "yes"),
        ("totals", "under", 135.5, "KXNCAAWBTOTAL-26NOV04CAMPNCST-136", "no"),
    ], report.get("reasons")
    assert {m["board_event_id"] for m in report["matches"]} == {"evt-camp-ncst"}


def test_the_underdog_side_of_a_spread_takes_NOs_price():
    report = _join(_CAMP_NCST_MARKETS, [_row(_CAMP_NCST, "spreads", "away", 26.5)], "2026-11-04")
    assert [(m["ticker"], m["kalshi_side"], m["kalshi_american"]) for m in report["matches"]] == [
        ("KXNCAAWBSPREAD-26NOV04CAMPNCST-NCST27", "no", -115.0)]


def test_a_market_for_another_date_does_not_pair():
    report = _join(_CAMP_NCST_MARKETS, [_row(_CAMP_NCST, "h2h", "home")], "2026-11-03")
    assert report["matched"] == 0


def test_OFF_IS_NOT_ON_the_join_matches_nothing_without_the_registry(monkeypatch):
    """Discovery would register the moneyline in production; the join reads the
    registry, and with neither it has nothing to place."""
    for series in _SERIES:
        monkeypatch.delitem(cat.SERIES_SPORT, series)
    rows = [_row(_CAMP_NCST, "h2h", "home"), _row(_CAMP_NCST, "totals", "over", 135.5)]
    assert _join(_CAMP_NCST_MARKETS, rows, "2026-11-04")["matched"] == 0


def test_OFF_IS_NOT_ON_without_the_spelling_the_game_does_not_pair(monkeypatch):
    rows = [_row(_CAMP_NCST, "h2h", "home")]
    assert _join(_CAMP_NCST_MARKETS, rows, "2026-11-04")["matched"] == 1
    monkeypatch.delitem(cat._KALSHI_COLLEGE_BASKETBALL_SPELLINGS, "North Carolina St.")
    assert _join(_CAMP_NCST_MARKETS, rows, "2026-11-04")["matched"] == 0


# ---------------------------------------------------------------------------
# 3. One spelling table for both college leagues
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kalshi,school", sorted(cat._KALSHI_COLLEGE_BASKETBALL_SPELLINGS.items()))
def test_each_kalshi_spelling_resolves_to_its_womens_registry_school(kalshi, school):
    from syndicate.features.shared.team_aliases import chip_join_key

    target = chip_join_key("wncaab", school)
    assert target, f"{school!r} is no longer a women's registry school"
    assert chip_join_key("wncaab", kalshi) is None, f"{kalshi!r} now resolves directly; drop it"
    assert cat.club_key("wncaab", kalshi) == target


@pytest.mark.parametrize("kalshi,board", [
    ("North Carolina St.", "NC State Wolfpack"),
    ("Southeastern Louisiana", "SE Louisiana Lions"),
    ("Southern University", "Southern Jaguars"),
])
def test_kalshis_spelling_and_the_boards_spelling_are_one_school(kalshi, board):
    """Each board name is from the fleet's 11-03 women's grid."""
    assert cat.club_key("wncaab", kalshi) == cat.club_key("wncaab", board) is not None


@pytest.mark.parametrize("name", ["District of Columbia", "Johnson C. Smith"])
def test_a_school_outside_division_one_stays_unresolved(name):
    assert cat.club_key("wncaab", name) is None


def test_the_two_miamis_stay_apart():
    assert cat.club_key("wncaab", "Miami (FL)") != cat.club_key("wncaab", "Miami (OH)")


# ---------------------------------------------------------------------------
# 4. The coverage join sees women's games
# ---------------------------------------------------------------------------


_GRID = {"wncaab": {"rows": [
    {"event_id": "evt-camp-ncst", "market": "totals", "line": 135.5, "segment": "full",
     "sides": ["over", "under"], "home_team": "NC State Wolfpack",
     "away_team": "Campbell Fighting Camels", "commence_time": "2026-11-04T23:00:00Z"},
]}}


def _grid_rows(monkeypatch):
    from pipeline import venue_odds_loop as vol
    from syndicate.features.shared import book_grid_artifact
    from syndicate.features.soccer import sources

    monkeypatch.setattr(book_grid_artifact, "read_book_grid_artifact", lambda sport, day: _GRID.get(sport))
    monkeypatch.setattr(sources, "game_odds_rows", lambda league: ())
    return vol


def test_the_womens_grid_reaches_the_join_rows(monkeypatch):
    vol = _grid_rows(monkeypatch)
    rows = vol.all_game_line_rows("2026-11-04")
    assert [(r["sport"], r["market"], r["side"], r["line"]) for r in rows] == [
        ("wncaab", "totals", "over", 135.5), ("wncaab", "totals", "under", 135.5)]
    report = _join(_CAMP_NCST_MARKETS, rows, "2026-11-04")
    assert report["matched"] == 2, report.get("reasons")


def test_OFF_IS_NOT_ON_without_wncaab_in_the_grid_sports_no_row_is_read(monkeypatch):
    vol = _grid_rows(monkeypatch)
    monkeypatch.setattr(vol, "_GRID_SPORTS", tuple(s for s in vol._GRID_SPORTS if s != "wncaab"))
    assert vol.all_game_line_rows("2026-11-04") == []


# ---------------------------------------------------------------------------
# 5. The capture writes WNCAAB game lines
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
    match = {"ticker": "KXNCAAWBGAME-26NOV04CAMPNCST-NCST", "series": "KXNCAAWBGAME",
             "market": "h2h", "player_name": None, "line": None, "board_side": "home",
             "kalshi_side": "yes", "kalshi_american": -1400, "board_event_id": "evt-camp-ncst",
             "game_line": True}
    match.update(over)
    return match


def test_a_wncaab_game_line_reaches_the_writer(monkeypatch):
    assert sport_allows_game_line_capture("wncaab")
    seen = _capture(monkeypatch, [_game_match()], [dict(_CAMP_NCST)])
    assert [(s["sport"], s["date_str"]) for s in seen] == [("wncaab", "2026-11-04")]
    row = seen[0]["rows"][0]
    assert (row["kind"], row["market"], row["selection"], row["bookmaker"]) == ("game", "h2h", "home", "kalshi")
    assert row["home_team"] == "NC State Wolfpack"


def test_OFF_IS_NOT_ON_without_the_capture_line_it_is_dropped(monkeypatch):
    import syndicate.features.shared.odds_book_quotes as obq

    monkeypatch.setattr(obq, "_GAME_LINE_CAPTURE_SPORTS", frozenset({"soccer", "nhl", "ncaab"}))
    assert _capture(monkeypatch, [_game_match()], [dict(_CAMP_NCST)]) == []
