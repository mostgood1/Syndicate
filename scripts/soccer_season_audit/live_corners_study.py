# -*- coding: utf-8 -*-
"""H29, offline: live REMAINING corners -- the production live re-sim vs the pregame estimator, with and
without an update on the corner rate observed so far.

Lane `soccer-live-model-study`, `#664` item 7. The rules are the registration, not this file:
`.syndicate/log/2026-09-17.md` ~11:50 CT (commit 16:51:51Z). Nothing here changes the engine.

    C0  production live: `project_live_match(state).projected_total_corners - so_far`, ratings computed as of
        the match date (`backtest_soccer_live_totals._production_ratings`), default profile (production passes
        none), include_stoppage=True, 300 simulations, seed 1
    C1  pregame pace:    E3_total * S(t)
    C2  running update:  S(t) * (a * E3_total + so_far) / (a + 1 - S(t))

S(t) is the mean share of a match's corners after cutoff t, and `a` is chosen from the registered grid; both
are fit on TRAIN (before 2026-08-22). Every number that decides the verdict is computed on TEST only.

    py -3 scripts/soccer_season_audit/live_corners_study.py --heldout <corners_estimators_heldout.csv>
        --espn-cache %TEMP%/espn_shots_cache --source-root <checkout>/data/soccer_source --out <dir>

The C0 projections are cached in `<out>/live_corners_c0.json` (the expensive part), so a re-run only re-scores.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
for p in (str(CHECKOUT), str(CHECKOUT / "scripts"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

CUTOFFS = (30, 45, 60, 75)
TRAIN_END = "2026-08-22"
A_GRID = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
SIMULATIONS, SEED = 300, 1
BOOT_REPS, BOOT_SEED = 2000, 11
EXCLUDED_LEAGUES = {"belgian_pro_league"}   # commentary carries no corners (0/554, measured before registering)


# ---------------------------------------------------------------------------- arms (pure)

def share_after(rows: list[dict]) -> dict[int, float]:
    """S(t): mean over matches (final > 0) of the share of the match's corners after cutoff t."""
    acc = collections.defaultdict(list)
    for r in rows:
        if r["final"] > 0:
            acc[r["cutoff"]].append((r["final"] - r["so_far"]) / r["final"])
    return {t: sum(v) / len(v) for t, v in acc.items() if v}


def c1(e3_total: float, s: float) -> float:
    return e3_total * s


def c2(e3_total: float, so_far: float, s: float, a: float) -> float:
    return s * (a * e3_total + so_far) / (a + 1.0 - s)


def pick_a(train: list[dict], s_by_t: dict[int, float]) -> tuple[float, dict[float, float]]:
    """The registered grid, pooled TRAIN MAE over the four cutoffs; ties go to the smaller a (listed first)."""
    scores = {}
    for a in A_GRID:
        errs = [abs(c2(r["e3"], r["so_far"], s_by_t[r["cutoff"]], a) - (r["final"] - r["so_far"])) for r in train]
        scores[a] = sum(errs) / len(errs)
    best = min(A_GRID, key=lambda a: scores[a])
    return best, scores


def paired_boot(rows: list[dict], fa: str, fb: str, reps: int = BOOT_REPS, seed: int = BOOT_SEED):
    """mean(|err fa| - |err fb|) with a match-clustered percentile CI (a match's cutoffs resampled together)."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["key"]].append(abs(r[fa]) - abs(r[fb]))
    units = list(by.values())
    stat = lambda s: sum(sum(u) for u in s) / max(sum(len(u) for u in s), 1)  # noqa: E731
    point = stat(units)
    if len(units) < 5:
        return point, (float("nan"), float("nan")), len(units)
    rng = random.Random(seed)
    k = len(units)
    vals = sorted(stat([units[rng.randrange(k)] for _ in range(k)]) for _ in range(reps))
    return point, (vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1]), k


def verdict(c2_vs_c0: tuple, c2_vs_c1_point: float) -> str:
    _, (lo, hi), _ = c2_vs_c0
    return "SUPPORTED" if (hi == hi and hi < 0 and c2_vs_c1_point <= 0) else "FALSIFIED"


# ---------------------------------------------------------------------------- data

def load_heldout(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            try:
                e3 = float(r["e3_h"]) + float(r["e3_a"])
            except (TypeError, ValueError):
                continue
            if math.isnan(e3) or r["lg"] in EXCLUDED_LEAGUES:
                continue
            out.append({"lg": r["lg"], "date": str(r["date"])[:10], "match_id": str(r["match_id"]), "e3": e3})
    return out


def engine_rows(matches: list[dict], espn_cache: Path, source_root: Path, cache_path: Path) -> tuple[list[dict], collections.Counter]:
    """One row per (match, cutoff): so_far, final, e3, C0. C0 projections cached on disk."""
    from outcomes import extract  # noqa: E402
    from backtest_soccer_live_totals import _production_ratings  # noqa: E402
    from syndicate.features.soccer.features.live_lens import project_live_match  # noqa: E402
    from syndicate.features.soccer.ingestion.espn_live_state import build_live_state  # noqa: E402

    cached = {}
    for other in sorted(cache_path.parent.glob("live_corners_c0*.json")):   # shard caches merge; seeds make them identical
        cached.update(json.loads(other.read_text(encoding="utf-8")))
    funnel = collections.Counter()
    rows = []
    started, dirty = time.time(), 0
    for i, m in enumerate(matches, 1):
        funnel["heldout_e3"] += 1
        path = espn_cache / f"{m['lg']}_{m['match_id']}.json"
        if not path.exists():
            continue
        summary = json.loads(path.read_text(encoding="utf-8"))
        box = extract(summary)
        if not box["completed"]:
            continue
        hc = (box["teams"].get("home") or {}).get("wonCorners")
        ac = (box["teams"].get("away") or {}).get("wonCorners")
        if hc is None or ac is None:
            continue
        funnel["completed_with_box_corners"] += 1
        final_state = build_live_state(summary, event_id=m["match_id"])
        pair = _production_ratings(m["lg"], source_root, m["date"], final_state["home_team"], final_state["away_team"])
        if pair is None:
            funnel["no_ratings_as_of"] += 1
            continue
        funnel["population"] += 1
        home_rating, away_rating = pair
        final = float(hc) + float(ac)
        for cutoff in CUTOFFS:
            key = f"{m['lg']}|{m['match_id']}|{cutoff}"
            state = build_live_state(summary, event_id=m["match_id"], as_of_seconds=cutoff * 60.0)
            so_far = float(int(state.get("home_corners_so_far") or 0) + int(state.get("away_corners_so_far") or 0))
            if key not in cached:
                proj = project_live_match(state, home_rating=home_rating, away_rating=away_rating,
                                          simulations=SIMULATIONS, seed=SEED, include_stoppage=True)
                cached[key] = {"projected_total_corners": proj.projected_total_corners, "so_far": so_far}
                dirty += 1
            rows.append({"key": f"{m['lg']}|{m['match_id']}", "lg": m["lg"], "date": m["date"], "cutoff": cutoff,
                         "so_far": so_far, "final": final, "e3": m["e3"],
                         "c0_remaining": float(cached[key]["projected_total_corners"]) - so_far})
        if dirty >= 40:
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            dirty = 0
        if i % 50 == 0:
            print(f"  {i}/{len(matches)} matches, {time.time() - started:.0f}s, funnel {dict(funnel)}", flush=True)
    cache_path.write_text(json.dumps(cached), encoding="utf-8")
    return rows, funnel


# ---------------------------------------------------------------------------- study

def study(rows: list[dict]) -> dict:
    train = [r for r in rows if r["date"] < TRAIN_END]
    test = [r for r in rows if r["date"] >= TRAIN_END]
    s_by_t = share_after(train)
    a, a_scores = pick_a(train, s_by_t)
    for r in test:
        target = r["final"] - r["so_far"]
        s = s_by_t[r["cutoff"]]
        r["err_c0"] = r["c0_remaining"] - target
        r["err_c1"] = c1(r["e3"], s) - target
        r["err_c2"] = c2(r["e3"], r["so_far"], s, a) - target

    def mae(rs, f):
        return sum(abs(x[f]) for x in rs) / len(rs) if rs else float("nan")

    def bias(rs, f):
        return sum(x[f] for x in rs) / len(rs) if rs else float("nan")

    out = {
        "train_matches": len({r["key"] for r in train}), "test_matches": len({r["key"] for r in test}),
        "S": s_by_t, "a": a, "a_train_mae": a_scores,
        "test_pooled": {f: {"mae": mae(test, f), "bias": bias(test, f)} for f in ("err_c0", "err_c1", "err_c2")},
        "per_cutoff": {t: {f: mae([r for r in test if r["cutoff"] == t], f) for f in ("err_c0", "err_c1", "err_c2")} for t in CUTOFFS},
        "per_league": {},
        "c2_vs_c0": paired_boot(test, "err_c2", "err_c0"),
        "c2_vs_c1": paired_boot(test, "err_c2", "err_c1"),
        "c1_vs_c0": paired_boot(test, "err_c1", "err_c0"),
    }
    for lg in sorted({r["lg"] for r in test}):
        sub = [r for r in test if r["lg"] == lg]
        out["per_league"][lg] = {"matches": len({r["key"] for r in sub}), **{f: mae(sub, f) for f in ("err_c0", "err_c1", "err_c2")},
                                 "bias_c0": bias(sub, "err_c0"), "bias_c2": bias(sub, "err_c2")}
    out["verdict"] = verdict(out["c2_vs_c0"], out["c2_vs_c1"][0])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--heldout", required=True)
    ap.add_argument("--espn-cache", required=True)
    ap.add_argument("--source-root", required=True, help="<checkout WITH data/>/data/soccer_source")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None, help="timing probe only; a limited run is never a verdict")
    ap.add_argument("--shard", default=None, help="i/N: fill the C0 cache for every N-th match only (no verdict); "
                    "run N shards in parallel, then once without --shard to score")
    args = ap.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    matches = sorted(load_heldout(Path(args.heldout)), key=lambda m: (m["date"], m["lg"], m["match_id"]))
    if args.limit:
        matches = matches[: args.limit]
    cache_name = "live_corners_c0.json"
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        matches = [m for k, m in enumerate(matches) if k % n == i]
        cache_name = f"live_corners_c0.shard{i}of{n}.json"
    rows, funnel = engine_rows(matches, Path(args.espn_cache), Path(args.source_root), out_dir / cache_name)
    print("funnel", dict(funnel), "rows", len(rows))
    if args.limit or args.shard:
        print("LIMITED OR SHARD RUN: no verdict")
        return 0
    res = study(rows)
    res["funnel"] = dict(funnel)
    (out_dir / "live_corners_study.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"TRAIN matches {res['train_matches']}  TEST matches {res['test_matches']}  S(t) {{{', '.join(f'{t}: {v:.3f}' for t, v in sorted(res['S'].items()))}}}  a={res['a']}")
    print("TEST pooled MAE / bias: " + " | ".join(f"{f[4:].upper()} {v['mae']:.3f} / {v['bias']:+.3f}" for f, v in res["test_pooled"].items()))
    for t, v in res["per_cutoff"].items():
        print(f"  {t:>2}'  C0 {v['err_c0']:.3f}  C1 {v['err_c1']:.3f}  C2 {v['err_c2']:.3f}")
    for name in ("c2_vs_c0", "c2_vs_c1", "c1_vs_c0"):
        p, (lo, hi), k = res[name]
        print(f"  {name}: mean |err| diff {p:+.4f} [{lo:+.4f}, {hi:+.4f}] over {k} matches")
    for lg, v in res["per_league"].items():
        print(f"  {lg:16s} n{v['matches']:4d}  C0 {v['err_c0']:.3f}  C1 {v['err_c1']:.3f}  C2 {v['err_c2']:.3f}  bias C0 {v['bias_c0']:+.2f}  C2 {v['bias_c2']:+.2f}")
    print("H29:", res["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
