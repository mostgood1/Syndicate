"""Syndicate Fair v1 -- the STAGE-2 forward read (pre-registration section 11 + amendment A1). OFFLINE research.

Lane `syndicate-fair-v1`, todo `#737`. Registered in `.syndicate/findings_2026-10-26_syndicate_fair_v1_preregistration.md`
(`be3fcf23`, A1 `7786ab1e`): the SAME code and constants as stage 1, the walk-forward continuing, the gate re-read on
test dates with kickoffs `2026-10-26T08:00Z <= commence < 2026-11-23T08:00Z` only, read ON OR AFTER 2026-11-24, in two
arms (A = v1 as registered, the gate; B = lambda in 1e-8..1e-5, secondary -- a B-only pass is a lead, not a gate pass).

WHY A SEPARATE DRIVER. Stage 2 must run the stage-1 code unchanged, so this file imports `scripts/syndicate_fair_fit.py`
and `syndicate/features/shared/syndicate_fair.py` as they are and REFUSES to read unless both match the git blobs
recorded at stage 1 (`acdc917b` / `17bb127f`). It adds only what the registration and the stage-1 findings ask for
beside the gate: the window filter, the two arms, |fair - close| in pp (stage 1: v1 won log loss but sat further from
the close in pp) and the +/-2 sigma coverage (already in the fit module's report).

    nice -n 19 ionice -c3 python3 scripts/syndicate_fair_stage2.py extract --out /mnt/c/tmp/sfv1_stage2    # the fleet
    py -3 scripts/syndicate_fair_stage2.py outcomes --out C:/tmp/sfv1_stage2
    py -3 scripts/syndicate_fair_stage2.py read --out C:/tmp/sfv1_stage2 --report C:/tmp/sfv1_stage2/stage2.json

`extract` takes the whole history from 2026-09-30 (the walk-forward trains on everything before each test date) up to
the stage-2 end; `outcomes` fetches final scores for the stage-2 window only (training never reads an outcome).
`read` before 2026-11-24, or with `--window`, prints and records `registered_read: false` -- a PREVIEW, never the read.

Nothing here publishes. If the read leads to a refit, the record's parameters are republished with
`scripts/publish_syndicate_fair_params.py` (lane `syndicate-decision-engine`), which this script only reminds about.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]

STAGE2_START = "2026-10-26T08:00:00+00:00"
STAGE2_END = "2026-11-23T08:00:00+00:00"
READ_NOT_BEFORE = "2026-11-24"
#: Stage-1 blobs (`git rev-parse <commit>:<path>`), recorded in lane `syndicate-fair-v1` and the findings.
PINNED_BLOBS: dict[str, str] = {
    "scripts/syndicate_fair_fit.py": "acdc917b",
    "syndicate/features/shared/syndicate_fair.py": "17bb127f",
}
#: Arm A is the registered grid (asserted equal to the fit module's own); arm B is amendment A1's.
ARMS: dict[str, tuple[float, ...]] = {"A": (1e-5, 1e-4, 1e-3, 1e-2), "B": (1e-8, 1e-7, 1e-6, 1e-5)}
#: Pre-registration section 7: the multiplicity view is the 1 - 0.05/13 interval, fixed at registration.
BONFERRONI_FAMILIES = 13
PASSING = ("PASS", "PASS (outcome unmeasured)")


# ----------------------------------------------------------------------------- the pin


def git_blob_sha(data: bytes) -> str:
    """git's blob id for a file's content. CRLF is folded to LF first: a Windows checkout (autocrlf) holds CRLF on
    disk while the blob holds LF, and the question is whether the CODE is the stage-1 code, not the line endings."""
    data = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def pin_status(root: Path = REPO_ROOT) -> dict[str, dict[str, Any]]:
    """{path: {'pinned', 'found', 'ok'}} for each pinned file under `root`."""
    out: dict[str, dict[str, Any]] = {}
    for rel, pinned in PINNED_BLOBS.items():
        path = root / rel
        found = git_blob_sha(path.read_bytes()) if path.exists() else None
        out[rel] = {"pinned": pinned, "found": found, "ok": bool(found and found.startswith(pinned))}
    return out


def load_fit_module(root: Path = REPO_ROOT) -> Any:
    """The stage-1 fit module, loaded by path and unchanged (its stdlib-only top level keeps `extract` fleet-safe)."""
    spec = importlib.util.spec_from_file_location("syndicate_fair_fit", root / "scripts" / "syndicate_fair_fit.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ----------------------------------------------------------------------------- the read's additions


def registered_read(now: datetime, window_override: bool) -> bool:
    """True only for the registered read: on/after READ_NOT_BEFORE (UTC) with the registered window."""
    return not window_override and now.astimezone(timezone.utc).date().isoformat() >= READ_NOT_BEFORE


def abs_pp(p: Any, t: Any) -> Any:
    """Per-row distance in percentage points: |p0 - t0| on a two-way line, half the L1 distance on a 1X2 (the
    same number for a two-way line). Padded (R, 3) arrays, zeros in the masked outcomes."""
    import numpy as np

    return 100.0 * np.abs(np.asarray(p, dtype=float) - np.asarray(t, dtype=float)).sum(axis=1) / 2.0


def gate_verdict(verdict_a: str, verdict_b: str) -> dict[str, Any]:
    """Amendment A1: arm A is the gate; a B pass that A does not share is a lead for a v2 registration."""
    out: dict[str, Any] = {"gate": verdict_a, "arm_a": verdict_a, "arm_b": verdict_b, "lead": None}
    if verdict_b in PASSING and verdict_a not in PASSING:
        out["lead"] = "B-only pass: a lead for a v2 registration, NOT a gate pass (amendment A1)"
    return out


def with_grid(fit: Any, grid: tuple[float, ...], fn: Callable[[], Any]) -> Any:
    """Run `fn` with the fit module's LAMBDA_GRID set to `grid`, restoring it whatever happens."""
    held = fit.LAMBDA_GRID
    fit.LAMBDA_GRID = tuple(grid)
    try:
        return fn()
    finally:
        fit.LAMBDA_GRID = held


def subset_walk(wf: Mapping[str, Any], idx: Any) -> dict[str, Any]:
    """The walk-forward's arrays restricted to rows `idx` (sorted), aligned with `[rows[i] for i in idx]`."""
    return {"ds": wf["ds"].subset(idx), "p_v1": wf["p_v1"][idx], "p_eq": wf["p_eq"][idx], "sigma": wf["sigma"][idx]}


def read_family(fit: Any, rows: list[dict], start: int, end: int, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Both arms on one family: the walk-forward over ALL its rows, the reads on the window's rows only."""
    import numpy as np

    rows = sorted(rows, key=lambda r: r["commence"])
    idx = np.flatnonzero([start <= r["commence"] < end for r in rows])
    out: dict[str, Any] = {"window_rows": int(len(idx)), "arms": {}}
    if not len(idx):
        out["verdict"] = gate_verdict("UNDERPOWERED", "UNDERPOWERED")
        return out
    window_rows = [rows[i] for i in idx]
    for arm, grid in ARMS.items():
        t0 = time.time()
        wf = with_grid(fit, grid, lambda: fit.walk_forward(rows, log=log))
        sub = subset_walk(wf, idx)
        result = fit.evaluate_family(window_rows, sub, BONFERRONI_FAMILIES)
        games = np.array([r["ev"] for r in window_rows])
        scored = ~np.isnan(sub["p_v1"][:, 0])
        has_t = scored & np.array([r["target"] is not None for r in window_rows])
        if has_t.any():
            T = fit._pad(r["target"] if r["target"] is not None else [0.0] * r["k"] for r in window_rows)
            base = fit._pad(r["base"] for r in window_rows)
            pp_shin, pp_v1 = abs_pp(base, T), abs_pp(sub["p_v1"], T)
            pp = fit.cluster_boot((pp_v1 - pp_shin)[has_t], games[has_t])
            pp["pp_shin_to_close"] = float(pp_shin[has_t].mean())
            pp["pp_v1_to_close"] = float(pp_v1[has_t].mean())
            pp["pp_v1_from_shin"] = float(abs_pp(sub["p_v1"], base)[has_t].mean())
            result["abs_pp_v1_minus_shin"] = pp
        window_dates = {r["date"] for r in window_rows}
        result["fits_in_window"] = [f for f in wf["fits"] if f["test_date"] in window_dates]
        result["lambdas_in_window"] = [f["lambda"] for f in result["fits_in_window"]]
        result["weights"] = fit.weights_report(wf["model"], window_rows)
        result["secs"] = round(time.time() - t0, 1)
        out["arms"][arm] = result
    out["engine_read_vs_consensus_close"] = fit.engine_read(window_rows, target="cons_close")
    out["verdict"] = gate_verdict(out["arms"]["A"]["verdict"], out["arms"]["B"]["verdict"])
    return out


def window_coverage(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    d_sharp = {r["date"] for r in rows if r["src"] == "sharp"}
    d_y = {r["date"] for r in rows if r["y"] is not None}
    return {"rows": len(rows), "games": len({r["ev"] for r in rows}), "dates": len({r["date"] for r in rows}),
            "rows_sharp_close": sum(1 for r in rows if r["src"] == "sharp"),
            "rows_consensus_close": sum(1 for r in rows if r["src"] == "consensus"),
            "rows_outcome": sum(1 for r in rows if r["y"] is not None),
            "dates_sharp_and_outcome": len(d_sharp & d_y)}


# ----------------------------------------------------------------------------- commands


def _require_pins(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    status = pin_status()
    for rel, s in status.items():
        print(f"PIN {rel} pinned={s['pinned']} found={(s['found'] or 'MISSING')[:12]} ok={s['ok']}", flush=True)
    if not all(s["ok"] for s in status.values()) and not getattr(args, "allow_unpinned", False):
        raise SystemExit("REFUSING: the stage-1 code has changed; stage 2 must run the pinned blobs "
                         "(check out the pinned files, or pass --allow-unpinned and say why in the findings)")
    return status


def cmd_extract(args: argparse.Namespace) -> int:
    _require_pins(args)
    fit = load_fit_module()
    return fit.cmd_extract(argparse.Namespace(data_root=args.data_root, out=args.out, sports=args.sports,
                                              start=fit.WINDOW_START, end=STAGE2_END))


def cmd_outcomes(args: argparse.Namespace) -> int:
    _require_pins(args)
    fit = load_fit_module()
    return fit.cmd_outcomes(argparse.Namespace(out=args.out, base_url=args.base_url, start=STAGE2_START, end=STAGE2_END,
                                               refresh=args.refresh))


def cmd_read(args: argparse.Namespace) -> int:
    pins = _require_pins(args)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    fit = load_fit_module()
    if tuple(fit.LAMBDA_GRID) != ARMS["A"]:
        raise SystemExit(f"REFUSING: the fit module's LAMBDA_GRID {fit.LAMBDA_GRID} is not arm A's {ARMS['A']}")
    start_iso, end_iso = (args.window or [STAGE2_START, STAGE2_END])
    start, end = fit.epoch(start_iso), fit.epoch(end_iso)
    registered = registered_read(datetime.now(timezone.utc), bool(args.window))
    banner = "REGISTERED STAGE-2 READ" if registered else "PREVIEW -- NOT THE REGISTERED READ"
    print(f"{banner}: window [{start_iso}, {end_iso})", flush=True)
    out = Path(args.out)
    chips = {p.stem: json.loads(p.read_text(encoding="utf-8")).get("chips") or []
             for p in sorted((out / "chips").glob("????-??-??.json"))}
    by_family: dict[str, list[dict]] = defaultdict(list)
    assembly: dict[str, Any] = {}
    for sport in args.sports.split(","):
        rows, counters = fit.assemble_sport(out, sport, chips)
        assembly[sport] = counters
        print(f"ASSEMBLE {sport} {json.dumps(counters, sort_keys=True)}", flush=True)
        for r in rows:
            by_family[r["family"]].append(r)
    latest = max((r["commence"] for rs in by_family.values() for r in rs), default=None)
    report: dict[str, Any] = {
        "registered_read": registered, "window": [start_iso, end_iso], "read_at": datetime.now(timezone.utc).isoformat(),
        "pins": pins, "arms": {k: list(v) for k, v in ARMS.items()}, "bonferroni_families": BONFERRONI_FAMILIES,
        "latest_commence_in_data": None if latest is None else fit.iso(latest), "assembly": assembly, "families": {}}
    if latest is not None and latest < end - 86400:
        print(f"WARNING: the data ends at {fit.iso(latest)}, more than a day before the window's end", flush=True)
    for fam in sorted(by_family):
        rows = by_family[fam]
        cov = window_coverage(r for r in rows if start <= r["commence"] < end)
        print(f"COVERAGE {fam} {json.dumps(cov, sort_keys=True)}", flush=True)
        if fam.split("|")[1] == "preseason":
            report["families"][fam] = {"coverage": cov, "verdict": {"gate": "NOT GATED (preseason)"}}
            continue
        result = read_family(fit, rows, start, end, log=lambda s: print(s, flush=True))
        result["coverage"] = cov
        report["families"][fam] = result
        Path(args.report).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        for arm, r in result["arms"].items():
            g1, g2, pp = r.get("g1_close") or {}, r.get("g2_outcome") or {}, r.get("abs_pp_v1_minus_shin") or {}
            sig = r.get("sigma") or {}
            print(f"RESULT {fam} arm={arm} verdict={r['verdict']} g1={g1.get('mean')} ci={g1.get('ci0.95')} "
                  f"games={g1.get('games')} g2={g2.get('mean')} ci={g2.get('ci0.95')} dpp={pp.get('mean')} "
                  f"ci={pp.get('ci0.95')} sigma1={sig.get('inside_1sigma')} sigma2={sig.get('inside_2sigma')}", flush=True)
        print(f"GATE {fam} {json.dumps(result['verdict'])}", flush=True)
    Path(args.report).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(f"{banner}: report {args.report}", flush=True)
    print("REMINDER: a refit reaches the DecisionRecord only through scripts/publish_syndicate_fair_params.py "
          "(lane syndicate-decision-engine); this script publishes nothing.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="fleet side: the stage-1 extractor over 09-30 .. the stage-2 end")
    ex.add_argument("--data-root", default="~/syndicate-prod/data")
    ex.add_argument("--out", required=True)
    ex.add_argument("--sports", default="mlb,nba,wnba,nhl,nfl,ncaaf,soccer")
    ex.add_argument("--allow-unpinned", action="store_true")
    ex.set_defaults(func=cmd_extract)
    oc = sub.add_parser("outcomes", help="final scores for the stage-2 window (fleet web game-chips GET)")
    oc.add_argument("--out", required=True)
    oc.add_argument("--base-url", default="http://127.0.0.1:10000")
    oc.add_argument("--refresh", action="store_true")
    oc.add_argument("--allow-unpinned", action="store_true")
    oc.set_defaults(func=cmd_outcomes)
    rd = sub.add_parser("read", help="both arms, scored on the stage-2 window only")
    rd.add_argument("--out", required=True)
    rd.add_argument("--report", required=True)
    rd.add_argument("--sports", default="mlb,nba,wnba,nhl,nfl,ncaaf,soccer")
    rd.add_argument("--window", nargs=2, metavar=("START", "END"),
                    help="score another window (ISO times) -- always a PREVIEW, never the registered read")
    rd.add_argument("--allow-unpinned", action="store_true")
    rd.set_defaults(func=cmd_read)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
