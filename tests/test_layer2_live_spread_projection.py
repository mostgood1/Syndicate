"""A live game line's Live column shows its OWN live number (lane nba-live-proj-actuals).

The gameline block's `total_mean` is the GAME's projected total. It was written to `live_total` on every live
gameline row, and the page renders `live_projection ?? live_total` -- so on 2026-11-05 00:49Z live spread rows
(NBA 27, NCAAF 6, NCAAB 3) and moneyline rows (NCAAB 3, NCAAF 1) showed "215.9" beside a -3.5 spread."""
from __future__ import annotations

import pytest

from syndicate.features.shared.layer2_board import _live_projection_columns

GAMELINE = {"total_mean": 215.91, "home_margin_mean": 8.0}


def _row(market, **extra):
    row = {"kind": "game", "market": market, "segment": "full",
           "projection": {"live_model_prob_over": 0.47}, "live_gameline": dict(GAMELINE),
           "game": {"state": "live", "home_score": 50, "away_score": 42}}
    row.update(extra)
    return row


@pytest.mark.parametrize("market", ["totals", "totals_alt", "alternate_totals", "TOTALS"])
def test_a_totals_row_keeps_the_live_projected_total(market):
    out = _live_projection_columns(_row(market))
    assert out["live_total"] == 215.91 and out["live_model_probability"] == 0.47
    assert out["actual"] == 92.0


@pytest.mark.parametrize("market", ["spreads", "spreads_alt", "alternate_spreads", "h2h", "h2h_3_way", "team_totals"])
def test_a_non_totals_row_never_shows_the_game_total(market):
    out = _live_projection_columns(_row(market))
    assert "live_total" not in out and "live_projection" not in out
    assert out["live_aware"] is True  # the row is still live-joined; only the wrong number is gone


def test_a_spread_row_falls_through_to_its_cover_probability():
    out = _live_projection_columns(_row("spreads_alt"))
    assert out["live_model_probability"] == 0.47


def test_a_prop_count_is_untouched():
    row = {"kind": "prop", "market": "player_points", "projection": {"live_projected": 17.36, "actual_so_far": 5.0}}
    out = _live_projection_columns(row)
    assert out["live_projection"] == 17.36 and out["live_total"] == 17.36 and out["actual"] == 5.0
