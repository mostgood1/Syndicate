"""MLB live-lens port, phase 1 (lane mlb-live-lens-native-p1, 2026-10-15).

The gate of record is scripts/mlb_live_lens_parity.py on the fleet (the vendored `_live_lens_reports_payload` recorded on a
frozen copy of production's MLB data, the port replayed on its own copy of the same snapshot; deploys.md). A committed
replay fixture is not practical here -- one call opens ~34k files (~3 GB) -- so this pins what can be pinned in the suite:
the package is exactly what the generator writes from the vendored source, it imports, and its one hand edit resolves the
vendored repo root the way the vendored file did.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDORED = ROOT / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"


@pytest.mark.skipif(not VENDORED.exists(), reason="vendor tree absent")
def test_generated_package_matches_the_generator():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "port_mlb_live_lens.py"), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "CHECK OK" in r.stdout, r.stdout + r.stderr[-3000:]


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
