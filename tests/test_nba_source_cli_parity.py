"""NBA source CLI parity, the in-repo half (lane nba-source-cli-native, 2026-10-12).

The gate of record is scripts/nba_source_cli_parity.py on the fleet: the whole eight-command bootstrap recorded through
the vendored CLI against the real network and replayed through the port, every written file compared (deploys.md).
A recording reads the whole data root, so the suite keeps a smaller real-data check instead: `build-features` --
the bootstrap step that turns the games history into the model features -- run through the vendored CLI and through
the port, each in its own process on its own copy of the vendored repo's committed games history, must write
identical features. A planted one-value change must be detected (the positive control). Skips once the vendor tree
is gone.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "nba_betting_repo"
GAMES = VENDOR / "data" / "raw" / "games_nba_api.csv"


def _run(arm: str, data_root: Path) -> pd.DataFrame:
    (data_root / "raw").mkdir(parents=True)
    shutil.copy2(GAMES, data_root / "raw" / "games_nba_api.csv")
    env = dict(os.environ, NBA_BETTING_DATA_ROOT=str(data_root), NBA_BETTING_RECONCILE_REPO_DATA="0", PYTHONUTF8="1")
    if arm == "vendored":
        env["PYTHONPATH"] = str(VENDOR / "src")
        cmd, cwd = [sys.executable, "-m", "nba_betting.cli", "build-features"], VENDOR
    else:
        env["PYTHONPATH"] = str(ROOT)
        cmd, cwd = [sys.executable, "-m", "syndicate.features.nba.source_cli.cli", "build-features"], ROOT
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return pd.read_csv(data_root / "processed" / "features.csv")


def test_build_features_is_identical(tmp_path):
    if not GAMES.exists():
        pytest.skip("vendor tree removed")
    vendored = _run("vendored", tmp_path / "v")
    port = _run("port", tmp_path / "p")
    assert len(vendored) > 1000 and vendored.shape[1] > 10, vendored.shape  # a real build, not an empty frame
    pd.testing.assert_frame_equal(vendored, port, check_exact=True)
    # positive control: one changed value must be detected by the same comparison
    planted = port.copy()
    col = next(c for c in planted.columns if pd.api.types.is_numeric_dtype(planted[c]) and planted[c].notna().any())
    planted.loc[planted[col].first_valid_index(), col] = planted[col].dropna().iloc[0] + 1
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(vendored, planted, check_exact=True)
