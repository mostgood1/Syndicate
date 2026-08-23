"""Which Kalshi series are which sport, and what bet each market actually is.

THE PIECE THAT MAKES KALSHI A MULTI-SPORT SOURCE. `kalshi_board_join` hardcoded
two MLB series to two board market names. That works for two series and stops
working at three, because the mapping it encodes -- Kalshi's wording to our
market vocabulary -- is a translation this repo already owns.

--------------------------------------------------------------------------
SERIES -> SPORT IS THE ONLY THING THIS FILE DECIDES
--------------------------------------------------------------------------

`market_keys.canonical_market_key(sport, stat_text)` is the authority on market
names (`#224`, whose first reading was `missing_market_key` at **100% of every
row, in every lane, in both sports**). It already maps Kalshi's own title
wording without help: "Outs Recorded" -> `outs`, "home runs" ->
`batter_home_runs`, "points" -> `player_points`.

So a series needs one fact from us -- WHICH SPORT -- and the stat text in its
own title supplies the rest. Adding NBA player points becomes one registry line
rather than a new mapping table, and a market vocabulary that changes changes in
exactly one place for every feed at once.

CLAUDE.md's rule against a third private normaliser is the reason this file does
not have its own market table. It nearly did.

--------------------------------------------------------------------------
NOTHING HERE IS GUESSED FROM A TICKER
--------------------------------------------------------------------------

Every series in `SERIES_SPORT` has been SEEN in a live listing, and the date it
was seen is in the comment beside it. Inventing plausible tickers (`KXNBAPTS`)
is the specific trap `kalshi_client`'s docstring warns about: a series that does
not exist returns an empty page that is indistinguishable from a venue listing
nothing, which is the false negative this whole integration was built to avoid.

An unrecognised series is therefore recorded BY NAME with a sample title rather
than dropped. That list is the work queue: it says what to add and what it looks
like, so one daily discovery run is the whole discovery loop.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = [
    "SERIES_SPORT",
    "sport_for_series",
    "classify_market",
    "unmapped_series",
    "GRAMMAR_PLAYER_THRESHOLD",
    "GRAMMAR_TEAM_TOTAL",
    "GRAMMAR_TEAM_SPREAD",
    "GRAMMAR_MONEYLINE",
]

# Kalshi series ticker -> the sport this repo calls it.
#
# EVERY ENTRY WAS OBSERVED, and the observation date is the point of the
# comment. `<seen>` means it appeared in a `[kalshi_discovery] LISTED` or
# `SERIES` line with the sample title quoted.
SERIES_SPORT: dict[str, str] = {
    # seen 2026-08-23, "Andrew Abbott: 7+ strikeouts?"
    "KXMLBKS": "mlb",
    # seen 2026-08-23, "... : 17+ Outs Recorded?"
    "KXMLBOUTS": "mlb",
    # seen 2026-08-23, "Pete Crow-Armstrong: 2+ home runs?"
    "KXMLBHR": "mlb",
    # seen 2026-08-23T23:28:49Z in the signed series catalogue, titled
    # "Women's Pro Basketball Player Rebounds". The ONLY WNBA player-prop
    # series in the 91 Kalshi lists -- every other one is a game line
    # (quarter/half winners, spreads, totals) or a future (MVP, ROY, draft),
    # and those need an event_ticker mapping that does not exist.
    #
    # `market_keys` resolves "rebounds" -> `player_rebounds` for wnba, and
    # `bet_status_wnba` reads `reb` off the live box, so this one line makes the
    # market priceable, joinable AND gradeable.
    "KXWNBAREB": "wnba",
}

# Series we have SEEN and deliberately do not cover. Kept explicit so they stop
# appearing in the unmapped work queue every day: "we do not model this" and
# "we have not looked at this yet" are different states and the queue is only
# useful if it means the second.
SERIES_OUT_OF_SCOPE: dict[str, str] = {
    # seen 2026-08-23 -- Japanese NPB and Korean KBO baseball, UFC, softball.
    # Real markets, no sim, no board rows: nothing could price them.
    "KXNPBTOTAL": "npb",
    "KXNPBSPREAD": "npb",
    "KXNPBRFI": "npb",
    "KXKBOTOTAL": "kbo",
    "KXKBOSPREAD": "kbo",
    "KXKBORFI": "kbo",
    "KXUFCFIGHT": "ufc",
    "KXSOWBBALLGAME": "softball",
}

GRAMMAR_PLAYER_THRESHOLD = "player_threshold"
GRAMMAR_TEAM_TOTAL = "team_total"
GRAMMAR_TEAM_SPREAD = "team_spread"
GRAMMAR_MONEYLINE = "moneyline"

REASON_UNMAPPED_SERIES = "unmapped_series"
REASON_OUT_OF_SCOPE = "series_out_of_scope"
REASON_COMBINATORIAL = "combinatorial_series"
REASON_UNREADABLE_TITLE = "unreadable_title"
REASON_UNMAPPED_STAT = "stat_not_in_market_vocabulary"

# "Andrew Abbott: 7+ strikeouts?" / "Pete Crow-Armstrong: 2+ home runs?"
_PLAYER_THRESHOLD = re.compile(
    r"^\s*(?P<player>[^:]+?)\s*:\s*(?P<threshold>\d+)\s*\+\s*(?P<stat>.+?)\s*\??\s*$"
)
# "Over 7.5 runs scored?"
_TEAM_TOTAL = re.compile(
    r"^\s*(?P<direction>over|under)\s+(?P<line>\d+(?:\.\d+)?)\s+(?P<stat>.+?)\s*\??\s*$",
    re.IGNORECASE,
)
# "Will the Yomiuri Giants win by over 2.5 runs?"
_TEAM_SPREAD = re.compile(
    r"^\s*will\s+(?:the\s+)?(?P<team>.+?)\s+win\s+by\s+(?P<direction>over|under)\s+"
    r"(?P<line>\d+(?:\.\d+)?)\s+(?P<stat>.+?)\s*\??\s*$",
    re.IGNORECASE,
)
# "Mexico wins" / "Yadong Song wins"
_MONEYLINE = re.compile(r"^\s*(?P<team>.+?)\s+wins\s*\??\s*$", re.IGNORECASE)


def sport_for_series(series: Any) -> str | None:
    """The sport, or None. Explicit table, never a prefix rule."""
    return SERIES_SPORT.get(str(series or "").strip().upper())


def threshold_to_line(threshold: Any) -> float | None:
    """Kalshi "N+" -> the board's half-point line. 7+ -> 6.5.

    The single most mismatch-prone number in this integration: matching 7+
    against a line of 7.0 finds nothing, and matching it against 7.5 finds a
    DIFFERENT bet and prices it confidently.
    """
    try:
        value = int(threshold)
    except (TypeError, ValueError):
        return None
    return float(value) - 0.5


def _parse_title(title: str) -> dict[str, Any] | None:
    """Which grammar reads this title, and what it says. None if none does.

    Ordered most-specific first. `_TEAM_SPREAD` must be tried before
    `_MONEYLINE`, because "Will the Giants win by over 2.5 runs?" contains
    "win" and a looser moneyline pattern would swallow it -- and a spread read
    as a moneyline is a bet on a different outcome at a confident price.
    """
    match = _PLAYER_THRESHOLD.match(title)
    if match:
        return {
            "grammar": GRAMMAR_PLAYER_THRESHOLD,
            "subject": match.group("player").strip(),
            "stat_text": match.group("stat").strip(),
            "line": threshold_to_line(match.group("threshold")),
            "side": "over",
        }

    match = _TEAM_SPREAD.match(title)
    if match:
        return {
            "grammar": GRAMMAR_TEAM_SPREAD,
            "subject": match.group("team").strip(),
            "stat_text": "spreads",
            "line": float(match.group("line")),
            "side": match.group("direction").strip().lower(),
        }

    match = _TEAM_TOTAL.match(title)
    if match:
        return {
            "grammar": GRAMMAR_TEAM_TOTAL,
            # A total names no team. The GAME is in `event_ticker`, which is why
            # this grammar cannot be joined by title alone -- see the note on
            # `needs_event_identity` below.
            "subject": None,
            "stat_text": "totals",
            "line": float(match.group("line")),
            "side": match.group("direction").strip().lower(),
        }

    match = _MONEYLINE.match(title)
    if match:
        return {
            "grammar": GRAMMAR_MONEYLINE,
            "subject": match.group("team").strip(),
            "stat_text": "h2h",
            "line": None,
            "side": "yes",
        }
    return None


# Grammars whose title does NOT identify the game. A player prop names a human,
# and a human plays one game a day, so (player, market, line) is a complete
# identity. "Over 7.5 runs scored?" names neither team -- joining it needs
# Kalshi's `event_ticker` mapped to our event id, which does not exist yet.
# Flagged rather than silently attempted: a total joined to the wrong game is a
# confidently-priced bet on strangers.
_NEEDS_EVENT_IDENTITY = frozenset({GRAMMAR_TEAM_TOTAL, GRAMMAR_TEAM_SPREAD, GRAMMAR_MONEYLINE})


def classify_market(market: Mapping[str, Any]) -> dict[str, Any]:
    """One Kalshi market -> what bet it is, or a NAMED reason we cannot say.

    Never raises and never guesses. The refusal reasons are the work queue:
    `unmapped_series` says add a registry line, `stat_not_in_market_vocabulary`
    says add a `market_keys` entry, and those are different jobs.
    """
    from syndicate.features.shared.kalshi_client import is_combinatorial_series
    from syndicate.features.shared.market_keys import canonical_market_key

    series = str(market.get("series") or "").strip().upper()
    if is_combinatorial_series(series):
        return {"status": "refused", "reason": REASON_COMBINATORIAL, "series": series}
    if series in SERIES_OUT_OF_SCOPE:
        return {
            "status": "refused",
            "reason": REASON_OUT_OF_SCOPE,
            "series": series,
            "detail": SERIES_OUT_OF_SCOPE[series],
        }

    sport = sport_for_series(series)
    if sport is None:
        return {"status": "refused", "reason": REASON_UNMAPPED_SERIES, "series": series}

    parsed = _parse_title(str(market.get("title") or ""))
    if parsed is None:
        return {"status": "refused", "reason": REASON_UNREADABLE_TITLE, "series": series}

    market_key = canonical_market_key(sport, parsed["stat_text"])
    if market_key is None:
        return {
            "status": "refused",
            "reason": REASON_UNMAPPED_STAT,
            "series": series,
            "sport": sport,
            # The stat text VERBATIM, so the `market_keys` entry to add is
            # readable straight off the log line.
            "detail": parsed["stat_text"],
        }

    return {
        "status": "ok",
        "series": series,
        "sport": sport,
        "market": market_key,
        "grammar": parsed["grammar"],
        "subject": parsed["subject"],
        "line": parsed["line"],
        "side": parsed["side"],
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        # True means the title alone cannot say WHICH GAME this is. The join
        # must refuse these until an event mapping exists.
        "needs_event_identity": parsed["grammar"] in _NEEDS_EVENT_IDENTITY,
    }


def unmapped_series(markets) -> dict[str, Any]:
    """What Kalshi lists that we cannot yet price, by series, with an example.

    THE WORK QUEUE, and the reason discovery is worth running at all. A count of
    unmapped markets says nothing actionable; a series name beside a sample
    title says exactly which registry line to add and what its titles look like.
    """
    seen: dict[str, dict[str, Any]] = {}
    for market in markets:
        verdict = classify_market(market)
        if verdict.get("status") == "ok":
            continue
        reason = str(verdict.get("reason"))
        if reason in {REASON_COMBINATORIAL, REASON_OUT_OF_SCOPE}:
            # Known and deliberately excluded -- keeping them here would drown
            # the queue in things nobody intends to do.
            continue
        series = str(verdict.get("series") or "<absent>")
        entry = seen.setdefault(
            series,
            {"count": 0, "reason": reason, "sample_title": str(market.get("title") or "")[:80]},
        )
        entry["count"] += 1
        if verdict.get("detail") and "detail" not in entry:
            entry["detail"] = verdict["detail"]
    return dict(sorted(seen.items(), key=lambda kv: -kv[1]["count"]))
