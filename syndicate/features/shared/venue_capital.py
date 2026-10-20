"""How much money each venue account actually holds, as a SIZING basis.

--------------------------------------------------------------------------
WHY THIS EXISTS: WINS NEVER COMPOUNDED
--------------------------------------------------------------------------

Every live stake was `stake_fraction x settings.bankroll_units`, and
`bankroll_units` is a CONSTANT (1000, `portfolio_settings.py`). Every live cap
was a constant dollar figure (`execution_guard.limits()`). So an account that
doubled kept betting the same dollars, and an account that halved kept betting
the same dollars too -- the second is the dangerous half. The capability audit
of 2026-10-19 ranked this first for autonomous trading.

This module turns the worker's balance stamp (`venue_balances.py`, written by
live-odds-worker every execution tick) into one number per venue -- the
CAPITAL -- and derives from it:

  * a SIZING bankroll per live position (`sizing_bankroll`), and
  * percentage CAPS per venue (`balance_caps`),

each bounded above by a dollar CEILING, so turning this on can only ever make
the system bet LESS than an operator has already allowed, never more.

--------------------------------------------------------------------------
WHAT "CAPITAL" IS, PER VENUE -- READ FROM THE STAMP, MEASURED 2026-10-19
--------------------------------------------------------------------------

KALSHI: `dollars` (cash, the SUM across exchange shards) + `portfolio_value_
dollars`. The second is the value of OPEN POSITIONS ONLY -- measured
2026-10-19T18:13Z it read 4.50 with exactly one open $4.50 position and $485.48
cash, so it does NOT include cash (venue_balances' old comment said it did).
Cash + positions is stable while money moves from one into the other, which a
cash-only basis is not: a day cap of 25% of CASH shrinks with every order it
admits.

  A Kalshi order is collateralised by ITS OWN SHARD only (`#573`), so a
  position's bankroll is additionally bounded by the cash on the shard its
  market's `exchange_index` routes to. Measured 2026-10-19: shards
  {0: 170.00, 1: 75.01, 2: 0.00, 3: 240.47} -- MLB, WNBA, NBA and Tennis all
  draw on shard 3, so sizing them against the $490 account would size as if
  money on shards 0 and 1 could fund them. It cannot.

POLYMARKET: `buyingPower`, PENDING DEPOSIT INCLUDED. Measured 2026-10-19:
`buyingPower` 586.05 = `displayedCash` 36.05 + `displayedAvailableSoon` 550.00,
with `depositReservation` 550.00 and `availableToWithdraw` 36.05. **A pending
deposit IS counted in buying power**, and the venue lets it be spent.

USER DECISION 2026-10-19 (lane caps-revamp): "the $500 pending on polymarket
CAN be used". This module first subtracted the deposit as money that might
bounce; that sized Polymarket at $36 against $586 the venue would accept.
Capital is now `buyingPower`, the figure the venue itself spends against. The
pending amount (max of `depositReservation`, `displayedAvailableSoon`) is
still read and reported as `pending_deposit_dollars`, so a bounced deposit
shows up as a drop in capital on the next stamp rather than going unseen.
Open Polymarket positions are not added -- the venue does not tell us their
value in a field we can prove means that -- which is the conservative error.

--------------------------------------------------------------------------
UNKNOWN FAILS CLOSED HERE -- THE OPPOSITE OF execution_guard's BALANCE GATE
--------------------------------------------------------------------------

`execution_guard._venue_available_dollars` lets an unknown balance ALLOW,
because the venue's own 4xx is a free backstop for a REFUSAL question. That
reasoning does not transfer to SIZING: if we do not know what the account
holds, there is no number to take a fraction of, and the only fallback that
exists -- the fixed $1,000 -- is the very thing this replaces. So a stale,
absent, non-`ok` or unreadable reading yields `known: False` with a NAMED
reason, and the callers refuse rather than size.

Every function here is PURE over a stamp it is handed (or reads once), never
raises, and reads nothing it was not told to.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "COMPOUNDING_MODE_ENV",
    "BALANCE_CAPS_ENV",
    "compounding_mode",
    "balance_caps_enabled",
    "compounding_config",
    "venue_capital",
    "sizing_bankroll",
    "balance_caps",
]

# off | shadow | on. ABSENT = off = today's behaviour exactly (fixed bankroll).
# `shadow` computes and stamps the compounding stake beside the real one and
# changes nothing placed -- the paper-measurement mode.
COMPOUNDING_MODE_ENV = "SYNDICATE_COMPOUNDING_BANKROLL"
# on | off. ABSENT = off = the dollar caps exactly as configured today.
BALANCE_CAPS_ENV = "SYNDICATE_EXECUTION_BALANCE_CAPS"

_FRACTION_ENV = "SYNDICATE_COMPOUNDING_BANKROLL_FRACTION"
_CEILING_ENV = "SYNDICATE_COMPOUNDING_BANKROLL_MAX_DOLLARS"
_DAY_PCT_ENV = "SYNDICATE_EXECUTION_BALANCE_DAY_PCT"
_ORDER_PCT_ENV = "SYNDICATE_EXECUTION_BALANCE_ORDER_PCT"
_MAX_AGE_ENV = "SYNDICATE_COMPOUNDING_MAX_STAMP_AGE_SECONDS"
# `SYNDICATE_COMPOUNDING_BANKROLL_MAX_DOLLARS=capital`: the ceiling follows the account.
_CEILING_CAPITAL = "capital"
# Option (b), user 2026-10-20: `venue_total` sizes Kalshi against the whole
# account; absent (`shard`) keeps the shard-bounded bankroll. Opt-in by value so
# this code cannot change live sizing at a restart before the user approves.
_BASIS_ENV = "SYNDICATE_COMPOUNDING_BASIS"
_BASIS_SHARD = "shard"
_BASIS_VENUE_TOTAL = "venue_total"
# Option (a), user 2026-10-20: `one_contract` makes the minimum for a compounded
# stake one whole contract at the order's price; absent keeps `min_stake_units`.
_MIN_STAKE_ENV = "SYNDICATE_COMPOUNDING_MIN_STAKE"
MIN_STAKE_DOLLARS = "dollars"
MIN_STAKE_ONE_CONTRACT = "one_contract"
# The user's pick, 2026-10-20 ("(b) + floor"): a compounded stake under one
# contract is ROUNDED UP to exactly one contract, fee included, instead of
# refused -- but never past the cash that has to fund it.
MIN_STAKE_FLOOR_ONE_CONTRACT = "floor_one_contract"
_MIN_STAKE_VALUES = (MIN_STAKE_ONE_CONTRACT, MIN_STAKE_FLOOR_ONE_CONTRACT)

# How much of a venue's capital is the sizing bankroll. 1.0 = the Kelly
# fractions `bankroll_manager` already computes are fractions of the real
# account, which is what a Kelly fraction means.
_DEFAULT_FRACTION = 1.0
# The share of a venue's capital that may be committed in one day, and in one
# order. User-specified starting points 2026-10-19 ("e.g. day 25%, per-order 5%").
_DEFAULT_DAY_PCT = 0.25
_DEFAULT_ORDER_PCT = 0.05
# The stamp is written every live-odds-worker execution tick (~5 min, measured
# 2026-10-19: 13:02:23, 13:07:27, 13:13:05 CDT). The same hour the balance gate
# uses: twelve missed ticks is not a slow worker, it is a stopped one.
_DEFAULT_MAX_AGE_SECONDS = 3600.0

_OFF = "off"
_SHADOW = "shadow"
_ON = "on"


def _float_env(name: str, default: float, *, low: float, high: float) -> float:
    """A bounded float from env; anything unusable is the DEFAULT, never 0/inf."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if value != value or value < low or value > high:
        return default
    return value


def compounding_mode() -> str:
    """`off` | `shadow` | `on`. Anything unrecognised is `off` -- today's sizing."""
    raw = str(os.environ.get(COMPOUNDING_MODE_ENV) or "").strip().lower()
    if raw in {"on", "1", "true", "yes", "live"}:
        return _ON
    if raw == _SHADOW:
        return _SHADOW
    return _OFF


def balance_caps_enabled() -> bool:
    raw = str(os.environ.get(BALANCE_CAPS_ENV) or "").strip().lower()
    return raw in {"on", "1", "true", "yes"}


def compounding_config() -> dict[str, Any]:
    """Every knob, resolved, so a log line can state what was applied."""
    ceiling_raw = str(os.environ.get(_CEILING_ENV) or "").strip().lower()
    ceiling = _float_env(_CEILING_ENV, -1.0, low=0.01, high=10_000_000.0)
    return {
        "mode": compounding_mode(),
        "balance_caps": balance_caps_enabled(),
        "fraction": _float_env(_FRACTION_ENV, _DEFAULT_FRACTION, low=0.01, high=1.0),
        # THE CEILING FOLLOWS THE ACCOUNT when set to `capital` [user 2026-10-20:
        # "make the ceiling adjust based on capital available"]: no fixed dollar
        # figure, so the bankroll is `fraction x capital` and grows (and shrinks)
        # with what the venue holds -- never more than all of it, since fraction
        # is bounded at 1.0, and Kalshi is still bounded by the order's shard.
        # Opt-in by value, not a new default: an ABSENT key keeps the fixed
        # bankroll, so shipping this code changes nothing until the env says so.
        "ceiling_mode": "capital" if ceiling_raw == _CEILING_CAPITAL else ("dollars" if ceiling > 0 else "fixed_bankroll"),
        # None = "the fixed bankroll in force today" -- see `sizing_bankroll`.
        "ceiling_dollars": ceiling if ceiling > 0 else None,
        "ceiling_env_set": bool(ceiling_raw),
        "basis": (
            _BASIS_VENUE_TOTAL
            if str(os.environ.get(_BASIS_ENV) or "").strip().lower() == _BASIS_VENUE_TOTAL
            else _BASIS_SHARD
        ),
        "min_stake": next(
            (
                value
                for value in _MIN_STAKE_VALUES
                if str(os.environ.get(_MIN_STAKE_ENV) or "").strip().lower() == value
            ),
            MIN_STAKE_DOLLARS,
        ),
        "day_pct": _float_env(_DAY_PCT_ENV, _DEFAULT_DAY_PCT, low=0.001, high=1.0),
        "order_pct": _float_env(_ORDER_PCT_ENV, _DEFAULT_ORDER_PCT, low=0.001, high=1.0),
        "max_age_seconds": _float_env(_MAX_AGE_ENV, _DEFAULT_MAX_AGE_SECONDS, low=60.0, high=86_400.0),
    }


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _age_seconds(stamp: Any, now: datetime | None) -> float | None:
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - parsed).total_seconds()


def _read_stamp() -> Mapping[str, Any] | None:
    try:
        from syndicate.features.shared.venue_balances import read_venue_balances

        return read_venue_balances()
    except Exception:
        return None


_NO_STAMP = object()


def venue_capital(
    venue: str | None,
    stamp: Any = _NO_STAMP,
    *,
    now: datetime | None = None,
    max_age_seconds: float | None = None,
) -> dict[str, Any]:
    """`{"known": bool, "capital": float, "reason": str|None, ...}` for one venue.

    `stamp` defaults to a fresh read; pass one to evaluate several venues on
    the SAME reading. `known` is False for every absence, each under its own
    reason -- "the worker never reported" and "the deposit may bounce" call for
    different responses.
    """
    name = str(venue or "").strip().lower()
    if not name:
        return {"known": False, "reason": "no_venue"}
    if stamp is _NO_STAMP:
        stamp = _read_stamp()
    if not isinstance(stamp, Mapping) or not stamp:
        return {"known": False, "venue": name, "reason": "never_recorded"}

    limit = float(max_age_seconds if max_age_seconds is not None else compounding_config()["max_age_seconds"])
    age = _age_seconds(stamp.get("recorded_at"), now)
    if age is None:
        return {"known": False, "venue": name, "reason": "unstamped_reading"}
    if age > limit:
        return {"known": False, "venue": name, "reason": "stale_reading", "age_seconds": round(age, 1)}

    row = (stamp.get("venues") or {}).get(name) if isinstance(stamp.get("venues"), Mapping) else None
    if not isinstance(row, Mapping) or not row:
        return {"known": False, "venue": name, "reason": "venue_absent_from_stamp"}
    if str(row.get("status") or "") != "ok":
        return {"known": False, "venue": name, "reason": f"balance_{row.get('status') or 'unknown'}"}

    base: dict[str, Any] = {"venue": name, "age_seconds": round(age, 1), "recorded_at": stamp.get("recorded_at")}

    if name == "kalshi":
        cash = _number(row.get("dollars"))
        if cash is None:
            return {"known": False, **base, "reason": "unusable_balance_value"}
        positions = _number(row.get("portfolio_value_dollars"))
        shards = row.get("shards") if str(row.get("shards_status") or "") == "ok" else None
        capital = cash + (positions if positions is not None and positions > 0 else 0.0)
        return {
            "known": True,
            **base,
            "capital": round(max(capital, 0.0), 2),
            "cash_dollars": round(cash, 2),
            "positions_dollars": round(positions, 2) if positions is not None else None,
            # "cash_plus_positions" or, when the venue omitted the positions
            # figure, the smaller and still-safe "cash_only".
            "basis": "cash_plus_positions" if positions is not None else "cash_only",
            "shards": {str(k): _number(v) for k, v in shards.items()} if isinstance(shards, Mapping) else None,
            "shards_status": row.get("shards_status"),
            "reason": None,
        }

    if name == "polymarket":
        buying_power = _number(row.get("buying_power_dollars"))
        if buying_power is None:
            buying_power = _number(row.get("dollars"))
        if buying_power is None:
            return {"known": False, **base, "reason": "unusable_balance_value"}
        # The pending deposit is spendable (user decision 2026-10-19, see the
        # module docstring), so it is REPORTED, not subtracted. An unreadable
        # pending figure no longer blocks sizing: it only changes what we can
        # say about the capital, not the capital itself.
        numbers = ((row.get("detail") or {}).get("numbers")) if isinstance(row.get("detail"), Mapping) else None
        pending_values = [
            value
            for value in (
                _number(numbers.get(key)) for key in ("depositReservation", "displayedAvailableSoon")
            )
            if value is not None
        ] if isinstance(numbers, Mapping) else []
        pending = max(pending_values + [0.0]) if pending_values else None
        return {
            "known": True,
            **base,
            "capital": round(max(buying_power, 0.0), 2),
            "buying_power_dollars": round(buying_power, 2),
            "pending_deposit_dollars": round(pending, 2) if pending is not None else None,
            "basis": "buying_power_incl_pending_deposit",
            "reason": None,
        }

    return {"known": False, **base, "reason": "venue_has_no_capital_rule"}


def sizing_bankroll(
    venue: str | None,
    *,
    fixed_bankroll: float,
    ticker: Any = None,
    stamp: Any = _NO_STAMP,
    shard_of: Callable[[Any], tuple[int | None, str | None]] | None = None,
    config: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The bankroll ONE live position is sized against, or a named refusal.

    `min(fraction x venue capital, ceiling)`, and for Kalshi also `<= the cash
    on the order's own shard`. The ceiling defaults to `fixed_bankroll` -- the
    number sizing used before this existed -- so enabling compounding cannot
    size a single dollar above today's policy until someone raises the ceiling
    on purpose (`SYNDICATE_COMPOUNDING_BANKROLL_MAX_DOLLARS`). Set to `capital`,
    the ceiling IS the venue's capital, so the bankroll tracks the account.
    """
    cfg = dict(config or compounding_config())
    capital = venue_capital(venue, stamp, now=now, max_age_seconds=cfg.get("max_age_seconds"))
    if not capital.get("known"):
        return {"known": False, "reason": capital.get("reason"), "capital": capital}

    ceiling = cfg.get("ceiling_dollars")
    if cfg.get("ceiling_mode") == "capital":
        ceiling = float(capital["capital"])
    elif ceiling is None:
        ceiling = float(fixed_bankroll)
    bankroll = min(float(cfg["fraction"]) * float(capital["capital"]), float(ceiling))
    result: dict[str, Any] = {
        "known": True,
        "reason": None,
        "venue": capital.get("venue"),
        "capital": round(float(capital["capital"]), 2),
        "capital_basis": capital.get("basis"),
        "fraction": cfg["fraction"],
        "ceiling_dollars": round(float(ceiling), 2),
        "age_seconds": capital.get("age_seconds"),
    }

    result["basis"] = cfg.get("basis") or _BASIS_SHARD
    if capital.get("venue") == "kalshi" and result["basis"] == _BASIS_VENUE_TOTAL:
        # THE WHOLE ACCOUNT IS THE BANKROLL [user 2026-10-20, option (b)]. Kelly
        # is a fraction of total wealth; which shard holds the cash is a FUNDING
        # question, and the placement-time shard gate
        # (`execution_guard._shard_available_dollars`, `insufficient_shard_balance`)
        # already refuses an order its shard cannot cover. Bounding the bankroll
        # by one shard instead shrank every position below one contract
        # (10-20: DEL $0.20 on shard 0, Maxey $0.49 on shard 3, both refused).
        # The shard is still reported when it resolves, never required.
        shards = capital.get("shards")
        if isinstance(shards, Mapping) and shard_of is not None:
            try:
                shard, _why = shard_of(ticker)
            except Exception:
                shard = None
            if shard is not None and shards.get(str(shard)) is not None:
                result["shard"] = shard
                result["shard_cash"] = round(float(shards[str(shard)]), 2)
    elif capital.get("venue") == "kalshi":
        shards = capital.get("shards")
        if not isinstance(shards, Mapping):
            return {"known": False, "reason": f"shards_{capital.get('shards_status') or 'absent'}", "capital": capital}
        if shard_of is None:
            return {"known": False, "reason": "shard_resolver_absent", "capital": capital}
        try:
            shard, why = shard_of(ticker)
        except Exception as exc:
            shard, why = None, f"resolver_error:{type(exc).__name__}"
        if shard is None:
            return {"known": False, "reason": f"shard_unresolved:{why}", "capital": capital}
        shard_cash = shards.get(str(shard))
        if shard_cash is None:
            return {"known": False, "reason": "shard_absent_from_breakdown", "shard": shard, "capital": capital}
        result["shard"] = shard
        result["shard_cash"] = round(float(shard_cash), 2)
        bankroll = min(bankroll, float(shard_cash))

    result["bankroll"] = round(max(bankroll, 0.0), 2)
    return result


def one_contract_dollars(position: Mapping[str, Any]) -> float | None:
    """What the smallest placeable order costs for this position, or None.

    A contract settles at $1, so its price is the implied probability of the
    side bought, read from the plan's American `price`. Polymarket orders come
    in `minimum_trade_qty` increments (carried on its `venue_ticker` dict), so
    its minimum is that many contracts. None when the price is unusable -- the
    caller then refuses rather than guessing.
    """
    american = _number(position.get("price"))
    if american is None or american == 0 or -100 < american < 100:
        return None
    each = 100.0 / (american + 100.0) if american > 0 else (-american) / (-american + 100.0)
    if not 0.0 < each < 1.0:
        return None
    qty = 1.0
    ticker = position.get("venue_ticker")
    if isinstance(ticker, Mapping):
        minimum = _number(ticker.get("minimum_trade_qty"))
        if minimum is not None and minimum > 1.0:
            qty = minimum
    return round(each * qty, 4)


def one_contract_floor_dollars(position: Mapping[str, Any], venue: str | None) -> dict[str, Any] | None:
    """The stake that buys EXACTLY one contract (one increment), fee included.

    `(price + taker fee per contract) x quantity`, rounded UP to the cent. The
    executors floor dollars to contracts with no fee taken off first
    (`kalshi_orders.contracts_for_stake`, `polymarket_us_orders.quantity_for_stake`),
    so this buys one, never two, while the fee is below the price -- always, on
    a $1 contract. If the live price has risen past the fee by send time, the
    count comes out 0 and the builder refuses before anything is sent: the
    floor cannot overbet. None when the plan cannot state a price.
    """
    each = one_contract_dollars({"price": position.get("price")})
    if each is None:
        return None
    qty = 1.0
    ticker = position.get("venue_ticker")
    if isinstance(ticker, Mapping):
        minimum = _number(ticker.get("minimum_trade_qty"))
        if minimum is not None and minimum > 1.0:
            qty = minimum
        ticker_ref = ticker.get("slug")
    else:
        ticker_ref = ticker
    fee_each = 0.0
    try:
        from syndicate.features.shared.venue_fees import taker_fee_per_contract

        rate, _basis, _bound = taker_fee_per_contract(
            venue, each, venue_ref=ticker_ref,
            sport=position.get("sport"), market=position.get("market"), segment=position.get("segment"),
        )
        # Kalshi's figure is dollars per $1 contract; Polymarket's is a rate on
        # the notional, which for one contract is its price.
        fee_each = float(rate) * (each if str(venue or "").lower() == "polymarket" else 1.0)
    except Exception:
        # An unreadable fee schedule is charged the conservative way: one cent.
        fee_each = 0.01
    import math

    dollars = math.ceil(round((each + fee_each) * qty * 100.0, 6)) / 100.0
    return {"dollars": dollars, "price_each": each, "fee_each": round(fee_each, 4), "qty": qty}


def balance_caps(
    ceilings: Mapping[str, float],
    *,
    venues: tuple[str, ...] = ("kalshi", "polymarket"),
    stamp: Any = _NO_STAMP,
    config: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Percentage caps per venue, each bounded by the dollar cap already in force.

    `ceilings` holds the dollar values `limits()` resolved the old way --
    `max_order_dollars`, `max_day_dollars_<venue>`, `max_day_dollars_all_venues`
    -- so a percentage can tighten a cap and never loosen it.

    A venue whose capital is unknown is listed in `fail_closed` with its reason
    and gets ZERO dollar caps: `check_order` refuses it by name.
    """
    cfg = dict(config or compounding_config())
    if stamp is _NO_STAMP:
        stamp = _read_stamp()
    day_pct = float(cfg["day_pct"])
    order_pct = float(cfg["order_pct"])

    capital: dict[str, Any] = {}
    day: dict[str, float] = {}
    order: dict[str, float] = {}
    fail_closed: dict[str, str] = {}
    known_total = 0.0
    for venue in venues:
        reading = venue_capital(venue, stamp, now=now, max_age_seconds=cfg.get("max_age_seconds"))
        capital[venue] = {
            key: reading.get(key)
            for key in ("known", "capital", "basis", "reason", "age_seconds", "pending_deposit_dollars")
            if key in reading
        }
        if not reading.get("known"):
            fail_closed[venue] = str(reading.get("reason") or "unknown")
            day[venue] = 0.0
            order[venue] = 0.0
            continue
        amount = float(reading["capital"])
        known_total += amount
        day[venue] = round(min(float(ceilings.get(f"max_day_dollars_{venue}", 0.0)), day_pct * amount), 2)
        order[venue] = round(min(float(ceilings.get("max_order_dollars", 0.0)), order_pct * amount), 2)

    all_venues = round(min(float(ceilings.get("max_day_dollars_all_venues", 0.0)), day_pct * known_total), 2)
    return {
        "enabled": True,
        "day_pct": day_pct,
        "order_pct": order_pct,
        "capital": capital,
        "max_day_dollars_by_venue": day,
        "max_order_dollars_by_venue": order,
        "max_day_dollars_all_venues": all_venues,
        "ceilings": {key: float(value) for key, value in ceilings.items()},
        "fail_closed": fail_closed,
        "recorded_at": stamp.get("recorded_at") if isinstance(stamp, Mapping) else None,
    }
