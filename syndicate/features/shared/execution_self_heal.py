"""Self-healing for the live execution ledger: resolve a Kalshi UNKNOWN SUBMIT the venue can account for.

Lane `execution-alerts`, 2026-10-19, built on the user's explicit yes in chat ("Yes, build it"). Called once
per execution tick by live-odds-worker (`_run_execution_tick`, after settlement, before placement), where the
venue credentials live.

THE GAP. An UNKNOWN SUBMIT is a live order whose submit failed with no venue answer (5xx, timeout) and no
`venue_order_id`: `status=failed`, no outcome, no resolution, not a 4xx refusal. Until now only a human could
clear one (`resolve_unknown_submit`, the /portfolio/live button), so live money left unattended carried a
question nobody would answer. And the reconciler cannot see one: `reconcile_live_orders` takes only
`submitted`/`filled` rows as candidates, so a lost Kalshi submit that DID land is merely an unclaimed
`RECONCILE_ORPHANS ... ours=1` in the log while the ledger still says `failed`.

WHAT THIS DOES, ONLY ON A DEFINITIVE VENUE STATEMENT. Kalshi's book read (`kalshi_orders.fetch_orders`, the
same call the reconciler makes) lists orders with OUR idempotency key as `client_order_id`. If an unknown
submit's key is in a SUCCESSFUL read, and the ticker agrees, the venue has told us what happened:

  state filled / resting  -> it is a position. `resolve_unknown_submit(placed)` records the finding (the
                             same record a human's click makes), then `complete_order(status=submitted,
                             venue_order_id=...)` hands the row back to the reconciler, which books the
                             fill, price and fees from the venue on its next read (this same tick).
  state dead, 0 filled    -> it reached the venue and holds no position. `resolve_unknown_submit(not_placed)`
                             -> `rejected`, exactly as a human would mark it.
  unknown / not listed    -> NOTHING. Absence from a list read is not absence at the venue (the read is
                             capped and an old order ages out), and an unmapped status is not evidence.

WHAT IT REFUSES TO DO:
  * Polymarket. It has no list route (`GET /v1/orders` is 501) and the per-order read needs the id the
    failed submit lost, so the venue CANNOT show an order state. Balance evidence
    (`venue_settlement._balance_evidence`) is an inference from the account, not an order state; it stays
    evidence in the alert email for a human. Releasing a retry on an inference risks a second real position.
  * A read that failed, a ticker that disagrees, an order younger than MIN_AGE_SECONDS (its submit may still
    be in flight), or more than MAX_RESOLUTIONS_PER_TICK in one pass (a burst that large is an incident, and
    the alert email is the right response).

Off switch: `SYNDICATE_EXECUTION_SELF_HEAL=off`. Default ON: the user asked for it, and every action it takes
is one a human was already expected to take by hand on the same evidence.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

MIN_AGE_SECONDS = 120.0
MAX_RESOLUTIONS_PER_TICK = 5
SELF_HEAL_ENV = "SYNDICATE_EXECUTION_SELF_HEAL"
LIVE = "live"


def self_heal_enabled() -> bool:
    return str(os.environ.get(SELF_HEAL_ENV) or "on").strip().lower() not in {"off", "0", "false", "no"}


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_unknown_submit(order: Mapping[str, Any]) -> bool:
    """The page's definition (`intelligence._is_unknown_submit`), over one row."""
    from syndicate.features.shared.execution_guard import is_non_position

    return (
        str(order.get("mode") or "") == LIVE
        and str(order.get("status") or "") == "failed"
        and not order.get("outcome")
        and not str(order.get("venue_order_id") or "").strip()
        and not order.get("operator_resolution")
        and not is_non_position(order)
    )


def decide(order: Mapping[str, Any], seen: Mapping[str, Any] | None) -> tuple[str | None, str]:
    """(finding or None, why). Pure: `seen` is `kalshi_orders.venue_order_view` of the matching venue row."""
    if seen is None:
        return None, "not_listed"
    ticker, seen_ticker = str(order.get("venue_ticker") or "").strip(), str(seen.get("ticker") or "").strip()
    if ticker and seen_ticker and ticker.upper() != seen_ticker.upper():
        return None, "ticker_mismatch"
    if not str(seen.get("order_id") or "").strip():
        return None, "no_venue_order_id"
    state = str(seen.get("state") or "unknown")
    if state in ("filled", "resting"):
        return "placed", state
    if state == "dead" and not seen.get("filled_count"):
        return "not_placed", "dead_unfilled"
    return None, f"state_{state}"


def auto_resolve_unknown_submits(
    *,
    now: datetime | None = None,
    load: Callable[[], Mapping[str, Any]] | None = None,
    fetch: Callable[..., Mapping[str, Any]] | None = None,
    view: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    resolve: Callable[..., Any] | None = None,
    complete: Callable[..., Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """One pass. Returns counters; prints one `SELF_HEAL` line whenever there was anything to look at.

    Makes NO venue call when there is no Kalshi unknown submit old enough to examine -- the normal case.
    """
    from syndicate.features.shared import execution_ledger as ledger

    if not self_heal_enabled():
        return {"status": "off"}
    now = now or datetime.now(timezone.utc)
    load = load or ledger._load  # noqa: SLF001 -- the ledger's own reader, same package
    rows = [o for o in (load().get("orders") or []) if isinstance(o, Mapping) and is_unknown_submit(o)]
    kalshi = [o for o in rows if str(o.get("venue") or "").strip().lower().startswith("kalshi")]
    counts: dict[str, Any] = {"status": "ok", "unknown": len(rows), "kalshi": len(kalshi), "resolved": [],
                              "skipped": {}, "polymarket_left_for_human": len(rows) - len(kalshi)}
    old_enough = []
    for o in kalshi:
        sent = _parse(o.get("venue_resolved_at") or o.get("submitted_at"))
        if sent is None or (now - sent).total_seconds() < MIN_AGE_SECONDS:
            counts["skipped"]["too_young"] = counts["skipped"].get("too_young", 0) + 1
            continue
        old_enough.append(o)
    if not old_enough:
        if rows:
            _report(counts)
        return counts

    if fetch is None or view is None:
        from syndicate.features.shared import kalshi_orders

        fetch, view = fetch or kalshi_orders.fetch_orders, view or kalshi_orders.venue_order_view
    read = fetch(limit=100, order_ids=[])
    if str(read.get("status") or "") != "ok":
        # A FAILED READ CHANGES NOTHING -- the reconciler's own rule.
        counts.update(status="read_failed", reason=str(read.get("reason"))[:160])
        _report(counts)
        return counts
    by_client: dict[str, Mapping[str, Any]] = {}
    for raw in read.get("orders") or []:
        seen = view(raw)
        client = str(seen.get("client_order_id") or "").strip()
        if client:
            by_client[client] = seen

    resolve = resolve or ledger.resolve_unknown_submit
    complete = complete or ledger.complete_order
    for order in old_enough:
        key = str(order.get("idempotency_key") or "")
        seen = by_client.get(key)
        finding, why = decide(order, seen)
        if finding is None:
            counts["skipped"][why] = counts["skipped"].get(why, 0) + 1
            continue
        if len(counts["resolved"]) >= MAX_RESOLUTIONS_PER_TICK:
            counts["skipped"]["tick_budget"] = counts["skipped"].get("tick_budget", 0) + 1
            continue
        note = (f"auto (execution_self_heal): kalshi lists client_order_id={key} as order {seen.get('order_id')} "
                f"state={seen.get('state')} venue_status={seen.get('venue_status')} filled={seen.get('filled_count')} "
                f"read {now.isoformat()}")
        entry = {"key": key, "finding": finding, "venue_order_id": seen.get("order_id"), "state": seen.get("state")}
        if not dry_run:
            try:
                resolve(key, finding, note=note)
                if finding == "placed":
                    # BACK TO THE RECONCILER, which books fill/price/fees from the venue. The original error is
                    # kept in the text; operator_resolution carries the finding and the venue's statement.
                    complete(key, status=ledger.STATUS_SUBMITTED, venue_order_id=str(seen.get("order_id")),
                             error=f"auto_recovered_unknown_submit (was failed: {str(order.get('error') or '')[:200]})")
            except Exception as exc:  # noqa: BLE001 -- e.g. already_settled while we looked
                entry["error"] = f"{type(exc).__name__}: {exc}"[:160]
        counts["resolved"].append(entry)
        print(f"[execution_self_heal] UNKNOWN_SUBMIT_AUTO_RESOLVED key={key} finding={finding}"
              f" venue_order_id={seen.get('order_id')} state={seen.get('state')} ticker={order.get('venue_ticker')}"
              f" stake={order.get('requested_stake_dollars')} dry_run={dry_run} error={entry.get('error')}",
              flush=True)
    _report(counts)
    return counts


def _report(counts: Mapping[str, Any]) -> None:
    print(
        f"[execution_self_heal] SELF_HEAL status={counts.get('status')} unknown={counts.get('unknown')}"
        f" kalshi={counts.get('kalshi')} resolved={len(counts.get('resolved') or [])}"
        f" skipped={counts.get('skipped')} polymarket_left_for_human={counts.get('polymarket_left_for_human')}"
        + (f" reason={counts.get('reason')}" if counts.get("reason") else ""),
        flush=True,
    )
