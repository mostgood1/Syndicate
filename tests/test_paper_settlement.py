"""Grading a placed bet — the step that was missing, not broken."""

from __future__ import annotations

import pytest

from syndicate.features.shared import paper_settlement as settle
from syndicate.features.shared.execution_ledger import OrderRequest, place_order


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


DATE = "2026-08-22"


def _place(price=-110.0, stake=10.0, side="over", line=6.5, key="p1", venue="paper"):
    return place_order(
        OrderRequest(
            position_key=key,
            selected_date=DATE,
            venue=venue,
            sport="mlb",
            event_id="evt-1",
            market="strikeouts",
            side=side,
            requested_price=price,
            requested_stake_dollars=stake,
            line=line,
            player_name="Andrew Abbott",
            game_pk="777",
        )
    )


def _resolver(value, *, is_final=True, unavailable=None):
    def resolve(_order):
        if unavailable:
            return {"unavailable_reason": unavailable}
        return {"current_value": value, "is_final": is_final, "started": True}

    return resolve


# --- the arithmetic --------------------------------------------------------


def test_american_odds_become_profit_per_dollar():
    assert settle.american_profit(150) == 1.5
    assert settle.american_profit(-110) == pytest.approx(0.9090909)


def test_an_unreadable_price_is_None_not_zero():
    # A zero would render a winning bet as break-even -- a wrong number that
    # looks like a modest result rather than like an error.
    assert settle.american_profit(None) is None
    assert settle.american_profit(0) is None
    assert settle.american_profit("even") is None


# --- grading ---------------------------------------------------------------


def test_a_won_bet_pays_the_price_it_was_FILLED_at():
    _place(price=-110.0, stake=10.0)
    result = settle.settle_orders(DATE, resolver=_resolver(9.0))

    assert result["graded"] == 1
    assert result["outcomes"] == {"won": 1}
    summary = settle.settlement_summary(DATE)
    assert summary["total"]["pnl_dollars"] == pytest.approx(9.09, abs=0.01)


def test_a_lost_bet_costs_the_stake_and_no_more():
    _place(price=-110.0, stake=10.0)
    settle.settle_orders(DATE, resolver=_resolver(3.0))

    summary = settle.settlement_summary(DATE)
    assert summary["total"]["pnl_dollars"] == -10.0
    assert summary["total"]["lost"] == 1


def test_a_final_tie_is_a_PUSH_and_returns_the_stake():
    """`resolve_bet_status` calls a decided tie `live_tied`, which reads oddly
    for a finished game. Folding it into the losses would understate every
    figure this module produces."""
    _place(price=-110.0, stake=10.0, line=7.0)
    settle.settle_orders(DATE, resolver=_resolver(7.0))

    summary = settle.settlement_summary(DATE)
    assert summary["total"]["push"] == 1
    assert summary["total"]["pnl_dollars"] == 0.0
    assert summary["total"]["lost"] == 0


def test_grading_uses_the_fill_price_not_the_requested_one():
    from syndicate.features.shared.execution_ledger import _load, _persist

    _place(price=-110.0, stake=10.0)
    state = _load()
    # Slippage: the plan wanted -110 and the book gave -130.
    state["orders"][0]["fill_price"] = -130.0
    _persist(state)

    settle.settle_orders(DATE, resolver=_resolver(9.0))
    summary = settle.settlement_summary(DATE)
    # Grading against the request would credit the strategy with a price it did
    # not get.
    assert summary["total"]["pnl_dollars"] == pytest.approx(7.69, abs=0.01)


# --- what must NOT be graded ----------------------------------------------


def test_an_undecided_bet_is_left_ungraded_with_a_reason():
    _place()
    result = settle.settle_orders(DATE, resolver=_resolver(3.0, is_final=False))

    assert result["graded"] == 0
    # "We have not graded this yet" and "this lost" are the two facts a
    # performance number must never blur.
    assert result["ungraded"] == {settle.REASON_NOT_DECIDED: 1}
    assert settle.settlement_summary(DATE)["total"]["pending"] == 1


def test_a_monotone_market_already_over_the_line_is_graded_mid_game():
    """A strikeout count only rises, so crossing the line decides an over
    permanently -- it cannot be taken back by anything later in the game."""
    _place(side="over", line=6.5)
    result = settle.settle_orders(DATE, resolver=_resolver(7.0, is_final=False))
    assert result["outcomes"] == {"won": 1}


def test_an_under_is_not_graded_early_even_when_comfortably_ahead():
    _place(side="under", line=6.5)
    result = settle.settle_orders(DATE, resolver=_resolver(1.0, is_final=False))
    # An under is merely still alive until the game ends.
    assert result["graded"] == 0


def test_a_feeds_own_refusal_is_passed_through_not_flattened():
    _place()
    result = settle.settle_orders(DATE, resolver=_resolver(None, unavailable="no_feed"))
    # `no_game_pk`, `no_feed` and `no_stat` are three different jobs.
    assert result["ungraded"] == {"no_feed": 1}


def test_a_resolver_that_raises_does_not_take_down_the_run():
    _place(key="p1")
    _place(key="p2")

    calls = {"n": 0}

    def flaky(order):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("feed exploded")
        return {"current_value": 9.0, "is_final": True, "started": True}

    result = settle.settle_orders(DATE, resolver=flaky)
    assert result["graded"] == 1
    assert result["ungraded"] == {"resolver_error:RuntimeError": 1}


# --- immutability ----------------------------------------------------------


def test_a_graded_order_is_never_re_graded():
    """A later feed read can differ -- a stat correction, or a cache miss
    returning nothing. A ledger that changes its mind about a settled bet is not
    a record of anything."""
    _place(price=-110.0, stake=10.0)
    settle.settle_orders(DATE, resolver=_resolver(9.0))

    def must_not_run(_order):
        raise AssertionError("a graded order was sent back to the resolver")

    second = settle.settle_orders(DATE, resolver=must_not_run)
    assert second["graded"] == 0
    assert second["already_graded"] == 1
    assert settle.settlement_summary(DATE)["total"]["pnl_dollars"] == pytest.approx(9.09, abs=0.01)


# --- the summary -----------------------------------------------------------


def test_the_two_paper_books_are_reported_separately():
    _place(key="a", venue="paper", stake=10.0)
    _place(key="b", venue="paper:kalshi", stake=4.0)
    settle.settle_orders(DATE, resolver=_resolver(9.0))

    summary = settle.settlement_summary(DATE)
    venues = {row["venue"]: row for row in summary["by_venue"]}
    # They exist to be compared; a pooled number destroys the comparison.
    assert venues["paper"]["staked_dollars"] == 10.0
    assert venues["paper:kalshi"]["staked_dollars"] == 4.0


def test_roi_is_omitted_rather_than_shown_as_zero_when_nothing_settled():
    _place()
    summary = settle.settlement_summary(DATE)
    # 0.0% on zero settled bets and 0.0% on fifty are the same string and
    # opposite facts.
    assert summary["total"]["roi_pct"] is None
    assert summary["total"]["win_pct"] is None


def test_roi_counts_settled_stake_only():
    _place(key="a", price=100.0, stake=10.0)
    _place(key="b", price=100.0, stake=90.0)

    def first_done_second_in_progress(order):
        if order.get("position_key") == "a":
            return {"current_value": 9.0, "is_final": True, "started": True}
        # Below the line and still playing: an over that is behind is not
        # decided, so it stays pending.
        return {"current_value": 2.0, "is_final": False, "started": True}

    settle.settle_orders(DATE, resolver=first_done_second_in_progress)
    summary = settle.settlement_summary(DATE)
    # +100 on $10 is +$10 on $10 settled = 100%. Including the $90 pending stake
    # would dilute the number with a bet that has not happened yet.
    assert summary["total"]["settled"] == 1
    assert summary["total"]["pending"] == 1
    assert summary["total"]["roi_pct"] == 100.0


def test_an_unfilled_order_is_not_counted_as_a_loss(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.delenv("SYNDICATE_EXECUTION_LIVE_ARMED", raising=False)
    record = _place()
    assert record["status"] == "rejected"

    result = settle.settle_orders(DATE, resolver=_resolver(3.0))
    # Charging the strategy for a bet it does not hold.
    assert result["ungraded"] == {settle.REASON_NOT_FILLED: 1}
    assert settle.settlement_summary(DATE)["total"]["lost"] == 0


def test_an_unmapped_market_is_reported_BY_NAME(monkeypatch):
    """`unmapped_market: 15` is a number nobody can act on.

    The market names are the difference between "add five mappings" and another
    round of guessing at which five.
    """
    _place(key="a")
    _place(key="b")

    def resolver(order):
        return {"unavailable_reason": "unmapped_market"}

    from syndicate.features.shared.execution_ledger import _load, _persist

    state = _load()
    state["orders"][0]["market"] = "batter_doubles"
    state["orders"][1]["market"] = "h2h"
    _persist(state)

    result = settle.settle_orders(DATE, resolver=resolver)
    assert result["ungraded"] == {"unmapped_market": 2}
    assert set(result["unmapped_markets"]) == {"batter_doubles", "h2h"}


def test_only_unmapped_market_contributes_names(monkeypatch):
    _place()
    result = settle.settle_orders(DATE, resolver=_resolver(None, unavailable="no_live_feed"))
    # A missing feed says nothing about the market vocabulary.
    assert result["unmapped_markets"] == {}


# --------------------------------------------------------------------------
# Per-sport dispatch -- WNBA joins MLB
# --------------------------------------------------------------------------


def test_each_sport_gets_its_own_resolver(monkeypatch):
    seen = []

    def fake_build(module, factory, date):
        def resolve(order):
            seen.append((order.get("sport"), module))
            return {"current_value": 9.0, "is_final": True, "started": True}
        return resolve

    monkeypatch.setattr(settle, "_build", fake_build)
    dispatch = settle._default_resolver(DATE)

    dispatch({"sport": "mlb"})
    dispatch({"sport": "wnba"})
    assert [s for s, _ in seen] == ["mlb", "wnba"]
    assert "bet_status_mlb" in seen[0][1]
    assert "bet_status_wnba" in seen[1][1]


def test_a_sport_with_no_resolver_is_named_not_silent():
    verdict = settle._default_resolver(DATE)({"sport": "soccer"})
    # The ungraded counts stay a work list rather than a mystery.
    assert verdict["unavailable_reason"] == "no_resolver_for_soccer"


def test_one_sports_broken_resolver_does_not_stop_another(monkeypatch):
    def fake_build(module, factory, date):
        if "wnba" in module:
            return None  # artifact unreadable, say
        return lambda order: {"current_value": 9.0, "is_final": True, "started": True}

    monkeypatch.setattr(settle, "_build", fake_build)
    dispatch = settle._default_resolver(DATE)

    assert dispatch({"sport": "wnba"})["unavailable_reason"] == "resolver_unavailable_for_wnba"
    # MLB keeps grading regardless.
    assert dispatch({"sport": "mlb"})["current_value"] == 9.0


def test_a_wnba_bet_now_grades_end_to_end(monkeypatch, tmp_path):
    """The whole point: a WNBA order used to come back `not_an_mlb_order`."""
    import json

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    box = tmp_path / "wnba_source" / "data" / "live" / f"live_player_box_{DATE}.json"
    box.parent.mkdir(parents=True, exist_ok=True)
    box.write_text(
        json.dumps({"payload": {"games": [{"event_id": "evt-w", "players": [
            {"player": "A'ja Wilson", "pts": 24, "reb": 8, "ast": 3, "threes_made": 1}]}]}}),
        encoding="utf-8",
    )

    place_order(
        OrderRequest(
            position_key="w1", selected_date=DATE, venue="paper", sport="wnba",
            event_id="evt-w", market="player_points", side="over",
            requested_price=-110.0, requested_stake_dollars=10.0, line=19.5,
            player_name="A'ja Wilson",
        )
    )

    result = settle.settle_orders(DATE)
    # Points only rise, so the over is decided the moment it crosses — no
    # game-status field required.
    assert result["outcomes"] == {"won": 1}


# --------------------------------------------------------------------------
# Two price units in one column, and the fees that come out of both
# --------------------------------------------------------------------------


def test_a_kalshi_contract_is_not_graded_as_american_odds():
    """THE LEDGER HOLDS BOTH UNITS IN ONE COLUMN. A sportsbook fill records
    American odds (-110); a Kalshi fill records probability dollars (0.46).
    `american_profit(0.46)` is 0.0046 -- a winning contract booked at 0.46%
    profit instead of 117%, ~250x too small, and it reads as a disappointing
    result rather than as an error. The same confusion rendered every Kalshi
    price on the live page as `+0`."""
    from syndicate.features.shared.paper_settlement import (
        american_profit,
        profit_per_dollar,
    )

    assert american_profit(0.46) == pytest.approx(0.0046)
    assert profit_per_dollar(0.46) == pytest.approx(0.5400 / 0.46)
    # American odds are untouched -- they are never strictly inside (-1, 1).
    assert profit_per_dollar(-110) == pytest.approx(100.0 / 110.0)
    assert profit_per_dollar(150) == pytest.approx(1.5)


def test_fees_are_netted_out_of_a_winner():
    from syndicate.features.shared.bet_status import STATUS_WON
    from syndicate.features.shared.paper_settlement import grade_order

    graded = grade_order(
        {"status": "filled", "fill_price": 0.54, "fill_stake_dollars": 1.08,
         "fees_dollars": 0.02},
        {"decided": True, "status": STATUS_WON},
    )
    # 2 contracts at $0.54 settle at $1.00 -> $0.92 gross, $0.90 after the fee.
    assert graded["pnl_dollars"] == pytest.approx(0.90, abs=1e-4)


def test_fees_are_charged_on_a_loser_too():
    from syndicate.features.shared.bet_status import STATUS_LOST
    from syndicate.features.shared.paper_settlement import grade_order

    graded = grade_order(
        {"status": "filled", "fill_price": 0.54, "fill_stake_dollars": 1.08,
         "fees_dollars": 0.02},
        {"decided": True, "status": STATUS_LOST},
    )
    assert graded["pnl_dollars"] == pytest.approx(-1.10, abs=1e-4)


def test_a_push_still_costs_the_fee():
    """The money left the account when the trade happened, not when it
    settled."""
    from syndicate.features.shared.paper_settlement import grade_order

    graded = grade_order(
        {"status": "filled", "fill_price": -110, "fill_stake_dollars": 10.0,
         "fees_dollars": 0.25},
        {"decided": True, "status": "live_tied"},
    )
    assert graded["outcome"] == "push"
    assert graded["pnl_dollars"] == pytest.approx(-0.25)


def test_an_absent_fee_is_charged_as_zero_not_refused():
    """A bet whose fee we cannot read is still a bet with a real outcome.
    Refusing to grade it would lose the outcome to save the rounding."""
    from syndicate.features.shared.bet_status import STATUS_WON
    from syndicate.features.shared.paper_settlement import grade_order

    graded = grade_order(
        {"status": "filled", "fill_price": -110, "fill_stake_dollars": 10.0},
        {"decided": True, "status": STATUS_WON},
    )
    assert graded["graded"] is True
    assert graded["pnl_dollars"] == pytest.approx(100.0 / 11.0, abs=1e-3)


# --------------------------------------------------------------------------
# Game lines reaching a graded outcome, through settle_orders itself
# --------------------------------------------------------------------------


def test_a_spread_order_grades_end_to_end(monkeypatch, tmp_path):
    """The 80 orders a slate could never grade. This is the whole path: the
    ledger record as it is actually written (side = a team NAME, line = the
    quoted handicap), through `settle_orders`, to a stored outcome and P&L."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared.paper_settlement import settle_orders

    request = ledger.OrderRequest(
        position_key="spread-1", selected_date="2026-08-22", venue="paper",
        sport="mlb", event_id="e1", market="spreads",
        # AS THE BOARD WRITES IT: the side is a club, not a direction.
        side="Houston Astros", line=-1.5,
        requested_price=-110.0, requested_stake_dollars=10.0,
        home_team="Houston Astros", away_team="Seattle Mariners",
    )
    ledger.place_order(request, mode=ledger.PAPER)

    # Houston won by 3, covering -1.5.
    result = settle_orders(
        "2026-08-22",
        resolver=lambda order: {"current_value": 3, "side": "over", "line": 1.5,
                                "is_final": True, "started": True},
    )
    assert result["graded"] == 1
    assert result["outcomes"] == {"won": 1}

    graded = ledger.find_order(ledger.idempotency_key(request))
    assert graded["outcome"] == "won"
    # -110 stake $10 -> $9.09 profit. The American-odds path is untouched by
    # the probability-dollar work.
    assert graded["pnl_dollars"] == pytest.approx(100.0 / 11.0, abs=1e-3)


def test_the_resolver_can_restate_side_and_line_but_the_ORDER_cannot_change(
    monkeypatch, tmp_path
):
    """The order records what was BET. A spread was bet on a club, and the
    ledger must keep saying so however the grader needed it phrased -- the
    record is the durable account of the position, not a scratch pad for the
    grading step."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared.paper_settlement import settle_orders

    request = ledger.OrderRequest(
        position_key="spread-2", selected_date="2026-08-22", venue="paper",
        sport="mlb", event_id="e2", market="h2h", side="Seattle Mariners",
        requested_price=-110.0, requested_stake_dollars=10.0,
    )
    ledger.place_order(request, mode=ledger.PAPER)
    settle_orders(
        "2026-08-22",
        resolver=lambda order: {"current_value": -3, "side": "over", "line": 0.0,
                                "is_final": True, "started": True},
    )

    stored = ledger.find_order(ledger.idempotency_key(request))
    assert stored["side"] == "Seattle Mariners"
    assert stored["outcome"] == "lost"


def test_a_player_prop_ignores_the_override_path(monkeypatch, tmp_path):
    """A resolver that says nothing about side or line leaves the order's own
    fields in charge -- so every prop that already graded is untouched."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared.paper_settlement import settle_orders

    request = ledger.OrderRequest(
        position_key="prop-1", selected_date="2026-08-22", venue="paper",
        sport="mlb", event_id="e3", market="strikeouts", side="over", line=4.5,
        player_name="Framber Valdez",
        requested_price=-110.0, requested_stake_dollars=10.0,
    )
    ledger.place_order(request, mode=ledger.PAPER)
    settle_orders(
        "2026-08-22",
        resolver=lambda order: {"current_value": 7, "is_final": True, "started": True},
    )
    assert ledger.find_order(ledger.idempotency_key(request))["outcome"] == "won"


def test_settling_reports_the_MONEY_not_only_the_counts(monkeypatch, tmp_path, capsys):
    """`SETTLED` has always said how many bets graded and why the rest did not.
    It never said what any of it won or lost -- that figure lived only on
    `/portfolio/paper`, a web page, and the web service is unreachable from the
    worker that computes settlement. So the question the whole layer exists to
    answer could only be asked from a browser, one date at a time.

    Both scopes, because they answer different questions: the date says how one
    slate went, all-time says whether this is working at all."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared.paper_settlement import settle_orders

    request = ledger.OrderRequest(
        position_key="pnl-1", selected_date="2026-08-22", venue="paper",
        sport="mlb", event_id="e1", market="spreads", side="home", line=-1.5,
        requested_price=-110.0, requested_stake_dollars=10.0,
    )
    ledger.place_order(request, mode=ledger.PAPER)
    settle_orders(
        "2026-08-22",
        resolver=lambda order: {"current_value": 3, "side": "over", "line": 1.5,
                                "is_final": True, "started": True},
    )

    out = capsys.readouterr().out
    assert "[paper_settlement] PNL date=2026-08-22" in out
    assert "[paper_settlement] PNL all_time" in out
    assert "won=1" in out and "staked=$10.0" in out


def test_the_pnl_line_says_n_a_rather_than_zero_when_nothing_settled(
    monkeypatch, tmp_path, capsys
):
    """A 0.0% return on zero bets and on fifty are the same string and opposite
    facts, which is why `settlement_summary` omits the percentage entirely."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared.paper_settlement import settle_orders

    settle_orders("2026-08-22", resolver=lambda order: {})
    out = capsys.readouterr().out
    assert "roi=n/a" in out


def test_a_reporting_failure_does_not_undo_the_grading(monkeypatch, tmp_path, capsys):
    """Grading is already persisted by this point. A broken summary must not
    take it back or stop the next date."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared import paper_settlement as mod

    request = ledger.OrderRequest(
        position_key="pnl-2", selected_date="2026-08-22", venue="paper",
        sport="mlb", event_id="e2", market="h2h", side="home",
        requested_price=-110.0, requested_stake_dollars=10.0,
    )
    ledger.place_order(request, mode=ledger.PAPER)

    def boom(*_a, **_k):
        raise RuntimeError("summary exploded")

    monkeypatch.setattr(mod, "settlement_summary", boom)
    result = mod.settle_orders(
        "2026-08-22",
        resolver=lambda order: {"current_value": 3, "side": "over", "line": 0.0,
                                "is_final": True, "started": True},
    )
    assert result["graded"] == 1
    assert ledger.find_order(ledger.idempotency_key(request))["outcome"] == "won"
    assert "PNL_FAILED" in capsys.readouterr().out


# --------------------------------------------------------------------------
# The cuts that separate best-of-N EV inflation from market mix
# --------------------------------------------------------------------------


def _settled(**kw):
    row = {"venue": "paper", "sport": "mlb", "market": "batter_hits",
           "status": "filled", "outcome": "won", "fill_stake_dollars": 10.0,
           "pnl_dollars": 9.09, "selected_date": "2026-08-23"}
    row.update(kw)
    return row


def test_the_book_splits_by_market_family():
    """MEASURED 2026-08-24: the unrestricted `paper` book returned -4.25% while
    four of five venue-scoped books were positive. A venue label cannot say
    whether that is best-of-N EV inflation admitting bad rows, or simply that
    the unrestricted book is prop-heavy while the venue books are game-line
    heavy. Those need opposite fixes, so the split is worth having."""
    from syndicate.features.shared.paper_settlement import settlement_summary

    summary = settlement_summary(orders=[
        _settled(market="batter_hits", pnl_dollars=9.09),
        _settled(market="spreads", outcome="lost", pnl_dollars=-10.0),
        _settled(market="h2h", outcome="lost", pnl_dollars=-10.0),
        _settled(market="totals", pnl_dollars=9.09),
    ])
    families = {b["key"]: b for b in summary["by_market_family"]}
    assert families["player_prop"]["settled"] == 1
    assert families["game_line"]["settled"] == 2
    assert families["game_line"]["pnl_dollars"] == -20.0
    assert families["game_total"]["settled"] == 1
    # A total is a scoreboard bet like a spread but is modelled completely
    # differently, so it is its own bucket rather than folded into either.
    assert families["game_total"]["key"] != families["game_line"]["key"]


def test_the_book_splits_by_sport():
    from syndicate.features.shared.paper_settlement import settlement_summary

    summary = settlement_summary(orders=[
        _settled(sport="mlb"), _settled(sport="wnba", outcome="lost", pnl_dollars=-10.0),
    ])
    sports = {b["key"]: b for b in summary["by_sport"]}
    assert sports["mlb"]["pnl_dollars"] == 9.09
    assert sports["wnba"]["pnl_dollars"] == -10.0


def test_the_cuts_agree_with_the_total():
    """Three views of one book. If they disagree, one of them is wrong, and a
    breakdown that does not reconcile is worse than no breakdown."""
    from syndicate.features.shared.paper_settlement import settlement_summary

    orders = [
        _settled(market="batter_hits", venue="paper"),
        _settled(market="spreads", venue="paper:kalshi", outcome="lost", pnl_dollars=-10.0),
        _settled(market="totals", venue="paper:novig", sport="wnba"),
    ]
    summary = settlement_summary(orders=orders)
    total = summary["total"]["pnl_dollars"]
    for cut in ("by_venue", "by_market_family", "by_sport", "by_venue_family"):
        assert round(sum(b["pnl_dollars"] for b in summary[cut]), 2) == total, cut
        assert sum(b["settled"] for b in summary[cut]) == summary["total"]["settled"], cut


def test_the_cross_holds_the_family_fixed_and_varies_the_venue():
    """The cut that actually decides between EV inflation and market mix.

    `by_market_family` alone cannot: a bad `player_prop` number is consistent
    with BOTH -- with inflation if props are where best-of-N lands, and with
    composition if props simply lose everywhere. Comparing the SAME family
    across two venues separates them, because repricing is a venue property and
    a losing family is not.
    """
    from syndicate.features.shared.paper_settlement import settlement_summary

    summary = settlement_summary(orders=[
        # Same family, two venues, opposite results -> repricing, not mix.
        _settled(market="h2h", venue="paper", outcome="lost", pnl_dollars=-10.0),
        _settled(market="h2h", venue="paper:kalshi", outcome="won", pnl_dollars=9.09),
        _settled(market="batter_hits", venue="paper", outcome="won", pnl_dollars=9.09),
    ])
    cross = {b["key"]: b for b in summary["by_venue_family"]}
    assert cross["paper/game_line"]["pnl_dollars"] == -10.0
    assert cross["paper:kalshi/game_line"]["pnl_dollars"] == 9.09
    assert cross["paper/player_prop"]["settled"] == 1
    # The venue that never quoted a prop has no prop bucket at all -- absence,
    # which is the composition claim stated directly rather than as a zero.
    assert "paper:kalshi/player_prop" not in cross


def test_an_unsettled_row_is_pending_in_every_cut_and_moves_no_money():
    from syndicate.features.shared.paper_settlement import settlement_summary

    summary = settlement_summary(orders=[_settled(outcome=None, pnl_dollars=None)])
    assert summary["total"]["settled"] == 0
    for cut in ("by_market_family", "by_sport"):
        assert summary[cut][0]["pending"] == 1
        assert summary[cut][0]["pnl_dollars"] == 0.0
        assert summary[cut][0]["roi_pct"] is None


def test_the_grade_audit_prints_the_facts_and_writes_nothing(monkeypatch, tmp_path, capsys):
    """Game lines returned -16.4% on 79 bets while totals returned +24.03%,
    and game lines are the ones graded by code shipped the same day. A
    consistent sign inversion looks exactly like that and passes every guard
    already in place — the unit tests assert both directions against my own
    convention, and the home/away guard checks source agreement, not whether
    the convention is right.

    So the audit prints ground truth: the bet's own side and line, the margin
    the grader was handed, and the verdict — plus what the verdict would be
    inverted, so the two sit side by side for a person to check."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared import paper_settlement as mod

    request = ledger.OrderRequest(
        position_key="audit-1", selected_date="2026-08-22", venue="paper",
        sport="mlb", event_id="e1", market="spreads", side="home", line=-1.5,
        requested_price=-110.0, requested_stake_dollars=10.0,
        home_team="Houston Astros", away_team="Seattle Mariners",
    )
    ledger.place_order(request, mode=ledger.PAPER)
    mod.settle_orders(
        "2026-08-22",
        resolver=lambda o: {"current_value": 3, "side": "over", "line": 1.5,
                            "is_final": True, "started": True},
    )
    key = ledger.idempotency_key(request)
    before = dict(ledger.find_order(key))

    result = mod.audit_game_line_grades("2026-08-22")
    out = capsys.readouterr().out

    assert result["rows"] == 1
    assert "GRADE_AUDIT" in out
    # From the LEDGER, not a re-derivation. `settled_value` is the margin the
    # grader actually used; recomputing could disagree with what was stored,
    # and then the audit reports a third thing rather than auditing the second.
    assert "margin_used=3" in out
    assert "must_beat=1.5" in out
    assert "our_verdict=won" in out
    # The other reading, side by side. Not a judgement — the point is that a
    # person can see both without re-deriving one.
    assert "if_inverted=lost" in out
    # AN AUDIT THAT WRITES CAN CREATE THE THING IT WAS MEANT TO DETECT.
    assert ledger.find_order(key) == before


def test_the_grade_audit_ignores_props_and_totals(monkeypatch, tmp_path, capsys):
    """Totals grade through the old, long-exercised path and are not what is
    in question."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared import paper_settlement as mod

    for market in ("totals", "batter_hits"):
        request = ledger.OrderRequest(
            position_key=f"skip-{market}", selected_date="2026-08-22", venue="paper",
            sport="mlb", event_id="e2", market=market, side="over", line=8.5,
            requested_price=-110.0, requested_stake_dollars=10.0,
        )
        ledger.place_order(request, mode=ledger.PAPER)
    mod.settle_orders(
        "2026-08-22",
        resolver=lambda o: {"current_value": 9, "is_final": True, "started": True},
    )
    assert mod.audit_game_line_grades("2026-08-22")["rows"] == 0
    assert "rows=0" in capsys.readouterr().out


def test_a_skipped_row_says_WHY(monkeypatch, tmp_path, capsys):
    """MEASURED 2026-08-24T19:29Z: the first version printed `audited=0 of=79`
    and no reason, because every row hit a bare `continue`. A diagnostic that
    refuses silently, in a repo whose whole discipline is named refusals --
    it made the audit itself unauditable."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared import paper_settlement as mod

    request = ledger.OrderRequest(
        position_key="skip-why", selected_date="2026-08-22", venue="paper",
        sport="mlb", event_id="e9", market="spreads", side="home", line=-1.5,
        requested_price=-110.0, requested_stake_dollars=10.0,
    )
    ledger.place_order(request, mode=ledger.PAPER)
    # Graded, but with no settled_value -- the shape the audit must explain
    # rather than silently drop.
    ledger.complete_order(ledger.idempotency_key(request), status=ledger.STATUS_FILLED,
                          fill_price=-110.0, fill_stake_dollars=10.0)
    state = ledger._load()
    for row in state["orders"]:
        if row.get("idempotency_key") == ledger.idempotency_key(request):
            row["outcome"] = "won"
            row["settled_value"] = None
    ledger._persist(state)

    result = mod.audit_game_line_grades("2026-08-22")
    assert result["rows"] == 0
    assert result["skipped"] == {"no_settled_value": 1}
    assert "skipped={'no_settled_value': 1}" in capsys.readouterr().out


def test_the_scoreboard_is_stored_and_printed_so_a_verdict_is_checkable(
    monkeypatch, tmp_path, capsys
):
    """MEASURED 2026-08-24T19:36Z: the grade audit was internally correct on
    all 25 rows and still could not answer whether the sign convention was
    right — because `settled_value` is the MARGIN, and a margin is
    self-consistent under an inversion. It can never falsify one.

    Two raw scores can. Storing them turns the audit from a request that
    someone go and look a game up into a line that is checkable on sight."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared import paper_settlement as mod

    request = ledger.OrderRequest(
        position_key="score-1", selected_date="2026-08-22", venue="paper",
        sport="mlb", event_id="e1", market="h2h", side="home",
        requested_price=-110.0, requested_stake_dollars=10.0,
        home_team="Kansas City Royals", away_team="Detroit Tigers",
    )
    ledger.place_order(request, mode=ledger.PAPER)
    mod.settle_orders(
        "2026-08-22",
        resolver=lambda o: {
            "current_value": 4, "side": "over", "line": 0.0,
            "is_final": True, "started": True,
            "home_score": 7, "away_score": 3,
            "home_name": "Kansas City Royals", "away_name": "Detroit Tigers",
        },
    )

    stored = ledger.find_order(ledger.idempotency_key(request))
    assert stored["home_score"] == 7 and stored["away_score"] == 3
    # The margin must agree with the scoreboard it came from: 7 - 3 = 4.
    assert stored["settled_value"] == stored["home_score"] - stored["away_score"]

    mod.audit_game_line_grades("2026-08-22")
    out = capsys.readouterr().out
    assert "score=Detroit Tigers 3 - 7 Kansas City Royals" in out
    assert "margin_used=4" in out
    assert "our_verdict=won" in out


def test_a_row_with_no_recorded_score_says_so_rather_than_printing_blanks(
    monkeypatch, tmp_path, capsys
):
    """Orders graded before the scoreboard was carried through have none.
    `<not_recorded>` is a named absence; two empty numbers would read as 0-0."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    from syndicate.features.shared import execution_ledger as ledger
    from syndicate.features.shared import paper_settlement as mod

    request = ledger.OrderRequest(
        position_key="score-2", selected_date="2026-08-22", venue="paper",
        sport="mlb", event_id="e2", market="h2h", side="home",
        requested_price=-110.0, requested_stake_dollars=10.0,
    )
    ledger.place_order(request, mode=ledger.PAPER)
    mod.settle_orders(
        "2026-08-22",
        resolver=lambda o: {"current_value": 4, "side": "over", "line": 0.0,
                            "is_final": True, "started": True},
    )
    mod.audit_game_line_grades("2026-08-22")
    assert "score=<not_recorded>" in capsys.readouterr().out


def test_the_audit_announces_rows_the_display_limit_never_examined(capsys, monkeypatch):
    """MEASURED 2026-08-24: `audited=25 of=79 skipped={}` is literally true and
    reads as "54 rows were refused without a reason". They were never examined
    -- `orders[:limit]` stopped first. A bound on coverage that does not
    announce itself makes a partial audit look like a complete one, which is
    the same failure as an unnamed skip in better clothes."""
    from syndicate.features.shared import paper_settlement as mod

    orders = [
        {"selected_date": "2026-08-23", "sport": "mlb", "market": "h2h",
         "outcome": "lost", "settled_value": -1.0, "side": "away",
         "pnl_dollars": -4.0, "line": None}
        for _ in range(9)
    ]
    from syndicate.features.shared import execution_ledger
    monkeypatch.setattr(execution_ledger, "_load", lambda: {"orders": orders})
    mod.audit_game_line_grades("2026-08-23", limit=3)
    summary = [
        line for line in capsys.readouterr().out.splitlines()
        if "GRADE_AUDIT_SUMMARY" in line
    ]
    assert summary, "no summary line"
    assert "audited=3" in summary[0]
    assert "of=9" in summary[0]
    assert "not_examined=6" in summary[0]
    assert "display limit=3" in summary[0]


def test_a_fully_examined_audit_does_not_claim_a_limit(capsys, monkeypatch):
    """`not_examined=0` with no parenthetical -- a limit that never bound is
    not a caveat worth printing."""
    from syndicate.features.shared import paper_settlement as mod

    orders = [
        {"selected_date": "2026-08-23", "sport": "mlb", "market": "h2h",
         "outcome": "won", "settled_value": 2.0, "side": "home",
         "pnl_dollars": 9.0, "line": None}
    ]
    from syndicate.features.shared import execution_ledger
    monkeypatch.setattr(execution_ledger, "_load", lambda: {"orders": orders})
    mod.audit_game_line_grades("2026-08-23", limit=25)
    summary = [
        line for line in capsys.readouterr().out.splitlines()
        if "GRADE_AUDIT_SUMMARY" in line
    ]
    assert "not_examined=0" in summary[0]
    assert "display limit" not in summary[0]
