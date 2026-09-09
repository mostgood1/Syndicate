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

**THE TABLE ABOVE IS THE IN-SOURCE DEFAULT AND PRODUCTION HAS NOT RUN IT SINCE
2026-08-27.** The live NCAAF profile is the promoted artifact
`data/calibration/ncaaf_profile.json` (`ncaaf-goal-line-refit-1`:
goal_line_touchdown ON, drive_yardage_multiplier 0.95, touchdown_weight
0.55, field_goal_attempt_base 0.58), and against IT the same run reads:

    metric              truth    sim @ ARTIFACT    error
    plays per drive      5.77         6.30         +9.3%
    seconds per drive   165.4        160.3         -3.1%
    possessions/game    23.65        22.91         -3.1%

i.e. two thirds of the gap this tool was written to chase is already closed,
and what remains is mostly OUTCOME QUALITY: game_total -7.1%, q2 scoring
-15.8%, yards/drive -22.3%, missed-FG rate +116%. `profile_source_banner()`
prints which of the two is loaded on every run, loudly, because a session
worktree excludes `data/` and the loader's fallback to the default is silent
by design.

S4a ADDITIONS (2026-09-09) -- three, all of them changes to what is MEASURED,
none to what is simulated:

1. TRUTH IS PARSED FROM THE REPORT, not re-typed here. `_truth_from_report()`
   reads the pooled 2023-2025 table out of the markdown. A hand-copied constant
   silently stops tracking its source the moment the source is re-derived; the
   parser cannot. The literal table is kept only as `_TRUTH_FALLBACK`, and
   `tests/test_ncaaf_drive_structure_calibration.py` asserts the two agree, so
   a divergence is a test failure rather than a quiet re-typing error.

2. `missed_field_goal` WAS BEING COUNTED AS `field_goal`. `_outcome` scanned for
   the substring "field_goal", and "missed_field_goal" CONTAINS it, so every
   missed kick landed in the made-FG bucket while truth's 10.0% counts made
   kicks only. That inflated the reported field_goal_rate error to +77%; split
   correctly it is made 12.5% vs 10.0% and missed 5.2% vs 3.1%. The gap is real
   but half the size the old number claimed, and it pointed at the wrong lever
   (make probability, when the attempt rate is what is high).

3. OUTCOME QUALITY IS MEASURED ALONGSIDE STRUCTURE. NFL's 2026-07-15 truth
   recalibration improved game-level metrics while per-quarter scoring got worse
   or stood still in three of four quarters (`smartsim_2_nfl_truth_recalibration_report.md`:
   q1 0.025 -> 0.063, q3 0.115 -> 0.115, q4 0.053 -> 0.075). That trade was only
   visible because someone measured it afterwards. Here it is a FIRST-CLASS
   score: `SECONDARY` carries game_total, the four quarters and the h1/h2 split,
   and `report()` prints a mean |err| for it beside the PRIMARY one. A fit that
   improves PRIMARY and degrades SECONDARY is a trade, and this tool says so.

   Dispersion note: `total_sd` here is measured at NEUTRAL ratings (both teams
   0.0), so it is the RESIDUAL, game-to-game spread only -- it does not contain
   the team-quality term that produces the ~2.17x-market over-dispersion
   recorded in `drive_priors.py:92`, which is a live-slate measurement with real
   SP+ ratings. `--rated` samples ratings so the slate-level term is present too;
   compare RATIOS between profiles there, not the absolute against the market.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import re
import statistics
import sys
from pathlib import Path
from random import Random

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE_METADATA
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_DRIVE_PROFILE_ACTIVE
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_DRIVE_PROFILE_VARIANTS
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import resolve_ncaaf_drive_profile

TRUTH_REPORT_PATH = REPO_ROOT / "docs" / "reports" / "ncaaf_historical_truth_report.md"

# Report row label -> metric key. The report's pooled table is the source; this
# only says which of its rows this tool compares against.
_TRUTH_ROW_KEYS: dict[str, str] = {
    "Possessions per game": "possessions_per_game",
    "Plays per drive": "plays_per_drive",
    "Seconds per drive": "seconds_per_drive",
    "Yards per drive": "yards_per_drive",
    "Touchdown rate": "touchdown_rate",
    "Field-goal rate (made)": "field_goal_rate",
    "Missed field-goal rate": "missed_field_goal_rate",
    "Punt rate": "punt_rate",
    "Turnover rate": "turnover_rate",
    "Turnover-on-downs rate": "turnover_on_downs_rate",
    "Q1 scoring": "quarter_1_scoring",
    "Q2 scoring": "quarter_2_scoring",
    "Q3 scoring": "quarter_3_scoring",
    "Q4 scoring": "quarter_4_scoring",
    "Game totals": "game_total",
}

# Kept ONLY as the cross-check for the parser, never as the value in use. Every
# number is from the truth report's pooled 2023-2025 table.
_TRUTH_FALLBACK: dict[str, float] = {
    "possessions_per_game": 23.65,
    "plays_per_drive": 5.77,
    "seconds_per_drive": 165.4,
    "yards_per_drive": 42.49,
    "touchdown_rate": 0.264,
    "field_goal_rate": 0.100,
    "missed_field_goal_rate": 0.031,
    "punt_rate": 0.351,
    "turnover_rate": 0.109,
    "turnover_on_downs_rate": 0.073,
    "quarter_1_scoring": 12.03,
    "quarter_2_scoring": 15.74,
    "quarter_3_scoring": 11.99,
    "quarter_4_scoring": 13.22,
    "game_total": 53.35,
}

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _truth_from_report(path: Path = TRUTH_REPORT_PATH) -> dict[str, float]:
    """Parse the pooled NCAAF truth column out of the truth report's markdown.

    The pooled table's rows are `| <label> | **<ncaaf>** | <nfl> | ... |`; the
    NCAAF column is the bolded one, which is what disambiguates it from the NFL
    column beside it. Percentages ("26.4%") are returned as rates.
    """
    text = path.read_text(encoding="utf-8")
    out: dict[str, float] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        key = _TRUTH_ROW_KEYS.get(cells[0])
        if key is None or key in out:
            continue
        raw = cells[1]
        if not (raw.startswith("**") and raw.endswith("**")):
            continue
        match = _NUMBER.search(raw)
        if match is None:
            continue
        value = float(match.group(0))
        out[key] = value / 100.0 if "%" in raw else value
    missing = set(_TRUTH_ROW_KEYS.values()) - set(out)
    if missing:
        raise ValueError(f"truth report {path} is missing rows for {sorted(missing)}")
    return out


TRUTH: dict[str, float] = dict(_truth_from_report())
# Derived, not stated separately in the report: equal to yards_per_drive /
# plays_per_drive there (42.49 / 5.77 = 7.36). In the SIM those two disagree,
# which is itself a finding -- see `yards_per_play_derived`.
TRUTH["yards_per_play"] = round(TRUTH["yards_per_drive"] / TRUTH["plays_per_drive"], 3)
TRUTH["yards_per_play_derived"] = TRUTH["yards_per_play"]
TRUTH["h1_scoring"] = round(TRUTH["quarter_1_scoring"] + TRUTH["quarter_2_scoring"], 2)
TRUTH["h2_scoring"] = round(TRUTH["quarter_3_scoring"] + TRUTH["quarter_4_scoring"], 2)

# Metrics whose gap this tool exists to close. Reported separately so a sweep
# cannot be declared a win on the strength of the metrics it did not move.
PRIMARY = ("plays_per_drive", "seconds_per_drive", "possessions_per_game", "yards_per_play")

# OUTCOME QUALITY -- scored as a first-class objective, not checked afterwards.
# See the module docstring: NFL's recalibration bought game-level metrics with
# per-quarter ones and nobody scored the trade while making it.
SECONDARY = (
    "game_total",
    "quarter_1_scoring",
    "quarter_2_scoring",
    "quarter_3_scoring",
    "quarter_4_scoring",
    "h1_scoring",
    "h2_scoring",
)

# OUTCOME MIX -- how drives END, and how far they travel. Scored as its own
# group rather than folded into either of the two above: a fit can hold
# plays/drive and game totals steady while quietly moving drives between the
# punt, field-goal and turnover-on-downs buckets, and neither PRIMARY nor
# SECONDARY would show it. The promoted artifact's own `fit_from.known_costs`
# records exactly that kind of accepted cost, so it must be visible here.
TERTIARY = (
    "touchdown_rate",
    "field_goal_rate",
    "missed_field_goal_rate",
    "punt_rate",
    "turnover_rate",
    "turnover_on_downs_rate",
    "yards_per_drive",
)

# Reported, not scored: no truth value exists for the sim's residual dispersion.
UNSCORED = ("total_sd",)

_ORDER = (
    "possessions_per_game",
    "plays_per_drive",
    "seconds_per_drive",
    "yards_per_drive",
    "yards_per_play",
    "yards_per_play_derived",
    "touchdown_rate",
    "field_goal_rate",
    "missed_field_goal_rate",
    "punt_rate",
    "turnover_rate",
    "turnover_on_downs_rate",
    "game_total",
    "total_sd",
    "quarter_1_scoring",
    "quarter_2_scoring",
    "quarter_3_scoring",
    "quarter_4_scoring",
    "h1_scoring",
    "h2_scoring",
)


def _outcome(drive: dict) -> str:
    raw = str(drive.get("outcome") or "").lower()
    # "missed_field_goal" BEFORE "field_goal": the longer label contains the
    # shorter one, and scanning in the other order counted every missed kick as
    # a made one. Truth's field-goal rate is made kicks only.
    for key in ("touchdown", "missed_field_goal", "field_goal", "punt", "turnover_on_downs", "turnover", "safety"):
        if key in raw:
            return key
    return "other"


def _rating_draw(rng: Random) -> float:
    """A team-quality rating on the engine's scale.

    SP+ components are points per game divided by `SP_RATING_SCALE = 10.0`
    (`generate_smartsim2_ncaaf_projections.py:499`), giving engine ratings with
    an SD near 0.7. Used only by `--rated`, and only to make the slate-level
    dispersion term PRESENT so two profiles can be compared on it -- the
    absolute is not a market comparison.
    """
    return rng.normalvariate(0.0, 0.7)


def measure(profile, *, games: int, seed0: int = 9001, rated: bool = False) -> dict[str, float]:
    plays, seconds, yards, poss, totals = [], [], [], [], []
    play_gains: list[float] = []
    quarter_points: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    counts: dict[str, int] = {}
    drives_total = 0
    rating_rng = Random(seed0)
    for i in range(games):
        if rated:
            home_off, home_def = _rating_draw(rating_rng), _rating_draw(rating_rng)
            away_off, away_def = _rating_draw(rating_rng), _rating_draw(rating_rng)
        else:
            home_off = home_def = away_off = away_def = 0.0
        out = simulate_game(
            SmartSim2SimulationInput(
                home_team="A", away_team="B", seed=seed0 + i,
                home_offense_rating=home_off, home_defense_rating=home_def,
                away_offense_rating=away_off, away_defense_rating=away_def,
            ),
            profile=profile,
        )
        log = list(out.drive_log or [])
        if not log:
            continue
        poss.append(float(len(log)))
        totals.append(float(out.final_score["home"]) + float(out.final_score["away"]))
        for entry in (out.quarter_log or []):
            quarter = int(entry.get("quarter") or 0)
            if quarter in quarter_points:
                quarter_points[quarter].append(
                    float(entry.get("home_points") or 0) + float(entry.get("away_points") or 0)
                )
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

    def _quarter_mean(quarter: int) -> float:
        values = quarter_points[quarter]
        return statistics.mean(values) if values else float("nan")

    quarter_means = {quarter: _quarter_mean(quarter) for quarter in (1, 2, 3, 4)}
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
        "missed_field_goal_rate": counts.get("missed_field_goal", 0) / drives_total if drives_total else float("nan"),
        "punt_rate": counts.get("punt", 0) / drives_total if drives_total else float("nan"),
        "turnover_rate": counts.get("turnover", 0) / drives_total if drives_total else float("nan"),
        "turnover_on_downs_rate": counts.get("turnover_on_downs", 0) / drives_total if drives_total else float("nan"),
        "game_total": statistics.mean(totals) if totals else float("nan"),
        "total_sd": statistics.pstdev(totals) if len(totals) > 1 else float("nan"),
        "quarter_1_scoring": quarter_means[1],
        "quarter_2_scoring": quarter_means[2],
        "quarter_3_scoring": quarter_means[3],
        "quarter_4_scoring": quarter_means[4],
        "h1_scoring": quarter_means[1] + quarter_means[2],
        "h2_scoring": quarter_means[3] + quarter_means[4],
        "_drives": float(drives_total),
    }


def profile_source_banner() -> str:
    """WHICH PROFILE IS BEING MEASURED, said out loud, every run.

    Measured 2026-09-09, and it cost most of a session: NCAAF's live profile is
    the PROMOTED ARTIFACT `data/calibration/ncaaf_profile.json`
    (`ncaaf-goal-line-refit-1`, goal_line_touchdown ON, drive_yardage_multiplier
    0.95), not the in-source default. A session worktree excludes `data/` by
    design, so `load_versioned_profile` finds no artifact, silently returns the
    DEFAULT -- which is what it is built to do -- and this tool then measures a
    profile production has not run since 2026-08-27. The numbers in this
    module's docstring (7.34 plays/drive, 20.02 possessions) are that default.
    Against the artifact the same run reads 6.30 and 22.91.

    An absent artifact is the loader's NORMAL state and must stay non-fatal, so
    the fix is not to raise -- it is to make the two cases impossible to confuse
    at a glance.
    """
    source = str(NCAAF_CALIBRATION_PROFILE_METADATA.get("source") or "?")
    version = str(NCAAF_CALIBRATION_PROFILE_METADATA.get("version") or "-")
    line = (f"profile source={source} version={version} variant={NCAAF_DRIVE_PROFILE_ACTIVE} "
            f"goal_line={NCAAF_CALIBRATION_PROFILE.goal_line_touchdown} "
            f"dy={NCAAF_CALIBRATION_PROFILE.drive_yardage_multiplier}")
    if source != "artifact":
        line += (
            "\n!!! NO PROMOTED ARTIFACT FOUND -- this is the IN-SOURCE DEFAULT, which is NOT what"
            f"\n!!! production runs. Expected at {NCAAF_CALIBRATION_PROFILE_METADATA.get('path')}."
            "\n!!! In a session worktree `data/` is excluded; point"
            "\n!!! SYNDICATE_CALIBRATION_PROFILE_DIR at a copy before trusting any number below."
        )
    return line


def report(measured: dict[str, float], *, label: str) -> tuple[float, float]:
    print(f"\n=== {label}   ({int(measured['_drives']):,} simulated drives)")
    print(f"{'metric':<26}{'truth':>9}{'sim':>10}{'err':>10}{'':>3}")
    primary_err, secondary_err, tertiary_err = [], [], []
    for key in _ORDER:
        sim = measured.get(key, float("nan"))
        truth = TRUTH.get(key)
        if truth is None:
            print(f"{key:<26}{'-':>9}{sim:>10.3f}{'-':>10}{'':>3}")
            continue
        err = (sim - truth) / truth if truth else float("nan")
        mark = " *" if key in PRIMARY else (" +" if key in SECONDARY else (" #" if key in TERTIARY else ""))
        print(f"{key:<26}{truth:>9.3f}{sim:>10.3f}{100 * err:>9.1f}%{mark}")
        if key in PRIMARY:
            primary_err.append(abs(err))
        if key in SECONDARY:
            secondary_err.append(abs(err))
        if key in TERTIARY:
            tertiary_err.append(abs(err))
    primary = statistics.mean(primary_err) if primary_err else float("nan")
    secondary = statistics.mean(secondary_err) if secondary_err else float("nan")
    tertiary = statistics.mean(tertiary_err) if tertiary_err else float("nan")
    print(f"{'':<26}{'':>9}{'PRIMARY   mean |err|':>20} {100 * primary:.2f}%   (* structure)")
    print(f"{'':<26}{'':>9}{'SECONDARY mean |err|':>20} {100 * secondary:.2f}%   (+ outcome quality)")
    print(f"{'':<26}{'':>9}{'TERTIARY  mean |err|':>20} {100 * tertiary:.2f}%   (# outcome mix)")
    return primary, secondary


def _coerce(raw: str) -> float | bool:
    lowered = raw.strip().lower()
    if lowered in {"true", "on", "yes"}:
        return True
    if lowered in {"false", "off", "no"}:
        return False
    return float(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description="NCAAF drive-structure calibration against measured truth.")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--sweep", type=str, default=None,
                    help="param=v1,v2,v3 -- re-measure the profile with that field replaced. "
                         "Values may be floats or true/false.")
    ap.add_argument("--set", dest="overrides", action="append", default=[],
                    help="param=value applied to the BASE profile before anything else. Repeatable.")
    ap.add_argument("--variant", type=str, default=None,
                    help=f"Also measure a named variant from NCAAF_DRIVE_PROFILE_VARIANTS "
                         f"({', '.join(sorted(NCAAF_DRIVE_PROFILE_VARIANTS)) or 'none registered'}).")
    ap.add_argument("--rated", action="store_true",
                    help="Sample team ratings instead of running both teams neutral, so the "
                         "slate-level dispersion term is present in total_sd. Compare RATIOS.")
    args = ap.parse_args()

    print(profile_source_banner())

    base = NCAAF_CALIBRATION_PROFILE
    if args.overrides:
        replacements = {}
        for item in args.overrides:
            name, _, raw = item.partition("=")
            replacements[name.strip()] = _coerce(raw)
        base = dataclasses.replace(base, **replacements)

    if os.environ.get("SYNDICATE_NCAAF_DRIVE_PROFILE"):
        # The flag rewrites NCAAF_CALIBRATION_PROFILE at import, so a sweep run
        # with it set is not measuring what its label says.
        print(f"NOTE: SYNDICATE_NCAAF_DRIVE_PROFILE={os.environ['SYNDICATE_NCAAF_DRIVE_PROFILE']!r} "
              f"is set -- the 'as shipped' baseline below is that variant, not the shipped profile.")

    source = str(NCAAF_CALIBRATION_PROFILE_METADATA.get("source") or "?")
    report(measure(base, games=args.games, rated=args.rated),
           label=f"live profile as loaded (source={source})")

    if args.variant:
        # Through the SAME resolver the engine uses, so the base-version guard
        # applies here too -- measuring a delta against the wrong base is exactly
        # the mistake this tool is now built to refuse.
        try:
            variant_profile, variant_name = resolve_ncaaf_drive_profile(
                base, args.variant,
                base_version=str(NCAAF_CALIBRATION_PROFILE_METADATA.get("version") or ""),
            )
        except ValueError as error:
            print(f"\nERROR: {error}")
            return 2
        report(
            measure(variant_profile, games=args.games, rated=args.rated),
            label=f"variant {variant_name}",
        )

    if args.sweep:
        name, _, values = args.sweep.partition("=")
        name = name.strip()
        if not hasattr(base, name):
            print(f"\nERROR: profile has no field {name!r}")
            return 2
        print(f"\n\n########## SWEEP {name} ##########")
        for raw in values.split(","):
            raw = raw.strip()
            if not raw:
                continue
            candidate = dataclasses.replace(base, **{name: _coerce(raw)})
            report(measure(candidate, games=args.games, rated=args.rated), label=f"{name}={raw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
