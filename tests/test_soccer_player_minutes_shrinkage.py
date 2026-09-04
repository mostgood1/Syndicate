"""Thin-minute players are INCLUDED and their rates SHRUNK, not deleted.

`minimum_minutes: float = 180.0` in `player_history.py` had been there since the
engine's first commit with no comment, no test, no ledger entry and no caller
ever overriding it -- and it acted as a ROSTER FILTER. Measured on the live feed
and production artifacts:

    epl 2025-26   440 rows at 180 min  ->  537 at 1 min   (+22%)
    epl 2026-27   100 rows at 180 min  ->  364 at 1 min   (+264%)
    41 of 288 production fixture-sides published ZERO players (14.2%)

Those absences are ~80% of the soccer projection gap, and no name-matching rule
reaches them.

**BUT LOWERING IT TO 1 ALONE WOULD HAVE BEEN THE WRONG FIX.** Every field here
is a PER-90 (`value / minutes * 90`), and `build_usage_profiles` requires that
"the rows only need to be internally COMPARABLE rates" -- then normalises them
into shares summing to ~1.0. A player with one shot in one minute publishes
90 shots/90 and would seize a large share of the team's simulated volume. That
is a fabricated number arriving dressed as a roster fix.

So the same 180 became a STABILISATION constant: shrink toward the positional
prior with weight `minutes / (minutes + 180)`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.ingestion.player_history import (  # noqa: E402
    _RATE_STABILISATION_MINUTES,
    _SHRUNK_PER90_FIELDS,
    normalize_understat_players,
)


def _p(pid, name, minutes, games, shots, goals, position="F"):
    return {"id": pid, "player_name": name, "team_title": "A", "position": position,
            "time": minutes, "games": games, "shots": shots, "xG": goals * 1.1,
            "xA": 0.0, "goals": goals, "assists": 0, "key_passes": 0}


def _rows():
    return normalize_understat_players([
        _p(1, "Regular Starter", 2000, 23, 80, 11),
        _p(2, "Squad Player", 180, 6, 6, 1),
        _p(3, "One Minute Hero", 1, 1, 1, 1),
    ], league="epl", season=2026)


# --- inclusion: the actual fix ----------------------------------------------


def test_thin_minute_players_are_no_longer_dropped():
    """THE fix. Under the old 180 cutoff only the starter survived."""
    rows = _rows()
    assert len(rows) == 3
    assert {r["player_name"] for r in rows} == {
        "Regular Starter", "Squad Player", "One Minute Hero"}


def test_a_player_who_never_played_is_still_excluded():
    """`minimum_minutes` is 1.0, not 0: a squad member with no minutes has no
    rate to estimate and nothing to shrink toward anything."""
    rows = normalize_understat_players(
        [_p(1, "Starter", 2000, 23, 80, 11), _p(9, "Never Played", 0, 0, 0, 0)],
        league="epl", season=2026)
    assert {r["player_name"] for r in rows} == {"Starter"}


# --- the reason a bare threshold change would have been wrong ---------------


def test_the_one_minute_rate_is_NOT_published_raw():
    """One shot in one minute is 90 shots/90. Publishing that into a share
    normalised to ~1.0 hands one player most of the team's volume."""
    hero = next(r for r in _rows() if r["player_name"] == "One Minute Hero")
    assert hero["shots_per90"] < 10.0, hero["shots_per90"]
    assert hero["goals_per90"] < 5.0, hero["goals_per90"]


def test_a_full_season_rate_is_left_essentially_alone():
    """Off != on in the other direction: shrinkage must not blunt a player we
    genuinely know about. 2000 minutes keeps ~92% of its own rate."""
    starter = next(r for r in _rows() if r["player_name"] == "Regular Starter")
    assert starter["rate_own_weight"] > 0.9
    assert abs(starter["shots_per90"] - (80 / 2000 * 90)) < 0.15


def test_the_weight_is_the_documented_curve():
    rows = _rows()
    by = {r["player_name"]: r for r in rows}
    assert abs(by["Squad Player"]["rate_own_weight"] - 0.5) < 1e-6, (
        "%s minutes must sit at half weight -- that is what the constant means"
        % _RATE_STABILISATION_MINUTES)
    assert by["One Minute Hero"]["rate_own_weight"] < 0.01
    assert by["Regular Starter"]["rate_own_weight"] > by["Squad Player"]["rate_own_weight"]


def test_it_is_empirical_bayes_count_shrinkage_in_rate_space():
    """The property that makes this defensible rather than an ad-hoc blend.

        w*own + (1-w)*prior   with w = m/(m+k)  and  own = e/m*90
      = (e*90 + k*prior) / (m+k)

    ...which is exactly shrinking the COUNTS toward the prior. Asserting it
    means a future edit that changes the weight curve cannot quietly stop being
    a principled estimator.
    """
    rows = _rows()
    k = _RATE_STABILISATION_MINUTES
    total_min = sum(float(r["minutes"]) for r in rows)
    # the prior is the POOLED rate: total events over total minutes
    pooled_goals = (11 + 1 + 1) / total_min * 90.0
    hero = next(r for r in rows if r["player_name"] == "One Minute Hero")
    expected = (1 * 90.0 + k * pooled_goals) / (1 + k)
    assert abs(hero["goals_per90"] - expected) < 0.02, (hero["goals_per90"], expected)


def test_every_declared_per90_field_is_shrunk():
    """A field added to the row but not to `_SHRUNK_PER90_FIELDS` would publish
    a raw 90x rate while its neighbours were shrunk -- the inconsistency being
    invisible because both look like rates."""
    hero = next(r for r in _rows() if r["player_name"] == "One Minute Hero")
    for field in _SHRUNK_PER90_FIELDS:
        assert field in hero, field
        assert hero[field] < 10.0, (field, hero[field])


def test_expected_minutes_share_is_deliberately_NOT_shrunk():
    """It is a share of a player's OWN appearances, not a rate estimated from
    them. Shrinking it would distort the very quantity that says how thin the
    sample is."""
    assert "expected_minutes_share" not in _SHRUNK_PER90_FIELDS
    hero = next(r for r in _rows() if r["player_name"] == "One Minute Hero")
    assert hero["expected_minutes_share"] > 0.0


def test_an_empty_population_does_not_raise():
    assert normalize_understat_players([], league="epl", season=2026) == []


# ---------------------------------------------------------------------------
# TWO DEFECTS IN THE FIRST VERSION OF THIS FIX, both found by the producer-step
# scoping pass rather than by these tests. Pinned so they cannot return.
# ---------------------------------------------------------------------------


def test_multi_position_strings_share_ONE_prior():
    """The bucket key was `position.upper()[:2]`, which turned Understat's
    multi-position strings into SEPARATE buckets:

        'D'      -> 'D'
        'D M'    -> 'D '     <- a different bucket
        'D M S'  -> 'D '

    Measured on real EPL data: 154 rows in one and 26 in the other. A fragmented
    bucket gives a noisier prior, and the prior is exactly what a thin-minute
    player is shrunk toward -- so the defect landed hardest on the rows this
    whole change exists to rescue.
    """
    rows = normalize_understat_players([
        _p(1, "Pure Defender", 2000, 23, 20, 1, position="D"),
        _p(2, "Def Mid", 1800, 21, 25, 2, position="D M"),
        _p(3, "Def Mid Sub", 1500, 20, 18, 1, position="D M S"),
        _p(4, "Thin Defender", 30, 3, 1, 1, position="D"),
    ], league="epl", season=2026)
    thin = next(r for r in rows if r["player_name"] == "Thin Defender")
    # 1 shot in 30 minutes is 3.0/90 raw. Shrunk toward the COMBINED defender
    # prior it lands near the squad's real defender rate.
    assert thin["shots_per90"] < 2.0, thin["shots_per90"]
    assert thin["rate_own_weight"] < 0.2


def test_goalkeeper_spellings_do_not_split():
    """`'GK'` and `'GK '` both keyed to `'GK'` by luck of the slice; a token
    split makes that true by construction rather than by coincidence."""
    rows = normalize_understat_players([
        _p(1, "Keeper A", 2000, 23, 0, 0, position="GK"),
        _p(2, "Keeper B", 1800, 20, 0, 0, position="GK "),
    ], league="epl", season=2026)
    assert len(rows) == 2
    assert all(r["rate_own_weight"] > 0.85 for r in rows)


def test_a_blank_position_still_buckets_without_raising():
    rows = normalize_understat_players([
        _p(1, "No Position", 900, 10, 9, 1, position=""),
    ], league="epl", season=2026)
    assert len(rows) == 1 and "rate_own_weight" in rows[0]


def test_the_MLS_path_shrinks_too():
    """`normalize_asa_players` builds the same per-90 fields and returned them
    RAW. It is not producing bad rows today only because ASA applies
    `minimum_minutes` SERVER-SIDE as a request parameter, so thin rows never
    arrive -- which also means lowering the local threshold does nothing there.

    That left a loaded gun: the moment the `--kind players` producer step lowers
    that request parameter, MLS would publish raw 90-shots/90 rows into a share
    that normalises to ~1.0. This asserts the shrinkage is in the path.
    """
    from syndicate.features.soccer.ingestion import player_history as ph
    import inspect

    src = inspect.getsource(ph.normalize_asa_players)
    assert "_shrink_toward_prior" in src, (
        "the MLS normaliser must shrink like the Understat one, or lowering "
        "ASA's server-side minimum_minutes becomes a fabricated-rate bug")
