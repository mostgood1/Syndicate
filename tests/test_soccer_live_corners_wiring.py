# -*- coding: utf-8 -*-
"""The CALL SITE: `poll_soccer_live_state.poll_league` must actually apply the live corners estimate.

`tests/test_soccer_live_corners.py` proves the module works. This proves PRODUCTION REACHES IT -- the
distinction that made four fixes inert in one session (`learnings.md`, presence is not reachability).
Both tests fail on the pre-wiring code: this one because `live_corners` is absent from the served game.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import poll_soccer_live_state as poller  # noqa: E402
from syndicate.features.soccer.features import live_corners as lc  # noqa: E402
from syndicate.features.soccer.features.live_lens import LiveMatchProjection  # noqa: E402

EVENT_ID = "401882908"
LEAGUE = "la_liga"
DATE = "2026-09-17"


def _live_state():
    return {"event_id": EVENT_ID, "home_team": "Real Madrid", "away_team": "Sevilla", "half": 2,
            "clock_remaining": 30 * 60.0, "score_home": 1, "score_away": 0, "home_red_cards": 0, "away_red_cards": 0,
            "home_shots_so_far": 8, "away_shots_so_far": 4, "home_shots_on_target_so_far": 3,
            "away_shots_on_target_so_far": 1, "home_corners_so_far": 5, "away_corners_so_far": 2, "player_stats": {}}


def _projection():
    return LiveMatchProjection(
        simulations=10, home_win_probability=0.7, draw_probability=0.2, away_win_probability=0.1,
        projected_final_home_goals=2.0, projected_final_away_goals=0.7, projected_final_total=2.7,
        over_2_5_probability=0.5, both_teams_scored_probability=0.4,
        projected_home_corners=9.0, projected_away_corners=5.0, projected_total_corners=14.0,
        home_red_card_applied=False, away_red_card_applied=False, scoreline_probabilities={"2-0": 0.3})


@pytest.fixture
def wired(monkeypatch, tmp_path):
    source_root, out_root = tmp_path / "source", tmp_path / "out"
    directory = source_root / LEAGUE / "api" / "recommendations"
    directory.mkdir(parents=True)
    (directory / f"recommendations_prekickoff_{DATE}.live-odds-worker.json").write_text(json.dumps({
        "league": LEAGUE, "date": DATE, "matches": {EVENT_ID: {"frozen_at": "2026-09-17T18:00:00+00:00", "match": {
            "match_id": EVENT_ID, "volume_projection": {
                "home_corners": 6.4, "away_corners": 4.1, "corners_basis": lc.PREGAME_BASIS}}}}}), encoding="utf-8")

    monkeypatch.setattr(poller, "fetch_events", lambda *a, **k: [
        {"event_id": EVENT_ID, "home_team": "Real Madrid", "away_team": "Sevilla",
         "status_display_clock": "60'", "status_period": 2, "status_detail": "2nd Half"}])
    monkeypatch.setattr(poller, "build_live_state", lambda *a, **k: _live_state())
    monkeypatch.setattr(poller, "fetch_match_summary", lambda *a, **k: {})
    monkeypatch.setattr(poller, "_load_team_ratings", lambda *a, **k: {})
    monkeypatch.setattr(poller, "_fill_promoted", lambda *a, **k: None)
    monkeypatch.setattr(poller, "_load_player_rows", lambda *a, **k: [])
    monkeypatch.setattr(poller, "_rating_for", lambda *a, **k: {"attack_rating": 0.0, "defense_rating": 0.0})
    monkeypatch.setattr(poller, "project_live_match", lambda *a, **k: _projection())
    monkeypatch.setattr(poller, "goal_in_window_probability", lambda *a, **k: 0.1)
    monkeypatch.setattr(poller, "project_live_player_props", lambda *a, **k: [])
    monkeypatch.setattr(poller, "fotmob_momentum_block", lambda *a, **k: {"supported": False})
    monkeypatch.setattr(poller, "_build_match_boxes", lambda *a, **k: {})
    return source_root, out_root


def test_the_poller_applies_the_pregame_corners_and_keeps_the_sim_beside(monkeypatch, wired):
    source_root, out_root = wired
    monkeypatch.delenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", raising=False)
    result = poller.poll_league(LEAGUE, DATE, source_root=source_root, out_root=out_root, simulations=10)
    game = result["games"][EVENT_ID]

    assert game["live_corners"]["state"] == "applied"
    projection = game["projection"]
    assert projection["corners_basis"] == lc.LIVE_CORNERS_BASIS
    assert projection["sim_projected_total_corners"] == 14.0            # the sim's own number survives
    share = lc.share_remaining(60 * 60.0)
    assert projection["projected_total_corners"] == pytest.approx(7 + 10.5 * share, abs=1e-3)
    assert projection["projected_total_corners"] != 14.0


def test_the_flag_off_serves_the_sim_untouched(monkeypatch, wired):
    source_root, out_root = wired
    monkeypatch.setenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", "off")
    game = poller.poll_league(LEAGUE, DATE, source_root=source_root, out_root=out_root, simulations=10)["games"][EVENT_ID]
    assert game["live_corners"]["state"] == "disabled"
    assert game["projection"]["projected_total_corners"] == 14.0
    assert game["projection"]["corners_basis"] == "sim"


def test_a_match_with_no_pregame_estimate_serves_the_sim_and_says_so(monkeypatch, wired, tmp_path):
    source_root, out_root = wired
    monkeypatch.delenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", raising=False)
    for path in (source_root / LEAGUE / "api" / "recommendations").glob("*.json"):
        path.unlink()
    game = poller.poll_league(LEAGUE, DATE, source_root=source_root, out_root=out_root, simulations=10)["games"][EVENT_ID]
    assert game["live_corners"]["state"] == "no_pregame_estimate"
    assert game["projection"]["projected_total_corners"] == 14.0


def test_the_history_accumulates_across_ticks_and_survives_the_match_leaving_games(monkeypatch, wired):
    """The durable capture: rows written by one tick are still in the artifact after the match ends."""
    source_root, out_root = wired
    monkeypatch.delenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", raising=False)
    first = poller.poll_league(LEAGUE, DATE, source_root=source_root, out_root=out_root, simulations=10)
    assert len(first["projection_history"][EVENT_ID]) == 1
    row = first["projection_history"][EVENT_ID][0]
    assert row["corners_basis"] == lc.LIVE_CORNERS_BASIS
    assert row["sim_projected_total_corners"] == 14.0 and row["live_corners_state"] == "applied"

    second = poller.poll_league(LEAGUE, DATE, source_root=source_root, out_root=out_root, simulations=10)
    assert len(second["projection_history"][EVENT_ID]) == 2, "the second tick must append, not replace"

    # the match ends: no in-play events at all, and the rows must still be there
    monkeypatch.setattr(poller, "fetch_events", lambda *a, **k: [])
    after = poller.poll_league(LEAGUE, DATE, source_root=source_root, out_root=out_root, simulations=10)
    assert after["games"] == {}
    assert len(after["projection_history"][EVENT_ID]) == 2


def test_a_corrupt_previous_artifact_starts_the_history_again_without_failing_the_tick(monkeypatch, wired):
    source_root, out_root = wired
    monkeypatch.delenv("SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR", raising=False)
    poller.poll_league(LEAGUE, DATE, source_root=source_root, out_root=out_root, simulations=10)
    path = out_root / LEAGUE / "api" / "live_state" / f"live_state_{DATE}.json"
    path.write_text("{ this is not json", encoding="utf-8")
    result = poller.poll_league(LEAGUE, DATE, source_root=source_root, out_root=out_root, simulations=10)
    assert len(result["projection_history"][EVENT_ID]) == 1
