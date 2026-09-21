# -*- coding: utf-8 -*-
"""One set of simulated paths for the live projection AND the live player props (lane soccer-live-shared-paths).

`project_live_player_props` used to re-simulate exactly the matches `project_live_match` had just simulated (same
state, ratings, seeds 1..n, profile and stoppage rule): 25% of a live tick, timed 2026-09-19. The poller now simulates
once. The claim is that NO NUMBER MOVES, so the reference here is the PRE-CHANGE code itself: `GOLDEN` was produced by
origin/main's `live_lens.py` before this change (loaded as a separate module) on the two fixtures below, 15 sims.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import poll_soccer_live_state as poller  # noqa: E402
from syndicate.features.soccer.features import live_lens as ll  # noqa: E402

FIXTURES = {
    "red_card_second_half": {
        "state": {"home_team": "Home FC", "away_team": "Away FC", "half": 2, "clock_remaining": 1500.0, "score_home": 1,
                  "score_away": 1, "home_red_cards": 0, "away_red_cards": 1, "home_corners_so_far": 4, "away_corners_so_far": 3,
                  "player_stats": {"h1": {"shots_so_far": 2, "shots_on_target_so_far": 1, "assists_so_far": 0},
                                   "a1": {"shots_so_far": 1, "shots_on_target_so_far": 0, "assists_so_far": 1}}},
        "home": {"attack_rating": 0.12, "defense_rating": -0.05}, "away": {"attack_rating": -0.08, "defense_rating": 0.04},
    },
    "neutral_first_half": {
        "state": {"home_team": "Home FC", "away_team": "Away FC", "half": 1, "clock_remaining": 1200.0, "score_home": 0,
                  "score_away": 0, "home_red_cards": 0, "away_red_cards": 0, "home_corners_so_far": 1, "away_corners_so_far": 2,
                  "player_stats": {}},
        "home": {"attack_rating": 0.0, "defense_rating": 0.0}, "away": {"attack_rating": 0.0, "defense_rating": 0.0},
    },
}
HOME_ROWS = [{"player_id": "h1", "player_name": "Home Striker", "team": "Home FC", "shots_per90": 3.0, "xg_per90": 0.5},
             {"player_id": "h2", "player_name": "Home Winger", "team": "Home FC", "shots_per90": 1.5, "xg_per90": 0.2}]
AWAY_ROWS = [{"player_id": "a1", "player_name": "Away Striker", "team": "Away FC", "shots_per90": 2.0, "xg_per90": 0.3}]
SIMS = 15

# Produced by origin/main's live_lens.py (pre-change), 2026-09-19, on FIXTURES / HOME_ROWS / AWAY_ROWS / SIMS.
GOLDEN = json.loads(r'''{"neutral_first_half": {"projection": {"away_red_card_applied": false, "away_win_probability": 0.1333, "both_teams_scored_probability": 0.4, "corners_basis": "sim", "draw_probability": 0.2667, "home_red_card_applied": false, "home_win_probability": 0.6, "over_2_5_probability": 0.3333, "projected_away_corners": 6.0, "projected_final_away_goals": 0.6667, "projected_final_home_goals": 1.3333, "projected_final_total": 2.0, "projected_home_corners": 5.7333, "projected_total_corners": 11.7333, "scoreline_probabilities": {"0-0": 0.1333, "0-1": 0.0667, "1-0": 0.2, "1-1": 0.0667, "2-0": 0.2, "2-1": 0.2, "2-2": 0.0667, "2-3": 0.0667}, "sim_projected_away_corners": null, "sim_projected_home_corners": null, "sim_projected_total_corners": null, "simulations": 15}, "props": [{"assists_over_probabilities": {"0.5": 0.0, "1.5": 0.0}, "assists_so_far": 0, "player_id": "h1", "player_name": "Home Striker", "projected_final_assists": 0.0, "projected_final_shots": 6.3111, "projected_final_shots_on_target": 2.0827, "projected_remainder_shots": 6.3111, "shots_on_target_over_probabilities": {"0.5": 0.8754, "1.5": 0.6159, "2.5": 0.3457, "3.5": 0.1581, "4.5": 0.0604}, "shots_on_target_so_far": 0, "shots_over_probabilities": {"0.5": 0.9982, "1.5": 0.9867, "2.5": 0.9506, "3.5": 0.8745, "4.5": 0.7544}, "shots_so_far": 0, "side": "home"}, {"assists_over_probabilities": {"0.5": 0.0, "1.5": 0.0}, "assists_so_far": 0, "player_id": "h2", "player_name": "Home Winger", "projected_final_assists": 0.0, "projected_final_shots": 3.1556, "projected_final_shots_on_target": 1.0413, "projected_remainder_shots": 3.1556, "shots_on_target_over_probabilities": {"0.5": 0.647, "1.5": 0.2794, "2.5": 0.0881, "3.5": 0.0216, "4.5": 0.0043}, "shots_on_target_so_far": 0, "shots_over_probabilities": {"0.5": 0.9574, "1.5": 0.8229, "2.5": 0.6107, "3.5": 0.3876, "4.5": 0.2115}, "shots_so_far": 0, "side": "home"}, {"assists_over_probabilities": {"0.5": 0.0, "1.5": 0.0}, "assists_so_far": 0, "player_id": "a1", "player_name": "Away Striker", "projected_final_assists": 0.0, "projected_final_shots": 7.8, "projected_final_shots_on_target": 2.574, "projected_remainder_shots": 7.8, "shots_on_target_over_probabilities": {"0.5": 0.9238, "1.5": 0.7276, "2.5": 0.475, "3.5": 0.2584, "4.5": 0.1189}, "shots_on_target_so_far": 0, "shots_over_probabilities": {"0.5": 0.9996, "1.5": 0.9964, "2.5": 0.9839, "3.5": 0.9515, "4.5": 0.8883}, "shots_so_far": 0, "side": "away"}]}, "red_card_second_half": {"projection": {"away_red_card_applied": true, "away_win_probability": 0.1333, "both_teams_scored_probability": 1.0, "corners_basis": "sim", "draw_probability": 0.2, "home_red_card_applied": false, "home_win_probability": 0.6667, "over_2_5_probability": 0.9333, "projected_away_corners": 3.8667, "projected_final_away_goals": 1.2667, "projected_final_home_goals": 2.0, "projected_final_total": 3.2667, "projected_home_corners": 7.2, "projected_total_corners": 11.0667, "scoreline_probabilities": {"1-1": 0.0667, "1-2": 0.1333, "2-1": 0.5333, "2-2": 0.1333, "3-1": 0.0667, "4-1": 0.0667}, "sim_projected_away_corners": null, "sim_projected_home_corners": null, "sim_projected_total_corners": null, "simulations": 15}, "props": [{"assists_over_probabilities": {"0.5": 0.0, "1.5": 0.0}, "assists_so_far": 0, "player_id": "h1", "player_name": "Home Striker", "projected_final_assists": 0.0, "projected_final_shots": 5.9111, "projected_final_shots_on_target": 2.2907, "projected_remainder_shots": 3.9111, "shots_on_target_over_probabilities": {"0.5": 1.0, "1.5": 0.7249, "2.5": 0.3699, "3.5": 0.1407, "4.5": 0.0422}, "shots_on_target_so_far": 1, "shots_over_probabilities": {"0.5": 1.0, "1.5": 1.0, "2.5": 0.98, "3.5": 0.9017, "4.5": 0.7486}, "shots_so_far": 2, "side": "home"}, {"assists_over_probabilities": {"0.5": 0.0, "1.5": 0.0}, "assists_so_far": 0, "player_id": "h2", "player_name": "Home Winger", "projected_final_assists": 0.0, "projected_final_shots": 1.9556, "projected_final_shots_on_target": 0.6453, "projected_remainder_shots": 1.9556, "shots_on_target_over_probabilities": {"0.5": 0.4755, "1.5": 0.137, "2.5": 0.0278, "3.5": 0.0043, "4.5": 0.0005}, "shots_on_target_so_far": 0, "shots_over_probabilities": {"0.5": 0.8585, "1.5": 0.5818, "2.5": 0.3113, "3.5": 0.1349, "4.5": 0.0487}, "shots_so_far": 0, "side": "home"}, {"assists_over_probabilities": {"0.5": 1.0, "1.5": 0.0}, "assists_so_far": 1, "player_id": "a1", "player_name": "Away Striker", "projected_final_assists": 1.0, "projected_final_shots": 3.4, "projected_final_shots_on_target": 0.792, "projected_remainder_shots": 2.4, "shots_on_target_over_probabilities": {"0.5": 0.5471, "1.5": 0.1883, "2.5": 0.0463, "3.5": 0.0088, "4.5": 0.0014}, "shots_on_target_so_far": 0, "shots_over_probabilities": {"0.5": 1.0, "1.5": 0.9093, "2.5": 0.6916, "3.5": 0.4303, "4.5": 0.2213}, "shots_so_far": 1, "side": "away"}]}}''')


def _run(fixture, paths=None):
    f = fixture
    projection = ll.project_live_match(f["state"], home_rating=f["home"], away_rating=f["away"], simulations=SIMS, paths=paths)
    props = ll.project_live_player_props(f["state"], home_rating=f["home"], away_rating=f["away"],
                                         home_player_rows=HOME_ROWS, away_player_rows=AWAY_ROWS, simulations=SIMS, paths=paths)
    return {"projection": projection.to_dict(), "props": [p.to_dict() for p in props]}


def _paths(fixture, **over):
    f = fixture
    return ll.simulate_live_paths(f["state"], home_rating=f["home"], away_rating=f["away"], simulations=over.pop("simulations", SIMS),
                                  **over)


# ---------------------------------------------------------------------------- no number moves

@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_without_paths_the_numbers_are_the_pre_change_codes(name):
    assert _run(FIXTURES[name]) == GOLDEN[name]


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_with_shared_paths_the_numbers_are_the_pre_change_codes(name, capsys):
    assert _run(FIXTURES[name], _paths(FIXTURES[name])) == GOLDEN[name]
    assert "SHARED_PATHS_MISMATCH" not in capsys.readouterr().out          # the paths were USED, not refused


# ---------------------------------------------------------------------------- foreign paths are refused

@pytest.mark.parametrize("change", [
    {"state": {"clock_remaining": 600.0}},
    {"state": {"score_home": 2}},
    {"state": {"home_red_cards": 1}},
    {"home": {"attack_rating": 0.2, "defense_rating": -0.05}},
    {"simulations": 14},
    {"seed": 2},
])
def test_paths_from_other_inputs_are_never_used(change, capsys):
    base = FIXTURES["red_card_second_half"]
    other = {"state": dict(base["state"], **change.get("state", {})), "home": change.get("home", base["home"]), "away": base["away"]}
    extra = {k: v for k, v in change.items() if k in ("simulations", "seed")}
    wrong = _paths(other, **extra)
    assert _run(base, wrong) == GOLDEN["red_card_second_half"]
    assert capsys.readouterr().out.count("SHARED_PATHS_MISMATCH") == 2      # both consumers refused them, by name


# ---------------------------------------------------------------------------- reachability: the poller shares them

def test_the_poller_simulates_each_match_once_for_both_consumers(monkeypatch, tmp_path):
    """Presence is not reachability: count what the production call site actually simulates. Per in-play match,
    n paths (shared by the projection and the props) + 2 x n for the goal windows = 3n; the pre-change code ran 4n."""
    state = dict(FIXTURES["red_card_second_half"]["state"], event_id="401900001", home_red_cards=0, away_red_cards=0,
                 home_shots_so_far=8, away_shots_so_far=4, home_shots_on_target_so_far=3, away_shots_on_target_so_far=1)
    monkeypatch.setattr(poller, "fetch_events", lambda *a, **k: [
        {"event_id": "401900001", "home_team": "Home FC", "away_team": "Away FC",
         "status_display_clock": "65'", "status_period": 2, "status_detail": "2nd Half"}])
    monkeypatch.setattr(poller, "build_live_state", lambda *a, **k: dict(state))
    monkeypatch.setattr(poller, "fetch_match_summary", lambda *a, **k: {})
    monkeypatch.setattr(poller, "_load_team_ratings", lambda *a, **k: {})
    monkeypatch.setattr(poller, "_fill_promoted", lambda *a, **k: None)
    monkeypatch.setattr(poller, "_load_player_rows", lambda *a, **k: HOME_ROWS + AWAY_ROWS)
    monkeypatch.setattr(poller, "_rating_for", lambda *a, **k: {"attack_rating": 0.0, "defense_rating": 0.0})
    monkeypatch.setattr(poller, "fotmob_momentum_block", lambda *a, **k: {"supported": False})
    monkeypatch.setattr(poller, "_build_match_boxes", lambda *a, **k: {})

    calls = []
    real = ll.simulate_match

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(ll, "simulate_match", counting)
    n = 5
    result = poller.poll_league("epl", "2026-09-19", source_root=tmp_path / "src", out_root=tmp_path / "out", simulations=n)
    game = result["games"]["401900001"]
    assert game["projection"]["simulations"] == n and game["live_player_props"]
    # n, not 3n: the projection and the props share one set of paths, and the two
    # goal windows are now READ OFF those same paths instead of simulating their
    # own truncated clocks (`goal_window_probabilities`).
    assert len(calls) == n


# ---------------------------------------------------------------------------- (B) the goal window's clock

@pytest.mark.parametrize("half,remaining,window", [
    (2, 1800.0, 300.0),
    (2, 1800.0, 600.0),
    (1, 1500.0, 600.0),
    (2, 400.0, 600.0),
    (2, 300.0, 300.0),
])
def test_a_goal_window_simulates_the_REAL_clock_and_is_cut_by_timestamp(monkeypatch, half, remaining, window):
    """It used to resume with `clock_remaining = window`, which is a different
    match: `situation_model.classify_urgency` reads that field, so a "next 5
    minutes" at the 60th minute was played as the last 5 minutes of a half.
    Measured 2026-09-21 (N=3000, neutral ratings): that ran 0.0183 low for
    next-5 and 0.0277 low for next-10 with a one-goal lead. The window is now
    taken out of a real-clock path by timestamp, so every simulation must see
    the match's own remaining clock -- plus the half's stoppage base, which is
    still to be played.
    """
    clocks = []
    real = ll.simulate_match

    def recording(*a, **k):
        clocks.append(k["initial_state"].clock_remaining)
        return real(*a, **k)

    monkeypatch.setattr(ll, "simulate_match", recording)
    state = {"home_team": "Home FC", "away_team": "Away FC", "half": half, "clock_remaining": remaining,
             "score_home": 0, "score_away": 0}
    p = ll.goal_in_window_probability(state, home_rating={}, away_rating={}, window_seconds=window, simulations=3)

    assert len(set(clocks)) == 1, clocks
    simulated = clocks[0]
    assert simulated > remaining, (simulated, remaining)          # the stoppage base is included
    assert simulated < remaining + 400.0, (simulated, remaining)  # and nothing else is
    assert 0.0 <= p <= 1.0


def test_a_longer_window_never_scores_lower_on_the_same_paths():
    """The windows come from ONE set of paths now, so this is exact rather than
    statistical: a goal inside 5 minutes is inside 10 minutes, every path."""
    state = {"home_team": "Home FC", "away_team": "Away FC", "half": 2, "clock_remaining": 1800.0,
             "score_home": 1, "score_away": 0}
    paths = ll.simulate_live_paths(state, home_rating={}, away_rating={}, simulations=40, seed=7)
    out = ll.goal_window_probabilities(paths, state, windows={"next_5": 300.0, "next_10": 600.0})
    assert out["next_5"] <= out["next_10"]


def test_a_window_that_reaches_the_half_end_counts_stoppage_goals():
    """The rule the old code had and this keeps: a window at or beyond the time
    left counts every goal still to come in the half, stoppage included, so it
    equals a window twice as long."""
    state = {"home_team": "Home FC", "away_team": "Away FC", "half": 2, "clock_remaining": 300.0,
             "score_home": 0, "score_away": 0}
    paths = ll.simulate_live_paths(state, home_rating={}, away_rating={}, simulations=40, seed=11)
    out = ll.goal_window_probabilities(paths, state, windows={"at_the_edge": 300.0, "well_past": 1200.0})
    assert out["at_the_edge"] == out["well_past"]
