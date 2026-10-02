"""Rebuild the LIVE execution record from the venues' own settlement history.

WHY THIS EXISTS (2026-10-02). Render was billing-suspended at 2026-09-30T06:37Z
and production moved to the local fleet on a FRESH Redis. The execution ledger
is a keyvalue document, so every live order Render placed stayed behind in the
suspended keyvalue: the fleet's ledger held 22 rows, all paper. VENUE_SETTLEMENT
read `unjoinable=593` (kalshi 432, polymarket 161). `unjoinable_split` then showed
all 593 settled BEFORE the suspension (newest 2026-09-28T03:16:56Z). So no
outcome was lost, but the whole live record (P&L, ROI) was.

WHAT IT REBUILDS, AND WHY THAT UNIT. One row per SETTLED MARKET POSITION, not
per order. Kalshi's order list has aged out (129 orders against 432
settlements), and Polymarket publishes no order list at all. A settlement row is
complete for the position, though: Kalshi gives contracts per side, cost, fees,
revenue and time; Polymarket gives the market, side and realized delta. Each row
is written ALREADY GRADED by the module's own graders (`venue_settlement`), so
the outcome and P&L are exactly what settlement would have written.

WHAT IT CANNOT RECOVER, stated rather than invented: the plan, model edge, sim
view and the book the bet was sized against. Those fields stay None, and
`source="venue_rebuild"` marks every row so no reader can mistake one for a
placed order with full metadata.

SAFETY:
  * Runs ONLY on a request file, inside live-odds-worker, which holds the
    credentials (`process_rebuild_request`).
  * `dry_run` writes nothing to the ledger and reports exactly what `apply`
    would write. `apply` REFUSES unless the request names the dry run's row
    count (`expect_rows`), so it cannot write something nobody reviewed.
  * Never duplicates: it skips any market already carrying a live row, and
    re-running it adds nothing (deterministic idempotency keys).
  * Rows are `status=filled` and dated by their slate, so they never enter
    today's `spent_today` or `unreconciled_orders`.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared import venue_settlement as vs

SOURCE = "venue_rebuild"
REQUEST_NAME = "ledger_rebuild_request.json"
RESULT_NAME = "ledger_rebuild_result.json"

_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}
_KALSHI_DATE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})")
_SLUG_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _central_date(value: Any) -> str | None:
    when = vs._parse_venue_time(value)
    if when is None:
        return None
    # Central without tz data: CDT (UTC-5) covers the whole affected window
    # (Apr-Nov). The fallback is used only when the ticker carries no date.
    return (when.astimezone(timezone.utc) - timedelta(hours=5)).date().isoformat()


def _kalshi_slate_date(ticker: str) -> str | None:
    m = _KALSHI_DATE.search(str(ticker or "").upper())
    if not m or m.group(2) not in _MONTHS:
        return None
    try:
        return datetime(2000 + int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3))).date().isoformat()
    except ValueError:
        return None


def _slug_slate_date(slug: str) -> str | None:
    m = _SLUG_DATE.search(str(slug or ""))
    return m.group(1) if m else None


def _kalshi_sport(ticker: str) -> str | None:
    try:
        from syndicate.features.shared.kalshi_catalogue import sport_for_series

        return sport_for_series(str(ticker or "").split("-")[0])
    except Exception:
        return None


_SLUG_SPORTS = {"mlb": "mlb", "nfl": "nfl", "nba": "nba", "wnba": "wnba", "nhl": "nhl", "cfb": "ncaaf", "cbb": "ncaab"}


def _slug_league(slug: str) -> str | None:
    parts = str(slug or "").split("-")
    return parts[1] if len(parts) > 2 and parts[1].isalpha() else None


def _slug_sport(slug: str) -> str | None:
    """Polymarket US slugs carry a LEAGUE code. Every code it lists outside the
    US leagues and college codes is a soccer competition (dry run 2026-10-02:
    lal, eflch, ere, sea, ligpor, epl, mls)."""
    league = _slug_league(slug)
    if league is None:
        return None
    return _SLUG_SPORTS.get(league, "soccer")


def _polymarket_cost(row: Mapping[str, Any]) -> tuple[float | None, float | None, float | None]:
    """(cost $, shares, venue avg price) of the position BEFORE it resolved.

    `beforePosition` states its own cost basis. A SHORT (a bought NO) reports
    `qtySold`/`netPosition<0` with `qtyBought=0`, so shares come from either.

    THE AVERAGE PRICE IS NOT WRITTEN AS `fill_price`. Measured in the 2026-10-02
    dry run: with a price derived as cost/shares (cost includes fees), 19 won
    rows read as P&L larger than their stake could pay, by 2-6%, and
    `repair_impossible_venue_pnl` would have REPLACED the venue's stated P&L
    with an estimate on the next tick. The repair exists for an attribution
    error that cannot occur here (each row IS the whole position), so the
    venue's number is kept and the price is stored only as `venue_avg_price`.
    """
    before = row.get("beforePosition") if isinstance(row.get("beforePosition"), Mapping) else {}
    cost = vs._amount(before.get("cost"))
    shares = (vs._num(before.get("qtyBoughtDecimal")) or vs._num(before.get("qtyBought"))
              or vs._num(before.get("qtySoldDecimal")) or vs._num(before.get("qtySold")))
    avg = vs._amount(before.get("avgPx"))
    if avg is not None and not (0.0 < avg < 1.0):
        avg = None
    if cost is None or cost <= 0:
        return None, shares, avg
    return round(cost, 4), shares, avg


def _base_row(*, venue: str, ticker: str, side: str, slate: str | None, slate_source: str,
              sport: str | None, verdict: Mapping[str, Any], settled_at: Any, now: str) -> dict[str, Any]:
    return {
        "idempotency_key": f"{SOURCE}:{venue}:{vs._join_key(ticker)}:{side}",
        "position_key": None,
        "selected_date": slate,
        "selected_date_source": slate_source,
        "mode": "live",
        "venue": venue,
        "sport": sport,
        "event_id": None,
        "market": None,
        "side": side,
        "line": None,
        "player_name": None,
        "book": venue,
        "segment": None,
        "home_team": None,
        "away_team": None,
        "commence_time": None,
        "opening_key": None,
        "game_pk": None,
        "venue_ticker": ticker,
        "model_edge_pct": None,
        "ev_pct": None,
        "sim_view": None,
        "sim_line_gap": None,
        "sim_probability_railed": None,
        "side_picked_by": None,
        "stake_fraction_ev_only": None,
        "sim_share_of_stake": None,
        "outcome": verdict.get("outcome"),
        "pnl_dollars": verdict.get("pnl_dollars"),
        "settled_value": None,
        "graded_at": now,
        "settled_by": "venue",
        "settled_at_venue": settled_at,
        "held_side": verdict.get("held_side"),
        "requested_price": None,
        "requested_stake_dollars": None,
        "submitted_at": settled_at,
        "status": "filled",
        "fill_price": None,
        "fill_stake_dollars": None,
        "fees_dollars": verdict.get("fees_dollars"),
        "venue_resolved_at": settled_at,
        "settled_at": settled_at,
        "source": SOURCE,
        "rebuilt_at": now,
    }


def kalshi_row(row: Mapping[str, Any], now: str) -> tuple[dict[str, Any] | None, str | None]:
    """One Kalshi settlement -> one graded live row, or (None, skip_reason)."""
    verdict = vs.grade_kalshi_settlement(row)
    if not verdict.get("graded"):
        return None, str(verdict.get("reason"))
    ticker = str(row.get("ticker") or "").strip()
    if not ticker:
        return None, "no_ticker"
    held = verdict["held_side"]
    contracts = vs._num(row.get(f"{held}_count_fp")) or 0.0
    cost = vs._num(row.get(f"{held}_total_cost_dollars")) or 0.0
    slate = _kalshi_slate_date(ticker)
    out = _base_row(
        venue="kalshi", ticker=ticker, side=held,
        slate=slate or _central_date(row.get("settled_time")),
        slate_source="ticker" if slate else "settled_time_central",
        sport=_kalshi_sport(ticker), verdict=verdict, settled_at=row.get("settled_time"), now=now,
    )
    # Probability dollars, the unit `profit_per_dollar` expects for a contract.
    if contracts > 0 and cost > 0:
        out["fill_price"] = round(cost / contracts, 4)
        out["fill_stake_dollars"] = round(cost, 4)
        out["fill_contracts"] = contracts
    return out, None


def polymarket_row(row: Mapping[str, Any], now: str) -> tuple[dict[str, Any] | None, str | None]:
    """One Polymarket resolution -> one graded live row, or (None, skip_reason).

    No cost basis is invented: the resolution carries the realized DELTA, and
    `fill_stake_dollars` stays None unless the position states its cost.
    """
    verdict = vs.grade_polymarket_resolution(row)
    if not verdict.get("graded"):
        return None, str(verdict.get("reason"))
    slug = str(row.get("marketSlug") or "").strip()
    if not slug:
        return None, "no_slug"
    slate = _slug_slate_date(slug)
    side = str(verdict.get("held_side") or "").replace("POSITION_RESOLUTION_SIDE_", "").lower() or "unknown"
    out = _base_row(
        venue="polymarket", ticker=slug, side=side,
        slate=slate or _central_date(row.get("updateTime")),
        slate_source="slug" if slate else "update_time_central",
        sport=_slug_sport(slug), verdict=verdict, settled_at=row.get("updateTime"), now=now,
    )
    out["venue_trade_id"] = row.get("tradeId")
    out["league"] = _slug_league(slug)
    cost, shares, avg = _polymarket_cost(row)
    out["venue_avg_price"] = avg
    if cost is not None:
        out["fill_stake_dollars"] = cost
        out["fill_contracts"] = shares
    return out, None


def _one_row_per_market(venue: str, source_rows: list, build, now: str,
                        skipped: dict[str, int]) -> list[dict[str, Any]]:
    """Exactly ONE row per market, never two.

    `repair_multi_side_grades` clears every venue grade on a market whose live
    rows hold more than one side. Its fallback is per-side inference, which
    needs a line these rows cannot carry, so a two-sided rebuild would sit
    ungraded for good. So a market settled more than once is MERGED when every
    row is graded on the same side (the venue's P&L is additive), and SKIPPED,
    counted, otherwise.
    """
    field = "ticker" if venue == "kalshi" else "marketSlug"
    groups: dict[str, list] = {}
    for raw in source_rows or []:
        groups.setdefault(vs._join_key((raw or {}).get(field)), []).append(raw)
    out: list[dict[str, Any]] = []
    for _key, members in groups.items():
        built = [build(raw, now) for raw in members]
        refused = [reason for row, reason in built if row is None]
        rows = [row for row, _ in built if row is not None]
        if len(members) == 1:
            if rows:
                out.append(rows[0])
            else:
                skipped[f"{venue}:{refused[0]}"] = skipped.get(f"{venue}:{refused[0]}", 0) + 1
            continue
        if refused or len({r["side"] for r in rows}) != 1:
            reason = "multi_side_market" if rows and len({r["side"] for r in rows}) > 1 else "partially_ungradable_market"
            skipped[f"{venue}:{reason}"] = skipped.get(f"{venue}:{reason}", 0) + len(members)
            continue
        merged = dict(rows[0])
        pnl = round(sum(float(r.get("pnl_dollars") or 0.0) for r in rows), 4)
        merged["pnl_dollars"] = pnl
        merged["outcome"] = "won" if pnl > 0 else "lost" if pnl < 0 else rows[0]["outcome"]
        merged["settled_at_venue"] = max(str(r.get("settled_at_venue") or "") for r in rows) or None
        stakes = [r.get("fill_stake_dollars") for r in rows]
        merged["fill_stake_dollars"] = round(sum(stakes), 4) if all(stakes) else None
        merged["fill_price"] = None if len(rows) > 1 else merged.get("fill_price")
        merged["merged_settlements"] = len(rows)
        skipped[f"{venue}:merged_into_one"] = skipped.get(f"{venue}:merged_into_one", 0) + len(rows) - 1
        out.append(merged)
    return out


def build_rows(kalshi: list, polymarket: list, existing_orders: list, *, now: str | None = None) -> dict[str, Any]:
    """Pure: venue rows + the current ledger -> what a rebuild would add."""
    now = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    held = {
        (str(o.get("venue") or "").lower(), vs._join_key(o.get("venue_ticker")))
        for o in existing_orders or []
        if str(o.get("mode") or "") == "live"
    }
    keys = {o.get("idempotency_key") for o in existing_orders or []}
    rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    seen: set[str] = set()
    for venue, source_rows, build in (("kalshi", kalshi, kalshi_row), ("polymarket", polymarket, polymarket_row)):
        for row in _one_row_per_market(venue, source_rows, build, now, skipped):
            if (venue, vs._join_key(row["venue_ticker"])) in held:
                skipped[f"{venue}:already_in_ledger"] = skipped.get(f"{venue}:already_in_ledger", 0) + 1
                continue
            key = row["idempotency_key"]
            if key in keys or key in seen:
                skipped[f"{venue}:duplicate_key"] = skipped.get(f"{venue}:duplicate_key", 0) + 1
                continue
            seen.add(key)
            rows.append(row)
    return {"rows": rows, "skipped": skipped, "summary": summarize(rows)}


def summarize(rows: list) -> dict[str, Any]:
    out: dict[str, Any] = {"rows": len(rows), "by_venue": {}}
    for row in rows:
        v = out["by_venue"].setdefault(row["venue"], {
            "rows": 0, "won": 0, "lost": 0, "push": 0, "pnl_dollars": 0.0, "staked_dollars": 0.0,
            "rows_with_stake": 0, "first_date": None, "last_date": None, "by_sport": {},
        })
        v["rows"] += 1
        v[str(row.get("outcome"))] = v.get(str(row.get("outcome")), 0) + 1
        v["pnl_dollars"] = round(v["pnl_dollars"] + float(row.get("pnl_dollars") or 0.0), 2)
        if row.get("fill_stake_dollars"):
            v["rows_with_stake"] += 1
            v["staked_dollars"] = round(v["staked_dollars"] + float(row["fill_stake_dollars"]), 2)
        d = row.get("selected_date")
        if d:
            v["first_date"] = min(filter(None, [v["first_date"], d]))
            v["last_date"] = max(filter(None, [v["last_date"], d]))
        sport = str(row.get("sport") or "unknown")
        v["by_sport"][sport] = v["by_sport"].get(sport, 0) + 1
    return out


def rebuild(*, dry_run: bool, expect_rows: int | None = None, fetch=None) -> dict[str, Any]:
    """Fetch both venues, build, and (apply only) persist. Never raises."""
    from syndicate.features.shared.execution_ledger import _load, _persist

    fetch = fetch or {"kalshi": vs.fetch_kalshi_settlements, "polymarket": vs.fetch_polymarket_resolutions}
    fetched: dict[str, list] = {}
    errors: dict[str, str] = {}
    for venue, fn in fetch.items():
        try:
            rows, error = fn()
        except Exception as exc:  # each fetch already catches; defence in depth
            rows, error = [], f"{type(exc).__name__}: {exc}"
        fetched[venue] = rows
        if error:
            errors[venue] = error
    result: dict[str, Any] = {
        "mode": "dry_run" if dry_run else "apply",
        "fetched": {k: len(v) for k, v in fetched.items()},
        "errors": errors,
        "polymarket_position_keys": sorted({
            k for r in fetched.get("polymarket", [])[:50] for k in (r.get("beforePosition") or {})
        }),
        # Cost-basis fields only (numbers, no identity), to check the units the
        # stake is built from before anything is applied.
        "polymarket_cost_sample": [
            {"side": r.get("side"),
             **{k: (r.get("beforePosition") or {}).get(k)
                for k in ("cost", "avgPx", "costPerShare", "qtyBought", "qtyBoughtDecimal", "qtySold", "netPosition", "realized")},
             "after_realized": (r.get("afterPosition") or {}).get("realized")}
            for r in fetched.get("polymarket", [])[:4]
        ],
    }
    if errors:
        # A partial fetch would rebuild a partial record that LOOKS whole.
        result["status"] = "refused_fetch_error"
        return result
    state = _load()
    built = build_rows(fetched["kalshi"], fetched["polymarket"], state.get("orders") or [])
    # Rows `repair_impossible_venue_pnl` would REWRITE on the next settlement
    # tick: a P&L the row's own stake cannot produce. Reported before apply so
    # the record written is the record that stays.
    impossible = [
        r for r in built["rows"]
        if r.get("pnl_dollars") is not None and vs._pnl_exceeds_own_fill(r, str(r.get("outcome")), float(r["pnl_dollars"]))
    ]
    result["pnl_exceeds_own_stake"] = {
        "rows": len(impossible),
        "by_venue": {v: sum(1 for r in impossible if r["venue"] == v) for v in ("kalshi", "polymarket")},
        "sample": [{k: r.get(k) for k in ("venue", "venue_ticker", "outcome", "pnl_dollars", "fill_stake_dollars", "fill_price")}
                   for r in impossible[:4]],
    }
    result.update(status="ok", skipped=built["skipped"], summary=built["summary"],
                  sample=[{k: r.get(k) for k in ("venue", "venue_ticker", "selected_date", "sport", "side",
                                                 "outcome", "pnl_dollars", "fill_stake_dollars", "fill_price")}
                          for r in built["rows"][:5]])
    if dry_run:
        return result
    if expect_rows is None or int(expect_rows) != len(built["rows"]):
        result["status"] = "refused_count_mismatch"
        result["expected_rows"] = expect_rows
        return result
    state.setdefault("orders", []).extend(built["rows"])
    _persist(state)
    after = _load()
    result["written"] = sum(1 for o in after.get("orders") or [] if o.get("source") == SOURCE)
    return result


def process_rebuild_request(directory: Path) -> dict[str, Any] | None:
    """The worker's hook: act on `ledger_rebuild_request.json` ONCE, if present.

    The request is `{"mode": "dry_run"}` or
    `{"mode": "apply", "expect_rows": <the dry run's summary.rows>}`. The result
    goes to `ledger_rebuild_result.json`, and the request is renamed `.done`, so
    a crash between the two re-runs a dry run harmlessly but cannot re-apply
    (apply is idempotent on its keys either way).
    """
    request_path = Path(directory) / REQUEST_NAME
    if not request_path.is_file():
        return None
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        request = {"mode": "invalid", "error": f"{type(exc).__name__}: {exc}"}
    mode = str(request.get("mode") or "")
    if mode == "dry_run":
        result = rebuild(dry_run=True)
    elif mode == "apply":
        result = rebuild(dry_run=False, expect_rows=request.get("expect_rows"))
    else:
        result = {"status": "refused_bad_request", "request": request}
    result["request"] = request
    result["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    (Path(directory) / RESULT_NAME).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    request_path.replace(request_path.with_suffix(".json.done"))
    return result
