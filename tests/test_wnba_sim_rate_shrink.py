"""Tests for syndicate/features/shared/wnba_sim_rate_shrink.py (lane `wnba-sim-rate-shrink`).

Reachability first (off != on, read through the board's own ladder reader), then: the new mean is exactly the fitted
estimator, the ladder is SHIFTED not widened, players without 3 prior games are untouched, NBA is untouched, only
games before the slate count, and a missing input names itself."""
from __future__ import annotations

import copy
import csv
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

from syndicate.features.shared import wnba_sim_rate_shrink as R
from syndicate.features.shared.basketball_props_smart_sim import _norm_name_key
from syndicate.features.shared.wnba_projections import _hit_prob_over

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "vendor" / "wnba_betting_repo" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor" / "wnba_betting_repo" / "src"))
from wnba_betting.prop_ladders import build_exact_ladder_payload as BUILD  # noqa: E402

_fit = importlib.util.spec_from_file_location("fit_rate", ROOT / "scripts" / "fit_wnba_sim_rate_shrink.py")
FIT = importlib.util.module_from_spec(_fit)
_fit.loader.exec_module(FIT)  # type: ignore[union-attr]

ON = {R.FLAG: "1"}
W = {"version": 1, "w": {"pts": 0.15, "reb": 0.15, "ast": 0.10, "threes": 0.35}}
PTS = [8] * 10 + [10] * 20 + [12] * 30 + [14] * 20 + [16] * 15 + [20] * 5     # sim mean 12.6
REB = [2] * 30 + [3] * 40 + [5] * 30
AST = [1] * 50 + [2] * 30 + [4] * 20
THR = [0] * 40 + [1] * 40 + [3] * 20


def _root(tmp_path, games=4, factors=W):
    (tmp_path / R.FACTOR_FILE).write_text(json.dumps(factors), encoding="utf-8")
    with (tmp_path / R.HISTORY_FILE).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "TEAM_ABBREVIATION", "PLAYER_NAME", "MIN", "PTS", "REB", "AST", "FG3M"])
        for i in range(games):                       # 30 min, 18 pts, 6 reb, 3 ast, 2 threes per game -> 0.6 pts/min
            w.writerow([f"2026-07-0{i + 1}", "LVA", "A'ja Wilson", 30, 18, 6, 3, 2])
        w.writerow(["2026-07-20", "LVA", "A'ja Wilson", 40, 60, 20, 10, 8])   # the slate itself: must not count
    return tmp_path


def _out():
    pr = [p + r for p, r in zip(PTS, REB)]
    row = {"player_name": "A'ja Wilson", "min_mean": 25.0, "pts_mean": sum(PTS) / 100, "reb_mean": sum(REB) / 100,
           "ast_mean": sum(AST) / 100, "threes_mean": sum(THR) / 100,
           "pra_mean": (sum(PTS) + sum(REB) + sum(AST)) / 100,
           "prop_ladders": {"pts": BUILD(PTS), "reb": BUILD(REB), "ast": BUILD(AST), "threes": BUILD(THR), "pr": BUILD(pr)}}
    return {"date": "2026-07-20", "players": {"home": [row], "away": []}}


def _apply(out, root, env=ON, league="wnba"):
    return R.apply_rate_shrink(out, league_code=league, processed_root=root, build_ladder=BUILD, name_key=_norm_name_key, env=env)


def test_reachability_off_and_on_differ_through_the_boards_reader(tmp_path):
    root = _root(tmp_path)
    off, on = _out(), _out()
    assert _apply(off, root, env={})["reason"] == f"{R.FLAG} off"
    assert _apply(on, root)["applied"] is True
    assert off == _out()
    p_off = _hit_prob_over(off["players"]["home"][0]["prop_ladders"]["pts"]["ladder"], 14.5)
    p_on = _hit_prob_over(on["players"]["home"][0]["prop_ladders"]["pts"]["ladder"], 14.5)
    assert p_on > p_off                    # own rate 0.6/min x 25 min = 15 > sim 12.6: the mean moves up


def test_new_mean_is_the_fitted_estimator_and_the_ladder_is_shifted_not_widened(tmp_path):
    out = _out()
    _apply(out, _root(tmp_path))
    row = out["players"]["home"][0]
    expected = FIT.shrunk_mean(12.6, 25.0, 0.6, 0.15)          # 25 * (0.6 + 0.15 * (0.504 - 0.6)) = 14.64
    assert row["pts_mean"] == pytest.approx(expected)
    assert expected == pytest.approx(14.64)
    assert row["rate_shrink"]["pts"] == pytest.approx(expected - 12.6)
    new = R._values(row["prop_ladders"]["pts"])
    old_sd = math.sqrt(sum((v - 12.6) ** 2 for v in PTS) / 100)
    m = sum(new) / 100
    assert m == pytest.approx(expected, abs=0.6)                # integer shift of a 2.125 delta
    assert math.sqrt(sum((v - m) ** 2 for v in new) / 100) == pytest.approx(old_sd, rel=0.01)
    d_pr = row["rate_shrink"]["pts"] + row["rate_shrink"]["reb"]
    assert sum(R._values(row["prop_ladders"]["pr"])) / 100 == pytest.approx((sum(PTS) + sum(REB)) / 100 + d_pr, abs=0.6)


def test_a_player_without_three_prior_games_is_untouched(tmp_path):
    out = _out()
    s = _apply(out, _root(tmp_path, games=2))
    assert s["applied"] is False
    assert out["players"]["home"][0] == _out()["players"]["home"][0]


def test_only_games_before_the_slate_count(tmp_path):
    out = _out()
    _apply(out, _root(tmp_path))
    # the 2026-07-20 row (1.5 pts/min) would have pulled the own rate above 0.6 if it were read
    assert out["players"]["home"][0]["pts_mean"] == pytest.approx(14.64)


def test_nba_and_missing_inputs_are_left_alone_with_a_reason(tmp_path):
    out = _out()
    assert _apply(out, _root(tmp_path), league="nba")["reason"] == "not wnba" and out == _out()
    empty = tmp_path / "empty"
    empty.mkdir()
    s = _apply(out, empty)
    assert s["applied"] is False and "factor file absent" in s["reason"] and out == _out()
    (empty / R.FACTOR_FILE).write_text(json.dumps(W), encoding="utf-8")
    s = _apply(out, empty)
    assert "history absent" in s["reason"] and out == _out()


@pytest.mark.parametrize("bad,needle", [({"w": {"pts": 2.0}}, "outside"), ({"w": {"pts": "x"}}, "not a number"),
                                        ({"version": 1}, "no 'w' map"), ({"w": {"blk": 0.2}}, "no known stat")])
def test_bad_factor_file_is_refused(tmp_path, bad, needle):
    out = _out()
    s = _apply(out, _root(tmp_path, factors=bad))
    assert s["applied"] is False and needle in s["reason"] and out == _out()
