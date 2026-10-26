"""Fit decision policy v1's lower-bound z (and the S2 residual r^2) ONCE, on stage-1 held-out closes. OFFLINE.

Lane `decision-policy-paper`. Implements section 3 of the pre-registration
(`.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md`, committed `8d16ab07` BEFORE this ran)
and nothing else. Writes `syndicate/features/shared/decision_policy_v1_params.json` (frozen for the forward test)
and a report beside it in --out.

  z_S1   the stage-1 walk-forward held-out arrays of the REGISTERED arm (<sfv1>/diag/<family>_registered.npz),
         the four PASS families. INPUT CHECK FIRST: their +/-1 sigma coverage around p_v1 must reproduce the
         published stage-1 table within 0.01, else z_S1 is not fitted.
  S2     rows from `syndicate_fair_fit.assemble_sport` over the stage-1 extract (all seven sports). The first two
         thirds of the UTC commence dates fit r^2 per (kind, mfam, tts); the last third is held out for z_S2.

The residual is always around `base`, the Shin median at the snapshot -- the p the bound is applied to at run
time (`market.p_market`, parity 0/3,125 in stage 1). z = -quantile(u, 0.1587): a one-sided Phi(1) lower bound.

    py -3 scripts/fit_decision_policy_z.py --sfv1 C:/tmp/sfv1 --out C:/tmp/dpv1
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import decision_policy_v1 as dp  # noqa: E402

PREREG_SHA = "8d16ab07"
S1_FAMILIES = ("ncaaf_regular_game", "nhl_regular_game", "nhl_regular_prop", "soccer_regular_game")
#: findings_2026-10-26_syndicate_fair_v1.md section 4 -- the input check's reference values.
PUBLISHED_1SIGMA = {"ncaaf_regular_game": 0.717, "nhl_regular_game": 0.735, "nhl_regular_prop": 0.772,
                    "soccer_regular_game": 0.700}
INPUT_CHECK_TOL = 0.01
SPORTS = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "soccer")
MIN_CELL_OUTCOMES = 200
TRAIN_SHARE = 2.0 / 3.0


def _idle() -> None:
    """Research jobs run at Idle: the fleet shares this host."""
    try:
        import psutil

        proc = psutil.Process()
        proc.nice(psutil.IDLE_PRIORITY_CLASS if sys.platform == "win32" else 19)
    except Exception:  # noqa: BLE001
        pass


def lower_z(u: Any) -> float | None:
    import numpy as np

    u = np.asarray(u, dtype=float)
    u = u[np.isfinite(u)]
    return None if not len(u) else float(-np.quantile(u, dp.LOWER_BOUND_TAIL))


def coverage(u: Any, k_sigma: float) -> float | None:
    import numpy as np

    u = np.asarray(u, dtype=float)
    u = u[np.isfinite(u)]
    return None if not len(u) else float(np.mean(np.abs(u) <= k_sigma))


def lower_coverage(u: Any, z: float) -> float | None:
    """Share of closes at or above the lower bound -- 0.8413 when the bound is calibrated."""
    import numpy as np

    u = np.asarray(u, dtype=float)
    u = u[np.isfinite(u)]
    return None if not len(u) else float(np.mean(u >= -z))


# ----------------------------------------------------------------------------- S1


def fit_s1(sfv1: Path) -> dict[str, Any]:
    import numpy as np

    from syndicate.features.shared import syndicate_fair as sf

    out: dict[str, Any] = {"families": {}}
    u_all: list[Any] = []
    u_sharp: list[Any] = []
    check_ok = True
    for fam in S1_FAMILIES:
        d = np.load(sfv1 / "diag" / f"{fam}_registered.npz", allow_pickle=True)
        k, has_t = d["k"], d["has_t"]
        sigma, T, base, p_v1 = d["sigma"], d["T"], d["base"], d["p_v1"]
        cols = np.arange(3)[None, :]
        valid = (cols < k[:, None]) & has_t[:, None] & np.isfinite(sigma) & (sigma > 0) & np.isfinite(T) \
            & np.isfinite(base) & np.isfinite(p_v1)
        # INPUT CHECK: the published +/-1 sigma coverage is around p_v1 on `scored_outcomes` (outcome 0 of a two-way
        # line, all three of a 1X2).
        scored = sf.scored_outcomes(cols < k[:, None]) & valid
        inside = np.abs(sf.logit(np.clip(T, 1e-6, 1 - 1e-6)) - sf.logit(np.clip(p_v1, 1e-6, 1 - 1e-6))) <= sigma
        cov = float((inside & scored).sum() / scored.sum()) if scored.any() else None
        ok = cov is not None and abs(cov - PUBLISHED_1SIGMA[fam]) <= INPUT_CHECK_TOL
        check_ok = check_ok and ok
        lt = sf.logit(np.clip(T, 1e-6, 1 - 1e-6))
        lb = sf.logit(np.clip(base, 1e-6, 1 - 1e-6))
        u = np.where(valid, (lt - lb) / np.where(sigma > 0, sigma, 1.0), np.nan)
        u_fam = u[valid]
        sharp = (d["src"] == "sharp")[:, None] & valid
        u_all.append(u_fam)
        u_sharp.append(u[sharp])
        out["families"][fam] = {
            "rows": int(len(k)), "rows_with_target": int(has_t.sum()), "games": int(len(set(d["games"][has_t]))),
            "outcomes_in_u": int(valid.sum()), "input_check_1sigma_around_p_v1": cov,
            "published_1sigma": PUBLISHED_1SIGMA[fam], "input_check_pass": ok,
            "z_family_reported_not_used": lower_z(u_fam),
        }
    u_cat = np.concatenate(u_all)
    out["input_check_pass"] = check_ok
    out["outcomes"] = int(len(u_cat))
    out["z_fitted"] = lower_z(u_cat) if check_ok else None
    out["z_sharp_target_reported_not_used"] = lower_z(np.concatenate(u_sharp))
    if out["z_fitted"] is not None:
        out["coverage_at_fitted_z"] = lower_coverage(u_cat, out["z_fitted"])
    out["coverage_1sigma_around_base"] = coverage(u_cat, 1.0)
    out["coverage_2sigma_around_base"] = coverage(u_cat, 2.0)
    return out


# ----------------------------------------------------------------------------- S2


def _load_fit_script() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("syndicate_fair_fit", REPO_ROOT / "scripts" / "syndicate_fair_fit.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def s2_outcome_rows(rows: list[dict]) -> list[dict]:
    """One entry per (row, outcome) with the dispersion variance and the residual around `base`.

    `scored` marks outcome 0 of a two-way line and every outcome of a 1X2 (the r^2 fit's set, as in
    `syndicate_fair.fit_residual_var`); the z quantile reads every outcome (a bet can be on either side)."""
    out = []
    for r in rows:
        target = r.get("target")
        if target is None:
            continue
        books = [list(p) for _b, _age, p in r["books"]]
        if len(books) < dp.MIN_BOOKS:
            continue
        k = int(r["k"])
        for j in range(k):
            out.append({
                "date": r["date"], "sport": r["sport"], "ev": r["ev"], "kind": r["kind"], "mfam": r["mfam"],
                "tts": r["tts"], "src": r["src"], "scored": (k == 3 or j == 0),
                "disp": dp.dispersion_var(books, j),
                "resid": dp.logit(float(target[j])) - dp.logit(float(r["base"][j])),
            })
    return out


def fit_r2(train: list[dict]) -> tuple[dict[str, float], dict[str, int]]:
    """r^2 = max(0, mean(resid^2) - mean(disp)) at three levels; a level is written only with >= 200 outcomes."""
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    for o in train:
        if not o["scored"]:
            continue
        for key in (f"{o['kind']}|{o['mfam']}|{o['tts']}", f"{o['kind']}|{o['mfam']}", o["kind"]):
            acc = sums[key]
            acc[0] += o["resid"] ** 2
            acc[1] += o["disp"]
            acc[2] += 1
    r2, n = {}, {}
    for key, (sq, disp, count) in sorted(sums.items()):
        n[key] = count
        if count >= MIN_CELL_OUTCOMES:
            r2[key] = max(0.0, (sq - disp) / count)
    return r2, n


def fit_s2(sfv1: Path, log: Any = print) -> dict[str, Any]:
    import numpy as np

    fit_script = _load_fit_script()
    outcomes: list[dict] = []
    counters: dict[str, Any] = {}
    for sport in SPORTS:  # one sport at a time: only the per-outcome numbers are kept
        if not (sfv1 / f"{sport}.snaps.jsonl.gz").is_file():
            continue
        t0 = time.time()
        got, _c = fit_script.assemble_sport(sfv1, sport, {}, parity_every=0)
        counters[sport] = {"rows": len(got), "rows_with_target": sum(1 for r in got if r["target"] is not None)}
        outcomes.extend(s2_outcome_rows(got))
        del got
        log(f"ASSEMBLED {sport} rows={counters[sport]['rows']} secs={time.time() - t0:.0f}")
    dates = sorted({o["date"] for o in outcomes})
    cut = int(math.floor(len(dates) * TRAIN_SHARE))
    train_dates, test_dates = set(dates[:cut]), set(dates[cut:])
    train = [o for o in outcomes if o["date"] in train_dates]
    test = [o for o in outcomes if o["date"] in test_dates]
    r2, n = fit_r2(train)
    params = dp.Params(r2_s2=r2, loaded=True)
    u = np.array([o["resid"] / math.sqrt(o["disp"] + dp.r2_for(params, o["kind"], o["mfam"], o["tts"]))
                  if (o["disp"] + dp.r2_for(params, o["kind"], o["mfam"], o["tts"])) > 0 else np.nan for o in test])
    z = lower_z(u)
    by_sport = {}
    for sport in sorted({o["sport"] for o in test}):
        sel = np.array([o["sport"] == sport for o in test])
        by_sport[sport] = {"outcomes": int(sel.sum()), "games": len({o["ev"] for o in test if o["sport"] == sport}),
                           "z_reported_not_used": lower_z(u[sel])}
    sharp = np.array([o["src"] == "sharp" for o in test])
    return {
        "per_sport_assembly": counters, "dates": [dates[0], dates[-1]] if dates else None,
        "train_dates": sorted(train_dates), "test_dates": sorted(test_dates),
        "train_outcomes": len(train), "test_outcomes": len(test),
        "test_games": len({o["ev"] for o in test}),
        "r2_s2": r2, "r2_cell_outcomes": n,
        "z_fitted": z, "coverage_at_fitted_z": lower_coverage(u, z) if z is not None else None,
        "coverage_1sigma": coverage(u, 1.0), "coverage_2sigma": coverage(u, 2.0),
        "z_sharp_target_reported_not_used": lower_z(u[sharp]) if sharp.any() else None,
        "z_by_sport_reported_not_used": by_sport,
        "median_sigma_logit_test": float(np.median([math.sqrt(o["disp"] + dp.r2_for(params, o["kind"], o["mfam"],
                                                                                   o["tts"])) for o in test]))
        if test else None,
    }


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short=8", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sfv1", default="C:/tmp/sfv1", help="the stage-1 extract directory")
    ap.add_argument("--out", default="C:/tmp/dpv1", help="where the full report is written")
    ap.add_argument("--params", default=str(dp.PARAMS_PATH))
    args = ap.parse_args(argv)
    _idle()
    sfv1, out = Path(args.sfv1), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    s1 = fit_s1(sfv1)
    print(f"S1 input_check_pass={s1['input_check_pass']} outcomes={s1['outcomes']} z={s1['z_fitted']}", flush=True)
    s2 = fit_s2(sfv1)
    print(f"S2 train={s2['train_outcomes']} test={s2['test_outcomes']} z={s2['z_fitted']}", flush=True)
    z_s1, z_s2 = s1["z_fitted"], s2["z_fitted"]
    guard = {name: (z is not None and dp.Z_GUARD[0] <= z <= dp.Z_GUARD[1]) for name, z in (("z_s1", z_s1), ("z_s2", z_s2))}
    head = _git_head()
    params = {
        "version": f"{dp.POLICY_VERSION}@2026-10-26@{head}",
        "preregistration": PREREG_SHA,
        "lower_bound_tail": dp.LOWER_BOUND_TAIL,
        "z_s1": z_s1, "z_s2": z_s2, "z_guard": list(dp.Z_GUARD), "z_inside_guard": guard,
        "r2_s2": s2["r2_s2"],
        "data": {"sfv1": str(sfv1), "s1_outcomes": s1["outcomes"], "s2_train_outcomes": s2["train_outcomes"],
                 "s2_test_outcomes": s2["test_outcomes"], "s2_dates": s2["dates"],
                 "s2_test_dates": s2["test_dates"]},
        "fitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "code_head": head,
    }
    Path(args.params).write_text(json.dumps(params, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "decision_policy_z_report.json").write_text(json.dumps({"s1": s1, "s2": s2, "params": params}, indent=1,
                                                                  sort_keys=True, default=str), encoding="utf-8")
    print(f"WROTE {args.params} and {out / 'decision_policy_z_report.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
