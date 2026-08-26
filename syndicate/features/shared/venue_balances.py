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
POLYMARKET_BALANCE_PATH_CANDIDATES: tuple[str, ...] = (
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


def _extract_balance(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    """Find a balance-shaped number and say WHICH field it came from.

    Returns `(raw_value, field_name)`, or `(None, None)`. Nested one level,
    because `/portfolio` style endpoints tend to wrap the number in an object
    and refusing those would report `shape_unrecognised` over a payload that
    plainly contains the answer.
    """
    for field in _BALANCE_FIELDS:
        value = payload.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), field
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        nested, field = _extract_balance(value)
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

    raw, field = _extract_balance(payload)
    if raw is None:
        # It answered and we do not understand it. Keys, not values -- enough to
        # fix the constant next time, nothing more.
        return {
            "venue": "kalshi",
            "status": "shape_unrecognised",
            "path": KALSHI_BALANCE_PATH,
            "payload_keys": sorted(payload.keys())[:20],
        }
    return {
        "venue": "kalshi",
        "status": "ok",
        "path": KALSHI_BALANCE_PATH,
        "dollars": round(raw / 100.0, 2) if KALSHI_BALANCE_IS_CENTS else round(raw, 2),
        # BOTH stamped, so a unit error is correctable from the artifact alone.
        "raw_value": raw,
        "raw_field": field,
        "unit_assumption": "cents" if KALSHI_BALANCE_IS_CENTS else "dollars",
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

        raw, field = _extract_balance(payload)
        if raw is None:
            attempts.append({"path": path, "error": "shape_unrecognised"})
            continue
        return {
            "venue": "polymarket",
            "status": "ok",
            "path": path,
            # NO UNIT DIVISION. Kalshi documents cents; this venue documents
            # nothing we have read, so dividing by 100 here would be inventing
            # a fact. `raw_value` and `raw_field` are stamped and the first live
            # run decides -- the same discipline that caught the 100x error
            # rather than shipping it.
            "dollars": round(raw, 2),
            "raw_value": raw,
            "raw_field": field,
            "unit_assumption": "dollars_unverified",
            "payload_keys": sorted(payload.keys())[:20],
        }

    return {"venue": "polymarket", "status": "path_unknown", "attempts": attempts}


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
