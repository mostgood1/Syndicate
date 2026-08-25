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

# LIVE defaults, deliberately small. These are the numbers a first funded week
# should survive being wrong about, not the numbers a confident system would
# choose.
_DEFAULT_MAX_ORDER_DOLLARS = 25.0
_DEFAULT_MAX_DAY_DOLLARS = 100.0
_DEFAULT_MAX_DAY_ORDERS = 10

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
_SPENT_STATUSES = {"submitted", "filled", "failed"}


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


def limits(mode: str | None = None) -> dict[str, Any]:
    """The caps in force, as data, so a log line can state them.

    The same env vars govern both modes -- one place to configure -- but the
    DEFAULTS differ, because "untested" and "unlimited" are not the same worry.
    """
    from syndicate.features.shared.execution_ledger import LIVE, execution_mode

    resolved = mode or execution_mode()
    paper = resolved != LIVE
    return {
        "mode": resolved,
        "max_order_dollars": _float_env(
            "SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS",
            _DEFAULT_PAPER_MAX_ORDER_DOLLARS if paper else _DEFAULT_MAX_ORDER_DOLLARS,
        ),
        "max_day_dollars": _float_env(
            "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS",
            _DEFAULT_PAPER_MAX_DAY_DOLLARS if paper else _DEFAULT_MAX_DAY_DOLLARS,
        ),
        "max_day_orders": _int_env(
            "SYNDICATE_EXECUTION_MAX_DAY_ORDERS",
            _DEFAULT_PAPER_MAX_DAY_ORDERS if paper else _DEFAULT_MAX_DAY_ORDERS,
        ),
        # THE ACCOUNT-WIDE CEILING, ACROSS EVERY VENUE AT ONCE.
        #
        # `max_day_dollars` is enforced PER VENUE -- `spent_today` filters on
        # `order.venue`, deliberately, so one venue's budget is not consumed by
        # another's. That is right for comparing books and WRONG as a statement
        # about the account: with a $40 day cap, one live venue risks $40 and
        # two risk $80, and the number nobody edited is the one that moved.
        #
        # Adding a venue must not raise total exposure by default. So this
        # DEFAULTS TO `max_day_dollars` -- the same figure, now meaning what a
        # reader already assumed it meant -- and only an explicit
        # SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES raises it. Turning on a
        # second venue then splits one budget instead of duplicating it, which
        # is a decision someone can make on purpose rather than one that
        # happens to them.
        "max_day_dollars_all_venues": _float_env(
            "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES",
            _float_env(
                "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS",
                _DEFAULT_PAPER_MAX_DAY_DOLLARS if paper else _DEFAULT_MAX_DAY_DOLLARS,
            ),
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
    caps = limits(resolved_mode)
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
        else spent_today(
            selected_date,
            venue=str(getattr(request, "venue", "") or "") or None,
            mode=resolved_mode,
        )
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

    if resolved_mode == LIVE:
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
