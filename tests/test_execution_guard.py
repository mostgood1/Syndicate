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


def test_absent_config_gives_the_restrictive_defaults_not_no_limit():
    caps = guard.limits()
    # #284's lesson applied to money: absent is not off.
    assert caps["max_order_dollars"] == 25.0
    assert caps["max_day_dollars"] == 100.0
    assert caps["max_day_orders"] == 10


def test_an_unparseable_cap_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "twenty-five")
    assert guard.limits()["max_order_dollars"] == 25.0


def test_a_non_positive_cap_is_a_typo_not_a_policy(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "0")
    # 0 would mean "never trade" and -1 would mean nothing at all; neither is a
    # thing anybody types on purpose into a cap.
    assert guard.limits()["max_day_dollars"] == 100.0


def test_an_oversized_order_is_refused_by_name():
    result = guard.check_order(_request(stake=40.0), already={"dollars": 0, "orders": 0})
    assert result["allowed"] is False
    assert result["reason"] == "over_max_order_dollars"


def test_the_day_dollar_cap_counts_what_is_already_spent():
    result = guard.check_order(_request(stake=20.0), already={"dollars": 95.0, "orders": 2})
    assert result["reason"] == "over_max_day_dollars"


def test_the_day_order_cap_is_separate_from_the_dollar_cap():
    result = guard.check_order(_request(stake=1.0), already={"dollars": 5.0, "orders": 10})
    # Ten $1 bets is nothing in dollars and still ten decisions from a model
    # that has settled zero of them.
    assert result["reason"] == "over_max_day_orders"


def test_a_within_limits_order_is_allowed_and_says_what_the_limits_were():
    result = guard.check_order(_request(stake=10.0), already={"dollars": 0, "orders": 0})
    assert result["allowed"] is True
    assert result["limits"]["max_day_dollars"] == 100.0


def test_caps_apply_in_paper_mode_too():
    # A cap whose first real exercise is with money on it has not been tested.
    result = guard.check_order(_request(stake=999.0), mode="paper", already={"dollars": 0, "orders": 0})
    assert result["allowed"] is False


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
