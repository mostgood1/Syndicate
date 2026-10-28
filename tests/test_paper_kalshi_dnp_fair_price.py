"""#744 Kalshi fair-price re-scope: on Kalshi a player who did not play is not a void.

User decision 2026-10-28, verbatim "Yes, build it" (to "Settle Kalshi-ladder paper
bets on players who didn't play at Kalshi's fair price?"). Kalshi's rule: "If a
player is inactive, or active but never takes the court, the market settles to a
fair price." MEASURED 14:41Z: the 9 tickers behind 10 `paper:kalshi:ladder`
voids all `finalized`, result `scalar`, $0.41-$0.65. Reachability first
(Kalshi venue != book venue, off != on), then the arithmetic on those measured
rows, the refusals, and the archive superseding the stale voids. No network.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger as ledger
from syndicate.features.shared import paper_settlement as ps
from syndicate.features.shared.execution_ledger import OrderRequest, place_order

DNP = "nba_player_did_not_play_void"
TICKER = "KXNBA3PT-26OCT25DETPHI-PHIVEDGECOMBE77-2"


def _order(**overrides):
    # VJ Edgecombe 2+ threes, as recorded on the fleet (fill -144, $1, fee 0.0287).
    order = {
        "sport": "nba",
        "mode": "paper",
        "venue": "paper:kalshi:ladder",
        "venue_ticker": TICKER,
        "status": "filled",
        "market": "player_threes",
        "side": "over",
        "line": 1.5,
        "player_name": "VJ Edgecombe",
        "selected_date": "2026-10-25",
        "fill_stake_dollars": 1.0,
        "fill_price": -144.0,
        "fees_dollars": 0.0287,
    }
    order.update(overrides)
    return order


def _market(value="0.6500", *, result="scalar", status="finalized"):
    return {"ticker": TICKER, "status": status, "result": result, "settlement_value_dollars": value}


def _refusing(reason, **extra):
    return lambda _order: {"unavailable_reason": reason, **extra}


@pytest.fixture
def kalshi(monkeypatch):
    """Stub Kalshi's market read; records every ticker asked."""
    asked: list[str] = []
    state = {"market": _market()}

    def read(ticker):
        asked.append(ticker)
        return state["market"]

    monkeypatch.setattr(ps, "_kalshi_market", read)
    monkeypatch.delenv(ps.DNP_VOID_ENV, raising=False)
    state["asked"] = asked
    return state


# --------------------------------------------------------------------------
# Reachability: the venue must change the answer, and so must the switch.
# --------------------------------------------------------------------------


def test_a_kalshi_venue_REACHES_the_fair_price_and_a_book_venue_still_voids(kalshi):
    book, _, _ = ps._our_verdict(_order(venue="paper"), _refusing(DNP))
    ladder, _, _ = ps._our_verdict(_order(), _refusing(DNP))

    assert book["void_reason"] == DNP and "fair_price_reason" not in book
    assert ladder["fair_price_reason"] == ps.REASON_KALSHI_FAIR_PRICE and "void_reason" not in ladder
    assert book != ladder
    assert kalshi["asked"] == [TICKER]


def test_the_switch_off_refuses_on_every_venue_and_never_reads_kalshi(kalshi, monkeypatch):
    monkeypatch.setenv(ps.DNP_VOID_ENV, "off")
    verdict, _, refusal = ps._our_verdict(_order(), _refusing(DNP))
    assert verdict is None and refusal == DNP
    assert kalshi["asked"] == []


@pytest.mark.parametrize("venue", ["kalshi", "paper:kalshi", "paper:kalshi:ladder"])
def test_every_kalshi_venue_settles_at_the_fair_price(kalshi, venue):
    verdict, _, _ = ps._our_verdict(_order(venue=venue), _refusing(DNP))
    assert verdict["fair_price_reason"] == ps.REASON_KALSHI_FAIR_PRICE


@pytest.mark.parametrize("venue", ["paper", "paper:polymarket:ladder", "paper:prophetx", "paper:novig"])
def test_venues_whose_rule_is_unread_keep_the_void(kalshi, venue):
    verdict, _, _ = ps._our_verdict(_order(venue=venue), _refusing(DNP))
    assert verdict["void_reason"] == DNP
    assert kalshi["asked"] == []


# --------------------------------------------------------------------------
# The arithmetic, on the rows measured 2026-10-28 14:41Z.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fill_price, fees, value, gross, net",
    [
        (-144.0, 0.0287, "0.6500", 0.1014, 0.0727),  # VJ Edgecombe 2+ threes
        (150.0, 0.0420, "0.4100", 0.0250, -0.0170),  # Kawhi Leonard 4+ assists
        (127.0, 0.0392, "0.4300", -0.0239, -0.0631),  # Tyjae Spears 3+ receptions
        (-104.0, 0.0344, "0.5600", 0.0985, 0.0641),  # Kyrie Irving 4+ assists
    ],
)
def test_the_measured_rows_settle_at_kalshis_price(kalshi, fill_price, fees, value, gross, net):
    kalshi["market"] = _market(value)
    verdict, _, _ = ps._our_verdict(_order(fill_price=fill_price, fees_dollars=fees), _refusing(DNP))

    assert verdict["outcome"] == ps.OUTCOME_PUSH
    assert verdict["pnl_gross_dollars"] == pytest.approx(gross, abs=1e-3)
    assert verdict["pnl_dollars"] == pytest.approx(net, abs=1e-3)
    assert verdict["venue_fair_value"] == pytest.approx(float(value))


def test_a_NO_leg_is_worth_one_minus_the_fair_value(kalshi):
    kalshi["market"] = _market("0.6500")
    verdict, _, _ = ps._our_verdict(_order(side="under", fill_price=0.40, fees_dollars=0.0), _refusing(DNP))
    # NO bought at $0.40 settles at $0.35: 1.0 * (0.35 / 0.40 - 1) = -0.125.
    assert verdict["venue_fair_value"] == pytest.approx(0.35)
    assert verdict["pnl_gross_dollars"] == pytest.approx(-0.125)


def test_a_probability_dollar_fill_price_is_its_own_entry(kalshi):
    kalshi["market"] = _market("0.5000")
    verdict, _, _ = ps._our_verdict(_order(fill_price=0.46, fees_dollars=0.0), _refusing(DNP))
    assert verdict["pnl_gross_dollars"] == pytest.approx(0.5 / 0.46 - 1.0, abs=1e-4)


# --------------------------------------------------------------------------
# Refusals: each by name, and never a void or a guess.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "market, reason",
    [
        (None, ps.REASON_KALSHI_UNREADABLE),
        (_market(result="yes"), ps.REASON_KALSHI_RESULT_BINARY),
        (_market(result="no"), ps.REASON_KALSHI_RESULT_BINARY),
        (_market(result="", status="closed"), ps.REASON_KALSHI_NOT_SETTLED),
        (_market(status="active"), ps.REASON_KALSHI_NOT_SETTLED),
        (_market(value="n/a"), ps.REASON_KALSHI_VALUE_UNREADABLE),
        (_market(value="1.5"), ps.REASON_KALSHI_VALUE_UNREADABLE),
    ],
)
def test_a_market_that_cannot_say_the_fair_price_refuses_by_name(kalshi, market, reason):
    kalshi["market"] = market
    verdict, _, refusal = ps._our_verdict(_order(), _refusing(DNP))
    assert verdict is None and refusal == reason


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"venue_ticker": None}, ps.REASON_KALSHI_NO_TICKER),
        ({"side": "home"}, ps.REASON_KALSHI_LEG_UNMAPPABLE),
        ({"status": "submitted"}, ps.REASON_NOT_FILLED),
    ],
)
def test_an_order_it_cannot_settle_refuses_WITHOUT_reading_kalshi(kalshi, overrides, reason):
    verdict, _, refusal = ps._our_verdict(_order(**overrides), _refusing(DNP))
    assert verdict is None and refusal == reason
    assert kalshi["asked"] == []


def test_a_refusal_that_is_not_a_did_not_play_never_reads_kalshi(kalshi):
    verdict, _, refusal = ps._our_verdict(_order(), _refusing("nba_player_not_in_box"))
    assert verdict is None and refusal == "nba_player_not_in_box"
    assert kalshi["asked"] == []


# --------------------------------------------------------------------------
# The row, the tally and the ROI.
# --------------------------------------------------------------------------


def test_the_stamped_row_says_why_and_carries_no_void_reason(kalshi):
    order = _order(void_reason=DNP)  # a stale void being re-graded
    resolved = {"unavailable_reason": DNP, "dnp_basis": "did_not_play", "espn_athlete_id": "5124612"}
    verdict, resolved, _ = ps._our_verdict(order, lambda _o: resolved)
    ps._stamp_grade(order, verdict, resolved)

    assert "void_reason" not in order
    assert order["fair_price_reason"] == ps.REASON_KALSHI_FAIR_PRICE
    assert order["dnp_reason"] == DNP and order["venue_fair_value"] == pytest.approx(0.65)
    assert order["dnp_basis"] == "did_not_play" and order["espn_athlete_id"] == "5124612"
    assert ps._outcome_key(verdict) == "fair_price"


def test_a_fair_price_stays_IN_the_ROI_denominator_and_out_of_the_win_rate():
    rows = [
        _order(outcome="won", pnl_dollars=0.69, fill_stake_dollars=1.0),
        _order(outcome="push", pnl_dollars=0.0727, fill_stake_dollars=1.0, fair_price_reason=ps.REASON_KALSHI_FAIR_PRICE),
        _order(outcome="push", pnl_dollars=0.0, fill_stake_dollars=1.0, void_reason=DNP),
    ]
    bucket = next(b for b in ps.settlement_summary(None, orders=rows)["by_venue"] if b["venue"] == "paper:kalshi:ladder")

    assert bucket["settled"] == 3 and bucket["void"] == 1 and bucket["push"] == 1
    assert bucket["staked_dollars"] == pytest.approx(2.0)  # the void's $1 is out, the fair price's is in
    assert bucket["pnl_dollars"] == pytest.approx(0.76)
    assert bucket["win_pct"] == pytest.approx(100.0)


# --------------------------------------------------------------------------
# The market read: base fallback, and only a SETTLED market is memoised.
# --------------------------------------------------------------------------


def test_the_market_read_falls_back_across_bases_and_memoises_only_settled(monkeypatch):
    from syndicate.features.shared import kalshi_client

    monkeypatch.setattr(ps, "_KALSHI_MARKET_MEMO", {})
    calls: list[str] = []
    payloads = {"OPEN": _market(result="", status="active"), TICKER: _market()}

    def fake_get(url, *, timeout=20.0):
        calls.append(url)
        if url.startswith(kalshi_client._BASE_URLS[0]):
            raise kalshi_client.KalshiError("first base down")
        return {"market": payloads[url.rsplit("/", 1)[1]]}

    monkeypatch.setattr(kalshi_client, "_get", fake_get)
    assert ps._kalshi_market(TICKER)["result"] == "scalar"
    assert ps._kalshi_market(TICKER)["result"] == "scalar"
    assert len(calls) == 2  # first base failed, second answered; then the memo

    ps._kalshi_market("OPEN")
    ps._kalshi_market("OPEN")
    assert len(calls) == 6  # an open market is re-read every time


def test_every_base_failing_is_None_and_refuses_unreadable(monkeypatch):
    from syndicate.features.shared import kalshi_client

    monkeypatch.setattr(ps, "_KALSHI_MARKET_MEMO", {})

    def down(url, *, timeout=20.0):
        raise kalshi_client.KalshiError("down")

    monkeypatch.setattr(kalshi_client, "_get", down)
    monkeypatch.delenv(ps.DNP_VOID_ENV, raising=False)
    assert ps._kalshi_market(TICKER) is None
    verdict, _, refusal = ps._our_verdict(_order(), _refusing(DNP))
    assert verdict is None and refusal == ps.REASON_KALSHI_UNREADABLE


# --------------------------------------------------------------------------
# The archive: a stale Kalshi void is superseded, once; a book void is not touched.
# --------------------------------------------------------------------------

DATE = "2026-10-25"
TODAY = "2026-10-28"


@pytest.fixture
def archive(tmp_path, monkeypatch, kalshi):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ledger, "_MAX_RECORDS", 2)
    import syndicate.features.shared.order_clv as order_clv

    monkeypatch.setattr(order_clv, "clv_for_orders", lambda rows, date=None: {"rows": []})
    return kalshi


def _place(key, venue, ticker=None):
    return place_order(
        OrderRequest(
            position_key=key,
            selected_date=DATE,
            venue=venue,
            sport="nba",
            event_id=f"evt-{key}",
            market="player_threes",
            side="over",
            requested_price=-144.0,
            requested_stake_dollars=1.0,
            line=1.5,
            player_name="VJ Edgecombe",
            commence_time="2026-10-25T23:00:00Z",
            venue_ticker=ticker,
        )
    )


def _archive_void(key, venue, ticker=None):
    """Place `key`, evict it with two fillers, then append the void the old rule wrote."""
    _place(key, venue, ticker)
    _place(f"{key}-f1", "paper")
    _place(f"{key}-f2", "paper")
    row = dict(next(o for o in ledger.archived_orders() if o["position_key"] == key))
    assert row["outcome"] is None and row["status"] == "filled"
    ps._stamp_grade(row, ps.void_order(row, DNP), {})
    row["graded_from"] = ps.GRADED_FROM_ARCHIVE
    ledger._archive_rows([row])
    return row


def _last(key):
    return next(o for o in ledger.archived_orders() if o["position_key"] == key)


def test_the_archived_pass_supersedes_a_kalshi_void_once_and_leaves_a_book_void(archive):
    _archive_void("k1", "paper:kalshi:ladder", TICKER)
    _archive_void("b1", "paper")
    asked: list[str] = []

    def factory(_slate):
        def resolve(order):
            asked.append(order["position_key"])
            # The evicted fillers are ungraded candidates too; they must not settle here.
            return {"unavailable_reason": DNP if order["position_key"] in {"k1", "b1"} else "no_feed"}

        return resolve

    first = ps.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=factory, max_age_days=None, max_dates=None)
    assert first["outcomes"] == {"fair_price": 1} and first["appended"] == 1
    assert "k1" in asked and "b1" not in asked  # the book void is not a candidate

    k1 = _last("k1")
    assert "void_reason" not in k1 and k1["fair_price_reason"] == ps.REASON_KALSHI_FAIR_PRICE
    assert k1["outcome"] == "push" and k1["pnl_gross_dollars"] == pytest.approx(0.1014, abs=1e-3)
    assert _last("b1")["void_reason"] == DNP

    asked.clear()
    second = ps.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=factory, max_age_days=None, max_dates=None)
    assert second["graded"] == 0 and "k1" not in asked


def test_with_the_switch_off_a_kalshi_void_is_not_a_candidate(archive, monkeypatch):
    _archive_void("k1", "paper:kalshi:ladder", TICKER)
    monkeypatch.setenv(ps.DNP_VOID_ENV, "off")
    asked: list[str] = []

    def factory(_slate):
        def resolve(order):
            asked.append(order["position_key"])
            return {"unavailable_reason": "no_feed"}

        return resolve

    ps.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=factory, max_age_days=None, max_dates=None)
    assert "k1" not in asked and _last("k1")["void_reason"] == DNP


def test_the_live_document_supersedes_a_kalshi_void_once_and_leaves_a_book_void(kalshi, monkeypatch):
    kalshi_void = _order(outcome="push", pnl_dollars=0.0, void_reason=DNP)
    book_void = _order(venue="paper", outcome="push", pnl_dollars=0.0, void_reason=DNP)
    state = {"orders": [kalshi_void, book_void]}
    asked: list[str] = []

    def resolve(order):
        asked.append(order["venue"])
        return {"unavailable_reason": DNP}

    monkeypatch.setattr(ledger, "_load", lambda: state)
    monkeypatch.setattr(ledger, "_persist", lambda _state: None)
    monkeypatch.setattr(ps, "stamp_closing_marks", lambda *a, **k: {})
    monkeypatch.setattr(ledger, "full_history_orders", lambda: [])

    first = ps.settle_orders("2026-10-25", resolver=resolve)
    assert first["outcomes"] == {"fair_price": 1} and first["already_graded"] == 1
    assert "void_reason" not in kalshi_void and kalshi_void["fair_price_reason"] == ps.REASON_KALSHI_FAIR_PRICE
    assert book_void["void_reason"] == DNP

    second = ps.settle_orders("2026-10-25", resolver=resolve)
    assert second["graded"] == 0 and second["already_graded"] == 2
    # Only the venue cross-check may look past a settled row, and paper rows are not venue-settled.
    assert asked == ["paper:kalshi:ladder"]


# --------------------------------------------------------------------------
# A live Kalshi entry that was SOLD cannot take a fair price through the exit math.
# --------------------------------------------------------------------------


def test_a_sold_live_kalshi_entry_with_a_fair_price_refuses_by_name(kalshi, monkeypatch):
    from syndicate.features.shared import venue_settlement as vs

    order = _order(mode="live", venue="kalshi", selected_date="2026-10-20", submitted_at="2026-10-20T18:00:00Z")
    persisted: list = []
    monkeypatch.setattr(ledger, "_load", lambda: {"orders": [order]})
    monkeypatch.setattr(ledger, "_persist", lambda state: persisted.append(state))
    monkeypatch.setattr(vs, "load_live_exits", lambda: ({}, None))
    monkeypatch.setattr(vs, "exit_for_order", lambda _o, _e: ("sold", {"exit_key": "x"}))
    monkeypatch.setattr(ps, "stamp_closing_marks", lambda *a, **k: {})
    monkeypatch.setattr(ledger, "full_history_orders", lambda: [])

    result = ps.settle_orders("2026-10-20", resolver=_refusing(DNP))
    assert result["graded"] == 0
    assert result["ungraded"] == {"exit_fair_price_unsupported": 1}
    assert kalshi["asked"] == [TICKER]  # the branch ran: the fair price was read, then refused
    assert "outcome" not in order
