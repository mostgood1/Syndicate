"""LIVE prop markets must match PREGAME's, or the board loses markets at kickoff.

Pregame prices shots, shots on target AND assists per line. Live carried shots
only, so a board pricing three prop markets before kickoff silently dropped to
one the moment a match went in play -- the opposite of what a live tier is for.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import soccer_live_gameline_source as src
from syndicate.features.shared.soccer_projections import _PLAYER_PROB_BY_LINE
from syndicate.features.soccer.features import live_lens as LL
from syndicate.features.soccer.sim_engine.soccersim import player_props as PP


def test_live_and_pregame_price_the_same_prop_markets():
    """The parity claim itself, as a test rather than a comment."""
    assert set(src.SOCCER_LIVE_PROP_MARKETS) == set(_PLAYER_PROB_BY_LINE)


def test_live_reuses_pregame_constants_rather_than_restating_them():
    """A second copy is how the two tiers drift into answering one market with
    different arithmetic."""
    assert LL._ASSIST_LINES is PP._ASSIST_LINES
    assert LL._ASSISTED_GOAL_SHARE == PP._ASSISTED_GOAL_SHARE


def _prop(**over):
    base = {
        "player_name": "Amine Gouiri",
        "shots_so_far": 2, "projected_final_shots": 3.4,
        "shots_over_probabilities": {"0.5": 0.99, "2.5": 0.61},
        "shots_on_target_so_far": 1, "projected_final_shots_on_target": 1.6,
        "shots_on_target_over_probabilities": {"0.5": 0.95, "1.5": 0.44},
        "assists_so_far": 0, "projected_final_assists": 0.18,
        "assists_over_probabilities": {"0.5": 0.17, "1.5": 0.02},
    }
    base.update(over)
    return base


def _index_from(prop, monkeypatch, tmp_path):
    monkeypatch.setattr(src, "soccer_live_games",
                        lambda date, data_root=None: [{"live_player_props": [prop]}])
    return src.soccer_live_prop_index("2026-08-21")


def test_all_three_markets_are_indexed(monkeypatch, tmp_path):
    r = _index_from(_prop(), monkeypatch, tmp_path)
    keys = {(m, l) for (_p, m, l) in r["index"]}
    assert ("player_shots", 2.5) in keys
    assert ("player_shots_on_target", 1.5) in keys
    assert ("player_assists", 0.5) in keys
    assert r["rows_indexed"] == 6


def test_banked_counts_are_per_market_not_shared(monkeypatch, tmp_path):
    """`actual_so_far` on an assists row must be assists, not shots -- reusing
    the shot count would report a player as 2 assists in."""
    r = _index_from(_prop(), monkeypatch, tmp_path)
    idx = r["index"]
    assert idx[("amine gouiri", "player_shots", 2.5)]["actual_so_far"] == 2
    assert idx[("amine gouiri", "player_shots_on_target", 1.5)]["actual_so_far"] == 1
    assert idx[("amine gouiri", "player_assists", 0.5)]["actual_so_far"] == 0


def test_an_older_snapshot_with_shots_only_still_indexes_shots(monkeypatch, tmp_path):
    """Rebuild lag is the norm; losing shots because assists are absent would
    be a regression caused by the fix."""
    old = {"player_name": "Amine Gouiri", "shots_so_far": 2,
           "projected_final_shots": 3.4,
           "shots_over_probabilities": {"2.5": 0.61}}
    r = _index_from(old, monkeypatch, tmp_path)
    assert r["rows_indexed"] == 1
    assert ("amine gouiri", "player_shots", 2.5) in r["index"]


def test_a_player_already_past_the_line_reads_certain():
    """`poisson_at_least(x, 0)` is 1.0, and that is correct: a player with 2
    shots has already cleared 1.5 whatever happens next."""
    p = LL.poisson_at_least(0.4, 0)
    assert p == pytest.approx(1.0)
