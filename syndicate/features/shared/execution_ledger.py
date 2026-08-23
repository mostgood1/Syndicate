"""Stage B -- the record of what was actually placed, and the seam that places it.

**PAPER BY DEFAULT.** `mode` is `paper` unless something explicitly says
otherwise, and the paper path and the live path are THE SAME CODE with one
boolean between them. That is the whole point of the stage: a paper harness that
differs structurally from the live one proves nothing about the live one, so
going live is a flag flip rather than a rewrite.

--------------------------------------------------------------------------
IDEMPOTENCY IS THE LOAD-BEARING PROPERTY, NOT A NICETY
--------------------------------------------------------------------------

The placer must never run inside `refresh-worker`: that service has a documented
OOM-kill history (110 kills on 2026-08-07) and restarts mid-job. A restart
between "order submitted" and "order recorded" double-places real money. So:

1. **Write-ahead.** The record is persisted BEFORE the submit call, never after.
   A crash therefore leaves an order in `submitted` with no result, which is a
   state that can be reconciled against the venue. A crash after an unrecorded
   submit leaves nothing, which cannot.
2. **A deterministic idempotency key**, derived from the position identity and
   the slate date -- so the same bet computed twice produces the same key and
   the second write is refused rather than duplicated.
3. **Refusal, not overwrite.** `record_order` returns the EXISTING record when
   the key is already present. A retry is a no-op by construction rather than by
   the caller remembering to check.

`learnings.md` is explicit about why the key must be an identity and not a
label: *"a wrongly resolved join prices a projection against a different human
being, which is worse at any stake than no bet."* The same reasoning with money
attached.

--------------------------------------------------------------------------
STORAGE -- and why this path carries NO DATE TOKEN
--------------------------------------------------------------------------

Measured 2026-08-22 on `red-d88bvljbc2fs73epfhhg`: the keyvalue store is at
36.6% of 268.4 MB with ~170 MB headroom and `persistenceMode: journal_snapshot`,
so it journals AND snapshots to disk -- it is not a pure cache. That is what
makes it an acceptable home for this at all, and it reverses the earlier reading
of 96% which would have forced a Postgres and a three-service `blueprint_sync`.

But `_default_keyvalue_ttl_seconds` hands any path containing a date token a
**10-day TTL**, and a record of money placed must not expire. So
`_ledger_path()` is deliberately date-free, and the date lives INSIDE each
record instead. `portfolio_settings.py` makes the same choice for the same
reason, and a test pins it.

**The consequence is that this is one growing document**, which is exactly the
shape that produced the 4.9GB-chunk incident `shadow_candidate_ledger.py`
documents. Three bounds, all enforced here rather than trusted to a caller:

- **Lean records only.** The fields needed to identify, place and later grade an
  order -- never the candidate's full payload, which is what made the other
  ledger's records large enough to matter.
- **A hard record cap** with LOUD trimming: `trimmed` rides on every write and
  the trim is logged. A ledger that silently forgets is worse than one that
  refuses to grow.
- **A size check before the write**, well under the store's 8MB refusal
  ceiling, so growth is reported while it is merely growing rather than
  discovered as an opaque connection reset.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from syndicate.features.shared.refresh_state_store import (
    read_json_file,
    reports_root,
    write_json_file,
)

PAPER = "paper"
LIVE = "live"

# Order lifecycle. `submitted` is the write-ahead state and is the one that
# matters: an order sitting in it after a restart was sent (or may have been)
# and its result is unknown, so it must be reconciled against the venue rather
# than retried.
STATUS_SUBMITTED = "submitted"
STATUS_FILLED = "filled"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"

# Bounds. See the storage note above.
_MAX_RECORDS = 5000
_WARN_BYTES = 2 * 1024 * 1024  # a quarter of the store's 8MB refusal ceiling

# Only these fields are persisted per order. Anything not named here does not
# reach the ledger, which is the bound that keeps a growing document small.
_LEAN_FIELDS = (
    "idempotency_key",
    "position_key",
    "selected_date",
    "mode",
    "venue",
    "sport",
    "event_id",
    "market",
    "segment",
    "side",
    "line",
    "player_name",
    "book",
    # THE MATCHUP, carried because a placed order has to stay readable after the
    # position leaves the plan. Measured 2026-08-22: 14 orders sat on
    # `/portfolio/paper` as `MLB batter_hits over betrivers -112` -- a row nobody
    # could identify as a bet, because the plan that named the player and the
    # teams had been rewritten by the next board build. The ledger is the
    # durable record; if it needs another artifact to be legible, it is not one.
    "home_team",
    "away_team",
    "commence_time",
    # THE RE-PRICING KEY. `clv_opening_ledger`'s identity for this market, so an
    # order can be joined back to the board -- for a live mark now, and for the
    # close later -- without reconstructing anything. `#505` is what
    # reconstruction costs: 4,560 `no_key_match` of 8,276.
    "opening_key",
    # The sport's own game id (MLB `gamePk`), needed to look up a live feed and
    # answer "is this bet winning". `event_id` is the odds-feed id and is not
    # interchangeable with it.
    "game_pk",
    "requested_price",
    "requested_stake_dollars",
    "submitted_at",
    "status",
    "fill_price",
    "fill_stake_dollars",
    "settled_at",
    "venue_order_id",
    "error",
)


class LedgerError(RuntimeError):
    """Raised only where continuing would risk placing money twice."""


@dataclass(frozen=True)
class OrderRequest:
    """One bet to place. Complete by construction -- no optionals on the fields
    that decide what gets placed, so a half-populated request cannot exist."""

    position_key: str
    selected_date: str
    venue: str
    sport: str
    event_id: str
    market: str
    side: str
    requested_price: float
    requested_stake_dollars: float
    line: float | None = None
    player_name: str | None = None
    book: str | None = None
    segment: str | None = None
    # Optional because orders placed before these existed have none, and an
    # absent matchup must read as absent rather than be invented. Everything
    # placed from here on carries them.
    home_team: str | None = None
    away_team: str | None = None
    commence_time: str | None = None
    opening_key: str | None = None
    game_pk: str | None = None


def execution_mode() -> str:
    """`paper` unless explicitly set to `live`.

    Any unrecognised value resolves to `paper`, and that direction is
    deliberate. The 2026-08-22 `SYNDICATE_REFRESH_STATE_BACKEND` incident is the
    counter-example: an unrecognised value there silently meant "local disk".
    Here the safe default is the one that spends no money, so a typo cannot
    switch this on.
    """
    raw = str(os.environ.get("SYNDICATE_EXECUTION_MODE") or "").strip().lower()
    return LIVE if raw == LIVE else PAPER


def live_execution_armed() -> bool:
    """A SECOND, independent switch for real money.

    Checked immediately before every submit rather than at startup. Two
    switches because one is a typo away from spending money, and because the
    kill switch has to be able to stop an in-flight slate, not just a restart.
    """
    raw = str(os.environ.get("SYNDICATE_EXECUTION_LIVE_ARMED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _ledger_path() -> Path:
    # NO DATE TOKEN -- see the module docstring. A dated path takes the store's
    # 10-day TTL and the record of what was placed would silently expire.
    return reports_root() / "intelligence" / "execution_ledger.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def idempotency_key(request: OrderRequest) -> str:
    """Deterministic, and an IDENTITY rather than a label.

    Keyed on the position identity plus the slate date and venue: the same bet
    computed twice yields the same key, so the second write is refused. The
    PRICE is deliberately excluded -- a quote refresh must not look like a new
    order, or a slate that re-priced would place every bet again.
    """
    parts = [
        request.position_key,
        request.selected_date,
        request.venue,
        request.sport,
        request.event_id,
        request.market,
        request.side,
        "" if request.line is None else f"{float(request.line):g}",
        request.player_name or "",
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _load() -> dict[str, Any]:
    try:
        payload = read_json_file(_ledger_path())
    except Exception as exc:
        # A ledger we cannot READ must never be treated as an empty one -- that
        # would make every existing order look unplaced and invite a duplicate
        # of the entire slate. This is the one place the module refuses rather
        # than degrades.
        raise LedgerError(f"execution ledger unreadable: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, Mapping):
        return {"orders": [], "created_at": _utc_now()}
    orders = payload.get("orders")
    return {
        "orders": [dict(o) for o in orders if isinstance(o, Mapping)] if isinstance(orders, list) else [],
        "created_at": payload.get("created_at") or _utc_now(),
    }


def _persist(state: dict[str, Any]) -> dict[str, Any]:
    orders = state.get("orders") or []
    trimmed = 0
    if len(orders) > _MAX_RECORDS:
        trimmed = len(orders) - _MAX_RECORDS
        # Oldest out. Reported, never silent -- a ledger that quietly forgets is
        # worse than one that refuses to grow, because the gap is invisible.
        orders = orders[-_MAX_RECORDS:]
        state["orders"] = orders
        print(
            f"[execution_ledger] TRIMMED dropped={trimmed} kept={len(orders)} cap={_MAX_RECORDS}",
            flush=True,
        )
    state["updated_at"] = _utc_now()
    serialized = json.dumps(state, separators=(",", ":"))
    size = len(serialized.encode("utf-8", errors="replace"))
    if size >= _WARN_BYTES:
        print(
            f"[execution_ledger] SIZE_WARNING bytes={size} warn_at={_WARN_BYTES} "
            f"orders={len(orders)} -- the store refuses at 8MB",
            flush=True,
        )
    write_json_file(_ledger_path(), state)
    state["trimmed"] = trimmed
    return state


def find_order(key: str) -> dict[str, Any] | None:
    for order in _load().get("orders") or []:
        if order.get("idempotency_key") == key:
            return order
    return None


def record_order(request: OrderRequest, *, mode: str | None = None) -> tuple[dict[str, Any], bool]:
    """WRITE-AHEAD. Persist the order as `submitted` BEFORE anything is sent.

    Returns `(record, created)`. `created` is False when the key already
    existed, in which case the EXISTING record comes back untouched -- a retry
    is a no-op by construction rather than by the caller remembering to check.
    """
    key = idempotency_key(request)
    state = _load()
    for order in state.get("orders") or []:
        if order.get("idempotency_key") == key:
            return order, False

    record = {
        "idempotency_key": key,
        "position_key": request.position_key,
        "selected_date": request.selected_date,
        "mode": (mode or execution_mode()),
        "venue": request.venue,
        "sport": request.sport,
        "event_id": request.event_id,
        "market": request.market,
        "side": request.side,
        "line": request.line,
        "player_name": request.player_name,
        "book": request.book,
        "segment": request.segment,
        "home_team": request.home_team,
        "away_team": request.away_team,
        "commence_time": request.commence_time,
        "opening_key": request.opening_key,
        "game_pk": request.game_pk,
        "requested_price": request.requested_price,
        "requested_stake_dollars": request.requested_stake_dollars,
        "submitted_at": _utc_now(),
        "status": STATUS_SUBMITTED,
        "fill_price": None,
        "fill_stake_dollars": None,
        "settled_at": None,
        "venue_order_id": None,
        "error": None,
    }
    state.setdefault("orders", []).append({k: record[k] for k in _LEAN_FIELDS})
    _persist(state)
    return record, True


def complete_order(
    key: str,
    *,
    status: str,
    fill_price: float | None = None,
    fill_stake_dollars: float | None = None,
    venue_order_id: str | None = None,
    error: str | None = None,
) -> dict[str, Any] | None:
    """Close out a write-ahead record with what actually happened."""
    state = _load()
    updated = None
    for order in state.get("orders") or []:
        if order.get("idempotency_key") != key:
            continue
        order["status"] = status
        order["fill_price"] = fill_price
        order["fill_stake_dollars"] = fill_stake_dollars
        order["venue_order_id"] = venue_order_id
        order["error"] = error
        order["settled_at"] = _utc_now()
        updated = dict(order)
        break
    if updated is not None:
        _persist(state)
    return updated


def place_order(
    request: OrderRequest,
    *,
    submit: Callable[[OrderRequest], dict[str, Any]] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """The one seam money goes through. Same code in paper and in live.

    Order of operations is the whole safety argument and does not vary by mode:
    record first, submit second, complete third. `submit` is only ever called
    for an order this call newly created -- an already-recorded key returns its
    existing record without touching the venue.
    """
    resolved_mode = mode or execution_mode()
    record, created = record_order(request, mode=resolved_mode)
    if not created:
        return record

    if resolved_mode != LIVE:
        # PAPER: the fill is the price that was available at decision time.
        # Same shape as a real fill so nothing downstream can tell them apart
        # except by `mode`, which is what makes the paper run evidence about
        # the live one.
        return complete_order(
            record["idempotency_key"],
            status=STATUS_FILLED,
            fill_price=request.requested_price,
            fill_stake_dollars=request.requested_stake_dollars,
            venue_order_id=None,
        ) or record

    # LIVE. Both switches, checked here rather than at startup so the kill
    # switch can stop an in-flight slate.
    if not live_execution_armed():
        return complete_order(
            record["idempotency_key"],
            status=STATUS_REJECTED,
            error="live mode requested but SYNDICATE_EXECUTION_LIVE_ARMED is not set",
        ) or record
    if submit is None:
        return complete_order(
            record["idempotency_key"],
            status=STATUS_REJECTED,
            error="live mode requested with no venue adapter wired",
        ) or record

    try:
        result = submit(request) or {}
    except Exception as exc:
        # The order STAYS recorded and is marked failed rather than deleted. A
        # submit that raised may still have reached the venue, so the record is
        # the only thing that makes reconciliation possible.
        return complete_order(
            record["idempotency_key"],
            status=STATUS_FAILED,
            error=f"{type(exc).__name__}: {exc}",
        ) or record

    return complete_order(
        record["idempotency_key"],
        status=str(result.get("status") or STATUS_FILLED),
        fill_price=result.get("fill_price"),
        fill_stake_dollars=result.get("fill_stake_dollars"),
        venue_order_id=result.get("venue_order_id"),
    ) or record


def unreconciled_orders() -> list[dict[str, Any]]:
    """Orders left in the write-ahead state -- sent, or possibly sent, with an
    unknown result. A restart mid-submit produces exactly these, and they must
    be checked against the venue rather than retried."""
    return [
        order
        for order in _load().get("orders") or []
        if order.get("status") == STATUS_SUBMITTED
    ]


def ledger_summary(selected_date: str | None = None) -> dict[str, Any]:
    orders = _load().get("orders") or []
    if selected_date:
        orders = [o for o in orders if o.get("selected_date") == selected_date]
    by_status: dict[str, int] = {}
    staked = 0.0
    for order in orders:
        status = str(order.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        if status == STATUS_FILLED:
            try:
                staked += float(order.get("fill_stake_dollars") or 0.0)
            except (TypeError, ValueError):
                pass
    return {
        "selected_date": selected_date,
        "orders": len(orders),
        "by_status": dict(sorted(by_status.items())),
        "filled_stake_dollars": round(staked, 2),
        "modes": sorted({str(o.get("mode") or "unknown") for o in orders}),
        "unreconciled": sum(1 for o in orders if o.get("status") == STATUS_SUBMITTED),
    }
