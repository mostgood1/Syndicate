"""How much MEMORY does raising the sim count actually cost? `#440` Phase 9.

Phase 9 measured that CRPS is still improving at 300 sims, so production's
counts (basketball 100, MLB live 120, soccer live 80) are too thin. The blocker
on raising them was never correctness -- it is that refresh-worker is
OOM-looping (`#449`) and live-odds-worker peaks at 1855/2048 MB. So the question
that decides the change is: **how many MB per game does each extra sim cost?**

THE ANSWER DEPENDS ENTIRELY ON ONE THING, and it is worth stating before any
number: does the caller RETAIN each simulation's result, or ACCUMULATE into a
fixed-size summary?

    accumulate -> memory is O(1) in n_sims. Raising sims costs CPU/time, NOT memory.
    retain     -> memory is O(n_sims). Raising sims is a linear memory cost.

These differ by orders of magnitude and the guess is not safe either way, so
both are measured here and the production call sites are reported alongside.

Measures RSS (what the container's cgroup limit actually counts, and what gets
a worker OOM-killed) and tracemalloc peak (Python-object allocation, which
excludes interpreter/allocator overhead). RSS is the one that matters for the
deploy decision; tracemalloc is reported because RSS is noisy and can be held
high by the allocator after objects are freed.

Usage:
  py -3 scripts/scope_sim_memory.py
  py -3 scripts/scope_sim_memory.py --sims 100 300 1000 2000 --games 2
"""

from __future__ import annotations

import argparse
import gc
import re
import sys
import tracemalloc
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor" / "mlb_bettingv2"
for p in (str(REPO_ROOT), str(VENDOR)):
    if p not in sys.path:
        sys.path.insert(0, p)

PK_RE = re.compile(r"_pk(\d+)_")
MLB_SNAPSHOTS = (REPO_ROOT
                 / "data/mlb_source/source_artifacts/data/daily_pitcher_props/snapshots")


def rss_mb() -> float:
    try:
        import psutil  # noqa: PLC0415
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return float("nan")


def find_roster() -> Path | None:
    if not MLB_SNAPSHOTS.exists():
        return None
    for snapshot in sorted(MLB_SNAPSHOTS.iterdir(), reverse=True):
        for path in sorted((snapshot / "roster_objs").glob("roster_obj_*.json")):
            if PK_RE.search(path.name):
                return path
    return None


def run(mode: str, away, home, cfg, sims: int, starters: set[str]) -> dict:
    """One game at `sims` draws. `mode` decides retain-vs-accumulate."""
    from sim_engine.simulate import simulate_game

    gc.collect()
    tracemalloc.start()
    base_rss = rss_mb()

    retained: list = []
    pmfs: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for i in range(sims):
        result = simulate_game(away, home, replace(cfg, rng_seed=2026 + i))
        if mode == "retain":
            # The worst case: hold every GameResult, as a caller building
            # per-sim sample files (NHL's props_boxscores_sim_samples_*.csv is
            # exactly this shape) necessarily does.
            retained.append(result)
        else:
            for pid, stats in result.pitcher_stats.items():
                if str(pid) in starters:
                    pmfs[str(pid)][int(stats.get("OUTS", 0))] += 1

    peak_rss = rss_mb()
    _, peak_py = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    held = len(retained)
    del retained, pmfs
    gc.collect()
    return {"mode": mode, "sims": sims, "rss_delta_mb": peak_rss - base_rss,
            "tracemalloc_peak_mb": peak_py / (1024 * 1024), "retained": held}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, nargs="+", default=[100, 300, 1000, 2000])
    parser.add_argument("--games", type=int, default=1)
    args = parser.parse_args()

    roster_path = find_roster()
    if roster_path is None:
        print("no MLB roster artifact found locally -- cannot scope")
        return 1

    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig

    raw = read_game_roster_artifact(roster_path)
    away, home = raw["away"], raw["home"]
    starters = {str(away.lineup.pitcher.player.mlbam_id),
                str(home.lineup.pitcher.player.mlbam_id)}
    cfg = GameConfig(rng_seed=2026, manager_pitching="v2")

    print("=" * 88)
    print("SIM-COUNT MEMORY SCOPING (MLB game sim)")
    print("=" * 88)
    print(f"\n  roster: {roster_path.name}")
    print(f"  psutil available: {'yes' if rss_mb() == rss_mb() else 'NO -- RSS will read nan'}\n")

    header = f"  {'mode':11s} {'sims':>6s} {'RSS delta MB':>13s} {'tracemalloc MB':>15s} {'MB / 1000 sims':>15s}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    rows = []
    for mode in ("accumulate", "retain"):
        for sims in args.sims:
            r = run(mode, away, home, cfg, sims, starters)
            per_1k = r["tracemalloc_peak_mb"] / sims * 1000
            rows.append(r | {"mb_per_1000_sims": per_1k})
            print(f"  {mode:11s} {sims:6d} {r['rss_delta_mb']:13.1f} "
                  f"{r['tracemalloc_peak_mb']:15.2f} {per_1k:15.2f}")

    acc = [r for r in rows if r["mode"] == "accumulate"]
    ret = [r for r in rows if r["mode"] == "retain"]
    print("\nREADING IT")
    if acc:
        lo, hi = acc[0], acc[-1]
        growth = hi["tracemalloc_peak_mb"] - lo["tracemalloc_peak_mb"]
        print(f"  accumulate: {lo['sims']} -> {hi['sims']} sims moved peak Python memory "
              f"by {growth:+.2f} MB")
        print("              If that is ~0, sim count is a CPU cost and NOT a memory cost,")
        print("              and the OOM constraint does not block raising it.")
    if ret:
        lo, hi = ret[0], ret[-1]
        span = hi["sims"] - lo["sims"]
        if span:
            slope = (hi["tracemalloc_peak_mb"] - lo["tracemalloc_peak_mb"]) / span * 1000
            print(f"  retain:     ~{slope:.2f} MB per 1000 sims per game -- linear, and the")
            print("              number a per-sim-sample writer must budget.")
    print("\n  Extrapolate to a slate by multiplying by CONCURRENT games, not total games:")
    print("  the MLB job simulates games sequentially, so peak is per-game, not per-slate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
