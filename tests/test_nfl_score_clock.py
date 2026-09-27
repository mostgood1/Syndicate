"""The score-and-clock model: the sign, the ties, and the refusals.

This model exists because smartsim2's NFL live re-sim LOSES to a frozen
baseline (measured 2026-09-27: MAE 9.596 vs 7.522 over 32 games) and still
loses after its too-narrow distribution is corrected. Its ratings carry about as
much noise as signal, so this uses only what is OBSERVED -- the scoreboard and
the clock.

It has no fitted parameters, so the things that can go wrong are not
overfitting. They are:

  * THE SIGN. Schema 1 folded every observation onto the leader's perspective
    and made the caller negate a trailing team's draw back. Schema 2 stopped
    folding -- it buckets by SIGNED margin in the home-positive frame, because
    the fold discarded a measured +2.25 points of home-field advantage. The
    risk therefore MOVED rather than vanished: a schema-1 artifact read by
    schema-2 code would apply a leader's distribution to a trailing team
    without negating it, reporting a home team down ten as a ten-point
    favourite. That is the inversion `price_distribution_market` warns about,
    so the version is refused rather than migrated.
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


def _artifact(tmp_path, *, cells=None, cell_n=None, pooled=None, min_cell_n=60,
              schema_version=2):
    art = {
        "schema_version": schema_version,
        "fit_seasons": [2023, 2024, 2025],
        "games": 800,
        "observations": 2400,
        "min_cell_n": min_cell_n,
        "margin_buckets": ["TIED", "H0-3", "H4-10", "H11-17", "H18-99",
                           "A0-3", "A4-10", "A11-17", "A18-99"],
        "margin_rest_correlation_by_period": {"1": 0.29, "2": 0.11, "3": -0.07},
        # REST is HOME-POSITIVE and nothing is mirrored (schema 2).
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

def test_the_draw_is_ADDED_home_positive_with_no_mirroring(tmp_path):
    """Schema 2 has no sign to unfold, so there is no sign to get backwards."""
    m = load_score_clock_model(_artifact(tmp_path))
    dist, source = m.margin_distribution(period=2, margin_at=10)
    assert dist == {"7": 100, "10": 100, "13": 100}
    assert source == "pooled:2"


def test_a_TRAILING_home_team_uses_the_TRAILING_cell_and_is_not_favoured(tmp_path):
    """The home-advantage fix, asserted as behaviour.

    Schema 1 mirrored onto "the leader" and averaged home and away leads
    together, discarding a MEASURED +2.25 points of home-field advantage. Here
    the `A4-10` cell describes trailing home teams specifically -- and it may
    legitimately be home-positive, because a trailing home team does tend to
    gain. What must never happen is a team down ten coming out favoured.
    """
    cells = {"2|A4-10": {"3": 100, "6": 100}}   # home trails but gains ground
    m = load_score_clock_model(_artifact(tmp_path, cells=cells,
                                         cell_n={"2|A4-10": 500}))
    dist, source = m.margin_distribution(period=2, margin_at=-10)
    assert source == "cell:2|A4-10", "the signed trailing cell was not selected"
    assert dist == {"-7": 100, "-4": 100}
    assert all(int(k) < 0 for k in dist), "a team down ten came out favoured"


def test_HOME_and_AWAY_leads_select_DIFFERENT_cells(tmp_path):
    """The whole point of unfolding: +7 and -7 are no longer the same cell."""
    cells = {"2|H4-10": {"0": 100}, "2|A4-10": {"0": 100}}
    m = load_score_clock_model(_artifact(tmp_path, cells=cells,
                                         cell_n={"2|H4-10": 500, "2|A4-10": 500}))
    _, home_src = m.margin_distribution(period=2, margin_at=7)
    _, away_src = m.margin_distribution(period=2, margin_at=-7)
    assert home_src == "cell:2|H4-10"
    assert away_src == "cell:2|A4-10"
    assert home_src != away_src


def test_a_TIED_game_has_its_own_cell(tmp_path):
    cells = {"2|TIED": {"1": 100}}
    m = load_score_clock_model(_artifact(tmp_path, cells=cells, cell_n={"2|TIED": 500}))
    dist, source = m.margin_distribution(period=2, margin_at=0)
    assert source == "cell:2|TIED"
    assert dist == {"1": 100}


def test_the_win_probability_moves_the_right_way_with_the_scoreboard(tmp_path):
    m = load_score_clock_model(_artifact(tmp_path))
    ahead = m.home_win_probability(period=2, margin_at=10)
    behind = m.home_win_probability(period=2, margin_at=-10)
    assert ahead == pytest.approx(1.0)
    assert behind == pytest.approx(0.0)
    assert ahead > behind


def test_a_SCHEMA_1_artifact_is_REFUSED_not_silently_misread(tmp_path):
    """A folded artifact read by unfolded code is the inversion itself.

    Schema 1 cells are the LEADER's perspective and require negation for a
    trailing team. This code does not negate, so a schema-1 artifact would
    report a home team down ten as a ten-point favourite. Refuse, do not
    migrate.
    """
    old = _artifact(tmp_path, schema_version=1)
    assert load_score_clock_model(old) is None
    assert load_score_clock_model(_artifact(tmp_path, schema_version=2)) is not None


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
    cells = {"2|H4-10": {"-5": 200}}
    m = load_score_clock_model(_artifact(tmp_path, cells=cells, cell_n={"2|H4-10": 200}))
    dist, source = m.margin_distribution(period=2, margin_at=7)
    assert dist == {"2": 200}
    assert source == "cell:2|H4-10"


def test_an_UNDERPOWERED_cell_falls_back_AND_THE_SOURCE_SAYS_SO(tmp_path):
    """A pooled answer is a different claim from a cell-backed one, and a
    caller that cannot tell them apart cannot report honestly."""
    cells = {"2|H4-10": {"-5": 3}}
    m = load_score_clock_model(_artifact(tmp_path, cells=cells, cell_n={"2|H4-10": 3}))
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
    empty.write_text(json.dumps({"schema_version": 2, "pooled_by_period": {}, "cells": {}}),
                     encoding="utf-8")
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


# --------------------------------------------------------------------------
# PRODUCER -> CONSUMER. The fixtures above are hand-written, and that is how a
# real mismatch survived them.
# --------------------------------------------------------------------------

def test_the_REAL_fit_output_is_readable_by_the_model_round_trip(tmp_path):
    """The fit's own artifact must select its own cells.

    MEASURED DEFECT this pins: `fit()` declared UNSIGNED `margin_buckets`
    (`4-10`) while keying `cells` SIGNED (`2|H4-10`). The model looked its
    bucket up in the declared list, matched nothing, and fell back to the pooled
    quarter -- legitimate behaviour, so nothing raised. 86 of 99 graded requests
    came from the pool despite only 2 of 27 cells being underpowered, and every
    hand-written fixture in this file passed throughout, because they supplied
    signed labels the producer was not actually emitting.

    So this drives the REAL producer and asserts the consumer selects a CELL.
    """
    from scripts.fit_nfl_score_clock import fit

    obs = []
    for i in range(400):
        # home leading 4-10, and a distinctive rest so the cell is identifiable
        obs.append({"season": 2024, "week": 1, "event_id": f"h{i}",
                    "period": 2, "margin_at": 7, "rest": 5})
        # away leading 4-10, different rest -- a folded fit would merge these
        obs.append({"season": 2024, "week": 1, "event_id": f"a{i}",
                    "period": 2, "margin_at": -7, "rest": 5})
    art = fit(obs)
    path = tmp_path / "real.json"
    path.write_text(json.dumps(art), encoding="utf-8")

    m = load_score_clock_model(path)
    assert m is not None, "the model refused its own fit's artifact"

    _, home_src = m.margin_distribution(period=2, margin_at=7)
    _, away_src = m.margin_distribution(period=2, margin_at=-7)
    assert home_src == "cell:2|H4-10", f"fell back instead of selecting: {home_src}"
    assert away_src == "cell:2|A4-10", f"fell back instead of selecting: {away_src}"

    # And the unfold is real: both sides gained +5, so the home-leading cell
    # ends ABOVE its start and the away-leading one ends above ITS start too.
    home_dist, _ = m.margin_distribution(period=2, margin_at=7)
    away_dist, _ = m.margin_distribution(period=2, margin_at=-7)
    assert home_dist == {"12": 400}
    assert away_dist == {"-2": 400}
