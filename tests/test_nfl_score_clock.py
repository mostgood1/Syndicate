"""The score-and-clock model: the sign, the ties, and the refusals.

This model exists because smartsim2's NFL live re-sim LOSES to a frozen
baseline (measured 2026-09-27: MAE 9.596 vs 7.522 over 32 games) and still
loses after its too-narrow distribution is corrected. Its ratings carry about as
much noise as signal, so this uses only what is OBSERVED -- the scoreboard and
the clock.

It has no fitted parameters, so the things that can go wrong are not
overfitting. They are:

  * THE SIGN, because the fit folds every observation onto the leader's
    perspective to double its cells and a trailing home team's draw must be
    negated back. Getting this backwards yields a confident distribution
    pointed the wrong way -- the inversion `price_distribution_market` warns
    about, which once put 0.74 on MLB underdogs.
  * THE TIES, because NFL regular-season games can end level and a tie is
    neither a home win nor an away win.
  * THE REFUSALS, because a live model that invents a distribution where it has
    no evidence is indistinguishable from one that has evidence.
  * THE FALLBACK BEING VISIBLE, because a cell-backed answer and a pooled one
    are different claims.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.score_clock import (  # noqa: E402
    load_score_clock_model,
    score_clock_model_path,
)


def _artifact(tmp_path, *, cells=None, cell_n=None, pooled=None, min_cell_n=60):
    art = {
        "schema_version": 1,
        "fit_seasons": [2023, 2024, 2025],
        "games": 800,
        "observations": 2400,
        "min_cell_n": min_cell_n,
        "margin_buckets": ["0-3", "4-10", "11-17", "18-99"],
        "margin_rest_correlation_by_period": {"1": 0.29, "2": 0.11, "3": -0.07},
        # REST from the LEADER's perspective: the leader tends to give some back.
        "pooled_by_period": pooled or {"1": {"-7": 100, "0": 100, "7": 100},
                                       "2": {"-3": 100, "0": 100, "3": 100},
                                       "3": {"-1": 100, "0": 100, "1": 100}},
        "cells": cells or {},
        "cell_n": cell_n or {},
    }
    p = tmp_path / "score_clock_margin.json"
    p.write_text(json.dumps(art), encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# the sign
# --------------------------------------------------------------------------

def test_a_LEADING_home_team_keeps_its_lead_in_the_frame(tmp_path):
    m = load_score_clock_model(_artifact(tmp_path))
    dist, source = m.margin_distribution(period=2, margin_at=10)
    # leader gives back -3/0/+3 -> final home margin 7/10/13
    assert dist == {"7": 100, "10": 100, "13": 100}
    assert source == "pooled:2"


def test_a_TRAILING_home_team_is_NEGATED_BACK_not_carried_through(tmp_path):
    """The fit folds onto the leader; the caller must unfold.

    Home trailing by 10 with the leader's own distribution applied UNFOLDED
    would give 7/10/13 -- a home team down ten reported as a ten-point
    favourite. Unfolded correctly it is -13/-10/-7.
    """
    m = load_score_clock_model(_artifact(tmp_path))
    dist, _ = m.margin_distribution(period=2, margin_at=-10)
    assert dist == {"-13": 100, "-10": 100, "-7": 100}
    assert all(int(k) < 0 for k in dist), "a trailing team came out favoured"


def test_the_win_probability_moves_the_right_way_with_the_scoreboard(tmp_path):
    m = load_score_clock_model(_artifact(tmp_path))
    ahead = m.home_win_probability(period=2, margin_at=10)
    behind = m.home_win_probability(period=2, margin_at=-10)
    assert ahead == pytest.approx(1.0)
    assert behind == pytest.approx(0.0)
    assert ahead > behind


# --------------------------------------------------------------------------
# ties
# --------------------------------------------------------------------------

def test_a_TIE_is_excluded_from_the_denominator_not_split(tmp_path):
    """NFL games can end level. Splitting a tie would drag the probability
    toward 0.5 by half the tie mass and make a model that knows about ties look
    less confident than one that does not."""
    pooled = {"2": {"-7": 50, "0": 50}}   # from +7: finals are 0 (tie) and +7
    m = load_score_clock_model(_artifact(tmp_path, pooled=pooled))
    p = m.home_win_probability(period=2, margin_at=7)
    # 50 wins at +7, 50 ties dropped -> 50/50 = 1.0, NOT 0.75
    assert p == pytest.approx(1.0)


# --------------------------------------------------------------------------
# the fallback, and saying so
# --------------------------------------------------------------------------

def test_a_POWERED_cell_is_used_and_names_itself(tmp_path):
    cells = {"2|4-10": {"-5": 200}}
    m = load_score_clock_model(_artifact(tmp_path, cells=cells, cell_n={"2|4-10": 200}))
    dist, source = m.margin_distribution(period=2, margin_at=7)
    assert dist == {"2": 200}
    assert source == "cell:2|4-10"


def test_an_UNDERPOWERED_cell_falls_back_AND_THE_SOURCE_SAYS_SO(tmp_path):
    """A pooled answer is a different claim from a cell-backed one, and a
    caller that cannot tell them apart cannot report honestly."""
    cells = {"2|4-10": {"-5": 3}}
    m = load_score_clock_model(_artifact(tmp_path, cells=cells, cell_n={"2|4-10": 3}))
    dist, source = m.margin_distribution(period=2, margin_at=7)
    assert source == "pooled:2", "an n=3 cell answered as if it were evidence"
    assert dist != {"2": 3}


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------

def test_an_UNSUPPORTED_period_is_REFUSED_not_mapped_to_the_nearest(tmp_path):
    """'End of Q2' and 'eight minutes into Q2' are different amounts of
    remaining football, and the fit only knows the first."""
    m = load_score_clock_model(_artifact(tmp_path))
    assert m.margin_distribution(period=4, margin_at=3) is None
    assert m.home_win_probability(period=0, margin_at=3) is None


def test_a_MISSING_or_JUNK_artifact_returns_None_rather_than_raising(tmp_path):
    assert load_score_clock_model(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_score_clock_model(bad) is None
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"pooled_by_period": {}, "cells": {}}), encoding="utf-8")
    assert load_score_clock_model(empty) is None


def test_the_artifact_path_sits_with_the_other_nfl_source_data():
    assert score_clock_model_path("/data").as_posix().endswith(
        "nfl_source/score_clock_margin.json")


def test_the_fit_PROVENANCE_survives_the_load(tmp_path):
    """A model that cannot say which seasons produced it cannot be shown to be
    out of sample -- which is the whole basis for trusting its grade."""
    m = load_score_clock_model(_artifact(tmp_path))
    assert m.fit_seasons == (2023, 2024, 2025)
    assert 2026 not in m.fit_seasons
    assert m.correlation_by_period["1"] == 0.29
