"""The ruler before the thing it measures.

`ncaaf/live_resim.py` deliberately withholds `marginDist` / `totalRunsDist`
because no NCAAF live totals estimator has ever been graded -- `#499`'s
precedent is that WNBA totals waited for a 249-game / 23,712-sample backtest and
a MEASURED worst-bucket 0.150. Measured 2026-09-26T21:28Z that gate costs 172
withheld rows and leaves 19 live games with 8 edges between them.

So the harness is the prerequisite, and these tests pin the parts of it that
decide whether a grade means anything:

  * THE PUSH RULE, because a discrete total has real mass on an integer line.
  * THE HOSTILE BASELINE, because a MAE with nothing beside it reads as good or
    bad depending on the reader's priors.
  * THE POWER FLOOR, because the WORST bucket is the headline and an n=3 cell
    would otherwise become the model's reported weakest point when it is noise.
  * THE REFUSAL TO INVENT RATINGS, because 0.0 is the engine's AVERAGE team and
    a substituted rating yields a probability indistinguishable from a real one.

The ESPN fetch is NOT tested here -- it is network -- but it was exercised
against a real slate while writing this: 2026-09-19 returned 71 completed games
with full linescores, i.e. 213 replay rows from a single date, which is what
makes a powered sample reachable at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import backtest_ncaaf_live_totals as bt  # noqa: E402


def _rows(dist, actual, n, at=0):
    return [
        {
            "actual_total": actual,
            "total_at_cutoff": at,
            "projected_total": 50.0,
            "total_dist": dist,
            "possession_unknown": False,
            "event_id": str(i),
        }
        for i in range(n)
    ]


# --------------------------------------------------------------------------
# the push rule
# --------------------------------------------------------------------------

def test_p_over_is_strictly_greater_and_excludes_the_push():
    assert bt._p_over({"40": 100, "45": 100, "50": 100}, 45.0) == pytest.approx(0.5)


def test_p_over_refuses_when_every_draw_lands_on_the_line():
    """0.0 and 0.5 would both be inventions."""
    assert bt._p_over({"45": 300}, 45.0) is None


def test_p_over_voids_on_an_unparseable_key():
    """Skipping a bucket silently reweights the distribution."""
    assert bt._p_over({"40": 100, "oops": 50}, 45.0) is None


def test_a_push_outcome_is_not_scored():
    """A game landing exactly on the line settles as a refund, so it is
    evidence about neither side."""
    result = bt.score(_rows({"60": 90, "40": 10}, 50, 40), lines=[50.0])
    assert result["calibration"] == []


# --------------------------------------------------------------------------
# calibration, and the power floor
# --------------------------------------------------------------------------

def test_a_calibrated_sample_reports_a_small_worst_gap():
    rows = _rows({"60": 90, "40": 10}, 61, 40) + _rows({"60": 10, "40": 90}, 39, 40)
    result = bt.score(rows, lines=[50.0])
    assert result["worst_powered_bucket_gap"] == pytest.approx(0.1, abs=1e-9)


def test_a_miscalibrated_sample_is_caught_at_the_confident_end():
    """Says 90% over and the total goes under every time. The headline must be
    the CONFIDENT cell, because that is the cell that gets bet."""
    result = bt.score(_rows({"60": 90, "40": 10}, 39, 40), lines=[50.0])
    assert result["worst_powered_bucket"] == "0.9-1.0"
    assert result["worst_powered_bucket_gap"] == pytest.approx(0.9, abs=1e-9)


def test_an_underpowered_bucket_is_reported_but_NOT_the_headline():
    result = bt.score(_rows({"60": 90, "40": 10}, 61, 5), lines=[50.0])
    assert result["worst_powered_bucket"] is None, "an n=5 cell became the headline"
    assert result["calibration"], "...but it must still be visible"
    assert result["calibration"][0]["powered"] is False


def test_the_power_floor_is_stated_in_the_output():
    """A reader must not have to guess why a bucket was excluded."""
    assert bt.score(_rows({"60": 90}, 61, 5), lines=[50.0])["min_bucket_n"] == bt.MIN_BUCKET_N


# --------------------------------------------------------------------------
# the hostile baseline
# --------------------------------------------------------------------------

def test_the_frozen_baseline_is_reported_beside_the_projection():
    """`frozen` = nobody scores again. Free to anyone watching."""
    rows = _rows({"60": 90, "40": 10}, 61, 10, at=20)
    result = bt.score(rows, lines=[50.0])
    assert result["mae_frozen"] == pytest.approx(41.0)   # |20 - 61|
    assert result["mae_projection"] == pytest.approx(11.0)  # |50 - 61|
    assert result["beats_frozen"] is True


def test_a_projection_WORSE_than_frozen_says_so():
    """The point of a hostile baseline is that it can win."""
    rows = _rows({"60": 90}, 52, 10, at=51)
    result = bt.score(rows, lines=[50.0])
    assert result["beats_frozen"] is False


def test_the_pooled_possession_hazard_is_surfaced():
    """Unknown possession pools two plans, widening the mixture, so a sample
    dominated by it is not the same reading as one with possession known."""
    rows = _rows({"60": 90}, 61, 4)
    rows[0]["possession_unknown"] = True
    assert bt.score(rows, lines=[50.0])["possession_unknown_share"] == pytest.approx(0.25)


# --------------------------------------------------------------------------
# ratings: use production's, or refuse -- never invent
# --------------------------------------------------------------------------

def test_a_ratings_file_is_read_in_both_shapes(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"Texas": [12.0, -4.0], "UTSA": {"offense": 1.0, "defense": 2.0}}),
                    encoding="utf-8")
    from scripts.generate_smartsim2_ncaaf_projections import norm

    table = bt._ratings_from_file(path)
    # KEYED THROUGH `norm`, because `sp_offense_defense_rating` looks up
    # `sp_index.get(norm(team))`. Keying on the raw name matched nothing and
    # every game came back "unrated" -- indistinguishable from an FBS-vs-FCS
    # refusal, which would have silently emptied the sample.
    assert table[norm("Texas")] == (12.0, -4.0)
    assert table[norm("UTSA")] == (1.0, 2.0)


def test_an_empty_ratings_file_RAISES_rather_than_returning_neutral(tmp_path):
    """0.0 is the engine's AVERAGE team. Substituting it would produce a
    probability indistinguishable from a real one."""
    path = tmp_path / "r.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(ValueError):
        bt._ratings_from_file(path)


def test_a_ratings_file_of_junk_pairs_RAISES(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"Texas": "not a pair"}), encoding="utf-8")
    with pytest.raises(ValueError):
        bt._ratings_from_file(path)


# --------------------------------------------------------------------------
# the gate this harness exists to inform
# --------------------------------------------------------------------------

def test_the_lens_publishes_BOTH_graded_distributions():
    """Both markets opened, each on its OWN grade -- never on the other's.

    Totals cleared first (worst bucket 0.0492, 561 rows / 187 games). Margins
    followed on a separate `--market margin` grade (0.0954 -> 0.0448 corrected,
    570 rows / 190 games), which is why the keys arrived in two commits and not
    one. If a future reader deletes either, the market it prices goes back to
    refusing by name rather than to guessing.
    """
    from syndicate.features.ncaaf.live_resim import NcaafLiveGameState, build_game_lens

    state = NcaafLiveGameState(
        home_team="Texas", away_team="UTSA", period=3, clock_seconds=0,
        home_score=23, away_score=6, possession_owner=None, as_of="2026-09-19",
    )
    result = {
        "home_win_prob": 0.9, "sims_run": 300, "home_margin_mean": 17.0,
        "total_mean": 29.0, "possession_unknown": True, "ties": 0,
        "margin_dist": {"17": 300}, "total_dist": {"29": 300},
    }
    lane = build_game_lens(state, result, live_state_as_of="2026-09-19")[0]
    assert lane["projection"]["totalRunsDist"] == {"29": 300}
    assert lane["projection"]["marginDist"] == {"17": 300}


def test_the_published_total_histogram_is_the_CALIBRATED_one():
    """The board must price the numbers that were graded.

    `resim_live_game` corrects `total_dist` in place and reports
    `total_mean_uncalibrated` beside it. If the lens ever published the RAW
    draws next to a corrected `total`, the displayed projection and the price
    would disagree -- and the 0.0492 reading would describe neither.
    """
    from syndicate.features.ncaaf.live_resim import (
        NcaafLiveGameState, build_game_lens, calibrate_total_distribution,
    )

    totals = [20, 27, 31, 38, 45, 52]
    corrected_mean, corrected = calibrate_total_distribution(totals)
    raw = {}
    for t in totals:
        raw[str(t)] = raw.get(str(t), 0) + 1
    assert corrected != raw, "the fixture cannot distinguish corrected from raw"

    state = NcaafLiveGameState(
        home_team="Texas", away_team="UTSA", period=2, clock_seconds=0,
        home_score=10, away_score=7, possession_owner=None, as_of="2026-09-19",
    )
    lanes = build_game_lens(
        state,
        {
            "home_win_prob": 0.55, "sims_run": 120, "home_margin_mean": 3.0,
            "total_mean": corrected_mean, "total_mean_uncalibrated": sum(totals) / len(totals),
            "possession_unknown": False, "ties": 0,
            "margin_dist": {"3": 6}, "total_dist": corrected,
        },
        live_state_as_of="2026-09-19",
    )
    assert lanes[0]["projection"]["totalRunsDist"] == corrected
    assert lanes[0]["projection"]["totalRunsDist"] != raw
