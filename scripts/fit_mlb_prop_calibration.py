"""Refit the MLB hitter-prop calibration against PRODUCTION, and prove it held-out.

`#624` step 1. This is the reproducible entrypoint behind
`vendor/mlb_bettingv2/data/tuning/hitter_props_calibration/default.json`; the
first fit of it (2026-09-01) found the DEPLOYED config had gone stale and was
measurably worse than no calibration at all.

WHY THIS EXISTS RATHER THAN A SCRATCH SCRIPT. `#622` wants calibration refit on
a schedule with a held-out gate, and a fit nobody can re-run is a fit nobody can
check. The math is NOT reimplemented here: the fit is
`vendor/mlb_bettingv2/tools/tune/fit_hitter_prob_calibration.py` and the
observation extraction is its own `_extract_prop_pairs`. A second definition of
either would drift from the thing being judged.

THE SPLIT IS THE POINT, and it is three-way on purpose:

    FIT   --batch-dir       fitted on
    VAL   --val-batch-dir   selects L2, and selects per-prop config below
                            -> USED BY FITTING, therefore NOT held out
    TEST  read exactly once at the end, by neither of the above

A two-way split would let VAL masquerade as a held-out set. Two refits in this
repo in one month looked better in-sample and were worse held-out (the WNBA
sigma refit and the soccer home-advantage refit), which is why the standing
rule is that a calibration validated only in-sample must not ship.

SUBSTRATE: Render, always. Reports are pulled from `/api/ops/artifacts/export`,
never from the local `data/**` mirror, which is refreshed per-family on
unrelated schedules and is not a snapshot of what production computed.

Usage:
    py -3 scripts/fit_mlb_prop_calibration.py --out-dir .\\reports\\prop_calibration
    py -3 scripts/fit_mlb_prop_calibration.py --out-dir ... --write-config
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from vendor.mlb_bettingv2.tools.tune.fit_hitter_prob_calibration import (  # noqa: E402
    _extract_prop_pairs,
    _iter_reports_from_batch,
)

DEFAULT_BASE = "https://syndicate-an21.onrender.com"
CONFIG_PATH = REPO_ROOT / "vendor" / "mlb_bettingv2" / "data" / "tuning" / "hitter_props_calibration" / "default.json"
FITTER = REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "tune" / "fit_hitter_prob_calibration.py"


# --------------------------------------------------------------------- scoring
def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _logit(p: float) -> float:
    p = min(1.0 - 1e-12, max(1e-12, p))
    return math.log(p) - math.log(1.0 - p)


def apply_calibration(p: float, spec: dict | None) -> float:
    """The applier's rule, restated only because this script must score what
    production would serve. Absent or disabled means identity."""
    if not spec or not spec.get("enabled", True):
        return p
    if str(spec.get("mode") or "affine_logit") != "affine_logit":
        return p
    return _sigmoid(float(spec.get("a", 1.0)) * _logit(p) + float(spec.get("b", 0.0)))


def spec_for(config: dict | None, prop: str) -> dict | None:
    if not config or not config.get("enabled", True):
        return None
    return (config.get("props") or {}).get(prop) or config.get("default")


def score(pairs: list[tuple[float, int]]) -> tuple[float, float]:
    brier = logloss = 0.0
    for p, y in pairs:
        pc = min(1.0 - 1e-12, max(1e-12, p))
        brier += (pc - y) ** 2
        logloss -= y * math.log(pc) + (1 - y) * math.log(1.0 - pc)
    n = max(1, len(pairs))
    return brier / n, logloss / n


def collect(batch_dir: Path) -> dict[str, list[tuple[float, int]]]:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in _iter_reports_from_batch(batch_dir)]
    props: set[str] = set()
    for report in reports:
        for game in report.get("games") or []:
            if isinstance(game, dict) and isinstance(game.get("hitter_props_backtest"), dict):
                props.update(str(key) for key in game["hitter_props_backtest"])
    out: dict[str, list[tuple[float, int]]] = {}
    for prop in sorted(props):
        pairs: list[tuple[float, int]] = []
        for report in reports:
            ps, ys, _ws = _extract_prop_pairs(report, prop)
            pairs.extend(zip(ps, ys))
        if pairs:
            out[prop] = pairs
    return out


def degenerate_dates(batch_dir: Path, prop: str) -> list[str]:
    """Dates where EVERY observation of `prop` is a literal 0.0 probability.

    A producer null looks exactly like this, and it poisons a fit without
    failing anything. MEASURED 2026-09-01, and this guard exists because the
    first run of this very script walked into it: `hits_runs_rbis_*` was 100%
    zeros on six dates (2026-06-14..06-25) and 0% on all 43 dates from 07-20,
    so a 60/20/20 chronological split put 1,422 of 7,074 HRR observations
    (20.1%) of literal zeros into FIT. The fitter did the only sane thing with
    them -- it pinned the slope at the clamp floor -- and I read that as
    "HRR carries no signal", which was a statement about the broken window and
    not about HRR. Refitted on clean dates the same prop yields healthy slopes
    (0.77-1.14).

    Whole-date and per-prop on purpose. A partial zero rate is a real (if ugly)
    distribution and excluding it would be editing data; a date that is 100%
    zeros for one prop while its neighbours are fine is a producer outage, and
    the `hits_1plus` control -- zero zeros on every date -- is what separates
    the two.
    """
    out: list[str] = []
    for path in _iter_reports_from_batch(batch_dir):
        match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
        report = json.loads(path.read_text(encoding="utf-8"))
        ps, _ys, _ws = _extract_prop_pairs(report, prop)
        if ps and all(p == 0.0 for p in ps):
            out.append(match.group(1) if match else path.name)
    return out


def report_degenerate(batch_dir: Path, props: list[str]) -> dict[str, list[str]]:
    """Announce what is being dropped. A silent exclusion is how a fit starts
    describing a population nobody chose."""
    found: dict[str, list[str]] = {}
    for prop in props:
        dates = degenerate_dates(batch_dir, prop)
        if dates:
            found[prop] = dates
            print(f"  DEGENERATE {prop}: {len(dates)} date(s) are 100% p=0.0 -> EXCLUDED "
                  f"({dates[0]}..{dates[-1]})", flush=True)
    return found


# ----------------------------------------------------------------- production
def _token(explicit: str) -> str:
    if explicit:
        return explicit
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no ADMIN_TOKEN (pass --admin-token or put it in .env)")


def _export(base: str, token: str, params: dict) -> dict:
    url = f"{base}/api/ops/artifacts/export?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"X-Admin-Token": token})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - a transient 502 must not lose the pull
            if attempt == 2:
                return {}
            time.sleep(5)
    return {}


def download_splits(base: str, token: str, work: Path) -> dict[str, tuple[str, str]]:
    names = sorted((_export(base, token, {"pattern": "*sim_vs_actual_*.json", "names_only": "1"}).get("artifacts") or {}))
    dated: list[tuple[str, str]] = []
    for name in names:
        match = re.search(r"sim_vs_actual_(\d{4}-\d{2}-\d{2})", name)
        if match:
            dated.append((match.group(1), name))
    dated.sort()
    if len(dated) < 12:
        raise SystemExit(f"only {len(dated)} reports on production; refusing to split a sample this thin")
    n_fit = int(len(dated) * 0.6)
    n_val = int(len(dated) * 0.2)
    splits = {"fit": dated[:n_fit], "val": dated[n_fit:n_fit + n_val], "test": dated[n_fit + n_val:]}
    windows: dict[str, tuple[str, str]] = {}
    for split, items in splits.items():
        out_dir = work / split
        out_dir.mkdir(parents=True, exist_ok=True)
        for date, name in items:
            payload = _export(base, token, {"pattern": name})
            artifacts = payload.get("artifacts") or {}
            doc = artifacts.get(name) or (next(iter(artifacts.values())) if artifacts else None)
            if isinstance(doc, str):
                doc = json.loads(doc)
            if isinstance(doc, dict):
                (out_dir / f"sim_vs_actual_{date}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        windows[split] = (items[0][0], items[-1][0])
        print(f"  {split}: {len(items)} reports {windows[split][0]}..{windows[split][1]}", flush=True)
    return windows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", required=True, help="Working dir for downloaded splits and the report")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--admin-token", default="")
    ap.add_argument("--min-n", type=int, default=500)
    ap.add_argument("--write-config", action="store_true",
                    help="Write the winning config. Refused unless it beats the incumbent held-out.")
    args = ap.parse_args()

    work = Path(args.out_dir)
    work.mkdir(parents=True, exist_ok=True)
    token = _token(args.admin_token)

    print("Pulling production sim_vs_actual reports (substrate: Render, not data/**)", flush=True)
    windows = download_splits(args.base_url, token, work)

    # SCAN FOR PRODUCER NULLS BEFORE FITTING ANYTHING. A date that is 100%
    # p=0.0 for one prop is an outage, not a distribution, and it silently
    # drags that prop's slope to the clamp floor -- which is precisely how the
    # first run of this script produced a confident wrong conclusion about
    # hits_runs_rbis. Dropping the report entirely is deliberate: the fitter
    # takes a DIRECTORY, so per-prop exclusion is not expressible, and a date
    # broken for one prop has no claim to be trusted for its neighbours.
    print("\nScanning for degenerate (100% p=0.0) dates before fitting:", flush=True)
    all_props = sorted(collect(work / "fit"))
    dropped = report_degenerate(work / "fit", all_props)
    if dropped:
        clean_dir = work / "fit_clean"
        if clean_dir.exists():
            for stale in clean_dir.glob("sim_vs_actual_*.json"):
                stale.unlink()
        clean_dir.mkdir(parents=True, exist_ok=True)
        bad = {date for dates in dropped.values() for date in dates}
        kept = 0
        for path in _iter_reports_from_batch(work / "fit"):
            match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
            if match and match.group(1) in bad:
                continue
            (clean_dir / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            kept += 1
        print(f"  fitting on {kept} clean report(s) instead of {kept + len(bad)}", flush=True)
        fit_dir = clean_dir
    else:
        print("  none", flush=True)
        fit_dir = work / "fit"

    candidate_path = work / "candidate_props.json"
    subprocess.run(
        [sys.executable, str(FITTER),
         "--batch-dir", str(fit_dir), "--val-batch-dir", str(work / "val"),
         "--out-props", str(candidate_path), "--out-hr", str(work / "candidate_hr.json"),
         "--min-n", str(args.min_n)],
        check=True, cwd=str(REPO_ROOT),
    )

    incumbent = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))

    # Per-prop selection on VAL. Never on TEST -- selecting on the held-out set
    # is fitting to it, and then it is no longer held out.
    val = collect(work / "val")
    hybrid = {"enabled": True, "default": incumbent.get("default"), "props": {}}
    chosen: dict[str, str] = {}
    for prop, pairs in val.items():
        options = {"raw": score([(p, y) for p, y in pairs])[1]}
        for label, config in (("incumbent", incumbent), ("candidate", candidate)):
            spec = (config.get("props") or {}).get(prop)
            if spec:
                options[label] = score([(apply_calibration(p, spec), y) for p, y in pairs])[1]
        best = min(options, key=options.get)
        chosen[prop] = best
        if best == "incumbent":
            hybrid["props"][prop] = incumbent["props"][prop]
        elif best == "candidate":
            hybrid["props"][prop] = candidate["props"][prop]
        # "raw" -> no entry at all, so the applier leaves the prop alone

    test = collect(work / "test")
    results = {}
    for label, config in (("raw", None), ("incumbent", incumbent), ("hybrid", hybrid)):
        pairs = [(apply_calibration(p, spec_for(config, prop)) if config else p, y)
                 for prop, prop_pairs in test.items() for p, y in prop_pairs]
        brier, logloss = score(pairs)
        results[label] = {"logloss": round(logloss, 5), "brier": round(brier, 5), "n": len(pairs)}

    print(f"\nHELD-OUT TEST {windows['test'][0]}..{windows['test'][1]} (never fitted, never selected on)")
    for label in ("raw", "incumbent", "hybrid"):
        row = results[label]
        print(f"  {label:<11} n={row['n']:<7} LogLoss={row['logloss']:.5f}  Brier={row['brier']:.5f}")

    beats = (results["hybrid"]["logloss"] < results["incumbent"]["logloss"]
             and results["hybrid"]["brier"] <= results["incumbent"]["brier"])
    print(f"\nGATE (must beat the INCUMBENT on both metrics held-out): {'PASS' if beats else 'FAIL'}")
    (work / "report.json").write_text(json.dumps(
        {"windows": {k: list(v) for k, v in windows.items()}, "test": results,
         "selected": chosen, "gate_pass": beats,
         "degenerate_dates_excluded": dropped}, indent=2), encoding="utf-8")

    if args.write_config:
        if not beats:
            print("REFUSING to write the config: it does not beat the incumbent held-out.")
            return 1
        hybrid["_meta"] = {"generated_at": time.strftime("%Y-%m-%d"), "windows": {k: list(v) for k, v in windows.items()},
                           "held_out_test": results, "per_prop_source": chosen}
        CONFIG_PATH.write_text(json.dumps(hybrid, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
