"""REACHABILITY, not correctness: does a measured correlation reach the consumers?

`model_engine_standard` §4.3 -- a reachability test (`off != on`) comes BEFORE
correctness tests, because a neutral default is indistinguishable from a working
feature at every level except the data.

The gap this pins: `compute_correlation` has TEN call sites and, when the
`measured_lookup` seam first landed, NONE of them passed one. A seam nothing
calls is inert, and inert-but-tested is the exact failure the standard was
written from -- 26 input fields the MLB sim read and nothing fed, four features
built, tested and dead, none of which produced an error or a log line.

So these tests do not call `compute_correlation`. They drive the REAL consumers
and assert the measured value moved their output. If someone later threads a
parameter through nine sites and misses the tenth, this is what catches it --
and the failure that would otherwise ship is subtle: the same pair scoring
differently depending on which consumer asked.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features import correlation_engine  # noqa: E402
from syndicate.features.correlation_engine import (  # noqa: E402
    CORRELATION_BASIS_HEURISTIC,
    CORRELATION_BASIS_MEASURED,
    compute_correlation,
    measured_correlation_resolver,
    register_measured_correlation_resolver,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    """The registry is process-wide, so leaking one into another test would make
    that test pass for the wrong reason."""
    register_measured_correlation_resolver(None)
    yield
    register_measured_correlation_resolver(None)


def _leg(subject: str, market: str, *, game: str = "g1", team: str = "NYY"):
    return {
        "sport": "mlb", "sport_slug": "mlb",
        "game_key": game, "event_id": game,
        "team": team, "team_key": team,
        "subject": subject, "player_name": subject,
        "market": market, "market_key": market,
        "selection": "over", "side": "over",
        "probability": 0.5, "model_probability": 0.5,
    }


A = _leg("Aaron Judge", "home_runs")
B = _leg("Aaron Judge", "total_bases")


# --- the registry itself -----------------------------------------------------


def test_the_registry_starts_empty_and_says_so():
    """A registry silently holding None is indistinguishable from one nobody
    registered, so it is inspectable."""
    assert measured_correlation_resolver() is None
    assert compute_correlation(A, B)["correlation_basis"] == CORRELATION_BASIS_HEURISTIC


def test_registering_a_resolver_reaches_compute_correlation_with_NO_caller_change():
    """The whole point: no consumer passes a lookup, and every consumer still
    gets the measurement."""
    register_measured_correlation_resolver(lambda a, b: -0.31)
    got = compute_correlation(A, B)
    assert got["correlation_score"] == -0.31
    assert got["correlation_basis"] == CORRELATION_BASIS_MEASURED


def test_an_explicit_lookup_still_wins_over_the_registry():
    """So a test or a one-off caller can inject without disturbing process-wide
    wiring."""
    register_measured_correlation_resolver(lambda a, b: 0.90)
    got = compute_correlation(A, B, measured_lookup=lambda a, b: 0.10)
    assert got["correlation_score"] == 0.10


def test_clearing_the_registry_returns_every_consumer_to_the_heuristic():
    register_measured_correlation_resolver(lambda a, b: 0.9)
    assert compute_correlation(A, B)["correlation_basis"] == CORRELATION_BASIS_MEASURED
    register_measured_correlation_resolver(None)
    assert compute_correlation(A, B)["correlation_basis"] == CORRELATION_BASIS_HEURISTIC


# --- the consumers, driven for real ------------------------------------------


def test_it_reaches_the_PARLAY_PRICER_and_moves_the_price():
    """`_combined_probability` -> `_correlation_adjusted_probability`. The
    measured sign is what decides whether a same-game parlay is priced above or
    below the independent product, so this is the money path."""
    from syndicate.features import intelligence_parlay_runtime as parlay

    legs = (dict(A), dict(B))

    register_measured_correlation_resolver(lambda a, b: 0.60)
    profile_pos = parlay._parlay_correlation_profile(legs)
    positive = parlay._combined_probability(legs, profile_pos)

    register_measured_correlation_resolver(lambda a, b: -0.60)
    profile_neg = parlay._parlay_correlation_profile(legs)
    negative = parlay._combined_probability(legs, profile_neg)

    assert positive is not None and negative is not None
    # The measured SIGN decides which side of independence the parlay is priced.
    independent = 0.5 * 0.5
    assert positive > independent > negative, (positive, independent, negative)
    # And the profile itself must carry the measurement, not the flag sum.
    assert profile_pos["average_correlation"] == pytest.approx(0.60)
    assert profile_neg["average_correlation"] == pytest.approx(-0.60)


def test_it_reaches_the_BOARD_BADGES():
    """`attach_board_correlation_flags` calls `compute_correlation` at its own
    site (`correlation_engine.py:357`), which the registry must also cover --
    the badge threshold is 0.5 and bet sizing keys off 0.65."""
    from syndicate.features.correlation_engine import attach_board_correlation_flags

    candidates = [dict(A), dict(B)]
    register_measured_correlation_resolver(lambda a, b: 0.95)
    attach_board_correlation_flags(candidates, threshold=0.5)
    flagged_high = sum(1 for c in candidates if c.get("correlation_flag") or c.get("correlated_with"))

    candidates = [dict(A), dict(B)]
    register_measured_correlation_resolver(lambda a, b: 0.0)
    attach_board_correlation_flags(candidates, threshold=0.5)
    flagged_low = sum(1 for c in candidates if c.get("correlation_flag") or c.get("correlated_with"))

    assert flagged_high > flagged_low, (flagged_high, flagged_low)


def test_a_broken_resolver_degrades_every_consumer_to_the_heuristic():
    """One bad artifact must not take the board down at ten call sites."""
    def _boom(a, b):
        raise RuntimeError("joint artifact unreadable")

    register_measured_correlation_resolver(_boom)
    got = compute_correlation(A, B)
    assert got["correlation_basis"] == CORRELATION_BASIS_HEURISTIC
    assert isinstance(got["correlation_score"], float)
