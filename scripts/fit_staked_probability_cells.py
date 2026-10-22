"""Fit the `staked_probability` blend per venue x sport x market x segment x season-phase cell.

Lane `sim-stake-earned-profile` (2026-10-22). Pre-registration:
`.syndicate/findings_2026-10-22_sim_stake_earned_profile.md` s1, committed BEFORE `fit` was run.

`scripts/fit_staked_probability.py` fits per (sport, market, segment), pools every venue and
every season phase into one cell, and gates on a point estimate. This harness REUSES its row
derivation, split, Brier and beta grid (imported, so the number fitted is still the number
the sizer stakes) and changes three things:

  * THE CELL carries the venue (the order's `book`, the price the bet was taken at) and the
    season phase from `season_phase.season_phase(sport, selected_date)`. Phases are never
    pooled; an UNKNOWN phase is its own cell, reported and never written (the sizer cannot
    know which population such a cell would apply to, and unknown is not regular).
  * EVENT-CLUSTERED UNCERTAINTY. Rows on one event share an outcome driver, so every CI is a
    bootstrap over EVENTS: the held-out Brier delta resamples held-out events; beta's CI
    refits the grid on resampled training events.
  * THE WRITE GATE is the pre-registered one: beta > 0 is written only when the held-out
    ``Brier(beta0) - Brier(fit)`` has its event-bootstrap 95% lower bound above 0. A cell
    whose train fit picks beta 0 and whose held-out Brier(beta0) < Brier(beta1) is
    `market_only` (the base harness's rule, unchanged).

    py -3 scripts/fit_staked_probability_cells.py coverage                 # counts only, no outcome read
    py -3 scripts/fit_staked_probability_cells.py fit --json-out cells.json
    py -3 scripts/fit_staked_probability_cells.py fit --profile-out candidate.json

Nothing here writes the live profile path. `--profile-out` writes a CANDIDATE document in the
store's format; publishing it is a separate, user-approved step.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import fit_staked_probability as base  # noqa: E402
from syndicate.features.shared.season_phase import season_phase  # noqa: E402

#: Pre-registered (findings s1). Constants, not flags, for the same reason as the base floor.
MIN_TEST_ROWS = base.MIN_TEST_ROWS  # 200
MIN_TEST_EVENTS = 30
BOOTSTRAP_DRAWS = 1000
BOOTSTRAP_SEED = 20261022
UNKNOWN_PHASE = "unknown"
CELL_FIELDS = ("venue", "sport", "market", "segment", "phase")

#: Below the floor, numbers are still computed for the report -- never written -- from here.
DIAGNOSTIC_MIN_TEST_ROWS = 50
DIAGNOSTIC_MIN_TEST_EVENTS = 10
GRAIN_CELL = "cell"      # venue|sport|market|segment|phase -- the fitted grain
GRAIN_POOLED_VENUE = "pooled_venue"  # sport|market|segment|phase -- diagnostic only, phases still apart

VERDICT_WRITE = "write"
VERDICT_POINT_ONLY = "refused_point_win_ci_includes_zero"
VERDICT_UNKNOWN_PHASE = "refused_unknown_phase"
VERDICT_EVENT_FLOOR = "refused_n_test_events_below_floor"
WRITTEN_VERDICTS = (VERDICT_WRITE, base.VERDICT_MARKET_ONLY)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def event_of(record: Mapping[str, Any]) -> str:
    for key in ("event_id", "game_pk"):
        value = _norm(record.get(key))
        if value and value != "none":
            return value
    opening = str(record.get("opening_key") or "")
    for part in opening.split("|"):
        if part.startswith("event_id="):
            return part[len("event_id="):]
    return "order:" + str(record.get("idempotency_key") or id(record))


def cell_of(record: Mapping[str, Any]) -> str:
    sport = _norm(record.get("sport"))
    phase = season_phase(sport, record.get("selected_date")) or UNKNOWN_PHASE
    return "|".join((_norm(record.get("book")), sport, _norm(record.get("market")), _norm(record.get("segment")), phase))


def cell_parts(cell: str) -> dict[str, str]:
    return dict(zip(CELL_FIELDS, cell.split("|")))


def rows_from_records(records: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Portfolio-book settled rows with a model view, derived by the base harness."""
    from syndicate.features.shared.paper_settlement import BOOK_PORTFOLIO, book_of

    rows: list[dict[str, Any]] = []
    dropped: dict[str, int] = defaultdict(int)
    for record in records:
        if not isinstance(record, Mapping):
            dropped["not_a_mapping"] += 1
            continue
        if book_of(record) != BOOK_PORTFOLIO:
            dropped["not_portfolio_book"] += 1
            continue
        row, reason = base.derive_row(record)
        if row is None:
            dropped[reason or "unknown"] += 1
            continue
        row["cell"] = cell_of(record)
        row["event"] = event_of(record)
        row["stake"] = base._as_float(record.get("fill_stake_dollars")) or base._as_float(record.get("requested_stake_dollars")) or 0.0
        rows.append(row)
    return rows, dict(dropped)


def by_cell(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        out[str(row["cell"])].append(row)
    return dict(sorted(out.items()))


def coverage(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per cell: rows, events, dates, first/last date. Reads no outcome."""
    out = []
    for cell, group in by_cell(rows).items():
        dates = sorted({str(r["date"]) for r in group})
        out.append({
            "cell": cell,
            "rows": len(group),
            "events": len({r["event"] for r in group}),
            "dates": len(dates),
            "first": dates[0],
            "last": dates[-1],
        })
    return out


# ---------------------------------------------------------------------------
# FIT
# ---------------------------------------------------------------------------


def _by_event(rows: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["event"])].append(row)
    return [groups[key] for key in sorted(groups)]


def _resample(groups: Sequence[Sequence[Mapping[str, Any]]], rng: random.Random) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for _ in range(len(groups)):
        out.extend(groups[rng.randrange(len(groups))])
    return out


def best_beta(rows: Sequence[Mapping[str, Any]]) -> float | None:
    scored = [(base.brier(rows, beta), beta) for beta in base.BETA_GRID]
    scored = [(score, beta) for score, beta in scored if score is not None]
    if not scored:
        return None
    return min(scored, key=lambda pair: (pair[0], pair[1]))[1]


def _sq_err(rows: Sequence[Mapping[str, Any]], beta: float) -> list[float]:
    out = []
    for row in rows:
        p = base.staked_probability(row["fair"], row["model"], beta=beta)
        out.append((float(p) - float(row["y"])) ** 2 if p is not None else float("nan"))
    return out


def _quantiles(values: Sequence[float]) -> tuple[float | None, float | None]:
    clean = sorted(v for v in values if v == v)
    if not clean:
        return None, None
    lo = clean[int(0.025 * (len(clean) - 1))]
    hi = clean[int(round(0.975 * (len(clean) - 1)))]
    return lo, hi


def fit_cell(
    rows: Sequence[Mapping[str, Any]],
    *,
    phase: str,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
    diagnostic: bool = False,
) -> dict[str, Any]:
    train, test = base.chronological_split(rows)
    out: dict[str, Any] = {
        "n_rows": len(rows),
        "n_events": len({r["event"] for r in rows}),
        "n_train": len(train),
        "n_test": len(test),
        "n_train_events": len({r["event"] for r in train}),
        "n_test_events": len({r["event"] for r in test}),
        "train_dates": [train[0]["date"], train[-1]["date"]] if train else None,
        "test_dates": [test[0]["date"], test[-1]["date"]] if test else None,
        "beta_fit": None,
        "beta_ci": None,
        "brier_beta0": None,
        "brier_beta1": None,
        "brier_fit": None,
        "delta_fit": None,
        "delta_fit_ci": None,
        "delta_beta1": None,
        "delta_beta1_ci": None,
        "verdict": None,
    }
    if not train or not test:
        out["verdict"] = base.VERDICT_NO_SPLIT
        return out
    floor = None
    if len(test) < MIN_TEST_ROWS:
        floor = base.VERDICT_FLOOR
    elif out["n_test_events"] < MIN_TEST_EVENTS:
        floor = VERDICT_EVENT_FLOOR
    if floor is not None:
        out["verdict"] = floor
        # DIAGNOSTIC ONLY (findings s1.6): a below-floor cell's numbers are reported, NEVER written.
        if not diagnostic or len(test) < DIAGNOSTIC_MIN_TEST_ROWS or out["n_test_events"] < DIAGNOSTIC_MIN_TEST_EVENTS:
            return out
        out["diagnostic"] = True

    beta = best_beta(train)
    if beta is None:
        out["verdict"] = base.VERDICT_NO_SPLIT
        return out
    out["beta_fit"] = beta
    out["brier_beta0"] = base.brier(test, 0.0)
    out["brier_beta1"] = base.brier(test, 1.0)
    out["brier_fit"] = base.brier(test, beta)
    # Positive delta = the blend (or raw model) beats the market alone on held-out rows.
    out["delta_fit"] = out["brier_beta0"] - out["brier_fit"]
    out["delta_beta1"] = out["brier_beta0"] - out["brier_beta1"]

    rng = random.Random(seed)
    test_groups = _by_event(test)
    # Per-event (sum of squared-error differences, rows), so a draw is a cheap re-sum.
    ev_fit: list[tuple[float, float, int]] = []
    for group in test_groups:
        e0, ef, e1 = _sq_err(group, 0.0), _sq_err(group, beta), _sq_err(group, 1.0)
        ev_fit.append((sum(a - b for a, b in zip(e0, ef)), sum(a - b for a, b in zip(e0, e1)), len(group)))
    d_fit, d_one = [], []
    for _ in range(draws):
        sf = s1 = n = 0.0
        for _ in range(len(ev_fit)):
            a, b, k = ev_fit[rng.randrange(len(ev_fit))]
            sf += a
            s1 += b
            n += k
        d_fit.append(sf / n)
        d_one.append(s1 / n)
    out["delta_fit_ci"] = list(_quantiles(d_fit))
    out["delta_beta1_ci"] = list(_quantiles(d_one))

    train_groups = _by_event(train)
    betas = []
    for _ in range(max(1, draws // 4)):
        b = best_beta(_resample(train_groups, rng))
        if b is not None:
            betas.append(b)
    out["beta_ci"] = list(_quantiles(betas))

    if floor is not None:
        return out
    lo = out["delta_fit_ci"][0]
    if beta > 0.0 and out["delta_fit"] > 0.0:
        if phase == UNKNOWN_PHASE:
            out["verdict"] = VERDICT_UNKNOWN_PHASE
        elif lo is not None and lo > 0.0:
            out["verdict"] = VERDICT_WRITE
        else:
            out["verdict"] = VERDICT_POINT_ONLY
    elif beta == 0.0 and out["brier_beta0"] < out["brier_beta1"]:
        out["verdict"] = VERDICT_UNKNOWN_PHASE if phase == UNKNOWN_PHASE else base.VERDICT_MARKET_ONLY
    else:
        out["verdict"] = base.VERDICT_NO_GAIN
    return out


def pooled_venue_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Same rows re-keyed without the venue. Phases stay apart. Diagnostic only."""
    return [{**row, "cell": "|".join(["*"] + str(row["cell"]).split("|")[1:])} for row in rows]


def fit_all(rows: Sequence[Mapping[str, Any]], *, draws: int = BOOTSTRAP_DRAWS, diagnostic: bool = False) -> dict[str, dict[str, Any]]:
    return {
        cell: fit_cell(group, phase=cell_parts(cell)["phase"], draws=draws, diagnostic=diagnostic)
        for cell, group in by_cell(rows).items()
    }


def candidate_profile(results: Mapping[str, Mapping[str, Any]], *, fitted_on: str, source: str) -> dict[str, Any]:
    """The candidate document, in `calibration_profile_store`'s shape. Cell keys carry the
    venue and phase: `<venue>|<sport>|<market>|<segment>|<phase>` -- the sizer's reader keys
    `<sport>|<market>|<segment>` today, so this document is INERT until the reader learns the
    longer key (findings s5)."""
    cells = {}
    for cell, result in results.items():
        if result.get("verdict") not in WRITTEN_VERDICTS or result.get("diagnostic") or cell.startswith("*|"):
            continue
        market_only = result["verdict"] == base.VERDICT_MARKET_ONLY
        cells[cell] = {
            "beta": 0.0 if market_only else float(result["beta_fit"]),
            "market_only": market_only,
            "fitted_on": fitted_on,
            "n_train": result["n_train"],
            "n_test": result["n_test"],
            "n_test_events": result["n_test_events"],
            "brier_beta0": result["brier_beta0"],
            "brier_fit": result["brier_fit"],
            "delta_fit_ci": result["delta_fit_ci"],
            "beta_ci": result["beta_ci"],
            "source": source,
        }
    version = f"staked_probability_cells_v1@{fitted_on}"
    return {"version": version, "fields": {"cells": cells}, "fit_from": {"source": source, "fitted_on": fitted_on,
            "min_test_rows": MIN_TEST_ROWS, "min_test_events": MIN_TEST_EVENTS, "bootstrap_draws": BOOTSTRAP_DRAWS,
            "train_share": base.TRAIN_SHARE, "key": "|".join(CELL_FIELDS)}}


def _fmt(value: Any, spec: str = ".5f") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def render_fit(results: Mapping[str, Mapping[str, Any]]) -> str:
    header = (f"{'cell':<52} {'tr':>5} {'te':>5} {'teEv':>4} {'beta':>4} {'betaCI':>11} "
              f"{'B0':>7} {'Bfit':>7} {'dFit':>8} {'dFitCI':>19} {'dB1':>8}  verdict")
    lines = [header, "-" * len(header)]
    for cell, r in results.items():
        bci = r.get("beta_ci") or [None, None]
        dci = r.get("delta_fit_ci") or [None, None]
        lines.append(
            f"{cell:<52} {r['n_train']:>5} {r['n_test']:>5} {r['n_test_events']:>4} {_fmt(r['beta_fit'], '.2f'):>4} "
            f"{_fmt(bci[0], '.2f'):>5},{_fmt(bci[1], '.2f'):>5} {_fmt(r['brier_beta0']):>7} {_fmt(r['brier_fit']):>7} "
            f"{_fmt(r['delta_fit'], '+.5f'):>8} [{_fmt(dci[0], '+.5f')},{_fmt(dci[1], '+.5f')}] "
            f"{_fmt(r['delta_beta1'], '+.5f'):>8}  {r['verdict']}{' [DIAGNOSTIC]' if r.get('diagnostic') else ''}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("coverage", "fit"))
    parser.add_argument("--rows-jsonl", default=None, help="ledger orders as JSONL instead of execution_ledger.full_history_orders()")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--profile-out", default=None, help="write the CANDIDATE profile document here (never the live path)")
    parser.add_argument("--draws", type=int, default=BOOTSTRAP_DRAWS)
    parser.add_argument("--grain", choices=(GRAIN_CELL, GRAIN_POOLED_VENUE), default=GRAIN_CELL,
                        help="pooled_venue is DIAGNOSTIC: never written to a profile")
    parser.add_argument("--diagnostic", action="store_true",
                        help=f"also report below-floor cells with n_test >= {DIAGNOSTIC_MIN_TEST_ROWS} (never written)")
    args = parser.parse_args(argv)

    if args.rows_jsonl:
        records = base.load_jsonl_records(Path(args.rows_jsonl))
        source = f"jsonl:{args.rows_jsonl}"
    else:
        # findings s7: `read_json_file` turns a FAILED keyvalue read (e.g. an interpreter with no
        # `redis`) into an empty live document, and `full_history_orders()` then returns the archive
        # alone -- a fit that looks complete and is missing the newest ~3,000 orders. Refuse instead.
        from syndicate.features.shared.execution_ledger import _ledger_path
        from syndicate.features.shared.refresh_state_store import read_json_file_result

        _payload, read_ok = read_json_file_result(_ledger_path())
        if not read_ok:
            print("[fit_staked_probability_cells] LEDGER READ FAILED (live document unreadable; not an empty "
                  "ledger) -- refusing to fit the archive alone (exit 4)", flush=True)
            return 4
        records, ledger_path = base.load_ledger_records()
        source = f"execution_ledger:{ledger_path}"
    rows, dropped = rows_from_records(records)
    print(f"[fit_staked_probability_cells] source={source} records={len(records)} usable_rows={len(rows)} "
          f"events={len({r['event'] for r in rows})} dropped={dropped}", flush=True)
    if not rows:
        return 3

    if args.command == "coverage":
        if args.grain == GRAIN_POOLED_VENUE:
            rows = pooled_venue_rows(rows)
        table = coverage(rows)
        print(f"{'cell':<52} {'rows':>5} {'events':>6} {'dates':>5}  first..last")
        for c in table:
            print(f"{c['cell']:<52} {c['rows']:>5} {c['events']:>6} {c['dates']:>5}  {c['first']}..{c['last']}")
        if args.json_out:
            Path(args.json_out).write_text(json.dumps({"source": source, "dropped": dropped, "cells": table}, indent=2), encoding="utf-8")
        return 0

    if args.grain == GRAIN_POOLED_VENUE:
        rows = pooled_venue_rows(rows)
    results = fit_all(rows, draws=args.draws, diagnostic=args.diagnostic)
    if args.diagnostic:
        results = {c: r for c, r in results.items() if r.get("beta_fit") is not None}
    print(render_fit(results), flush=True)
    verdicts: dict[str, int] = defaultdict(int)
    for r in results.values():
        verdicts[r["verdict"]] += 1
    print(f"[fit_staked_probability_cells] verdicts={dict(verdicts)}", flush=True)
    fitted_on = base._utc_now()
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"source": source, "fitted_on": fitted_on, "dropped": dropped,
                                                   "cells": results}, indent=2, sort_keys=True), encoding="utf-8")
    if args.profile_out and args.grain == GRAIN_CELL:
        doc = candidate_profile(results, fitted_on=fitted_on, source=source)
        Path(args.profile_out).write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        print(f"[fit_staked_probability_cells] candidate profile -> {args.profile_out} "
              f"cells={sorted(doc['fields']['cells'])}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
