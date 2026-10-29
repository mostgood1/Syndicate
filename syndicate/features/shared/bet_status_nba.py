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

DID NOT PLAY (2026-10-28, user decision "Yes, void them", `#744`). The box keeps
only players with minutes, so a player who sat out is ABSENT -- and absence alone
cannot tell a sat-out player from a name the box spells differently. ESPN,
read on the three known games:

    dressed, sat out   core game roster: `didNotPlay: true`, no statistics
                       (Kawhi Leonard, 401909864, "LEFT KNEE SWELLING")
    inactive           absent from the summary box, the core game roster AND
                       the current injury list (LeBron James 401909855, Kyrie
                       Irving 401909858)

So for a FINAL game more than six hours past tip, a player absent from the box
is matched by name to ONE athlete on the two clubs' ESPN team rosters, and that
athlete's ID is looked up among the game roster's `playerId`s: `didNotPlay`
with no statistics, or absent from both game rosters, is `REASON_DNP_VOID`,
which `paper_settlement` settles as a void. A name no team-roster athlete
carries refuses -- it never voids -- so absence is judged by ID, never by name.
The reads are `bet_status_nfl.EspnSettlementFeed`'s, with its timeout and its
process-wide refusal memo.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from syndicate.features.shared.bet_status import segment_refusal

__all__ = ["nba_status_resolver", "did_not_play", "REASON_NO_BOX", "REASON_DNP_VOID"]

REASON_NO_EVENT_ID = "no_event_id"
REASON_NO_BOX = "no_live_box_for_date"
REASON_GAME_NOT_IN_BOX = "game_not_in_live_box"
REASON_NO_MATCHUP_ON_ORDER = "no_matchup_on_order"
REASON_AMBIGUOUS_MATCHUP = "matchup_twice_in_live_box"
REASON_UNMAPPED_MARKET = "unmapped_market"
REASON_PLAYER_NOT_FOUND = "player_not_in_box"
REASON_NO_STAT = "stat_not_in_box"
REASON_NO_TEAM_SCORES = "no_team_scores_in_live_box"
# Did-not-play, settlement-only (module docstring). Only REASON_DNP_VOID voids.
REASON_DNP_VOID = "nba_player_did_not_play_void"
REASON_ROSTER_UNAVAILABLE = "nba_game_roster_unavailable"
REASON_NOT_ON_TEAM_ROSTER = "nba_player_not_on_either_team_roster"
REASON_ROSTER_AMBIGUOUS = "nba_player_ambiguous_on_team_rosters"
REASON_PLAYED_NOT_IN_BOX = "nba_player_played_but_not_in_box"
REASON_PARTICIPATION_UNKNOWN = "nba_player_participation_unproven"

_DEFINITIVE_ROSTER_REFUSALS = frozenset(
    {REASON_DNP_VOID, REASON_NOT_ON_TEAM_ROSTER, REASON_ROSTER_AMBIGUOUS, REASON_PLAYED_NOT_IN_BOX,
     REASON_PARTICIPATION_UNKNOWN}
)
# An NBA team dresses at least eight. Fewer game-roster rows than two of those is
# a partial read, and a partial read cannot say a player was absent.
_MIN_GAME_ROSTER_ENTRIES = 16

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

# A DOUBLE-DOUBLE IS A COUNT, NOT A STAT [`#744`]. Yes/no on how many of points,
# rebounds, assists, steals and blocks reached ten -- two for a double, three for
# a triple. The order carries no line (`NaN` on the fleet), so the resolver
# RESTATES one, the way `game_line_bet` restates a spread: the value is the count
# and the line is `needed - 0.5`, so Yes is an over and No an under. Before this
# every pass logged `ARCHIVED_UNMAPPED_MARKETS {'player_double_double': 1}`
# (Nikola Jokic, 2026-10-24, the only one in the archive). The same table
# `population_outcomes_espn._WNBA_DOUBLES` grades the population with.
_MARKET_TO_DOUBLES: dict[str, int] = {"player_double_double": 2, "player_triple_double": 3}
_DOUBLE_STATS = ("pts", "reb", "ast", "stl", "blk")

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


def _athlete_names(athlete: Mapping[str, Any]) -> set[str]:
    first, last = str(athlete.get("firstName") or "").strip(), str(athlete.get("lastName") or "").strip()
    names = (athlete.get("fullName"), athlete.get("displayName"), f"{first} {last}".strip())
    return {key for key in (_normalize_name(name) for name in names) if key}


def did_not_play(feed: Any, event_id: str, player_name: Any) -> dict[str, Any]:
    """For a player ABSENT from a final box: `{"unavailable_reason": ...}`, always.

    `REASON_DNP_VOID` (with `dnp_basis`) only when ESPN identifies him on one of
    the two clubs and his athlete ID either sat out on the game roster or is not
    on it at all. See the module docstring."""
    team_ids = feed.competitor_ids(event_id)
    entries = feed.game_roster(event_id)
    if team_ids is None or entries is None or len(entries) < _MIN_GAME_ROSTER_ENTRIES:
        return {"unavailable_reason": REASON_ROSTER_UNAVAILABLE}
    wanted = _normalize_name(player_name)
    athlete_ids: set[str] = set()
    for team_id in team_ids:
        athletes = feed.team_athletes(team_id)
        if athletes is None:
            return {"unavailable_reason": REASON_ROSTER_UNAVAILABLE}
        athlete_ids.update(
            str(athlete.get("id") or "").strip() for athlete in athletes if wanted and wanted in _athlete_names(athlete)
        )
    athlete_ids.discard("")
    if not athlete_ids:
        return {"unavailable_reason": REASON_NOT_ON_TEAM_ROSTER}
    if len(athlete_ids) > 1:
        return {"unavailable_reason": REASON_ROSTER_AMBIGUOUS}
    athlete_id = next(iter(athlete_ids))
    rows = [entry for entry in entries if str(entry.get("playerId") or "").strip() == athlete_id]
    if not rows:
        return {"unavailable_reason": REASON_DNP_VOID, "dnp_basis": "inactive", "espn_athlete_id": athlete_id}
    if len(rows) > 1:
        return {"unavailable_reason": REASON_ROSTER_AMBIGUOUS}
    has_stats = isinstance(rows[0].get("statistics"), Mapping)
    if rows[0].get("didNotPlay") is True and not has_stats:
        return {"unavailable_reason": REASON_DNP_VOID, "dnp_basis": "did_not_play", "espn_athlete_id": athlete_id}
    if rows[0].get("didNotPlay") is False and has_stats:
        # He played; our box spells him differently. Never a void, never a zero.
        return {"unavailable_reason": REASON_PLAYED_NOT_IN_BOX}
    return {"unavailable_reason": REASON_PARTICIPATION_UNKNOWN}


def nba_status_resolver(selected_date: str, *, fetch_json=None):
    """A resolver `bet_status`/`paper_settlement` can inject, for NBA orders.

    The box is read ONCE per resolver, not once per order. `fetch_json` is the
    did-not-play check's ESPN read (a test's seam; None is the network).
    """
    from syndicate.features.shared.game_line_bet import is_game_line_market

    cache: dict[str, Any] = {}

    def box():
        if "box" not in cache:
            cache["box"] = _load_box(selected_date)
        return cache["box"]

    def absent(order: Mapping[str, Any], game: Mapping[str, Any]) -> dict[str, Any]:
        """A player not in the box of a FINAL game: did he play? (module docstring)"""
        from syndicate.features.shared import bet_status_nfl as espn

        event_id = str(game.get("event_id") or "").strip()
        if not event_id or not espn.settlement_window_open(None, order):
            return {"unavailable_reason": REASON_PLAYER_NOT_FOUND}
        if "feed" not in cache:
            cache["feed"] = espn.EspnSettlementFeed("nba", fetch_json=fetch_json)
        feed = cache["feed"]
        key = espn.settlement_memo_key("nba", event_id, order.get("player_name"))
        remembered = espn.settlement_memo_get(feed, key)
        if remembered is not None:
            return remembered
        refusal = did_not_play(feed, event_id, order.get("player_name"))
        if refusal["unavailable_reason"] in _DEFINITIVE_ROSTER_REFUSALS:
            espn.settlement_memo_put(feed, key, refusal, definitive=True)
        elif refusal["unavailable_reason"] == REASON_ROSTER_UNAVAILABLE:
            espn.settlement_memo_put(feed, key, refusal, definitive=False)
        return refusal

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
        needed = _MARKET_TO_DOUBLES.get(market)
        is_line = box_key is None and sum_keys is None and needed is None
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
            # the worst wrong answer this can give. Once the game is FINAL, ESPN
            # can say whether he sat out (`absent`).
            if stamp["is_final"]:
                return absent(order, game)
            return {"unavailable_reason": REASON_PLAYER_NOT_FOUND}
        if needed is not None:
            parts = [_as_float(row.get(key)) for key in _DOUBLE_STATS]
            if any(part is None for part in parts):
                # A missing category could be the one that reached ten.
                return {"unavailable_reason": REASON_NO_STAT}
            count = float(sum(1 for part in parts if part >= 10))
            return {**stamp, "current_value": count, "line": needed - 0.5}
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
