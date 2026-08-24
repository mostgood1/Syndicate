"""Resolve a WNBA bet's CURRENT value from the live player box score.

The sibling of `bet_status_mlb`, and deliberately the same shape: it answers
"what is the thing this bet is on worth right now" and leaves every judgement
about winning and losing to `resolve_bet_status`.

--------------------------------------------------------------------------
KEYED ON `event_id`, WHICH SIDESTEPS MLB'S WHOLE PROBLEM
--------------------------------------------------------------------------

MLB cost a day because the board stamps `game_pk` from `row["event_id"]` -- the
OddsAPI hash -- while StatsAPI wants a numeric gamePk, and `int()` cannot parse
a hash. Every MLB order resolved to `no_game_pk`.

WNBA has no such gap: `live_player_box_<date>.json` is keyed by `event_id`, the
SAME id the order carries. No schedule lookup, no matchup recovery, no
doubleheader ambiguity. The id on the record is the id in the artifact.

--------------------------------------------------------------------------
NO FINAL FLAG IN THIS ARTIFACT, AND THAT IS STATED RATHER THAN GUESSED
--------------------------------------------------------------------------

The capture stores what `/wnba/api/live_player_boxscore` returns: minutes,
points, rebounds, assists, threes. **There is no game-status field.** So this
resolver reports `is_final=False` ALWAYS, and never claims a game has ended.

That is not a shrug -- it is exactly right for the bets in question, because it
loses nothing on the OVER side. Points, rebounds, assists and threes are
counting stats, so `bet_status.is_monotone_market` returns True for all of them
and an over DECIDES the instant it crosses its line, final flag or not. What it
costs is the under side: an under cannot be settled until the game is known to
be over, so it stays `live_ahead` rather than grading.

Claiming a game was final on a guess would be the opposite trade: it would
settle unders early, and an under graded at halftime is a confident wrong
answer on a bet that was still live. Waiting is recoverable; that is not.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["wnba_status_resolver"]

REASON_NO_EVENT_ID = "no_event_id"
REASON_NO_BOX = "no_live_box_for_date"
REASON_GAME_NOT_IN_BOX = "game_not_in_live_box"
# The market IS gradeable in principle -- `game_line_bet` handles spreads and
# moneylines for any sport that can supply two team scores. This capture is a
# PLAYER box and has none, so the fix is upstream in the capture rather than a
# missing entry in a table here.
REASON_NO_TEAM_SCORES = "no_team_scores_in_player_box"
REASON_UNMAPPED_MARKET = "unmapped_market"
REASON_PLAYER_NOT_FOUND = "player_not_in_box"
REASON_NO_STAT = "stat_not_in_box"

# Canonical board market -> the key the live box row carries.
# Canonical because `market_keys` owns that vocabulary (`#224`); the RAW board
# name is canonicalised on the way in, so both spellings resolve. Four separate
# market tables drifted apart in this codebase on 2026-08-23 and every one of
# them was a private list exactly like this one would have been.
_MARKET_TO_BOX_KEY: dict[str, str] = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "threes_made",
}

# Combination markets the box does not carry directly but can SUM. Listed
# explicitly rather than parsed out of the market name: `player_points_rebounds`
# and `player_points_rebounds_assists` differ by one token and a prefix rule
# would price one as the other.
_MARKET_TO_BOX_SUM: dict[str, tuple[str, ...]] = {
    "player_points_rebounds": ("pts", "reb"),
    "player_points_assists": ("pts", "ast"),
    "player_rebounds_assists": ("reb", "ast"),
    "player_points_rebounds_assists": ("pts", "reb", "ast"),
}


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _canonical(market: Any) -> str:
    from syndicate.features.shared.market_keys import canonical_market_key

    raw = str(market or "").strip().lower()
    return canonical_market_key("wnba", raw) or raw


def wnba_status_resolver(selected_date: str):
    """A resolver `bet_status`/`paper_settlement` can inject, for WNBA orders.

    The box is read ONCE per resolver, not once per order: a slate of forty
    orders must not mean forty reads of one unchanging artifact.
    """
    from syndicate.features.shared.game_line_bet import is_game_line_market
    from syndicate.features.shared.wnba_live_prop_rows import normalize_name

    cache: dict[str, Any] = {}

    def box_index() -> dict[str, dict[str, Mapping[str, Any]]] | None:
        if "index" in cache:
            return cache["index"]
        cache["index"] = _load_box_index(selected_date, normalize_name)
        return cache["index"]

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if str(order.get("sport") or "").strip().lower() != "wnba":
            # This resolver is handed every order; a non-WNBA one is not a
            # defect in anything and must not be reported as a WNBA failure.
            return {"unavailable_reason": f"not_a_wnba_order"}

        # THE MARKET CHECK COMES FIRST, before the artifact read. "We have no
        # box key for this market" is permanent; "the box is not captured yet"
        # is temporary, and checking the transient one first hides the
        # structural one -- measured on the MLB grader this morning, where
        # `no_live_feed: 50` concealed 40 orders that could never grade.
        market = _canonical(order.get("market"))
        box_key = _MARKET_TO_BOX_KEY.get(market)
        sum_keys = _MARKET_TO_BOX_SUM.get(market)
        if box_key is None and sum_keys is None:
            # A GAME LINE IS NOT AN UNMAPPED PROP, and lumping the two together
            # is what made this invisible. `game_line_bet` can grade spreads
            # and moneylines for any sport that supplies two team scores; this
            # artifact is a PLAYER box and carries none, so the blocker is the
            # capture, not the vocabulary.
            #
            # MLB gained game-line grading on 2026-08-24; WNBA did not, and
            # this reason is the difference between "add four market names"
            # (wrong, and would have been tried) and "the box needs team
            # scores in it" (right). Reported honestly rather than made to
            # look like the same fix.
            if is_game_line_market("wnba", market):
                return {"unavailable_reason": REASON_NO_TEAM_SCORES}
            return {"unavailable_reason": REASON_UNMAPPED_MARKET}

        event_id = str(order.get("event_id") or "").strip()
        if not event_id:
            return {"unavailable_reason": REASON_NO_EVENT_ID}

        index = box_index()
        if index is None:
            return {"unavailable_reason": REASON_NO_BOX}
        players = index.get(event_id)
        if players is None:
            return {"unavailable_reason": REASON_GAME_NOT_IN_BOX}

        row = players.get(normalize_name(order.get("player_name")))
        if row is None:
            # The player is not in this game's box, OR the name did not match.
            # Named rather than defaulted to 0: a bet reported as "0 points,
            # Under is fine" when we simply failed to find her is the worst
            # possible wrong answer, and it is the one `bet_status_mlb` calls
            # out for the same reason.
            return {"unavailable_reason": REASON_PLAYER_NOT_FOUND}

        if sum_keys is not None:
            parts = [_as_float(row.get(key)) for key in sum_keys]
            if any(part is None for part in parts):
                # A partial sum is a smaller number that looks like a real one.
                return {"unavailable_reason": REASON_NO_STAT}
            value = sum(parts)
        else:
            value = _as_float(row.get(box_key))
            if value is None:
                return {"unavailable_reason": REASON_NO_STAT}

        return {
            "current_value": value,
            # ALWAYS False -- this artifact carries no game status. See the
            # module docstring: overs still decide on crossing because these are
            # counting stats, and unders wait rather than being settled on a
            # guess about whether the game ended.
            "is_final": False,
            "started": True,
        }

    return resolve


def _load_box_index(selected_date: str, normalize_name) -> dict[str, dict[str, Mapping[str, Any]]] | None:
    """`event_id -> {normalized player name -> row}`, or None if unreadable.

    None means "we could not read the box", which is NOT the same as a box with
    no games in it -- the caller reports them as different reasons.
    """
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    try:
        record = read_json_file(
            data_root() / f"wnba_source/data/live/live_player_box_{selected_date}.json"
        )
    except Exception:
        return None
    if not isinstance(record, Mapping):
        return None
    payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else record

    index: dict[str, dict[str, Mapping[str, Any]]] = {}
    for game in payload.get("games") or []:
        if not isinstance(game, Mapping):
            continue
        event_id = str(game.get("event_id") or "").strip()
        if not event_id:
            continue
        players: dict[str, Mapping[str, Any]] = {}
        for player in game.get("players") or []:
            if not isinstance(player, Mapping):
                continue
            key = normalize_name(player.get("player") or player.get("player_name"))
            if key:
                players[key] = player
        index[event_id] = players
    return index
