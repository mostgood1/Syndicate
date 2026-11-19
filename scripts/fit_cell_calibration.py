"""Fit and grade the per-cell calibration table (todo #847, lane `cell-calibration-847`).

Read-only on whatever state file it is given (copy the fleet's out first; never point it at a live file that a
job writes). The rule it fits is `syndicate.features.shared.cell_calibration`; the pre-registration it grades is
`.syndicate/findings_2026-11-18_cell_calibration.md` §1.3.

    py -3 scripts/fit_cell_calibration.py fit   --state STATE.json --today 2026-11-18 [--out TABLE.json]
    py -3 scripts/fit_cell_calibration.py grade --state STATE.json --fit-today 2026-11-11 --from 2026-11-11 --to 2026-11-17
    py -3 scripts/fit_cell_calibration.py grade --state STATE.json --table FROZEN.json --from 2026-11-19 --to 2026-11-25
        (H-F: grade a FROZEN table's k exactly, no refit -- the state drops games older than 35 days and late-graded
        games arrive, so a refit on a later state is not the table that was frozen)
    py -3 scripts/fit_cell_calibration.py rail  --state STATE.json --fit-today 2026-11-15 --flags C_rail_rows.jsonl \
        --from 2026-11-15 --to 2026-11-17

`--today` / `--fit-today` is the first date NOT in the fit: the window is the optimizer's 28 days before it.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared import cell_calibration as cc  # noqa: E402
from syndicate.features.shared import daily_optimizer as opt  # noqa: E402

RESAMPLES = 2000
SEED = 20261118
RAIL_MIN_PP = 3.0
GATE_MIN_FLAGS = 30
CELL_MIN_GAMES = 20


def load_state(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fit(state: Mapping[str, Any], today: str, *, resamples: int) -> dict[str, Any]:
    games = opt.window_games(state, today)
    return cc.fit_table(games, now=datetime.now(timezone.utc), today=today, resamples=resamples)


def _boot(items: Sequence[Any], stat: Callable[[Sequence[Any]], float | None], *, seed: int,
          resamples: int = RESAMPLES) -> list[float] | None:
    rng = random.Random(seed)
    n = len(items)
    if n < 2:
        return None
    out = []
    for _ in range(resamples):
        value = stat([items[rng.randrange(n)] for _ in range(n)])
        if value is not None:
            out.append(value)
    out.sort()
    if not out:
        return None
    return [out[int(0.025 * len(out))], out[min(len(out) - 1, int(0.975 * len(out)))]]


def _variants(table: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    served = {cell: float(e["k"]) for cell, e in table["cells"].items()}
    if not table.get("diagnostics"):
        return {"served": served}  # a frozen table: its own k only
    diag = {d["cell"]: d for d in table["diagnostics"]}

    def clip(v: Any) -> float | None:
        return None if v is None else min(1.0, max(cc.K_FLOOR, float(v)))

    out = {"served": served, "overlay_today": {}, "post_mean": {}, "unpooled_ci_upper": {}}
    for cell in served:
        d = diag[cell]
        if d.get("optimizer_factor") is not None:
            out["overlay_today"][cell] = float(d["optimizer_factor"])
        if d.get("post_mean") is not None:
            out["post_mean"][cell] = clip(d["post_mean"])
        if d.get("ci95"):
            out["unpooled_ci_upper"][cell] = clip(d["ci95"][1])
    return out


def grade(state: Mapping[str, Any], table: Mapping[str, Any], date_from: str, date_to: str) -> dict[str, Any]:
    held = [{**g, "key": k} for k, g in sorted(state["games"].items())
            if date_from <= str(g.get("date") or "") <= date_to]
    variants = _variants(table)
    result: dict[str, Any] = {"held_out": {"from": date_from, "to": date_to, "games": len(held),
                                           "dates": len({g["date"] for g in held})}}
    for name, ks in variants.items():
        per_game = []
        per_cell: dict[str, list[list[float]]] = {}
        for game in held:
            parts = cc.held_out_brier([game], ks)
            if parts:
                per_game.append([(cell, r, d) for cell, vals in parts.items() for r, d in vals])
                for cell, vals in parts.items():
                    per_cell.setdefault(cell, []).extend(vals)

        def pooled(items: Sequence[Sequence[tuple[str, float, float]]]) -> float | None:
            rows = sum(r for g in items for _, r, _ in g)
            return (sum(d for g in items for _, _, d in g) / rows) if rows else None

        point = pooled(per_game)
        ci = _boot(per_game, pooled, seed=SEED + len(name))
        cells_out = {}
        for cell, vals in sorted(per_cell.items()):
            rows = sum(v[0] for v in vals)
            cells_out[cell] = {"k": round(ks[cell], 4), "games": len(vals), "rows": int(rows),
                               "d_brier_per_row": round(sum(v[1] for v in vals) / rows, 6) if rows else None}
        eligible = [c for c in cells_out.values() if c["games"] >= CELL_MIN_GAMES]
        better = sum(1 for c in eligible if (c["d_brier_per_row"] or 0) < 0)
        result[name] = {"cells": len(ks), "cells_with_held_out": len(cells_out), "games": len(per_game),
                        "rows": int(sum(c["rows"] for c in cells_out.values())),
                        "d_brier_per_row": round(point, 6) if point is not None else None,
                        "ci95": [round(v, 6) for v in ci] if ci else None,
                        "eligible_cells": len(eligible), "eligible_cells_better": better,
                        "per_cell": cells_out}
    s = result["served"]
    s["pass"] = bool(s["ci95"] and s["ci95"][1] < 0 and s["eligible_cells"]
                     and s["eligible_cells_better"] * 3 >= 2 * s["eligible_cells"])
    return result


def _ll(y: int, p: float) -> float:
    p = min(1 - 1e-9, max(1e-9, p))
    return math.log(p) if y else math.log(1.0 - p)


def rail(table: Mapping[str, Any], flags_path: str, date_from: str, date_to: str) -> dict[str, Any]:
    ks = {cell: float(e["k"]) for cell, e in table["cells"].items()}
    flags = []
    for line in Path(flags_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("g") not in ("win", "loss") or not (date_from <= str(r.get("day") or "") <= date_to):
            continue
        cell = f"{r['sport']}|{r['market']}|{r.get('segment') or 'full'}|live"
        k = ks.get(cell)
        p_raw, fair = float(r["model"]), float(r["fair"])
        p_cal = cc.calibrate(p_raw, fair, k) if k is not None else p_raw
        y = 1 if r["g"] == "win" else 0
        flags.append({"chip": r["chip"], "day": r["day"], "cell": cell, "k": k, "y": y, "fair": fair,
                      "p_raw": p_raw, "p_cal": p_cal, "gain": _ll(y, p_cal) - _ll(y, p_raw),
                      "kept": (p_cal - fair) * 100.0 >= RAIL_MIN_PP})
    by_chip: dict[str, list[dict[str, Any]]] = {}
    for f in flags:
        by_chip.setdefault(f["chip"], []).append(f)
    clusters = list(by_chip.values())

    def mean_gain(items: Sequence[Sequence[Mapping[str, Any]]]) -> float | None:
        n = sum(len(c) for c in items)
        return sum(f["gain"] for c in items for f in c) / n if n else None

    def hit_minus(field: str, subset: Callable[[Mapping[str, Any]], bool]) -> dict[str, Any]:
        chosen = [[f for f in c if subset(f)] for c in clusters]
        chosen = [c for c in chosen if c]
        n = sum(len(c) for c in chosen)

        def stat(items: Sequence[Sequence[Mapping[str, Any]]]) -> float | None:
            m = sum(len(c) for c in items)
            return 100.0 * sum(f["y"] - f[field] for c in items for f in c) / m if m else None

        point = stat(chosen)
        ci = _boot(chosen, stat, seed=SEED + 7)
        return {"flags": n, "games": len(chosen), "pp": round(point, 2) if point is not None else None,
                "ci95": [round(v, 2) for v in ci] if ci else None}

    gain = mean_gain(clusters)
    gain_ci = _boot(clusters, mean_gain, seed=SEED + 3)
    per_cell: dict[str, dict[str, Any]] = {}
    for f in flags:
        c = per_cell.setdefault(f["cell"], {"k": f["k"], "flags": 0, "kept": 0, "gain_sum": 0.0})
        c["flags"] += 1
        c["kept"] += 1 if f["kept"] else 0
        c["gain_sum"] += f["gain"]
    for c in per_cell.values():
        c["gain_per_flag"] = round(c.pop("gain_sum") / c["flags"], 5)
    gates = [cell for cell, c in per_cell.items()
             if c["k"] is not None and c["flags"] >= GATE_MIN_FLAGS and c["kept"] == 0]
    by_day: dict[str, dict[str, int]] = {}
    for f in flags:
        d = by_day.setdefault(f["day"], {"flags": 0, "kept": 0})
        d["flags"] += 1
        d["kept"] += 1 if f["kept"] else 0
    out = {
        "flags": len(flags), "games": len(clusters), "dates": len(by_day), "by_day": by_day,
        "served_cells": sorted(ks),
        "ll_gain_per_flag": round(gain, 5) if gain is not None else None,
        "ll_gain_ci95": [round(v, 5) for v in gain_ci] if gain_ci else None,
        "kept": sum(1 for f in flags if f["kept"]),
        "kept_hit_minus_cal": hit_minus("p_cal", lambda f: f["kept"]),
        "kept_hit_minus_fair": hit_minus("fair", lambda f: f["kept"]),
        "all_hit_minus_raw": hit_minus("p_raw", lambda f: True),
        "all_hit_minus_cal": hit_minus("p_cal", lambda f: True),
        "per_cell": dict(sorted(per_cell.items(), key=lambda kv: -kv[1]["flags"])),
        "gates": gates,
    }
    out["pass"] = bool(out["ll_gain_ci95"] and out["ll_gain_ci95"][0] > 0 and not gates)
    return out


def summarize_table(table: Mapping[str, Any]) -> str:
    lines = [f"window {table['window']}  served cells {len(table['cells'])}"]
    for cell, e in sorted(table["cells"].items()):
        lines.append(f"  {cell:45s} k {e['k']:.3f}  w {e['w']}  ci {e['ci95']}  post {e['post_mean']}±{e['post_sd']}"
                     f"  grp {e['group_w']}  tau2 {e['tau2']}  overlay {e['optimizer_factor']}  "
                     f"{e['games']}g/{e['dates']}d/{e['rows']}r")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_fit = sub.add_parser("fit")
    p_fit.add_argument("--state", required=True)
    p_fit.add_argument("--today", required=True)
    p_fit.add_argument("--out")
    p_grade = sub.add_parser("grade")
    p_grade.add_argument("--state", required=True)
    p_grade.add_argument("--fit-today", help="refit on the window before this date")
    p_grade.add_argument("--table", help="a FROZEN table JSON ({'cells': {cell: {'k': ...}}}); grades its k exactly")
    p_grade.add_argument("--from", dest="date_from", required=True)
    p_grade.add_argument("--to", dest="date_to", required=True)
    p_rail = sub.add_parser("rail")
    p_rail.add_argument("--state", required=True)
    p_rail.add_argument("--fit-today", required=True)
    p_rail.add_argument("--flags", required=True)
    p_rail.add_argument("--from", dest="date_from", required=True)
    p_rail.add_argument("--to", dest="date_to", required=True)
    for p in (p_fit, p_grade, p_rail):
        p.add_argument("--resamples", type=int, default=opt.RESAMPLES)
        p.add_argument("--json-out")
    args = parser.parse_args(argv)
    state = load_state(args.state)
    if args.cmd == "fit":
        table = fit(state, args.today, resamples=args.resamples)
        print(summarize_table(table))
        if args.out:
            Path(args.out).write_text(json.dumps(table, indent=1, sort_keys=True), encoding="utf-8")
        payload: Any = table
    else:
        if args.cmd == "grade" and getattr(args, "table", None):
            frozen = json.loads(Path(args.table).read_text(encoding="utf-8"))
            table = {"cells": frozen["cells"], "diagnostics": [], "window": frozen.get("window")}
            print(f"frozen table {args.table}: {len(table['cells'])} cells, window {table['window']}")
        elif getattr(args, "fit_today", None):
            table = fit(state, args.fit_today, resamples=args.resamples)
            print(summarize_table(table))
        else:
            parser.error("grade needs --table or --fit-today; rail needs --fit-today")
        if args.cmd == "grade":
            payload = {"table_window": table["window"], "grade": grade(state, table, args.date_from, args.date_to)}
        else:
            payload = {"table_window": table["window"],
                       "rail": rail(table, args.flags, args.date_from, args.date_to)}
        printable = json.loads(json.dumps(payload))
        for block in printable.values():
            if isinstance(block, dict):
                for v in block.values():
                    if isinstance(v, dict) and "per_cell" in v and len(v["per_cell"]) > 40:
                        v["per_cell"] = f"<{len(v['per_cell'])} cells; see --json-out>"
        print(json.dumps(printable, indent=1))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
