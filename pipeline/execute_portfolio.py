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
        segment=position.get("segment"),
        # Copied onto the order so the bet stays legible and re-priceable once
        # the plan that described it has been rewritten -- which happens on
        # every board build, i.e. every few minutes. See `_LEAN_FIELDS`.
        home_team=position.get("home_team"),
        away_team=position.get("away_team"),
        commence_time=position.get("commence_time"),
        opening_key=position.get("opening_key"),
        game_pk=(str(position.get("game_pk")).strip() or None)
        if position.get("game_pk") is not None
        else None,
        # THE EXCHANGE CONTRACT, stamped by `venue_scope` at decision time from
        # the same match that supplied the price. None on an unrestricted row --
        # there is no single contract when the price came from an aggregator's
        # best-of-many, which is exactly why the Kalshi adapter refuses without
        # one rather than picking a plausible ticker at submit time.
        venue_ticker=(str(position.get("venue_ticker")).strip() or None)
        if position.get("venue_ticker")
        else None,
    )


def run_execution(
    selected_date: str,
    *,
    force: bool = False,
    inline: bool = False,
    venue_scope: str | None = None,
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

    **`venue_scope` places `paper2`'s venue-restricted plan instead of the
    unrestricted one.** The two books must stay separable at every level or the
    comparison they exist for is destroyed, so a scoped run reads a different
    plan artifact AND books its orders under a different `venue`
    (`paper:kalshi`, not `paper`). `idempotency_key` already includes `venue`,
    so the same position placed in both books yields two distinct keys and
    neither is refused as the other's duplicate -- a property worth stating
    because if it were false, paper2 would silently suppress the main book's
    orders rather than fail visibly.
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

    # Resolved before the plan read: it decides WHICH plan is read.
    scope = str(venue_scope or "").strip().lower()

    # LIVE MUST READ THE VENUE-RESTRICTED PLAN. Measured 2026-08-24T00:34Z: the
    # worker called `run_execution(date)` with no scope, so live mode read the
    # UNRESTRICTED plan and tried to place a SOCCER TOTAL and an MLB SPREAD on
    # Kalshi -- markets the join never paired, carrying no venue ticker and
    # priced at some other book. Both failed at order build, so nothing reached
    # the venue; that was the last guard in the chain doing the work, not a
    # design.
    #
    # The unrestricted plan is a different book with a different meaning: its
    # prices come from whichever bookmaker was best, and a position in it is
    # not a claim that THIS venue quotes the market at all. Sending it to one
    # venue is a category error, and the failure mode if a price ever did
    # resolve is a real bet on a market nothing matched to the board row.
    #
    # Refused rather than defaulted, because guessing the scope here would make
    # the wrong plan reachable again through a different door.
    if mode == LIVE and not scope:
        print(
            "[execute_portfolio] LIVE_WITHOUT_VENUE_SCOPE date="
            f"{normalized} -- refusing to place the unrestricted plan at one venue",
            flush=True,
        )
        return {
            "status": "skipped",
            "reason": "live_mode_requires_venue_scope",
            "date": normalized,
        }
    if scope:
        from pipeline.portfolio_commit import read_portfolio_plan_for_venue

        plan = read_portfolio_plan_for_venue(normalized, scope)
    else:
        plan = read_portfolio_plan(normalized)
    if not isinstance(plan, dict):
        print(f"[execute_portfolio] NO_PLAN date={normalized}", flush=True)
        return {"status": "skipped", "reason": "no_plan", "date": normalized}

    positions = plan.get("positions")
    if not isinstance(positions, list):
        return {"status": "skipped", "reason": "plan_has_no_positions_key", "date": normalized}

    venue = PAPER_VENUE if mode != LIVE else str(os.environ.get("SYNDICATE_EXECUTION_VENUE") or "").strip()
    if scope and mode != LIVE:
        # Suffixed rather than replaced: the record must still say PAPER at a
        # glance, and `mode` alone would not distinguish the two paper books.
        #
        # PAPER ONLY. In live mode the venue IS the scope -- suffixing produced
        # `kalshi:kalshi`, which resolves to no adapter, so the first live run
        # after the scope became mandatory would have refused every order with
        # `no_adapter_for_venue:kalshi:kalshi`. Caught by the existing live
        # tests the moment the scope was threaded through, which is the whole
        # reason they name the adapter lookup explicitly.
        venue = f"{venue}:{scope}"
    if mode == LIVE and not venue:
        return {"status": "skipped", "reason": "live_mode_with_no_venue_configured", "date": normalized}

    from syndicate.features.shared.execution_ledger import STATUS_REJECTED
    from syndicate.features.shared.execution_guard import (
        check_order,
        guarded_submit,
        limits,
        spent_today,
    )

    # THE VENUE ADAPTER. `None` in paper mode -- `place_order` never calls it
    # there, and passing one would make paper and live differ in the one seam
    # that must not differ.
    #
    # Wrapped in `guarded_submit` so the kill switch is re-checked with nothing
    # between the check and the call: a switch pulled during a twelve-order loop
    # has to stop order four, not order one.
    submitter = None
    if mode == LIVE:
        submitter = _venue_submitter(venue)
        if submitter is None:
            return {
                "status": "skipped",
                "reason": f"no_adapter_for_venue:{venue}",
                "date": normalized,
            }
        submitter = guarded_submit(submitter)

    caps = limits(mode)
    # Seeded ONCE from the ledger and then incremented per placement. Seeded
    # rather than started at zero, because a restart mid-slate must not hand the
    # day its budget back; incremented rather than re-read, because a re-read
    # between two placements in the same loop would still miss the one just
    # made if the store lags, and the local count cannot.
    used = spent_today(normalized, venue=venue, mode=mode)
    print(
        f"[execute_portfolio] LIMITS date={normalized} mode={mode} venue={venue} "
        f"already={used} caps={caps}",
        flush=True,
    )

    placed = 0
    duplicates = 0
    retried = 0
    skipped = 0
    # Every refusal is COUNTED BY NAME. A single `skipped` number cannot tell a
    # plan that named nothing bettable from a cap that stopped a good slate, and
    # those want opposite responses.
    refused: dict[str, int] = {}
    for position in positions:
        if not isinstance(position, Mapping):
            skipped += 1
            refused["not_a_mapping"] = refused.get("not_a_mapping", 0) + 1
            continue
        request = _order_from_position(position, normalized, venue)
        if request is None:
            skipped += 1
            refused["incomplete_position"] = refused.get("incomplete_position", 0) + 1
            continue

        before = _status_of(request)
        # A REJECTED order never reached the venue, so a fresh attempt is a
        # PLACEMENT, not a duplicate. Measured 2026-08-24T12:58Z: the retry
        # unblock worked and the order really was submitted -- and this branch
        # still counted it `duplicates=1` and `continue`d PAST the LIVE_ORDER
        # log, so a real order went to Kalshi and its outcome was never
        # recorded anywhere a person could read. Invisible is the one thing an
        # order that moves money must never be.
        retryable = before is None or before == STATUS_REJECTED
        if retryable:
            # Checked for anything that would be NEWLY placed, retries
            # included -- a retry spends, so it must be charged. A duplicate
            # places nothing, and charging that would let a re-run exhaust a
            # budget it never spent.
            verdict = check_order(request, mode=mode, already=used)
            if not verdict.get("allowed"):
                reason = str(verdict.get("reason"))
                refused[reason] = refused.get(reason, 0) + 1
                skipped += 1
                continue

        record = place_order(request, submit=submitter)
        if not retryable:
            duplicates += 1
            continue
        if before == STATUS_REJECTED:
            retried += 1
        status = str(record.get("status") or "")
        if mode == LIVE:
            # EVERY LIVE ORDER GETS A LINE, whatever happened to it. Measured
            # 2026-08-24T00:23:47Z: the first real order this system ever sent
            # FAILED, and the only trace was `placed=0 ... spent={'dollars':
            # 4.39, 'orders': 1}` -- a pair of numbers that reads identically to
            # "nothing was attempted", because `placed` counts fills and `spent`
            # charges anything that may have reached the venue. Telling those
            # apart took reading this function's source. The venue's own reason
            # for refusing real money is the most valuable string in the system
            # and it was being written to the ledger and never printed.
            print(
                f"[execute_portfolio] LIVE_ORDER status={status}"
                f" venue={venue} ticker={record.get('venue_ticker')}"
                f" sport={record.get('sport')} market={record.get('market')}"
                f" player={record.get('player_name')!r}"
                f" side={record.get('side')} line={record.get('line')}"
                f" price={record.get('requested_price')}"
                f" stake={record.get('requested_stake_dollars')}"
                f" fill_price={record.get('fill_price')}"
                f" error={record.get('error')!r}",
                flush=True,
            )
        if status in {"filled"}:
            placed += 1
        # Charged for anything that MAY have reached the venue, matching
        # `spent_today`'s rule. `rejected` is the one status set without a call.
        if status in {"filled", "submitted", "failed"}:
            used = {
                "dollars": round(
                    float(used.get("dollars") or 0.0) + float(request.requested_stake_dollars), 2
                ),
                "orders": int(used.get("orders") or 0) + 1,
            }

    summary = ledger_summary(normalized)
    print(
        f"[execute_portfolio] EXECUTED date={normalized} mode={mode} venue={venue} "
        f"armed={live_execution_armed()} positions={len(positions)} placed={placed} "
        f"duplicates={duplicates} retried={retried} skipped={skipped} refused={refused} "
        f"spent={used} summary={summary}",
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
        # Orders that had been REJECTED and were attempted again. Counted apart
        # from `placed` so a retry storm is visible rather than looking like
        # ordinary volume.
        "retried": retried,
        "skipped": skipped,
        "refused": refused,
        "spent": used,
        "limits": caps,
        "summary": summary,
    }


def _venue_submitter(venue: str):
    """The adapter that actually places an order at `venue`, or None.

    NAMED PER VENUE and refused when absent, rather than defaulting to
    something. A live run against a venue with no adapter must stop with a
    reason, not fall through to a paper fill wearing a live `mode` -- that would
    put a record in the ledger claiming money moved when none did, which is
    worse than either outcome on its own.
    """
    name = str(venue or "").strip().lower()
    # `paper:kalshi` and friends never reach here: `place_order` only calls a
    # submitter in LIVE mode, and those venues exist only in paper.
    if name == "kalshi":
        from syndicate.features.shared.kalshi_orders import kalshi_submitter

        return kalshi_submitter(_kalshi_price_for)
    return None


def _kalshi_price_for(request) -> float | None:
    """The CURRENT Kalshi ask for this contract, in dollars.

    Re-read at submit time rather than taken from the plan, and that is
    deliberate even though the plan's price is what the EV was computed from:
    the limit price we send has to be one Kalshi is actually showing, or the
    order rests unfilled. The gap between the two IS the slippage, and
    `execution_ledger` records both so it stays visible.
    """
    from syndicate.features.shared.kalshi_client import dollars_to_probability
    from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

    ticker = str(getattr(request, "venue_ticker", "") or "").strip()
    if not ticker:
        return None
    try:
        payload = read_json_file(reports_root() / "intelligence" / "kalshi_markets.json") or {}
    except Exception:
        return None
    for market in payload.get("markets") or []:
        if str(market.get("ticker") or "") != ticker:
            continue
        side = str(getattr(request, "side", "") or "").strip().lower()
        key = "no_ask_dollars" if side in {"under", "no"} else "yes_ask_dollars"
        return dollars_to_probability(market.get(key))
    return None


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
