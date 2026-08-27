"""User-editable execution caps: the per-venue day budgets, and the ceilings.

**WHY A SECOND SETTINGS FILE AND NOT `portfolio_settings.py`.** Those two sets
of numbers answer opposite questions and fail in opposite directions.
`portfolio_settings` decides how much the model will COMMIT to a plan; a lost
value there must land on a WORKING default, because a bankroll resolving to 0
sizes every bet at $0 and reads as a quiet slate. These decide how much may
reach a VENUE; the whole point of `execution_guard` is that absence is
restrictive. Sharing one store would make one file's fail-safe direction the
other's hazard.

--------------------------------------------------------------------------
THE ONLY THING THAT MATTERS HERE IS THAT THE WORKER READS IT
--------------------------------------------------------------------------

`execution_guard.limits()` read environment variables and nothing else, and it
runs on **live-odds-worker**. The web service has none of those variables --
that is the whole reason `record_execution_state` exists. So a settings form
that wrote to a store the worker never consulted would render, accept a value,
show it back, and change nothing about what gets placed. Every field here is
therefore read by `limits()` itself, on the worker, on the same call
`check_order` uses to refuse an order -- not by the page, and not by a separate
copy of the resolution logic.

`refresh_state_store` is what makes that possible: web writes and the worker
reads, through the shared keyvalue, because the three services' disks cannot be
shared. Same mechanism `portfolio_settings` and the kill switch already use.

--------------------------------------------------------------------------
LIVE ONLY. PAPER STAYS UNCAPPED
--------------------------------------------------------------------------

`execution_guard`'s own docstring is explicit that the PAPER numbers must stay
inert -- "capping them at the live limits would silently truncate the tail of
every slate and make the ledger evidence about the cap instead of about the
strategy". A stored cap is a statement about real money, so it binds live and
is ignored in paper mode. An operator who genuinely wants paper bound still has
the env vars, exactly as that docstring says.

--------------------------------------------------------------------------
FAIL-SAFE, AND IT INVERTS FOR A CAP
--------------------------------------------------------------------------

For a bankroll, "absent resolves to the default" is the safe direction. For a
spending cap it is not symmetric: if the user LOWERS Kalshi from $50 to $20 and
the store then loses the key, falling back to the default resolves UPWARD, to a
budget larger than the one they set.

That is accepted here for one specific reason, and it is not "unlikely":
`kill_switch_engaged()` fails CLOSED on this same store, and `check_order`
consults it before any live order is placed. A store that cannot answer stops
live trading outright, before a cap is ever the deciding factor. What is left
is the paper path, which caps do not bind anyway, and the display -- and
`store_error` is surfaced on the page so a read failure is never silent.

**A value that does not parse, or lands outside its bounds, is REFUSED BY NAME
and leaves the previous value standing.** Not clamped: a clamp turns a typo
into a silently different policy that still looks accepted, which is the same
call `portfolio_settings._coerce` and `learnings.md` 2026-08-08 make.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from syndicate.features.shared.refresh_state_store import (
    read_json_file,
    reports_root,
    write_json_file,
)

# The venues these caps are expressed per. Lowercase, matching
# `OrderRequest.venue` as every caller in `execution_guard` normalises it.
VENUES: tuple[str, ...] = ("kalshi", "polymarket")

# Bounds are a REFUSAL RANGE, not a suggestion. The high ends are deliberately
# far above the funded accounts and far below a fat-finger: $10,000 a day at a
# venue is not a plausible edit on a $1,000 bankroll, and 1,000 orders is not a
# plausible day. The low ends stop a "0" from reading as "unlimited" -- the
# same worry `_float_env` already has about a non-positive env var.
_BOUNDS: dict[str, tuple[float, float]] = {
    "max_order_dollars": (0.01, 1_000.0),
    "max_day_dollars_kalshi": (0.01, 10_000.0),
    "max_day_dollars_polymarket": (0.01, 10_000.0),
    "max_day_orders_kalshi": (1, 1_000),
    "max_day_orders_polymarket": (1, 1_000),
    "max_day_dollars_all_venues": (0.01, 20_000.0),
    "max_day_orders_all_venues": (1, 2_000),
}

# Whole numbers, so the form and the guard agree that 15.5 orders is not a
# thing. Dollars stay float; a $12.50 cap is meaningful.
_INTEGER_FIELDS = frozenset(
    {"max_day_orders_kalshi", "max_day_orders_polymarket", "max_day_orders_all_venues"}
)

EDITABLE_FIELDS: tuple[str, ...] = tuple(_BOUNDS.keys())


def _settings_path():
    # NO DATE TOKEN. `_default_keyvalue_ttl_seconds` hands any dated path a
    # 10-day TTL, and a spending cap that silently expires back to the default
    # is the worst possible failure of this file.
    return reports_root() / "intelligence" / "execution_limits.json"


def _coerce(name: str, value: Any) -> float | None:
    """Parse and bound one field. None means unusable -- refuse, never clamp."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).strip().replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    low, high = _BOUNDS[name]
    if parsed < low or parsed > high:
        return None
    return float(int(parsed)) if name in _INTEGER_FIELDS else parsed


def _read_stored() -> tuple[dict[str, Any], str | None]:
    try:
        payload = read_json_file(_settings_path())
    except Exception as exc:  # store down, key evicted, payload unparseable
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, Mapping):
        return {}, None
    return dict(payload), None


def stored_limits() -> dict[str, Any]:
    """The user's saved caps, parsed and bounded. Absent fields are ABSENT.

    Deliberately does NOT fill in defaults. `execution_guard.limits()` owns the
    default and env layers, and a second copy of them here would be a second
    thing to keep in sync -- the drift this whole module exists to avoid.
    Callers get "what did the user set", and nothing else.
    """
    stored, _ = _read_stored()
    if not stored:
        return {}
    resolved: dict[str, Any] = {}
    for name in EDITABLE_FIELDS:
        parsed = _coerce(name, stored.get(name))
        if parsed is None:
            continue
        resolved[name] = int(parsed) if name in _INTEGER_FIELDS else parsed
    return resolved


def stored_limit(name: str) -> float | None:
    """One saved cap, or None. The hot path `limits()` calls per field.

    Never raises: a store that cannot answer resolves to None, which sends the
    caller to its env-then-default chain. See the module note on why that is
    acceptable in exactly this system and not in general.
    """
    if name not in _BOUNDS:
        return None
    try:
        return stored_limits().get(name)
    except Exception:
        return None


def resolve_view() -> dict[str, Any]:
    """Everything the page needs: values in force, where each came from, and
    whether the two account-wide ceilings make the per-venue caps unreachable.

    `sources` is the same distinction `portfolio_settings` draws and for the
    same reason -- "you set $200" and "the store lost your edit and you are
    looking at the default" are different facts about a real-money cap.

    THE REACHABILITY NOTE IS THE POINT OF THIS FUNCTION. `max_day_dollars_
    all_venues` is enforced BEFORE the per-venue budgets and defaults to $150,
    so a user who raises Kalshi to $200 and Polymarket to $200 has changed
    nothing at all until the ceiling moves too. A form that accepted those
    edits without saying so would be the third inert-feature shape in one
    file. Computed, not asserted, so it stays true if the defaults change.
    """
    from syndicate.features.shared.execution_guard import LIVE_LIMIT_FIELDS, limits

    stored, store_error = _read_stored()
    live_caps = limits("live")
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for name in EDITABLE_FIELDS:
        values[name] = live_caps.get(name)
        if _coerce(name, stored.get(name)) is not None:
            sources[name] = "stored"
        elif os.environ.get(LIVE_LIMIT_FIELDS[name]):
            sources[name] = "env"
        else:
            sources[name] = "default"

    dollars_sum = float(values["max_day_dollars_kalshi"] or 0) + float(
        values["max_day_dollars_polymarket"] or 0
    )
    orders_sum = int(values["max_day_orders_kalshi"] or 0) + int(
        values["max_day_orders_polymarket"] or 0
    )

    def _severity(fields: tuple[str, ...]) -> str:
        """WARN ONLY WHEN SOMEBODY'S EDIT CAUSED IT.

        The SHIPPED DEFAULTS already trip this: 15 + 15 books against a 25
        account ceiling, and `execution_guard` says in as many words that the
        gap is on purpose -- "deliberately LESS than 15+15=30, so simply
        enabling a second venue cannot silently double the account's daily
        order budget". A permanent orange warning over a system behaving as
        designed is the exact thing the resting-orders banner was rewritten to
        stop being: *"a warning that fires on the system working correctly
        teaches the reader to ignore the warning"*.

        So the FACT is always reported -- a cap nobody can reach must never
        render as simply accepted -- and only its LOUDNESS depends on whether a
        stored or env value put it there.
        """
        return "warn" if any(sources.get(name) != "default" for name in fields) else "info"

    ceiling_notes: list[dict[str, str]] = []
    if dollars_sum > float(values["max_day_dollars_all_venues"] or 0):
        ceiling_notes.append(
            {
                "severity": _severity(
                    ("max_day_dollars_kalshi", "max_day_dollars_polymarket", "max_day_dollars_all_venues")
                ),
                "text": (
                    f"The two venue budgets total ${dollars_sum:,.2f}, above the "
                    f"${float(values['max_day_dollars_all_venues'] or 0):,.2f} account ceiling, which is "
                    "checked first — so the two books cannot both spend to their own number on one day."
                ),
            }
        )
    if orders_sum > int(values["max_day_orders_all_venues"] or 0):
        ceiling_notes.append(
            {
                "severity": _severity(
                    ("max_day_orders_kalshi", "max_day_orders_polymarket", "max_day_orders_all_venues")
                ),
                "text": (
                    f"The two venue order caps total {orders_sum}, above the "
                    f"{int(values['max_day_orders_all_venues'] or 0)} account ceiling, which is checked "
                    "first — so the two books cannot both place their full count on one day."
                ),
            }
        )

    updated_at = stored.get("updated_at") if isinstance(stored.get("updated_at"), str) else None
    return {
        **values,
        "sources": sources,
        "updated_at": updated_at,
        "store_error": store_error,
        "ceiling_notes": ceiling_notes,
        "venues": list(VENUES),
        "bounds": {name: list(bounds) for name, bounds in _BOUNDS.items()},
    }


def update_limits(changes: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Apply a partial edit. Returns the new view and per-field rejections.

    A rejected field keeps its previous value and is named in the result: a
    partial edit must never blank what it did not mention, and a bad value must
    never be silently ignored on a surface that spends money.
    """
    rejected: dict[str, str] = {}
    stored, _ = _read_stored()
    payload: dict[str, Any] = {name: stored.get(name) for name in EDITABLE_FIELDS if name in stored}

    for key, raw in (changes or {}).items():
        name = str(key).strip()
        if name not in _BOUNDS:
            rejected[name] = "unknown_field"
            continue
        parsed = _coerce(name, raw)
        if parsed is None:
            low, high = _BOUNDS[name]
            rejected[name] = f"out_of_range_or_unparseable (allowed {low}..{high})"
            continue
        payload[name] = int(parsed) if name in _INTEGER_FIELDS else parsed

    if not rejected or len(rejected) < len(changes or {}):
        payload["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            write_json_file(_settings_path(), payload)
        except Exception:
            # The caller still gets a view, and `resolve_view` will report the
            # store error -- but a write that failed must not read as a save.
            rejected.setdefault("__store__", "write_failed")

    return resolve_view(), rejected
