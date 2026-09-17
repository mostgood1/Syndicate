# -*- coding: utf-8 -*-
"""syndicate/features/soccer/features/live_corners.py -- live corners from the pre-kickoff estimate.

REACHABILITY FIRST (model engine standard): the first test drives the real projection through the call the
poller will make, with the flag off and on, and asserts the published corners DIFFER. Everything else is
correctness on top of that.
"""
import pytest

from syndicate.features.soccer.features import live_corners as lc
from syndicate.features.soccer.features.live_lens import project_live_match

RATING = {"attack_rating": 0.0, "defense_rating": 0.0}


def _state(**over):
    state = {
        "event_id": "401882908", "home_team": "Real Madrid", "away_team": "Sevilla",
        "half": 2, "clock_remaining": 30.0 * 60.0, "score_home": 1, "score_away": 0,
        "home_red_cards": 0, "away_red_cards": 0,
        "home_shots_so_far": 8, "away_shots_so_far": 4,
        "home_shots_on_target_so_far": 3, "away_shots_on_target_so_far": 1,
        "home_corners_so_far": 5, "away_corners_so_far": 2, "player_stats": {},
    }
    state.update(over)
    return state


def _freeze(home=6.4, away=4.1, basis=lc.PREGAME_BASIS, match_id="401882908"):
    return {"matches": {match_id: {"frozen_at": "2026-09-17T18:00:00+00:00", "match": {
        "match_id": match_id, "volume_projection": {"home_corners": home, "away_corners": away, "corners_basis": basis}}}}}


def _project(state):
    return project_live_match(state, home_rating=dict(RATING), away_rating=dict(RATING), simulations=12, seed=1)


# ---------------------------------------------------------------------------- reachability

def test_off_and_on_publish_different_corners_through_the_projection(monkeypatch):
    state = _state()
    pregame = lc.pregame_corners_from_payload(_freeze(), "401882908")

    monkeypatch.setenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", "off")
    off = _project(state)
    off, off_audit = lc.apply_live_corners(off, state, pregame)

    monkeypatch.setenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", "on")
    on = _project(state)
    on, on_audit = lc.apply_live_corners(on, state, pregame)

    assert off_audit["state"] == "disabled" and on_audit["state"] == "applied"
    assert off.projected_total_corners != on.projected_total_corners
    assert off.corners_basis == "sim" and on.corners_basis == lc.LIVE_CORNERS_BASIS
    # the sim's own numbers survive the swap, which is what H32 will grade against
    assert on.sim_projected_total_corners == off.projected_total_corners
    assert on.to_dict()["sim_projected_total_corners"] == off.projected_total_corners
    assert off.to_dict()["sim_projected_total_corners"] is None


def test_the_published_number_is_corners_so_far_plus_the_pregame_total_times_the_share(monkeypatch):
    monkeypatch.delenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", raising=False)
    state = _state()                                     # 60' played, 7 corners so far
    projection = _project(state)
    projection, audit = lc.apply_live_corners(projection, state, (6.4, 4.1))
    share = lc.share_remaining(60 * 60.0)
    assert audit["share_remaining"] == pytest.approx(share)
    assert projection.projected_total_corners == pytest.approx(7 + 10.5 * share, abs=1e-3)
    # the pregame split decides the sides
    assert projection.projected_home_corners == pytest.approx(5 + 10.5 * share * (6.4 / 10.5), abs=1e-3)


# ---------------------------------------------------------------------------- refusals are never silent

@pytest.mark.parametrize("pregame,expected", [
    (None, "no_pregame_estimate"),
    ((0.0, 0.0), "pregame_total_not_positive"),
])
def test_a_missing_or_empty_pregame_estimate_leaves_the_sim_untouched(monkeypatch, pregame, expected):
    monkeypatch.delenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", raising=False)
    state = _state()
    projection = _project(state)
    before = projection.projected_total_corners
    projection, audit = lc.apply_live_corners(projection, state, pregame)
    assert audit["state"] == expected
    assert projection.projected_total_corners == before
    assert projection.corners_basis == "sim" and projection.sim_projected_total_corners is None


def test_a_possession_sim_pregame_number_is_refused_rather_than_used():
    assert lc.pregame_corners_from_payload(_freeze(basis="sim"), "401882908") is None
    assert lc.pregame_corners_from_payload(_freeze(), "other-match") is None


def test_pregame_corners_read_from_a_recommendations_artifact_too():
    payload = {"matches": [{"match_id": "401882908", "volume_projection": {
        "home_corners": 6.0, "away_corners": 4.0, "corners_basis": lc.PREGAME_BASIS}}]}
    assert lc.pregame_corners_from_payload(payload, "401882908") == (6.0, 4.0)


# ---------------------------------------------------------------------------- the clock

@pytest.mark.parametrize("half,remaining,expected_minutes", [
    (1, 45 * 60.0, 0.0),
    (1, 15 * 60.0, 30.0),
    (2, 45 * 60.0, 45.0),
    (2, 0.0, 90.0),
])
def test_elapsed_seconds_reads_the_state_clock(half, remaining, expected_minutes):
    assert lc.elapsed_seconds(_state(half=half, clock_remaining=remaining)) == pytest.approx(expected_minutes * 60.0)


def test_share_remaining_is_monotone_clamped_and_interpolated():
    assert lc.share_remaining(-10.0) == 1.0
    assert lc.share_remaining(0.0) == 1.0
    assert lc.share_remaining(120 * 60.0) == lc.SHARE_TABLE[-1][1]
    mid = lc.share_remaining(32.5 * 60.0)               # halfway between the 30' and 35' points
    assert mid == pytest.approx((0.742 + 0.686) / 2)
    values = [lc.share_remaining(m * 60.0) for m in range(0, 95, 5)]
    assert all(b <= a for a, b in zip(values, values[1:]))


# ---------------------------------------------------------------------------- the artifact the caller reads

def test_load_pregame_payload_prefers_the_freeze_and_merges_services(tmp_path):
    import json as _json
    directory = tmp_path / "la_liga" / "api" / "recommendations"
    directory.mkdir(parents=True)
    (directory / "recommendations_2026-09-17.json").write_text(_json.dumps({"matches": [
        {"match_id": "401882908", "volume_projection": {"home_corners": 1.0, "away_corners": 1.0, "corners_basis": "sim"}}]}), encoding="utf-8")
    early = _freeze(home=5.0, away=5.0)
    early["matches"]["401882908"]["frozen_at"] = "2026-09-17T12:00:00+00:00"
    (directory / "recommendations_prekickoff_2026-09-17.live-odds-worker.json").write_text(_json.dumps(early), encoding="utf-8")
    late = _freeze(home=6.4, away=4.1)
    late["matches"]["401882908"]["frozen_at"] = "2026-09-17T18:30:00+00:00"
    (directory / "recommendations_prekickoff_2026-09-17.refresh-worker-4tx2.json").write_text(_json.dumps(late), encoding="utf-8")

    payload = lc.load_pregame_payload(tmp_path, "la_liga", "2026-09-17")
    assert lc.pregame_corners_from_payload(payload, "401882908") == (6.4, 4.1)   # the later freeze wins


def test_load_pregame_payload_falls_back_to_the_artifact_and_never_raises(tmp_path):
    import json as _json
    directory = tmp_path / "epl" / "api" / "recommendations"
    directory.mkdir(parents=True)
    (directory / "recommendations_2026-09-17.json").write_text(_json.dumps({"matches": [
        {"match_id": "x", "volume_projection": {"home_corners": 6.0, "away_corners": 4.0, "corners_basis": lc.PREGAME_BASIS}}]}), encoding="utf-8")
    assert lc.pregame_corners_from_payload(lc.load_pregame_payload(tmp_path, "epl", "2026-09-17"), "x") == (6.0, 4.0)
    assert lc.load_pregame_payload(tmp_path, "nowhere", "2026-09-17") == {}
