"""Stage B runner: take a committed portfolio plan and place it, on paper.

Worker-side, dark by default, and **deliberately a separate entrypoint from the
commit job**. Deciding and placing are different failures with different blast
radii: a bad commit writes a wrong plan you can read and discard, a bad
execution spends money. Keeping them in one process makes it easy to ship a
change to one and restart the other.

**NEVER RUN THIS INSIDE `refresh-worker`.** That service has a documented
OOM-kill history (110 kills on 2026-08-07) and restarts mid-job; a restart
between submit and record is what the write-ahead in `execution_ledger` exists
to survive, and giving it a stable host is the cheaper half of the same
problem.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from syndicate.features.shared.execution_ledger import (
    LIVE,
    OrderRequest,
    execution_mode,
    ledger_summary,
    live_execution_armed,
    place_order,
    unreconciled_orders,
)

# The venue every paper order is booked against. Named rather than blank so a
# paper record is never mistaken for one that reached a real venue.
PAPER_VENUE = "paper"


def execution_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_EXECUTION_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _order_from_position(position: Mapping[str, Any], selected_date: str, venue: str) -> OrderRequest | None:
    """One committed position -> one order request, or None with nothing placed.

    Every field the request needs is required. A position missing any of them is
    SKIPPED rather than defaulted, for the reason Stage A refuses rather than
    defaults: a neutral value here is a real bet on something we could not
    identify.
    """
    position_key = str(position.get("position_key") or "").strip()
    event_id = str(position.get("event_id") or "").strip()
    market = str(position.get("market") or "").strip()
    side = str(position.get("side") or "").strip()
    sport = str(position.get("sport") or "").strip()
    try:
        price = float(position["price"])
        stake = float(position["stake_dollars"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (position_key and event_id and market and side and sport) or stake <= 0:
        return None
    line = position.get("line")
    try:
        line_value = None if line is None else float(line)
    except (TypeError, ValueError):
        line_value = None
    return OrderRequest(
        position_key=position_key,
        selected_date=selected_date,
        venue=venue,
        sport=sport,
        event_id=event_id,
        market=market,
        side=side,
        requested_price=price,
        requested_stake_dollars=stake,
        line=line_value,
        player_name=(str(position.get("player_name")).strip() or None) if position.get("player_name") else None,
        book=(str(position.get("book")).strip() or None) if position.get("book") else None,
    )


def run_execution(
    selected_date: str, *, force: bool = False, inline: bool = False
) -> dict[str, Any]:
    """Place today's committed plan. Returns a status payload, never raises.

    `force` bypasses only the enablement flag. It does NOT bypass the mode, the
    live arm, or the unreconciled check -- a convenience flag that can reach
    real money is not a convenience.

    **`inline=True` REFUSES LIVE MODE STRUCTURALLY.** It is passed by the one
    caller that runs inside the intelligence-state build on `refresh-worker`,
    and it exists because this module's own contract says the placer must never
    run there: that service has 110 OOM kills on record and restarts mid-job,
    which is what the write-ahead exists to survive rather than something to
    invite. Paper cannot double-spend, so the harness that generates Stage C's
    evidence is safe inline; real money has to move to its own service.

    Enforced HERE rather than by configuration, because "set the env var
    correctly" is exactly the guarantee that failed on 2026-08-22 when an
    unrecognised value for a different key silently meant something else.
    """
    normalized = str(selected_date or "").strip()
    if not normalized:
        return {"status": "skipped", "reason": "no_date"}
    if not (force or execution_enabled()):
        return {"status": "skipped", "reason": "disabled", "date": normalized}

    mode = execution_mode()
    if inline and mode == LIVE:
        # Loud, not silent: a live-configured worker that quietly fell back to
        # paper would produce a ledger nobody could trust the `mode` field on.
        print(
            "[execute_portfolio] REFUSED_LIVE_INLINE date="
            f"{normalized} -- live placement must not run inside refresh-worker; "
            "run it from its own service",
            flush=True,
        )
        return {
            "status": "skipped",
            "reason": "live_mode_refused_inline",
            "date": normalized,
        }

    # UNRECONCILED ORDERS BLOCK A NEW RUN, in live mode only. An order left in
    # the write-ahead state was sent, or may have been, with an unknown result.
    # Placing a fresh slate on top of that risks doubling it. Paper mode cannot
    # double-spend, so it is not blocked -- but it still reports the count.
    try:
        stranded = unreconciled_orders()
    except Exception as exc:
        return {"status": "error", "reason": f"ledger_unreadable: {exc}", "date": normalized}
    if stranded and mode == LIVE:
        print(
            f"[execute_portfolio] BLOCKED_ON_UNRECONCILED count={len(stranded)} "
            f"keys={[o.get('idempotency_key') for o in stranded[:5]]}",
            flush=True,
        )
        return {
            "status": "blocked",
            "reason": "unreconciled_orders",
            "date": normalized,
            "unreconciled": len(stranded),
        }

    from pipeline.portfolio_commit import read_portfolio_plan

    plan = read_portfolio_plan(normalized)
    if not isinstance(plan, dict):
        print(f"[execute_portfolio] NO_PLAN date={normalized}", flush=True)
        return {"status": "skipped", "reason": "no_plan", "date": normalized}

    positions = plan.get("positions")
    if not isinstance(positions, list):
        return {"status": "skipped", "reason": "plan_has_no_positions_key", "date": normalized}

    venue = PAPER_VENUE if mode != LIVE else str(os.environ.get("SYNDICATE_EXECUTION_VENUE") or "").strip()
    if mode == LIVE and not venue:
        return {"status": "skipped", "reason": "live_mode_with_no_venue_configured", "date": normalized}

    placed = 0
    duplicates = 0
    skipped = 0
    for position in positions:
        if not isinstance(position, Mapping):
            skipped += 1
            continue
        request = _order_from_position(position, normalized, venue)
        if request is None:
            skipped += 1
            continue
        before = _status_of(request)
        record = place_order(request)
        if before is not None:
            duplicates += 1
        elif record.get("status") in {"filled"}:
            placed += 1

    summary = ledger_summary(normalized)
    print(
        f"[execute_portfolio] EXECUTED date={normalized} mode={mode} venue={venue} "
        f"armed={live_execution_armed()} positions={len(positions)} placed={placed} "
        f"duplicates={duplicates} skipped={skipped} summary={summary}",
        flush=True,
    )
    return {
        "status": "ok",
        "date": normalized,
        "mode": mode,
        "venue": venue,
        "positions": len(positions),
        "placed": placed,
        # A re-run places nothing new. This is the number that proves the
        # idempotency works in production rather than only in a test.
        "duplicates": duplicates,
        "skipped": skipped,
        "summary": summary,
    }


def _status_of(request: OrderRequest) -> str | None:
    from syndicate.features.shared.execution_ledger import find_order, idempotency_key

    existing = find_order(idempotency_key(request))
    return None if existing is None else str(existing.get("status") or "")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Place a committed portfolio plan.")
    parser.add_argument("--date", required=True, help="slate date, YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="ignore the enablement flag only")
    args = parser.parse_args()
    result = run_execution(args.date, force=args.force)
    print(result.get("status"), result.get("reason") or "")
    return 0 if result.get("status") in {"ok", "skipped", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
