"""Women's college basketball sims (lane wncaab-module, user 2026-11-02 "Approve the loans").

The men's producers, team model and re-sim take a `league` switch; every NCAAB path and value stays the
default. These tests pin both halves: the women's switch reaches the women's data, and the men's does not move.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_ratings_producer_switches_registry_path_and_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_NCAAB_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("SYNDICATE_WNCAAB_SOURCE_ROOT", raising=False)
    ratings = _load("ratings_wncaab_test", "scripts/build_ncaab_team_ratings.py")
    men = ratings.load_registry()
    assert "mens-college-basketball" in ratings.SPORT_PATH and ratings.ncaab_root() == tmp_path / "ncaab_source"
    ratings.configure_league("wncaab")
    women = ratings.load_registry()
    assert "womens-college-basketball" in ratings.SPORT_PATH and ratings.processed_dir() == tmp_path / "wncaab_source" / "data" / "processed"
    assert len(women) >= 350 and {"2511", "88"} <= set(women) and "2511" not in men  # Queens: women's D-I only
    ratings.configure_league("ncaab")
    assert ratings.load_registry() == men


def test_player_priors_producer_follows_the_ratings_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_WNCAAB_SOURCE_ROOT", raising=False)
    priors = _load("priors_wncaab_test", "scripts/build_ncaab_player_priors.py")
    priors.ratings.configure_league("wncaab")
    try:
        assert priors.box_path(2026) == tmp_path / "wncaab_source" / "data" / "processed" / "player_game_box_2026.csv"
    finally:
        priors.ratings.configure_league("ncaab")
    assert priors.box_path(2026) == tmp_path / "ncaab_source" / "data" / "processed" / "player_game_box_2026.csv"
