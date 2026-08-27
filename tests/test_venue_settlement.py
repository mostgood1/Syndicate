"""Settling from the venue, and every way that could quietly be wrong.

The point of this module is to DELETE an estimator: `paper_settlement` grades
against a status we resolve, and its own record shows 80 of 171 orders on one
date refusing with `unmapped_market`. So the tests that matter are not about
arithmetic -- they are about the three ways an authoritative source can be
turned back into a guess:

1. Grading from OUR `side`/`line` instead of the venue's statement of what we
   actually held. That reintroduces the exact join this replaces.
2. Reading a cumulative field as an event. `UserPosition.realized` is a running
   total; taking `afterPosition.realized` alone reports a position's whole
   history as one settlement.
3. Splitting a MARKET's P&L across several of our orders on it. The outcome is
   shared, the money is not.

Plus the contract this shares with the ledger: an order carrying an outcome is
never re-graded, because this writes into a money record.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import venue_settlement as vs


# ---------------------------------------------------------------------------
# Kalshi grading
# ---------------------------------------------------------------------------


def _k(**over):
    row = {
        "ticker": "KXNFLGAME-26AUG27-NE",
        "market_result": "yes",
        "yes_count_fp": "10.00",
        "no_count_fp": "0.00",
        "yes_total_cost_dollars": "5.4000",
        "no_total_cost_dollars": "0.0000",
        "revenue": 1000,
        "fee_cost": "0.3400",
        "settled_time": "2026-08-27T03:10:00Z",
    }
    row.update(over)
    return row


def test_a_held_yes_on_a_yes_market_is_a_win_with_the_venues_own_pnl():
    """P&L is revenue/100 - cost - fees, all three from the venue. Ten winning
    contracts pay $10.00 against $5.40 cost and $0.34 fees."""
    v = vs.grade_kalshi_settlement(_k())
    assert v["graded"] is True
    assert v["outcome"] == "won"
    assert v["pnl_dollars"] == pytest.approx(4.26)
    assert v["held_side"] == "yes"


def test_a_held_yes_on_a_no_market_is_a_loss():
    v = vs.grade_kalshi_settlement(_k(market_result="no", revenue=0))
    assert v["outcome"] == "lost"
    # Lost the cost basis and still paid the fee.
    assert v["pnl_dollars"] == pytest.approx(-5.74)


def test_the_outcome_comes_from_what_we_HELD_not_from_our_own_side_field():
    """The whole reason this module exists. A row where we held NO and the
    market resolved NO is a WIN, and nothing about our order's `side`/`line`
    is consulted to reach that."""
    v = vs.grade_kalshi_settlement(
        _k(market_result="no", yes_count_fp="0", no_count_fp="12", revenue=1200,
           yes_total_cost_dollars="0", no_total_cost_dollars="7.20")
    )
    assert v["outcome"] == "won"
    assert v["held_side"] == "no"


def test_a_cost_basis_sent_as_a_string_is_not_dropped():
    """Both venues send money as decimal strings in places. A float-only parse
    would silently treat cost as zero and report the gross payout as profit --
    a settled bet that looks twice as good as it was."""
    v = vs.grade_kalshi_settlement(_k(yes_total_cost_dollars="5.4000"))
    assert v["pnl_dollars"] == pytest.approx(4.26)
    assert vs._num("5.4000") == 5.4


def test_a_scalar_market_is_refused_by_name_rather_than_guessed():
    """`scalar` settles at a VALUE, not a side. Nothing here trades one, and
    inventing a side would be a coin flip recorded as a fact."""
    v = vs.grade_kalshi_settlement(_k(market_result="scalar"))
    assert v["graded"] is False
    assert "scalar" in v["reason"]


def test_holding_both_sides_refuses_rather_than_picking_one():
    v = vs.grade_kalshi_settlement(_k(yes_count_fp="5", no_count_fp="5"))
    assert v["graded"] is False
    assert v["reason"] == "both_sides_held"


def test_a_settlement_on_a_market_we_held_nothing_in_is_refused():
    v = vs.grade_kalshi_settlement(_k(yes_count_fp="0", no_count_fp="0"))
    assert v["graded"] is False
    assert v["reason"] == "no_position_held"


# ---------------------------------------------------------------------------
# Polymarket grading
# ---------------------------------------------------------------------------


def _p(before=3.0, after=12.6, side="POSITION_RESOLUTION_SIDE_LONG"):
    return {
        "marketSlug": "asc-nfl-ne-cle-2026-08-27",
        "side": side,
        "updateTime": "2026-08-27T03:10:00Z",
        "beforePosition": {"realized": {"value": str(before), "currency": "USD"}},
        "afterPosition": {"realized": {"value": str(after), "currency": "USD"}},
    }


def test_the_realized_DELTA_is_the_settlement_not_the_running_total():
    """`realized` is cumulative. Reading `afterPosition.realized` alone would
    report a position's entire trading history as this one settlement -- here
    $12.60 instead of the $9.60 this event actually booked."""
    v = vs.grade_polymarket_resolution(_p(before=3.0, after=12.6))
    assert v["graded"] is True
    assert v["pnl_dollars"] == pytest.approx(9.6)
    assert v["outcome"] == "won"


def test_a_negative_realized_delta_is_a_loss():
    v = vs.grade_polymarket_resolution(_p(before=3.0, after=-6.6))
    assert v["outcome"] == "lost"
    assert v["pnl_dollars"] == pytest.approx(-9.6)


def test_the_venues_own_word_for_a_void_is_a_push():
    v = vs.grade_polymarket_resolution(_p(before=3.0, after=3.0, side="POSITION_RESOLUTION_SIDE_NEUTRAL"))
    assert v["outcome"] == "push"


def test_a_resolution_with_no_realized_amount_is_refused():
    row = _p()
    row["afterPosition"] = {}
    v = vs.grade_polymarket_resolution(row)
    assert v["graded"] is False
    assert v["reason"] == "no_realized_amount"


# ---------------------------------------------------------------------------
# The join and the write
# ---------------------------------------------------------------------------


def _order(**over):
    order = {
        "idempotency_key": "k1",
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": "KXNFLGAME-26AUG27-NE",
        "status": "filled",
        "fill_stake_dollars": 5.40,
        "selected_date": "2026-08-26",
    }
    order.update(over)
    return order


@pytest.fixture
def ledger(monkeypatch):
    """An in-memory ledger, so no test touches disk or a venue."""
    state = {"orders": []}
    persisted = {"count": 0}

    import syndicate.features.shared.execution_ledger as led

    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: persisted.__setitem__("count", persisted["count"] + 1))
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([], None))
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([], None))
    state["_persisted"] = persisted
    return state


def _kalshi_rows(monkeypatch, rows):
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: (rows, None))


def test_off_is_not_on_a_matching_settlement_grades_and_a_missing_one_does_not(ledger, monkeypatch):
    """Reachability before correctness. With no settlement the order is
    untouched; with one it gains an outcome. If both pass, the join is inert."""
    ledger["orders"] = [_order()]

    before = vs.settle_from_venue()
    assert before["settled"] == 0
    assert before["awaiting"] == 1
    assert "outcome" not in ledger["orders"][0]

    _kalshi_rows(monkeypatch, [_k()])
    after = vs.settle_from_venue()
    assert after["settled"] == 1
    assert ledger["orders"][0]["outcome"] == "won"
    assert ledger["orders"][0]["pnl_dollars"] == pytest.approx(4.26)


def test_a_venue_settled_row_is_marked_as_authoritative(ledger, monkeypatch):
    """`settled_by` is what keeps an authoritative outcome distinguishable from
    an inferred one. An evaluation pass that cannot tell them apart is one that
    will eventually average them."""
    ledger["orders"] = [_order()]
    _kalshi_rows(monkeypatch, [_k()])
    vs.settle_from_venue()
    assert ledger["orders"][0]["settled_by"] == "venue"
    assert ledger["orders"][0]["settled_at_venue"] == "2026-08-27T03:10:00Z"


def test_an_already_settled_order_is_never_regraded(ledger, monkeypatch):
    """The contract `settle_orders` keeps, and for the same reason: re-running
    must not be able to change a bet that is already settled."""
    ledger["orders"] = [_order(outcome="lost", pnl_dollars=-5.40)]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["settled"] == 0
    assert result["already"] == 1
    assert ledger["orders"][0]["outcome"] == "lost"


def test_two_orders_on_ONE_SIDE_share_the_outcome_and_each_gets_its_own_pnl(ledger, monkeypatch):
    """The market resolved one way for everyone on that side, so the outcome
    applies to both. The venue's P&L is the MARKET's total and still does not
    divide -- but each order's own fill does, exactly: a binary contract bought
    at $p settles at $1. Leaving these with no P&L is what put `WON —` on the
    board beside yesterday's fully-resolved lines."""
    ledger["orders"] = [
        _order(idempotency_key="a", fill_stake_dollars=4.0, fill_price=0.40),
        _order(idempotency_key="b", fill_stake_dollars=2.0, fill_price=0.50),
    ]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["settled"] == 2
    assert result["pnl_derived"] == 2
    assert all(o["outcome"] == "won" for o in ledger["orders"])
    # $4 at 40c returns (1-.4)/.4 = 1.5x -> +6.00; $2 at 50c returns 1.0x -> +2.00
    assert ledger["orders"][0]["pnl_dollars"] == pytest.approx(6.0)
    assert ledger["orders"][1]["pnl_dollars"] == pytest.approx(2.0)


def test_OPPOSITE_sides_on_one_market_are_refused_not_both_marked_won(ledger, monkeypatch):
    """MEASURED IN PRODUCTION 2026-08-27. `aec-mlb-cle-laa-2026-08-26` carried a
    `side=home` and a `side=away` order, one verdict was applied to both, and
    the board showed **Los Angeles Angels WON and Cleveland Guardians WON on
    the same game**. At most one of those can be true.

    Kalshi refuses this as `both_sides_held` from its own counts; Polymarket
    cannot, because a PositionResolution carries ONE aggregate realized delta
    that describes neither side. An ungraded row is a visible gap; a
    confidently wrong outcome on a money record is not."""
    ledger["orders"] = [
        _order(idempotency_key="a", side="home"),
        _order(idempotency_key="b", side="away"),
    ]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["settled"] == 0
    assert result["refused"]["ambiguous_multi_side"] == 1
    assert all("outcome" not in o for o in ledger["orders"])


def test_a_derived_loss_is_the_stake_and_a_derived_push_is_only_the_fee(ledger, monkeypatch):
    ledger["orders"] = [
        _order(idempotency_key="a", fill_stake_dollars=5.0, fill_price=0.40, fees_dollars=0.10),
        _order(idempotency_key="b", fill_stake_dollars=3.0, fill_price=0.40),
    ]
    _kalshi_rows(monkeypatch, [_k(market_result="no", revenue=0)])
    vs.settle_from_venue()
    assert ledger["orders"][0]["pnl_dollars"] == pytest.approx(-5.10)
    assert ledger["orders"][1]["pnl_dollars"] == pytest.approx(-3.0)


def test_a_settlement_matching_no_order_is_counted_not_dropped(ledger, monkeypatch):
    """"Nothing settled" and "we cannot see what settled" are opposite facts."""
    ledger["orders"] = [_order(venue_ticker="SOMETHING-ELSE")]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["unjoinable"] == 1
    assert result["awaiting"] == 1
    assert result["settled"] == 0


def test_a_paper_order_is_never_touched(ledger, monkeypatch):
    """This grades the LIVE book. A paper row settled from the live venue would
    put a real outcome under a banner promising no money moved."""
    ledger["orders"] = [_order(mode="paper")]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["settled"] == 0
    assert "outcome" not in ledger["orders"][0]


def test_a_rejected_order_has_no_position_to_settle(ledger, monkeypatch):
    ledger["orders"] = [_order(status="rejected", error="http_404 market_not_found")]
    _kalshi_rows(monkeypatch, [_k()])
    assert vs.settle_from_venue()["settled"] == 0


def test_the_join_survives_a_case_difference_in_the_ticker(ledger, monkeypatch):
    ledger["orders"] = [_order(venue_ticker="kxnflgame-26aug27-ne")]
    _kalshi_rows(monkeypatch, [_k()])
    assert vs.settle_from_venue()["settled"] == 1


def test_a_venue_error_is_reported_and_does_not_stop_the_other_venue(ledger, monkeypatch):
    """Settlement runs inside the execution tick. One venue being down must not
    cost the other's settlements, and must never stop orders being placed."""
    ledger["orders"] = [_order(venue="polymarket", venue_ticker="asc-nfl-ne-cle-2026-08-27")]
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([], "http_401: bad key"))
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([_p()], None))
    result = vs.settle_from_venue()
    assert result["errors"]["kalshi"].startswith("http_401")
    assert result["settled"] == 1
    assert ledger["orders"][0]["outcome"] == "won"


def test_nothing_is_persisted_when_nothing_graded(ledger, monkeypatch):
    """A write to a money record for no reason is a write that can fail for no
    reason."""
    ledger["orders"] = [_order()]
    vs.settle_from_venue()
    assert ledger["_persisted"]["count"] == 0
    _kalshi_rows(monkeypatch, [_k()])
    vs.settle_from_venue()
    assert ledger["_persisted"]["count"] == 1


def test_dry_run_grades_in_memory_without_persisting(ledger, monkeypatch):
    ledger["orders"] = [_order()]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue(dry_run=True)
    assert result["settled"] == 1
    assert ledger["_persisted"]["count"] == 0


# ---------------------------------------------------------------------------
# The ROI must stop blending an authoritative outcome with an inferred one.
# ---------------------------------------------------------------------------


def _settled(**over):
    row = {"venue": "kalshi", "mode": "live", "status": "filled",
           "outcome": "won", "fill_stake_dollars": 10.0, "pnl_dollars": 9.0}
    row.update(over)
    return row


def test_settlement_summary_splits_venue_from_inferred():
    """Measured 2026-08-26, the first evening both sources existed: venue
    -11.88% on 3 bets against inferred +51.07% on 12, and the page showed only
    the +32.60% blend. n=3 proves nothing about which is right -- which is
    exactly why they must be reported apart rather than averaged."""
    from syndicate.features.shared.paper_settlement import settlement_summary

    rows = [
        _settled(settled_by="venue", outcome="lost", fill_stake_dollars=4.0, pnl_dollars=-4.0),
        _settled(settled_by="venue", outcome="won", fill_stake_dollars=8.0, pnl_dollars=4.0),
        _settled(outcome="won", fill_stake_dollars=10.0, pnl_dollars=9.0),
    ]
    summary = settlement_summary(None, orders=rows)
    by = {b["key"]: b for b in summary["by_settled_by"]}

    assert by["venue"]["settled"] == 2
    assert by["venue"]["pnl_dollars"] == pytest.approx(0.0)
    assert by["inferred"]["settled"] == 1
    assert by["inferred"]["pnl_dollars"] == pytest.approx(9.0)
    # The two ROIs differ, and neither equals the blend -- the whole point.
    assert by["venue"]["roi_pct"] != by["inferred"]["roi_pct"]
    assert summary["total"]["roi_pct"] not in (by["venue"]["roi_pct"], by["inferred"]["roi_pct"])


def test_an_absent_settled_by_counts_as_inferred_not_unknown():
    """`paper_settlement` stamps nothing when it grades, so absent means OUR
    inference. Bucketing it as `unknown` would leave the blend un-attributable
    in a different way."""
    from syndicate.features.shared.paper_settlement import settlement_summary

    summary = settlement_summary(None, orders=[_settled()])
    assert [b["key"] for b in summary["by_settled_by"]] == ["inferred"]


def test_the_whole_book_total_is_unchanged_by_the_split():
    """`total` still answers "how has this done" over the whole book. Removing
    that would be a different lie; what changes is that it is no longer the
    only number available."""
    from syndicate.features.shared.paper_settlement import settlement_summary

    rows = [_settled(settled_by="venue", pnl_dollars=1.0, fill_stake_dollars=10.0),
            _settled(pnl_dollars=3.0, fill_stake_dollars=10.0)]
    summary = settlement_summary(None, orders=rows)
    assert summary["total"]["settled"] == 2
    assert summary["total"]["pnl_dollars"] == pytest.approx(4.0)
    assert summary["total"]["roi_pct"] == pytest.approx(20.0)
