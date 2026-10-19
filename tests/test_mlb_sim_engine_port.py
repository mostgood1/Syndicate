"""The native MLB engine (syndicate/features/mlb/sim_engine).

Frozen from vendor/mlb_bettingv2 at 988fa33d and maintained here (syndicate/features/mlb/FROZEN_FROM_VENDOR.md).
This pins: the live lens imports NO vendored module; every `_ENGINE_FILE` sits under engines/mlb at the old vendored depth; and every
data-root helper resolves under engines/mlb or the repo's own data/, never vendor/.
"""
from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_live_lens_imports_no_vendored_module():
    """In a FRESH interpreter -- this process may already hold vendored modules from other tests."""
    code = (
        "import sys, json\n"
        "before = set(sys.modules)\n"
        "import syndicate.features.mlb.live_lens_port.app_slice\n"
        "import syndicate.features.mlb.sim_engine, pkgutil, importlib\n"
        "import syndicate.features.mlb.sim_engine as S\n"
        "[importlib.import_module(m.name) for m in pkgutil.walk_packages(S.__path__, S.__name__ + '.')]\n"
        "print(json.dumps(sorted(n for n, m in sys.modules.items() if n not in before\n"
        "    and '/vendor/' in (getattr(m, '__file__', '') or '').replace(chr(92), '/'))))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-3000:]
    assert json.loads(r.stdout.strip().splitlines()[-1]) == []


def test_engine_file_sits_under_engines_mlb_at_the_vendored_depth():
    """`_ENGINE_FILE` is the module's path as if its tree sat at engines/mlb (lane mlb-engine-data-native-p4). The file
    need not exist; its PARENTS are the point: the package root is engines/mlb and the repo root is where it was."""
    import syndicate.features.mlb.sim_engine as S

    engine_root = (ROOT / "engines" / "mlb").resolve()
    sites = {}
    for mi in pkgutil.walk_packages(S.__path__, S.__name__ + "."):
        ef = getattr(importlib.import_module(mi.name), "_ENGINE_FILE", None)
        if ef:
            sites[mi.name] = Path(ef).resolve()
    assert len(sites) >= 10, sites  # 13 at generation; a drop means the EDIT rule stopped firing
    for name, ef in sites.items():
        rel = ef.relative_to(engine_root)  # raises if the file is not under engines/mlb
        assert rel.parts[0] == "sim_engine", (name, rel)
        assert ef.parents[len(rel.parts) - 1] == engine_root
        assert ef.parents[len(rel.parts) + 1] == ROOT.resolve()  # the repo root: same depth as vendor/mlb_bettingv2



def test_data_roots_resolve_under_engines_mlb_or_the_repo_data_dir():
    """Each no-argument data-root helper that reads `_ENGINE_FILE` lands in engines/mlb or the Syndicate repo's data/."""
    engine_root = (ROOT / "engines" / "mlb").resolve()
    repo_data = (ROOT / "data").resolve()
    from syndicate.features.mlb.sim_engine import forward_tuning, pitcher_so_model

    assert Path(forward_tuning._ROOT).resolve() == engine_root
    assert Path(pitcher_so_model._DEFAULT_MODEL_PATH).resolve().is_relative_to(engine_root)
    checked = 0
    for mod in ("arsenal", "batted_ball", "conditional_mix", "quality", "statcast_bvp", "roster_registry", "statcast_pitch_splits"):
        m = importlib.import_module(f"syndicate.features.mlb.sim_engine.data.{mod}")
        for name, fn in inspect.getmembers(m, inspect.isfunction):
            if fn.__module__ != m.__name__ or inspect.signature(fn).parameters or "_ENGINE_FILE" not in inspect.getsource(fn):
                continue
            got = Path(str(fn())).resolve()
            assert got.is_relative_to(engine_root) or got.is_relative_to(repo_data), f"{mod}.{name} -> {got}"
            assert "vendor" not in got.parts, f"{mod}.{name} -> {got}"
            checked += 1
    assert checked >= 7, checked
