"""Settle live orders from the venue's own settlement record.

--------------------------------------------------------------------------
THIS IS NOT A BETTER ESTIMATOR. IT REMOVES THE ESTIMATOR
--------------------------------------------------------------------------

`paper_settlement.settle_orders` grades an order against a status WE resolve:
our boxscore feed, our team aliases, our line handling, our over/under
vocabulary. Every one of those is a place to be wrong, and its own record says
so -- 80 of 171 orders on 2026-08-23 refused with `unmapped_market`, and always
would have, because a spread arrives as `side="Texas Rangers", line=-1.5` and
that is not expressible in the grader's vocabulary.

Both venues will simply tell us how a market we hold resolved. There is no
join to get wrong, no alias to miss, and no feed to be late. That matters far
beyond tidiness: **every stake on this board is sized at 1/16th Kelly and the
sim carries zero weight, both because settled sample is zero everywhere.**
`settled > 0` is the gate the whole feedback loop is stuck behind, and this is
the shortest path through it.

--------------------------------------------------------------------------
THE VENUE'S ARITHMETIC, NOT OURS
--------------------------------------------------------------------------

Kalshi (`GET /portfolio/settlements`, docs read 2026-08-26):

    ticker, market_result (yes|no|scalar), settled_time
    yes_count_fp / no_count_fp        contracts WE HELD at settlement
    yes_total_cost_dollars / no_...   our cost basis, fixed-point strings
    revenue                           payout in CENTS (winners pay 100c each)
    fee_cost                          fixed-point dollars

    P&L = revenue/100 - (yes_cost + no_cost) - fee_cost

Polymarket (`GET /v1/portfolio/activities?types=ACTIVITY_TYPE_POSITION_RESOLUTION`):

    positionResolution.marketSlug, side (LONG|SHORT|NEUTRAL), updateTime
    beforePosition / afterPosition    UserPosition, whose `realized` is an
                                      Amount {value: decimal string, currency}

    P&L = afterPosition.realized - beforePosition.realized

**WON/LOST IS DERIVED FROM WHICH SIDE WE HELD, NEVER FROM OUR OWN `side` AND
`line` FIELDS.** Those are the fields the alias joins get wrong; using them here
would reintroduce the exact estimator this module exists to delete. Kalshi
states our holdings in the settlement row itself, and Polymarket's realized
delta carries its own sign.

--------------------------------------------------------------------------
ONE MARKET CAN CARRY SEVERAL OF OUR ORDERS, AND P&L DOES NOT DIVIDE
--------------------------------------------------------------------------

A venue settles a MARKET. We may hold two orders on one ticker. The OUTCOME is
shared and safe to apply to both -- the market resolved one way for everyone.
The P&L is not: the row states the market total, and splitting it across orders
would be an invented number wearing an exact one's clothes.

So: one ungraded order on a market gets the outcome AND the venue's P&L; several
get the outcome and no P&L, counted as `pnl_unattributed`. Holding BOTH sides
refuses outright -- the outcome is genuinely ambiguous per order then, and a
guess would be a coin flip recorded as a fact.

--------------------------------------------------------------------------
IDEMPOTENT, AND IT WRITES INTO A MONEY RECORD SOMEBODY ELSE ALSO WRITES
--------------------------------------------------------------------------

An order already carrying an `outcome` is skipped before anything else happens
-- the same contract `settle_orders` keeps, and for the same reason: re-running
must not be able to change a settled bet. Rows this module grades are stamped
`settled_by: "venue"`, so an AUTHORITATIVE outcome stays distinguishable from an
INFERRED one. A later evaluation pass that cannot tell those apart is one that
will eventually average them.

**Two absences, counted separately and never collapsed:** settlement rows that
match no order of ours (`unjoinable`), and open orders with no settlement row
yet (`awaiting`). "Nothing has settled" and "we cannot see what settled" are
opposite facts.
"""

from __future__ import annotations

from typing import Any, Mapping

VENUES: tuple[str, ...] = ("kalshi", "polymarket")

KALSHI_SETTLEMENTS_PATH = "/portfolio/settlements"
POLYMARKET_ACTIVITIES_PATH = "/portfolio/activities"
POLYMARKET_RESOLUTION_TYPE = "ACTIVITY_TYPE_POSITION_RESOLUTION"

OUTCOME_WON = "won"
OUTCOME_LOST = "lost"
OUTCOME_PUSH = "push"


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _num(value: Any) -> float | None:
    """A number, including a fixed-point string. `True` is not a number.

    Both venues send money as decimal STRINGS in places -- Kalshi's
    `yes_total_cost_dollars`, Polymarket's `Amount.value` -- so a float-only
    parse would silently drop the cost basis and report the gross payout as
    profit.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _amount(value: Any) -> float | None:
    """Polymarket's `Amount` -> a float. `{value: "40.5", currency: "USD"}`."""
    if isinstance(value, Mapping):
        return _num(value.get("value"))
    return _num(value)


def _join_key(value: Any) -> str:
    """Tickers and slugs, normalised for comparison only.

    Case-folded because a ticker we stored and a ticker the venue echoes back
    have differed by case before (`fetch_market` accepted a body carrying ANY
    ticker, which is how an alias slipped through). Folding is not permissive
    -- it matches more, never grades more loosely.
    """
    return str(value or "").strip().casefold()


# ---------------------------------------------------------------------------
# Kalshi
# ---------------------------------------------------------------------------


def fetch_kalshi_settlements(*, limit: int = 200, max_pages: int = 10) -> tuple[list[dict], str | None]:
    """Our settled markets, newest first. Returns `(rows, error)`.

    Paged by the documented `cursor`. Never raises: settlement is a read, and a
    read that throws inside the execution tick would stop orders being placed.
    """
    try:
        from syndicate.features.shared.kalshi_auth import (
            KalshiAuthError,
            _base_url,
            load_credentials,
            signed_request,
        )
    except Exception as exc:
        return [], f"import: {type(exc).__name__}: {exc}"

    creds = load_credentials()
    if creds.get("status") != "ok":
        return [], "credentials_absent"

    rows: list[dict] = []
    cursor = ""
    for _ in range(max(1, int(max_pages))):
        url = f"{_base_url()}{KALSHI_SETTLEMENTS_PATH}?limit={int(limit)}"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            payload = signed_request("GET", url, credentials=creds)
        except KalshiAuthError as exc:
            return rows, str(exc)[:300]
        except Exception as exc:
            return rows, f"{type(exc).__name__}: {exc}"
        page = payload.get("settlements")
        if not isinstance(page, list):
            return rows, "shape_unrecognised"
        rows.extend(row for row in page if isinstance(row, dict))
        cursor = str(payload.get("cursor") or "")
        # An empty cursor OR a short page means the end. Both, because a venue
        # that keeps echoing a cursor forever would page until max_pages.
        if not cursor or len(page) < int(limit):
            break
    return rows, None


def grade_kalshi_settlement(row: Mapping[str, Any]) -> dict[str, Any]:
    """One settlement row -> outcome and P&L, or a NAMED refusal.

    Never returns a bare failure: a refusal says which of the several genuinely
    different reasons applied, because `scalar_market` and `both_sides_held`
    call for completely different follow-ups.
    """
    result = str(row.get("market_result") or "").strip().lower()
    yes_ct = _num(row.get("yes_count_fp")) or 0.0
    no_ct = _num(row.get("no_count_fp")) or 0.0

    if result not in {"yes", "no"}:
        # `scalar` settles at a VALUE, not a side. Nothing this system trades is
        # scalar, and inventing a side for one would be a guess recorded as a fact.
        return {"graded": False, "reason": f"unsupported_market_result:{result or 'absent'}"}
    if yes_ct <= 0 and no_ct <= 0:
        return {"graded": False, "reason": "no_position_held"}
    if yes_ct > 0 and no_ct > 0:
        return {"graded": False, "reason": "both_sides_held"}

    held = "yes" if yes_ct > 0 else "no"
    outcome = OUTCOME_WON if held == result else OUTCOME_LOST

    revenue_cents = _num(row.get("revenue"))
    cost = (_num(row.get("yes_total_cost_dollars")) or 0.0) + (
        _num(row.get("no_total_cost_dollars")) or 0.0
    )
    fees = _num(row.get("fee_cost")) or 0.0
    pnl = None
    if revenue_cents is not None:
        pnl = round(revenue_cents / 100.0 - cost - fees, 4)

    return {
        "graded": True,
        "outcome": outcome,
        "pnl_dollars": pnl,
        "held_side": held,
        "market_result": result,
        "settled_at_venue": row.get("settled_time"),
        "fees_dollars": round(fees, 4) if fees else None,
    }


# ---------------------------------------------------------------------------
# Polymarket US
# ---------------------------------------------------------------------------


def fetch_polymarket_resolutions(*, limit: int = 200, max_pages: int = 10) -> tuple[list[dict], str | None]:
    """Our position resolutions, newest first. Returns `(rows, error)`.

    Asks the venue to filter by type rather than pulling every trade and
    discarding most of it -- `types` is a documented query parameter, and a
    client-side filter would page through fills to find settlements.
    """
    try:
        from syndicate.features.shared.polymarket_us_auth import (
            BASE_URL,
            PolymarketUSAuthError,
            _API_PREFIX,
            credentials_present,
            signed_request,
        )
    except Exception as exc:
        return [], f"import: {type(exc).__name__}: {exc}"

    if not credentials_present():
        return [], "credentials_absent"

    rows: list[dict] = []
    cursor = ""
    for _ in range(max(1, int(max_pages))):
        url = (
            f"{BASE_URL}{_API_PREFIX}{POLYMARKET_ACTIVITIES_PATH}"
            f"?limit={int(limit)}&types={POLYMARKET_RESOLUTION_TYPE}"
        )
        if cursor:
            url += f"&cursor={cursor}"
        try:
            payload = signed_request("GET", url)
        except PolymarketUSAuthError as exc:
            return rows, str(exc)[:300]
        except Exception as exc:
            return rows, f"{type(exc).__name__}: {exc}"
        page = payload.get("activities")
        if not isinstance(page, list):
            return rows, "shape_unrecognised"
        for item in page:
            if not isinstance(item, dict):
                continue
            resolution = item.get("positionResolution")
            if isinstance(resolution, dict) and resolution.get("marketSlug"):
                rows.append(resolution)
        cursor = str(payload.get("nextCursor") or "")
        if payload.get("eof") or not cursor:
            break
    return rows, None


def grade_polymarket_resolution(row: Mapping[str, Any]) -> dict[str, Any]:
    """One resolution -> outcome and P&L, or a NAMED refusal.

    THE REALIZED DELTA IS THE SETTLEMENT. `UserPosition.realized` is cumulative,
    so the difference across the resolution is exactly what this event booked --
    and its sign is the outcome. Reading `afterPosition.realized` alone would
    report the position's whole trading history as this settlement's result.
    """
    before = row.get("beforePosition") if isinstance(row.get("beforePosition"), Mapping) else {}
    after = row.get("afterPosition") if isinstance(row.get("afterPosition"), Mapping) else {}
    before_realized = _amount(before.get("realized"))
    after_realized = _amount(after.get("realized"))

    if after_realized is None:
        return {"graded": False, "reason": "no_realized_amount"}

    delta = after_realized - (before_realized or 0.0)
    side = str(row.get("side") or "").strip().upper()

    if side.endswith("NEUTRAL"):
        # The venue's own word for a resolution that moved nothing.
        outcome = OUTCOME_PUSH
    elif delta > 0:
        outcome = OUTCOME_WON
    elif delta < 0:
        outcome = OUTCOME_LOST
    else:
        outcome = OUTCOME_PUSH

    return {
        "graded": True,
        "outcome": outcome,
        "pnl_dollars": round(delta, 4),
        "held_side": side or None,
        "settled_at_venue": row.get("updateTime"),
    }


# ---------------------------------------------------------------------------
# The join, and the write
# ---------------------------------------------------------------------------


def settle_from_venue(*, dry_run: bool = False) -> dict[str, Any]:
    """Grade every ungraded LIVE order that the venue has settled. Persists.

    WORKER ONLY -- it needs venue credentials and it writes the execution ledger.

    Returns counters rather than a bare count, because the interesting states
    here are the absences: a settlement matching no order and an order with no
    settlement are different problems and only one of them is ours.
    """
    from syndicate.features.shared.execution_ledger import LIVE, _load, _persist

    counters: dict[str, Any] = {
        "settled": 0,
        "already": 0,
        "awaiting": 0,
        "unjoinable": 0,
        "pnl_unattributed": 0,
        "refused": {},
        "by_venue": {},
        "errors": {},
    }

    try:
        state = _load()
    except Exception as exc:
        counters["errors"]["ledger"] = f"{type(exc).__name__}: {exc}"
        return {"status": "error", **counters}

    orders = [o for o in (state.get("orders") or []) if str(o.get("mode") or "") == LIVE]

    # UNGRADED, FILLED orders only. An order that never filled has no position
    # to settle, and one already carrying an outcome is never touched again.
    open_by_key: dict[tuple[str, str], list[dict]] = {}
    for order in orders:
        if order.get("outcome"):
            counters["already"] += 1
            continue
        if str(order.get("status") or "") == "rejected":
            continue
        venue = str(order.get("venue") or "").strip().lower()
        key = _join_key(order.get("venue_ticker"))
        if not venue or not key:
            continue
        open_by_key.setdefault((venue, key), []).append(order)

    fetched: dict[str, list[dict]] = {}
    for venue, fetch in (
        ("kalshi", fetch_kalshi_settlements),
        ("polymarket", fetch_polymarket_resolutions),
    ):
        try:
            rows, error = fetch()
        except Exception as exc:  # defence in depth; each fetch already catches
            rows, error = [], f"{type(exc).__name__}: {exc}"
        fetched[venue] = rows
        if error:
            counters["errors"][venue] = error

    matched_keys: set[tuple[str, str]] = set()
    graded_any = False

    for venue, rows in fetched.items():
        grade = grade_kalshi_settlement if venue == "kalshi" else grade_polymarket_resolution
        ticker_field = "ticker" if venue == "kalshi" else "marketSlug"
        per_venue = counters["by_venue"].setdefault(venue, {"rows": len(rows), "settled": 0})

        for row in rows:
            key = (venue, _join_key(row.get(ticker_field)))
            targets = open_by_key.get(key)
            if not targets:
                # A market the venue settled that we hold no ungraded order on.
                # Expected constantly (already-graded rows, other accounts'
                # history) -- counted, never treated as an error.
                counters["unjoinable"] += 1
                continue

            verdict = grade(row)
            if not verdict.get("graded"):
                reason = str(verdict.get("reason"))
                counters["refused"][reason] = counters["refused"].get(reason, 0) + 1
                continue

            matched_keys.add(key)
            # ONE MARKET, POSSIBLY SEVERAL ORDERS. The outcome is shared and
            # safe; the P&L is the MARKET's total and does not divide.
            attributable = len(targets) == 1
            for order in targets:
                order["outcome"] = verdict["outcome"]
                order["settled_by"] = "venue"
                order["settled_at_venue"] = verdict.get("settled_at_venue")
                order["graded_at"] = _utc_now()
                if attributable:
                    if verdict.get("pnl_dollars") is not None:
                        order["pnl_dollars"] = verdict["pnl_dollars"]
                    if verdict.get("fees_dollars") is not None:
                        order["fees_dollars"] = verdict["fees_dollars"]
                else:
                    counters["pnl_unattributed"] += 1
                counters["settled"] += 1
                per_venue["settled"] += 1
                graded_any = True

    counters["awaiting"] = sum(
        len(v) for k, v in open_by_key.items() if k not in matched_keys
    )

    if graded_any and not dry_run:
        try:
            _persist(state)
        except Exception as exc:
            counters["errors"]["persist"] = f"{type(exc).__name__}: {exc}"
            return {"status": "error", **counters}

    return {"status": "ok", **counters}
