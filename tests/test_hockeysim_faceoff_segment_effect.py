"""Unit tests for `historical_truth.faceoff_segment_effect` — the segment-level (not
season-aggregate) validation of `_faceoff_multipliers`: does winning a real faceoff produce a
real, measurable shot-generation edge in the seconds immediately following that specific draw?
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_segment_effect import (
    compute_post_faceoff_shots,
    compute_post_faceoff_shots_by_strength_role,
    summarize_post_faceoff_shots,
)

HOME_ID, AWAY_ID = 13, 16


def _mmss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _faceoff(owner_id, seconds, period=1, situation="1551", zone=None):
    details = {"eventOwnerTeamId": owner_id}
    if zone is not None:
        details["zoneCode"] = zone
    return {"typeDescKey": "faceoff", "situationCode": situation,
            "periodDescriptor": {"number": period}, "timeInPeriod": _mmss(seconds),
            "details": details}


def _shot(owner_id, seconds, period=1, situation="1551", kind="shot-on-goal"):
    return {"typeDescKey": kind, "situationCode": situation,
            "periodDescriptor": {"number": period}, "timeInPeriod": _mmss(seconds),
            "details": {"eventOwnerTeamId": owner_id}}


def _payload(plays, *, home_id=HOME_ID, away_id=AWAY_ID):
    return {"id": 1, "plays": plays, "homeTeam": {"id": home_id}, "awayTeam": {"id": away_id}}


def test_shot_by_winner_within_window_counts_as_winner_shot():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(HOME_ID, 5),
    ]), window_seconds=15)
    assert rec.n_faceoffs == 1
    assert rec.winner_shots == 1
    assert rec.other_shots == 0


def test_shot_by_loser_within_window_counts_as_other_shot():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(AWAY_ID, 5),
    ]), window_seconds=15)
    assert rec.winner_shots == 0
    assert rec.other_shots == 1


def test_shot_after_window_is_not_counted():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(HOME_ID, 20),  # outside a 15s window
    ]), window_seconds=15)
    assert rec.winner_shots == 0
    assert rec.other_shots == 0


def test_window_truncates_at_the_next_faceoff_not_double_counted():
    """A shot between two close-together draws must attribute to the SECOND draw's window only,
    not the first's (whose window is truncated to end exactly where the second draw starts)."""
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _faceoff(AWAY_ID, 10),   # second draw only 10s after the first -- truncates draw 1's window
        _shot(HOME_ID, 12),      # 2s after the SECOND draw, not the first
    ]), window_seconds=15)
    assert rec.n_faceoffs == 2
    # The shot at t=12 is after draw 1's truncated window (ends at t=10) so NOT counted there;
    # it's 2s into draw 2's window (AWAY won draw 2), so it's an "other" shot for draw 2.
    assert rec.winner_shots == 0
    assert rec.other_shots == 1


def test_window_seconds_total_reflects_truncation():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _faceoff(AWAY_ID, 10),
    ]), window_seconds=15)
    # draw 1's window truncates to 10s (ends at draw 2); draw 2's window is the full 15s
    # (nothing truncates it in this fixture).
    assert rec.window_seconds_total == pytest.approx(10.0 + 15.0)


def test_non_ev_faceoff_is_excluded_entirely():
    """A power-play-strength faceoff (unequal skaters) must not be counted as a draw, and must
    not act as a window boundary for a nearby EV draw either."""
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0, situation="1551"),
        _faceoff(AWAY_ID, 5, situation="1451"),   # PP-strength -- excluded
        _shot(HOME_ID, 8, situation="1551"),
    ]), window_seconds=15)
    assert rec.n_faceoffs == 1  # only the EV draw counts
    assert rec.winner_shots == 1  # the shot at t=8 still falls in draw 1's (untruncated) window


def test_non_ev_shot_is_excluded():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(HOME_ID, 5, situation="1451"),  # PP-strength shot -- excluded
    ]), window_seconds=15)
    assert rec.winner_shots == 0
    assert rec.other_shots == 0


def test_window_capped_at_period_end():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 1195),  # 5s left in the period; a 15s window would overrun it
    ]), window_seconds=15)
    assert rec.window_seconds_total == pytest.approx(5.0)


def test_missing_plays_returns_none():
    assert compute_post_faceoff_shots({"id": 1}) is None


def test_not_a_dict_returns_none():
    assert compute_post_faceoff_shots(None) is None


def test_goal_events_count_as_shots():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0),
        _shot(HOME_ID, 5, kind="goal"),
    ]), window_seconds=15)
    assert rec.winner_shots == 1


def test_summary_aggregates_across_games():
    recs = [
        compute_post_faceoff_shots(_payload([_faceoff(HOME_ID, 0), _shot(HOME_ID, 5)]), window_seconds=15),
        compute_post_faceoff_shots(_payload([_faceoff(HOME_ID, 0), _shot(AWAY_ID, 5)]), window_seconds=15),
    ]
    summary = summarize_post_faceoff_shots(recs)
    assert summary.n_games == 2
    assert summary.n_faceoffs == 2
    assert summary.winner_shots == 1
    assert summary.other_shots == 1
    assert summary.winner_share == pytest.approx(0.5)


def test_summary_empty_is_zeroed_not_a_crash():
    summary = summarize_post_faceoff_shots([])
    assert summary.n_games == 0
    assert summary.winner_share == 0.0


# ---------------------------------------------------------------------------
# `winner_zone` filter -- the population `hockeysim_faceoff_dz_segment_validation_report.md`
# needs to test the DZ mechanism's dual offense/defense claim directly.
# ---------------------------------------------------------------------------

def test_winner_zone_filter_keeps_only_matching_draws():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0, zone="D"),
        _shot(HOME_ID, 5),
        _faceoff(AWAY_ID, 50, zone="O"),  # different draw, different zone -- excluded
        _shot(AWAY_ID, 55),
    ]), window_seconds=15, winner_zone="D")
    assert rec.n_faceoffs == 1
    assert rec.winner_shots == 1
    assert rec.other_shots == 0


def test_winner_zone_filter_excludes_non_matching_draws_entirely():
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0, zone="O"),
        _shot(HOME_ID, 5),
    ]), window_seconds=15, winner_zone="D")
    assert rec.n_faceoffs == 0
    assert rec.winner_shots == 0


def test_winner_zone_filter_none_matches_original_unfiltered_behaviour():
    plays = [_faceoff(HOME_ID, 0, zone="D"), _shot(HOME_ID, 5),
             _faceoff(AWAY_ID, 50, zone="O"), _shot(AWAY_ID, 55)]
    unfiltered = compute_post_faceoff_shots(_payload(plays), window_seconds=15)
    assert unfiltered.n_faceoffs == 2
    assert unfiltered.winner_shots == 2


def test_winner_zone_filter_truncation_boundary_uses_any_zone_not_just_matching():
    """The NEXT-faceoff truncation boundary must consider EVERY EV faceoff, regardless of ITS OWN
    zone -- truncation is about not double-counting a shot, not about which draws are studied."""
    rec = compute_post_faceoff_shots(_payload([
        _faceoff(HOME_ID, 0, zone="D"),
        _faceoff(AWAY_ID, 10, zone="O"),  # different zone, but still truncates draw 1's window
        _shot(HOME_ID, 12),
    ]), window_seconds=15, winner_zone="D")
    assert rec.n_faceoffs == 1  # only the "D" draw is studied
    assert rec.winner_shots == 0  # the shot at t=12 falls after draw 1's truncated window (ends t=10)
    assert rec.other_shots == 0  # and draw 2 (zone "O") isn't studied at all under this filter


# ---------------------------------------------------------------------------
# Strength-state (PP/PK) faceoff role -- the population `_extract_timed_events`'s default
# (EV-only) path excludes entirely. situationCode: [awayGoalieInNet][awaySkaters][homeSkaters]
# [homeGoalieInNet]. "1451" = home has the skater advantage (home PP); "1541" = away does.
# ---------------------------------------------------------------------------

def test_pp_role_isolates_draws_the_advantaged_team_won():
    """HOME wins a draw while HOME has the skater advantage ("1451") -- winner_role="PP" must
    count it; winner_role="PK" must not."""
    payload = _payload([_faceoff(HOME_ID, 0, situation="1451"), _shot(HOME_ID, 5)])
    pp = compute_post_faceoff_shots_by_strength_role(payload, window_seconds=15, winner_role="PP")
    pk = compute_post_faceoff_shots_by_strength_role(payload, window_seconds=15, winner_role="PK")
    assert pp.n_faceoffs == 1
    assert pp.winner_shots == 1
    assert pk.n_faceoffs == 0


def test_pk_role_isolates_draws_the_shorthanded_team_won():
    """AWAY wins a draw while HOME has the skater advantage ("1451") -- AWAY is shorthanded, so
    winner_role="PK" must count it; winner_role="PP" must not."""
    payload = _payload([_faceoff(AWAY_ID, 0, situation="1451"), _shot(AWAY_ID, 5)])
    pp = compute_post_faceoff_shots_by_strength_role(payload, window_seconds=15, winner_role="PP")
    pk = compute_post_faceoff_shots_by_strength_role(payload, window_seconds=15, winner_role="PK")
    assert pk.n_faceoffs == 1
    assert pk.winner_shots == 1
    assert pp.n_faceoffs == 0


def test_role_flips_with_which_side_has_the_advantage():
    """Same HOME winner, opposite situationCode ("1541" = AWAY has the advantage) -- HOME is now
    the shorthanded winner, so this must classify as PK, not PP (the role is relative to who has
    the skater advantage, not a fixed home/away label)."""
    payload = _payload([_faceoff(HOME_ID, 0, situation="1541")])
    pp = compute_post_faceoff_shots_by_strength_role(payload, window_seconds=15, winner_role="PP")
    pk = compute_post_faceoff_shots_by_strength_role(payload, window_seconds=15, winner_role="PK")
    assert pk.n_faceoffs == 1
    assert pp.n_faceoffs == 0


def test_strength_role_excludes_ev_draws_entirely():
    payload = _payload([_faceoff(HOME_ID, 0, situation="1551"), _shot(HOME_ID, 5)])
    pp = compute_post_faceoff_shots_by_strength_role(payload, window_seconds=15, winner_role="PP")
    pk = compute_post_faceoff_shots_by_strength_role(payload, window_seconds=15, winner_role="PK")
    assert pp.n_faceoffs == 0
    assert pk.n_faceoffs == 0


def test_strength_role_counts_shots_from_any_strength_state_in_the_window():
    """Unlike the EV-only path, the post-draw shot count here isn't restricted to matching-strength
    shots -- a shot taken after the man advantage expires (still within the window) counts too,
    since the shot stream doesn't pause for a strength-state change mid-window."""
    payload = _payload([
        _faceoff(HOME_ID, 0, situation="1451"),
        _shot(HOME_ID, 8, situation="1551"),  # PP has already expired by t=8, still counts
    ])
    pp = compute_post_faceoff_shots_by_strength_role(payload, window_seconds=15, winner_role="PP")
    assert pp.winner_shots == 1


def test_strength_role_missing_plays_returns_none():
    assert compute_post_faceoff_shots_by_strength_role({"id": 1}, winner_role="PP") is None


def test_strength_role_backward_compat_ev_only_path_unaffected():
    """The pre-existing EV-only extraction path must still exclude non-EV faceoffs entirely --
    confirms `include_non_ev`'s default (`False`) truly reproduces the original behavior for every
    caller that doesn't opt in."""
    payload = _payload([_faceoff(HOME_ID, 0, situation="1451"), _shot(HOME_ID, 5, situation="1451")])
    rec = compute_post_faceoff_shots(payload, window_seconds=15)
    assert rec.n_faceoffs == 0
