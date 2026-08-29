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


def test_a_zero_delta_is_REFUSED_not_called_a_push(app=None):
    """[user 2026-08-27] "polymarket is still calling everything from today a
    push."

    IT WAS, AND THE ERROR WAS PERMANENT. Measured on the live book: seven
    pushes, every one Polymarket, every one dated that day, every one
    `pnl_dollars=0.0` and `settled_by='venue'`, while the same venue's rows
    from the day before graded won/lost with real money. One carried
    `settled_at=2026-08-27T13:49:55Z` against a `commence_time` of `23:16:00Z`
    -- settled nine and a half hours before first pitch.

    `delta == 0` conflates "resolved and moved no money" with "nothing booked
    yet". Grading the second writes an AUTHORITATIVE outcome over a live bet,
    and `settle_from_venue` skips rows that already carry one -- so the mistake
    can never correct itself. Only the venue SAYING neutral may be a push.
    """
    v = vs.grade_polymarket_resolution(_p(before=3.0, after=3.0))
    assert v["graded"] is False
    assert v["reason"] == "zero_realized_delta"
    assert "outcome" not in v


def test_a_zero_delta_the_venue_CALLS_neutral_is_still_a_push():
    """The refusal above must not swallow the one case that is genuinely a
    push. The discriminator is the venue's own word, not the arithmetic."""
    v = vs.grade_polymarket_resolution(
        _p(before=3.0, after=3.0, side="POSITION_RESOLUTION_SIDE_NEUTRAL")
    )
    assert v["graded"] is True
    assert v["outcome"] == "push"
    assert v["pnl_dollars"] == pytest.approx(0.0)


def test_a_refused_zero_delta_leaves_the_row_open_for_a_later_tick():
    """The point of refusing rather than grading: the position stays ungraded,
    so the next pass can settle it once the venue has actually booked the
    resolution. A row frozen as `push` would never be looked at again."""
    v = vs.grade_polymarket_resolution(_p(before=0.0, after=0.0))
    assert v["graded"] is False
    # No outcome and no money -- nothing for the writer to apply.
    assert v.get("pnl_dollars") is None


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


# ---------------------------------------------------------------------------
# The repair. It writes to a money record, so its LIMITS are what get tested.
# ---------------------------------------------------------------------------


def test_the_repair_ungrades_an_impossible_opposite_side_pair(ledger, monkeypatch):
    """MEASURED 2026-08-27: two rows on aec-mlb-cle-laa-2026-08-26 were both
    graded WON, one side=home and one side=away. Both graders are idempotent,
    so a wrong outcome is permanent unless something removes it."""
    ledger["orders"] = [
        _order(idempotency_key="a", side="home", outcome="won", pnl_dollars=1.0,
               settled_by="venue", graded_at="x"),
        _order(idempotency_key="b", side="away", outcome="won", pnl_dollars=2.0,
               settled_by="venue", graded_at="x"),
    ]
    result = vs.repair_multi_side_grades()
    assert result["cleared"] == 2
    assert result["markets"] == 1
    for o in ledger["orders"]:
        assert "outcome" not in o and "settled_by" not in o and "pnl_dollars" not in o


def test_the_repair_is_self_limiting(ledger):
    """After one pass the rows are ungraded, so a second pass finds nothing.
    A repair that fired every tick would rewrite the ledger forever."""
    ledger["orders"] = [
        _order(idempotency_key="a", side="home", outcome="won", settled_by="venue"),
        _order(idempotency_key="b", side="away", outcome="won", settled_by="venue"),
    ]
    assert vs.repair_multi_side_grades()["cleared"] == 2
    assert vs.repair_multi_side_grades()["cleared"] == 0


def test_the_repair_never_touches_an_INFERRED_grade(ledger):
    """An inferred outcome is another module's record. Even on an opposite-side
    market it is not this repair's to remove."""
    ledger["orders"] = [
        _order(idempotency_key="a", side="home", outcome="won", pnl_dollars=1.0),
        _order(idempotency_key="b", side="away", outcome="lost", pnl_dollars=-2.0),
    ]
    assert vs.repair_multi_side_grades()["cleared"] == 0
    assert ledger["orders"][0]["outcome"] == "won"


def test_the_repair_leaves_a_SAME_side_market_alone(ledger):
    """Two orders on one side share an outcome legitimately -- that is not the
    defect, and clearing them would destroy correct settlements."""
    ledger["orders"] = [
        _order(idempotency_key="a", side="away", outcome="lost", settled_by="venue"),
        _order(idempotency_key="b", side="away", outcome="lost", settled_by="venue"),
    ]
    assert vs.repair_multi_side_grades()["cleared"] == 0


def test_the_repair_never_touches_paper(ledger):
    ledger["orders"] = [
        _order(idempotency_key="a", side="home", mode="paper", outcome="won", settled_by="venue"),
        _order(idempotency_key="b", side="away", mode="paper", outcome="won", settled_by="venue"),
    ]
    assert vs.repair_multi_side_grades()["cleared"] == 0


def test_a_missing_pnl_is_backfilled_without_touching_the_outcome(ledger):
    """Rows graded before `_derived_pnl` existed kept an outcome and no number
    -- `LOST —` on the board. Idempotency means the grading path will never
    revisit them, so the repair adds the figure. Strictly additive: derived
    from the order's OWN fill, and an outcome is only ever read."""
    ledger["orders"] = [
        _order(idempotency_key="a", side="away", outcome="lost", settled_by="venue",
               fill_stake_dollars=3.41),
        _order(idempotency_key="b", side="away", outcome="won", settled_by="venue",
               fill_stake_dollars=4.0, fill_price=0.40),
    ]
    result = vs.repair_multi_side_grades()
    assert result["pnl_backfilled"] == 2
    assert ledger["orders"][0]["outcome"] == "lost"
    assert ledger["orders"][0]["pnl_dollars"] == pytest.approx(-3.41)
    assert ledger["orders"][1]["outcome"] == "won"
    assert ledger["orders"][1]["pnl_dollars"] == pytest.approx(6.0)


def test_the_backfill_never_overwrites_an_existing_pnl(ledger):
    ledger["orders"] = [_order(side="away", outcome="lost", settled_by="venue",
                               pnl_dollars=-99.0, fill_stake_dollars=3.41)]
    vs.repair_multi_side_grades()
    assert ledger["orders"][0]["pnl_dollars"] == -99.0


def test_the_backfill_never_touches_an_inferred_row(ledger):
    ledger["orders"] = [_order(side="away", outcome="lost", fill_stake_dollars=3.41)]
    result = vs.repair_multi_side_grades()
    assert result.get("pnl_backfilled", 0) == 0
    assert ledger["orders"][0].get("pnl_dollars") is None


def test_the_guard_sees_a_sibling_that_is_ALREADY_graded(ledger, monkeypatch):
    """The sequencing that walked around the first fix, measured in production
    2026-08-27: the repair cleared both rows, the `away` row aged past the 24h
    grace and INFERENCE graded it, leaving ONE ungraded order -- so the
    ungraded-only guard slept and the venue graded `home` the same way. Both
    teams won again.

    Worse than a missed case: the repair clears the venue grade and the grader
    re-applies it, so the two fight on every tick forever."""
    ledger["orders"] = [
        _order(idempotency_key="a", side="away", outcome="won"),   # already inferred
        _order(idempotency_key="b", side="home"),                  # lone ungraded
    ]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["settled"] == 0
    assert result["refused"]["ambiguous_multi_side"] == 1
    assert "outcome" not in ledger["orders"][1]


def test_a_lone_order_on_a_single_side_market_still_grades(ledger, monkeypatch):
    """The guard must not refuse the ordinary case it shares a code path with."""
    ledger["orders"] = [_order(idempotency_key="a", side="away")]
    _kalshi_rows(monkeypatch, [_k()])
    assert vs.settle_from_venue()["settled"] == 1


def test_repair_and_grader_cannot_oscillate(ledger, monkeypatch):
    """Repair clears, grader must NOT re-apply -- otherwise the ledger is
    rewritten on every tick indefinitely."""
    ledger["orders"] = [
        _order(idempotency_key="a", side="home", outcome="won", settled_by="venue"),
        _order(idempotency_key="b", side="away", outcome="won"),
    ]
    _kalshi_rows(monkeypatch, [_k()])
    first = vs.settle_from_venue()          # repairs, then must refuse
    assert "outcome" not in ledger["orders"][0]
    second = vs.settle_from_venue()         # nothing left to repair or grade
    assert second["settled"] == 0
    assert "outcome" not in ledger["orders"][0]


# --------------------------------------------------------------------------
# The repair for pushes already written from a zero delta
# --------------------------------------------------------------------------


def _bad_push(**over):
    """A row exactly as the defective grader left it: push, no money, venue's
    word, and NO `held_side` -- because nothing stored it before this change."""
    row = {
        "mode": "live", "venue": "polymarket", "outcome": "push",
        "pnl_dollars": 0.0, "settled_by": "venue", "selected_date": "2026-08-27",
        "settled_at_venue": "2026-08-28T01:40:46Z", "graded_at": "2026-08-28T01:43:53Z",
    }
    row.update(over)
    return row


def _repair(monkeypatch, orders):
    import syndicate.features.shared.execution_ledger as el

    state = {"orders": orders}
    monkeypatch.setattr(el, "_load", lambda: state)
    monkeypatch.setattr(el, "_persist", lambda s: None)
    return vs.repair_zero_delta_pushes(), state


def test_the_repair_clears_a_push_written_from_a_zero_delta(monkeypatch):
    out, state = _repair(monkeypatch, [_bad_push()])
    assert out["cleared"] == 1
    assert out["dates"] == ["2026-08-27"]
    row = state["orders"][0]
    # Un-graded, not re-graded: the repair never invents an outcome.
    for field in ("outcome", "pnl_dollars", "settled_by", "settled_at_venue", "graded_at"):
        assert field not in row


def test_the_repair_TERMINATES_and_does_not_reopen_a_correct_push(monkeypatch):
    """THE CLAUSE THAT MAKES THIS SAFE TO RUN EVERY TICK.

    A genuine push -- one the venue itself called NEUTRAL -- looks identical in
    the stored data: push / 0.00 / venue. Clearing on that signature alone
    would re-open a CORRECT grade, the next tick would re-grade it push, and
    this would clear it again forever. A row carrying `held_side` was written
    by the fixed code and must be left alone.
    """
    good = _bad_push(held_side="POSITION_RESOLUTION_SIDE_NEUTRAL")
    out, state = _repair(monkeypatch, [good])
    assert out["cleared"] == 0
    assert state["orders"][0]["outcome"] == "push"


def test_the_repair_will_not_touch_another_modules_record(monkeypatch):
    """An inferred grade belongs to the inference path. Kalshi never had this
    defect, and a won/lost row is not the signature."""
    rows = [
        _bad_push(settled_by="inferred"),
        _bad_push(venue="kalshi"),
        _bad_push(outcome="lost", pnl_dollars=-2.0),
        _bad_push(mode="paper"),
    ]
    out, _ = _repair(monkeypatch, rows)
    assert out["cleared"] == 0


def test_a_push_carrying_real_money_is_not_the_defect(monkeypatch):
    """The signature is a ZERO P&L. A push with money attached came from
    somewhere else and is not this repair's business."""
    out, _ = _repair(monkeypatch, [_bad_push(pnl_dollars=-0.5)])
    assert out["cleared"] == 0


# --------------------------------------------------------------------------
# The unknown-order probe -- Polymarket's only orphan angle
# --------------------------------------------------------------------------


def _unknown_order(**over):
    """An order the venue never answered: no id, failed, no outcome."""
    row = {
        "mode": "live", "venue": "polymarket", "status": "failed",
        "error": 'PolymarketUSAuthError: http_503: {"code":14}',
        "venue_order_id": None, "venue_ticker": "aec-mlb-kc-tor-2026-08-27",
        "idempotency_key": "unk1", "selected_date": "2026-08-27",
        "requested_stake_dollars": 6.22,
    }
    row.update(over)
    return row


def _resolution(slug="aec-mlb-kc-tor-2026-08-27"):
    return {"marketSlug": slug, "side": "POSITION_RESOLUTION_SIDE_LONG"}


def test_a_resolution_on_a_market_we_only_hold_an_unknown_on_is_evidence():
    """The one angle that exists: the feed is keyed by marketSlug, not order id.
    If that market resolved and NOTHING ELSE of ours could account for it, a
    position of ours was probably there."""
    out = vs.probe_unknown_polymarket_positions([_unknown_order()], [_resolution()])
    assert out["unknown"] == 1
    assert out["evidenced"] == 1
    finding = out["findings"][0]
    assert finding["resolution_rows"] == 1
    assert finding["sole_claim"] is True


def test_another_order_on_the_same_market_makes_it_a_COINCIDENCE():
    """The discriminator between signal and noise. A filled order of ours on
    that market explains the resolution row completely, so it is no longer
    evidence about the unknown one."""
    filled = {
        "mode": "live", "venue": "polymarket", "status": "filled",
        "venue_order_id": "ABC", "venue_ticker": "aec-mlb-kc-tor-2026-08-27",
        "idempotency_key": "other",
    }
    out = vs.probe_unknown_polymarket_positions([_unknown_order(), filled], [_resolution()])
    assert out["unknown"] == 1
    assert out["evidenced"] == 0
    assert out["findings"][0]["sole_claim"] is False


def test_no_resolution_row_is_NOT_evidence_of_absence():
    """The dangerous half. An order that landed and is still OPEN has no
    resolution row, and neither does a market that has not settled. A clean
    probe means "nothing found", never "nothing there" -- so the unknown order
    is still reported, with zero rows against it."""
    out = vs.probe_unknown_polymarket_positions([_unknown_order()], [])
    assert out["unknown"] == 1, "it must still be reported"
    assert out["evidenced"] == 0
    assert out["findings"][0]["resolution_rows"] == 0


def test_an_order_the_venue_REFUSED_is_not_in_question():
    """A 4xx the venue answered is certainly not a position. Only a submit with
    no answer is genuinely unknown."""
    refused = _unknown_order(error="http_404: market_not_found", idempotency_key="refused")
    out = vs.probe_unknown_polymarket_positions([refused], [_resolution()])
    assert out["unknown"] == 0


def test_an_order_we_hold_an_id_for_is_not_unknown():
    """With a venue_order_id the per-order read can answer directly, so it is
    reconciliation's job rather than this probe's."""
    known = _unknown_order(venue_order_id="C4H2MGSSGGNP", idempotency_key="known")
    out = vs.probe_unknown_polymarket_positions([known], [_resolution()])
    assert out["unknown"] == 0


def test_the_probe_writes_nothing():
    """It reports. Grading on circumstantial evidence is exactly what the
    zero-delta push defect did."""
    orders = [_unknown_order()]
    vs.probe_unknown_polymarket_positions(orders, [_resolution()])
    assert "outcome" not in orders[0]
    assert orders[0]["status"] == "failed"


# --------------------------------------------------------------------------
# THE BALANCE ANGLE. Reproduces 2026-08-29 exactly: order 5c53789d... took
# http_503 at 21:06:37 and Polymarket buyingPower read 96.05 before it and
# 96.05 after it. Flat across the submit -- nothing was placed.
#
# The module's docstring used to say flatly that nothing could settle these.
# --------------------------------------------------------------------------


def _reading(at, dollars, status="ok"):
    return {"recorded_at": at, "polymarket": {"status": status, "dollars": dollars}}


_THE_REAL_TRAIL = [
    _reading("2026-08-29T21:05:56Z", 96.04765),   # 40s before the submit
    _reading("2026-08-29T21:12:47Z", 96.04765),
    _reading("2026-08-29T21:18:46Z", 96.04765),
    _reading("2026-08-29T21:25:09Z", 96.04765),
]


def _the_503(**over):
    row = _unknown_order(
        idempotency_key="5c53789d4d21d05fc501b05d",
        venue_ticker="tsc-mls-nyr-phi-2026-08-29-3pt5",
        selected_date="2026-08-29",
        requested_stake_dollars=1.84,
        submitted_at="2026-08-29T21:06:36.292084Z",
        venue_resolved_at="2026-08-29T21:06:37.686282Z",
    )
    row.update(over)
    return row


def _probe(monkeypatch, orders, readings, resolutions=()):
    monkeypatch.setattr(
        "syndicate.features.shared.venue_balances.read_balance_history",
        lambda: list(readings),
    )
    return vs.probe_unknown_polymarket_positions(list(orders), list(resolutions))


def test_a_flat_balance_across_the_submit_says_NOT_PLACED(monkeypatch):
    out = _probe(monkeypatch, [_the_503()], _THE_REAL_TRAIL)
    evidence = out["findings"][0]["balance_evidence"]
    assert evidence["verdict"] == "not_placed"
    assert evidence["reason"] == "balance_unchanged_across_submit"
    assert evidence["delta_dollars"] == 0.0
    assert out["balance_settled"] == 1


def test_a_debit_of_the_stake_says_PLACED(monkeypatch):
    """The other direction, and the one that must never be missed: the order
    DID land and we are holding a position we have no id for."""
    trail = [
        _reading("2026-08-29T21:05:56Z", 96.04765),
        _reading("2026-08-29T21:12:47Z", 94.20765),  # -1.84
    ]
    out = _probe(monkeypatch, [_the_503()], trail)
    evidence = out["findings"][0]["balance_evidence"]
    assert evidence["verdict"] == "placed"
    assert out["balance_settled"] == 1


def test_another_order_in_the_window_is_CONFOUNDED_not_a_verdict(monkeypatch):
    """A busy slate is the common case and the delta stops being attributable.
    The honest answer is "I cannot tell", never the permissive one."""
    other = {
        "mode": "live", "venue": "polymarket", "status": "filled",
        "idempotency_key": "other", "venue_ticker": "tsc-other",
        "submitted_at": "2026-08-29T21:08:00Z", "venue_order_id": "X",
    }
    out = _probe(monkeypatch, [_the_503(), other], _THE_REAL_TRAIL)
    evidence = out["findings"][0]["balance_evidence"]
    assert evidence["verdict"] == "unknown"
    assert evidence["reason"] == "confounded"
    assert evidence["confounding_orders"] == 1
    assert out["balance_settled"] == 0


def test_no_trail_is_UNKNOWN_and_never_not_placed(monkeypatch):
    """The ordinary state for any order older than the history. A guard that
    maps absent onto its permissive branch would release a retry here."""
    out = _probe(monkeypatch, [_the_503()], [])
    evidence = out["findings"][0]["balance_evidence"]
    assert evidence["verdict"] == "unknown"
    assert evidence["reason"] == "no_bracketing_reading"


def test_a_trail_that_starts_after_the_submit_proves_nothing(monkeypatch):
    trail = [_reading("2026-08-29T21:12:47Z", 96.04765), _reading("2026-08-29T21:18:46Z", 96.04765)]
    out = _probe(monkeypatch, [_the_503()], trail)
    assert out["findings"][0]["balance_evidence"]["reason"] == "no_bracketing_reading"


def test_an_unreadable_balance_is_not_an_unchanged_one(monkeypatch):
    """"We could not read it" and "it did not move" are opposite facts that a
    naive implementation renders identically."""
    trail = [
        _reading("2026-08-29T21:05:56Z", None, status="auth_error"),
        _reading("2026-08-29T21:12:47Z", 96.04765),
    ]
    out = _probe(monkeypatch, [_the_503()], trail)
    evidence = out["findings"][0]["balance_evidence"]
    assert evidence["verdict"] == "unknown"
    assert evidence["reason"] == "unreadable"


def test_a_move_that_does_not_match_the_stake_is_INCONCLUSIVE(monkeypatch):
    trail = [
        _reading("2026-08-29T21:05:56Z", 96.04765),
        _reading("2026-08-29T21:12:47Z", 95.90000),  # -0.15, not 1.84
    ]
    out = _probe(monkeypatch, [_the_503()], trail)
    evidence = out["findings"][0]["balance_evidence"]
    assert evidence["verdict"] == "unknown"
    assert evidence["reason"] == "moved_but_not_by_this_order"


def test_the_order_never_counts_as_its_own_confounder(monkeypatch):
    """By key, not identity -- the same bug `sole_claim` was written to avoid."""
    out = _probe(monkeypatch, [_the_503()], _THE_REAL_TRAIL)
    assert out["findings"][0]["balance_evidence"]["confounding_orders"] == 0
