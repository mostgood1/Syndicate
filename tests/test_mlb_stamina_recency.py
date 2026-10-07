"""Late-season workload: recency-weighted starter stamina (lane mlb-statsapi-asof-rebuild)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor" / "mlb_bettingv2"))

from sim_engine.data import build_roster as br  # noqa: E402
from sim_engine.data import recency  # noqa: E402


def _log(rows):
    return [{"stat": {"gamesStarted": gs, "numberOfPitches": n}} for gs, n in rows]


def test_recent_start_pitches_uses_only_the_last_starts(monkeypatch):
    rows = [(1, 100)] * 4 + [(0, 30), (1, 80), (1, 70), (0, 25), (1, 90), (1, 60), (1, 75)]
    monkeypatch.setattr(recency, "fetch_person_gamelog", lambda *a, **k: _log(rows))
    # last 5 STARTS: 80, 70, 90, 60, 75 (relief outings ignored)
    assert recency.pitcher_recent_start_pitches(None, 1, 2026, starts=5) == pytest.approx(75.0)


def test_too_few_starts_returns_none(monkeypatch):
    monkeypatch.setattr(recency, "fetch_person_gamelog", lambda *a, **k: _log([(1, 90), (0, 20), (1, 85)]))
    assert recency.pitcher_recent_start_pitches(None, 1, 2026) is None


def test_weight_zero_is_untouched_and_makes_no_request(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("weight 0 must not fetch anything")
    monkeypatch.setattr(br, "pitcher_recent_start_pitches", boom)
    assert br._blend_recent_starter_stamina(None, 1, 2026, 93, 0.0, 5) == 93


def test_blend_and_clamps(monkeypatch):
    monkeypatch.setattr(br, "pitcher_recent_start_pitches", lambda *a, **k: 80.0)
    assert br._blend_recent_starter_stamina(None, 1, 2026, 96, 0.5, 5) == 88
    monkeypatch.setattr(br, "pitcher_recent_start_pitches", lambda *a, **k: 40.0)
    assert br._blend_recent_starter_stamina(None, 1, 2026, 72, 1.0, 5) == 70  # floor
    monkeypatch.setattr(br, "pitcher_recent_start_pitches", lambda *a, **k: None)
    assert br._blend_recent_starter_stamina(None, 1, 2026, 91, 0.75, 5) == 91  # no history -> untouched
