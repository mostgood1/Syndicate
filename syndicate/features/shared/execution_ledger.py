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
    # THE VENUE'S OWN IDENTIFIER for the contract, stamped at decision time
    # rather than resolved at submit time. An exchange order names a ticker, and
    # re-deriving that ticker seconds before sending money means re-deriving it
    # from a catalogue that may have moved -- so the thing we priced and the
    # thing we buy could differ with nothing recording that they did.
    "venue_ticker",
    # HOW THE BET ACTUALLY WENT. Distinct from `status` (what the ORDER did at
    # the venue) and from `settled_at` (when the ORDER reached a terminal state,
    # stamped seconds after a paper fill and hours before the game ends).
    # Conflating those two is the reason `settled_count` read 0 while orders
    # were filling normally: nothing had ever graded a WAGER.
    "outcome",
    "pnl_dollars",
    "settled_value",
    "graded_at",
    "requested_price",
    "requested_stake_dollars",
    "submitted_at",
    "status",
    "fill_price",
    "fill_stake_dollars",
    "fees_dollars",
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
    # The venue's contract id (a Kalshi ticker). Optional because every order
    # placed so far is on paper against an aggregator, where there is no such
    # thing; required by the Kalshi adapter, which refuses by name without it.
    venue_ticker: str | None = None


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
    orders = state.get("orders") or []
    for index, order in enumerate(orders):
        if order.get("idempotency_key") != key:
            continue
        if str(order.get("status") or "") != STATUS_REJECTED:
            return order, False
        # A REJECTED ORDER NEVER REACHED THE VENUE, so re-attempting it cannot
        # double anything -- and refusing to is how a transient refusal becomes
        # permanent. Measured 2026-08-24T12:46Z: the Zebby Matthews order was
        # correctly reclassified `rejected` after the dead-route 410, its $1.58
        # was released, and the very next tick still reported
        # `placed=0 duplicates=1` -- because the RECORD still existed. Freeing
        # the budget without freeing the retry is half a fix.
        #
        # Only `rejected`. `filled`, `submitted` and `failed` all mean the
        # venue may hold this order, and re-sending any of them is how one bet
        # becomes two.
        orders.pop(index)
        state["orders"] = orders
        break

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
        "venue_ticker": request.venue_ticker,
        # Ungraded until something grades it. `None` rather than absent so the
        # field is present on every record and a summary cannot mistake "no such
        # key" for "not settled yet".
        "outcome": None,
        "pnl_dollars": None,
        "settled_value": None,
        "graded_at": None,
        "requested_price": request.requested_price,
        "requested_stake_dollars": request.requested_stake_dollars,
        "submitted_at": _utc_now(),
        "status": STATUS_SUBMITTED,
        "fill_price": None,
        "fill_stake_dollars": None,
        # Present from creation so a summary cannot mistake "no such key" for
        # "no fee" -- the same reason `outcome` is None rather than absent.
        # Filled in by reconciliation from the venue's own charge.
        "fees_dollars": None,
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
        #
        # UNLESS THE ADAPTER SAYS IT NEVER GOT THERE. An adapter can raise
        # before sending anything -- a stake below one contract, a price out of
        # range, no venue price at all -- and it marks those `venue_contacted =
        # False`. Those are REJECTED, which is the status for a refusal made
        # without a venue call: not charged against the day's budget, and not
        # blocking the next run as unreconciled.
        #
        # The distinction is not cosmetic. Measured 2026-08-24T00:34Z: two
        # orders that never left the process were recorded `failed` and charged
        # $7.02 against a $40 daily cap. A systematic build error would have
        # spent an entire day's budget without one request reaching Kalshi, and
        # the day would have ended looking like it had traded.
        #
        # Default is TRUE -- an exception that says nothing about whether it
        # sent is treated as though it might have.
        contacted = bool(getattr(exc, "venue_contacted", True))
        return complete_order(
            record["idempotency_key"],
            status=STATUS_FAILED if contacted else STATUS_REJECTED,
            error=f"{type(exc).__name__}: {exc}",
        ) or record

    return complete_order(
        record["idempotency_key"],
        status=str(result.get("status") or STATUS_FILLED),
        fill_price=result.get("fill_price"),
        fill_stake_dollars=result.get("fill_stake_dollars"),
        venue_order_id=result.get("venue_order_id"),
    ) or record


def execution_state_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    # NO DATE TOKEN: a date-tokened path takes the keyvalue store's 10-day TTL,
    # and this must survive a quiet week. Same choice as the ledger itself.
    return reports_root() / "intelligence" / "execution_state.json"


def record_execution_state(*, recorded_by: str) -> dict[str, Any]:
    """Stamp THIS process's execution switches and caps where web can read them.

    THE WEB SERVICE CANNOT ANSWER THIS QUESTION. The switches and the caps are
    environment variables on the WORKER; the web process has none of them, so
    reading its own env reports `mode=paper armed=no job=off` and the DEFAULT
    caps -- all true of web, and all worthless to a person looking at a live
    book. Measured 2026-08-24: `/portfolio/live` showed "LIVE MODE OFF" and
    "$25 per order / $100 a day" while the worker was live, armed, and capped
    at $10 and $40.

    This is the identical defect the paper page had in August, when it printed
    "COMMIT JOB off" beside filled orders it had just rendered. The fix there
    was for the worker to stamp `job_state` into the plan and for the page to
    say which source it was showing; this is that fix for the live surface.

    Written on every execution tick rather than at boot, so `recorded_at` is
    also a heartbeat: state from forty minutes ago is not current state, and
    the page can say so instead of presenting it as now.
    """
    from syndicate.features.shared.execution_guard import kill_switch_engaged, limits
    from syndicate.features.shared.refresh_state_store import write_json_file
    from pipeline.execute_portfolio import execution_enabled

    try:
        switch = kill_switch_engaged()
    except Exception as exc:
        # Fail closed, and say why -- an unreadable switch is an engaged one.
        switch = {"engaged": True, "source": "read_failed", "detail": type(exc).__name__}

    mode = execution_mode()
    state = {
        "recorded_by": str(recorded_by),
        "recorded_at": _utc_now(),
        "execution_mode": mode,
        "live_armed": live_execution_armed(),
        "execution_enabled": execution_enabled(),
        "kill_switch": switch,
        "limits": limits(mode),
        "venue": str(os.environ.get("SYNDICATE_EXECUTION_VENUE") or "").strip(),
    }
    try:
        write_json_file(execution_state_path(), state)
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    return {"status": "ok", **state}


def read_execution_state() -> dict[str, Any] | None:
    """The worker's stamped state, or None if it has never written one.

    None is a real answer and the caller must render it as "we do not know",
    never as "off" -- those license opposite actions.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file

    try:
        state = read_json_file(execution_state_path())
    except Exception:
        return None
    return state if isinstance(state, dict) and state.get("recorded_at") else None


def reclassify_presend_failures() -> dict[str, Any]:
    """Correct orders recorded `failed` that never reached the venue.

    NOT A DELETE, AND DELIBERATELY SO. The two rows this exists for are real
    events: the system decided to bet, built an order, and the builder refused
    it before any request was sent. That happened, and a ledger that forgets it
    stops being a record -- the same reason a graded bet is never re-graded.

    What is WRONG is the status. `failed` means "may have reached the venue",
    so `spent_today` charges it and `unreconciled_orders` can block the next
    live run. `rejected` is the status for a refusal made without a venue call.
    The code now records this correctly (adapters raise with
    `venue_contacted = False`), but rows written before that fix carry the old
    status and keep charging a budget nothing spent -- $7.02 of a $40 daily cap
    on 2026-08-24, for two orders that never left the process.

    NARROW ON PURPOSE. Only `failed` rows whose error names a build error are
    touched, because that prefix is itself the proof no request was sent -- it
    is raised while assembling the order. Anything else keeps the conservative
    reading: a status we cannot prove is safe stays `failed`.

    Idempotent -- a corrected row is no longer `failed`, so a second call is a
    no-op. Returns what it changed, including the zero.
    """
    state = _load()
    changed: list[dict[str, Any]] = []
    for order in state.get("orders") or []:
        if str(order.get("status") or "") != STATUS_FAILED:
            continue
        error = str(order.get("error") or "")
        # The prefix IS the evidence. `OrderBuildError` is raised before the
        # request is assembled, so it cannot have reached a venue.
        #
        # A 410 on a DEPRECATED ENDPOINT is the same kind of proof from the
        # other end: the route is gone, so nothing was created behind it.
        # Measured 2026-08-24T08:01Z -- a real, correctly built order (Zebby
        # Matthews under 4.5 strikeouts, $1.58) died there, and because the
        # ledger records it `failed` it can never be retried: `place_order`
        # finds the key, returns the record, and never contacts the venue.
        # A dead route would otherwise poison every position it touched,
        # permanently, and charge the day's budget for each one.
        #
        # NARROW ON PURPOSE. Only this code, not 4xx or 5xx generally -- a 500
        # may well have been processed, and a status we cannot prove is safe
        # stays `failed`.
        recoverable = error.startswith("OrderBuildError:") or (
            "http_410" in error and "deprecated_v1_order_endpoint" in error
        )
        if not recoverable:
            continue
        order["status"] = STATUS_REJECTED
        order["reclassified_at"] = _utc_now()
        # The original status is kept rather than overwritten silently: a
        # correction nobody can see is indistinguishable from a rewrite.
        order["reclassified_from"] = STATUS_FAILED
        changed.append(
            {
                "idempotency_key": order.get("idempotency_key"),
                "selected_date": order.get("selected_date"),
                "stake_dollars": order.get("requested_stake_dollars"),
                "error": error,
            }
        )

    if changed:
        _persist(state)
    return {"status": "ok", "reclassified": len(changed), "orders": changed}


def _requested_contracts(order: Mapping[str, Any]) -> int | None:
    """How many contracts the stake could have bought, at the price we asked.

    The upper bound on any honest fill. Derived rather than stored because the
    ledger records dollars and a price, not a count -- `contracts_for_stake`
    does this same floor at order-build time, and this must agree with it.
    """
    from syndicate.features.shared.kalshi_orders import contracts_for_stake

    try:
        stake = float(order.get("requested_stake_dollars") or 0.0)
        price = float(order.get("requested_price") or 0.0)
    except (TypeError, ValueError):
        return None
    if stake <= 0 or not 0.0 < price < 1.0:
        # An American-odds price (or none at all) means this is not a Kalshi
        # order priced in probability dollars, and the bound cannot be
        # computed. No bound is better than a wrong one.
        return None
    try:
        return contracts_for_stake(stake, price)
    except Exception:
        return None


def _venue_reader(venue: str):
    """The read side of a venue adapter. Only Kalshi has one."""
    if str(venue or "").strip().lower().startswith("kalshi"):
        from syndicate.features.shared.kalshi_orders import fetch_orders, venue_order_view

        return fetch_orders, venue_order_view
    return None, None


def reconcile_live_orders(*, limit: int = 100, venue: str = "kalshi") -> dict[str, Any]:
    """Correct the live ledger from what the VENUE says, not from what we sent.

    ------------------------------------------------------------------
    WHY THIS EXISTS AND WHY IT IS NOT OPTIONAL
    ------------------------------------------------------------------

    A submit response describes the moment of submission. It cannot describe
    what the order did afterwards, and a limit order's whole point is that it
    does something afterwards. Two failures follow from treating the submit as
    the final word, and we have now had one of each:

    1. MEASURED 2026-08-24T13:12Z -- our ledger read `filled` for an order
       Kalshi showed as resting with `Filled: 0`. Found by the USER looking at
       the Kalshi UI. No log said anything was wrong, because from inside the
       process nothing was: we had recorded exactly what we decided to record.
    2. The mirror image, which has not bitten yet and will: an order correctly
       recorded `submitted`, which FILLS an hour later. Settlement never grades
       it, P&L never books it, and the position is real the entire time.

    Neither is fixable by writing the submit path more carefully. Both need a
    second read.

    ------------------------------------------------------------------
    THE VENUE IS THE AUTHORITY -- BUT ONLY WHEN IT ANSWERS
    ------------------------------------------------------------------

    A FETCH FAILURE MUST NEVER MODIFY A RECORD. Absence in a failed read is not
    absence at the venue, and the difference is a live position deleted out of
    our own books. So: a failed fetch returns an error and changes nothing; an
    order missing from a SUCCESSFUL read is counted `not_found` and still
    changes nothing, because the list is capped at `limit` and an older order
    legitimately ages out of it. Only a positive statement about a specific
    order can move that order.

    `unknown` is treated the same way. A venue status we have never mapped is
    not evidence in either direction, and guessing is what produced (1).

    Idempotent: a second pass over unchanged orders reports zero changes.
    """
    fetch, view = _venue_reader(venue)
    if fetch is None:
        return {"status": "skipped", "reason": f"no_reader_for_venue:{venue}"}

    state = _load()
    orders = state.get("orders") or []
    candidates = [
        o
        for o in orders
        if str(o.get("mode") or "") == LIVE
        and str(o.get("status") or "") in (STATUS_SUBMITTED, STATUS_FILLED)
        and o.get("outcome") is None
        and str(o.get("venue") or "").strip().lower().startswith(str(venue).strip().lower())
    ]
    if not candidates:
        return {"status": "ok", "candidates": 0, "changed": 0, "orders": []}

    read = fetch(limit=limit)
    if read.get("status") != "ok":
        # Reported, not raised, and NOTHING WRITTEN. The caller is a periodic
        # loop; a venue that is briefly unreachable must leave the ledger
        # exactly as it found it.
        print(
            f"[execution_ledger] RECONCILE_READ_FAILED venue={venue}"
            f" candidates={len(candidates)} reason={read.get('reason')}",
            flush=True,
        )
        return {
            "status": "error",
            "reason": read.get("reason"),
            "candidates": len(candidates),
            "changed": 0,
        }

    by_client: dict[str, dict[str, Any]] = {}
    by_venue_id: dict[str, dict[str, Any]] = {}
    for raw in read.get("orders") or []:
        seen = view(raw)
        client = str(seen.get("client_order_id") or "").strip()
        if client:
            by_client[client] = seen
        venue_id = str(seen.get("order_id") or "").strip()
        if venue_id:
            by_venue_id[venue_id] = seen

    changed: list[dict[str, Any]] = []
    not_found = 0
    unknown = 0
    implausible = 0

    for order in candidates:
        key = str(order.get("idempotency_key") or "")
        # OUR key first. `client_order_id` IS the idempotency key by
        # construction, so it matches even for an order whose submit response
        # was lost and whose venue id we therefore never learned -- the case
        # the write-ahead record exists for.
        seen = by_client.get(key) or by_venue_id.get(str(order.get("venue_order_id") or ""))
        if seen is None:
            not_found += 1
            continue

        venue_state = seen.get("state")
        if venue_state == "unknown":
            unknown += 1
            print(
                f"[execution_ledger] RECONCILE_UNKNOWN_STATUS key={key}"
                f" venue_status={seen.get('venue_status')!r} -- left untouched",
                flush=True,
            )
            continue

        before = str(order.get("status") or "")
        if venue_state == "filled":
            contracts = seen.get("filled_count")

            # A FILL CANNOT BE LARGER THAN THE ORDER. `fill_count_fp` carries
            # an undocumented `_fp` suffix -- if it turns out to be a
            # fixed-point scale rather than a plain count, a 2-contract fill
            # arrives as some large number and booking it claims a position
            # orders of magnitude beyond anything the stake could buy.
            #
            # This invariant holds whatever `_fp` means, and is worth keeping
            # once it is known: no venue can fill more than was asked for, so a
            # count that exceeds the request is a PARSE failure, never a trade.
            # Refused by name and left untouched, in the same spirit as
            # `unknown` -- a number we cannot believe must not become a
            # position, and must not silently become zero either.
            requested_contracts = _requested_contracts(order)
            if (
                contracts is not None
                and requested_contracts is not None
                and contracts > requested_contracts
            ):
                implausible += 1
                print(
                    f"[execution_ledger] RECONCILE_COUNT_IMPLAUSIBLE key={key}"
                    f" venue_count={contracts} requested={requested_contracts}"
                    " -- left untouched; check the `_fp` unit",
                    flush=True,
                )
                continue

            after = STATUS_FILLED
            # The venue's own fill price where it gave one, ours where it did
            # not. Never the requested price when the venue disagrees with it:
            # a fill at a better price is money we would otherwise not book.
            price = seen.get("fill_price")
            if price is None:
                price = order.get("fill_price")
            if price is None:
                price = order.get("requested_price")

            # WHAT KALSHI BILLED, in preference to what we can reconstruct.
            # `count * price` was always arithmetic over two numbers we parsed;
            # `taker_fill_cost_dollars + maker_fill_cost_dollars` is the charge
            # itself.
            stake = seen.get("fill_cost_dollars")
            if stake is None and contracts is not None and price is not None:
                try:
                    stake = round(int(contracts) * float(price), 2)
                except (TypeError, ValueError):
                    stake = None
            new_fields = {
                "status": after,
                "fill_price": price,
                "fill_stake_dollars": stake,
                "contracts": contracts,
                # FEES ARE REAL MONEY AND WERE MODELLED AS ZERO EVERYWHERE.
                # Kalshi took $0.02 on a $1.08 fill -- ~1.9%, against edges
                # this system will happily act on at 3%. They arrive on every
                # order read (`taker_fees_dollars`, `maker_fees_dollars`), so
                # the only reason they were absent from the ledger is that
                # nothing carried them across.
                "fees_dollars": seen.get("fees_dollars"),
                "error": None,
            }
        elif venue_state == "resting":
            # THE PHANTOM-FILL REPAIR. The order exists and has traded nothing,
            # so every fill field on it is a number nobody should believe.
            after = STATUS_SUBMITTED
            new_fields = {
                "status": after,
                "fill_price": None,
                "fill_stake_dollars": None,
                "contracts": 0,
                # Nothing traded, so nothing was charged. Left as None rather
                # than 0.0: "no fee because no fill" and "a fill that cost
                # nothing" are different claims.
                "fees_dollars": None,
            }
        else:  # dead
            # Cancelled or expired with nothing filled: no exposure, no
            # position, and the idempotency key is free again. `rejected` is
            # the status that means exactly that, and it releases the budget
            # this order has been charging.
            after = STATUS_REJECTED
            new_fields = {
                "status": after,
                "fill_price": None,
                "fill_stake_dollars": None,
                "contracts": 0,
                "fees_dollars": None,
                "error": f"venue_{seen.get('venue_status') or 'dead'}",
            }

        stamp = {
            **new_fields,
            "venue_status": seen.get("venue_status"),
            "venue_order_id": seen.get("order_id") or order.get("venue_order_id"),
            "reconciled_at": _utc_now(),
        }
        # Only a REAL difference counts as a change. Re-stamping an unchanged
        # row every tick would make the log say work happened on every pass and
        # make "did anything move" unanswerable.
        moved = any(order.get(field) != value for field, value in new_fields.items())
        order.update(stamp)
        if not moved:
            continue
        if before != after:
            order["reconciled_from"] = before
        changed.append(
            {
                "idempotency_key": key,
                "ticker": order.get("venue_ticker"),
                "from": before,
                "to": after,
                "venue_status": seen.get("venue_status"),
                "contracts": order.get("contracts"),
                "fill_price": order.get("fill_price"),
                "fees_dollars": order.get("fees_dollars"),
            }
        )

    if changed:
        _persist(state)
        for row in changed:
            print(
                f"[execution_ledger] RECONCILED key={row['idempotency_key']}"
                f" ticker={row['ticker']} {row['from']}->{row['to']}"
                f" venue_status={row['venue_status']!r}"
                f" contracts={row['contracts']} fill_price={row['fill_price']}"
                f" fees={row['fees_dollars']}",
                flush=True,
            )
    print(
        f"[execution_ledger] RECONCILE venue={venue} candidates={len(candidates)}"
        f" venue_orders={len(read.get('orders') or [])} changed={len(changed)}"
        f" not_found={not_found} unknown={unknown} implausible={implausible}",
        flush=True,
    )
    return {
        "status": "ok",
        "candidates": len(candidates),
        "changed": len(changed),
        "not_found": not_found,
        "unknown": unknown,
        "implausible": implausible,
        "orders": changed,
    }


def _float_env(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    # Non-positive is read as a typo rather than as "zero window". A zero here
    # would mean every reconciliation is instantly stale, i.e. the exact
    # behaviour the setting exists to change, reached by fat-fingering it.
    return value if value > 0 else default


def _reconciled_recently(order: Mapping[str, Any], *, within_seconds: float) -> bool:
    stamp = str(order.get("reconciled_at") or "").strip()
    if not stamp:
        return False
    try:
        seen = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - seen).total_seconds() <= within_seconds


def unreconciled_orders() -> list[dict[str, Any]]:
    """Orders whose result is UNKNOWN -- sent, or possibly sent, with nothing
    since. A restart mid-submit produces exactly these, and they must be
    checked against the venue rather than retried.

    A RESTING ORDER WE HAVE JUST READ FROM THE VENUE IS NOT ONE OF THESE, and
    the distinction is load-bearing. `submitted` carries two meanings that look
    identical in the ledger: "we do not know what happened" and "we know
    precisely what happened -- it is sitting on the book unfilled". The first
    must block a new live slate, because placing on top of it risks doubling.
    The second must not, or the first limit order that rests for an afternoon
    jams live execution until someone edits the ledger by hand.

    `reconcile_live_orders` is what tells them apart, and its stamp is what is
    read here. The freshness window matters: a reconciliation from yesterday
    says nothing about now, so a stale stamp falls back to blocking. Blocking
    is the safe direction and stays the default for everything this cannot
    positively account for.
    """
    window = _float_env("SYNDICATE_EXECUTION_RECONCILE_FRESH_SECONDS", 900.0)
    return [
        order
        for order in _load().get("orders") or []
        if order.get("status") == STATUS_SUBMITTED
        and not _reconciled_recently(order, within_seconds=window)
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
