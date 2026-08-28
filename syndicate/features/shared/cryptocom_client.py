"""Crypto.com Predictions market data -- NO SANCTIONED, SERVER-READABLE API.

WHY THIS MODULE LOOKS THE WAY IT DOES. Same lane as `coinbase_client.py` /
`robinhood_client.py`. Unlike those two, this venue's data is NOT available via
a known, already-built other client -- it is its own platform with its own
(undocumented) surface. So `probe()` does something the Coinbase/Robinhood ones
don't: it actually ATTEMPTS a live check, because "coming soon" is a moving
target and the honest way to track it moving is to keep checking.

--------------------------------------------------------------------------
THIS FILE WAS REWRITTEN 2026-08-28 AND THE CORRECTIONS ARE THE POINT
--------------------------------------------------------------------------

The 2026-08-24 version of this module was written from a cloud sandbox whose
agent proxy 403s CONNECT to `crypto.com`. It reasoned about a page it could not
read, and it got three things wrong -- all three in the direction of
UNDERSTATING what exists, which is the direction that makes a future session
stop looking:

  1. It said the endpoint `GET /api/v1/predictions/events?kind=COMPANIES` came
     from "a third-party marketing site" and was "uncorroborated by any
     Crypto.com-owned source". **It is printed on Crypto.com's own API page**,
     in the hero terminal sample, under the comment `# Predictions - market
     data`. The third party was quoting them. The DECISION not to build against
     it was right; the REASON recorded for it was false, and a false reason is
     worse than none -- it reads as a closed question.
  2. It said "no public REST/WebSocket market-data API has shipped". **A JSON
     endpoint serving sports events exists and was read live** (see
     `_APP_PROXY_EVENTS_URL` below). It is undocumented, Cloudflare-gated and
     carries no prices -- which is a much more specific and more useful fact
     than "nothing shipped".
  3. It treated "sports" as unnamed. Sports is a HEADLINE category of the
     product: MLB/soccer/football/basketball/hockey and more, priced in dollars
     of probability against a $1 settlement, CFTC-regulated via CDNA. Reading
     `crypto.com/exchange-pro`'s "crypto, politics and economics" as a
     statement about the VENUE was the error; it is a statement about the
     DCM/FCM institutional feed only.

Full evidence, with every reading and its timestamp:
`.syndicate/findings_2026-08-28_cryptocom_venue_evaluation.md`.

--------------------------------------------------------------------------
THE GATE IS EGRESS, NOT EXISTENCE -- AND THAT IS WHAT `probe()` NOW TESTS
--------------------------------------------------------------------------

The old `probe()` fetched the marketing page and reported whether its text
still said "coming soon", and its docstring named "HTML that mentions a live
REST path" as the unblock signal. **That signal would fire today and be
wrong, twice over:** the page says "REST API - Available" in its Predictions
showcase while its own coverage table two sections earlier says "REST - Coming
soon", and no host serves the path either statement refers to.

So `probe()` no longer lets any page's PROSE decide anything. It reads the two
surfaces that can actually be true or false, and it reports `unblocked` -- which
defaults to False and can only be flipped by a positive, named signal from a
SANCTIONED endpoint. `learnings.md`'s standing rule applies directly: unknown
must not default permissive.

  * `_EXCHANGE_INSTRUMENTS_URL` -- the documented, public, unauthenticated
    catalogue. Measured 2026-08-28: 957 instruments, `inst_type` in
    {CCY_PAIR 578, PERPETUAL_SWAP 367, FUTURE 12}, **zero event contracts**.
    An event contract appearing here IS the unblock signal, because this
    endpoint answers a plain server-side GET -- the thing a Render worker can
    actually do.
  * `_APP_PROXY_EVENTS_URL` -- the consumer web app's own internal proxy. This
    is where the sports data lives. It is checked so its status is RECORDED,
    never so it can unblock anything: measured 2026-08-28 it returns 200 JSON
    to a real browser carrying a Cloudflare `cf_clearance` cookie and **403
    Cloudflare HTML to a plain client, with or without full browser headers**.

**WHY A 403 HERE IS THE WHOLE ANSWER AND NOT A DETAIL.** Kalshi's
`api.elections.kalshi.com` and Polymarket's `gamma-api`/`clob` all answer a
plain server-side GET (verified 2026-08-26,
`.syndicate/findings_2026-08-26_venue_api_unblock.md`). Our workers fetch with
`urllib.request`. A venue that serves JSON only to a challenged browser session
hands them HTML where JSON was expected -- and a fetcher returning HTML is
`kalshi_client`'s founding failure mode: an empty result indistinguishable from
a venue that lists nothing.

**DO NOT "FIX" THIS BY DRIVING A BROWSER.** It works -- every measurement above
came out of one -- and it must not ship: the proxy is the app's private BFF with
no contract or versioning (unknown paths return `Invalid proxy path or method`),
the prices are not even in it (they are server-rendered into the page's RSC
payload; the only price JSON is a two-point sparkline), it defeats a bot control
on someone else's site, and a Chromium process does not fit a worker that
reboots on every deploy. The unblock path is the "Get Prediction Markets Data"
contact form, which is a business decision, not a code task.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

__all__ = [
    "FINDING",
    "probe",
    "CryptocomError",
    "CRYPTO_DERIVATIVE_INSTRUMENT_TYPES",
]

FINDING = {
    "product": "cryptocom_predictions_sports_event_contracts",
    # NOT "no_public_api_yet" -- that was the 2026-08-24 wording and it is
    # falsified. An endpoint exists; it is the ACCESS that is unavailable, and
    # the two send a future session to completely different places.
    "status": "no_sanctioned_server_readable_api",
    "summary": (
        "Crypto.com Predictions is a real, live, CFTC-regulated (via CDNA) sports "
        "event-contract venue, priced in dollars of probability against a $1 settlement "
        "-- the same unit convention as Kalshi. Its sports market data IS served as JSON, "
        "but only by the consumer web app's own undocumented internal proxy, which is "
        "Cloudflare-gated (200 to a challenged browser session, 403 to any plain client) "
        "and carries no prices. The documented institutional surface (Exchange REST) lists "
        "zero event contracts. There is no server-readable, sanctioned path to this venue's "
        "prices, so it cannot be integrated; the unblock is a commercial conversation, "
        "not code."
    ),
    "measured_2026_08_28": [
        "PRODUCT IS REAL AND DEEP: web.crypto.com lists Baseball, Soccer, Football, Golf, "
        "Basketball, Tennis, Esports, Motorsports, Fighting, Sailing, Hockey. Read live: "
        "'Boston @ New York Y', Yankee Stadium, BOS $0.42 / NYY $0.59 (sum 1.01, ~1pt vig). "
        "One MLB game carried cumulative_traded_usd 1370106.22.",
        "UNITS MATCH KALSHI: '$1 return per contract if your prediction is correct', so a "
        "price in dollars IS the probability -- kalshi_client's dollars_to_probability / "
        "dollars_to_american would port unchanged.",
        "A JSON SPORTS ENDPOINT EXISTS: GET .../predictions/public/api/v1/events?limit=200 "
        "-> 200, 200 MLB rows, 41 fields (id, event_kind, event_kind_asset_type='sports', "
        "event_type match 173 / league 27, title, event_date, venue, game_status, slug, "
        "close_date, cumulative_traded_usd). 46 of 200 future-dated.",
        "IT CARRIES NO PRICES: no bid, ask, size or contract list. Prices are server-rendered "
        "into the detail page's Next.js RSC payload; the only price JSON is a per-symbol "
        "sparkline (.../predictions/charts?symbol=...&timeframe=all) which returned TWO "
        "points for timeframe 'all'.",
        "ITS FILTERS ARE SILENTLY IGNORED: ?kind=SPORTS and ?kind=COMPANIES returned "
        "byte-identical 15,922-byte MLB payloads. Only `limit` is honoured, and its own "
        "error text disagreed with itself ('between 1 and 2' then 'between 1 and 20') while "
        "limit=200 served 200 rows.",
        "THE PROXY IS AN ALLOWLIST: markets, contracts, orderbook, quotes, tickers, "
        "instruments, leagues, categories all -> 403 "
        "{'code':-1,'message':'Invalid proxy path or method'}. There is no undiscovered "
        "price path; the surface is exactly what the app happens to call.",
        "CLOUDFLARE IS THE BLOCKER: the same events endpoint returned 200 JSON to a real "
        "browser session and 403 Cloudflare HTML to curl BOTH plain AND with full Chrome "
        "UA / Accept / Accept-Language / Referer / sec-ch-ua / sec-fetch-* headers.",
        "EXCHANGE REST HAS NO EVENT CONTRACTS: api.crypto.com/exchange/v1/public/"
        "get-instruments -> 200, 530,758 bytes, 957 instruments, inst_type CCY_PAIR 578 / "
        "PERPETUAL_SWAP 367 / FUTURE 12, zero event contracts, and no event/outcome/"
        "resolution field in the row schema.",
        "THE DOCUMENTED SAMPLE PATH HAS NO HOST: api.crypto.com/api/v1/predictions/events"
        "?kind=COMPANIES -> 404 {'code':'10004','msg':'BAD_REQUEST'}; predictions.crypto.com "
        "and api.predictions.crypto.com do not resolve; exchange-docs.crypto.com is a "
        "167-byte JS shell with zero occurrences of 'prediction'.",
        "THE API PAGE CONTRADICTS ITSELF: its coverage table says DCM/FCM Predictions REST "
        "'Coming soon', WebSocket 'Coming soon', FIX 'Available'; its Predictions showcase "
        "~400 words later says 'REST API - Available, WebSocket - Coming soon'. Same page, "
        "same load. Do not resolve this by picking the favourable one.",
    ],
    "corrected_source": (
        "SUPERSEDES the 2026-08-24 `rejected_source`, which said "
        "GET /api/v1/predictions/events?kind=COMPANIES came from 'a third-party marketing "
        "site' and was 'uncorroborated by any Crypto.com-owned source'. It is printed on "
        "crypto.com/exchange-pro/en-US/api itself, in the hero terminal sample, with an "
        "example row {'id':'8741d85d-...','title':'OpenAI IPO Date','kind':'COMPANIES',"
        "'type':'league','status':'active','contracts_count':2}. Still NOT implemented -- "
        "no host answers it (see measured_2026_08_28) -- but the reason is 'documented and "
        "dead', not 'invented by a stranger'. The example row is also evidence the "
        "DCM/FCM feed is not a sports surface: kind COMPANIES, title an IPO date."
    ),
    "coverage_caveat": (
        "The MLB game page offered 'Winner' only -- two contracts "
        "(MLB-...-M-RedSox-O11, MLB-...-M-Yankees-O12). No spread, total or player prop was "
        "observed at game level. This platform's board is h2h PLUS spreads, totals and props, "
        "so even with perfect access the joinable surface may be moneyline-shaped. NOT fully "
        "surveyed -- flagged, not concluded."
    ),
    "open_question": (
        "How Crypto.com Predictions (web.crypto.com, CDNA), the older non-US in-app 'Predict' "
        "feature, and the spun-out OG.com relate. Unresolved 2026-08-24 and still unresolved: "
        "og.com serves 200 but exposes no API host or /api path in its SSR HTML. This matters "
        "before any build, not after -- Polymarket needed TWO modules for two exchanges under "
        "one brand because an account funded on one is not funded on the other, and pricing "
        "off the wrong book does not fail, it produces plausible edges against prices that do "
        "not exist where the order lands (polymarket_us_markets.py's header)."
    ),
    "confidence": (
        "HIGH on everything in measured_2026_08_28 -- read live from a local machine with "
        "full egress, not researched. The 2026-08-24 version of this finding was written from "
        "a sandbox whose proxy 403s CONNECT to crypto.com and could not read the page it was "
        "reasoning about; three of its claims are corrected above. Remaining low confidence "
        "is confined to `open_question` and `coverage_caveat`."
    ),
    "researched": "2026-08-24",
    "measured": "2026-08-28",
}

# The documented, public, unauthenticated Exchange catalogue. This is the
# SANCTIONED surface and the only one `probe()` lets flip `unblocked`, because
# it is the only one a worker can read with `urllib.request`.
_EXCHANGE_INSTRUMENTS_URL = "https://api.crypto.com/exchange/v1/public/get-instruments"

# The consumer app's own internal proxy -- where the sports data actually is.
# Checked so its status is RECORDED, never so it can unblock anything.
_APP_PROXY_EVENTS_URL = (
    "https://web.crypto.com/api/proxy/public/knock-out/predictions"
    "/public/api/v1/events?limit=20"
)

# What the Exchange catalogue held on 2026-08-28, all 957 rows. An `inst_type`
# OUTSIDE this set is the signal that something other than a crypto derivative
# has been listed -- named as a constant so the assumption is in ONE place and a
# future session can see exactly what it is being compared against.
CRYPTO_DERIVATIVE_INSTRUMENT_TYPES: frozenset[str] = frozenset(
    {"CCY_PAIR", "PERPETUAL_SWAP", "FUTURE"}
)

_USER_AGENT = "syndicate/1.0"


class CryptocomError(RuntimeError):
    """Raised when a check cannot be trusted."""


def _get(url: str, *, timeout: float) -> dict[str, Any]:
    """One GET, reported rather than parsed. Never raises for a network or
    HTTP failure -- the caller needs the failure IN the report, because "this
    host refused us" is the finding here, not an obstacle to it.
    """
    out: dict[str, Any] = {"url": url}
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json, text/html", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            out["http_status"] = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        out["status"] = "error"
        out["error"] = f"http_{exc.code}"
        return out
    except Exception as exc:
        out["status"] = "error"
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    out["status"] = "ok"
    out["byte_length"] = len(body)
    try:
        out["json"] = json.loads(body.decode("utf-8"))
        out["decoded_json"] = True
    except (ValueError, UnicodeDecodeError):
        out["decoded_json"] = False
        # A body that is HTML where JSON was expected is the Cloudflare
        # signature and is reported BY NAME. This is the exact confusion
        # `kalshi_client` exists to prevent: HTML parsed as "no markets" is
        # indistinguishable from a venue that lists nothing.
        text = body.decode("utf-8", errors="ignore").lower()
        out["looks_like_html"] = "<html" in text or "<!doctype html" in text
        out["looks_like_bot_challenge"] = (
            "cloudflare" in text or "attention required" in text
        )
    return out


def _summarize_instruments(payload: Any) -> dict[str, Any]:
    """Count the catalogue by `inst_type` and report anything that is not a
    crypto derivative BY NAME.

    Counted over the rows themselves, never grepped for a keyword -- a name
    match would call an event contract a crypto pair the moment either side
    renames, and this is the one number `unblocked` is allowed to turn on.
    """
    report: dict[str, Any] = {"instrument_count": 0, "by_inst_type": {}, "non_crypto": []}
    if not isinstance(payload, dict):
        report["error"] = "payload_not_an_object"
        return report
    result = payload.get("result")
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        # NOT an empty catalogue -- an unrecognised shape. Reported as such,
        # because "zero instruments" and "we cannot read this" must never
        # arrive at the caller looking the same.
        report["error"] = "no_result_data_list"
        return report

    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        inst_type = str(row.get("inst_type") or "").strip().upper()
        counts[inst_type or "(missing)"] = counts.get(inst_type or "(missing)", 0) + 1
        if inst_type and inst_type not in CRYPTO_DERIVATIVE_INSTRUMENT_TYPES:
            report["non_crypto"].append(
                {"inst_type": inst_type, "symbol": row.get("symbol")}
            )
    report["instrument_count"] = len(rows)
    report["by_inst_type"] = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    report["non_crypto_count"] = len(report["non_crypto"])
    return report


def probe(*, timeout: float = 20.0) -> dict[str, Any]:
    """Is there a SANCTIONED, SERVER-READABLE market-data surface yet?

    Returns `unblocked` -- False unless the documented Exchange catalogue,
    fetched with a plain server-side client, lists at least one instrument that
    is not a crypto derivative. Nothing else can flip it: not the marketing
    page's prose (which contradicts itself), and not the app proxy (which a
    worker cannot read).

    **`unblocked=True` is a signal to LOOK, not a green light.** It means the
    sanctioned catalogue started carrying something new. A human still has to
    confirm the rows are sports contracts AND carry a price before anything is
    built -- `_summarize_instruments` reports the new rows by `inst_type` and
    `symbol` for exactly that read.

    Both checks are always performed and always reported, including their
    failures. `status` is `error` only when EVERY check failed, so a probe run
    from a network that cannot reach the venue at all is distinguishable from
    one where the venue answered and the answer was "no".
    """
    exchange = _get(_EXCHANGE_INSTRUMENTS_URL, timeout=timeout)
    app_proxy = _get(_APP_PROXY_EVENTS_URL, timeout=timeout)

    result: dict[str, Any] = {
        "finding": FINDING,
        "checks": {"exchange_rest": exchange, "app_proxy": app_proxy},
        "unblocked": False,
        "blocked_reason": None,
    }

    if exchange.get("status") == "ok" and exchange.get("decoded_json"):
        instruments = _summarize_instruments(exchange.get("json"))
        # The raw payload is large and is not what a reader needs; the counts
        # are. Dropped AFTER summarizing so nothing here parses it twice.
        exchange.pop("json", None)
        exchange["instruments"] = instruments
        if instruments.get("error"):
            result["blocked_reason"] = f"exchange_rest_unreadable:{instruments['error']}"
        elif instruments.get("non_crypto_count"):
            result["unblocked"] = True
            result["blocked_reason"] = None
        else:
            result["blocked_reason"] = "exchange_rest_lists_no_event_contracts"
    else:
        exchange.pop("json", None)
        result["blocked_reason"] = (
            f"exchange_rest_unreachable:{exchange.get('error') or 'not_json'}"
        )

    # Recorded, never load-bearing. A 403 here is the EXPECTED reading and is
    # the single most important fact about this venue -- see the module header.
    if app_proxy.get("status") == "error":
        app_proxy["interpretation"] = f"unreadable_server_side:{app_proxy.get('error')}"
    elif app_proxy.get("looks_like_bot_challenge"):
        app_proxy["interpretation"] = "bot_challenge_html_not_json"
    elif app_proxy.get("decoded_json"):
        # Would be new: a plain client got JSON out of the app proxy. Still does
        # NOT unblock -- an undocumented private BFF is not an integration
        # surface no matter who can reach it -- but it is worth surfacing loudly.
        app_proxy["interpretation"] = "unexpected_server_side_json_investigate"
    else:
        app_proxy["interpretation"] = "non_json_body"
    app_proxy.pop("json", None)

    every_check_failed = all(
        check.get("status") == "error" for check in result["checks"].values()
    )
    result["status"] = "error" if every_check_failed else "ok"
    if every_check_failed:
        # Preserve the flat `error` key the probe scripts and their tests read.
        result["error"] = exchange.get("error")
        result["blocked_reason"] = "no_check_reached_the_venue"
    return result
