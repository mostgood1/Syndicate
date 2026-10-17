"""The consistency ladder -- "has hit 30 yds 10/10, 40 yds 8/10" (lane alt-ladder-consistency, user 2026-10-16)."""
from __future__ import annotations

import pytest

from syndicate.features.shared import alt_consistency as ac


def _row(player="Davante Adams", market="Receiving Yards", side="over", line=54.5, values=None, p_market=0.5,
         median_implied=0.5238, event="e1"):
    values = values if values is not None else [61, 72, 38, 55, 90, 47, 66, 52, 31, 80]
    return {"player": player, "market": market, "side": side, "line": line, "event_id": event, "team": "LAR",
            "check": {"form10": {"games": len(values), "values": values}, "p_market": p_market},
            "shop": {"median_implied": median_implied}}


def test_round_number_rungs_count_the_last_ten_like_the_user_said():
    lad = ac.ladder_for(_row())
    labels = [c["label"] for c in lad["rungs"]]
    assert labels == ["40+", "50+", "55+", "60+", "70+", "80+"]          # the line, and round tens around it
    by = {c["label"]: (c["hits"], c["games"]) for c in lad["rungs"]}
    assert by["40+"] == (8, 10) and by["50+"] == (7, 10) and by["60+"] == (5, 10) and by["80+"] == (2, 10)
    assert [c["main"] for c in lad["rungs"]].count(True) == 1


@pytest.mark.parametrize("market,line,expected", [
    ("SOG", 2.5, ["1+", "2+", "3+", "4+", "5+"]),
    ("POINTS", 0.5, ["1+", "2+", "3+"]),
    ("Passing Yards", 200.5, ["150+", "175+", "201+", "225+", "250+"]),      # 200+ merged into the 200.5 line
    ("Receptions", 4.5, ["3+", "4+", "5+", "6+", "7+"]),
])
def test_rungs_by_scale(market, line, expected):
    assert [ac.rung_label(r) for r in ac.generated_rungs(market, line)] == expected


def test_captured_alt_rungs_carry_price_and_a_shrunk_probability():
    rows = [_row(player="Nazem Kadri", market="SOG", line=2.5, values=[2, 3, 3, 2, 4, 4, 2, 2, 2, 0],
                 p_market=0.52, median_implied=0.546)]
    alt = [{"player": "Nazem Kadri", "base_market": "player_shots_on_goal", "side": "over", "line": 3.5,
            "bookmaker": bk, "price": price, "captured_at": "2026-10-16T22:00:00Z"}
           for bk, price in (("draftkings", 200), ("fanduel", 180))]
    [lad] = ac.build({"sport": "nhl", "rows": rows}, alt)
    four = next(c for c in lad["rungs"] if c["label"] == "4+")
    assert four["best_price"] == 200 and four["best_book"] == "draftkings" and four["books"] == 2
    factor = 0.546 / 0.52
    median = sorted([100 / 300, 100 / 280])[1]
    assert four["p_market"] == pytest.approx(median / factor, abs=1e-4)
    assert four["hits"] == 2 and four["p_shrunk"] == pytest.approx((40 * four["p_market"] + 2) / 50, abs=1e-4)
    assert "estimate" in four["p_market_basis"]
    assert lad["alt_captured"] is True


def test_a_one_sided_prop_borrows_the_markets_typical_margin():
    two_sided = _row(player="A", market="batter_hits", line=0.5, p_market=0.6, median_implied=0.63)
    one_sided = _row(player="B", market="batter_hits", line=0.5, p_market=None, median_implied=0.4)
    alt = [{"player": "B", "base_market": "batter_hits", "side": "over", "line": 1.5, "bookmaker": "dk", "price": 300}]
    lads = {lad["player"]: lad for lad in ac.build({"sport": "mlb", "rows": [two_sided, one_sided]}, alt)}
    cell = next(c for c in lads["B"]["rungs"] if c.get("best_price") is not None)
    assert cell["p_market"] == pytest.approx(0.25 / (0.63 / 0.6), abs=1e-4)
    assert "typical" in cell["p_market_basis"]


def test_one_ladder_per_player_and_stat_and_none_without_values():
    rows = [_row(side="over"), _row(side="under"), _row(player="No Form", values=[])]
    lads = ac.build({"sport": "nfl", "rows": rows})
    assert [l["player"] for l in lads] == ["Davante Adams"]


def test_the_ladder_is_context_never_a_pick():
    [lad] = ac.build({"sport": "nfl", "rows": [_row()]})
    flat = repr(lad).lower()
    assert "suggested" not in flat and "edge" not in flat and "pick" not in flat
