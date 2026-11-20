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
