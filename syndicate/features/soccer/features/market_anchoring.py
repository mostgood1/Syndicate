"""Market-anchoring: blend history-derived team ratings toward market odds.

The EPL h2h validation run (``soccersim_epl_truth_baseline_report.md`` /
``validate_soccer_vs_market.py h2h``) showed the model's largest per-fixture
gaps are transfer-window information the market has priced in that last
season's xG history can't see (a signing, an injury, a managerial change).
Market odds are the fastest-available correction for that blind spot.

This is a *ratings*-level anchor, not a probability-level one: a market-
implied rating shift is solved by bisection (small Monte Carlo batches) so
it moves the whole simulated distribution -- goals, shots, props -- not
just a relabeled three-way probability. It's opt-in: call
``anchor_ratings_to_market`` before ``build_soccer_simulation_input`` for
fixtures where you have market odds, and leave it alone otherwise.
"""

from __future__ import annotations

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import CalibrationProfile
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match

_RATING_CAP = 0.35


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def devig_decimal_odds(prices: dict[str, float]) -> dict[str, float]:
    """Normalize decimal odds (which sum to > 1 including the book's
    margin) into a probability distribution that sums to 1."""
    implied = {side: 1.0 / price for side, price in prices.items() if price and price > 1.0}
    total = sum(implied.values())
    if total <= 0:
        return {}
    return {side: value / total for side, value in implied.items()}


def simulated_home_win_probability(
    *,
    home_rating: dict[str, float],
    away_rating: dict[str, float],
    shift: float = 0.0,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
    simulations: int = 150,
    seed: int = 1,
) -> float:
    """The model's own simulated home win probability at a given rating
    shift. At ``shift=0.0`` this is the model's unadjusted read -- useful
    as the reference point for how large a shift a target probability
    actually implies. Draws mean this is well below 0.5 at parity (a
    three-outcome market, not a coinflip), so don't assume "no shift
    needed" corresponds to a 0.5 target; compute the baseline first.
    """
    return _simulated_home_win_probability(
        home_rating=home_rating, away_rating=away_rating, shift=shift, profile=profile, simulations=simulations, seed=seed
    )


def _simulated_home_win_probability(
    *,
    home_rating: dict[str, float],
    away_rating: dict[str, float],
    shift: float,
    profile: CalibrationProfile,
    simulations: int,
    seed: int,
) -> float:
    wins = 0
    for offset in range(simulations):
        simulation_input = SoccerSimSimulationInput(
            home_team="HOME",
            away_team="AWAY",
            seed=seed + offset,
            home_attack_rating=_clamp(home_rating.get("attack_rating", 0.0) + shift, -_RATING_CAP, _RATING_CAP),
            home_defense_rating=home_rating.get("defense_rating", 0.0),
            away_attack_rating=_clamp(away_rating.get("attack_rating", 0.0) - shift, -_RATING_CAP, _RATING_CAP),
            away_defense_rating=away_rating.get("defense_rating", 0.0),
        )
        output = simulate_match(simulation_input, profile=profile)
        if output.final_score["home"] > output.final_score["away"]:
            wins += 1
    return wins / simulations if simulations else 0.0


def solve_market_rating_shift(
    *,
    home_rating: dict[str, float],
    away_rating: dict[str, float],
    market_home_win_probability: float,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
    simulations: int = 100,
    seed: int = 1,
    max_iterations: int = 5,
    shift_bound: float = 0.30,
) -> float:
    """Bisection search for the symmetric attack-rating shift (added to home,
    subtracted from away) whose simulated home win probability matches
    ``market_home_win_probability``.

    A single scalar shift can't fully disentangle attack from defense from
    a three-outcome probability, but it captures the dominant signal (which
    side the market thinks is stronger, and by how much) cheaply. Simulation
    batches are small and seed-fixed so the search converges in a handful of
    steps; treat the result as a directional correction, not a precise
    decomposition.
    """
    low, high = -shift_bound, shift_bound
    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        simulated = _simulated_home_win_probability(
            home_rating=home_rating,
            away_rating=away_rating,
            shift=mid,
            profile=profile,
            simulations=simulations,
            seed=seed,
        )
        if simulated < market_home_win_probability:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def anchor_team_ratings(
    home_rating: dict[str, float],
    away_rating: dict[str, float],
    *,
    market_home_win_probability: float,
    weight: float,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
    simulations: int = 100,
    seed: int = 1,
) -> tuple[dict[str, float], dict[str, float]]:
    """Blend history-derived ratings toward the market-implied shift.

    ``weight`` is 0 (pure history, no anchoring) to 1 (fully market-implied
    shift applied). A middle value (0.3-0.5) is a sensible default: it lets
    the market correct for information the history window can't see without
    discarding the history signal entirely.
    """
    weight = _clamp(weight, 0.0, 1.0)
    if weight <= 0.0:
        return dict(home_rating), dict(away_rating)
    shift = solve_market_rating_shift(
        home_rating=home_rating,
        away_rating=away_rating,
        market_home_win_probability=market_home_win_probability,
        profile=profile,
        simulations=simulations,
        seed=seed,
    )
    applied = shift * weight
    anchored_home = dict(home_rating)
    anchored_away = dict(away_rating)
    anchored_home["attack_rating"] = round(
        _clamp(home_rating.get("attack_rating", 0.0) + applied, -_RATING_CAP, _RATING_CAP), 4
    )
    anchored_away["attack_rating"] = round(
        _clamp(away_rating.get("attack_rating", 0.0) - applied, -_RATING_CAP, _RATING_CAP), 4
    )
    anchored_home["market_shift_applied"] = round(applied, 4)
    anchored_away["market_shift_applied"] = round(-applied, 4)
    return anchored_home, anchored_away


def anchor_ratings_to_market(
    ratings: dict[str, dict[str, float]],
    fixtures: list[dict],
    *,
    weight: float = 0.35,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
    simulations: int = 100,
) -> dict[str, dict[str, float]]:
    """Anchor a ratings table's home/away pair for each fixture that carries
    market odds.

    Each fixture dict needs ``home_team``, ``away_team``, and a
    ``market_odds`` block: either ``{"home_win_probability": float}``
    directly, or ``{"moneyline": {"home": decimal, "draw": decimal, "away":
    decimal}}`` to devig first. Fixtures without ``market_odds`` are left
    untouched. Returns a new ratings dict; the input is not mutated.
    """
    anchored = {team: dict(rating) for team, rating in ratings.items()}
    for index, fixture in enumerate(fixtures):
        market = fixture.get("market_odds") or {}
        home_win_probability = market.get("home_win_probability")
        if home_win_probability is None:
            moneyline = market.get("moneyline")
            if not moneyline:
                continue
            devigged = devig_decimal_odds(moneyline)
            home_win_probability = devigged.get("home")
        if home_win_probability is None:
            continue
        home_team = str(fixture.get("home_team") or "")
        away_team = str(fixture.get("away_team") or "")
        home_rating = anchored.get(home_team, {"attack_rating": 0.0, "defense_rating": 0.0})
        away_rating = anchored.get(away_team, {"attack_rating": 0.0, "defense_rating": 0.0})
        new_home, new_away = anchor_team_ratings(
            home_rating,
            away_rating,
            market_home_win_probability=float(home_win_probability),
            weight=weight,
            profile=profile,
            simulations=simulations,
            seed=1000 + index,
        )
        if home_team:
            anchored[home_team] = {**home_rating, **new_home}
        if away_team:
            anchored[away_team] = {**away_rating, **new_away}
    return anchored


__all__ = [
    "anchor_ratings_to_market",
    "anchor_team_ratings",
    "devig_decimal_odds",
    "simulated_home_win_probability",
    "solve_market_rating_shift",
]
