"""Vendored code is not copied onto the data disk (lane wnba-bootstrap-src-off-vendor, 2026-10-12)."""

from __future__ import annotations

import importlib.util
import sys
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


def test_vendored_app_imports_its_own_src_not_a_data_disk_copy(tmp_path, monkeypatch):
    refresh = _load("refresh_wnba_probe_src", "scripts/refresh_wnba_oddsapi_props.py")
    app_root = tmp_path / "app_root"
    (app_root / "src" / "wnba_betting").mkdir(parents=True)
    (app_root / "app.py").write_text("x = 1\n", encoding="utf-8")
    stale_copy = str(tmp_path / "data" / "wnba_source" / "src")
    seen = {}

    def fake_loader(name, path):
        seen["path0"] = sys.path[0]
        seen["order"] = [p for p in sys.path if p in (str(app_root / "src"), stale_copy)]
        return object()

    monkeypatch.setattr(refresh, "_load_module_from_path", fake_loader)
    monkeypatch.setattr(sys, "path", [stale_copy] + list(sys.path))  # what the props steps leave first today
    assert refresh._load_source_app(app_root) is not None
    assert seen["path0"] == str(app_root / "src")
    assert seen["order"] == [str(app_root / "src"), stale_copy]
