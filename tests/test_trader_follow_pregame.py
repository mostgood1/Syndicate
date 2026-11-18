"""The pregame trader-following study's pure parts (lane trader-following-pregame-study)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import trader_follow_pregame as tp  # noqa: E402

START = 1_800_000_000


def _t(ts, price=0.5, side="BUY", idx=0, cid="0xAbC", slug="nba-lal-bos-2026-11-01", size=10.0):
    return {"timestamp": ts, "price": price, "side": side, "outcome_index": idx, "condition_id": cid, "slug": slug,
            "event_slug": slug, "outcome": "Lakers", "size": size}


def test_parse_start_reads_gamma_and_iso_forms():
    assert tp.parse_start({"gameStartTime": "2026-08-20 01:30:00+00"}) == 1787189400
    assert tp.parse_start({"gameStartTime": "2026-08-20T01:30:00Z"}) == 1787189400
    assert tp.parse_start({"gameStartTime": ""}) is None and tp.parse_start(None) is None
    assert tp.parse_start({"gameStartTime": "not a time"}) is None


def test_token_for_picks_the_bought_outcome():
    m = {"clobTokenIds": json.dumps(["111", "222"])}
    assert tp.token_for(m, 0) == "111" and tp.token_for(m, 1) == "222"
    assert tp.token_for(m, 2) is None and tp.token_for(None, 0) is None


def test_only_pregame_in_band_buys_qualify():
    assert tp.qualifies(_t(START - 1), START)
    assert not tp.qualifies(_t(START), START)                    # at kickoff is not pregame
    assert not tp.qualifies(_t(START - 1), None)                 # no start time, no bet
    assert tp.qualifies(_t(START - 1, price=0.10), START) and tp.qualifies(_t(START - 1, price=0.90), START)
    assert not tp.qualifies(_t(START - 1, price=0.95), START) and not tp.qualifies(_t(START - 1, price=0.05), START)
    assert not tp.qualifies(_t(START - 1, side="SELL"), START)
    assert not tp.qualifies(_t(START - 1, slug="btc-updown-5m"), START)


def test_pregame_bets_fold_only_qualifying_buys():
    starts = {"0xabc": START}
    trades = [_t(START - 300, price=0.40, size=10), _t(START - 200, price=0.60, size=30),
              _t(START + 60, price=0.20, size=100),               # in-play: ignored
              _t(START - 100, price=0.97, size=50)]               # out of band: ignored
    bets = tp.pregame_bets("w", trades, starts)
    assert len(bets) == 1
    b = bets[0]
    assert b.first_ts == START - 300 and b.shares == 40 and abs(b.price - 0.55) < 1e-9


def test_follow_price_is_the_latest_midpoint_at_or_before_the_delay_plus_cost():
    hist = [{"t": START - 400, "p": 0.50}, {"t": START - 340, "p": 0.52}, {"t": START - 280, "p": 0.55}]
    first = START - 350
    assert abs(tp.book_follow_price(hist, first, 0, START) - 0.51) < 1e-9          # point at -400 (+0.01)
    assert abs(tp.book_follow_price(hist, first, 60, START) - 0.53) < 1e-9         # point at -340 (+0.01)
    assert abs(tp.book_follow_price(hist, first, 80, START) - 0.56) < 1e-9         # point at -280 (+0.01)


def test_follow_price_never_reads_after_the_delay():
    hist = [{"t": START - 400, "p": 0.50}]
    first = START - 350
    before = tp.book_follow_price(hist, first, 60, START)
    later = hist + [{"t": first + 61, "p": 0.90}, {"t": first + 500, "p": 0.10}]
    assert tp.book_follow_price(later, first, 60, START) == before                 # future points change nothing


def test_follow_price_unfollowable_cases():
    first = START - 1000
    assert tp.book_follow_price([{"t": first - 400, "p": 0.5}], first, 0, START) is None   # older than 300 s
    assert tp.book_follow_price([], first, 0, START) is None
    assert tp.book_follow_price([{"t": START - 50, "p": 0.5}], START - 30, 60, START) is None  # follow lands in-play
    assert tp.book_follow_price([{"t": first, "p": 0.995}], first, 0, START) is None        # price + cost >= 1


def test_verdict_applies_the_registered_rule():
    good = {"60s": {"roi_pct": 4.0, "lo95_pct": 1.0}}
    assert tp.verdict(good, {"60s": {"roi_pct": 1.0}}, 2)["verdict"].startswith("GO")
    assert tp.verdict(good, {"60s": {"roi_pct": 5.0}}, 2)["verdict"] == "NO-GO"
    assert tp.verdict({"60s": {"roi_pct": 4.0, "lo95_pct": -0.1}}, {"60s": {"roi_pct": 1.0}}, 2)["verdict"] == "NO-GO"
    assert tp.verdict(good, {"60s": {"roi_pct": 1.0}}, 0)["verdict"] == "NO-GO"
