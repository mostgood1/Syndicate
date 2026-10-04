"""Unit tests for scripts/measure_nfl_kalshi_forward_clv.py -- side pairing, freshness and the bet rule."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "measure_nfl_kalshi_forward_clv.py"
_spec = importlib.util.spec_from_file_location("nfl_kalshi_clv", _PATH)
kc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kc)  # type: ignore[union-attr]

KO = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)


def _q(book, side, price, at, line=4.5, player="A Player"):
    return {"sport": "nfl", "kind": "prop", "segment": "full", "bookmaker": book, "selection": side, "price": price,
            "snapshot_ts": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "commence_time": KO.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "home_team": "Home", "market": "Receptions", "player_name": player, "line": line}


def _books(at, over=-110, under=-110, books=("a", "b", "c")):
    rows = []
    for b in books:
        rows.append(_q(b, "over", over, at))
        rows.append(_q(b, "under", under, at + timedelta(seconds=1)))   # one second apart, as the ledger writes them
    return rows


def test_sides_written_a_second_apart_still_pair():
    t = KO - timedelta(hours=3)
    idx = kc.BookIndex(_books(t))
    fair, n, age = idx.consensus(kc.key_of(_q("a", "over", -110, t)), t + timedelta(minutes=5))
    assert n == 3 and fair["over"] == pytest.approx(0.5)
    assert age == pytest.approx(5.0)


def test_quotes_older_than_the_lookback_are_not_used():
    t = KO - timedelta(hours=10)
    idx = kc.BookIndex(_books(t))
    fair, n, _ = idx.consensus(kc.key_of(_q("a", "over", -110, t)), t + kc.LOOKBACK + timedelta(minutes=1))
    assert fair is None and n == 0


def test_first_positive_fee_net_ask_becomes_the_bet_and_gets_clv():
    entry = KO - timedelta(hours=4)
    rows = _books(entry - timedelta(minutes=10))                       # consensus 50/50 at entry
    rows += _books(KO - timedelta(minutes=30), over=-150, under=125)    # market moves toward the over by the close
    rows.append(_q("kalshi", "over", 110, entry))                      # +110 ask = 0.476 implied: beats 0.5 after fee
    rows.append(_q("kalshi", "under", -125, entry))
    bets, ctl, drops = kc.measure(rows)
    assert len(bets) == 1 and bets[0]["side"] == "over" and bets[0]["ev_entry"] > 0
    assert bets[0]["fee"] > 0 and bets[0]["clv"] > bets[0]["ev_entry"]   # the close moved toward the bet
    assert {r["side"] for r in ctl} == {"over", "under"}


def test_illiquid_asks_are_excluded():
    entry = KO - timedelta(hours=4)
    rows = _books(entry - timedelta(minutes=10))
    rows.append(_q("kalshi", "over", -1567, entry))                    # empty-book ask, implied 0.94
    rows.append(_q("kalshi", "under", -4900, entry))
    bets, ctl, drops = kc.measure(rows)
    assert not bets and not ctl
    assert drops["illiquid_price"] + drops["illiquid_pair"] == 2
