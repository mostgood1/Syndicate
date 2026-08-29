"""ESPN live game state for the NCAAF board, joined on ESPN's own team ids.

    ncaaf_game_state_index(dates)  ->  {"153@2628": {...}, ...}
    attach_ncaaf_live_game_state(games, index)  ->  coverage counts

--------------------------------------------------------------------------
WHY THIS EXISTS: THE LIVE LENS SHIPPED WITH ITS STATE BRANCH UNREACHABLE
--------------------------------------------------------------------------

`ncaaf/live_lens.py::_game_state_label` reads `shared_game_state`, which
`publication_adapter._shared_game_state` derives entirely from
`game["live_state"]`. `ncaaf/cards.py` contained **zero occurrences of
`live_state`**, so that dict was `{live: false, final: false, period: null,
clock: "", startTime: null}` on every card and the lens's live branch could
never be taken.

Measured on production 2026-08-29T16:0xZ, with UNC @ TCU at ESPN `state=in`,
1st Quarter: `/ncaaf/api/live-lens` served `Games 51 | Live 0 | Final 0 |
Pregame 51`. The state PATH shipped 2026-08-27 (lane `ncaaf-board-surfaces`)
and its own ledger entry said the DATA "cannot be [tested] until a game is in
progress". A game was in progress and the data was not there.

--------------------------------------------------------------------------
THE JOIN IS ON ESPN TEAM IDS, AND EVERY OTHER KEY ON THIS BOARD IS UNSAFE
--------------------------------------------------------------------------

Measured over the 2026 week-1 board (51 games) and the 08-29 ESPN scoreboard:

| key                | result                                              |
|--------------------|-----------------------------------------------------|
| ESPN team id pair  | **51/51 cards carry both, 51 distinct pairs, exact** |
| abbreviation pair  | **0 of 10** comparable games matched                 |
| team display name  | unsafe -- see below                                  |

The board's abbreviations are CFBD's, not ESPN's: `NC`/`UNC`, `SJS`/`SJSU`,
`NS`/`NCSU`, `VIR`/`UVA`, `JS`/`JVST`, `NDS`/`NDSU`, `SS`/`SAC`, `EM`/`EMU`,
`NMS`/`NMSU`, `FS`/`FSU`. Not one matches. A board that joined on abbreviations
would report every game pregame forever and look exactly like this bug.

Names are worse, not better. `ncaaf-settlement-resolver` measured NCAAF's name
space and found `team_aliases._alias_map("ncaaf")` empty, so matching falls
through to a prefix heuristic under which **"Michigan" matches "Michigan
State"** and both Miamis match each other -- across ~130 FBS teams. On a live
board that mis-joins state onto the wrong game, which is strictly worse than
showing none: a wrong clock renders confidently and nothing downstream can tell.
The accent trap is real here too and already cost this platform a props panel
(`San José State` vs `San Jose State`, findings 2026-08-26 §3).

**The ids were already on the card and nothing read them.** `_resolve_branding`
stamps `logo_url = https://a.espncdn.com/i/teamlogos/ncaa/500/<espn_id>.png`,
so the exact key this join needs has been sitting in the payload the whole time.

--------------------------------------------------------------------------
ONE PARSER, NOT THREE
--------------------------------------------------------------------------

State semantics come from `scripts/poll_ncaaf_live_state._game_from_event` --
imported, never reimplemented. That module's docstring warns that it and
`nfl/live_game_state.py` must not drift on ESPN payload handling, and a third
copy on the board side is exactly the drift it warns about. In particular its
`final` reads BOTH `completed` and `state == "post"`, and it suppresses the
0-0 placeholder score on unstarted games -- both measured behaviours this
module inherits rather than re-derives.

This module adds only what the board needs and settlement does not: the ESPN
**team ids** (the join key) and **period** / **displayClock** (the eyebrow).
Those are read straight off the same event mapping, so they cannot disagree
with the state fields beside them.

`scripts/poll_ncaaf_live_state.py` is owned by OPEN lane
`ncaaf-settlement-resolver`; this module imports it READ-ONLY and changes
nothing in it.

--------------------------------------------------------------------------
REQUEST PATH, DELIBERATELY, WITH THE SAME GUARD NFL USES
--------------------------------------------------------------------------

This runs on web, in the cards builder, behind a TTL cache and
`warn_if_compute_in_request_path` -- the identical shape
`nfl/live_game_state.py` already uses in production for the same purpose. It is
a bounded GET, never a computation, and it fails SOFT: any failure yields an
EMPTY index, and an empty index leaves every card untouched. "State unknown"
and "nothing is live" must never render the same way by accident, so callers
get coverage counters (`matched` separately from `live`/`final`) rather than a
single number that cannot distinguish a dead join from a quiet slate.

Only dates that have already begun are fetched. A future date is pregame by
definition and ESPN adds nothing to it, so a 10-day NCAAF week costs one call
on opening Saturday rather than ten.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path

__all__ = [
    "ncaaf_game_state_index",
    "attach_ncaaf_live_game_state",
    "espn_team_id_from_logo",
    "past_or_current_dates",
]

# Short enough that a live clock is not visibly stale, long enough that a
# refresh storm on one board cannot turn into a fetch per request.
_CACHE_TTL_SECONDS = 45.0

_cache: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}
_cache_lock = threading.Lock()

# `.../i/teamlogos/ncaa/500/153.png` -> `153`
_LOGO_ID_RE = re.compile(r"/(\d+)\.png(?:\?|$)")


def espn_team_id_from_logo(container: Any) -> str | None:
    """The ESPN team id a card's `logo_url` already carries, or None."""
    if not isinstance(container, Mapping):
        return None
    match = _LOGO_ID_RE.search(str(container.get("logo_url") or ""))
    return match.group(1) if match else None


def past_or_current_dates(dates: Any, *, today: str | None = None) -> tuple[str, ...]:
    """The subset of `dates` that has actually started, ascending.

    A future kickoff date cannot contribute a live or final game, so fetching
    it buys nothing and costs a round trip. Compared as ISO strings, which sort
    correctly and avoid inventing a timezone the board does not carry.
    """
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seen: list[str] = []
    for value in dates or ():
        text = str(value or "").strip()
        if len(text) == 10 and text <= today and text not in seen:
            seen.append(text)
    return tuple(sorted(seen))


def _state_rows_for_date(iso_date: str) -> list[dict[str, Any]]:
    """One date's events, with team ids and clock added to the shared parse.

    Returns `[]` on any failure -- never raises, never fabricates.
    """
    try:
        from scripts.poll_ncaaf_live_state import _fetch_scoreboard, _game_from_event
    except Exception as exc:  # noqa: BLE001
        # NAMED, never silent. `scripts/` is a namespace package imported from
        # the repo root; if the web service's working directory ever stops
        # making that resolvable, every card silently reverts to pregame --
        # which is indistinguishable from the bug this module fixes. An empty
        # index is a legitimate reading (no games today); a failed IMPORT is
        # not, and must not look like one.
        print(f"NCAAF_LIVE_STATE_IMPORT_FAILED error={type(exc).__name__}: {exc}", flush=True)
        return []

    payload = _fetch_scoreboard(iso_date)
    if not isinstance(payload, Mapping):
        return []
    events = payload.get("events")
    if not isinstance(events, list):
        return []

    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        # State semantics: the shared parser, unmodified.
        state = _game_from_event(event)
        if state is None:
            continue
        state = dict(state)
        state["date"] = iso_date

        competitions = event.get("competitions")
        competition = (
            competitions[0]
            if isinstance(competitions, list) and competitions and isinstance(competitions[0], Mapping)
            else {}
        )
        competitors = competition.get("competitors")
        competitors = competitors if isinstance(competitors, list) else []
        for row in competitors:
            if not isinstance(row, Mapping):
                continue
            side = str(row.get("homeAway") or "").strip().lower()
            if side not in ("home", "away"):
                continue
            team = row.get("team") if isinstance(row.get("team"), Mapping) else {}
            team_id = str(team.get("id") or "").strip()
            if team_id:
                state[f"{side}_id"] = team_id

        # The eyebrow's two fields. Settlement has no use for them, so the
        # shared parser does not carry them.
        status = event.get("status") if isinstance(event.get("status"), Mapping) else {}
        period = status.get("period")
        if isinstance(period, (int, float)) and period:
            state["period"] = int(period)
        clock = str(status.get("displayClock") or "").strip()
        if clock:
            state["clock"] = clock

        rows.append(state)
    return rows


def ncaaf_game_state_index(dates: Any) -> dict[str, dict[str, Any]]:
    """Per-game ESPN state for the given dates, keyed `"{away_id}@{home_id}"`.

    An empty result means STATE UNKNOWN and must never be read as "nothing is
    live" -- see the module docstring.
    """
    index: dict[str, dict[str, Any]] = {}
    for iso_date in past_or_current_dates(dates):
        now = time.monotonic()
        with _cache_lock:
            cached = _cache.get(iso_date)
            rows_by_key = dict(cached[1]) if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS else None

        if rows_by_key is None:
            warn_if_compute_in_request_path("ncaaf_espn_game_state_fetch")
            rows_by_key = {}
            for state in _state_rows_for_date(iso_date):
                away_id = str(state.get("away_id") or "")
                home_id = str(state.get("home_id") or "")
                if away_id and home_id:
                    rows_by_key[f"{away_id}@{home_id}"] = state
            # An empty result is cached too, so an ESPN outage costs one fetch
            # per TTL rather than one per request. It stays EMPTY, so it still
            # cannot be mistaken for a confident "everything is pregame".
            with _cache_lock:
                _cache[iso_date] = (time.monotonic(), dict(rows_by_key))
                if len(_cache) > 16:
                    oldest = min(_cache, key=lambda item: _cache[item][0])
                    _cache.pop(oldest, None)

        # A later date wins a duplicate pairing (a rescheduled matchup).
        index.update(rows_by_key)
    return index


def _lookup(index: Mapping[str, Mapping[str, Any]], game: Mapping[str, Any]) -> Mapping[str, Any] | None:
    away_id = espn_team_id_from_logo(game.get("away"))
    home_id = espn_team_id_from_logo(game.get("home"))
    if not away_id or not home_id:
        return None
    return index.get(f"{away_id}@{home_id}")


def _stamp_side_scores(game: dict[str, Any], state: Mapping[str, Any]) -> None:
    """Live score onto the side containers, where the card template reads it."""
    for side, key in (("away", "away_score"), ("home", "home_score")):
        value = state.get(key)
        if value is None:
            continue
        container = game.get(side)
        if isinstance(container, dict):
            container["score"] = value


def attach_ncaaf_live_game_state(
    games: list[dict[str, Any]], index: Mapping[str, Mapping[str, Any]]
) -> dict[str, int]:
    """Stamp `live_state`, a real `startTime` and a real `status` onto cards.

    Returns coverage counts. `matched` is reported separately from `live` and
    `final` on purpose: "the join found nothing" and "the join worked and every
    game is pregame" produce an identical board and are different defects.

    `status` is overwritten only for games ESPN says have started. The NCAAF
    board's `status` is the constant `"Week 1"`, which
    `_shared_game_state` copies into `shared_game_state.status` and
    `_game_state_label` falls back to when period/clock are missing -- so
    leaving it would render a live game's eyebrow as "Week 1". Pregame games
    keep the week label they have always had.
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
            # Leave the card untouched: absence must stay absent.
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
        if state.get("away_score") is not None:
            live_state["away_pts"] = state["away_score"]
        if state.get("home_score") is not None:
            live_state["home_pts"] = state["home_score"]
        game["live_state"] = live_state

        # `shared_game_state.startTime` was null on all 51 cards, so the shared
        # board contract could not sort or filter the slate by kickoff
        # (findings 2026-08-26 §1). ESPN carries it; `setdefault` so a real
        # value already on the card wins.
        if state.get("start_time"):
            game.setdefault("startTime", state["start_time"])

        if live_state["final"]:
            final += 1
            if live_state["status"]:
                game["status"] = live_state["status"]
            _stamp_side_scores(game, state)
        elif live_state["in_progress"]:
            live += 1
            if live_state["status"]:
                game["status"] = live_state["status"]
            _stamp_side_scores(game, state)

    return {"matched": matched, "live": live, "final": final, "games": len(games), "index": len(index)}
