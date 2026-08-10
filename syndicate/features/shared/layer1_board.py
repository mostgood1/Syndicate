"""L1 board — ONE sport-generic presentation of the Layer 1 market grid (`#329`).

WHY THIS EXISTS. Layer 1 had eight implementations of the same idea. Measured on
production 2026-08-10, `/<sport>/api/market-board` against `/api/board/book-grid`
for the same date:

    sport    page  api    games  board rows   grid rows
    mlb       200  200       10         531         839
    nba       200  200        0           0           0   out of season
    wnba      200  200        2         228         202
    nhl       404  404        -           -           0   NO ROUTE AT ALL
    nfl       200  200       16          84       1,381   16x gap
    ncaaf     200  200       16           0           0   games, zero rows
    ncaab     404  404        -           -           0   NO ROUTE AT ALL
    soccer    200  200        1           1           7

Six bespoke builders (`build_mlb_market_board`, `build_nba_market_board`,
`build_ncaaf_market_board`, `build_nfl_market_board`,
`build_nfl_preseason_market_board`, `build_soccer_market_board`,
`build_wnba_market_board`) and two sports with nothing. Adding a seventh and
eighth builder would have made the divergence permanent.

The grid is already sport-generic -- `/api/board/book-grid?sport=` serves all
eight from one code path -- and `layer2_board.build_layer2_rows` ALREADY consumes
it. So the grid is Layer 1's row contract in fact, and the per-sport boards are a
*view* of it. This module is that view, written once.

THE ROW MODEL IS THE GRID'S, AND THAT IS THE POINT
--------------------------------------------------
A grid row is one market INSTANCE with every side on it (`sides`, `cells[book][side]`,
`best`, `consensus`). The per-sport boards emit one row per side instead, so a
total arrives as two rows both stamped `model_side: "over"`. Merging them is the
difference between "over 8.5 at -101 / under 8.5 at -119, six books" being one
readable line and being two rows you have to pair up by eye.

The vocabularies also disagree, three ways, and translating them is `#329`'s job
rather than something each consumer redoes:

    concept        grid              per-sport board
    game vs prop   kind              market_type
    period         segment "full"    period "full_game"
    market name    h2h / totals      Moneyline / Total

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not fetch, and it does not compute a projection. It reshapes an ALREADY
ENRICHED grid -- `board_enrichment` attaches `game`, `projection` and
`modelled_fair` upstream (`#328`), and a grid that arrives without them produces
a board that says so rather than one that looks sim-less.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

# THE SHARD IS KEYED BY CAPTURE DATE, NOT BY GAME DATE, and that difference is
# visible on the board. `book_quotes/<date>.jsonl` holds every quote OBSERVED
# that day, including quotes for fixtures weeks out, so a grid built from it is
# "what we saw today", not "today's slate".
#
# Measured 2026-08-10 by running this builder over the live production grid:
# NFL's 1,381 rows grouped into **288 games**, because preseason capture covers
# the whole forward schedule. MLB looked right (10 games) only because MLB
# captures today's slate and little else -- so the defect was invisible on the
# reference sport and obvious on the next one.
#
# Rows for other dates are EXCLUDED and COUNTED, never silently dropped: a board
# that quietly discards rows and a board whose sport genuinely has no slate are
# the same empty board otherwise.
_BOARD_TZ = os.environ.get("SYNDICATE_BOARD_TZ", "America/Chicago")

# The three states a game can be in, plus the one that matters most here.
#
# `unknown` IS A STATE, not a synonym for pregame. A row whose game state failed
# to join has an unknown state, and folding it into `pregame` would put a
# possibly-settled market on the pregame board -- which is exactly the defect
# `#298`/`#300` fixed for the staleness floor ("an unknown game state must FAIL
# the floor, not skip it"). The same rule applies to routing: unknown must land
# in its own bucket, be counted, and be visible.
BOARD_STATES = ("live", "pregame", "final", "unknown")


def _row_state(row: Mapping[str, Any]) -> str:
    game = row.get("game")
    if not isinstance(game, dict):
        return "unknown"
    state = str(game.get("state") or "").strip().lower()
    return state if state in BOARD_STATES else "unknown"


def _row_is_enriched(row: Mapping[str, Any]) -> bool:
    return isinstance(row.get("game"), dict)


def _game_key(row: Mapping[str, Any]) -> str:
    """Group rows into games.

    `event_id` first because it is the grid's own identity and both game lines
    and player props on the same fixture carry it. The team pair is the fallback
    for any producer that omits it -- never a synthesized id, because two rows
    that fall back to different keys would split one game into two cards and the
    board would look like it had more fixtures than the slate.
    """
    event_id = str(row.get("event_id") or "").strip()
    if event_id:
        return event_id
    away = str(row.get("away_team") or "").strip()
    home = str(row.get("home_team") or "").strip()
    if away or home:
        return f"{away}@{home}"
    return "unknown_game"


def _card_for(row: Mapping[str, Any]) -> dict[str, Any]:
    game = row.get("game") if isinstance(row.get("game"), dict) else {}
    return {
        "event_id": str(row.get("event_id") or "") or None,
        "away_team": row.get("away_team"),
        "home_team": row.get("home_team"),
        "matchup": game.get("matchup") or _fallback_matchup(row),
        "state": _row_state(row),
        "start_time_utc": game.get("start_time_utc") or row.get("commence_time"),
        "status_token": game.get("status_token"),
        "away_score": game.get("away_score"),
        "home_score": game.get("home_score"),
        # Counted, not listed: a card is a summary and the rows are right there.
        "market_count": 0,
        "game_market_count": 0,
        "prop_market_count": 0,
        "rows_with_projection": 0,
    }


def _row_local_date(row: Mapping[str, Any], tz_name: str) -> str | None:
    """The row's game date in the board's timezone, or None if unknowable.

    Reads `game.start_time_utc` first (the scoreboard's own kickoff, joined by
    `attach_game_state`) and falls back to the grid's `commence_time`. None when
    neither parses -- and an unknown date is NEVER treated as "matches", because
    a row that cannot be dated would then appear on every date's board.
    """
    game = row.get("game") if isinstance(row.get("game"), dict) else {}
    raw = str(game.get("start_time_utc") or row.get("commence_time") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except Exception:
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _fallback_matchup(row: Mapping[str, Any]) -> str | None:
    away = str(row.get("away_team") or "").strip()
    home = str(row.get("home_team") or "").strip()
    if away and home:
        return f"{away} @ {home}"
    return None


def build_layer1_board(
    grid: Iterable[Mapping[str, Any]],
    *,
    sport: str,
    selected_date: str,
    grid_absent_reason: str | None = None,
) -> dict[str, Any]:
    """Group an enriched grid into per-game cards, partitioned by game state.

    `grid_absent_reason` is threaded from the caller rather than guessed at.
    A SPORT WITH NO ROWS MUST SAY WHY (`#296`): out of season, no shard captured,
    and "the join dropped everything" are three different facts that render as
    the same empty board, and only the caller knows which one it is.
    """
    all_rows = [row for row in grid if isinstance(row, Mapping)]

    # Date scoping, before anything else. See `_BOARD_TZ` -- the shard is keyed
    # by capture date, so "every row in today's shard" is not "today's slate".
    wanted_date = str(selected_date or "").strip()
    rows: list[Mapping[str, Any]] = []
    other_dates: dict[str, int] = {}
    undated_rows = 0
    for row in all_rows:
        row_date = _row_local_date(row, _BOARD_TZ)
        if row_date is None:
            # Undated rows are held OUT, not let through. A row that cannot be
            # dated would otherwise appear on every date's board at once.
            undated_rows += 1
            continue
        if wanted_date and row_date != wanted_date:
            other_dates[row_date] = other_dates.get(row_date, 0) + 1
            continue
        rows.append(row)

    cards: dict[str, dict[str, Any]] = {}
    rows_by_game: dict[str, list[Mapping[str, Any]]] = {}
    state_counts = {state: 0 for state in BOARD_STATES}
    enriched_rows = 0
    projected_rows = 0

    for row in rows:
        key = _game_key(row)
        if key not in cards:
            cards[key] = _card_for(row)
            rows_by_game[key] = []
        card = cards[key]
        rows_by_game[key].append(row)

        card["market_count"] += 1
        if str(row.get("kind") or "").lower() == "prop":
            card["prop_market_count"] += 1
        else:
            card["game_market_count"] += 1
        if isinstance(row.get("projection"), dict):
            card["rows_with_projection"] += 1
            projected_rows += 1
        if _row_is_enriched(row):
            enriched_rows += 1

    for key, card in cards.items():
        state_counts[card["state"]] += 1

    games = [
        {**card, "rows": rows_by_game[key]}
        for key, card in sorted(
            cards.items(),
            # Live first, then pregame by start time, then everything else. A
            # board people read top-down should lead with the game that can move.
            key=lambda item: (
                {"live": 0, "pregame": 1, "unknown": 2, "final": 3}.get(item[1]["state"], 4),
                str(item[1].get("start_time_utc") or ""),
                str(item[1].get("matchup") or ""),
            ),
        )
    ]

    # The enrichment state of the WHOLE board, so a sim-less board is
    # attributable. `#328` made the grid carry projections; a grid that arrives
    # without them means the artifact predates that or the join found nothing,
    # and those must not render identically.
    if not rows:
        enrichment = "no_rows"
    elif enriched_rows == 0:
        enrichment = "grid_not_enriched"
    elif projected_rows == 0:
        enrichment = "enriched_no_projections"
    else:
        enrichment = "enriched"

    payload: dict[str, Any] = {
        "sport": str(sport or "").strip().lower(),
        "date": str(selected_date or "").strip(),
        "games": games,
        "counts": {
            "games": len(games),
            "rows": len(rows),
            "rows_enriched": enriched_rows,
            "rows_with_projection": projected_rows,
            "by_state": state_counts,
            # What the date scope removed, so a thin board is attributable to
            # scoping rather than read as a thin slate.
            "rows_in_grid": len(all_rows),
            "rows_other_dates": sum(other_dates.values()),
            "rows_undated": undated_rows,
        },
        "date_scope": {
            "timezone": _BOARD_TZ,
            # Top few, so "which day did they belong to" is answerable without
            # dumping the whole distribution onto every response.
            "other_dates": dict(sorted(other_dates.items(), key=lambda kv: (-kv[1], kv[0]))[:7]),
        },
        "enrichment": enrichment,
    }
    if not rows:
        # Never an empty list with no explanation. `#296`: a sport with no quotes
        # must say why, not vanish. "The grid was empty" and "the grid was full
        # of other days" are different facts with different fixes -- the first is
        # a capture question, the second is a scoping one -- so they get
        # different reasons even though both render as an empty board.
        if all_rows and not undated_rows:
            payload["empty_reason"] = "grid_rows_all_for_other_dates"
        elif all_rows:
            payload["empty_reason"] = "grid_rows_undated_or_other_dates"
        else:
            payload["empty_reason"] = grid_absent_reason or "no_grid_rows_for_sport_date"
    return payload


def partition_board_by_state(board: Mapping[str, Any], state: str) -> dict[str, Any]:
    """The pregame board and the live board, from one build.

    Two views over ONE payload rather than two fetches: they are the same slate
    filtered, and a game that goes live must LEAVE the pregame board in the same
    instant it joins the live one. Deriving both from a single grouping is what
    makes that atomic -- two independent queries can and will disagree across
    the transition, showing a game on both boards or neither.
    """
    wanted = str(state or "").strip().lower()
    if wanted not in BOARD_STATES:
        raise ValueError(f"unknown board state: {state!r}; expected one of {BOARD_STATES}")
    games = [game for game in (board.get("games") or []) if game.get("state") == wanted]
    out = dict(board)
    out["games"] = games
    out["view"] = wanted
    out["counts"] = {
        **(board.get("counts") or {}),
        "games_in_view": len(games),
        "rows_in_view": sum(len(game.get("rows") or []) for game in games),
    }
    return out
