"""The phase-aware staked-probability read (lane sim-stake-earned-profile, user decision (a) 2026-10-22).

A cell fitted on one season phase must never stake another (findings_2026-10-22_sim_stake_earned_profile.md
s5). With a phase, the profile reads ONLY the 4-part `sport|market|segment|phase` key -- no fallback to the
phase-blind 3-part one -- and `commit_portfolio` passes its slate date so that read is the one production
uses. Without a date, the 3-part read is unchanged.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.portfolio_commit import commit_portfolio, sizing_inputs_with_provenance
from syndicate.features.shared.portfolio_settings import PortfolioSettings
from syndicate.features.shared.staked_probability_profile import (
    StakedProbabilityProfile,
    cell_key,
)


def _row(**overrides):
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "kind": "game",
        "market": "h2h",
        "segment": "full_game",
        "line": None,
        "player_name": None,
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2026-08-22T23:05:00Z",
        "side": "home",
        "quote": {"price": -110, "bookmaker": "draftkings"},
        "ev_pct": 4.5,
        "model_edge_pct": 3.2,
        "score": {"score": 5.1, "price_reliability": 0.82},
    }
    row.update(overrides)
    return row


REGULAR_DAY = "2026-08-22"     # MLB regular season
POSTSEASON_DAY = "2026-10-10"  # MLB postseason
OFF_SEASON_DAY = "2026-12-15"  # no MLB phase -> "unknown"


def _profile(cells):
    return StakedProbabilityProfile().with_cells(cells, version="sp-phase-test")


@pytest.fixture(autouse=True)
def _raw_unfitted(monkeypatch):
    # Pin the unfitted behaviour so "no fitted cell" reads the same everywhere (absent = raw).
    monkeypatch.delenv("SYNDICATE_STAKED_PROBABILITY_UNFITTED", raising=False)


def test_cell_key_has_a_fourth_part_only_with_a_phase():
    assert cell_key("MLB", "h2h", "Full_Game") == "mlb|h2h|full_game"
    assert cell_key("mlb", "h2h", "full_game", "Regular") == "mlb|h2h|full_game|regular"
    assert cell_key("mlb", "h2h", "full_game", "") == "mlb|h2h|full_game|unknown"


def test_a_phase_read_matches_only_its_own_phase_and_never_falls_back():
    profile = _profile({cell_key("mlb", "h2h", "full_game", "regular"): {"beta": 0.4}})
    assert profile.beta_for("mlb", "h2h", "full_game", phase="regular") == 0.4
    assert profile.beta_for("mlb", "h2h", "full_game", phase="postseason") == 0.0
    assert profile.beta_for("mlb", "h2h", "full_game") == 0.0  # dateless: the 3-part key, absent

    blind = _profile({cell_key("mlb", "h2h", "full_game"): {"beta": 0.4}})
    assert blind.beta_for("mlb", "h2h", "full_game") == 0.4  # unchanged without a phase
    assert blind.beta_for("mlb", "h2h", "full_game", phase="regular") == 0.0  # no fallback


def test_the_seam_blends_only_in_the_fitted_phase():
    profile = _profile({cell_key("mlb", "h2h", "full_game", "regular"): {"beta": 0.4}})
    _, _, regular = sizing_inputs_with_provenance(_row(), profile=profile, selected_date=REGULAR_DAY)
    _, _, post = sizing_inputs_with_provenance(_row(), profile=profile, selected_date=POSTSEASON_DAY)
    _, _, off = sizing_inputs_with_provenance(_row(), profile=profile, selected_date=OFF_SEASON_DAY)
    assert (regular["blend_beta"], regular["staked_probability_phase"]) == (0.4, "regular")
    assert (post["blend_beta"], post["staked_probability_phase"]) == (0.0, "postseason")
    assert (off["blend_beta"], off["staked_probability_phase"]) == (0.0, "unknown")


def test_commit_portfolio_reads_the_phase_for_its_slate_date(monkeypatch):
    # Reachability: production's commit must pass its date. A regular-season cell blends on a
    # regular-season slate and does nothing on a postseason one.
    import syndicate.features.shared.portfolio_commit as pc

    profile = _profile({cell_key("mlb", "h2h", "full_game", "regular"): {"beta": 0.4}})
    monkeypatch.setattr(pc, "load_staked_probability_profile", lambda: (profile, {"source": "test"}))
    settings = PortfolioSettings(min_ev_pct=2.0, sources={})
    on_regular = commit_portfolio([_row()], selected_date=REGULAR_DAY, settings=settings)
    on_post = commit_portfolio([_row()], selected_date=POSTSEASON_DAY, settings=settings)
    assert on_regular["positions"][0]["sizing"]["blend_beta"] == 0.4
    assert on_post["positions"][0]["sizing"]["blend_beta"] == 0.0
