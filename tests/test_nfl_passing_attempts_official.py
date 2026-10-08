"""`passing_attempts` counts OFFICIAL attempts (lane `nfl-passing-yards-prop-coin`, 2026-10-08).

nflverse's `pass_attempt` is 1 on sacks and two-point tries, which put +2.42 attempts per QB-game into both the
model's mean and every backtest's graded outcome. (The name-fallback fix is in test_nfl_prop_name_prior_collision.)
"""
from __future__ import annotations

from syndicate.features.nfl import player_stats as ps


def _play(**kw):
    base = {"passer_player_id": "QB", "pass_attempt": "1", "sack": "0", "two_point_attempt": "0"}
    return base | kw


def test_a_sack_is_not_a_passing_attempt():
    extract = ps._STAT_EXTRACTORS["passing_attempts"]
    assert extract(_play(), "QB") == 1.0
    assert extract(_play(sack="1"), "QB") == 0.0
    assert extract(_play(two_point_attempt="1"), "QB") == 0.0
    assert extract(_play(pass_attempt="0"), "QB") == 0.0
    assert extract(_play(), "OTHER") == 0.0


def test_the_columns_the_extractor_reads_are_loaded():
    """Without these columns every play reads sack=None and the fix is silently inert."""
    assert {"sack", "two_point_attempt"} <= set(ps._PLAY_COLUMNS)
