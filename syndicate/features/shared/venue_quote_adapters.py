"""One adapter per odds source. Each reads an ARTIFACT, never a venue API.

A second independent API caller for one venue is a documented incident class
here -- `#139/#144` did it to MLB, `#148` did it to soccer, the same violation
twice. So every adapter below reads the artifact that venue's own refresh
already wrote. If a venue has no artifact yet, that is a NAMED REFUSAL, never
a fetch bolted on here.

THE UNIT IS DECLARED PER SOURCE, NEVER INFERRED (fan-in rule 5). Kalshi's first
live run corrected a 100x price error that came from assuming a unit matched
another venue's. Each adapter states its own and converts once.
"""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from syndicate.features.shared.venue_quote_fanin import (
    NOVIG_PUBLIC_TIER_REFUSAL,
    Quote,
    SourceOutcome,
)

__all__ = [
    "kalshi_outcome",
    "polymarket_us_outcome",
    "novig_outcome",
    "oddsapi_outcome",
    "probability_to_american",
    "quote_key",
]


def quote_key(sport: str, market: str, side: str, line: float | None) -> str:
    """The join key. Line is part of it: a spread at -1.5 and the same spread
    at -2.5 are different bets, and collapsing them prices one at the other's
    number."""
    line_part = "" if line is None else f"|{float(line):g}"
    return f"{str(sport or '').lower()}|{str(market or '').lower()}|{str(side or '').lower()}{line_part}"


def probability_to_american(probability: float | None) -> int | None:
    """Probability in (0,1) -> American odds. Declared once, used by every
    adapter whose venue quotes probability, so the conversion cannot drift
    between them."""
    try:
        p = float(probability)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0):
        # 0 and 1 are settled markets or a unit error. Both must stop here
        # rather than divide by zero downstream.
        return None
    return int(round(-100.0 * p / (1.0 - p))) if p > 0.5 else int(round(100.0 * (1.0 - p) / p))


def _artifact(path_parts: tuple[str, ...]) -> tuple[Any, float | None]:
    """`(payload, mtime)` or `(None, None)`. mtime is what makes the age real:
    a payload with no file behind it has no defensible freshness."""
    try:
        from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

        path = reports_root().joinpath(*path_parts)
        payload = read_json_file(path)
        try:
            mtime = float(path.stat().st_mtime)
        except Exception:
            mtime = None
        return payload, mtime
    except Exception:
        return None, None


def _fetched_at(payload: Mapping[str, Any] | None, mtime: float | None) -> float | None:
    """Prefer the payload's OWN stamp over the file's mtime.

    An artifact republished unchanged gets a new mtime while its contents are
    hours old -- `PUBLISH_SKIPPED_UNCHANGED` and the artifact-pull sweep both
    touch files this way. Trusting mtime there would launder stale data as
    fresh, which is precisely the failure this module exists to catch.
    """
    for key in ("fetched_at", "generated_at", "last_updated", "as_of"):
        raw = (payload or {}).get(key) if isinstance(payload, Mapping) else None
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw)
        if isinstance(raw, str) and raw.strip():
            parsed = _parse_iso(raw)
            if parsed is not None:
                return parsed
    return mtime


def _parse_iso(text: str) -> float | None:
    import datetime

    try:
        cleaned = str(text).strip().replace("Z", "+00:00")
        parsed = datetime.datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.timestamp()
    except Exception:
        return None


# --------------------------------------------------------------------------
# KALSHI -- quotes DOLLARS-AS-PROBABILITY (a $0.54 contract is p=0.54)
# --------------------------------------------------------------------------


def kalshi_outcome(sport: str, selected_date: str) -> SourceOutcome:
    payload, mtime = _artifact(("intelligence", "kalshi_markets.json"))
    if not isinstance(payload, Mapping):
        return SourceOutcome(source="kalshi", status="error", reason="kalshi_markets.json_unreadable")
    rows = payload.get("markets")
    if not isinstance(rows, list):
        return SourceOutcome(source="kalshi", status="error", reason="markets_key_absent")
    fetched_at = _fetched_at(payload, mtime)
    if fetched_at is None:
        # No defensible age. Refusing beats emitting quotes the freshness gate
        # cannot reason about.
        return SourceOutcome(source="kalshi", status="error", reason="no_fetched_at_or_mtime")

    quotes: list[Quote] = []
    try:
        from syndicate.features.shared.kalshi_catalogue import classify_market
    except Exception as exc:  # noqa: BLE001
        return SourceOutcome(source="kalshi", status="error", reason=f"classify_unavailable: {type(exc).__name__}")

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            classified = classify_market(row)
        except Exception:
            continue
        if not isinstance(classified, Mapping):
            continue
        if str(classified.get("sport") or "").lower() != str(sport or "").lower():
            continue
        market = str(classified.get("market") or "")
        side = str(classified.get("side") or "")
        if not market or not side:
            continue
        probability = _as_float(row.get("yes_bid") or row.get("last_price"))
        if probability is not None and probability > 1.0:
            # Kalshi has quoted CENTS on some routes. 54 is not a probability;
            # converting it as one is the 100x error its first live run found.
            probability = probability / 100.0
        line = _as_float(classified.get("line"))
        quotes.append(
            Quote(
                key=quote_key(sport, market, side, line),
                source="kalshi",
                sport=str(sport or ""),
                market=market,
                side=side,
                probability=probability,
                american=probability_to_american(probability),
                line=line,
                fetched_at=fetched_at,
                venue_ref=str(row.get("ticker") or "") or None,
            )
        )
    return SourceOutcome(
        source="kalshi",
        status="ok" if quotes else "no_rows",
        reason=None if quotes else "no_kalshi_market_classified_to_this_sport",
        quotes=quotes,
        age_seconds=max(0.0, time.time() - fetched_at),
    )


# --------------------------------------------------------------------------
# POLYMARKET US -- quotes PROBABILITY directly (outcomePrices are 0..1)
# --------------------------------------------------------------------------


def polymarket_us_outcome(sport: str, selected_date: str) -> SourceOutcome:
    payload, mtime = _artifact(("intelligence", "polymarket_us_games.json"))
    if not isinstance(payload, Mapping):
        # The catalogue is reachable (7,585 game markets measured 2026-08-24)
        # but nothing persists it yet. A named refusal, not an error: this is a
        # missing writer, and saying so points at the fix.
        return SourceOutcome(
            source="polymarket_us",
            status="refused",
            reason="no_polymarket_us_games_artifact: the slate is reachable via "
                   "polymarket_us_markets.fetch_game_markets but no refresh persists it yet",
        )
    rows = payload.get("markets")
    if not isinstance(rows, list):
        return SourceOutcome(source="polymarket_us", status="error", reason="markets_key_absent")
    fetched_at = _fetched_at(payload, mtime)
    if fetched_at is None:
        return SourceOutcome(source="polymarket_us", status="error", reason="no_fetched_at_or_mtime")

    quotes: list[Quote] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        parsed = _polymarket_sides(row)
        if not parsed:
            continue
        market, sides, line = parsed
        for side, probability in sides:
            quotes.append(
                Quote(
                    key=quote_key(sport, market, side, line),
                    source="polymarket_us",
                    sport=str(sport or ""),
                    market=market,
                    side=side,
                    probability=probability,
                    american=probability_to_american(probability),
                    line=line,
                    fetched_at=fetched_at,
                    venue_ref=str(row.get("slug") or "") or None,
                )
            )
    return SourceOutcome(
        source="polymarket_us",
        status="ok" if quotes else "no_rows",
        reason=None if quotes else "no_polymarket_row_parsed_for_this_sport",
        quotes=quotes,
        age_seconds=max(0.0, time.time() - fetched_at),
    )


def _polymarket_sides(row: Mapping[str, Any]) -> tuple[str, list[tuple[str, float | None]], float | None] | None:
    """`(market, [(side, probability)], line)` from one Polymarket US row.

    `outcomes` and `outcomePrices` arrive as JSON STRINGS
    (`'["Titans","Chargers"]'`), not lists -- measured 2026-08-24. Treating
    them as lists yields no sides at all and reads as "this venue quotes
    nothing", which is the exact confusion rule 3 exists for.
    """
    outcomes = _maybe_json_list(row.get("outcomes"))
    prices = _maybe_json_list(row.get("outcomePrices"))
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None
    market_type = str(row.get("sportsMarketTypeV2") or "").upper()
    market = {
        "SPORTS_MARKET_TYPE_MONEYLINE": "h2h",
        "SPORTS_MARKET_TYPE_SPREAD": "spreads",
        "SPORTS_MARKET_TYPE_TOTAL": "totals",
    }.get(market_type)
    if market is None:
        # PROP and DRAWABLE_OUTCOME are real and joinable, but they need a
        # market mapping this module has not measured. Refusing one row is
        # cheaper than inventing a market name that silently never matches.
        return None
    sides = [(str(name), _as_float(price)) for name, price in zip(outcomes, prices)]
    return market, sides, _as_float(row.get("line"))


def _maybe_json_list(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        return parsed if isinstance(parsed, list) else None
    return None


# --------------------------------------------------------------------------
# NOVIG -- a CAPABILITY GAP, stated rather than left looking broken
# --------------------------------------------------------------------------


def novig_outcome(sport: str, selected_date: str) -> SourceOutcome:
    """Measured 2026-08-24 (`f58905948`): the public CSV mirror is anonymized
    at the game/player/team level. `reportTicker`/`contractSeries` name a
    CATEGORY, never a specific bet, so no amount of freshness makes it price a
    named row. The credentialed REST tier could; nobody has that credential."""
    return SourceOutcome(source="novig", status="refused", reason=NOVIG_PUBLIC_TIER_REFUSAL)


# --------------------------------------------------------------------------
# ODDSAPI -- quotes AMERICAN. One source among venues, switchable.
# --------------------------------------------------------------------------


def oddsapi_outcome(sport: str, selected_date: str) -> SourceOutcome:
    """Reads the odds_history shard the existing pipeline already loads.

    Deliberately NOT privileged. It is one entry in `SOURCES` and one env flag
    away from off, because it being the spine is what let a 13.9-hour quote
    define the board on 2026-08-24.
    """
    try:
        from syndicate.features.shared.odds_control_plane import (
            load_odds_history_payload_for_sport,
        )
    except Exception as exc:  # noqa: BLE001
        return SourceOutcome(source="oddsapi", status="error", reason=f"loader_unavailable: {type(exc).__name__}")

    try:
        payload = load_odds_history_payload_for_sport(str(sport or ""), str(selected_date or ""))
    except Exception as exc:  # noqa: BLE001
        return SourceOutcome(source="oddsapi", status="error", reason=f"{type(exc).__name__}: {exc}")
    if not isinstance(payload, Mapping):
        return SourceOutcome(source="oddsapi", status="no_rows", reason="no_odds_history_shard_for_this_sport_and_date")

    markets = payload.get("markets")
    if not isinstance(markets, Mapping) or not markets:
        return SourceOutcome(source="oddsapi", status="no_rows", reason="shard_has_no_markets")
    fetched_at = _fetched_at(payload, None)
    if fetched_at is None:
        return SourceOutcome(source="oddsapi", status="error", reason="shard_has_no_timestamp")

    quotes: list[Quote] = []
    for market_key, entry in markets.items():
        if not isinstance(entry, Mapping):
            continue
        american = _as_float(entry.get("american") or entry.get("price"))
        quotes.append(
            Quote(
                key=str(market_key),
                source="oddsapi",
                sport=str(sport or ""),
                market=str(entry.get("market") or ""),
                side=str(entry.get("side") or ""),
                probability=_as_float(entry.get("probability")),
                american=int(american) if american is not None else None,
                line=_as_float(entry.get("line")),
                fetched_at=fetched_at,
            )
        )
    return SourceOutcome(
        source="oddsapi",
        status="ok" if quotes else "no_rows",
        reason=None if quotes else "shard_parsed_to_zero_quotes",
        quotes=quotes,
        age_seconds=max(0.0, time.time() - fetched_at),
    )


def _as_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
