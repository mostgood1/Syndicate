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


def held_as_taker(request: Any, orders: Sequence[Mapping[str, Any]]) -> bool:
    """The ledger already holds this position from a TAKER entry (resting or filled): the executor's
    own duplicate check will place nothing, so the pilot neither routes nor logs it. Measured on the
    fleet 2026-10-25 15:23Z: PUR@PSU, filled as taker before the pilot shipped, logged
    `ROUTE routed=1` every pass and then `duplicates=1`."""
    key = _key(request)
    return any(row.get("idempotency_key") == key and row.get("status") in _SPENDING for row in orders)


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
TAKER_HELD = "held_as_taker"
_QUIET = {"pilot_off", TAKER_HELD}


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
    if held_as_taker(request, book):
        return TAKER_HELD
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
        if why not in _QUIET:
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
    maker_cost, taker_cost = row.get("maker_fill_cost_dollars"), row.get("taker_fill_cost_dollars")
    role = ("maker" if (maker_cost or 0) > 0 and not (taker_cost or 0) > 0 else
            "TAKER" if (taker_cost or 0) > 0 and not (maker_cost or 0) > 0 else
            "mixed" if (maker_cost or 0) > 0 else "unknown")
    return (f"[kalshi_maker_pilot] MAKER_PILOT {kind} key={row.get('idempotency_key')} ticker={row.get('ticker')}"
            f" {row.get('from')}->{to} venue_status={row.get('venue_status')!r}"
            f" filled_as={role if kind == 'FILL' else '-'} maker_cost={maker_cost} taker_cost={taker_cost}"
            f" contracts={row.get('contracts')} fill_price={row.get('fill_price')} fees={row.get('fees_dollars')}")


# ------------------------------------------------------------------ the fair-move cancel
# USER DECISION 2026-10-31 ("Yes, build it", session 684b1d, lane maker-pilot-fair-cancel), on
# `.syndicate/findings_2026-10-31_maker_pilot_review.md`: over the first 10 pilot fills the consensus
# edge was +3.2pp at POST and +1.2pp at FILL, and 3 of 10 filled at NEGATIVE edge. A post that is never
# re-priced and rests up to ~40 h is a stale quote: it fills once the world has moved to the taker's
# side. So a resting post now lives only while the PLAN still wants it at the price it rests at.
#
# THE FAIR IS THE PLAN'S OWN. Every live Kalshi executor pass records each plan position at the TOP
# of its loop (`observe_plan_position`, before any gate) with the plan's current price and EV, both on
# market fair (#704). fair = P(price) x (1 + ev_pct/100), the same number the plan sized on; on the
# review's fills it matched the book consensus within ~1pp. Keyed by CONTRACT (ticker + our leg), not
# idempotency key: a post made 10-29 for a 10-31 game comes back in the 10-30 plan under a new key and
# is refused `held_other_slate` long before `route` -- recorded in `route`, as first built, it was
# never seen again and would have been cancelled as dropped.
#
# Two reasons to cancel, judged by `review_resting` from the executor's per-tick Kalshi reconcile
# (`pipeline/execute_portfolio`). NOT the stale pass: `cancel_stale_resting_orders` runs only from the
# worker's boot dump, when nothing has been seen -- hooked there, as first built, it was live and inert
# (0 passes over 13 reconciles, 2026-11-01 16:55-17:25Z):
#   * `edge_below_floor` -- the latest sighting's fair minus our resting price < the floor (+1pp);
#   * `plan_dropped`     -- a plan pass for the sighting's date or later ran PLAN_DROP_MARGIN_S after
#                           the last sighting without re-sending this position. Usually the edge at the
#                           ask fell below the plan's EV floor, which is the case this exists for.
# NO SIGHTING, NO CANCEL: after a restart nothing is known until the next pass re-sends the position.
# A cancel is never re-posted (the row stays, so `held_by_pilot` holds) and costs nothing at Kalshi.
# OFF WHEN ABSENT (user decision relayed 2026-10-31 from coordinator 332cb014: "behind a switch").
# `SYNDICATE_KALSHI_MAKER_PILOT_FAIR_CANCEL=on` turns it on; absent or anything else = rest-to-kickoff
# exactly as before, and nothing is cancelled. Sightings are recorded either way (a dict write), so
# turning it on needs no warm-up beyond the next plan pass.

EDGE_FLOOR_DEFAULT = 0.01
EDGE_FLOOR_CEILING = 0.10
PLAN_DROP_MARGIN_S = 300.0
#: contract ("ticker|leg") -> {"fair": float | None, "at": epoch s, "date": plan date} of the latest sighting.
_seen: dict[str, dict[str, Any]] = {}
#: plan date -> epoch s of the latest Kalshi request of that date to reach `route` (a pass happened).
_pass_at: dict[str, float] = {}


def fair_cancel_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_KALSHI_MAKER_PILOT_FAIR_CANCEL") or "").strip().lower() in _ON


def edge_floor() -> float:
    try:
        value = float(str(os.environ.get("SYNDICATE_KALSHI_MAKER_PILOT_EDGE_FLOOR") or "").strip())
    except ValueError:
        return EDGE_FLOOR_DEFAULT
    if not (0.0 <= value <= EDGE_FLOOR_CEILING):
        return EDGE_FLOOR_DEFAULT
    return value


def _probability(price: Any) -> float | None:
    """American odds (the plan's unit), or a probability / decimal price, -> P(our side)."""
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value >= 100:
        return 100.0 / (value + 100.0)
    if value <= -100:
        return -value / (-value + 100.0)
    if 0.0 < value < 1.0:
        return value
    if value > 1.0:
        return 1.0 / value
    return None


def plan_fair(request: Any) -> float | None:
    """The plan's fair on our side: P(requested_price) x (1 + ev_pct/100), or None (no EV on the row)."""
    prob = _probability(getattr(request, "requested_price", None))
    try:
        ev = float(getattr(request, "ev_pct", None))
    except (TypeError, ValueError):
        return None
    if prob is None or ev != ev:
        return None
    fair = prob * (1.0 + ev / 100.0)
    return round(fair, 4) if 0.0 < fair < 1.0 else None


def _epoch(now: _dt.datetime | None) -> float:
    return (now or _dt.datetime.now(_dt.timezone.utc)).timestamp()


def _leg_of(side: Any, market: Any, line: Any) -> str | None:
    """Our Kalshi leg, mapped with market and line like the order body (a spread is not a moneyline:
    DET@BKN `side=home` is the NO leg of the -DET14 contract)."""
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    try:
        return _side_to_kalshi(side, market, line)
    except Exception:
        return None


def _contract(ticker: Any, side: Any, market: Any, line: Any) -> str | None:
    leg = _leg_of(side, market, line)
    return f"{ticker}|{leg}" if ticker and leg else None


def note_plan_sighting(request: Any, *, now: _dt.datetime | None = None) -> None:
    """Record that the plan sent this Kalshi position now, at this fair."""
    contract = _contract(getattr(request, "venue_ticker", None), getattr(request, "side", None),
                         getattr(request, "market", None), getattr(request, "line", None))
    if contract is None:
        return
    at = _epoch(now)
    date = str(getattr(request, "selected_date", "") or "")
    _seen[contract] = {"fair": plan_fair(request), "at": at, "date": date}
    if date:
        _pass_at[date] = max(_pass_at.get(date, 0.0), at)


def observe_plan_position(request: Any) -> None:
    """The executor's hook, first thing for every live Kalshi plan position. Never raises."""
    try:
        if pilot_switch_on():
            note_plan_sighting(request)
    except Exception as exc:  # noqa: BLE001 -- a bookkeeping write must never cost an order
        print(f"[kalshi_maker_pilot] MAKER_PILOT SIGHTING_FAILED {type(exc).__name__}: {exc}", flush=True)


def _resting_leg_price(row: Mapping[str, Any]) -> float | None:
    """What we rest at on OUR leg."""
    leg = _leg_of(row.get("side"), row.get("market"), row.get("line"))
    if leg is None:
        return None
    try:
        value = float(row.get(f"{leg}_price"))
    except (TypeError, ValueError):
        return None
    return value if 0.0 < value < 1.0 else None


def review_resting(rows: Sequence[Mapping[str, Any]], *, now: _dt.datetime | None = None,
                   cancel: Callable[[Any], Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Cancel resting pilot posts the plan no longer supports. `rows` = reconcile's resting maker rows."""
    counts = {"rows": len(rows), "cancelled": 0, "failed": 0, "kept": 0, "unseen": 0, "no_fair": 0,
              "unreadable": 0}
    if not rows:
        return {"status": "ok", **counts, "orders": []}
    if not fair_cancel_enabled():
        print(f"[kalshi_maker_pilot] MAKER_PILOT FAIR_PASS off rows={len(rows)}", flush=True)
        return {"status": "off", **counts, "orders": []}
    if cancel is None:
        from syndicate.features.shared.kalshi_orders import cancel_order as cancel
    at, floor = _epoch(now), edge_floor()
    done: list[dict[str, Any]] = []
    for row in rows:
        key = row.get("idempotency_key")
        seen = _seen.get(_contract(row.get("ticker"), row.get("side"), row.get("market"), row.get("line")) or "")
        if seen is None:
            counts["unseen"] += 1
            continue
        resting = _resting_leg_price(row)
        fair = seen.get("fair")
        later = [t for d, t in _pass_at.items() if d >= seen["date"]]
        edge = round(fair - resting, 4) if fair is not None and resting is not None else None
        if later and max(later) > seen["at"] + PLAN_DROP_MARGIN_S:
            reason = "plan_dropped"
        elif fair is None:
            counts["no_fair"] += 1
            continue
        elif resting is None:
            counts["unreadable"] += 1
            continue
        elif edge < floor - 1e-9:
            reason = "edge_below_floor"
        else:
            counts["kept"] += 1
            continue
        print(f"[kalshi_maker_pilot] MAKER_PILOT FAIR_CANCEL key={key} ticker={row.get('ticker')}"
              f" reason={reason} fair={fair} resting={resting} edge={edge} floor={floor}"
              f" seen_age_s={at - seen['at']:.0f}", flush=True)
        result = cancel(row.get("order_id"))
        if result.get("status") != "ok":
            counts["failed"] += 1
            print(f"[kalshi_maker_pilot] MAKER_PILOT FAIR_CANCEL_FAILED key={key}"
                  f" reason={result.get('reason')} -- order left resting", flush=True)
            continue
        counts["cancelled"] += 1
        done.append({"idempotency_key": key, "ticker": row.get("ticker"), "reason": reason,
                     "fair": fair, "resting": resting, "edge": edge})
    print(f"[kalshi_maker_pilot] MAKER_PILOT FAIR_PASS rows={counts['rows']} cancelled={counts['cancelled']}"
          f" failed={counts['failed']} kept={counts['kept']} unseen={counts['unseen']}"
          f" no_fair={counts['no_fair']} unreadable={counts['unreadable']} floor={floor}"
          f" sightings={len(_seen)}", flush=True)
    return {"status": "ok", **counts, "orders": done}
