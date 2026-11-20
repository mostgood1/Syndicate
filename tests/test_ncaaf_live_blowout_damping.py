"""todo #852: the NCAAF live re-sim's leader eases off in a blowout (lane ncaaf-live-endgame-surplus). DEFAULT OFF.

REACHABILITY FIRST (`model_engine_standard.md`). Absent / off must leave `resim_live_game` and the worker's tick
byte-identical to the pre-change default (`profile=NCAAF_CALIBRATION_PROFILE`). On must change what the tick publishes
for a blowout. Only then is the direction and the knob handling tested.
"""
from __future__ import annotations

import math

import pytest

import scripts.run_refresh_worker as rw
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.play_simulator import blowout_damping_factor
from syndicate.features.football.sim_engine.smartsim2.play_state import PlayState
from syndicate.features.ncaaf import live_blowout_damping as lbd
from syndicate.features.ncaaf import live_resim as lr
from tests.test_ncaaf_live_resim_wiring import _espn_event, _FakeProjection, _wire_tick
from tests.test_ncaaf_live_total_dispersion import _stable

KNOB_ENVS = (lbd.STRENGTH_ENV, lbd.THRESHOLD_ENV, lbd.SPAN_ENV)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(lbd.SWITCH_ENV, raising=False)
    for name in KNOB_ENVS:
        monkeypatch.delenv(name, raising=False)
    rw._NCAAF_SP_RATINGS_MEMO.clear()
    yield
    rw._NCAAF_SP_RATINGS_MEMO.clear()


def _blowout(**over):
    """Home up 28 with 12:00 left, home ball at its own 25: the state the damping exists for."""
    kw = dict(away_team="Baylor", home_team="Auburn", period=4, clock_seconds=720, home_score=35, away_score=7,
              down=1, distance=10, field_position=25, possession_owner="home")
    kw.update(over)
    return lr.NcaafLiveGameState(**kw)


def _resim(state, sims=40, **kw):
    return lr.resim_live_game(state, home_offense=0.6, home_defense=0.4, away_offense=-0.2, away_defense=-0.1,
                              sims=sims, **kw)


# --------------------------------------------------------------------------
# REACHABILITY
# --------------------------------------------------------------------------

def test_REACHABILITY_absent_is_byte_identical_to_the_pre_change_default():
    assert _resim(_blowout()) == _resim(_blowout(), profile=NCAAF_CALIBRATION_PROFILE)


@pytest.mark.parametrize("raw", ["off", "0", "", "false", "maybe", "onn"])
def test_REACHABILITY_off_and_unrecognised_values_are_byte_identical_to_absent(monkeypatch, raw):
    absent = _resim(_blowout())
    monkeypatch.setenv(lbd.SWITCH_ENV, raw)
    assert _resim(_blowout()) == absent
    assert "blowout_damping" not in absent


def test_REACHABILITY_on_changes_the_resim_of_a_blowout(monkeypatch):
    off = _resim(_blowout())
    monkeypatch.setenv(lbd.SWITCH_ENV, "on")
    on = _resim(_blowout())
    assert on["total_dist"] != off["total_dist"]
    assert on["blowout_damping"] == {"on": True, "strength": lbd.DEFAULT_STRENGTH,
                                     "lead_threshold": lbd.DEFAULT_LEAD_THRESHOLD, "lead_span": lbd.DEFAULT_LEAD_SPAN}


def _run_tick(monkeypatch, tmp_path):
    _wire_tick(
        monkeypatch, tmp_path,
        events=[_espn_event(away_loc="Baylor", home_loc="Auburn", away_id="239", home_id="2", period=4,
                            clock="12:00", away_score="7", home_score="35",
                            situation={"possession": "2", "down": 1, "distance": 10, "yardLine": 25})],
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
    monkeypatch.setenv(lbd.SWITCH_ENV, "off")
    _meta, off = _run_tick(monkeypatch, tmp_path / "off")
    assert _stable(off) == _stable(absent)
    monkeypatch.setenv(lbd.SWITCH_ENV, "on")
    _meta, on = _run_tick(monkeypatch, tmp_path / "on")
    lane_off, lane_on = absent["games"][0]["gameLens"][0], on["games"][0]["gameLens"][0]
    assert lane_on["projection"]["totalRunsDist"] != lane_off["projection"]["totalRunsDist"]
    # the state on the board is the board's, whatever the engine does with the rest of the game
    for key in ("homeScore", "awayScore", "period", "clockSeconds"):
        assert lane_on["projection"][key] == lane_off["projection"][key]


# --------------------------------------------------------------------------
# WHAT IT DOES
# --------------------------------------------------------------------------

def test_on_lowers_the_leaders_late_scoring_in_a_blowout(monkeypatch):
    off = _resim(_blowout(), sims=200)
    monkeypatch.setenv(lbd.SWITCH_ENV, "on")
    on = _resim(_blowout(), sims=200)
    # the leader (home) scores less: the margin and the total both fall, on the same seeds
    assert on["home_margin_mean_uncalibrated"] < off["home_margin_mean_uncalibrated"] - 1.0
    assert on["total_mean_uncalibrated"] < off["total_mean_uncalibrated"] - 1.0


def test_an_explicit_profile_is_honoured_as_given_when_on(monkeypatch):
    plain = _resim(_blowout(), profile=NCAAF_CALIBRATION_PROFILE)
    monkeypatch.setenv(lbd.SWITCH_ENV, "on")
    assert _resim(_blowout(), profile=NCAAF_CALIBRATION_PROFILE) == plain


def test_the_kickoff_total_path_sees_the_same_engine(monkeypatch):
    """#835's E0 calls `resim_live_game` at kickoff with no profile, so the anchor reads the damped engine when on."""
    monkeypatch.setenv(lbd.SWITCH_ENV, "on")
    kick = lr.NcaafLiveGameState(away_team="Baylor", home_team="Auburn", period=1, clock_seconds=900, home_score=0,
                                 away_score=0)
    assert _resim(kick, sims=4)["blowout_damping"]["on"] is True


def test_off_resolves_to_the_same_profile_object():
    profile, block = lbd.resolve(NCAAF_CALIBRATION_PROFILE, {})
    assert profile is NCAAF_CALIBRATION_PROFILE and block is None


def test_on_sets_only_the_three_damping_fields():
    import dataclasses

    profile, _block = lbd.resolve(NCAAF_CALIBRATION_PROFILE, {lbd.SWITCH_ENV: "on"})
    changed = {f.name for f in dataclasses.fields(profile)
               if getattr(profile, f.name) != getattr(NCAAF_CALIBRATION_PROFILE, f.name)}
    assert changed == {"blowout_damping_strength"} | (
        {"blowout_damping_lead_threshold"} if lbd.DEFAULT_LEAD_THRESHOLD != 14.0 else set()) | (
        {"blowout_damping_lead_span"} if lbd.DEFAULT_LEAD_SPAN != 14.0 else set())
    assert profile.blowout_damping_strength == lbd.DEFAULT_STRENGTH
    assert profile.blowout_damping_lead_threshold == lbd.DEFAULT_LEAD_THRESHOLD
    assert profile.blowout_damping_lead_span == lbd.DEFAULT_LEAD_SPAN
    assert NCAAF_CALIBRATION_PROFILE.blowout_damping_strength == 0.0  # production's own profile is untouched


def _play(diff, quarter, seconds):
    return PlayState(possession_team="Auburn", down=1, distance=10, yardline=40, quarter=quarter,
                     seconds_remaining=seconds, score_differential=diff)


@pytest.mark.parametrize("diff,quarter,seconds,damped", [
    (28, 4, 300, True),     # a leader up 28 late
    (28, 2, 300, False),    # the first half is never damped
    (14, 4, 300, False),    # at the threshold, not above it
    (-28, 4, 300, False),   # the trailer is never damped
    (0, 4, 300, False),
])
def test_the_resolved_profile_damps_only_a_leader_above_the_threshold_in_the_second_half(diff, quarter, seconds,
                                                                                          damped):
    profile, _ = lbd.resolve(NCAAF_CALIBRATION_PROFILE, {lbd.SWITCH_ENV: "on"})
    factor = blowout_damping_factor(_play(diff, quarter, seconds), profile)
    assert (factor < 1.0) is damped
    assert blowout_damping_factor(_play(diff, quarter, seconds), NCAAF_CALIBRATION_PROFILE) == 1.0


# --------------------------------------------------------------------------
# THE SWITCH AND ITS KNOBS
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,on", [("on", True), ("1", True), ("true", True), ("yes", True), (" ON ", True),
                                    ("", False), ("off", False), ("0", False), ("no", False), ("onn", False)])
def test_the_switch_reads_only_explicit_on_values(raw, on):
    assert lbd.enabled({lbd.SWITCH_ENV: raw}) is on


@pytest.mark.parametrize("raw", ["abc", "nan", "inf", "-0.5", "0", "1.5", "  "])
def test_a_bad_strength_falls_back_to_the_fitted_default_not_to_no_damping(raw):
    assert lbd.settings({lbd.STRENGTH_ENV: raw})["strength"] == lbd.DEFAULT_STRENGTH


@pytest.mark.parametrize("name,key,raw,expected", [
    (lbd.STRENGTH_ENV, "strength", "0.6", 0.6),
    (lbd.STRENGTH_ENV, "strength", "1", 1.0),
    (lbd.THRESHOLD_ENV, "lead_threshold", "17", 17.0),
    (lbd.THRESHOLD_ENV, "lead_threshold", "-3", lbd.DEFAULT_LEAD_THRESHOLD),
    (lbd.THRESHOLD_ENV, "lead_threshold", "61", lbd.DEFAULT_LEAD_THRESHOLD),
    (lbd.SPAN_ENV, "lead_span", "10", 10.0),
    (lbd.SPAN_ENV, "lead_span", "0", lbd.DEFAULT_LEAD_SPAN),
])
def test_knobs_apply_in_range_and_fall_back_out_of_it(name, key, raw, expected):
    assert lbd.settings({name: raw})[key] == pytest.approx(expected)


def test_the_fitted_defaults_are_in_range():
    assert 0.0 < lbd.DEFAULT_STRENGTH <= 1.0
    assert 0.0 < lbd.DEFAULT_LEAD_THRESHOLD <= 60.0 and 0.0 < lbd.DEFAULT_LEAD_SPAN <= 60.0
    assert math.isfinite(lbd.DEFAULT_STRENGTH)
