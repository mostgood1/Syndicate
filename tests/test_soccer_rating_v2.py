"""RATING V2 (lane `soccer-team-strength`, shipped by user decision 2026-10-19).

Recency, a current-season blend and shrinkage toward a fitted promoted-club prior, on the raw deviation before
`clamp(0.55 * x, +-0.35)`. Evidence: `.syndicate/findings_2026-10-16_soccer_rating_inputs.md` (CUM arm) and
`.syndicate/findings_2026-10-19_soccer_rating_v2_sim.md` (through the real sim). These tests pin the mechanism,
the off switch, and reachability (off != on) through the production order.
"""

from __future__ import annotations

import pytest

from scripts.build_soccer_artifacts import (
    PROMOTED_TEAM_RATING,
    RATING_V2_PROMOTED_PRIOR,
    _fill_promoted,
    _gate_few_match,
    _rating_v2,
)
from syndicate.features.soccer.features.loaders import (
    RatingV2,
    _rating_for,
    compute_team_ratings,
    rating_from_raw,
    season_label,
)


def _row(team, date, season, xf, xa):
    return {"team": team, "date": date, "season": season, "xg_for": xf, "xg_against": xa}


def _history():
    rows = []
    # Old Club: 30 rows last season at league average, then 6 strong rows this season.
    for i in range(30):
        rows.append(_row("Old Club", f"2025-{8 + i // 10:02d}-{1 + i % 10 * 2:02d}", 2025, 1.4, 1.4))
    for i in range(6):
        rows.append(_row("Old Club", f"2026-08-{2 + 3 * i:02d}", 2026, 2.4, 0.8))
    # Steady: 36 rows at the mean in both seasons.
    for i in range(30):
        rows.append(_row("Steady", f"2025-{8 + i // 10:02d}-{1 + i % 10 * 2:02d}", 2025, 1.4, 1.4))
    for i in range(6):
        rows.append(_row("Steady", f"2026-08-{2 + 3 * i:02d}", 2026, 1.4, 1.4))
    # New Club: promoted, 3 rows this season only, very strong.
    for i in range(3):
        rows.append(_row("New Club", f"2026-08-{2 + 3 * i:02d}", 2026, 2.6, 0.6))
    return rows


def test_v2_none_is_the_original_rating_exactly():
    rows = _history()
    a = compute_team_ratings(rows, as_of="2026-10-01", window=45)
    b = compute_team_ratings(rows, as_of="2026-10-01", window=45, v2=None)
    assert a == b
    assert "rating_model" not in a["Old Club"]


def test_v2_moves_a_club_with_a_strong_current_season_up():
    rows = _history()
    v1 = compute_team_ratings(rows, as_of="2026-10-01", window=45)
    v2 = compute_team_ratings(rows, as_of="2026-10-01", window=45, v2=RatingV2())
    assert v2["Old Club"]["attack_rating"] > v1["Old Club"]["attack_rating"]
    assert v2["Old Club"]["rating_model"] == "v2_h40_c40_n5"
    assert v2["Old Club"]["matches"] == v1["Old Club"]["matches"], "row count is unchanged"


def test_shrinkage_pulls_a_promoted_club_toward_its_prior_not_the_mean():
    rows = _history()
    prior = (-0.30, -0.30)
    v1 = compute_team_ratings(rows, as_of="2026-10-01", window=45)
    v2 = compute_team_ratings(rows, as_of="2026-10-01", window=45, v2=RatingV2(promoted_prior=prior))
    assert v1["New Club"]["attack_rating"] == 0.35, "v1 rates 3 strong rows at the cap"
    # League mean xG for over the window rows: (30*1.4 + 6*2.4 + 36*1.4 + 3*2.6) / 75.
    mu = 114.6 / 75
    # PROMOTED (no earlier-season row): 3 rows against n0 5, so 5/8 of the weight is on the prior.
    x_new = 2.6 / mu - 1.0
    assert v2["New Club"]["attack_rating"] == pytest.approx(0.55 * (3 * x_new + 5 * prior[0]) / 8, abs=1e-4)
    # ESTABLISHED: shrunk toward 0 (the league mean), not toward the prior: 36 rows against n0 5.
    x_steady = 1.4 / mu - 1.0
    assert v2["Steady"]["attack_rating"] == pytest.approx(0.55 * 36 * x_steady / 41, abs=1e-4)


def test_recency_weights_the_latest_rows_more():
    rows = [_row("A", f"2025-08-{d:02d}", 2025, 1.0, 1.4) for d in range(1, 21)]
    rows += [_row("A", f"2025-09-{d:02d}", 2025, 2.0, 1.4) for d in range(1, 11)]
    rows += [_row("B", f"2025-08-{d:02d}", 2025, 1.4, 1.4) for d in range(1, 31)]
    flat = compute_team_ratings(rows, as_of="2025-10-01", window=45, v2=RatingV2(half_life=1e12, blend_c=1e12, shrink_n0=0.0))
    rec = compute_team_ratings(rows, as_of="2025-10-01", window=45, v2=RatingV2(half_life=5, blend_c=1e12, shrink_n0=0.0))
    assert rec["A"]["attack_rating"] > flat["A"]["attack_rating"]


def test_neutral_config_reproduces_v1():
    """Infinite half-life, no blend and no shrinkage is the original arithmetic."""
    rows = _history()
    v1 = compute_team_ratings(rows, as_of="2026-10-01", window=45)
    neutral = compute_team_ratings(rows, as_of="2026-10-01", window=45,
                                   v2=RatingV2(half_life=1e15, blend_c=1e15, shrink_n0=0.0))
    for team in v1:
        for field in ("attack_rating", "defense_rating"):
            assert neutral[team][field] == pytest.approx(v1[team][field], abs=1e-4)


def test_season_label_is_july_to_june():
    assert season_label("2026-07-01") == 2026
    assert season_label("2026-06-30") == 2025


def test_rating_v2_is_off_unless_enabled_and_covers_the_eight_measured_leagues_only(monkeypatch):
    monkeypatch.delenv("SYNDICATE_SOCCER_RATING_V2", raising=False)
    assert _rating_v2("epl") is None, "OFF by default until the real-sim A/B passes"
    monkeypatch.setenv("SYNDICATE_SOCCER_RATING_V2", "1")
    for league in RATING_V2_PROMOTED_PRIOR:
        assert _rating_v2(league) == RatingV2(promoted_prior=RATING_V2_PROMOTED_PRIOR[league])
    assert _rating_v2("championship") is None
    assert _rating_v2("mls") is None
    for off in ("0", "off", "false", "no"):
        monkeypatch.setenv("SYNDICATE_SOCCER_RATING_V2", off)
        assert _rating_v2("epl") is None


def test_v2_league_skips_the_hard_gate_and_fills_the_fitted_prior(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", "1")
    monkeypatch.setenv("SYNDICATE_SOCCER_RATING_V2", "1")
    ratings = {"Thin": {"attack_rating": 0.2, "defense_rating": 0.1, "matches": 4.0}}
    assert _gate_few_match(ratings, ["Thin"], "epl") == [], "shrinkage replaces the gate"
    assert ratings["Thin"]["attack_rating"] == 0.2
    assert _fill_promoted(ratings, ["Unseen FC"], "epl") == ["Unseen FC"]
    pa, pd = RATING_V2_PROMOTED_PRIOR["epl"]
    assert ratings["Unseen FC"]["attack_rating"] == rating_from_raw(pa)
    assert ratings["Unseen FC"]["defense_rating"] == rating_from_raw(pd)
    # No league -> the original behaviour (live and pregame callers that predate V2).
    legacy = {"Thin": {"attack_rating": 0.2, "defense_rating": 0.1, "matches": 4.0}}
    assert _gate_few_match(legacy, ["Thin"]) == ["Thin"]
    assert _fill_promoted(legacy, ["Unseen FC"]) == ["Unseen FC"]
    assert legacy["Unseen FC"]["attack_rating"] == PROMOTED_TEAM_RATING["attack_rating"]


def test_reachability_off_differs_from_on_through_the_production_order(monkeypatch):
    """REACHABILITY: the rating the sim reads (`_rating_for` after fill + gate) differs with V2 off vs on."""
    monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", "1")
    seen = {}
    for flag in ("0", "1"):
        monkeypatch.setenv("SYNDICATE_SOCCER_RATING_V2", flag)
        ratings = compute_team_ratings(_history(), as_of="2026-10-01", window=45, v2=_rating_v2("epl"))
        teams = ["Old Club", "New Club", "Unseen FC"]
        _fill_promoted(ratings, teams, "epl")
        _gate_few_match(ratings, teams, "epl")
        seen[flag] = tuple(_rating_for(ratings, t)[0]["attack_rating"] for t in teams)
    assert all(a != b for a, b in zip(seen["0"], seen["1"])), seen
