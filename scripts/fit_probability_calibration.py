"""Fit per-(sport, market, segment) probability-calibration curves from SETTLED rows.

`lane pricing-plane-v1`, P5. Produces the versioned profile that
`syndicate/features/shared/probability_calibration.py` applies at the board's
pricing seam (`layer2_board._calibrate_model_edge`) when
`SYNDICATE_PRICING_CALIBRATION=on`.

WHAT IT REFUSES, AND WHY -- every rule here came from `learnings.md`:

  * IN-SAMPLE PROMOTION. The split is CHRONOLOGICAL (earliest `--train-frac`
    of each cell's rows train, the rest test) and a cell is written only when a
    method beats RAW on HELD-OUT Brier. A WNBA sigma refit once improved
    +21% in-sample and was worse held out; this harness cannot reproduce that.
  * POOLING ACROSS ARTIFACT ROOTS. `--root` is ONE explicit directory and rows
    that name a different `artifact_root` are refused, not merged.
  * POOLING ACROSS SCORER VERSIONS. Rows are grouped by `scorer_version`; a
    cell whose rows span more than one version is refused unless
    `--scorer-version` selects one.
  * THIN CELLS. `n_test >= --min-test` (200) or the cell is reported and not
    written.
  * `--dry-run` IS THE DEFAULT. `--write` is explicit, and even then only the
    winning cells are written; every cell is printed either way.

INPUTS -- two shapes, one row contract:

  1. The paper/live EXECUTION LEDGER, `<root>/intelligence/execution_ledger.json`
     (`execution_ledger.py`). Rows with `outcome in {won, lost}` and a
     `model_edge_pct` + `ev_pct` are usable; the model probability is recovered
     exactly the way the sizer recovers it (`portfolio_commit.sizing_inputs_from_row`):
         profit = net profit per unit at the fill price
         fair   = (ev_pct/100 + 1) / (profit + 1)
         p      = fair + model_edge_pct/100
     A push is neither outcome and is dropped.
  2. A JSONL of pre-joined settled rows (`--rows-jsonl`), one object per line:
         {"sport", "market", "segment", "model_probability", "outcome"|"y",
          "date", "scorer_version", "artifact_root"}
     This is the shape a clv_join / evaluation-ledger exporter writes; the
     harness does not reach into those ledgers itself because their record
     shape is owned by `intelligence_evaluation.py`, which another lane holds.

OUTPUT: `<data_root>/<sport>_source/calibration/probability_calibration.json`,
the `calibration_profile_store` envelope, cells merged onto any existing file
(a cell that did not win keeps whatever it had). Every written cell carries
`version`, `fitted_on`, `n`, `n_test`, `held_out_brier_raw`, `held_out_brier_cal`,
`held_out_logloss_raw`, `held_out_logloss_cal`, `scorer_version`, `artifact_root`.

Usage:
    python scripts/fit_probability_calibration.py --root reports --sport mlb
    python scripts/fit_probability_calibration.py --root reports --sport soccer --market h2h --start 2026-08-01 --end 2026-09-07
    python scripts/fit_probability_calibration.py --rows-jsonl settled.jsonl --root /data/root --sport wnba --write
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared import probability_calibration as pc  # noqa: E402

EXIT_OK = 0
EXIT_REFUSED = 2

UNVERSIONED = "unversioned"


# --------------------------------------------------------------------------
# Row loading
# --------------------------------------------------------------------------


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _net_profit_per_unit(american: float) -> float | None:
    if american == 0:
        return None
    return (american / 100.0) if american > 0 else (100.0 / abs(american))


def _outcome_to_y(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return 1 if float(value) >= 0.5 else 0
    token = str(value or "").strip().lower()
    if token in {"won", "win", "w", "1", "true", "yes"}:
        return 1
    if token in {"lost", "loss", "l", "0", "false", "no"}:
        return 0
    return None


def row_from_order(order: Mapping[str, Any], *, artifact_root: str) -> dict[str, Any] | None:
    """One execution-ledger order -> settled row, or None with no guessing."""
    y = _outcome_to_y(order.get("outcome"))
    if y is None:
        return None
    edge = _as_float(order.get("model_edge_pct"))
    ev = _as_float(order.get("ev_pct"))
    price = _as_float(order.get("fill_price"))
    if price is None:
        price = _as_float(order.get("requested_price"))
    if edge is None or ev is None or price is None:
        return None
    profit = _net_profit_per_unit(price)
    if profit is None:
        return None
    fair = (ev / 100.0 + 1.0) / (profit + 1.0)
    if not (0.0 < fair < 1.0):
        return None
    p = fair + edge / 100.0
    if not (0.0 < p < 1.0):
        return None
    return {
        "sport": str(order.get("sport") or "").strip().lower(),
        "market": str(order.get("market") or "").strip().lower(),
        "segment": str(order.get("segment") or "").strip().lower() or pc.ANY_SEGMENT,
        "model_probability": p,
        "y": y,
        "date": str(order.get("selected_date") or order.get("commence_time") or "")[:10],
        "scorer_version": str(order.get("scorer_version") or UNVERSIONED),
        "artifact_root": artifact_root,
    }


def load_execution_ledger_rows(root: Path) -> list[dict[str, Any]]:
    path = root / "intelligence" / "execution_ledger.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    orders = payload.get("orders") if isinstance(payload, Mapping) else None
    if not isinstance(orders, list):
        return []
    rows = []
    for order in orders:
        if isinstance(order, Mapping):
            row = row_from_order(order, artifact_root=str(root))
            if row is not None:
                rows.append(row)
    return rows


def load_jsonl_rows(path: Path, *, default_root: str) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, Mapping):
                continue
            p = _as_float(record.get("model_probability", record.get("p")))
            y = _outcome_to_y(record.get("y", record.get("outcome")))
            if p is None or y is None or not (0.0 < p < 1.0):
                continue
            rows.append(
                {
                    "sport": str(record.get("sport") or "").strip().lower(),
                    "market": str(record.get("market") or "").strip().lower(),
                    "segment": str(record.get("segment") or "").strip().lower() or pc.ANY_SEGMENT,
                    "model_probability": p,
                    "y": y,
                    "date": str(record.get("date") or record.get("selected_date") or "")[:10],
                    "scorer_version": str(record.get("scorer_version") or UNVERSIONED),
                    "artifact_root": str(record.get("artifact_root") or default_root),
                }
            )
    return rows


def filter_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    sport: str | None,
    market: str | None,
    segment: str | None,
    start: str | None,
    end: str | None,
) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if sport and row.get("sport") != sport:
            continue
        if market and row.get("market") != market:
            continue
        if segment and row.get("segment") != segment:
            continue
        date = str(row.get("date") or "")
        if start and date and date < start:
            continue
        if end and date and date > end:
            continue
        out.append(dict(row))
    return out


# --------------------------------------------------------------------------
# Fitting
# --------------------------------------------------------------------------


def fit_cell(
    rows: Sequence[Mapping[str, Any]],
    *,
    train_frac: float,
    min_test: int,
) -> dict[str, Any]:
    """Chronological split, fit both families on train, score all three on test."""
    ordered = sorted(rows, key=lambda r: (str(r.get("date") or ""), float(r["model_probability"])))
    n = len(ordered)
    n_train = int(n * train_frac)
    train, test = ordered[:n_train], ordered[n_train:]
    result: dict[str, Any] = {"n": n, "n_train": len(train), "n_test": len(test), "winner": "raw", "reason": None}
    if len(test) < min_test or not train:
        result["reason"] = f"n_test {len(test)} < {min_test}" if len(test) < min_test else "no training rows"
        return result
    p_train = [float(r["model_probability"]) for r in train]
    y_train = [int(r["y"]) for r in train]
    p_test = [float(r["model_probability"]) for r in test]
    y_test = [int(r["y"]) for r in test]

    a, b = pc.fit_affine_logit(p_train, y_train)
    xs, ys = pc.fit_isotonic(p_train, y_train)
    p_affine = [pc.apply_affine_logit(p, a, b) for p in p_test]
    p_iso = [pc.apply_isotonic(p, xs, ys) for p in p_test]

    scores = {
        "raw": {"brier": pc.brier(p_test, y_test), "logloss": pc.log_loss(p_test, y_test)},
        pc.METHOD_AFFINE_LOGIT: {"brier": pc.brier(p_affine, y_test), "logloss": pc.log_loss(p_affine, y_test)},
        pc.METHOD_ISOTONIC: {"brier": pc.brier(p_iso, y_test), "logloss": pc.log_loss(p_iso, y_test)},
    }
    result["scores"] = scores
    result["affine"] = {"a": a, "b": b}
    result["isotonic"] = {"x": xs, "y": ys}
    raw_brier = scores["raw"]["brier"]
    best_method, best_brier = "raw", raw_brier
    for method in (pc.METHOD_AFFINE_LOGIT, pc.METHOD_ISOTONIC):
        candidate = scores[method]["brier"]
        if candidate is not None and best_brier is not None and candidate < best_brier - 1e-12:
            best_method, best_brier = method, candidate
    result["winner"] = best_method
    if best_method == "raw":
        result["reason"] = "no method beat raw on held-out Brier"
    return result


def group_cells(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    cells: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cells[(str(row["sport"]), str(row["market"]), str(row["segment"]))].append(dict(row))
    return dict(cells)


def build_cell_entry(fit: Mapping[str, Any], *, version: str, fitted_on: str, scorer_version: str, artifact_root: str) -> dict[str, Any]:
    method = fit["winner"]
    entry: dict[str, Any] = {
        "method": method,
        "version": version,
        "fitted_on": fitted_on,
        "n": fit["n"],
        "n_train": fit["n_train"],
        "n_test": fit["n_test"],
        "held_out_brier_raw": fit["scores"]["raw"]["brier"],
        "held_out_brier_cal": fit["scores"][method]["brier"],
        "held_out_logloss_raw": fit["scores"]["raw"]["logloss"],
        "held_out_logloss_cal": fit["scores"][method]["logloss"],
        "scorer_version": scorer_version,
        "artifact_root": artifact_root,
    }
    if method == pc.METHOD_AFFINE_LOGIT:
        entry["a"] = fit["affine"]["a"]
        entry["b"] = fit["affine"]["b"]
    elif method == pc.METHOD_ISOTONIC:
        entry["x"] = fit["isotonic"]["x"]
        entry["y"] = fit["isotonic"]["y"]
    return entry


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{float(value):.5f}"


def run(
    rows: Sequence[Mapping[str, Any]],
    *,
    artifact_root: str,
    scorer_version: str | None,
    train_frac: float,
    min_test: int,
    write: bool,
    data_root: Path | None,
    version: str | None = None,
    out=sys.stdout,
) -> tuple[int, dict[str, Any]]:
    """Fit every cell, print the table, write the winners. Returns (exit, report)."""
    report: dict[str, Any] = {"cells": [], "written": [], "refused": []}
    roots = sorted({str(r.get("artifact_root") or "") for r in rows})
    if len(roots) > 1:
        msg = f"REFUSED: rows span {len(roots)} artifact roots {roots}; pass one root and fit per root"
        print(msg, file=out)
        report["refused"].append(msg)
        return EXIT_REFUSED, report
    if roots and roots[0] != artifact_root:
        msg = f"REFUSED: rows name artifact_root {roots[0]!r} but --root is {artifact_root!r}"
        print(msg, file=out)
        report["refused"].append(msg)
        return EXIT_REFUSED, report

    if scorer_version:
        rows = [r for r in rows if str(r.get("scorer_version")) == scorer_version]

    fitted_on = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    version = version or fitted_on
    winners_by_sport: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    header = f"{'sport':8} {'market':28} {'segment':10} {'ver':12} {'n':>6} {'n_test':>6} {'brier_raw':>10} {'brier_aff':>10} {'brier_iso':>10} {'ll_raw':>9} {'ll_aff':>9} {'ll_iso':>9}  winner"
    print(header, file=out)
    for (sport, market, segment), cell_rows in sorted(group_cells(rows).items()):
        versions = sorted({str(r.get("scorer_version")) for r in cell_rows})
        if len(versions) > 1:
            msg = f"{sport:8} {market:28} {segment:10} REFUSED: {len(versions)} scorer versions {versions}; pass --scorer-version"
            print(msg, file=out)
            report["refused"].append(msg)
            continue
        fit = fit_cell(cell_rows, train_frac=train_frac, min_test=min_test)
        scores = fit.get("scores") or {}
        line = (
            f"{sport:8} {market:28} {segment:10} {versions[0][:12]:12} {fit['n']:6d} {fit['n_test']:6d} "
            f"{_fmt((scores.get('raw') or {}).get('brier')):>10} "
            f"{_fmt((scores.get(pc.METHOD_AFFINE_LOGIT) or {}).get('brier')):>10} "
            f"{_fmt((scores.get(pc.METHOD_ISOTONIC) or {}).get('brier')):>10} "
            f"{_fmt((scores.get('raw') or {}).get('logloss')):>9} "
            f"{_fmt((scores.get(pc.METHOD_AFFINE_LOGIT) or {}).get('logloss')):>9} "
            f"{_fmt((scores.get(pc.METHOD_ISOTONIC) or {}).get('logloss')):>9}  {fit['winner']}"
        )
        if fit.get("reason"):
            line += f"  ({fit['reason']})"
        print(line, file=out)
        record = {"sport": sport, "market": market, "segment": segment, "scorer_version": versions[0], **fit}
        report["cells"].append(record)
        if fit["winner"] != "raw":
            winners_by_sport[sport][pc.cell_key(market, segment)] = build_cell_entry(
                fit, version=version, fitted_on=fitted_on, scorer_version=versions[0], artifact_root=artifact_root
            )

    if not write:
        print(f"dry-run: {sum(len(v) for v in winners_by_sport.values())} cell(s) would be written; pass --write", file=out)
        return EXIT_OK, report

    for sport, cells in winners_by_sport.items():
        existing, _meta = pc.load_profile(sport, data_root=data_root)
        merged = dict(existing.cells) if existing is not pc.IDENTITY_PROFILE else {}
        merged.update(cells)
        profile = pc.ProbabilityCalibrationProfile(version=version, sport=sport, cells=merged)
        path = pc.save_profile(
            profile,
            data_root=data_root,
            fit_from={"artifact_root": artifact_root, "scorer_version": scorer_version, "train_frac": train_frac, "min_test": min_test},
        )
        print(f"wrote {len(cells)} cell(s) -> {path}", file=out)
        report["written"].append({"sport": sport, "path": str(path), "cells": sorted(cells)})
    if not winners_by_sport:
        print("nothing to write: no cell beat raw on held-out with enough test rows", file=out)
    return EXIT_OK, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="ONE artifact/reports root (holds intelligence/execution_ledger.json). Never pooled.")
    parser.add_argument("--rows-jsonl", default=None, help="Pre-joined settled rows (JSONL) instead of / in addition to the ledger.")
    parser.add_argument("--sport", default=None)
    parser.add_argument("--market", default=None)
    parser.add_argument("--segment", default=None)
    parser.add_argument("--start", default=None, help="YYYY-MM-DD inclusive")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD inclusive")
    parser.add_argument("--scorer-version", default=None, help="Fit only rows from this scorer version.")
    parser.add_argument("--train-frac", type=float, default=0.7)
    parser.add_argument("--min-test", type=int, default=200)
    parser.add_argument("--version", default=None, help="Profile version label (default: fit timestamp).")
    parser.add_argument("--data-root", default=None, help="Where to write <sport>_source/calibration/ (default SYNDICATE_DATA_ROOT).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--write", action="store_true", default=False)
    parser.add_argument("--json", action="store_true", help="Print the report as JSON after the table.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    rows: list[dict[str, Any]] = load_execution_ledger_rows(root)
    if args.rows_jsonl:
        rows.extend(load_jsonl_rows(Path(args.rows_jsonl), default_root=str(root)))
    rows = filter_rows(
        rows,
        sport=(args.sport or "").strip().lower() or None,
        market=(args.market or "").strip().lower() or None,
        segment=(args.segment or "").strip().lower() or None,
        start=args.start,
        end=args.end,
    )
    print(f"rows: {len(rows)} usable settled rows under {root}", flush=True)
    if not rows:
        print("nothing to fit", flush=True)
        return EXIT_OK
    code, report = run(
        rows,
        artifact_root=str(root),
        scorer_version=args.scorer_version,
        train_frac=args.train_frac,
        min_test=args.min_test,
        write=bool(args.write),
        data_root=Path(args.data_root).expanduser().resolve() if args.data_root else None,
        version=args.version,
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
