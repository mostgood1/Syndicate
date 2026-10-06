"""Lane `football-scenario-calibration` H2: fourth down decided from measured behaviour.

OFF (default): FG ladder -> punt ladder -> go as the residual, and the FG ladder never
reads yards-to-go. ON: one draw of go/fg/punt from `situation_model.FOURTH_DOWN_TABLES`
and a measured conversion rate.
"""
from __future__ import annotations

from dataclasses import replace
from random import Random

from syndicate.features.football.sim_engine.smartsim2 import drive_simulator as D
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE_DEFAULT
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE_DEFAULT
from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state
from syndicate.features.football.sim_engine.smartsim2.situation_model import (
    FOURTH_DOWN_TABLES,
    fourth_down_buckets,
    fourth_down_table,
)
from syndicate.features.shared.calibration_profile_store import profile_with_overrides

ON_NFL = replace(NFL_CALIBRATION_PROFILE_DEFAULT, fourth_down_decision_model=True)
ON_NCAAF = replace(NCAAF_CALIBRATION_PROFILE_DEFAULT, fourth_down_decision_model=True)


def _state(fp, togo, quarter=2, clock=600, home=0, away=0):
    return build_initial_possession_state(home_team="H", away_team="A", field_position=fp, down=4, distance=togo,
                                          quarter=quarter, clock_remaining=clock, score_home=home, score_away=away)


def test_default_is_off_and_round_trips():
    assert NFL_CALIBRATION_PROFILE_DEFAULT.fourth_down_decision_model is False
    assert NCAAF_CALIBRATION_PROFILE_DEFAULT.fourth_down_decision_model is False
    back = profile_with_overrides(NFL_CALIBRATION_PROFILE_DEFAULT, ON_NFL.to_dict())
    assert back.fourth_down_decision_model is True


def test_tables_are_complete_probability_tables():
    for sport in ("nfl", "ncaaf"):
        t = FOURTH_DOWN_TABLES[sport]
        assert len(t["decision"]) == 7 * 6
        assert all(abs(sum(v) - 1.0) < 2e-3 and min(v) >= 0 for v in t["decision"].values())
        assert all(0.0 < p < 1.0 for p in t["conversion"].values())
        # conversion falls with distance -- the measured shape, not an assumption
        conv = [t["conversion"][k] for k in range(6)]
        assert conv[0] > conv[2] > conv[5]


def test_profile_name_selects_the_sport():
    assert fourth_down_table("ncaaf") is FOURTH_DOWN_TABLES["ncaaf"]
    assert fourth_down_table("nfl") is FOURTH_DOWN_TABLES["nfl"]


def test_draw_reproduces_the_table_cell():
    """4th-and-1 at the opp 15: the draw frequencies are the table's, for each sport."""
    for prof, sport in ((ON_NFL, "nfl"), (ON_NCAAF, "ncaaf")):
        st = _state(85, 1)
        rng = Random(1)
        n = 20000
        counts = {"go": 0, "fg": 0, "punt": 0}
        for _ in range(n):
            counts[D._fourth_down_draw(st, rng, prof)] += 1
        p_go, p_fg, _ = FOURTH_DOWN_TABLES[sport]["decision"][fourth_down_buckets(85, 1)]
        assert abs(counts["go"] / n - p_go) < 0.015 and abs(counts["fg"] / n - p_fg) < 0.015


def test_the_bug_off_kicks_short_yardage_in_range_and_on_does_not():
    """OFF, the FG ladder ignores to-go: 4th-and-1 at the opp 15 kicks almost always."""
    st = _state(85, 1)
    rng = Random(2)
    off_kicks = sum(D._field_goal_decision(st, None, rng, NFL_CALIBRATION_PROFILE_DEFAULT) for _ in range(2000)) / 2000
    rng = Random(2)
    on_kicks = sum(D._fourth_down_draw(st, rng, ON_NFL) == "fg" for _ in range(2000)) / 2000
    assert off_kicks > 0.9 and on_kicks < 0.4


def test_conversion_uses_the_measured_rate_without_the_multiplier():
    assert NCAAF_CALIBRATION_PROFILE_DEFAULT.fourth_down_conversion_multiplier != 1.0
    st = _state(50, 1)
    assert D._fourth_down_conversion(st, ON_NCAAF) == FOURTH_DOWN_TABLES["ncaaf"]["conversion"][0]


def test_reachability_on_differs_from_off_and_goes_for_it_more():
    def go_rate(prof):
        go = n = 0
        for seed in range(1, 41):
            out = simulate_game(SmartSim2SimulationInput(home_team="H", away_team="A", seed=seed), profile=prof)
            for d in out.drive_log:
                for s in d.get("steps") or []:
                    st = s["start_state"]
                    if st["down"] == 4 and st["field_position"] >= 70 and st["distance"] <= 2:
                        n += 1
                        go += str(getattr(s["outcome"], "value", s["outcome"])) not in (
                            "field_goal", "missed_field_goal", "punt")
        return go / max(1, n), n
    off, n_off = go_rate(NFL_CALIBRATION_PROFILE_DEFAULT)
    on, n_on = go_rate(ON_NFL)
    assert n_off > 10 and n_on > 10
    assert on > off + 0.3
