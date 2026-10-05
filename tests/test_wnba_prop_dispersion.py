"""Tests for syndicate/features/shared/wnba_prop_dispersion.py (lane `wnba-prop-dispersion`).

Reachability first (model_engine_standard §4.3): flag off and flag on must produce DIFFERENT ladders, read through the
board's own reader (`wnba_projections._hit_prob_over`), not through this module's fields. Then: NBA never touched, a
missing/broken factor file leaves the ladders untouched with a NAMED reason, and the engine's estimator is exactly
the one the fit scored."""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

from syndicate.features.shared import wnba_prop_dispersion as D
from syndicate.features.shared.wnba_projections import _hit_prob_over

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "vendor" / "wnba_betting_repo" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor" / "wnba_betting_repo" / "src"))
from wnba_betting.prop_ladders import build_exact_ladder_payload as BUILD  # noqa: E402  (the engine's own builder)
_fit = importlib.util.spec_from_file_location("fit_disp", ROOT / "scripts" / "fit_wnba_prop_dispersion.py")
FIT = importlib.util.module_from_spec(_fit)
_fit.loader.exec_module(FIT)  # type: ignore[union-attr]

# Real shape: Marina Mabrey pts on the 2026-07-20 as-of re-run (the 100-draw distribution), built by the vendor builder.
PTS = [3, 4, 5, 6, 6, 7, 7, 7, 7, 8, 8, 8, 9, 9] + [10] * 10 + [11] * 3 + [12] * 5 + [13] * 6 + [14] * 9 + [15] * 14 \
    + [16] * 7 + [17] * 3 + [18] * 6 + [19] * 3 + [20] * 3 + [21] * 5 + [22] * 3 + [23] * 2 + [24] * 3 + [25] * 2 + [32, 44]
REB = [0] * 5 + [1] * 15 + [2] * 20 + [3] * 25 + [4] * 15 + [5] * 10 + [6] * 6 + [8] * 4
FACTORS = {"version": 1, "k": {"pts": 1.35, "reb": 1.25, "pr": 1.5}}


def _out():
    pr = [p + r for p, r in zip(PTS, REB)]
    row = {"player_name": "Marina Mabrey",
           "prop_ladders": {"pts": BUILD(PTS), "reb": BUILD(REB), "pr": BUILD(pr)},
           "prop_distributions": {"pts": {"distribution": BUILD(PTS)["distribution"]}}}
    return {"players": {"home": [row], "away": []}, "score": {}}


def _root(tmp_path, doc=FACTORS):
    (tmp_path / D.FILE_NAME).write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def _sd(payload):
    vals = D._values_from_ladder(payload)
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def test_reachability_off_and_on_differ_through_the_boards_reader(tmp_path):
    root = _root(tmp_path)
    off, on = _out(), _out()
    s_off = D.apply_prop_dispersion(off, league_code="wnba", processed_root=root, build_ladder=BUILD, env={})
    s_on = D.apply_prop_dispersion(on, league_code="wnba", processed_root=root, build_ladder=BUILD, env={D.FLAG: "1"})
    assert s_off["applied"] is False and s_off["reason"] == f"{D.FLAG} unset and factor file not enabled"
    assert s_on["applied"] is True and s_on["ladders"] == 3
    p_off = _hit_prob_over(off["players"]["home"][0]["prop_ladders"]["pts"]["ladder"], 22.5)
    p_on = _hit_prob_over(on["players"]["home"][0]["prop_ladders"]["pts"]["ladder"], 22.5)
    assert p_on > p_off                                # an upper-tail line gains probability when widened
    assert off == _out()                               # OFF leaves the result byte-identical


def test_widens_by_k_and_keeps_the_mean(tmp_path):
    out = _out()
    D.apply_prop_dispersion(out, league_code="wnba", processed_root=_root(tmp_path), build_ladder=BUILD, env={D.FLAG: "on"})
    new = out["players"]["home"][0]
    assert _sd(new["prop_ladders"]["pts"]) == pytest.approx(1.35 * _sd(BUILD(PTS)), rel=0.03)
    assert new["prop_ladders"]["pts"]["mean"] == pytest.approx(sum(PTS) / len(PTS), abs=0.15)
    assert new["prop_dispersion"] == {"pts": 1.35, "reb": 1.25, "pr": 1.5}
    assert new["prop_distributions"]["pts"]["distribution"] == new["prop_ladders"]["pts"]["distribution"]
    assert out["prop_dispersion"]["k"] == {"pts": 1.35, "reb": 1.25, "pr": 1.5}


def test_nba_is_never_touched(tmp_path):
    out = _out()
    s = D.apply_prop_dispersion(out, league_code="nba", processed_root=_root(tmp_path), build_ladder=BUILD, env={D.FLAG: "1"})
    assert s["applied"] is False and s["reason"] == "not wnba"
    assert out == _out()


@pytest.mark.parametrize("doc,needle", [
    (None, "absent"),
    ({"version": 1}, "no 'k' map"),
    ({"k": {"pts": 9.0}}, "outside"),
    ({"k": {"pts": "wide"}}, "not a number"),
    ({"k": {"blk": 1.2}}, "no known ladder key"),
])
def test_unusable_factor_file_leaves_ladders_untouched_with_a_named_reason(tmp_path, doc, needle):
    root = tmp_path if doc is None else _root(tmp_path, doc)
    out = _out()
    s = D.apply_prop_dispersion(out, league_code="wnba", processed_root=root, build_ladder=BUILD, env={D.FLAG: "1"})
    assert s["applied"] is False and needle in s["reason"]
    assert out == _out()


def test_engine_estimator_is_the_one_the_fit_scored():
    mu = sum(PTS) / len(PTS)
    engine = D.dilate_values(PTS, 1.35)
    hist = {}
    for v in engine:
        hist[v] = hist.get(v, 0) + 1
    fitted = FIT.dilate({v: float(PTS.count(v)) for v in set(PTS)}, mu, 1.35)
    assert hist == {k: int(v) for k, v in fitted.items()}


def test_a_ladder_without_a_distribution_is_skipped_not_guessed(tmp_path):
    out = _out()
    out["players"]["home"][0]["prop_ladders"]["pts"].pop("distribution")
    before = copy.deepcopy(out["players"]["home"][0]["prop_ladders"]["pts"])
    D.apply_prop_dispersion(out, league_code="wnba", processed_root=_root(tmp_path), build_ladder=BUILD, env={D.FLAG: "1"})
    assert out["players"]["home"][0]["prop_ladders"]["pts"] == before
    assert "pts" not in out["players"]["home"][0]["prop_dispersion"]


def _disp(out, root, env):
    return D.apply_prop_dispersion(out, league_code="wnba", processed_root=root, build_ladder=BUILD, env=env)


def test_file_switch_turns_it_on_with_the_env_unset(tmp_path):
    """FILE SWITCH (2026-10-05): production enables it by the factor file -- no role restart."""
    out = _out()
    s = _disp(out, _root(tmp_path, doc={**FACTORS, "enabled": True}), env={})
    assert s["applied"] is True and s["switch"] == "file" and out != _out()


def test_env_zero_is_a_kill_switch_over_an_enabled_file(tmp_path):
    out = _out()
    s = _disp(out, _root(tmp_path, doc={**FACTORS, "enabled": True}), env={D.FLAG: "0"})
    assert s["reason"] == f"{D.FLAG} off" and out == _out()


def test_a_stat_left_out_of_the_factor_file_is_untouched(tmp_path):
    """The shipped file leaves reb/ast/threes OUT (prop shape owns those ladders): they must stay byte-identical."""
    out = _out()
    doc = {"version": 1, "k": {"pts": 1.25, "pr": 1.35}, "enabled": True}
    _disp(out, _root(tmp_path, doc=doc), env={})
    assert out["players"]["home"][0]["prop_ladders"]["reb"] == _out()["players"]["home"][0]["prop_ladders"]["reb"]
    assert out["players"]["home"][0]["prop_ladders"]["pts"] != _out()["players"]["home"][0]["prop_ladders"]["pts"]

