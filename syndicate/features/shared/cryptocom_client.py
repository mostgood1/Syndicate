"""OG.com prediction-market data (the platform the user calls "Crypto.com
OG") -- NO PUBLIC REST/WEBSOCKET API HAS SHIPPED AS OF THIS RESEARCH.

WHY THIS MODULE LOOKS THE WAY IT DOES. Same lane as `coinbase_client.py` /
`robinhood_client.py`. Unlike those two, research did NOT find that this
venue's data is available via a known, already-built other client -- OG.com is
its own platform with its own (not-yet-public) API, so this module's `probe()`
does something the Coinbase/Robinhood ones don't: it actually ATTEMPTS a live
check of the one candidate endpoint research surfaced, rather than only
reporting a finding, because "coming soon" is a moving target and the honest
way to track it moving is to keep checking rather than to re-research it.

--------------------------------------------------------------------------
THE FINDING: "OG" IS OG.COM, A SEPARATELY-BRANDED SPINOUT, NOT A CODENAME
--------------------------------------------------------------------------

**"OG" = OG.com**, a standalone US prediction-market/event-contracts platform
Crypto.com spun out and launched 2026-02-03 (timed before the Super Bowl),
citing "40x weekly growth" in Crypto.com's prior in-app prediction-market
activity as the reason. It is regulated/operated through **Crypto.com
Derivatives North America (CDNA)**, a CFTC-registered DCM/DCO -- multiple
sources tie CDNA back to Nadex (Crypto.com's earlier US-regulated-exchange
acquisition), i.e. CDNA reads as the renamed/successor entity to Nadex's DCM/DCO
registrations. Live in production since launch; a Trading Technologies (TT)
institutional-connectivity partnership is targeted for Q4 2026 but is about
order routing, not public read-only market data.

**Distinct from** Crypto.com's older/international "Predict" feature (an
earlier, non-US-regulated, in-app product) -- research could not fully confirm
the boundary between the two, flagged as unresolved below.

--------------------------------------------------------------------------
API STATUS: "COMING SOON", ONE UNCORROBORATED THIRD-PARTY ENDPOINT REJECTED
--------------------------------------------------------------------------

Independent review sites (multiple, 2026 vintage) state OG.com has not
published a public developer API. A search-indexed snippet attributed to
Crypto.com's own Exchange API page (`crypto.com/exchange-pro/en-US/api`)
describes a Predictions section with **DCM** and **FCM** entries: REST =
"coming soon", WebSocket = "coming soon", **FIX = available**. FIX is an
institutional binary protocol, not something this module implements -- it is
not a public HTTP read.

One third-party marketing site (not Crypto.com-owned) advertised a specific
endpoint, `GET /api/v1/predictions/events?kind=COMPANIES`. **Deliberately NOT
implemented here.** It is uncorroborated by any Crypto.com-owned source, reads
oddly for a sports/politics/finance product ("kind=COMPANIES"), and building
against an unverified third-party guess at someone else's schema is exactly
the failure mode this lane's whole discipline exists to avoid -- see
`kalshi_client.py`'s header on what an untested schema assumption cost there.

`probe()` checks the ONE thing that IS a real, Crypto.com-owned candidate: the
Exchange API's predictions section itself, in case "coming soon" has shipped
since this research.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

__all__ = ["FINDING", "probe", "CryptocomError"]

FINDING = {
    "product": "og_dot_com_prediction_markets",
    "status": "no_public_api_yet",
    "summary": (
        "OG.com is a real, live, CFTC-regulated (via CDNA) prediction-market platform "
        "Crypto.com spun out 2026-02-03. No public REST/WebSocket market-data API has "
        "shipped -- Crypto.com's own Exchange API page reportedly lists Predictions "
        "REST/WebSocket as 'coming soon', with only FIX (an institutional protocol) "
        "currently available."
    ),
    "evidence": [
        "Launched 2026-02-03, timed before the Super Bowl, citing 40x weekly growth in "
        "Crypto.com's prior in-app prediction-market activity.",
        "Regulated through Crypto.com Derivatives North America (CDNA), a CFTC-registered "
        "DCM/DCO tied to the earlier Nadex acquisition.",
        "Trading Technologies institutional-connectivity partnership targeted Q4 2026 -- "
        "order routing, not public read-only data.",
        "Multiple independent 2026 review sites state no public developer API exists at launch.",
        "crypto.com/exchange-pro/en-US/api reportedly lists a Predictions section: "
        "DCM/FCM entries, REST 'coming soon', WebSocket 'coming soon', FIX available.",
    ],
    "rejected_source": (
        "A third-party marketing site advertised GET /api/v1/predictions/events?kind=COMPANIES. "
        "NOT implemented -- uncorroborated by any Crypto.com-owned source and the query shape "
        "reads as unrelated to a sports/politics/finance event-contract product."
    ),
    "open_question": (
        "Whether OG.com is the same system as Crypto.com's older, non-US-regulated in-app "
        "'Predict' feature or a genuinely separate one -- research could not resolve this."
    ),
    "confidence": "moderate -- corroborated across ~6 independent outlets for the spinout/CDNA "
    "facts, lower confidence on the 'coming soon' API claim (search-snippet only, the agent "
    "proxy denied a direct read of crypto.com's own API page).",
    "researched": "2026-08-24",
}

# The one Crypto.com-owned candidate host research surfaced for predictions
# market data. NOT a market-listing endpoint -- an API landing page. probe()
# reads it to see whether "coming soon" is still true, nothing more.
_CANDIDATE_API_LANDING = "https://crypto.com/exchange-pro/en-US/api"


class CryptocomError(RuntimeError):
    """Raised when a check cannot be trusted."""


def probe(*, timeout: float = 20.0) -> dict[str, Any]:
    """Check the one real candidate host, report what comes back, change
    nothing about `FINDING` based on the result -- a page fetch cannot itself
    confirm a REST market-data endpoint exists, only that the landing page
    responded. A future session finding this returning HTML that mentions a
    live REST path is the actual "unblocked" signal, not this function's
    return value alone.
    """
    result: dict[str, Any] = {"finding": FINDING, "checked_url": _CANDIDATE_API_LANDING}
    request = urllib.request.Request(
        _CANDIDATE_API_LANDING,
        headers={"Accept": "text/html,application/json", "User-Agent": "syndicate/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        result["status"] = "error"
        result["error"] = f"http_{exc.code}"
        return result
    except Exception as exc:
        # Network denial included -- the agent proxy 403s CONNECT for this
        # host, so a local run fails here and that is expected, not a fault.
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["status"] = "ok"
    result["http_status"] = status
    result["byte_length"] = len(body)
    try:
        payload = json.loads(body.decode("utf-8"))
        result["decoded_json"] = True
        result["json_keys"] = sorted(payload.keys()) if isinstance(payload, dict) else None
    except (ValueError, UnicodeDecodeError):
        result["decoded_json"] = False
        # A cheap, bounded signal without parsing HTML: whether "coming soon"
        # still appears near "predictions" in the raw page text.
        text_lower = body.decode("utf-8", errors="ignore").lower()
        result["mentions_predictions"] = "prediction" in text_lower
        result["mentions_coming_soon"] = "coming soon" in text_lower
    return result
