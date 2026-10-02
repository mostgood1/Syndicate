"""NCAAF's games cache lives on the data root (lane ncaaf-games-cache-data-root).

`DEFAULT_CACHE_DIR` resolved from `__file__`, so `refresh_games_cache` rewrote the
git-tracked `data/ncaaf_source/historical_truth/games_2026.json.gz` in the fleet's
code checkout (left modified) while the data root kept an orphaned copy 71
completed games behind (2026-10-02: 331 vs 260 of 888).
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from syndicate.features.football.sim_engine.smartsim2.historical_truth import ncaaf_historical_loader as loader

REPO_ROOT = Path(__file__).resolve().parents[1]
GAMES = [{"id": 1, "week": 5, "homeTeam": "Alabama", "awayTeam": "Auburn", "completed": True}]


def _write_games(path: Path, rows=GAMES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(rows, handle)


def test_default_cache_dir_follows_the_ncaaf_source_root(tmp_path, monkeypatch):
    root = tmp_path / "data" / "ncaaf_source"
    root.mkdir(parents=True)
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(root))
    assert loader._default_cache_dir() == root / "historical_truth"


def test_default_cache_dir_is_not_the_checkout_on_a_configured_host(tmp_path, monkeypatch):
    root = tmp_path / "data" / "ncaaf_source"
    root.mkdir(parents=True)
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(root))
    assert loader._default_cache_dir() != loader.REPO_CACHE_DIR


def test_cold_data_root_is_seeded_from_the_repo_copy_without_an_api_call(tmp_path, monkeypatch):
    seed_dir = tmp_path / "repo_ht"
    _write_games(seed_dir / "games_2026.json.gz")
    monkeypatch.setattr(loader, "REPO_CACHE_DIR", seed_dir)

    def no_api(*_a, **_k):
        raise AssertionError("CFBD must not be called when a seed exists")

    monkeypatch.setattr(loader, "_cfbd_get", no_api)
    cache = tmp_path / "data_root_ht"
    path = loader.ensure_games_cached(2026, cache_dir=cache)
    assert path == cache / "games_2026.json.gz"
    assert loader._read_json_gz(path) == GAMES


def test_without_a_seed_the_api_is_still_the_fallback(tmp_path, monkeypatch):
    """off != on: the seed branch is what avoided the call above."""
    monkeypatch.setattr(loader, "REPO_CACHE_DIR", tmp_path / "empty")
    calls = []
    monkeypatch.setattr(loader, "_cfbd_get", lambda *a, **k: calls.append(a) or GAMES)
    path = loader.ensure_games_cached(2026, cache_dir=tmp_path / "data_root_ht")
    assert calls and loader._read_json_gz(path) == GAMES


def test_an_existing_data_root_copy_wins_over_the_seed(tmp_path, monkeypatch):
    seed_dir = tmp_path / "repo_ht"
    _write_games(seed_dir / "games_2026.json.gz", rows=[{"id": "seed"}])
    monkeypatch.setattr(loader, "REPO_CACHE_DIR", seed_dir)
    cache = tmp_path / "data_root_ht"
    _write_games(cache / "games_2026.json.gz", rows=[{"id": "fresh"}])
    assert loader._read_json_gz(loader.ensure_games_cached(2026, cache_dir=cache)) == [{"id": "fresh"}]


def test_generator_cached_games_reads_the_loader_dir(tmp_path, monkeypatch):
    path = REPO_ROOT / "scripts" / "generate_smartsim2_ncaaf_projections.py"
    spec = importlib.util.spec_from_file_location("gen_ncaaf_under_test", path)
    gen = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gen
    spec.loader.exec_module(gen)
    cache = tmp_path / "data_root_ht"
    _write_games(cache / "games_2026.json.gz")
    monkeypatch.setattr(loader, "DEFAULT_CACHE_DIR", cache)
    rows = gen._cached_games(2026, 5)
    assert rows is not None and len(rows) == 1
