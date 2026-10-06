"""As-of roster rebuild: every current-season input is bounded at D-1 (lane mlb-asof-roster-rebuild)."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "vendor" / "mlb_bettingv2"))

import mlb_asof_roster_build as asof  # noqa: E402
from sim_engine.data import build_roster as br  # noqa: E402
from sim_engine.data.statsapi import StatsApiClient  # noqa: E402


def _client(monkeypatch, tmp_path, seen):
    def fake_get(self, path, params=None):
        seen.append((path, dict(params or {})))
        if (params or {}).get("stats") == "gameLog":
            return {"stats": [{"splits": [{"date": "2026-06-13"}, {"date": "2026-06-14"}, {"date": "2026-06-15"}]}]}
        return {"stats": [{"splits": [{"stat": {"a": 1}}, {"stat": {"b": 2}}]}]}

    monkeypatch.setattr(StatsApiClient, "get", fake_get)
    return asof.make_client("2026-06-15", 2026, tmp_path, Counter())


def test_season_stats_become_byDateRange_ending_the_day_before(monkeypatch, tmp_path):
    seen = []
    c = _client(monkeypatch, tmp_path, seen)
    out = c.get("/people/1/stats", {"stats": "season", "season": 2026, "group": "pitching"})
    assert seen[-1][1]["stats"] == "byDateRange" and seen[-1][1]["endDate"] == "2026-06-14"
    assert len(out["stats"][0]["splits"]) == 1


def test_gamelog_drops_rows_on_or_after_D(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, [])
    out = c.get("/people/1/stats", {"stats": "gameLog", "season": 2026})
    assert [s["date"] for s in out["stats"][0]["splits"]] == ["2026-06-13", "2026-06-14"]


def test_splits_go_to_prior_season_and_unknown_types_are_refused(monkeypatch, tmp_path):
    seen = []
    c = _client(monkeypatch, tmp_path, seen)
    c.get("/people/1/stats", {"stats": "statSplits", "season": 2026})
    assert seen[-1][1]["season"] == 2025
    with pytest.raises(asof.LeakRefused):
        c.get("/people/1/stats", {"stats": "careerRegularSeason", "season": 2026})


def test_statcast_features_are_built_to_D_minus_1_and_stamina_follows_the_cache_hit_path(monkeypatch, tmp_path):
    calls = {}

    def fake_build(**kw):
        calls.update(kw)
        return {"pitchers": {"7": {}}, "batters": {}}

    import tools.datasets.build_statcast_player_feature_set as fs
    monkeypatch.setattr(fs, "build_feature_set", fake_build)
    monkeypatch.setattr(br, "_apply_statcast_features_to_pitcher", lambda prof, season: True)
    monkeypatch.setattr(br, "_apply_statcast_pitch_count_stamina_adjustment", lambda prof: True)
    monkeypatch.setattr(br, "_asof_stamina_wrapped", False, raising=False)
    monkeypatch.setattr(br, "_STATCAST_FEATURES_CACHE_BY_SEASON", {})
    monkeypatch.setattr(br, "_STATCAST_QUALITY_CACHE_BY_SEASON", {})
    counters = Counter()
    asof.install_asof_statcast(tmp_path, "2026-06-15", 2026, counters)
    assert str(calls["end_date"]) == "2026-06-14"
    # Production has no 2025 file and falls back to `_latest`, i.e. the current file.
    assert br._STATCAST_FEATURES_CACHE_BY_SEASON[2026] is br._STATCAST_FEATURES_CACHE_BY_SEASON[2025]
    assert br._STATCAST_QUALITY_CACHE_BY_SEASON == {2026: {}, 2025: {}}
    assert br._apply_statcast_features_to_pitcher(object(), 2026) is True
    assert counters["stamina_adjusted"] == 1
