"""Novig market data -- one PUBLIC path, one CREDENTIAL-GATED path, and one
path this module deliberately does NOT implement.

WHY THIS EXISTS. Same lane as `polymarket_client.py` and
`.syndicate/scope_2026-08-24_exchange_markets_api_integration.md`: pull
markets/odds for six venues ahead of the order-automation phase another
session is building for Kalshi.

--------------------------------------------------------------------------
THREE TIERS OF ACCESS, RESEARCHED (not called -- see below), AND KEPT DISTINCT
--------------------------------------------------------------------------

Research (WebSearch/WebFetch, triangulated across ~15 independent third-party
repos that reference `docs.novig.com` -- the agent proxy 403s CONNECT to both
`docs.novig.com` and `api.novig.us`, same denial `kalshi_client.py`'s header
records for Kalshi) found Novig exposes THREE structurally different things,
and conflating any two of them would misrepresent what this module can
actually do:

1. **`data.novig.com` -- genuinely public, no auth, CDN-served daily CSV
   dumps** (`trades.csv`, `markets.csv`). This is END-OF-DAY / historical tape,
   not a live quote. `fetch_daily_csv()` implements THIS tier -- it is the one
   thing in this module runnable today with no credential and no ToS question.
2. **The official "NBX API"** (`docs.novig.com`, REST under
   `api.novig.us/nbx/v1|v2`, OAuth2 client-credentials) -- Novig's own
   documented, versioned, supported API. Confirmed by multiple independent
   sources to be **founder-gated**: credentials are requested directly from
   Novig, not self-serve. `fetch_open_markets()` implements THIS tier and
   REFUSES BY NAME (`no_credential`) without `NOVIG_CLIENT_ID` /
   `NOVIG_CLIENT_SECRET` -- it does not fall back to anything else.
3. **An undocumented, unauthenticated Hasura GraphQL backend**
   (`api.novig.us/v1/graphql`) that several independent third-party scrapers
   use by reverse-engineering Novig's own consumer app. **Deliberately NOT
   implemented here.** It is not published, not supported, can change without
   notice, and its terms-of-service status for third-party read access is
   explicitly unclear in every source that mentions it. Building durable
   Syndicate infrastructure on an app-internal endpoint we were not given is a
   different kind of risk than an unverified-but-documented schema, and this
   module does not take it. If Novig ever documents or grants access to this
   surface, it belongs in tier 2, not smuggled in as tier 1.

--------------------------------------------------------------------------
PRICES ARE PROBABILITY, NOT AMERICAN ODDS -- BUT LESS CERTAIN THAN KALSHI'S
--------------------------------------------------------------------------

Two independent third-party sources describe Novig's outcome `last` /
`available` fields identically: **de-vigged probabilities** (over + under =~
1.0), not American or decimal odds. That is what `probability_to_american`
below assumes. Unlike Kalshi's dollars-as-probability convention (verified
against a live response) this is corroborated-but-unread -- `probe()` exists
so the first live call checks it rather than assuming it.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

__all__ = [
    "probability_to_american",
    "normalize_market",
    "load_credentials",
    "fetch_open_markets",
    "fetch_daily_csv",
    "probe",
    "NovigError",
]

# Tier 2: the official, documented, OAuth-gated REST API.
_API_BASE = "https://api.novig.us/nbx/v2"
_TOKEN_URL = "https://api.novig.us/nbx/v1/auth/emm-token"
_MARKETS_PATH = "/emm/markets/open"

# Tier 1: the genuinely public, no-auth CSV mirror. Historical/EOD, not live.
_DAILY_CSV_BASE = "https://data.novig.com"

# The fields this module reads off a market/outcome row -- RESEARCHED from
# convergent third-party repos referencing Novig's own GraphQL schema, never
# read from a live response. `kalshi_client`'s first live run corrected 10 of
# 17 field names written the identical way; treat this list with the same
# suspicion until `probe()` runs from a host that can reach Novig.
_MARKET_FIELDS = (
    "id",
    "league",
    "type",
    "status",
    "scheduled_start",
    "market_type",
    "is_consensus",
    "strike",
)
_OUTCOME_FIELDS = ("type", "last", "available")


class NovigError(RuntimeError):
    """Raised when a fetch cannot be trusted -- never swallowed into an empty list."""


def probability_to_american(probability: float | None) -> int | None:
    """De-vigged probability -> American odds. See module header for the
    convention this assumes and how confident that assumption is."""
    if probability is None:
        return None
    if not (0.0 < probability < 1.0):
        return None
    if probability >= 0.5:
        return int(round(-100.0 * probability / (1.0 - probability)))
    return int(round(100.0 * (1.0 - probability) / probability))


def _as_probability(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or not (0.0 < parsed < 1.0):
        return None
    return parsed


def normalize_market(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One market row, flattened, outcomes normalized. Missing fields are None
    and COUNTED -- same contract as `kalshi_client.normalize_market`."""
    out: dict[str, Any] = {}
    missing: list[str] = []
    for field in _MARKET_FIELDS:
        if field in raw:
            out[field] = raw.get(field)
        else:
            out[field] = None
            missing.append(field)

    outcomes_raw = raw.get("outcomes")
    outcomes: list[dict[str, Any]] = []
    if isinstance(outcomes_raw, list):
        for row in outcomes_raw:
            if not isinstance(row, Mapping):
                continue
            probability = _as_probability(row.get("last") if row.get("last") is not None else row.get("available"))
            entry: dict[str, Any] = {}
            outcome_missing: list[str] = []
            for field in _OUTCOME_FIELDS:
                if field in row:
                    entry[field] = row.get(field)
                else:
                    entry[field] = None
                    outcome_missing.append(field)
            entry["probability"] = probability
            entry["american"] = probability_to_american(probability)
            entry["missing_fields"] = outcome_missing
            outcomes.append(entry)
    else:
        missing.append("outcomes")

    out["outcomes"] = outcomes
    out["missing_fields"] = missing
    return out


def load_credentials() -> dict[str, Any]:
    """The OAuth client-credentials pair, or a NAMED reason there isn't one.

    Founder-gated per every source that describes tier 2 -- there is no
    self-serve signup, so an absent credential here is the EXPECTED state
    until Novig issues one, not a misconfiguration.
    """
    client_id = (os.environ.get("NOVIG_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("NOVIG_CLIENT_SECRET") or "").strip()
    if not client_id:
        return {"status": "unavailable", "reason": "no_client_id"}
    if not client_secret:
        return {"status": "unavailable", "reason": "no_client_secret"}
    return {"status": "ok", "client_id": client_id, "client_secret": client_secret}


def _get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0) -> Any:
    request_headers = {"Accept": "application/json", "User-Agent": "syndicate/1.0"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise NovigError(f"http_{exc.code}: {url}") from exc
    except Exception as exc:
        raise NovigError(f"{type(exc).__name__}: {exc}") from exc
    return body


def _fetch_token(creds: dict[str, Any], *, timeout: float = 20.0) -> str:
    """OAuth2 client-credentials exchange. Tokens expire every ~30 min per
    documentation research -- never cached across calls in this module; the
    caller decides caching policy."""
    body = json.dumps(
        {
            "grant_type": "client_credentials",
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "syndicate/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise NovigError(f"token_http_{exc.code}") from exc
    except Exception as exc:
        raise NovigError(f"token_{type(exc).__name__}: {exc}") from exc
    token = payload.get("access_token") if isinstance(payload, Mapping) else None
    if not token:
        raise NovigError("token_response_missing_access_token")
    return str(token)


def fetch_open_markets(*, league: str | None = None, market_type: str = "MONEY") -> dict[str, Any]:
    """Tier 2: the official, credential-gated REST listing.

    Refuses by name (`no_client_id` / `no_client_secret`) rather than
    returning an empty list -- an empty list here would be indistinguishable
    from "Novig lists nothing", and the actual, much more common reason is
    that this lane has no partner credential yet.
    """
    creds = load_credentials()
    if creds.get("status") != "ok":
        return {"status": "unavailable", "reason": creds.get("reason")}

    try:
        token = _fetch_token(creds)
    except NovigError as exc:
        return {"status": "error", "reason": str(exc)}

    query = f"marketType={market_type}"
    if league:
        query += f"&league={league}"
    url = f"{_API_BASE}{_MARKETS_PATH}?{query}"
    try:
        raw_body = _get(url, headers={"Authorization": f"Bearer {token}"})
        payload = json.loads(raw_body.decode("utf-8"))
    except NovigError as exc:
        return {"status": "error", "reason": str(exc), "url": url}
    except (ValueError, UnicodeDecodeError) as exc:
        return {"status": "error", "reason": f"undecodable_response: {exc}", "url": url}

    rows = payload.get("markets") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        return {
            "status": "error",
            "reason": f"unexpected_shape: got {type(payload).__name__}",
            "url": url,
        }

    markets = [normalize_market(m) for m in rows if isinstance(m, Mapping)]
    missing_counts: dict[str, int] = {}
    for market in markets:
        for field in market.get("missing_fields") or ():
            missing_counts[field] = missing_counts.get(field, 0) + 1

    return {
        "status": "ok",
        "url": url,
        "league": league,
        "market_type": market_type,
        "markets": markets,
        "count": len(markets),
        "missing_fields": dict(sorted(missing_counts.items())),
    }


def fetch_daily_csv(name: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Tier 1: the genuinely public, no-auth daily CSV mirror.

    `name` is `"trades"` or `"markets"` -- the two dumps research found
    documented at `docs.novig.com/api-reference/trade-data`. This is
    END-OF-DAY tape, never a live quote; a caller wanting current prices needs
    tier 2, credentials or not. Runnable today, unlike `fetch_open_markets`.
    """
    key = str(name or "").strip().lower()
    if key not in ("trades", "markets"):
        return {"status": "error", "reason": "invalid_name", "name": name}
    url = f"{_DAILY_CSV_BASE}/{key}.csv"
    try:
        raw_body = _get(url, headers={"Accept": "text/csv"}, timeout=timeout)
    except NovigError as exc:
        return {"status": "error", "reason": str(exc), "url": url}
    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"status": "error", "reason": f"undecodable_response: {exc}", "url": url}
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return {
        "status": "ok",
        "url": url,
        "name": key,
        "count": len(rows),
        "columns": reader.fieldnames or [],
        "rows": rows,
    }


def probe(*, league: str | None = None) -> dict[str, Any]:
    """Report the shape that ACTUALLY comes back for both tiers, unparsed.

    Tier 2 reports `credential_unavailable` rather than attempting a call when
    no credential is configured -- there is no point probing a schema behind
    an auth wall this lane cannot open yet. Tier 1 always attempts a call: it
    needs no credential and is the one thing this module can verify today.
    """
    result: dict[str, Any] = {"checked_at": time.time()}

    creds = load_credentials()
    if creds.get("status") != "ok":
        result["tier2_official_rest"] = {"status": "credential_unavailable", "reason": creds.get("reason")}
    else:
        try:
            token = _fetch_token(creds)
            query = f"marketType=MONEY" + (f"&league={league}" if league else "")
            url = f"{_API_BASE}{_MARKETS_PATH}?{query}"
            raw_body = _get(url, headers={"Authorization": f"Bearer {token}"})
            payload = json.loads(raw_body.decode("utf-8"))
            rows = payload.get("markets") if isinstance(payload, Mapping) else payload
            sample = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], Mapping) else None
            result["tier2_official_rest"] = {
                "status": "ok",
                "url": url,
                "top_level_keys": sorted(payload.keys()) if isinstance(payload, Mapping) else None,
                "market_keys": sorted(sample.keys()) if sample else None,
                "expected_but_absent": sorted(set(_MARKET_FIELDS) - set(sample or {})),
                "present_but_unexpected": sorted(set(sample or {}) - set(_MARKET_FIELDS)),
                "sample": sample,
            }
        except Exception as exc:  # noqa: BLE001 -- a probe must never crash the caller
            result["tier2_official_rest"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    csv_result = fetch_daily_csv("markets")
    if csv_result.get("status") == "ok":
        result["tier1_daily_csv"] = {
            "status": "ok",
            "url": csv_result.get("url"),
            "columns": csv_result.get("columns"),
            "count": csv_result.get("count"),
            "sample_row": csv_result.get("rows", [None])[0],
        }
    else:
        result["tier1_daily_csv"] = csv_result

    return result
