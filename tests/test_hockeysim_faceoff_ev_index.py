"""Unit tests for `historical_truth.faceoff_ev_index` — closes a real mismatch between
`engine.py`'s `faceoff_ev_only=True` gate and the all-situations `faceoff_win_pct` blend it was
fed: this module produces a genuinely EV-SPECIFIC per-team faceoff win-rate signal, parsed from
real `situationCode` strength-state data in the `playbyplay` cache.
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_ev_index import (
    DEFAULT_FACEOFF_EV_INDEX,
    DEFAULT_FACEOFF_OZ_INDEX,
    MIN_GAMES_FOR_FACEOFF_INDEX,
    MIN_GAMES_FOR_FACEOFF_OZ_INDEX,
    compute_team_faceoff_ev_index,
    compute_team_faceoff_oz_index,
    parse_playbyplay_faceoffs_by_zone,
    parse_playbyplay_faceoffs_ev,
)


def _faceoff_event(*, owner_id, situation="1551", zone=None):
    details = {"eventOwnerTeamId": owner_id}
    if zone is not None:
        details["zoneCode"] = zone
    return {
        "typeDescKey": "faceoff",
        "situationCode": situation,
        "details": details,
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


# ---------------------------------------------------------------------------
# Zone-specific (offensive-zone) win index
# ---------------------------------------------------------------------------

def _zone_playbyplay(*, home_id=13, away_id=16, home_abbr="FLA", away_abbr="CHI", plays=None):
    return {
        "id": 1,
        "homeTeam": {"id": home_id, "abbrev": home_abbr},
        "awayTeam": {"id": away_id, "abbrev": away_abbr},
        "plays": plays or [],
    }


def test_zone_parse_attributes_winners_own_zone_directly():
    """`zoneCode` is relative to the WINNER (confirmed against real data, see the module
    docstring) -- a home win with zoneCode="O" counts as a home OZ win directly, no flip needed."""
    payload = _zone_playbyplay(plays=[
        _faceoff_event(owner_id=13, zone="O"),
        _faceoff_event(owner_id=13, zone="D"),
        _faceoff_event(owner_id=13, zone="N"),
    ])
    rec = parse_playbyplay_faceoffs_by_zone(payload)
    assert rec.home_zone_wins == {"O": 1, "N": 1, "D": 1}
    assert rec.home_zone_total["O"] == 1


def test_zone_parse_flips_the_losers_zone():
    """AWAY loses a draw where the WINNER's (home's) zoneCode is "O" -- from away's own
    perspective, that same physical draw is in THEIR defensive zone (O<->D flip), not "O"."""
    payload = _zone_playbyplay(plays=[_faceoff_event(owner_id=13, zone="O")])  # home wins in home's OZ
    rec = parse_playbyplay_faceoffs_by_zone(payload)
    assert rec.away_zone_total["D"] == 1  # away's own frame: this was THEIR defensive zone
    assert rec.away_zone_total["O"] == 0
    assert rec.away_zone_wins == {"O": 0, "N": 0, "D": 0}  # away didn't win it


def test_zone_parse_neutral_zone_does_not_flip():
    payload = _zone_playbyplay(plays=[_faceoff_event(owner_id=16, zone="N")])  # away wins in neutral
    rec = parse_playbyplay_faceoffs_by_zone(payload)
    assert rec.home_zone_total["N"] == 1  # neutral stays neutral for both sides
    assert rec.away_zone_total["N"] == 1


def test_zone_parse_excludes_pp_strength_faceoffs():
    payload = _zone_playbyplay(plays=[
        _faceoff_event(owner_id=13, zone="O", situation="1551"),
        _faceoff_event(owner_id=13, zone="O", situation="1451"),  # home on the PP -- excluded
    ])
    rec = parse_playbyplay_faceoffs_by_zone(payload)
    assert rec.home_zone_total["O"] == 1


def test_zone_parse_missing_zone_code_is_skipped_not_guessed():
    payload = _zone_playbyplay(plays=[_faceoff_event(owner_id=13, zone=None)])
    rec = parse_playbyplay_faceoffs_by_zone(payload)
    assert sum(rec.home_zone_total.values()) == 0
    assert sum(rec.away_zone_total.values()) == 0


def test_zone_parse_not_a_dict_or_missing_ids_returns_none():
    assert parse_playbyplay_faceoffs_by_zone(None) is None
    payload = _zone_playbyplay()
    del payload["homeTeam"]["id"]
    assert parse_playbyplay_faceoffs_by_zone(payload) is None


def test_oz_index_neutral_below_games_floor():
    recs = [parse_playbyplay_faceoffs_by_zone(_zone_playbyplay(
        plays=[_faceoff_event(owner_id=13, zone="O")])) for _ in range(3)]
    assert 3 < MIN_GAMES_FOR_FACEOFF_OZ_INDEX
    idx = compute_team_faceoff_oz_index(recs)
    assert idx["FLA"].index == DEFAULT_FACEOFF_OZ_INDEX


def test_oz_index_reflects_a_real_above_average_oz_winner():
    """Two INDEPENDENT sets of OZ draws (FLA's own OZ, and separately CHI's own OZ) -- each set
    needs BOTH wins and losses to exercise the zone-flip attribution, not just one-sided wins
    (an all-wins fixture would make the league rate itself 1.0, not the true zero-sum 0.5, and
    silently pass regardless of whether the flip logic works at all)."""
    n = MIN_GAMES_FOR_FACEOFF_OZ_INDEX + 5
    plays = (
        [_faceoff_event(owner_id=13, zone="O") for _ in range(7)]  # FLA wins FLA's own OZ, 7x
        + [_faceoff_event(owner_id=16, zone="D") for _ in range(1)]  # CHI wins in FLA's OZ (FLA loses it)
        + [_faceoff_event(owner_id=16, zone="O") for _ in range(1)]  # CHI wins CHI's own OZ, only 1x (weak)
        + [_faceoff_event(owner_id=13, zone="D") for _ in range(7)]  # FLA wins in CHI's OZ (CHI loses it, 7x)
    )
    recs = [parse_playbyplay_faceoffs_by_zone(_zone_playbyplay(plays=plays)) for _ in range(n)]
    idx = compute_team_faceoff_oz_index(recs)
    # FLA: own-OZ rate 7/8=0.875 vs league 0.5 -> index 1.75. CHI: own-OZ rate 1/8=0.125 -> index 0.25.
    assert idx["FLA"].index > 1.0
    assert idx["CHI"].index < 1.0


def test_oz_index_is_self_consistent_zero_sum():
    n = MIN_GAMES_FOR_FACEOFF_OZ_INDEX + 5
    plays = (
        [_faceoff_event(owner_id=13, zone="O") for _ in range(5)]  # FLA wins FLA's own OZ, 5x
        + [_faceoff_event(owner_id=16, zone="D") for _ in range(5)]  # CHI wins in FLA's OZ (FLA loses it, 5x)
        + [_faceoff_event(owner_id=16, zone="O") for _ in range(5)]  # CHI wins CHI's own OZ, 5x
        + [_faceoff_event(owner_id=13, zone="D") for _ in range(5)]  # FLA wins in CHI's OZ (CHI loses it, 5x)
    )
    recs = [parse_playbyplay_faceoffs_by_zone(_zone_playbyplay(plays=plays)) for _ in range(n)]
    idx = compute_team_faceoff_oz_index(recs)
    assert idx["FLA"].index == pytest.approx(1.0, abs=1e-6)
    assert idx["CHI"].index == pytest.approx(1.0, abs=1e-6)


def test_oz_index_missing_data_is_empty_not_a_crash():
    assert compute_team_faceoff_oz_index([]) == {}
