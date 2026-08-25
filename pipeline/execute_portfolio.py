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

            reconcile_live_orders()
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
    try:
        result = fetch_market(ticker)
        if result.get("status") == "ok":
            live = dollars_to_probability((result.get("market") or {}).get(key))
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
            f" live={live} drift={drift:+.4f}",
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
    for market in payload.get("markets") or []:
        if str(market.get("ticker") or "") == ticker:
            return dollars_to_probability(market.get(key))
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


def _polymarket_resolve_market(request) -> tuple[str, float, Any, Any] | None:
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
    and never a guaranteed array order). Whether that team is
    `OUTCOME_SIDE_YES` or `_NO` on Polymarket's own books is decided by
    `polymarket_us_orders._side_to_outcome` from `request.side` directly, not
    here -- and that YES/NO convention is itself UNVERIFIED against a real
    venue response (no live order has ever been placed on this venue). Getting
    the PRICE right for the wrong `outcomeSide` would still buy the wrong side
    at a price never quoted for it, so this is named rather than assumed away.
    """
    from syndicate.features.shared.kalshi_board_join import _side_for_team
    from syndicate.features.shared.polymarket_us_markets import GAME_SLATE_ARTIFACT
    from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

    slug = str(getattr(request, "venue_ticker", "") or "").strip()
    if not slug:
        print("[execute_portfolio] POLYMARKET_NO_SLUG -- venue_ticker unset", flush=True)
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

    price = None
    for name, raw_price in zip(outcomes, prices):
        side = _side_for_team(name, resolution, sport=sport)
        if side is not None and (side == "home") == wants_home:
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                price = None
            break
    if price is None:
        print(
            f"[execute_portfolio] POLYMARKET_SIDE_UNRESOLVED slug={slug}"
            f" side={getattr(request, 'side', None)}",
            flush=True,
        )
        return None

    fetched_at = (payload or {}).get("fetched_at")
    planned = getattr(request, "requested_price", None)
    if planned is not None:
        drift = round(price - float(planned), 4)
        if drift > max_slippage_dollars():
            raise _SlippageExceeded(
                f"polymarket_slippage: slug={slug} planned={planned} price={price}"
                f" drift={drift:+.4f} max={max_slippage_dollars()} fetched_at={fetched_at}"
            )
    print(
        f"[execute_portfolio] POLYMARKET_ARTIFACT_PRICE slug={slug} price={price}"
        f" planned={planned} fetched_at={fetched_at}",
        flush=True,
    )

    return (slug, price, row.get("orderPriceMinTickSize"), row.get("minimumTradeQty"))


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
