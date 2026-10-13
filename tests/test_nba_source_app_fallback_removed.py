"""The NBA refresh's vendored source-app fallback is gone (lane nba-source-cli-native, user decision 2026-10-13).

It could not run in production: SYNDICATE_NBA_SOURCE_APP_FALLBACK=false on every fleet role, and it loaded app.py from
the data bundle, which has none. Every branch was replaced by what it did with the flag off, so this pins only that
nothing of it remains: no flag, no app loader, no in-process route call into a vendored Flask app.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_nba_oddsapi_props.py"


def test_no_fallback_names_left():
    spec = importlib.util.spec_from_file_location("refresh_nba_probe_fallback", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("_source_app_fallback_enabled", "_load_source_app", "_run_source_cli_command", "_load_source_cli"):
        assert not hasattr(mod, name), name


def test_no_vendored_route_or_app_load_left():
    src = SCRIPT.read_text(encoding="utf-8")
    for needle in ("SYNDICATE_NBA_SOURCE_APP_FALLBACK", ".test_client()", 'source_root / "app.py"',
                   "/api/cards?", "/api/cron/reconcile-games", "/api/download_live_lens", "/api/season/", "/api/live_state"):
        assert needle not in src, needle
