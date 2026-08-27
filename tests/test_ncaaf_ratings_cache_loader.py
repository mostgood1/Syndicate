"""SP+ ratings belong in the historical-truth loader, beside games/drives/plays.

WHAT WAS MISSING AND WHY IT MATTERED. The loader cached three datasets — games,
drives, plays — all of them EVENT data, a record of what happened. Ratings were
never cached, and they are the one input that:

  * CANNOT be derived from the events (SP+ is CFBD's own model output)
  * DOES NOT CHANGE for a completed season
  * IS THE PRIMARY MODEL INPUT (SP+ beat PPA on both backtested season pairs;
    PPA is only the fallback)

So the bulky, derivable datasets were retained and the small, irreplaceable one
was discarded after every run.

MEASURED COST, 2026-08-27: a few full-season pulls exhausted the CFBD quota and
it was still HTTP 429 thirteen hours later — a hard cap, not a rolling window.
Projection regeneration was blocked outright, which blocked the production
confirmation that a promoted calibration artifact had loaded. A 19 August run
HAD fetched SP+ 2026 successfully and the numbers were discarded; they cannot be
recovered from the projections (51 games, ~204 unknowns, 300-seed Monte Carlo).
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2.historical_truth import ncaaf_historical_loader as L

_PAYLOAD = [
    {"team": "Alabama", "offense": {"rating": 30.1}, "defense": {"rating": 12.4}},
    {"team": "Auburn", "offense": {"rating": 22.0}, "defense": {"rating": 18.1}},
    {"team": "nationalAverages", "offense": {"rating": 0}, "defense": {"rating": 0}},
]


def test_ratings_sit_beside_the_other_cached_datasets(tmp_path):
    path = L._ratings_cache_path(2025, tmp_path)
    assert path.parent == tmp_path
    assert path.name == "ratings_sp_2025.json.gz"
    assert path.suffixes[-2:] == [".json", ".gz"], "same gzipped-JSON shape as games/drives/plays"


def test_a_present_cache_is_returned_without_fetching(tmp_path, monkeypatch):
    path = L._ratings_cache_path(2025, tmp_path)
    with gzip.open(path, "wt", encoding="utf-8") as h:
        json.dump(_PAYLOAD, h)
    monkeypatch.setattr(L, "_cfbd_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("CFBD called")))
    assert L.ensure_ratings_cached(2025, cache_dir=tmp_path) == path


def test_a_successful_fetch_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "_cfbd_get", lambda *a, **k: _PAYLOAD)
    path = L.ensure_ratings_cached(2024, cache_dir=tmp_path)
    assert path.exists()
    with gzip.open(path, "rt", encoding="utf-8") as h:
        assert json.load(h) == _PAYLOAD, "the payload is stored verbatim, like its siblings"


def test_AN_EMPTY_PAYLOAD_IS_NEVER_CACHED(tmp_path, monkeypatch):
    """A rate-limited or malformed response written once would be served forever
    as real, and the generator would produce projections with NO RATINGS — which
    looks exactly like a completed run. An absent file is honest; an empty one
    is not."""
    monkeypatch.setattr(L, "_cfbd_get", lambda *a, **k: [])
    with pytest.raises(RuntimeError):
        L.ensure_ratings_cached(2027, cache_dir=tmp_path)
    assert not L._ratings_cache_path(2027, tmp_path).exists()


def test_load_returns_None_not_empty_when_absent(tmp_path):
    """None, not []. An empty list reads as "this season has no ratings", which
    is indistinguishable from a failed fetch and sends a caller down the
    no-ratings path instead of to the API."""
    assert L.load_cached_ratings(2025, cache_dir=tmp_path) is None


def test_a_corrupt_cache_reads_as_absent(tmp_path):
    path = L._ratings_cache_path(2025, tmp_path)
    path.write_bytes(b"not gzip")
    assert L.load_cached_ratings(2025, cache_dir=tmp_path) is None


def test_load_round_trips_a_written_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "_cfbd_get", lambda *a, **k: _PAYLOAD)
    L.ensure_ratings_cached(2024, cache_dir=tmp_path)
    back = L.load_cached_ratings(2024, cache_dir=tmp_path)
    assert back == _PAYLOAD


def test_the_generator_prefers_the_loader_cache(tmp_path, monkeypatch):
    """Reachability: one owner for the payload, so the two caches cannot diverge."""
    import importlib.util as iu

    spec = iu.spec_from_file_location("_g2", REPO_ROOT / "scripts" / "generate_smartsim2_ncaaf_projections.py")
    gen = iu.module_from_spec(spec)
    sys.modules["_g2"] = gen
    spec.loader.exec_module(gen)

    monkeypatch.setattr(L, "DEFAULT_CACHE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(gen, "_cfbd_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("CFBD called")))
    monkeypatch.setattr(gen, "_SP_CACHE_REFRESH", False, raising=False)
    monkeypatch.setattr(L, "load_cached_ratings", lambda season, **k: _PAYLOAD)

    index = gen.load_sp_ratings(2026)
    assert gen.norm("Alabama") in index
    assert index[gen.norm("Alabama")] == (30.1, 12.4)
    assert "nationalaverages" not in {k.lower() for k in index}, "the sentinel row must be dropped"
