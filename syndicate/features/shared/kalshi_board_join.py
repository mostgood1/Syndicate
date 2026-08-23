"""Match a Kalshi market to a board row -- the join Stage D actually needs.

WHY THIS IS THE HARD PART. Kalshi and the board describe the same bet in two
unrelated vocabularies:

    Kalshi  ticker KXMLBKS-..., title "Andrew Abbott: 7+ strikeouts?",
            YES/NO, price in dollars
    board   market `pitcher_strikeouts`, player_name "Andrew Abbott",
            line 6.5, side Over/Under, price in American odds

Nothing lines up automatically, and `#505` is what a wrong join costs: the
settlement path matched on an id that changed whenever the price moved and
reported **4,560 `no_key_match` of 8,276**. So every mapping here is explicit,
every failure is named, and nothing is inferred from a pattern that merely
looks right.

--------------------------------------------------------------------------
"7+" IS OVER 6.5, AND OFF-BY-A-HALF WOULD MISMATCH EVERY SINGLE LINE
--------------------------------------------------------------------------

Kalshi states a threshold as "at least N". YES on "7+ strikeouts" pays when the
pitcher records 7 or more. The board states the same bet as a half-point line:
Over 6.5 pays at 7 or more. So

    Kalshi YES at threshold N  ==  board Over  (N - 0.5)
    Kalshi NO  at threshold N  ==  board Under (N - 0.5)

Matching "7+" against a line of 7.0 would find nothing, and -- worse -- matching
it against Over 7.5 would find a DIFFERENT BET and price it confidently. This is
the same shape as the cents/dollars error the probe caught: a convention
mismatch that produces plausible numbers rather than an obvious failure.

--------------------------------------------------------------------------
SIDES ARE NOT SYMMETRIC AND ARE NOT DERIVED FROM EACH OTHER
--------------------------------------------------------------------------

`yes_ask_dollars` and `no_ask_dollars` are separately quoted; they do not sum to
1 (the gap is the spread). Each board side is matched to its OWN Kalshi side and
priced from that side's ask -- deriving the Under from the Over's price would
erase the spread and invent an edge that is not there.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "normalize_person",
    "parse_prop_title",
    "series_to_market",
    "threshold_to_line",
    "join_kalshi_to_board",
    "kalshi_price_resolver",
]

# Kalshi series -> the board's market vocabulary. VERIFIED from the live
# listing 2026-08-23; both map onto families the sim already models and that
# `bet_status_mlb` can resolve a live value for.
_SERIES_TO_MARKET: dict[str, str] = {
    "KXMLBKS": "pitcher_strikeouts",
    "KXMLBOUTS": "pitcher_outs",
}

# "Andrew Abbott: 7+ strikeouts?" / "Andrew Abbott: 17+ Outs Recorded?"
_PROP_TITLE = re.compile(
    r"^\s*(?P<player>[^:]+?)\s*:\s*(?P<threshold>\d+)\s*\+\s*(?P<stat>.+?)\s*\??\s*$"
)

REASON_UNPARSEABLE_TITLE = "unparseable_title"
REASON_UNMAPPED_SERIES = "unmapped_series"
REASON_NO_BOARD_ROW = "no_matching_board_row"
REASON_NO_PRICE = "no_kalshi_price"


def normalize_person(value: Any) -> str:
    """Same normalisation MLB's own name matching uses (accents folded, cased
    down, whitespace collapsed) rather than a third private variant -- two
    normalisers that disagree on one name is a silent mismatch nobody sees."""
    text = " ".join(str(value or "").strip().lower().split())
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    # Punctuation varies between feeds ("Jr.", "O'Neill"); drop it rather than
    # let a period decide whether a bet matches.
    return re.sub(r"[^a-z0-9 ]", "", stripped).strip()


def parse_prop_title(title: Any) -> dict[str, Any] | None:
    """`"Andrew Abbott: 7+ strikeouts?"` -> player, threshold, stat text.

    Returns None rather than a partial parse: a title this cannot read is a
    market we must not guess at, and a half-parsed player name would match the
    wrong human -- `learnings.md`'s "worse at any stake than no bet".
    """
    match = _PROP_TITLE.match(str(title or ""))
    if not match:
        return None
    try:
        threshold = int(match.group("threshold"))
    except (TypeError, ValueError):
        return None
    player = match.group("player").strip()
    if not player:
        return None
    return {
        "player_name": player,
        "player_key": normalize_person(player),
        "threshold": threshold,
        "stat_text": match.group("stat").strip(),
    }


def series_to_market(series: Any) -> str | None:
    """Explicit table, never a prefix rule. An unknown series is refused."""
    return _SERIES_TO_MARKET.get(str(series or "").strip().upper())


def threshold_to_line(threshold: Any) -> float | None:
    """Kalshi "N+" -> the board's half-point line. 7+ -> 6.5.

    The single most mismatch-prone number in this module. See the module
    docstring: matching 7+ against a line of 7.0 finds nothing, and matching it
    against 7.5 finds a different bet and prices it confidently.
    """
    try:
        value = int(threshold)
    except (TypeError, ValueError):
        return None
    return float(value) - 0.5


def _board_key(row: Mapping[str, Any]) -> tuple[str, str, float] | None:
    market = str(row.get("market") or "").strip().lower()
    player = normalize_person(row.get("player_name"))
    try:
        line = float(row.get("line"))
    except (TypeError, ValueError):
        return None
    if not market or not player:
        return None
    return (market, player, line)


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def kalshi_price_resolver(matches: Sequence[Mapping[str, Any]]):
    """A resolver `venue_scope` can price from: board row -> Kalshi's own price.

    THE SEAM THAT MAKES PAPER2 REAL. Until now paper2 priced Kalshi from
    `quote.book_prices["kalshi"]`, which is OddsAPI's view -- game lines only,
    and the reason every coverage figure in this thread was about the aggregator
    rather than the venue. This prices from what Kalshi is actually quoting.

    Keyed on (market, player, line, side): the same identity the join matched
    on, so a resolver cannot pair a row with a price for a different bet. A
    lookup that is looser than the join would silently reintroduce exactly the
    mismatches the join refuses.
    """
    index: dict[tuple[str, str, float, str], float] = {}
    for match in matches:
        try:
            line = float(match.get("line"))
        except (TypeError, ValueError):
            continue
        price = match.get("kalshi_american")
        if price is None:
            continue
        key = (
            str(match.get("market") or "").strip().lower(),
            normalize_person(match.get("player_name")),
            line,
            str(match.get("board_side") or "").strip().lower(),
        )
        index[key] = float(price)

    def resolve(row: Mapping[str, Any]) -> float | None:
        try:
            line = float(row.get("line"))
        except (TypeError, ValueError):
            return None
        return index.get(
            (
                str(row.get("market") or "").strip().lower(),
                normalize_person(row.get("player_name")),
                line,
                str(row.get("side") or "").strip().lower(),
            )
        )

    resolve.market_count = len(index)  # type: ignore[attr-defined]
    return resolve


def join_kalshi_to_board(
    kalshi_markets: Sequence[Mapping[str, Any]],
    board_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Pair each Kalshi market with the board row for the same bet.

    Returns matches plus a named reason for every market that did not pair, so
    "Kalshi has nothing we bet" and "our join is broken" can never share a
    number -- which is the failure mode that produced `#505`.
    """
    by_key: dict[tuple[str, str, float], list[Mapping[str, Any]]] = {}
    for row in board_rows:
        key = _board_key(row)
        if key is not None:
            by_key.setdefault(key, []).append(row)

    matches: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}

    def _refuse(reason: str) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1

    for market in kalshi_markets:
        series = market.get("series")
        board_market = series_to_market(series)
        if board_market is None:
            _refuse(REASON_UNMAPPED_SERIES)
            continue
        parsed = parse_prop_title(market.get("title"))
        if parsed is None:
            _refuse(REASON_UNPARSEABLE_TITLE)
            continue
        line = threshold_to_line(parsed["threshold"])
        if line is None:
            _refuse(REASON_UNPARSEABLE_TITLE)
            continue

        rows = by_key.get((board_market, parsed["player_key"], line))
        if not rows:
            _refuse(REASON_NO_BOARD_ROW)
            continue

        yes_price = _as_float(market.get("yes_american"))
        no_price = _as_float(market.get("no_american"))
        if yes_price is None and no_price is None:
            _refuse(REASON_NO_PRICE)
            continue

        for row in rows:
            side = str(row.get("side") or "").strip().lower()
            # EACH SIDE FROM ITS OWN QUOTE. See the module docstring -- deriving
            # one from the other erases the spread and invents edge.
            if side in {"over", "o"}:
                kalshi_price = yes_price
                kalshi_side = "yes"
            elif side in {"under", "u"}:
                kalshi_price = no_price
                kalshi_side = "no"
            else:
                _refuse("unmapped_board_side")
                continue
            if kalshi_price is None:
                _refuse(REASON_NO_PRICE)
                continue
            matches.append(
                {
                    "ticker": market.get("ticker"),
                    "series": series,
                    "market": board_market,
                    "player_name": parsed["player_name"],
                    "line": line,
                    "board_side": side,
                    "kalshi_side": kalshi_side,
                    "kalshi_american": kalshi_price,
                    "kalshi_probability": market.get(
                        "yes_probability" if kalshi_side == "yes" else "no_probability"
                    ),
                    "board_price": row.get("quote", {}).get("price")
                    if isinstance(row.get("quote"), Mapping)
                    else None,
                    "board_event_id": row.get("event_id"),
                    "model_edge_pct": row.get("model_edge_pct"),
                }
            )

    # SAMPLES FROM BOTH SIDES, so a zero-match join says WHICH FIELD disagrees.
    # `no_matching_board_row: 132` alone is exactly the `#505` report -- a count
    # of failures with no way to see the mismatch. Keys from each side side by
    # side is what turns that into a fixable observation.
    kalshi_keys: list[str] = []
    for market in kalshi_markets:
        board_market = series_to_market(market.get("series"))
        parsed = parse_prop_title(market.get("title"))
        if board_market and parsed:
            line = threshold_to_line(parsed["threshold"])
            kalshi_keys.append(f"{board_market}|{parsed['player_key']}|{line}")
        if len(kalshi_keys) >= 5:
            break
    board_keys = [f"{k[0]}|{k[1]}|{k[2]}" for k in list(by_key)[:5]]
    # The board's market vocabulary, counted -- if `pitcher_strikeouts` is not
    # in it, the mapping table is simply wrong and that is visible at a glance.
    board_markets: dict[str, int] = {}
    for row in board_rows:
        name = str(row.get("market") or "").strip().lower()
        if name:
            board_markets[name] = board_markets.get(name, 0) + 1

    return {
        "kalshi_markets": len(kalshi_markets),
        "board_rows": len(board_rows),
        "matched": len(matches),
        "reasons": dict(sorted(reasons.items())),
        "kalshi_key_sample": kalshi_keys,
        "board_key_sample": board_keys,
        "board_market_vocabulary": dict(
            sorted(board_markets.items(), key=lambda kv: -kv[1])[:12]
        ),
        "matches": matches,
    }
