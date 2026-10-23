"""Hold near settlement [user 2026-10-23, "guard against in game exits where the prop has
been achieved", design "Price guard (fast)", lane live-min-stake-five].

On 10-23 00:07Z a won "over 0.5 blocks" was sold at ~$0.94; it settles at $1. With
`SYNDICATE_EXIT_HOLD_AT_OR_ABOVE_BID` set, a bid at or above it is never sold: the
position is held to settlement. Absent / 0 = the pre-guard behaviour.
"""

from __future__ import annotations

from tests.test_execution_exits import NOW, _market, _position
from syndicate.features.shared import execution_exits as ex

_ENV = "SYNDICATE_EXIT_HOLD_AT_OR_ABOVE_BID"


def _allen_like():
    """YES over 0.5 bought at 0.64 (7 contracts), now bid 0.94 -- the 10-23 sale."""
    p = _position(side="over", fill_price=0.64, requested_price=0.64, fill_stake_dollars=4.48,
                  requested_stake_dollars=4.48, fees_dollars=0.11)
    return p, _market(yes_bid_dollars="0.9400", yes_ask_dollars="0.9600",
                      no_bid_dollars="0.0400", no_ask_dollars="0.0600")


def test_off_the_achieved_prop_is_sold(monkeypatch):
    """Reachability, off side: absent guard sells it under a 0.10 margin, as on 10-23."""
    monkeypatch.delenv(_ENV, raising=False)
    p, m = _allen_like()
    d = ex.evaluate_exit(p, m, margin=0.10, fair_buffer=0.0, now=NOW)
    assert d["rule"] is not None and ex.RULE_TAKE_PROFIT in d["rule"]


def test_on_the_achieved_prop_is_held(monkeypatch):
    """Reachability, on side: the same decision holds to settlement."""
    monkeypatch.setenv(_ENV, "0.90")
    p, m = _allen_like()
    d = ex.evaluate_exit(p, m, margin=0.10, fair_buffer=0.0, now=NOW)
    assert d["rule"] is None and d["reason"] == "near_settlement_hold"
    assert d["bid"] == 0.94 and d["hold_at_or_above"] == 0.90


def test_a_bid_below_the_line_still_takes_profit(monkeypatch):
    """0.80 bid on a 0.64 entry: +0.16 clears a 0.10 margin and is not near settlement."""
    monkeypatch.setenv(_ENV, "0.90")
    p, m = _allen_like()
    m = _market(yes_bid_dollars="0.8000", yes_ask_dollars="0.8200", no_bid_dollars="0.1800", no_ask_dollars="0.2000")
    d = ex.evaluate_exit(p, m, margin=0.10, fair_buffer=0.0, now=NOW)
    assert d["rule"] is not None and ex.RULE_TAKE_PROFIT in d["rule"]


def test_the_no_leg_is_guarded_on_its_own_bid(monkeypatch):
    """A held NO under (the fixture's default) at a 0.97 NO bid is held, not sold."""
    monkeypatch.setenv(_ENV, "0.90")
    d = ex.evaluate_exit(_position(), _market(), margin=0.0, fair_buffer=0.0, now=NOW)
    assert d["reason"] == "near_settlement_hold"


def test_zero_turns_the_guard_off(monkeypatch):
    monkeypatch.setenv(_ENV, "0")
    p, m = _allen_like()
    d = ex.evaluate_exit(p, m, margin=0.10, fair_buffer=0.0, now=NOW)
    assert d["rule"] is not None


def test_an_unusable_value_guards_at_the_default(monkeypatch):
    """Set but unreadable must not mean "sell anything"."""
    for raw in ("abc", "-1", "1.5", "nan"):
        monkeypatch.setenv(_ENV, raw)
        p, m = _allen_like()
        d = ex.evaluate_exit(p, m, margin=0.10, fair_buffer=0.0, now=NOW)
        assert d["reason"] == "near_settlement_hold", raw
