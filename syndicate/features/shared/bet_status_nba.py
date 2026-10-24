"""Resolve an NBA bet's CURRENT value from the live player box.

The sibling of `bet_status_wnba`, and the same contract: it answers "what is the
thing this bet is on worth right now" and leaves every judgement about winning
and losing to `bet_status.resolve_bet_status`. So an over 0.5 blocks reads WON
the moment the box shows one block -- blocks are monotone -- and an under waits
for the final.

Until this existed `_default_resolver` had no `nba` entry, and every open NBA
order on the portfolio page read `no_resolver_for_nba` (measured on the fleet
2026-10-24 00:3xZ: 113 NBA orders in the book, every open one carrying it).

THE ARTIFACT is `nba_source/data/live/live_player_box_<date>.json`, written by
`syndicate.features.nba.live_player_box.capture` from the live-lens tick on the
worker. Unlike the WNBA live box it carries per-game STATE (`pre`/`in`/`post`)
and team scores, so this resolver can say "not started", settle an under once
the game is over, and read game lines (totals, spreads, moneylines) from the
same file.

KEYED ON THE MATCHUP. The order carries the board's OddsAPI hash and the box an
ESPN id -- the namespace gap `bet_status_wnba` documents at length -- so the id
is tried first and the two clubs second. Both sides go through
`team_aliases.canonical_team("nba", ...)`, which resolves every full club name
and every tri-code the tick writes (30 of 30 each, checked); `nba/cards.py`'s
`_canonical_nba_tri` alone returns "UTAH JAZZ" for "Utah Jazz".

NOT SEGMENT-AWARE. The box is whole-game, so a first-half or quarter bet refuses
with the shared `actual_is_full_game_not_<seg>` reason rather than grading off
the full game.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from syndicate.features.shared.bet_status import segment_refusal

__all__ = ["nba_status_resolver", "REASON_NO_BOX"]

REASON_NO_EVENT_ID = "no_event_id"
REASON_NO_BOX = "no_live_box_for_date"
REASON_GAME_NOT_IN_BOX = "game_not_in_live_box"
REASON_NO_MATCHUP_ON_ORDER = "no_matchup_on_order"
REASON_AMBIGUOUS_MATCHUP = "matchup_twice_in_live_box"
REASON_UNMAPPED_MARKET = "unmapped_market"
REASON_PLAYER_NOT_FOUND = "player_not_in_box"
REASON_NO_STAT = "stat_not_in_box"
REASON_NO_TEAM_SCORES = "no_team_scores_in_live_box"

# Canonical board market -> the key the box row carries (the live tick's own
# spelling, `_live_extract_player_boxscore_from_espn_summary`).
_MARKET_TO_BOX_KEY: dict[str, str] = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "threes_made",
    "player_steals": "stl",
    "player_blocks": "blk",
    "player_turnovers": "tov",
}

# Listed, not parsed out of the name -- `player_points_rebounds` and
# `player_points_rebounds_assists` differ by one token.
_MARKET_TO_BOX_SUM: dict[str, tuple[str, ...]] = {
    "player_points_rebounds": ("pts", "reb"),
    "player_points_assists": ("pts", "ast"),
    "player_rebounds_assists": ("reb", "ast"),
    "player_points_rebounds_assists": ("pts", "reb", "ast"),
    "player_blocks_steals": ("blk", "stl"),
}

_TOTAL_MARKETS = frozenset({"totals", "totals_alt"})


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _canonical_market(market: Any) -> str:
    from syndicate.features.shared.market_keys import canonical_market_key

    raw = str(market or "").strip().lower()
    return canonical_market_key("nba", raw) or raw


def _club(value: Any) -> str | None:
    """One key per NBA club, from a full name or any tri-code spelling."""
    text = str(value or "").strip()
    if not text:
        return None
    from syndicate.features.shared.team_aliases import canonical_team

    club = canonical_team("nba", text)
    if club:
        return club
    try:
        from syndicate.features.nba.cards import _canonical_nba_tri

        return canonical_team("nba", _canonical_nba_tri(text)) or None
    except Exception:
        return None


def _matchup_key(one: Any, two: Any):
    left, right = _club(one), _club(two)
    if not left or not right or left == right:
        return None
    return frozenset((left, right))


def _normalize_name(value: Any) -> str:
    from syndicate.features.nba.live_tick.player_names import normalize_player_name_key

    return normalize_player_name_key(value)


def _load_box(selected_date: str) -> dict[str, Any] | None:
    """`{"by_event": {id: game}, "by_matchup": {frozenset: game}}`, or None if unreadable."""
    from syndicate.features.nba.live_player_box import artifact_relative_path
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    try:
        record = read_json_file(data_root() / artifact_relative_path(selected_date))
    except Exception:
        return None
    if not isinstance(record, Mapping):
        return None
    payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else record
    by_event: dict[str, dict[str, Any]] = {}
    by_matchup: dict[Any, dict[str, Any]] = {}
    for game in payload.get("games") or []:
        if not isinstance(game, Mapping):
            continue
        event_id = str(game.get("event_id") or "").strip()
        players: dict[str, Mapping[str, Any]] = {}
        for player in game.get("players") or []:
            if isinstance(player, Mapping):
                key = _normalize_name(player.get("player") or player.get("player_name"))
                if key:
                    players[key] = player
        entry = {**dict(game), "_players": players}
        if event_id:
            by_event[event_id] = entry
        key = _matchup_key(game.get("away_tri"), game.get("home_tri"))
        if key is not None:
            # The same two clubs twice on one date is an artifact defect, not a
            # doubleheader; refuse both rather than pick one.
            by_matchup[key] = {"ambiguous": True} if key in by_matchup else entry
    return {"by_event": by_event, "by_matchup": by_matchup}


def _find_game(order: Mapping[str, Any], box: Mapping[str, Any]):
    """(game, matched_by) or (None, refusal reason)."""
    event_id = str(order.get("event_id") or "").strip()
    game = box["by_event"].get(event_id) if event_id else None
    if game is not None:
        return game, "event_id"
    key = _matchup_key(order.get("away_team"), order.get("home_team"))
    if key is None:
        return None, (REASON_NO_EVENT_ID if not event_id else REASON_NO_MATCHUP_ON_ORDER)
    game = box["by_matchup"].get(key)
    if game is None:
        return None, REASON_GAME_NOT_IN_BOX
    if game.get("ambiguous"):
        return None, REASON_AMBIGUOUS_MATCHUP
    return game, "matchup"


def _game_stamp(game: Mapping[str, Any], matched_by: str) -> dict[str, Any]:
    state = str(game.get("state") or "")
    return {
        "matched_by": matched_by,
        "is_final": bool(game.get("final")),
        "started": state in {"in", "post"},
        # THE AS-OF. When this game's box was last read, not when the plan was
        # written -- a stale box must say so on the page.
        "as_of": game.get("captured_at"),
        "game_state": game.get("status_detail") or state or None,
    }


def _game_line(order: Mapping[str, Any], market: str, game: Mapping[str, Any], matched_by: str) -> dict[str, Any]:
    from syndicate.features.shared.game_line_bet import game_line_view

    stamp = _game_stamp(game, matched_by)
    if not stamp["started"]:
        return stamp
    # Orient the box's scores to the ORDER's home/away; a swap is a join defect
    # that must never silently invert a spread.
    if _club(order.get("home_team")) == _club(game.get("home_tri")):
        home_score, away_score = game.get("home_score"), game.get("away_score")
    elif _club(order.get("home_team")) == _club(game.get("away_tri")):
        home_score, away_score = game.get("away_score"), game.get("home_score")
    else:
        return {"unavailable_reason": REASON_GAME_NOT_IN_BOX}
    home_score, away_score = _as_float(home_score), _as_float(away_score)
    if home_score is None or away_score is None:
        return {"unavailable_reason": REASON_NO_TEAM_SCORES}
    scores = {
        "home_score": home_score,
        "away_score": away_score,
        "home_name": order.get("home_team"),
        "away_name": order.get("away_team"),
    }
    if market in _TOTAL_MARKETS:
        return {**stamp, **scores, "current_value": home_score + away_score}
    view = game_line_view(
        sport="nba",
        market=market,
        side=order.get("side"),
        line=order.get("line"),
        home_team=order.get("home_team"),
        away_team=order.get("away_team"),
        home_score=home_score,
        away_score=away_score,
        draw_possible=False,
    )
    if view.get("unavailable_reason"):
        return view
    return {**view, **stamp, **scores}


def nba_status_resolver(selected_date: str):
    """A resolver `bet_status`/`paper_settlement` can inject, for NBA orders.

    The box is read ONCE per resolver, not once per order.
    """
    from syndicate.features.shared.game_line_bet import is_game_line_market

    cache: dict[str, Any] = {}

    def box():
        if "box" not in cache:
            cache["box"] = _load_box(selected_date)
        return cache["box"]

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if str(order.get("sport") or "").strip().lower() != "nba":
            return {"unavailable_reason": "not_a_nba_order"}

        refusal = segment_refusal(order)
        if refusal is not None:
            return refusal

        # The market check before the artifact read: "no mapping" is permanent,
        # "no box yet" is transient, and the transient one must not hide it.
        market = _canonical_market(order.get("market"))
        box_key = _MARKET_TO_BOX_KEY.get(market)
        sum_keys = _MARKET_TO_BOX_SUM.get(market)
        is_line = box_key is None and sum_keys is None
        if is_line and not (is_game_line_market("nba", market) or market in _TOTAL_MARKETS):
            return {"unavailable_reason": REASON_UNMAPPED_MARKET}

        index = box()
        if index is None:
            return {"unavailable_reason": REASON_NO_BOX}
        game, matched = _find_game(order, index)
        if game is None:
            return {"unavailable_reason": matched}

        if is_line:
            return _game_line(order, market, game, matched)

        stamp = _game_stamp(game, matched)
        if not stamp["started"]:
            return stamp
        row = game["_players"].get(_normalize_name(order.get("player_name")))
        if row is None:
            # Not in the box (has not played yet, or a name mismatch). Named, never
            # a zero: "0 blocks, under is fine" when we simply failed to find him is
            # the worst wrong answer this can give.
            return {"unavailable_reason": REASON_PLAYER_NOT_FOUND}
        if sum_keys is not None:
            parts = [_as_float(row.get(key)) for key in sum_keys]
            if any(part is None for part in parts):
                # A partial sum is a smaller number that looks real.
                return {"unavailable_reason": REASON_NO_STAT}
            value = sum(parts)
        else:
            value = _as_float(row.get(box_key))
            if value is None:
                return {"unavailable_reason": REASON_NO_STAT}
        return {**stamp, "current_value": value}

    return resolve
