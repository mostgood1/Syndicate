"""What is actually in each venue account, fetched on the worker, read by web.

--------------------------------------------------------------------------
WHY THIS IS A STAMPED ARTIFACT AND NOT A CALL FROM THE PAGE
--------------------------------------------------------------------------

Two independent reasons, and either alone settles it:

1. **Web has no credentials and must not get them.** `KALSHI_PRIVATE_KEY` and
   `POLYMARKET_US_PRIVATE_KEY` are dashboard-set on live-odds-worker,
   deliberately absent from `render.yaml` (`#284` -- a `render.yaml` push fires
   `blueprint_sync` against all three services). The web process literally
   cannot sign a request, which is the same reason `record_execution_state`
   exists at all.

2. **A second independent live caller of a venue is a documented incident class
   here** (`#139`/`#144`/`#148`, and `venue_quote_adapters.py` says so in its
   own words). `_polymarket_resolve_market` was rewritten in August precisely to
   read a persisted artifact instead of calling the venue a second time. A
   balance widget that hit the venue on every page load would be that mistake
   with a nicer UI: one request handler, N viewers, no rate budget.

So: the worker fetches on its execution tick (≥5 minutes apart), stamps here,
and the page reads the stamp with its age. Identical shape to
`execution_state.json`, and for identical reasons.

--------------------------------------------------------------------------
NO NUMBER IS BETTER THAN A WRONG ONE, AND $0.00 IS THE WRONG ONE
--------------------------------------------------------------------------

"We could not read the balance" and "the account is empty" are opposite facts
that a naive implementation renders as the same `$0.00` -- and one of them says
stop trading while the other says something is broken. Every failure here
therefore carries a NAMED status and no dollar figure at all:

    ok                  a number we read
    credentials_absent  no key configured on this process
    auth_error          the venue answered and refused (or the call failed)
    path_unknown        Polymarket only -- no balance endpoint has answered yet
    shape_unrecognised  it answered, and nothing in it looks like a balance

--------------------------------------------------------------------------
KALSHI IS VERIFIED. POLYMARKET IS NOT, AND IS NOT PRETENDED TO BE
--------------------------------------------------------------------------

`GET /trade-api/v2/portfolio/balance` is exercised and working: measured
2026-08-23T22:53Z, it returned 200 from a signed call in the same minute
unauthenticated reads were being rate-limited (`kalshi_client.py:252`), and
`kalshi_auth.probe_auth` has asked for it ever since.

`api.polymarket.us` has no balance path documented anywhere in this repo --
`polymarket_us_auth.probe_auth()` asks `/markets`. Rather than hard-code a
guess that fails as a 404 forever, this DISCOVERS the path once from a short
ordered candidate list, records which one answered, and reuses it. If none
answer, the state is `path_unknown` and the page says so. The candidates are
all read-only GETs and discovery runs only while nothing is recorded.

THE UNIT IS AN ASSUMPTION AND IT IS NAMED. Kalshi documents cents; this repo
has already been burned by exactly that class of error once (a 100x price bug
caught by reporting the shape rather than parsing it). So the raw value and the
assumed unit are BOTH stamped, and the first real run can correct the constant
without anyone having to reverse-engineer a displayed number.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any

from syndicate.features.shared.refresh_state_store import (
    read_json_file,
    reports_root,
    write_json_file,
)

VENUES: tuple[str, ...] = ("kalshi", "polymarket")

# Kalshi's balance endpoint, relative to the signed base URL. Verified working.
KALSHI_BALANCE_PATH = "/portfolio/balance"

# ASSUMPTION, in one place so a live run can correct it the way `_MARKET_FIELDS`
# was corrected. Kalshi documents integer CENTS for balance.
KALSHI_BALANCE_IS_CENTS = True

# Polymarket US candidates, most-likely first. All GET, all read-only. An
# operator can pin the answer with `POLYMARKET_US_BALANCE_PATH` and skip
# discovery entirely.
#
# `/account/balances` IS THE REAL ONE -- supplied by the user 2026-08-26 after
# the first production discovery round returned `path_unknown` against all four
# guesses. It is PLURAL, which is exactly why the singular `/account/balance`
# missed by one character. Recorded here rather than pinned in an env var so it
# lives in git and needs no dashboard state to survive.
#
# The rest are kept below it: they cost one GET each only on a venue that has
# never answered, and a venue that renames its route is exactly the case
# discovery exists for.
POLYMARKET_BALANCE_PATH_CANDIDATES: tuple[str, ...] = (
    "/account/balances",
    "/portfolio/balance",
    "/account/balance",
    "/balance",
    "/portfolio",
)

# Field names to look for in whatever comes back, in order. Reported rather
# than assumed: `shape_unrecognised` is a real answer and a useful one.
_BALANCE_FIELDS: tuple[str, ...] = (
    "balance",
    "available_balance",
    "availableBalance",
    "cash_balance",
    "cashBalance",
    "buying_power",
    "buyingPower",
    "available",
)


def balances_path():
    # NO DATE TOKEN, same as the ledger and the execution stamp: a balance that
    # silently expires after ten days would leave the page reporting nothing
    # while the account is funded.
    return reports_root() / "intelligence" / "venue_balances.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Currency/asset labels that mean "this row is the spendable cash one" when an
# endpoint returns a LIST of balances. Anything else is left alone rather than
# guessed at.
_CASH_ASSETS = frozenset({"usd", "usdc", "cash", "usdc.e"})
_ASSET_FIELDS: tuple[str, ...] = ("asset", "currency", "symbol", "token", "ticker", "denom")


def _as_number(value: Any) -> float | None:
    """A number, including one sent as a string. `True` is not a number.

    Financial APIs commonly serialise amounts as strings to dodge float
    precision, and rejecting those would report `shape_unrecognised` over a
    payload that plainly carries the answer. `isinstance(True, int)` is True in
    Python, so the bool check is load-bearing: a flag named `available` would
    otherwise read as a $1.00 account.
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


def _extract_balance(payload: Any, *, _depth: int = 0) -> tuple[float | None, str | None]:
    """Find a balance-shaped number and say WHICH field it came from.

    Returns `(raw_value, field_name)`, or `(None, None)`.

    Descends into nested objects AND lists, because a `/account/balances`
    endpoint -- plural -- may well answer with one row per asset, and refusing
    that shape would report `shape_unrecognised` over a payload that contains
    the answer. Depth-bounded so a self-referential payload cannot spin.

    A MULTI-ROW LIST IS NOT SUMMED. Adding a USDC row to a points row, or to a
    second venue's, would invent a number nobody can check. Instead the CASH row
    is picked by its own asset label, and if no row identifies itself the answer
    is `(None, None)` -- `shape_unrecognised`, with the keys stamped, which is
    one tick away from correct and never a wrong dollar figure.
    """
    if _depth > 3:
        return None, None

    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
        # One row and no ambiguity: take it.
        if len(rows) == 1:
            found, field = _extract_balance(rows[0], _depth=_depth + 1)
            if found is not None:
                return found, f"[0].{field}"
            return None, None
        # Several rows: the cash one, identified by its own label.
        for index, row in enumerate(rows):
            label = ""
            for name in _ASSET_FIELDS:
                if isinstance(row.get(name), str):
                    label = row[name].strip().lower()
                    break
            if label in _CASH_ASSETS:
                found, field = _extract_balance(row, _depth=_depth + 1)
                if found is not None:
                    return found, f"[{index}:{label}].{field}"
        return None, None

    if not isinstance(payload, dict):
        return None, None

    for field in _BALANCE_FIELDS:
        found = _as_number(payload.get(field))
        if found is not None:
            return found, field
    for key, value in payload.items():
        if not isinstance(value, (dict, list)):
            continue
        nested, field = _extract_balance(value, _depth=_depth + 1)
        if nested is not None:
            return nested, f"{key}.{field}"
    return None, None


def fetch_kalshi_balance() -> dict[str, Any]:
    """One signed read of Kalshi's balance. Never raises."""
    try:
        from syndicate.features.shared.kalshi_auth import (
            KalshiAuthError,
            _base_url,
            load_credentials,
            signed_request,
        )
    except Exception as exc:
        return {"venue": "kalshi", "status": "auth_error", "detail": f"import: {type(exc).__name__}: {exc}"}

    creds = load_credentials()
    if creds.get("status") != "ok":
        return {
            "venue": "kalshi",
            "status": "credentials_absent",
            "detail": creds.get("reason"),
        }

    url = f"{_base_url()}{KALSHI_BALANCE_PATH}"
    try:
        payload = signed_request("GET", url, credentials=creds)
    except KalshiAuthError as exc:
        return {"venue": "kalshi", "status": "auth_error", "detail": str(exc)[:300], "path": KALSHI_BALANCE_PATH}
    except Exception as exc:
        return {"venue": "kalshi", "status": "auth_error", "detail": f"{type(exc).__name__}: {exc}"}

    # THE DOCUMENTED SHAPE, parsed by name (docs.kalshi.com, read 2026-08-26):
    #
    #   balance          int64   available balance in CENTS
    #   balance_dollars  string  the same figure as fixed-point dollars
    #   portfolio_value  int64   cash PLUS open positions, in cents
    #
    # `balance_dollars` is preferred because it is documented as dollars, which
    # turns this module's one remaining unit ASSUMPTION into a stated fact. The
    # cents field is still read and the two are CROSS-CHECKED: if they ever
    # disagree the venue has changed something under us, and that is worth a
    # named state rather than a silently-picked winner.
    cents = _as_number(payload.get("balance"))
    dollars_string = _as_number(payload.get("balance_dollars"))

    if dollars_string is not None:
        dollars, field = dollars_string, "balance_dollars"
    elif cents is not None:
        dollars, field = cents / 100.0, "balance(cents)"
    else:
        # It answered and we do not understand it. Keys, not values.
        return {
            "venue": "kalshi",
            "status": "shape_unrecognised",
            "path": KALSHI_BALANCE_PATH,
            "payload_keys": sorted(payload.keys())[:20],
        }

    disagreement = None
    if dollars_string is not None and cents is not None:
        if abs(dollars_string - cents / 100.0) > 0.01:
            disagreement = {"balance_dollars": dollars_string, "balance_cents": cents}

    portfolio_cents = _as_number(payload.get("portfolio_value"))
    return {
        "venue": "kalshi",
        "status": "ok",
        "path": KALSHI_BALANCE_PATH,
        # SPENDABLE CASH, which is what a day cap should be compared against.
        "dollars": round(dollars, 2),
        # CASH PLUS OPEN POSITIONS. A different question -- "what is the book
        # worth" rather than "what can I deploy" -- and conflating them over a
        # book with open positions overstates what is available by exactly the
        # amount already at risk.
        "portfolio_value_dollars": round(portfolio_cents / 100.0, 2) if portfolio_cents is not None else None,
        "raw_value": cents if cents is not None else dollars,
        "raw_field": field,
        "unit_assumption": "documented",
        # Non-None means the venue's own two representations disagree.
        "unit_disagreement": disagreement,
    }


def fetch_polymarket_balance() -> dict[str, Any]:
    """Polymarket US balance, discovering the path once if it is not pinned.

    Discovery is bounded and read-only: at most one GET per candidate, and only
    while no path has been recorded or configured. A venue that answers 404 to
    all of them yields `path_unknown` -- which is the honest answer and the one
    the page can act on, unlike a zero.
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
        return {"venue": "polymarket", "status": "auth_error", "detail": f"import: {type(exc).__name__}: {exc}"}

    if not credentials_present():
        return {"venue": "polymarket", "status": "credentials_absent"}

    pinned = str(os.environ.get("POLYMARKET_US_BALANCE_PATH") or "").strip()
    recorded = _recorded_polymarket_path()
    candidates = (
        (pinned,)
        if pinned
        else ((recorded,) if recorded else POLYMARKET_BALANCE_PATH_CANDIDATES)
    )

    attempts: list[dict[str, str]] = []
    for path in candidates:
        url = f"{BASE_URL}{_API_PREFIX}{path}"
        try:
            payload = signed_request("GET", url)
        except PolymarketUSAuthError as exc:
            attempts.append({"path": path, "error": str(exc)[:160]})
            # A 401 is about the CREDENTIAL, not the path -- trying three more
            # paths cannot fix it and just spends the venue's patience.
            if "http_401" in str(exc) or "http_403" in str(exc):
                return {
                    "venue": "polymarket",
                    "status": "auth_error",
                    "detail": str(exc)[:300],
                    "attempts": attempts,
                }
            continue
        except Exception as exc:
            attempts.append({"path": path, "error": f"{type(exc).__name__}: {exc}"[:160]})
            continue

        row = _polymarket_cash_row(payload)
        if row is None:
            attempts.append({"path": path, "error": "shape_unrecognised"})
            continue

        # THE DOCUMENTED SHAPE (docs.polymarket.us, read 2026-08-26). Every
        # figure is `number<decimal>` -- DOLLARS, not cents, so nothing is
        # divided here. That was an open assumption until the docs settled it.
        buying_power = _as_number(row.get("buyingPower"))
        current = _as_number(row.get("currentBalance"))
        if buying_power is None and current is None:
            attempts.append({"path": path, "error": "shape_unrecognised"})
            continue

        # BUYING POWER IS THE RIGHT NUMBER FOR A CAP COMPARISON, and it is not
        # the same as the cash balance. The docs define it as "unencumbered
        # capital available for trading, factoring in all security valuations
        # and open orders" -- i.e. what can actually be deployed right now --
        # while `currentBalance` is fiat only, excluding securities. A day cap
        # checked against the latter would look reachable while every dollar
        # sat in resting orders.
        spendable = buying_power if buying_power is not None else current
        return {
            "venue": "polymarket",
            "status": "ok",
            "path": path,
            "dollars": round(spendable, 2),
            "buying_power_dollars": round(buying_power, 2) if buying_power is not None else None,
            "cash_dollars": round(current, 2) if current is not None else None,
            "open_orders_dollars": _round_or_none(_as_number(row.get("openOrders"))),
            "unsettled_dollars": _round_or_none(_as_number(row.get("unsettledFunds"))),
            "currency": row.get("currency"),
            "raw_value": spendable,
            "raw_field": "buyingPower" if buying_power is not None else "currentBalance",
            "unit_assumption": "documented",
        }

    return {"venue": "polymarket", "status": "path_unknown", "attempts": attempts}


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _polymarket_cash_row(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The USD row out of `{"balances": [...]}`, or None.

    PARSED BY NAME AGAINST THE DOCUMENTED SHAPE rather than scanned for
    anything balance-looking, and that is not pedantry here: each row also
    carries `pendingWithdrawals[].balance`, so a generic field scan over a row
    with no top-level match would happily report a PENDING WITHDRAWAL as the
    account balance. The generic scanner remains for genuinely unknown shapes;
    a documented one gets read the way it is documented.

    A single unlabelled row is accepted (an account with one currency is the
    normal case); several rows are resolved by `currency`, and if none of them
    say USD the answer is None -- `shape_unrecognised` -- rather than a guess at
    which pile of money is the spendable one.
    """
    rows = payload.get("balances")
    if not isinstance(rows, list):
        return None
    rows = [row for row in rows if isinstance(row, dict)]
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    for row in rows:
        currency = str(row.get("currency") or "").strip().lower()
        if currency in _CASH_ASSETS:
            return row
    return None


def _recorded_polymarket_path() -> str | None:
    """The path that answered last time, so discovery runs once and not daily."""
    try:
        stamp = read_json_file(balances_path())
    except Exception:
        return None
    if not isinstance(stamp, dict):
        return None
    row = (stamp.get("venues") or {}).get("polymarket")
    if isinstance(row, dict) and row.get("status") == "ok" and row.get("path"):
        return str(row["path"])
    return None


# HOW MANY READINGS THE HISTORY KEEPS. The worker's execution tick is >=5
# minutes apart, so 128 is roughly half a day -- comfortably longer than the
# window between a submit and somebody asking what happened to it, and small
# enough that the file stays trivial next to the ledger.
_BALANCE_HISTORY_LIMIT = 128


def balance_history_path():
    # NO DATE TOKEN, same reason as `balances_path`.
    return reports_root() / "intelligence" / "venue_balance_history.json"


def _history_entry(stamp: Mapping[str, Any]) -> dict[str, Any]:
    """One reading, reduced to what a later question can be asked of it.

    NUMBERS AND STATUS ONLY. A history is for arithmetic across time, and
    carrying the discovered path and unit assumptions on every row would make
    it a log of things that do not change.
    """
    row: dict[str, Any] = {"recorded_at": stamp.get("recorded_at")}
    venues = stamp.get("venues")
    if isinstance(venues, Mapping):
        for venue, reading in venues.items():
            if not isinstance(reading, Mapping):
                continue
            row[str(venue)] = {
                "status": reading.get("status"),
                # `dollars` is the headline number each venue's fetch settled
                # on; the extra two are Polymarket's and are absent elsewhere.
                "dollars": reading.get("dollars"),
                "cash_dollars": reading.get("cash_dollars"),
                "open_orders_dollars": reading.get("open_orders_dollars"),
            }
    return row


def append_balance_history(stamp: Mapping[str, Any]) -> None:
    """Keep a bounded trail of readings. Never raises.

    ----------------------------------------------------------------------
    WHY A SINGLE STAMP WAS NOT ENOUGH
    ----------------------------------------------------------------------

    `balances_path()` is overwritten every tick, so it answers "what is in the
    account now" and cannot answer "did anything leave the account when that
    submit failed" -- which is the only question that settles an order the
    venue never answered.

    MEASURED 2026-08-29, and note HOW it was measured. Order
    `5c53789d4d21d05fc501b05d` took `http_503` with no order id at 21:06:37,
    and Polymarket `buyingPower` read 96.05 at 21:05:56, 21:12:47, 21:18:46 and
    21:25:09, then 94.15 once the retry filled. Flat across the failed submit,
    so **nothing was ever placed** -- $1.84 settled in five numbers.

    Those five numbers existed only because the worker happens to `print` them
    and Render happens to retain logs. Nothing in the artifact layer could have
    answered it, and a human was asked to check a venue screen instead. This
    makes the trail a first-class artifact so the probe can do that arithmetic
    itself.
    """
    try:
        existing = read_json_file(balance_history_path())
    except Exception:
        existing = None
    rows = existing.get("readings") if isinstance(existing, Mapping) else None
    history = [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []
    history.append(dict(_history_entry(stamp)))
    try:
        write_json_file(
            balance_history_path(),
            {"readings": history[-_BALANCE_HISTORY_LIMIT:]},
        )
    except Exception as exc:
        # A NICETY, exactly like the stamp itself. A history that cannot be
        # written must not take down the tick that places orders.
        print(f"[venue_balances] HISTORY_WRITE_FAILED {type(exc).__name__}: {exc}", flush=True)


def read_balance_history() -> list[dict[str, Any]]:
    """Oldest first. An empty list means "no trail", never "nothing moved"."""
    try:
        payload = read_json_file(balance_history_path())
    except Exception:
        return []
    rows = payload.get("readings") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return []
    return [dict(r) for r in rows if isinstance(r, Mapping) and r.get("recorded_at")]


def record_venue_balances(*, recorded_by: str) -> dict[str, Any]:
    """Fetch both venues and stamp the result. **WORKER ONLY.**

    Called from live-odds-worker's execution tick, beside
    `record_execution_state`, so the two readings a person compares -- what the
    caps allow and what the account holds -- are stamped in the same breath and
    cannot be minutes apart from each other.

    Never raises: a balance read is a nicety and must not be able to take down
    the tick that places orders.
    """
    venues: dict[str, Any] = {}
    for venue, fetch in (("kalshi", fetch_kalshi_balance), ("polymarket", fetch_polymarket_balance)):
        try:
            venues[venue] = fetch()
        except Exception as exc:  # defence in depth; each fetch already catches
            venues[venue] = {"venue": venue, "status": "auth_error", "detail": f"{type(exc).__name__}: {exc}"}

    stamp = {"recorded_by": str(recorded_by), "recorded_at": _utc_now(), "venues": venues}
    # BEFORE the stamp write, so a trail exists even on the tick whose stamp
    # write is the thing that fails. `append_balance_history` never raises.
    append_balance_history(stamp)
    try:
        write_json_file(balances_path(), stamp)
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}", **stamp}
    return {"status": "ok", **stamp}


def read_venue_balances() -> dict[str, Any] | None:
    """The worker's stamp, or None if it has never written one.

    None is a real answer -- "the worker has not reported" -- and the caller
    must render it as that rather than as "no money", the same distinction
    `read_execution_state` draws for the switches.
    """
    try:
        stamp = read_json_file(balances_path())
    except Exception:
        return None
    return stamp if isinstance(stamp, dict) and stamp.get("recorded_at") else None
