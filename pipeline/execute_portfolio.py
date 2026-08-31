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

import datetime as _dt
import os
import time
from collections.abc import Sequence
from typing import Any, Mapping

from syndicate.features.shared.execution_ledger import (
    LIVE,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_SUBMITTED,
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


def _venue_ticker_of(position: Mapping[str, Any]) -> str | None:
    """The venue's contract id as a STRING, whatever shape the plan stored.

    --------------------------------------------------------------------------
    THE DICT IS STRINGIFIED HERE, AND THAT IS WHERE IT WENT WRONG
    --------------------------------------------------------------------------

    This was `str(position.get("venue_ticker")).strip()`. `venue_scope.py:190`
    stamps `ticker_resolver(row)` verbatim, and the two venues return different
    shapes: Kalshi a string ticker, Polymarket a dict
    `{slug, tick_size, minimum_trade_qty}` -- because `order_body` REFUSES to
    infer the last two and the resolver is the only thing holding them.

    So a Polymarket position arrived here as a dict and left as the string
    `"{'slug': 'aec-mlb-tex-cws-2026-08-25', 'tick_size': 0.005, ...}"`, which
    is TRUTHY, sails past every `if not slug` guard, and is then looked up in
    the slate as a slug. MEASURED 2026-08-25 15:50:40Z, after the deploy that
    was supposed to fix this:

        POLYMARKET_MARKET_NOT_FOUND
          slug={'slug': 'aec-mlb-tex-cws-2026-08-25', 'tick_size': 0.005, ...}

    **The first fix read the dict inside `_polymarket_resolve_market`, which is
    one layer too late** -- by then `str()` had already run here, and
    `isinstance(raw_ticker, Mapping)` was False on a string that merely looked
    like a dict. The log line said so plainly and is the only reason this was
    caught on the same slate rather than assumed fixed.

    Normalised at the BOUNDARY instead, so `OrderRequest.venue_ticker` holds
    what its type says: a string. `tick_size` and `minimum_trade_qty` are not
    carried on the request -- `_polymarket_resolve_market` reads both from the
    slate row, which is the venue's own current answer and outranks a value
    captured a refresh earlier.
    """
    raw = position.get("venue_ticker")
    if isinstance(raw, Mapping):
        # Polymarket. An entry with no slug is not a contract id, and returning
        # `"{}"` would be the same truthy-garbage bug in a smaller costume.
        return str(raw.get("slug") or "").strip() or None
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


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
        # THE PRE-2026-08-30 KEY, and WITHOUT THIS LINE THE MIGRATION GUARD IS
        # INERT. `portfolio_commit` emits it and `record_order` checks it, but
        # the request in between never carried it -- so `_legacy_idempotency_key`
        # returned None on every order and the dual-key check was decoration.
        #
        # Caught in production 2026-08-30 18:41Z, on the first executor cycle
        # after the fix deployed: `placed=0 duplicates=8` on kalshi and
        # `duplicates=1` on polymarket looked like the guard working, and
        # `LEGACY_KEY_MATCH` had fired ZERO times. Those duplicates matched on
        # the plan's STORED keys, which still predate the change -- the real
        # test arrives on the next plan rebuild, when fresh keys are computed
        # and nothing would have matched the ledger's pre-fix rows.
        #
        # `presence != reachability`: three modules each held a correct half and
        # the chain was never joined.
        legacy_position_key=position.get("legacy_position_key"),
        opening_key=position.get("opening_key"),
        game_pk=(str(position.get("game_pk")).strip() or None)
        if position.get("game_pk") is not None
        else None,
        # THE EXCHANGE CONTRACT, stamped by `venue_scope` at decision time from
        # the same match that supplied the price. None on an unrestricted row --
        # there is no single contract when the price came from an aggregator's
        # best-of-many, which is exactly why the Kalshi adapter refuses without
        # one rather than picking a plausible ticker at submit time.
        venue_ticker=_venue_ticker_of(position),
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

    # ASK THE VENUE FIRST. Everything below this line reasons about our own
    # ledger -- the stranded-order gate, the daily budget, the duplicate check
    # -- and all of it is only as true as the ledger is. A resting order that
    # filled since the last run is a position we hold and do not know about; a
    # phantom fill is a position we do not hold and do believe in. Both are
    # corrected here, before any decision is made on top of them.
    #
    # Live only: paper orders have no venue to ask.
    #
    # NEVER FATAL. A venue that will not answer leaves the ledger untouched and
    # the run continues under the conservative reading -- which is exactly what
    # the gate below enforces, since an unreconciled order still blocks.
    if mode == LIVE:
        try:
            from syndicate.features.shared.execution_ledger import reconcile_live_orders

            # THE VENUE WE ARE ABOUT TO PLACE ON, not the default. This called
            # `reconcile_live_orders()` bare, and its `venue` defaults to
            # `"kalshi"` -- so a Polymarket order was never asked about and its
            # `submitted` row could not clear. Measured 2026-08-25T16:40:00Z:
            # one resting Polymarket order blocked BOTH scopes, and the block
            # was self-sustaining because the read that lifts it never ran.
            #
            # Both venues every pass, not just `venue`: the gate below is
            # global -- ANY unreconciled live order blocks this run whatever
            # venue it belongs to -- so reconciling only our own would leave us
            # blocked by a row we deliberately declined to ask about.
            for reconcile_venue in ("kalshi", "polymarket"):
                outcome = reconcile_live_orders(venue=reconcile_venue)
                if str(outcome.get("status") or "") != "ok":
                    print(
                        f"[execute_portfolio] RECONCILE venue={reconcile_venue}"
                        f" status={outcome.get('status')}"
                        f" reason={outcome.get('reason')}",
                        flush=True,
                    )
        except Exception as exc:
            print(
                f"[execute_portfolio] RECONCILE_FAILED {type(exc).__name__}: {exc}",
                flush=True,
            )

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

    # LIVE VENUE COMES FROM THE SCOPE, NEVER FROM THE ENV VAR.
    #
    # This read `os.environ["SYNDICATE_EXECUTION_VENUE"]` directly. That was
    # already redundant -- the comment six lines down says "in live mode the
    # venue IS the scope" -- and it was correct only for as long as the env var
    # held exactly one venue equal to the scope it was called with.
    #
    # MEASURED 2026-08-25T00:13:26Z, the first tick after the var became a
    # list: both venues refused with
    # `no_adapter_for_venue:kalshi,polymarket`. The loop passed `scope=kalshi`
    # and `scope=polymarket` correctly; this line then looked past the argument
    # and read the WHOLE STRING back out of the environment, so
    # `_venue_submitter` was asked for an adapter named "kalshi,polymarket" and
    # there is none. Kalshi, which had been placing, stopped placing.
    #
    # It fails CLOSED, which is the only reason this was cheap: an unknown
    # venue name resolves to no adapter and `place_order` rejects rather than
    # falling through to a paper fill wearing a live mode. Still a regression,
    # and the fix is to trust the argument that was passed in.
    venue = PAPER_VENUE if mode != LIVE else scope
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

    caps = limits(mode, venue=venue)
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
    filled = 0
    failed = 0
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

        # TOO EARLY TO PLACE  [2026-08-31, user decision]
        #
        # MEASURED, and this is the only cause left standing after ten were
        # eliminated: Polymarket fills happen on LIVE-or-PAST markets (8 of 8)
        # and pregame orders rest (3 of 3). PRICE IS NOT THE CONSTRAINT -- we
        # bid the quote and they rested, then bid a tick ABOVE it and they
        # rested again, same markets, same session. There is no book to hit.
        #
        # WHAT PLACING EARLY ACTUALLY COSTS. Not the stake -- an unfilled order
        # holds no reserved funds (balance was flat at $87.26 across a
        # cancellation). It costs CHURN: the order rests, the venue cancels it,
        # the next tick re-places it, and that submit -> cancel -> resubmit loop
        # is where the duplicate exposure came from ($9.12 on lad-det, two live
        # orders for one intended bet).
        #
        # HOLD, DO NOT DROP. `skipped` means "not placed on this pass", and the
        # position stays in the plan, so the next tick inside the window places
        # it normally. Nothing is abandoned.
        held = _polymarket_hold_hours(request, venue)
        if held is not None:
            skipped += 1
            refused["too_early_to_place"] = refused.get("too_early_to_place", 0) + 1
            print(
                f"[execute_portfolio] HELD_TOO_EARLY venue={venue}"
                f" ticker={getattr(request, 'venue_ticker', None)!r}"
                f" market={getattr(request, 'market', None)}"
                f" hours_to_commence={held:.1f}"
                f" threshold={_polymarket_min_hours_to_commence()}"
                " -- pregame orders do not fill at any price; it will be placed nearer kickoff",
                flush=True,
            )
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
        # PLACED MEANS THE VENUE TOOK IT. FILLED MEANS IT TRADED.
        #
        # These were one counter, and the phantom-fill fix silently broke it.
        # Before that fix a submit response defaulted to `filled`, so counting
        # fills happened to count placements too. Now a resting limit order
        # correctly records `submitted` -- and MEASURED 2026-08-24T15:38:23Z,
        # a real order went to Kalshi (Sandy Alcantara over 4.5 Ks, 3 contracts
        # at $0.50) and the run reported `placed=0 duplicates=0 retried=0
        # skipped=0 refused={}`. Every counter zero, an order at the venue.
        #
        # That is the exact reading `LIVE_ORDER` was added to prevent, arrived
        # at from the other direction: making the STATUS honest made the COUNT
        # dishonest, because the count was reading the status as a proxy for a
        # different question. A correct fix that breaks its neighbour is still
        # a break.
        #
        # So the two questions get two counters. A limit order that rests all
        # afternoon is placed and not filled, and both of those are true.
        if status in {STATUS_FILLED, STATUS_SUBMITTED}:
            placed += 1
        if status == STATUS_FILLED:
            filled += 1
        if status == STATUS_FAILED:
            failed += 1
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
        f"filled={filled} failed={failed} "
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
        # Reported apart from `placed` because a resting order is placed and
        # not filled, and collapsing them makes a working limit book look like
        # a run that did nothing.
        "filled": filled,
        "failed": failed,
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
    if name == "polymarket":
        from syndicate.features.shared.polymarket_us_orders import polymarket_us_submitter

        return polymarket_us_submitter(_polymarket_resolve_market)
    return None


def _yes_leg_corroboration_required() -> bool:
    """Must the venue's `yesLegIndex` agree with our own away-team position
    before a team side is placed? YES by default, and that default is the fix.

    An env switch rather than a code edit because the answer is empirical and
    the log line beside it (`POLYMARKET_YES_LEG ... agree=`) is what will
    settle it. If disagreements turn out to be common AND the venue's index
    turns out to be the right one, this comes off in minutes rather than in a
    deploy. It does not open team betting on its own -- with it off, a market
    still needs a stated `yesLegIndex`, and one that states none is refused by
    `_resolve_outcome_side` exactly as it is today.
    """
    raw = (os.environ.get("SYNDICATE_POLYMARKET_YES_LEG_CORROBORATE") or "").strip()
    # ABSENT MEANS ON. `bool(os.environ.get(...))` would read "false" as True,
    # and an unknown value must not land on the permissive branch.
    return raw.lower() not in {"0", "false", "no", "off"}


def max_slippage_dollars() -> float:
    """How far worse than the planned price we will still pay, in dollars.

    A MARKETABLE LIMIT WITHOUT THIS IS "PAY ANYTHING". Repricing to whatever
    the venue currently shows is how the order fills; refusing to bound it is
    how it fills at a price the edge was never computed against. Three cents
    by default on a contract that settles at a dollar -- roughly a 3% band.
    """
    raw = (os.environ.get("SYNDICATE_EXECUTION_MAX_SLIPPAGE_DOLLARS") or "").strip()
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return 0.03
    return parsed if parsed > 0 else 0.03


def _kalshi_price_for(request) -> float | None:
    """The price to send: the venue's CURRENT ask, bounded by slippage.

    A MARKETABLE LIMIT. This used to read `kalshi_markets.json` and call that
    "re-read at submit time" -- but the artifact refreshes 12 series a tick
    across 155, so its ask can be ~26 minutes old. Measured 2026-08-24: we sent
    $0.54 because that was the artifact's ask; the live ask was $0.56, and the
    order rested unfilled.

    A resting order is worse than a missed one. It fills only if the market
    comes back to our stale price -- which is the market moving AGAINST the
    thesis -- so a standing limit at a price we no longer believe is a free
    option written to everyone else.

    So: read the live ask and pay it, unless it has moved further than
    `max_slippage_dollars` from what the plan priced. Beyond that the edge is
    not the edge we sized, and refusing is the honest answer.

    Falls back to the artifact ONLY when the live read fails, and says so --
    a stale price is better than no order, but the two must not be confused.
    """
    from syndicate.features.shared.kalshi_client import dollars_to_probability, fetch_market

    ticker = str(getattr(request, "venue_ticker", "") or "").strip()
    if not ticker:
        return None
    side = str(getattr(request, "side", "") or "").strip().lower()
    key = "no_ask_dollars" if side in {"under", "no"} else "yes_ask_dollars"

    planned = _artifact_price(ticker, key)

    live = None
    event_ticker = ""
    try:
        result = fetch_market(ticker)
        if result.get("status") == "ok":
            market = result.get("market") or {}
            live = dollars_to_probability(market.get(key))
            event_ticker = str(market.get("event_ticker") or "")
        else:
            print(
                f"[execute_portfolio] LIVE_PRICE_UNAVAILABLE ticker={ticker}"
                f" reason={result.get('reason')}",
                flush=True,
            )
    except Exception as exc:
        print(
            f"[execute_portfolio] LIVE_PRICE_ERROR ticker={ticker}"
            f" {type(exc).__name__}: {exc}",
            flush=True,
        )

    if live is None:
        # The artifact, explicitly labelled. Not silently -- an order priced off
        # a 26-minute-old quote should be visible as such in the one log a
        # person reads while money is moving.
        print(
            f"[execute_portfolio] PRICE_FROM_ARTIFACT ticker={ticker} price={planned}",
            flush=True,
        )
        return planned

    planned = planned_probability(planned)
    if planned is not None:
        drift = round(live - planned, 4)
        if drift > max_slippage_dollars():
            # WORSE than planned by more than we allow. Refused by raising, so
            # the order is recorded with a reason rather than silently skipped.
            raise _SlippageExceeded(
                f"slippage: planned={planned} live={live} drift={drift:+.4f}"
                f" max={max_slippage_dollars()}"
            )
        print(
            f"[execute_portfolio] LIVE_PRICE ticker={ticker} planned={planned}"
            f" live={live} drift={drift:+.4f} event_ticker={event_ticker or '-'}",
            flush=True,
        )
    return live


class _SlippageExceeded(Exception):
    """The live price moved past the tolerance. Never reached the venue."""

    venue_contacted = False


def _artifact_price(ticker: str, key: str) -> float | None:
    """The last price the refresh recorded. The FALLBACK, not the source."""
    from syndicate.features.shared.kalshi_client import dollars_to_probability
    from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

    try:
        payload = read_json_file(reports_root() / "intelligence" / "kalshi_markets.json") or {}
    except Exception:
        return None
    # THROUGH THE MERGE HELPER, not `payload["markets"]`. That key is no longer
    # persisted: storing the merged list beside the per-series entries wrote the
    # same payload twice and pushed the document past the store's 8MB ceiling,
    # at which point it stopped being written at all. The helper reads the
    # per-series entries and still falls back to the legacy key.
    from pipeline.kalshi_odds_refresh import markets_from_state

    for market in markets_from_state(payload):
        if str(market.get("ticker") or "") == ticker:
            return dollars_to_probability(market.get(key))
    return None


def planned_probability(value: Any) -> float | None:
    """`requested_price` as a PROBABILITY, whatever unit it arrived in.

    THE SLIPPAGE GUARD HAS NEVER WORKED, on either venue, because it compared
    two different units. MEASURED 2026-08-25T17:59:06Z, the first totals order
    to resolve a side:

        _SlippageExceeded: polymarket_slippage: slug=tsc-mlb-tb-det-2026-08-25-7pt5
            planned=-108.0 price=0.52 drift=+108.5200 max=0.03

    `planned` is AMERICAN ODDS off our own board; `price` is a probability from
    the venue. Subtracting them is meaningless, and the meaninglessness is
    ASYMMETRIC, which is why it went unnoticed:

      * negative American odds (-108) produce a huge POSITIVE drift and refuse
        every order;
      * positive American odds (+104) produce a huge NEGATIVE drift, which is
        never `> max`, so the order sails through unchecked.

    The one live order that reached a venue today was `planned=104.0` against
    `price=0.495` -- drift -103.5, silently passed. The single guard standing
    between us and a bad fill was decided by the SIGN of the odds.

    Kalshi's copy at `_kalshi_price_for` had the identical defect and is fixed
    through this same helper, so the two cannot drift apart again.

    UNIT IS INFERRED FROM MAGNITUDE, because both forms genuinely occur: a
    probability is strictly inside (0, 1), and American odds are conventionally
    at least 100 away from zero. Anything between is AMBIGUOUS and returns None
    rather than being guessed -- a guessed unit here is a guessed guard.
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


def _decode_polymarket_list(value: Any) -> list[Any] | None:
    """`outcomes`/`outcomePrices` arrive as either a real list or a JSON-
    encoded string, depending on which layer last touched the row. Small and
    duplicated from `kalshi_polymarket_arb._decode_list` on purpose: that is a
    private helper of another lane's module, and this file's own contract is
    that a price-and-side resolver here never reaches across a lane boundary
    for logic it can own in six lines.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            import json

            decoded = json.loads(value)
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, list) else None
    return None


# Same vocabulary `kalshi_orders._side_to_kalshi` and
# `polymarket_us_orders._side_to_outcome` already use for `request.side` --
# not invented here, reused so all three venues agree on what "the home-ish
# side" means.
_HOME_LIKE_SIDES = {"yes", "over", "home"}

# Board market names whose OUTCOMES are Over/Under rather than team names.
_TOTAL_MARKETS = {"totals", "total", "totals_alt", "alternate_totals"}
# ...and whose outcomes are signed numbers, naming no team at all.
_SPREAD_MARKETS = {"spreads", "spread", "spreads_alt", "alternate_spreads", "run_line", "puck_line"}


# The ceiling is a MULTIPLE of the writer's cadence, and the multiple is named
# once. Restating the product is what let the two drift apart.
_SLATE_CEILING_MULTIPLE = 3


def _slate_ceiling_default() -> float:
    from syndicate.features.shared.polymarket_us_markets import SLATE_INTERVAL_SECONDS

    return float(SLATE_INTERVAL_SECONDS * _SLATE_CEILING_MULTIPLE)


def _polymarket_max_price_age_seconds() -> float:
    """How old the persisted slate may be and still price a real order.

    Default is THREE TIMES the writer's cadence, DERIVED from
    `polymarket_us_markets.SLATE_INTERVAL_SECONDS` rather than restated -- so a
    couple of missed writes are tolerated and a stopped writer is not.

    LOWERED WITH THE CADENCE, and that coupling is the point. This was 1800s
    against a 900s writer. When the writer dropped to 180s the old ceiling
    became TEN times the cadence, which would have let a writer that stopped
    nine cycles ago still price a real order -- the guard would still have been
    present, still logged, and no longer guarding anything. Tied to the
    cadence deliberately: a ceiling unrelated to how often the artifact is
    refreshed either refuses
    healthy slates or admits dead ones.
    """
    raw = os.environ.get("SYNDICATE_POLYMARKET_MAX_PRICE_AGE_SECONDS")
    try:
        parsed = float(str(raw).strip())
    except (TypeError, ValueError):
        return _slate_ceiling_default()
    # A non-positive ceiling is a typo, not an instruction to refuse everything
    # forever -- same reading `execution_guard._float_env` gives a bad cap.
    return parsed if parsed > 0 else _slate_ceiling_default()


def _polymarket_min_hours_to_commence() -> float:
    """Hold a Polymarket order further out than this many hours from kickoff.

    `SYNDICATE_POLYMARKET_MIN_HOURS_TO_COMMENCE`. **The default of 24 is a
    JUDGEMENT, not a measurement, and it is deliberately loose.** What is
    measured is only the two ends: orders on LIVE markets fill (8 of 8), and
    orders 12 hours and 5 days out do not (3 of 3, at two different prices).
    Nothing establishes where between "live" and "12 hours" the boundary sits,
    so this suppresses only the clearly-premature end and leaves the ambiguous
    middle alone.

    `0` disables the hold entirely and restores placing whenever the plan says.
    """
    raw = str(os.environ.get("SYNDICATE_POLYMARKET_MIN_HOURS_TO_COMMENCE") or "").strip()
    if not raw:
        return 24.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        print(
            f"[execute_portfolio] MIN_HOURS_TO_COMMENCE_UNREADABLE {raw!r} -- not holding",
            flush=True,
        )
        return 0.0


def _polymarket_hold_hours(request, venue: str) -> float | None:
    """Hours to kickoff if this order should be HELD, else None.

    RETURNS None ON ANYTHING IT CANNOT ESTABLISH. An unreadable or absent
    `commence_time` must not silently suppress a bet: "we do not know when this
    starts" and "this starts too far away" are different facts, and only the
    second is a reason not to place. Unknown places, as it does today.
    """
    if "polymarket" not in str(venue or "").lower():
        return None
    threshold = _polymarket_min_hours_to_commence()
    if threshold <= 0:
        return None
    raw = getattr(request, "commence_time", None)
    if not raw:
        return None
    try:
        text = str(raw).strip().replace("Z", "+00:00")
        starts = _dt.datetime.fromisoformat(text)
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=_dt.timezone.utc)
    except (TypeError, ValueError):
        return None
    hours = (starts - _dt.datetime.now(_dt.timezone.utc)).total_seconds() / 3600.0
    # ALREADY STARTED IS NEVER TOO EARLY. A live market is the one regime that
    # demonstrably fills, so a negative value must place, not hold.
    return hours if hours > threshold else None


def _polymarket_cross_ticks() -> int:
    """Ticks to bid ABOVE the venue quote. `SYNDICATE_POLYMARKET_CROSS_TICKS`.

    Defaults to 1: this is a running experiment (see the block that calls it),
    and the default is the arm being tested. `0` restores bidding exactly the
    quote. Bounded at 3 -- a large cross stops being a spread-crossing test and
    becomes an unpriced market order, and the slippage guard should not be the
    only thing standing between a typo and the book.
    """
    raw = str(os.environ.get("SYNDICATE_POLYMARKET_CROSS_TICKS") or "").strip()
    if not raw:
        return 1
    try:
        return max(0, min(3, int(float(raw))))
    except (TypeError, ValueError):
        # UNREADABLE IS NOT ZERO and is not the default either -- say so, then
        # take the safe arm, which is not crossing.
        print(
            f"[execute_portfolio] POLYMARKET_CROSS_TICKS_UNREADABLE {raw!r} -- not crossing",
            flush=True,
        )
        return 0


def _polymarket_resolve_market(request) -> tuple | None:
    """`(slug, price, tick_size, min_qty)` for one Polymarket US position, or
    `None` to refuse cleanly -- which `polymarket_us_submitter` turns into an
    `OrderBuildError` (recorded as failed, never sent at a price nobody chose,
    same discipline `_kalshi_price_for` returning `None` uses).

    --------------------------------------------------------------------------
    READS THE PERSISTED ARTIFACT, NEVER CALLS THE VENUE DIRECTLY
    --------------------------------------------------------------------------

    An earlier version of this function called
    `polymarket_us_markets.fetch_game_markets()` live, on the reasoning that no
    single-market-by-id fetch exists on this venue. MEASURED 2026-08-24 (same
    day, `.syndicate/deploys.md`, the owning lane's own finding):
    `venue_quote_adapters.py`'s own header states outright that "a second
    independent caller for one venue is a documented incident class here"
    (`#139/#144` for MLB, `#148` for soccer) -- and that module already reads
    `polymarket_us_markets.GAME_SLATE_ARTIFACT`
    (`reports/intelligence/polymarket_us_games.json`, refreshed on a 900s
    cadence by `persist_game_slate`) instead of calling the venue, for exactly
    this reason. This function now does the same rather than being the second
    independent caller.

    --------------------------------------------------------------------------
    KEYED BY `slug`, NOT `id` -- THE ARTIFACT DOES NOT CARRY `id`
    --------------------------------------------------------------------------

    `polymarket_us_markets._SLATE_STORAGE_FIELDS` (what actually gets
    persisted) is `slug, sportsMarketTypeV2, outcomes, outcomePrices, line,
    gameStartTime, orderPriceMinTickSize, minimumTradeQty, orderable` -- no
    `id`. So `request.venue_ticker` is read here as the Polymarket market's
    `slug` (`OrderRequest.venue_ticker`: "the venue's contract id" -- the
    field Kalshi's own ticker resolver fills with a Kalshi ticker; here it
    holds a different venue's identifier, same as that field already does for
    Kalshi). This also means `order_body`'s own `market_slug` argument needs
    no separate lookup: what identifies the row IS what gets sent.

    Nothing populates `request.venue_ticker` with a Polymarket slug yet --
    `portfolio_commit.py::_venue_price_resolver`'s polymarket branch is what
    would do that, and it does not exist (see this lane's own note in
    `.syndicate/lanes.md`: that is a full board-join resolver across every
    market type, materially bigger scope than wiring this submitter). Until it
    lands, a polymarket position reaching here has an empty `venue_ticker` and
    this refuses immediately -- wiring the submitter is necessary but not
    sufficient on its own.

    --------------------------------------------------------------------------
    STALENESS: UP TO 900s OLD, LOGGED, NEVER HARD-REFUSED HERE
    --------------------------------------------------------------------------

    The artifact's own `fetched_at` is logged on every resolution so a reader
    can see how old the price actually was when the order used it. This does
    NOT bound it the way `_kalshi_price_for`'s slippage check bounds a live
    read against a stale artifact -- there is no live comparison available
    without becoming the second caller this function exists to avoid. The
    `requested_price` slippage check below is the only freshness guard.

    --------------------------------------------------------------------------
    WHICH PRICE, NOT WHICH `outcomeSide`
    --------------------------------------------------------------------------

    This function only selects the persisted price for OUR named team --
    `request.home_team`/`away_team` matched against the market's `outcomes`
    via `kalshi_board_join._side_for_team`, the SAME resolver
    `kalshi_polymarket_arb.py` already uses and tests for the identical
    problem (Polymarket's `outcomes` carry bare team names, never "yes"/"no",
    and never a guaranteed array order).

    IT ALSO SELECTS THE SIDE, and that is a correction. This docstring used to
    end by naming the risk and leaving it: the `outcomeSide` was decided
    separately by `_side_to_outcome` from `request.side`, the YES/NO convention
    was "UNVERIFIED against a real venue response", and getting the price right
    for the wrong side "would still buy the wrong side at a price never quoted
    for it". A live order then did precisely that -- `side=home` on Texas @
    Chicago White Sox bought TEXAS at the White Sox's price, and did not fill,
    because the limit was priced for the outcome it was not buying.

    A named risk is not a mitigation. The index this function resolves is now
    returned and carried into `order_body`, so the price and the side are two
    readings of one match instead of two independent guesses that happened to
    be compared by nobody.
    """
    from syndicate.features.shared.kalshi_board_join import _side_for_team
    from syndicate.features.shared.polymarket_us_markets import GAME_SLATE_ARTIFACT
    from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

    # `venue_ticker` CARRIES A DICT FOR THIS VENUE, NOT A STRING.
    #
    # MEASURED 2026-08-25 14:57:34Z, on what would have been the first two
    # Polymarket orders ever placed:
    #
    #   LIVE_ORDER status=failed venue=polymarket
    #     ticker={'slug': 'tsc-mlb-bal-stl-2026-08-25-8pt5', 'tick_size': 0.005,
    #             'minimum_trade_qty': 0.01}
    #     error='OrderBuildError: market_unresolved_for_position'
    #
    # `venue_scope.py:190` stamps `scoped_row["venue_ticker"] =
    # ticker_resolver(row)` VERBATIM. Kalshi's resolver returns a string ticker;
    # `polymarket_ticker_resolver` returns a dict, because `order_body` REFUSES
    # to infer `tick_size` and `minimum_trade_qty` and the resolver is the only
    # thing holding them. So this field legitimately holds two shapes.
    #
    # `str(a_dict)` is TRUTHY, so the `POLYMARKET_NO_SLUG` guard below never
    # fired -- the stringified dict was carried forward and looked up in the
    # slate as if it were a slug, matched nothing, and returned None. Every
    # Polymarket order has failed this way; none has ever been placeable.
    #
    # Read as a dict FIRST, falling back to the string form: a caller that
    # stamps a bare slug (a hand-built request, an older plan) still works, and
    # nothing about that path changes.
    raw_ticker = getattr(request, "venue_ticker", None)
    ticker_tick = ticker_min_qty = None
    if isinstance(raw_ticker, Mapping):
        slug = str(raw_ticker.get("slug") or "").strip()
        ticker_tick = raw_ticker.get("tick_size")
        ticker_min_qty = raw_ticker.get("minimum_trade_qty")
    else:
        slug = str(raw_ticker or "").strip()
    if not slug:
        print(
            "[execute_portfolio] POLYMARKET_NO_SLUG -- venue_ticker unset or"
            f" carries no slug (type={type(raw_ticker).__name__})",
            flush=True,
        )
        return None

    try:
        payload = read_json_file(reports_root().joinpath(*GAME_SLATE_ARTIFACT))
    except Exception as exc:
        print(
            f"[execute_portfolio] POLYMARKET_ARTIFACT_READ_ERROR slug={slug}"
            f" {type(exc).__name__}: {exc}",
            flush=True,
        )
        return None
    rows = (payload or {}).get("markets")
    if not isinstance(rows, list):
        print(f"[execute_portfolio] POLYMARKET_ARTIFACT_EMPTY slug={slug}", flush=True)
        return None

    # BOUND THE AGE OF A PRICE THAT IS ABOUT TO BUY SOMETHING.
    #
    # This function's docstring said staleness here is "logged, never
    # hard-refused" -- reasonable when the only alternative was becoming a
    # second independent caller. It stopped being reasonable on 2026-08-25,
    # when two facts met: Polymarket went live with real money, and the slate
    # writer turned out to be BOOT-ONLY (called once before the loop, so the
    # artifact aged with the worker's uptime -- 99 minutes between writes on a
    # 900s cadence). The writer is fixed in the same change; this is the guard
    # that means a writer which stops for any OTHER reason cannot quietly
    # price an order off an hours-old book.
    #
    # Fails CLOSED and BY NAME. A missing timestamp refuses too: "we cannot
    # tell how old this is" and "this is fresh" must never share an outcome,
    # which is the same fail-closed reading `kill_switch_engaged` uses for an
    # unreadable flag.
    max_age = _polymarket_max_price_age_seconds()
    fetched_at = (payload or {}).get("fetched_at")
    try:
        age = time.time() - float(fetched_at)
    except (TypeError, ValueError):
        print(
            f"[execute_portfolio] POLYMARKET_ARTIFACT_NO_FETCHED_AT slug={slug}"
            " -- refusing rather than pricing an order off a book of unknown age",
            flush=True,
        )
        return None
    if age > max_age:
        print(
            f"[execute_portfolio] POLYMARKET_ARTIFACT_STALE slug={slug}"
            f" age_s={age:.0f} max_s={max_age:.0f}"
            " -- refusing rather than buying at a price this old",
            flush=True,
        )
        return None

    row = next((m for m in rows if isinstance(m, Mapping) and str(m.get("slug") or "") == slug), None)
    if row is None:
        print(f"[execute_portfolio] POLYMARKET_MARKET_NOT_FOUND slug={slug}", flush=True)
        return None
    if not row.get("orderable"):
        # `orderable` is `trimmed_row`'s own check that tick size and minimum
        # quantity are BOTH present -- see `polymarket_us_markets.trimmed_row`.
        print(f"[execute_portfolio] POLYMARKET_MARKET_NOT_ORDERABLE slug={slug}", flush=True)
        return None

    outcomes = _decode_polymarket_list(row.get("outcomes"))
    prices = _decode_polymarket_list(row.get("outcomePrices"))
    if not (isinstance(outcomes, list) and isinstance(prices, list)) or len(outcomes) != 2 or len(prices) != 2:
        print(f"[execute_portfolio] POLYMARKET_OUTCOMES_UNREADABLE slug={slug}", flush=True)
        return None

    resolution = {
        "home_team": getattr(request, "home_team", None),
        "away_team": getattr(request, "away_team", None),
    }
    sport = getattr(request, "sport", None)
    wants_home = str(getattr(request, "side", "") or "").strip().lower() in _HOME_LIKE_SIDES

    # KEEP THE INDEX. This loop already establishes exactly which entry of
    # `outcomes` is our team -- and it used to throw that away and return only
    # the price, leaving `order_body` to pick the side positionally from
    # `home`/`away`. The two disagreed, and on 2026-08-25T16:08:10Z that bought
    # TEXAS on a `side=home` row whose home team is the White Sox, at the price
    # resolved for the White Sox. One reading now feeds both.
    market = str(getattr(request, "market", "") or "").strip().lower()
    our_side = str(getattr(request, "side", "") or "").strip().lower()

    # WHICH OUTCOME IS OURS DEPENDS ON WHAT KIND OF MARKET THIS IS.
    #
    # MEASURED 2026-08-25T17:45:13Z. The slug was RIGHT -- the right game and
    # the right number -- and the order still failed:
    #
    #   totals over 7.5 Tampa Bay Rays @ Detroit Tigers
    #   slug=tsc-mlb-tb-det-2026-08-25-7pt5
    #   OrderBuildError: market_unresolved_for_position
    #
    # This loop matched every outcome with `_side_for_team`, which resolves
    # TEAM NAMES. A totals market's outcomes are `["Over","Under"]` and a
    # spread's are `["+2.50","-2.50"]` -- neither is a team, so both outcomes
    # were skipped, the price stayed None, and every totals and spreads order
    # on this venue has failed this way since the venue went live. Only
    # moneylines ever resolved, because only moneyline outcomes are teams.
    price = None
    outcome_index = None
    away_index = None
    refusal = None
    # Set when a soccer Yes/No h2h is resolved by its SLUG SUBJECT. The
    # away-index corroboration below cannot apply to a market whose outcomes
    # are literally `Yes`/`No` -- no outcome names a team -- and its
    # corroborator is the subject match itself.
    yes_no_subject_index = None

    if market in _TOTAL_MARKETS:
        # UNAMBIGUOUS. `Over` and `Under` name the side directly, and our own
        # side is already `over`/`under`.
        for position, (name, raw_price) in enumerate(zip(outcomes, prices)):
            if str(name or "").strip().lower() != our_side:
                continue
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                price = None
            else:
                outcome_index = position
            break
        if outcome_index is None:
            refusal = "total_side_not_in_outcomes"
    elif market in _SPREAD_MARKETS:
        # REFUSED BY NAME, and this is a deliberate stop rather than an
        # omission. A spread's outcomes are SIGNED NUMBERS -- `["+2.50",
        # "-2.50"]` -- and nothing in them says which TEAM is getting the
        # points. Our side is `home`/`away`, so pairing them means assuming an
        # ordering, and an assumed ordering on this venue has already bought
        # the wrong team once today at a real cost. The slug's `pos`/`neg`
        # token is a candidate answer and it is UNVERIFIED against the
        # outcomes array, so it stays a candidate.
        refusal = "spread_side_needs_verified_team_mapping"
    else:
        for position, (name, raw_price) in enumerate(zip(outcomes, prices)):
            side = _side_for_team(name, resolution, sport=sport)
            if side == "away":
                # THE CORROBORATING WITNESS, collected in the pass that is
                # already running. Independent of `marketSides`: this comes
                # from OUR board's home/away designation matched against the
                # outcome NAMES, while `yesLegIndex` comes from the venue's own
                # `long` flag. Two sources that can disagree are the only thing
                # standing in for the 8 settled markets that no longer exist.
                away_index = position
            if (
                outcome_index is None
                and price is None
                and side is not None
                and (side == "home") == wants_home
            ):
                # FIRST MATCH WINS, pinned explicitly. The `break` that used to
                # enforce that is gone -- it stopped the scan at our own team
                # and left `away_index` unset whenever ours came first, so the
                # gate below would read "not corroborated" on half the markets
                # for a reason that is an artifact of loop order. Dropping the
                # break without this guard would have let a SECOND matching
                # outcome overwrite the first, which is a different bug and a
                # silent one.
                try:
                    price = float(raw_price)
                except (TypeError, ValueError):
                    price = None
                else:
                    outcome_index = position
        if outcome_index is None:
            refusal = "team_side_not_in_outcomes"
            # ------------------------------------------------------------------
            # SOCCER h2h IS THREE MARKETS, AND ITS OUTCOMES ARE `Yes`/`No`.
            # ------------------------------------------------------------------
            #
            # Polymarket splits a 3-way into one binary per outcome with the
            # SUBJECT in the slug: `atc-epl-liv-not-2026-08-29-liv` is
            # "Liverpool win?", `-draw` is "draw?". So `_side_for_team` above is
            # matching "home"/"away" against `["Yes","No"]` and can never
            # succeed -- every soccer moneyline refused as
            # `team_side_not_in_outcomes` and never reached the yes-leg gate at
            # all. Measured 2026-08-31: 9 markets resolved, 0 gate lines.
            #
            # `polymarket_board_join` ALREADY solved this on the read side and
            # its helpers are imported rather than re-implemented -- a second
            # decoder here could disagree with the one that actually refuses,
            # which is the rule this file already applies to `_outcome_reason_of`.
            #
            # BUYING `No` IS NOT BETTING THE OTHER TEAM. A soccer 3-way has a
            # DRAW leg, so `No` on "will SHA win?" pays on SHE **or** a draw.
            # Only the market whose subject IS our side is takeable, and it is
            # taken as `Yes`. Anything else refuses by name.
            #
            # The `Yes` index is found BY NAME, never by position: the same
            # fixture ships `["Yes","No"]` for one leg and `["No","Yes"]` for
            # the other (measured, `atc-irlp-sha-she-2026-08-21`).
            try:
                from syndicate.features.shared.polymarket_board_join import (
                    _is_yes_no_market,
                    _subject_is_side,
                    parse_slug,
                )
            except Exception as exc:  # noqa: BLE001
                # LOUD, not silent. The first version of this import named the
                # wrong module for `parse_slug`; the bare `except` swallowed the
                # ImportError and the whole branch became inert while three of
                # its own tests still "passed" -- because they assert a REFUSAL,
                # and everything refuses when the decoder is missing. A wiring
                # failure that disables a feature must say so.
                _is_yes_no_market = None
                print(
                    f"[execute_portfolio] YES_NO_DECODER_UNAVAILABLE {exc!r}"
                    " -- every soccer moneyline will refuse",
                    flush=True,
                )
            if _is_yes_no_market is not None and _is_yes_no_market(
                [(str(n), None) for n in outcomes]
            ):
                candidate = {"parsed": parse_slug(slug) or {}}
                if _subject_is_side(candidate, row, our_side, sport):
                    for position, name in enumerate(outcomes):
                        if str(name or "").strip().lower() != "yes":
                            continue
                        try:
                            price = float(prices[position])
                        except (TypeError, ValueError, IndexError):
                            price = None
                        else:
                            outcome_index = position
                            # THE YES LEG, BY NAME. On a literal Yes/No market
                            # the YES leg IS the index of the string "Yes", so
                            # this rides the same channel as a team market's
                            # `yesLegIndex` and `_resolve_outcome_side` returns
                            # OUTCOME_SIDE_YES for our home/away side without a
                            # second code path.
                            yes_no_subject_index = position
                            refusal = None
                        break
                    if outcome_index is None and refusal is not None:
                        refusal = "yes_leg_unpriced_on_yes_no_market"
                else:
                    # NAMED, and deliberately not a fallback to `No`. The
                    # subject is the other team or the draw; taking the
                    # complement would buy an outcome nobody chose.
                    refusal = "yes_no_market_subject_is_not_our_side"

    if price is None or outcome_index is None:
        print(
            f"[execute_portfolio] POLYMARKET_SIDE_REFUSED slug={slug}"
            f" market={market!r} side={our_side!r} reason={refusal}"
            f" outcomes={outcomes!r}",
            flush=True,
        )
        return None

    fetched_at = (payload or {}).get("fetched_at")

    # SNAP FIRST, THEN GUARD -- the guard has to judge the price we will
    # ACTUALLY SEND. `order_body` snaps the limit up to the market's tick, so
    # checking slippage against the raw quote measured a number that never
    # reaches the venue and let up to one tick of drift past a tolerance whose
    # default is only three. Snapping here makes the two agree: `order_body`
    # re-snaps an already-legal price to itself.
    tick = row.get("orderPriceMinTickSize")
    min_qty = row.get("minimumTradeQty")
    tick_value = tick if tick is not None else ticker_tick
    min_qty_value = min_qty if min_qty is not None else ticker_min_qty

    quoted = price
    if tick_value is not None:
        from syndicate.features.shared.polymarket_us_orders import round_price_to_tick

        try:
            price = round_price_to_tick(price, tick_value, direction="up")
        except Exception as exc:
            # UNREADABLE TICK IS NOT A ZERO TICK. Leave the quote untouched and
            # say so; `order_body` refuses on the same value a moment later,
            # which is the right place for that refusal to be raised.
            print(
                f"[execute_portfolio] POLYMARKET_TICK_UNREADABLE slug={slug}"
                f" tick={tick_value!r} {type(exc).__name__}: {exc}",
                flush=True,
            )
            price = quoted
        else:
            # ------------------------------------------------------------
            # THE CROSSING EXPERIMENT  [2026-08-31, user decision]
            # ------------------------------------------------------------
            #
            # WHAT IT TESTS. Every Polymarket order observed splits the same
            # way: PREGAME markets rest untouched (3 of 3 pending, cum=0),
            # LIVE-or-PAST markets fill (8 of 8 settled). And we bid EXACTLY
            # the venue's quote, never under it -- measured on both live
            # orders, `lec-rom` quote 0.48 sent 0.48 and `scp-scf` quote 0.44
            # sent 0.44, both `snapped=False`.
            #
            # Nine explanations are already dead by measurement: the tick
            # floor, a stale ask, bidding a mid, our own cancel loop, market
            # close, a venue expiry (`goodTillTime=None`), insufficient
            # collateral, restart/OOM, and deploy. What survives is that the
            # quote is DISPLAYED with no size behind it pregame -- and that is
            # INFERENCE, because nothing we have reads book DEPTH.
            #
            # This is the cheapest test of it. Bid one tick ABOVE the quote:
            #   fills                      -> size sits just above; price was it
            #   never fills at any price   -> no book yet; the fix is TIMING
            #
            # WHY IT IS CHEAP. A marketable limit fills at the BOOK, not at the
            # limit: `C4N3GPYA4GNQ` was submitted at 0.51 and filled at
            # avgPx=0.4900. A tick of headroom costs nothing when the book is
            # better, and at most one tick when it sits exactly at our price.
            #
            # AND IT STAYS GUARDED. This runs BEFORE the slippage check below,
            # so a cross that pushes past tolerance is REFUSED rather than
            # silently paid -- the reason the snap was moved above that check.
            #
            # `SYNDICATE_POLYMARKET_CROSS_TICKS=0` turns it off. It defaults to
            # 1 because this is a RUNNING experiment, not a shipped policy.
            cross = _polymarket_cross_ticks()
            if cross:
                try:
                    crossed = round(price + cross * float(tick_value), 9)
                except (TypeError, ValueError):
                    crossed = price
                if crossed < 1.0:
                    print(
                        f"[execute_portfolio] POLYMARKET_CROSS slug={slug}"
                        f" quote={quoted} snapped={price} crossed={crossed}"
                        f" ticks={cross} tick={tick_value!r}",
                        flush=True,
                    )
                    price = crossed
                else:
                    # A cross that leaves (0,1) is not a price. Declining to
                    # cross is NOT declining the order -- the snapped price
                    # stands and the order still goes.
                    print(
                        f"[execute_portfolio] POLYMARKET_CROSS_SKIPPED slug={slug}"
                        f" snapped={price} would_be={crossed} -- not a probability",
                        flush=True,
                    )

    planned_raw = getattr(request, "requested_price", None)
    planned = planned_probability(planned_raw)
    if planned_raw is not None and planned is None:
        # AMBIGUOUS UNIT -- named, never guessed, and never silently skipped.
        print(
            f"[execute_portfolio] SLIPPAGE_UNCHECKED slug={slug}"
            f" planned={planned_raw!r} -- not readable as odds or a probability",
            flush=True,
        )
    if planned is not None:
        drift = round(price - planned, 4)
        if drift > max_slippage_dollars():
            raise _SlippageExceeded(
                f"polymarket_slippage: slug={slug} planned={planned_raw}"
                f" planned_prob={planned:.4f} price={price} quoted={quoted}"
                f" drift={drift:+.4f} max={max_slippage_dollars()} fetched_at={fetched_at}"
            )
    # THE NAME WE RESOLVED, not just the number. A price alone cannot be
    # checked against the venue's own order screen; the outcome name can, and
    # that screen is what caught the inverted order.
    # `quoted` AND `price`, not just one. The tick snap silently moved the
    # limit for every order this venue placed and appeared in no log line: the
    # 0.515 that was sent as 0.51 on 2026-08-30 could only be found by pairing
    # this line against FILL_ABOVE_LIMIT. A transform that decides whether an
    # order fills belongs in the log a person reads while money is moving.
    print(
        f"[execute_portfolio] POLYMARKET_ARTIFACT_PRICE slug={slug} price={price}"
        f" quoted={quoted} tick={tick_value!r} snapped={price != quoted}"
        f" planned={planned} fetched_at={fetched_at}"
        f" our_side={getattr(request, 'side', None)}"
        f" outcome_index={outcome_index} outcome={outcomes[outcome_index]!r}"
        f" outcomes={outcomes!r}",
        flush=True,
    )

    # ARTIFACT FIRST, ticker dict as the fallback. The slate row is the venue's
    # own current answer; the values carried on `venue_ticker` were captured at
    # commit time by `polymarket_ticker_resolver` and are the same fields one
    # refresh earlier. `order_body` refuses to INFER either, so having a second
    # source for them is the difference between an order and a refusal when the
    # artifact row is thin.
    # ----------------------------------------------------------------------
    # WHICH LEG DOES THE YES TOKEN PAY -- AND DOES A SECOND SOURCE AGREE?
    # ----------------------------------------------------------------------
    #
    # `yesLegIndex` is derived by `polymarket_us_markets._slate_row_for_storage`
    # from the venue's own `marketSides[].long` and persisted on EVERY row. It
    # has been sitting on the row unread while `_resolve_outcome_side` refused
    # every moneyline for want of exactly this field.
    #
    # WHY A GATE AND NOT A STRAIGHT READ. `yes_leg_index_from_market` says the
    # rule must be "scored against all 8 venue-settled moneylines" first. That
    # cannot be done: `marketSides` is deliberately never persisted, so the rule
    # cannot be re-run against a market that has already settled. The sentence
    # blocks the fix permanently rather than gating it. What replaces it is a
    # SECOND, INDEPENDENT WITNESS -- our own board's away-team designation --
    # and a refusal whenever the two disagree.
    #
    # THE ASYMMETRY THAT MAKES THIS SAFE: today EVERY team side is refused. A
    # market where the two sources disagree is refused exactly as it is now, so
    # the gate cannot be worse than the status quo. It can only add the markets
    # where two independent encodings already agree.
    #
    # EVIDENCE, 2026-08-30 (`findings_2026-08-30_polymarket_yes_leg_evidence.md`):
    # `long_index` VARIES (wnba 1, boxing 1; mlb/nfl/cfb 0), killing the all-NFL
    # constant-0 null result. On 9 real markets `outcomes` order runs 5 matching
    # the slug and 4 REVERSED, so `outcomes[0]` is a coin flip. And on
    # `aec-mlb-az-sf-2026-08-27` -- outcome_index=0 (SF), submitted YES, SF won
    # 6-1, venue graded LOST, held_side=SHORT -- the YES leg is provably the
    # AWAY team. This code sends NO there, which is the token that pays SF.
    #
    # NOT CLAIMED: that "YES == away" is a venue contract. It is an observed
    # regularity over five team-sport markets, and `outcome_side_for_index`
    # already records a market whose outcomes are reversed against its own slug.
    # That is why it is a corroborator that can only REFUSE, never a resolver.
    from syndicate.features.shared.polymarket_us_markets import (
        YES_LEG_INDEX_FIELD,
        YES_LEG_REASON_FIELD,
    )

    yes_leg_index = row.get(YES_LEG_INDEX_FIELD)
    yes_leg_reason = row.get(YES_LEG_REASON_FIELD)
    if yes_no_subject_index is not None:
        # RESOLVED BY SUBJECT, so the away-index gate is skipped -- but SAID,
        # not silently. A gate that quietly stops applying is indistinguishable
        # from one that is passing.
        print(
            f"[execute_portfolio] POLYMARKET_YES_LEG slug={slug}"
            f" yes_leg_index={yes_no_subject_index} away_index=None"
            f" our_index={outcome_index} agree=subject reason='yes_no_market'"
            f" outcomes={outcomes!r}",
            flush=True,
        )
        yes_leg_index = yes_no_subject_index
        yes_leg_reason = "yes_no_market_subject"
    elif market not in _TOTAL_MARKETS and market not in _SPREAD_MARKETS:
        agree = (
            yes_leg_index is not None
            and away_index is not None
            and int(yes_leg_index) == int(away_index)
        )
        print(
            f"[execute_portfolio] POLYMARKET_YES_LEG slug={slug}"
            f" yes_leg_index={yes_leg_index!r} away_index={away_index!r}"
            f" our_index={outcome_index} agree={agree}"
            f" reason={yes_leg_reason!r} outcomes={outcomes!r}",
            flush=True,
        )
        if yes_leg_index is not None and not agree:
            # NAMED, and it returns None like every other refusal here rather
            # than raising: a disagreement is a market we decline, not a broken
            # run. `unknown` must not land on the permissive branch, so an
            # UNSET `away_index` counts as disagreement and refuses too.
            print(
                f"[execute_portfolio] POLYMARKET_SIDE_REFUSED slug={slug}"
                f" market={market!r} side={our_side!r}"
                " reason=yes_leg_disagrees_with_away_index"
                f" yes_leg_index={yes_leg_index!r} away_index={away_index!r}",
                flush=True,
            )
            if _yes_leg_corroboration_required():
                return None

    return (
        slug,
        price,
        tick_value,
        min_qty_value,
        outcome_index,
        (yes_leg_index, yes_leg_reason),
    )


def verify_order_paths(
    selected_date: str, *, venues: Sequence[str] = ("kalshi", "polymarket")
) -> dict[str, Any]:
    """Would today's plan actually BUILD an order at each venue? Never submits.

    WHY THIS EXISTS. Until now the only way to learn whether the order chain
    works was to wait for the portfolio to produce a position, let it reach a
    real venue, and read the failure. That is how every defect on
    2026-08-25 was found -- wrong game, dict-as-slug, wrong side, unreadable
    venue, totals unresolvable, an inert slippage guard -- each one hidden
    behind the one before it, each costing a slate to discover, and every one
    of those positions was a bet we intended to hold and did not.

    A chain of six sequential single-shot discoveries is not a testing
    strategy. This runs the SAME resolve and body-build path the placer uses,
    against the SAME production artifacts, for every position in the plan, and
    reports what would happen -- so the next defect is found in one reading
    rather than one slate.

    IT CANNOT PLACE AN ORDER. There is no submit function anywhere in this
    function and no adapter is constructed; the venue is contacted only by the
    reads the resolvers already do. That is what makes it safe to run on every
    cycle rather than only when someone is watching.

    Grouped by (venue, market, verdict) because the interesting question is
    never "did one order fail" but "which whole market family cannot transact".
    `totals` failing on every row and `h2h` succeeding on every row is a
    different fact from a scattering of misses, and a per-order log cannot show
    it.
    """
    from pipeline.portfolio_commit import read_portfolio_plan

    from pipeline import portfolio_commit

    normalized = str(selected_date or "").strip()[:10]
    out: dict[str, Any] = {"date": normalized, "venues": {}}

    for venue in venues:
        summary: dict[str, dict[str, int]] = {}
        examples: dict[str, str] = {}

        def note(market: str, verdict: str, detail: str = "") -> None:
            bucket = summary.setdefault(market or "unknown", {})
            bucket[verdict] = bucket.get(verdict, 0) + 1
            if detail and verdict not in examples:
                examples[f"{market}|{verdict}"] = detail[:160]

        try:
            plan = portfolio_commit.read_portfolio_plan_for_venue(normalized, venue) or {}
        except Exception as exc:
            out["venues"][venue] = {"status": "plan_unreadable", "reason": f"{type(exc).__name__}: {exc}"}
            continue

        positions = plan.get("positions")
        if not isinstance(positions, list) or not positions:
            out["venues"][venue] = {"status": "no_positions", "markets": {}}
            continue

        for position in positions:
            if not isinstance(position, Mapping):
                continue
            request = _order_from_position(position, normalized, venue)
            if request is None:
                note(str(position.get("market") or ""), "incomplete_position")
                continue
            market = str(getattr(request, "market", "") or "")
            try:
                if venue == "polymarket":
                    # NO TICKER AND UNRESOLVABLE ARE DIFFERENT FAILURES, and
                    # folding them together cost a real order's diagnosis.
                    #
                    # Kalshi has had a distinct `no_venue_ticker` verdict all
                    # along; Polymarket's was counted as `market_unresolved`,
                    # which says "we found the market and could not price it"
                    # about a position that never had a market identified at
                    # all. Measured 2026-08-25 4:36:05 PM Central, an h2h on
                    # Cleveland @ LA Angels rejected with
                    # `market_unresolved_for_position` while the resolver's own
                    # log line said `POLYMARKET_NO_SLUG ... (type=NoneType)`.
                    # The two point at different fixes: one is the board join
                    # not stamping a slug, the other is the slate or the price.
                    #
                    # AND IT CARRIED NO DETAIL. `note()` takes one and this
                    # passed none, so `examples` held nothing for the single
                    # most common Polymarket failure -- a counter naming a
                    # problem while withholding its data, which is the shape
                    # this verifier exists to eliminate.
                    ticker = _venue_ticker_of(position)
                    if not ticker:
                        note(
                            market,
                            "no_venue_ticker",
                            f"{position.get('event_id') or '?'}"
                            f" {position.get('side') or '?'} {position.get('line')}",
                        )
                        continue
                    resolved = _polymarket_resolve_market(request)
                    if not resolved:
                        note(market, "market_unresolved", str(ticker))
                        continue
                    slug, price, tick, min_qty, index = resolved[:5]
                    yes_leg = resolved[5] if len(resolved) > 5 else (None, None)
                    from syndicate.features.shared.polymarket_us_orders import order_body

                    # THE DRY RUN MUST BUILD THE SAME BODY THE LIVE PATH DOES.
                    # Dropping the yes-leg here would make `verify_order_paths`
                    # report `would_build` for a moneyline the real submit
                    # refuses -- a green check for a path that does not run.
                    order_body(
                        request, market_slug=slug, price_dollars=price,
                        tick_size=tick, minimum_trade_qty=min_qty, outcome_index=index,
                        yes_leg_index=yes_leg[0], yes_leg_reason=yes_leg[1],
                    )
                    note(market, "would_build", f"{slug} @ {price}")
                else:
                    ticker = _venue_ticker_of(position)
                    if not ticker:
                        # `price_source` IS THE WHOLE VERDICT HERE, and without
                        # it this line cannot be acted on.
                        #
                        # A row priced from the AGGREGATOR has no Kalshi match
                        # by definition, so it has no contract id and is
                        # correctly unplaceable -- the paper book still records
                        # what the strategy would have done. A row priced from
                        # the VENUE and still missing a ticker is a real defect:
                        # we matched it, priced it, and lost the id.
                        #
                        # Identical outcomes, opposite fixes. Measured
                        # 2026-08-25 5:01:58 PM Central, the first Kalshi
                        # position ever committed reached here as
                        # `{'totals_alt': {'no_venue_ticker': 1}} examples={}`
                        # and nothing on the line said which of the two it was.
                        note(
                            market,
                            "no_venue_ticker",
                            f"price_source={position.get('price_source') or '?'}"
                            f" event={position.get('event_id') or '?'}"
                            f" side={position.get('side') or '?'}"
                            f" line={position.get('line')}",
                        )
                        continue
                    price = _kalshi_price_for(request)
                    if price is None:
                        note(market, "no_live_price", str(ticker))
                        continue
                    from syndicate.features.shared.kalshi_orders import order_body

                    order_body(request, price_dollars=price)
                    note(market, "would_build", f"{ticker} @ {price}")
            except Exception as exc:
                # The venue's own reason, by TYPE and message. A verifier that
                # reported "failed" would reproduce the counter this whole
                # session has been prying data out of.
                #
                # AND FOR AN `OrderBuildError`, BY ITS REASON TOKEN RATHER THAN
                # BY THE EXCEPTION CLASS `[2026-08-28]`. Every refusal that
                # module raises is an `OrderBuildError`, so one bucket held
                # `team_side_needs_verified_yes_leg` beside `price_out_of_range`
                # and `stake_below_minimum_quantity` -- the count told you a
                # family could not transact and not WHY, which is the thing this
                # report exists to say.
                #
                # It matters now because two Polymarket populations are refused
                # for two different unverified mappings:
                # `spread_side_needs_verified_team_mapping` (the slug's
                # `pos`/`neg` token vs the outcomes array) and
                # `team_side_needs_verified_yes_leg` (which outcome the YES
                # token pays). They will be lifted at different times by
                # different evidence, and on the day one is, nobody can tell
                # which population just became placeable from a count of
                # `OrderBuildError`.
                #
                # `str(exc)` still carries the whole message into `examples`;
                # this only changes the KEY. The token is the text before the
                # first colon, which is the convention every refusal in
                # `polymarket_us_orders` and `kalshi_orders` already writes.
                # MATCHED BY CLASS NAME, NOT BY `isinstance`. There are THREE
                # `OrderBuildError` classes -- `kalshi_orders`, `novig_orders`
                # and `polymarket_us_orders` each define their own -- so an
                # `isinstance` check would need all three imported here and
                # would silently stop covering the fourth venue somebody adds.
                # They all subclass `ValueError`, which is too broad to key on.
                reason = str(exc)
                if type(exc).__name__ == "OrderBuildError":
                    token = reason.split(":", 1)[0].strip()
                    # A refusal that carried no token would key on the whole
                    # message -- unbounded cardinality in a counter. Fall back
                    # to the class rather than let that happen.
                    key = token if token and " " not in token else type(exc).__name__
                else:
                    key = type(exc).__name__
                note(market, key, reason)

        out["venues"][venue] = {
            "status": "ok",
            "positions": len(positions),
            "markets": summary,
            "examples": examples,
        }
    return out


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
