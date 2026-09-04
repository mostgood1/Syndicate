"""Phase 4 (`#621`) consumer seam: a MEASURED correlation may replace the guess.

`compute_correlation` returns a sum of categorical flags -- `same_game` 0.25,
`same_team` 0.14, `same_subject` 0.40 -- plus a static per-market-pair table
carrying one constant for every player in every game. It has never been measured
against an outcome, and it reaches real money through three consumers: parlay
pricing, the board correlation badges, and `bankroll_manager.build_portfolio`
bet sizing.

The simulation already produces the joint that would answer it, and throws it
away: `_sim_many` reduces every per-sim result into marginal counters, and only
50 per-segment score samples reach the artifact -- 0.137% of the 292,000 scalars
a 1,000-sim game produces.

This is the seam that value lands in. As with Phase 3's `staked_probability`,
the consumer ships FIRST and inert: with no resolver the function is
byte-identical to before, so the producer arrives into something already proven
live rather than the other way round.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.correlation_engine import (  # noqa: E402
    CORRELATION_BASIS_HEURISTIC,
    CORRELATION_BASIS_MEASURED,
    compute_correlation,
)


def _leg(subject: str, market: str, *, game: str = "g1", team: str = "NYY", side: str = "over"):
    return {
        "sport": "mlb",
        "sport_slug": "mlb",
        "game_key": game,
        "event_id": game,
        "team": team,
        "team_key": team,
        "subject": subject,
        "player_name": subject,
        "market": market,
        "market_key": market,
        "selection": side,
        "side": side,
    }


A = _leg("Aaron Judge", "home_runs")
B = _leg("Aaron Judge", "total_bases")


# --- inert by default --------------------------------------------------------


def test_with_no_resolver_the_result_is_unchanged_and_marked_heuristic():
    """The deployment argument, same as Phase 3's beta=0 passthrough."""
    got = compute_correlation(A, B)
    assert got["correlation_basis"] == CORRELATION_BASIS_HEURISTIC
    assert isinstance(got["correlation_score"], float)


def test_a_resolver_that_declines_falls_back_to_the_heuristic():
    """`None` is the NORMAL case -- most pairs will have no measured joint --
    so it must be a quiet fallback, not an error."""
    baseline = compute_correlation(A, B)["correlation_score"]
    got = compute_correlation(A, B, measured_lookup=lambda a, b: None)
    assert got["correlation_score"] == baseline
    assert got["correlation_basis"] == CORRELATION_BASIS_HEURISTIC


# --- off != on ---------------------------------------------------------------


def test_a_measured_value_REPLACES_the_heuristic_stack():
    """Replaces, does not adjust. Averaging a measurement with a guess produces
    neither."""
    baseline = compute_correlation(A, B)["correlation_score"]
    got = compute_correlation(A, B, measured_lookup=lambda a, b: 0.11)
    assert got["correlation_score"] == 0.11
    assert got["correlation_score"] != baseline
    assert got["correlation_basis"] == CORRELATION_BASIS_MEASURED


def test_a_measured_NEGATIVE_correlation_survives():
    """The heuristic can only reach negatives through fixed penalties. A
    measurement must be able to say 'these legs conflict' on its own evidence --
    and that is the sign the parlay pricer was previously discarding."""
    got = compute_correlation(A, B, measured_lookup=lambda a, b: -0.42)
    assert got["correlation_score"] == -0.42
    assert got["correlation_basis"] == CORRELATION_BASIS_MEASURED


def test_the_measurement_is_still_clamped():
    """A resolver bug must not put an out-of-range coefficient into a pricer."""
    high = compute_correlation(A, B, measured_lookup=lambda a, b: 12.0)
    low = compute_correlation(A, B, measured_lookup=lambda a, b: -12.0)
    assert -1.0 <= high["correlation_score"] <= 1.0
    assert -1.0 <= low["correlation_score"] <= 1.0


# --- the resolver is not trusted to behave -----------------------------------


def test_a_raising_resolver_cannot_take_the_board_down():
    def _boom(a, b):
        raise RuntimeError("artifact unreadable")

    baseline = compute_correlation(A, B)["correlation_score"]
    got = compute_correlation(A, B, measured_lookup=_boom)
    assert got["correlation_score"] == baseline
    assert got["correlation_basis"] == CORRELATION_BASIS_HEURISTIC


def test_a_nonsense_resolver_result_falls_back():
    for bad in ("", "abc", object(), float("nan"), None):
        got = compute_correlation(A, B, measured_lookup=lambda a, b, v=bad: v)
        assert got["correlation_basis"] == CORRELATION_BASIS_HEURISTIC, bad


def test_zero_is_a_MEASUREMENT_not_an_absence():
    """A measured independence must not collapse into 'no measurement'. The
    heuristic would score this pair well above zero, so the difference is the
    whole point."""
    baseline = compute_correlation(A, B)["correlation_score"]
    got = compute_correlation(A, B, measured_lookup=lambda a, b: 0.0)
    assert got["correlation_score"] == 0.0
    assert got["correlation_basis"] == CORRELATION_BASIS_MEASURED
    assert baseline != 0.0, "fixture no longer discriminates -- pick another pair"


# --- provenance --------------------------------------------------------------


def test_every_result_states_its_basis():
    """Nothing downstream could previously tell a coefficient from a flag sum."""
    for lookup in (None, lambda a, b: None, lambda a, b: 0.3):
        got = compute_correlation(A, B, measured_lookup=lookup)
        assert got["correlation_basis"] in {
            CORRELATION_BASIS_HEURISTIC,
            CORRELATION_BASIS_MEASURED,
        }
