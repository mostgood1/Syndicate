"""Deliberate departures of the live-tick port from the vendored code (scripts/port_basketball_live_tick.py FIXES).

`wnba-registry-current-last-updates` (user decision 2026-10-12): the vendored WNBA `_update_registry_bucket` lost its
`current_last_updates` parameter, so every call raised TypeError inside a `try` and the WNBA live-props registry was
never written. These tests pin:
  * the frozen port carries the FIX exactly once (the verbatim text is that port with it reversed);
  * BEHAVIOUR, on synthetic OddsAPI responses: the fixed port writes the registry and fills the first/last-seen,
    first/last line + price and observation maps. The verbatim text -- the positive control, i.e. the bug -- writes
    nothing and leaves every one of those maps EMPTY (`out` initialises them to {}). Every other key is identical.
"""
from __future__ import annotations

import difflib
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "syndicate" / "features" / "wnba" / "live_tick"
# The one deliberate departure from the vendored text, recorded here since the generator that carried it (FIXES in
# scripts/port_basketball_live_tick.py) is retired (lane wnba-vendor-deletion-prep). The verbatim text is the frozen port with it reversed.
FIX_OLD = "        current_prices: dict[str, Any],\n        default_observed_at: Any,\n    ) -> None:"
FIX_NEW = ("        current_prices: dict[str, Any],\n        current_last_updates: dict[str, Any],  # FIX wnba-registry-current-last-updates\n"
           "        default_observed_at: Any,\n    ) -> None:")
REGISTRY_KEYS = {"first_seen_at_by_key", "last_seen_at_by_key", "first_line_by_key", "last_line_by_key",
                 "first_prices_by_key", "last_prices_by_key", "observations_by_key"}
EVENT_ID = "evt0001"


@pytest.fixture(scope="module")
def unfixed_pkg(tmp_path_factory):
    """The verbatim (vendored) text: a copy of the frozen WNBA port package with the FIX reversed."""
    import shutil

    out = tmp_path_factory.mktemp("unfixed")
    pkg = out / "unfixed_wnba_live_tick"
    shutil.copytree(PORT, pkg, ignore=shutil.ignore_patterns("__pycache__"))
    tick = (pkg / "tick.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert tick.count(FIX_NEW) == 1, "the frozen port no longer carries the FIX verbatim"
    (pkg / "tick.py").write_text(tick.replace(FIX_NEW, FIX_OLD), encoding="utf-8")
    return pkg


def test_the_frozen_port_carries_the_fix_exactly_once():
    tick = (PORT / "tick.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert tick.count(FIX_NEW) == 1 and tick.count("current_last_updates: dict[str, Any],  # FIX") == 1


def _fake_get(url, params=None, headers=None, timeout=None):
    import requests

    def resp(obj):
        r = requests.models.Response()
        r.status_code = 200
        r._content = json.dumps(obj).encode("utf-8")
        r.headers["content-type"] = "application/json"
        return r

    if url.endswith("/events"):
        return resp([{"id": EVENT_ID, "home_team": "Golden State Valkyries", "away_team": "Atlanta Dream",
                      "commence_time": "2026-10-17T19:30:00Z"}])
    if url.endswith(f"/events/{EVENT_ID}/markets"):
        return resp({"bookmakers": [{"key": "draftkings", "markets": [{"key": "player_points"}, {"key": "player_rebounds"}]}]})
    if url.endswith(f"/events/{EVENT_ID}/odds"):
        def mk(key, player, point):
            return {"key": key, "last_update": "2026-10-17T20:31:00Z", "outcomes": [
                {"name": "Over", "description": player, "price": -115, "point": point},
                {"name": "Under", "description": player, "price": -105, "point": point}]}
        return resp({"id": EVENT_ID, "bookmakers": [{"key": "draftkings", "last_update": "2026-10-17T20:31:00Z", "markets": [
            mk("player_points", "Rhyne Howard", 19.5), mk("player_rebounds", "Brionna Jones", 7.5)]}]})
    raise AssertionError(f"unexpected request {url}")


def _run(mod, monkeypatch, tmp_path):
    monkeypatch.setenv("ODDS_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LIVE_PLAYER_PROP_BOOKMAKERS", "draftkings")
    monkeypatch.setattr(mod, "DATA_PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(mod.requests, "get", _fake_get)
    out = mod._live_oddsapi_player_props_for_game("2026-10-17", "GSV", "ATL")
    files = sorted((tmp_path / "processed" / "live_lens_registry").glob("*.json")) if (tmp_path / "processed" / "live_lens_registry").exists() else []
    return out, files


def _load_unfixed(unfixed_pkg):
    sys.path.insert(0, str(unfixed_pkg.parent))
    try:
        return importlib.import_module(f"{unfixed_pkg.name}.tick")
    finally:
        sys.path.remove(str(unfixed_pkg.parent))


def test_fix_writes_the_registry_and_the_verbatim_text_does_not(unfixed_pkg, monkeypatch, tmp_path):
    from syndicate.features.wnba.live_tick import tick as fixed

    out_f, files_f = _run(fixed, monkeypatch, tmp_path / "fixed")
    out_v, files_v = _run(_load_unfixed(unfixed_pkg), monkeypatch, tmp_path / "verbatim")

    assert out_f.get("lines"), out_f  # the synthetic odds were really parsed (not an early empty return)
    # The fix: a registry file, and populated first/last-seen maps.
    assert len(files_f) == 1, files_f
    reg = json.loads(files_f[0].read_text(encoding="utf-8"))
    assert reg["event_id"] == EVENT_ID and reg["markets"], reg
    assert REGISTRY_KEYS <= set(out_f) and out_f["first_seen_at_by_key"] and out_f["observations_by_key"], sorted(out_f)
    registry_maps = {p + k for p in ("", "short_", "all_") for k in REGISTRY_KEYS} & set(out_f)
    # The positive control: the vendored behaviour (the bug) writes nothing and leaves every registry map empty.
    assert files_v == [], files_v
    assert all(out_v.get(k) == {} for k in registry_maps), {k: out_v.get(k) for k in registry_maps if out_v.get(k)}
    # Nothing else moves: same keys, and every non-registry key carries the same value.
    assert set(out_f) == set(out_v)
    # `generated_at` is the wall clock at each call (the two runs can straddle a second boundary; seen on the fleet).
    skip = registry_maps | {"generated_at"}
    assert {k: v for k, v in out_f.items() if k not in skip} == {k: v for k, v in out_v.items() if k not in skip}
