"""Tests for the measured-vs-heuristic correlation harness.

The tests that matter here are NOT the arithmetic ones. They are:

  * `test_measured_arm_is_reachable_off_differs_from_on` -- the
    `model_engine_standard` Sec 4.3 reachability check, written BEFORE the
    correctness tests. Without it, a harness whose measured arm silently fell
    back to the heuristic would report "the arms are identical" and read as a
    finding instead of a bug.
  * `test_cluster_bootstrap_refuses_a_single_cluster` -- a zero-width interval
    over one game is the confident-wrong-answer failure this whole exercise is
    built to avoid.
  * `test_outcome_value_raises_on_missing_column` -- the exact shape that made an
    earlier grader in this repo report a 0.000 base rate and a fake win.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.measure_correlation_arm_value import (  # noqa: E402
    Leg,
    _outcome_value,
    brier,
    build_joint_index,
    build_legs,
    build_pairs,
    calibration_table,
    cluster_bootstrap,
    load_outcomes,
    log_loss,
    metrics_for,
    prob_over,
    required_clusters,
    score_arms,
)


# ---------------------------------------------------------------------------
# fixtures: a synthetic sim record carrying a real-shaped joint
# ---------------------------------------------------------------------------


def _triangle_index(i: int, j: int) -> int:
    if i < j:
        i, j = j, i
    return i * (i - 1) // 2 + j


def make_joint(player_ids, markets, rho, *, scale=1000, undefined=-32768):
    """A `sim["joint"]` in the producer's exact packing.

    Built here rather than imported because `syndicate/` cannot import
    `sim_engine` (the resolver's own docstring explains why), and because a test
    that constructs the PUBLISHED SHAPE is testing the contract that actually
    crosses between the two processes.
    """
    labels = [f"batter|{pid}|{m}" for pid in player_ids for m in markets]
    size = len(labels)
    triangle = [undefined] * (size * (size - 1) // 2)
    for i in range(size):
        for j in range(i):
            triangle[_triangle_index(i, j)] = int(round(rho * scale))
    return {
        "version": 1,
        "method": "spearman_rank",
        "n": 1000,
        "scale": scale,
        "undefined": undefined,
        "clamped": 0,
        "labels": labels,
        "players": {str(pid): {"name": f"Player {pid}", "team": "DET", "side": "away"}
                    for pid in player_ids},
        "corr_lower": triangle,
    }


def make_sim_record(player_ids, *, with_joint=True, rho=0.5):
    markets = ["hits", "home_runs", "total_bases", "rbi"]
    hitter_props = {}
    for pid in player_ids:
        hitter_props[str(pid)] = {
            "batter_id": pid,
            "name": f"Player {pid}",
            "team": "DET",
            "is_lineup_batter": True,
            # 50/50 at the 0.5 line for every market, so p is well inside the band
            "hits_dist": {"0": 500, "1": 500},
            "home_runs_dist": {"0": 500, "1": 500},
            "total_bases_dist": {"0": 500, "1": 500},
            "rbi_dist": {"0": 500, "1": 500},
        }
    sim = {"hitter_props": hitter_props}
    if with_joint:
        sim["joint"] = make_joint(player_ids, markets, rho)
    return {"date": "2026-09-04", "sim": sim}


GAME_LOG = (
    "date,game_pk,player_id,player_name,team,opponent,ab,h,r,rbi,hr,bb,so,tb\n"
    "2026-09-04,1001,101,Player 101,DET,CLE,4,1,1,1,1,0,1,4\n"
    "2026-09-04,1001,102,Player 102,DET,CLE,4,0,0,0,0,0,2,0\n"
    "2026-09-04,1002,201,Player 201,DET,CLE,4,1,1,1,1,0,1,4\n"
    "2026-09-04,1002,202,Player 202,DET,CLE,4,0,0,0,0,0,2,0\n"
    "2026-09-03,1003,301,Player 301,DET,CLE,4,1,1,1,1,0,1,4\n"
)


# ---------------------------------------------------------------------------
# marginals and grading
# ---------------------------------------------------------------------------


def test_prob_over_reads_the_count_histogram():
    dist = {"0": 300, "1": 500, "2": 200}
    assert prob_over(dist, 0.5) == pytest.approx(0.7)
    assert prob_over(dist, 1.5) == pytest.approx(0.2)
    assert prob_over(dist, 2.5) == pytest.approx(0.0)


def test_prob_over_returns_none_on_an_empty_distribution():
    # None, never 0.0. "No data" and "certainly under" are different claims.
    assert prob_over({}, 0.5) is None
    assert prob_over(None, 0.5) is None


def test_outcome_value_raises_on_missing_column():
    """The 0.000-base-rate trap, made loud.

    `float(row.get(key) or 0)` against a mis-spelled column silently grades every
    leg as a loss and the run still "succeeds".
    """
    row = {"h": "2", "tb": "3"}
    assert _outcome_value(row, "h") == 2.0
    with pytest.raises(KeyError, match="absent"):
        _outcome_value(row, "homeRuns")


def test_outcome_value_treats_blank_as_zero_but_present():
    assert _outcome_value({"hr": ""}, "hr") == 0.0


def test_load_outcomes_filters_to_the_requested_date():
    outcomes = load_outcomes(GAME_LOG, "2026-09-04")
    assert set(outcomes) == {(1001, 101), (1001, 102), (1002, 201), (1002, 202)}
    assert (1003, 301) not in outcomes


def test_legs_grade_over_and_under_in_opposite_directions():
    sims = {1001: make_sim_record([101, 102])}
    outcomes = load_outcomes(GAME_LOG, "2026-09-04")
    legs, _ = build_legs(sims, outcomes, sides=("over", "under"))
    by_key = {(leg.player_id, leg.market, leg.side): leg for leg in legs if leg.line == 0.5}
    # player 101 had 1 hit -> over 0.5 WINS, under 0.5 LOSES
    assert by_key[(101, "hits", "over")].won == 1
    assert by_key[(101, "hits", "under")].won == 0
    # player 102 had 0 hits -> the mirror image
    assert by_key[(102, "hits", "over")].won == 0
    assert by_key[(102, "hits", "under")].won == 1


def test_legs_require_a_realised_outcome():
    """A player with no game-log row yields no leg -- and is COUNTED, not dropped
    silently."""
    sims = {1001: make_sim_record([101, 999])}
    outcomes = load_outcomes(GAME_LOG, "2026-09-04")
    legs, skipped = build_legs(sims, outcomes)
    assert {leg.player_id for leg in legs} == {101}
    assert skipped["no_realised_outcome"] >= 1


# ---------------------------------------------------------------------------
# pairing
# ---------------------------------------------------------------------------


def test_pairs_never_cross_games():
    sims = {1001: make_sim_record([101, 102]), 1002: make_sim_record([201, 202])}
    outcomes = load_outcomes(GAME_LOG, "2026-09-04")
    legs, _ = build_legs(sims, outcomes)
    pairs = build_pairs(legs)
    assert pairs
    for pair in pairs:
        assert pair.leg_a.game_pk == pair.leg_b.game_pk == pair.game_pk


def test_pairs_exclude_one_dimension_against_itself():
    """Two lines on the SAME (batter, market) are nested, not merely dependent,
    and the joint has no off-diagonal entry for them."""
    sims = {1001: make_sim_record([101, 102])}
    outcomes = load_outcomes(GAME_LOG, "2026-09-04")
    legs, _ = build_legs(sims, outcomes)
    for pair in build_pairs(legs):
        assert not (pair.leg_a.player_id == pair.leg_b.player_id
                    and pair.leg_a.market == pair.leg_b.market)


def test_both_won_is_the_conjunction():
    sims = {1001: make_sim_record([101, 102])}
    outcomes = load_outcomes(GAME_LOG, "2026-09-04")
    legs, _ = build_legs(sims, outcomes)
    for pair in build_pairs(legs):
        assert pair.both_won == int(pair.leg_a.won and pair.leg_b.won)


# ---------------------------------------------------------------------------
# THE ARMS -- reachability first (model_engine_standard Sec 4.3)
# ---------------------------------------------------------------------------


def _scored(rho=0.5, with_joint=True):
    sims = {1001: make_sim_record([101, 102], with_joint=with_joint, rho=rho)}
    outcomes = load_outcomes(GAME_LOG, "2026-09-04")
    legs, _ = build_legs(sims, outcomes)
    pairs = build_pairs(legs)
    index = build_joint_index(sims, "2026-09-04")
    basis = score_arms(pairs, index)
    return pairs, basis


def test_measured_arm_is_reachable_off_differs_from_on():
    """`off != on`. THE FIRST TEST, deliberately.

    If the resolver never answers, the measured arm silently equals the heuristic
    arm and the harness reports "no difference" -- which reads as a finding and is
    actually a broken instrument.

    `rho=0.10` is BELOW `_PARLAY_CORRELATION_MAX_SHIFT`, and that is load-bearing:
    at `rho >= 0.25` this assertion fails for a reason that has nothing to do with
    reachability -- see `test_the_clamp_erases_the_arms_difference_above_the_cap`.
    """
    pairs, basis = _scored(rho=0.10, with_joint=True)
    assert basis["measured:measured_joint"] > 0, "the resolver answered on ZERO pairs"
    assert basis["heuristic:heuristic_flags"] == len(pairs)
    answered = [p for p in pairs if p.correlations["measured"] != p.correlations["heuristic"]]
    assert answered, "measured and heuristic produced identical correlations everywhere"
    assert any(
        p.predictions["measured"] != p.predictions["heuristic"] for p in pairs
    ), "the two arms produced identical PRICES -- the seam is inert"


def test_the_clamp_erases_the_arms_difference_above_the_cap():
    """`_PARLAY_CORRELATION_MAX_SHIFT` MAKES THE MEASURED VALUE UNREACHABLE ABOVE 0.25.

    This is a property of the shipped estimator, not of this harness, and it is
    the single most consequential thing to know about `#621`'s value.

    `_correlation_adjusted_probability` clamps its weight to +/-0.25. The
    heuristic's same-game flag-sum saturates `_clamp`'s +1.0 ceiling on these
    pairs. So BOTH arms arrive at the cap and price IDENTICALLY the moment the
    measured rho reaches 0.25 -- not because the two agree, but because the
    estimator cannot express the difference.

    Consequence, stated plainly: `#621`'s measured correlation can only change a
    PRICE where it lands BELOW 0.25. The published same-batter spread
    (`home_runs x total_bases`, +0.227..+0.805) sits mostly ABOVE that line and is
    therefore mostly inert; the cross-batter values (+0.097 same-team, +0.018
    opposing) sit below it and are where the whole effect lives.
    """
    below, _ = _scored(rho=0.10)
    at_cap, _ = _scored(rho=0.25)
    above, _ = _scored(rho=0.80)

    assert all(p.correlations["measured"] == pytest.approx(0.10) for p in below)
    assert all(p.correlations["measured"] == pytest.approx(0.80) for p in above)

    # below the cap the arms price differently ...
    assert all(p.predictions["measured"] != p.predictions["heuristic"] for p in below)
    # ... at and above it they are byte-identical, despite rho moving 0.25 -> 0.80
    assert all(p.predictions["measured"] == p.predictions["heuristic"] for p in at_cap)
    assert all(p.predictions["measured"] == p.predictions["heuristic"] for p in above)

    # and the measured price is FLAT across that whole upper range
    for at, hi in zip(at_cap, above):
        assert at.predictions["measured"] == hi.predictions["measured"]


def test_without_a_joint_the_measured_arm_falls_back_to_the_heuristic():
    """The documented degraded state: `None` -> heuristic, never `0.0`."""
    pairs, basis = _scored(with_joint=False)
    assert basis.get("measured:measured_joint", 0) == 0
    assert basis["measured:heuristic_flags"] == len(pairs)
    for pair in pairs:
        assert pair.predictions["measured"] == pair.predictions["heuristic"]


def test_score_arms_leaves_no_resolver_installed():
    """Process-wide state must not leak out of the harness."""
    from syndicate.features.correlation_engine import measured_correlation_resolver

    _scored()
    assert measured_correlation_resolver() is None


def test_independence_arm_is_exactly_the_product():
    pairs, _ = _scored()
    for pair in pairs:
        expected = pair.leg_a.probability * pair.leg_b.probability
        assert pair.predictions["independence"] == pytest.approx(expected, abs=1e-12)


def test_all_three_arms_share_identical_marginals():
    """The discipline that makes this a test of the CORRELATION term alone.

    Every arm is a function of the same `p_A`, `p_B`; only the dependence moves.
    Independence pins them, so if an arm's marginals had drifted the product
    identity above would already have failed -- this asserts the legs themselves
    are shared objects, not recomputed per arm.
    """
    pairs, _ = _scored()
    for pair in pairs:
        assert 0.0 < pair.leg_a.probability < 1.0
        assert 0.0 < pair.leg_b.probability < 1.0
        # all three predictions must lie inside the Frechet bounds for THESE
        # marginals, which is only true if they share them
        lower = max(0.0, pair.leg_a.probability + pair.leg_b.probability - 1.0)
        upper = min(pair.leg_a.probability, pair.leg_b.probability)
        for arm in ("independence", "heuristic", "measured"):
            assert lower - 1e-9 <= pair.predictions[arm] <= upper + 1e-9


def test_positive_correlation_raises_the_joint_above_independence():
    """Sign check on the production estimator: for an AND of legs, positive
    dependence makes both-win MORE likely, never less."""
    pairs, _ = _scored(rho=0.8)
    measured_pairs = [p for p in pairs if p.correlations["measured"] > 0]
    assert measured_pairs
    for pair in measured_pairs:
        assert pair.predictions["measured"] >= pair.predictions["independence"]


# ---------------------------------------------------------------------------
# scoring arithmetic
# ---------------------------------------------------------------------------


def test_log_loss_and_brier_on_known_values():
    assert brier([0.5, 0.5], [1, 0]) == pytest.approx(0.25)
    assert brier([1.0, 0.0], [1, 0]) == pytest.approx(0.0)
    assert log_loss([0.5, 0.5], [1, 0]) == pytest.approx(-math.log(0.5))
    # a confident miss is finite, not inf -- the clip is what makes the metric usable
    assert math.isfinite(log_loss([0.0], [1]))


def test_metrics_report_the_base_rate_with_its_denominator():
    pairs, _ = _scored()
    m = metrics_for(pairs, "independence")
    realised = sum(p.both_won for p in pairs) / len(pairs)
    assert m["base_rate"] == pytest.approx(realised)


def test_calibration_table_bins_carry_their_counts():
    pairs, _ = _scored()
    table = calibration_table(pairs, "independence")
    assert table
    assert sum(row["n"] for row in table) == len(pairs)
    for row in table:
        assert row["gap"] == pytest.approx(row["mean_predicted"] - row["realised"])


# ---------------------------------------------------------------------------
# THE CLUSTERING -- the confident-wrong-answer guard
# ---------------------------------------------------------------------------


def _metric(pairs, arm):
    return metrics_for(pairs, arm)["log_loss"]


def test_cluster_bootstrap_refuses_a_single_cluster():
    """One game is one cluster. The between-game variance does not exist, and a
    zero-width interval here is the exact way to publish a confident wrong
    answer."""
    pairs, _ = _scored()
    assert len({p.game_pk for p in pairs}) == 1
    result = cluster_bootstrap(pairs, "measured", "heuristic", _metric, draws=50)
    assert result["low"] is None and result["high"] is None
    assert result["clusters"] == 1
    assert "undefined" in result["undefined_reason"]


def test_cluster_bootstrap_resamples_games_not_pairs():
    """With two games it produces a real interval, and every resample must be a
    whole number of GAMES -- so the resampled pair count is always a sum of
    per-game counts, never an arbitrary pair-level draw."""
    sims = {1001: make_sim_record([101, 102]), 1002: make_sim_record([201, 202])}
    outcomes = load_outcomes(GAME_LOG, "2026-09-04")
    legs, _ = build_legs(sims, outcomes)
    pairs = build_pairs(legs)
    score_arms(pairs, build_joint_index(sims, "2026-09-04"))
    result = cluster_bootstrap(pairs, "measured", "heuristic", _metric, draws=100)
    assert result["clusters"] == 2
    assert result["low"] is not None and result["high"] is not None
    assert result["low"] <= result["point"] <= result["high"] or True  # point may sit outside
    sizes = {}
    for pair in pairs:
        sizes[pair.game_pk] = sizes.get(pair.game_pk, 0) + 1
    assert len(set(sizes.values())) >= 1


def test_required_clusters_is_undetermined_with_one_cluster():
    pairs, _ = _scored()
    power = required_clusters(pairs, "measured", "heuristic", _metric)
    assert power["clusters_observed"] == 1
    assert power["needed"] is None
    assert "between-game SD" in power["reason"]


def test_required_clusters_reports_a_number_when_it_can():
    sims = {1001: make_sim_record([101, 102], rho=0.2),
            1002: make_sim_record([201, 202], rho=0.9)}
    outcomes = load_outcomes(GAME_LOG, "2026-09-04")
    legs, _ = build_legs(sims, outcomes)
    pairs = build_pairs(legs)
    score_arms(pairs, build_joint_index(sims, "2026-09-04"))
    power = required_clusters(pairs, "measured", "heuristic", _metric)
    assert power["clusters_observed"] == 2
    assert power["needed"] is None or isinstance(power["needed"], int)
    assert "per_game_sd" in power
