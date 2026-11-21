"""todo #859: the NCAAF live re-sim's end game (lane ncaaf-margin-aware-endgame). DEFAULT OFF.

`SYNDICATE_NCAAF_LIVE_ENDGAME` arms #808's end-of-half clock, #859's trailing concession and #855's college overtime
for the live re-sim; ESPN's timeouts left now reach the engine.

REACHABILITY FIRST (`model_engine_standard.md`). Absent / off must leave `resim_live_game` and the worker's tick
byte-identical to the pre-change default, timeouts fed or not. On must change what the tick publishes for a late
blowout. Then the timeouts mapping, the chaining with #852 and the knob handling.
"""
from __future__ import annotations

import dataclasses

import pytest

import scripts.run_refresh_worker as rw
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE
from syndicate.features.ncaaf import live_blowout_damping as lbd
from syndicate.features.ncaaf import live_endgame as leg
from syndicate.features.ncaaf import live_resim as lr
from tests.test_ncaaf_live_resim_wiring import _espn_event, _FakeProjection, _wire_tick
from tests.test_ncaaf_live_total_dispersion import _stable

ENVS = (leg.SWITCH_ENV, leg.CONCEDE_ENV, lbd.SWITCH_ENV, lbd.STRENGTH_ENV, lbd.THRESHOLD_ENV, lbd.SPAN_ENV)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ENVS:
        monkeypatch.delenv(name, raising=False)
    rw._NCAAF_SP_RATINGS_MEMO.clear()
    leg._ANNOUNCED.clear()
    yield
    rw._NCAAF_SP_RATINGS_MEMO.clear()


def _late(**over):
    """Home down 28 with 5:00 left and the ball at its own 30: the state the concession exists for."""
    kw = dict(away_team="Baylor", home_team="Auburn", period=4, clock_seconds=300, home_score=7, away_score=35,
              down=1, distance=10, field_position=30, possession_owner="home")
    kw.update(over)
    return lr.NcaafLiveGameState(**kw)


def _resim(state, sims=40, **kw):
    return lr.resim_live_game(state, home_offense=0.6, home_defense=0.4, away_offense=-0.2, away_defense=-0.1,
                              sims=sims, **kw)


# --------------------------------------------------------------------------
# REACHABILITY
# --------------------------------------------------------------------------

def test_REACHABILITY_absent_is_byte_identical_to_the_pre_change_default():
    assert _resim(_late()) == _resim(_late(), profile=NCAAF_CALIBRATION_PROFILE)


def test_REACHABILITY_absent_fed_timeouts_change_nothing():
    """The engine reads timeouts only under `end_of_half_clock`, which is off unless the switch is on."""
    assert _resim(_late(home_timeouts=0, away_timeouts=1)) == _resim(_late())


@pytest.mark.parametrize("raw", ["off", "0", "", "false", "maybe", "onn"])
def test_REACHABILITY_off_and_unrecognised_values_are_byte_identical_to_absent(monkeypatch, raw):
    absent = _resim(_late())
    monkeypatch.setenv(leg.SWITCH_ENV, raw)
    assert _resim(_late()) == absent
    assert "endgame" not in absent


def test_REACHABILITY_on_changes_the_resim_of_a_late_blowout(monkeypatch):
    off = _resim(_late())
    monkeypatch.setenv(leg.SWITCH_ENV, "on")
    on = _resim(_late(home_timeouts=2, away_timeouts=3))
    assert on["total_dist"] != off["total_dist"]
    assert on["endgame"] == {"on": True, "concede_deficit": 25, "end_of_half_clock": True, "college_overtime": True,
                             "timeouts_fed": True}
    assert _resim(_late(home_timeouts=2))["endgame"]["timeouts_fed"] is False  # one side unreported


def _run_tick(monkeypatch, tmp_path, situation_extra=None):
    situation = {"possession": "2", "down": 1, "distance": 10, "yardLine": 30, **(situation_extra or {})}
    _wire_tick(
        monkeypatch, tmp_path,
        events=[_espn_event(away_loc="Baylor", home_loc="Auburn", away_id="239", home_id="2", period=4,
                            clock="5:00", away_score="35", home_score="7", situation=situation)],
        projections=[_FakeProjection("Baylor", "Auburn")],
        ratings_teams={"baylor": (25.0, 20.0), "auburn": (28.0, 18.0)},
    )
    monkeypatch.setenv("NCAAF_LIVE_RESIM_SIMS", "40")
    meta = rw._run_ncaaf_live_resim_tick()
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    return meta, read_json_file(lr.live_lens_snapshot_path(data_root()))


def test_REACHABILITY_through_the_tick_off_is_byte_identical_and_on_changes_the_published_lane(monkeypatch, tmp_path):
    meta, absent = _run_tick(monkeypatch, tmp_path / "absent")
    assert meta["written"] is True and meta["coverage"]["live_resimmed"] == 1
    _meta, fed_absent = _run_tick(monkeypatch, tmp_path / "fed", {"homeTimeouts": 1, "awayTimeouts": 3})
    assert _stable(fed_absent) == _stable(absent)  # ESPN's timeouts alone change nothing while the switch is off
    monkeypatch.setenv(leg.SWITCH_ENV, "off")
    _meta, off = _run_tick(monkeypatch, tmp_path / "off", {"homeTimeouts": 1, "awayTimeouts": 3})
    assert _stable(off) == _stable(absent)
    monkeypatch.setenv(leg.SWITCH_ENV, "on")
    seen = _capture(monkeypatch)
    _meta, on = _run_tick(monkeypatch, tmp_path / "on", {"homeTimeouts": 1, "awayTimeouts": 3})
    # ESPN's situation survives the poller's row and the parser all the way to the engine input
    assert {(i.initial_timeouts_home, i.initial_timeouts_away) for i, _p in seen} == {(1, 3)}
    assert {p.trailing_concede_deficit for _i, p in seen} == {25}
    lane_off, lane_on = absent["games"][0]["gameLens"][0], on["games"][0]["gameLens"][0]
    assert lane_on["projection"]["totalRunsDist"] != lane_off["projection"]["totalRunsDist"]
    for key in ("homeScore", "awayScore", "period", "clockSeconds"):
        assert lane_on["projection"][key] == lane_off["projection"][key]


# --------------------------------------------------------------------------
# ESPN'S TIMEOUTS LEFT
# --------------------------------------------------------------------------

def _row(**situation):
    return {"in_progress": True, "final": False, "period": 4, "clock": "5:00", "home_score": 7, "away_score": 35,
            "possession_owner": "home", "situation": {"down": 1, "distance": 10, "yardLine": 30, **situation}}


def test_the_parser_reads_espns_situation_timeouts():
    st = lr.live_state_from_espn_event(_row(homeTimeouts=1, awayTimeouts=0), away_team="A", home_team="B")
    assert (st.home_timeouts, st.away_timeouts) == (1, 0)
    st = lr.live_state_from_espn_event(_row(homeTimeouts="3", awayTimeouts=2.0), away_team="A", home_team="B")
    assert (st.home_timeouts, st.away_timeouts) == (3, 2)


@pytest.mark.parametrize("bad", [None, 4, -1, 1.5, "two", "", True, [1]])
def test_an_unreadable_timeout_is_none_never_clamped(bad):
    st = lr.live_state_from_espn_event(_row(homeTimeouts=bad, awayTimeouts=bad), away_team="A", home_team="B")
    assert (st.home_timeouts, st.away_timeouts) == (None, None)


def test_absent_timeouts_are_none():
    st = lr.live_state_from_espn_event(_row(), away_team="A", home_team="B")
    assert (st.home_timeouts, st.away_timeouts) == (None, None)


def _capture(monkeypatch):
    seen = []
    real = lr.simulate_game

    def spy(sim_input, profile=None):
        seen.append((sim_input, profile))
        return real(sim_input, profile=profile)

    monkeypatch.setattr(lr, "simulate_game", spy)
    return seen


def test_fed_timeouts_reach_the_engine_input_and_absent_stays_absent(monkeypatch):
    seen = _capture(monkeypatch)
    _resim(_late(home_timeouts=1, away_timeouts=2), sims=4)
    assert {(i.initial_timeouts_home, i.initial_timeouts_away) for i, _p in seen} == {(1, 2)}
    seen.clear()
    _resim(_late(), sims=4)
    assert {(i.initial_timeouts_home, i.initial_timeouts_away) for i, _p in seen} == {(None, None)}
    seen.clear()
    _resim(_late(away_timeouts=0), sims=4)
    assert {(i.initial_timeouts_home, i.initial_timeouts_away) for i, _p in seen} == {(None, 0)}


def test_on_the_fed_timeouts_matter(monkeypatch):
    """Home trails by 4 with 1:30 left and the away side runs the clock: home's timeouts are its chance."""
    monkeypatch.setenv(leg.SWITCH_ENV, "on")
    close = dict(clock_seconds=90, home_score=24, away_score=28, possession_owner="away", field_position=40)
    none_left = _resim(_late(**close, home_timeouts=0, away_timeouts=3))
    all_left = _resim(_late(**close, home_timeouts=3, away_timeouts=3))
    assert none_left["margin_dist"] != all_left["margin_dist"] or none_left["home_win_prob"] != all_left["home_win_prob"]


# --------------------------------------------------------------------------
# THE PROFILE, ALONE AND CHAINED WITH #852
# --------------------------------------------------------------------------

def test_off_resolves_to_the_same_profile_object():
    profile, block = leg.resolve(NCAAF_CALIBRATION_PROFILE, {})
    assert profile is NCAAF_CALIBRATION_PROFILE and block is None


def test_on_sets_only_the_end_game_fields():
    profile, block = leg.resolve(NCAAF_CALIBRATION_PROFILE, {leg.SWITCH_ENV: "on"})
    expected = set(leg.END_OF_HALF_SWITCHES) | {"trailing_concede_deficit", "college_overtime"}
    changed = {f.name for f in dataclasses.fields(profile)
               if getattr(profile, f.name) != getattr(NCAAF_CALIBRATION_PROFILE, f.name)}
    assert changed <= expected and "trailing_concede_deficit" in changed
    assert all(getattr(profile, name) is True for name in leg.END_OF_HALF_SWITCHES)
    assert profile.college_overtime is True and profile.trailing_concede_deficit == 25
    assert NCAAF_CALIBRATION_PROFILE.trailing_concede_deficit is None  # production's own profile is untouched
    assert block == {"on": True, "concede_deficit": 25, "end_of_half_clock": True, "college_overtime": True}


def test_with_852_on_the_resim_runs_the_gated_v4a_profile(monkeypatch):
    """Both switches on = #859's gated arm: #852's damping + #808's clock + college OT + the concession at 25."""
    monkeypatch.setenv(lbd.SWITCH_ENV, "on")
    monkeypatch.setenv(leg.SWITCH_ENV, "on")
    seen = _capture(monkeypatch)
    out = _resim(_late(), sims=2)
    assert out["blowout_damping"]["on"] is True and out["endgame"]["on"] is True
    profiles = {id(p): p for _i, p in seen}
    assert len(profiles) == 1
    (p,) = profiles.values()
    assert (p.blowout_damping_strength, p.blowout_damping_lead_threshold, p.blowout_damping_lead_span) == (
        lbd.DEFAULT_STRENGTH, lbd.DEFAULT_LEAD_THRESHOLD, lbd.DEFAULT_LEAD_SPAN)
    assert all(getattr(p, name) is True for name in leg.END_OF_HALF_SWITCHES)
    assert p.college_overtime is True and p.trailing_concede_deficit == 25


def test_an_explicit_profile_is_honoured_as_given_when_on(monkeypatch):
    plain = _resim(_late(), profile=NCAAF_CALIBRATION_PROFILE)
    monkeypatch.setenv(leg.SWITCH_ENV, "on")
    assert _resim(_late(), profile=NCAAF_CALIBRATION_PROFILE) == plain


def test_the_kickoff_total_path_sees_the_same_engine(monkeypatch):
    """#835's E0 calls `resim_live_game` at kickoff with no profile, so the anchor reads the same engine when on."""
    monkeypatch.setenv(leg.SWITCH_ENV, "on")
    kick = lr.NcaafLiveGameState(away_team="Baylor", home_team="Auburn", period=1, clock_seconds=900, home_score=0,
                                 away_score=0)
    assert _resim(kick, sims=4)["endgame"]["on"] is True


def test_the_concession_itself_is_what_slows_a_hopeless_game(monkeypatch):
    """Same clock, same seeds: conceding at 25 (the trailer is down 28) against never conceding (60)."""
    monkeypatch.setenv(leg.SWITCH_ENV, "on")
    conceding = _resim(_late(home_timeouts=3, away_timeouts=3), sims=200)
    monkeypatch.setenv(leg.CONCEDE_ENV, "60")
    hurrying = _resim(_late(home_timeouts=3, away_timeouts=3), sims=200)
    assert conceding["total_mean_uncalibrated"] < hurrying["total_mean_uncalibrated"]


def test_the_switch_announces_itself_once(monkeypatch, capsys):
    monkeypatch.setenv(leg.SWITCH_ENV, "on")
    _resim(_late(), sims=2)
    _resim(_late(), sims=2)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("NCAAF_LIVE_ENDGAME on")]
    assert len(lines) == 1 and "concede_deficit=25" in lines[0]


# --------------------------------------------------------------------------
# KNOBS
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,on", [("1", True), ("on", True), ("TRUE", True), (" yes ", True),
                                    ("0", False), ("off", False), ("", False), ("enabled", False)])
def test_the_switch_reads_only_explicit_on_values(raw, on):
    assert leg.enabled({leg.SWITCH_ENV: raw}) is on


@pytest.mark.parametrize("raw,expected", [("17", 17), ("25", 25), ("1", 1), ("60", 60), ("0", 25), ("61", 25),
                                          ("-3", 25), ("24.5", 25), ("lots", 25), ("", 25)])
def test_a_bad_concede_deficit_falls_back_to_the_pre_registered_25(raw, expected):
    assert leg.concede_deficit({leg.CONCEDE_ENV: raw}) == expected
