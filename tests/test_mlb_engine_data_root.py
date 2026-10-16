"""The MLB engine's DATA root is engines/mlb, not vendor/mlb_bettingv2 (lane mlb-engine-data-native-p4, 2026-10-16).

Pins: the git-tracked engine inputs moved byte-identically; engine runtime state is ignored there as it was under
vendor/; no production MLB entry point names the vendored tree in CODE; and scripts/migrate_mlb_engine_data.py copies
runtime state (and production's rewrite of a tracked input) without ever rolling a newer destination back.
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
VENDOR_DATA = "vendor/mlb_bettingv2/data"
ENGINE_DATA = ROOT / "engines" / "mlb" / "data"
#: The production MLB entry points that read, write or run the engine (and its inputs' producers).
SWITCHED = ["scripts/run_mlb_daily_sim_job.py", "scripts/sim_input_checklist.py", "scripts/refresh_mlb_statcast_features.py",
            "scripts/fit_mlb_prop_calibration.py", "scripts/build_mlb_pitch_splits_artifact.py",
            "scripts/build_mlb_conditional_mix_artifact.py", "scripts/run_refresh_worker.py"]


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True).stdout.decode("utf-8", "replace")


def test_tracked_engine_inputs_moved_byte_identically():
    tracked = [f for f in _git("ls-files", VENDOR_DATA).split() if f]
    if not tracked:
        pytest.skip("vendor tree absent")
    assert len(tracked) >= 12, tracked
    for f in tracked:
        blob = subprocess.run(["git", "show", f"HEAD:{f}"], cwd=ROOT, capture_output=True, check=True).stdout
        moved = ENGINE_DATA / Path(f).relative_to(VENDOR_DATA)
        assert moved.is_file() and moved.read_bytes().replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n"), f


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
    hits = [s for s in _code_strings(ROOT / script) if "mlb_bettingv2" in s
            and not s.lstrip().startswith(("py -3 ", "vendor\\\\mlb_bettingv2\\\\.venv", "  vendor\\mlb_bettingv2\\.venv"))]
    assert hits == [], hits


def _migrate():
    spec = importlib.util.spec_from_file_location("migrate_mlb_engine_data", ROOT / "scripts" / "migrate_mlb_engine_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_migration_copies_runtime_state_and_never_rolls_back(tmp_path, capsys):
    repo = tmp_path / "repo"
    src = repo / "vendor" / "mlb_bettingv2" / "data"
    (src / "tuning").mkdir(parents=True)
    (src / "tuning" / "default.json").write_text('{"v": 1}', encoding="utf-8")         # tracked, unchanged
    (src / "features.json").write_text('{"f": "git"}', encoding="utf-8")              # tracked, rewritten below
    _git("init", "-q", cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed", cwd=repo)
    (src / "features.json").write_text('{"f": "production"}', encoding="utf-8")       # runtime rewrite of a tracked file
    (src / "roster_registry").mkdir()
    (src / "roster_registry" / "team_1.json").write_text('{"t": 1}', encoding="utf-8")  # untracked runtime state
    dst = repo / "engines" / "mlb" / "data"
    (dst / "tuning").mkdir(parents=True)
    (dst / "tuning" / "default.json").write_text('{"v": 1}', encoding="utf-8")        # the git move
    (dst / "features.json").write_text('{"f": "git"}', encoding="utf-8")              # the git move (git's copy)
    m = _migrate()
    assert m.main(["--repo", str(repo)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (dst / "roster_registry" / "team_1.json").read_text(encoding="utf-8") == '{"t": 1}'
    assert (dst / "features.json").read_text(encoding="utf-8") == '{"f": "production"}'
    assert out["runtime state"] == 1 and out["runtime-rewritten tracked input"] == 1
    # After the switch the engine writes engines/mlb itself: a re-run must keep its newer state.
    (dst / "roster_registry" / "team_1.json").write_text('{"t": 2}', encoding="utf-8")
    assert m.main(["--repo", str(repo)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (dst / "roster_registry" / "team_1.json").read_text(encoding="utf-8") == '{"t": 2}'
    assert out["kept newer destination"] == 1
