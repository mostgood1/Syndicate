"""Pins S8's pre-registered scoring rules (`.syndicate/findings_2026-11-20_s8_lip_shadow.md`)."""
from __future__ import annotations

import pytest

from scripts import s8_lip_shadow as s8


def test_book_parses_both_formats_best_first():
    yes, no = s8.parse_book({"orderbook_fp": {"yes_dollars": [["0.40", "10"], ["0.42", "5"]],
                                              "no_dollars": [["0.55", "7"]]}})
    assert yes == [(0.42, 5.0), (0.40, 10.0)] and no == [(0.55, 7.0)]
    yes, no = s8.parse_book({"orderbook": {"yes": [[40, 10], [42, 5]], "no": None}})
    assert yes == [(0.42, 5.0), (0.40, 10.0)] and no == []


def test_reference_walks_to_the_level_where_cumulative_reaches_target_over_five():
    levels = [(0.50, 50), (0.49, 100), (0.48, 1000)]
    assert s8.reference_price(levels, target=1000) == 0.48
    assert s8.reference_price(levels, target=500) == 0.49  # 150 >= 100
    assert s8.reference_price([], target=500) is None


def test_orders_worse_than_the_reference_are_discounted_per_tick():
    levels = [(0.50, 100), (0.48, 100)]
    assert s8.others_score(levels, ref=0.50, df=0.5) == pytest.approx(100 + 100 * 0.25)


def test_our_share_and_the_both_sides_target_rule():
    yes = [(0.40, 300)]
    no = [(0.55, 300)]
    sh = s8.snapshot_shares(yes, no, target=350, df=0.5, s=100)
    assert sh["qualifies"] and sh["share_yes"] == pytest.approx(100 / 400) and sh["share_no"] == pytest.approx(0.25)
    # NO side short of target even with our 100: nobody is paid that snapshot
    sh = s8.snapshot_shares(yes, [(0.55, 200)], target=350, df=0.5, s=100)
    assert not sh["qualifies"] and sh["share_yes"] == 0 and sh["share_no"] == 0
    # a side we are not resting on scores 0 but its book still decides qualification
    sh = s8.snapshot_shares(yes, [(0.55, 400)], target=350, df=0.5, s=100, no_on=False)
    assert sh["qualifies"] and sh["share_no"] == 0 and sh["share_yes"] == pytest.approx(0.25)


def test_snapshot_reward_weights_by_gap_and_drops_long_gaps():
    sh = {"qualifies": True, "share_yes": 0.5, "share_no": 0.5}
    assert s8.snapshot_reward(86400.0, 60, sh) == pytest.approx(60 * 0.5)
    assert s8.snapshot_reward(86400.0, 121, sh) == 0.0
    assert s8.snapshot_reward(86400.0, 60, {"qualifies": False, "share_yes": 1, "share_no": 1}) == 0.0


def test_m1_fill_rule():
    assert s8.m1_fills_side({"taker_side": "no", "yes_price_dollars": "0.40"}, "yes", 0.40)
    assert not s8.m1_fills_side({"taker_side": "no", "yes_price_dollars": "0.41"}, "yes", 0.40)
    assert not s8.m1_fills_side({"taker_side": "yes", "yes_price_dollars": "0.30"}, "yes", 0.40)
    assert s8.m1_fills_side({"taker_side": "yes", "yes_price": 46}, "no", 0.55)  # 0.46 >= 1 - 0.55
    assert not s8.m1_fills_side({"taker_side": "yes", "yes_price": 44}, "no", 0.55)


def test_maker_fee_only_on_maker_fee_series():
    assert s8.maker_fee("quadratic", 0.5) == 0.0
    assert s8.maker_fee("quadratic_with_maker_fees", 0.5) == pytest.approx(0.0175 * 0.25)


def test_greedy_book_ranks_by_dollars_per_capital_within_budget():
    entries = [{"usd_day_static": 10, "capital": 100}, {"usd_day_static": 30, "capital": 100},
               {"usd_day_static": 50, "capital": 2400}]
    book = s8.greedy_book(entries, budget=250)
    assert [e["usd_day_static"] for e in book] == [30, 10]


def test_usd_per_day_is_centi_cents_over_program_days():
    p = {"period_reward": 1_000_000, "start_date": "2026-11-20T00:00:00Z", "end_date": "2026-11-22T00:00:00Z"}
    assert s8.program_usd_per_day(p) == pytest.approx(50.0)


def test_a_restart_reuses_only_this_slots_book(tmp_path):
    import datetime as dt
    import json

    def write(name, selected_at):
        (tmp_path / name).write_text(json.dumps({"selected_at": selected_at, "book": []}), encoding="utf-8")

    write("universe_20261120T141218Z.json", "2026-11-20T14:12:18+00:00")  # 8:12 AM CST 11-20
    now = dt.datetime(2026, 11, 20, 15, 30, tzinfo=dt.timezone.utc)      # 9:30 AM CST, same slot
    assert s8.current_slot_universe(tmp_path, now).name == "universe_20261120T141218Z.json"
    later = dt.datetime(2026, 11, 21, 12, 30, tzinfo=dt.timezone.utc)    # 6:30 AM CST 11-21: a new slot
    assert s8.current_slot_universe(tmp_path, later) is None
    early = dt.datetime(2026, 11, 21, 11, 0, tzinfo=dt.timezone.utc)     # 5:00 AM CST 11-21: still 11-20's slot
    assert s8.current_slot_universe(tmp_path, early).name == "universe_20261120T141218Z.json"


MKT = {"target": 350, "df": 0.5, "usd_day_pool": 86400.0, "fee_type": "quadratic"}


def _snap(t, yes=((0.40, 300),), no=((0.55, 300),)):
    return {"t": t, "y": [list(lv) for lv in yes], "n": [list(lv) for lv in no]}


def _iso(t):
    import datetime as dt
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()


def test_score_stream_accrues_reward_per_interval_on_the_previous_book():
    r = s8.score_stream([_snap(1_000_000), _snap(1_000_060), _snap(1_000_120)], [], MKT)
    # each 60 s interval: 86400/day * 60/86400 * 0.5 * (0.25 + 0.25) = 15
    assert r["reward"] == pytest.approx(30.0) and r["fills"] == []


def test_a_trade_through_our_yes_bid_fills_it_and_that_side_stops_earning_for_the_interval():
    trades = [{"created_time": _iso(1_000_030), "taker_side": "no", "yes_price_dollars": "0.40"}]
    deep_yes = ((0.40, 400),)  # still reaches the 350 target without our 100 once we are filled
    r = s8.score_stream([_snap(1_000_000, yes=deep_yes), _snap(1_000_060, yes=deep_yes)], trades, MKT)
    assert len(r["fills"]) == 1 and r["fills"][0]["side"] == "yes" and r["fills"][0]["price"] == 0.40
    assert r["reward"] == pytest.approx(7.5)  # only the NO side earned that interval: 0.5 * 100/400 * 60 s


def test_a_filled_side_whose_book_then_misses_target_disqualifies_the_whole_snapshot():
    trades = [{"created_time": _iso(1_000_030), "taker_side": "no", "yes_price_dollars": "0.40"}]
    r = s8.score_stream([_snap(1_000_000), _snap(1_000_060)], trades, MKT)  # YES book 300 < 350 without us
    assert len(r["fills"]) == 1 and r["reward"] == 0.0


def test_fill_pnl_settled_and_marked():
    f = {"side": "yes", "price": 0.40}
    assert s8.fill_pnl(f, "yes", None, "quadratic", s=100) == (pytest.approx(60.0), True)
    assert s8.fill_pnl(f, "no", None, "quadratic", s=100) == (pytest.approx(-40.0), True)
    v, settled = s8.fill_pnl({"side": "no", "price": 0.55}, None, 0.50, "quadratic", s=100)
    assert v == pytest.approx(100 * (0.50 - 0.55)) and not settled
    v, _ = s8.fill_pnl(f, "yes", None, "quadratic_with_maker_fees", s=100)
    assert v == pytest.approx(100 * (0.60 - 0.0175 * 0.4 * 0.6))


def test_verdict_follows_the_preregistered_table():
    assert s8.verdict(30, 1, 60, final=False) == "PASS"
    assert s8.verdict(30, -5, 60, final=False).startswith("INSUFFICIENT")
    assert s8.verdict(30, -5, 60, final=True).startswith("KILL")
    assert s8.verdict(8, 2, 20, final=False) == "KILL"
    assert s8.verdict(15, -40, -1, final=False) == "KILL"


def test_bootstrap_is_seeded_and_scales_by_days():
    a = s8.bootstrap_ci({"e1": 10.0, "e2": 20.0, "e3": 30.0}, days=2.0)
    assert a == s8.bootstrap_ci({"e1": 10.0, "e2": 20.0, "e3": 30.0}, days=2.0)
    assert 15.0 <= a[0] <= a[1] <= 45.0
