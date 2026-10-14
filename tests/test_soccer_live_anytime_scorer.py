"""Live anytime-goalscorer rows get a LIVE model probability.

Lane `soccer-live-anytime-scorer` (2026-10-12). On 10-10, 1,986 of 2,030 live soccer
props reaching the opportunity lane were dropped as hold-restatement EV for want of a
model edge: the live re-sim published shots / SOT / assists only, and the join skipped
line-less rows (miss_line 1,558 of 3,477). Path under test:
live_lens.project_live_player_props -> soccer_live_prop_index -> attach_live_projections.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import live_projection_join as J
from syndicate.features.shared import soccer_live_gameline_source as src
from syndicate.features.soccer.features import live_lens as LL

_NEUTRAL = {"attack_rating": 0.0, "defense_rating": 0.0}


def _state(**over):
    base = {
        "event_id": "e1", "home_team": "Home FC", "away_team": "Away FC",
        "half": 2, "clock_remaining": 1800, "score_home": 0, "score_away": 0,
        "home_red_cards": 0, "away_red_cards": 0, "home_corners_so_far": 2, "away_corners_so_far": 2,
        "player_stats": {
            "h1": {"player_id": "h1", "player_name": "Home Striker", "shots_so_far": 1, "goals_so_far": 0},
            "h2": {"player_id": "h2", "player_name": "Home Scorer", "shots_so_far": 2, "goals_so_far": 1},
        },
    }
    base.update(over)
    return base


def _rows():
    return [
        {"player_id": "h1", "player_name": "Home Striker", "team": "Home FC", "shots_per90": 3.0, "xg_per90": 0.5},
        {"player_id": "h2", "player_name": "Home Scorer", "team": "Home FC", "shots_per90": 2.0, "xg_per90": 0.3},
    ]


def _project(**state_over):
    return {p.player_id: p for p in LL.project_live_player_props(
        _state(**state_over), home_rating=_NEUTRAL, away_rating=_NEUTRAL,
        home_player_rows=_rows(), away_player_rows=[], simulations=60, seed=2)}


def test_the_resumed_sim_publishes_a_live_anytime_probability():
    p = _project()["h1"]
    prob = p.goals_over_probabilities["0.5"]
    assert 0.0 < prob < 1.0
    assert "goals_over_probabilities" in p.to_dict()


def test_a_goal_already_scored_banks_the_bet():
    assert _project()["h2"].goals_over_probabilities["0.5"] == 1.0


def test_less_time_left_means_a_lower_probability():
    late = _project(clock_remaining=120)["h1"].goals_over_probabilities["0.5"]
    early = _project(half=1, clock_remaining=2400)["h1"].goals_over_probabilities["0.5"]
    assert late < early


def test_remaining_fraction_reads_the_half_and_clock():
    assert LL._remaining_match_fraction({"half": 1, "clock_remaining": 2700}) == 1.0
    assert LL._remaining_match_fraction({"half": 2, "clock_remaining": 1350}) == 0.25
    assert LL._remaining_match_fraction({}) == 0.0


def _index(prop, monkeypatch):
    monkeypatch.setattr(src, "soccer_live_games", lambda date, data_root=None: [{"live_player_props": [prop]}])
    return src.soccer_live_prop_index("2026-10-12")


def _anytime_row(**over):
    row = {"sport": "soccer", "kind": "prop", "market": "player_goal_scorer_anytime", "player_name": "Home Striker",
           "line": None, "sides": ["yes"], "game": {"state": "live"},
           "modelled_fair": {"yes": 0.25}}
    row.update(over)
    return row


def test_a_line_less_anytime_row_joins_the_live_goals_key(monkeypatch):
    prop = LL.LivePlayerPropProjection(
        player_id="h1", player_name="Home Striker", side="home", shots_so_far=1,
        projected_remainder_shots=1.0, projected_final_shots=2.0,
        goals_so_far=0, projected_final_goals=0.31, goals_over_probabilities={"0.5": 0.27}).to_dict()
    indexed = _index(prop, monkeypatch)
    assert ("home striker", "player_goals", 0.5) in indexed["index"]
    grid = [_anytime_row()]
    coverage = J.attach_live_projections(grid, indexed)
    assert coverage["rows_live_projected"] == 1
    assert coverage["miss_no_line"] == 0


def test_off_is_not_on_without_the_yes_no_table_the_row_is_a_line_miss(monkeypatch):
    """Reachability: empty the table and the same row falls back to miss_no_line, so
    the projection above is the new mapping's doing."""
    prop = LL.LivePlayerPropProjection(
        player_id="h1", player_name="Home Striker", side="home", shots_so_far=1,
        projected_remainder_shots=1.0, projected_final_shots=2.0,
        goals_over_probabilities={"0.5": 0.27}).to_dict()
    indexed = _index(prop, monkeypatch)
    monkeypatch.setattr(J, "_YES_NO_LINE_KEYS", {})
    coverage = J.attach_live_projections([_anytime_row()], indexed)
    assert coverage["rows_live_projected"] == 0
    assert coverage["miss_no_line"] == 1


def test_first_and_last_scorer_are_not_mapped_onto_goals():
    """They are races, not a goal count."""
    assert "player_first_goal_scorer" not in J._YES_NO_LINE_KEYS
    assert "player_last_goal_scorer" not in J._YES_NO_LINE_KEYS


def test_a_live_anytime_row_reaches_a_MODELLED_EDGE_not_just_a_projection():
    """The lane's point is the EDGE, and anytime is a yes-only market: no de-vig can answer, so the one-sided
    branch must price it against the pregame modelled fair (10-12 20:55Z: 25 of 26 projected soccer rows were
    withheld `no_fair_value_one_sided_quote`). Live P(score) 0.27 vs modelled fair 0.12 -> +15.0 points."""
    from syndicate.features.shared.book_margin_model import EDGE_FIELD

    row = _anytime_row(modelled_fair={"yes": {"fair_method": "book_margin_model", "fair_probability": 0.12,
                                              "basis": "measured_hold", "assumed_hold_pct": 8.0}})
    row["projection"] = {"basis": "soccer_sim", "side": "yes", "market_fair_unavailable_reason": "one_sided_quote"}
    indexed = {"index": {("home striker", "player_goals", 0.5): {
                   "live_prob_over": 0.27, "live_projection": 0.31, "model_prob_over": None,
                   "actual_so_far": 0, "side": "over"}},
               "players_seen": {"home striker"},
               "lines_by_player_market": {("home striker", "player_goals"): {0.5}}}
    coverage = J.attach_live_projections([row], indexed)
    assert coverage["rows_live_projected"] == 1
    assert coverage.get("rows_live_edged_modelled") == 1
    assert row["projection"].get(EDGE_FIELD) == pytest.approx(15.0)
