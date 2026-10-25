"""Kalshi MAKER pilot, LIVE: rest a bid instead of taking the ask -- behind `SYNDICATE_KALSHI_MAKER_PILOT`.

USER DECISION 2026-10-24 (relayed verbatim by coordinator 332cb014, lane maker-vs-taker-shadow):
"C: Small live pilot" -- "Tight-capped live pregame maker pilot on Kalshi now, against the
evidence". The evidence it is against: `.syndicate/findings_2026-10-24_maker_vs_taker_shadow.md`
(no cell beats taker out of sample; pregame fills ~45% resting to kickoff and save ~4-5% of stake;
in-play fills are adversely selected). The pilot exists to measure what the shadow could not.

NO NEW SELECTION. A pilot position is an existing live-plan Kalshi position that the executor was
about to TAKE; this module only changes how it is entered. Everything the plan, the event cap, the
per-order cap and `execution_guard.check_order` decided has already happened when `route` is asked.

OFF BY DEFAULT. A request is routed to maker only when ALL hold, re-read on every request:
  * `SYNDICATE_KALSHI_MAKER_PILOT` is `on` or `live` (absent / anything else = off);
  * the executor is live AND armed (`execution_mode() == live`, `live_execution_armed()`);
  * venue `kalshi`, and the game has not started: `commence_time` readable and at least
    `MIN_LEAD_MINUTES` ahead (pregame only -- no in-play resting bids, ever);
  * the venue will expire the order at kickoff: `kalshi_orders.kickoff_expiration` returns
    `kickoff`, which needs `SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF` on. The kickoff cancel is the
    second backstop, not the only one;
  * the pilot's OWN day spend + this order <= `SYNDICATE_KALSHI_MAKER_PILOT_DAY_DOLLARS`
    (default 10, and 10 is a CEILING the env cannot raise).
A request that fails any of these is NOT routed and goes on as a taker order exactly as before.
That is "not in the pilot", not a taker fallback: once a maker order is posted it is never
converted, re-priced or re-sent.

THE ORDER: stake `SYNDICATE_KALSHI_MAKER_PILOT_ORDER_DOLLARS` (default 5, ceiling 5 -- the $5
minimum), good-till-cancelled with `expiration_time` = commence, `post_only` (the venue refuses
rather than lets it take), at
    b = min(live bid + 1c, live ask - 1c)   on our leg, read from the venue at build time,
placed only if 0.01 <= b < ask. A book with no bid refuses at build (`no_live_price`), nothing
written, nothing taken. Reconcile books the fill; kickoff cancel / venue expiry end the rest.

DAY SPEND = the stake of today's (Central) pilot rows that are resting (`submitted`) or `filled`,
plus this process's own routes not yet visible in the (5 s cached) ledger read. An expired or
refused post spent nothing and releases its room.

ONE POST PER POSITION, EVER. A position with ANY pilot row (resting, filled, expired, refused) is
SKIPPED (`maker_pilot_held`) -- never re-posted, never taken. That is what "no re-price, no taker
fallback" means once the executor's next pass sees the position again. It holds only while the
switch is on: switch OFF and the executor is byte-for-byte what it was before this module, so a
position whose pilot post was refused may then be taken as usual. Switching off ends the pilot.

LEDGER: `execution_style = "maker_pilot"` on the row (`OrderRequest.execution_style`), so the cell
scorecard can split maker from taker. Log lines, all prefixed `[kalshi_maker_pilot] MAKER_PILOT`:
`ROUTE` (not routed: reason), `POST` (the send and its venue status), and from reconcile `FILL` /
`EXPIRE` (`execution_ledger.reconcile_live_orders`).
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import os
import time
from typing import Any, Callable, Mapping, Sequence

EXECUTION_STYLE = "maker_pilot"
DAY_DOLLARS_DEFAULT = 10.0
DAY_DOLLARS_CEILING = 10.0
ORDER_DOLLARS_DEFAULT = 5.0
ORDER_DOLLARS_CEILING = 5.0
MIN_LEAD_MINUTES = 10.0
TICK = 0.01
_ON = {"on", "live"}
_SPENDING = {"submitted", "filled"}
LEDGER_CACHE_S = 5.0
_cache: dict[str, Any] = {"at": None, "orders": []}
#: (idempotency_key, central day, stake) of every route this process made. Covers the gap between a
#: route and the cached ledger read seeing its row, so one pass cannot post past the day cap.
_routed_here: list[tuple[str, str, float]] = []


def pilot_switch_on() -> bool:
    return str(os.environ.get("SYNDICATE_KALSHI_MAKER_PILOT") or "").strip().lower() in _ON


def _dollars(env: str, default: float, ceiling: float) -> float:
    try:
        value = float(str(os.environ.get(env) or "").strip())
    except ValueError:
        return default
    if not (value > 0):
        return default
    return min(value, ceiling)


def day_budget_dollars() -> float:
    return _dollars("SYNDICATE_KALSHI_MAKER_PILOT_DAY_DOLLARS", DAY_DOLLARS_DEFAULT, DAY_DOLLARS_CEILING)


def order_dollars() -> float:
    return _dollars("SYNDICATE_KALSHI_MAKER_PILOT_ORDER_DOLLARS", ORDER_DOLLARS_DEFAULT, ORDER_DOLLARS_CEILING)


def pilot_enabled() -> bool:
    """Switch on AND the executor itself live and armed. Default False."""
    if not pilot_switch_on():
        return False
    from syndicate.features.shared.execution_ledger import LIVE, execution_mode, live_execution_armed

    return execution_mode() == LIVE and bool(live_execution_armed())


def _central_day(stamp: Any) -> str | None:
    from syndicate.features.shared.timezone import central_date_from_iso

    day = central_date_from_iso(stamp)
    return day.isoformat() if day else None


def day_spent(orders: Sequence[Mapping[str, Any]], day: str) -> float:
    total = 0.0
    for row in orders:
        if row.get("execution_style") != EXECUTION_STYLE or row.get("mode") != "live":
            continue
        if str(row.get("status") or "") not in _SPENDING:
            continue
        if _central_day(row.get("submitted_at")) != day:
            continue
        total += float(row.get("fill_stake_dollars") or row.get("requested_stake_dollars") or 0.0)
    return round(total, 2)


def _ledger_orders() -> list[Mapping[str, Any]]:
    from syndicate.features.shared.execution_ledger import _load

    now = time.monotonic()
    if _cache["at"] is None or now - _cache["at"] > LEDGER_CACHE_S:
        _cache["orders"] = list(_load().get("orders") or [])
        _cache["at"] = now
    return _cache["orders"]


def _key(request: Any) -> str:
    from syndicate.features.shared.execution_ledger import idempotency_key

    return idempotency_key(request)


def held_by_pilot(request: Any, orders: Sequence[Mapping[str, Any]]) -> bool:
    key = _key(request)
    if any(k == key for k, _d, _s in _routed_here):
        return True
    return any(row.get("idempotency_key") == key and row.get("execution_style") == EXECUTION_STYLE
               for row in orders)


def _spent_with_routes(orders: Sequence[Mapping[str, Any]], day: str) -> float:
    seen = {row.get("idempotency_key") for row in orders if row.get("execution_style") == EXECUTION_STYLE}
    extra = sum(stake for key, d, stake in _routed_here if d == day and key not in seen)
    return round(day_spent(orders, day) + extra, 2)


def _leg(request: Any) -> str:
    from pipeline.execute_portfolio import _kalshi_contract_side

    return _kalshi_contract_side(request)


def maker_price(request: Any, *, fetch: Callable[[str], Mapping[str, Any]] | None = None) -> float | None:
    """`min(bid + 1c, ask - 1c)` on our leg from the LIVE market, or None (refuses at build)."""
    from syndicate.features.shared.kalshi_client import dollars_to_probability

    if fetch is None:
        from syndicate.features.shared.kalshi_client import fetch_market as fetch
    ticker = str(getattr(request, "venue_ticker", "") or "").strip()
    if not ticker:
        return None
    result = fetch(ticker)
    if result.get("status") != "ok":
        print(f"[kalshi_maker_pilot] MAKER_PILOT PRICE_UNAVAILABLE ticker={ticker}"
              f" reason={result.get('reason')}", flush=True)
        return None
    market = result.get("market") or {}
    leg = _leg(request)
    bid = dollars_to_probability(market.get(f"{leg}_bid_dollars"))
    ask = dollars_to_probability(market.get(f"{leg}_ask_dollars"))
    if bid is None or ask is None or not (0.0 < bid < ask < 1.0):
        print(f"[kalshi_maker_pilot] MAKER_PILOT NO_BOOK ticker={ticker} leg={leg} bid={bid} ask={ask}",
              flush=True)
        return None
    price = round(min(bid + TICK, ask - TICK), 2)
    if not (TICK - 1e-9 <= price < ask - 1e-9):
        return None
    print(f"[kalshi_maker_pilot] MAKER_PILOT PRICE ticker={ticker} leg={leg} bid={bid} ask={ask} post={price}",
          flush=True)
    return price


class _Maker:
    """The request as the order body sees it: identical, plus post_only."""

    post_only = True

    def __init__(self, request: Any):
        self._r = request

    def __getattr__(self, name: str) -> Any:
        return getattr(self._r, name)


def maker_submitter(price_for: Callable[[Any], float | None] = maker_price):
    """A two-phase Kalshi adapter that posts at the maker price with post_only."""
    from syndicate.features.shared.kalshi_orders import kalshi_submitter

    base = kalshi_submitter(price_for)

    def _build(request):
        send = base.build(_Maker(request))

        def _send():
            # The row exists from here on (write-ahead), so the position is held and its stake counts.
            _routed_here.append((_key(request), _central_day(_dt.datetime.now(_dt.timezone.utc).isoformat()) or "",
                                 float(getattr(request, "requested_stake_dollars", 0.0) or 0.0)))
            result = send()
            print(f"[kalshi_maker_pilot] MAKER_PILOT POST ticker={getattr(request, 'venue_ticker', None)}"
                  f" stake={getattr(request, 'requested_stake_dollars', None)}"
                  f" status={result.get('status')} venue_status={result.get('venue_status')}"
                  f" order_id={result.get('venue_order_id')} commence={getattr(request, 'commence_time', None)}",
                  flush=True)
            return result

        return _send

    def _submit(request):
        return _build(request)()

    _submit.build = _build
    return _submit


HELD = "maker_pilot_held"


@dataclasses.dataclass(frozen=True)
class Routed:
    """`skip` set: place NOTHING for this position this pass (it already has a pilot row)."""

    request: Any
    submitter: Any
    skip: str | None = None


def _starts(request: Any) -> _dt.datetime | None:
    text = str(getattr(request, "commence_time", None) or "").strip()
    if not text:
        return None
    try:
        starts = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return starts if starts.tzinfo else starts.replace(tzinfo=_dt.timezone.utc)


def refusal(request: Any, *, now: _dt.datetime | None = None,
            orders: Sequence[Mapping[str, Any]] | None = None,
            enabled_fn: Callable[[], bool] = pilot_enabled) -> str | None:
    """Why this request is NOT routed to maker, or None when it is. Pure apart from the reads named."""
    from syndicate.features.shared.kalshi_orders import kickoff_expiration
    from syndicate.features.shared.timezone import central_today_iso

    if not enabled_fn():
        return "pilot_off"
    if str(getattr(request, "venue", "") or "").strip().lower() != "kalshi":
        return "not_kalshi"
    moment = now or _dt.datetime.now(_dt.timezone.utc)
    starts = _starts(request)
    if starts is None:
        return "no_commence_time"
    if starts - moment < _dt.timedelta(minutes=MIN_LEAD_MINUTES):
        return "not_pregame"
    expiry, why = kickoff_expiration(request, now=moment)
    if expiry is None:
        return f"no_kickoff_expiry:{why}"
    book = _ledger_orders() if orders is None else orders
    if held_by_pilot(request, book):
        return HELD
    day = _central_day(moment.isoformat()) or central_today_iso()
    spent = _spent_with_routes(book, day)
    if spent + order_dollars() > day_budget_dollars() + 1e-9:
        return f"pilot_day_cap:{spent:.2f}+{order_dollars():.2f}>{day_budget_dollars():.2f}"
    return None


def route(request: Any, *, now: _dt.datetime | None = None,
          orders: Sequence[Mapping[str, Any]] | None = None,
          enabled_fn: Callable[[], bool] = pilot_enabled,
          wrap: Callable[[Any], Any] | None = None) -> Routed | None:
    """The maker form of `request` and its adapter, or None (the request stays a taker order)."""
    why = refusal(request, now=now, orders=orders, enabled_fn=enabled_fn)
    if why == HELD:
        return Routed(request=request, submitter=None, skip=HELD)
    if why is not None:
        if why != "pilot_off":
            print(f"[kalshi_maker_pilot] MAKER_PILOT ROUTE routed=0 reason={why}"
                  f" ticker={getattr(request, 'venue_ticker', None)}", flush=True)
        return None
    if wrap is None:
        from syndicate.features.shared.execution_guard import guarded_submit as wrap
    routed = dataclasses.replace(request, requested_stake_dollars=order_dollars(),
                                 execution_style=EXECUTION_STYLE)
    print(f"[kalshi_maker_pilot] MAKER_PILOT ROUTE routed=1 ticker={getattr(request, 'venue_ticker', None)}"
          f" planned_stake={getattr(request, 'requested_stake_dollars', None)} stake={order_dollars():.2f}",
          flush=True)
    return Routed(request=routed, submitter=wrap(maker_submitter()))


def reconcile_line(row: Mapping[str, Any]) -> str | None:
    """`FILL` / `EXPIRE` for a pilot row whose status reconcile just changed, else None."""
    if row.get("execution_style") != EXECUTION_STYLE:
        return None
    to = str(row.get("to") or "")
    if to == "filled":
        kind = "FILL"
    elif to in {"rejected", "canceled", "cancelled", "expired"}:
        kind = "EXPIRE"
    else:
        return None
    return (f"[kalshi_maker_pilot] MAKER_PILOT {kind} key={row.get('idempotency_key')} ticker={row.get('ticker')}"
            f" {row.get('from')}->{to} venue_status={row.get('venue_status')!r}"
            f" contracts={row.get('contracts')} fill_price={row.get('fill_price')} fees={row.get('fees_dollars')}")
