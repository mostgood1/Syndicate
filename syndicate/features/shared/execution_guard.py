"""Caps and a kill switch: the layer that stands between a plan and real money.

`execution_ledger.place_order` already gets the ORDER of operations right --
record, submit, complete -- so a restart mid-submit is survivable. What it has
no opinion about is SIZE. It will place whatever it is handed, as many times as
it is handed something, and every stake in the system today is decided by a
Kelly fraction computed from a model that has settled **zero** bets (`#502`).

That is fine on paper and unacceptable with a funded account, so the limits live
here, outside the thing that does the placing.

--------------------------------------------------------------------------
EVERY DEFAULT IS THE RESTRICTIVE ONE, AND ABSENCE NEVER MEANS "NO LIMIT"
--------------------------------------------------------------------------

`#284`'s lesson, applied to money: **absent is not off.** A cap read from an
unset variable defaults to a small number, not to infinity, so a config that
never arrived produces a tiny account rather than an unbounded one. A cap whose
value does not parse falls back to the same default rather than to zero-or-
infinity -- both of those turn a typo into a policy.

--------------------------------------------------------------------------
THE KILL SWITCH FAILS CLOSED, AND IT IS NOT THE ARM SWITCH
--------------------------------------------------------------------------

`SYNDICATE_EXECUTION_LIVE_ARMED` is an ARM: something a human sets once to say
this system may trade. A kill switch is the opposite thing -- it must stop a
slate that is already running, from a person who is not mid-deploy, in seconds.
An env var cannot do that on Render without a restart, so this also reads a
flag from the shared state store, which the ops surface can write.

**If that read fails, the switch is treated as ENGAGED.** That is the expensive
direction and it is the correct one: an unreadable kill switch means we do not
know whether someone has pulled it, and "we do not know" must not place bets.
The opposite choice -- trade when the store is flaky -- is how a store hiccup
becomes a position.

--------------------------------------------------------------------------
SPENT MEANS "MAY HAVE REACHED THE VENUE", NOT "CONFIRMED FILLED"
--------------------------------------------------------------------------

The daily total counts `submitted` (the write-ahead state) and `failed`
alongside `filled`, because an order that raised on submit may still have been
accepted. Counting only confirmed fills would let a series of ambiguous submits
spend the budget twice. `rejected` is excluded, and only that -- it is the one
status the ledger sets without ever calling the venue.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import os
from collections.abc import Mapping
from typing import Any

__all__ = [
    "kill_switch_engaged",
    "limits",
    "spent_today",
    "check_order",
    "guarded_submit",
    "KILL_SWITCH_PATH_NAME",
]

KILL_SWITCH_PATH_NAME = "execution_kill_switch.json"

# LIVE defaults. `#544`-adjacent, user decision 2026-08-25: the real funded
# accounts are $50 (Kalshi) / $100 (Polymarket), max order size is $10, and the
# day-count budget is 10 per exchange or 15 across both. These are no longer
# "small numbers a first funded week should survive being wrong about" --
# they are the stated real policy, so they are the code default rather than an
# env override layered on top of a different one (one source of truth; see
# `#284`'s lesson about a render.yaml env block drifting from what the code
# actually assumes).
_DEFAULT_MAX_ORDER_DOLLARS = 10.0
_DEFAULT_MAX_DAY_DOLLARS = 100.0
# 15 PER BOOK [USER DECISION 2026-08-25], raised from 10.
_DEFAULT_MAX_DAY_ORDERS = 15
# THE ACCOUNT-WIDE ORDER-COUNT CEILING, the count equivalent of
# `max_day_dollars_all_venues` below -- 25 across both venues [USER DECISION
# 2026-08-25], deliberately LESS than 15+15=30, so simply enabling a second
# venue cannot silently double the account's daily order budget the way it
# could not for dollars either.
_DEFAULT_MAX_DAY_ORDERS_ALL_VENUES = 25

# PER-VENUE DOLLAR CAPS. `max_day_dollars` above is the FALLBACK for a venue
# with no entry here (a future venue, or a test that does not pass one) --
# Kalshi and Polymarket get their own numbers because that is what is actually
# funded on each account. THIS IS A DAY-SPEND CAP, THE SAME MECHANISM AS EVERY
# OTHER NUMBER IN THIS FILE -- it is not a running "capital currently
# available" ledger (nothing here subtracts an open, unsettled position's
# stake from tomorrow's budget), so it is a conservative proxy for "how much is
# funded", not an exact one. Keyed lowercase to match `OrderRequest.venue` as
# already normalised by every caller in this file.
_DEFAULT_MAX_DAY_DOLLARS_BY_VENUE: dict[str, float] = {
    "kalshi": 50.0,
    "polymarket": 100.0,
}

# PER-VENUE ORDER-COUNT CAPS, the count twin of the dollar map above.
#
# WHY THIS DID NOT EXIST AND WHY IT HAD TO. `max_day_orders` was FLAT -- one
# number for whichever venue was asking -- while `max_day_dollars` had been
# per-venue since 2026-08-25. So `spent_today` filtered orders per venue and
# then compared that count against an account-shaped number. Both venues
# happening to default to 15 hid it. The moment a user sets "Kalshi 5 orders a
# day" the two readings diverge, and the flat field would have accepted the
# edit and enforced nothing -- a field that displays a policy it does not
# apply. Both entries are the previous flat default, so nothing already
# configured changes meaning.
_DEFAULT_MAX_DAY_ORDERS_BY_VENUE: dict[str, int] = {
    "kalshi": _DEFAULT_MAX_DAY_ORDERS,
    "polymarket": _DEFAULT_MAX_DAY_ORDERS,
}

# THE NAME OF THE ENV VAR BEHIND EACH USER-EDITABLE CAP.
#
# Exported because `execution_limits_settings.resolve_view` needs to tell "you
# set this" from "an operator set the env var" from "nobody set anything", and
# a second hand-written copy of these names in that file is a mapping that
# drifts. One table, two readers.
LIVE_LIMIT_FIELDS: dict[str, str] = {
    "max_order_dollars": "SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS",
    "max_day_dollars_kalshi": "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI",
    "max_day_dollars_polymarket": "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_POLYMARKET",
    "max_day_orders_kalshi": "SYNDICATE_EXECUTION_MAX_DAY_ORDERS_KALSHI",
    "max_day_orders_polymarket": "SYNDICATE_EXECUTION_MAX_DAY_ORDERS_POLYMARKET",
    "max_day_dollars_all_venues": "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES",
    "max_day_orders_all_venues": "SYNDICATE_EXECUTION_MAX_DAY_ORDERS_ALL_VENUES",
}


def _stored_live_limit(name: str, paper: bool) -> float | None:
    """A cap the USER saved on `/portfolio`, or None.

    THIS IS THE HOP THAT MAKES THE FORM REAL. Everything else in this file
    reads `os.environ`, and this module runs on **live-odds-worker** -- the web
    service that renders the form has none of those variables. Without this
    read the settings page would accept a number, show it back, and place
    orders against the old one.

    Read FRESH on every call rather than cached. A cached cap is a cap that
    does not respond to the edit that lowered it, and this is a ≤25-orders-a-day
    path where `spent_today` already reads the same store per check.

    PAPER IS EXEMPT BY DESIGN -- see the module docstring on why the paper
    numbers stay inert. A user's live cap must not quietly truncate the tail of
    every paper slate and turn that ledger into evidence about the cap.

    Never raises. A store that cannot answer sends the caller to its env-then-
    default chain, which is safe here only because `kill_switch_engaged()`
    fails CLOSED on the same store and `check_order` consults it before any
    live order is placed.
    """
    if paper:
        return None
    try:
        from syndicate.features.shared.execution_limits_settings import stored_limit

        return stored_limit(name)
    except Exception:
        return None

# PAPER defaults, deliberately INERT. The mechanism must run on paper -- a cap
# whose first exercise is with money on it has not been tested -- but the
# NUMBERS must not, because the paper books exist to record what the strategy
# would have done. Capping them at the live limits would silently truncate the
# tail of every slate and make the ledger evidence about the cap instead of
# about the strategy. Set the env vars to bind them.
_DEFAULT_PAPER_MAX_ORDER_DOLLARS = 10_000.0
_DEFAULT_PAPER_MAX_DAY_DOLLARS = 1_000_000.0
_DEFAULT_PAPER_MAX_DAY_ORDERS = 10_000

# Statuses that mean the venue may have seen this order. See the module note.
#
# `rejected` is absent because those never reached the venue at all
# (`OrderBuildError.venue_contacted = False`). `failed` IS here because the
# general case is genuinely unknown -- a submit that timed out may have landed,
# and the write-ahead record exists precisely for that gap.
_SPENT_STATUSES = {"submitted", "filled", "failed"}

# ...but a 4xx IS AN ANSWER. The venue replied and refused; no contract exists,
# no money moved, and nothing is pending reconciliation.
#
# Measured 2026-08-25: three Kalshi orders failed `http_404 market_not_found`
# and charged $5.01 and three orders against a $50 / 15-order budget for
# positions that were never opened. A cap that counts refusals is a cap that
# shrinks every time the venue says no.
#
# 5xx and timeouts deliberately still count: "the venue broke" and "the venue
# refused" are opposite facts about whether a position might exist, and only
# one of them is safe to treat as free.
_VENUE_REFUSED_ERROR = re.compile(r"http_4\d\d", re.IGNORECASE)


def _is_venue_refusal(order: Mapping[str, Any]) -> bool:
    """A `failed` order the venue ANSWERED and refused -- so not spend."""
    if str(order.get("status") or "") != "failed":
        return False
    return bool(_VENUE_REFUSED_ERROR.search(str(order.get("error") or "")))


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        parsed = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    # A non-positive cap is a typo, not an instruction to trade nothing forever
    # -- and not an instruction to trade without limit either.
    return parsed if parsed > 0 else default


def _int_env(name: str, default: int) -> int:
    value = _float_env(name, float(default))
    return int(value)


_UNSET = object()


def _float_env_or_none(name: str) -> float | None:
    """Like `_float_env`, but tells "nobody set this" apart from any default."""
    value = _float_env(name, _UNSET)  # type: ignore[arg-type]
    return None if value is _UNSET else value


def limits(mode: str | None = None, venue: str | None = None) -> dict[str, Any]:
    """The caps in force, as data, so a log line can state them.

    The same env vars govern both modes -- one place to configure -- but the
    DEFAULTS differ, because "untested" and "unlimited" are not the same worry.

    `venue` resolves the PER-VENUE `max_day_dollars` (Kalshi and Polymarket are
    funded at different amounts) -- omitted entirely, it falls back to the
    flat `max_day_dollars` default rather than guessing at a venue.
    """
    from syndicate.features.shared.execution_ledger import LIVE, execution_mode

    resolved = mode or execution_mode()
    paper = resolved != LIVE
    normalized_venue = str(venue or "").strip().lower() or None

    # ------------------------------------------------------------------
    # PER-VENUE DOLLARS: stored (the user's edit) > per-venue env > flat env >
    # default. The store layer is new; the rest is the existing chain, kept in
    # the same order, because the more specific knob has always won here.
    # ------------------------------------------------------------------
    def _venue_day_dollars(name: str | None) -> float:
        default = _DEFAULT_PAPER_MAX_DAY_DOLLARS if paper else _DEFAULT_MAX_DAY_DOLLARS
        if not paper and name in _DEFAULT_MAX_DAY_DOLLARS_BY_VENUE:
            default = _DEFAULT_MAX_DAY_DOLLARS_BY_VENUE[name]
        if name:
            saved = _stored_live_limit(f"max_day_dollars_{name}", paper)
            if saved is not None:
                return float(saved)
        env_name = (
            f"SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_{name.upper()}"
            if name
            else "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS"
        )
        return _float_env(env_name, _float_env("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", default))

    def _venue_day_orders(name: str | None) -> int:
        default = _DEFAULT_PAPER_MAX_DAY_ORDERS if paper else _DEFAULT_MAX_DAY_ORDERS
        if not paper and name in _DEFAULT_MAX_DAY_ORDERS_BY_VENUE:
            default = _DEFAULT_MAX_DAY_ORDERS_BY_VENUE[name]
        if name:
            saved = _stored_live_limit(f"max_day_orders_{name}", paper)
            if saved is not None:
                return int(saved)
        env_name = (
            f"SYNDICATE_EXECUTION_MAX_DAY_ORDERS_{name.upper()}"
            if name
            else "SYNDICATE_EXECUTION_MAX_DAY_ORDERS"
        )
        return _int_env(env_name, _int_env("SYNDICATE_EXECUTION_MAX_DAY_ORDERS", default))

    def _stored_or_env_float(field: str, env_name: str, default: float) -> float:
        saved = _stored_live_limit(field, paper)
        return float(saved) if saved is not None else _float_env(env_name, default)

    max_day_dollars = _venue_day_dollars(normalized_venue)

    return {
        "mode": resolved,
        "venue": normalized_venue,
        "max_order_dollars": _stored_or_env_float(
            "max_order_dollars",
            "SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS",
            _DEFAULT_PAPER_MAX_ORDER_DOLLARS if paper else _DEFAULT_MAX_ORDER_DOLLARS,
        ),
        "max_day_dollars": max_day_dollars,
        # THE PER-VENUE CAPS, ALWAYS BOTH, whatever venue this call asked
        # about. `max_day_dollars` above is whichever ONE venue was resolved,
        # and a page rendering that single figure as "the" daily cap reads as
        # an account limit while the two books are funded differently -- the
        # live portfolio banner showed exactly one number for months.
        #
        # THESE ARE NOW RESOLVED, NOT THE RAW DEFAULT MAP. They used to be
        # `_DEFAULT_MAX_DAY_DOLLARS_BY_VENUE[...]` read straight out -- so a
        # `SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI` twenty-five lines above
        # moved ENFORCEMENT while the banner kept printing $50. The page and
        # the guard disagreeing about a money cap is the exact failure this
        # file's comments keep repairing elsewhere; it was true here too.
        "max_day_dollars_by_venue": {
            name: _venue_day_dollars(name) for name in _DEFAULT_MAX_DAY_DOLLARS_BY_VENUE
        },
        "max_day_dollars_kalshi": _venue_day_dollars("kalshi"),
        "max_day_dollars_polymarket": _venue_day_dollars("polymarket"),
        "max_day_orders": _venue_day_orders(normalized_venue),
        "max_day_orders_by_venue": {
            name: _venue_day_orders(name) for name in _DEFAULT_MAX_DAY_ORDERS_BY_VENUE
        },
        "max_day_orders_kalshi": _venue_day_orders("kalshi"),
        "max_day_orders_polymarket": _venue_day_orders("polymarket"),
        # THE ACCOUNT-WIDE CEILINGS, ACROSS EVERY VENUE AT ONCE.
        #
        # `max_day_dollars` is enforced PER VENUE -- `spent_today` filters on
        # `order.venue`, deliberately, so one venue's budget is not consumed by
        # another's. That is right for comparing books and WRONG as a statement
        # about the account: two funded venues must not silently add up to more
        # risk than either alone, just because nobody set a combined number.
        #
        # DOLLARS default to the SUM of the known per-venue defaults ($50 + $100
        # = $150) rather than to the flat `max_day_dollars` -- now that venues
        # carry DIFFERENT numbers, "default to max_day_dollars" would silently
        # mean "default to whichever venue happens to be asking", which is not
        # a combined cap at all. An explicit
        # `SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES` still overrides it.
        #
        # EXCEPT: if someone set the flat `SYNDICATE_EXECUTION_MAX_DAY_DOLLARS`
        # env var directly (the pre-per-venue-cap way of configuring one shared
        # number), that edit must still move the combined ceiling -- "nobody
        # edits a cap and total exposure doubles" applies to the flat knob too,
        # and it is the more specific signal than the two venues' code defaults.
        #
        # EDITABLE TOO, and that is not scope creep -- it is what stops the two
        # per-venue fields above from being an inert form. This ceiling is
        # checked BEFORE them and defaults to $150, so raising Kalshi to $200
        # on the settings page changes nothing at all while it stands. The page
        # says so out loud when the two venue budgets sum above it.
        "max_day_dollars_all_venues": _stored_or_env_float(
            "max_day_dollars_all_venues",
            "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES",
            (
                _DEFAULT_PAPER_MAX_DAY_DOLLARS
                if paper
                else (
                    _float_env_or_none("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS")
                    or sum(_DEFAULT_MAX_DAY_DOLLARS_BY_VENUE.values())
                )
            ),
        ),
        "max_day_orders_all_venues": int(
            _stored_or_env_float(
                "max_day_orders_all_venues",
                "SYNDICATE_EXECUTION_MAX_DAY_ORDERS_ALL_VENUES",
                float(_DEFAULT_PAPER_MAX_DAY_ORDERS if paper else _DEFAULT_MAX_DAY_ORDERS_ALL_VENUES),
            )
        ),
    }


def kill_switch_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    # No date token: a kill switch that expires is not a kill switch.
    return reports_root() / "intelligence" / KILL_SWITCH_PATH_NAME


def kill_switch_engaged() -> dict[str, Any]:
    """Is trading stopped? Returns the ANSWER AND ITS SOURCE.

    Two sources, either of which stops trading, and a read failure stops it too.
    The source is returned because "stopped by a human" and "stopped because we
    could not tell" need different responses from whoever reads the log.
    """
    raw = str(os.environ.get("SYNDICATE_EXECUTION_KILL_SWITCH") or "").strip().lower()
    if raw in {"1", "true", "yes", "on", "engaged"}:
        return {"engaged": True, "source": "env"}

    from syndicate.features.shared.refresh_state_store import read_json_file_result

    try:
        payload, read_ok = read_json_file_result(kill_switch_path())
    except Exception as exc:
        return {"engaged": True, "source": "read_failed", "detail": type(exc).__name__}
    if not read_ok:
        # FAIL CLOSED. `read_json_file` alone collapses "no flag was ever
        # written" into the same None as "the store did not answer", and those
        # must not both mean "go ahead" -- that is how a store hiccup becomes a
        # position.
        return {"engaged": True, "source": "read_failed"}
    if payload and bool(payload.get("engaged")):
        return {
            "engaged": True,
            "source": "flag",
            "detail": payload.get("reason"),
            "set_at": payload.get("set_at"),
        }
    return {"engaged": False, "source": "clear"}


def spent_today(
    selected_date: str, *, venue: str | None = None, mode: str | None = None
) -> dict[str, Any]:
    """Dollars and order count already committed for `selected_date`.

    Read from the LEDGER rather than from the plan. A worker restart mid-slate
    would otherwise start the day's budget over, which is the one way a per-day
    cap can be enforced everywhere and still not hold.

    Scoped by MODE and optionally by VENUE, because the books are separate
    ledgers sharing one file: paper's spend must not consume live's budget, and
    `paper` must not consume `paper:kalshi`'s -- the two paper books exist to be
    compared, and a shared budget would make each one's size depend on the
    other's. Defaults to LIVE, so a caller that forgets to say gets the
    strictest reading rather than a pooled one.
    """
    from syndicate.features.shared.execution_ledger import LIVE, _load

    resolved_mode = mode or LIVE
    dollars = 0.0
    count = 0
    for order in (_load().get("orders") or []):
        if str(order.get("mode")) != resolved_mode:
            continue
        if str(order.get("selected_date") or "") != str(selected_date):
            continue
        if venue is not None and str(order.get("venue") or "") != venue:
            continue
        if str(order.get("status") or "") not in _SPENT_STATUSES:
            continue
        if _is_venue_refusal(order):
            # The venue answered and refused. No contract, no money, nothing
            # to reconcile -- see `_VENUE_REFUSED_ERROR`.
            continue
        try:
            dollars += float(
                order.get("fill_stake_dollars")
                if order.get("fill_stake_dollars") is not None
                else order.get("requested_stake_dollars") or 0.0
            )
            # FEES COME OUT OF THE SAME BALANCE. A daily cap that counts only
            # stake is a cap the account can exceed -- ~1.9% on the first real
            # Kalshi fill, which compounds across a slate. Absent means the
            # venue reported none, which is true of every venue but Kalshi and
            # of any Kalshi order not yet reconciled.
            dollars += float(order.get("fees_dollars") or 0.0)
        except (TypeError, ValueError):
            # An unparseable stake is counted as an ORDER but not as dollars,
            # and that asymmetry is stated rather than silent: dropping it from
            # both would make the day's spend read lower than it is.
            pass
        count += 1
    return {"dollars": round(dollars, 2), "orders": count}


# How much this venue can actually fund right now, or "we do not know".
#
# UNKNOWN ALLOWS, WHICH INVERTS THE HOUSE RULE -- stated here rather than left
# to look like an oversight. The rule is that a guard must not map "unknown"
# onto its permissive branch, because a failed lookup then reads as permission.
# It does not hold here, for a specific reason: a SECOND AND AUTHORITATIVE
# check sits downstream. The venue itself refuses an unfunded order with a 4xx
# -- no contract is created, no money moves, and `_is_venue_refusal` already
# exempts it from the day budget. The cost of wrongly allowing is one wasted
# request.
#
# The cost of wrongly REFUSING is not symmetric. A stale artifact or a broken
# credential would stop every live order, silently, and a system placing
# nothing looks exactly like a quiet day. Failing closed would trade a free,
# self-correcting error for an expensive, invisible one.
#
# STALENESS IS A REAL BOUND, not a formality: the stamp is written once per
# execution tick, so it is minutes old by construction and cannot see orders
# placed since. Those are subtracted rather than ignored.
_BALANCE_MAX_AGE_SECONDS = 3600.0


def _venue_available_dollars(venue: str | None) -> dict[str, Any]:
    """`{"known": bool, "available": float, ...}` for one venue.

    `known` is False for every absence -- no stamp, no such venue, a non-`ok`
    status, an unusable number, or a reading too old to trust -- and each one
    carries a DISTINCT `reason`, because "the worker never reported" and "the
    credentials are wrong" are different problems that would otherwise share a
    silent branch.
    """
    if not venue:
        return {"known": False, "reason": "no_venue_on_request"}
    try:
        from syndicate.features.shared.venue_balances import read_venue_balances

        stamp = read_venue_balances()
    except Exception as exc:
        return {"known": False, "reason": f"read_error:{type(exc).__name__}"}
    if not stamp:
        return {"known": False, "reason": "never_recorded"}

    row = ((stamp.get("venues") or {}).get(str(venue).strip().lower())) or {}
    if not row:
        return {"known": False, "reason": "venue_absent_from_stamp"}
    if str(row.get("status") or "") != "ok":
        return {"known": False, "reason": f"balance_{row.get('status') or 'unknown'}"}

    raw = row.get("dollars")
    try:
        dollars = float(raw)
    except (TypeError, ValueError):
        return {"known": False, "reason": "unusable_balance_value"}

    age = _age_seconds(stamp.get("recorded_at"))
    if age is None:
        return {"known": False, "reason": "unstamped_reading"}
    if age > _BALANCE_MAX_AGE_SECONDS:
        return {"known": False, "reason": "stale_reading", "age_seconds": round(age, 1)}

    # ORDERS PLACED SINCE THE STAMP ARE NOT IN IT. Without this, several orders
    # inside one tick each measure themselves against the same pre-tick cash
    # and the gate passes all of them -- the exact overspend it exists to stop.
    committed = _live_stake_since(stamp.get("recorded_at"), venue=venue)
    available = dollars - committed
    return {
        "known": True,
        "available": round(available if available > 0 else 0.0, 4),
        "balance_dollars": round(dollars, 4),
        "committed_since_reading": round(committed, 4),
        "age_seconds": round(age, 1),
        "venue": str(venue).strip().lower(),
    }


def _age_seconds(stamp: Any) -> float | None:
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _live_stake_since(stamp: Any, *, venue: str) -> float:
    """Live dollars committed at `venue` since `stamp`. Never raises.

    A balance gate that threw would stop the tick that places orders, which is
    a far worse failure than the one it is preventing.
    """
    if not stamp:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    try:
        from syndicate.features.shared.execution_ledger import LIVE as _LIVE
        from syndicate.features.shared.execution_ledger import _load
    except Exception:
        return 0.0
    try:
        orders = (_load() or {}).get("orders") or []
    except Exception:
        return 0.0

    total = 0.0
    want = str(venue).strip().lower()
    for order in orders:
        if str(order.get("mode") or "") != _LIVE:
            continue
        if str(order.get("venue") or "").strip().lower() != want:
            continue
        # Only statuses where money may actually be committed. A `rejected`
        # order never reached the venue and a 4xx `failed` was refused -- the
        # same distinction `_SPENT_STATUSES` and `_is_venue_refusal` draw.
        status = str(order.get("status") or "")
        if status not in _SPENT_STATUSES or _is_venue_refusal(order):
            continue
        try:
            at = datetime.fromisoformat(str(order.get("submitted_at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at <= parsed:
            continue
        amount = order.get("fill_stake_dollars")
        if amount is None:
            amount = order.get("requested_stake_dollars")
        try:
            total += float(amount or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def check_order(
    request: Any, *, mode: str | None = None, already: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """May this order be placed? A NAMED refusal, never a bare False.

    Paper orders are checked too. A cap that only applies in live mode is a cap
    whose first real exercise is with money on it -- the paper run exists to be
    evidence about the live one, and that includes the limits.
    """
    from syndicate.features.shared.execution_ledger import LIVE, execution_mode

    resolved_mode = mode or execution_mode()
    request_venue = str(getattr(request, "venue", "") or "") or None
    caps = limits(resolved_mode, venue=request_venue)
    stake = float(getattr(request, "requested_stake_dollars", 0.0) or 0.0)

    if stake <= 0:
        return {"allowed": False, "reason": "non_positive_stake", "limits": caps}

    if stake > caps["max_order_dollars"]:
        return {
            "allowed": False,
            "reason": "over_max_order_dollars",
            "stake": stake,
            "limits": caps,
        }

    selected_date = str(getattr(request, "selected_date", "") or "")
    used = (
        dict(already)
        if already is not None
        else spent_today(selected_date, venue=request_venue, mode=resolved_mode)
    )
    if float(used.get("dollars") or 0.0) + stake > caps["max_day_dollars"]:
        return {
            "allowed": False,
            "reason": "over_max_day_dollars",
            "stake": stake,
            "already": used,
            "limits": caps,
        }
    if int(used.get("orders") or 0) + 1 > caps["max_day_orders"]:
        return {
            "allowed": False,
            "reason": "over_max_day_orders",
            "already": used,
            "limits": caps,
        }

    # ACROSS EVERY VENUE. Read separately and NEVER from `already`, which the
    # caller computes per venue -- passing it here would make the account-wide
    # cap read one venue's spend and agree with itself.
    #
    # A distinct reason string, because "this venue is done for the day" and
    # "the account is done for the day" call for different responses and a
    # shared name would hide which one stopped the slate.
    all_venues = spent_today(selected_date, venue=None, mode=resolved_mode)
    if float(all_venues.get("dollars") or 0.0) + stake > caps["max_day_dollars_all_venues"]:
        return {
            "allowed": False,
            "reason": "over_max_day_dollars_all_venues",
            "stake": stake,
            "already": used,
            "already_all_venues": all_venues,
            "limits": caps,
        }
    if int(all_venues.get("orders") or 0) + 1 > caps["max_day_orders_all_venues"]:
        return {
            "allowed": False,
            "reason": "over_max_day_orders_all_venues",
            "already": used,
            "already_all_venues": all_venues,
            "limits": caps,
        }

    if resolved_mode == LIVE:
        # DO WE ACTUALLY HAVE THE MONEY AT THIS VENUE?
        #
        # MEASURED 2026-08-27: 7 live Kalshi orders died `http_400
        # insufficient_balance`, all of them SMALL -- $1.09 to $3.39, 3 to 7
        # contracts at implied prices of 0.28-0.49. Not a sizing bug and not an
        # empty account: $32.46 was tied up in open positions against $53.89
        # free, so venue cash runs to the floor and refills only as markets
        # settle. The day caps ($50/$40) are larger than the cash behind them,
        # so no cap could express this and the venue was the only thing that
        # noticed.
        #
        # A NAMED REFUSAL RATHER THAN A DOOMED REQUEST. Being capital-bound is
        # a fact about the strategy and belongs on the board beside the caps,
        # not rediscovered one 400 at a time.
        balance = _venue_available_dollars(request_venue)
        if balance.get("known") and stake > float(balance["available"]):
            return {
                "allowed": False,
                "reason": "insufficient_venue_balance",
                "stake": stake,
                "balance": balance,
                "limits": caps,
            }

        # Checked LAST among the live-only gates but before anything is placed,
        # and checked again immediately before submit by `guarded_submit`.
        switch = kill_switch_engaged()
        if switch.get("engaged"):
            return {"allowed": False, "reason": "kill_switch", "switch": switch, "limits": caps}

    return {
        "allowed": True,
        "reason": None,
        "limits": caps,
        "already": used,
        "already_all_venues": all_venues,
    }


class KillSwitchEngaged(RuntimeError):
    """Raised from inside a submit so the ledger records the order as failed.

    Deliberately raised rather than returned: `place_order` marks a submit that
    raised as `failed` and KEEPS the record, which is the correct state for an
    order we stopped at the last instant -- reconciliation should still look for
    it, because "we did not send it" is a belief and not a fact until the venue
    agrees.
    """


def guarded_submit(submit):
    """Wrap a venue adapter so the kill switch is checked IMMEDIATELY before it.

    The check in `check_order` happens before the ledger write; this one happens
    after it, with nothing in between but the call itself. That gap is what
    "stops an in-flight slate" actually means -- a switch pulled during a
    twelve-order loop must stop order four, not order one.
    """

    def _submit(request):
        switch = kill_switch_engaged()
        if switch.get("engaged"):
            raise KillSwitchEngaged(f"kill_switch:{switch.get('source')}")
        return submit(request)

    return _submit
