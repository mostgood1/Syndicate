"""todo #835: the NCAAF live total calibration (anchor to the close + widen), lane ncaaf-live-total-dispersion.

REACHABILITY FIRST (`model_engine_standard.md`): through `run_refresh_worker._run_ncaaf_live_resim_tick` -- the function
the worker runs -- the switch must change the PUBLISHED snapshot when on and leave it, and the tick's status,
byte-identical when absent. Only then is what the transform computes tested.
"""
from __future__ import annotations

import json
import statistics

import pytest

import scripts.run_refresh_worker as rw
from syndicate.features.ncaaf import live_resim as lr
from syndicate.features.ncaaf import live_total_dispersion as ltd
from tests.test_ncaaf_live_resim_wiring import _espn_event, _FakeProjection, _wire_tick

RATINGS = {"oregon": (1.2, 0.6), "boise state": (0.1, 0.1), "penn state": (1.5, 0.8), "marshall": (-0.4, -0.2)}
# The fleet's quote log, in `closing_totals`' own key shape (`_join_key('ncaaf', name)`, home first).
CLOSES = {("oregon", "boise state"): (61.5, 9), ("penn state", "marshall"): (48.0, 7),
          ("auburn", "baylor"): (52.5, 11)}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(ltd.SWITCH_ENV, raising=False)
    monkeypatch.delenv(ltd.K_ENV, raising=False)
    ltd._CLOSE_SOURCES.clear()
    ltd._E0_CACHE.clear()
    rw._NCAAF_SP_RATINGS_MEMO.clear()
    monkeypatch.setattr(ltd, "_closing_totals", lambda date: CLOSES)
    yield
    ltd._CLOSE_SOURCES.clear()
    ltd._E0_CACHE.clear()
    rw._NCAAF_SP_RATINGS_MEMO.clear()


# --------------------------------------------------------------------------
# REACHABILITY, through the worker's tick
# --------------------------------------------------------------------------

def _run_tick(monkeypatch, tmp_path):
    _wire_tick(
        monkeypatch, tmp_path,
        events=[_espn_event(away_loc="Baylor", home_loc="Auburn", away_id="239", home_id="2", period=2,
                            clock="9:41", away_score="7", home_score="10",
                            situation={"possession": "2", "down": 2, "distance": 6, "yardLine": 41})],
        projections=[_FakeProjection("Baylor", "Auburn")],
        ratings_teams={"baylor": (25.0, 20.0), "auburn": (28.0, 18.0)},
    )
    meta = rw._run_ncaaf_live_resim_tick()
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    snapshot = read_json_file(lr.live_lens_snapshot_path(data_root()))
    status = read_json_file(rw._ncaaf_live_resim_status_path())
    return meta, snapshot, status


def _stable(doc):
    """The snapshot minus its wall clocks (two runs read the clock at different instants), and nothing else."""
    out = json.loads(json.dumps(doc))
    for key in ("generatedAt", "elapsedSeconds"):
        out.pop(key, None)
    ((out.get("coverage") or {}).get("player_exits") or {}).pop("elapsed_seconds", None)
    for game in out.get("games") or ():
        for lane in game.get("gameLens") or ():
            lane.pop("liveStateAsOf", None)
    return out


def _lane(snapshot):
    return snapshot["games"][0]["gameLens"][0]


def test_REACHABILITY_absent_switch_never_runs_the_transform(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("the calibration ran with the switch absent")

    monkeypatch.setattr(ltd, "apply", boom)
    monkeypatch.setattr(ltd, "closing_total_for", boom)
    meta, snapshot, status = _run_tick(monkeypatch, tmp_path)
    assert meta["written"] is True and meta["coverage"]["live_resimmed"] == 1
    assert "totalCalibration" not in snapshot
    assert "totalCalibration" not in _lane(snapshot)["projection"]
    assert "total_calibration" not in meta and "total_calibration" not in status["last"]


def test_REACHABILITY_off_is_byte_identical_to_absent(monkeypatch, tmp_path):
    _meta, absent, _status = _run_tick(monkeypatch, tmp_path / "absent")
    monkeypatch.setenv(ltd.SWITCH_ENV, "off")
    _meta, off, _status = _run_tick(monkeypatch, tmp_path / "off")
    assert _stable(off) == _stable(absent)


def test_REACHABILITY_on_changes_the_published_total_and_nothing_else(monkeypatch, tmp_path):
    _meta, off, _status = _run_tick(monkeypatch, tmp_path / "off")
    monkeypatch.setenv(ltd.SWITCH_ENV, "on")
    meta, on, status = _run_tick(monkeypatch, tmp_path / "on")
    lane_off, lane_on = _lane(off), _lane(on)
    assert lane_on["projection"]["totalRunsDist"] != lane_off["projection"]["totalRunsDist"]
    block = lane_on["projection"]["totalCalibration"]
    assert block["source"] == "book_quotes_close+live_kickoff_resim"
    assert block["marketTotal"] == 52.5 and block["books"] == 11
    assert block["rawTotal"] == lane_off["projection"]["total"]
    # the margin, the win probability and the state are the re-sim's own
    for key in ("homeMargin", "marginDist", "homeScore", "awayScore", "period", "clockSeconds"):
        assert lane_on["projection"][key] == lane_off["projection"][key]
    assert lane_on["modelHomeWinProb"] == lane_off["modelHomeWinProb"]
    # counted where the fleet can read it: the snapshot and the tick's status
    assert on["totalCalibration"]["anchored"] == 1
    assert meta["total_calibration"]["anchored"] == 1
    assert status["last"]["total_calibration"]["anchored"] == 1


def test_REACHABILITY_the_published_total_is_the_mean_of_the_published_histogram(monkeypatch, tmp_path):
    monkeypatch.setenv(ltd.SWITCH_ENV, "on")
    _meta, snapshot, _status = _run_tick(monkeypatch, tmp_path)
    lane = _lane(snapshot)
    dist = {int(k): v for k, v in lane["projection"]["totalRunsDist"].items()}
    assert sum(dist.values()) == lane["simsRun"]
    assert lane["projection"]["total"] == pytest.approx(sum(k * v for k, v in dist.items()) / sum(dist.values()),
                                                       abs=1e-3)


def test_REACHABILITY_the_calibrated_total_prices_through_the_real_join(monkeypatch, tmp_path):
    """The join reads `totalRunsDist`: the calibrated one must be the one it prices."""
    from syndicate.features.shared.live_gameline_join import build_live_gameline_index, lens_sources_for_sport

    monkeypatch.setenv(ltd.SWITCH_ENV, "on")
    _meta, snapshot, _status = _run_tick(monkeypatch, tmp_path)
    index = build_live_gameline_index(snapshot, sources=lens_sources_for_sport("ncaaf"), diagnostics={},
                                      sport="ncaaf")
    (hit,) = index.values()
    published = _lane(snapshot)["projection"]["totalRunsDist"]
    assert {str(k): v for k, v in (hit.get("total_runs_dist") or hit.get("totalRunsDist") or {}).items()} == \
        {str(k): v for k, v in published.items()}


# --------------------------------------------------------------------------
# THE SNAPSHOT PASS: its inputs
# --------------------------------------------------------------------------

def _games():
    return [{"away_team": "Boise State", "home_team": "Oregon", "live_key": "a"},
            {"away_team": "Marshall", "home_team": "Penn State", "live_key": "b"}]


def _index():
    row = {"in_progress": True, "final": False}
    return {"a": {**row, "period": 2, "clock": "11:17", "home_score": 7, "away_score": 7,
                  "situation": {"down": 4, "distance": 5, "yardLine": 97}},
            "b": {**row, "period": 3, "clock": "13:28", "home_score": 17, "away_score": 0,
                  "situation": {"down": 2, "distance": 5, "yardLine": 24}}}


def _snapshot(sims=40):
    return lr.build_live_lens_snapshot("2026-11-14", games=_games(), live_index=_index(), ratings=RATINGS, sims=sims)


def test_the_kickoff_total_is_the_resim_itself_at_kickoff_and_is_computed_once():
    snap = _snapshot()
    ltd.calibrate_snapshot_totals(snap, ratings=RATINGS, date_str="2026-11-14", env={ltd.SWITCH_ENV: "on"})
    kick = lr.resim_live_game(lr.NcaafLiveGameState(away_team="Boise State", home_team="Oregon", period=1,
                                                    clock_seconds=900, home_score=0, away_score=0),
                              home_offense=1.2, home_defense=0.6, away_offense=0.1, away_defense=0.1, sims=40)
    (oregon,) = [g for g in snap["games"] if g["home_name"] == "Oregon"]  # the snapshot runs cheapest-first
    block = oregon["gameLens"][0]["projection"]["totalCalibration"]
    assert block["kickoffTotal"] == pytest.approx(kick["total_mean"], abs=1e-3)
    assert block["offset"] == pytest.approx(61.5 - kick["total_mean"], abs=1e-3)
    assert snap["totalCalibration"]["kickoff_sims"] == 2
    again = _snapshot()
    summary = ltd.calibrate_snapshot_totals(again, ratings=RATINGS, date_str="2026-11-14", env={ltd.SWITCH_ENV: "on"})
    assert summary["kickoff_sims"] == 0 and summary["anchored"] == 2


def test_with_852s_damping_on_the_kickoff_total_is_the_DAMPED_kickoff_resim(monkeypatch):
    """#852 (`live_blowout_damping`) changes `resim_live_game`'s default profile. The snapshot's draws and E0 must come
    from the same engine: both damped when its switch is on, and a cached undamped E0 must not be reused."""
    from syndicate.features.ncaaf import live_blowout_damping as lbd

    kickoff = lr.NcaafLiveGameState(away_team="Boise State", home_team="Oregon", period=1, clock_seconds=900,
                                    home_score=0, away_score=0)

    def oregon_e0():
        snap = _snapshot()
        ltd.calibrate_snapshot_totals(snap, ratings=RATINGS, date_str="2026-11-14", env={ltd.SWITCH_ENV: "on"})
        (oregon,) = [g for g in snap["games"] if g["home_name"] == "Oregon"]
        return oregon["gameLens"][0]["projection"]["totalCalibration"]["kickoffTotal"]

    plain = oregon_e0()
    monkeypatch.setenv(lbd.SWITCH_ENV, "on")
    damped = oregon_e0()  # same process, same cache: the key must tell the two engines apart
    kick = lr.resim_live_game(kickoff, home_offense=1.2, home_defense=0.6, away_offense=0.1, away_defense=0.1, sims=40)
    assert "blowout_damping" in kick
    assert damped == pytest.approx(kick["total_mean"], abs=1e-3)
    assert damped != pytest.approx(plain, abs=1e-3)


def test_kickoff_sims_are_capped_per_tick_and_the_rest_are_widened_by_name():
    snap = _snapshot()
    summary = ltd.calibrate_snapshot_totals(snap, ratings=RATINGS, date_str="2026-11-14", env={ltd.SWITCH_ENV: "on"},
                                            max_kickoff_sims=1)
    assert summary["kickoff_sims"] == 1
    assert summary["anchored"] == 1 and summary["widened_only:kickoff_total_pending"] == 1


def test_a_game_with_no_close_is_widened_and_names_why(monkeypatch):
    monkeypatch.setattr(ltd, "_closing_totals", lambda date: {})
    raw = _snapshot()
    snap = _snapshot()
    summary = ltd.calibrate_snapshot_totals(snap, ratings=RATINGS, date_str="2026-11-14", env={ltd.SWITCH_ENV: "on"})
    assert summary == {"k": [1.2, 1.6], "kickoff_sims": 0, "widened_only:no_closing_total": 2}
    for g_raw, g in zip(raw["games"], snap["games"]):
        block = g["gameLens"][0]["projection"]["totalCalibration"]
        assert block["anchorRefusal"] == "no_closing_total" and "offset" not in block
        assert g["gameLens"][0]["projection"]["totalRunsDist"] != g_raw["gameLens"][0]["projection"]["totalRunsDist"]


def test_refused_lanes_are_left_alone():
    snap = lr.build_live_lens_snapshot("2026-11-14", games=_games(), live_index={}, ratings=RATINGS, sims=20)
    before = json.loads(json.dumps(snap))
    summary = ltd.calibrate_snapshot_totals(snap, ratings=RATINGS, date_str="2026-11-14", env={ltd.SWITCH_ENV: "on"})
    assert summary == {"k": [1.2, 1.6], "kickoff_sims": 0}
    snap.pop("totalCalibration")
    assert snap == before


def test_the_close_falls_back_to_the_previous_shard_for_games_past_midnight_utc(monkeypatch):
    shards = {"2026-11-15": {}, "2026-11-14": {("oregon", "boise state"): (61.5, 9)}}
    monkeypatch.setattr(ltd, "_closing_totals", lambda date: shards[date])
    assert ltd.anchor_dates("2026-11-15") == ["2026-11-15", "2026-11-14"]
    assert ltd.closing_total_for(ltd.anchor_dates("2026-11-15"), "Oregon", "Boise State") == (61.5, 9)
    assert ltd.closing_total_for(ltd.anchor_dates("2026-11-15"), "Boise State", "Oregon") == (61.5, 9)
    assert ltd.closing_total_for(["2026-11-15"], "Oregon", "Boise State") is None


# --------------------------------------------------------------------------
# CORRECTNESS of the transform
# --------------------------------------------------------------------------

DRAWS = [21, 24, 28, 31, 31, 34, 35, 38, 41, 42, 45, 45, 48, 49, 52, 55, 56, 59, 62, 66]


def test_identity_at_k_one_and_no_anchor():
    assert ltd.calibrate_total_draws(DRAWS, score_so_far=14, remaining_share=0.5, anchor_offset=None, k=1.0) == DRAWS


@pytest.mark.parametrize("rho,offset", [(1.0, 6.5), (0.5, 6.5), (0.25, -4.0), (0.0, 9.0), (0.7, 0.3)])
def test_the_anchor_moves_the_mean_by_offset_times_the_share_left(rho, offset):
    out = ltd.calibrate_total_draws(DRAWS, score_so_far=0, remaining_share=rho, anchor_offset=offset, k=1.0)
    assert len(out) == len(DRAWS)
    assert statistics.fmean(out) == pytest.approx(statistics.fmean(DRAWS) + offset * rho, abs=0.5 / len(DRAWS))
    assert max(abs(a - (b + offset * rho)) for a, b in zip(out, sorted(DRAWS))) < 1.0


def test_the_spread_scales_by_k_and_keeps_the_mean():
    out = ltd.calibrate_total_draws(DRAWS, score_so_far=0, remaining_share=0.6, anchor_offset=None, k=1.2)
    assert statistics.fmean(out) == pytest.approx(statistics.fmean(DRAWS), abs=0.05)
    assert statistics.pstdev(out) == pytest.approx(1.2 * statistics.pstdev(DRAWS), rel=0.03)


def test_points_already_scored_are_never_taken_back():
    late = [24, 24, 24, 24, 27, 27, 31, 31, 34, 38]
    out = ltd.calibrate_total_draws(late, score_so_far=24, remaining_share=0.05, anchor_offset=-12.0, k=1.5)
    assert min(out) >= 24 and len(out) == len(late)


def test_the_floor_does_not_move_the_centre():
    """Widening a late, lumpy histogram pushes draws below the score; flooring them alone would raise the mean."""
    late = [24] * 50 + [27] * 20 + [31] * 35 + [34] * 10 + [38] * 5
    out = ltd.calibrate_total_draws(late, score_so_far=24, remaining_share=0.08, anchor_offset=None, k=1.5)
    assert min(out) >= 24
    assert statistics.fmean(out) == pytest.approx(statistics.fmean(late), abs=0.5 / len(late) + 1e-9)
    assert statistics.pstdev(out) > statistics.pstdev(late)


def test_the_histogram_round_trips_the_draws():
    assert ltd.histogram([3, 1, 3, 2]) == {"1": 1, "2": 1, "3": 2}
    assert sorted(ltd._draws(ltd.histogram(DRAWS))) == sorted(DRAWS)


def test_the_share_left_is_regulation_only():
    assert ltd.remaining_regulation_share(1, 900) == 1.0
    assert ltd.remaining_regulation_share(2, 450) == pytest.approx(0.625)
    assert ltd.remaining_regulation_share(4, 0) == 0.0
    assert ltd.remaining_regulation_share(5, 600) == 0.0
    assert ltd.remaining_regulation_share(None, 600) == 0.0


@pytest.mark.parametrize("raw,expected", [("", 1.2), ("1.35", 1.35), ("abc", 1.2), ("-1", 1.2), ("0", 1.2),
                                          ("inf", 1.2)])
def test_a_typo_in_k_falls_back_to_the_default_not_to_no_widening(raw, expected):
    assert ltd.spread_k({ltd.K_ENV: raw}) == expected
    late = {"": 1.6, "abc": 1.6, "-1": 1.6, "0": 1.6, "inf": 1.6}.get(raw, expected)
    assert ltd.spread_k_late({ltd.K_LATE_ENV: raw}) == late


@pytest.mark.parametrize("played,k", [(0.0, 1.2), (0.3, 1.2), (0.5, 1.2), (0.725, 1.4), (0.95, 1.6), (1.0, 1.6)])
def test_k_is_flat_to_half_time_then_ramps_to_the_late_value_at_95_percent(played, k):
    assert ltd.k_at(1.0 - played, k_early=ltd.DEFAULT_K, k_late=ltd.DEFAULT_K_LATE) == pytest.approx(k)


def test_the_lane_records_the_k_it_used_at_its_own_clock():
    late = ltd.apply(DRAWS, score_so_far=14, period=4, clock_seconds=180, close=None, e0=None)[1]
    early = ltd.apply(DRAWS, score_so_far=14, period=1, clock_seconds=600, close=None, e0=None)[1]
    assert early["k"] == 1.2
    assert late["k"] == pytest.approx(ltd.k_at(180 / 3600, k_early=1.2, k_late=1.6), abs=1e-4)


@pytest.mark.parametrize("raw,on", [("on", True), ("1", True), ("TRUE", True), ("yes", True), ("off", False),
                                    ("", False), ("0", False), ("enabled", False)])
def test_the_switch_reads_only_explicit_on_values(raw, on):
    assert ltd.enabled({ltd.SWITCH_ENV: raw}) is on
