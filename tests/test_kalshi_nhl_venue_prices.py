"""NHL reaches the venue-priced book (lane nhl-venue-price-gap).

MEASURED on the fleet 2026-10-31: 0 of 618 NHL DecisionRecords carried a Kalshi
or Polymarket price (NFL: 158 of 1,056), so no paper strategy could book NHL.
Two mechanisms, each covered here end to end:

  1. PROPS. Kalshi titles its NHL prop series 'Pro Hockey Points', 'NHL
     Goalscorer' and 'Pro Hockey Assists'. The discovery gate wants "Player
     <stat>", so none was registered and none was ever fetched.
  2. GAME LINES. The join matched NHL game markets and the quote capture dropped
     every one, because `_GAME_LINE_CAPTURE_SPORTS` was soccer-only.

A third was found while fixing the first: NHL's shard files props as `POINTS`,
so a Kalshi row under `player_points` would have been its own one-book grid row,
which is the NFL defect of 2026-09-10 over again.

Every Kalshi ticker and title below is real, read 2026-11-01T15:52Z from
Kalshi's public listing (Ottawa at Anaheim, 2026-11-01).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import kalshi_catalogue as cat
from syndicate.features.shared.kalshi_board_join import join_kalshi_to_board
from syndicate.features.shared.market_keys import canonical_market_key
from syndicate.features.shared.odds_book_quotes import (
    book_quote_prop_market,
    quote_rows_from_kalshi_matches,
    sport_allows_game_line_capture,
)

# Kalshi's own series titles, from `/series/<ticker>`.
_SERIES_TITLES = {
    "KXNHLPTS": "Pro Hockey Points",
    "KXNHLGOAL": "NHL Goalscorer",
    "KXNHLAST": "Pro Hockey Assists",
}

# (ticker, title, canonical market, the board's code, Kalshi strike as a line)
_PROPS = [
    ("KXNHLPTS-26NOV01OTTANA-OTTTSTUTZLE18-1", "Tim Stutzle: 1+ points", "player_points", "POINTS", 0.5),
    ("KXNHLGOAL-26NOV01OTTANA-OTTTSTUTZLE18-1", "Tim Stutzle: 1+ goals", "player_goals", "GOALS", 0.5),
    ("KXNHLAST-26NOV01OTTANA-OTTTSTUTZLE18-2", "Tim Stutzle: 2+ assists", "player_assists", "ASSISTS", 1.5),
]

_OTT_AT_ANA = {
    "event_id": "evt-ottana",
    "sport": "nhl",
    "home_team": "Anaheim Ducks",
    "away_team": "Ottawa Senators",
    "commence_time": "2026-11-02T00:00:00Z",
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


def _board_row(code, line, side="Over", player="Tim Stutzle"):
    """An NHL board prop as the board spells it: the grid CODE, not the key."""
    return {
        "sport": "nhl",
        "event_id": _OTT_AT_ANA["event_id"],
        "market": code,
        "player_name": player,
        "line": line,
        "side": side,
        "model_edge_pct": 2.0,
        "quote": {"bookmaker": "pinnacle", "price": -140},
    }


# ---------------------------------------------------------------------------
# 1. Registration: the series are fetched at all
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("series", sorted(_SERIES_TITLES))
def test_each_nhl_prop_series_is_registered_as_a_full_game_nhl_series(series):
    assert cat.sport_for_series(series) == "nhl"
    assert cat.segment_for_series(series) == "full"


def test_OFF_the_title_gate_alone_registers_none_of_them():
    """Why the registry lines are needed. The control proves the gate itself
    works, so the empty result is about these titles and not a broken gate."""
    assert cat.auto_series_from_catalogue(_SERIES_TITLES) == {}
    assert cat.auto_series_from_catalogue({"KXNBAPTS": "NBA Player Points"}) == {"KXNBAPTS": "nba"}


@pytest.mark.parametrize("ticker,title,market,_code,line", _PROPS)
def test_a_real_nhl_prop_title_classifies(ticker, title, market, _code, line):
    verdict = cat.classify_market(_kalshi(ticker, title))
    assert verdict["status"] == "ok", verdict
    assert (verdict["sport"], verdict["market"], verdict["line"], verdict["side"]) == (
        "nhl", market, line, "over")
    assert verdict["subject"] == "Tim Stutzle"


def test_OFF_IS_NOT_ON_without_the_registry_line_the_market_is_refused(monkeypatch):
    monkeypatch.delitem(cat.SERIES_SPORT, "KXNHLPTS")
    ticker, title = _PROPS[0][:2]
    verdict = cat.classify_market(_kalshi(ticker, title))
    assert verdict["status"] == "refused"
    assert verdict["reason"] == cat.REASON_UNMAPPED_SERIES


# ---------------------------------------------------------------------------
# 2. The join pairs them with the NHL board's own rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ticker,title,market,code,line", _PROPS)
def test_the_join_pairs_each_series_with_the_board_row_spelled_as_the_board_spells_it(
    ticker, title, market, code, line
):
    report = join_kalshi_to_board([_kalshi(ticker, title)], [_board_row(code, line)],
                                  selected_date="2026-11-01")
    assert report["matched"] == 1, report.get("reasons")
    match = report["matches"][0]
    assert (match["market"], match["player_name"], match["line"]) == (market, "Tim Stutzle", line)
    assert (match["board_side"], match["kalshi_side"]) == ("over", "yes")
    assert match["board_event_id"] == "evt-ottana"


def test_the_under_takes_NOs_price():
    ticker, title, _m, code, line = _PROPS[2]
    report = join_kalshi_to_board([_kalshi(ticker, title, yes=-150, no=120)],
                                  [_board_row(code, line, side="Under")])
    assert [(m["kalshi_side"], m["kalshi_american"]) for m in report["matches"]] == [("no", 120.0)]


def test_OFF_IS_NOT_ON_the_join_matches_nothing_without_the_registry(monkeypatch):
    for series in _SERIES_TITLES:
        monkeypatch.delitem(cat.SERIES_SPORT, series)
    markets = [_kalshi(t, title) for t, title, *_ in _PROPS]
    rows = [_board_row(code, line) for *_, code, line in _PROPS]
    assert join_kalshi_to_board(markets, rows)["matched"] == 0


# ---------------------------------------------------------------------------
# 3. The quote lands in the SAME grid row as Pinnacle's
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("_t,_title,market,code,_line", _PROPS)
def test_a_kalshi_nhl_prop_is_filed_under_the_shards_code(_t, _title, market, code, _line):
    assert book_quote_prop_market("nhl", market) == code


def test_the_codes_are_the_nhl_prop_joins_own():
    """Pinned against `prop_projections._MARKET_CODES`, which reads the book
    grid's codes, so a renamed code fails here instead of splitting the grid."""
    from syndicate.features.nhl.prop_projections import _MARKET_CODES

    for code in _MARKET_CODES.values():
        canonical = canonical_market_key("nhl", code)
        assert canonical is not None, code
        assert book_quote_prop_market("nhl", canonical) == code


def test_OFF_IS_NOT_ON_mlb_and_nfl_labels_are_unchanged():
    assert book_quote_prop_market("mlb", "batter_home_runs") == "batter_home_runs"
    assert book_quote_prop_market("nfl", "player_receptions") == "Receptions"
    assert book_quote_prop_market(None, "player_points") == "player_points"


def test_on_the_GRID_the_kalshi_nhl_quote_is_a_cell_in_pinnacles_row():
    """Asserted on `build_book_grid`'s output. The unrelabelled control must
    reproduce the defect, or the merged case proves nothing."""
    from syndicate.features.shared.book_grid import build_book_grid
    from syndicate.features.shared.book_shortlist import (
        QUOTE_SOURCE_FIELD,
        QUOTE_SOURCE_VENUE_DIRECT,
    )
    from syndicate.features.shared.odds_book_quotes import _normalize

    identity = {k: _OTT_AT_ANA[k] for k in ("home_team", "away_team", "commence_time")}
    stamp = "2026-11-01T22:00:00Z"
    pinnacle = [
        _normalize(
            {"bookmaker": "pinnacle", "market": "POINTS", "selection": side,
             "player_name": "Tim Stutzle", "line": 0.5, "price": price,
             "event_id": "evt-ottana", "kind": "prop", **identity},
            sport="nhl", date_str="2026-11-01", captured_at=stamp,
        )
        for side, price in (("over", -180), ("under", 145))
    ]

    def kalshi(sport):
        matches = [
            {"market": "player_points", "player_name": "Tim Stutzle", "line": 0.5,
             "board_side": side, "kalshi_american": price, "board_event_id": "evt-ottana",
             "series": "KXNHLPTS", **identity}
            for side, price in (("over", -170), ("under", 150))
        ]
        out = []
        for row in quote_rows_from_kalshi_matches(matches, sport=sport):
            normalized = _normalize(row, sport="nhl", date_str="2026-11-01", captured_at=stamp)
            normalized[QUOTE_SOURCE_FIELD] = QUOTE_SOURCE_VENUE_DIRECT
            out.append(normalized)
        return out

    now = datetime(2026, 11, 1, 22, 5, tzinfo=timezone.utc)
    merged = [g for g in build_book_grid(pinnacle + kalshi("nhl"), now=now) if g["kind"] == "prop"]
    split = [g for g in build_book_grid(pinnacle + kalshi(None), now=now) if g["kind"] == "prop"]
    assert len(split) == 2, "the control must reproduce the defect or this test proves nothing"
    assert len(merged) == 1
    assert sorted(merged[0]["books"]) == ["kalshi", "pinnacle"]


# ---------------------------------------------------------------------------
# 4. The capture writes them: props, and now NHL game lines
# ---------------------------------------------------------------------------


def _capture(monkeypatch, matches, board_rows, *, date="2026-11-01"):
    """Drive `_capture_kalshi_quotes` with the writer spied, so the assertion is
    on WHAT REACHED THE WRITER."""
    from pipeline import kalshi_odds_refresh as k
    import syndicate.features.shared.odds_book_quotes as obq

    seen: list[dict] = []

    def fake_append(*, sport, date_str, rows, captured_at, publish=True, extra=None):
        seen.append({"sport": sport, "date_str": date_str, "rows": list(rows)})
        return {"appended": len(list(rows))}

    monkeypatch.setattr(obq, "append_book_quotes", fake_append)
    k._capture_kalshi_quotes({"matches": matches}, board_rows, selected_date=date)
    return seen


def _game_match(series="KXNHLGAME", event_id="evt-ottana", **over):
    match = {"ticker": f"{series}-26NOV01OTTANA-ANA", "series": series, "market": "h2h",
             "player_name": None, "line": None, "board_side": "home", "kalshi_side": "yes",
             "kalshi_american": 105, "board_event_id": event_id, "game_line": True}
    match.update(over)
    return match


def test_an_nhl_prop_match_reaches_the_writer_under_the_shards_code(monkeypatch):
    prop = {"series": "KXNHLPTS", "market": "player_points", "player_name": "Tim Stutzle",
            "line": 0.5, "board_side": "over", "kalshi_american": -170, "board_event_id": "evt-ottana"}
    seen = _capture(monkeypatch, [prop], [dict(_OTT_AT_ANA)])
    assert [(s["sport"], s["date_str"]) for s in seen] == [("nhl", "2026-11-01")]
    row = seen[0]["rows"][0]
    assert (row["bookmaker"], row["market"], row["kind"]) == ("kalshi", "POINTS", "prop")


def test_an_nhl_game_line_is_now_captured(monkeypatch):
    assert sport_allows_game_line_capture("nhl")
    seen = _capture(monkeypatch, [_game_match()], [dict(_OTT_AT_ANA)])
    assert len(seen) == 1 and seen[0]["sport"] == "nhl"
    row = seen[0]["rows"][0]
    assert (row["kind"], row["market"], row["selection"], row["bookmaker"]) == ("game", "h2h", "home", "kalshi")
    assert row["home_team"] == "Anaheim Ducks"


def test_OFF_IS_NOT_ON_an_mlb_game_line_is_still_dropped(monkeypatch):
    """The collision is real for MLB (OddsAPI writes its exchange game rows)."""
    mlb = {"event_id": "evt-mlb", "sport": "mlb"}
    assert _capture(monkeypatch, [_game_match(series="KXMLBGAME", event_id="evt-mlb")], [mlb]) == []


def test_a_period_market_is_SKIPPED_not_filed_as_a_full_game(monkeypatch, capsys):
    """A match carries no segment and `_normalize` defaults it to "full", so a
    first-half total would be logged as a full-game total at the half's line."""
    soccer = {"event_id": "evt-soc", "sport": "soccer"}
    half = _game_match(series="KXEPL1HTOTAL", event_id="evt-soc", market="totals",
                       line=1.5, board_side="over")
    full = _game_match(series="KXEPLTOTAL", event_id="evt-soc", market="totals",
                       line=2.5, board_side="over")
    assert cat.segment_for_series("KXEPL1HTOTAL") != "full"
    seen = _capture(monkeypatch, [half, full], [soccer])
    assert [r["line"] for s in seen for r in s["rows"]] == [2.5]
    assert "segment_skipped=1" in capsys.readouterr().out
