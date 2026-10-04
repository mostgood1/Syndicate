"""Tests for syndicate/features/shared/wnba_sim_minutes_redistribution.py (lane `wnba-minutes-redistribution`).

Reachability first (off != on, read through the board's own ladder reader), then: the estimator conserves the pool's
minutes minus the leak and flattens toward the mean, `freed` grows the flattening, `freed` is computed from the team's
PREVIOUS game strictly before the slate (aliases folded, non-WNBA opponents ignored), the counting-stat means scale with
minutes and ladders SHIFT, NBA and a missing parameter file are untouched with a named reason."""
from __future__ import annotations

import copy
import csv
import json
import sys
from pathlib import Path

import pytest

from syndicate.features.shared import wnba_sim_minutes_redistribution as R
from syndicate.features.shared.basketball_props_smart_sim import _norm_name_key
from syndicate.features.shared.wnba_projections import _hit_prob_over

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "vendor" / "wnba_betting_repo" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor" / "wnba_betting_repo" / "src"))
from wnba_betting.prop_ladders import build_exact_ladder_payload as BUILD  # noqa: E402

ON = {R.FLAG: "1"}
P = {"b0": 0.1, "b1": 0.3, "leak": 2.0}
PTS = [10] * 20 + [14] * 50 + [18] * 30


def _root(tmp_path, params=P, history=True):
    if params is not None:
        (tmp_path / R.PARAM_FILE).write_text(json.dumps({"params": params}), encoding="utf-8")
    if history:
        with (tmp_path / R.HISTORY_FILE).open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["game_id", "date", "TEAM_ABBREVIATION", "PLAYER_NAME", "MIN"])
            w.writerow(["g1", "2026-07-01", "LVA", "Star", 34])
            w.writerow(["g1", "2026-07-01", "LVA", "Sixth", 20])
            w.writerow(["g1", "2026-07-01", "LVA", "Gone Guard", 30])
            w.writerow(["g2", "2026-07-03", "LV", "Star", 36])          # ESPN alias -> LVA; the previous game
            w.writerow(["g2", "2026-07-03", "LV", "Gone Guard", 26])    # played it, absent from today's pool
            w.writerow(["g2", "2026-07-03", "LV", "Benchwarmer", 0])    # did not play -> not freed
            w.writerow(["x1", "2026-07-04", "JPN", "Gone Guard", 40])   # exhibition opponent row: ignored
            w.writerow(["g3", "2026-07-20", "LVA", "Gone Guard", 40])   # the slate itself: must not count
    return tmp_path


def _out():
    def row(name, mins, pts):
        return {"player_name": name, "team": "LVA", "min_mean": mins, "pts_mean": pts, "reb_mean": mins / 5,
                "ast_mean": mins / 10, "threes_mean": 1.0, "pra_mean": pts + mins / 5 + mins / 10,
                "prop_ladders": {"pts": BUILD(PTS)}}
    rows = [row("Star", 36.0, sum(PTS) / 100), row("Sixth", 20.0, 8.0), row("Deep Bench", 4.0, 1.5)]
    rows += [row(f"Filler {i}", 140.0 / 7, 6.0) for i in range(7)]
    return {"date": "2026-07-20", "home": "LVA", "away": "SEA", "players": {"home": rows, "away": []}}


def _apply(out, root, env=ON, league="wnba"):
    return R.apply_minutes_redistribution(out, league_code=league, processed_root=root, build_ladder=BUILD,
                                          name_key=_norm_name_key, env=env)


def test_reachability_off_is_untouched_and_on_moves_the_board_probability(tmp_path):
    root = _root(tmp_path)
    off, on = _out(), _out()
    s_off = _apply(off, root, env={})
    s_on = _apply(on, root)
    assert s_off["applied"] is False and R.FLAG in s_off["reason"]
    assert off == _out()
    assert s_on["applied"] is True
    p_off = _hit_prob_over(off["players"]["home"][0]["prop_ladders"]["pts"]["ladder"], 16.5)
    p_on = _hit_prob_over(on["players"]["home"][0]["prop_ladders"]["pts"]["ladder"], 16.5)
    assert p_off is not None and p_on is not None and p_on < p_off                     # the star loses minutes -> her points ladder moves down


def test_reshare_conserves_minutes_minus_leak_and_flattens():
    sims = [36.0, 20.0, 4.0] + [20.0] * 7
    new = R.reshare(sims, 0.0, P)
    assert sum(new) == pytest.approx(sum(sims) - P["leak"])
    assert new[0] < sims[0] and new[2] > sims[2]
    assert R.reshare(sims, 0.0, {"b0": 0.0, "b1": 0.0, "leak": 0.0}) == pytest.approx(sims)


def test_freed_minutes_grow_the_flattening():
    sims = [36.0, 20.0, 4.0] + [20.0] * 7
    calm, freed = R.reshare(sims, 0.0, P), R.reshare(sims, 30.0, P)
    assert freed[0] < calm[0] and freed[2] > calm[2]


def test_freed_is_the_previous_games_absent_players_strictly_before_the_slate(tmp_path):
    root = _root(tmp_path)
    pool = {_norm_name_key(n).upper() for n in ("Star", "Sixth")}
    freed, why = R.freed_minutes(root, "2026-07-20", "LVA", pool, _norm_name_key)
    assert why == "ok"
    assert freed == pytest.approx((30 + 26) / 2)   # Gone Guard's as-of mean; slate, exhibition and DNP rows excluded


def test_a_sub_half_unit_change_still_moves_a_low_count_ladder():
    """Discriminating: the shift-by-delta convention (round_half_up(v + d)) left a threes ladder byte-identical for a
    -0.3 mean change (measured 2026-10-04, Brier delta exactly [0.0, 0.0]); scaling must move it."""
    thr = [0] * 40 + [1] * 40 + [2] * 15 + [3] * 5                  # mean 0.85
    k = 0.65                                                       # -0.30 threes
    assert [int(v + (0.85 * (k - 1)) + 0.5) for v in thr] == thr   # the old rule: nothing moves
    new = R.scale_values(thr, k)
    assert sum(new) / len(new) == pytest.approx(0.85 * k, abs=0.01)
    assert _hit_prob_over(BUILD(new)["ladder"], 0.5) < _hit_prob_over(BUILD(thr)["ladder"], 0.5)


def test_means_and_ladders_scale_with_minutes(tmp_path):
    root = _root(tmp_path)
    out = _out()
    before = copy.deepcopy(out["players"]["home"][0])
    _apply(out, root)
    after = out["players"]["home"][0]
    k = after["min_mean"] / before["min_mean"]
    assert after["pts_mean"] == pytest.approx(before["pts_mean"] * k)
    assert after["reb_mean"] == pytest.approx(before["reb_mean"] * k)
    d = after["pts_mean"] - before["pts_mean"]
    assert after["pra_mean"] == pytest.approx(before["pra_mean"] + d + (after["reb_mean"] - before["reb_mean"])
                                              + (after["ast_mean"] - before["ast_mean"]))
    lb, la = before["prop_ladders"]["pts"], after["prop_ladders"]["pts"]
    assert la["mean"] == pytest.approx(lb["mean"] * k, abs=0.01)            # the ladder mean follows the minutes
    assert la["maxTotal"] < lb["maxTotal"]


def test_nba_and_missing_inputs_are_untouched_with_a_reason(tmp_path):
    out = _out()
    assert _apply(out, _root(tmp_path), league="nba")["reason"] == "not wnba"
    assert out == _out()
    s = _apply(out, _root(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, params=None, history=False))
    assert s["applied"] is False and "parameter file absent" in s["reason"]
    assert out == _out()


def test_out_of_range_parameters_are_refused(tmp_path):
    out = _out()
    s = _apply(out, _root(tmp_path, params={"b0": 5.0, "b1": 0.0, "leak": 0.0}))
    assert s["applied"] is False and "outside" in s["reason"]
    assert out == _out()


def test_bench_only_leaves_every_cut_player_exactly_as_simulated(tmp_path):
    """The full re-share hurt the regulars' props (2026-10-04); bench-only must not touch anyone it would cut -- not
    even min_mean, which the rate shrink divides by -- and must still scale the players it gives minutes to."""
    root = _root(tmp_path, params={**P, "bench_only": True})
    out = _out()
    before = copy.deepcopy(out)
    s = _apply(out, root)
    star_b, star_a = before["players"]["home"][0], out["players"]["home"][0]
    bench_b, bench_a = before["players"]["home"][2], out["players"]["home"][2]
    assert star_a == star_b
    assert bench_a["min_mean"] > bench_b["min_mean"]
    assert bench_a["pts_mean"] == pytest.approx(bench_b["pts_mean"] * bench_a["min_mean"] / bench_b["min_mean"])
    assert 0 < s["players"] < len(out["players"]["home"])


def test_bench_only_must_be_a_boolean(tmp_path):
    out = _out()
    s = _apply(out, _root(tmp_path, params={**P, "bench_only": "yes"}))
    assert s["applied"] is False and "bench_only" in s["reason"]
