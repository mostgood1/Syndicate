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
