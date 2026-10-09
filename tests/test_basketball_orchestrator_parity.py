"""Plan P6 parity, the in-repo half: native orchestrator == vendored orchestrator on a synthetic game, same seed.

The gate of record is scripts/basketball_orchestrator_parity.py over REAL production games on the fleet
(deploys.md). This keeps a cheap version in the suite: both leagues, every leaf, with positive controls so a
0 can be trusted. The vendored arm is the pre-P6 bridge read from git (`VENDORED_ARM_COMMIT`); without git
history or the vendor tree the comparison skips, and the static checks still run.
"""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import importlib
import inspect
import random
import subprocess
import symtable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import basketball_orchestrator_parity as par
from syndicate.features.basketball_engine.orchestrator import runtime
from syndicate.features.shared import basketball_props_smart_sim as bps

ROOT = Path(__file__).resolve().parents[1]
PKG = "syndicate.features.basketball_engine.orchestrator"
GENERATED = ("smart_sim", "quarters", "connected_game", "boxscores", "prob_calibration", "prop_ladders", "roster_files", "player_names", "player_priors", "league_config", "advanced_stats_boxscores", "advanced_stats_player_logs", "wnba_teams")


def _game(tmp_path: Path, league: str, seed: int = 11):
    home, away = ("LVA", "NYL") if league == "wnba" else ("BOS", "NYK")
    rows = []
    for t, o in ((home, away), (away, home)):
        for i in range(10):
            rows.append({"player_name": f"{t} P{i}", "team": t, "opponent": o, "pred_min": 34 - 2.5 * i, "mean_pts": 20 - 1.5 * i,
                         "mean_reb": 7 - 0.4 * i, "mean_ast": 5 - 0.3 * i, "mean_threes": 2 - 0.1 * i, "starter": 1 if i < 5 else 0})
    processed = tmp_path / f"{league}_source" / "data" / "processed"
    processed.mkdir(parents=True)
    pace = 98.0 if league == "nba" else 79.5
    qs = bps._simulate_quarters_local(
        processed_root=processed,
        inp=bps.GameInputsLocal(
            date="2026-10-05",
            home=bps.TeamContextLocal(team=home, pace=pace, off_rating=112.0, def_rating=110.0),
            away=bps.TeamContextLocal(team=away, pace=pace - 1.0, off_rating=110.0, def_rating=112.0),
        ),
        league=bps._league_for_code_local(league),
        n_samples=200,
    ).quarters
    kwargs = {
        "date_str": "2026-10-05", "home_tri": home, "away_tri": away, "props_df": pd.DataFrame(rows), "quarters": qs,
        "market_total": None, "market_home_spread": None,
        "cfg": bps._build_smart_sim_config_local(n_sims=5, seed=seed, use_pbp=True, roster_mode="pregame"),
        "excluded_player_keys_by_team": {},
        "pregame_context": {"home_pace": pace, "away_pace": pace - 1.0, "home_b2b": False, "away_b2b": True, "home_injuries_out": 1, "away_injuries_out": 0},
        "processed_root": processed,
    }
    return processed, kwargs


def _run(arm: str, processed: Path, league: str, kwargs: dict):
    np.random.seed(5)
    random.seed(5)
    return par.arm_fn(arm)(processed_root=processed, league_code=league, kwargs=copy.deepcopy(kwargs))


@pytest.fixture(scope="module")
def vendored_available():
    try:
        par.vendored_arm_source()
    except Exception as exc:  # no git history here
        pytest.skip(f"pre-P6 bridge not readable from git: {exc}")
    for pkg in ("nba_betting", "wnba_betting"):
        if not (ROOT / "vendor" / f"{pkg}_repo" / "src" / pkg / "sim" / "smart_sim.py").exists():
            pytest.skip("vendored orchestrator not present")
    return True


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_native_equals_vendored_every_leaf(league, tmp_path, vendored_available):
    processed, kw = _game(tmp_path, league)
    a = _run("vendored", processed, league, kw)
    b = _run("native", processed, league, kw)
    n, diffs = par.leaf_compare(a, b)
    assert n > 5000, n
    assert diffs == []
    assert len(b["players"]["home"]) == 10


def test_positive_controls_the_comparison_can_fail(tmp_path, vendored_available, monkeypatch):
    processed, kw = _game(tmp_path, "nba")
    a = _run("vendored", processed, "nba", kw)
    kw_seed = copy.deepcopy(kw)
    kw_seed["cfg"].seed = 12
    assert par.leaf_compare(a, _run("native", processed, "nba", kw_seed))[1], "a different seed did not show"
    monkeypatch.setattr(runtime, "NBA", dataclasses.replace(runtime.NBA, prune_pregame_pool=True, stamp_team_opponent=True))
    diffs = par.leaf_compare(a, _run("native", processed, "nba", kw))[1]
    assert any("pregame_rotation_pool" in d for d in diffs), diffs


def test_generated_modules_have_no_undefined_globals():
    """The vendored code swallows exceptions in many try/except blocks, so a NameError in the port would be
    SILENT. Every global a function reads must exist in its module (or builtins)."""
    bad = []
    for m in GENERATED + ("runtime", "hooks", "view"):
        mod = importlib.import_module(f"{PKG}.{m}")
        src = Path(mod.__file__).read_text(encoding="utf-8")
        known = set(vars(mod)) | set(dir(builtins))

        def walk(t):
            for s in t.get_symbols():
                implicit_global = s.is_global() and not s.is_declared_global()
                module_free = t.get_type() == "module" and s.is_referenced() and not (s.is_assigned() or s.is_imported())
                if s.is_referenced() and (implicit_global or module_free) and s.get_name() not in known:
                    bad.append(f"{m}: {s.get_name()} in {t.get_name()}")
            for c in t.get_children():
                walk(c)

        walk(symtable.symtable(src, mod.__file__, "exec"))
    assert bad == []


def test_every_call_to_an_orch_function_passes_orch():
    """A missing `orch=` is a TypeError at call time, and inside the vendored try/except blocks it would be
    swallowed into a silent behaviour change."""
    bad = []
    for m in GENERATED:
        mod = importlib.import_module(f"{PKG}.{m}")
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                fn = getattr(mod, n.func.id, None)
                if not callable(fn):
                    continue
                try:
                    params = inspect.signature(inspect.unwrap(fn)).parameters
                except (TypeError, ValueError):
                    continue
                if "orch" in params and params["orch"].kind is inspect.Parameter.KEYWORD_ONLY and not any(k.arg == "orch" for k in n.keywords):
                    bad.append(f"{m}:{n.lineno} {n.func.id}")
    assert bad == []
