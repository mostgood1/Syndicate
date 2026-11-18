"""The trader-following backtest's pure parts (lane trader-following-study)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import trader_follow_study as tf  # noqa: E402


def _t(ts, side="BUY", size=10.0, price=0.5, idx=0, slug="nba-lal-bos-2026-11-01", cid="0xabc", outcome="Lakers"):
    return {"timestamp": ts, "side": side, "size": size, "price": price, "outcome_index": idx, "slug": slug,
            "event_slug": slug, "condition_id": cid, "outcome": outcome}


def test_sport_filter_keeps_only_the_sports_we_trade():
    assert tf.sport_of("nba-lal-bos-2026-11-01") == "nba" and tf.sport_of("cfb-ala-lsu") == "cfb"
    assert tf.sport_of("btc-updown-5m-1794964800") is None and tf.sport_of("cs2-nip-lg6") is None
    assert tf.sport_of(None) is None


def test_repeat_buys_fold_into_one_bet_at_the_size_weighted_price():
    bets, two_sided = tf.bets_from_trades("w", [_t(100, size=10, price=0.4), _t(200, size=30, price=0.6),
                                                _t(150, side="SELL", size=5, price=0.7), _t(120, slug="btc-x")])
    assert len(bets) == 1 and not two_sided
    b = bets[0]
    assert b.first_ts == 100 and b.shares == 40 and abs(b.price - 0.55) < 1e-9


def test_buying_both_outcomes_of_a_market_marks_it_two_sided():
    bets, two_sided = tf.bets_from_trades("w", [_t(100, idx=0), _t(110, idx=1, outcome="Celtics")])
    assert len(bets) == 2 and two_sided == {"0xabc"}


def test_settlement_reads_resolved_outcome_prices_only():
    closed = {"closed": True, "outcomePrices": json.dumps(["1", "0"])}
    assert tf.settle(0, closed) is True and tf.settle(1, closed) is False
    assert tf.settle(0, {"closed": False, "outcomePrices": json.dumps(["1", "0"])}) is None
    assert tf.settle(0, {"closed": True, "outcomePrices": json.dumps(["0.5", "0.5"])}) is None  # voided / 50-50
    assert tf.settle(0, None) is None


def test_return_per_dollar():
    assert abs(tf.ret_per_dollar(0.4, True) - 1.5) < 1e-9 and tf.ret_per_dollar(0.4, False) == -1.0


def test_follow_price_is_the_first_taker_buy_of_the_same_outcome_after_the_delay():
    tape = [_t(1000, price=0.50), _t(1030, price=0.52), _t(1065, price=0.55), _t(1070, idx=1, price=0.45),
            _t(1080, side="SELL", price=0.53), _t(1400, price=0.60), _t(4000, price=0.70)]
    assert tf.follow_price(tape, 0, 1000, 0) == 0.50
    assert tf.follow_price(tape, 0, 1000, 60) == 0.55
    assert tf.follow_price(tape, 0, 1000, 300) == 0.60
    assert tf.follow_price(tape, 0, 1000, 600, max_wait=1800) is None   # nothing between 1600 and 2800
    assert tf.follow_price(tape, 1, 1000, 60) == 0.45


def test_clustered_se_counts_events_not_bets():
    one_event = [("e1", 1.0), ("e1", -1.0), ("e1", 1.0), ("e1", -1.0)]
    many = [("e1", 1.0), ("e2", -1.0), ("e3", 1.0), ("e4", -1.0)]
    a, b = tf.clustered(one_event), tf.clustered(many)
    assert a["events"] == 1 and b["events"] == 4 and a["roi_pct"] == b["roi_pct"] == 0.0
    assert tf.clustered([])["n"] == 0


def test_selection_applies_the_pre_registered_rule():
    good = [(f"e{i}", 0.2 if i % 2 else 0.1) for i in range(120)]
    few = good[:50]
    coin = [(f"e{i}", 1.0 if i % 2 else -1.0) for i in range(200)]
    train = {"good": good, "few": few, "coin": coin, "twosided": good, "hf": good}
    chosen = tf.select_wallets(train, {"twosided": {"0xabc"}}, capped={"hf"})
    assert set(chosen) == {"good"}


def test_market_lookup_asks_for_closed_markets():
    """Gamma serves open markets only unless closed=true is passed; without it every bet goes unresolved."""
    seen = []

    class FakeApi:
        def get(self, url, params, cache=True):
            seen.append(list(params))
            return [{"conditionId": c, "closed": True} for k, c in params if k == "condition_ids"]

    out = tf.markets(FakeApi(), [f"0x{i:02x}" for i in range(45)])
    assert len(out) == 45 and len(seen) == 2
    assert all(("closed", "true") in p for p in seen)
