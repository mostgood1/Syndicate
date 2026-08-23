"""Resolve an MLB bet's CURRENT value from the live game feed.

The resolver `bet_status` takes as an injection. It answers one question --
"what is the thing this bet is on worth right now" -- and leaves every judgement
about winning, losing and decided to `resolve_bet_status`, which is where the
monotonicity rules live.

**IT READS THE LIVE FEED, NOT A FINAL ONE.** `box_score_stats.final_stat_value`
is named for its original caller (settlement) but is a pure function over a
`feed/live` payload, and an in-progress game's payload has exactly the same
boxscore shape as a finished one. So the same tested reader serves both, and
there is no second copy of MLB's stat-name vocabulary to drift.

**NO SYNCHRONOUS FETCH.** `load_final_feed` will hit statsapi.mlb.com when the
cache misses; this passes `fetch_if_missing=False`. The refresh worker already
captures `feed_live` on its own cadence, and a per-bet network call inside the
board build would put a live HTTP dependency in the middle of the artifact
pipeline -- which is the shape `#506` removed from the web service (15 live
statsapi calls per request, 3318-8400ms). A missing feed is a NAMED absence
here, not something to go and fetch.

**MARKET NAMES ARE MAPPED EXPLICITLY.** The board's market vocabulary
(`batter_total_bases`) and the box score's stat vocabulary (`total_bases`) are
different namespaces that happen to look similar. Stripping a `batter_` prefix
would work until it met `batter_hits_runs_rbis`, so every market is listed.
An unmapped market is refused by name rather than guessed at.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["mlb_status_resolver"]

REASON_NO_GAME_PK = "no_game_pk"
REASON_NO_FEED = "no_live_feed"
REASON_UNMAPPED_MARKET = "unmapped_market"
REASON_NO_STAT = "stat_not_in_feed"

# board market -> (group, box-score stat name)
_MARKET_TO_STAT: dict[str, tuple[str, str]] = {
    "batter_hits": ("hitter", "hits"),
    "batter_total_bases": ("hitter", "total_bases"),
    "batter_home_runs": ("hitter", "home_runs"),
    "batter_rbis": ("hitter", "rbi"),
    "batter_runs_scored": ("hitter", "runs"),
    "batter_hits_runs_rbis": ("hitter", "hits_runs_rbis"),
    "pitcher_strikeouts": ("pitcher", "strikeouts"),
    "pitcher_hits_allowed": ("pitcher", "hits_allowed"),
    "pitcher_earned_runs": ("pitcher", "earned_runs"),
    "pitcher_walks": ("pitcher", "walks_allowed"),
    "pitcher_outs": ("pitcher", "outs"),
}

# Markets resolved from the SCOREBOARD rather than a player's line.
_GAME_TOTAL_MARKETS = frozenset({"totals", "totals_alt"})


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _game_is_final(feed: Mapping[str, Any]) -> bool:
    state = (
        ((feed.get("gameData") or {}).get("status") or {}).get("abstractGameState")
    )
    return str(state or "").strip().lower() == "final"


def _game_has_started(feed: Mapping[str, Any]) -> bool:
    state = (
        ((feed.get("gameData") or {}).get("status") or {}).get("abstractGameState")
    )
    return str(state or "").strip().lower() in {"live", "final"}


def _combined_score(feed: Mapping[str, Any]) -> float | None:
    linescore = (feed.get("liveData") or {}).get("linescore") or {}
    teams = linescore.get("teams") or {}
    home = ((teams.get("home") or {}).get("runs"))
    away = ((teams.get("away") or {}).get("runs"))
    if home is None or away is None:
        return None
    try:
        return float(home) + float(away)
    except (TypeError, ValueError):
        return None


def mlb_status_resolver(selected_date: str):
    """Build a resolver bound to one slate date.

    Feeds are cached per game for the life of the returned closure: a slate has
    far more bets than games, and re-reading (and gunzipping) the same payload
    once per bet is the kind of quiet cost that turns a diagnostic into a
    reason the board build got slower.
    """
    from syndicate.features.mlb.box_score_stats import final_stat_value, load_final_feed

    cache: dict[int, Mapping[str, Any] | None] = {}

    def _feed(game_pk: int) -> Mapping[str, Any] | None:
        if game_pk not in cache:
            try:
                # fetch_if_missing=False -- see the module docstring.
                cache[game_pk] = load_final_feed(
                    selected_date, game_pk, fetch_if_missing=False
                )
            except Exception:
                cache[game_pk] = None
        return cache[game_pk]

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        game_pk = _int_or_none(order.get("game_pk"))
        if game_pk is None:
            # Orders placed before `game_pk` was carried on the record have
            # none, and there is nothing to look it up from here.
            return {"unavailable_reason": REASON_NO_GAME_PK}

        feed = _feed(game_pk)
        if not isinstance(feed, Mapping) or not feed:
            return {"unavailable_reason": REASON_NO_FEED}

        started = _game_has_started(feed)
        is_final = _game_is_final(feed)
        market = str(order.get("market") or "").strip().lower()

        if market in _GAME_TOTAL_MARKETS:
            total = _combined_score(feed)
            if total is None:
                return {"unavailable_reason": REASON_NO_STAT}
            return {"current_value": total, "is_final": is_final, "started": started}

        mapped = _MARKET_TO_STAT.get(market)
        if mapped is None:
            # Spreads, moneylines and every prop family not listed. Named rather
            # than guessed -- a wrong stat produces a confident wrong verdict.
            return {"unavailable_reason": REASON_UNMAPPED_MARKET}

        group, stat = mapped
        value = final_stat_value(
            dict(feed),
            group=group,
            stat=stat,
            player_name=str(order.get("player_name") or ""),
        )
        if value is None:
            # The player has not recorded this stat yet, OR the name did not
            # match. Those are different and this cannot tell them apart, so it
            # does NOT default to 0 -- a bet reported as "0 hits, Under is fine"
            # when we simply failed to find the player is the worst possible
            # wrong answer.
            return {"unavailable_reason": REASON_NO_STAT}

        return {"current_value": value, "is_final": is_final, "started": started}

    return resolve
