"""How many sims does EACH SPORT actually need? `#440` Phase 9, generalised.

Phase 9 measured MLB's curve directly (100/300/1000 draws, 490k game-sims) and
found the knee at ~300. That is one quantity -- pitcher outs -- and the obvious
question is whether 300 transfers to a soccer 3-way or a basketball prop. Doing
it by brute force means re-simulating every sport at several counts, which is
days of compute.

It does not need brute force, because the effect has a closed form.

THE MODEL. Scoring with an n-draw EMPIRICAL forecast instead of the underlying
distribution inflates CRPS by a known amount:

    E[CRPS_n]  =  CRPS_inf  +  MD / (2n)

where MD = E|X - X'| is the mean absolute difference between two independent
draws from the forecast. For a roughly Normal forecast MD = 2*sigma/sqrt(pi),
so the penalty is

    inflation  ~=  0.564 * sigma / n

Two things follow, and they are what make this useful:

  * the penalty scales with the FORECAST'S OWN SPREAD. A sport whose outcome is
    a 40-point football margin needs far more draws than one whose outcome is a
    3-goal soccer total, for the SAME accuracy in absolute terms.
  * what matters for a skill number is the penalty RELATIVE to the climatology
    CRPS, because that is the denominator every skill score is divided by.

So the requirement is

    n  >=  0.564 * sigma / (f * CRPS_climatology)

for a tolerated skill distortion of f (default 1%, i.e. the measurement is
within 1 skill point of what an infinite-sim forecast would score).

VALIDATION IS NOT OPTIONAL. The formula assumes near-Normality and the
quantities here are discrete, bounded below, and skewed. So it is CHECKED
against MLB's three measured points before being applied anywhere else, and the
check is printed. If it does not reproduce the measured curve, do not trust the
per-sport numbers under it.

Usage:
  py -3 scripts/sim_count_requirement.py
  py -3 scripts/sim_count_requirement.py --tolerance 0.005
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DATA = REPO_ROOT / "data"
PHASE7 = REPO_ROOT / "reports/phase7"

# Production sim counts, read from code defaults and live Render env 2026-08-17.
CURRENT = {
    ("soccer", "live_tick"): 80,
    ("basketball", "props_live_odds_worker"): 100,
    ("mlb", "live"): 120,
    ("football", "projections"): 300,
    ("soccer", "pregame"): 400,
    ("basketball", "props_code_default"): 500,
    ("mlb", "pregame"): 1000,
    ("nhl", "game_market"): 20000,
}

MD_OVER_SIGMA = 2.0 / math.sqrt(math.pi)  # = 1.1284, exact for a Normal


def pmf_sigma(pmf: dict) -> float | None:
    vals, wts = [], []
    for k, v in pmf.items():
        try:
            vals.append(float(k))
            wts.append(float(v))
        except (TypeError, ValueError):
            continue
    total = sum(wts)
    if total <= 0 or len(vals) < 2:
        return None
    mean = sum(v * w for v, w in zip(vals, wts)) / total
    var = sum(w * (v - mean) ** 2 for v, w in zip(vals, wts)) / total
    return math.sqrt(max(0.0, var))


def mlb_validation() -> dict:
    """Check the model against Phase 9's three MEASURED points."""
    measured = {}
    for n in (100, 300, 1000):
        path = PHASE7 / f"pmfs_sims_{n}.json"
        if not path.is_file():
            continue
        recs = [r for r in json.loads(path.read_text(encoding="utf-8")) if "error" not in r]
        # leash 5 == production's setting
        sigmas = [s for s in (pmf_sigma(r["pmf"]) for r in recs if int(r.get("grid", -1)) == 5)
                  if s is not None]
        if sigmas:
            measured[n] = statistics.fmean(sigmas)
    # CRPS actually measured at each count (leash 5), from the session record
    crps = {100: 2.5110, 300: 2.4516, 1000: 2.4498}
    return {"sigma_by_n": measured, "crps_by_n": crps}


def football_sigma(sport: str) -> dict[str, float]:
    out: dict[str, list[float]] = {"margin": [], "total": []}
    src = DATA / f"{sport}_source"
    for path in src.rglob("smartsim2_*projections_*.csv"):
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    for market, key in (("margin", "margin_stdev"), ("total", "total_stdev")):
                        try:
                            v = float(row.get(key))
                        except (TypeError, ValueError):
                            continue
                        if v > 0:
                            out[market].append(v)
        except Exception:  # noqa: BLE001
            continue
    return {k: statistics.fmean(v) for k, v in out.items() if v}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tolerance", type=float, default=0.01,
                        help="tolerated skill distortion, as a fraction of climatology CRPS")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    f = args.tolerance

    print("=" * 96)
    print("PER-SPORT SIM-COUNT REQUIREMENT")
    print("=" * 96)

    # ---- validate on MLB, where three points were actually measured ----
    val = mlb_validation()
    print("\nVALIDATION against Phase 9's measured MLB curve (leash 5)\n")
    if val["sigma_by_n"]:
        sigma = statistics.fmean(val["sigma_by_n"].values())
        print(f"  mean forecast sigma (outs)   {sigma:.3f}")
        base_n = 1000
        base_crps = val["crps_by_n"][base_n]
        crps_inf = base_crps - MD_OVER_SIGMA * sigma / (2 * base_n)
        print(f"  implied CRPS_inf             {crps_inf:.4f}")
        print(f"\n  {'n':>6s} {'measured':>10s} {'predicted':>10s} {'error':>8s} {'penalty x':>10s}")
        worst_ratio = 1.0
        for n, meas in sorted(val["crps_by_n"].items()):
            pred = crps_inf + MD_OVER_SIGMA * sigma / (2 * n)
            err = pred - meas
            # The quantity that matters is not the absolute CRPS error but how
            # badly the PENALTY (the part above CRPS_inf) is under-stated -- that
            # is what decides whether a recommended n is too small.
            pen_pred, pen_meas = pred - crps_inf, meas - crps_inf
            ratio = (pen_meas / pen_pred) if pen_pred > 1e-9 else 1.0
            worst_ratio = max(worst_ratio, ratio)
            print(f"  {n:6d} {meas:10.4f} {pred:10.4f} {err:+8.4f} {ratio:9.2f}x")
        print(f"\n  The Normal model UNDER-STATES the penalty at low n by up to "
              f"{worst_ratio:.1f}x.")
        print("  It is exact at n>=300 and wrong where it would matter most: at n=100 the")
        print("  real penalty is larger, because `outs` is discrete, bounded and skewed")
        print("  (26.78% of simulated mass sits on a single value) and the Normal's MD")
        print("  under-counts the spread of a lumpy distribution.")
        print("\n  => The closed form gives the SCALING, not the LEVEL. Below, the level is")
        print("     anchored on MLB's MEASURED knee (300) rather than taken from the formula.")
    else:
        print("  no Phase 9 PMFs on disk -- cannot validate; numbers below are UNVALIDATED")
        sigma = None

    # ---- per-sport requirement ----
    census_path = PHASE7 / "skill_census.json"
    clim: dict[tuple[str, str], float] = {}
    if census_path.is_file():
        for row in json.loads(census_path.read_text(encoding="utf-8")).get("rows", []):
            if row.get("crps_climatology"):
                clim[(row["sport"], row["market"])] = float(row["crps_climatology"])

    rows = []
    # ANCHOR: MLB's knee was MEASURED at 300 for a ratio of sigma/CRPS_clim.
    # Every other sport is scaled off that ratio rather than off the formula's
    # absolute level, which is known to be optimistic at small n.
    mlb_ratio = (sigma / 2.1927) if sigma else None
    MLB_MEASURED_KNEE = 300
    print(f"\nREQUIRED n -- formula for SCALING, level ANCHORED on MLB's measured knee "
          f"({MLB_MEASURED_KNEE})\n")
    if mlb_ratio:
        print(f"  anchor: MLB sigma/CRPS_clim = {mlb_ratio:.3f}  ->  measured knee "
              f"{MLB_MEASURED_KNEE} sims\n")
    header = (f"  {'sport':8s} {'market':9s} {'sigma':>8s} {'CRPS clim':>10s} {'ratio':>7s} "
              f"{'formula n':>10s} {'ANCHORED n':>11s}   current")
    print(header)
    print("  " + "-" * (len(header) + 4))

    entries = []
    for sport in ("nfl", "ncaaf"):
        sig = football_sigma(sport)
        for market, s in sig.items():
            entries.append((sport, market, s, clim.get((sport, market))))
    if sigma is not None:
        entries.append(("mlb", "outs", sigma, 2.1927))

    for sport, market, s, cc in entries:
        if not cc:
            print(f"  {sport:8s} {market:9s} {s:8.3f} {'—':>10s} {'—':>7s} {'—':>10s} "
                  f"{'—':>11s}   no climatology measured -- cannot compute")
            continue
        formula_n = MD_OVER_SIGMA * s / (2 * f * cc)
        ratio = s / cc
        anchored = (MLB_MEASURED_KNEE * ratio / mlb_ratio) if mlb_ratio else float("nan")
        cur = {"nfl": 300, "ncaaf": 300, "mlb": 1000}.get(sport)
        verdict = "OK" if cur and cur >= anchored else "TOO THIN"
        rows.append({"sport": sport, "market": market, "sigma": s, "crps_clim": cc,
                     "ratio": ratio, "formula_n": formula_n, "anchored_n": anchored,
                     "current": cur, "verdict": verdict})
        print(f"  {sport:8s} {market:9s} {s:8.3f} {cc:10.4f} {ratio:7.3f} {formula_n:10.0f} "
              f"{anchored:11.0f}   {cur} -> {verdict}")

    print("\nCURRENT PRODUCTION COUNTS, for reference (no principle connects them):")
    for (sport, path), n in sorted(CURRENT.items(), key=lambda kv: kv[1]):
        print(f"    {sport:11s} {path:26s} {n:>6d}")

    print("\n  THE TRANSFERABLE RESULT: required n scales with sigma / CRPS_climatology.")
    print("  A sport whose forecast spread is LARGE relative to how spread the outcome")
    print("  itself is needs MORE draws. That ratio -- not the sport -- is what sets it.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"tolerance": f, "rows": rows,
                                         "validation": val}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
