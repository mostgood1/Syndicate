"""`#621` Phase 5 -- the MEASURED joint priced as a joint, not as an average.

REACHABILITY BEFORE CORRECTNESS (`model_engine_standard` 4.3). The first test
here is `off != on` on a real code path, because every other assertion in this
file is worthless if the flag does not actually reach the estimator. Four inert
features in one session were caught by exactly this test and by nothing else.
"""
from __future__ import annotations

import json
import math

import pytest

from syndicate.features import correlation_engine
from syndicate.features import intelligence_parlay_runtime as pr
from syndicate.features.mlb.sim_joint_correlation import JointCorrelationIndex
from syndicate.features.mlb.threshold_correlation import threshold_correlation

FLAG = "SYNDICATE_PARLAY_MEASURED_JOINT"


def _triangle_index(i: int, j: int) -> int:
    if i < j:
        i, j = j, i
    return i * (i - 1) // 2 + j


def _joint(labels, pairs, *, scale=1000, undefined=-32768, players=None):
    """A published-shape `sim.joint` with the given (label_a, label_b) -> rho."""
    position = {label: index for index, label in enumerate(labels)}
    size = len(labels) * (len(labels) - 1) // 2
    triangle = [undefined] * size
    for (label_a, label_b), rho in pairs.items():
        triangle[_triangle_index(position[label_a], position[label_b])] = int(round(rho * scale))
    return {
        "version": 1,
        "method": "spearman_rank",
        "labels": list(labels),
        "n": 1000,
        "scale": scale,
        "undefined": undefined,
        "corr_lower": triangle,
        "clamped": 0,
        "players": players or {},
    }


LABELS = [
    "team|full|away",
    "batter|101|hits",
    "batter|101|total_bases",
    "batter|202|hits",
    "batter|303|hits",
]
PLAYERS = {
    "101": {"name": "Aaron Judge", "team": "NYY", "side": "home"},
    "202": {"name": "Anthony Volpe", "team": "NYY", "side": "home"},
    # 303 is in the sim but carries no measurable pair below.
    "303": {"name": "Ezequiel Tovar", "team": "COL", "side": "away"},
}


def _index(pairs):
    index = JointCorrelationIndex()
    index.add_game(823497, _joint(LABELS, pairs, players=PLAYERS))
    return index


def _leg(player_id, name, market, probability, *, team="NYY", sport="mlb"):
    return {
        "sport": sport,
        "sport_slug": sport,
        "game_pk": 823497,
        "event_id": "pk823497",
        "game_key": "pk823497",
        "player_id": player_id,
        "player_name": name,
        "subject_key": name,
        "name": f"{name} Over {market}",
        "team": team,
        "team_key": team,
        "market": market,
        "market_key": market,
        "selection": "over",
        "side": "over",
        "model_probability": probability,
    }


JUDGE_HITS = _leg(101, "Aaron Judge", "batter_hits", 0.62)
JUDGE_TB = _leg(101, "Aaron Judge", "batter_total_bases", 0.48)
VOLPE_HITS = _leg(202, "Anthony Volpe", "batter_hits", 0.55)
TOVAR_HITS = _leg(303, "Ezequiel Tovar", "batter_hits", 0.51, team="COL")

MEASURED_PAIRS = {
    ("batter|101|hits", "batter|101|total_bases"): 0.780,
    ("batter|101|hits", "batter|202|hits"): 0.041,
    ("batter|101|total_bases", "batter|202|hits"): 0.033,
}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    correlation_engine.register_measured_correlation_resolver(None)
    monkeypatch.delenv(FLAG, raising=False)
    pr.reset_measured_joint_coverage()
    yield
    correlation_engine.register_measured_correlation_resolver(None)
    pr.reset_measured_joint_coverage()


def _price(legs):
    profile = pr._parlay_correlation_profile(legs)
    return pr._combined_probability(legs, profile), profile


# --- reachability -----------------------------------------------------------


def test_off_is_not_on_the_flag_actually_reaches_the_price(monkeypatch):
    """`off != on` on the SAME legs and the SAME installed resolver."""
    correlation_engine.register_measured_correlation_resolver(_index(MEASURED_PAIRS).as_lookup())
    legs = (JUDGE_HITS, JUDGE_TB, VOLPE_HITS)

    off_price, off_profile = _price(legs)
    monkeypatch.setenv(FLAG, "1")
    on_price, on_profile = _price(legs)

    assert off_price != on_price, "the flag does not reach the price -- feature is inert"
    assert "measured_joint" not in off_profile
    assert on_profile["measured_joint"]["applied"] is True


def test_flag_absent_is_byte_for_byte_todays_payload():
    """With the flag absent the profile is IDENTICAL, resolver installed or not."""
    legs = (JUDGE_HITS, JUDGE_TB, VOLPE_HITS)
    _, bare = _price(legs)
    correlation_engine.register_measured_correlation_resolver(_index(MEASURED_PAIRS).as_lookup())
    _, wired = _price(legs)
    # `correlation_score` legitimately changes (the resolver is installed and
    # `compute_correlation` consults it -- that is `#621` Phase 4, already
    # shipped). What must not change is the SHAPE: no new keys, no new branch.
    assert set(bare) == set(wired)
    assert "measured_joint" not in wired
    assert pr.measured_joint_coverage()["parlays_seen"] == 0


def test_flag_absent_leaves_the_estimator_on_the_average(monkeypatch):
    legs = (JUDGE_HITS, JUDGE_TB, VOLPE_HITS)
    price, profile = _price(legs)
    probabilities = [0.62, 0.48, 0.55]
    assert price == round(
        pr._correlation_adjusted_probability(probabilities, profile["average_correlation"]), 4
    )


# --- the estimator ----------------------------------------------------------


def test_two_leg_price_equals_the_gaussian_copula_orthant(monkeypatch):
    """For n=2 the second-order expansion is EXACT, not an approximation.

    `P = p_a p_b + phi sqrt(p_a q_a p_b q_b)` is the definition of phi
    rearranged, so the price must reproduce `threshold_correlation`'s own
    bivariate-normal tail probability to floating point. If this drifts, the
    expansion and the conversion have stopped agreeing about what phi means.
    """
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(_index(MEASURED_PAIRS).as_lookup())
    legs = (JUDGE_HITS, JUDGE_TB)
    price, profile = _price(legs)

    p_a, p_b = 0.62, 0.48
    phi = threshold_correlation(0.780, p_a, p_b)
    expected = p_a * p_b + phi * math.sqrt(p_a * (1 - p_a) * p_b * (1 - p_b))
    assert profile["measured_joint"]["pairs_measured"] == 1
    assert price == pytest.approx(round(expected, 4), abs=2e-4)


def test_the_matrix_is_not_collapsed_to_its_average():
    """Two tickets with the SAME mean pairwise correlation and DIFFERENT
    structure must price differently. Under the average they cannot."""
    flat = {
        ("batter|101|hits", "batter|101|total_bases"): 0.30,
        ("batter|101|hits", "batter|202|hits"): 0.30,
        ("batter|101|total_bases", "batter|202|hits"): 0.30,
    }
    peaked = {
        ("batter|101|hits", "batter|101|total_bases"): 0.86,
        ("batter|101|hits", "batter|202|hits"): 0.02,
        ("batter|101|total_bases", "batter|202|hits"): 0.02,
    }
    assert sum(flat.values()) == pytest.approx(sum(peaked.values()), abs=1e-9)

    import os

    os.environ[FLAG] = "1"
    try:
        legs = (JUDGE_HITS, JUDGE_TB, VOLPE_HITS)
        correlation_engine.register_measured_correlation_resolver(_index(flat).as_lookup())
        flat_price, _ = _price(legs)
        correlation_engine.register_measured_correlation_resolver(_index(peaked).as_lookup())
        peaked_price, _ = _price(legs)
    finally:
        os.environ.pop(FLAG, None)
    assert flat_price != peaked_price


def test_positive_correlation_raises_and_negative_lowers(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    probabilities = [0.62, 0.48]
    independent = 0.62 * 0.48
    for rho, direction in ((0.60, +1), (-0.60, -1)):
        correlation_engine.register_measured_correlation_resolver(
            _index({("batter|101|hits", "batter|101|total_bases"): rho}).as_lookup()
        )
        price, _ = _price((JUDGE_HITS, JUDGE_TB))
        assert direction * (price - independent) > 0
        lower, upper = pr._frechet_bounds(probabilities)
        assert lower <= price <= upper


def test_price_never_leaves_the_frechet_bounds(monkeypatch):
    """Even at a comonotone measurement, which is where an uncapped
    second-order expansion overshoots."""
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(
        _index({("batter|101|hits", "batter|101|total_bases"): 0.999}).as_lookup()
    )
    price, _ = _price((JUDGE_HITS, JUDGE_TB))
    lower, upper = pr._frechet_bounds([0.62, 0.48])
    assert lower <= price <= upper


# --- the cap ----------------------------------------------------------------


def test_the_cap_still_binds(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(
        _index({("batter|101|hits", "batter|101|total_bases"): 0.999}).as_lookup()
    )
    price, profile = _price((JUDGE_HITS, JUDGE_TB))
    _, upper = pr._frechet_bounds([0.62, 0.48])
    independent = 0.62 * 0.48
    capped = independent + pr._MEASURED_JOINT_MAX_SHIFT * (upper - independent)
    assert profile["measured_joint"]["max_shift"] == pytest.approx(pr._MEASURED_JOINT_MAX_SHIFT)
    assert price == pytest.approx(round(capped, 4), abs=2e-4)
    assert price < upper, "an uncapped measurement reached the comonotone bound"


def test_the_measured_cap_is_above_the_heuristic_cap_and_below_one():
    assert pr._PARLAY_CORRELATION_MAX_SHIFT < pr._MEASURED_JOINT_MAX_SHIFT < 1.0


def test_the_cap_scales_with_the_measured_share():
    full = pr._effective_max_shift(3, 3)
    partial = pr._effective_max_shift(1, 3)
    none = pr._effective_max_shift(0, 3)
    assert full == pytest.approx(pr._MEASURED_JOINT_MAX_SHIFT)
    assert none == pytest.approx(pr._PARLAY_CORRELATION_MAX_SHIFT)
    assert pr._PARLAY_CORRELATION_MAX_SHIFT < partial < pr._MEASURED_JOINT_MAX_SHIFT


def test_heuristic_path_cap_is_unchanged():
    """The default `max_shift` is the heuristic's, so every existing caller is
    untouched by the new keyword."""
    probabilities = [0.62, 0.48]
    independent = 0.62 * 0.48
    _, upper = pr._frechet_bounds(probabilities)
    assert pr._correlation_adjusted_probability(probabilities, 0.99) == pytest.approx(
        independent + pr._PARLAY_CORRELATION_MAX_SHIFT * (upper - independent)
    )


# --- None vs 0.0, and the coverage denominator ------------------------------


def test_an_unmeasured_pair_falls_back_and_is_counted_not_zeroed(monkeypatch):
    """Tovar is in the sim but has no measured pair. He must NOT be priced as
    independent -- he must keep the heuristic coefficient and be COUNTED."""
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(_index(MEASURED_PAIRS).as_lookup())
    legs = (JUDGE_HITS, JUDGE_TB, TOVAR_HITS)
    _, profile = _price(legs)
    block = profile["measured_joint"]
    assert block["pairs_total"] == 3
    assert block["pairs_measured"] == 1
    assert block["pairs_fallback"] == 2
    assert block["applied"] is True
    fallback = [d for d in profile["pair_details"] if d.get("measured_joint_pair") is False]
    assert len(fallback) == 2
    for detail in fallback:
        # the heuristic score, not a zero
        assert detail["correlation_score"] != 0.0
        assert "threshold_correlation" not in detail

    coverage = pr.measured_joint_coverage()
    assert coverage["pairs_total"] == 3
    assert coverage["pairs_measured"] == 1
    assert coverage["pairs_fallback"] == 2
    assert coverage["legs_measured"] == 2
    assert coverage["legs_total"] == 3


def test_no_measured_pair_at_all_is_todays_price(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(_index({}).as_lookup())
    legs = (JUDGE_HITS, JUDGE_TB, VOLPE_HITS)
    price, profile = _price(legs)
    assert profile["measured_joint"]["applied"] is False
    assert price == round(
        pr._correlation_adjusted_probability(
            [0.62, 0.48, 0.55], profile["average_correlation"]
        ),
        4,
    )
    assert pr.measured_joint_coverage()["parlays_no_measured_pair"] == 1


def test_a_measured_zero_is_honoured_not_treated_as_absent(monkeypatch):
    """0.0 is a MEASUREMENT ('these legs are independent') and a large one. It
    must count as measured, not as a fallback onto the heuristic's +0.53."""
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(
        _index({("batter|101|hits", "batter|202|hits"): 0.0}).as_lookup()
    )
    price, profile = _price((JUDGE_HITS, VOLPE_HITS))
    assert profile["measured_joint"]["pairs_measured"] == 1
    assert profile["measured_joint"]["pairs_fallback"] == 0
    assert price == pytest.approx(round(0.62 * 0.55, 4), abs=2e-4)


def test_a_leg_without_a_marginal_is_a_counted_fallback(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(_index(MEASURED_PAIRS).as_lookup())
    no_marginal = dict(JUDGE_TB)
    for key in ("model_probability", "fair_probability", "confidence"):
        no_marginal.pop(key, None)
    _, profile = _price((JUDGE_HITS, no_marginal))
    block = profile["measured_joint"]
    assert block["pairs_measured"] == 0
    assert block["pairs_fallback"] == 1
    assert block["pairs_fallback_no_marginal"] == 1
    assert block["applied"] is False


# --- MLB only ---------------------------------------------------------------


def test_a_non_mlb_ticket_is_refused_up_front(monkeypatch):
    """No other sport publishes a joint. The path must REFUSE rather than run
    with 100% fallbacks and report itself as measured."""
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(_index(MEASURED_PAIRS).as_lookup())
    nba_a = _leg(1, "Jalen Brunson", "player_points", 0.55, team="NYK", sport="nba")
    nba_b = _leg(2, "Josh Hart", "player_rebounds", 0.48, team="NYK", sport="nba")
    price, profile = _price((nba_a, nba_b))
    block = profile["measured_joint"]
    assert block["sport_eligible"] is False
    assert block["applied"] is False
    assert pr.measured_joint_coverage()["parlays_not_mlb"] == 1
    assert price == round(
        pr._correlation_adjusted_probability([0.55, 0.48], profile["average_correlation"]), 4
    )


def test_a_mixed_sport_ticket_is_refused(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(_index(MEASURED_PAIRS).as_lookup())
    nba = _leg(2, "Josh Hart", "player_rebounds", 0.48, team="NYK", sport="nba")
    _, profile = _price((JUDGE_HITS, nba))
    assert profile["measured_joint"]["sport_eligible"] is False
    assert profile["measured_joint"]["applied"] is False


# --- the payload has to survive the wire ------------------------------------


def test_the_profile_is_json_serialisable(monkeypatch):
    """`correlation_profile` rides into an API payload. A tuple key here would
    raise at serialization time on a surface nobody tests with an MLB ticket."""
    monkeypatch.setenv(FLAG, "1")
    correlation_engine.register_measured_correlation_resolver(_index(MEASURED_PAIRS).as_lookup())
    _, profile = _price((JUDGE_HITS, JUDGE_TB, VOLPE_HITS))
    json.dumps(profile)
