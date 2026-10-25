"""scripts/pinnacle_edge_deciles.py -- the Pinnacle and consensus two-way joins, the edge, the age, the deciles."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pinnacle_edge_deciles.py"
_spec = importlib.util.spec_from_file_location("pinnacle_edge_deciles", _PATH)
pe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pe)

T0 = datetime(2026, 10, 22, 18, 0, tzinfo=timezone.utc)


def _q(minutes, selection, line, price, updated_minutes=None, book="pinnacle"):
    at = T0 + timedelta(minutes=minutes)
    upd = None if updated_minutes is None else T0 + timedelta(minutes=updated_minutes)
    return (at, upd, book, selection, line, price)


def _order(**kw):
    base = {"venue": "paper:kalshi", "sport": "ncaaf", "status": "filled", "outcome": "won", "event_id": "e1",
            "side": "home", "market": "spreads", "line": -3.5, "segment": "full", "fill_stake_dollars": 5.0,
            "fill_price": 0.45, "fees_dollars": 0.0, "pnl_dollars": 6.0, "selected_date": "2026-10-22",
            "submitted_at": (T0 + timedelta(minutes=10)).isoformat(), "commence_time": (T0 + timedelta(minutes=60)).isoformat()}
    base.update(kw)
    return base


KEY = pe.quote_key("e1", "spreads", "full", None)


def test_two_way_needs_both_sides_at_our_line_and_ages_by_the_older_leg():
    quotes = {KEY: [_q(0, "home", -3.5, -110, updated_minutes=0), _q(8, "away", 3.5, -110, updated_minutes=8),
                    _q(9, "home", -4.5, -150), _q(30, "home", -3.5, -130), _q(30, "away", 3.5, 110)]}
    j = pe.join_order(_order(), quotes)
    assert abs(j["at_submit"]["fair"] - 0.5) < 1e-9          # -110/-110 de-vigs to 50%
    assert j["at_submit"]["age_s"] == 600.0                    # the home leg is 10 min old at submit
    assert j["at_close"]["fair"] > 0.5                         # the later -130/+110 is the close
    assert pe.join_order(_order(line=-4.5), quotes)["at_submit"] is None  # no two-way at that line


def test_consensus_is_the_median_over_non_venue_books_and_counts_fresh_ones():
    quotes = {KEY: sorted([
        _q(0, "home", -3.5, -110, book="dk"), _q(0, "away", 3.5, -110, book="dk"),            # 0.50, then moves off
        _q(5, "home", -4.5, -120, book="dk"),                                                 # -> dk is STALE at -3.5
        _q(1, "home", -3.5, -130, book="fd"), _q(1, "away", 3.5, 110, book="fd"),             # ~0.55, fresh
        _q(2, "home", -3.5, -150, book="mgm"), _q(2, "away", 3.5, 130, book="mgm"),           # ~0.59, fresh
        _q(3, "home", -3.5, 200, book="kalshi"), _q(3, "away", 3.5, -250, book="kalshi"),     # our venue: excluded
    ], key=lambda r: r[0])}
    j = pe.join_order(_order(), quotes)
    c = j["cons_submit"]
    assert c["books"] == 3 and c["fresh_books"] == 2
    fd = (130 / 230) / (130 / 230 + 100 / 210)
    assert abs(c["fair"] - fd) < 1e-9                          # the median of the three book fairs is fd's
    assert j["at_submit"] is None                              # no Pinnacle in this series


def test_edge_is_fair_minus_price_plus_fee_and_buckets_the_age():
    joined = {"at_submit": {"fair": 0.50, "age_s": 60.0}, "at_close": {"fair": 0.52, "age_s": 0.0},
              "cons_submit": {"fair": 0.48, "books": 5, "fresh_books": 3, "age_s": 1200.0}, "cons_close": None}
    row = pe.order_row(_order(fees_dollars=0.11), joined)        # 5 / 0.45 = 11.11 contracts, fee 0.0099 each
    assert abs(row["cost"] - 0.4599) < 1e-3 and abs(row["edge"] - 4.01) < 0.02 and row["age"] == "<=2m"
    assert abs(row["close_edge"] - 6.01) < 0.02 and row["book"] == "paper" and row["venue"] == "kalshi"
    assert abs(row["cons_edge"] - 2.01) < 0.02 and row["cons_fresh"] == "3+" and row["cons_age"] == ">15m"
    empty = pe.order_row(_order(), {"at_submit": None, "at_close": None, "cons_submit": None, "cons_close": None})
    assert empty["age"] == "absent" and empty["cons_fresh"] == "none" and empty["cons_edge"] is None


def test_eligibility_is_venue_priced_settled_two_way_markets():
    assert pe.eligible(_order())
    assert pe.eligible(_order(sport="nba"))                    # the consensus arm covers NBA
    assert not pe.eligible(_order(sport="soccer", market="h2h"))   # three-way: no two-way de-vig
    assert pe.eligible(_order(sport="soccer", market="totals", side="over"))
    assert not pe.eligible(_order(venue="paper"))              # sportsbook paper, not venue-priced
    assert not pe.eligible(_order(outcome=None))
    assert pe.eligible(_order(venue="paper:polymarket:ladder"))


def test_deciles_split_the_joined_population():
    rows = [{"edge": float(i), "game": f"g{i}", "ret": 0.1, "stake": 1.0, "pnl": 0.1, "close_edge": None,
             "sport": "ncaaf", "book": "paper", "age": "<=2m"} for i in range(100)]
    rows.append({**rows[0], "edge": None, "age": "absent"})
    report = pe.build_report(rows)
    assert len(report["decile_cuts_pp"]) == 9
    assert report["by_decile"]["D01"]["n"] == 10 and report["by_decile"]["D10"]["n"] == 10
    assert report["by_decile"]["none"]["n"] == 1
