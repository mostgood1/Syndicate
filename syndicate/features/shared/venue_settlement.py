"""Settle live orders from the venue's own settlement record.

--------------------------------------------------------------------------
THIS IS NOT A BETTER ESTIMATOR. IT REMOVES THE ESTIMATOR
--------------------------------------------------------------------------

`paper_settlement.settle_orders` grades an order against a status WE resolve:
our boxscore feed, our team aliases, our line handling, our over/under
vocabulary. Every one of those is a place to be wrong, and its own record says
so -- 80 of 171 orders on 2026-08-23 refused with `unmapped_market`, and always
would have, because a spread arrives as `side="Texas Rangers", line=-1.5` and
that is not expressible in the grader's vocabulary.

Both venues will simply tell us how a market we hold resolved. There is no
join to get wrong, no alias to miss, and no feed to be late. That matters far
beyond tidiness: **every stake on this board is sized at 1/16th Kelly and the
sim carries zero weight, both because settled sample is zero everywhere.**
`settled > 0` is the gate the whole feedback loop is stuck behind, and this is
the shortest path through it.

--------------------------------------------------------------------------
THE VENUE'S ARITHMETIC, NOT OURS
--------------------------------------------------------------------------

Kalshi (`GET /portfolio/settlements`, docs read 2026-08-26):

    ticker, market_result (yes|no|scalar), settled_time
    yes_count_fp / no_count_fp        contracts WE HELD at settlement
    yes_total_cost_dollars / no_...   our cost basis, fixed-point strings
    revenue                           payout in CENTS (winners pay 100c each)
    fee_cost                          fixed-point dollars

    P&L = revenue/100 - (yes_cost + no_cost) - fee_cost

Polymarket (`GET /v1/portfolio/activities?types=ACTIVITY_TYPE_POSITION_RESOLUTION`):

    positionResolution.marketSlug, side (LONG|SHORT|NEUTRAL), updateTime
    beforePosition / afterPosition    UserPosition, whose `realized` is an
                                      Amount {value: decimal string, currency}

    P&L = afterPosition.realized - beforePosition.realized

**WON/LOST IS DERIVED FROM WHICH SIDE WE HELD, NEVER FROM OUR OWN `side` AND
`line` FIELDS.** Those are the fields the alias joins get wrong; using them here
would reintroduce the exact estimator this module exists to delete. Kalshi
states our holdings in the settlement row itself, and Polymarket's realized
delta carries its own sign.

--------------------------------------------------------------------------
ONE MARKET CAN CARRY SEVERAL OF OUR ORDERS, AND P&L DOES NOT DIVIDE
--------------------------------------------------------------------------

A venue settles a MARKET. We may hold two orders on one ticker. The OUTCOME is
shared and safe to apply to both -- the market resolved one way for everyone.
The P&L is not: the row states the market total, and splitting it across orders
would be an invented number wearing an exact one's clothes.

So: one ungraded order on a market gets the outcome AND the venue's P&L; several
get the outcome and no P&L, counted as `pnl_unattributed`. Holding BOTH sides
refuses outright -- the outcome is genuinely ambiguous per order then, and a
guess would be a coin flip recorded as a fact.

--------------------------------------------------------------------------
IDEMPOTENT, AND IT WRITES INTO A MONEY RECORD SOMEBODY ELSE ALSO WRITES
--------------------------------------------------------------------------

An order already carrying an `outcome` is skipped before anything else happens
-- the same contract `settle_orders` keeps, and for the same reason: re-running
must not be able to change a settled bet. Rows this module grades are stamped
`settled_by: "venue"`, so an AUTHORITATIVE outcome stays distinguishable from an
INFERRED one. A later evaluation pass that cannot tell those apart is one that
will eventually average them.

**Two absences, counted separately and never collapsed:** settlement rows that
match no order of ours (`unjoinable`), and open orders with no settlement row
yet (`awaiting`). "Nothing has settled" and "we cannot see what settled" are
opposite facts.
"""

from __future__ import annotations

from typing import Any, Mapping

VENUES: tuple[str, ...] = ("kalshi", "polymarket")

KALSHI_SETTLEMENTS_PATH = "/portfolio/settlements"
POLYMARKET_ACTIVITIES_PATH = "/portfolio/activities"
POLYMARKET_RESOLUTION_TYPE = "ACTIVITY_TYPE_POSITION_RESOLUTION"

OUTCOME_WON = "won"
OUTCOME_LOST = "lost"
OUTCOME_PUSH = "push"


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _num(value: Any) -> float | None:
    """A number, including a fixed-point string. `True` is not a number.

    Both venues send money as decimal STRINGS in places -- Kalshi's
    `yes_total_cost_dollars`, Polymarket's `Amount.value` -- so a float-only
    parse would silently drop the cost basis and report the gross payout as
    profit.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _amount(value: Any) -> float | None:
    """Polymarket's `Amount` -> a float. `{value: "40.5", currency: "USD"}`."""
    if isinstance(value, Mapping):
        return _num(value.get("value"))
    return _num(value)


def _join_key(value: Any) -> str:
    """Tickers and slugs, normalised for comparison only.

    Case-folded because a ticker we stored and a ticker the venue echoes back
    have differed by case before (`fetch_market` accepted a body carrying ANY
    ticker, which is how an alias slipped through). Folding is not permissive
    -- it matches more, never grades more loosely.
    """
    return str(value or "").strip().casefold()


# ---------------------------------------------------------------------------
# Kalshi
# ---------------------------------------------------------------------------


def fetch_kalshi_settlements(*, limit: int = 200, max_pages: int = 10) -> tuple[list[dict], str | None]:
    """Our settled markets, newest first. Returns `(rows, error)`.

    Paged by the documented `cursor`. Never raises: settlement is a read, and a
    read that throws inside the execution tick would stop orders being placed.
    """
    try:
        from syndicate.features.shared.kalshi_auth import (
            KalshiAuthError,
            _base_url,
            load_credentials,
            signed_request,
        )
    except Exception as exc:
        return [], f"import: {type(exc).__name__}: {exc}"

    creds = load_credentials()
    if creds.get("status") != "ok":
        return [], "credentials_absent"

    rows: list[dict] = []
    cursor = ""
    for _ in range(max(1, int(max_pages))):
        url = f"{_base_url()}{KALSHI_SETTLEMENTS_PATH}?limit={int(limit)}"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            payload = signed_request("GET", url, credentials=creds)
        except KalshiAuthError as exc:
            return rows, str(exc)[:300]
        except Exception as exc:
            return rows, f"{type(exc).__name__}: {exc}"
        page = payload.get("settlements")
        if not isinstance(page, list):
            return rows, "shape_unrecognised"
        rows.extend(row for row in page if isinstance(row, dict))
        cursor = str(payload.get("cursor") or "")
        # An empty cursor OR a short page means the end. Both, because a venue
        # that keeps echoing a cursor forever would page until max_pages.
        if not cursor or len(page) < int(limit):
            break
    return rows, None


def grade_kalshi_settlement(row: Mapping[str, Any]) -> dict[str, Any]:
    """One settlement row -> outcome and P&L, or a NAMED refusal.

    Never returns a bare failure: a refusal says which of the several genuinely
    different reasons applied, because `scalar_market` and `both_sides_held`
    call for completely different follow-ups.
    """
    result = str(row.get("market_result") or "").strip().lower()
    yes_ct = _num(row.get("yes_count_fp")) or 0.0
    no_ct = _num(row.get("no_count_fp")) or 0.0

    if result not in {"yes", "no"}:
        # `scalar` settles at a VALUE, not a side. Nothing this system trades is
        # scalar, and inventing a side for one would be a guess recorded as a fact.
        return {"graded": False, "reason": f"unsupported_market_result:{result or 'absent'}"}
    if yes_ct <= 0 and no_ct <= 0:
        return {"graded": False, "reason": "no_position_held"}
    if yes_ct > 0 and no_ct > 0:
        return {"graded": False, "reason": "both_sides_held"}

    held = "yes" if yes_ct > 0 else "no"
    outcome = OUTCOME_WON if held == result else OUTCOME_LOST

    revenue_cents = _num(row.get("revenue"))
    cost = (_num(row.get("yes_total_cost_dollars")) or 0.0) + (
        _num(row.get("no_total_cost_dollars")) or 0.0
    )
    fees = _num(row.get("fee_cost")) or 0.0
    pnl = None
    if revenue_cents is not None:
        pnl = round(revenue_cents / 100.0 - cost - fees, 4)

    return {
        "graded": True,
        "outcome": outcome,
        "pnl_dollars": pnl,
        "held_side": held,
        "market_result": result,
        "settled_at_venue": row.get("settled_time"),
        "fees_dollars": round(fees, 4) if fees else None,
    }


# ---------------------------------------------------------------------------
# Polymarket US
# ---------------------------------------------------------------------------


def fetch_polymarket_resolutions(*, limit: int = 200, max_pages: int = 10) -> tuple[list[dict], str | None]:
    """Our position resolutions, newest first. Returns `(rows, error)`.

    Asks the venue to filter by type rather than pulling every trade and
    discarding most of it -- `types` is a documented query parameter, and a
    client-side filter would page through fills to find settlements.
    """
    try:
        from syndicate.features.shared.polymarket_us_auth import (
            BASE_URL,
            PolymarketUSAuthError,
            _API_PREFIX,
            credentials_present,
            signed_request,
        )
    except Exception as exc:
        return [], f"import: {type(exc).__name__}: {exc}"

    if not credentials_present():
        return [], "credentials_absent"

    rows: list[dict] = []
    cursor = ""
    for _ in range(max(1, int(max_pages))):
        url = (
            f"{BASE_URL}{_API_PREFIX}{POLYMARKET_ACTIVITIES_PATH}"
            f"?limit={int(limit)}&types={POLYMARKET_RESOLUTION_TYPE}"
        )
        if cursor:
            url += f"&cursor={cursor}"
        try:
            payload = signed_request("GET", url)
        except PolymarketUSAuthError as exc:
            return rows, str(exc)[:300]
        except Exception as exc:
            return rows, f"{type(exc).__name__}: {exc}"
        page = payload.get("activities")
        if not isinstance(page, list):
            return rows, "shape_unrecognised"
        for item in page:
            if not isinstance(item, dict):
                continue
            resolution = item.get("positionResolution")
            if isinstance(resolution, dict) and resolution.get("marketSlug"):
                rows.append(resolution)
        cursor = str(payload.get("nextCursor") or "")
        if payload.get("eof") or not cursor:
            break

    # THE SHAPE, ONCE PER READ, BECAUSE THIS MODULE HAD NO LOGGING AT ALL.
    #
    # Every other venue reader here reports the payload it got on its first
    # live run, and each time that has corrected field names nobody could have
    # guessed -- ten on `kalshi_client`, `state` vs `status` on
    # `polymarket_us_orders`. This module skipped it, which is exactly why the
    # push defect above had to be diagnosed backwards from ledger rows instead
    # of read off a log line.
    #
    # KEYS AND THE REALIZED PAIR ONLY. The delta is the whole grading input, so
    # a zero one has to be visible as a zero rather than inferred from a
    # `push` appearing downstream. These are our own settled positions, not
    # credentials.
    if rows:
        sample = rows[0]
        before = sample.get("beforePosition") if isinstance(sample.get("beforePosition"), Mapping) else {}
        after = sample.get("afterPosition") if isinstance(sample.get("afterPosition"), Mapping) else {}
        zero = sum(
            1
            for r in rows
            if _amount((r.get("afterPosition") or {}).get("realized")) is not None
            and (
                (_amount((r.get("afterPosition") or {}).get("realized")) or 0.0)
                - (_amount((r.get("beforePosition") or {}).get("realized")) or 0.0)
            )
            == 0.0
        )
        print(
            f"[venue_settlement] POLYMARKET_RESOLUTIONS n={len(rows)}"
            f" zero_delta={zero} keys={sorted(sample.keys())}"
            f" sides={sorted({str(r.get('side') or '') for r in rows})}"
            f" before_realized={before.get('realized')!r}"
            f" after_realized={after.get('realized')!r}",
            flush=True,
        )
    else:
        print("[venue_settlement] POLYMARKET_RESOLUTIONS n=0", flush=True)
    return rows, None


def grade_polymarket_resolution(row: Mapping[str, Any]) -> dict[str, Any]:
    """One resolution -> outcome and P&L, or a NAMED refusal.

    THE REALIZED DELTA IS THE SETTLEMENT. `UserPosition.realized` is cumulative,
    so the difference across the resolution is exactly what this event booked --
    and its sign is the outcome. Reading `afterPosition.realized` alone would
    report the position's whole trading history as this settlement's result.
    """
    before = row.get("beforePosition") if isinstance(row.get("beforePosition"), Mapping) else {}
    after = row.get("afterPosition") if isinstance(row.get("afterPosition"), Mapping) else {}
    before_realized = _amount(before.get("realized"))
    after_realized = _amount(after.get("realized"))

    if after_realized is None:
        return {"graded": False, "reason": "no_realized_amount"}

    delta = after_realized - (before_realized or 0.0)
    side = str(row.get("side") or "").strip().upper()

    if side.endswith("NEUTRAL"):
        # The venue's own word for a resolution that moved nothing. This is the
        # ONLY thing that may be graded a push -- the venue SAYING so.
        outcome = OUTCOME_PUSH
    elif delta > 0:
        outcome = OUTCOME_WON
    elif delta < 0:
        outcome = OUTCOME_LOST
    else:
        # ------------------------------------------------------------------
        # A ZERO DELTA IS AMBIGUOUS AND MUST NOT BE GRADED. `[user 2026-08-27]`
        # "polymarket is still calling everything from today a push."
        # ------------------------------------------------------------------
        #
        # It was. MEASURED on the live book 2026-08-28T02:3xZ: SEVEN pushes,
        # every one Polymarket, every one dated that day, every one
        # `pnl_dollars=0.0` and `settled_by='venue'` -- while the same venue's
        # rows from the day before graded won/lost with real money. One of them
        # carried `settled_at=2026-08-27T13:49:55.546Z` against a
        # `commence_time` of `23:16:00Z`: settled nine and a half hours BEFORE
        # first pitch, which no real resolution can be.
        #
        # `delta == 0` conflates two opposite facts: "this market resolved and
        # moved no money" and "nothing has been booked against this position
        # yet". Grading the second as a push writes an AUTHORITATIVE outcome
        # (`settled_by='venue'`) over a live bet -- and `settle_from_venue`
        # skips rows that already carry an outcome, so the error is PERMANENT
        # and self-concealing. It also silently inflates the push column, which
        # is the one bucket nobody audits because it looks like a non-event.
        #
        # Refusing costs nothing: the row stays open and the next tick grades
        # it once the venue has actually booked the resolution. That is the
        # same rule this file already applies everywhere else -- an absence is
        # not evidence, and a named refusal is better than a confident zero.
        return {"graded": False, "reason": "zero_realized_delta"}

    return {
        "graded": True,
        "outcome": outcome,
        "pnl_dollars": round(delta, 4),
        "held_side": side or None,
        "settled_at_venue": row.get("updateTime"),
    }


# ---------------------------------------------------------------------------
# The join, and the write
# ---------------------------------------------------------------------------


def _derived_pnl(order: Mapping[str, Any], outcome: str) -> float | None:
    """This order's P&L from ITS OWN fill, for a venue-stated outcome.

    Used when one market carries several of our orders, so the venue's
    market-total P&L cannot be handed to any single row. Nothing is
    apportioned: a binary contract bought at $p settles at $1, so the
    arithmetic is per-order and exact. `profit_per_dollar` is the same function
    the inferred path grades with, so the two sources cannot disagree about how
    a fill converts into money -- only about the OUTCOME, which is the
    distinction `settled_by` exists to preserve.

    Fees are netted where the venue reported them, and an absent fee is charged
    as zero rather than refused -- the same choice `grade_order` makes, for the
    same reason: a bet whose fee we cannot read is still a bet with a real
    result, and refusing would lose the outcome to save the rounding.
    """
    from syndicate.features.shared.paper_settlement import (
        OUTCOME_LOST,
        OUTCOME_PUSH,
        OUTCOME_WON,
        profit_per_dollar,
    )

    stake = _num(order.get("fill_stake_dollars"))
    if stake is None or stake <= 0:
        return None
    fees = _num(order.get("fees_dollars")) or 0.0

    if outcome == OUTCOME_PUSH:
        return round(-fees, 4)
    if outcome == OUTCOME_LOST:
        return round(-stake - fees, 4)
    if outcome != OUTCOME_WON:
        return None

    multiple = profit_per_dollar(order.get("fill_price"))
    if multiple is None:
        return None
    return round(stake * multiple - fees, 4)


# Fields this module writes, and therefore the only fields a repair may clear.
_VENUE_GRADE_FIELDS = (
    "outcome", "pnl_dollars", "settled_by", "settled_at_venue", "graded_at", "held_side",
)


def probe_unknown_polymarket_positions(
    orders: Any, resolution_rows: Any
) -> dict[str, Any]:
    """Did an order we LOST THE RESPONSE TO actually reach the venue?

    THE GAP THIS EXISTS FOR, and it is structural rather than a bug. A submit
    that fails with no answer -- measured 2026-08-28, two orders on
    `http_503 {"code":14}` (gRPC UNAVAILABLE) -- leaves us holding NO
    `venue_order_id`. Polymarket publishes no route that lists orders:
    `GET /v1/orders` answers `501 UNIMPLEMENTED`, `/v1/orders/open` is open-only,
    and the per-order read needs the id we never got. So the order is invisible
    to every read available to us, and $8.21 of possible exposure sits in the
    `unknown` bucket that nothing can confirm or deny.

    THE ONE ANGLE THAT EXISTS: the resolution feed is keyed by `marketSlug`,
    not by order id. If that market resolved AND we hold no other order on it,
    the resolution row is evidence a position of ours was there.

    READ-ONLY AND IT WRITES NOTHING. It cannot grade, because the evidence is
    circumstantial in both directions:

      * EVIDENCE FOUND is not proof. Nothing in the row says the position was
        ours -- only that the market resolved while we believed we might hold
        it. `sole_claim` reports whether any OTHER order of ours could account
        for it, which is what separates a real signal from a coincidence.
      * NO EVIDENCE IS NOT ABSENCE, and this is the more dangerous half. An
        order that landed and is STILL OPEN has no resolution row at all, and a
        market that has not settled yet has none either. A clean probe means
        "nothing found", never "nothing there".

    Returns a report for a human to act on. The only thing that settles these
    is the venue's own UI.
    """
    from syndicate.features.shared.execution_guard import is_non_position

    rows = list(resolution_rows or [])
    by_market: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = _join_key(row.get("marketSlug"))
        if key:
            by_market[key] = by_market.get(key, 0) + 1

    # EVERY polymarket order we hold, by market, so a resolution can be checked
    # against ALL possible claimants rather than only the unknown one.
    claims: dict[str, list[dict]] = {}
    unknown: list[dict] = []
    for order in (orders or []):
        if not isinstance(order, Mapping):
            continue
        if str(order.get("mode") or "") != "live":
            continue
        if str(order.get("venue") or "").strip().lower() != "polymarket":
            continue
        key = _join_key(order.get("venue_ticker"))
        if key:
            claims.setdefault(key, []).append(dict(order))
        # UNKNOWN: we sent it, the venue never answered, and we hold no id.
        # `is_non_position` excludes the ones the venue REFUSED outright --
        # those are certainly not positions and are not in question.
        if (
            not order.get("outcome")
            and not str(order.get("venue_order_id") or "").strip()
            and str(order.get("status") or "") == "failed"
            and not is_non_position(order)
        ):
            unknown.append(dict(order))

    findings: list[dict[str, Any]] = []
    for order in unknown:
        key = _join_key(order.get("venue_ticker"))
        # BY KEY, NOT BY IDENTITY. `claims` holds copies, so `is not` would
        # count the order against itself and never report a sole claim.
        others = [
            o
            for o in claims.get(key, [])
            if str(o.get("idempotency_key") or "") != str(order.get("idempotency_key") or "")
        ]
        findings.append(
            {
                "idempotency_key": str(order.get("idempotency_key") or ""),
                "market": key,
                "selected_date": str(order.get("selected_date") or ""),
                "stake_dollars": order.get("requested_stake_dollars"),
                "resolution_rows": by_market.get(key, 0),
                # TRUE only when no other order of ours could account for the
                # resolution. That is the difference between a signal and a
                # coincidence, and it is why this is reported rather than
                # inferred.
                "sole_claim": not others,
            }
        )

    evidenced = [f for f in findings if f["resolution_rows"] and f["sole_claim"]]
    return {
        "status": "ok",
        "unknown": len(findings),
        "evidenced": len(evidenced),
        "findings": findings,
    }


def repair_zero_delta_pushes(*, dry_run: bool = False) -> dict[str, Any]:
    """Un-grade pushes written from a ZERO realized delta. Worker only.

    `[user 2026-08-27]` "polymarket is still calling everything from today a
    push." MEASURED on the live book: seven pushes, all Polymarket, all that
    day, all `pnl_dollars=0.0` / `settled_by='venue'`, while the previous day's
    rows on the same venue graded won and lost with real money. One carried
    `settled_at=2026-08-27T13:49:55Z` against a `commence_time` of `23:16:00Z`
    -- graded settled nine and a half hours before first pitch.

    `grade_polymarket_resolution` now REFUSES a zero delta, so no new row can
    be written this way. That does nothing for the rows already carrying it:
    grading is idempotent, so a wrong outcome is permanent unless something
    deliberately removes it. Same reasoning as `repair_multi_side_grades`.

    NARROW BY CONSTRUCTION, because this writes to a money record:

      * `mode=live` only;
      * `venue=polymarket` only -- Kalshi's grader never had this defect;
      * rows THIS module graded (`settled_by == "venue"`); an inferred grade is
        another module's record and is never touched;
      * `outcome == push` with a P&L of zero -- the exact signature;
      * and NO `held_side` recorded.

    THAT LAST CLAUSE IS WHAT MAKES THIS TERMINATE, and it is worth being
    explicit about. A legitimate push -- one where the venue itself said
    NEUTRAL -- is indistinguishable from the defect in the stored data: both
    are `push / 0.00 / venue`. Clearing on the signature alone would re-open a
    CORRECT grade, the next tick would re-grade it push, and the repair would
    clear it again on every tick forever. `held_side` is now persisted at grade
    time, so a row written after this change carries it and is never touched,
    while every row written before it is cleared exactly once.

    Nothing here invents an outcome. It removes an assertion the venue never
    made, and lets a later tick grade the row once the resolution is actually
    booked. A row that really was neutral comes straight back as a push, this
    time carrying the venue's word for it.
    """
    from syndicate.features.shared.execution_ledger import LIVE, _load, _persist

    counters: dict[str, Any] = {"cleared": 0, "dates": []}
    try:
        state = _load()
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}", **counters}

    for order in (state.get("orders") or []):
        if str(order.get("mode") or "") != LIVE:
            continue
        if str(order.get("venue") or "").strip().lower() != "polymarket":
            continue
        if str(order.get("settled_by") or "") != "venue":
            continue
        if str(order.get("outcome") or "") != OUTCOME_PUSH:
            continue
        if order.get("held_side"):
            continue
        pnl = _num(order.get("pnl_dollars"))
        if pnl is None or abs(pnl) > 1e-9:
            continue
        for field in _VENUE_GRADE_FIELDS:
            order.pop(field, None)
        counters["cleared"] += 1
        date = str(order.get("selected_date") or "")
        if date and date not in counters["dates"]:
            counters["dates"].append(date)

    if counters["cleared"] and not dry_run:
        _persist(state)
    return {"status": "ok", **counters}


def repair_multi_side_grades(*, dry_run: bool = False) -> dict[str, Any]:
    """Un-grade rows this module wrongly settled by sharing one verdict across
    OPPOSITE SIDES of a market. Runs before grading, on the worker.

    WHY A REPAIR EXISTS AT ALL. Both graders are idempotent by design -- an
    order carrying an `outcome` is skipped -- which is what makes a settled bet
    quotable. The same property means a WRONG outcome is permanent unless
    something deliberately removes it. On 2026-08-27 two rows on
    `aec-mlb-cle-laa-2026-08-26` were graded WON simultaneously, one `side=home`
    and one `side=away`, and the board asserted that both teams won the same
    game.

    NARROW BY CONSTRUCTION, because this writes to a money record:

      * only `mode=live` rows;
      * only rows THIS module graded (`settled_by == "venue"`) -- an inferred
        grade is another module's record and is never touched;
      * only markets where our own ungraded-plus-graded orders genuinely hold
        MORE THAN ONE side, which is the exact condition that made the verdict
        unsafe;
      * only the fields this module writes.

    SELF-LIMITING. After a repair those rows are ungraded, and `settle_from_venue`
    now REFUSES an opposite-side market, so the next tick finds nothing to
    repair and nothing to re-grade. The rows fall to the 24h inference fallback,
    which grades each side against its own line and gets this case right.

    Nothing here invents an outcome. It removes an assertion that could not have
    been true, and lets the path that CAN resolve per side do it.
    """
    from syndicate.features.shared.execution_ledger import LIVE, _load, _persist

    counters: dict[str, Any] = {"markets": 0, "cleared": 0, "tickers": []}
    try:
        state = _load()
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}", **counters}

    groups: dict[tuple[str, str], list[dict]] = {}
    for order in (state.get("orders") or []):
        if str(order.get("mode") or "") != LIVE:
            continue
        key = (str(order.get("venue") or "").strip().lower(), _join_key(order.get("venue_ticker")))
        if not key[0] or not key[1]:
            continue
        groups.setdefault(key, []).append(order)

    changed = False
    for (_venue, ticker), rows in groups.items():
        if len(rows) < 2:
            continue
        sides = {str(o.get("side") or "").strip().lower() for o in rows}
        if len(sides) < 2:
            continue
        venue_graded = [o for o in rows if str(o.get("settled_by") or "") == "venue"]
        if not venue_graded:
            continue
        counters["markets"] += 1
        counters["tickers"].append(ticker)
        for order in venue_graded:
            for field in _VENUE_GRADE_FIELDS:
                order.pop(field, None)
            counters["cleared"] += 1
            changed = True

    # BACKFILL A MISSING P&L, WITHOUT TOUCHING ANY OUTCOME.
    #
    # Rows graded before `_derived_pnl` existed kept an outcome and no number --
    # `LOST —` on the board beside yesterday's fully-resolved lines, which is
    # the inconsistency the user actually reported. Idempotency means the
    # grading path will never revisit them, so the number has to be added here.
    #
    # This is STRICTLY ADDITIVE and cannot change a settled result: it only
    # fills `pnl_dollars` where the field is absent, only on rows this module
    # graded, and it derives the figure from the order's OWN fill -- a binary
    # contract bought at $p settles at $1. An outcome is never read as anything
    # but input.
    for order in (state.get("orders") or []):
        if str(order.get("mode") or "") != LIVE:
            continue
        if str(order.get("settled_by") or "") != "venue":
            continue
        outcome = str(order.get("outcome") or "")
        if not outcome or order.get("pnl_dollars") is not None:
            continue
        derived = _derived_pnl(order, outcome)
        if derived is None:
            counters["pnl_backfill_refused"] = counters.get("pnl_backfill_refused", 0) + 1
            continue
        order["pnl_dollars"] = derived
        counters["pnl_backfilled"] = counters.get("pnl_backfilled", 0) + 1
        changed = True

    if changed and not dry_run:
        try:
            _persist(state)
        except Exception as exc:
            return {"status": "error", "reason": f"{type(exc).__name__}: {exc}", **counters}
    return {"status": "ok", **counters}


def settle_from_venue(*, dry_run: bool = False) -> dict[str, Any]:
    """Grade every ungraded LIVE order that the venue has settled. Persists.

    WORKER ONLY -- it needs venue credentials and it writes the execution ledger.

    Returns counters rather than a bare count, because the interesting states
    here are the absences: a settlement matching no order and an order with no
    settlement are different problems and only one of them is ours.
    """
    from syndicate.features.shared.execution_ledger import LIVE, _load, _persist

    counters: dict[str, Any] = {
        "settled": 0,
        "already": 0,
        "awaiting": 0,
        "unjoinable": 0,
        "pnl_derived": 0,
        "refused": {},
        "by_venue": {},
        "errors": {},
    }

    # REPAIR BEFORE GRADING, so a row this module previously got wrong is
    # ungraded again before anything reads it as settled. Never raises -- a
    # repair that could stop the tick would be worse than the defect.
    try:
        repaired = repair_multi_side_grades(dry_run=dry_run)
        if repaired.get("cleared"):
            counters["repaired"] = repaired
    except Exception as exc:
        counters["errors"]["repair"] = f"{type(exc).__name__}: {exc}"

    try:
        unpushed = repair_zero_delta_pushes(dry_run=dry_run)
        if unpushed.get("cleared"):
            counters["repaired_pushes"] = unpushed
            print(
                f"[venue_settlement] ZERO_DELTA_PUSHES_CLEARED n={unpushed['cleared']}"
                f" dates={unpushed.get('dates')}",
                flush=True,
            )
    except Exception as exc:
        counters["errors"]["repair_pushes"] = f"{type(exc).__name__}: {exc}"

    try:
        state = _load()
    except Exception as exc:
        counters["errors"]["ledger"] = f"{type(exc).__name__}: {exc}"
        return {"status": "error", **counters}

    orders = [o for o in (state.get("orders") or []) if str(o.get("mode") or "") == LIVE]

    # UNGRADED, FILLED orders only. An order that never filled has no position
    # to settle, and one already carrying an outcome is never touched again.
    open_by_key: dict[tuple[str, str], list[dict]] = {}
    # EVERY side we hold on a market, GRADED OR NOT.
    #
    # The opposite-side guard below used to read only the UNGRADED orders, and
    # sequencing walked straight around it. MEASURED 2026-08-27 on
    # `aec-mlb-cle-laa-2026-08-26`, after the first fix had shipped:
    #
    #   1. the repair cleared both rows              -> both ungraded
    #   2. the `away` row aged past the 24h grace    -> INFERENCE graded it won
    #   3. one ungraded order now remained, so       -> venue graded `home` won
    #      `len(targets) == 1` and the guard slept
    #
    # and the board asserted both teams won again. Worse than a missed case:
    # the repair clears the venue grade and the grader immediately re-applies
    # it, so the two would have fought each other on every tick forever.
    #
    # The question the guard has to ask is "does this MARKET carry more than
    # one of our sides", which has nothing to do with which rows happen to be
    # graded right now.
    sides_by_key: dict[tuple[str, str], set[str]] = {}
    for order in orders:
        venue_all = str(order.get("venue") or "").strip().lower()
        key_all = _join_key(order.get("venue_ticker"))
        side_all = str(order.get("side") or "").strip().lower()
        if venue_all and key_all and side_all:
            sides_by_key.setdefault((venue_all, key_all), set()).add(side_all)

    for order in orders:
        if order.get("outcome"):
            counters["already"] += 1
            continue
        if str(order.get("status") or "") == "rejected":
            continue
        venue = str(order.get("venue") or "").strip().lower()
        key = _join_key(order.get("venue_ticker"))
        if not venue or not key:
            continue
        open_by_key.setdefault((venue, key), []).append(order)

    fetched: dict[str, list[dict]] = {}
    for venue, fetch in (
        ("kalshi", fetch_kalshi_settlements),
        ("polymarket", fetch_polymarket_resolutions),
    ):
        try:
            rows, error = fetch()
        except Exception as exc:  # defence in depth; each fetch already catches
            rows, error = [], f"{type(exc).__name__}: {exc}"
        fetched[venue] = rows
        if error:
            counters["errors"][venue] = error

    # THE ORPHAN ANGLE POLYMARKET OTHERWISE HAS NONE OF. Runs on rows already
    # fetched, so it costs no extra venue call, and it WRITES NOTHING -- see
    # `probe_unknown_polymarket_positions` for why the evidence cannot grade.
    try:
        probe = probe_unknown_polymarket_positions(
            [o for o in (state.get("orders") or [])], fetched.get("polymarket") or []
        )
        if probe.get("unknown"):
            counters["unknown_probe"] = probe
            print(
                f"[venue_settlement] UNKNOWN_ORDER_PROBE venue=polymarket"
                f" unknown={probe['unknown']} evidenced={probe['evidenced']}"
                f" findings={probe['findings']}",
                flush=True,
            )
    except Exception as exc:
        counters["errors"]["unknown_probe"] = f"{type(exc).__name__}: {exc}"

    matched_keys: set[tuple[str, str]] = set()
    graded_any = False

    for venue, rows in fetched.items():
        grade = grade_kalshi_settlement if venue == "kalshi" else grade_polymarket_resolution
        ticker_field = "ticker" if venue == "kalshi" else "marketSlug"
        per_venue = counters["by_venue"].setdefault(venue, {"rows": len(rows), "settled": 0})

        for row in rows:
            key = (venue, _join_key(row.get(ticker_field)))
            targets = open_by_key.get(key)
            if not targets:
                # A market the venue settled that we hold no ungraded order on.
                # Expected constantly (already-graded rows, other accounts'
                # history) -- counted, never treated as an error.
                counters["unjoinable"] += 1
                continue

            verdict = grade(row)
            if not verdict.get("graded"):
                reason = str(verdict.get("reason"))
                counters["refused"][reason] = counters["refused"].get(reason, 0) + 1
                continue

            # OPPOSITE SIDES ON ONE MARKET CANNOT SHARE AN OUTCOME.
            #
            # MEASURED IN PRODUCTION 2026-08-27, and it is the reason this
            # branch exists rather than a hypothetical: `aec-mlb-cle-laa-
            # 2026-08-26` carried one `side=home` and one `side=away` order,
            # and the earlier version applied ONE verdict to both -- so the
            # board showed **Los Angeles Angels WON and Cleveland Guardians
            # WON on the same game**. At most one of those can be true.
            #
            # Kalshi's grader already refuses this as `both_sides_held`, from
            # `yes_count_fp`/`no_count_fp`. Polymarket's cannot: a
            # PositionResolution carries ONE aggregate realized delta for the
            # position and never names the winning outcome, so opposite-side
            # orders net out into a single number that describes neither.
            #
            # Refused and COUNTED rather than guessed. An ungraded row is a
            # visible gap; a confidently wrong outcome on a money record is
            # not, and it also poisons the venue-vs-inferred comparison this
            # whole path exists to make possible.
            #
            # The real resolution is per-side and it is known, just not built:
            # the PUBLIC gateway's `GET /markets/{slug}/settlement` names the
            # winning outcome, which would let each order be graded against its
            # own side instead of against the position's net.
            # ALL our sides on this market, not just the ungraded ones -- see
            # `sides_by_key` above for the sequencing that defeated the
            # ungraded-only version.
            sides = sides_by_key.get(key) or {
                str(o.get("side") or "").strip().lower() for o in targets
            }
            if len(sides) > 1:
                counters["refused"]["ambiguous_multi_side"] = (
                    counters["refused"].get("ambiguous_multi_side", 0) + 1
                )
                continue

            matched_keys.add(key)
            # ONE MARKET, POSSIBLY SEVERAL ORDERS ON THE SAME SIDE. The outcome
            # is shared and now provably safe. The venue's P&L is the MARKET's
            # total and still does not divide -- but each order's own fill does,
            # and a binary contract's arithmetic is exact from it.
            attributable = len(targets) == 1
            for order in targets:
                order["outcome"] = verdict["outcome"]
                order["settled_by"] = "venue"
                order["settled_at_venue"] = verdict.get("settled_at_venue")
                order["graded_at"] = _utc_now()
                # THE VENUE'S OWN WORD FOR WHICH SIDE WE HELD, PERSISTED.
                #
                # Both graders have always returned it and nothing stored it,
                # which is why the zero-delta push defect could not be told
                # apart from a legitimate venue-stated NEUTRAL push after the
                # fact -- both are `outcome=push, pnl=0, settled_by=venue`.
                # Storing it makes `repair_zero_delta_pushes` able to terminate
                # instead of clearing a correct grade every tick forever.
                order["held_side"] = verdict.get("held_side")
                if attributable and verdict.get("pnl_dollars") is not None:
                    # ONE ORDER: take the venue's own arithmetic, which nets
                    # fees the venue actually charged.
                    order["pnl_dollars"] = verdict["pnl_dollars"]
                    if verdict.get("fees_dollars") is not None:
                        order["fees_dollars"] = verdict["fees_dollars"]
                else:
                    # SEVERAL ORDERS: derive each one from ITS OWN fill.
                    #
                    # This is not an apportionment and nothing is invented. A
                    # binary contract bought at $p settles at $1, so a winner
                    # returns (1-p)/p per dollar staked and a loser returns the
                    # stake -- exactly what `profit_per_dollar` computes for the
                    # inferred path. Leaving these rows with NO P&L is what put
                    # `WON —` on the board beside yesterday's fully-resolved
                    # lines, and an outcome without a number is not a settled
                    # bet a person can read.
                    derived = _derived_pnl(order, verdict["outcome"])
                    if derived is not None:
                        order["pnl_dollars"] = derived
                    counters["pnl_derived"] += 1
                counters["settled"] += 1
                per_venue["settled"] += 1
                graded_any = True

    counters["awaiting"] = sum(
        len(v) for k, v in open_by_key.items() if k not in matched_keys
    )

    if graded_any and not dry_run:
        try:
            _persist(state)
        except Exception as exc:
            counters["errors"]["persist"] = f"{type(exc).__name__}: {exc}"
            return {"status": "error", **counters}

    return {"status": "ok", **counters}
