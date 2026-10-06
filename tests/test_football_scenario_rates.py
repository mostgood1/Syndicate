"""Lane `football-scenario-calibration`: the scenario counters both sides share."""
from __future__ import annotations

from random import Random

from scripts import football_scenario_rates as F
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game


def _drive(**kw):
    base = dict(side="home", q=1, gsr=3600, diff=0, fp=25, result="PUNT", pts=0, plays=5, secs=150,
                rz=False, prev="half")
    base.update(kw)
    return F.Drive(**base)


def test_garbage_time_is_q4_and_sport_threshold():
    c = {}
    F.add_drive(c, _drive(q=4, diff=17, result="TD", pts=7), "nfl")
    F.add_drive(c, _drive(q=4, diff=17), "ncaaf")          # 17 < 21: not garbage in NCAAF
    F.add_drive(c, _drive(q=3, diff=30), "nfl")            # Q3: never garbage
    assert c["gt:lead:drives"] == 1 and c["gt:lead:pts"] == 7
    assert c["drives"] == 3


def test_overtime_drives_are_kept_out_of_regulation_rates():
    c = {}
    F.add_drive(c, _drive(q=5, result="TD", pts=7), "nfl")
    assert "drives" not in c and c["ot:drives"] == 1 and c["ot:pts"] == 7


def test_fourth_down_and_field_goal_buckets():
    c = {}
    F.add_drive(c, _drive(fourths=[(30, 1, "punt"), (75, 4, "fg")], fgs=[(42, True), (52, False)]), "nfl")
    assert c["4th:own|1-2:punt"] == 1 and c["4th:opp29in|3-5:fg"] == 1
    assert c["fg:40-49:made"] == 1 and c["fg:50+:att"] == 1 and "fg:50+:made" not in c


def test_sim_drives_reads_a_real_engine_output():
    """Reachability of the SIM side: the records come from a real `simulate_game`."""
    out = simulate_game(SmartSim2SimulationInput(home_team="A", away_team="B", seed=3), rng=Random(3))
    drives = F.sim_drives(out)
    assert len(drives) == len(out.drive_log) > 10
    assert {d.side for d in drives} == {"home", "away"}
    reg = [d for d in drives if d.q <= 4]
    # drive points reconcile to the final score: the sim has no non-offensive scoring
    assert sum(d.pts for d in drives) == out.final_score["home"] + out.final_score["away"]
    assert all(1 <= d.fp <= 99 for d in reg)
    assert any(d.prev == "score" for d in reg) and reg[0].prev == "half"


def test_accumulator_matches_counter_of_its_drives():
    out = simulate_game(SmartSim2SimulationInput(home_team="A", away_team="B", seed=5), rng=Random(5))
    acc = F.ScenarioAccumulator("nfl")
    acc.add(out)
    assert acc.game["g:n"] == 1 and acc.game["g:nonoff"] == 0
    home = [d for d in F.sim_drives(out) if d.side == "home" and d.q <= 4]
    assert acc.side["home"]["drives"] == len(home)
    assert acc.ratings is not None
