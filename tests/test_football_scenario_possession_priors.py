"""Lane `football-scenario-calibration` H4: drive priors read the teams on the field.

OFF (default) `build_drive_priors` seeds EVERY drive from the home offense and the
home team's own defense. `possession_aware_priors` ON uses the possessing offense
and the opposing defense; `home_field_bonus` is the re-fit's home-field lever.
"""
from __future__ import annotations

from dataclasses import replace

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE_DEFAULT
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state
from syndicate.features.shared.calibration_profile_store import profile_with_overrides

OFF = NFL_CALIBRATION_PROFILE_DEFAULT
ON = replace(OFF, possession_aware_priors=True)


def _success(inp, owner, profile):
    st = build_initial_possession_state(home_team="H", away_team="A", owner=owner)
    return build_drive_priors(inp, possession_state=st, profile=profile).drive_success_probability


def _inp(**kw):
    return SmartSim2SimulationInput(home_team="H", away_team="A", seed=1, **kw)


def test_defaults_and_round_trip():
    assert OFF.possession_aware_priors is False and OFF.home_field_bonus == 0.0
    back = profile_with_overrides(OFF, replace(ON, home_field_bonus=0.05).to_dict())
    assert back.possession_aware_priors is True and back.home_field_bonus == 0.05


def test_off_is_the_defect_away_drive_ignores_the_away_offense():
    base = _success(_inp(), "away", OFF)
    assert _success(_inp(away_offense_rating=0.3), "away", OFF) == base
    assert _success(_inp(home_offense_rating=0.3), "away", OFF) > base


def test_on_away_drive_moves_with_away_offense_and_home_defense_only():
    base = _success(_inp(), "away", ON)
    assert _success(_inp(away_offense_rating=0.3), "away", ON) > base
    assert _success(_inp(home_defense_rating=0.3), "away", ON) < base       # better home defense
    assert _success(_inp(home_offense_rating=0.3), "away", ON) == base
    assert _success(_inp(away_defense_rating=0.3), "away", ON) == base


def test_on_home_drive_faces_the_away_defense():
    base = _success(_inp(), "home", ON)
    assert _success(_inp(away_defense_rating=0.3), "home", ON) < base
    assert _success(_inp(home_defense_rating=0.3), "home", ON) == base


def test_home_field_bonus_helps_only_the_home_offense():
    hfb = replace(ON, home_field_bonus=0.1)
    assert _success(_inp(), "home", hfb) > _success(_inp(), "home", ON)
    assert _success(_inp(), "away", hfb) == _success(_inp(), "away", ON)


def test_reachability_and_home_edge_through_the_game():
    inp = [SmartSim2SimulationInput(home_team="H", away_team="A", seed=s, away_offense_rating=0.2) for s in range(1, 81)]
    off = [simulate_game(i).final_score for i in inp]
    on = [simulate_game(i, profile=ON).final_score for i in inp]
    assert off != on
    # a stronger AWAY offense must score more ON than OFF (OFF its drives ignored it)
    assert sum(s["away"] for s in on) > sum(s["away"] for s in off)

def test_home_field_bonus_moves_the_home_margin():
    # Not paired seed-by-seed (the rng streams diverge), so it needs volume: measured
    # +0.1 -> about +2.3 pts over 1,000 games (SE 0.4). 400 games at +0.2 vs 0.
    inp = [SmartSim2SimulationInput(home_team="H", away_team="A", seed=s) for s in range(1, 401)]
    def margin(profile):
        return sum(o["home"] - o["away"] for o in (simulate_game(i, profile=profile).final_score for i in inp)) / len(inp)
    assert margin(replace(ON, home_field_bonus=0.2)) - margin(ON) > 1.5
