"""The close's own spread, and CLV against the spread-free (fair) close.

Lane `clv-fair-close`. A quoted close is not the market's probability: a venue
quote is an ASK and a sportsbook price carries its vig. MEASURED 2026-11-27 by
replaying this code over the fleet's quote log for the 30-day decided live
orders: 419 of 571 same-book closes de-vigged, overround +1.49 pp, CLV +0.56
against the quoted close and -0.27 against the fair one (game-clustered).

What these pin:
  * the close carries `close_overround_pp` / `close_fair_prob` from the SAME
    book's last PREGAME quote of every other selection of the market;
  * which rows are "the other side" -- same line for a total or prop, the other
    team at the NEGATED line for a spread, every selection for a moneyline;
  * an incomplete or implausible set gets a named reason, never a number;
  * the quoted close (`close_price`, `close_book_scope`, `clv_pct`) is exactly
    what it was without the other side -- `min_ev_tuner` reads those three;
  * the mark carries `clv_fair_pct` / `clv_fair_net_pct`, always present.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import clv_join
from syndicate.features.shared.clv_join import compute_clv_for_date
from syndicate.features.shared.order_clv import REASON_RESOLVED, clv_for_orders

_DATE = "2026-09-20"
_OPEN_AT = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
_KICKOFF = "2026-09-20T17:00:00Z"
_EVENT = "2143ade9684fd876b68a4e8cbf451f05"
_NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
_CLOSE_AT = "2026-09-20T16:30:00+00:00"

# The quoted-close fields whose values this lane must not change.
_QUOTED = ("close_price", "close_book_scope", "clv_pct", "close_captured_at", "matched_bookmaker",
           "close_source", "close_bookmaker")


def _opening(**over):
    row = {
        "sport": "nfl",
        "event_id": _EVENT,
        "home_team": "Baltimore Ravens",
        "away_team": "Cleveland Browns",
        "market": "spreads",
        "side": "home",
        "line": -6.5,
        "segment": "full",
        "player_name": None,
        "commence_time": _KICKOFF,
        "quote": {"price": -105, "bookmaker": "fanduel"},
    }
    quote = over.pop("quote", None)
    row.update(over)
    if quote is not None:
        row["quote"] = quote
    return row


def _quote(captured_at, price, **over):
    row = {
        "captured_at": captured_at,
        "snapshot_ts": captured_at,
        "sport": "nfl",
        "date": _DATE,
        "kind": "game",
        "event_id": _EVENT,
        "commence_time": _KICKOFF,
        "bookmaker": "fanduel",
        "market": "spreads",
        "segment": "full",
        "selection": "home",
        "player_name": None,
        "line": -6.5,
        "price": price,
    }
    row.update(over)
    return row


def _report(tmp_path, quotes, *, sport="nfl", openings=None, calls=None):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(list(openings or [_opening()]), date=_DATE, now=_OPEN_AT, root=tmp_path)

    def load(sport_name, shard, event_ids):
        if calls is not None:
            calls.append((sport_name, shard))
        if shard != _DATE:
            return None
        return [row for row in quotes if row.get("event_id") in event_ids]

    return compute_clv_for_date(
        _DATE, sport, root=tmp_path, history_payload={"markets": {}}, quote_rows=load, now=_NOW,
    )


def _implied(price):
    from syndicate.features.prediction_ledger import _implied_from_price

    return _implied_from_price(price)


# --------------------------------------------------------------------------
# The resolver: which rows are the other side, and what the close carries
# --------------------------------------------------------------------------


def test_a_spreads_other_side_is_the_other_team_at_the_negated_line(tmp_path):
    report = _report(tmp_path, [
        _quote("2026-09-20T13:00:00+00:00", -110),
        _quote(_CLOSE_AT, -120),                                          # our close
        _quote("2026-09-20T16:20:00+00:00", +100, selection="away", line=6.5),  # its complement
        _quote("2026-09-20T16:25:00+00:00", -150, selection="away", line=-6.5),  # a different bet
    ])
    (row,) = report["rows"]
    total = _implied(-120) + _implied(+100)
    assert row["close_overround_pp"] == pytest.approx(round((total - 1) * 100, 4))
    assert row["close_fair_prob"] == pytest.approx(round(_implied(-120) / total, 6))
    assert row["close_fair_reason"] is None
    # The complement last moved 40 minutes before kickoff.
    assert row["close_other_age_seconds"] == 2400.0


def test_the_same_line_on_the_other_team_is_not_the_complement(tmp_path):
    report = _report(tmp_path, [
        _quote(_CLOSE_AT, -120),
        _quote("2026-09-20T16:25:00+00:00", -150, selection="away", line=-6.5),
    ])
    (row,) = report["rows"]
    assert row["close_overround_pp"] is None and row["close_fair_prob"] is None
    assert row["close_fair_reason"] == "close_other_side_absent"


def test_a_prop_pairs_with_the_other_selection_at_the_same_line_and_player(tmp_path):
    opening = _opening(market="player_reception_yds", side="over", line=52.5, player_name="Luther Burden III",
                       quote={"price": -110, "bookmaker": "draftkings"})
    common = dict(kind="prop", market="player_reception_yds", player_name="luther burden iii",
                  bookmaker="draftkings")
    report = _report(tmp_path, [
        _quote(_CLOSE_AT, -130, selection="over", line=52.5, **common),
        _quote("2026-09-20T16:31:00+00:00", +105, selection="under", line=52.5, **common),
        _quote("2026-09-20T16:31:00+00:00", -200, selection="under", line=49.5, **common),  # other line
        _quote("2026-09-20T16:31:00+00:00", -999, selection="under", line=52.5,           # other player
               **{**common, "player_name": "someone else"}),
    ], openings=[opening])
    (row,) = report["rows"]
    total = _implied(-130) + _implied(+105)
    assert row["close_fair_prob"] == pytest.approx(round(_implied(-130) / total, 6))


def test_only_the_same_books_pregame_quotes_count_and_the_latest_wins(tmp_path):
    report = _report(tmp_path, [
        _quote(_CLOSE_AT, -120),
        _quote("2026-09-20T14:00:00+00:00", -105, selection="away", line=6.5),
        _quote("2026-09-20T16:00:00+00:00", +102, selection="away", line=6.5),    # latest pregame
        _quote("2026-09-20T17:30:00+00:00", +400, selection="away", line=6.5),    # in play
        _quote("2026-09-20T16:50:00+00:00", -300, selection="away", line=6.5, bookmaker="draftkings"),
    ])
    (row,) = report["rows"]
    total = _implied(-120) + _implied(+102)
    assert row["close_fair_prob"] == pytest.approx(round(_implied(-120) / total, 6))
    assert row["close_other_age_seconds"] == 3600.0


def test_a_three_way_moneyline_needs_the_draw(tmp_path):
    soccer = dict(sport="soccer", market="h2h", line=None, bookmaker="kalshi")
    opening = _opening(sport="soccer", market="h2h", side="home", line=None,
                       quote={"price": 0.42, "bookmaker": "kalshi"})
    quotes = [
        _quote(_CLOSE_AT, 0.45, selection="home", **soccer),
        _quote(_CLOSE_AT, 0.31, selection="away", **soccer),
        _quote(_CLOSE_AT, 0.28, selection="draw", **soccer),
    ]
    (row,) = _report(tmp_path / "with", quotes, sport="soccer", openings=[opening])["rows"]
    assert row["close_overround_pp"] == pytest.approx(4.0)
    assert row["close_fair_prob"] == pytest.approx(round(0.45 / 1.04, 6))

    (row,) = _report(tmp_path / "without", quotes[:2], sport="soccer", openings=[opening])["rows"]
    assert row["close_fair_prob"] is None
    assert row["close_fair_reason"] == "close_draw_absent"


def test_a_two_way_moneyline_is_whole_where_there_is_no_draw(tmp_path):
    opening = _opening(market="h2h", side="away", line=None, quote={"price": 0.40, "bookmaker": "polymarket"})
    common = dict(market="h2h", line=None, bookmaker="polymarket")
    (row,) = _report(tmp_path, [
        _quote(_CLOSE_AT, 0.41, selection="away", **common),
        _quote(_CLOSE_AT, 0.61, selection="home", **common),
    ], openings=[opening])["rows"]
    assert row["close_overround_pp"] == pytest.approx(2.0)
    assert row["close_fair_prob"] == pytest.approx(round(0.41 / 1.02, 6))


def test_a_one_sided_close_is_named_never_a_number(tmp_path):
    (row,) = _report(tmp_path, [_quote(_CLOSE_AT, -120)])["rows"]
    assert row["close_price"] == -120.0
    assert row["close_overround_pp"] is None and row["close_fair_prob"] is None
    assert row["close_fair_reason"] == "close_other_side_absent"


def test_a_spread_with_no_home_away_selection_is_not_devigged(tmp_path):
    opening = _opening(side="baltimore ravens")
    (row,) = _report(tmp_path, [
        _quote(_CLOSE_AT, -120, selection="Baltimore Ravens"),
        _quote(_CLOSE_AT, +100, selection="Cleveland Browns", line=6.5),
    ], openings=[opening])["rows"]
    assert row["close_fair_prob"] is None
    assert row["close_fair_reason"] == "close_selection_set_unrecognized"


def test_summed_quotes_outside_the_plausible_range_claim_no_fair_price(tmp_path):
    # 0.30 + 0.99: a pulled or placeholder side, not one market at one instant.
    opening = _opening(market="totals", side="over", line=8.5, quote={"price": 0.28, "bookmaker": "kalshi"})
    common = dict(market="totals", line=8.5, bookmaker="kalshi")
    (row,) = _report(tmp_path, [
        _quote(_CLOSE_AT, 0.30, selection="over", **common),
        _quote(_CLOSE_AT, 0.99, selection="under", **common),
    ], openings=[opening])["rows"]
    assert row["close_price"] == 0.30
    assert row["close_overround_pp"] is None and row["close_fair_prob"] is None
    assert row["close_fair_reason"] == "close_overround_implausible"


def test_a_lay_market_is_never_summed_but_a_player_market_is():
    # "lay" as a substring is inside "player"; it must match only as a word.
    lay = clv_join._fair_close("home", -110, {"away": -110}, market="h2h_lay", sport="nfl")
    assert lay == (None, None, "close_selection_set_unrecognized")
    for market in ("player_points", "player_reception_yds", "passing tds"):
        assert clv_join._fair_close("over", -110, {"under": -110}, market=market, sport="nba")[2] is None, market


def test_the_quoted_close_is_unchanged_by_the_other_side(tmp_path):
    """`min_ev_tuner._gross_clv` reads close_price / close_book_scope / clv_pct: identical either way."""
    ours = [_quote("2026-09-20T13:00:00+00:00", -110), _quote(_CLOSE_AT, -120)]
    other = [_quote("2026-09-20T16:20:00+00:00", +100, selection="away", line=6.5)]
    (alone,) = _report(tmp_path / "alone", ours)["rows"]
    (paired,) = _report(tmp_path / "paired", ours + other)["rows"]
    assert {f: alone.get(f) for f in _QUOTED} == {f: paired.get(f) for f in _QUOTED}
    assert paired["close_fair_prob"] is not None and alone["close_fair_prob"] is None
    # Nothing else moved either: the rows differ in the fair fields alone.
    fair = set(clv_join.QUOTE_FAIR_FIELDS)
    assert {k: v for k, v in alone.items() if k not in fair} == {k: v for k, v in paired.items() if k not in fair}


def test_the_other_side_costs_no_extra_shard_read(tmp_path):
    calls = []
    _report(tmp_path, [_quote(_CLOSE_AT, -120), _quote(_CLOSE_AT, +100, selection="away", line=6.5)],
            calls=calls)
    assert calls == [("nfl", _DATE)]


# --------------------------------------------------------------------------
# The order: fair CLV on the grade, and on the stamped mark
# --------------------------------------------------------------------------

_K_EVENT = "5d13b613a334039f0694d8c95af28728"
_K_DATE = "2026-10-03"
_K_KICKOFF = "2026-10-03T17:01:00Z"
_K_NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _k_order(**over):
    order = {
        "idempotency_key": "eaed7679b7f266b466352e28",
        "opening_key": f"event_id={_K_EVENT}|market=totals|player=|segment=first5|side=over|line=3.5|bookmaker=kalshi",
        "sport": "mlb",
        "venue": "kalshi",
        "event_id": _K_EVENT,
        "market": "totals",
        "segment": "first5",
        "side": "over",
        "line": 3.5,
        "player_name": None,
        "book": "kalshi",
        "commence_time": _K_KICKOFF,
        "submitted_at": "2026-10-02T21:11:31.740043Z",
        "requested_price": 0.52,
        "fill_price": 0.52,
        "fill_stake_dollars": 1.87,
        "fees_dollars": 0.07,
        "selected_date": _K_DATE,
        "status": "filled",
        "outcome": "lost",
    }
    order.update(over)
    return order


def _k_quote(captured_at, price, **over):
    row = {
        "captured_at": captured_at,
        "snapshot_ts": captured_at,
        "sport": "mlb",
        "kind": "game",
        "event_id": _K_EVENT,
        "commence_time": _K_KICKOFF,
        "bookmaker": "kalshi",
        "market": "totals",
        "segment": "first5",
        "selection": "over",
        "player_name": None,
        "line": 3.5,
        "price": price,
        "source": "venue_direct",
    }
    row.update(over)
    return row


def _grade(orders, *quotes):
    def load(sport, shard, event_ids):
        return [row for row in quotes if row["event_id"] in event_ids] if shard == _K_DATE else None

    return clv_for_orders(orders, date=_K_DATE, clv_rows=[], unresolved_rows=[], quote_rows=load, now=_K_NOW)


def test_an_order_is_graded_against_the_fair_close_beside_the_quoted_one():
    from syndicate.features.shared.order_clv import fee_net_clv_pct

    order = _k_order()
    report = _grade([order], _k_quote("2026-10-03T15:30:00Z", 0.55),
                    _k_quote("2026-10-03T15:40:00Z", 0.50, selection="under"))
    (row,) = report["rows"]
    assert row["reason"] == REASON_RESOLVED
    assert row["clv_pct"] == pytest.approx(3.0)
    assert row["close_overround_pp"] == pytest.approx(5.0)
    fair = round(0.55 / 1.05, 6)
    assert row["close_fair_prob"] == pytest.approx(fair)
    assert row["clv_fair_pct"] == pytest.approx(clv_join.clv_pct_from_prices(0.52, fair))
    net = fee_net_clv_pct(order, row["clv_fair_pct"], entry=0.52)
    assert net is not None and row["clv_fair_net_pct"] == pytest.approx(net)
    assert row["close_fair_reason"] is None


def test_an_order_without_the_other_side_carries_the_reason_and_no_fair_clv():
    (row,) = _grade([_k_order()], _k_quote("2026-10-03T15:30:00Z", 0.55))["rows"]
    assert row["reason"] == REASON_RESOLVED and row["clv_pct"] == pytest.approx(3.0)
    assert row["clv_fair_pct"] is None and row["clv_fair_net_pct"] is None
    assert row["close_fair_reason"] == "close_other_side_absent"


def test_a_close_from_odds_history_says_so():
    """A history row (no quote-log fair fields) is never given a fair CLV -- learnings 2026-10-26."""
    order = _k_order(fill_price=-110, requested_price=-110)
    key = order["opening_key"]
    history_row = {"key": key, "close_price": -125, "close_source": "odds_history_last_pregame",
                   "close_book_scope": "same_book", "close_captured_at": "2026-10-03T16:00:00Z"}
    report = clv_for_orders([order], date=_K_DATE, clv_rows=[history_row], unresolved_rows=[], now=_K_NOW)
    (row,) = report["rows"]
    assert row["reason"] == REASON_RESOLVED
    assert row["clv_fair_pct"] is None
    assert row["close_fair_reason"] == "close_not_from_quote_log"


def test_the_stamped_mark_carries_the_fair_fields_and_always_names_fair_clv():
    from syndicate.features.shared import paper_settlement as settle

    graded = _grade([_k_order()], _k_quote("2026-10-03T15:30:00Z", 0.55),
                    _k_quote("2026-10-03T15:40:00Z", 0.50, selection="under"))
    orders = [_k_order(), _k_order(idempotency_key="other")]
    rows = list(graded["rows"]) + [{"idempotency_key": "other", "reason": "no_close_for_market",
                                    "clv_pct": None}]
    settle.stamp_closing_marks(orders, _K_DATE, closer=lambda _o, _d: {"rows": rows}, now=_K_NOW)
    mark = orders[0]["closing_mark"]
    for field in ("close_overround_pp", "close_fair_prob", "clv_fair_pct", "clv_fair_net_pct"):
        assert mark[field] == pytest.approx(graded["rows"][0][field]), field
    assert mark["close_price"] == 0.55 and mark["close_book_scope"] == "same_book"
    # Present and None on a mark with no reading -- never a key a reader could default to zero.
    other = orders[1]["closing_mark"]
    assert "clv_fair_pct" in other and other["clv_fair_pct"] is None
    assert "clv_fair_net_pct" in other and other["clv_fair_net_pct"] is None
