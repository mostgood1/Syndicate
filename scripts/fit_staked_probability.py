"""Fit the `staked_probability` blend weight per (sport, market, segment).

Pricing plane v1, P2 (`lane p2-sizer-blend`, 2026-09-08). The consumer is
`portfolio_commit.sizing_inputs_with_provenance`; the artifact is
`staked_probability_profile.PROFILE_RELATIVE_PATH`; the seam whose coefficient
this fits is `opportunity_signals.staked_probability`.

    py -3 scripts/fit_staked_probability.py --sport mlb                       # dry run, ledger
    py -3 scripts/fit_staked_probability.py --sport mlb --start 2026-08-22 --end 2026-09-07
    py -3 scripts/fit_staked_probability.py --sport mlb --rows-jsonl rows.jsonl --write
    py -3 scripts/fit_staked_probability.py --sport mlb --clv-enrich --json

WHAT IT FITS. For every settled row: ``fair = (ev_pct/100 + 1)/(profit + 1)``
and ``model = fair + model_edge_pct/100`` -- the sizer's OWN derivation,
imported, so the number fitted is the number staked. ``y`` is 1 for `won`, 0
for `lost`; a `push` is dropped by name (it is not a Bernoulli outcome). Per
cell, ``beta`` is chosen on a grid ``0.00 .. 1.00`` step 0.05 to minimise the
TRAIN Brier score of ``staked_probability(fair, model, beta=beta)``, and then
judged ONLY on the held-out rows.

THE SPLIT IS CHRONOLOGICAL. Rows are ordered by ``selected_date`` then
``submitted_at`` and cut at the date boundary at or after the 70th-percentile
row, so no date straddles the cut. A random split would let a game's own
outcome leak into its training fold through a correlated leg; `learnings.md`
forbids in-sample calibration promotion for the same reason.

THE FLOOR: 200 HELD-OUT ROWS PER CELL, PRE-REGISTERED. ROI needs ~2,300 bets
to separate a real edge from noise at the sizes this book runs; the Brier
score of a probability needs far fewer because every row contributes a
continuous residual rather than a single sign. 200 is the floor chosen here
BEFORE any fit was run, and it is a constant rather than a flag so a thin cell
cannot be argued past it on the day. Below it the cell is refused by name and
NOTHING is written for it.

THE WRITE RULE. A cell is written only when ``brier_fit < brier_beta0`` on the
held-out rows -- the blend must beat the MARKET ALONE out of sample, which is
the gate `staked_probability`'s docstring pre-registered. Brier at ``beta = 1``
(the raw model, which is what the sizer stakes today) is printed beside them so
the reader can see all three, but it is not the gate. A write REPLACES every
cell of the sport it fitted; it never merges a fresh cell beside a stale one for
the same sport, because two fits from different ledgers pooled into one
profile is exactly the cross-root pooling `learnings.md` forbids.

SOURCES. The paper/live order ledger (`execution_ledger`) is the only place a
settled OUTCOME lives today, so it is the default. `clv_join` rows carry no
outcome; ``--clv-enrich`` uses them the one way they help -- filling
`model_edge_pct`/`ev_pct` on ledger orders that lack them, joined by
`opening_key`. ``--rows-jsonl`` accepts any pre-joined source (the evaluation
ledger settles from 2026-09-09) with the same field names as a ledger order.

``--dry-run`` is the default. ``--write`` is explicit. Exit codes:
  0  at least one cell is writable (written only under --write)
  2  rows were found but no cell passed the floor and the write rule
  3  no usable rows at all
Nothing is written on any non-zero exit.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.calibration_profile_store import (  # noqa: E402
    load_versioned_profile,
    save_versioned_profile,
)
from syndicate.features.shared.opportunity_signals import staked_probability  # noqa: E402
from syndicate.features.shared.portfolio_commit import _net_profit_per_unit  # noqa: E402
from syndicate.features.shared.staked_probability_profile import (  # noqa: E402
    DEFAULT_PROFILE,
    BlendCell,
    StakedProbabilityProfile,
    cell_key,
    profile_path,
)

#: Pre-registered. See the module docstring for why it is a constant.
MIN_TEST_ROWS = 200
TRAIN_SHARE = 0.7
BETA_GRID: tuple[float, ...] = tuple(round(i * 0.05, 2) for i in range(0, 21))
SCORER = "portfolio_commit.additive_v1"

VERDICT_WRITE = "write"
VERDICT_FLOOR = "refused_n_test_below_floor"
VERDICT_NO_SPLIT = "refused_no_chronological_split"
VERDICT_NO_GAIN = "refused_does_not_beat_beta0"


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# ROWS
# ---------------------------------------------------------------------------


def derive_row(record: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """One settled record -> ``{cell, fair, model, y, date, at}``, or a named refusal.

    The derivation is the sizer's own (`portfolio_commit`), not a restatement.
    """
    outcome = str(record.get("outcome") or "").strip().lower()
    if outcome == "won":
        y = 1.0
    elif outcome == "lost":
        y = 0.0
    elif outcome == "push":
        return None, "push"
    else:
        return None, "unsettled"

    price = None
    for key in ("requested_price", "fill_price", "price"):
        price = _as_float(record.get(key))
        if price is not None:
            break
    if price is None:
        return None, "no_price"
    profit = _net_profit_per_unit(price)
    if profit is None:
        return None, "unusable_price"

    ev_pct = _as_float(record.get("ev_pct"))
    if ev_pct is None:
        return None, "no_ev_pct"
    fair = (ev_pct / 100.0 + 1.0) / (profit + 1.0)
    if not (0.0 < fair < 1.0):
        return None, "fair_out_of_range"

    model_edge_pct = _as_float(record.get("model_edge_pct"))
    if model_edge_pct is None:
        # No model view: the blend has nothing to weigh. These rows are the
        # market-fair book and are not evidence about beta.
        return None, "no_model_edge_pct"
    model = fair + model_edge_pct / 100.0
    if not (0.0 < model < 1.0):
        return None, "model_out_of_range"

    date = str(record.get("selected_date") or "").strip()
    if not date:
        return None, "no_selected_date"

    return (
        {
            "cell": cell_key(record.get("sport"), record.get("market"), record.get("segment")),
            "fair": fair,
            "model": model,
            "y": y,
            "date": date,
            "at": str(record.get("submitted_at") or ""),
        },
        None,
    )


def _in_range(date: str, start: str | None, end: str | None) -> bool:
    if start and date < start:
        return False
    if end and date > end:
        return False
    return True


def rows_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    sport: str,
    start: str | None,
    end: str | None,
    portfolio_book_only: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter + derive. Every drop is counted under a name."""
    from syndicate.features.shared.paper_settlement import BOOK_PORTFOLIO, book_of

    want = sport.strip().lower()
    rows: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}

    def _drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for record in records:
        if not isinstance(record, Mapping):
            _drop("not_a_mapping")
            continue
        if str(record.get("sport") or "").strip().lower() != want:
            _drop("other_sport")
            continue
        if portfolio_book_only and book_of(record) != BOOK_PORTFOLIO:
            # The venue-comparison shadow books re-price the same decision at
            # other venues; counting them would weight one outcome several times.
            _drop("not_portfolio_book")
            continue
        date = str(record.get("selected_date") or "").strip()
        if not _in_range(date, start, end):
            _drop("outside_date_range")
            continue
        row, reason = derive_row(record)
        if row is None:
            _drop(reason or "unknown")
            continue
        rows.append(row)
    return rows, dropped


def load_ledger_records() -> tuple[list[dict[str, Any]], str]:
    from syndicate.features.shared.execution_ledger import _ledger_path, _load

    return list(_load().get("orders") or []), str(_ledger_path())


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping):
                out.append(dict(payload))
    return out


def clv_enrich(records: list[dict[str, Any]], *, sport: str) -> dict[str, int]:
    """Fill `model_edge_pct`/`ev_pct` on ledger orders that lack them from the
    CLV opening rows, joined by `opening_key`. Mutates `records` in place and
    returns counts. Every failure is counted, never raised: an enrichment that
    cannot run leaves the row exactly as the ledger had it."""
    from syndicate.features.shared.clv_join import compute_clv_for_date

    counts = {"candidates": 0, "dates": 0, "enriched": 0, "no_opening_match": 0, "date_failed": 0}
    by_date: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if str(record.get("sport") or "").strip().lower() != sport.strip().lower():
            continue
        if _as_float(record.get("model_edge_pct")) is not None and _as_float(record.get("ev_pct")) is not None:
            continue
        key = record.get("opening_key")
        date = str(record.get("selected_date") or "").strip()
        if not (isinstance(key, str) and key and date):
            continue
        counts["candidates"] += 1
        by_date.setdefault(date, []).append(record)
    for date, group in sorted(by_date.items()):
        counts["dates"] += 1
        try:
            report = compute_clv_for_date(date, sport)
        except Exception as exc:  # noqa: BLE001
            counts["date_failed"] += 1
            print(f"[fit_staked_probability] clv_enrich date={date} failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        openings = {
            str(row.get("key")): row
            for row in (report or {}).get("rows") or ()
            if isinstance(row, Mapping) and row.get("key")
        }
        for record in group:
            opening = openings.get(str(record.get("opening_key")))
            if opening is None:
                counts["no_opening_match"] += 1
                continue
            if _as_float(record.get("model_edge_pct")) is None:
                record["model_edge_pct"] = opening.get("model_edge_pct")
            if _as_float(record.get("ev_pct")) is None:
                record["ev_pct"] = opening.get("ev_pct")
            counts["enriched"] += 1
    return counts


# ---------------------------------------------------------------------------
# FIT
# ---------------------------------------------------------------------------


def chronological_split(rows: Sequence[Mapping[str, Any]], *, train_share: float = TRAIN_SHARE) -> tuple[list, list]:
    """Cut at the date boundary at or after the `train_share` row. Never
    splits a date. Returns (train, test); train is empty when the cut lands on
    the first date, which the caller reports as `refused_no_chronological_split`."""
    ordered = sorted(rows, key=lambda r: (str(r["date"]), str(r.get("at") or "")))
    if not ordered:
        return [], []
    cut_index = int(len(ordered) * train_share)
    cut_index = min(max(cut_index, 0), len(ordered) - 1)
    cut_date = str(ordered[cut_index]["date"])
    train = [r for r in ordered if str(r["date"]) < cut_date]
    test = [r for r in ordered if str(r["date"]) >= cut_date]
    return train, test


def brier(rows: Sequence[Mapping[str, Any]], beta: float) -> float | None:
    """Mean squared error of the blended probability against the outcome."""
    total = 0.0
    n = 0
    for row in rows:
        p = staked_probability(row["fair"], row["model"], beta=beta)
        if p is None:
            continue
        total += (float(p) - float(row["y"])) ** 2
        n += 1
    return total / n if n else None


def fit_cell(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Grid-fit one cell and judge it out of sample. Never writes."""
    train, test = chronological_split(rows)
    out: dict[str, Any] = {
        "n_rows": len(rows),
        "n_train": len(train),
        "n_test": len(test),
        "beta_fit": None,
        "brier_train_beta0": None,
        "brier_train_fit": None,
        "brier_beta0": None,
        "brier_beta1": None,
        "brier_fit": None,
        "verdict": None,
    }
    if not train or not test:
        out["verdict"] = VERDICT_NO_SPLIT
        return out
    if len(test) < MIN_TEST_ROWS:
        out["verdict"] = VERDICT_FLOOR
        return out

    scored = [(brier(train, beta), beta) for beta in BETA_GRID]
    scored = [(score, beta) for score, beta in scored if score is not None]
    if not scored:
        out["verdict"] = VERDICT_NO_SPLIT
        return out
    # Smallest beta wins a tie: the market is the incumbent and the model has
    # to EARN its weight, not receive it on equal footing.
    best_score, best_beta = min(scored, key=lambda pair: (pair[0], pair[1]))
    out["beta_fit"] = best_beta
    out["brier_train_beta0"] = brier(train, 0.0)
    out["brier_train_fit"] = best_score
    out["brier_beta0"] = brier(test, 0.0)
    out["brier_beta1"] = brier(test, 1.0)
    out["brier_fit"] = brier(test, best_beta)
    if best_beta > 0.0 and out["brier_fit"] is not None and out["brier_beta0"] is not None and out["brier_fit"] < out["brier_beta0"]:
        out["verdict"] = VERDICT_WRITE
    else:
        out["verdict"] = VERDICT_NO_GAIN
    return out


def fit_all(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_cell: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_cell.setdefault(str(row["cell"]), []).append(row)
    return {cell: fit_cell(group) for cell, group in sorted(by_cell.items())}


# ---------------------------------------------------------------------------
# WRITE
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.5f}"
    return str(value)


def render_table(results: Mapping[str, Mapping[str, Any]]) -> str:
    header = f"{'cell':<40} {'n_train':>7} {'n_test':>6} {'beta':>5} {'B(0)':>8} {'B(1)':>8} {'B(fit)':>8}  verdict"
    lines = [header, "-" * len(header)]
    for cell, result in results.items():
        lines.append(
            f"{cell:<40} {result['n_train']:>7} {result['n_test']:>6} {_fmt(result['beta_fit']):>5} "
            f"{_fmt(result['brier_beta0']):>8} {_fmt(result['brier_beta1']):>8} {_fmt(result['brier_fit']):>8}  {result['verdict']}"
        )
    return "\n".join(lines)


def write_profile(
    *,
    sport: str,
    results: Mapping[str, Mapping[str, Any]],
    artifact_path: Path,
    fit_from: Mapping[str, Any],
) -> tuple[Path, str]:
    """Replace every cell of `sport` with the writable ones in `results`."""
    fitted_on = _utc_now()
    existing, _meta = load_versioned_profile(default_profile=DEFAULT_PROFILE, artifact_path=artifact_path)
    prefix = f"{sport.strip().lower()}|"
    kept = {key: dict(value) for key, value in existing.cells.items() if not str(key).startswith(prefix)}
    source = str(fit_from.get("source") or "")
    new_cells: dict[str, BlendCell] = {}
    for cell, result in results.items():
        if result.get("verdict") != VERDICT_WRITE:
            continue
        new_cells[cell] = BlendCell(
            beta=float(result["beta_fit"]),
            fitted_on=fitted_on,
            n_train=int(result["n_train"]),
            n_test=int(result["n_test"]),
            brier_beta0=float(result["brier_beta0"]),
            brier_fit=float(result["brier_fit"]),
            source=source,
        )
    version = f"staked_probability_v1@{fitted_on}"
    profile = StakedProbabilityProfile(cells=kept).with_cells(new_cells, version=version)
    save_versioned_profile(
        profile,
        artifact_path=artifact_path,
        version=version,
        fit_from={**dict(fit_from), "fitted_on": fitted_on, "cells_written": sorted(new_cells)},
    )
    return artifact_path, version


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sport", required=True, help="one sport slug; the fit is sport-scoped by design")
    parser.add_argument("--start", default=None, help="selected_date >= (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="selected_date <= (YYYY-MM-DD)")
    parser.add_argument("--rows-jsonl", default=None, help="pre-joined settled rows instead of the order ledger")
    parser.add_argument("--clv-enrich", action="store_true", help="fill missing model_edge_pct/ev_pct from clv_join openings")
    parser.add_argument("--profile-path", default=None, help="override the artifact path (default: staked_probability_profile.profile_path())")
    parser.add_argument("--json", action="store_true", help="print the per-cell results as JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="(default) fit and report, write nothing")
    mode.add_argument("--write", action="store_true", help="write the versioned profile for writable cells")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sport = str(args.sport).strip().lower()

    if args.rows_jsonl:
        records = load_jsonl_records(Path(args.rows_jsonl))
        source = f"jsonl:{args.rows_jsonl}"
        portfolio_book_only = False
    else:
        records, ledger_path = load_ledger_records()
        source = f"execution_ledger:{ledger_path}"
        portfolio_book_only = True

    enrich_counts: dict[str, int] | None = None
    if args.clv_enrich:
        enrich_counts = clv_enrich(records, sport=sport)
        print(f"[fit_staked_probability] clv_enrich {enrich_counts}", flush=True)

    rows, dropped = rows_from_records(
        records, sport=sport, start=args.start, end=args.end, portfolio_book_only=portfolio_book_only
    )
    print(
        f"[fit_staked_probability] sport={sport} source={source} records={len(records)} "
        f"usable_rows={len(rows)} dropped={dropped}",
        flush=True,
    )
    if not rows:
        print("[fit_staked_probability] NO USABLE ROWS -- nothing to fit, nothing written (exit 3)", flush=True)
        return 3

    results = fit_all(rows)
    print(render_table(results), flush=True)
    print(
        f"[fit_staked_probability] floor: n_test >= {MIN_TEST_ROWS} per cell (pre-registered); "
        f"write rule: brier_fit < brier_beta0 on held-out; split: chronological {TRAIN_SHARE:.0%} by date",
        flush=True,
    )
    if args.json:
        print(json.dumps({"sport": sport, "source": source, "dropped": dropped, "cells": results}, indent=2, sort_keys=True), flush=True)

    writable = [cell for cell, result in results.items() if result["verdict"] == VERDICT_WRITE]
    if not writable:
        print("[fit_staked_probability] NO CELL PASSED -- nothing written (exit 2)", flush=True)
        return 2

    if not args.write:
        print(f"[fit_staked_probability] DRY RUN -- {len(writable)} writable cell(s): {writable}. Re-run with --write.", flush=True)
        return 0

    target = Path(args.profile_path) if args.profile_path else profile_path()
    if target is None:
        print("[fit_staked_probability] no data root resolvable and no --profile-path; nothing written (exit 2)", flush=True)
        return 2
    fit_from = {
        "sport": sport,
        "start": args.start,
        "end": args.end,
        "source": source,
        "records": len(records),
        "usable_rows": len(rows),
        "dropped": dropped,
        "clv_enrich": enrich_counts,
        "min_test_rows": MIN_TEST_ROWS,
        "train_share": TRAIN_SHARE,
        "beta_grid_step": 0.05,
        "scorer": SCORER,
    }
    path, version = write_profile(sport=sport, results=results, artifact_path=target, fit_from=fit_from)
    print(f"[fit_staked_probability] WROTE {path} version={version} cells={writable}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
