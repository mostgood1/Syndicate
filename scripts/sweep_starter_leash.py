"""Sweep the F5 leash (`starter_min_innings`) against real rosters and outcomes.

`#440` Phase 7 follow-up. Companion to `scripts/score_projections.py`, which
MEASURED the defect; this one tests whether the newly-exposed knob fixes it.

WHY THIS PARAMETER. Measured 2026-08-17 on 726 production starts: the sim
produces starts under 15 outs at 0.104 against an actual 0.296, and 26.78% of
all simulated mass sits at exactly 15 outs -- a point mass on the
`starter_min_innings = 5` boundary. Every other starter-depth knob in
`manager_pitching_overrides` acts on the pitch-count hook, which the leash
BYPASSES inside five innings, so none of them can move short starts. Until
2026-08-17 the leash was not exposed as an override at all.

WHAT THIS DOES. Re-simulates real games from their archived roster artifacts at
each grid value, joins the simulated starter-outs distribution to the real box
score on (date, game_pk, player_id), and scores each grid point with
`projection_score`. Point-in-time safe by construction: the roster artifact is a
frozen record of the inputs the sim actually had that day.

WHAT IT DOES NOT DO, AND WHY THAT MATTERS BEFORE ANYONE PROMOTES A VALUE.
It reports STATISTICAL accuracy only -- bias, MAE, CRPS, dispersion. It does NOT
grade betting hit rate against market lines. The overrides file records the hard
way that these come apart: `starter_tto_quality_scaling` was promoted on a clean
statistical improvement and reverted the same session because it made strikeout
betting accuracy WORSE (55.78% -> 54.65%). **A grid point that wins here is a
CANDIDATE, not a promotion.**

Usage:
  py -3 scripts/sweep_starter_leash.py --dates 1 --sims 40      # smoke
  py -3 scripts/sweep_starter_leash.py --sims 100 --workers 8   # real sweep
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor" / "mlb_bettingv2"
for entry in (str(REPO_ROOT), str(VENDOR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

MLB_DATA = REPO_ROOT / "data/mlb_source/source_artifacts/data"
DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
PK_RE = re.compile(r"_pk(\d+)_")
DEFAULT_GRID = (0, 3, 4, 5, 6)


def _work_units(limit_dates: int | None) -> list[tuple[str, Path]]:
    """(date, roster_artifact_path) for every archived game we can replay."""
    seen: dict[tuple[str, str], Path] = {}
    for family in ("daily_pitcher_props", "daily_hitter_props"):
        base = MLB_DATA / family / "snapshots"
        if not base.exists():
            continue
        for snapshot in sorted(base.iterdir()):
            match = DATE_RE.fullmatch(snapshot.name)
            if not match:
                continue
            date = snapshot.name
            for path in sorted((snapshot / "roster_objs").glob("roster_obj_*.json")):
                pk = PK_RE.search(path.name)
                if pk:
                    seen.setdefault((date, pk.group(1)), path)
    units = [(date, path) for (date, _pk), path in sorted(seen.items())]
    if limit_dates:
        keep = sorted({d for d, _ in units})[:limit_dates]
        units = [u for u in units if u[0] in set(keep)]
    return units


def load_actuals() -> dict[tuple[str, str, str], float]:
    path = MLB_DATA / "processed/mlb_pitcher_game_log.csv"
    out: dict[tuple[str, str, str], float] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                out[(row["date"], row["game_pk"], row["player_id"])] = float(row["outs"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


def simulate_unit(args: tuple[str, str, list[int], int, int]) -> list[dict[str, Any]]:
    """One game, every grid value. Returns per-(grid, starter) outs PMFs.

    Top-level so it is picklable on Windows spawn.
    """
    date, path_str, grid, sims, seed = args
    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    path = Path(path_str)
    pk_match = PK_RE.search(path.name)
    if not pk_match:
        return [{"error": f"no game_pk in {path.name}"}]
    game_pk = pk_match.group(1)

    try:
        # NOTE: this returns TeamRoster objects already -- do NOT pass them
        # through roster_from_dict. The first draft did, every worker raised
        # AttributeError, and a bare `except: return []` reported the whole
        # sweep as "0 joined" with no reason. Failures are counted now.
        raw = read_game_roster_artifact(path)
        away = raw["away"]
        home = raw["home"]
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"{path.name}: {type(exc).__name__}: {exc}"}]

    starters = {
        str(away.lineup.pitcher.player.mlbam_id),
        str(home.lineup.pitcher.player.mlbam_id),
    }

    records: list[dict[str, Any]] = []
    for value in grid:
        cfg = GameConfig(
            rng_seed=seed,
            manager_pitching="v2",
            manager_pitching_overrides={
                # The four already-promoted knobs, so the sweep runs on top of
                # production's real configuration rather than code defaults.
                "starter_hook_add_pitches": -13,
                "starter_hook_stamina_excess_weight": 0.75,
                "starter_quality_hook_weight": 1.0,
                "starter_tto_quality_scaling": 0.0,
                "starter_min_innings": int(value),
            },
        )
        pmfs: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        for i in range(sims):
            try:
                result = simulate_game(away, home, replace(cfg, rng_seed=seed + i))
            except Exception:
                continue
            for pid, stats in result.pitcher_stats.items():
                key = str(pid)
                if key in starters:
                    pmfs[key][int(stats.get("OUTS", 0))] += 1
        for pid, pmf in pmfs.items():
            records.append(
                {"date": date, "game_pk": game_pk, "player_id": pid,
                 "grid": int(value), "pmf": {str(k): v for k, v in pmf.items()}}
            )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=int, nargs="+", default=list(DEFAULT_GRID))
    parser.add_argument("--sims", type=int, default=100)
    parser.add_argument("--dates", type=int, default=None, help="limit to first N dates (smoke)")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument(
        "--dump-pmfs", type=Path, default=None,
        help="write per-start simulated PMFs so grading can be re-run without re-simulating "
             "(87,500 game-sims is ~7 minutes; grading them is instant)",
    )
    args = parser.parse_args()

    from syndicate.features.shared.projection_score import ProjectionObservation, score_cell

    units = _work_units(args.dates)
    actuals = load_actuals()
    dates = sorted({d for d, _ in units})
    actual_dates = sorted({k[0] for k in actuals})
    usable = sorted(set(dates) & set(actual_dates))

    print("=" * 100)
    print("F5 LEASH SWEEP -- starter_min_innings, real rosters, real outcomes")
    print("=" * 100)
    print("\nCOVERAGE FIRST")
    print(f"  roster-artifact dates   {len(dates)}  {dates[0] if dates else '-'} .. {dates[-1] if dates else '-'}")
    print(f"  outcome dates           {len(actual_dates)}")
    print(f"  INTERSECTION            {len(usable)}  {usable[0] if usable else '-'} .. {usable[-1] if usable else '-'}")
    units = [u for u in units if u[0] in set(usable)]
    print(f"  games replayable        {len(units)}")
    print(f"  grid                    {args.grid}   sims/game {args.sims}   workers {args.workers}")
    print(f"  total game-sims         {len(units) * len(args.grid) * args.sims:,}")
    if not units:
        print("\nNOTHING TO REPLAY -- no date has both a roster artifact and an outcome row.")
        return 1

    payloads = [(d, str(p), list(args.grid), int(args.sims), int(args.seed)) for d, p in units]

    records: list[dict[str, Any]] = []
    if args.workers > 1:
        import multiprocessing as mp

        with mp.Pool(processes=args.workers) as pool:
            for i, chunk in enumerate(pool.imap_unordered(simulate_unit, payloads, chunksize=1), 1):
                records.extend(chunk)
                if i % 25 == 0 or i == len(payloads):
                    print(f"    ... {i}/{len(payloads)} games", flush=True)
    else:
        for i, payload in enumerate(payloads, 1):
            records.extend(simulate_unit(payload))
            if i % 5 == 0 or i == len(payloads):
                print(f"    ... {i}/{len(payloads)} games", flush=True)

    # Score each grid point on IDENTICAL starts.
    errors = [r["error"] for r in records if "error" in r]
    records = [r for r in records if "error" not in r]
    if errors:
        print(f"\n  REPLAY FAILURES: {len(errors)} (first 3 shown) -- these are DROPPED games,")
        print("  reported rather than silently narrowing the sample:")
        for message in errors[:3]:
            print(f"    {message}")

    if args.dump_pmfs:
        args.dump_pmfs.parent.mkdir(parents=True, exist_ok=True)
        args.dump_pmfs.write_text(json.dumps(records), encoding="utf-8")
        print(f"  dumped {len(records)} per-start PMFs -> {args.dump_pmfs}")

    by_grid: dict[int, list[ProjectionObservation]] = defaultdict(list)
    short_sim: dict[int, list[float]] = defaultdict(list)
    joined = 0
    unjoined = 0
    actual_short: list[float] = []
    seen_starts: set[tuple[str, str, str]] = set()
    for rec in records:
        key = (rec["date"], rec["game_pk"], rec["player_id"])
        actual = actuals.get(key)
        if actual is None:
            unjoined += 1
            continue
        joined += 1
        pmf = rec["pmf"]
        total = sum(pmf.values())
        if total:
            below = sum(v for k, v in pmf.items() if float(k) < 15)
            short_sim[rec["grid"]].append(below / total)
        if key not in seen_starts:
            seen_starts.add(key)
            actual_short.append(1.0 if actual < 15 else 0.0)
        by_grid[rec["grid"]].append(
            ProjectionObservation(sport="mlb", market="pitcher_outs", actual=actual,
                                  distribution=pmf, subject_id=rec["player_id"], date=rec["date"])
        )

    actual_short_rate = sum(actual_short) / len(actual_short) if actual_short else float("nan")
    print(f"\n  starter-observations joined {joined}   unjoined {unjoined}")
    print(f"  distinct starts {len(seen_starts)}   ACTUAL P(outs<15) = {actual_short_rate:.4f}")

    print("\nRESULTS  (bias = actual - mean; negative = SIM RUNS HIGH. Target dispersion 0.7979)")
    header = (f"  {'leash':>6s} {'n':>6s} {'bias':>8s} {'MAE':>8s} {'CRPS':>8s} "
              f"{'disp':>7s} {'simP(<15)':>10s} {'vs actual':>10s} {'beats base':>11s}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    rows = []
    for value in args.grid:
        cell = score_cell(by_grid.get(value, []))
        sim_short = sum(short_sim.get(value, [])) / len(short_sim[value]) if short_sim.get(value) else float("nan")
        rows.append({"leash": value, "sim_p_short": sim_short, **cell})
        mark = "  <- current" if value == 5 else ""
        beat = cell["beats_constant_baseline"]

        def f(v, w=8, p=3):
            return f"{v:>{w}.{p}f}" if isinstance(v, (int, float)) else f"{'-':>{w}}"

        print(f"  {value:6d} {cell['sample_size']:6d} {f(cell['mean_signed_error'])} "
              f"{f(cell['mean_absolute_error'])} {f(cell['crps_empirical'])} "
              f"{f(cell['dispersion_ratio'], 7)} {f(sim_short, 10, 4)} "
              f"{f(sim_short - actual_short_rate, 10, 4)} "
              f"{('YES' if beat else 'no'):>11s}{mark}")

    print("\n  A grid point that wins here is a CANDIDATE, not a promotion:")
    print("  betting hit rate vs market lines is NOT graded by this script, and the")
    print("  overrides file records a knob that won statistically and lost real money.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"grid": args.grid, "sims": args.sims, "dates": usable,
             "actual_p_short": actual_short_rate, "rows": rows}, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
