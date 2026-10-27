"""ev_lb funnel -- a READ-ONLY, post-hoc diagnostic of Phase 2's primary rule (`#738`, `#736`).

Why `ev_lb` books so few paper bets: for each ELIGIBLE candidate, which of three things stops it. It re-runs the
paper job's OWN candidate path (`decision_policy_paper.book_build` minus every write: expand -> load_grid ->
sigma_for_record -> decision_policy_v1.evaluate) on record files already on disk. It changes no rule, places nothing
and writes only to --out. Findings: `.syndicate/findings_2026-10-27_ev_lb_funnel.md`.

In probability points, with g = p - ask, f = the taker fee and h = p - p_lb (the uncertainty haircut):

    EV_lb > 0  <=>  p_lb > ask + fee  <=>  g > f + h

    A  g <= 0          the ask is at or above the consensus fair (no raw edge)
    B  0 < g <= f      a raw edge the taker fee eats
    C  f < g <= f + h  net EV > 0, eaten by the uncertainty haircut
    D  g > f + h       qualifies

A and B do not depend on sigma at all. Replaying an OLD record file is only faithful for A/B: the book grid has
moved on since that build, so sigma falls back to S3 and the haircut reads too wide. Read C/D on current files.

Usage (fleet, at Idle):
    nice -n 19 python scripts/ev_lb_funnel_read.py --out /mnt/c/tmp/funnel/out [record files...]
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIELDS = ("file", "build_id", "written_at", "sport", "kind", "market", "segment", "venue", "sigma_source", "tts",
          "seconds_to_start", "p", "price_prob", "fee", "fee_is_bound", "cost", "p_lb", "z", "sigma", "ev_net_pct",
          "ev_lb_pct", "eligible", "failed_gates", "board_suggested", "in_band", "g", "h", "bucket")
BUCKETS = ("A_no_raw_edge", "B_fee_eats", "C_haircut_eats", "D_qualifies")


def bucket(g: float, f: float, h: float) -> str:
    if g <= 0:
        return BUCKETS[0]
    if g <= f:
        return BUCKETS[1]
    if g <= f + h:
        return BUCKETS[2]
    return BUCKETS[3]


def _q(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(pct * (len(s) - 1) + 0.5))], 4)


def summarise(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    counts = collections.Counter(r["bucket"] for r in rows)
    g = [float(r["g"]) for r in rows]
    return {
        "n": n,
        "buckets": {b: [counts.get(b, 0), round(100.0 * counts.get(b, 0) / n, 1) if n else None] for b in BUCKETS},
        "g_pts": {"p10": _q(g, .1), "p50": _q(g, .5), "p90": _q(g, .9), "max": _q(g, 1.0)},
        "fee_pts_p50": _q([float(r["fee"]) for r in rows], .5),
        "haircut_pts_p50": _q([float(r["h"]) for r in rows], .5),
        "net_ev_pos": sum(1 for r in rows if float(r["g"]) > float(r["fee"])),
        "at_half_haircut": sum(1 for r in rows if float(r["g"]) > float(r["fee"]) + float(r["h"]) / 2),
    }


def candidate_rows(path: Path, root: Path, params: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The paper job's candidates for one record file, as rows. Mirrors `book_build` up to `select`; writes nothing."""
    from syndicate.features.shared import decision_policy_paper as dpp
    from syndicate.features.shared import decision_policy_v1 as dp
    from syndicate.features.shared import decision_record as drm
    from syndicate.features.shared import syndicate_fair_runtime as sfr

    doc = drm.read_records_file(path)
    if not doc:
        return [], {"file": path.name, "status": "unreadable"}
    build_id, written_at = str(doc.get("build_id") or ""), doc.get("written_at")
    selected_date = str(doc.get("selected_date") or "")
    decided = dpp._epoch(written_at)
    raw = doc.get("records") or []
    records = [drm.expand_record(r) for r in raw if isinstance(r, Mapping)
               and any(isinstance(p, Mapping) and p.get("role") == "venue" for p in r.get("prices") or [])]
    kinds: dict[str, set] = collections.defaultdict(set)
    for rec in records:
        if rec.identity.sport:
            kinds[rec.identity.sport].add(rec.identity.kind or "game")
    grid = dpp.load_grid(root, kinds, selected_date)
    rows: list[dict[str, Any]] = []
    qualifying: collections.Counter = collections.Counter()
    for rec in records:
        info = dpp.sigma_for_record(rec, grid, params, decided)
        for venue in dp.VENUES:
            c = dp.evaluate(rec, venue, str(written_at), info, params)
            if c is None:
                continue
            for s in dp.STRATEGIES:
                qualifying[s] += dp.qualifies(s, c)
            row = {k: getattr(c, k) for k in FIELDS if hasattr(c, k)}
            row.update(file=path.name, build_id=build_id, written_at=written_at, eligible=c.eligible,
                       failed_gates="|".join(c.failed_gates),
                       tts=sfr.tts_bucket(c.seconds_to_start) if c.seconds_to_start else None)
            if None not in (c.p, c.price_prob, c.fee, c.p_lb):
                row["g"], row["h"] = round(c.p - c.price_prob, 6), round(c.p - c.p_lb, 6)
                row["bucket"] = bucket(row["g"], c.fee, row["h"])
            rows.append(row)
    summary = {"file": path.name, "build_id": build_id, "written_at": written_at, "selected_date": selected_date,
               "records": len(raw), "venue_records": len(records), "candidates": len(rows),
               "eligible": sum(1 for r in rows if r["eligible"]), "qualifying": dict(qualifying)}
    return rows, summary


def report(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    elig = [r for r in rows if r["eligible"] and r.get("bucket")]
    out: dict[str, Any] = {"n_candidates": len(rows), "all_eligible": summarise(elig)}
    for key in ("venue", "sport", "kind", "sigma_source", "tts", "file"):
        groups: dict[str, list] = collections.defaultdict(list)
        for r in elig:
            groups[str(r.get(key))].append(r)
        out[f"by_{key}"] = {k: summarise(v) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))}
    combo: dict[str, list] = collections.defaultdict(list)
    for r in elig:
        combo[f"{r['sport']}|{r['venue']}|{r['kind']}"].append(r)
    out["by_sport_venue_kind"] = {k: summarise(v) for k, v in sorted(combo.items(), key=lambda kv: -len(kv[1]))}
    gates: collections.Counter = collections.Counter()
    for r in rows:
        gates.update(g for g in str(r.get("failed_gates") or "").split("|") if g)
    out["failed_gates_all_candidates"] = dict(gates.most_common())
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="record files (default: every one on disk)")
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    from syndicate.features.shared import decision_policy_v1 as dp
    from syndicate.features.shared import decision_record as drm
    from syndicate.features.shared.refresh_state_store import data_root

    root = args.data_root or data_root()
    params = dp.load_params()
    if not params.loaded:
        print(f"params not loaded: {params.error}", file=sys.stderr)
        return 2
    files = args.files or sorted(drm.records_dir(root).glob("*.json.gz"))
    rows: list[dict[str, Any]] = []
    per_file: list[dict[str, Any]] = []
    for path in files:
        file_rows, summary = candidate_rows(path, root, params)
        rows.extend(file_rows)
        per_file.append(summary)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "candidates.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in FIELDS})
    result = {"params_version": params.version, "files": per_file, **report(rows)}
    (args.out / "report.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"files": per_file, "all_eligible": result["all_eligible"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
