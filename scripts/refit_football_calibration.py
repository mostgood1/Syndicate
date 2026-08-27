"""Re-fit BOTH football calibration profiles with the goal-line fix ON.

WHY BOTH, AND WHY NOW. `_goal_line_touchdown` (default-off, behind
`SYNDICATE_FOOTBALL_GOAL_LINE_TOUCHDOWN`) removes a real defect: touchdowns were
SAMPLED from a weight distribution and never triggered by reaching the end zone,
while the yardline clamps at 100, so a drive could pin itself on the goal line
and keep running plays. **6.60% of NCAAF drives gained more yards than the field
is long**; the longest reached 249.

It ships off because both profiles were fitted WITH that defect present, so
correcting the mechanism invalidates the estimators absorbing it:

    NFL   mean |err| vs truth   4.8% BEFORE  ->  5.9% AFTER the fix
    NCAAF drive-structure err  13.0% BEFORE  ->   5.2% AFTER

NFL is production and gets WORSE. That is `model_engine_standard.md`'s
mechanism-vs-estimator rule, measured rather than cited: a mechanism added to a
calibrated engine owes a re-fit of the rates that were absorbing it.

SHADOW, NEVER AUTO-APPLY. This writes CANDIDATE artifacts through
`save_versioned_profile` and promotes nothing. That is the store's own Phase 8
posture, and it is why NFL's profile resolves through `load_versioned_profile`
at import: a candidate can be pinned per-engine with
`SYNDICATE_CALIBRATION_PROFILE_PATH_{ENGINE}` for a shadow run without touching
code or the other sport.

TRUTH: `docs/reports/ncaaf_historical_truth_report.md` -- 53,548 real NCAAF
drives / 2,264 games and 17,677 real NFL drives / 816 games, 2023-2025. Both
columns of the same table, computed by the same builder.

THE SCORE IS A MEAN OVER STATED METRICS, and the metric set is fixed BEFORE any
sweep runs. Optimising a score chosen after seeing results is how a re-fit gets
credited for the metrics it happened to move.

    py -3 scripts/refit_football_calibration.py --games 200
    py -3 scripts/refit_football_calibration.py --games 200 --write-candidates
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FLAG = "SYNDICATE_FOOTBALL_GOAL_LINE_TOUCHDOWN"

# Truth, both columns of the same measured table. NOT market numbers and not
# accuracy scores -- a calibration target has to be a measured property of real
# football, or the fit chases the wrong thing.
TRUTH: dict[str, dict[str, float]] = {
    "ncaaf": {
        "possessions_per_game": 23.65,
        "plays_per_drive": 5.77,
        "seconds_per_drive": 165.4,
        "yards_per_drive": 42.49,
        "yards_per_play": 7.364,
        "touchdown_rate": 0.264,
        "field_goal_rate": 0.100,
        "punt_rate": 0.351,
        "turnover_rate": 0.109,
        "game_total": 53.35,
    },
    "nfl": {
        "possessions_per_game": 21.66,
        "plays_per_drive": 5.93,
        "seconds_per_drive": 166.2,
        "yards_per_drive": 30.66,
        "yards_per_play": 5.17,
        "touchdown_rate": 0.220,
        "field_goal_rate": 0.157,
        "punt_rate": 0.351,
        "turnover_rate": 0.111,
        "game_total": 45.13,
    },
}

# FIXED BEFORE THE SWEEP. Drive STRUCTURE plus the two scoring shares the
# goal-line fix disturbs, plus the game total that everything rolls up into.
SCORED = (
    "possessions_per_game", "plays_per_drive", "seconds_per_drive",
    "yards_per_drive", "touchdown_rate", "punt_rate", "game_total",
)


def _profiles():
    from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
    from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE
    return {"ncaaf": NCAAF_CALIBRATION_PROFILE, "nfl": NFL_CALIBRATION_PROFILE}


def _outcome(drive: dict) -> str:
    raw = str(drive.get("outcome") or "").lower()
    for key in ("touchdown", "field_goal", "punt", "turnover_on_downs", "turnover", "safety"):
        if key in raw:
            return key
    return "other"


def measure(profile, *, games: int, seed0: int = 9001) -> dict[str, float]:
    from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
    from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game

    plays, seconds, yards, poss, totals, gains = [], [], [], [], [], []
    counts: dict[str, int] = {}
    drives_total = 0
    for i in range(games):
        out = simulate_game(
            SmartSim2SimulationInput(
                home_team="A", away_team="B", seed=seed0 + i,
                home_offense_rating=0.0, home_defense_rating=0.0,
                away_offense_rating=0.0, away_defense_rating=0.0,
            ),
            profile=profile,
        )
        log = list(out.drive_log or [])
        if not log:
            continue
        poss.append(float(len(log)))
        totals.append(float(out.final_score["home"]) + float(out.final_score["away"]))
        for drive in log:
            drives_total += 1
            plays.append(float(drive.get("play_count") or 0))
            seconds.append(float(drive.get("clock_consumed") or 0))
            yards.append(float(drive.get("yards_gained") or 0))
            for step in (drive.get("steps") or []):
                gain = step.get("yards_gained") if isinstance(step, dict) else None
                if isinstance(gain, (int, float)):
                    gains.append(float(gain))
            counts[_outcome(drive)] = counts.get(_outcome(drive), 0) + 1

    def rate(key: str) -> float:
        return counts.get(key, 0) / drives_total if drives_total else float("nan")

    return {
        "possessions_per_game": statistics.mean(poss) if poss else float("nan"),
        "plays_per_drive": statistics.mean(plays) if plays else float("nan"),
        "seconds_per_drive": statistics.mean(seconds) if seconds else float("nan"),
        "yards_per_drive": statistics.mean(yards) if yards else float("nan"),
        "yards_per_play": statistics.mean(gains) if gains else float("nan"),
        "touchdown_rate": rate("touchdown"),
        "field_goal_rate": rate("field_goal"),
        "punt_rate": rate("punt"),
        "turnover_rate": rate("turnover"),
        "game_total": statistics.mean(totals) if totals else float("nan"),
        "_drives": float(drives_total),
    }


def score(measured: dict[str, float], sport: str) -> float:
    truth = TRUTH[sport]
    return statistics.mean(abs((measured[k] - truth[k]) / truth[k]) for k in SCORED)


def report(measured: dict[str, float], sport: str, label: str) -> float:
    truth = TRUTH[sport]
    print(f"\n=== {sport.upper()} · {label}   ({int(measured['_drives']):,} drives)")
    print(f"{'metric':<24}{'truth':>9}{'sim':>10}{'err':>9}")
    for key, want in truth.items():
        got = measured[key]
        mark = " *" if key in SCORED else ""
        print(f"{key:<24}{want:>9.3f}{got:>10.3f}{100 * (got - want) / want:>8.1f}%{mark}")
    s = score(measured, sport)
    print(f"{'SCORED mean |err|':<24}{'':>9}{'':>10}{100 * s:>8.2f}%")
    return s


# Coordinate descent over the levers each sport actually has. Ordered so the
# structural ones move before the scoring ones -- a scoring lever fitted against
# the wrong possession count has to be re-fitted the moment that count changes.
SWEEP: dict[str, list[tuple[str, list[float]]]] = {
    "ncaaf": [
        ("drive_yardage_multiplier", [1.15, 1.05, 0.95, 0.85, 0.78]),
        ("touchdown_weight_multiplier", [0.66, 0.55, 0.45, 0.36, 0.30]),
        ("red_zone_touchdown_weight_bonus", [0.58, 0.45, 0.33, 0.22]),
        ("field_goal_attempt_base_probability", [0.88, 0.78, 0.68, 0.58]),
    ],
    "nfl": [
        ("drive_yardage_multiplier", [1.00, 0.94, 0.88, 0.82]),
        ("touchdown_weight_multiplier", [1.00, 0.86, 0.74, 0.62]),
        ("red_zone_touchdown_weight_bonus", [0.33, 0.24, 0.16]),
        ("field_goal_attempt_base_probability", [0.88, 0.80, 0.72]),
    ],
}


def refit(sport: str, base, *, games: int) -> tuple[object, float, dict[str, float]]:
    best = base
    best_score = score(measure(base, games=games), sport)
    print(f"  start {sport}: {100 * best_score:.2f}%")
    for field, values in SWEEP[sport]:
        local_best, local_score = best, best_score
        for value in values:
            candidate = dataclasses.replace(best, **{field: value})
            s = score(measure(candidate, games=games), sport)
            if s < local_score - 1e-9:
                local_best, local_score = candidate, s
        if local_best is not best:
            print(f"    {field:<38} -> {getattr(local_best, field):<6} {100 * local_score:.2f}%")
        else:
            print(f"    {field:<38}    (no improvement, kept {getattr(best, field)})")
        best, best_score = local_best, local_score
    return best, best_score, measure(best, games=games)


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-fit both football profiles with the goal-line fix ON.")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--write-candidates", action="store_true",
                    help="Write candidate artifacts. Promotes NOTHING -- pin one with "
                         "SYNDICATE_CALIBRATION_PROFILE_PATH_{ENGINE} for a shadow run.")
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    if os.environ.get(FLAG, "").strip().lower() not in {"1", "true", "yes", "on"}:
        print(f"ERROR: {FLAG} is not set. This re-fit is only meaningful with the")
        print("       goal-line fix ON -- fitting against the defect is what produced")
        print("       the profiles being replaced.")
        return 2

    profiles = _profiles()
    results = {}
    for sport in ("ncaaf", "nfl"):
        base = profiles[sport]
        before = measure(base, games=args.games)
        report(before, sport, "as shipped, goal-line fix ON")
        print(f"\n  sweeping {sport} ...")
        fitted, fitted_score, after = refit(sport, base, games=args.games)
        report(after, sport, "RE-FITTED candidate")
        results[sport] = (base, fitted, score(before, sport), fitted_score)

    print("\n" + "=" * 74)
    print(f"{'sport':<8}{'as shipped':>14}{'re-fitted':>12}{'change':>12}")
    for sport, (_b, _f, s0, s1) in results.items():
        print(f"{sport:<8}{100 * s0:>13.2f}%{100 * s1:>11.2f}%{100 * (s1 - s0):>+11.2f}pts")
    print("=" * 74)

    for sport, (base, fitted, s0, s1) in results.items():
        changed = {f.name: getattr(fitted, f.name) for f in dataclasses.fields(fitted)
                   if getattr(fitted, f.name) != getattr(base, f.name)}
        print(f"\n{sport} changed fields: {changed or '(none)'}")

    if args.write_candidates:
        from syndicate.features.shared.calibration_profile_paths import calibration_profile_path
        from syndicate.features.shared.calibration_profile_store import save_versioned_profile
        for sport, (base, fitted, s0, s1) in results.items():
            if fitted is base:
                print(f"\n{sport}: no change, nothing written")
                continue
            path = args.out_dir / f"{sport}_candidate.json" if args.out_dir else calibration_profile_path(sport)
            written = save_versioned_profile(
                fitted,
                artifact_path=path,
                version=f"{sport}-goal-line-refit-1",
                fit_from={
                    "reason": "re-fit with SYNDICATE_FOOTBALL_GOAL_LINE_TOUCHDOWN enabled",
                    "truth": "ncaaf_historical_truth_report.md (53,548 NCAAF / 17,677 NFL drives)",
                    "scored_metrics": list(SCORED),
                    "games_per_measure": args.games,
                    "score_before": round(s0, 5),
                    "score_after": round(s1, 5),
                },
            )
            print(f"\n{sport}: candidate written -> {written}")
        print("\nPROMOTED NOTHING. Pin a candidate for a shadow run with")
        print("  SYNDICATE_CALIBRATION_PROFILE_PATH_<ENGINE>=<path>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
