"""Pull Polymarket's own catalogue on a cadence, and report what it looks like.

--------------------------------------------------------------------------
WHY THIS IS THE FIRST THING, NOT THE ORDER PATH
--------------------------------------------------------------------------

`paper:polymarket` already reports +21.41% on 14 settled bets. That number is
NOT measured against Polymarket. `venue_scope._venue_price` reads
`book_prices["polymarket"]` off the board row, and those come from the ODDS
FEED's view of the venue -- which `kalshi_client`'s header measures at **1.54%
of a slate**. So the current polymarket book claims an edge at a price nothing
has ever checked against Polymarket's own order book.

That is the same best-of-N fiction the CLV path refuses, wearing a venue name.
Fixing it needs Polymarket's real prices, which needs its catalogue, which
needs a join -- and the join cannot be designed until someone has SEEN the
questions. This module is that step.

--------------------------------------------------------------------------
THE JOIN IS THE HARD PART AND IT CANNOT BE GUESSED
--------------------------------------------------------------------------

Kalshi cost a full day on exactly this. Its market titles were assumed to read
"Will the X win by over N runs?" and actually read "Texas wins by over 3.5
runs?", so `unreadable_title: 302` sat in the log until someone read one. The
date was assumed to be `close_time` and was actually encoded in the event
ticker; `matched=0` for hours because a settlement deadline is days after the
game.

Polymarket is harder, not easier. It has no tickers at all: markets are
free-text `question` strings against ERC-1155 `clobTokenIds`. So this module
deliberately does NOT attempt a join. It fetches, persists, and PRINTS SAMPLES
-- and the sample lines are the deliverable, because they are what the join
gets written from.

--------------------------------------------------------------------------
READ-ONLY, AND STRUCTURALLY SO
--------------------------------------------------------------------------

Gamma `/markets` and CLOB `/price` need no API key, no wallet and no
signature. Nothing in this file can place an order or move a cent, and it
imports nothing that can. Order placement needs an Ethereum private key and
EIP-712 signing, which is a different module, a different credential class,
and a different risk conversation.

Dark by default is therefore NOT the posture here -- there is nothing to arm.
`SYNDICATE_POLYMARKET_ODDS_ENABLED` defaults ON, matching
`kalshi_odds_enabled()` for the same reason: read-only price data, no
credential, nothing tradeable.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "polymarket_odds_enabled",
    "refresh_interval_seconds",
    "markets_artifact_path",
    "run_polymarket_odds_refresh",
]

# Slower than Kalshi's 120s. Kalshi's reads are SIGNED, which is what made two
# minutes affordable; these are anonymous and share whatever quota Polymarket
# applies to unauthenticated callers. Five minutes is enough for a pregame
# board and does not pick a fight with a rate limiter nobody has measured yet.
DEFAULT_REFRESH_INTERVAL_SECONDS = 300
FAILED_RETRY_SECONDS = 900

# How many questions to print per cycle. The whole point of this module is the
# sample, but a catalogue of thousands printed in full is a log nobody reads.
DEFAULT_SAMPLE_SIZE = 12


def polymarket_odds_enabled() -> bool:
    """Default ON. Read-only price data, no credential, nothing tradeable."""
    raw = os.environ.get("SYNDICATE_POLYMARKET_ODDS_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def refresh_interval_seconds() -> int:
    """A bad value falls back to the default, never to 0.

    `int("")` raising into a bare except that returns 0 would turn a typo into
    an unpaced loop against an anonymous quota -- the exact gate
    `kalshi_odds_refresh` documents, and the same trap here.
    """
    raw = os.environ.get("SYNDICATE_POLYMARKET_REFRESH_INTERVAL_SECONDS")
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_INTERVAL_SECONDS
    return parsed if parsed >= 0 else DEFAULT_REFRESH_INTERVAL_SECONDS


def sample_size() -> int:
    raw = os.environ.get("SYNDICATE_POLYMARKET_SAMPLE_SIZE")
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_SAMPLE_SIZE
    return parsed if parsed > 0 else DEFAULT_SAMPLE_SIZE


def markets_artifact_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    # NO DATE TOKEN, matching `kalshi_markets.json`: a date-tokened path takes
    # the keyvalue store's 10-day TTL, and the catalogue must survive a quiet
    # week rather than expire into an empty read that looks like "no markets".
    return reports_root() / "intelligence" / "polymarket_markets.json"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds_since(stamp: Any) -> float | None:
    if not stamp:
        return None
    try:
        parsed = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


# Tokens that suggest a market is about a SPORTS event rather than politics,
# crypto or weather. Deliberately crude and deliberately NOT a filter: it
# classifies the sample so the log says how much of the catalogue is even
# potentially joinable, and a market it misses is still fetched and persisted.
#
# A real classifier is written AFTER reading the sample, not before. Kalshi's
# grammar was written from production titles for exactly this reason.
_SPORT_HINTS = (
    "mlb", "nba", "wnba", "nhl", "nfl", "ncaa", "soccer", "premier league",
    "la liga", "serie a", "bundesliga", "ligue 1", "champions league",
    "world series", "super bowl", "vs.", " vs ", "@",
)


def _looks_sporting(question: Any) -> bool:
    text = str(question or "").lower()
    return any(hint in text for hint in _SPORT_HINTS)


def run_polymarket_odds_refresh(*, force: bool = False) -> dict[str, Any]:
    """Fetch the catalogue, persist it, and report its SHAPE.

    Returns a status payload and never raises: this runs inside the refresh
    loop, and a venue being unreachable must degrade to a named refusal rather
    than take the loop down with it.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    if not polymarket_odds_enabled():
        return {"status": "skipped", "reason": "disabled"}

    path = markets_artifact_path()
    try:
        state = read_json_file(path) or {}
    except Exception:
        # An unreadable artifact is not a reason to refuse the fetch -- it is a
        # reason to replace it. Distinct from the ledger, where an unreadable
        # file MUST refuse, because there the file is the only record of money.
        state = {}

    age = _seconds_since(state.get("fetched_at"))
    interval = refresh_interval_seconds()
    if not force and age is not None and age < interval:
        return {
            "status": "cached",
            "age_seconds": round(age, 1),
            "interval_seconds": interval,
            "count": int(state.get("count") or 0),
        }

    from syndicate.features.shared.polymarket_client import PolymarketError, fetch_markets

    try:
        result = fetch_markets(active=True, closed=False)
    except PolymarketError as exc:
        # NAMED, and the previous catalogue is LEFT IN PLACE. A failed fetch
        # that cleared the artifact would turn "we could not reach Polymarket"
        # into "Polymarket lists nothing", which is the absence/failure
        # confusion this whole layer exists to keep apart.
        print(f"[polymarket_odds] FETCH_FAILED {exc}", flush=True)
        return {"status": "error", "reason": str(exc), "kept": int(state.get("count") or 0)}
    except Exception as exc:
        print(f"[polymarket_odds] FETCH_FAILED {type(exc).__name__}: {exc}", flush=True)
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}

    markets = list(result.get("markets") or [])
    sporting = [m for m in markets if _looks_sporting(m.get("question"))]

    state["markets"] = markets
    state["count"] = len(markets)
    state["fetched_at"] = _now_stamp()
    state["pages"] = result.get("pages")
    state["truncated"] = bool(result.get("truncated"))
    try:
        write_json_file(path, state)
        written = True
    except Exception as exc:
        # Reported, not raised. The fetch succeeded and the caller can still
        # use the result; only the cache is missing.
        print(f"[polymarket_odds] WRITE_FAILED {type(exc).__name__}: {exc}", flush=True)
        written = False

    print(
        f"[polymarket_odds] CATALOGUE count={len(markets)}"
        f" sporting={len(sporting)} pages={result.get('pages')}"
        # TRUNCATED IS LOUD. `fetch_markets` stops at `max_pages`, and a
        # truncated catalogue read as the whole one is how a market we could
        # have traded becomes invisible.
        f" truncated={bool(result.get('truncated'))}"
        f" missing_fields={result.get('missing_fields')}"
        f" decode_errors={result.get('decode_errors')}"
        f" written={written}",
        flush=True,
    )

    # THE ACTUAL DELIVERABLE. Kalshi's join was written from production titles
    # after two wrong guesses; this is that step done first rather than third.
    # Sporting questions preferentially, because those are the only ones a
    # sports board could ever join to.
    # CAMELCASE, VERBATIM FROM GAMMA. `normalize_market` flattens the row but
    # deliberately does not rename anything -- `_MARKET_FIELDS` is the schema
    # assumption in one place, and renaming here would create a second one.
    # Written as `outcome_prices`/`clob_token_ids`/`end_date` first, which
    # would have printed `None` on every line of the one output this module
    # exists to produce.
    for market in (sporting or markets)[: sample_size()]:
        print(
            f"[polymarket_odds] QUESTION {str(market.get('question'))[:110]!r}"
            f" outcomes={market.get('outcomes')}"
            f" prices={market.get('outcomePrices')}"
            f" end={market.get('endDate')}"
            f" book={market.get('enableOrderBook')}"
            f" liq={market.get('liquidity')}"
            f" tokens={str(market.get('clobTokenIds'))[:60]}",
            flush=True,
        )
    if not markets:
        print("[polymarket_odds] EMPTY the catalogue returned no active markets", flush=True)

    return {
        "status": "ok",
        "count": len(markets),
        "sporting": len(sporting),
        "pages": result.get("pages"),
        "truncated": bool(result.get("truncated")),
        "written": written,
    }
