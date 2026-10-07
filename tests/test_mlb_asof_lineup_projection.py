"""As-of lineup projection (option B) and the StatsAPI-source context (lane mlb-statsapi-asof-rebuild)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "vendor" / "mlb_bettingv2"))

import mlb_asof_lineup_projection as lp  # noqa: E402

VS_R = list(range(1, 10))           # the lineup against right-handers
VS_L = [1, 2, 3, 4, 5, 6, 7, 20, 21]  # two platoon bats against left-handers


def _history():
    h = [{"date": f"2026-06-{d:02d}", "lineup": VS_R, "opp_hand": "R"} for d in range(1, 11)]
    h += [{"date": f"2026-06-{d:02d}", "lineup": VS_L, "opp_hand": "L"} for d in range(11, 17)]
    return sorted(h, key=lambda r: r["date"])


def test_uses_only_games_strictly_before_the_date():
    hist = _history() + [{"date": "2026-06-20", "lineup": [90 + i for i in range(9)], "opp_hand": "R"}]
    assert set(lp.project(hist, "2026-06-20", "R")) == set(VS_R)


def test_picks_the_lineup_for_the_opposing_hand():
    assert set(lp.project(_history(), "2026-06-20", "L")) == set(VS_L)
    assert set(lp.project(_history(), "2026-06-20", "R")) == set(VS_R)


def test_too_few_same_hand_games_falls_back_to_all_recent_games():
    hist = [{"date": f"2026-06-{d:02d}", "lineup": VS_R, "opp_hand": "R"} for d in range(1, 11)]
    hist.append({"date": "2026-06-11", "lineup": VS_L, "opp_hand": "L"})
    assert set(lp.project(hist, "2026-06-20", "L")) == set(VS_R)


def test_roster_filter_replaces_an_unavailable_regular():
    hist = _history()
    roster = set(range(1, 9)) | {20}  # player 9 (vs-R regular) is off the active roster
    out = lp.project(hist, "2026-06-20", "R", roster=roster)
    assert 9 not in out and 20 in out and len(out) == 9


def test_order_follows_mean_batting_slot():
    rev = list(reversed(VS_R))
    hist = [{"date": f"2026-06-{d:02d}", "lineup": rev, "opp_hand": "R"} for d in range(1, 11)]
    assert lp.project(hist, "2026-06-20", "R") == rev


def test_umpire_shrink_matches_production_formula():
    import mlb_asof_roster_build as asof

    class _Mult(SimpleNamespace):
        pass

    ump = SimpleNamespace(source="statsapi_live_feed", home_plate_umpire_id=1, home_plate_umpire_name="x",
                          called_strike_mult=1.08)
    ump.multipliers = lambda: _Mult(called_strike_mult=ump.called_strike_mult)
    out = asof._context_obj(None, None, ump)
    # tools/daily_update.py _apply_umpire_shrink: 1 + s * (old - 1), s = 0.75
    assert abs(out["umpire"]["called_strike_mult"] - (1.0 + 0.75 * 0.08)) < 1e-12
