"""Tests for scripts/fit_wnba_sim_availability.py: the as-of features must see only the TEAM's earlier games."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fit_avail", ROOT / "scripts" / "fit_wnba_sim_availability.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)  # type: ignore[union-attr]


def _games():
    def g(i, tip, home, away):
        return {"id": i, "tip": tip, "home": home, "away": away}
    return {"1": g("1", "2026-07-01T23:00Z", "LVA", "IND"), "2": g("2", "2026-07-03T23:00Z", "SEA", "LVA"),
            "3": g("3", "2026-07-05T23:00Z", "LVA", "MIN")}


def test_features_are_as_of_and_per_team():
    box = {"1": {"LVA": {"wilson": 34.0, "bell": 12.0}, "IND": {"clark": 35.0}},
           "2": {"LVA": {"wilson": 33.0, "bell": 0.0}, "SEA": {}},
           "3": {"LVA": {"wilson": 30.0, "bell": 25.0}, "MIN": {}}}
    th = F.TeamHistory(_games(), box)
    f = th.features("LVA", "bell", "2026-07-05T23:00Z")          # before game 3: bell sat game 2 (MIN 0)
    assert f["missed_last_1"] is True and f["missed_last_2"] is False and f["since_last"] == 1
    assert th.features("LVA", "wilson", "2026-07-05T23:00Z")["missed_last_1"] is False
    assert th.features("LVA", "bell", "2026-07-01T23:00Z") == {"team_games_prior": 0, "missed_last_1": False,
                                                               "missed_last_2": False, "missed_last_3": False,
                                                               "since_last": 0, "ever_played_for_team": False}
    # game 3 itself must not inform a feature taken at its own tip
    assert th.features("LVA", "bell", "2026-07-05T23:00Z")["team_games_prior"] == 2
    # another team's games never count
    assert th.features("IND", "bell", "2026-07-05T23:00Z")["ever_played_for_team"] is False
