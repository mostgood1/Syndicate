"""Tests for syndicate/features/shared/wnba_prop_shape.py (lane `wnba-prop-shape`).

Reachability first (off != on through the board's ladder reader); then: the materialised ladder reproduces the pmf
the fit scored (the engine estimator is the fitted one), the mean is preserved, combos and NBA are untouched, and
an unusable factor file is refused with a named reason."""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

from syndicate.features.shared import wnba_prop_shape as S
from syndicate.features.shared.basketball_props_smart_sim import _norm_name_key
from syndicate.features.shared.wnba_projections import _hit_prob_over

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "vendor" / "wnba_betting_repo" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor" / "wnba_betting_repo" / "src"))
from wnba_betting.prop_ladders import build_exact_ladder_payload as BUILD  # noqa: E402

_fit = importlib.util.spec_from_file_location("fit_shape", ROOT / "scripts" / "fit_wnba_prop_shape.py")
FIT = importlib.util.module_from_spec(_fit)
_fit.loader.exec_module(FIT)  # type: ignore[union-attr]

ON = {S.FLAG: "1"}
FACTORS = {"version": 1, "stats": {"reb": {"k": 1e9, "d_league": 1.189}, "ast": {"k": 64.0, "d_league": 1.089},
                                   "threes": {"k": 1e9, "d_league": 1.131}}}
# A too-peaked sim ladder for rebounds: almost everything at 5-6 (the shape the backtest found wrong).
REB = [4] * 10 + [5] * 40 + [6] * 40 + [7] * 10
RA = [r + 2 for r in REB]


def _out():
    row = {"player_name": "Napheesa Collier", "reb_mean": 5.5, "ast_mean": 2.0, "threes_mean": 1.0,
           "prop_ladders": {"reb": BUILD(REB), "ra": BUILD(RA)}}
    return {"date": "2026-08-10", "players": {"home": [row], "away": []}}


def _root(tmp_path, doc=FACTORS):
    (tmp_path / S.FACTOR_FILE).write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def _apply(out, root, env=ON, league="wnba"):
    return S.apply_prop_shape(out, league_code=league, processed_root=root, build_ladder=BUILD, name_key=_norm_name_key, env=env)


def test_reachability_off_and_on_differ_through_the_boards_reader(tmp_path):
    root = _root(tmp_path)
    off, on = _out(), _out()
    assert _apply(off, root, env={})["reason"] == f"{S.FLAG} off" and off == _out()
    s = _apply(on, root)
    assert s["applied"] is True and s["ladders"] == 1        # only reb has a ladder in this row
    p_off = _hit_prob_over(off["players"]["home"][0]["prop_ladders"]["reb"]["ladder"], 8.5)
    p_on = _hit_prob_over(on["players"]["home"][0]["prop_ladders"]["reb"]["ladder"], 8.5)
    assert p_off == 0.0 and p_on > 0.05                      # the peaked ladder said "never 9+"; the NB does not


def test_materialised_ladder_is_the_fitted_pmf_and_keeps_the_mean(tmp_path):
    out = _out()
    _apply(out, _root(tmp_path))
    lad = out["players"]["home"][0]["prop_ladders"]["reb"]
    pmf = FIT.nb_pmf(5.5, 1.189)                              # league-only dispersion (k = 1e9, no history file)
    assert S.nb_pmf(5.5, 1.189) == pytest.approx(pmf)
    for line in (3.5, 5.5, 7.5, 9.5):
        assert _hit_prob_over(lad["ladder"], line) == pytest.approx(FIT.p_over_pmf(pmf, line), abs=1 / 100 + 1e-9)
    assert lad["mean"] == pytest.approx(5.5, abs=0.05)
    assert out["players"]["home"][0]["prop_shape"] == {"reb": 1.189}


def test_combos_and_nba_are_untouched(tmp_path):
    out = _out()
    _apply(out, _root(tmp_path))
    assert out["players"]["home"][0]["prop_ladders"]["ra"] == BUILD(RA)
    n = _out()
    assert _apply(n, _root(tmp_path), league="nba")["reason"] == "not wnba" and n == _out()


def test_materialise_is_exact_count_and_deterministic():
    pmf = S.nb_pmf(2.3, 1.1)
    a, b = S.materialise(pmf, 500), S.materialise(pmf, 500)
    assert a == b and len(a) == 500
    assert sum(a) / 500 == pytest.approx(2.3, abs=0.02)


@pytest.mark.parametrize("doc,needle", [
    (None, "absent"), ({"version": 1}, "no 'stats' map"), ({"stats": {"reb": {"k": 1}}}, "lacks numeric"),
    ({"stats": {"reb": {"k": 1, "d_league": 9.0}}}, "out of bounds"), ({"stats": {"blk": {"k": 1, "d_league": 1.1}}}, "no known stat")])
def test_unusable_factor_file_is_refused(tmp_path, doc, needle):
    root = tmp_path if doc is None else _root(tmp_path, doc)
    out = _out()
    s = _apply(out, root)
    assert s["applied"] is False and needle in s["reason"] and out == _out()
