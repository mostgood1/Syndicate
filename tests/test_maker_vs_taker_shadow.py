"""maker_vs_taker_shadow: a read-only counterfactual. These pin the rules the pre-registration fixed."""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import maker_vs_taker_shadow as m

SCRIPT = Path(m.__file__)
T0 = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)


def _print(minutes: float, taker_side: str, yes_price: float, count: float = 5.0) -> dict:
    return {"created_time": (T0 + timedelta(minutes=minutes)).isoformat(), "taker_side": taker_side,
            "yes_price_dollars": f"{yes_price:.4f}", "no_price_dollars": f"{1 - yes_price:.4f}",
            "count_fp": str(count)}


def test_no_order_or_credential_path():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    forbidden = ("kalshi_orders", "polymarket_us_orders", "polymarket_us_auth", "execute_portfolio",
                 "novig_orders", "kalshi_auth")
    assert not [mod for mod in imported if any(f in mod for f in forbidden)]
    text = SCRIPT.read_text(encoding="utf-8")
    # every HTTP call is a bare GET: no method override, no request body
    assert "method=" not in text and "data=" not in text and '"POST"' not in text and '"DELETE"' not in text


def test_leg_of_does_not_route_through_the_order_module_for_team_sides():
    assert m.leg_of({"venue": "kalshi", "side": "home", "market": "spreads"}) is None
    assert m.leg_of({"venue": "kalshi", "position_key": "ingame:KXNBATOTAL-X-216:no", "side": "under"}) == "no"
    assert m.leg_of({"venue": "polymarket", "side": "short"}) == "no"


def test_through_needs_a_seller_strictly_below_our_bid():
    end = T0 + timedelta(minutes=60)
    # leg yes, bid 0.44: a taker selling YES is taker_side "no"
    at_bid = [_print(5, "no", 0.44)]
    below = [_print(5, "no", 0.43)]
    buyer = [_print(5, "yes", 0.40)]
    assert m.kalshi_fill(at_bid, "yes", 0.44, True, T0, end, 1, "through") is None
    assert m.kalshi_fill(at_bid, "yes", 0.44, True, T0, end, 1, "touch") is not None
    assert m.kalshi_fill(at_bid, "yes", 0.44, False, T0, end, 1, "touch") is None   # joined the queue
    assert m.kalshi_fill(below, "yes", 0.44, True, T0, end, 1, "through") is not None
    assert m.kalshi_fill(buyer, "yes", 0.44, True, T0, end, 1, "through") is None


def test_through_needs_our_size_and_the_window():
    end = T0 + timedelta(minutes=60)
    small = [_print(5, "no", 0.40, count=2), _print(70, "no", 0.40, count=50)]
    assert m.kalshi_fill(small, "yes", 0.44, True, T0, end, 3, "through") is None
    assert m.kalshi_fill(small + [_print(9, "no", 0.41, count=1)], "yes", 0.44, True, T0, end, 3, "through") is not None


def test_no_leg_reads_the_mirrored_book():
    # leg no: a taker selling NO buys YES; NO printed at 1 - yes
    end = T0 + timedelta(minutes=60)
    assert m.kalshi_fill([_print(5, "yes", 0.62)], "no", 0.40, True, T0, end, 1, "through") is not None
    candle = [{"end_period_ts": int(T0.timestamp()) - 60,
               "yes_bid": {"close_dollars": "0.5800"}, "yes_ask": {"close_dollars": "0.6100"}}]
    assert m.kalshi_quote(candle, T0, "yes") == (0.58, 0.61)
    assert m.kalshi_quote(candle, T0, "no") == (0.39, 0.42)
    assert m.kalshi_quote(candle, T0 - timedelta(minutes=5), "yes") == (None, None)


def test_maker_fee_zero_on_quadratic_and_cent_ceiled_otherwise():
    assert m.kalshi_maker_fee(10, 0.5, "quadratic", 1.0) == 0.0
    assert m.kalshi_maker_fee(10, 0.5, "quadratic_with_maker_fees", 1.0) == 0.05
    assert m.kalshi_taker_fee(10, 0.5, 1.0) == 0.18


def test_split_moves_to_the_median_date_when_discover_is_thin():
    sims = [{"sims": {}, "submitted_at": f"2026-10-{d:02d}T12:00:00Z"} for d in (19, 20, 21, 21, 22, 23)]
    # 10-21 has only 2 of 6 before it; 10-22 is the first date with >= 50% before it
    assert m.apply_split(sims) == "2026-10-22T00:00:00Z"
    assert [s["split"] for s in sims] == ["discover"] * 4 + ["confirm"] * 2
    early = [{"sims": {}, "submitted_at": "2026-09-20T00:00:00Z"}] * 4 + [{"sims": {}, "submitted_at": "2026-10-05T00:00:00Z"}]
    assert m.apply_split(early) == m.SPLIT_AT
