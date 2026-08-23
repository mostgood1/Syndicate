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
    "join_kalshi_to_board",
    "kalshi_price_resolver",
]

# "Andrew Abbott: 7+ strikeouts?" / "Andrew Abbott: 17+ Outs Recorded?"
_PROP_TITLE = re.compile(
    r"^\s*(?P<player>[^:]+?)\s*:\s*(?P<threshold>\d+)\s*\+\s*(?P<stat>.+?)\s*\??\s*$"
)

# THE CATALOGUE'S NAMES, re-exported rather than restated. Two modules with
# their own spelling of the same refusal is how a log line and a test end up
# disagreeing about what happened.
from syndicate.features.shared.kalshi_catalogue import (  # noqa: E402
    REASON_COMBINATORIAL,
    REASON_OUT_OF_SCOPE,
    REASON_UNMAPPED_SERIES,
    REASON_UNMAPPED_STAT,
    REASON_UNREADABLE_TITLE,
)

REASON_WRONG_DATE = "market_closes_on_another_date"
# Split out from the above: this one means the player, market and line all
# matched a board row and ONLY the date disagreed. Same refusal, opposite
# diagnosis -- one says Kalshi is quoting a slate we are not looking at, the
# other says our date field is wrong.
REASON_WOULD_MATCH_WRONG_DATE = "would_match_but_wrong_date"
REASON_NO_BOARD_ROW = "no_matching_board_row"
REASON_NO_PRICE = "no_kalshi_price"
# A market whose title does not say which game it is. Distinct from every other
# refusal: these are markets we CAN read and CANNOT yet place, so the number is
# the size of the game-lines gap rather than a defect.
REASON_NEEDS_EVENT_MAPPING = "needs_event_mapping"


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


def _board_key(row: Mapping[str, Any]) -> tuple[str, str, float] | None:
    """The board row's identity, in the CANONICAL market vocabulary.

    Canonicalised here rather than matched against a list of aliases, because
    `market_keys` already knows that `pitcher_strikeouts` and `strikeouts` are
    the same market (`#224`). Both sides of the join therefore speak one
    vocabulary and the aliases live in the module that owns them -- an alias
    tuple in this file was a second place for the two to drift apart, which is
    the whole failure this join exists to avoid.

    Falls back to the raw name when the vocabulary does not know it: an
    unrecognised market keys on itself rather than being dropped, so a market we
    have no entry for can still match one Kalshi spells identically.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    raw = str(row.get("market") or "").strip().lower()
    market = canonical_market_key(row.get("sport"), raw) or raw
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


def _classify(market):
    from syndicate.features.shared.kalshi_catalogue import classify_market

    return classify_market(market)


def join_kalshi_to_board(
    kalshi_markets: Sequence[Mapping[str, Any]],
    board_rows: Sequence[Mapping[str, Any]],
    *,
    selected_date: str | None = None,
) -> dict[str, Any]:
    """Pair each Kalshi market with the board row for the same bet.

    Returns matches plus a named reason for every market that did not pair, so
    "Kalshi has nothing we bet" and "our join is broken" can never share a
    number -- which is the failure mode that produced `#505`.

    **`selected_date` KEEPS THE JOIN INSIDE ONE SLATE.** Kalshi's open markets
    span several days ahead; the board is built for one date. Measured
    2026-08-23T04:22Z: Kalshi was quoting tomorrow's MLB while the board had
    rolled to European soccer, so the join saw 132 markets and 421 rows with
    nothing in common -- correct, but only by luck of the vocabularies not
    overlapping. A starting pitcher with the same strikeout line on two
    different days WOULD have matched the wrong game and been priced
    confidently. Same class as `clv_join`'s arrow-of-time check: a pairing that
    looks well-formed and joins two unrelated instants.

    Absent, the check is skipped rather than guessed at -- a caller that does
    not know the slate date should get the old behaviour, not a silent filter.
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

    wanted_date = str(selected_date or "").strip()[:10]
    for market in kalshi_markets:
        # THE CATALOGUE DECIDES WHAT THIS MARKET IS, for every sport at once.
        # This used to be a two-entry series table plus a private title parser,
        # which is a mapping that works for two series and stops at three.
        verdict = _classify(market)
        if verdict.get("status") != "ok":
            _refuse(str(verdict.get("reason")))
            continue

        if verdict.get("needs_event_identity"):
            # A player prop names a human, and a human plays one game a day, so
            # (player, market, line) is a complete identity. A total names
            # neither team -- pairing it needs `event_ticker` mapped to our
            # event id, which does not exist yet. REFUSED rather than attempted:
            # a total joined to the wrong game is a confidently-priced bet on
            # strangers.
            _refuse(REASON_NEEDS_EVENT_MAPPING)
            continue

        series = verdict.get("series")
        board_market = verdict["market"]
        line = verdict["line"]
        player_key = normalize_person(verdict.get("subject"))
        parsed = {"player_name": verdict.get("subject"), "player_key": player_key}
        rows = by_key.get((board_market, player_key, line))

        # THE DATE CHECK RUNS AFTER THE KEY LOOKUP, not before it. Ordering it
        # first is cheaper and it is what this module shipped with -- and it
        # cost a whole diagnostic cycle: `market_closes_on_another_date: 213`
        # swallowed every market before anything could report whether the NAMES
        # agreed, so one wrong assumption hid another. Refusing late means one
        # run answers both questions: `would_match_but_wrong_date` says the key
        # is right and only the calendar disagrees, while `no_matching_board_row`
        # says the key is still wrong.
        if wanted_date:
            # `close_time` compared on the DATE only -- a night game closes
            # after midnight UTC (`#370`). Whether `close_time` is first pitch
            # at all is UNVERIFIED; see `kalshi_odds_refresh`'s DATE_FIELDS.
            close_date = str(market.get("close_time") or "")[:10]
            if close_date and close_date != wanted_date:
                _refuse(REASON_WOULD_MATCH_WRONG_DATE if rows else REASON_WRONG_DATE)
                continue

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
        verdict = _classify(market)
        if verdict.get("status") != "ok":
            continue
        # Built by the SAME code path the join uses, so the sample cannot say
        # one thing while the join does another -- which would make this line
        # actively misleading rather than merely unhelpful.
        kalshi_keys.append(
            f"{verdict['market']}|{normalize_person(verdict.get('subject'))}|{verdict['line']}"
        )
        if len(kalshi_keys) >= 6:
            break
    board_keys = [f"{k[0]}|{k[1]}|{k[2]}" for k in list(by_key)[:5]]
    # The board's market vocabulary, counted -- if the market the catalogue
    # resolved is not in it, the mapping is simply wrong and that is visible at
    # a glance.
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
