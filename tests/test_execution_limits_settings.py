"""User-editable venue caps, and the one thing worth testing: that they BIND.

A settings form is easy to build and easy to build wrong. The wrong version
accepts a number, stores it, echoes it back on the page, and places orders
against the old one -- with no exception, no log line, and a UI that looks like
it worked. This repo has a name for that shape and a standing rule about it
(`model_engine_standard.md`: reachability before correctness, `off != on`).

There are three independent ways this feature could have been inert, and each
gets its own test here:

1. `execution_guard.limits()` read `os.environ` and nothing else, and it runs
   on live-odds-worker. A store only web reads changes nothing.
2. `max_day_orders` was FLAT while `max_day_dollars` was per-venue -- so a
   per-venue orders field would have been stored, displayed, and unenforced.
3. `max_day_dollars_all_venues` is checked BEFORE the per-venue budgets and
   defaults to $150, so raising one venue to $200 moves nothing on its own.

Everything here drives `check_order`, the function that actually refuses, not
the settings module in isolation.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_guard
from syndicate.features.shared import execution_limits_settings as limits_settings


class _Req:
    """The bits of an OrderRequest the guard reads."""

    def __init__(self, *, venue="kalshi", stake=5.0, date="2026-08-26"):
        self.venue = venue
        self.requested_stake_dollars = stake
        self.selected_date = date


@pytest.fixture
def store(monkeypatch):
    """An in-memory settings store, so nothing here touches disk or keyvalue.

    Stubbed at `read_json_file`, NOT at `_read_stored`, deliberately: the
    module's own error handling -- the thing that turns a dead store into a
    `store_error` instead of an exception on a money path -- is inside
    `_read_stored`, and a fixture that replaced it would test around the code
    under test.
    """
    state: dict = {"spent": {"dollars": 0.0, "orders": 0}, "spent_all": None}

    def fake_read_json_file(path):
        if state.get("raise"):
            raise RuntimeError(state["raise"])
        return dict(state.get("payload") or {})

    monkeypatch.setattr(limits_settings, "read_json_file", fake_read_json_file)
    # Live mode, kill switch clear -- so the ONLY thing that can refuse an order
    # in these tests is a cap.
    monkeypatch.setattr(execution_guard, "kill_switch_engaged", lambda: {"engaged": False, "source": "clear"})

    def fake_spent(date, venue=None, mode=None):
        if venue is None and state.get("spent_all") is not None:
            return dict(state["spent_all"])
        return dict(state["spent"])

    monkeypatch.setattr(execution_guard, "spent_today", fake_spent)
    # A stray env var from a developer's `.env` would make these pass or fail on
    # machine configuration rather than on this code.
    for env_name in execution_guard.LIVE_LIMIT_FIELDS.values():
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.delenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", raising=False)
    monkeypatch.delenv("SYNDICATE_EXECUTION_MAX_DAY_ORDERS", raising=False)
    return state


def _set(store, **fields):
    store["payload"] = {**(store.get("payload") or {}), **fields}


def _spent(store, dollars=0.0, orders=0, *, all_venues=None):
    store["spent"] = {"dollars": dollars, "orders": orders}
    store["spent_all"] = all_venues


# ---------------------------------------------------------------------------
# 1. THE STORE REACHES THE GUARD. Reachability before correctness.
# ---------------------------------------------------------------------------


def test_a_saved_venue_cap_actually_refuses_an_order(store):
    """`off != on`, through the function that says no.

    $18 already spent at Kalshi today and a $5 order on the way: $23 fits the
    $50 default. Store $20 and the SAME order must be refused, by name. If this
    passes with the store empty and fails with it set -- or passes both ways --
    the form is scenery.

    (Stakes stay under `max_order_dollars`'s $10 default on purpose: an order
    refused for being too big would make this test green for the wrong reason,
    which is its own entry in this repo's book of ways to be wrong.)
    """
    _spent(store, dollars=18.0)
    before = execution_guard.check_order(_Req(stake=5.0), mode="live")
    assert before["allowed"] is True, before

    _set(store, max_day_dollars_kalshi=20.0)
    after = execution_guard.check_order(_Req(stake=5.0), mode="live")
    assert after["allowed"] is False
    assert after["reason"] == "over_max_day_dollars"
    assert after["limits"]["max_day_dollars"] == 20.0


def test_raising_a_venue_cap_admits_an_order_the_default_refused(store):
    """The other direction, because a cap that only ever tightens is half a
    feature -- and a store read that silently no-ops would pass the tightening
    test whenever the default happened to be lower."""
    _spent(store, dollars=48.0)
    refused = execution_guard.check_order(_Req(stake=5.0), mode="live")
    assert refused["allowed"] is False
    assert refused["reason"] == "over_max_day_dollars"

    _set(store, max_day_dollars_kalshi=200.0)
    allowed = execution_guard.check_order(_Req(stake=5.0), mode="live")
    assert allowed["allowed"] is True, allowed


def test_the_two_venues_do_not_share_a_saved_cap(store):
    """Kalshi and Polymarket are funded separately; one edit must not move the
    other. A single shared key would pass every test above and still be wrong."""
    _spent(store, dollars=18.0)
    _set(store, max_day_dollars_kalshi=20.0, max_day_dollars_polymarket=300.0)
    assert execution_guard.check_order(_Req(venue="kalshi", stake=5.0), mode="live")["allowed"] is False
    assert execution_guard.check_order(_Req(venue="polymarket", stake=5.0), mode="live")["allowed"] is True


# ---------------------------------------------------------------------------
# 2. ORDERS PER DAY IS PER VENUE. It was flat, and a flat field would have
#    accepted "Kalshi 5 a day" and enforced 15.
# ---------------------------------------------------------------------------


def test_a_saved_order_count_is_enforced_per_venue(store, monkeypatch):
    monkeypatch.setattr(
        execution_guard,
        "spent_today",
        lambda date, venue=None, mode=None: {"dollars": 0.0, "orders": 6 if venue == "kalshi" else 0},
    )
    _set(store, max_day_orders_kalshi=5, max_day_orders_polymarket=50, max_day_orders_all_venues=100)

    refused = execution_guard.check_order(_Req(venue="kalshi", stake=1.0), mode="live")
    assert refused["allowed"] is False
    assert refused["reason"] == "over_max_day_orders"
    # Polymarket has its own count and its own spend; it is unaffected.
    assert execution_guard.check_order(_Req(venue="polymarket", stake=1.0), mode="live")["allowed"] is True


def test_the_flat_order_cap_still_answers_for_an_unknown_venue(store):
    """A venue with no per-venue entry must not fall off the map into
    "unlimited". Backward compatibility AND the fail-safe direction."""
    caps = execution_guard.limits("live", venue="somenewbook")
    assert caps["max_day_orders"] == execution_guard._DEFAULT_MAX_DAY_ORDERS
    assert caps["max_day_dollars"] == execution_guard._DEFAULT_MAX_DAY_DOLLARS


# ---------------------------------------------------------------------------
# 3. THE ACCOUNT CEILING BINDS FIRST, and the page must SAY so.
# ---------------------------------------------------------------------------


def test_the_account_ceiling_still_refuses_above_a_raised_venue_cap(store):
    """The inert-form trap in its purest form: both venue budgets raised, the
    ceiling untouched, and nothing can actually reach the new numbers."""
    # $60 spent at Kalshi (inside its raised $200), $148 across BOTH books
    # (outside the untouched $150 ceiling once this $5 lands).
    _spent(store, dollars=60.0, all_venues={"dollars": 148.0, "orders": 4})
    _set(store, max_day_dollars_kalshi=200.0, max_day_dollars_polymarket=200.0)
    result = execution_guard.check_order(_Req(stake=5.0), mode="live")
    assert result["allowed"] is False
    assert result["reason"] == "over_max_day_dollars_all_venues"

    # And raising the ceiling is what actually unblocks it -- the point of
    # making that field editable alongside the two venue budgets.
    _set(store, max_day_dollars_all_venues=500.0)
    assert execution_guard.check_order(_Req(stake=5.0), mode="live")["allowed"] is True


def test_the_view_says_out_loud_when_the_ceiling_makes_a_cap_unreachable(store):
    _set(store, max_day_dollars_kalshi=200.0, max_day_dollars_polymarket=200.0)
    view = limits_settings.resolve_view()
    notes = view["ceiling_notes"]
    assert notes, "a cap nobody can reach must not render as accepted"
    dollars = [n for n in notes if "budgets total" in n["text"]]
    assert dollars and "account ceiling" in dollars[0]["text"]
    # A STORED value caused it, so it is loud.
    assert dollars[0]["severity"] == "warn"

    _set(store, max_day_dollars_all_venues=500.0)
    assert not [n for n in limits_settings.resolve_view()["ceiling_notes"] if "budgets total" in n["text"]]


def test_the_shipped_defaults_do_not_raise_a_permanent_warning(store):
    """15 + 15 books against a 25 account ceiling is the DESIGNED gap -- and a
    warning that fires on a correctly-working system teaches the reader to
    ignore the warning. Still reported, just not as an alarm."""
    notes = limits_settings.resolve_view()["ceiling_notes"]
    orders = [n for n in notes if "order caps total" in n["text"]]
    assert orders, "the ceiling still binds, so it must still be stated"
    assert orders[0]["severity"] == "info"

    # ...and it becomes an alarm the moment an edit is what makes it unreachable.
    _set(store, max_day_orders_kalshi=20)
    loud = [n for n in limits_settings.resolve_view()["ceiling_notes"] if "order caps total" in n["text"]]
    assert loud[0]["severity"] == "warn"


# ---------------------------------------------------------------------------
# Paper stays uncapped -- `execution_guard`'s own stated design.
# ---------------------------------------------------------------------------


def test_a_saved_live_cap_does_not_bind_paper(store):
    """Capping paper would make that ledger evidence about the cap instead of
    about the strategy, which is the reason the paper defaults are inert."""
    _set(store, max_day_dollars_kalshi=20.0, max_order_dollars=1.0)
    paper = execution_guard.limits("paper", venue="kalshi")
    assert paper["max_day_dollars"] == execution_guard._DEFAULT_PAPER_MAX_DAY_DOLLARS
    assert paper["max_order_dollars"] == execution_guard._DEFAULT_PAPER_MAX_ORDER_DOLLARS
    assert execution_guard.check_order(_Req(stake=500.0), mode="paper")["allowed"] is True


# ---------------------------------------------------------------------------
# Refusal, precedence, and the failure modes
# ---------------------------------------------------------------------------


def test_a_bad_value_is_refused_by_name_and_leaves_the_old_one_standing(store, monkeypatch):
    written: dict = {}
    monkeypatch.setattr(limits_settings, "write_json_file", lambda path, payload: written.update(payload))
    _set(store, max_day_dollars_kalshi=75.0)

    _, rejected = limits_settings.update_limits({"max_day_dollars_kalshi": "999999", "max_day_orders_kalshi": "8"})
    assert "max_day_dollars_kalshi" in rejected
    assert "out_of_range" in rejected["max_day_dollars_kalshi"]
    # The good half landed; the bad half did not overwrite the previous value.
    assert written["max_day_orders_kalshi"] == 8
    assert written["max_day_dollars_kalshi"] == 75.0


def test_zero_is_refused_rather_than_read_as_unlimited(store, monkeypatch):
    monkeypatch.setattr(limits_settings, "write_json_file", lambda path, payload: None)
    _, rejected = limits_settings.update_limits({"max_day_dollars_kalshi": "0"})
    assert "max_day_dollars_kalshi" in rejected


def test_an_unknown_field_cannot_read_as_a_successful_save(store, monkeypatch):
    monkeypatch.setattr(limits_settings, "write_json_file", lambda path, payload: None)
    _, rejected = limits_settings.update_limits({"max_day_dollars_binance": "50"})
    assert rejected["max_day_dollars_binance"] == "unknown_field"


def test_a_stored_value_outranks_the_env_var(store, monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI", "60")
    assert execution_guard.limits("live", venue="kalshi")["max_day_dollars"] == 60.0
    _set(store, max_day_dollars_kalshi=25.0)
    assert execution_guard.limits("live", venue="kalshi")["max_day_dollars"] == 25.0


def test_an_unreadable_store_falls_back_rather_than_raising(store):
    """It must not take the guard down. The upward fallback is survivable only
    because `kill_switch_engaged` fails CLOSED on this same store -- asserted
    here so that coupling is not silently removed later."""
    store["raise"] = "keyvalue unreachable"
    caps = execution_guard.limits("live", venue="kalshi")
    assert caps["max_day_dollars"] == 50.0
    assert limits_settings.resolve_view()["store_error"].startswith("RuntimeError")


def test_the_kill_switch_still_fails_closed_on_a_store_failure():
    """The load-bearing half of the sentence above, tested directly against the
    real function rather than the fixture's stub."""
    from syndicate.features.shared import execution_guard as guard

    original = guard.kill_switch_engaged
    assert original({"engaged": True}) if False else True  # no-op, keeps the import honest
    import syndicate.features.shared.refresh_state_store as store_mod

    saved = store_mod.read_json_file_result
    try:
        store_mod.read_json_file_result = lambda path: (_ for _ in ()).throw(RuntimeError("down"))
        assert original()["engaged"] is True
    finally:
        store_mod.read_json_file_result = saved


# ---------------------------------------------------------------------------
# The banner and the guard must not disagree -- a pre-existing defect.
# ---------------------------------------------------------------------------


def test_the_displayed_per_venue_figure_matches_what_is_enforced(store, monkeypatch):
    """MEASURED AS A BUG, not hypothesised. `limits()` returned
    `max_day_dollars_kalshi` straight from the DEFAULT map while resolving the
    enforced `max_day_dollars` from the per-venue env var 25 lines above -- so
    an operator override moved enforcement and the banner kept printing $50.
    """
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI", "37")
    caps = execution_guard.limits("live", venue="kalshi")
    assert caps["max_day_dollars"] == 37.0
    assert caps["max_day_dollars_kalshi"] == 37.0
    assert caps["max_day_dollars_by_venue"]["kalshi"] == 37.0


def test_the_worker_stamp_carries_the_saved_caps(store, monkeypatch):
    """The page reads the WORKER's stamp, not web's env. If the stamp does not
    carry these numbers the banner reports the old caps forever."""
    from syndicate.features.shared import execution_ledger

    written: dict = {}
    monkeypatch.setattr(execution_ledger, "write_json_file", lambda path, payload: written.update(payload), raising=False)
    monkeypatch.setattr(execution_ledger, "execution_mode", lambda: "live")
    monkeypatch.setattr(execution_ledger, "live_execution_armed", lambda: True)
    _set(store, max_day_dollars_kalshi=22.0, max_day_orders_polymarket=3)

    state = execution_ledger.record_execution_state(recorded_by="test")
    caps = state["limits"]
    assert caps["max_day_dollars_kalshi"] == 22.0
    assert caps["max_day_orders_polymarket"] == 3


# ---------------------------------------------------------------------------
# The page. A cap you cannot type is not editable, whatever the store supports.
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from syndicate.app import app

    return app.test_client()


def test_every_editable_cap_has_an_input_on_the_page(client, store):
    """The user asked for Polymarket and Kalshi max-per-day and orders-per-day.
    Asserted against `EDITABLE_FIELDS` rather than a hand-written list, so a
    field added to the store cannot quietly fail to reach the form."""
    body = client.get("/portfolio").get_data(as_text=True)
    for name in limits_settings.EDITABLE_FIELDS:
        assert f'name="{name}"' in body, name
    assert 'action="/portfolio/limits"' in body
    assert 'id="venue-limits"' in body


def test_the_settings_url_a_browser_would_guess_reaches_the_form(client):
    r = client.get("/portfolio/limits")
    assert r.status_code == 303
    assert r.headers["Location"].endswith("/portfolio#venue-limits")


def test_saving_returns_to_the_form_not_the_top_of_the_page(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        limits_settings, "update_limits", lambda changes: seen.update(changes) or ({}, {})
    )
    r = client.post(
        "/portfolio/limits",
        data={"max_day_dollars_kalshi": "75", "max_day_orders_polymarket": "9"},
    )
    assert r.status_code == 303
    assert r.headers["Location"].endswith("/portfolio#venue-limits")
    assert seen == {"max_day_dollars_kalshi": "75", "max_day_orders_polymarket": "9"}


def test_the_api_rejects_by_name_without_pretending_to_save(client, store, monkeypatch):
    monkeypatch.setattr(limits_settings, "write_json_file", lambda path, payload: None)
    r = client.post("/api/portfolio/limits", json={"max_day_dollars_kalshi": "-5"})
    assert r.status_code == 400
    assert "max_day_dollars_kalshi" in r.get_json()["rejected"]


def test_a_partial_success_is_not_reported_as_a_failure(client, store, monkeypatch):
    monkeypatch.setattr(limits_settings, "write_json_file", lambda path, payload: None)
    r = client.post(
        "/api/portfolio/limits",
        json={"max_day_orders_kalshi": "7", "max_day_orders_polymarket": "-1"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["accepted"] == ["max_day_orders_kalshi"]
    assert "max_day_orders_polymarket" in body["rejected"]
