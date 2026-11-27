"""Todo #861 step 1e (lane surface-consistency-oversight): the board shows the EV it judges, and the venue prices.

- `ev_net_pct` / `fee_basis` on a card are `score_v2`'s, the numbers `_suggested_reasons` reads.
- `venue_prices` are priced by the purchaser's own `venue_scope.scope_rows_to_venue`, never by a second copy of its
  maths, and the venue that IS the best book is left out (its price is the Best price, its net EV the EV column's).
- The row is never written: these are card fields, display only.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from syndicate.features.shared import layer2_board as lb
from syndicate.features.shared.venue_scope import scope_rows_to_venue

TEMPLATE = Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "intelligence.html"


def _row(*, best="fanduel", price=110, ev=4.0, book_prices=None, v2=None, state="pregame"):
    row = {
        "sport": "nfl",
        "market": "Receptions",
        "segment": "full",
        "player_name": "Test Player",
        "side": "over",
        "line": 3.5,
        "event_id": "e1",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2030-01-01T18:00:00Z",
        "game_state": state,
        "is_live": state != "pregame",
        "ev_pct": ev,
        "board_lane": "opportunity",
        "quote": {
            "bookmaker": best,
            "price": price,
            "fair_probability": 0.4952,
            "fair_method": "consensus",
            "books_quoting": 5,
            "book_prices": dict(book_prices if book_prices is not None else {best: price, "kalshi": 105, "polymarket": 102}),
        },
        "score": {"score": 3.0},
    }
    if v2 is not None:
        row["score_v2"] = v2
    return row


def test_net_ev_is_score_v2s_number():
    v2 = {"ev_net_pct": 2.91, "fee_basis": "kalshi_series_from_market", "fee_per_contract": 0.0123, "fee_is_upper_bound": False}
    cols = lb._layer2_fee_and_venue_columns(_row(best="kalshi", price=110, v2=v2))
    assert cols["ev_net_pct"] == 2.91
    assert cols["fee_basis"] == "kalshi_series_from_market"
    assert cols["fee_per_contract"] == 0.0123
    assert "fee_is_upper_bound" not in cols


def test_fee_upper_bound_is_carried():
    v2 = {"ev_net_pct": 1.2, "fee_basis": "novig_assumed_live_rate", "fee_per_contract": 0.01, "fee_is_upper_bound": True}
    assert lb._layer2_fee_and_venue_columns(_row(best="novig", v2=v2))["fee_is_upper_bound"] is True


def test_no_score_v2_means_no_net_fields():
    cols = lb._layer2_fee_and_venue_columns(_row(book_prices={"fanduel": 110}))
    assert cols == {}


def test_venue_prices_equal_the_purchasers_function():
    row = _row(best="fanduel", price=110)
    cols = lb._layer2_fee_and_venue_columns(row)
    venues = {v["venue"]: v for v in cols["venue_prices"]}
    assert set(venues) == {"kalshi", "polymarket"}
    for venue, entry in venues.items():
        scoped, refusals = scope_rows_to_venue([row], venue)
        assert refusals == {}
        s = scoped[0]
        assert entry["price"] == s["quote"]["price"]
        assert entry["ev_pct"] == round(s["ev_pct"], 4)
        assert entry["ev_net_pct"] == round(s["ev_pct_net_of_fee"], 4)
        assert entry["fee_per_contract"] == s["venue_fee_per_contract"]
        assert entry["fee_basis"] == s["venue_fee_basis"]
        assert entry["price_source"] == "aggregator"
        # The fee is real: net is below gross at an exchange.
        assert entry["ev_net_pct"] < entry["ev_pct"]
    assert [v["venue"] for v in cols["venue_prices"]] == ["kalshi", "polymarket"]


def test_the_best_book_venue_is_left_out():
    v2 = {"ev_net_pct": 2.5, "fee_basis": "kalshi_series_from_market", "fee_per_contract": 0.012}
    cols = lb._layer2_fee_and_venue_columns(_row(best="kalshi", price=110, v2=v2))
    assert [v["venue"] for v in cols["venue_prices"]] == ["polymarket"]


def test_venue_not_quoting_is_absent_not_invented():
    cols = lb._layer2_fee_and_venue_columns(_row(book_prices={"fanduel": 110, "draftkings": 105}))
    assert "venue_prices" not in cols


def test_implausible_venue_price_is_refused_by_name():
    # fair 0.4952 at +400 is EV +147%: past the shortlist's plausibility gate, which the purchaser applies.
    cols = lb._layer2_fee_and_venue_columns(_row(book_prices={"fanduel": 110, "kalshi": 400}))
    (entry,) = cols["venue_prices"]
    assert entry == {"venue": "kalshi", "price": 400.0, "refused": "venue_ev_implausible"}


def test_the_row_is_never_written():
    row = _row(v2={"ev_net_pct": 3.9, "fee_basis": "none", "fee_per_contract": 0.0})
    before = copy.deepcopy(row)
    lb._layer2_fee_and_venue_columns(row)
    assert row == before


def test_reachability_the_card_carries_the_fields():
    """off != on: a row with a venue price yields a card with `venue_prices`; without one, none."""
    with_venue = lb.layer2_rows_to_board_cards([_row(v2={"ev_net_pct": 4.0, "fee_basis": "none", "fee_per_contract": 0.0})])
    without = lb.layer2_rows_to_board_cards([_row(book_prices={"fanduel": 110})])
    assert with_venue[0]["ev_net_pct"] == 4.0 and with_venue[0]["fee_basis"] == "none"
    assert {v["venue"] for v in with_venue[0]["venue_prices"]} == {"kalshi", "polymarket"}
    assert "venue_prices" not in without[0] and "ev_net_pct" not in without[0]


def test_the_columns_helper_portfolio_commit_calls_is_unchanged():
    """`portfolio_commit` calls `_layer2_board_columns`; the new fields must not ride into it."""
    row = _row(v2={"ev_net_pct": 2.0, "fee_basis": "kalshi_series", "fee_per_contract": 0.01})
    cols = lb._layer2_board_columns(row, row["quote"], row["score"])
    assert not {"venue_prices", "ev_net_pct", "fee_basis", "fee_per_contract"} & set(cols)


def _script() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_page_reads_the_fields_it_is_given():
    html = _script()
    # The EV column sorts and shows the judged number; the cell explains the fee; the Best price cell lists venues.
    assert re.search(r'key: "ev", label: "EV", type: "number", getValue: \(item\) => evShownValue\(item\)', html)
    assert "const ev = evShownValue(item);" in html
    assert "${renderBlotterEvFee(item)}" in html
    assert "${field}${renderBlotterVenues(item)}" in html
    for field in ("item.ev_net_pct", "item?.fee_basis", "item.fee_per_contract", "item?.venue_prices"):
        assert field in html, field


def test_page_shown_ev_rule():
    html = _script()
    body = html[html.index("function evShownValue(item)"):]
    body = body[: body.index("}") + 1]
    assert "evFeeCharged(item) ? evNetValue(item) : evVsFairValue(item)" in body
