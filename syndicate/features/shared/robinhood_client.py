"""Robinhood event-contract market data -- THERE IS NO ROBINHOOD MARKET-DATA
API, OFFICIAL OR UNOFFICIAL.

WHY THIS MODULE LOOKS THE WAY IT DOES. Same lane as `coinbase_client.py`, and
the finding is even more clear-cut: Robinhood's historical pattern (no
official public API for equities or options either) holds for event contracts
too, and research found no reverse-engineered one either -- most sources
report event contracts are viewable ONLY in the mobile app, with no order-book
visibility exposed even to a logged-in user on web.

--------------------------------------------------------------------------
THE FINDING: ROBINHOOD IS A DISTRIBUTION FRONT END OVER OTHER VENUES' DCMs
--------------------------------------------------------------------------

Robinhood's "Event Contracts" run through Robinhood Derivatives, LLC (a
CFTC-registered FCM) as a front end over contracts actually listed and cleared
by THIRD-PARTY Designated Contract Markets:

- **KalshiEX LLC** -- the original and still-primary partner (integration
  since Oct 2024; full "Prediction Markets Hub" launch March 2025).
- **ForecastEx, LLC** -- used for some contract types (e.g. early presidential
  election contracts before the Kalshi hub launched).
- **Rothera Exchange and Clearing LLC** -- new as of ~Q1 2026. Robinhood and
  Susquehanna International Group jointly acquired MIAXdx (an existing
  CFTC-licensed DCM/DCO) and renamed it Rothera; reporting on the June 2026
  World Cup describes Robinhood actively shifting volume onto this
  self-controlled venue and away from Kalshi.

For the KalshiEX-sourced share of the catalogue, the underlying market data
genuinely lives on Kalshi's own API (same relationship `coinbase_client.py`
documents for Coinbase Predict). No evidence was found that Rothera or
ForecastEx expose a public API of their own.

--------------------------------------------------------------------------
WHAT THIS MEANS FOR PULLING ROBINHOOD'S MARKETS/ODDS
--------------------------------------------------------------------------

There is no Robinhood-specific fetch to build. `discover_via_kalshi()` below
is the same honest pass-through pattern `coinbase_client.py` uses: it answers
"what does Robinhood's Kalshi-sourced catalogue look like" via the other
session's `kalshi_client.py` (read-only surface only), clearly labelled so it
is never mistaken for Robinhood's own data -- and it is explicitly INCOMPLETE,
because the ForecastEx- and Rothera-sourced share of Robinhood's catalogue has
no known public source at all, unlike Coinbase Predict where Kalshi supplies
the whole thing.
"""

from __future__ import annotations

from typing import Any

__all__ = ["FINDING", "discover_via_kalshi", "probe"]

FINDING = {
    "product": "robinhood_event_contracts",
    "status": "no_public_api",
    "summary": (
        "Robinhood has no public market-data API for event contracts -- official "
        "or reverse-engineered -- consistent with its historical stance on equities "
        "and options. Contracts are sourced from three third-party CFTC DCMs: "
        "KalshiEX (primary), ForecastEx, and the newly acquired Rothera (ex-MIAXdx)."
    ),
    "evidence": [
        "No official developer API for event contracts found; the only official API "
        "(trading.robinhood.com Crypto Trading API) is scoped strictly to crypto pairs.",
        "Existing unofficial/reverse-engineered Robinhood API tooling targets equities, "
        "options, and crypto -- none of it documents event-contract endpoints.",
        "One source states event contracts are viewable only in the mobile app, with no "
        "order-book visibility exposed even to logged-in web users.",
        "Robinhood + Susquehanna jointly acquired MIAXdx, renamed Rothera, and reporting "
        "(Bloomberg, 2026-06-04) describes shifting World Cup volume there from Kalshi.",
    ],
    "confidence": "moderate-high -- corroborated across many independent sources for the "
    "'no public API' claim, but the agent proxy denied direct reads of robinhood.com and the "
    "newsroom pages, so nothing here was confirmed against Robinhood's own page text.",
    "coverage_caveat": (
        "Only the KalshiEX-sourced share of Robinhood's catalogue has a known public source "
        "(Kalshi's own API). ForecastEx- and Rothera-sourced contracts have NO known public "
        "market-data path at all -- discover_via_kalshi() cannot see them and does not claim to."
    ),
    "researched": "2026-08-24",
}


def discover_via_kalshi(*, limit: int = 1000, max_pages: int = 40) -> dict[str, Any]:
    """The KalshiEX-sourced SLICE of what Robinhood shows -- not the whole
    catalogue. See `FINDING["coverage_caveat"]`.

    Same pattern as `coinbase_client.discover_via_kalshi`: reads only
    `kalshi_client`'s public, read-only surface, never `kalshi_auth`.
    """
    from syndicate.features.shared.kalshi_client import KalshiError, discover

    try:
        report = discover(limit=limit, max_pages=max_pages)
    except KalshiError as exc:
        return {"status": "error", "reason": str(exc), "finding": FINDING}
    report = dict(report)
    report["status"] = "ok"
    report["venue"] = "robinhood_event_contracts_via_kalshi_partial"
    report["finding"] = FINDING
    return report


def probe() -> dict[str, Any]:
    """There is no Robinhood-specific endpoint to probe. Reports the finding
    plus a pass-through of Kalshi's own `probe()` for the partial slice this
    module CAN see."""
    result: dict[str, Any] = {"finding": FINDING}
    try:
        from syndicate.features.shared.kalshi_client import probe as kalshi_probe

        result["kalshi_probe"] = kalshi_probe()
    except Exception as exc:  # noqa: BLE001 -- a probe must never crash the caller
        result["kalshi_probe"] = {"error": f"{type(exc).__name__}: {exc}"}
    return result
