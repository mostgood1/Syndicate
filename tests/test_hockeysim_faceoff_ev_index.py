"""Unit tests for `historical_truth.faceoff_ev_index` — closes a real mismatch between
`engine.py`'s `faceoff_ev_only=True` gate and the all-situations `faceoff_win_pct` blend it was
fed: this module produces a genuinely EV-SPECIFIC per-team faceoff win-rate signal, parsed from
real `situationCode` strength-state data in the `playbyplay` cache.
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_ev_index import (
    DEFAULT_FACEOFF_EV_INDEX,
    MIN_GAMES_FOR_FACEOFF_INDEX,
    compute_team_faceoff_ev_index,
    parse_playbyplay_faceoffs_ev,
)


def _faceoff_event(*, owner_id, situation="1551"):
    return {
        "typeDescKey": "faceoff",
        "situationCode": situation,
        "details": {"eventOwnerTeamId": owner_id},
    }


def _playbyplay(*, home_id=13, away_id=16, home_abbr="FLA", away_abbr="CHI",
                 home_ev_wins=20, away_ev_wins=15, pp_events=2):
    plays = []
    for _ in range(home_ev_wins):
        plays.append(_faceoff_event(owner_id=home_id, situation="1551"))
    for _ in range(away_ev_wins):
        plays.append(_faceoff_event(owner_id=away_id, situation="1551"))
    # PP-strength faceoffs (unequal skaters) -- must be EXCLUDED from the EV count regardless of
    # who won them, proving the strength-state filter actually filters.
    for _ in range(pp_events):
        plays.append(_faceoff_event(owner_id=home_id, situation="1451"))
    return {
        "id": 1,
        "homeTeam": {"id": home_id, "abbrev": home_abbr},
        "awayTeam": {"id": away_id, "abbrev": away_abbr},
        "plays": plays,
    }


def test_parse_counts_only_even_strength_faceoffs():
    rec = parse_playbyplay_faceoffs_ev(_playbyplay(home_ev_wins=20, away_ev_wins=15, pp_events=5))
    assert rec is not None
    assert rec.home_ev_wins == 20
    assert rec.away_ev_wins == 15
    assert rec.ev_total == 35  # the 5 PP-strength draws are excluded entirely


def test_parse_excludes_home_and_away_power_play_situation_codes():
    # "1451" = home team on the power play (away 4 skaters, home 5); "1541" = away on the PP.
    payload = _playbyplay(home_ev_wins=10, away_ev_wins=10, pp_events=0)
    payload["plays"].append(_faceoff_event(owner_id=13, situation="1451"))
    payload["plays"].append(_faceoff_event(owner_id=16, situation="1541"))
    rec = parse_playbyplay_faceoffs_ev(payload)
    assert rec.ev_total == 20  # both PP-strength draws excluded


def test_parse_unresolved_owner_is_skipped_not_misattributed():
    payload = _playbyplay(home_ev_wins=10, away_ev_wins=10, pp_events=0)
    payload["plays"].append(_faceoff_event(owner_id=999999, situation="1551"))  # neither team's id
    rec = parse_playbyplay_faceoffs_ev(payload)
    assert rec.ev_total == 20  # the unresolved draw contributes to neither side


def test_parse_missing_team_ids_returns_none():
    payload = _playbyplay()
    del payload["homeTeam"]["id"]
    assert parse_playbyplay_faceoffs_ev(payload) is None


def test_parse_missing_plays_returns_none():
    payload = _playbyplay()
    del payload["plays"]
    assert parse_playbyplay_faceoffs_ev(payload) is None


def test_parse_not_a_dict_or_missing_abbrev_returns_none():
    assert parse_playbyplay_faceoffs_ev(None) is None
    assert parse_playbyplay_faceoffs_ev({}) is None


def test_index_neutral_below_games_floor():
    recs = [parse_playbyplay_faceoffs_ev(_playbyplay()) for _ in range(3)]
    assert 3 < MIN_GAMES_FOR_FACEOFF_INDEX
    idx = compute_team_faceoff_ev_index(recs)
    assert idx["FLA"].index == DEFAULT_FACEOFF_EV_INDEX


def test_index_reflects_a_real_above_average_faceoff_team():
    n = MIN_GAMES_FOR_FACEOFF_INDEX + 5
    # FLA wins EV draws heavily (25 of 30/game), CHI wins them rarely -- enough games to clear
    # the floor.
    recs = [parse_playbyplay_faceoffs_ev(_playbyplay(home_ev_wins=25, away_ev_wins=5)) for _ in range(n)]
    idx = compute_team_faceoff_ev_index(recs)
    assert idx["FLA"].index > 1.0
    assert idx["CHI"].index < 1.0


def test_index_is_self_consistent_zero_sum():
    """Faceoffs are zero-sum (every draw has exactly one winner) -- the league-wide EV win rate
    the index normalizes against should land at (very close to) 0.5 by construction, so a team at
    the true league-average rate lands at index ~= 1.0, not some other baseline."""
    n = MIN_GAMES_FOR_FACEOFF_INDEX + 5
    recs = [parse_playbyplay_faceoffs_ev(_playbyplay(home_ev_wins=15, away_ev_wins=15)) for _ in range(n)]
    idx = compute_team_faceoff_ev_index(recs)
    assert idx["FLA"].index == pytest.approx(1.0, abs=1e-6)
    assert idx["CHI"].index == pytest.approx(1.0, abs=1e-6)


def test_index_missing_data_is_empty_not_a_crash():
    assert compute_team_faceoff_ev_index([]) == {}
