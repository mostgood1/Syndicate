"""Two venues placing live, and the cap that keeps that from doubling exposure.

CONTEXT. Live execution reads `SYNDICATE_EXECUTION_VENUE` and places today's
venue-restricted plan. It read that variable as ONE STRING, so exactly one
venue could ever transact: Kalshi held the slot, and Polymarket US could not
place an order no matter how complete its order path was (auth verified live
2026-08-24T20:18Z, `POLYMARKET_US_AUTH ok=True`; submitter, resolver and ticker
stamp all wired).

THE CAP IS THE REASON THIS NEEDED A TEST AND NOT JUST AN EDIT.
`execution_guard.spent_today` filters on `order.venue`, deliberately -- one
venue's budget must not be consumed by another's. That makes `max_day_dollars`
a PER-VENUE number, so with a $40 day cap one live venue risks $40 and two risk
$80. Nobody edits a cap and total exposure doubles. `max_day_dollars_all_venues`
defaults to the same figure precisely so adding a venue splits one budget
rather than duplicating it, and raising it is an explicit act.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_guard


class _Request:
    def __init__(self, *, venue: str, stake: float, date: str = "2026-08-24") -> None:
        self.venue = venue
        self.requested_stake_dollars = stake
        self.selected_date = date


@pytest.fixture(autouse=True)
def _live_and_unswitched(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setattr(
        execution_guard, "kill_switch_engaged", lambda: {"engaged": False, "source": "clear"}
    )


def _with_spend(monkeypatch, *, per_venue: float, all_venues: float) -> None:
    """Stub the ledger read so the caps are tested, not the ledger."""

    def spent_today(selected_date, *, venue=None, mode=None):
        dollars = per_venue if venue else all_venues
        return {"dollars": dollars, "orders": 1}

    monkeypatch.setattr(execution_guard, "spent_today", spent_today)


def test_the_account_wide_cap_DEFAULTS_to_the_per_venue_day_cap(monkeypatch):
    """Adding a second venue must not raise total exposure by itself."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "40")
    monkeypatch.delenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES", raising=False)
    caps = execution_guard.limits("live")
    assert caps["max_day_dollars_all_venues"] == 40.0
    assert caps["max_day_dollars"] == 40.0


def test_a_second_venue_is_STOPPED_by_the_account_cap_the_first_venue_filled(monkeypatch):
    """Kalshi spent the whole day budget; Polymarket's own budget is untouched.

    This is the exact case the per-venue cap alone gets wrong: polymarket has
    spent $0 of its own $40, so `over_max_day_dollars` never fires, and without
    the account-wide check the day's real exposure would reach $80.
    """
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "40")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "10")
    monkeypatch.delenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES", raising=False)
    _with_spend(monkeypatch, per_venue=0.0, all_venues=39.0)

    verdict = execution_guard.check_order(_Request(venue="polymarket", stake=5.0), mode="live")

    assert verdict["allowed"] is False
    # A DISTINCT reason: "this venue is done" and "the account is done" call
    # for different responses and must never share a name.
    assert verdict["reason"] == "over_max_day_dollars_all_venues"
    assert verdict["already_all_venues"]["dollars"] == 39.0


def test_raising_the_account_cap_EXPLICITLY_lets_both_venues_run(monkeypatch):
    """Separately funded balances are a real reason to raise it -- on purpose."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "40")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "10")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES", "80")
    _with_spend(monkeypatch, per_venue=0.0, all_venues=39.0)

    verdict = execution_guard.check_order(_Request(venue="polymarket", stake=5.0), mode="live")

    assert verdict["allowed"] is True, verdict


def test_the_account_cap_never_reads_the_callers_PER_VENUE_already(monkeypatch):
    """`already` is computed per venue by the caller. Reusing it here would
    make the account-wide cap read one venue's spend and agree with itself."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "40")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "10")
    _with_spend(monkeypatch, per_venue=0.0, all_venues=39.0)

    verdict = execution_guard.check_order(
        _Request(venue="polymarket", stake=5.0),
        mode="live",
        already={"dollars": 0.0, "orders": 0},
    )

    assert verdict["reason"] == "over_max_day_dollars_all_venues", (
        "the account-wide cap was satisfied by the caller's per-venue figure"
    )


def test_the_per_venue_cap_still_fires_on_its_own(monkeypatch):
    """The new check must not have replaced the old one."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "40")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "10")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES", "1000")
    _with_spend(monkeypatch, per_venue=39.0, all_venues=39.0)

    verdict = execution_guard.check_order(_Request(venue="kalshi", stake=5.0), mode="live")

    assert verdict["allowed"] is False
    assert verdict["reason"] == "over_max_day_dollars"


# ---------------------------------------------------------------------------
# The venue list itself.
# ---------------------------------------------------------------------------


def _parse_venues(raw: str | None) -> list:
    """The worker's own parse, isolated. Kept in step with
    `run_live_odds_refresh_worker._run_execution_tick`."""
    venues = [part.strip().lower() for part in str(raw or "").split(",") if part.strip()]
    return venues or [None]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("kalshi", ["kalshi"]),
        ("kalshi,polymarket", ["kalshi", "polymarket"]),
        (" Kalshi , Polymarket ", ["kalshi", "polymarket"]),
        ("kalshi,,polymarket", ["kalshi", "polymarket"]),
        ("", [None]),
        (None, [None]),
    ],
)
def test_the_venue_list_parses_without_changing_what_one_venue_MEANT(raw, expected):
    """One venue is a list of one, so nothing already configured moves."""
    assert _parse_venues(raw) == expected


def test_the_worker_runs_execution_ONCE_PER_VENUE(monkeypatch):
    """Each venue must read its OWN venue-restricted plan.

    Pooling them into a single call would hand one venue another's positions --
    the `LIVE_WITHOUT_VENUE_SCOPE` category error, arrived at from a new door.
    """
    import scripts.run_live_odds_refresh_worker as worker

    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi,polymarket")
    monkeypatch.setattr(worker, "_LAST_EXECUTION_AT", None, raising=False)

    calls: list = []

    def fake_run_execution(date, *, venue_scope=None):
        calls.append(venue_scope)
        return {"status": "ok", "placed": 0, "mode": "live", "venue": venue_scope}

    monkeypatch.setattr("pipeline.execute_portfolio.execution_enabled", lambda: True)
    monkeypatch.setattr("pipeline.execute_portfolio.run_execution", fake_run_execution)
    monkeypatch.setattr(
        "syndicate.features.shared.execution_ledger.record_execution_state",
        lambda **_: None,
    )

    worker._run_execution_tick()

    assert calls == ["kalshi", "polymarket"], (
        f"expected one scoped call per venue, got {calls}"
    )


# ---------------------------------------------------------------------------
# The key-space diagnostic.
# ---------------------------------------------------------------------------


def test_the_reprice_reports_BOTH_SIDES_of_an_unmatched_join():
    """`stamped=0` alone cannot distinguish a key-space mismatch from a venue
    that genuinely lists nothing. Recording the board's key beside the keys the
    sources offered is what turns that into a reading."""
    from syndicate.features.shared.venue_quote_fanin import apply_venue_quotes
    from syndicate.features.shared.venue_quote_adapters import Quote, quote_key

    # The venue publishes a team's SHORT name; the board asks by full name.
    offered = quote_key("mlb", "h2h", "Padres", None)
    collected = {
        "mlb": {
            "quotes": {
                offered: Quote(
                    key=offered,
                    source="polymarket_us",
                    sport="mlb",
                    market="h2h",
                    side="Padres",
                    probability=0.55,
                    american=-122,
                    line=None,
                    fetched_at=1.0,
                )
            },
            "ceiling_seconds": 21600,
            "by_source": {},
        }
    }
    rows = [{"sport": "mlb", "market": "h2h", "side": "San Diego Padres", "line": None}]

    result = apply_venue_quotes(rows, "2026-08-24", collected_by_sport=collected)

    assert result["stamped"] == 0
    assert result["unmatched_by_sport"] == {"mlb": 1}
    assert result["unmatched_sample"] == ["mlb|h2h|san diego padres"]
    # And what the source actually had, so the mismatch is visible side by side.
    assert result["offered_sample"]["mlb"]["polymarket_us"] == ["mlb|h2h|padres"]


def test_the_unmatched_sample_is_BOUNDED():
    """A diagnostic that prints thousands of keys stops being read."""
    from syndicate.features.shared.venue_quote_fanin import (
        _UNMATCHED_SAMPLE_LIMIT,
        apply_venue_quotes,
    )

    rows = [
        {"sport": "mlb", "market": "h2h", "side": f"team-{index}", "line": None}
        for index in range(50)
    ]
    collected = {"mlb": {"quotes": {}, "ceiling_seconds": 21600, "by_source": {}}}

    result = apply_venue_quotes(rows, "2026-08-24", collected_by_sport=collected)

    assert result["unmatched_by_sport"] == {"mlb": 50}, "the COUNT must be complete"
    assert len(result["unmatched_sample"]) == _UNMATCHED_SAMPLE_LIMIT, (
        "the SAMPLE must be bounded"
    )
