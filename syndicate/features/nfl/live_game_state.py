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

--------------------------------------------------------------------------
IN A WEB REQUEST THIS NO LONGER FETCHES `[2026-11-27]`
--------------------------------------------------------------------------

Lane `nfl-request-path-espn`, after NCAAF's and WNBA's (`c2fb7f49b`). Web
fetched this scoreboard inside requests: 40
`compute in request path (operation=nfl_espn_game_state_fetch)` lines on
11-27 between 00:00Z and 16:39Z. Most were past-date `/api/board/game-chips`
builds (the 8:15 AM play-cards grader asks for every date since 10-16). The
rest were current-week page builds. When the host's network is down, each
GET stalls in DNS inside the request (61-113 s game-chips requests on 11-26).

The workers already call this for the current week about 200 times an hour,
outside any request (0 request-path lines in either worker log, 11-27). So
what they fetch is now kept:

  * a WORKER RECORD per (season, seasontype, week), written through
    `refresh_state_store` (the keyvalue store on the fleet) after each
    successful fetch outside a request. The filename carries no date token,
    so the store gives it no TTL; it is about 25 keys a season.
  * a FINAL-WEEK ARCHIVE on disk, written once a fetch sees every game of the
    week final. It never changes again. Written straight to disk under
    `reports_root()`, because the fleet's roles share that disk, and the
    store's disk marker sits in a file another lane owns.

Inside a web request, with `SYNDICATE_REQUEST_PATH_ESPN_FETCH` absent or off:
cache -> archive -> worker record (at any age; its age is printed) -> `{}`
(state unknown, named `NFL_GAME_STATE_REQUEST_NO_FETCH`). Never a GET.
`SYNDICATE_REQUEST_PATH_ESPN_FETCH=on` restores the request-path fetch.
Outside a request (the workers) every read is unchanged; they only gain the
writes. `scripts/backfill_nfl_final_archives.py` wrote the archive for the
weeks that ended before this landed.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path
from syndicate.features.shared.segment_actuals import linescores_from_competitor


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

# The `situation` fields a live card carries (lane `nfl-live-card-situation`):
# what `game_chip_detail.live_detail` reads, plus the raw spot and timeouts so a
# reader can audit them. Every one was present on ESPN's NFL scoreboard on MNF
# 2026-11-16; `lastPlay` is left out on purpose (a large nested block).
_CARD_SITUATION_KEYS = (
    "possession", "down", "distance", "yardLine", "possessionText",
    "downDistanceText", "shortDownDistanceText", "isRedZone",
    "homeTimeouts", "awayTimeouts",
)

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

    # PER-PERIOD SCORES, CARRIED RATHER THAN DROPPED -- the same root cause
    # NCAAF's box-score tab had (`9b57dd52`). `competitors[].linescores[]` has
    # been in this exact payload the whole time and this function read only the
    # aggregate, so the board could show a final score and had no way to show
    # HOW it got there. `scripts/poll_nfl_live_state._game_from_event` already
    # parses the identical field off the identical endpoint for settlement;
    # this is the CARD's reader of it, and it costs no extra fetch.
    #
    # `linescores_from_competitor` is the platform's one parser: it honours an
    # entry's own `period` so a feed that skips one leaves a HOLE rather than
    # shifting every later quarter left. A shifted linescore renders the wrong
    # quarter with total confidence.
    #
    # Same pregame gate as the score. An unstarted game must carry `None`, not
    # `[]` -- an empty list downstream reads as "played, scored nothing".
    away_linescores = linescores_from_competitor(away_row) if (in_progress or final) else None
    home_linescores = linescores_from_competitor(home_row) if (in_progress or final) else None

    return {
        "event_id": event_id,
        "away_abbr": away_abbr,
        "home_abbr": home_abbr,
        # ESPN names the team in possession by ID (`situation.possession`), not
        # by side, so the live re-sim's tick adapter needs the ids to resolve
        # it to home / away (todo #813). Text, as ESPN sends ids as strings.
        "away_team_id": _text(away_team.get("id")),
        "home_team_id": _text(home_team.get("id")),
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
        "away_linescores": away_linescores,
        "home_linescores": home_linescores,
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


def _index_from_states(states: list[Any]) -> dict[str, dict[str, Any]]:
    """Key each game by ESPN event id and by `"{AWAY}@{HOME}"`.

    The one keying rule, used by the fetch and by both stored readers, so a
    record can never resolve a card the fetch would not.
    """
    index: dict[str, dict[str, Any]] = {}
    for state in states:
        if not isinstance(state, Mapping):
            continue
        state = dict(state)
        event_id = _text(state.get("event_id"))
        away_abbr = _text(state.get("away_abbr"))
        home_abbr = _text(state.get("home_abbr"))
        if event_id:
            index[event_id] = state
        if away_abbr and home_abbr:
            index.setdefault(f"{away_abbr}@{home_abbr}", state)
    return index


# --------------------------------------------------------------------------
# The worker record and the final-week archive (2026-11-27, lane
# `nfl-request-path-espn`). See the module docstring.
# --------------------------------------------------------------------------

RECORD_PARTS = ("nfl_source", "api", "game_state_index")
FINAL_ARCHIVE_PARTS = ("nfl_source", "api", "game_state_final")

# Weeks this process has already archived, so an all-final week the workers
# keep building (they do, for hours after Monday night) costs one disk write.
_archived_weeks: set[tuple[int, int, int]] = set()
_archived_lock = threading.Lock()


def _week_file_name(season: int, seasontype: int, week: int) -> str:
    # Letters between the numbers on purpose: `refresh_state_store` gives a
    # key a 10-day TTL when its path holds a date-like token
    # (`20\d{2}[-_]?\d{2}[-_]?\d{2}`), and `2026_2_12` would not match but
    # `2026_10_12` would. `s2026_t2_w12` never matches.
    return f"game_state_s{int(season)}_t{int(seasontype)}_w{int(week):02d}.json"


def record_path(season: int, seasontype: int, week: int) -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root().joinpath(*RECORD_PARTS, _week_file_name(season, seasontype, week))


def final_archive_path(season: int, seasontype: int, week: int) -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root().joinpath(*FINAL_ARCHIVE_PARTS, _week_file_name(season, seasontype, week))


def _in_web_request() -> bool:
    try:
        from flask import has_request_context

        return bool(has_request_context())
    except Exception:  # noqa: BLE001 -- no Flask, no request
        return False


def _request_path_fetch_enabled() -> bool:
    """`SYNDICATE_REQUEST_PATH_ESPN_FETCH`: absent or anything but on = no ESPN fetch in a web request."""
    return str(os.environ.get("SYNDICATE_REQUEST_PATH_ESPN_FETCH") or "").strip().lower() in {"1", "true", "on", "yes"}


def _unique_states(index: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The index holds each game twice (id and matchup key); a record holds it once."""
    seen: set[int] = set()
    states: list[dict[str, Any]] = []
    for state in index.values():
        if id(state) in seen:
            continue
        seen.add(id(state))
        states.append(dict(state))
    return states


def _write_final_archive(path: Path, record: Mapping[str, Any]) -> None:
    from syndicate.features.shared.refresh_state_store import _atomic_write_text

    _atomic_write_text(path, json.dumps(record, indent=2, sort_keys=True))


def persist_week(season: int, seasontype: int, week: int, index: Mapping[str, Mapping[str, Any]], *, archive_only: bool = False) -> dict[str, Any]:
    """Write the worker record and, once every game is final, the archive.

    Never raises: a failed write costs the record, never the caller's board.
    `archive_only` is the backfill's mode: it writes the archive (when the week
    is all final) and leaves the live record alone.
    """
    states = _unique_states(index)
    result: dict[str, Any] = {"games": len(states), "finals": sum(1 for s in states if s.get("final")),
                              "recorded": False, "archived": False}
    if not states:
        return result
    record = {
        "season": int(season),
        "seasontype": int(seasontype),
        "week": int(week),
        "games": states,
        "count": len(states),
        "finals": result["finals"],
        "fetched_at": time.time(),
    }
    if not archive_only:
        try:
            from syndicate.features.shared.refresh_state_store import write_json_file

            write_json_file(record_path(season, seasontype, week), record)
            result["recorded"] = True
        except Exception as exc:  # noqa: BLE001 -- named, never fatal to the board
            print(f"NFL_GAME_STATE_RECORD_WRITE_FAILED season={season} seasontype={seasontype} week={week} "
                  f"error={type(exc).__name__}: {exc}", flush=True)
    if result["finals"] == len(states):
        key = (int(season), int(seasontype), int(week))
        with _archived_lock:
            done = key in _archived_weeks
        if not done:
            try:
                path = final_archive_path(season, seasontype, week)
                if not path.exists():
                    _write_final_archive(path, record)
                    print(f"NFL_GAME_STATE_ARCHIVED season={season} seasontype={seasontype} week={week} "
                          f"games={len(states)}", flush=True)
                with _archived_lock:
                    _archived_weeks.add(key)
                result["archived"] = True
            except Exception as exc:  # noqa: BLE001 -- named, never fatal to the board
                print(f"NFL_GAME_STATE_ARCHIVE_WRITE_FAILED season={season} seasontype={seasontype} week={week} "
                      f"error={type(exc).__name__}: {exc}", flush=True)
    return result


def _states_from_final_archive(season: int, seasontype: int, week: int) -> list[Any] | None:
    """The archive's games, or None. Accepted only when every game is final."""
    path = final_archive_path(season, seasontype, week)
    try:
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- named, never fatal to the board
        print(f"NFL_GAME_STATE_ARCHIVE_READ_FAILED season={season} seasontype={seasontype} week={week} "
              f"error={type(exc).__name__}: {exc}", flush=True)
        return None
    games = record.get("games") if isinstance(record, Mapping) else None
    if not isinstance(games, list) or not games:
        return None
    if not all(isinstance(g, Mapping) and g.get("final") for g in games):
        return None
    return games


def _states_from_worker_record(season: int, seasontype: int, week: int) -> tuple[list[Any], float | None] | None:
    """The worker record's games and age in seconds, or None."""
    try:
        from syndicate.features.shared.refresh_state_store import read_json_file

        record = read_json_file(record_path(season, seasontype, week))
    except Exception as exc:  # noqa: BLE001 -- named, never fatal to the board
        print(f"NFL_GAME_STATE_RECORD_READ_FAILED season={season} seasontype={seasontype} week={week} "
              f"error={type(exc).__name__}: {exc}", flush=True)
        return None
    games = record.get("games") if isinstance(record, Mapping) else None
    if not isinstance(games, list) or not games:
        return None
    try:
        age = max(0.0, time.time() - float(record.get("fetched_at")))
    except (TypeError, ValueError):
        age = None
    return games, age


def _index_without_fetch(season: int, seasontype: int, week: int) -> dict[str, dict[str, Any]]:
    """A web request's answer: archive -> worker record -> state unknown. No GET.

    The archive goes first: it holds only settled weeks, so it can never be
    older than what it says. The record is served at any age, because the
    newest state a worker read beats a GET whose duration nobody bounds; its
    age is printed. Nothing here is cached: these are cheap reads, and a cached
    `{}` would also answer a later call outside a request in the same process,
    which is still allowed to fetch.
    """
    games = _states_from_final_archive(season, seasontype, week)
    if games is not None:
        index = _index_from_states(games)
        print(f"NFL_GAME_STATE_FROM_ARCHIVE season={season} seasontype={seasontype} week={week} "
              f"games={len(games)}", flush=True)
        return index
    found = _states_from_worker_record(season, seasontype, week)
    if found is not None:
        games, age = found
        index = _index_from_states(games)
        age_text = f"{age:.0f}" if age is not None else "unknown"
        print(f"NFL_GAME_STATE_FROM_WORKER season={season} seasontype={seasontype} week={week} "
              f"games={len(games)} age_seconds={age_text}", flush=True)
        return index
    print(f"NFL_GAME_STATE_REQUEST_NO_FETCH season={season} seasontype={seasontype} week={week}", flush=True)
    return {}


def nfl_game_state_index(season: int, week: int, *, seasontype: int) -> dict[str, dict[str, Any]]:
    """Per-game ESPN state for one NFL week, keyed by ESPN event id.

    Also keyed by `"{AWAY}@{HOME}"` so a card whose `gamePk` is not an ESPN
    event id can still resolve. Returns `{}` on any failure -- callers must
    treat an empty index as "state unknown", never as "nothing is live".

    Inside a web request it never fetches (see the module docstring); outside
    one it fetches as before and keeps what it fetched for the web to read.
    """
    key = (int(season), int(seasontype), int(week))
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return dict(cached[1])

    in_request = _in_web_request()
    if in_request and not _request_path_fetch_enabled():
        return _index_without_fetch(int(season), int(seasontype), int(week))

    warn_if_compute_in_request_path("nfl_espn_game_state_fetch")
    payload = _fetch_scoreboard(int(season), int(seasontype), int(week))
    states: list[dict[str, Any]] = []
    events = payload.get("events") if isinstance(payload, Mapping) else None
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, Mapping):
                continue
            state = _state_from_event(event)
            if state is not None:
                states.append(state)
    index = _index_from_states(states)

    # An empty result is cached too, so a scoreboard outage costs one fetch
    # per TTL rather than one per request. It is still an EMPTY index, so it
    # cannot be mistaken for a confident "everything is pregame".
    with _cache_lock:
        _cache[key] = (now, index)
        if len(_cache) > 16:
            oldest = min(_cache, key=lambda item: _cache[item][0])
            _cache.pop(oldest, None)

    # Kept for the web to read: outside a request only (the workers), and only
    # a fetch that returned games. A web request never writes.
    if index and not in_request:
        persist_week(int(season), int(seasontype), int(week), index)
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
        # THE ESPN EVENT ID, kept so a per-game reader can address this game.
        # NFL's `gamePk` is nflverse-shaped (`2026_01_NE_SEA`) and is NOT an
        # ESPN id -- the join above reaches this row through the
        # `"{AWAY}@{HOME}"` fallback key, and that resolution was then thrown
        # away. `live_player_box` needs exactly this id and has no other way to
        # get it without repeating the join.
        if state.get("event_id"):
            live_state["event_id"] = str(state["event_id"])
        if state.get("period") is not None:
            live_state["period"] = state["period"]
        if state.get("clock"):
            live_state["clock"] = state["clock"]
        if state.get("away_pts") is not None:
            live_state["away_pts"] = state["away_pts"]
        if state.get("home_pts") is not None:
            live_state["home_pts"] = state["home_pts"]
        # Copied only when PRESENT and non-empty, so absence stays absent: a
        # pregame game must not gain an empty list that a box renderer would
        # read as "four quarters played, zero points". A list may still contain
        # `None` holes -- see `linescores_from_competitor` -- and the box
        # renders those as an em dash rather than a zero.
        for side_key in ("away_linescores", "home_linescores"):
            values = state.get(side_key)
            if isinstance(values, list) and values:
                live_state[side_key] = list(values)
        # DOWN / DISTANCE / WHO HAS THE BALL for the card, in ESPN's own words
        # (lane `nfl-live-card-situation`), the same two keys NCAAF's card has
        # carried since `games-rail-full-detail`. Without them
        # `game_chip_detail.live_detail` fell back to the shape and printed
        # ESPN's team ID ("33 ball") and the raw home-frame `yardLine` ("at 52"
        # for LAC at its own 48). Live games only: `_state_from_event` keeps
        # `situation` only while in progress, so a final carries neither.
        # Only the fields a reader uses -- not `lastPlay`, which is a large
        # nested block the board would otherwise ship on every live card.
        situation = state.get("situation")
        if live_state["in_progress"] and isinstance(situation, Mapping):
            live_state["espn_situation"] = {
                key: situation[key] for key in _CARD_SITUATION_KEYS if key in situation
            }
            # ESPN names the team in possession by ID; the side is resolved
            # against the competitors' ids, never guessed when neither matches.
            holder = str(situation.get("possession") or "").strip()
            if holder:
                if holder == str(state.get("home_team_id") or "").strip():
                    live_state["possession_side"] = "home"
                elif holder == str(state.get("away_team_id") or "").strip():
                    live_state["possession_side"] = "away"
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
            _stamp_started_status(game, live_state)
        elif live_state["in_progress"]:
            live += 1
            _stamp_side_scores(game, state)
            _stamp_started_status(game, live_state)

    return {"matched": matched, "live": live, "final": final, "games": len(games), "index": len(index)}


def _stamp_started_status(game: dict[str, Any], live_state: Mapping[str, Any]) -> None:
    """Overwrite the card's `status` with ESPN's, for a game that has STARTED.

    THE PARITY GAP THIS CLOSES. `attach_ncaaf_live_game_state` has done this
    since 2026-08-29 and this function did not, so the two football boards
    disagreed about what a live game's own header says. Measured on the served
    payloads 2026-09-07:

        NCAAF   status = "Final" x50, "14:40 - 3rd" x1
        NFL     status = "Week 1" x16

    NFL's slate was genuinely pregame that day, so this is a LATENT defect
    rather than a visible one -- and that is exactly why it needed finding
    before kickoff rather than during it. `_shared_game_state` copies `status`
    straight into `shared_game_state.status`, which is what the compact strip's
    live head and the live lens's eyebrow both fall back to. Left alone, a live
    NFL card would have rendered its eyebrow as "Week 1" while the clock ran.

    STARTED GAMES ONLY. A pregame card keeps the week label it has always had:
    ESPN's pregame `shortDetail` is a date-and-time string ("9/9 - 8:20 PM
    EDT") and the strip already has a properly formatted kickoff line of its
    own to show there.

    An empty ESPN status leaves the card untouched rather than blanking it.
    """
    status = str(live_state.get("status") or "").strip()
    if status:
        game["status"] = status


def _stamp_side_scores(game: dict[str, Any], state: Mapping[str, Any]) -> None:
    for side, key in (("away", "away_pts"), ("home", "home_pts")):
        value = state.get(key)
        if value is None:
            continue
        container = game.get(side)
        if isinstance(container, dict):
            container["score"] = value
