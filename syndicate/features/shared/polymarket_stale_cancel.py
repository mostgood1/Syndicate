"""Pull an untouched Polymarket TAKER order off the book once the book has left its price.

--------------------------------------------------------------------------
WHY THIS EXISTS  [2026-11-21, user via the fleet-watcher: "yes, add the
Polymarket stale cancel to the 12-08 queue", "yes, ask the portfolio session
to build it"; lane polymarket-stale-cancel]
--------------------------------------------------------------------------

MEASURED 2026-11-21: order `ac07e83e` (NBA alternate spread, sent 12:50Z as a
taker at a cost of 0.56) rested untouched -- `ORDER_STATE_NEW`, cumQuantity 0,
read about every 5 min by the reconcile -- until its good-till-date expiry at
the 01:10Z tip-off, about 12 hours later. It could not fill at its price, and
it held its idempotency key the whole time, so the executor could not
re-evaluate that bet at a price that existed. That is the Zebby Matthews
failure (`execution_ledger.cancel_stale_resting_orders`, 2026-08-24) on the
venue that pass never reads.

HOW OFTEN, so nobody expects more of this than it does: the live-odds-worker
log of 11-20 16:02Z .. 11-21 18:06Z saw 51 Polymarket orders reconciled; 50
were never seen resting untouched and 1 (that one) rested over 4 hours. This
acts on about one order a day.

--------------------------------------------------------------------------
WHY A SECOND PASS, AND WHY HERE
--------------------------------------------------------------------------

`cancel_stale_resting_orders` is Kalshi-only (it cancels through
`kalshi_orders.cancel_order` and prices off Kalshi tickers) AND it runs from
the live-odds-worker's boot dump only, so even on Kalshi it is not a clock.
The executor's per-tick reconcile (`pipeline/execute_portfolio.py`) is the only
per-tick read of what rests; this runs off the Polymarket reconcile there, in
the Polymarket-scope run only.

--------------------------------------------------------------------------
THE DECISION THIS OVERRIDES, AND THE SAFEGUARDS IT KEEPS
--------------------------------------------------------------------------

`polymarket_us_orders.cancel_order` (2026-08-30) says nothing should call it in
a loop: it was built for an operator retiring one leg of a DUPLICATE pair, where
choosing the leg is a judgement. This pass makes no such judgement: it cancels
one specific order we placed, named by its own client id and market slug, and
`cancel_order` itself still reads the order first and refuses a filled,
cancelled or expired one, or one whose client id or slug disagrees.

The cancel ROUTE IS UNEXERCISED against the live venue (its own docstring says
the first real cancel is the probe). So:
  * `shadow` exists, and is the recommended first step: it reads, decides, and
    calls `cancel_order(execute=False)` -- a GET and a log line, no write. Not
    a betting change; it can load outside a window.
  * A failed or refused cancel changes nothing: the order is still resting and
    can still fill. Only a cancel the venue accepted is remembered.

--------------------------------------------------------------------------
THE RULE (all must hold, otherwise the order is left alone)
--------------------------------------------------------------------------

  1. A TAKER order: `execution_style` absent or "taker". Any other style rests
     on purpose and is not this pass's to judge.
  2. Older than SYNDICATE_POLYMARKET_STALE_CANCEL_MAX_AGE_SECONDS (900) since
     our submit -- it has had its chance.
  3. The venue says it is UNTOUCHED: cumQuantity 0, leavesQuantity > 0, not in
     a terminal state. A partly filled order is a position as well as an order
     and is left alone.
  4. THE BOOK HAS LEFT ITS PRICE by at least
     SYNDICATE_POLYMARKET_STALE_CANCEL_PRICE_BAND (0.01): our side's ask minus
     what one contract costs us. Both on OUR side's scale -- the wire price is
     the YES price, so a NO order costs 1 - price and the NO ask is
     1 - best YES bid (`polymarket_us_orders._log_book_at_build`).
     NO PRICE, NO CANCEL: an unreadable order or book leaves the order resting.
  5. At most SYNDICATE_EXECUTION_MAX_CANCELS (3) per pass, shared with Kalshi.

THE LEDGER IS NOT UPDATED HERE. The next Polymarket reconcile reads the venue's
cancel and moves the row through the one path allowed to change a status, as
for every other cancel.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

ENV = "SYNDICATE_POLYMARKET_STALE_CANCEL"
MAX_AGE_ENV = "SYNDICATE_POLYMARKET_STALE_CANCEL_MAX_AGE_SECONDS"
BAND_ENV = "SYNDICATE_POLYMARKET_STALE_CANCEL_PRICE_BAND"
MAX_CANCELS_ENV = "SYNDICATE_EXECUTION_MAX_CANCELS"

MODE_OFF, MODE_SHADOW, MODE_ON = "off", "shadow", "on"
_ON_TOKENS = frozenset({"on", "1", "true", "yes"})
_TAKER_STYLES = frozenset({"", "none", "taker"})
_TERMINAL = ("CANCELED", "CANCELLED", "FILLED", "EXECUTED", "EXPIRED", "REJECTED")

#: Order ids this process has had a cancel ACCEPTED for. The reconcile moves the row
#: only when it next reads the venue, so a lagging read can hand the same order back as
#: resting; remembering it keeps the pass to one cancel per order. In-process on purpose:
#: after a restart the worst case is one extra cancel, which `cancel_order` refuses on
#: its own read of a cancelled order.
_CANCELLED: set[str] = set()


def mode() -> str:
    """`off` unless the env says `shadow` or on/1/true/yes. Absent, blank or unknown is OFF."""
    raw = str(os.environ.get(ENV) or "").strip().lower()
    if raw in _ON_TOKENS:
        return MODE_ON
    if raw == MODE_SHADOW:
        return MODE_SHADOW
    return MODE_OFF


def _positive_env(name: str, default: float) -> float:
    try:
        value = float(str(os.environ.get(name) or "").strip())
    except ValueError:
        return default
    # Non-positive is a typo, not "every order is stale" (same rule as execution_ledger._float_env).
    return value if value > 0 else default


def _float(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("value")
    if isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).strip().strip("'\""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _age_seconds(stamp: Any, now: datetime) -> float | None:
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        seen = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (now - seen).total_seconds()


def _read_order(order_id: str) -> Mapping[str, Any] | None:
    """The venue's own record of one order (GET), or None when it cannot be read."""
    from syndicate.features.shared import polymarket_us_auth as auth
    from syndicate.features.shared.polymarket_us_orders import _order_url

    if not auth.credentials_present():
        return None
    try:
        raw = auth.signed_request("GET", _order_url(order_id))
    except Exception:  # noqa: BLE001 -- a failed read is not permission to write
        return None
    if not isinstance(raw, Mapping):
        return None
    order = raw.get("order") if isinstance(raw.get("order"), Mapping) else raw
    return order if isinstance(order, Mapping) else None


def is_untouched(order: Mapping[str, Any]) -> bool:
    """Nothing filled, something still working, and not in a terminal state."""
    state = str(order.get("state") or order.get("orderStatus") or "").upper()
    if any(token in state for token in _TERMINAL):
        return False
    cum, leaves = _float(order.get("cumQuantity")), _float(order.get("leavesQuantity"))
    return cum is not None and leaves is not None and cum == 0 and leaves > 0


def our_cost(order: Mapping[str, Any]) -> float | None:
    """What one contract costs OUR side. The wire price is the YES price (`_our_side_price`)."""
    from syndicate.features.shared.polymarket_us_orders import _SIDE_NO

    wire = _float(order.get("price"))
    if wire is None or not 0.0 < wire < 1.0:
        return None
    return round(1.0 - wire, 9) if order.get("outcomeSide") == _SIDE_NO else wire


def ask_for_side(book: Mapping[str, Any], outcome_side: Any) -> float | None:
    """Our side's best ask from a `/book` payload. NO buys at 1 - best YES bid."""
    from syndicate.features.shared.polymarket_us_orders import _SIDE_NO, _book_level

    data = book.get("marketData", book) if isinstance(book, Mapping) else {}
    if not isinstance(data, Mapping):
        return None
    if outcome_side == _SIDE_NO:
        best_bid = _book_level(data.get("bids") or [])
        ask = None if best_bid is None else round(1.0 - best_bid[0], 6)
    else:
        best_offer = _book_level(data.get("offers") or [])
        ask = None if best_offer is None else best_offer[0]
    return ask if ask is not None and 0.0 < ask < 1.0 else None


def _read_ask(slug: str, outcome_side: Any) -> float | None:
    from syndicate.features.shared.polymarket_us_orders import _read_book

    try:
        book = _read_book(slug)
    except Exception:  # noqa: BLE001 -- NO PRICE, NO CANCEL
        return None
    return ask_for_side(book, outcome_side) if isinstance(book, Mapping) else None


def cancel_stale_polymarket_resting(
    resting: Sequence[Mapping[str, Any]], *, now: datetime | None = None
) -> dict[str, Any]:
    """One pass over `reconcile_live_orders(venue="polymarket")["resting"]`. See the module docstring."""
    current = mode()
    if current == MODE_OFF:
        return {"status": "skipped", "reason": "disabled", "mode": current, "cancelled": 0}
    from syndicate.features.shared import polymarket_us_orders

    moment = now or datetime.now(timezone.utc)
    max_age = _positive_env(MAX_AGE_ENV, 900.0)
    band = _positive_env(BAND_ENV, 0.01)
    limit = int(_positive_env(MAX_CANCELS_ENV, 3.0))
    counts = {"not_taker": 0, "too_young": 0, "already": 0, "unreadable": 0, "touched": 0, "at_market": 0,
              "failed": 0}
    acted: list[dict[str, Any]] = []

    for row in resting or ():
        style = str(row.get("execution_style") or "").strip().lower()
        if style not in _TAKER_STYLES:
            counts["not_taker"] += 1
            continue
        order_id = str(row.get("order_id") or "").strip()
        slug = str(row.get("ticker") or "").strip()
        key = str(row.get("idempotency_key") or "").strip()
        if order_id in _CANCELLED:
            counts["already"] += 1
            continue
        age = _age_seconds(row.get("submitted_at"), moment)
        if age is None or age < max_age:
            counts["too_young"] += 1
            continue
        if not order_id or not slug or not key:
            counts["unreadable"] += 1
            continue
        if len(acted) + counts["failed"] >= limit:
            print(f"[polymarket_stale_cancel] CANCEL_CAPPED limit={limit} -- the rest wait for the next pass",
                  flush=True)
            break

        order = _read_order(order_id)
        if order is None:
            counts["unreadable"] += 1
            print(f"[polymarket_stale_cancel] SKIPPED_NO_ORDER_READ key={key} slug={slug}", flush=True)
            continue
        if not is_untouched(order):
            counts["touched"] += 1
            continue
        side = order.get("outcomeSide")
        cost = our_cost(order)
        ask = _read_ask(slug, side)
        if cost is None or ask is None:
            counts["unreadable"] += 1
            print(f"[polymarket_stale_cancel] SKIPPED_NO_PRICE key={key} slug={slug} cost={cost} ask={ask}",
                  flush=True)
            continue
        drift = round(ask - cost, 4)
        if drift < band:
            counts["at_market"] += 1
            continue

        print(
            f"[polymarket_stale_cancel] {'CANCEL_STALE' if current == MODE_ON else 'WOULD_CANCEL'} key={key}"
            f" slug={slug} side={side} cost={cost} ask={ask} drift={drift:+} age_s={age:.0f} mode={current}",
            flush=True,
        )
        result = polymarket_us_orders.cancel_order(
            order_id, execute=(current == MODE_ON), expect_client_order_id=key, expect_market_slug=slug
        )
        status = str(result.get("status") or "")
        expected = "sent" if current == MODE_ON else "dry_run"
        if status != expected:
            counts["failed"] += 1
            print(
                f"[polymarket_stale_cancel] CANCEL_NOT_DONE key={key} status={status}"
                f" reason={str(result.get('reason'))[:200]} -- order left resting",
                flush=True,
            )
            continue
        if current == MODE_ON:
            _CANCELLED.add(order_id)
        acted.append({"idempotency_key": key, "slug": slug, "cost": cost, "ask": ask, "drift": drift,
                      "age_seconds": round(age, 0)})

    if acted or counts["failed"] or counts["unreadable"]:
        print(
            f"[polymarket_stale_cancel] PASS mode={current} resting={len(resting or ())}"
            f" {'cancelled' if current == MODE_ON else 'would_cancel'}={len(acted)}"
            + "".join(f" {k}={v}" for k, v in counts.items()),
            flush=True,
        )
    return {"status": "ok", "mode": current,
            "cancelled": len(acted) if current == MODE_ON else 0,
            "would_cancel": len(acted) if current == MODE_SHADOW else 0,
            **counts, "orders": acted}
