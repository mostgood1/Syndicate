"""User-editable portfolio policy: the bankroll, and the knobs that spend it.

**WHY THIS FILE EXISTS.** `bankroll_manager` has always returned FRACTIONS --
`stake_fraction`, `cap_fraction`, `_DEFAULT_GAME_EXPOSURE_CAP` -- and there was
no number anywhere in the system for them to be fractions OF. So the board
could say "2.1% of bankroll" and nothing could turn that into dollars. This
holds that number, and the three policy knobs that decide how much of it a
single slate may spend.

**THE STORAGE DECISION, AND WHY IT IS NOT THE OBVIOUS ONE.**

`render.yaml` declares no database of any kind: three services, three separate
50GB disks, one shared 256MB `keyvalue` on the starter plan. That store is
recorded in `refresh_state_store.py:139-205` at 96% memory with 34,529
LRU-evicted keys and a 44% keyspace miss rate. Two things follow, and both
shape this file:

1. **No date token in the path.** `_default_keyvalue_ttl_seconds` hands any
   path containing a date a 10-day TTL. A bankroll that silently expires after
   ten days is worse than one that cannot be edited at all, because the failure
   is invisible. `_settings_path()` is deliberately date-free.
2. **`allkeys-lru` evicts keys that carry no TTL too.** So this file must
   assume its own store can return nothing at any time, on a healthy system,
   with no error. That is not a hypothetical: 38,865 keys had been evicted when
   the store was last measured.

**Therefore every read is fail-SAFE in a stated direction: a missing or
unreadable setting resolves to the DEFAULT, never to zero and never to an
exception.** A bankroll that reads as 0 would size every bet at $0 and produce
an empty portfolio that looks exactly like "the model found nothing today" --
the single most expensive confusion this system can generate, and precisely the
shape `learnings.md` keeps calling out: a zero that cannot be told apart from a
working feature. `resolve_settings()` therefore reports `source` per field, so
"you set this" and "you are seeing the default because the store lost it" are
distinguishable at a glance rather than by inference.

**Precedence:** stored value (user edit) > environment variable > built-in
default. The env layer exists so an operator can move the default without a
user edit, and so a test can pin one without touching the store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from syndicate.features.shared.refresh_state_store import (
    read_json_file,
    reports_root,
    write_json_file,
)

# The user's opening figure, 2026-08-22. Editable in the UI; this is only the
# value a brand-new install (or a store that lost the key) resolves to.
DEFAULT_BANKROLL_UNITS = 1000.0

# How much of the bankroll one slate may have at risk in total, across every
# position. Distinct from bankroll_manager's `_DEFAULT_GAME_EXPOSURE_CAP`
# (0.05), which bounds ONE GAME -- without a slate-level ceiling, twenty
# uncorrelated games at the per-game cap would put the entire bankroll in play
# on a single evening and still satisfy every existing rule.
DEFAULT_MAX_SLATE_EXPOSURE_FRACTION = 0.20

# The cut line. A row whose expected value is below this does not get committed
# at any size. Expressed in the same units the board reports (`ev_pct`, points
# of percent per unit staked), so it can be compared against a served row
# without a conversion.
DEFAULT_MIN_EV_PCT = 2.0

# A hard count ceiling, independent of money. Twelve positions a slate is
# already more than a person can follow; the cap exists so a day with hundreds
# of thin edges cannot produce a portfolio nobody can execute or check.
DEFAULT_MAX_POSITIONS = 12

# Below this, a stake is not worth placing -- rounding and minimum bet sizes at
# any venue make a $0.40 position noise. Committed rows below it are dropped
# with a named reason rather than rounded up.
DEFAULT_MIN_STAKE_UNITS = 1.0

_BOUNDS: dict[str, tuple[float, float]] = {
    "bankroll_units": (1.0, 10_000_000.0),
    "max_slate_exposure_fraction": (0.001, 1.0),
    "min_ev_pct": (-100.0, 100.0),
    "max_positions": (1, 500),
    "min_stake_units": (0.0, 100_000.0),
}

_ENV_KEYS: dict[str, str] = {
    "bankroll_units": "SYNDICATE_BANKROLL_UNITS",
    "max_slate_exposure_fraction": "SYNDICATE_MAX_SLATE_EXPOSURE_FRACTION",
    "min_ev_pct": "SYNDICATE_PORTFOLIO_MIN_EV_PCT",
    "max_positions": "SYNDICATE_PORTFOLIO_MAX_POSITIONS",
    "min_stake_units": "SYNDICATE_PORTFOLIO_MIN_STAKE_UNITS",
}

_DEFAULTS: dict[str, float] = {
    "bankroll_units": DEFAULT_BANKROLL_UNITS,
    "max_slate_exposure_fraction": DEFAULT_MAX_SLATE_EXPOSURE_FRACTION,
    "min_ev_pct": DEFAULT_MIN_EV_PCT,
    "max_positions": float(DEFAULT_MAX_POSITIONS),
    "min_stake_units": DEFAULT_MIN_STAKE_UNITS,
}

EDITABLE_FIELDS = tuple(_DEFAULTS.keys())


@dataclass(frozen=True)
class PortfolioSettings:
    """Resolved policy. `sources` says where each field actually came from."""

    bankroll_units: float = DEFAULT_BANKROLL_UNITS
    max_slate_exposure_fraction: float = DEFAULT_MAX_SLATE_EXPOSURE_FRACTION
    min_ev_pct: float = DEFAULT_MIN_EV_PCT
    max_positions: int = DEFAULT_MAX_POSITIONS
    min_stake_units: float = DEFAULT_MIN_STAKE_UNITS
    sources: Mapping[str, str] = field(default_factory=dict)
    updated_at: str | None = None
    # Set when the stored settings could not be read AT ALL (store down, key
    # evicted, payload corrupt). Distinct from "nothing has ever been saved":
    # the first is a fault the user should see, the second is a fresh install.
    store_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "bankroll_units": self.bankroll_units,
            "max_slate_exposure_fraction": self.max_slate_exposure_fraction,
            "min_ev_pct": self.min_ev_pct,
            "max_positions": self.max_positions,
            "min_stake_units": self.min_stake_units,
            "sources": dict(self.sources or {}),
            "updated_at": self.updated_at,
            "store_error": self.store_error,
            "defaults": dict(_DEFAULTS),
        }

    def max_slate_exposure_units(self) -> float:
        return self.bankroll_units * self.max_slate_exposure_fraction


def _settings_path():
    # NO DATE TOKEN. See the module docstring -- a dated path would be handed a
    # 10-day TTL by `_default_keyvalue_ttl_seconds` and the user's bankroll
    # would expire without anything saying so.
    return reports_root() / "intelligence" / "portfolio_settings.json"


def _coerce(name: str, value: Any) -> float | None:
    """Parse and bound one field. Returns None when the value is unusable.

    Refusing rather than clamping is deliberate: a clamp turns a typo into a
    silently different policy that still looks accepted. `learnings.md`
    2026-08-08 makes the same call for `_MODEL_EDGE_MAX_POINTS` -- "dropped, not
    clamped ... a wrong answer wearing a plausible one's clothes".
    """
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
    return parsed


def _read_stored() -> tuple[dict[str, Any], str | None]:
    try:
        payload = read_json_file(_settings_path())
    except Exception as exc:  # store down, evicted, unparseable
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, Mapping):
        return {}, None
    return dict(payload), None


def resolve_settings() -> PortfolioSettings:
    """Stored > env > default, per field, with the winner recorded.

    Never raises and never returns a zero bankroll. Every failure mode lands on
    the default and says so in `sources`.
    """
    stored, store_error = _read_stored()
    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    for name, default in _DEFAULTS.items():
        parsed = _coerce(name, stored.get(name)) if stored else None
        if parsed is not None:
            values[name], sources[name] = parsed, "stored"
            continue
        parsed = _coerce(name, os.environ.get(_ENV_KEYS[name]))
        if parsed is not None:
            values[name], sources[name] = parsed, "env"
            continue
        values[name], sources[name] = default, "default"
    updated_at = stored.get("updated_at") if isinstance(stored.get("updated_at"), str) else None
    return PortfolioSettings(
        bankroll_units=values["bankroll_units"],
        max_slate_exposure_fraction=values["max_slate_exposure_fraction"],
        min_ev_pct=values["min_ev_pct"],
        max_positions=int(values["max_positions"]),
        min_stake_units=values["min_stake_units"],
        sources=sources,
        updated_at=updated_at,
        store_error=store_error,
    )


def update_settings(changes: Mapping[str, Any]) -> tuple[PortfolioSettings, dict[str, str]]:
    """Apply a partial edit. Returns the new settings and per-field rejections.

    A rejected field is reported BY NAME and leaves its previous value intact --
    a partial edit must never blank the fields it did not mention, and a bad
    value must never be silently ignored. Unknown keys are rejected too, so a
    typo'd field name cannot read as a successful save.
    """
    rejected: dict[str, str] = {}
    stored, _ = _read_stored()
    payload = {name: stored.get(name) for name in EDITABLE_FIELDS if name in stored}

    for key, raw in (changes or {}).items():
        name = str(key).strip()
        if name not in _DEFAULTS:
            rejected[name] = "unknown_field"
            continue
        parsed = _coerce(name, raw)
        if parsed is None:
            low, high = _BOUNDS[name]
            rejected[name] = f"out_of_range_or_unparseable (allowed {low}..{high})"
            continue
        payload[name] = int(parsed) if name == "max_positions" else parsed

    if not rejected or len(rejected) < len(changes or {}):
        payload["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            write_json_file(_settings_path(), payload)
        except Exception as exc:
            # The write is the whole point of this call -- a failure here must
            # surface, not resolve to "saved" with the old value returned.
            rejected["_store"] = f"write_failed: {type(exc).__name__}: {exc}"
        else:
            # READ IT BACK. A write that raises is easy; a write that returns
            # cleanly and does not land is the one that costs you -- and on this
            # store that is a real shape, not a hypothetical: `write_json_file`
            # routes to the keyvalue backend, whose payload guard can reject and
            # whose policy can evict. Without this, "saved" and "silently did
            # not save" are the same screen.
            try:
                stored_back, _ = _read_stored()
                for name, value in payload.items():
                    if name == "updated_at":
                        continue
                    if _coerce(name, stored_back.get(name)) != _coerce(name, value):
                        rejected["_store"] = (
                            f"write_not_durable: {name} read back as "
                            f"{stored_back.get(name)!r}, expected {value!r}"
                        )
                        break
            except Exception as exc:
                rejected["_store"] = f"readback_failed: {type(exc).__name__}: {exc}"

    return resolve_settings(), rejected
