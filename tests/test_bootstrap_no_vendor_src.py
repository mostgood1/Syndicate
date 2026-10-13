"""Vendored code is not copied onto the data disk (lane wnba-bootstrap-src-off-vendor, 2026-10-12)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bootstrap_copies_no_vendored_source(tmp_path):
    boot = _load("bootstrap_data_root_probe", "scripts/bootstrap_data_root.py")
    assert boot.BOOTSTRAP_VENDOR_ROOTS == ()
    pairs = boot._bootstrap_root_pairs(ROOT, tmp_path / "data")
    for src, dst, key, _policy in pairs:
        assert "vendor" not in Path(key).parts, key
        assert not str(dst).replace("\\", "/").endswith("wnba_source/src"), dst

