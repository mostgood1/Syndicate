"""todo #808, lane `football-end-of-half-fix`: the end-of-half fix for smartsim2.

Two new `CalibrationProfile` switches, both default OFF (pre-registered in
.syndicate/findings_2026-11-15_football_end_of_half_fix.md):

  * `q2_urgency_ignores_score` -- in Q2 the urgency field goal and the two-minute
    drill fire at any score (Q4 unchanged);
  * `end_of_half_clock` -- timeouts, the NFL two-minute warning and a measured clock
    for snaps in the last 120 s of Q2 / Q4.

OFF must be byte-identical to the engine before this change: the digests below
were computed from the unmodified code (lane commit 03d1066c6's tree) and are
pinned here. Reachability (ON != OFF) is asserted for each switch before any
behaviour test.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import (
    NFL_CALIBRATION_PROFILE_DEFAULT,
    CalibrationProfile,
)
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
    NCAAF_CALIBRATION_PROFILE_DEFAULT,
)
from syndicate.features.football.sim_engine.smartsim2.situation_model import (
    END_OF_HALF_CLOCK_TABLES,
    END_OF_HALF_WINDOW_SECONDS,
    URGENCY_END_GAME_PRESERVATION,
    URGENCY_HALFTIME_PRESERVATION,
    URGENCY_NEUTRAL,
    URGENCY_TWO_MINUTE,
    classify_urgency,
)
from syndicate.features.shared.calibration_profile_store import profile_with_overrides

NFL = NFL_CALIBRATION_PROFILE_DEFAULT
NCAAF = NCAAF_CALIBRATION_PROFILE_DEFAULT
FULL_NFL = replace(NFL, halftime_kickoff=True, q2_urgency_ignores_score=True, end_of_half_clock=True)
FULL_NCAAF = replace(NCAAF, halftime_kickoff=True, q2_urgency_ignores_score=True, end_of_half_clock=True)

# sha256 over `simulate_game(...).to_dict()` (json, sort_keys) for seeds 1..20, from
# the code BEFORE this change. Same inputs as `_digest` below.
PINNED_OFF_DIGESTS = {
    "nfl_pregame": "3a3a0e2a901be3fbed0ec477a0dbaf971b9289dcb0498fb70d26a3bb6411242e",
    "ncaaf_pregame": "2b2b1a67ebc85873c99b6113b5619a29c68954cb1a66762093bb744b50cb7c36",
    "nfl_q2_resume": "829377b6f019c173d91db07fe41cba975f11e0536ab7ffd1976bc8ec605c5f3a",
}
Q2_RESUME = dict(initial_quarter=2, initial_clock_seconds=150, initial_score_home=7, initial_score_away=10,
                 initial_possession_owner="away", initial_field_position=40)


def _inp(seed: int, **kw) -> SmartSim2SimulationInput:
    return SmartSim2SimulationInput(home_team="H", away_team="A", seed=seed, home_offense_rating=0.1,
                                    away_defense_rating=-0.05, **kw)


def _digest(profile: CalibrationProfile, **kw) -> str:
    h = hashlib.sha256()
    for seed in range(1, 21):
        h.update(json.dumps(simulate_game(_inp(seed, **kw), profile=profile).to_dict(), sort_keys=True).encode())
    return h.hexdigest()


def _steps(out):
    for drive in out.drive_log:
        for step in drive["steps"]:
            yield step


# --------------------------------------------------------------------- OFF / contract

def test_both_switches_default_off_on_both_sports():
    for prof in (NFL, NCAAF):
        assert prof.q2_urgency_ignores_score is False
        assert prof.end_of_half_clock is False


def test_fields_round_trip_through_the_artifact_dict():
    # A field missing from to_dict() loads back OFF and the switch is inert (the goal_line lesson).
    d = FULL_NFL.to_dict()
    assert d["q2_urgency_ignores_score"] is True and d["end_of_half_clock"] is True
    back = profile_with_overrides(NFL, d)
    assert back.q2_urgency_ignores_score is True and back.end_of_half_clock is True


@pytest.mark.parametrize("shape", sorted(PINNED_OFF_DIGESTS))
def test_off_is_byte_identical_to_the_pre_change_engine(shape):
    prof = NCAAF if shape.startswith("ncaaf") else NFL
    kw = Q2_RESUME if shape == "nfl_q2_resume" else {}
    assert _digest(prof, **kw) == PINNED_OFF_DIGESTS[shape]


def test_off_output_carries_no_timeout_keys():
    out = simulate_game(_inp(3), profile=NFL)  # OFF named: production's NFL profile has the clock ON since #808
    assert "timeouts_home" not in out.final_state and "timeouts_away" not in out.final_state
    assert "initial_timeouts_home" not in out.input_state
    assert all("timeouts_home" not in s["start_state"] for s in _steps(out))


# --------------------------------------------------------------------- reachability first

@pytest.mark.parametrize("field", ["q2_urgency_ignores_score", "end_of_half_clock"])
def test_reachability_each_switch_alone_changes_the_output(field):
    for base in (NFL, NCAAF):
        on = replace(base, **{field: True})
        off_scores = [simulate_game(_inp(s), profile=base).to_dict() for s in range(1, 31)]
        on_scores = [simulate_game(_inp(s), profile=on).to_dict() for s in range(1, 31)]
        assert off_scores != on_scores, f"{field} is inert on {base.name}"


# --------------------------------------------------------------------- part 2: Q2 ignores the score

def test_two_minute_drill_in_q2_ignores_the_score_only_when_on():
    kw = dict(quarter=2, seconds_remaining=100, score_differential=14, yardline=60)
    assert classify_urgency(**kw) == URGENCY_NEUTRAL
    assert classify_urgency(**kw, q2_ignores_score=True) == URGENCY_TWO_MINUTE
    # the halftime kneel still comes first
    kneel = dict(quarter=2, seconds_remaining=40, score_differential=3, yardline=30)
    assert classify_urgency(**kneel, q2_ignores_score=True) == URGENCY_HALFTIME_PRESERVATION
    # Q4 is unchanged: a leader runs out the clock, a trailer by 8+ is not in the drill
    assert classify_urgency(quarter=4, seconds_remaining=100, score_differential=14, yardline=60,
                            q2_ignores_score=True) == URGENCY_END_GAME_PRESERVATION
    assert classify_urgency(quarter=4, seconds_remaining=100, score_differential=-10, yardline=60,
                            q2_ignores_score=True) == classify_urgency(quarter=4, seconds_remaining=100,
                                                                       score_differential=-10, yardline=60)


def _first_step(profile, **kw):
    return next(_steps(simulate_game(_inp(1, **kw), profile=profile)))


def test_q2_urgency_field_goal_fires_when_leading_only_when_on():
    # Q2, 0:45 left, home leads by 10 at the opponent's 25 (field goal range): a Q4 rule
    # says "do not kick"; the league kicks here at any score.
    kw = dict(initial_quarter=2, initial_clock_seconds=45, initial_score_home=17, initial_score_away=7,
              initial_possession_owner="home", initial_field_position=75)
    on = replace(NFL, q2_urgency_ignores_score=True)
    assert _first_step(on, **kw)["outcome"] in ("field_goal", "missed_field_goal")
    assert _first_step(NFL, **kw)["outcome"] not in ("field_goal", "missed_field_goal")
    # Q4 with the same lead: unchanged by the switch (no urgency kick)
    kw4 = dict(kw, initial_quarter=4)
    assert _first_step(on, **kw4)["outcome"] == _first_step(NFL, **kw4)["outcome"]


def test_amendment_3_q2_early_down_kick_waits_for_the_last_running_play_with_the_clock_on():
    both = replace(NFL, q2_urgency_ignores_score=True, end_of_half_clock=True)
    base = dict(initial_quarter=2, initial_score_home=17, initial_score_away=7, initial_possession_owner="home",
                initial_field_position=75)
    # 45 s left on 1st down in range: one more play fits, so no kick yet
    assert _first_step(both, initial_clock_seconds=45, **base)["outcome"] not in ("field_goal", "missed_field_goal")
    # 10 s left: kick now
    assert _first_step(both, initial_clock_seconds=10, **base)["outcome"] in ("field_goal", "missed_field_goal")
    # 4th down at 45 s: the <= 90 s rule is unchanged
    assert _first_step(both, initial_clock_seconds=45, initial_down=4, initial_distance=6,
                       **base)["outcome"] in ("field_goal", "missed_field_goal")
    # Q4: unchanged by the rule (a tied game at 45 s in range kicks on 1st down, as before)
    q4 = dict(base, initial_quarter=4, initial_score_home=10, initial_score_away=10)
    assert _first_step(both, initial_clock_seconds=45, **q4)["outcome"] in ("field_goal", "missed_field_goal")


# --------------------------------------------------------------------- part 3: the clock

def test_tables_have_every_cell_the_engine_reads():
    pooled = {"td", "fg_good", "fg_miss", "punt", "turnover", "tod", "safety", "penalty", "incomplete", "oob",
              "spike", "to_spike", "2_kneel", "4_kneel"}
    bucketed = {f"{q}_{c}" for q in (2, 4) for c in ("to_off", "to_def", "run_hurry", "run_preserve")}
    qm = {"2_hurry", "2_preserve", "4_hurry", "4_preserve"}
    zones = {f"{q}_{z}" for q in (2, 4) for z in ("own", "mid", "range")}
    for sport, table in END_OF_HALF_CLOCK_TABLES.items():
        assert pooled <= set(table["delta"]), sport
        assert "kneel_live" not in table["delta"]  # Amendment 4: the formula's value is table["kneel_live"]
        assert 0 < table["kneel_live"] < 10
        if table["first_down_stop"]:
            assert "first_down" in table["delta"]
        for mean, sd in table["delta"].values():
            assert mean > 0 and sd >= 0
        assert bucketed <= set(table["delta_by_bucket"]), sport
        for row in table["delta_by_bucket"].values():
            assert len(row) == 4 and all(mean > 0 and sd >= 0 for mean, sd in row)
        expected = {
            "p_incomplete": qm, "p_sack": qm, "p_turnover": qm, "p_oob": qm, "p_to_off": qm,
            "p_to_off_need": zones,
            "p_to_def": {"2_lead", "2_trail", "4_lead", "4_trail"},
        }
        for key, keys in expected.items():
            assert set(table[key]) == keys, (sport, key)
            for row in table[key].values():
                assert len(row) == 4 and all(0.0 <= p < 1.0 for p in row)
        assert set(table["p_spike"]) == zones and all(0.0 <= p < 1.0 for p in table["p_spike"].values())
    assert END_OF_HALF_CLOCK_TABLES["nfl"]["two_minute_warning"] is True
    assert END_OF_HALF_CLOCK_TABLES["ncaaf"]["two_minute_warning"] is False


def test_bucket_boundaries():
    from syndicate.features.football.sim_engine.smartsim2.situation_model import end_of_half_bucket
    assert [end_of_half_bucket(s) for s in (0, 30, 31, 60, 61, 90, 91, 120)] == [0, 0, 1, 1, 2, 2, 3, 3]


def test_window_incompletion_share_matches_the_table_only_when_on():
    from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors
    from syndicate.features.football.sim_engine.smartsim2.play_outcomes import PlayOutcome
    from syndicate.features.football.sim_engine.smartsim2.play_simulator import _play_outcome_weights
    from syndicate.features.football.sim_engine.smartsim2.play_state import build_play_state_from_possession_state
    from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state

    inp = _inp(1)
    st = build_initial_possession_state(home_team="H", away_team="A", quarter=2, clock_remaining=20,
                                        field_position=40, score_home=3, score_away=10)
    ps = build_play_state_from_possession_state(st, q2_urgency_ignores_score=True)
    priors = build_drive_priors(inp, possession_state=st, profile=NFL)
    on = replace(NFL, q2_urgency_ignores_score=True, end_of_half_clock=True)
    w_on = _play_outcome_weights(ps, priors, on)
    w_off = _play_outcome_weights(ps, priors, replace(NFL, q2_urgency_ignores_score=True))
    non_pen = sum(v for k, v in w_on.items() if k != PlayOutcome.PENALTY)
    table = END_OF_HALF_CLOCK_TABLES["nfl"]
    for outcome, cell in ((PlayOutcome.INCOMPLETE_PASS, "p_incomplete"), (PlayOutcome.SACK, "p_sack"),
                          (PlayOutcome.TURNOVER, "p_turnover")):
        assert abs(w_on[outcome] / non_pen - table[cell]["2_hurry"][0]) < 1e-9, cell
    assert w_off[PlayOutcome.INCOMPLETE_PASS] != w_on[PlayOutcome.INCOMPLETE_PASS]
    # the other outcomes keep their relative weights (the TD weight keeps its field-position dependence)
    for a, b in ((PlayOutcome.GAIN, PlayOutcome.EXPLOSIVE_GAIN), (PlayOutcome.GAIN, PlayOutcome.TOUCHDOWN)):
        assert abs(w_on[a] / w_on[b] - w_off[a] / w_off[b]) < 1e-9


def test_timeouts_are_tracked_never_negative_never_regained_within_a_half():
    for prof in (FULL_NFL, FULL_NCAAF):
        for seed in range(1, 41):
            out = simulate_game(_inp(seed), profile=prof)
            seen = {"home": {1: 3, 2: 3}, "away": {1: 3, 2: 3}}
            for step in _steps(out):
                st = step["end_state"]
                q = int(st["quarter"])
                if q > 4:
                    continue
                half = 1 if q <= 2 else 2
                for side in ("home", "away"):
                    left = st[f"timeouts_{side}"]
                    assert 0 <= left <= 3
                    assert left <= seen[side][half], "a team regained a timeout inside a half"
                    seen[side][half] = left


def test_timeouts_are_spent_only_in_the_last_120_s_of_q2_and_q4():
    for seed in range(1, 41):
        for step in _steps(simulate_game(_inp(seed), profile=FULL_NFL)):
            a, b = step["start_state"], step["end_state"]
            spent = (a["timeouts_home"] - b["timeouts_home"]) + (a["timeouts_away"] - b["timeouts_away"])
            if spent:
                assert spent == 1
                assert int(a["quarter"]) in (2, 4) and int(a["clock_remaining"]) <= END_OF_HALF_WINDOW_SECONDS


def test_second_half_starts_with_three_timeouts_each():
    for seed in range(1, 21):
        out = simulate_game(_inp(seed), profile=FULL_NFL)
        q3 = next(d for d in out.drive_log if int(d["start_state"]["quarter"]) == 3)
        assert (q3["start_state"]["timeouts_home"], q3["start_state"]["timeouts_away"]) == (3, 3)


def test_resume_takes_the_real_timeouts_left():
    out = simulate_game(_inp(1, initial_quarter=4, initial_clock_seconds=100, initial_timeouts_home=0,
                             initial_timeouts_away=2, initial_score_away=3), profile=FULL_NFL)
    first = out.drive_log[0]["start_state"]
    assert (first["timeouts_home"], first["timeouts_away"]) == (0, 2)
    assert out.input_state["initial_timeouts_home"] == 0


def test_nfl_two_minute_warning_stops_a_step_that_crosses_two_minutes():
    live = round(END_OF_HALF_CLOCK_TABLES["nfl"]["live_seconds"])
    crossed = 0
    for seed in range(1, 61):
        for step in _steps(simulate_game(_inp(seed), profile=FULL_NFL)):
            a, b = step["start_state"], step["end_state"]
            if int(a["quarter"]) not in (2, 4) or int(a["clock_remaining"]) <= END_OF_HALF_WINDOW_SECONDS:
                continue
            if int(b["clock_remaining"]) < END_OF_HALF_WINDOW_SECONDS:
                crossed += 1
                assert int(step["clock_consumed"]) <= live, step  # only a live play itself may cross 2:00
    # and some steps do reach the warning exactly
    hits = sum(1 for seed in range(1, 61) for step in _steps(simulate_game(_inp(seed), profile=FULL_NFL))
               if int(step["end_state"]["quarter"]) in (2, 4)
               and int(step["end_state"]["clock_remaining"]) == END_OF_HALF_WINDOW_SECONDS)
    assert hits > 20


def test_ncaaf_has_no_two_minute_warning():
    crossed = 0
    for seed in range(1, 61):
        for step in _steps(simulate_game(_inp(seed), profile=FULL_NCAAF)):
            a, b = step["start_state"], step["end_state"]
            if (int(a["quarter"]) in (2, 4) and int(a["clock_remaining"]) > END_OF_HALF_WINDOW_SECONDS + 10
                    and int(b["clock_remaining"]) < END_OF_HALF_WINDOW_SECONDS - 10):
                crossed += 1
    assert crossed > 0


def _window_snaps(profile, n=150):
    snaps = 0
    for seed in range(1, n + 1):
        for step in _steps(simulate_game(_inp(seed), profile=profile)):
            a = step["start_state"]
            if int(a["quarter"]) == 2 and int(a["clock_remaining"]) <= END_OF_HALF_WINDOW_SECONDS \
                    and step["outcome"] != "penalty":
                snaps += 1
    return snaps / n


def test_the_clock_adds_snaps_to_the_end_of_the_half():
    # Direction only (the size is the FIT read's job, not a unit test's).
    off = _window_snaps(replace(NFL, halftime_kickoff=True, q2_urgency_ignores_score=True))
    on = _window_snaps(FULL_NFL)
    assert on > off + 1.0, (off, on)


def test_quarters_one_and_three_are_untouched_by_the_clock():
    # The clock re-times nothing outside Q2 / Q4: a Q3 resume that ends before Q4
    # changes only through the timeouts on the state, which Q3 never spends.
    prof = replace(NFL, end_of_half_clock=True)
    for seed in range(1, 21):
        kw = dict(initial_quarter=3, initial_clock_seconds=600, initial_score_home=10)
        a = simulate_game(_inp(seed, **kw), profile=NFL)
        b = simulate_game(_inp(seed, **kw), profile=prof)
        qa = [x for x in a.quarter_log if x["quarter"] == 3]
        qb = [x for x in b.quarter_log if x["quarter"] == 3]
        assert qa == qb


# --------------------------------------------------------------------- v2 (pre-registered 9affd0cba)

V2_FIELDS = ("end_of_half_kneel_out", "end_of_half_clock_by_need", "q4_kick_waits")
FULL2_NFL = replace(FULL_NFL, **{f: True for f in V2_FIELDS})
FULL2_NCAAF = replace(FULL_NCAAF, **{f: True for f in V2_FIELDS})


def test_v2_switches_default_off_and_round_trip():
    for prof in (NFL, NCAAF):
        assert not any(getattr(prof, f) for f in V2_FIELDS)
    back = profile_with_overrides(NFL, FULL2_NFL.to_dict())
    assert all(getattr(back, f) for f in V2_FIELDS)


@pytest.mark.parametrize("field", V2_FIELDS)
def test_v2_reachability_each_switch_changes_the_output_on_top_of_the_clock(field):
    for base in (FULL_NFL, FULL_NCAAF):
        on = replace(base, **{field: True})
        a = [simulate_game(_inp(s), profile=base).to_dict() for s in range(1, 61)]
        b = [simulate_game(_inp(s), profile=on).to_dict() for s in range(1, 61)]
        assert a != b, f"{field} is inert on {base.name}"


@pytest.mark.parametrize("field", V2_FIELDS)
def test_v2_switches_are_inert_without_the_clock(field):
    alone = replace(NFL, **{field: True})
    for s in range(1, 21):
        assert simulate_game(_inp(s), profile=alone).to_dict() == simulate_game(_inp(s), profile=NFL).to_dict()


def test_kneel_out_kneels_when_the_clock_can_be_run_out_and_not_otherwise():
    kneel = replace(FULL_NFL, end_of_half_kneel_out=True)
    lead = dict(initial_quarter=4, initial_score_home=24, initial_score_away=17, initial_possession_owner="home",
                initial_field_position=40)
    # 1:00 left, 1st down, the defense out of timeouts: 40 * 4 + 4 * kneel_live >= 60 -> kneel
    step = _first_step(kneel, initial_clock_seconds=60, initial_timeouts_away=0, **lead)
    assert step["summary"].endswith("took a knee") and step["yards_gained"] == -1 and step["points_scored"] == 0
    # 1:50 left, 1st down, the defense holds 3: 40 * 1 + 4 * kneel_live < 110 -> no kneel
    step = _first_step(kneel, initial_clock_seconds=110, initial_timeouts_away=3, **lead)
    assert not step["summary"].endswith("took a knee")
    # OFF: never
    assert not _first_step(FULL_NFL, initial_clock_seconds=60, initial_timeouts_away=0, **lead)["summary"].endswith("took a knee")


def test_kneel_out_ends_the_game_without_leader_points():
    kneel = replace(FULL_NFL, end_of_half_kneel_out=True)
    for seed in range(1, 31):
        out = simulate_game(_inp(seed, initial_quarter=4, initial_clock_seconds=60, initial_score_home=24,
                                 initial_score_away=17, initial_possession_owner="home", initial_field_position=40,
                                 initial_timeouts_away=0), profile=kneel)
        assert out.final_score == {"home": 24, "away": 17}


def _spikes(profile, n=120, **kw):
    hits, with_timeouts = 0, 0
    for seed in range(1, n + 1):
        for step in _steps(simulate_game(_inp(seed, **kw), profile=profile)):
            if step["summary"].endswith("spiked the ball"):
                hits += 1
                a = step["start_state"]
                left = a["timeouts_home"] if a["possession_owner"] == "home" else a["timeouts_away"]
                with_timeouts += left > 0
                assert int(a["quarter"]) in (2, 4) and int(a["clock_remaining"]) <= 60
                assert step["clock_consumed"] <= 5 and step["yards_gained"] == 0
    return hits, with_timeouts


def test_spikes_only_by_need():
    trailing_q4 = dict(initial_quarter=4, initial_clock_seconds=58, initial_score_home=10, initial_score_away=14,
                       initial_possession_owner="home", initial_field_position=55, initial_timeouts_home=0)
    hits, with_timeouts = _spikes(replace(FULL_NFL, end_of_half_clock_by_need=True), **trailing_q4)
    assert hits > 0 and with_timeouts == 0
    assert _spikes(FULL_NFL, **trailing_q4) == (0, 0)  # by-need OFF: no spikes at all


def test_q4_kick_waits_only_with_its_switch():
    q4 = dict(initial_quarter=4, initial_score_home=10, initial_score_away=10, initial_possession_owner="home",
              initial_field_position=75, initial_clock_seconds=45)
    assert _first_step(FULL_NFL, **q4)["outcome"] in ("field_goal", "missed_field_goal")
    waits = replace(FULL_NFL, q4_kick_waits=True)
    assert _first_step(waits, **q4)["outcome"] not in ("field_goal", "missed_field_goal")
    assert _first_step(waits, **dict(q4, initial_clock_seconds=8))["outcome"] in ("field_goal", "missed_field_goal")
    assert _first_step(waits, **dict(q4, initial_down=4, initial_distance=6))["outcome"] in ("field_goal", "missed_field_goal")


# --------------------------------------------------------------------- v3 (pre-registered a02911da1)

FULL3_NFL = replace(FULL2_NFL, kneel_out_q4_only=True)
FULL3_NCAAF = replace(FULL2_NCAAF, kneel_out_q4_only=True)
Q2_KNEEL = dict(initial_quarter=2, initial_clock_seconds=40, initial_score_home=10, initial_score_away=7,
                initial_possession_owner="home", initial_field_position=30)


def test_v3_switch_defaults_off_and_round_trips():
    for prof in (NFL, NCAAF):
        assert prof.kneel_out_q4_only is False
    assert profile_with_overrides(NFL, FULL3_NFL.to_dict()).kneel_out_q4_only is True


def test_v3_reachability_on_top_of_the_kneel_out():
    for v2, v3 in ((FULL2_NFL, FULL3_NFL), (FULL2_NCAAF, FULL3_NCAAF)):
        a = [simulate_game(_inp(s), profile=v2).to_dict() for s in range(1, 61)]
        b = [simulate_game(_inp(s), profile=v3).to_dict() for s in range(1, 61)]
        assert a != b, f"kneel_out_q4_only is inert on {v2.name}"


def test_v3_switch_is_inert_without_the_kneel_out():
    no_kneel = replace(FULL2_NFL, end_of_half_kneel_out=False)
    alone = replace(no_kneel, kneel_out_q4_only=True)
    for s in range(1, 21):
        for kw in ({}, Q2_KNEEL):
            assert simulate_game(_inp(s, **kw), profile=alone).to_dict() == \
                simulate_game(_inp(s, **kw), profile=no_kneel).to_dict()


def test_v3_kneels_in_q4_but_not_at_the_half():
    # Q2, 0:40, own 30, 1st down, the defense holds 3: 40 * 1 + 4 * kneel_live >= 40 -> v2 kneels at the half
    assert _first_step(FULL2_NFL, **Q2_KNEEL)["summary"].endswith("took a knee")
    assert not _first_step(FULL3_NFL, **Q2_KNEEL)["summary"].endswith("took a knee")
    # Q4 is unchanged: the leader still kneels out the game
    lead = dict(initial_quarter=4, initial_clock_seconds=60, initial_score_home=24, initial_score_away=17,
                initial_possession_owner="home", initial_field_position=40, initial_timeouts_away=0)
    assert _first_step(FULL3_NFL, **lead)["summary"].endswith("took a knee")
    for seed in range(1, 21):
        assert simulate_game(_inp(seed, **lead), profile=FULL3_NFL).final_score == {"home": 24, "away": 17}
