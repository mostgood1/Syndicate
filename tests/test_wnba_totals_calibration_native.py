"""The WNBA totals calibration builder runs on Syndicate's CLI port, not the vendored package (lane nba-source-cli-native,
user decision 2026-10-13).

`scripts/build_wnba_totals_calibration.py` (run once a day by the WNBA props refresh, `_ensure_wnba_totals_calibration`)
put `vendor/wnba_betting_repo/src` on sys.path for `wnba_betting.{cli,config,features_enhanced,games_npu}`. It now imports
the same names from `syndicate.features.wnba.source_cli`, the generated port `predict-date` already runs from.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_wnba_totals_calibration.py"


def test_imports_nothing_vendored():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            mods.append(node.module or "")
    assert not [m for m in mods if m.split(".")[0] in {"wnba_betting", "nba_betting", "vendor"}], mods
    assert "syndicate.features.wnba.source_cli.games_npu" in mods and "syndicate.features.wnba.source_cli.config" in mods
    assert '"vendor"' not in SCRIPT.read_text(encoding="utf-8")


def test_main_resolves_the_data_root_through_the_port(tmp_path):
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    existing = processed / "calibration_totals_2026-10-16.json"
    existing.write_text("{}", encoding="utf-8")
    env = {**__import__("os").environ, "WNBA_BETTING_DATA_ROOT": str(tmp_path / "data")}
    code = ("import runpy, sys; sys.argv = ['x', '--date', '2026-10-17'];"
            f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out == {"status": "exists", "path": str(existing)}
    assert "wnba_betting" not in r.stderr


def test_the_port_carries_the_feature_columns_the_builder_loads():
    from syndicate.features.wnba.source_cli.config import paths

    assert (paths.models / "feature_columns_enhanced.joblib").is_file()
    assert "vendor" not in paths.models.parts
