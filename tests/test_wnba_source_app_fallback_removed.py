"""The WNBA refresh's vendored source-app fallback is gone (lane nba-source-cli-native, user decision 2026-10-13).

Every branch but one sat behind SYNDICATE_WNBA_SOURCE_APP_FALLBACK=false (every fleet role). The exception was the
cards_sim_detail export: when the local smart-sim build was empty it imported the vendored app (vendor/wnba_betting_repo
fallback root) and wrote the file from /api/cards. Measured 09-24..10-13 that happened only on dates with no WNBA game
(10-03/06/08/11 files), where the route returned the NEXT games' sims; readers key on a game's own date. Now: no local
games -> no file. This pins that nothing of the fallback remains.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_wnba_oddsapi_props.py"


def test_no_fallback_names_left():
    spec = importlib.util.spec_from_file_location("refresh_wnba_probe_fallback", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("_source_app_fallback_enabled", "_load_source_app", "_run_source_cli_command", "_load_source_cli"):
        assert not hasattr(mod, name), name


def test_no_vendored_route_or_app_load_left():
    src = SCRIPT.read_text(encoding="utf-8")
    for needle in ("SYNDICATE_WNBA_SOURCE_APP_FALLBACK", ".test_client()", '"app.py"', "/api/cards?", "/api/cron/reconcile-games",
                   "/api/download_live_lens", "/api/live_state", 'f"/api/{kind}'):
        assert needle not in src, needle


def test_empty_local_sim_writes_no_cards_sim_detail(tmp_path):
    spec = importlib.util.spec_from_file_location("refresh_wnba_probe_fallback2", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    processed = tmp_path / "bundle" / "data" / "processed"
    processed.mkdir(parents=True)
    mod._build_cards_sim_detail_from_local_smart_sim = lambda **kw: []
    mod._copy_existing_processed_artifact = lambda **kw: None
    assert mod._export_cards_sim_detail_snapshot(source_root=tmp_path / "source", date_str="2026-10-06", processed_root=processed) is None
    assert not (processed / "cards_sim_detail_2026-10-06.json").exists()
