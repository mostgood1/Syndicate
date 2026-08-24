"""ProphetX market data via the documented "Affiliate API" -- PARTNER-GATED,
never a public unauthenticated read.

WHY THIS EXISTS. Same lane as `polymarket_client.py` / `novig_client.py`; see
`.syndicate/scope_2026-08-24_exchange_markets_api_integration.md`.

--------------------------------------------------------------------------
ProphetX SHIPS FOUR APIs. THIS MODULE IMPLEMENTS ONE OF THEM.
--------------------------------------------------------------------------

Research (WebSearch/WebFetch over search-indexed `docs.prophetx.co` snippets --
the agent proxy 403s CONNECT to every ProphetX host, same denial recorded in
`kalshi_client.py`'s header for Kalshi) found ProphetX documents a Trading API
(order placement, real-time odds, wallet -- for algo traders and liquidity
providers), a read-only **Affiliate API** ("for partners looking to display
markets without placing trades" -- the one this module implements), a Parlay
API, and a White-label product. **None of these is self-serve.** Access to even
the read-only Affiliate API requires a partner conversation and a
Novig-style-gated "production affiliate API token" issued by ProphetX -- there
is no anonymous read path, unlike Polymarket's Gamma/CLOB APIs.

--------------------------------------------------------------------------
THE PRODUCTION BASE URL IS UNCONFIRMED. THE SANDBOX ONE IS NOT.
--------------------------------------------------------------------------

`https://api.sandbox.prophetx.dev/partner` appears verbatim, quoted, in
multiple independent research sources. No source gave a production affiliate
host directly -- one older article (pre-rebrand, "Prophet Exchange") names
`cash.api.prophetx.co` for a TRADING endpoint, which may or may not be the same
host the current affiliate API answers on. So `PROPHETX_API_BASE` is a
required override, not a guessed default: shipping a wrong production URL
silently would read as "ProphetX lists nothing" exactly the way a wrong Kalshi
host would have, and there is no live call available from this lane to catch
it (see module-level fetch behaviour below).

--------------------------------------------------------------------------
ODDS ARE AMERICAN, BUT LESS CERTAIN THAN THE FIELD NAMES THEMSELVES
--------------------------------------------------------------------------

The one concrete example payload research found carries `"odds": 119` /
`"display_odds": "+119"` -- unambiguous American-odds notation. A single
secondary source separately claimed ProphetX "converts odds to decimal
format", which reads as a description of THAT AGGREGATOR's own normalized
output rather than ProphetX's raw wire format, and it directly contradicts the
one concrete example found. This module assumes American odds and says so;
`probe()` exists to check it the moment a credential and a confirmed
production host exist.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

__all__ = [
    "american_to_probability",
    "normalize_selection",
    "normalize_market",
    "api_token",
    "fetch_markets",
    "probe",
    "ProphetXError",
]

# The one base URL research confirmed directly (quoted verbatim across
# independent sources). Sandbox only -- see module header on why production
# is not defaulted.
_SANDBOX_BASE = "https://api.sandbox.prophetx.dev/partner"
_GET_MULTIPLE_MARKETS_PATH = "/v4/affiliate/get_multiple_markets"
_GET_MARKETS_PATH = "/v4/affiliate/get_markets"

# RESEARCHED, never called -- one selection object from a documented example
# payload. Same discipline as every other module in this lane: one place, and
# `probe()` diffs it against the real thing on the first live call.
_SELECTION_FIELDS = (
    "outcome_id",
    "name",
    "line_id",
    "line",
    "display_line",
    "odds",
    "display_odds",
    "type",
)


class ProphetXError(RuntimeError):
    """Raised when a fetch cannot be trusted -- never swallowed into an empty list."""


def american_to_probability(odds: Any) -> float | None:
    """American odds -> implied probability. The concrete example payload
    research found (`"odds": 119`) is this convention; see module header for
    the one contradicting secondary claim this module does NOT follow."""
    try:
        value = float(odds)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    return (100.0 / (value + 100.0)) if value > 0 else (abs(value) / (abs(value) + 100.0))


def normalize_selection(raw: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    missing: list[str] = []
    for field in _SELECTION_FIELDS:
        if field in raw:
            out[field] = raw.get(field)
        else:
            out[field] = None
            missing.append(field)
    out["probability"] = american_to_probability(raw.get("odds"))
    out["missing_fields"] = missing
    return out


def normalize_market(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One market row. `selections` is the only nested shape research
    actually found an example of; everything else about the event-level
    object (teams, start time, status) was NOT FOUND by research and is
    passed through verbatim rather than guessed at."""
    selections_raw = raw.get("selections")
    selections = (
        [normalize_selection(s) for s in selections_raw if isinstance(s, Mapping)]
        if isinstance(selections_raw, list)
        else []
    )
    out = dict(raw)
    out["selections"] = selections
    out["selections_present"] = isinstance(selections_raw, list)
    return out


def api_token() -> str | None:
    """The partner-issued affiliate token, or None.

    ProphetX's Affiliate API is founder-gated: there is no signup flow, only a
    token issued after a partner conversation. An absent token here is the
    EXPECTED state until one exists, not a misconfiguration -- same posture
    `novig_client.load_credentials` takes for Novig's OAuth tier.
    """
    return (os.environ.get("PROPHETX_API_TOKEN") or "").strip() or None


def _base_url() -> str:
    """`PROPHETX_API_BASE` overrides; otherwise the sandbox, NEVER a guessed
    production host. See module header -- shipping a wrong production URL
    silently would misreport "ProphetX lists nothing"."""
    override = (os.environ.get("PROPHETX_API_BASE") or "").strip()
    return override or _SANDBOX_BASE


def _get(url: str, *, token: str, timeout: float = 20.0) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "syndicate/1.0",
        "Authorization": f"Bearer {token}",
    }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProphetXError(f"http_{exc.code}: {url}") from exc
    except Exception as exc:
        raise ProphetXError(f"{type(exc).__name__}: {exc}") from exc
    return payload


def fetch_markets(event_ids: list[str] | None = None) -> dict[str, Any]:
    """The affiliate market listing. Refuses by name without a token -- an
    empty list here would be indistinguishable from "ProphetX lists nothing",
    and the actual, near-certain reason is that this lane has no partner
    token yet."""
    token = api_token()
    if not token:
        return {"status": "unavailable", "reason": "no_api_token"}

    base = _base_url()
    if event_ids:
        query = "&".join(f"event_ids={eid}" for eid in event_ids)
        url = f"{base}{_GET_MULTIPLE_MARKETS_PATH}?{query}"
    else:
        url = f"{base}{_GET_MARKETS_PATH}"

    try:
        payload = _get(url, token=token)
    except ProphetXError as exc:
        return {"status": "error", "reason": str(exc), "url": url}

    rows = payload.get("markets") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        return {"status": "error", "reason": f"unexpected_shape: got {type(payload).__name__}", "url": url}

    markets = [normalize_market(m) for m in rows if isinstance(m, Mapping)]
    return {
        "status": "ok",
        "url": url,
        "base_url": base,
        "markets": markets,
        "count": len(markets),
    }


def probe(event_ids: list[str] | None = None) -> dict[str, Any]:
    """Report the shape that ACTUALLY comes back, unparsed -- or a NAMED
    reason no call was attempted. There is no point probing a schema behind
    an auth wall this lane cannot open yet."""
    token = api_token()
    if not token:
        return {"status": "credential_unavailable", "reason": "no_api_token"}

    base = _base_url()
    url = f"{base}{_GET_MARKETS_PATH}"
    try:
        payload = _get(url, token=token)
    except ProphetXError as exc:
        return {"status": "error", "error": str(exc), "url": url}

    rows = payload.get("markets") if isinstance(payload, Mapping) else payload
    sample = None
    if isinstance(rows, list) and rows and isinstance(rows[0], Mapping):
        sample = rows[0]
        sample_selection = sample.get("selections")
        selection_sample = (
            sample_selection[0]
            if isinstance(sample_selection, list) and sample_selection and isinstance(sample_selection[0], Mapping)
            else None
        )
    else:
        selection_sample = None

    return {
        "status": "ok",
        "url": url,
        "base_url": base,
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, Mapping) else None,
        "market_count": len(rows) if isinstance(rows, list) else None,
        "market_keys": sorted(sample.keys()) if sample else None,
        "selection_keys": sorted(selection_sample.keys()) if selection_sample else None,
        "expected_but_absent_in_selection": (
            sorted(set(_SELECTION_FIELDS) - set(selection_sample or {})) if selection_sample else None
        ),
        "sample": sample,
    }
