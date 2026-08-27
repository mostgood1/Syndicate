"""Coinbase "Predict" market data -- THERE IS NO COINBASE MARKET-DATA API.

WHY THIS MODULE LOOKS THE WAY IT DOES. This lane set out to write a
`coinbase_client.py` that mirrors `kalshi_client.py`'s shape: its own base URL,
its own field-name schema, its own `probe()`. Research (WebSearch/WebFetch,
2026-08-24) found that would be fabricating an API that does not exist, so this
module reports the finding instead.

--------------------------------------------------------------------------
THE FINDING: COINBASE PREDICT IS A BROKER LAYER OVER KALSHI'S OWN EXCHANGE
--------------------------------------------------------------------------

"Coinbase Predict" (branded inconsistently -- also "Prediction Markets" in
Coinbase's own help-center URL path) rolled out to all 50 US states in January
2026, built via a **non-exclusive partnership with Kalshi under which Kalshi
supplies every contract and all liquidity at launch**. Coinbase does not run
its own CFTC-registered exchange for this product: trades route through
Coinbase Financial Markets (CFM, an FCM/NFA member) which "layers a broker fee
on top of the existing Kalshi exchange" -- KalshiEX LLC remains the actual
Designated Contract Market that owns the order book.

**Structural evidence, not just a press-release claim:** a live Coinbase
Predict event URL found by research was
`coinbase.com/predictions/event/KXETHD-26AUG2019` -- `KXETHD-...` is Kalshi's
own "KX" series-ticker convention. Coinbase's UI is surfacing Kalshi's own
market identifiers directly, not minting Coinbase-specific contract IDs.

No Coinbase-branded public market-data endpoint was found anywhere -- not on
the Advanced Trade API (`api.coinbase.com`), not in the CDP developer docs. The
one prediction-markets-adjacent field found, `prediction_market_positions` on
the AUTHENTICATED Advanced Trade WebSocket `positions` channel, is a private
your-own-positions field (beta), not a public market listing.

--------------------------------------------------------------------------
WHAT THIS MEANS FOR PULLING COINBASE'S MARKETS/ODDS
--------------------------------------------------------------------------

There is no separate integration to build. The market data Coinbase Predict
shows IS Kalshi's market data. `discover_via_kalshi()` below is a thin,
clearly-labelled pass-through to the other session's `kalshi_client.py`
(read-only functions only -- `fetch_markets`/`discover`, never anything from
`kalshi_auth.py`) so a caller asking "what does Coinbase Predict list" gets an
honest answer instead of a silently-empty fabricated client. **This is NOT
"Coinbase's own catalogue"** -- Coinbase has never confirmed it lists Kalshi's
full catalogue rather than a curated subset, and `venue` is stamped
`"coinbase_predict_via_kalshi"` rather than `"coinbase"` so a caller cannot
mistake one for the other.
"""

from __future__ import annotations

from typing import Any

__all__ = ["FINDING", "discover_via_kalshi", "probe"]

FINDING = {
    "product": "coinbase_predict",
    "status": "no_distinct_api",
    "summary": (
        "Coinbase Predict has no Coinbase-branded public market-data API. "
        "Contracts and liquidity are supplied entirely by Kalshi (KalshiEX LLC) "
        "via a broker relationship through Coinbase Financial Markets; Coinbase's "
        "own UI surfaces Kalshi's KX-prefixed tickers directly."
    ),
    "evidence": [
        "Rolled out to all 50 US states January 2026 via a non-exclusive Kalshi partnership.",
        "Coinbase Financial Markets (FCM/NFA member) layers a broker fee on Kalshi's exchange; "
        "Kalshi (KalshiEX LLC) remains the CFTC-registered DCM.",
        "A live event URL observed: coinbase.com/predictions/event/KXETHD-26AUG2019 -- "
        "'KXETHD-' is Kalshi's own series-ticker convention, not a Coinbase-minted id.",
        "No endpoint found on api.coinbase.com or docs.cdp.coinbase.com for prediction-market "
        "listings; the only related field is an authenticated, beta, positions-only WebSocket key.",
    ],
    "confidence": "moderate-high -- corroborated across independent secondary sources "
    "(CoinDesk, CoinMarketCap Academy, CNBC), but the agent proxy denied direct reads of "
    "coinbase.com/help.coinbase.com, so nothing here was confirmed against Coinbase's own page text.",
    "researched": "2026-08-24",
}


def discover_via_kalshi(*, limit: int = 1000, max_pages: int = 40) -> dict[str, Any]:
    """What Kalshi lists, labelled as the honest answer to "what does Coinbase
    Predict list" -- because that is the same catalogue, per `FINDING`.

    Deliberately imports `kalshi_client` lazily and reads ONLY its public,
    read-only surface (`discover`) -- never `kalshi_auth`, never anything that
    could place an order. That module belongs to another session's lane; this
    function is a caller, not an editor, of it.
    """
    from syndicate.features.shared.kalshi_client import KalshiError, discover

    try:
        report = discover(limit=limit, max_pages=max_pages)
    except KalshiError as exc:
        return {"status": "error", "reason": str(exc), "finding": FINDING}
    report = dict(report)
    report["status"] = "ok"
    report["venue"] = "coinbase_predict_via_kalshi"
    report["finding"] = FINDING
    return report


def probe() -> dict[str, Any]:
    """There is nothing Coinbase-specific to probe. This reports the finding
    plus a pass-through of Kalshi's own `probe()`, so a caller that runs this
    expecting a schema gets the actual answer instead of a wrong one."""
    result: dict[str, Any] = {"finding": FINDING}
    try:
        from syndicate.features.shared.kalshi_client import probe as kalshi_probe

        result["kalshi_probe"] = kalshi_probe()
    except Exception as exc:  # noqa: BLE001 -- a probe must never crash the caller
        result["kalshi_probe"] = {"error": f"{type(exc).__name__}: {exc}"}
    return result
