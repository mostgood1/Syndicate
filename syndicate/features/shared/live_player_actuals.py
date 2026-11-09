"""Live box-score ACTUALS for NHL and NFL player props on the Layer 2 board. Shown, never priced.

WHY THIS EXISTS `[2026-11-09, lane nhl-nfl-live-prop-actuals]`. Measured on the served board
2026-11-09 01:31Z, SNF TB@CHI and PIT@ANA in play: live NHL props **0 of 29** and live NFL props
**0 of 140** had a Live actual or a Live proj. `board_enrichment.attach_live_projections_for_sport`
serves only `_LIVE_PROP_SPORTS` (mlb / wnba / soccer, plus nba behind its switch), and no NHL or NFL
producer published per-player live numbers: `nhl/live_resim.py` publishes the moneyline only, and
NFL's re-sim is team-level.

THE ACTUAL IS THE CHEAP, HONEST HALF. A player's stat so far is a box-score count. It needs no model,
so it can be shown on a live row long before any live player model is graded.

WHAT IS PUBLISHED, AND BY WHOM. Each live game in the sport's live snapshot carries a
`livePlayerStats` block (`player_stats_block` below). The block is written on a WORKER by the tick
that already owns the live game: NHL's on live-odds-worker (`nhl/live_resim.build_live_lens_snapshot`,
`live/nhl_live_lens.json`), NFL's on refresh-worker (`nfl/live_resim.build_live_lens_snapshot`,
`live/nfl_live_resim.json`). The board join below only READS that block -- it never fetches.

THE SAME FIELD THE GRADER SETTLES ON. The market -> box-field map, the box parser and the player
matcher are the settlement graders' own (`bet_status_nhl` / `bet_status_nfl`), not a copy. So the
number in the Actual column is the number paper settlement would read for that bet at that moment,
and a market the grader cannot settle gets no Actual either.

WHAT THIS NEVER DOES. It writes `actual_so_far` and the display-only flags, and nothing the edge, the
ranking or `live_edge_policy` reads: no `model_prob_over`, no `live_aware`, no `basis` change. A live
NHL/NFL row keeps the edge suppression it has today (0 of 169 carried an edge at 01:31Z). Pricing
live NHL/NFL props is a separate decision that needs a graded live player model first.

REFUSALS, BY NAME. A row gets no Actual when: its game has no block (no box yet, or the producer did
not run); the block is stale (`MAX_BLOCK_AGE_SECONDS`); the market has no box field; the player is
absent from the box or matches two players; or the stat is not the player's role (saves on a skater).
An absent player is NOT shown as 0: ESPN lists a football player only once he records a stat, and a
name the matcher misses would otherwise read as a confident zero all game.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Callable

# Which sports reach this join is decided in ONE place, `board_enrichment._LIVE_PLAYER_ACTUAL_SPORTS`.

# The snapshot key a live game carries its block under.
BLOCK_KEY = "livePlayerStats"

SOURCE_NHL_BOX = "nhl_gamecenter_boxscore"
SOURCE_ESPN_SUMMARY = "espn_summary_boxscore"

# A block older than this at board-build time is refused, not shown. The board is rebuilt every
# ~9 min; NHL's tick runs every ~60 s and NFL's every 300 s, so a fresh block is never near this.
# A block past it means the producer stopped, and a stopped producer's number reads as "current"
# on a live row -- the fabricated-live-cell failure `layer2_board._live_projection_columns` names.
MAX_BLOCK_AGE_SECONDS = 20 * 60

# NHL box fields kept per role. Exactly `bet_status_nhl.parse_boxscore_players`' fields.
_NHL_SKATER_FIELDS = ("goals", "assists", "points", "sog", "blocked_shots")
_NHL_GOALIE_FIELDS = ("saves", "shots_against")

# Roster names per NHL game, kept for the process. `rosterSpots` (full first/last names) is the
# play-by-play payload's, which grows to several hundred KB late in a game; the dressed roster does
# not change once the game is under way, so it is fetched ONCE per game rather than every tick.
_NHL_ROSTER_NAMES: dict[str, dict[str, dict[str, str]]] = {}
_NHL_ROSTER_LOCK = threading.Lock()
_NHL_ROSTER_MAX = 64


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_instant(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def player_stats_block(
    *,
    source: str,
    players: Sequence[Mapping[str, Any]],
    game_id: Any,
    as_of: str | None = None,
    game_state: Any = None,
) -> dict[str, Any]:
    """The `livePlayerStats` block one live game carries. The contract the join reads."""
    return {
        "source": source,
        "gameId": str(game_id or ""),
        "gameState": str(game_state or ""),
        "asOf": as_of or utc_now_iso(),
        "players": [dict(player) for player in players],
    }


# ---------------------------------------------------------------------------
# PRODUCERS. Network reads, so WORKER-ONLY: the join below never calls them.
# ---------------------------------------------------------------------------


def nhl_live_player_stats(
    game_pk: Any,
    *,
    fetch_json: Callable[[str], Any] | None = None,
    game_state: Any = None,
) -> dict[str, Any] | None:
    """One live NHL game's box as a `livePlayerStats` block, or None if the box could not be read.

    The box (`/v1/gamecenter/{id}/boxscore`) lists every dressed player with zeros, so a player absent
    from it was not dressed. Names come from the game's `rosterSpots` (fetched once per game, see
    `_NHL_ROSTER_NAMES`); a player missing there keeps the box's own "C. McDavid", which
    `bet_status_nhl.match_player` matches by initial + last name, uniquely or not at all -- exactly the
    grader's fallback (`NhlFeed.box`).
    """
    from syndicate.features.shared import bet_status_nhl as nhl

    pk = str(game_pk or "").strip()
    if not pk:
        return None
    fetch = fetch_json or nhl._default_fetch_json
    base = nhl._nhle_base()
    try:
        stats = nhl.parse_boxscore_players(fetch(f"{base}/gamecenter/{pk}/boxscore"))
    except Exception:
        stats = None
    if not stats or not stats.get("players"):
        return None

    with _NHL_ROSTER_LOCK:
        names = _NHL_ROSTER_NAMES.get(pk)
    if names is None:
        try:
            roster = nhl.parse_roster_spots(fetch(f"{base}/gamecenter/{pk}/play-by-play"))
        except Exception:
            roster = None
        if roster is not None and roster.get("names"):
            names = dict(roster["names"])
            with _NHL_ROSTER_LOCK:
                _NHL_ROSTER_NAMES[pk] = names
                while len(_NHL_ROSTER_NAMES) > _NHL_ROSTER_MAX:
                    _NHL_ROSTER_NAMES.pop(next(iter(_NHL_ROSTER_NAMES)))
    names = names or {}

    players: list[dict[str, Any]] = []
    for row in stats["players"]:
        name = names.get(row.get("player_id")) or {}
        if name.get("first") or name.get("last"):
            first, last = name.get("first", ""), name.get("last", "")
        else:
            first, _, last = str(row.get("name_abbrev") or "").partition(" ")
        goalie = row.get("role") == "goalie"
        fields = _NHL_GOALIE_FIELDS if goalie else _NHL_SKATER_FIELDS
        players.append({
            "playerName": f"{first} {last}".strip(),
            "first": first,
            "last": last,
            "playerId": row.get("player_id"),
            "team": row.get("team_abbr"),
            "role": row.get("role"),
            "toiSeconds": row.get("toi_seconds"),
            "stats": {field: row.get(field) for field in fields},
        })
    return player_stats_block(
        source=SOURCE_NHL_BOX,
        players=players,
        game_id=pk,
        game_state=game_state or stats.get("state"),
    )


def nfl_live_player_stats(event_id: Any, *, game_state: Any = None) -> dict[str, Any] | None:
    """One live NFL game's ESPN box as a `livePlayerStats` block, or None if it could not be read.

    `fetch_player_stat_rows` is the SETTLEMENT read: every athlete in the box, every field, real zeros
    kept. Never the card's filtered display rows, which drop a player with no yards and no touchdown.
    """
    from syndicate.features.nfl.live_player_box import fetch_player_stat_rows

    event = str(event_id or "").strip()
    if not event:
        return None
    rows = fetch_player_stat_rows(event)
    if not rows:
        return None
    players = [
        {
            "playerName": row.get("player_name"),
            "team": row.get("team_abbr"),
            "stats": {key: value for key, value in row.items() if key not in ("player_name", "team_abbr")},
        }
        for row in rows
        if isinstance(row, Mapping)
    ]
    return player_stats_block(source=SOURCE_ESPN_SUMMARY, players=players, game_id=event, game_state=game_state)


# ---------------------------------------------------------------------------
# THE JOIN. Reads the published block only. Runs in the Layer 2 build (refresh-worker).
# ---------------------------------------------------------------------------


def _game_key(sport: str, away: Any, home: Any) -> tuple[str, str] | None:
    """Both clubs, canonical. The snapshot and the grid name clubs differently.

    Measured 2026-11-09: NHL's re-sim snapshot says `'Penguins' @ 'Ducks'` (the `/v1/score` short
    name) while every board row says `'Pittsburgh Penguins' @ 'Anaheim Ducks'`. `canonical_team`
    resolves both to `pittsburgh penguins`; a plain lowercase compare matches neither.
    """
    from syndicate.features.shared.team_aliases import canonical_team

    def one(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return canonical_team(sport, text) or " ".join(text.lower().split())

    a, h = one(away), one(home)
    return (a, h) if a and h else None


def _market_field(sport: str, market: Any) -> str | None:
    """The box field that settles this market, by the GRADER's own map, or None."""
    if sport == "nhl":
        from syndicate.features.shared.bet_status_nhl import _prop_market

        field, _anytime = _prop_market(market)
        return field
    if sport == "nfl":
        from syndicate.features.shared.bet_status_nfl import _norm, prop_field

        return prop_field(_norm(market))
    return None


def _match_player(sport: str, players: list[Mapping[str, Any]], name: Any) -> tuple[Mapping[str, Any] | None, str]:
    """`(player, "")` or `(None, reason)`, by the GRADER's own matcher."""
    if sport == "nhl":
        from syndicate.features.shared.bet_status_nhl import match_player

        rows = [
            {"player_name": p.get("playerName"), "first": p.get("first"), "last": p.get("last"), "_p": p}
            for p in players
        ]
        row, why = match_player(rows, name)
        if row is not None:
            return row["_p"], ""
        return None, "absent" if why == "absent" else "ambiguous_or_unmatched"
    from syndicate.features.shared.bet_status_nfl import match_box_player

    rows = [{"player_name": p.get("playerName"), "_p": p} for p in players]
    row, why = match_box_player(rows, name)
    if row is not None:
        return row["_p"], ""
    return None, "absent" if why == "absent" else "ambiguous_or_unmatched"


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def attach_live_player_actuals(
    grid: Sequence[Any],
    snapshot: Mapping[str, Any] | None,
    *,
    sport: str,
    now: datetime | None = None,
    max_age_seconds: float = MAX_BLOCK_AGE_SECONDS,
) -> dict[str, Any]:
    """Write a display-only Live actual onto live NHL/NFL prop rows. Returns a coverage payload.

    The counters use `attach_live_projections`' names where the meaning is the same, so the
    existing `LIVE_PROJECTION_JOIN` line reads them: `display_only` is the rows given an Actual,
    `projected` stays 0 (this writes no Live proj.), `edged` is 0 by construction.
    """
    from syndicate.features.shared.probability_refusal import refuse_published_certainty
    from syndicate.features.shared.segment_actuals import FULL_GAME_SEGMENT, order_segment

    sport = str(sport or "").strip().lower()
    instant = now or datetime.now(timezone.utc)
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    duplicate_pairs: set[tuple[str, str]] = set()
    games_seen = 0
    games_with_block = 0
    players_indexed = 0
    games = (snapshot or {}).get("games") if isinstance(snapshot, Mapping) else None
    for game in games if isinstance(games, Sequence) else ():
        if not isinstance(game, Mapping):
            continue
        games_seen += 1
        block = game.get(BLOCK_KEY)
        if not isinstance(block, Mapping) or not isinstance(block.get("players"), list):
            continue
        key = _game_key(sport, game.get("away_name"), game.get("home_name"))
        if key is None:
            continue
        games_with_block += 1
        players_indexed += len(block["players"])
        if key in index:
            # Two live games under one club pair (a doubleheader shape). Neither is trusted.
            duplicate_pairs.add(key)
        index[key] = block
    for key in duplicate_pairs:
        index.pop(key, None)

    coverage: dict[str, Any] = {
        "supported": True,
        "join": "live_player_actuals",
        "rows_live_considered": 0,
        "rows_live_projected": 0,
        "rows_live_edged": 0,
        "rows_live_display_only": 0,
        "rows_live_actual": 0,
        "snapshot_games": games_seen,
        "live_games_in_snapshot": games_with_block,
        "snapshot_rows_indexed": players_indexed,
        "games_ambiguous": len(duplicate_pairs),
        "miss_no_game": 0,
        "miss_stale_block": 0,
        "miss_segment": 0,
        "miss_no_market_field": 0,
        "miss_no_player": 0,
        "miss_player_absent": 0,
        "miss_player_ambiguous": 0,
        "miss_stat_unavailable": 0,
        "unmatched_samples": [],
    }
    if not games_with_block:
        coverage["reason"] = (
            f"no {sport} live game in the snapshot carries {BLOCK_KEY} "
            "(no game in play, or the producer is not on this deploy)"
        )

    samples: list[dict[str, Any]] = coverage["unmatched_samples"]

    def miss(counter: str, row: Mapping[str, Any]) -> None:
        coverage[counter] += 1
        if len(samples) < 8:
            samples.append({"why": counter, "player": row.get("player_name"), "market": row.get("market")})

    for row in grid:
        if not isinstance(row, Mapping) or str(row.get("kind") or "") != "prop":
            continue
        game = row.get("game") if isinstance(row.get("game"), Mapping) else {}
        if str(game.get("state") or "").strip().lower() not in {"live", "in_progress"}:
            continue
        coverage["rows_live_considered"] += 1
        key = _game_key(
            sport,
            row.get("away_team") or game.get("away_team"),
            row.get("home_team") or game.get("home_team"),
        )
        block = index.get(key) if key else None
        if block is None:
            miss("miss_no_game", row)
            continue
        as_of = _parse_instant(block.get("asOf"))
        if as_of is None or (instant - as_of).total_seconds() > float(max_age_seconds):
            miss("miss_stale_block", row)
            continue
        if order_segment(row) != FULL_GAME_SEGMENT:
            # The box is whole-game. A period/quarter prop shown the full-game count would show
            # the wrong quantity -- the grader refuses it for the same reason.
            miss("miss_segment", row)
            continue
        field = _market_field(sport, row.get("market"))
        if field is None:
            miss("miss_no_market_field", row)
            continue
        if not str(row.get("player_name") or "").strip():
            miss("miss_no_player", row)
            continue
        player, why = _match_player(sport, block["players"], row.get("player_name"))
        if player is None:
            miss("miss_player_absent" if why == "absent" else "miss_player_ambiguous", row)
            continue
        stats = player.get("stats") if isinstance(player.get("stats"), Mapping) else {}
        value = _as_float(stats.get(field))
        if value is None:
            # A goalie's `goals` / a skater's `saves` is absent from that role's stats by
            # construction, so a role mismatch lands here too.
            miss("miss_stat_unavailable", row)
            continue

        shown = dict(row.get("projection") or {})
        shown.update({
            "actual_so_far": value,
            "live_display_only": True,
            "live_actual_source": block.get("source"),
            "live_actual_as_of": block.get("asOf"),
            "live_actual_field": field,
        })
        row["projection"] = refuse_published_certainty(shown)  # type: ignore[index]
        coverage["rows_live_display_only"] += 1
        coverage["rows_live_actual"] += 1

    return coverage
