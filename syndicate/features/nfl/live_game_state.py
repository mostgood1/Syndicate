"""Real NFL game state (live / final / score / clock / kickoff) from ESPN.

WHY THIS EXISTS -- measured in production 2026-08-13, during the 6-game
preseason slate:

    DET @ CIN   117 live in-game market rows, odds 1.3 min fresh,
                state=pregame, score=-, status_token=''
    by_state    {"pregame": 6, "live": 0, "final": 0}

while ESPN reported two of those games genuinely in Q1 (GB @ PIT 3-0,
7:53 left). The board was taking live in-game odds on games it believed
had not kicked off.

THE CAUSE IS ONE MISSING JOIN, NOT FIVE BROKEN SURFACES.
`_NFLDataProvider.games()` (blueprints/home.py) hands `build_game_chips`
the week-scoped projection cards, and those cards carry no game state of
any kind: `status` is the plain string "Preseason Week 1", there is no
`live_state`, no score, no clock, no kickoff time. So
`game_chip_scoreboard._game_flags` reads `(is_live=False, is_final=False)`
for every NFL game and `build_game_chip` stamps `state="pregame"` --
by construction, forever. Everything downstream inherits that one value:

    board_enrichment.attach_game_state  -> row["game"]["state"]
    layer1_board                        -> counts.by_state
    publication_adapter                 -> shared_game_state / shared_is_live
    nfl/live_lens.py                    -> "live" rows that are never live

THE FIX GOES IN THE CARD, NOT IN THE CONSUMERS. `#334`'s lesson is to
enumerate the callers and fix the choke point they all share, because a
fix applied at one call site leaves the others silently broken. Both
`publication_adapter._shared_game_state` (reads `live_state` for
live/final/period/clock/startTime) and `game_chip_scoreboard._game_flags`
(reads `live_state.in_progress` / `live_state.final`) already consume a
`live_state` mapping -- neither NFL card builder ever set one. Populating
it fixes every consumer at once and touches zero call sites.

JOIN KEY. ESPN's event id IS the card's `gamePk` on this board -- verified
on the live slate: the cards carry 401873272/401873275/... and ESPN's
scoreboard returns those same ids. So this is an exact id join, with a
(away_abbr, home_abbr) fallback for any row whose id is absent. No alias
guessing.

ABSENCE IS NOT PREGAME. If the fetch fails, or a game is simply not in
ESPN's response, this stamps NOTHING and the card keeps whatever it had.
An unknown state must never be mapped onto the confident-looking branch
(ledger: "unknown must not default permissive") -- a wrong `pregame` on a
game that has finished is exactly the failure being fixed here, and it
would be worse coming from the fix than from the gap.

DO NOT ADD A BROWSER USER-AGENT. ESPN returns HTTP 403 to browser-spoof
User-Agents from Render's outbound IP -- confirmed 2026-08-05 across three
header variants, and again from this developer machine 2026-08-13, where
PowerShell's default UA got 403 on the same URL that urllib's honest
default fetched fine. `urllib.request.Request(url)` with no headers is
load-bearing, not an oversight. See
scripts/fetch_espn_live_status_for_date.py for the original probe.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Any, Mapping

from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path


_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# ESPN season types: 1 = preseason, 2 = regular season, 3 = postseason.
SEASONTYPE_PRESEASON = 1
SEASONTYPE_REGULAR = 2

# One ESPN call serves a whole week (16 games on a preseason week), so the
# per-request cost is one HTTP GET amortised across every card on the board.
# The TTL is deliberately short: this is a LIVE signal, and a board that is
# 60s stale during a game is the defect this module exists to remove. Long
# enough that a burst of requests (cards + chips + board, same page load)
# collapses to a single fetch.
_CACHE_TTL_SECONDS = 20.0
_FETCH_TIMEOUT_SECONDS = 6.0

_cache: dict[tuple[int, int, int], tuple[float, dict[str, dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _score_or_none(value: Any) -> int | None:
    return _int_or_none(value)


def _fetch_scoreboard(season: int, seasontype: int, week: int) -> dict[str, Any] | None:
    url = f"{_SCOREBOARD_URL}?seasontype={int(seasontype)}&week={int(week)}&year={int(season)}"
    # See the module docstring: no custom headers. urllib's own default
    # User-Agent is what ESPN accepts from Render.
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=_FETCH_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        # Fail SOFT and SILENT-to-the-caller: a scoreboard outage must not
        # take down the cards board. The caller distinguishes "no state" from
        # "not live" by getting an empty index, never a fabricated one.
        return None


def _state_from_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    event_id = _text(event.get("id"))
    competitions = event.get("competitions") if isinstance(event.get("competitions"), list) else []
    competition = competitions[0] if competitions and isinstance(competitions[0], Mapping) else {}
    competitors = competition.get("competitors") if isinstance(competition.get("competitors"), list) else []

    away_row: Mapping[str, Any] = {}
    home_row: Mapping[str, Any] = {}
    for row in competitors:
        if not isinstance(row, Mapping):
            continue
        side = _text(row.get("homeAway")).lower()
        if side == "away":
            away_row = row
        elif side == "home":
            home_row = row
    if not away_row or not home_row:
        return None

    away_team = away_row.get("team") if isinstance(away_row.get("team"), Mapping) else {}
    home_team = home_row.get("team") if isinstance(home_row.get("team"), Mapping) else {}
    away_abbr = _text(away_team.get("abbreviation")).upper()
    home_abbr = _text(home_team.get("abbreviation")).upper()

    status = event.get("status") if isinstance(event.get("status"), Mapping) else {}
    status_type = status.get("type") if isinstance(status.get("type"), Mapping) else {}
    espn_state = _text(status_type.get("state")).lower()

    in_progress = espn_state == "in"
    # Both signals, not just `completed`: a game can be `state=post` with
    # `completed` absent on some payload shapes, and reading only one of them
    # would leave a finished game rendering as live all night.
    final = bool(status_type.get("completed")) or espn_state == "post"

    # A 0-0 "score" on a game that has not started is a schedule placeholder,
    # not a result. Emitting it would put 0-0 on every pregame card.
    away_pts = _score_or_none(away_row.get("score")) if (in_progress or final) else None
    home_pts = _score_or_none(home_row.get("score")) if (in_progress or final) else None

    return {
        "event_id": event_id,
        "away_abbr": away_abbr,
        "home_abbr": home_abbr,
        "in_progress": in_progress,
        "final": final,
        # `period`/`clock` are what game_chip_scoreboard._live_status_token
        # turns into "Q1 8:05" for football, and what
        # publication_adapter._shared_game_state surfaces on the card.
        "period": _int_or_none(status.get("period")) if (in_progress or final) else None,
        "clock": _text(status.get("displayClock")) if in_progress else "",
        "status": _text(status_type.get("shortDetail")) or _text(status_type.get("description")),
        "detail": _text(status_type.get("detail")) or _text(status_type.get("shortDetail")),
        # The cards board has no per-game kickoff time at all today (measured:
        # every game returned startTime='' ), so a week-scoped board cannot say
        # which of its 16 games is tonight. This supplies it.
        "start_time": _text(event.get("date")),
        "away_pts": away_pts,
        "home_pts": home_pts,
        # DOWN / DISTANCE / FIELD POSITION WERE ALREADY IN THIS PAYLOAD AND WERE
        # BEING THROWN AWAY. `_fetch_scoreboard` returns the whole scoreboard
        # JSON, whose competitions carry a `situation` block; nothing in `nfl/`,
        # `ncaaf/` or `football/` read it -- the only `down` references in the
        # tree are the sim engine's internal `play_state` and the historical
        # loaders, neither of which is on the live path. So this costs no extra
        # fetch and no extra credit: it stops discarding what we already have.
        #
        # Kept RAW and only on a live game. A `situation` on a finished or
        # unstarted game is a stale or placeholder artefact of the feed, and
        # storing it would make "3rd and 7" render on a game that ended hours
        # ago -- the same class of bug as the 0-0 placeholder score above.
        "situation": (competition.get("situation") if in_progress and isinstance(competition.get("situation"), Mapping) else None),
    }


def nfl_game_state_index(season: int, week: int, *, seasontype: int) -> dict[str, dict[str, Any]]:
    """Per-game ESPN state for one NFL week, keyed by ESPN event id.

    Also keyed by `"{AWAY}@{HOME}"` so a card whose `gamePk` is not an ESPN
    event id can still resolve. Returns `{}` on any failure -- callers must
    treat an empty index as "state unknown", never as "nothing is live".
    """
    key = (int(season), int(seasontype), int(week))
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return dict(cached[1])

    warn_if_compute_in_request_path("nfl_espn_game_state_fetch")
    payload = _fetch_scoreboard(int(season), int(seasontype), int(week))
    index: dict[str, dict[str, Any]] = {}
    events = payload.get("events") if isinstance(payload, Mapping) else None
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, Mapping):
                continue
            state = _state_from_event(event)
            if state is None:
                continue
            if state["event_id"]:
                index[state["event_id"]] = state
            if state["away_abbr"] and state["home_abbr"]:
                index.setdefault(f"{state['away_abbr']}@{state['home_abbr']}", state)

    # An empty result is cached too, so a scoreboard outage costs one fetch
    # per TTL rather than one per request. It is still an EMPTY index, so it
    # cannot be mistaken for a confident "everything is pregame".
    with _cache_lock:
        _cache[key] = (now, index)
        if len(_cache) > 16:
            oldest = min(_cache, key=lambda item: _cache[item][0])
            _cache.pop(oldest, None)
    return dict(index)


def _lookup(index: Mapping[str, Mapping[str, Any]], game: Mapping[str, Any]) -> Mapping[str, Any] | None:
    game_pk = _text(game.get("gamePk"))
    if game_pk and game_pk in index:
        return index[game_pk]
    away = _text((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), Mapping) else "").upper()
    home = _text((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), Mapping) else "").upper()
    if away and home:
        return index.get(f"{away}@{home}")
    return None


def attach_nfl_live_game_state(
    games: list[dict[str, Any]], index: Mapping[str, Mapping[str, Any]]
) -> dict[str, int]:
    """Stamp `live_state` (and a real kickoff `startTime`) onto NFL cards.

    Returns coverage counts. `matched` is reported separately from `live` and
    `final` on purpose: "the join found nothing" and "the join worked and
    every game is pregame" produce the same board and are different defects
    (ledger: a pooled counter whose populations differ in eligibility cannot
    be read).
    """
    matched = 0
    live = 0
    final = 0
    if not index:
        return {"matched": 0, "live": 0, "final": 0, "games": len(games), "index": 0}

    for game in games:
        if not isinstance(game, dict):
            continue
        state = _lookup(index, game)
        if state is None:
            # Deliberately leaves the card untouched -- see the module
            # docstring on absence.
            continue
        matched += 1
        live_state: dict[str, Any] = {
            "in_progress": bool(state.get("in_progress")),
            "final": bool(state.get("final")),
            "status": state.get("status") or "",
            "source": "espn_scoreboard",
        }
        if state.get("period") is not None:
            live_state["period"] = state["period"]
        if state.get("clock"):
            live_state["clock"] = state["clock"]
        if state.get("away_pts") is not None:
            live_state["away_pts"] = state["away_pts"]
        if state.get("home_pts") is not None:
            live_state["home_pts"] = state["home_pts"]
        # GAME SHAPE -- the state this game is in, kept instead of discarded.
        # Lane `game-shape-capture`; contract in `shared/game_shape.py`.
        # Nothing downstream can currently ask WHEN a football projection is
        # wrong (early vs late, one score vs three, backed up vs red zone),
        # only whether it is wrong on average, because the conditioning
        # variable is never written down.
        #
        # Function-local import and a bare except on purpose: this is
        # instrumentation for a measurement that does not exist yet, and the
        # cards board is the product. A failure here must cost the shape block
        # and nothing else. Same rule `live_gameline_ledger` states for its own
        # append path.
        try:
            from syndicate.features.shared.game_shape import football_game_shape

            live_state["game_shape"] = football_game_shape(
                live_state, sport="nfl", situation=state.get("situation")
            )
        except Exception:
            live_state["game_shape"] = None
        game["live_state"] = live_state

        # `_scheduled_status_token` and `_resolve_scheduled_start_utc` both
        # read camelCase `startTime` first; the cards carried none at all.
        if state.get("start_time"):
            game.setdefault("startTime", state["start_time"])

        if live_state["final"]:
            final += 1
            # Scores belong on the side containers too: `_side_score` checks
            # `game[side]["score"]` before it reaches `live_state`, and the
            # card template renders from the side containers.
            _stamp_side_scores(game, state)
        elif live_state["in_progress"]:
            live += 1
            _stamp_side_scores(game, state)

    return {"matched": matched, "live": live, "final": final, "games": len(games), "index": len(index)}


def _stamp_side_scores(game: dict[str, Any], state: Mapping[str, Any]) -> None:
    for side, key in (("away", "away_pts"), ("home", "home_pts")):
        value = state.get(key)
        if value is None:
            continue
        container = game.get(side)
        if isinstance(container, dict):
            container["score"] = value
