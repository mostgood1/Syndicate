"""SP+ ratings must come from disk when a cache exists — no CFBD call.

WHY THIS IS THE ONE WORTH CACHING. The NCAAF projections generator hits four
CFBD endpoints, and only one of them cannot be served from an artifact this repo
already holds:

    /games       -> historical_truth/games_<season>.json.gz  (888 rows, 2026 wk1-6)
    /ppa/teams   -> FALLBACK rating source only
    /ppa/games   -> the as-of variant of the same fallback
    /ratings/sp  -> PRIMARY rating source, no local equivalent

SP+ is a projection published by CFBD; it cannot be derived from drives, plays
or games. And a COMPLETED season's SP+ never changes, so re-fetching it on every
run buys nothing.

WHAT IT COST. Measured 2026-08-27: a few full-season pulls put EVERY CFBD
endpoint behind HTTP 429 for over two hours — 20 retries, all refused — which
blocked the totals re-fit AND the confirmation that a promoted calibration
artifact had loaded. Both were gated on this single call.

THE TWO FAILURE MODES THESE PIN, because either would be worse than no cache:
  * a rate-limited run writing an EMPTY index that is then served forever as
    though it were real
  * a corrupt cache raising, rather than behaving as if absent
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import importlib.util as _iu

_spec = _iu.spec_from_file_location("_gen", REPO_ROOT / "scripts" / "generate_smartsim2_ncaaf_projections.py")
gen = _iu.module_from_spec(_spec)
sys.modules["_gen"] = gen
_spec.loader.exec_module(gen)


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_SP_RATINGS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(gen, "_SP_CACHE_REFRESH", False, raising=False)
    yield tmp_path


def _forbid_api(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("CFBD was called even though a cache exists")
    monkeypatch.setattr(gen, "_cfbd_get", _boom)


def test_a_cached_season_is_served_without_touching_cfbd(cache_dir, monkeypatch):
    """THE POINT. With a cache present, no network call may happen."""
    path = gen.sp_ratings_cache_path(2025)
    path.write_text(json.dumps({"season": 2025, "teams": {"alabama": [30.1, -12.4], "auburn": [22.0, -8.1]}}), encoding="utf-8")
    _forbid_api(monkeypatch)
    index = gen.load_sp_ratings(2025)
    assert index["alabama"] == (30.1, -12.4)
    assert index["auburn"] == (22.0, -8.1)


def test_a_successful_fetch_is_written_to_the_cache(cache_dir, monkeypatch):
    monkeypatch.setattr(gen, "_cfbd_get", lambda *a, **k: [
        {"team": "Alabama", "offense": {"rating": 30.1}, "defense": {"rating": 12.4}},
        {"team": "nationalAverages", "offense": {"rating": 0}, "defense": {"rating": 0}},
    ])
    index = gen.load_sp_ratings(2024)
    assert gen.norm("Alabama") in index
    payload = json.loads(gen.sp_ratings_cache_path(2024).read_text(encoding="utf-8"))
    assert payload["season"] == 2024
    assert gen.norm("Alabama") in payload["teams"]
    assert "nationalaverages" not in {k.lower() for k in payload["teams"]}, "the sentinel row must not be cached"
    assert "fetched_at" in payload, "provenance: when this was taken"


def test_AN_EMPTY_FETCH_IS_NEVER_CACHED(cache_dir, monkeypatch):
    """A rate-limited or malformed response must not poison the cache.

    Writing `{}` once would serve an empty rating index forever, and the
    generator would silently produce projections with no ratings at all.
    """
    monkeypatch.setattr(gen, "_cfbd_get", lambda *a, **k: [])
    index = gen.load_sp_ratings(2027)
    assert index == {}
    assert not gen.sp_ratings_cache_path(2027).exists(), "an empty index was cached"


def test_a_corrupt_cache_behaves_as_if_absent(cache_dir, monkeypatch):
    """Never raise on a bad cache — degrade to the fetch, like the profile store."""
    path = gen.sp_ratings_cache_path(2025)
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(gen, "_cfbd_get", lambda *a, **k: [
        {"team": "Alabama", "offense": {"rating": 1.0}, "defense": {"rating": 2.0}}
    ])
    index = gen.load_sp_ratings(2025)
    assert gen.norm("Alabama") in index


def test_refresh_flag_ignores_the_cache(cache_dir, monkeypatch):
    """In-season a rating still moves week to week."""
    gen.sp_ratings_cache_path(2026).write_text(
        json.dumps({"season": 2026, "teams": {"stale": [1.0, 1.0]}}), encoding="utf-8")
    monkeypatch.setattr(gen, "_SP_CACHE_REFRESH", True, raising=False)
    monkeypatch.setattr(gen, "_cfbd_get", lambda *a, **k: [
        {"team": "Fresh", "offense": {"rating": 9.0}, "defense": {"rating": 3.0}}
    ])
    index = gen.load_sp_ratings(2026)
    assert gen.norm("Fresh") in index
    assert "stale" not in index


def test_the_cache_defaults_to_the_other_cfbd_caches(monkeypatch):
    """It belongs beside games_*.json.gz and drives_*.json.gz, which is what
    reaches Render with the code deploy — `data/` is git-tracked here."""
    monkeypatch.delenv("SYNDICATE_SP_RATINGS_CACHE_DIR", raising=False)
    path = gen.sp_ratings_cache_path(2025)
    assert path.parent.name == "historical_truth"
    assert path.name == "sp_ratings_2025.json"
