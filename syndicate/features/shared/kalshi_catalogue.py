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
    "sport_for_ticker",
    "auto_series_from_catalogue",
    "register_discovered",
    "all_series",
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
    # The other three WNBA player props, seen in the same catalogue read:
    # "Women's Pro Basketball Player Points" / "Player Assists" /
    # "Player Threes". `market_keys` resolves all three for wnba and
    # `bet_status_wnba` reads pts / ast / threes_made off the live box.
    #
    # HAND-REGISTERED even though `auto_series_from_catalogue` finds all four,
    # and the duplication is deliberate. Discovery is PER-PROCESS state
    # populated at boot: if the catalogue read fails once -- a 429, a restart
    # mid-outage -- that process prices nothing but the hand-written entries for
    # its whole life, silently. Naming the ones that matter tonight makes them
    # independent of a network call succeeding at the right moment.
    # `register_discovered` never overwrites these, so discovery finding them
    # again is a no-op rather than a conflict.
    "KXWNBAPTS": "wnba",
    "KXWNBAAST": "wnba",
    "KXWNBA3PT": "wnba",
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


# Ticker token -> sport. ORDER MATTERS AND IS THE WHOLE TRAP: "KXWNBAREB"
# contains "NBA", so a naive scan registers every WNBA series as NBA and prices
# women's rebounds off a men's box score. Longest-first, and WNBA before NBA.
_SPORT_TOKENS: tuple[tuple[str, str], ...] = (
    ("NCAAF", "ncaaf"),
    ("NCAAB", "ncaab"),
    ("WNBA", "wnba"),
    ("NBA", "nba"),
    ("MLB", "mlb"),
    ("NFL", "nfl"),
    ("NHL", "nhl"),
)

# A title that names a PLAYER prop. Kalshi words them "…Player Rebounds",
# "…Player Points". The word PLAYER is the discriminator: "Team Totals",
# "1st Quarter Spread" and "Rookie of the Year" all lack it, and every one of
# them is a market this system must not auto-register -- a game line has no
# player to join on and needs an event mapping that does not exist.
_PLAYER_PROP_TITLE = re.compile(r"\bplayer\s+(?P<stat>[A-Za-z0-9 +'-]+)$", re.IGNORECASE)


def sport_for_ticker(ticker: Any) -> str | None:
    """The sport a series ticker names, or None. Longest token first."""
    text = str(ticker or "").strip().upper()
    for token, sport in _SPORT_TOKENS:
        if token in text:
            return sport
    return None


def auto_series_from_catalogue(titles: Mapping[str, Any]) -> dict[str, str]:
    """Series Kalshi lists that are PLAYER PROPS we can already price.

    THE ALTERNATIVE TO A HAND-MAINTAINED REGISTRY. Kalshi lists 13,389 series;
    four were registered by hand, and every sport added that way is a sport
    somebody has to remember. This reads the catalogue Kalshi gave us and keeps
    the ones that satisfy BOTH conditions:

      1. the TITLE says "Player <stat>" -- Kalshi's own word for a player prop,
         and the discriminator that excludes team totals, quarter spreads and
         every futures market, none of which have a player to join on; and
      2. `market_keys` resolves that stat for that sport -- so a market we
         cannot name is never registered, however player-shaped it looks.

    Both, because either alone is a guess. A title with "Player" in it whose
    stat we cannot resolve would price nothing; a stat we can resolve on a
    series that is actually a game line would join to the wrong thing.

    The SPORT comes from the ticker, never the title: "Women's Pro Basketball"
    is not a token this repo uses anywhere.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    found: dict[str, str] = {}
    for ticker, title in (titles or {}).items():
        sport = sport_for_ticker(ticker)
        if sport is None:
            continue
        match = _PLAYER_PROP_TITLE.search(str(title or "").strip())
        if not match:
            continue
        if canonical_market_key(sport, match.group("stat").strip()) is None:
            continue
        found[str(ticker).strip().upper()] = sport
    return found


def sport_for_series(series: Any) -> str | None:
    """The sport, or None. Hand registry first, then anything discovery added.

    Discovery writes into `_DISCOVERED` rather than into `SERIES_SPORT`, so a
    hand-written entry always wins and the two never become indistinguishable
    -- "we chose this" and "a title matched" are different confidence levels.
    """
    key = str(series or "").strip().upper()
    return SERIES_SPORT.get(key) or _DISCOVERED.get(key)


_DISCOVERED: dict[str, str] = {}


def register_discovered(found: Mapping[str, str]) -> dict[str, Any]:
    """Add auto-discovered series. Reports what was ADDED, not what was seen.

    Idempotent, and never overwrites a hand-written entry.
    """
    added = {
        ticker: sport
        for ticker, sport in (found or {}).items()
        if ticker not in SERIES_SPORT and _DISCOVERED.get(ticker) != sport
    }
    _DISCOVERED.update(added)
    return {"added": added, "total_discovered": len(_DISCOVERED)}


def all_series() -> dict[str, str]:
    """Every series we price: hand-registered plus discovered."""
    return {**_DISCOVERED, **SERIES_SPORT}


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
