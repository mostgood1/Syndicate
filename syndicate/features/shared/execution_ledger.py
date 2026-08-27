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
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence
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
    # the venue) and from `venue_resolved_at` (when the SUBMIT resolved --
    # stamped ~400ms after submitting, hours before the game ends).
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
    # WHEN THE SUBMIT RESOLVED -- the write-ahead record being closed with a
    # venue response. NOT when the bet was decided. Grading is `outcome` +
    # `graded_at`, and `paper_settlement` exists because that distinction was
    # lost once already ("`settled_count` has been 0 for as long as it has been
    # reported ... Nobody had written the grader").
    "venue_resolved_at",
    # DEPRECATED MIRROR of `venue_resolved_at`, kept only so stored rows and any
    # outside reader keep working. NOTHING IN THIS REPO READS IT -- verified by
    # grep 2026-08-26 -- and its sole measurable effect has been to mislead: a
    # peer session reading `settled_at` populated 400ms after `submitted_at` on
    # four OPEN orders reasonably concluded settlement was being faked, and
    # proposed it as the root cause of positions not reconciling. It was not; a
    # settlement sweep cannot be fooled by a field it never reads
    # (`settle_orders` keys on `outcome` and `status == "filled"`).
    #
    # A name that needs a warning in two module docstrings to defuse, and still
    # catches a careful reader with the source open, is not a documentation
    # problem. Write both, read neither, retire the liar.
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


# A `failed` order the venue refused BECAUSE IT WAS NOT TRADING AT ALL.
#
# `failed` is normally terminal, and the comment in `record_order` says exactly
# why: the venue may hold the order, so re-sending is how one bet becomes two.
# That reasoning is about UNCERTAINTY, and these two codes remove it. A 409
# `exchange_is_paused` / `trading_is_paused` is the exchange stating it accepted
# nothing from anyone -- no contract exists, no money moved, and the next tick
# can safely ask again. It is the same epistemic position as `rejected`, which
# is already freed for retry.
#
# MEASURED 2026-08-27: 5 live Kalshi orders died this way in one day, all
# terminal, none retried. The market was fine, the price was fine and the
# balance was fine -- the exchange was briefly paused and the candidate was
# discarded permanently.
#
# DELIBERATELY NOT EVERY 4xx, though the budget path exempts all of them as
# refusals. `market_not_found` and `insufficient_balance` are also answers the
# venue gave, but re-asking cannot change either one, so retrying them would
# just burn a tick forever. Only transient EXCHANGE STATE belongs here; a code
# is added to this list when re-asking is capable of a different answer.
_RETRYABLE_VENUE_STATE = re.compile(
    r'"code"\s*:\s*"(exchange_is_paused|trading_is_paused)"', re.IGNORECASE
)


def _is_retryable_venue_pause(order: Mapping[str, Any]) -> bool:
    """`failed` only because the exchange was not trading. Safe to re-send."""
    if str(order.get("status") or "") != STATUS_FAILED:
        return False
    return bool(_RETRYABLE_VENUE_STATE.search(str(order.get("error") or "")))


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
        if str(order.get("status") or "") != STATUS_REJECTED and not _is_retryable_venue_pause(order):
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
        "venue_resolved_at": None,
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
        # BOTH, for now. The new name is the true one; the old is a mirror so
        # no stored row or outside consumer changes shape under them.
        resolved_at = _utc_now()
        order["venue_resolved_at"] = resolved_at
        order["settled_at"] = resolved_at
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


def _requested_contracts(order: Mapping[str, Any]) -> float | None:
    """How many contracts the stake could have bought, at the price we asked.

    The upper bound on any honest fill. Derived rather than stored because the
    ledger records dollars and a price, not a count -- `contracts_for_stake`
    does this same floor at order-build time, and this must agree with it.
    """
    try:
        stake = float(order.get("requested_stake_dollars") or 0.0)
    except (TypeError, ValueError):
        return None
    if stake <= 0:
        return None

    # THE PRICE MAY BE AMERICAN ODDS, AND USUALLY IS.
    #
    # This required `0 < price < 1` and returned None otherwise, with the
    # comment "no bound is better than a wrong one". That reasoning is right
    # and its effect was that the bound was NEVER COMPUTED for Polymarket --
    # every order there carries American odds (`requested_price=-108.0`), so
    # the guard returned None on the venue we actually trade. "A fill cannot be
    # larger than the order" was present, documented, and inert.
    #
    # Same shape as the slippage guard, which compared American odds against
    # probabilities and so refused on negative odds and passed silently on
    # positive ones. A guard that cannot read its input is not a guard.
    price = _price_as_probability(order.get("requested_price"))
    if price is None:
        return None

    # UNFLOORED, and deliberately not `contracts_for_stake`. That helper floors
    # to WHOLE contracts, which is right for Kalshi and wrong here: a real
    # 2.65-contract Polymarket fill against a floor of 2 would be refused as
    # `implausible` and left unbooked -- turning a guard against phantom
    # positions into a cause of missing real ones. `stake / price` is the true
    # upper bound at either venue, since a whole-contract fill is never more
    # than the fractional one.
    return stake / price


def _price_as_probability(value: Any) -> float | None:
    """A price as a probability, whether it arrived as odds or a probability.

    Both forms genuinely occur: the board stores American odds, the venues
    quote probability dollars. Magnitude decides -- a probability is strictly
    inside (0, 1) and American odds are conventionally at least 100 from zero.
    Anything between is AMBIGUOUS and returns None rather than being guessed,
    because a guessed unit here is a guessed bound.
    """
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    if 0.0 < parsed < 1.0:
        return parsed
    if abs(parsed) >= 100.0:
        from syndicate.features.shared.prophetx_client import american_to_probability

        return american_to_probability(parsed)
    return None


def _venue_reader(venue: str):
    """The read side of a venue adapter.

    POLYMARKET WAS MISSING AND THAT TOOK THE LIVE PATH DOWN. This said "Only
    Kalshi has one", so a Polymarket order recorded `submitted` could never be
    corrected -- and an unreconciled order blocks live mode on EVERY venue, not
    only its own. Measured 2026-08-25T16:40:00Z, from one resting Polymarket
    order:

        BLOCKED_ON_UNRECONCILED count=1 keys=['1984a57ed28e1cd5ccad8b16']
        EXECUTION status=blocked reason=unreconciled_orders scope=kalshi
        EXECUTION status=blocked reason=unreconciled_orders scope=polymarket

    A gap in the read side is not a missing feature; it is a latch. Nothing in
    the system could clear that state, because the only thing that clears it is
    a venue read that did not exist.
    """
    name = str(venue or "").strip().lower()
    if name.startswith("kalshi"):
        from syndicate.features.shared import kalshi_orders as adapter
    elif name.startswith("polymarket"):
        from syndicate.features.shared import polymarket_us_orders as adapter
    else:
        return None, None, "unknown"
    # THE COVERAGE COMES WITH THE READER, not from its result. A zero-candidate
    # pass has to decide whether an orphan scan is possible BEFORE it makes the
    # call -- asking a per-order reader for a list it does not have would 501
    # every cycle and turn "nothing to do" into a recurring error.
    return (
        adapter.fetch_orders,
        adapter.venue_order_view,
        getattr(adapter, "ORDER_READ_COVERAGE", "unknown"),
    )


# How far past the requested stake a fill may land before it is refused as a
# parse error. Generous on purpose: fees and rounding ride along in the venue's
# numbers, and the failure this bound exists to catch is a fixed-point scale
# error -- off by 100x or 1000x, never by 5%.
_FILL_DOLLAR_TOLERANCE = 1.25

# VENUE ROUNDING, not a real overfill. Kalshi sells whole contracts and
# Polymarket sells hundredths (`minimumTradeQty: 0.01`), so a venue count is
# reported to two decimals while ours is a raw quotient. One cent of a
# contract of slack costs nothing against a guard whose target is a 100x
# fixed-point scale error.
_FILL_COUNT_TOLERANCE = 0.01

# ABOVE THIS MULTIPLE OF THE STAKE, THE NUMBER IS A UNIT ERROR, NOT A FILL.
#
# The `_fp` scale worry this guard exists for is 100x or 1e6x. An overspend of
# 33% is a BAD FILL -- real, confirmed by the venue, and money that has already
# moved. Refusing to record it does not unwind it; it strands the order at
# `submitted` forever, understates exposure, and stops reconcile converging.
#
# Measured 2026-08-26T03:43:08Z, the fill that forced this split:
#
#   venue_count=30.46 fill_price=0.345 filled_dollars=10.5087
#   stake_ceiling=9.9 requested_stake=7.92
#
# The venue held it as ORDER_STATE_FILLED while our ledger showed $0.00 --
# `venue_orders=7 stamped=6 implausible=1`. The venue was right and the ledger
# was hiding a live position, which is the opposite of what a safety guard
# should do.
_FILL_DOLLAR_ABSURD = 10.0


# OUR IDEMPOTENCY KEYS, BY SHAPE. `idempotency_key` is
# `sha1(...).hexdigest()[:24]` -- 24 lowercase hex characters, no dashes.
#
# THIS EXISTS BECAUSE `bool(client_order_id)` WAS USED AS "IS THIS OURS", and it
# reported `orphans_ours=6` at 2026-08-26T15:21Z -- six positions of real money
# supposedly opened by this system and lost from the ledger. All six were
# `KXMVECROSSCATEGORY` PARLAYS, a series `kalshi_client._COMBINATORIAL_SERIES_PREFIXES`
# explicitly excludes because "the board does not bet parlays". This system has
# no code path that can place one. Their ids are UUID-shaped
# (`64643034-3834-3635-...`); ours are 24 bare hex characters.
#
# A field the venue lets ANY client set is not an identity claim on its own --
# the Kalshi app stamps one too. Six phantom missing positions, produced by the
# counter written to stop exactly that class of false alarm.
_OUR_KEY_LENGTH = 24
_HEX = frozenset("0123456789abcdef")


def _is_our_key(client_order_id: Any) -> bool:
    text = str(client_order_id or "").strip()
    return len(text) == _OUR_KEY_LENGTH and all(ch in _HEX for ch in text)


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
    fetch, view, declared_coverage = _venue_reader(venue)
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
    if not candidates and declared_coverage != "book":
        # NOTHING TO CORRECT AND NOTHING TO DISCOVER. A per-order reader can
        # only see the ids it is handed, and with no candidates there are none
        # -- the call would fall through to a list route this venue does not
        # implement and error every cycle.
        return {
            "status": "ok",
            "candidates": 0,
            "changed": 0,
            "orders": [],
            "coverage": declared_coverage,
            "orphans": None,
        }
    if not candidates:
        # A BOOK READER STILL READS. An empty ledger is the state where an
        # orphan is MOST dangerous, not least: nothing here is open, so nothing
        # would ever prompt a look, while the venue may be holding a live
        # position from a submit whose response we lost. Falling through to the
        # scan below costs one read and is the only thing that can find it.
        print(
            f"[execution_ledger] RECONCILE_ORPHAN_SCAN_ONLY venue={venue}"
            " candidates=0 -- reading the book anyway",
            flush=True,
        )

    # THE IDS WE HOLD, handed to the reader. Kalshi lists the whole book in one
    # call and ignores these; Polymarket publishes no list route at all --
    # `GET /v1/orders` answers `code: 12` UNIMPLEMENTED -- and reads one order
    # at a time via `GET /v1/order/{orderId}`. A reader that cannot be told
    # WHICH orders matter can only be a list reader, so the contract carries
    # them and each venue uses what it needs.
    #
    # A CANDIDATE WITH NO VENUE ID IS STILL A CANDIDATE. The submit response
    # can be lost -- that is the case the write-ahead record exists for -- and
    # such an order has no id to fetch by. It is simply absent from a per-order
    # read and counts `not_found`, which changes nothing. That is the correct
    # outcome and not a silent one: `not_found` is reported.
    read = fetch(
        limit=limit,
        order_ids=[
            str(o.get("venue_order_id") or "").strip()
            for o in candidates
            if str(o.get("venue_order_id") or "").strip()
        ],
    )
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
    stamped = 0
    resting: list[dict[str, Any]] = []

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

            # A FILL CANNOT BE LARGER THAN THE ORDER -- IN DOLLARS. `fill_count_fp`
            # carries an undocumented `_fp` suffix, and if that is a fixed-point
            # scale rather than a plain count, a 2-contract fill arrives as some
            # large number and booking it claims a position orders of magnitude
            # beyond anything the stake could buy. The guard against that is
            # worth keeping.
            #
            # BUT IT WAS BOUNDED IN CONTRACTS, AND CONTRACTS ARE NOT THE
            # INVARIANT. A better fill price buys MORE contracts for the same
            # money, which is price improvement -- the good outcome -- and this
            # read it as a parse failure. Measured 2026-08-25 6:50:34 PM
            # Central, and it halted all trading on BOTH venues:
            #
            #   RECONCILE_COUNT_IMPLAUSIBLE venue_count=5.82 requested=5.221
            #   BLOCKED_ON_UNRECONCILED count=1
            #   EXECUTION status=blocked reason=unreconciled_orders  (x2 venues)
            #
            # `over 6.5 TB@DET`, +127, $2.30. +127 is 0.4405, so $2.30 sized
            # 5.221 contracts. The venue filled at 0.395 -- $2.30 / 0.395 = 5.82.
            # Every number is correct and the order was refused for being
            # cheaper than planned.
            #
            # The DOLLAR bound catches the `_fp` scale error just as well (a
            # fixed-point count times any sane price blows past the stake by
            # orders of magnitude) without punishing a good fill. Tolerance is
            # generous because fees and rounding ride along; the failure this
            # guards against is 100x, not 2%.
            requested_contracts = _requested_contracts(order)
            fill_price = _price_as_probability(seen.get("fill_price"))
            filled_dollars = (
                None if (contracts is None or fill_price is None)
                else float(contracts) * float(fill_price)
            )
            stake_ceiling = None
            try:
                stake = float(order.get("requested_stake_dollars") or 0.0)
                if stake > 0:
                    stake_ceiling = stake * _FILL_DOLLAR_TOLERANCE
            except (TypeError, ValueError):
                stake_ceiling = None

            over_budget = False
            if filled_dollars is not None and stake_ceiling is not None:
                # TWO BANDS, NOT ONE. Over the tolerance is an OVERSPEND -- a
                # real fill that cost more than planned, which gets recorded
                # and flagged. Only an absurd multiple is a unit error, and
                # only that is refused.
                #
                # One band meant a 33% overspend was treated exactly like a
                # 1,000,000x parse failure: both stranded. A confirmed fill
                # must reach the ledger, because the money moved whether we
                # write it down or not, and the day budget cannot charge for
                # what it cannot see.
                bound = "dollars"
                implausible_count = filled_dollars > stake * _FILL_DOLLAR_ABSURD
                over_budget = (not implausible_count) and filled_dollars > stake_ceiling
            else:
                # No readable fill price: fall back to the contract bound rather
                # than to no bound at all.
                #
                # WITH A ROUNDING TOLERANCE, because the venues round and we do
                # not. Measured 2026-08-26 00:27:38Z: `venue_count=2.39
                # requested=2.3920000000000003` -- the venue reported two
                # decimals against our raw float, and an exact `>` on that pair
                # is a coin flip on the third digit. The failure this guards
                # against is a fixed-point scale error, which is 100x; two
                # thousandths of a contract is not it.
                bound = "contracts"
                implausible_count = (
                    contracts is not None
                    and requested_contracts is not None
                    and float(contracts) > float(requested_contracts) + _FILL_COUNT_TOLERANCE
                )
            if implausible_count:
                implausible += 1
                # THE NUMBERS THE BRANCH ACTUALLY COMPARED, not a pair that
                # merely describes the order. The previous line printed
                # `venue_count` and `requested` for BOTH bounds -- but on the
                # dollar branch neither of those is what was compared, so a
                # reader (this one, twice) works backwards from two numbers
                # that cannot produce the verdict. A counter that names a
                # problem while withholding its data is a recurring defect in
                # this repo; this is that defect, in the code that halts
                # trading.
                print(
                    f"[execution_ledger] RECONCILE_COUNT_IMPLAUSIBLE key={key}"
                    f" bound={bound}"
                    f" venue_count={contracts} requested={requested_contracts}"
                    f" fill_price={fill_price} raw_fill_price={seen.get('fill_price')!r}"
                    f" filled_dollars={filled_dollars} stake_ceiling={stake_ceiling}"
                    f" requested_stake={order.get('requested_stake_dollars')!r}"
                    f" requested_price={order.get('requested_price')!r}"
                    " -- left untouched; check the `_fp` unit",
                    flush=True,
                )
                continue

            if over_budget:
                # RECORDED AND NAMED, not refused. The fill is real; this line
                # is what makes the overspend findable instead of inferred from
                # a stake that quietly does not match.
                print(
                    f"[execution_ledger] RECONCILE_FILL_OVER_BUDGET key={key}"
                    f" filled_dollars={filled_dollars} stake_ceiling={stake_ceiling}"
                    f" requested_stake={order.get('requested_stake_dollars')!r}"
                    f" venue_count={contracts} fill_price={fill_price}"
                    " -- BOOKED; the money moved, the ledger follows",
                    flush=True,
                )

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
                    # FLOAT, NOT INT. Kalshi sells WHOLE contracts, so `int()`
                    # was harmless there and wrong the moment a second venue
                    # arrived: Polymarket sells fractional ones
                    # (`minimumTradeQty: 0.01`).
                    #
                    # MEASURED 2026-08-25T18:21:25Z, the first real Polymarket
                    # fill: 2.65 contracts at $0.52 is $1.38, and the run
                    # reported `spent={'dollars': 1.04}` -- because
                    # `int(2.65) * 0.52` is `2 * 0.52`. A 25% under-count of
                    # real money against a daily cap, silently, on every
                    # fractional fill.
                    #
                    # Under-counting spend is the dangerous direction: the cap
                    # exists to bound what the account can lose, and a cap fed
                    # a number smaller than reality lets the account exceed it.
                    stake = round(float(contracts) * float(price), 2)
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
            resting.append(
                {
                    "idempotency_key": key,
                    "order_id": seen.get("order_id"),
                    "ticker": order.get("venue_ticker") or seen.get("ticker"),
                    "side": order.get("side"),
                    "yes_price": seen.get("yes_price"),
                    "no_price": seen.get("no_price"),
                    "submitted_at": order.get("submitted_at"),
                }
            )
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
            # OPEN-NESS IS ORTHOGONAL TO STATUS, and stamping it here is what
            # lets the page count what is actually working at the venue. A
            # partially filled row is `filled` AND open; a resting row is
            # `submitted` AND open; a completely filled row is neither.
            "venue_open": bool(seen.get("open_at_venue")),
            "venue_remaining_count": seen.get("remaining_count"),
            "venue_status": seen.get("venue_status"),
            "venue_order_id": seen.get("order_id") or order.get("venue_order_id"),
            "reconciled_at": _utc_now(),
        }
        # Only a REAL difference counts as a CHANGE. Re-stamping an unchanged
        # row every tick would make the log say work happened on every pass and
        # make "did anything move" unanswerable.
        #
        # BUT THE STAMP IS STILL WRITTEN. Measured 2026-08-24T15:04:08Z: the
        # first version persisted only when something moved, so `reconciled_at`
        # was discarded in exactly the steady state it exists for -- a resting
        # order read successfully, agreeing with the ledger, and therefore never
        # marked as read. `RECONCILE ... changed=0` and
        # `BLOCKED_ON_UNRECONCILED count=1` fired in the same second, on the
        # same order, and live execution stayed jammed.
        #
        # "Nothing changed" and "nothing was learned" are different facts. The
        # freshness stamp records the second one, and it is the whole basis on
        # which a known-resting order stops blocking.
        moved = any(order.get(field) != value for field, value in new_fields.items())
        order.update(stamp)
        stamped += 1
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

    if stamped:
        _persist(state)
    if changed:
        for row in changed:
            print(
                f"[execution_ledger] RECONCILED key={row['idempotency_key']}"
                f" ticker={row['ticker']} {row['from']}->{row['to']}"
                f" venue_status={row['venue_status']!r}"
                f" contracts={row['contracts']} fill_price={row['fill_price']}"
                f" fees={row['fees_dollars']}",
                flush=True,
            )
    # ------------------------------------------------------------------
    # THE OTHER DIRECTION: A POSITION THE VENUE HOLDS AND WE DO NOT.
    # ------------------------------------------------------------------
    #
    # Everything above walks OUR rows and asks the venue about each. That can
    # only ever correct a row we already have. The mirror failure -- an order
    # live at the venue with no row here at all -- is invisible to it, and it
    # is real money: a submit whose response was lost leaves a write-ahead row
    # with no venue id, and a submit that never got written at all leaves
    # nothing.
    #
    # MEASURED 2026-08-26T12:57Z, which is why this exists: Kalshi returned
    # `venue_orders=33` while we asked about `candidates=4`. Twenty-nine orders
    # on our own account were read into memory every cycle and never compared
    # to anything.
    #
    # ONLY MEANINGFUL ON A BOOK READ. Polymarket publishes no list route
    # (`GET /v1/orders` answers `code: 12` UNIMPLEMENTED) so its reader fetches
    # exactly the ids we hand it -- `venue_orders == candidates` is a tautology
    # there, not a reconciliation, and an orphan count of 0 from it would be a
    # false assurance rather than a finding. The coverage is asked for, not
    # inferred from the counts, because the counts are exactly what a
    # per-order read makes uninformative.
    #
    # NOTHING IS WRITTEN. This reports; it does not invent ledger rows from
    # venue data. What it buys is that the gap becomes a number somebody can
    # see, instead of a silence.
    coverage = str(read.get("coverage") or "unknown")
    orphans: list[dict[str, Any]] = []
    if coverage == "book":
        # THE WHOLE LIVE LEDGER, not just the candidates. A filled or settled
        # order is legitimately in the venue's book and is not an orphan; only
        # a venue order matching NO row we hold is.
        known_keys = {
            str(o.get("idempotency_key") or "").strip()
            for o in orders
            if str(o.get("mode") or "") == LIVE
        }
        known_keys.discard("")
        known_ids = {
            str(o.get("venue_order_id") or "").strip()
            for o in orders
            if str(o.get("mode") or "") == LIVE
        }
        known_ids.discard("")
        for raw in read.get("orders") or []:
            seen = view(raw)
            client = str(seen.get("client_order_id") or "").strip()
            venue_id = str(seen.get("order_id") or "").strip()
            if client and client in known_keys:
                continue
            if venue_id and venue_id in known_ids:
                continue
            orphans.append(
                {
                    "order_id": venue_id,
                    "client_order_id": client,
                    "ticker": seen.get("ticker"),
                    "venue_status": seen.get("venue_status"),
                    "filled_count": seen.get("filled_count"),
                    # WHICH KIND OF ORPHAN, and the whole point of the split.
                    #
                    # Every order this system places stamps the idempotency key
                    # as `client_order_id`. So:
                    #
                    #   no client id     -> not ours. Placed by hand in the
                    #                       venue's UI, or predating the
                    #                       stamp. Account history, not a
                    #                       tracking failure.
                    #   client id we do  -> OURS, and the ledger row is gone.
                    #   not hold            That is real money this system
                    #                       opened and cannot see.
                    #
                    # Measured 2026-08-26T13:18Z: `orphans=26`, every sampled
                    # row with `client_order_id: ''` and dated 08-07 or 08-23,
                    # across NFL/WNBA/MLB. Reported as one number it reads as
                    # "26 positions we do not know about", which is alarming
                    # and probably wrong. A count that cannot distinguish the
                    # benign case from the serious one is not actionable in
                    # either direction.
                    "ours": _is_our_key(client),
                }
            )
        if orphans:
            ours = [o for o in orphans if o["ours"]]
            # THREE BUCKETS, because two could not tell these apart. A venue
            # order carrying SOMEONE ELSE'S client id is not the same fact as
            # one carrying none: the first says another client of this account
            # placed it, the second says the venue's own UI did. Neither is
            # money we lost. Only `ours` is.
            foreign = [o for o in orphans if not o["ours"] and o["client_order_id"]]
            unclaimed = len(orphans) - len(ours) - len(foreign)
            # THE ROWS, NOT JUST THE COUNT. A counter that names a problem
            # while withholding its data is the defect this repo keeps
            # relearning; an orphan is only actionable if you can see which
            # ticker it is.
            print(
                f"[execution_ledger] RECONCILE_ORPHANS venue={venue}"
                f" n={len(orphans)} ours={len(ours)}"
                f" foreign_client={len(foreign)} unclaimed={unclaimed}"
                # OURS FIRST IN THE SAMPLE. With a flat cap at 5 the serious
                # rows can be crowded out by benign history and never printed.
                f" sample_ours={ours[:5]} sample_foreign={foreign[:2]}"
                f" sample_unclaimed={[o for o in orphans if not o['ours'] and not o['client_order_id']][:2]}"
                " -- at the venue, absent from our ledger; NOTHING WRITTEN"
                " (ours=OUR KEY SHAPE, ledger row LOST -- the only alarming one;"
                " foreign_client=another client of this account;"
                " unclaimed=no client id, placed in the venue UI)",
                flush=True,
            )

    print(
        f"[execution_ledger] RECONCILE venue={venue} candidates={len(candidates)}"
        f" venue_orders={len(read.get('orders') or [])} changed={len(changed)}"
        f" not_found={not_found} unknown={unknown} implausible={implausible}"
        f" stamped={stamped}"
        # COVERAGE ON THE SAME LINE AS THE COUNTS IT QUALIFIES. Read without
        # it, `not_found=0 venue_orders=15` on a per-order venue looks exactly
        # like a clean full-book reconciliation and is not one.
        f" coverage={coverage}"
        f" orphans={len(orphans) if coverage == 'book' else 'n/a'}"
        # THE ONE THAT MATTERS, ON THE SUMMARY LINE. `orphans=26` alone cannot
        # say whether anything is wrong; `orphans_ours` can.
        f" orphans_ours={len([o for o in orphans if o['ours']]) if coverage == 'book' else 'n/a'}",
        flush=True,
    )
    return {
        "status": "ok",
        "candidates": len(candidates),
        "changed": len(changed),
        "not_found": not_found,
        "unknown": unknown,
        "implausible": implausible,
        "stamped": stamped,
        "coverage": coverage,
        # `None`, not `[]`, when the read cannot see orphans at all. An empty
        # list would say "we looked and there were none".
        "orphans": orphans if coverage == "book" else None,
        # Handed out rather than acted on here: reconciliation READS the venue
        # and must stay something safe to run anywhere. Cancelling is a WRITE,
        # and it gets its own call and its own log line.
        "resting": resting,
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


def _age_seconds(stamp: Any) -> float | None:
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        seen = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - seen).total_seconds()


def _market_price_for_side(ticker: Any, side: Any) -> float | None:
    """What we would PAY, right now, on our leg of this market."""
    from syndicate.features.shared.kalshi_client import fetch_market
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    try:
        contract_side = _side_to_kalshi(side)
    except Exception:
        return None
    read = fetch_market(str(ticker or ""))
    if read.get("status") != "ok":
        return None
    market = read.get("market") or {}
    field = "yes_ask_dollars" if contract_side == "yes" else "no_ask_dollars"
    try:
        value = float(market.get(field))
    except (TypeError, ValueError):
        return None
    return value if 0.0 < value < 1.0 else None


def _resting_price_for_side(row: Mapping[str, Any]) -> float | None:
    """What we are resting at, on our leg. Kalshi hands over both legs."""
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    try:
        contract_side = _side_to_kalshi(row.get("side"))
    except Exception:
        return None
    price = row.get("yes_price") if contract_side == "yes" else row.get("no_price")
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    return value if 0.0 < value < 1.0 else None


def cancel_stale_resting_orders(resting: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pull resting orders off the book once their price has stopped existing.

    ------------------------------------------------------------------
    WHY AGE AND PRICE, AND WHY BOTH
    ------------------------------------------------------------------

    A limit order that has not filled is not automatically wrong -- that is
    what a limit is for, and cancelling one the moment the market ticks would
    churn the book and never let a good price come to us. What makes one dead
    is that it has sat there long enough to have had its chance AND the market
    has left the price behind. Either alone is a bad rule; together they name
    exactly the order nobody would leave standing.

    MEASURED 2026-08-24: the Zebby Matthews order rested from ~12:58Z at $0.54
    for NO while the market moved to $0.56. It could not fill at that price and
    was never going to, and it held its own idempotency key hostage -- so the
    marketable-limit path could not re-place it either, because the ledger
    correctly saw a live order at the venue.

    ------------------------------------------------------------------
    WHAT MAKES A VENUE WRITE SAFE TO RUN ON A LOOP
    ------------------------------------------------------------------

    - NO PRICE, NO CANCEL. If the live market cannot be read, the order stays.
      Cancelling on an unreadable price is acting on the absence of
      information, which is the failure this whole layer keeps refusing.
    - A FAILED CANCEL CHANGES NOTHING. The order is still resting and can
      still fill; marking it dead would free a key the venue still holds, and
      that is how one bet becomes two. Only a successful DELETE moves the row.
    - BOUNDED PER PASS. `SYNDICATE_EXECUTION_MAX_CANCELS` (default 3) caps it,
      so a bad rule cannot empty the book before anyone reads a log.
    - Every cancel is logged by name, including the refusals.

    Cancelling costs nothing at Kalshi -- an unfilled order carries no fee --
    so the asymmetry runs the right way: a cancel we should not have made costs
    a re-place, a fill we should not have taken costs the stake.
    """
    from syndicate.features.shared.kalshi_orders import cancel_order

    max_age = _float_env("SYNDICATE_EXECUTION_RESTING_MAX_AGE_SECONDS", 900.0)
    band = _float_env("SYNDICATE_EXECUTION_RESTING_PRICE_BAND", 0.01)
    limit = int(_float_env("SYNDICATE_EXECUTION_MAX_CANCELS", 3.0))

    cancelled: list[dict[str, Any]] = []
    too_young = 0
    at_market = 0
    unreadable = 0
    failed = 0

    for row in resting:
        if len(cancelled) >= limit:
            print(
                f"[execution_ledger] CANCEL_CAPPED limit={limit}"
                " -- remaining resting orders left for the next pass",
                flush=True,
            )
            break

        age = _age_seconds(row.get("submitted_at"))
        if age is None or age < max_age:
            too_young += 1
            continue

        resting_price = _resting_price_for_side(row)
        market_price = _market_price_for_side(row.get("ticker"), row.get("side"))
        if resting_price is None or market_price is None:
            unreadable += 1
            print(
                f"[execution_ledger] CANCEL_SKIPPED_NO_PRICE key={row.get('idempotency_key')}"
                f" ticker={row.get('ticker')} resting={resting_price} market={market_price}",
                flush=True,
            )
            continue

        drift = round(market_price - resting_price, 4)
        if abs(drift) < band:
            at_market += 1
            continue

        print(
            f"[execution_ledger] CANCEL_STALE key={row.get('idempotency_key')}"
            f" ticker={row.get('ticker')} side={row.get('side')}"
            f" resting={resting_price} market={market_price} drift={drift:+}"
            f" age_s={age:.0f}",
            flush=True,
        )
        result = cancel_order(row.get("order_id"))
        if result.get("status") != "ok":
            failed += 1
            print(
                f"[execution_ledger] CANCEL_FAILED key={row.get('idempotency_key')}"
                f" reason={result.get('reason')} -- order left resting",
                flush=True,
            )
            continue
        cancelled.append(
            {
                "idempotency_key": row.get("idempotency_key"),
                "ticker": row.get("ticker"),
                "resting_price": resting_price,
                "market_price": market_price,
                "drift": drift,
                "age_seconds": round(age, 0),
            }
        )

    # THE LEDGER IS NOT UPDATED HERE. The next reconciliation pass reads the
    # venue, sees `canceled`, and moves the row to `rejected` through the one
    # path that is allowed to change a status -- the venue's own word. Writing
    # it here would be this module believing its own API call over the book,
    # which is the habit that produced the phantom fill.
    if cancelled or failed or unreadable:
        print(
            f"[execution_ledger] CANCEL_PASS resting={len(resting)}"
            f" cancelled={len(cancelled)} failed={failed} unreadable={unreadable}"
            f" too_young={too_young} at_market={at_market}",
            flush=True,
        )
    return {
        "status": "ok",
        "cancelled": len(cancelled),
        "failed": failed,
        "unreadable": unreadable,
        "too_young": too_young,
        "at_market": at_market,
        "orders": cancelled,
    }


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
