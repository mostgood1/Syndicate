"""The MLB live-lens app slice (syndicate/features/mlb/live_lens_port/app_slice.py).

Frozen from vendor/mlb_bettingv2 at 988fa33d and maintained here (syndicate/features/mlb/FROZEN_FROM_VENDOR.md).
This pins: it imports with both entry points, and its one root edit resolves the engines/mlb data root.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_port_imports_with_both_entry_points():
    from syndicate.features.mlb.live_lens_port import app_slice

    assert callable(app_slice._live_lens_reports_payload)
    assert callable(app_slice.start_live_lens_background_loop)


def test_root_edit_resolves_the_engine_data_root():
    """In the vendored file `Path(__file__).parents[2]` of tools/web/flask_frontend.py is vendor/mlb_bettingv2, the
    app's DATA root; since lane mlb-engine-data-native-p4 that root is Syndicate's engines/mlb."""
    from syndicate.features.mlb.live_lens_port import app_slice

    expected = (ROOT / "engines" / "mlb").resolve()
    assert Path(app_slice._ROOT).resolve() == expected
    assert Path(app_slice._ROOT_DIR).resolve() == expected
    assert Path(app_slice._WEB_DIR).resolve() == expected / "tools" / "web"
