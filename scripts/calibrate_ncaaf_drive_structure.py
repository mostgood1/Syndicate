"""Measure the NCAAF sim's DRIVE STRUCTURE against measured truth, and sweep levers.

WHY THIS EXISTS. `ncaaf_calibration_profile.py` says plays/drive and
seconds/drive were "measured within 3% of truth ... left at NFL defaults". That
line compares **NCAAF truth to NFL truth** -- two real-world datasets. It does
NOT say the SIMULATION reproduces them, and the simulation does not:

    metric              truth    sim @ profile v2    error
    plays per drive      5.77         7.34           +27%
    seconds per drive   165.4        185.7           +12%
    possessions/game    23.65        20.02           -15%

Those three are one defect, not three: drives that run too many plays consume
too much clock, so fewer possessions fit in a game.

PACE IS NOT THE LEVER, and this was measured before concluding it. The engine's
`pace_seconds_per_play` input is not on the real-world scale its name implies --
feeding the true league mean (26.27 s/play, from 20k cached drives) moves every
metric FURTHER from truth (possessions 17.91, seconds/drive 209.1). Hitting
truth through that input alone would need ~22.0, BELOW the hardcoded 24.0 and
below any real team. So the drive-structure gap is a profile-parameter problem.

TRUTH: `docs/reports/ncaaf_historical_truth_report.md`, 53,548 real drives over
2,264 games (2023-2025). Game totals there (53.35) independently agree with the
52.90 mean measured over 711 completed 2025 games, which is the check that the
truth table and the outcome data describe the same football.

    py -3 scripts/calibrate_ncaaf_drive_structure.py --games 200
    py -3 scripts/calibrate_ncaaf_drive_structure.py --sweep drive_yardage_multiplier=1.15,1.3,1.45
"""
from __future__ import annotations

import argparse
import dataclasses
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE

# Measured truth. Every number is from the truth report's pooled 2023-2025 table.
TRUTH: dict[str, float] = {
    "possessions_per_game": 23.65,
    "plays_per_drive": 5.77,
    "seconds_per_drive": 165.4,
    "yards_per_drive": 42.49,
    # Stated directly in the truth report AND equal to yards_per_drive /
    # plays_per_drive there (42.49 / 5.77 = 7.36). In the SIM those two
    # disagree, which is itself a finding -- see `yards_per_play_derived`.
    "yards_per_play": 7.364,
    "touchdown_rate": 0.264,
    "field_goal_rate": 0.100,
    "punt_rate": 0.351,
    "turnover_rate": 0.109,
    "turnover_on_downs_rate": 0.073,
    "game_total": 53.35,
    # Equal to `yards_per_play` in truth by construction; carried so the sim's
    # gross-vs-net gap is visible as a number rather than inferred.
    "yards_per_play_derived": 7.364,
}

# Metrics whose gap this tool exists to close. Reported separately so a sweep
# cannot be declared a win on the strength of the metrics it did not move.
PRIMARY = ("plays_per_drive", "seconds_per_drive", "possessions_per_game", "yards_per_play")


def _outcome(drive: dict) -> str:
    raw = str(drive.get("outcome") or "").lower()
    for key in ("touchdown", "field_goal", "punt", "turnover_on_downs", "turnover", "safety"):
        if key in raw:
            return key
    return "other"


def measure(profile, *, games: int, seed0: int = 9001) -> dict[str, float]:
    plays, seconds, yards, poss, totals = [], [], [], [], []
    play_gains: list[float] = []
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
            # MEASURED per play, the way the truth report measures it. The first
            # version only DERIVED yards/play as drive_yards / drive_plays and
            # reported -18.9% against truth. Measured directly it is +2.3%, and
            # the two disagree ONLY in the sim: in real football
            # 42.49 / 5.77 = 7.36 exactly. Comparing a derived quantity to a
            # measured one manufactured a defect that is not there.
            for step in (drive.get("steps") or []):
                gain = step.get("yards_gained") if isinstance(step, dict) else None
                if isinstance(gain, (int, float)):
                    play_gains.append(float(gain))
            plays.append(float(drive.get("play_count") or 0))
            seconds.append(float(drive.get("clock_consumed") or 0))
            yards.append(float(drive.get("yards_gained") or 0))
            key = _outcome(drive)
            counts[key] = counts.get(key, 0) + 1

    mean_plays = statistics.mean(plays) if plays else float("nan")
    return {
        "possessions_per_game": statistics.mean(poss) if poss else float("nan"),
        "plays_per_drive": mean_plays,
        "seconds_per_drive": statistics.mean(seconds) if seconds else float("nan"),
        "yards_per_drive": statistics.mean(yards) if yards else float("nan"),
        # MEASURED, comparable to truth.
        "yards_per_play": statistics.mean(play_gains) if play_gains else float("nan"),
        # DERIVED the way a drive table would give it. Equal to the measured
        # value in real football; a gap here means gross play gains are not
        # accumulating into drive yardage, which is the actual anomaly.
        "yards_per_play_derived": (statistics.mean(yards) / mean_plays) if plays and mean_plays else float("nan"),
        "touchdown_rate": counts.get("touchdown", 0) / drives_total if drives_total else float("nan"),
        "field_goal_rate": counts.get("field_goal", 0) / drives_total if drives_total else float("nan"),
        "punt_rate": counts.get("punt", 0) / drives_total if drives_total else float("nan"),
        "turnover_rate": counts.get("turnover", 0) / drives_total if drives_total else float("nan"),
        "turnover_on_downs_rate": counts.get("turnover_on_downs", 0) / drives_total if drives_total else float("nan"),
        "game_total": statistics.mean(totals) if totals else float("nan"),
        "_drives": float(drives_total),
    }


def report(measured: dict[str, float], *, label: str) -> float:
    print(f"\n=== {label}   ({int(measured['_drives']):,} simulated drives)")
    print(f"{'metric':<26}{'truth':>9}{'sim':>10}{'err':>10}{'':>3}")
    primary_err = []
    for key, truth in TRUTH.items():
        sim = measured.get(key, float("nan"))
        err = (sim - truth) / truth if truth else float("nan")
        mark = " *" if key in PRIMARY else ""
        print(f"{key:<26}{truth:>9.3f}{sim:>10.3f}{100 * err:>9.1f}%{mark}")
        if key in PRIMARY:
            primary_err.append(abs(err))
    score = statistics.mean(primary_err) if primary_err else float("nan")
    print(f"{'':<26}{'':>9}{'PRIMARY mean |err|':>20} {100 * score:.2f}%")
    return score


def main() -> int:
    ap = argparse.ArgumentParser(description="NCAAF drive-structure calibration against measured truth.")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--sweep", type=str, default=None,
                    help="param=v1,v2,v3 -- re-measure the profile with that field replaced.")
    args = ap.parse_args()

    base = measure(NCAAF_CALIBRATION_PROFILE, games=args.games)
    report(base, label="profile v2 as shipped")

    if args.sweep:
        name, _, values = args.sweep.partition("=")
        name = name.strip()
        if not hasattr(NCAAF_CALIBRATION_PROFILE, name):
            print(f"\nERROR: profile has no field {name!r}")
            return 2
        print(f"\n\n########## SWEEP {name} ##########")
        for raw in values.split(","):
            raw = raw.strip()
            if not raw:
                continue
            candidate = dataclasses.replace(NCAAF_CALIBRATION_PROFILE, **{name: float(raw)})
            report(measure(candidate, games=args.games), label=f"{name}={raw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
