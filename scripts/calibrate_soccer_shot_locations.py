"""Shot-location calibration for a SoccerSim league profile.

Automates the methodology proven manually for EPL (Phase 11) and La Liga
(Phase 12): pull a full season of real shots from ESPN's commentary feed,
classify by location (box/six-yard-box/outside-box) and phase
(from-corner), measure real P(goal|shot) per bucket, set the profile's
``box_shot_conversion_base``/``outside_box_conversion_base``/
``corner_shot_conversion_base`` directly to the measured values (matching
precedent: the *box* bucket's own rate is used as-is, not blended with the
much smaller six-yard-box bucket -- the profile has no separate six-yard
field), then re-checks the profile's mean simulated goals/match against
the league's documented truth total and searches a small
``goal_conversion_multiplier`` grid to re-anchor it if the location-base
change moved it more than 0.05 goals/match.

This prints the new values; it does not edit league_profiles.py -- apply
them by hand (small, auditable diffs, same as every prior calibration
pass) so each change stays reviewable rather than silently overwritten.

Usage:
    python scripts/calibrate_soccer_shot_locations.py --league bundesliga --truth-total 3.20
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from random import Random
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.features.schedule import season_date_range
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_shot_events import aggregate_season_shot_events
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import get_league_profile
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match

_TOLERANCE_GOALS = 0.08
# A location-base change can shift scoring by a lot more than the original
# hand-picked multiplier anticipated (observed: Bundesliga's measured
# corner-conversion rate came in at more than double the v0 default, which
# needed a far wider search than a small nudge around the pre-existing
# multiplier finds) -- scan a wide absolute range rather than assuming the
# right value is near the old multiplier at all.
#
# A prior two-phase (coarse-then-fine) version of this search was dropped:
# at a few hundred simulations per candidate, per-match goal-total variance
# is large enough that the "best" fine-scan pick didn't reproduce under an
# independent verification batch (observed directly: a reported gap of
# 0.062 came back as 0.633 on a fresh batch at the same multiplier). One
# wide single-pass scan, each candidate evaluated with the full simulation
# budget, is a more honest use of a fixed compute budget than a second
# noisier pass that mostly re-measures sampling error.
_MULTIPLIER_CANDIDATES = tuple(round(0.5 + 0.1 * i, 2) for i in range(13))  # 0.5 .. 1.7


def _season_windows(league: str, season: int, *, window_days: int = 30) -> list[str]:
    start, end = season_date_range(league, season)
    windows: list[str] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=window_days - 1), end)
        windows.append(f"{cursor.strftime('%Y%m%d')}-{window_end.strftime('%Y%m%d')}")
        cursor = window_end + timedelta(days=1)
    return windows


def _conversion(shots: list[dict], *, location: str | None = None, from_corner: bool | None = None) -> tuple[float, int]:
    filtered = shots
    if location is not None:
        filtered = [s for s in filtered if s.get("location") == location]
    if from_corner is not None:
        filtered = [s for s in filtered if bool(s.get("from_corner")) == from_corner]
    if not filtered:
        return 0.0, 0
    goals = sum(1 for s in filtered if s.get("outcome") == "goal")
    return goals / len(filtered), len(filtered)


def _mean_simulated_goals(profile, *, simulations: int, seed_offset: int = 0) -> float:
    totals = []
    for offset in range(simulations):
        seed = seed_offset + offset
        sim_input = SoccerSimSimulationInput(home_team="HOME", away_team="AWAY", seed=seed)
        output = simulate_match(sim_input, rng=Random(seed), profile=profile)
        totals.append(float(output.final_score["home"] + output.final_score["away"]))
    return mean(totals)


def calibrate(league: str, *, season: int, truth_total: float | None, simulations: int) -> None:
    windows = _season_windows(league, season)
    print(f"fetching shot events for {league} across {len(windows)} windows ({season} season)...")
    shots = aggregate_season_shot_events(league, date_windows=windows)
    print(f"{len(shots)} shots collected")
    if not shots:
        print("no shots collected -- nothing to calibrate")
        return

    locations = Counter(s.get("location") for s in shots)
    print(f"locations: {dict(locations)}")

    box_rate, box_n = _conversion(shots, location="box")
    six_yard_rate, six_yard_n = _conversion(shots, location="six_yard_box")
    outside_rate, outside_n = _conversion(shots, location="outside_box")
    corner_rate, corner_n = _conversion(shots, from_corner=True)
    non_corner_rate, non_corner_n = _conversion(shots, from_corner=False)

    print(f"box: conversion={box_rate:.4f} n={box_n}")
    print(f"six_yard_box: conversion={six_yard_rate:.4f} n={six_yard_n}")
    print(f"outside_box: conversion={outside_rate:.4f} n={outside_n}")
    print(f"from_corner=True: {corner_rate:.4f} n={corner_n}")
    print(f"from_corner=False: {non_corner_rate:.4f} n={non_corner_n}")

    current_profile = get_league_profile(league)
    print(
        f"current profile: box={current_profile.box_shot_conversion_base:.3f} "
        f"outside_box={current_profile.outside_box_conversion_base:.3f} "
        f"corner={current_profile.corner_shot_conversion_base:.3f} "
        f"goal_conversion_multiplier={current_profile.goal_conversion_multiplier:.3f}"
    )

    if box_n < 200 or outside_n < 200:
        print(f"WARNING: low sample size (box n={box_n}, outside_box n={outside_n}) -- treat these numbers cautiously")

    updated_profile = replace(
        current_profile,
        box_shot_conversion_base=round(box_rate, 3),
        outside_box_conversion_base=round(outside_rate, 3),
        corner_shot_conversion_base=round(corner_rate, 3),
    )

    if truth_total is None:
        print("no --truth-total given; skipping goal_conversion_multiplier re-anchor step")
        best_multiplier = current_profile.goal_conversion_multiplier
    else:
        print("multiplier scan:")
        best_multiplier = current_profile.goal_conversion_multiplier
        best_gap = None
        for candidate_multiplier in _MULTIPLIER_CANDIDATES:
            candidate_profile = replace(updated_profile, goal_conversion_multiplier=candidate_multiplier)
            simulated_total = _mean_simulated_goals(candidate_profile, simulations=simulations, seed_offset=int(candidate_multiplier * 1000) + 5000)
            gap = abs(simulated_total - truth_total)
            print(f"  multiplier={candidate_multiplier:.2f} -> simulated_total={simulated_total:.3f} (truth={truth_total:.2f}, gap={gap:.3f})")
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best_multiplier = candidate_multiplier
        if best_gap is not None and best_gap > _TOLERANCE_GOALS:
            print(f"WARNING: best achievable gap ({best_gap:.3f}) exceeds tolerance ({_TOLERANCE_GOALS}) -- treat this multiplier as a starting point, not a final answer; verify with a larger --simulations budget before trusting it to the last decimal")

    final_profile = replace(updated_profile, goal_conversion_multiplier=best_multiplier)
    final_total = _mean_simulated_goals(final_profile, simulations=simulations * 2, seed_offset=9000)
    print(
        f"\nFINAL for {league}: box_shot_conversion_base={final_profile.box_shot_conversion_base}, "
        f"outside_box_conversion_base={final_profile.outside_box_conversion_base}, "
        f"corner_shot_conversion_base={final_profile.corner_shot_conversion_base}, "
        f"goal_conversion_multiplier={final_profile.goal_conversion_multiplier}"
    )
    print(f"final simulated total goals/match: {final_total:.3f}" + (f" (truth {truth_total:.2f})" if truth_total is not None else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(LEAGUE_ESPN_SLUGS))
    parser.add_argument("--season", type=int, default=2025, help="Season start year to pull shots for (default: 2025, the just-completed season)")
    parser.add_argument("--truth-total", type=float, default=None, help="Known real goals/match to re-anchor goal_conversion_multiplier against")
    parser.add_argument("--simulations", type=int, default=400)
    args = parser.parse_args()
    calibrate(args.league, season=args.season, truth_total=args.truth_total, simulations=args.simulations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
