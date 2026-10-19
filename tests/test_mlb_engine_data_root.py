"""The MLB engine's DATA root is engines/mlb (lane mlb-engine-data-native-p4; frozen from vendor/mlb_bettingv2 at 988fa33d and maintained here).

Pins: the 12 git-tracked engine inputs are tracked there and parse; engine runtime state is ignored there; no
production MLB entry point names the vendored tree in CODE.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE_DATA = ROOT / "engines" / "mlb" / "data"
#: The production MLB entry points that read, write or run the engine (and its inputs' producers).
SWITCHED = ["scripts/run_mlb_daily_sim_job.py", "scripts/sim_input_checklist.py", "scripts/refresh_mlb_statcast_features.py",
            "scripts/fit_mlb_prop_calibration.py", "scripts/build_mlb_pitch_splits_artifact.py",
            "scripts/build_mlb_conditional_mix_artifact.py", "scripts/run_refresh_worker.py"]


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True).stdout.decode("utf-8", "replace")


def test_engine_runtime_state_is_ignored():
    r = subprocess.run(["git", "check-ignore", "-q", "engines/mlb/data/roster_registry/team_108.json"], cwd=ROOT)
    assert r.returncode == 0


def _code_strings(path: Path) -> list[str]:
    """String constants in CODE -- docstrings excluded (comments are not in the AST at all)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


@pytest.mark.parametrize("script", SWITCHED)
def test_production_entry_points_name_no_vendored_mlb_path(script):
    # No exemptions any more: the operator hints were replaced (lane mlb-vendor-deletion-prep).
    hits = [s for s in _code_strings(ROOT / script) if "mlb_bettingv2" in s]
    assert hits == [], hits



def test_tracked_engine_inputs_are_tracked_and_parse():
    tracked = [f for f in _git("ls-files", "engines/mlb/data").split() if f]
    assert len(tracked) >= 12, tracked
    for f in tracked:
        if f.endswith(".json"):
            json.loads((ROOT / f).read_text(encoding="utf-8"))
