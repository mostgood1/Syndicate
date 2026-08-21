"""Soccer's live re-sim, adapted to the gameline-index contract.

Anchored to the REAL artifact shape written by scripts/poll_soccer_live_state.py
(`games[event_id].projection` = LiveMatchProjection.to_dict()).
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import soccer_live_gameline_source as src


def _projection(**over):
    base = {
        "simulations": 400,
        "home_win_probability": 0.62,
        "draw_probability": 0.23,
        "away_win_probability": 0.15,
        "projected_final_home_goals": 1.9,
        "projected_final_away_goals": 1.1,
        "projected_final_total": 3.0,
        "over_2_5_probability": 0.58,
        "both_teams_scored_probability": 0.61,
        "home_red_card_applied": False,
        "away_red_card_applied": True,
    }
    base.update(over)
    return base


def _write(root, league, date, games, *, match_box=None):
    d = root / "soccer_source" / league / "api" / "live_state"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"live_state_{date}.json").write_text(
        json.dumps({
            "league": league,
            "date": date,
            "generated_at": "2026-08-21T19:20:00+00:00",
            "count": len(games),
            "games": games,
            "match_box": match_box or {},
        }),
        encoding="utf-8",
    )


@pytest.fixture
def root(tmp_path):
    return tmp_path


def _index(root, date="2026-08-21"):
    return src.soccer_live_gameline_index(date, data_root=root)


def test_in_play_match_is_indexed_on_full_names(root):
    _write(root, "epl", "2026-08-21", {
        "401879301": {
            "home_team": "Arsenal", "away_team": "Coventry City",
            "score_home": 2, "score_away": 0,
            "status_display_clock": "63'",
            "projection": _projection(),
        }
    })
    idx = _index(root)
    assert list(idx) == [("coventry city", "arsenal")]
    hit = idx[("coventry city", "arsenal")]
    assert hit["home_win_prob"] == 0.62
    assert hit["sims_run"] == 400
    assert hit["clock"] == "63'"
    assert hit["live_score"] == {"home": 2, "away": 0}


def test_full_three_way_vector_is_published(root):
    """The whole reason this module exists. A DRAW row priced against
    `home_win_prob` compares one outcome's probability to another outcome's
    price and calls the difference an edge."""
    _write(root, "epl", "2026-08-21", {
        "1": {"home_team": "Arsenal", "away_team": "Coventry City",
              "projection": _projection()},
    })
    sides = _index(root)[("coventry city", "arsenal")]["side_probabilities"]
    assert sides == {"home": 0.62, "draw": 0.23, "away": 0.15}
    assert abs(sum(sides.values()) - 1.0) < 0.01


def test_match_box_only_match_is_not_indexed(root):
    """`match_box` spans in+post and carries a BOX SCORE with no projection.
    Gate 1 reads it deliberately; this must not, or a FINISHED match would get
    a live price."""
    _write(root, "la_liga", "2026-08-21", {}, match_box={
        "9": {"home_team": "Real Betis", "away_team": "Real Sociedad",
              "status_state": "post", "final": True,
              "score_home": 1, "score_away": 1},
    })
    assert _index(root) == {}


def test_no_distributions_are_claimed(root):
    """The live projection has summary probabilities and means only. Empty
    dicts are what every consumer reads as 'no shape', so totals/spreads get
    refused by name instead of answered from a mean."""
    _write(root, "epl", "2026-08-21", {
        "1": {"home_team": "Arsenal", "away_team": "Coventry City",
              "projection": _projection()},
    })
    hit = _index(root)[("coventry city", "arsenal")]
    assert hit["total_runs_dist"] == {}
    assert hit["margin_dist"] == {}


def test_totals_are_analytic_at_2_5_only(root):
    _write(root, "epl", "2026-08-21", {
        "1": {"home_team": "Arsenal", "away_team": "Coventry City",
              "projection": _projection()},
    })
    am = _index(root)[("coventry city", "arsenal")]["analytic_markets"]
    assert am["totals"]["line"] == 2.5
    assert am["totals"]["prob_over"] == 0.58


def test_absent_over_probability_publishes_no_analytic_market(root):
    """An absent probability must not become a line priced at None."""
    _write(root, "epl", "2026-08-21", {
        "1": {"home_team": "Arsenal", "away_team": "Coventry City",
              "projection": _projection(over_2_5_probability=None)},
    })
    assert _index(root)[("coventry city", "arsenal")]["analytic_markets"] == {}


def test_home_margin_is_derived_only_when_both_goals_exist(root):
    _write(root, "epl", "2026-08-21", {
        "1": {"home_team": "Arsenal", "away_team": "Coventry City",
              "projection": _projection()},
        "2": {"home_team": "Fulham", "away_team": "Chelsea",
              "projection": _projection(projected_final_away_goals=None)},
    })
    idx = _index(root)
    assert idx[("coventry city", "arsenal")]["home_margin"] == pytest.approx(0.8)
    assert idx[("chelsea", "fulham")]["home_margin"] is None


def test_unusable_probability_is_skipped_not_clamped(root):
    _write(root, "epl", "2026-08-21", {
        "1": {"home_team": "Arsenal", "away_team": "Coventry City",
              "projection": _projection(home_win_probability=1.7)},
        "2": {"home_team": "Fulham", "away_team": "Chelsea",
              "projection": _projection(home_win_probability=None)},
    })
    assert _index(root) == {}


def test_absent_root_returns_empty_rather_than_raising(tmp_path):
    assert src.soccer_live_gameline_index("2026-08-21", data_root=tmp_path / "nope") == {}


def test_sims_run_is_carried_because_soccer_actually_has_one(root):
    """WNBA publishes no simsRun and is withheld by REASON_UNUSABLE_SIMS.
    Soccer's n is real (400 on the 2026-08-21 artifacts), so it must reach the
    pricer -- and must never be invented when absent."""
    _write(root, "epl", "2026-08-21", {
        "1": {"home_team": "Arsenal", "away_team": "Coventry City",
              "projection": _projection(simulations=None)},
    })
    assert _index(root)[("coventry city", "arsenal")]["sims_run"] is None
