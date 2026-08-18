"""Measure the NFL sim-count knee directly. `#440` Phase 9, second anchor.

WHY. Phase 9 measured ONE knee -- MLB pitcher outs, ~300 sims. Every per-sport
recommendation in `sim_count_requirement.py` is scaled off that single point, so
the whole table is an anchored extrapolation. A second MEASURED knee on a
different sport, engine and quantity turns it into a fit, and NFL is the right
second sport: it is the only forecast with proven distributional skill
(margin +3.20%, CI [+1.10%, +5.31%]) and it has a validated truth join.

WHAT IT DOES. Regenerates 2025 regular-season projections at several seed counts
and scores each against the SAME climatology, exactly as the MLB sweep did.

TWO SAFETY PROPERTIES, both verified before this script existed:

  * **It cannot clobber production artifacts.** Output is redirected per seed
    level via `SYNDICATE_NFL_SOURCE_ROOT`; reads still probe `DATA_ROOT`.
    Confirmed by md5 on `smartsim2_projections_2025_wk1.csv` across a trial run.
  * **Regeneration is point-in-time correct.** `team_rating(..., before_week=w)`
    filters plays to before the target week and the prior season is used for the
    fallback, so this is genuinely walk-forward -- NOT the NCAAF failure mode,
    where full-season ratings were applied to games inside that season.

Concurrency is deliberately low: each subprocess parses two seasons of nflverse
pbp, so this is memory-bound rather than CPU-bound.

Usage:
  py -3 scripts/sweep_nfl_sim_count.py --seeds 50 100 300 1000 --weeks 1-18
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.model_scoring import crps_empirical, crps_normal  # noqa: E402

from scripts.skill_census_crps import _nflverse_finals  # noqa: E402

GEN = REPO_ROOT / "scripts" / "generate_smartsim2_nfl_projections.py"


def run_one(args: tuple[int, int, str]) -> dict:
    season, week, out_root = args
    env = dict(os.environ, SYNDICATE_NFL_SOURCE_ROOT=out_root)
    try:
        proc = subprocess.run(
            [sys.executable, str(GEN), "--season", str(season),
             "--week", str(week), "--seeds", str(int(Path(out_root).name.split("_")[-1]))],
            capture_output=True, text=True, env=env, timeout=3600)
        ok = proc.returncode == 0
        return {"week": week, "ok": ok,
                "err": (proc.stderr or "")[-200:] if not ok else None}
    except Exception as exc:  # noqa: BLE001
        return {"week": week, "ok": False, "err": f"{type(exc).__name__}: {exc}"}


def score(out_root: Path, finals: dict) -> dict:
    """CRPS of margin and total against the joined finals."""
    obs: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for path in sorted(out_root.glob("smartsim2_projections_*_wk*.csv")):
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    final = finals.get((row.get("game_id") or "").strip())
                    if final is None:
                        continue
                    home, away = final
                    for market, actual, mk, sk in (
                        ("margin", home - away, "margin_mean", "margin_stdev"),
                        ("total", home + away, "total_mean", "total_stdev"),
                    ):
                        try:
                            mean, sigma = float(row[mk]), float(row[sk])
                        except (TypeError, ValueError, KeyError):
                            continue
                        if sigma > 0:
                            obs[market].append((float(actual), mean, sigma))
        except Exception:  # noqa: BLE001
            continue

    out = {}
    for market, triples in obs.items():
        actuals = [t[0] for t in triples]
        clim_pmf = {str(v): c for v, c in Counter(actuals).items()}
        clim = [s for s in (crps_empirical(a, clim_pmf) for a in actuals) if s is not None]
        model = [s for s in (crps_normal(a, m, sg) for a, m, sg in triples) if s is not None]
        if not clim or not model:
            continue
        cm, cc = statistics.fmean(model), statistics.fmean(clim)
        out[market] = {"n": len(model), "crps_model": cm, "crps_climatology": cc,
                       "skill": 1.0 - cm / cc,
                       "mean_sigma": statistics.fmean(t[2] for t in triples)}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--seeds", type=int, nargs="+", default=[50, 100, 300, 1000])
    parser.add_argument("--weeks", default="1-18")
    parser.add_argument("--workers", type=int, default=4,
                        help="LOW on purpose: each subprocess parses two seasons of pbp")
    parser.add_argument("--scratch", type=Path,
                        default=Path(os.environ.get("TEMP", "/tmp")) / "nfl_seed_sweep")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    lo, _, hi = args.weeks.partition("-")
    weeks = list(range(int(lo), int(hi or lo) + 1))

    print("=" * 92)
    print("NFL SIM-COUNT SWEEP -- measuring the knee directly")
    print("=" * 92)
    print(f"\n  season {args.season}   weeks {weeks[0]}..{weeks[-1]}   seeds {args.seeds}")
    print(f"  scratch {args.scratch}")
    print("  production artifacts are NOT touched (writes redirected per seed level)\n")

    finals = _nflverse_finals({args.season}, "nfl")
    print(f"  truth games loaded: {len(finals)}\n")

    results = {}
    for seeds in args.seeds:
        out_root = args.scratch / f"seeds_{seeds}"
        out_root.mkdir(parents=True, exist_ok=True)
        todo = [(args.season, w, str(out_root)) for w in weeks]
        done = 0
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_one, t) for t in todo]
            for fut in as_completed(futures):
                r = fut.result()
                done += 1
                if not r["ok"]:
                    print(f"    seeds={seeds} wk{r['week']} FAILED: {r['err']}")
        scored = score(out_root, finals)
        results[seeds] = scored
        for market, cell in sorted(scored.items()):
            print(f"  seeds={seeds:5d} {market:7s} n={cell['n']:4d} "
                  f"CRPS={cell['crps_model']:.4f} skill={cell['skill']:+.2%}")

    print("\nTHE CURVE\n")
    for market in ("margin", "total"):
        print(f"  {market}")
        prev = None
        for seeds in args.seeds:
            cell = results.get(seeds, {}).get(market)
            if not cell:
                continue
            gain = "" if prev is None else f"   gain {(cell['skill'] - prev) * 100:+.2f} pp"
            print(f"    {seeds:5d}  CRPS {cell['crps_model']:.4f}  "
                  f"skill {cell['skill']:+.2%}{gain}")
            prev = cell["skill"]

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
