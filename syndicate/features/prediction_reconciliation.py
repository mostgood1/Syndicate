"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Reconciles predictions with outcomes and writes reconciliation summaries.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.prediction_ledger import load_all_predictions
from syndicate.features.prediction_ledger import record_result


logger = logging.getLogger(__name__)


RECONCILIATION_PATTERNS = (
    "recon_props_{date}.csv",
    "recon_games_{date}.csv",
    "props_actuals_{date}.csv",
    "game_results_{date}.csv",
    "game_results_{date}.json",
    "closing_lines_{date}.csv",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _prediction_date(prediction: Mapping[str, Any]) -> str | None:
    features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    for key in ("selected_date", "date", "game_date"):
        value = str(features.get(key) or "").strip()
        if len(value) >= 10:
            return value[:10]
    timestamp = str(prediction.get("timestamp") or "").strip()
    if len(timestamp) >= 10:
        return timestamp[:10]
    return None


def _prediction_keys(prediction: Mapping[str, Any]) -> set[str]:
    keys = {
        _normalize_text(prediction.get("sport")),
        _normalize_text(prediction.get("market")),
        _normalize_text(prediction.get("selection")),
    }
    features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    for key in ("event_id", "game_id", "player_name", "player", "team", "name", "market_key", "line"):
        keys.add(_normalize_text(features.get(key)))
    return {item for item in keys if item}


def _row_keys(row: Mapping[str, Any]) -> set[str]:
    keys = {
        _normalize_text(row.get("sport")),
        _normalize_text(row.get("market")),
        _normalize_text(row.get("selection")),
        _normalize_text(row.get("player")),
        _normalize_text(row.get("name")),
        _normalize_text(row.get("team")),
    }
    return {item for item in keys if item}


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "results", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _walk_for_names(root: Path, names: Sequence[str]) -> list[list[Path]]:
    """ONE walk of `root`, returning every file named in `names`, per name.

    This replaced one `root.rglob(name)` per name. On Render the root is the
    whole persistent disk (48,816 directories on 2026-09-18), and each rglob is
    a full walk plus a stat of every directory. Six patterns, called twice per
    date across 14 dates, came to 168 walks and a ~23 min autorun that runs
    INLINE in refresh-worker's main loop, so no book-grid tick happens while it
    runs (lane `reconciliation-disk-walks`).

    SAME PATHS, SAME ORDER as rglob on CPython 3.11 (`render.yaml` pins
    3.11.9), because the first matching row wins in `_match_result_row`, so the
    ORDER of files decides which of two conflicting rows settles a
    prediction. rglob visits a directory before its children, and the children
    in `os.scandir` order. It does not descend into symlinked directories. It
    yields `<dir>/<name>` wherever that exists, and the caller then keeps
    `is_file()`. This visits the same directories in the same pre-order and
    checks every name against each directory's listing, so N names cost one
    walk. `tests/test_reconciliation_disk_walks.py` holds a frozen copy of the
    rglob version and compares the two.
    """
    hits: list[list[Path]] = [[] for _ in names]
    wanted = {os.path.normcase(name): index for index, name in enumerate(names)}
    stack: list[Path] = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except PermissionError:
            # rglob could still stat `<dir>/<name>` inside an unlistable
            # directory; keep that answer rather than silently narrowing it.
            for index, name in enumerate(names):
                candidate = directory / name
                if candidate.is_file():
                    hits[index].append(candidate)
            continue
        subdirectories: list[Path] = []
        for entry in entries:
            index = wanted.get(os.path.normcase(entry.name))
            if index is not None:
                try:
                    entry_is_file = entry.is_file()
                except OSError:
                    entry_is_file = False
                if entry_is_file:
                    # The pattern's own spelling, as rglob yields it.
                    hits[index].append(directory / names[index])
            try:
                entry_is_dir = entry.is_dir()
            except OSError:
                entry_is_dir = False
            if entry_is_dir and not entry.is_symlink():
                subdirectories.append(directory / entry.name)
        # Pushed reversed so they pop in scandir order: a pre-order walk.
        stack.extend(reversed(subdirectories))
    return hits


def _candidate_result_paths(date_value: str, roots: Sequence[Path]) -> list[Path]:
    names = [pattern.format(date=date_value) for pattern in RECONCILIATION_PATTERNS]
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        # Pattern-major within a root, as the per-pattern rglob loop was.
        for per_name in _walk_for_names(root, names):
            paths.extend(per_name)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _result_rows_from_paths(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """Rows from `_candidate_result_paths`' files, in that order.

    Takes the paths rather than re-deriving them: the caller also reports the
    file list, and deriving it twice was a second full-disk walk per date.
    """
    rows: list[dict[str, Any]] = []
    for path in paths:
        if path.suffix.lower() == ".csv":
            rows.extend(_load_csv_rows(path))
        elif path.suffix.lower() == ".json":
            rows.extend(_load_json_rows(path))
    return rows


def _row_outcome(row: Mapping[str, Any], prediction: Mapping[str, Any]) -> str | None:
    explicit = _normalize_text(row.get("result") or row.get("outcome") or row.get("grade"))
    if explicit in {"win", "loss", "push", "void"}:
        return explicit

    actual_value = row.get("actual")
    line_value = row.get("closing_line") or row.get("line") or row.get("market_line")
    if actual_value is None or line_value is None:
        return None

    try:
        actual = float(str(actual_value).replace(",", ""))
        line = float(str(line_value).replace(",", ""))
    except Exception:
        return None

    # The wagered side lives in features_snapshot.pick for bets logged since
    # the bet-slip write-path fix (portfolio_bets_api) -- `prediction.
    # selection` is the player's name for a straight prop bet, not the side,
    # so it never carries over/under text on its own. Legacy predictions
    # (no features_snapshot.pick) fall through to the old selection-text
    # heuristic, which still works for any prediction whose selection text
    # itself happens to be "Over 4.5"/"Under 4.5"-shaped.
    features_snapshot = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    pick_text = _normalize_text(features_snapshot.get("pick"))
    selection_text = pick_text or _normalize_text(prediction.get("selection"))
    if "under" in selection_text:
        if actual < line:
            return "win"
        if actual > line:
            return "loss"
        return "push"
    if "over" in selection_text or selection_text.endswith("+"):
        if actual > line:
            return "win"
        if actual < line:
            return "loss"
        return "push"
    return None


def _row_original_line(prediction: Mapping[str, Any], row: Mapping[str, Any]) -> Any:
    features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    for key in ("original_line", "line", "market_line", "prop_line"):
        value = features.get(key)
        if value is not None and str(value).strip() != "":
            return value
    for key in ("original_line", "line", "market_line", "prop_line"):
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _row_closing_line(row: Mapping[str, Any]) -> Any:
    for key in ("closing_line", "closing", "close_line", "line"):
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _row_closing_price(row: Mapping[str, Any]) -> Any:
    """The closing PRICE, distinct from the closing line.

    Line CLV is undefined for moneyline -- there is no line -- so on a ledger of
    moneylines and parlays it is null for almost everything (measured on
    production 2026-08-06: avg_clv null across the board). Price CLV is defined
    for every bet that has a price, which is all of them.
    """
    for key in ("closing_price", "closing_odds", "close_price", "price", "odds"):
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _prediction_original_price(prediction: Mapping[str, Any]) -> Any:
    """The price we actually struck at.

    Prefers the #213 bet-time quote, which records the book and the price
    together, and falls back to the bare `odds` column for predictions logged
    before that existed. Returns None rather than guessing when neither is
    present -- an unknown CLV must stay distinguishable from a zero one.
    """
    quote = prediction.get("quote") if isinstance(prediction.get("quote"), Mapping) else None
    if quote is not None and quote.get("price") is not None:
        return quote.get("price")
    odds = prediction.get("odds")
    return odds if odds is not None and str(odds).strip() != "" else None


def _american_profit(odds: Any, stake: float = 1.0) -> float | None:
    try:
        value = float(str(odds).replace(",", ""))
    except Exception:
        return None
    if value == 0:
        return None
    if value > 0:
        return round(stake * (value / 100.0), 4)
    return round(stake * (100.0 / abs(value)), 4)


def _row_pnl(row: Mapping[str, Any], outcome: str | None, prediction: Mapping[str, Any]) -> float | None:
    for key in ("pnl", "profit", "profit_u", "payout"):
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            try:
                return round(float(str(value).replace(",", "")), 4)
            except Exception:
                continue

    if outcome not in {"win", "loss", "push", "void"}:
        return None

    stake = 1.0
    stake_value = row.get("stake") or row.get("risk") or row.get("wager")
    if stake_value is not None and str(stake_value).strip() != "":
        try:
            stake = float(str(stake_value).replace(",", ""))
        except Exception:
            stake = 1.0

    if outcome in {"push", "void"}:
        return 0.0

    odds = prediction.get("odds")
    if odds is None:
        odds = row.get("odds") or row.get("price")
    if odds is None:
        return -round(stake, 4) if outcome == "loss" else round(stake, 4)

    profit = _american_profit(odds, stake=stake)
    if profit is None:
        return -round(stake, 4) if outcome == "loss" else round(stake, 4)
    return profit if outcome == "win" else -round(stake, 4)


KeyedResultRow = tuple[Mapping[str, Any], set[str], str]


def _keyed_result_rows(rows: Iterable[Any]) -> list[KeyedResultRow]:
    """Each result row with its match keys and normalised market, computed ONCE per date.

    `_match_result_row` used to recompute both for every (prediction, row)
    pair: 11,201 closing-line rows on 2026-09-18, scanned once per unsettled
    prediction. Non-mapping rows are dropped here, where the matcher used to
    skip them.
    """
    keyed: list[KeyedResultRow] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        keyed.append((row, _row_keys(row), _normalize_text(row.get("market"))))
    return keyed


def _match_result_row(prediction: Mapping[str, Any], keyed_rows: Iterable[KeyedResultRow]) -> Mapping[str, Any] | None:
    """The FIRST row that shares a key with the prediction and does not name a different market."""
    prediction_keys = _prediction_keys(prediction)
    prediction_market = _normalize_text(prediction.get("market"))
    for row, row_keys, row_market in keyed_rows:
        if prediction_keys and row_keys and prediction_keys.isdisjoint(row_keys):
            continue
        if row_market and prediction_market and row_market != prediction_market:
            continue
        return row
    return None


def _candidate_result_debug_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        candidates.append(
            {
                "prediction_id": str(row.get("prediction_id") or row.get("id") or "").strip() or None,
                "sport": row.get("sport"),
                "market": row.get("market"),
                "selection": row.get("selection") or row.get("player") or row.get("name"),
                "result": row.get("result") or row.get("outcome") or row.get("grade"),
                "actual": row.get("actual"),
                "line": row.get("line") or row.get("market_line") or row.get("closing_line"),
                "closing_line": row.get("closing_line"),
            }
        )
    return candidates


def pending_prediction_dates(*, ledger_path: Path | str | None = None) -> list[str]:
    """Distinct dates (YYYY-MM-DD) carrying at least one still-unsettled
    prediction.

    Without this, a caller that only ever reconciles a fixed rolling window
    (e.g. "yesterday and today") can never retry a prediction whose date
    fell outside that window on every run since it was logged -- worker
    downtime, the autorun flag not being live yet, or simply placing a bet
    a few days ahead of the game all produce a prediction that's dated
    outside "yesterday/today" forever, even once real result data exists.
    """
    ledger_root = Path(ledger_path) if ledger_path is not None else None
    predictions = load_all_predictions(ledger_path=ledger_root)
    dates: set[str] = set()
    for prediction in predictions:
        result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else None
        if result and _normalize_text(result.get("outcome")) in {"win", "loss", "push", "void"}:
            continue
        prediction_date = _prediction_date(prediction)
        if prediction_date:
            dates.add(prediction_date)
    return sorted(dates)


def reconcile_prediction_results_for_date(
    date_value: str,
    *,
    ledger_path: Path | str | None = None,
    result_roots: Sequence[Path | str] | None = None,
) -> dict[str, Any]:
    date_token = str(date_value or "").strip()
    if len(date_token) < 10:
        raise ValueError("date_value must be an ISO date like YYYY-MM-DD")
    date_token = date_token[:10]

    ledger_root = Path(ledger_path) if ledger_path is not None else None
    roots = [Path(root) for root in result_roots] if result_roots is not None else [_repo_root() / "data"]

    started = time.perf_counter()
    predictions = load_all_predictions(ledger_path=ledger_root)
    scoped_predictions = [prediction for prediction in predictions if _prediction_date(prediction) == date_token]
    loaded_ledger = time.perf_counter()
    # ONE walk per date, shared by the rows and the reported file list (it
    # used to be two, each six rglobs of the whole disk).
    result_paths = _candidate_result_paths(date_token, roots)
    walked = time.perf_counter()
    result_rows = _result_rows_from_paths(result_paths)
    keyed_rows = _keyed_result_rows(result_rows)
    read_rows = time.perf_counter()

    resolved = 0
    skipped = 0
    # WHY A BREAKDOWN. On 2026-09-19's first post-fix autorun every date read
    # `resolved=0`, including dates with plenty of result rows (07-05: 20
    # predictions against 906 rows). A single `skipped` counter cannot tell
    # "nothing was resolvable" from "the matcher stopped matching", and the
    # comparison that would have settled it does not exist retrospectively:
    # this timing line is newer than the old code it replaced. So the line now
    # carries its own explanation.
    skip_reasons: Counter[str] = Counter()
    result_files = [str(path) for path in result_paths]
    reconciled_predictions: list[dict[str, Any]] = []
    # Also INFO: the debug payload below serialises every result row, so it is
    # built only when something will actually emit it. Render's collector does
    # not see logger.info, and building it anyway cost one full dump of the
    # date's rows per unmatched prediction.
    debug_unmatched = logger.isEnabledFor(logging.INFO)
    write_seconds = 0.0

    for prediction in scoped_predictions:
        result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else None
        if result and _normalize_text(result.get("outcome")) in {"win", "loss", "push", "void"}:
            skipped += 1
            skip_reasons["already_resolved"] += 1
            reconciled_predictions.append(dict(prediction))
            continue

        matched_row = _match_result_row(prediction, keyed_rows)
        if matched_row is None:
            if debug_unmatched:
                logger.info(
                    json.dumps(
                        {
                            "prediction_id": prediction.get("id"),
                            "sport": prediction.get("sport"),
                            "selection": prediction.get("selection"),
                            "market": prediction.get("market"),
                            "reason": "no match found",
                            "candidate_results_checked": _candidate_result_debug_rows(result_rows),
                        },
                        sort_keys=True,
                        default=str,
                    )
                )
            skipped += 1
            skip_reasons["no_result_row_matched"] += 1
            reconciled_predictions.append(dict(prediction))
            continue

        outcome = _row_outcome(matched_row, prediction)
        if outcome is None:
            skipped += 1
            skip_reasons["outcome_unreadable"] += 1
            reconciled_predictions.append(dict(prediction))
            continue

        original_line = _row_original_line(prediction, matched_row)
        closing_line = _row_closing_line(matched_row)
        pnl = _row_pnl(matched_row, outcome, prediction)
        write_started = time.perf_counter()
        result_payload = record_result(
            prediction_id=prediction.get("id"),
            outcome=outcome,
            original_line=original_line,
            closing_line=closing_line,
            pnl=pnl,
            original_price=_prediction_original_price(prediction),
            closing_price=_row_closing_price(matched_row),
            ledger_path=ledger_root,
        )
        write_seconds += time.perf_counter() - write_started
        resolved += 1
        reconciled_predictions.append({**dict(prediction), "result": result_payload})

    finished = time.perf_counter()
    # One line per date, so the autorun's time can be split by stage from the
    # logs (lane `reconciliation-disk-walks`). print, not logger.info: only
    # stdout reaches Render's collector.
    print(
        f"[prediction_reconciliation] RECONCILE_DATE_TIMING date={date_token} "
        f"predictions={len(scoped_predictions)} resolved={resolved} skipped={skipped} "
        f"skipped_by={json.dumps(dict(sorted(skip_reasons.items())), separators=(',', ':'))} "
        f"result_files={len(result_paths)} result_rows={len(result_rows)} "
        f"ledger_s={loaded_ledger - started:.2f} walk_s={walked - loaded_ledger:.2f} "
        f"rows_s={read_rows - walked:.2f} match_s={finished - read_rows - write_seconds:.2f} "
        f"write_s={write_seconds:.2f} total_s={finished - started:.2f}",
        flush=True,
    )

    summary = {
        "date": date_token,
        "predictions": len(scoped_predictions),
        "resolved": resolved,
        "skipped": skipped,
        "result_files": result_files,
    }
    return {
        "ok": True,
        "summary": summary,
        "predictions": reconciled_predictions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile prediction results for a date")
    parser.add_argument("--date", required=True, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--ledger-path", default="", help="Optional ledger path")
    parser.add_argument("--result-root", action="append", default=[], help="Optional result root; repeat to add more")
    args = parser.parse_args(list(argv) if argv is not None else None)

    ledger_path = Path(args.ledger_path) if str(args.ledger_path or "").strip() else None
    result_roots = [Path(value) for value in args.result_root] if args.result_root else None
    payload = reconcile_prediction_results_for_date(args.date, ledger_path=ledger_path, result_roots=result_roots)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
