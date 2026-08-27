"""Caps, and a kill switch that fails closed."""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_guard as guard
from syndicate.features.shared.execution_ledger import OrderRequest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    for name in (
        "SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS",
        "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS",
        "SYNDICATE_EXECUTION_MAX_DAY_ORDERS",
        "SYNDICATE_EXECUTION_KILL_SWITCH",
        "SYNDICATE_EXECUTION_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _request(stake=10.0, date="2026-08-24"):
    return OrderRequest(
        position_key="p1",
        selected_date=date,
        venue="kalshi",
        sport="mlb",
        event_id="e1",
        market="pitcher_strikeouts",
        side="over",
        requested_price=-110.0,
        requested_stake_dollars=stake,
    )


def test_absent_config_gives_the_restrictive_defaults_in_live_mode():
    caps = guard.limits("live")
    # #284's lesson applied to money: absent is not off.
    assert caps["max_order_dollars"] == 10.0
    assert caps["max_day_dollars"] == 100.0
    assert caps["max_day_orders"] == 15
    assert caps["max_day_dollars_all_venues"] == 150.0
    assert caps["max_day_orders_all_venues"] == 25


def test_paper_defaults_are_inert_so_the_ledger_records_the_strategy():
    caps = guard.limits("paper")
    # The MECHANISM runs on paper; the NUMBERS must not. Capping the paper books
    # at the live limits would truncate the tail of every slate and make the
    # ledger evidence about the cap instead of about the strategy.
    assert caps["max_day_dollars"] >= 1_000_000.0
    assert caps["max_day_orders"] >= 10_000


def test_the_same_env_vars_bind_both_modes(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_ORDERS", "3")
    # One place to configure, two sets of defaults.
    assert guard.limits("paper")["max_day_orders"] == 3
    assert guard.limits("live")["max_day_orders"] == 3


def test_an_unparseable_cap_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "twenty-five")
    assert guard.limits("live")["max_order_dollars"] == 10.0


def test_a_non_positive_cap_is_a_typo_not_a_policy(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "0")
    # 0 would mean "never trade" and -1 would mean nothing at all; neither is a
    # thing anybody types on purpose into a cap.
    assert guard.limits("live")["max_day_dollars"] == 100.0


def test_an_oversized_order_is_refused_by_name():
    result = guard.check_order(
        _request(stake=40.0), mode="live", already={"dollars": 0, "orders": 0}
    )
    assert result["allowed"] is False
    assert result["reason"] == "over_max_order_dollars"


def test_the_day_dollar_cap_counts_what_is_already_spent():
    # stake stays under the $10 per-order cap; it's the ALREADY-SPENT total
    # (kalshi's own $50 day cap) that this order pushes over.
    result = guard.check_order(
        _request(stake=10.0), mode="live", already={"dollars": 45.0, "orders": 2}
    )
    assert result["reason"] == "over_max_day_dollars"


def test_the_day_order_cap_is_separate_from_the_dollar_cap():
    result = guard.check_order(
        _request(stake=1.0), mode="live", already={"dollars": 5.0, "orders": 15}
    )
    # Fifteen $1 bets is nothing in dollars and still fifteen decisions
        # from a model
    # that has settled zero of them.
    assert result["reason"] == "over_max_day_orders"


def test_a_within_limits_order_is_allowed_and_says_what_the_limits_were():
    result = guard.check_order(
        _request(stake=10.0), mode="live", already={"dollars": 0, "orders": 0}
    )
    assert result["allowed"] is True
    # _request()'s default venue is "kalshi" -- its own per-venue cap, not the
    # flat fallback.
    assert result["limits"]["max_day_dollars"] == 50.0


def test_kalshi_and_polymarket_get_their_own_day_dollar_cap():
    """Real funded accounts, not one shared number: Kalshi $50, Polymarket $100."""
    assert guard.limits("live", venue="kalshi")["max_day_dollars"] == 50.0
    assert guard.limits("live", venue="polymarket")["max_day_dollars"] == 100.0


def test_an_unknown_venue_falls_back_to_the_flat_default():
    assert guard.limits("live", venue="prophetx")["max_day_dollars"] == 100.0
    assert guard.limits("live", venue=None)["max_day_dollars"] == 100.0


def test_a_per_venue_override_wins_over_the_flat_one(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "5")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI", "50")
    # The specific knob wins over the flat one for Kalshi...
    assert guard.limits("live", venue="kalshi")["max_day_dollars"] == 50.0
    # ...and the flat one still governs a venue with no specific override.
    assert guard.limits("live", venue="polymarket")["max_day_dollars"] == 5.0


def test_paper_mode_ignores_the_per_venue_dollar_defaults():
    """The MECHANISM (venue resolution) still runs in paper; the NUMBERS stay
    inert, same reasoning as every other paper default in this file."""
    assert guard.limits("paper", venue="kalshi")["max_day_dollars"] >= 1_000_000.0


def test_kalshis_own_cap_refuses_an_order_the_flat_hundred_would_allow():
    """The regression this whole change guards: before per-venue caps, $45
    already spent plus a new $10 Kalshi order would have passed the flat $100
    cap. Kalshi is only funded for $50."""
    result = guard.check_order(
        _request(stake=10.0), mode="live", already={"dollars": 45.0, "orders": 0}
    )
    assert result["allowed"] is False
    assert result["reason"] == "over_max_day_dollars"
    assert result["limits"]["max_day_dollars"] == 50.0


def test_the_all_venues_dollar_cap_defaults_to_the_sum_of_the_per_venue_ones():
    assert guard.limits("live")["max_day_dollars_all_venues"] == 150.0


def test_an_order_within_its_own_venues_cap_can_still_be_refused_account_wide(monkeypatch):
    """Both venues are individually well under their own cap; the ACCOUNT is
    what stops the third order. The combined default equals the sum of the
    two per-venue defaults by construction (see the module comment), so this
    needs its own explicit override to demonstrate -- under plain defaults the
    combined cap can never bind before one venue's own cap already would."""
    from dataclasses import replace

    from syndicate.features.shared import execution_ledger

    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES", "95")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    execution_ledger.place_order(
        replace(_request(stake=45.0, date="2026-08-24"), venue="kalshi"),
        submit=lambda r: {"status": "filled", "fill_stake_dollars": 45.0},
    )
    execution_ledger.place_order(
        replace(_request(stake=45.0, date="2026-08-24"), venue="polymarket", position_key="p2"),
        submit=lambda r: {"status": "filled", "fill_stake_dollars": 45.0},
    )
    # A third order, $10 on Polymarket (own cap $100, well within it at
    # 45+10=55, and under the $10 per-order cap) -- only the $95 account-wide
    # override (90 already spent + 10 = 100) refuses it.
    result = guard.check_order(
        replace(_request(stake=10.0, date="2026-08-24"), venue="polymarket", position_key="p3"),
        mode="live",
    )
    assert result["allowed"] is False
    assert result["reason"] == "over_max_day_dollars_all_venues"


def test_the_all_venues_order_count_cap_is_tighter_than_the_sum_of_the_books():
    """25 across both books against 15 each [USER DECISION 2026-08-25].
    Deliberately less than 15+15, so enabling a second venue cannot silently
    double the account's daily order budget."""
    caps = guard.limits("live")
    assert caps["max_day_orders_all_venues"] == 25
    assert caps["max_day_orders_all_venues"] < caps["max_day_orders"] * 2


def test_twenty_five_orders_across_both_venues_refuses_the_twenty_sixth(monkeypatch):
    from dataclasses import replace

    from syndicate.features.shared import execution_ledger

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    for n in range(25):
        venue = "kalshi" if n % 2 == 0 else "polymarket"
        # A unique position_key per order -- the ledger's idempotency key
        # includes position_key+date+venue, so fifteen identical requests on
        # the same venue would collapse to one write instead of recording all
        # of them.
        execution_ledger.place_order(
            replace(_request(stake=1.0, date="2026-08-24"), venue=venue, position_key=f"p{n}"),
            submit=lambda r: {"status": "filled", "fill_stake_dollars": 1.0},
        )

    result = guard.check_order(
        replace(_request(stake=1.0, date="2026-08-24"), position_key="p15"), mode="live"
    )
    assert result["allowed"] is False
    assert result["reason"] == "over_max_day_orders_all_venues"


def test_the_cap_MECHANISM_runs_in_paper_mode_too(monkeypatch):
    """A cap whose first real exercise is with money on it has not been tested.

    So the check runs on paper and refuses by the same names -- what differs is
    only the default it compares against.
    """
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "25")
    result = guard.check_order(
        _request(stake=999.0), mode="paper", already={"dollars": 0, "orders": 0}
    )
    assert result["allowed"] is False
    assert result["reason"] == "over_max_order_dollars"


def test_the_env_kill_switch_engages():
    import os

    os.environ["SYNDICATE_EXECUTION_KILL_SWITCH"] = "on"
    try:
        assert guard.kill_switch_engaged() == {"engaged": True, "source": "env"}
    finally:
        del os.environ["SYNDICATE_EXECUTION_KILL_SWITCH"]


def test_a_written_flag_engages_and_carries_its_reason():
    from syndicate.features.shared.refresh_state_store import write_json_file

    write_json_file(
        guard.kill_switch_path(),
        {"engaged": True, "reason": "line moved against us", "set_at": "2026-08-24T18:00:00Z"},
    )
    switch = guard.kill_switch_engaged()
    assert switch["engaged"] is True
    assert switch["source"] == "flag"
    assert switch["detail"] == "line moved against us"


def test_no_flag_at_all_is_clear_not_engaged():
    # Fail-closed must not mean "refuse to trade because nobody wrote a file".
    assert guard.kill_switch_engaged() == {"engaged": False, "source": "clear"}


def test_an_unreadable_store_engages_the_kill_switch(monkeypatch):
    def unreadable(_path):
        return (None, False)

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file_result", unreadable
    )
    switch = guard.kill_switch_engaged()
    # "We cannot tell whether someone pulled the switch" must not place bets.
    assert switch == {"engaged": True, "source": "read_failed"}


def test_a_raising_store_engages_the_kill_switch(monkeypatch):
    def boom(_path):
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file_result", boom
    )
    assert guard.kill_switch_engaged()["engaged"] is True


def test_live_mode_refuses_while_the_switch_is_engaged(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_KILL_SWITCH", "1")
    result = guard.check_order(_request(stake=5.0), mode="live", already={"dollars": 0, "orders": 0})
    assert result["reason"] == "kill_switch"


def test_guarded_submit_checks_the_switch_immediately_before_submitting(monkeypatch):
    calls: list[str] = []
    submit = guard.guarded_submit(lambda request: calls.append("sent") or {"status": "filled"})

    assert submit(_request())["status"] == "filled"
    assert calls == ["sent"]

    monkeypatch.setenv("SYNDICATE_EXECUTION_KILL_SWITCH", "1")
    with pytest.raises(guard.KillSwitchEngaged):
        submit(_request())
    # Order four must not be sent because the switch was pulled after order one.
    assert calls == ["sent"]


def test_a_stopped_order_is_recorded_as_failed_not_forgotten(monkeypatch, tmp_path):
    """The reason `guarded_submit` raises rather than returning a refusal."""
    from syndicate.features.shared import execution_ledger

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_KILL_SWITCH", "1")

    record = execution_ledger.place_order(
        _request(), submit=guard.guarded_submit(lambda r: {"status": "filled"})
    )
    # "We did not send it" is a belief, not a fact, until the venue agrees --
    # so reconciliation must still be able to find this order.
    assert record["status"] == "failed"
    assert "kill_switch" in str(record.get("error"))


def test_spent_today_counts_ambiguous_submits_not_just_confirmed_fills(monkeypatch):
    from syndicate.features.shared import execution_ledger

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    def boom(_request):
        raise RuntimeError("connection reset after send")

    execution_ledger.place_order(_request(stake=12.0), submit=boom)

    used = guard.spent_today("2026-08-24")
    # A submit that raised may still have reached the venue. Counting only
    # confirmed fills would let a run of ambiguous submits spend twice.
    assert used == {"dollars": 12.0, "orders": 1}


def test_a_rejected_order_does_not_consume_the_budget(monkeypatch):
    from syndicate.features.shared import execution_ledger

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.delenv("SYNDICATE_EXECUTION_LIVE_ARMED", raising=False)

    # Unarmed -> rejected, which the ledger sets WITHOUT calling the venue.
    record = execution_ledger.place_order(_request(stake=12.0), submit=lambda r: {"status": "filled"})
    assert record["status"] == "rejected"
    assert guard.spent_today("2026-08-24") == {"dollars": 0.0, "orders": 0}


def test_paper_orders_do_not_consume_the_live_budget(monkeypatch):
    from syndicate.features.shared import execution_ledger

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    execution_ledger.place_order(_request(stake=12.0))
    assert guard.spent_today("2026-08-24") == {"dollars": 0.0, "orders": 0}


def test_paper_spend_does_not_consume_the_live_budget_and_vice_versa(monkeypatch):
    from syndicate.features.shared import execution_ledger

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    execution_ledger.place_order(_request(stake=12.0))

    assert guard.spent_today("2026-08-24", mode="paper")["dollars"] == 12.0
    assert guard.spent_today("2026-08-24", mode="live")["dollars"] == 0.0
    # The default is the strictest reading, not a pooled one.
    assert guard.spent_today("2026-08-24")["dollars"] == 0.0


def test_the_two_paper_books_do_not_share_a_budget(monkeypatch):
    from dataclasses import replace

    from syndicate.features.shared import execution_ledger

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    execution_ledger.place_order(replace(_request(stake=12.0), venue="paper"))
    execution_ledger.place_order(replace(_request(stake=7.0), venue="paper:kalshi"))

    # They exist to be compared. A shared budget would make each one's size
    # depend on the other's.
    assert guard.spent_today("2026-08-24", venue="paper", mode="paper")["dollars"] == 12.0
    assert guard.spent_today("2026-08-24", venue="paper:kalshi", mode="paper")["dollars"] == 7.0


def test_the_caps_are_the_ones_the_user_set():
    """[USER DECISION 2026-08-25] Bankroll $1,000, $10 per order, Kalshi $50 and
    Polymarket $100 per day, 15 orders per book and 25 across both.

    Pinned as VALUES because they are policy, not preference: the portfolio
    page renders them as "CAPS IN FORCE" and a drift between what is displayed
    and what binds is the failure `#284` records for env blocks.
    """
    from syndicate.features.shared import execution_guard as guard
    from syndicate.features.shared.portfolio_settings import DEFAULT_BANKROLL_UNITS

    assert DEFAULT_BANKROLL_UNITS == 1000.0
    assert guard._DEFAULT_MAX_ORDER_DOLLARS == 10.0
    assert guard._DEFAULT_MAX_DAY_DOLLARS_BY_VENUE == {"kalshi": 50.0, "polymarket": 100.0}
    assert guard._DEFAULT_MAX_DAY_ORDERS == 15
    assert guard._DEFAULT_MAX_DAY_ORDERS_ALL_VENUES == 25
    # The combined ceiling stays BELOW the sum, so enabling a second venue
    # cannot silently double the account's daily order budget.
    assert guard._DEFAULT_MAX_DAY_ORDERS_ALL_VENUES < guard._DEFAULT_MAX_DAY_ORDERS * 2


def test_an_order_the_venue_REFUSED_does_not_spend_the_budget(tmp_path, monkeypatch):
    """A 4xx IS AN ANSWER.

    Measured 2026-08-25: three Kalshi orders failed `http_404 market_not_found`
    and charged $5.01 and three orders against a $50 / 15-order budget for
    positions that were never opened. The venue replied and refused -- no
    contract exists, no money moved, nothing is pending reconciliation. A cap
    that counts refusals shrinks every time the venue says no.
    """
    from syndicate.features.shared import execution_ledger, execution_guard as guard

    from syndicate.features.shared.refresh_state_store import write_json_file

    path = tmp_path / "l.json"
    monkeypatch.setattr(execution_ledger, "_ledger_path", lambda: path)
    write_json_file(path, {"orders": [
        {"mode": "live", "selected_date": "2026-08-25", "venue": "kalshi",
         "status": "failed", "requested_stake_dollars": 2.30,
         "error": "KalshiAuthError: http_404: market_not_found"},
        {"mode": "live", "selected_date": "2026-08-25", "venue": "kalshi",
         "status": "filled", "fill_stake_dollars": 1.00},
    ]})

    spent = guard.spent_today("2026-08-25", venue="kalshi")
    assert spent["orders"] == 1, spent
    assert round(float(spent["dollars"]), 2) == 1.00, spent


def test_a_venue_that_BROKE_still_spends_because_a_position_may_exist():
    """The opposite direction, and the reason the 4xx test is narrow. "The
    venue broke" and "the venue refused" are opposite facts about whether a
    contract exists, and only one of them is safe to treat as free -- a submit
    that timed out may well have landed, which is why the write-ahead record
    exists at all."""
    from syndicate.features.shared.execution_guard import _is_venue_refusal

    assert _is_venue_refusal({"status": "failed", "error": "http_404: nope"}) is True
    assert _is_venue_refusal({"status": "failed", "error": "http_500: internal"}) is False
    assert _is_venue_refusal({"status": "failed", "error": "ReadTimeout"}) is False
    assert _is_venue_refusal({"status": "failed", "error": ""}) is False
    # A fill is never a refusal, whatever its error field says.
    assert _is_venue_refusal({"status": "filled", "error": "http_404"}) is False
