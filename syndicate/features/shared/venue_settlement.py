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
sim carries a BOUNDED weight (`_SCORE_SIM_WEIGHT` 0.125, capped at 1.5 EV
points as of 2026-08-2x; it was 0.0 when this was written), and the settled
sample is still zero everywhere.**
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
get the outcome and a P&L DERIVED from each order's own fill, counted as
`pnl_derived` -- nothing is apportioned, because a binary contract bought at $p
settles at $1 and that arithmetic is exact per order. Holding BOTH sides refuses
outright -- the outcome is genuinely ambiguous per order then, and a guess would
be a coin flip recorded as a fact.

**"ONE ORDER IN OUR BOOK" IS NOT "ONE FILL AT THE VENUE", and the difference cost
real money.** `attributable` counts OUR ledger rows for the market; a Polymarket
`realized` delta covers the venue's whole position there, including fills we
never recorded separately. Measured 2026-08-31: a $3.20 fill was graded LOST at
-$12.9188 and reported -159.38% ROI on a binary contract. So the venue's number
is preferred but BOUNDED by what the fill it lands on can physically produce
(`_pnl_exceeds_own_fill`); past that bound the per-order arithmetic wins and the
row is counted as `pnl_exceeded_own_fill`.

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
# Unjoinable rows, split by WHEN they settled
# ---------------------------------------------------------------------------

# The moment Render was suspended (every service's `updatedAt`). The local fleet
# started on a fresh Redis with NONE of Render's live orders (measured
# 2026-10-02: 22 ledger rows, all paper), so every venue settlement row is
# `unjoinable` -- and the bare count cannot say whether those are history
# Render already graded or outcomes that landed after Render stopped and that
# nothing has recorded. This split is that answer, read by the worker that
# holds the credentials. Override with `SYNDICATE_SETTLEMENT_SPLIT_AT`.
UNJOINABLE_SPLIT_DEFAULT = "2026-09-30T06:37:00Z"


def _parse_venue_time(value: Any):
    """A venue timestamp -> aware UTC datetime, or None. Polymarket sends
    nanosecond fractions, which `fromisoformat` refuses; they are trimmed to
    microseconds."""
    import re
    from datetime import datetime, timezone

    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_settled_time(venue: str, row: Mapping[str, Any]):
    return _parse_venue_time(row.get("settled_time") if venue == "kalshi" else row.get("updateTime"))


def split_unjoinable(rows_by_venue: Mapping[str, list], split_at: str | None = None) -> dict[str, Any]:
    """Unjoinable settlement rows counted BEFORE / AFTER `split_at`.

    The after-rows are also GRADED here (pure; nothing is written), because
    "how many" without "won or lost, for how much" cannot size the gap.
    `before + after + undated == len(rows)` always; `undated` is never folded
    into either side.
    """
    import os

    raw = split_at or os.environ.get("SYNDICATE_SETTLEMENT_SPLIT_AT") or UNJOINABLE_SPLIT_DEFAULT
    cutoff = _parse_venue_time(raw)
    out: dict[str, Any] = {
        "at": raw,
        "before": 0,
        "after": 0,
        "undated": 0,
        "after_by_venue": {},
        "after_outcomes": {},
        "after_refused": 0,
        "after_pnl_dollars": 0.0,
        "newest": None,
    }
    newest = None
    for venue, rows in rows_by_venue.items():
        grade = grade_kalshi_settlement if venue == "kalshi" else grade_polymarket_resolution
        for row in rows or []:
            when = _row_settled_time(venue, row)
            if when is None or cutoff is None:
                out["undated"] += 1
                continue
            newest = when if newest is None or when > newest else newest
            if when < cutoff:
                out["before"] += 1
                continue
            out["after"] += 1
            out["after_by_venue"][venue] = out["after_by_venue"].get(venue, 0) + 1
            verdict = grade(row)
            if not verdict.get("graded"):
                out["after_refused"] += 1
                continue
            outcome = str(verdict.get("outcome"))
            out["after_outcomes"][outcome] = out["after_outcomes"].get(outcome, 0) + 1
            out["after_pnl_dollars"] += float(verdict.get("pnl_dollars") or 0.0)
    out["after_pnl_dollars"] = round(out["after_pnl_dollars"], 2)
    out["newest"] = newest.strftime("%Y-%m-%dT%H:%M:%SZ") if newest else None
    return out


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


def _pnl_exceeds_own_fill(order: Mapping[str, Any], outcome: str, pnl: float) -> bool:
    """Is a venue-stated P&L larger than this ONE order's fill can produce?

    MEASURED IN PRODUCTION 2026-08-31, and it is the reason this exists rather
    than a hypothetical. Polymarket order `C7AZA3MBEKDD`
    (`aec-mlb-mia-wsh-2026-08-31`, 6.4 contracts filled at $0.50, so
    `fill_stake_dollars=3.20`) was graded LOST with `pnl_dollars=-12.9188`.
    A binary contract cannot lose more than it cost: the floor is -$3.20 either
    way round, and -$12.92 is 4.04x it. That single row drove
    `polymarket/game_line` to a reported **-159.38% ROI on $16.37 staked** and
    about 40% of that day's whole reported loss. An ROI past -100% on a binary
    contract is arithmetically impossible and is the symptom to watch for.

    THE CAUSE IS THE ATTRIBUTION TEST, NOT THE ARITHMETIC. `attributable` asks
    whether OUR LEDGER holds one order for the market. A PositionResolution's
    `realized` delta covers the venue's WHOLE position there -- including fills
    our ledger never recorded as separate orders. That order carries a
    `prior_attempts` entry for a replaced order the venue reported canceled, so
    "one order in our book" was true and "the whole delta belongs to this
    order" was not. The two are not the same claim and the code treated them as
    one.

    So the venue's number stays PREFERRED -- it nets fees the venue actually
    charged, which `_derived_pnl` can only guess at -- but it must first be
    POSSIBLE for the fill it is being written onto. Where it is not, the caller
    falls back to per-order arithmetic and counts it, rather than writing a
    number it can prove wrong onto a money record.

    The tolerance is relative and small: fees and the venue's own rounding move
    these by cents, never by multiples.
    """
    from syndicate.features.shared.paper_settlement import OUTCOME_LOST, OUTCOME_WON

    bound = _derived_pnl(order, outcome)
    if bound is None:
        # No fill to bound against. Nothing is claimed and nothing is refused --
        # the same choice `_derived_pnl` itself makes for a stakeless row.
        return False
    tolerance = max(0.01, abs(bound) * 0.02)
    if outcome == OUTCOME_LOST:
        # A loss deeper than stake + fees, or a "loss" that made money.
        return pnl < bound - tolerance or pnl > tolerance
    if outcome == OUTCOME_WON:
        # A win larger than the contract pays, or a "win" that lost money.
        return pnl > bound + tolerance or pnl < -tolerance
    return False


# Fields this module writes, and therefore the only fields a repair may clear.
_VENUE_GRADE_FIELDS = (
    "outcome", "pnl_dollars", "settled_by", "settled_at_venue", "graded_at", "held_side",
    "exit_applied",
)


# Tolerance on a balance comparison, in dollars. The venue reports to five
# decimals (`96.04765`) and nothing else should move between two readings, so
# this only has to absorb rounding -- not real money.
_BALANCE_EPSILON = 0.005


def _parse_stamp(value: Any) -> str:
    """Readings and orders both stamp ISO-8601 Z, so string order IS time order."""
    return str(value or "").strip()


def _balance_evidence(
    order: Mapping[str, Any],
    *,
    readings: list[Mapping[str, Any]],
    same_venue_orders: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Did the account move when this submit failed?

    ----------------------------------------------------------------------
    THE READ THIS MODULE SAID DID NOT EXIST
    ----------------------------------------------------------------------

    `probe_unknown_polymarket_positions` has said, in its own docstring, that
    "Polymarket publishes no route that can settle the question" and that "the
    only thing that settles these is the venue's own UI". That was true of the
    ORDER routes and was never true of the account: `/account/balances` was
    supplied by the user on 2026-08-26, `venue_balances` has fetched it every
    worker tick since, and it settles this question directly. A submit that
    landed reserves or spends money; a submit that never arrived does not.

    MEASURED 2026-08-29 on order `5c53789d4d21d05fc501b05d` ($1.84,
    `tsc-mls-nyr-phi-2026-08-29-3pt5`, `http_503` at 21:06:37): Polymarket
    `buyingPower` read 96.05 at 21:05:56 -- 40 seconds before the submit -- and
    again at 21:12:47, 21:18:46 and 21:25:09, then fell to 94.15 only after the
    retry filled. **Flat across the failed submit. Nothing was placed.** A human
    had already been asked to go and look at a venue screen to learn that.

    ----------------------------------------------------------------------
    WHAT THIS REFUSES TO CONCLUDE, AND WHY EACH REFUSAL IS LOAD-BEARING
    ----------------------------------------------------------------------

    `unknown` is the DEFAULT and every path that cannot do the arithmetic
    returns it. A guard that maps "I could not tell" onto its permissive branch
    turns a failed join into a relaxed rule, and the permissive branch here
    would release a retry that books a second real position.

      no_bracketing_reading  the trail does not span the submit. A history that
                             starts after the order proves nothing about it,
                             and this is the ordinary state for any order older
                             than the trail.
      unreadable             a reading exists but its status is not `ok`. "We
                             could not read the balance" and "the balance did
                             not move" are opposite facts.
      confounded             ANOTHER order of ours was submitted inside the same
                             window, so the delta cannot be attributed to this
                             one. Not a failure -- the honest answer, and the
                             common one on a busy slate.
      not_placed             flat across the submit, within a rounding epsilon.
      placed                 the account fell by at least this order's stake.
      inconclusive           it moved, but not by an amount this order explains.

    STILL WRITES NOTHING. This is evidence handed to a human and to the banner,
    not a grade -- same contract as the rest of the probe.
    """
    verdict = {"verdict": "unknown", "reason": None}
    submitted = _parse_stamp(order.get("submitted_at"))
    if not submitted:
        verdict["reason"] = "no_submitted_at"
        return verdict

    # The last reading strictly BEFORE the submit, and the first strictly after
    # the submit resolved. `venue_resolved_at` is when the failure came back;
    # anything the venue did with the order had happened by then.
    resolved = _parse_stamp(order.get("venue_resolved_at")) or submitted
    venue = str(order.get("venue") or "").strip().lower()

    before = None
    after = None
    for row in readings:
        at = _parse_stamp(row.get("recorded_at"))
        if not at:
            continue
        if at < submitted:
            before = row
        elif at > resolved and after is None:
            after = row
    if before is None or after is None:
        verdict["reason"] = "no_bracketing_reading"
        return verdict

    def _reading(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
        value = row.get(venue)
        return value if isinstance(value, Mapping) else None

    first, last = _reading(before), _reading(after)
    if first is None or last is None or first.get("status") != "ok" or last.get("status") != "ok":
        verdict["reason"] = "unreadable"
        return verdict

    try:
        opening = float(first.get("dollars"))
        closing = float(last.get("dollars"))
    except (TypeError, ValueError):
        verdict["reason"] = "unreadable"
        return verdict

    window = (_parse_stamp(before.get("recorded_at")), _parse_stamp(after.get("recorded_at")))
    # ANY OTHER ORDER IN THE WINDOW POISONS THE ARITHMETIC. By key, so this
    # order never counts against itself.
    others = [
        o
        for o in same_venue_orders
        if str(o.get("idempotency_key") or "") != str(order.get("idempotency_key") or "")
        and window[0] < _parse_stamp(o.get("submitted_at")) < window[1]
    ]
    verdict.update(
        {
            "window": list(window),
            "opening_dollars": round(opening, 5),
            "closing_dollars": round(closing, 5),
            "delta_dollars": round(opening - closing, 5),
            "confounding_orders": len(others),
        }
    )
    if others:
        verdict["verdict"] = "unknown"
        verdict["reason"] = "confounded"
        return verdict

    delta = opening - closing
    stake = _num(order.get("requested_stake_dollars"))
    if abs(delta) <= _BALANCE_EPSILON:
        verdict["verdict"] = "not_placed"
        verdict["reason"] = "balance_unchanged_across_submit"
    elif stake is not None and delta >= stake - _BALANCE_EPSILON:
        verdict["verdict"] = "placed"
        verdict["reason"] = "balance_fell_by_at_least_the_stake"
    else:
        verdict["reason"] = "moved_but_not_by_this_order"
    return verdict


def balance_evidence_for_unknown_submits(orders: Any) -> dict[str, dict[str, Any]]:
    """`{idempotency_key: balance_evidence}` for every unknown submit in `orders`.

    THE PAGE'S DOOR TO THE SAME ARITHMETIC THE PROBE USES, and it exists so
    there is exactly ONE implementation. `_live_portfolio_payload` needs this
    per row; reimplementing the comparison there would let the banner and the
    worker's `UNKNOWN_ORDER_PROBE` disagree about the same order, which is the
    failure `_resolve_live_slate` already names in its own docstring -- "an API
    that silently disagrees with the page it backs is a trap this repo has paid
    for more than once".

    SAFE ON THE WEB SERVICE, and that is a deliberate property rather than a
    happy accident:

      * NO VENUE CALL. It reads `venue_balances`' stamped trail and the ledger
        rows the caller already holds, then does arithmetic. Web has no
        credentials and must not get them (`venue_balances` says why at
        length), and a second independent live caller of a venue is a
        documented incident class here (`#139`/`#144`/`#148`).
      * NO HEAVY COMPUTE. Two list walks over a bounded trail (128 readings).

    Keyed by `idempotency_key` because that is this ledger's identity for an
    order (`_order_identity`), and because the caller re-filters rows for
    display -- a key survives that, a list position does not.

    An order with no key is skipped rather than given a synthetic one: it could
    not be joined back to a row anyway, and inventing an identity to make a
    dict shape work is how two different orders end up sharing evidence.
    """
    from syndicate.features.shared.venue_balances import read_balance_history

    rows = [o for o in (orders or []) if isinstance(o, Mapping)]
    live = [o for o in rows if str(o.get("mode") or "") == "live"]
    readings = read_balance_history()
    out: dict[str, dict[str, Any]] = {}
    for order in rows:
        key = str(order.get("idempotency_key") or "").strip()
        if not key:
            continue
        venue = str(order.get("venue") or "").strip().lower()
        # SAME-VENUE ONLY. A Kalshi order inside the window cannot explain a
        # move in the Polymarket balance, and counting it would report
        # `confounded` on an order this evidence could actually settle.
        same_venue = [o for o in live if str(o.get("venue") or "").strip().lower() == venue]
        out[key] = _balance_evidence(order, readings=readings, same_venue_orders=same_venue)
    return out


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

    TWO ANGLES EXIST, and the second one is stronger.

    THE ACCOUNT `[added 2026-08-29]`. A submit that landed reserves or spends
    money; one that never arrived does not. `/account/balances` is fetched every
    worker tick and `venue_balances.append_balance_history` now keeps a bounded
    trail of the readings, so the balance either side of a failed submit can be
    compared directly -- see `_balance_evidence`. This is what actually settled
    `5c53789d4d21d05fc501b05d`, and the paragraph above used to say flatly that
    nothing could. **It was true of the ORDER routes and was never true of the
    account, and stating it without that qualifier sent a human to look at a
    venue screen for a question five numbers already answered.**

    THE MARKET: the resolution feed is keyed by `marketSlug`, not by order id.
    If that market resolved AND we hold no other order on it, the resolution row
    is evidence a position of ours was there.

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

    # THE BALANCE TRAIL, read once for the whole pass. Absent (or too short)
    # simply yields `no_bracketing_reading` per order -- see `_balance_evidence`.
    from syndicate.features.shared.venue_balances import read_balance_history

    readings = read_balance_history()
    polymarket_orders = [
        o for o in (orders or [])
        if isinstance(o, Mapping)
        and str(o.get("mode") or "") == "live"
        and str(o.get("venue") or "").strip().lower() == "polymarket"
    ]

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
                # DID THE ACCOUNT MOVE? The read this module used to say did
                # not exist. Defaults to `unknown` on every path that cannot
                # do the arithmetic.
                "balance_evidence": _balance_evidence(
                    order, readings=readings, same_venue_orders=polymarket_orders
                ),
            }
        )

    evidenced = [f for f in findings if f["resolution_rows"] and f["sole_claim"]]
    # COUNTED SEPARATELY FROM `evidenced`, which means "the market resolved and
    # nothing else of ours could claim it" -- circumstantial, and about a
    # market. This is about the ACCOUNT, and it is the stronger signal of the
    # two. Merging them into one number would hide which kind of evidence a
    # given finding actually rests on.
    settled = [
        f for f in findings
        if (f.get("balance_evidence") or {}).get("verdict") in ("placed", "not_placed")
    ]
    return {
        "status": "ok",
        "unknown": len(findings),
        "evidenced": len(evidenced),
        "balance_settled": len(settled),
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


def repair_impossible_venue_pnl(*, dry_run: bool = False) -> dict[str, Any]:
    """Correct an already-graded P&L that the order's own fill cannot produce.

    THE GUARD ALONE CANNOT MEET ITS OWN GATE. `_pnl_exceeds_own_fill` stops the
    next bad write, but grading is idempotent -- a row carrying an `outcome` is
    skipped forever -- so the row measured on 2026-08-31 (a $3.20 fill graded
    LOST at -$12.9188, driving `polymarket/game_line` to -159.38% ROI) would sit
    on the money record unchanged. Something has to reach back for it.

    THIS CORRECTS, IT DOES NOT UN-GRADE, and the distinction is the whole design.
    `repair_multi_side_grades` clears the outcome because the OUTCOME was the
    thing that could not be true. Here the outcome is fine: the venue said LOST
    and it is the venue's own word, which is exactly the estimator-free fact this
    module exists to capture. Only the MAGNITUDE is impossible. Un-grading would
    discard a correct venue outcome and drop the row to inference -- trading a
    wrong number for a worse source.

    NARROW BY CONSTRUCTION, because this writes to a money record:

      * only `mode=live` rows;
      * only rows THIS module graded (`settled_by == "venue"`) -- an inferred
        grade is another module's record and is never touched;
      * only rows whose stored P&L is outside what their OWN fill can produce,
        by the same bound the grading path now applies;
      * only `pnl_dollars`. The outcome, `settled_by`, `held_side` and the
        venue timestamps are left exactly as the venue stated them.

    SELF-LIMITING. A corrected row sits inside the bound, so the next tick finds
    nothing to correct. That is what makes it safe to run every tick rather than
    as a one-off migration -- and a one-off is what left the previous two repair
    paths needing to exist at all.
    """
    from syndicate.features.shared.execution_ledger import LIVE, _load, _persist

    counters: dict[str, Any] = {"corrected": 0, "keys": []}
    try:
        state = _load()
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}", **counters}

    changed = False
    for order in (state.get("orders") or []):
        if str(order.get("mode") or "") != LIVE:
            continue
        if str(order.get("settled_by") or "") != "venue":
            continue
        outcome = str(order.get("outcome") or "")
        if not outcome:
            continue
        if order.get("exit_applied"):
            # A SOLD position's P&L is not bounded by hold-to-settle arithmetic:
            # a contract sold at a profit on a market that then resolved LOST
            # made money, and "a loss that made money" is exactly what the
            # bound flags. `exit_adjusted_pnl` wrote it from the sale itself.
            continue
        stored = _num(order.get("pnl_dollars"))
        if stored is None:
            continue
        if not _pnl_exceeds_own_fill(order, outcome, stored):
            continue
        corrected = _derived_pnl(order, outcome)
        if corrected is None:
            continue
        order["pnl_dollars"] = corrected
        counters["corrected"] += 1
        key = str(order.get("idempotency_key") or order.get("venue_ticker") or "")
        if key and key not in counters["keys"]:
            counters["keys"].append(key)
        changed = True

    if changed and not dry_run:
        _persist(state)
    return {"status": "ok", **counters}


def _order_side_key(venue: str, order: Mapping[str, Any]) -> str:
    """The side an order holds, in a vocabulary where equal means SAME BET.

    A Kalshi order's `side` is OUR label (`over`, `home`, `yes`, ...), and two
    labels can name one leg. MEASURED 2026-10-23 on
    `KXNBATOTAL-26OCT23NYKBOS-220`: a pregame `over` and a live in-game `yes`,
    both YES, read as two sides and refused `ambiguous_multi_side` forever. So
    Kalshi labels go through `_side_to_kalshi` -- the SAME mapping the order
    builder used to choose the leg we bought -- and come out `yes`/`no`.

    A label it refuses stays raw: two unmappable labels that differ still count
    as two sides, which keeps the refusal. Polymarket is untouched; its sides
    name outcomes and have no leg to collapse onto.
    """
    raw = str(order.get("side") or "").strip().lower()
    if venue != "kalshi" or not raw:
        return raw
    try:
        from syndicate.features.shared.kalshi_orders import _side_to_kalshi

        return _side_to_kalshi(raw, order.get("market"), order.get("line"))
    except Exception:
        return raw


def _kalshi_legs_consistent(outcomes_by_leg: Mapping[str, set[str]]) -> bool:
    """Can these per-leg outcomes all be true of ONE Kalshi market?

    The 08-27 invariant, stated per leg: a market resolves YES or NO, so every
    order on one leg shares an outcome, and the two legs' outcomes are
    OPPOSITE. Both legs `won` -- "both teams won" -- is the shape this refuses;
    so is anything that is not won/lost, or a leg that is not yes/no.
    """
    if not outcomes_by_leg or not set(outcomes_by_leg) <= {"yes", "no"}:
        return False
    for outcomes in outcomes_by_leg.values():
        if len(outcomes) != 1 or not outcomes <= {OUTCOME_WON, OUTCOME_LOST}:
            return False
    if len(outcomes_by_leg) == 2:
        return outcomes_by_leg["yes"] != outcomes_by_leg["no"]
    return True


def _both_legs_grades(
    row: Mapping[str, Any],
    targets: list[dict],
    key_orders: list[Mapping[str, Any]],
) -> dict[int, tuple[str, str]] | None:
    """Per-target `(leg, outcome)` for a GENUINE both-legs Kalshi holding, or None.

    MEASURED 2026-10-23: live in-game entries bought YES and NO of one ticker
    (`KXNBASPREAD-26OCT23ATLCHA-ATL9`, `KXNBATOTAL-26OCT23ATLCHA-230`), before
    the one-entry-per-game-axis fix. The settlement row carries both counts, so
    `grade_kalshi_settlement` refuses `both_sides_held` -- correctly, because
    the ROW's revenue is the pair's total and names no single order. But the
    row's `market_result` grades each LEG exactly, and each order's money comes
    from its own fill (`_derived_pnl`), so nothing has to be apportioned.

    Allowed only when it can be nothing else:
      * every one of our orders on this ticker maps to yes/no;
      * the row's yes/no counts EQUAL the contracts our filled orders hold on
        each leg (a count we did not make is not ours to explain);
      * the outcomes -- these, plus any already graded on the ticker -- pass
        `_kalshi_legs_consistent`, so two legs can never share a WON.
    """
    result = str(row.get("market_result") or "").strip().lower()
    if result not in {"yes", "no"}:
        return None
    held: dict[str, float] = {"yes": 0.0, "no": 0.0}
    outcomes_by_leg: dict[str, set[str]] = {}
    for order in key_orders:
        if str(order.get("status") or "") == "rejected":
            continue
        leg = _order_side_key("kalshi", order)
        if leg not in {"yes", "no"}:
            return None
        contracts = _num(order.get("contracts"))
        if contracts is None or contracts <= 0:
            return None
        held[leg] += contracts
        if order.get("outcome"):
            outcomes_by_leg.setdefault(leg, set()).add(str(order.get("outcome")))
    for leg in ("yes", "no"):
        count = _num(row.get(f"{leg}_count_fp"))
        if count is None or abs(count - held[leg]) > 1e-6:
            return None
    grades: dict[int, tuple[str, str]] = {}
    for order in targets:
        leg = _order_side_key("kalshi", order)
        outcome = _kalshi_outcome_from_leg(result, leg)
        if outcome is None:
            return None
        grades[id(order)] = (leg, outcome)
        outcomes_by_leg.setdefault(leg, set()).add(outcome)
    if not _kalshi_legs_consistent(outcomes_by_leg):
        return None
    return grades


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
        sides = {_order_side_key(_venue, o) for o in rows}
        if len(sides) < 2:
            continue
        venue_graded = [o for o in rows if str(o.get("settled_by") or "") == "venue"]
        if not venue_graded:
            continue
        if _venue == "kalshi":
            # A KALSHI TICKER IS ONE YES/NO MARKET, so per-leg grades that can
            # all be true together (`settle_from_venue`'s both-legs path) are
            # not the 08-27 defect. Clearing them would re-grade them next tick
            # and fight forever. Both legs WON still fails this and is cleared.
            by_leg: dict[str, set[str]] = {}
            for o in rows:
                if o.get("outcome"):
                    by_leg.setdefault(_order_side_key(_venue, o), set()).add(str(o.get("outcome")))
            if _kalshi_legs_consistent(by_leg):
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


# ---------------------------------------------------------------------------
# Exits: a position SOLD before the market settled
# ---------------------------------------------------------------------------
#
# `execution_exits` can sell a held Kalshi contract back before settlement
# (reduce_only, its own `x`+23-hex key space, its own document). Kalshi's
# settlement row then describes only what was STILL HELD when the market
# settled -- the remainder, or nothing at all -- so grading the entry from that
# row alone books hold-to-settle money for contracts we no longer owned, and a
# fully sold position may never get a row at all and wait forever.
#
# So an entry whose LIVE exit FILLED is graded from our own two fills, exactly:
#
#     pnl = sold * exit_price - exit_fee              (the sale)
#         + remainder * settle_value                  (settlement, unsold only)
#         - entry_cost - entry_fee                    (what the entry paid)
#
# The OUTCOME stays the venue's statement about the market, as for every other
# row -- it is a fact about the game, not about our money.
#
# PAPER EXITS CHANGE NOTHING. They are counterfactual; the venue still holds
# every one of those contracts. Only `mode == "live"` exit rows are read here,
# so a paper sale cannot reach a money record by construction.
#
# A LIVE EXIT WHOSE FATE IS UNKNOWN DEFERS THE GRADE. `submitted`/`failed` means
# the sale may have traded; grading then would write hold-to-settle money that a
# later reconcile proves wrong onto a record that is never regraded. The exit
# tick reconciles those every cycle, so the deferral is short.

_EXIT_NONE = "none"
_EXIT_SOLD = "sold"
_EXIT_DEFER = "defer"

_SETTLE_VALUE = {OUTCOME_WON: 1.0, OUTCOME_LOST: 0.0}


def load_live_exits() -> tuple[dict[str, dict], str | None]:
    """`exit_key -> row` for LIVE exits only. Returns `(rows, error)`.

    An UNREADABLE document is an error, never an empty one: "no sale happened"
    and "we cannot see whether a sale happened" are opposite facts, and only
    the first may grade.
    """
    try:
        from syndicate.features.shared.execution_exits import EXIT_LIVE, load_state

        state = load_state()
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    rows: dict[str, dict] = {}
    for key, row in (state.get("exits") or {}).items():
        if isinstance(row, Mapping) and str(row.get("mode") or "") == EXIT_LIVE:
            rows[str(key)] = dict(row)
    return rows, None


def exit_for_order(order: Mapping[str, Any], live_exits: Mapping[str, Mapping[str, Any]]) -> tuple[str, Mapping[str, Any] | None]:
    """`(effect, row)`: `none` grades as before, `sold` grades exit-aware,
    `defer` waits for the exit to be reconciled.

    Looked up by `exit_idempotency_key(entry_key)` -- the key the exit was sent
    under -- and the row must name this entry back. Any status not known to
    mean "nothing traded" or "traded" defers: an unknown must not default to the
    branch that writes money.
    """
    from syndicate.features.shared.execution_exits import (
        EXIT_DEAD,
        EXIT_FILLED,
        EXIT_REJECTED,
        exit_idempotency_key,
    )

    entry_key = str(order.get("idempotency_key") or "").strip()
    if not entry_key or not live_exits:
        return _EXIT_NONE, None
    row = live_exits.get(exit_idempotency_key(entry_key))
    if row is None or str(row.get("entry_key") or "") != entry_key:
        return _EXIT_NONE, None
    status = str(row.get("status") or "")
    if status in {EXIT_REJECTED, EXIT_DEAD}:
        return _EXIT_NONE, row
    if status == EXIT_FILLED:
        sold = _num(row.get("filled_contracts"))
        if sold is not None and sold <= 0:
            return _EXIT_NONE, row
        return _EXIT_SOLD, row
    return _EXIT_DEFER, row


def exit_adjusted_pnl(
    order: Mapping[str, Any], outcome: str, exit_row: Mapping[str, Any]
) -> tuple[float | None, dict[str, Any]]:
    """P&L of an entry that was partly or fully SOLD, from both fills.

    Returns `(pnl, detail)`; `pnl` is None with `detail["refused"]` naming why.
    Every input is required except the fees, and a missing EXIT fee is
    ESTIMATED at the full taker rate (`estimate_kalshi_fee`'s rule: understating
    a fee invents edge) and marked so. A push refunds the remainder at cost.
    """
    from syndicate.features.shared.execution_exits import _probability, estimate_kalshi_fee

    price = _probability(order.get("fill_price"))
    if price is None:
        price = _num(exit_row.get("entry_price"))
    cost = _num(order.get("fill_stake_dollars"))
    if price is None or not (0.0 < price < 1.0) or cost is None or cost <= 0:
        return None, {"refused": "exit_entry_unpriced"}

    contracts = _num(exit_row.get("contracts"))
    if contracts is None or contracts <= 0:
        contracts = float(round(cost / price))
    sold = _num(exit_row.get("filled_contracts"))
    exit_price = _num(exit_row.get("fill_price"))
    if sold is None or sold <= 0 or exit_price is None or not (0.0 <= exit_price <= 1.0):
        return None, {"refused": "exit_unpriced"}
    # reduce_only means the venue cannot have sold more than we held; a row
    # that says otherwise is capped and SAID, not trusted.
    oversold = sold > contracts + 1e-9
    sold = min(sold, contracts)
    remainder = max(0.0, contracts - sold)

    if outcome == OUTCOME_PUSH:
        settle_value = price
    elif outcome in _SETTLE_VALUE:
        settle_value = _SETTLE_VALUE[outcome]
    else:
        return None, {"refused": f"exit_outcome_unsupported:{outcome or 'absent'}"}

    exit_fee = _num(exit_row.get("exit_fee_dollars"))
    exit_fee_estimated = exit_fee is None
    if exit_fee is None:
        exit_fee = estimate_kalshi_fee(str(exit_row.get("ticker") or order.get("venue_ticker") or ""), sold, exit_price)
    entry_fee = _num(order.get("fees_dollars"))
    entry_fee_source = "order"
    if entry_fee is None:
        entry_fee = _num(exit_row.get("entry_fee_dollars"))
        entry_fee_source = "exit_row" if entry_fee is not None else "absent"
    entry_fee = entry_fee or 0.0

    proceeds = sold * exit_price
    settlement = remainder * settle_value
    pnl = round(proceeds - exit_fee + settlement - cost - entry_fee, 4)
    detail = {
        "exit_key": exit_row.get("exit_key"),
        "contracts": round(contracts, 4),
        "contracts_sold": round(sold, 4),
        "contracts_settled": round(remainder, 4),
        "exit_price": round(exit_price, 4),
        "proceeds_dollars": round(proceeds, 4),
        "exit_fee_dollars": round(exit_fee, 4),
        "exit_fee_estimated": exit_fee_estimated,
        "entry_cost_dollars": round(cost, 4),
        "entry_fee_dollars": round(entry_fee, 4),
        "entry_fee_source": entry_fee_source,
        "settlement_dollars": round(settlement, 4),
    }
    if oversold:
        detail["oversold_capped"] = True
    return pnl, detail


def _kalshi_outcome_from_leg(market_result: Any, leg: Any) -> str | None:
    """won/lost from the venue's result and the leg the EXIT says we held.

    For a FULLY sold position, whose settlement row holds nothing (or which has
    no row at all). Both values are venue vocabulary -- `yes`/`no` -- so this is
    the venue's arithmetic, not a read of our `side`/`line`.
    """
    result = str(market_result or "").strip().lower()
    held = str(leg or "").strip().lower()
    if result not in {"yes", "no"} or held not in {"yes", "no"}:
        return None
    return OUTCOME_WON if held == result else OUTCOME_LOST


def _both_sides_is_our_partial_close(
    row: Mapping[str, Any], effects: list[tuple[str, Mapping[str, Any] | None]]
) -> bool:
    """True when a `both_sides_held` row is OUR OWN PARTIAL SALE, not a real
    two-sided holding.

    Kalshi books a close as a BUY of the opposite leg (`exit_order_body`: a NO
    holding is sold as a YES `bid`), so the settlement row of a partly sold
    position carries BOTH counts. MEASURED 2026-10-20 on
    `KXWNBAPTS-26OCT19ATLGS-GSKTHORNTON5-10`: 5 NO bought, 1 sold ->
    `no_count_fp=5.00, yes_count_fp=1.00`, refused `both_sides_held` on every
    pass while the entry sat ungraded.

    Allowed through only when it can be nothing else: every target was SOLD by
    a filled live exit, all of them on the same leg, and the row's count on the
    OPPOSITE leg equals the contracts those exits filled. Any other shape -- no
    exit, a deferred one, a count we did not make -- is a genuine both-sides
    holding and still refuses.
    """
    if not effects or any(effect != _EXIT_SOLD or exit_row is None for effect, exit_row in effects):
        return False
    legs = {str(exit_row.get("leg") or "").strip().lower() for _effect, exit_row in effects}
    if len(legs) != 1 or not legs <= {"yes", "no"}:
        return False
    held = next(iter(legs))
    opposite = "no" if held == "yes" else "yes"
    held_count = _num(row.get(f"{held}_count_fp"))
    opposite_count = _num(row.get(f"{opposite}_count_fp"))
    sold = [_num(exit_row.get("filled_contracts")) for _effect, exit_row in effects]
    if held_count is None or opposite_count is None or any(s is None or s <= 0 for s in sold):
        return False
    total_sold = sum(sold)
    # reduce_only: the close can never exceed what we held, so a held-leg
    # count below the sale is not a shape our own exits produce.
    return abs(opposite_count - total_sold) < 1e-6 and held_count + 1e-6 >= total_sold


def fetch_kalshi_market_results(tickers: list[str]) -> tuple[dict[str, dict], str | None]:
    """`ticker -> {result, status}` for markets a fully sold position left.

    Kalshi's `/portfolio/settlements` lists what we HELD at settlement, so a
    position sold to zero may never appear there. `GET /markets?tickers=` is
    public and states the result. Only `result` in yes|no is ever used; an
    absent or empty one means "not settled yet" and the entry waits.

    MEASURED 2026-10-19T21:01Z on two markets the fleet traded live and the
    venue graded: `KXNFLREC-26SEP27LARDEN-LARDADAMS17-6` (ledger: held yes,
    WON) -> `result='yes'`, and `KXNFLREC-26SEP27LVNO-NOAKAMARA41-3` (held
    yes, LOST) -> `result='no'`; both `status='finalized'`, and
    `settlement_ts` equal to the ledger's `settled_at_venue` to the
    microsecond.
    """
    import urllib.parse

    try:
        from syndicate.features.shared.kalshi_client import _BASE_URLS, _MARKETS_PATH, _get
    except Exception as exc:
        return {}, f"import: {type(exc).__name__}: {exc}"

    unique = sorted({str(t).strip() for t in tickers if str(t or "").strip()})
    out: dict[str, dict] = {}
    error: str | None = None
    for start in range(0, len(unique), 50):
        chunk = unique[start : start + 50]
        query = urllib.parse.urlencode({"tickers": ",".join(chunk), "limit": len(chunk)})
        last = ""
        for base in _BASE_URLS:
            try:
                payload = _get(f"{base}{_MARKETS_PATH}?{query}")
            except Exception as exc:  # next base, then a named error
                last = f"{type(exc).__name__}: {exc}"[:200]
                continue
            for raw in payload.get("markets") or []:
                if isinstance(raw, Mapping) and raw.get("ticker") in chunk:
                    out[_join_key(raw["ticker"])] = {
                        "result": raw.get("result"),
                        "status": raw.get("status"),
                        "settled_time": raw.get("settlement_ts") or raw.get("close_time"),
                    }
            last = ""
            break
        if last:
            error = last
    return out, error


def _apply_exit_grade(
    order: dict[str, Any],
    outcome: str,
    exit_row: Mapping[str, Any],
    *,
    settled_at: Any,
    held_side: Any,
    venue_pnl: Any = None,
) -> str | None:
    """Write an exit-aware grade. Returns a refusal token, or None on success."""
    pnl, detail = exit_adjusted_pnl(order, outcome, exit_row)
    if pnl is None:
        return str(detail.get("refused") or "exit_refused")
    if venue_pnl is not None:
        # Kept for audit only: the venue's figure covers what was still HELD at
        # settlement and is not this entry's P&L once anything was sold.
        detail["venue_settlement_pnl_dollars"] = venue_pnl
    order["outcome"] = outcome
    order["pnl_dollars"] = pnl
    order["settled_by"] = "venue"
    order["settled_at_venue"] = settled_at
    order["graded_at"] = _utc_now()
    order["held_side"] = held_side
    order["exit_applied"] = detail
    return None


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
        "pnl_exceeded_own_fill": 0,
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
        rebounded = repair_impossible_venue_pnl(dry_run=dry_run)
        if rebounded.get("corrected"):
            counters["repaired_pnl"] = rebounded
            print(
                f"[venue_settlement] IMPOSSIBLE_PNL_CORRECTED n={rebounded['corrected']}"
                f" keys={rebounded.get('keys')}",
                flush=True,
            )
    except Exception as exc:
        counters["errors"]["repair_pnl"] = f"{type(exc).__name__}: {exc}"

    try:
        state = _load()
    except Exception as exc:
        counters["errors"]["ledger"] = f"{type(exc).__name__}: {exc}"
        return {"status": "error", **counters}

    orders = [o for o in (state.get("orders") or []) if str(o.get("mode") or "") == LIVE]

    # WHAT WAS SOLD BEFORE SETTLEMENT. See the "Exits" section above. Unreadable
    # defers every Kalshi grade this tick rather than grading blind.
    live_exits, exits_error = load_live_exits()
    if exits_error:
        counters["errors"]["exits"] = exits_error
        print(f"[venue_settlement] EXITS_UNREADABLE kalshi grading deferred: {exits_error}", flush=True)
    counters["exit_adjusted"] = 0
    counters["exit_deferred"] = 0

    def _exit_effect(venue_name: str, order: Mapping[str, Any]) -> tuple[str, Mapping[str, Any] | None]:
        if venue_name != "kalshi":
            return _EXIT_NONE, None  # exits are Kalshi-only
        if exits_error:
            return _EXIT_DEFER, None
        return exit_for_order(order, live_exits)

    left_open = 0

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
    #
    # Kalshi sides are compared as LEGS (`_order_side_key`): `over` and `yes`
    # on one totals ticker are the same bet, and counting them as two refused
    # `KXNBATOTAL-26OCT23NYKBOS-220` for days.
    sides_by_key: dict[tuple[str, str], set[str]] = {}
    orders_by_key: dict[tuple[str, str], list[dict]] = {}
    for order in orders:
        venue_all = str(order.get("venue") or "").strip().lower()
        key_all = _join_key(order.get("venue_ticker"))
        side_all = _order_side_key(venue_all, order)
        if venue_all and key_all:
            orders_by_key.setdefault((venue_all, key_all), []).append(order)
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
                f" balance_settled={probe.get('balance_settled')}"
                f" findings={probe['findings']}",
                flush=True,
            )
    except Exception as exc:
        counters["errors"]["unknown_probe"] = f"{type(exc).__name__}: {exc}"

    matched_keys: set[tuple[str, str]] = set()
    graded_any = False
    unjoinable_rows: dict[str, list] = {}

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
                unjoinable_rows.setdefault(venue, []).append(row)
                continue

            verdict = grade(row)
            effects = [_exit_effect(venue, order) for order in targets]
            # A position SOLD TO ZERO settles holding nothing, so the grader
            # refuses it `no_position_held` -- correctly, about the row. The
            # market still resolved, and every target's exit says which leg we
            # held, so those entries grade from the sale (below).
            sold_out = (
                venue == "kalshi"
                and verdict.get("reason") == "no_position_held"
                and all(effect == _EXIT_SOLD for effect, _row in effects)
            )
            # A position PARTLY sold settles holding both legs, because the
            # venue booked our close as a buy of the other one. Same rescue,
            # under the stricter count check in `_both_sides_is_our_partial_close`.
            partly_sold = (
                venue == "kalshi"
                and verdict.get("reason") == "both_sides_held"
                and _both_sides_is_our_partial_close(row, effects)
            )
            if partly_sold:
                counters["exit_partial_both_sides"] = counters.get("exit_partial_both_sides", 0) + 1
            # WE GENUINELY HELD BOTH LEGS, with no sale involved: each order
            # grades on its own leg from the row's result, at its own fill.
            # See `_both_legs_grades` for the shape checks and the 08-27 guard.
            both_legs = (
                None
                if partly_sold or venue != "kalshi" or verdict.get("reason") != "both_sides_held"
                or any(effect != _EXIT_NONE for effect, _r in effects)
                else _both_legs_grades(row, targets, orders_by_key.get(key) or [])
            )
            if both_legs is not None:
                matched_keys.add(key)
                for order in targets:
                    leg, outcome = both_legs[id(order)]
                    order["outcome"] = outcome
                    order["settled_by"] = "venue"
                    order["settled_at_venue"] = row.get("settled_time")
                    order["graded_at"] = _utc_now()
                    order["held_side"] = leg
                    derived = _derived_pnl(order, outcome)
                    if derived is not None:
                        order["pnl_dollars"] = derived
                    counters["pnl_derived"] += 1
                    counters["both_legs_graded"] = counters.get("both_legs_graded", 0) + 1
                    counters["settled"] += 1
                    per_venue["settled"] += 1
                    graded_any = True
                continue
            if not verdict.get("graded") and not (sold_out or partly_sold):
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
            sides = sides_by_key.get(key) or {_order_side_key(venue, o) for o in targets}
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
            for order, (effect, exit_row) in zip(targets, effects):
                if effect == _EXIT_DEFER:
                    # The sale may have traded and we do not know yet. Grading
                    # now would write hold-to-settle money onto a record that
                    # is never regraded.
                    counters["exit_deferred"] += 1
                    left_open += 1
                    continue
                if effect == _EXIT_SOLD and exit_row is not None:
                    outcome = (
                        verdict["outcome"]
                        if verdict.get("graded")
                        else _kalshi_outcome_from_leg(row.get("market_result"), exit_row.get("leg"))
                    )
                    refusal = (
                        "exit_outcome_unreadable"
                        if outcome is None
                        else _apply_exit_grade(
                            order,
                            outcome,
                            exit_row,
                            settled_at=verdict.get("settled_at_venue") or row.get("settled_time"),
                            held_side=verdict.get("held_side") or exit_row.get("leg"),
                            venue_pnl=verdict.get("pnl_dollars") if attributable else None,
                        )
                    )
                    if refusal:
                        counters["refused"][refusal] = counters["refused"].get(refusal, 0) + 1
                        left_open += 1
                        continue
                    counters["exit_adjusted"] += 1
                    counters["settled"] += 1
                    per_venue["settled"] += 1
                    graded_any = True
                    continue
                if not verdict.get("graded"):
                    continue  # unreachable: `sold_out`/`partly_sold` require every target sold
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
                # ONE ORDER IN OUR BOOK IS NOT THE SAME CLAIM AS ONE FILL AT THE
                # VENUE. See `_pnl_exceeds_own_fill` -- a position built by
                # fills we never recorded separately makes `attributable` true
                # while the delta still belongs to more than this row.
                impossible = (
                    attributable
                    and verdict.get("pnl_dollars") is not None
                    and _pnl_exceeds_own_fill(
                        order, verdict["outcome"], float(verdict["pnl_dollars"])
                    )
                )
                if impossible:
                    counters["pnl_exceeded_own_fill"] += 1
                if attributable and verdict.get("pnl_dollars") is not None and not impossible:
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

    # SOLD TO ZERO, AND NO SETTLEMENT ROW. `/portfolio/settlements` lists what
    # we HELD at settlement, so a position fully sold may never appear there.
    # Its money was fixed when the sale filled; only the market's result is
    # missing, and the public market read states it. Asked ONLY for such
    # entries -- with no live exit filled, this costs no venue call at all.
    sold_to_zero: list[tuple[tuple[str, str], dict, Mapping[str, Any]]] = []
    for key, waiting in open_by_key.items():
        if key in matched_keys or key[0] != "kalshi":
            continue
        for order in waiting:
            effect, exit_row = _exit_effect("kalshi", order)
            if effect != _EXIT_SOLD or exit_row is None:
                continue
            # The outcome does not change the quantities; LOST is only a probe.
            _pnl, detail = exit_adjusted_pnl(order, OUTCOME_LOST, exit_row)
            if detail.get("contracts_settled") == 0:
                sold_to_zero.append((key, order, exit_row))
    if sold_to_zero:
        results, error = fetch_kalshi_market_results(
            [str(order.get("venue_ticker") or "") for _k, order, _r in sold_to_zero]
        )
        if error:
            counters["errors"]["kalshi_market_results"] = error
        per_venue = counters["by_venue"].setdefault("kalshi", {"rows": 0, "settled": 0})
        for key, order, exit_row in sold_to_zero:
            market = results.get(key[1]) or {}
            outcome = _kalshi_outcome_from_leg(market.get("result"), exit_row.get("leg"))
            if outcome is None:
                continue  # not settled yet -- stays awaiting
            refusal = _apply_exit_grade(
                order,
                outcome,
                exit_row,
                settled_at=market.get("settled_time"),
                held_side=exit_row.get("leg"),
            )
            if refusal:
                counters["refused"][refusal] = counters["refused"].get(refusal, 0) + 1
                continue
            counters["exit_adjusted"] += 1
            counters["settled"] += 1
            per_venue["settled"] += 1
            graded_any = True

    counters["awaiting"] = left_open + sum(
        1
        for k, v in open_by_key.items()
        if k not in matched_keys
        for order in v
        if not order.get("outcome")
    )
    try:
        counters["unjoinable_split"] = split_unjoinable(unjoinable_rows)
    except Exception as exc:  # a diagnostic must never cost a settlement
        counters["errors"]["unjoinable_split"] = f"{type(exc).__name__}: {exc}"

    if graded_any and not dry_run:
        try:
            _persist(state)
        except Exception as exc:
            counters["errors"]["persist"] = f"{type(exc).__name__}: {exc}"
            return {"status": "error", **counters}

    return {"status": "ok", **counters}
