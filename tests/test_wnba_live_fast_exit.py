"""Live WNBA `--mode fast` runs no longer exit 1 for missing edge rows
(lane wnba-live-fast-exit).

Fast mode skips predictions/edges by design, but main()'s --do-edges check still
demanded edge rows: 31 of 42 live WNBA runs on 2026-10-02 exited 1 that way.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("refresh_wnba_fast_exit_under_test", REPO_ROOT / "scripts" / "refresh_wnba_oddsapi_props.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("mode, expected", [("fast", 0), ("full", 1)])
def test_missing_edges_fail_only_in_full_mode(tmp_path, monkeypatch, mode, expected):
    mod = _load()
    state = {"date": "2026-10-02", "snapshot_rows": 569, "snapshot_alias_rows": 569, "edges_rows": 0, "recs_rows": 0,
             "player_prop_rows": 569, "error": None}
    monkeypatch.setattr(mod, "_run_refresh_via_cli", lambda **k: dict(state))
    monkeypatch.setattr(sys, "argv", ["refresh_wnba_oddsapi_props.py", "--date", "2026-10-02", "--source-root", str(tmp_path),
                                      "--log-file", str(tmp_path / "r.log"), "--do-edges", "--do-export",
                                      "--phase", "live", "--mode", mode])
    assert mod.main() == expected
