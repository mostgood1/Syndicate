# -*- coding: utf-8 -*-
"""H35, offline: the DISTRIBUTION of live remaining corners around the published mean.

Lane `soccer-live-corners-dispersion`. The rules are the registration, not this file:
`.syndicate/log/2026-09-18.md` ~09:59 CT (commit `7efc381a`). Nothing here changes the engine.

The live projection publishes a remaining-corners MEAN (`prekickoff_pace_v1`: pregame E3 x the production
`SHARE_TABLE`), and an over/under price needs a distribution around it. Three laws, each with that mean:

    P0  Poisson
    P1  NB1  variance = phi * mu, one phi (the platform's pregame corners convention, `common.nb_sf`)
    P2  NB2  variance = mu + mu^2 / k, one k (a gamma-distributed match rate; its variance ratio shrinks late)

phi and k are fitted on TRAIN (before 2026-08-22) by maximum likelihood over registered grids; TRAIN
half-line log-loss picks P1 or P2; every number that decides the verdict is computed on TEST.

    py -3 scripts/soccer_season_audit/live_corners_dispersion_study.py --heldout <corners_estimators_heldout.csv>
        --espn-cache %TEMP%/espn_shots_cache --out <dir>
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
for p in (str(CHECKOUT), str(CHECKOUT / "scripts"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

CUTOFFS = (20, 30, 40, 50, 60, 70, 80)
TRAIN_END = "2026-08-22"
# 1.00 .. 5.00. AMENDED before any real data was read (`log/2026-09-18.md`): registered as 1.00 .. 3.00, which
# saturated on synthetic data with a true ratio of ~3.5, so an NB1-vs-NB2 choice could have been decided by the edge.
PHI_GRID = tuple(round(1.0 + 0.05 * i, 2) for i in range(81))
K_GRID = (1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 128, 256)
CLIP = 1e-6
BOOT_REPS, BOOT_SEED = 2000, 11
EXCLUDED_LEAGUES = frozenset({"belgian_pro_league"})   # historical commentary carries no corners; replays cannot use the box
LAWS = ("p0", "p1", "p2")


# ---------------------------------------------------------------------------- laws (pure)

def poisson_logpmf(x: int, mu: float) -> float:
    return -mu + x * math.log(mu) - math.lgamma(x + 1)


def nb1_logpmf(x: int, mu: float, phi: float) -> float:
    """Variance phi * mu, parameterised exactly as `common.nb_sf` (p = 1/phi, r = mu p / (1 - p))."""
    if phi <= 1.0001:
        return poisson_logpmf(x, mu)
    p = 1.0 / phi
    r = mu * p / (1.0 - p)
    return math.lgamma(x + r) - math.lgamma(r) - math.lgamma(x + 1) + r * math.log(p) + x * math.log(1.0 - p)


def nb2_logpmf(x: int, mu: float, k: float) -> float:
    """Variance mu + mu^2 / k: a Poisson whose rate is gamma-distributed with shape k."""
    p = k / (k + mu)
    return math.lgamma(x + k) - math.lgamma(k) - math.lgamma(x + 1) + k * math.log(p) + x * math.log(1.0 - p)


def logpmf(law: str, x: int, mu: float, fit: dict) -> float:
    mu = max(mu, 1e-9)
    if law == "p0":
        return poisson_logpmf(x, mu)
    if law == "p1":
        return nb1_logpmf(x, mu, fit["phi"])
    return nb2_logpmf(x, mu, fit["k"])


def prob_over(law: str, line: float, mu: float, fit: dict) -> float:
    """P(R > line) for a half-line, i.e. P(R >= line + 0.5)."""
    need = int(math.floor(line)) + 1
    cdf = sum(math.exp(logpmf(law, i, mu, fit)) for i in range(need))
    return min(1.0, max(0.0, 1.0 - cdf))


def lines_for(mu: float) -> list[float]:
    """The registered half-lines on remaining corners: floor(mu) - 0.5, + 0.5, + 1.5, none below 0.5."""
    f = math.floor(mu)
    return [line for line in (f - 0.5, f + 0.5, f + 1.5) if line >= 0.5]


def bernoulli_loss(p: float, happened: bool) -> float:
    p = min(1.0 - CLIP, max(CLIP, p))
    return -math.log(p if happened else 1.0 - p)


# ---------------------------------------------------------------------------- fitting + scoring

def fit_laws(train: list[dict]) -> dict:
    """phi and k by maximum likelihood of R on TRAIN, over the registered grids (ties to the first listed)."""
    def loglik(law, fit):
        return sum(logpmf(law, r["r_count"], r["mu"], fit) for r in train)

    phi_ll = {phi: loglik("p1", {"phi": phi}) for phi in PHI_GRID}
    k_ll = {k: loglik("p2", {"k": k}) for k in K_GRID}
    phi = max(PHI_GRID, key=lambda v: phi_ll[v])
    k = max(K_GRID, key=lambda v: k_ll[v])
    return {"phi": phi, "k": k, "phi_loglik": phi_ll, "k_loglik": k_ll}


def row_losses(row: dict, fit: dict) -> dict[str, list[float]]:
    out = {law: [] for law in LAWS}
    for line in lines_for(row["mu"]):
        happened = row["r"] > line
        for law in LAWS:
            out[law].append(bernoulli_loss(prob_over(law, line, row["mu"], fit), happened))
    return out


def mean_loss(rows: list[dict], fit: dict, law: str) -> float:
    vals = [v for r in rows for v in row_losses(r, fit)[law]]
    return sum(vals) / len(vals) if vals else float("nan")


def choose(train: list[dict], fit: dict) -> tuple[str, dict]:
    scores = {law: mean_loss(train, fit, law) for law in ("p1", "p2")}
    return ("p1" if scores["p1"] <= scores["p2"] else "p2"), scores


def paired_boot(test: list[dict], fit: dict, chosen: str, reps: int = BOOT_REPS, seed: int = BOOT_SEED):
    """mean(loss chosen - loss P0) over every TEST row and line, CI clustered by match."""
    by = collections.defaultdict(list)
    for r in test:
        losses = row_losses(r, fit)
        by[r["key"]].extend(a - b for a, b in zip(losses[chosen], losses["p0"]))
    units = [u for u in by.values() if u]
    stat = lambda s: sum(sum(u) for u in s) / max(sum(len(u) for u in s), 1)  # noqa: E731
    if not units:
        return float("nan"), (float("nan"), float("nan")), 0
    point = stat(units)
    rng = random.Random(seed)
    k = len(units)
    vals = sorted(stat([units[rng.randrange(k)] for _ in range(k)]) for _ in range(reps))
    return point, (vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1]), k


def verdict(boot: tuple) -> str:
    _, (_, hi), _ = boot
    return "SUPPORTED" if (hi == hi and hi < 0) else "FALSIFIED"


def reliability(rows: list[dict], fit: dict, law: str) -> list[dict]:
    """P(R > main line) in deciles of the prediction; main line = floor(mu) + 0.5."""
    bins = collections.defaultdict(list)
    for r in rows:
        line = math.floor(r["mu"]) + 0.5
        p = prob_over(law, line, r["mu"], fit)
        bins[min(9, int(p * 10))].append((p, r["r"] > line))
    return [{"decile": d, "n": len(v), "predicted": sum(p for p, _ in v) / len(v), "observed": sum(o for _, o in v) / len(v)}
            for d, v in sorted(bins.items())]


def variance_ratio(rows: list[dict]) -> float:
    if len(rows) < 2:
        return float("nan")
    resid = [r["r"] - r["mu"] for r in rows]
    return statistics.pvariance(resid) / (sum(r["mu"] for r in rows) / len(rows))


def study(rows: list[dict]) -> dict:
    train = [r for r in rows if r["date"] < TRAIN_END]
    test = [r for r in rows if r["date"] >= TRAIN_END]
    fit = fit_laws(train)
    chosen, train_scores = choose(train, fit)
    boot = paired_boot(test, fit, chosen)

    def pmf_score(rs, law):
        return -sum(logpmf(law, r["r_count"], r["mu"], fit) for r in rs) / len(rs) if rs else float("nan")

    return {
        "train_matches": len({r["key"] for r in train}), "test_matches": len({r["key"] for r in test}),
        "train_rows": len(train), "test_rows": len(test),
        "negative_remaining_rows": sum(1 for r in rows if r["r"] < 0),
        "phi": fit["phi"], "k": fit["k"], "chosen": chosen, "train_halfline_loss": train_scores,
        # a fit on the edge of its grid is a grid artefact, not an estimate; named so a reader cannot miss it
        "fit_at_grid_edge": [name for name, hit in (("phi", fit["phi"] == PHI_GRID[-1]), ("k", fit["k"] == K_GRID[0])) if hit],
        "test_halfline_loss": {law: mean_loss(test, fit, law) for law in LAWS},
        "test_pmf_logscore": {law: pmf_score(test, law) for law in LAWS},
        "per_cutoff": {t: {law: mean_loss([r for r in test if r["cutoff"] == t], fit, law) for law in LAWS}
                       for t in CUTOFFS},
        "variance_ratio": {t: {"train": variance_ratio([r for r in train if r["cutoff"] == t]),
                               "test": variance_ratio([r for r in test if r["cutoff"] == t])} for t in CUTOFFS},
        "per_league": {lg: {"matches": len({r["key"] for r in test if r["lg"] == lg}),
                            **{law: mean_loss([r for r in test if r["lg"] == lg], fit, law) for law in LAWS}}
                       for lg in sorted({r["lg"] for r in test})},
        "reliability": {law: reliability(test, fit, law) for law in sorted({"p0", chosen})},
        "chosen_vs_p0": boot,
        "verdict": verdict(boot),
    }


# ---------------------------------------------------------------------------- data

def match_rows(lg: str, match_id: str, date: str, e3: float, final: float, so_far_at) -> list[dict]:
    """One row per registered cutoff. `so_far_at(cutoff_minutes)` returns corners taken by then."""
    from syndicate.features.soccer.features.live_corners import share_remaining  # noqa: E402

    rows = []
    for cutoff in CUTOFFS:
        so_far = float(so_far_at(cutoff))
        remaining = final - so_far
        rows.append({"key": f"{lg}|{match_id}", "lg": lg, "date": date, "cutoff": cutoff, "so_far": so_far,
                     "final": final, "e3": e3, "mu": e3 * share_remaining(cutoff * 60.0),
                     "r": remaining, "r_count": max(0, int(round(remaining)))})
    return rows


def build_rows(heldout: Path, espn_cache: Path) -> tuple[list[dict], collections.Counter]:
    from live_corners_study import load_heldout  # noqa: E402 -- H29's reader: E3 per match, Belgian excluded
    from outcomes import extract  # noqa: E402
    from syndicate.features.soccer.ingestion.espn_live_state import build_live_state  # noqa: E402

    funnel = collections.Counter()
    rows = []
    for m in sorted(load_heldout(heldout), key=lambda m: (m["date"], m["lg"], m["match_id"])):
        funnel["heldout_e3"] += 1
        if m["lg"] in EXCLUDED_LEAGUES:
            continue
        path = espn_cache / f"{m['lg']}_{m['match_id']}.json"
        if not path.exists():
            funnel["no_summary"] += 1
            continue
        summary = json.loads(path.read_text(encoding="utf-8"))
        box = extract(summary)
        hc = (box["teams"].get("home") or {}).get("wonCorners")
        ac = (box["teams"].get("away") or {}).get("wonCorners")
        if not box["completed"] or hc is None or ac is None:
            funnel["not_completed_or_no_box"] += 1
            continue
        funnel["population"] += 1

        def so_far_at(cutoff, summary=summary, event=m["match_id"]):
            state = build_live_state(summary, event_id=event, as_of_seconds=cutoff * 60.0)
            return int(state.get("home_corners_so_far") or 0) + int(state.get("away_corners_so_far") or 0)

        rows.extend(match_rows(m["lg"], m["match_id"], m["date"], m["e3"], float(hc) + float(ac), so_far_at))
    return rows, funnel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--heldout", required=True)
    ap.add_argument("--espn-cache", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, funnel = build_rows(Path(args.heldout), Path(args.espn_cache))
    res = study(rows)
    res["funnel"] = dict(funnel)
    (out / "live_corners_dispersion_study.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")

    print(f"funnel {dict(funnel)}")
    print(f"TRAIN {res['train_matches']} matches / {res['train_rows']} rows   TEST {res['test_matches']} / {res['test_rows']}"
          f"   remaining < 0 rows: {res['negative_remaining_rows']}")
    print(f"fitted on TRAIN: phi {res['phi']}  k {res['k']}   TRAIN half-line loss {res['train_halfline_loss']}  -> chosen {res['chosen']}"
          f"   AT GRID EDGE: {res['fit_at_grid_edge'] or 'none'}")
    print("TEST half-line log-loss: " + "  ".join(f"{law} {v:.5f}" for law, v in res["test_halfline_loss"].items()))
    print("TEST full-pmf log score: " + "  ".join(f"{law} {v:.5f}" for law, v in res["test_pmf_logscore"].items()))
    for t in CUTOFFS:
        v, vr = res["per_cutoff"][t], res["variance_ratio"][t]
        print(f"  {t:>2}'  p0 {v['p0']:.4f}  p1 {v['p1']:.4f}  p2 {v['p2']:.4f}   var ratio TRAIN {vr['train']:.3f}  TEST {vr['test']:.3f}")
    for lg, v in res["per_league"].items():
        print(f"  {lg:16s} n{v['matches']:4d}  p0 {v['p0']:.4f}  p1 {v['p1']:.4f}  p2 {v['p2']:.4f}")
    for law, table in res["reliability"].items():
        print(f"  reliability {law}: " + "  ".join(f"[{b['decile']}] {b['predicted']:.2f}/{b['observed']:.2f} n{b['n']}" for b in table))
    p, (lo, hi), k = res["chosen_vs_p0"]
    print(f"  {res['chosen']} - p0 half-line log-loss {p:+.5f} [{lo:+.5f}, {hi:+.5f}] over {k} TEST matches")
    print("H35:", res["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
