"""Per-player NFL lines for ONE game, from ESPN's summary endpoint.

WHY A NEW READER RATHER THAN `nfl/player_stats.py`. That module can produce
real player lines off `pbp_{season}.csv`, and it is the WRONG SOURCE for a live
tab: nflverse's play-by-play lands days after a game. On a Wednesday-night
week-1 kickoff it holds nothing for this season and everything for the last
one, so a box built on it would either be empty or -- far worse -- be LAST
SEASON'S numbers printed under tonight's teams. That is a fabricated box score
that looks entirely plausible and is wrong in every cell. It stays the right
source for a settled archive and is deliberately not used here.

WHY NOT A THIRD PARSER. `site.api.espn.com/.../football/nfl/summary?event=`
returns the identical `boxscore.players[].statistics[].keys/athletes` shape
this repo already parses twice -- `nba/cards.py`'s
`_public_live_player_boxscore_payload` and `scripts/build_wnba_boxscores.py`'s
`rows_from_summary`. Both walk `keys` (the stat NAMES) against `stats` (the
values, positionally) rather than trusting `labels`, because `labels` are the
display strings and change. This does the same, over football's own groups.

    passing    completions/passingAttempts, passingYards, ..., passingTouchdowns
    rushing    rushingAttempts, rushingYards, ..., rushingTouchdowns
    receiving  receptions, receivingYards, ..., receivingTouchdowns

Verified on a real completed game (401873297, SEA @ TEN, 2026-08-23): two team
blocks, ten stat groups each, `keys` present on every one.

--------------------------------------------------------------------------
THE COST, AND WHAT BOUNDS IT
--------------------------------------------------------------------------

The web service reads artifacts; it does not recompute. This is a READ, and it
is the same class of read `live_game_state.nfl_game_state_index` already does
in this exact request path -- but it is PER EVENT rather than per week, so an
unbounded version would turn one Sunday board into thirteen serial HTTP calls.
Four things bound it and all four matter:

  * STARTED GAMES ONLY. A pregame event has no player box to fetch, so a
    Thursday board costs ZERO calls and tonight's board costs one.
  * A cache keyed by event id, with a long TTL on a FINAL game (its box will
    never change again) and a short one on a live game (a box that is 60s
    stale during a game is the defect this exists to remove).
  * Concurrency, and a WALL-CLOCK BUDGET on the whole batch. Whatever has not
    come back when the budget expires is absent, and absent renders as a
    stated empty state -- never as a slow page.
  * Negative caching. A failed fetch is remembered briefly, so a feed outage
    costs one attempt per TTL rather than one per request.

DO NOT ADD A BROWSER USER-AGENT. ESPN returns HTTP 403 to browser-spoof
User-Agents from Render's outbound IP -- confirmed three times, most recently
2026-08-13. `urllib.request.Request(url)` with no headers is load-bearing, not
an oversight. `live_game_state.py`'s docstring carries the original probe.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable, Mapping

from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path

__all__ = [
    "fetch_player_stat_rows",
    "nfl_player_box_index",
    "player_rows_from_summary",
    "player_stat_rows_from_summary",
]

_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"

_FETCH_TIMEOUT_SECONDS = 5.0
# A finished game's box is immutable; a live one's changes every drive.
_LIVE_TTL_SECONDS = 25.0
_FINAL_TTL_SECONDS = 900.0
# A failure is remembered too, so an outage costs one attempt per window
# instead of one per request.
_FAILURE_TTL_SECONDS = 45.0
# The whole batch, not one call. Anything still outstanding when this expires
# is treated as absent and renders as a stated empty state.
_BATCH_BUDGET_SECONDS = 8.0
_MAX_WORKERS = 6
# A Sunday early window is 13 games; a whole slate never arrives at once. This
# is a REFUSAL cap, not a display cap -- if a board ever asks for more events
# than this, the extra ones go unfetched rather than the page going slow.
_MAX_EVENTS_PER_BUILD = 16

# event_id -> (expires_at_monotonic, rows | None)
_cache: dict[str, tuple[float, list[dict[str, Any]] | None]] = {}
_cache_lock = threading.Lock()

# The three groups a football box is actually read for. `fumbles`,
# `defensive`, `kicking` and the return groups are deliberately not merged in:
# a defensive player's tackle line has no cell in this grid, and inventing one
# per group would make the table unreadable on a card.
_YARD_KEYS = {
    "passingYards": "pass_yards",
    "rushingYards": "rush_yards",
    "receivingYards": "rec_yards",
}
_TD_KEYS = {
    "passingTouchdowns": "pass_td",
    "rushingTouchdowns": "rush_td",
    "receivingTouchdowns": "rec_td",
}
# COUNTING STATS, added 2026-09-10 for SETTLEMENT: `bet_status_nfl` grades
# player props off these. Each key is unique across ESPN's football groups, so
# it maps without consulting the group name.
_COUNT_KEYS = {
    "rushingAttempts": "rush_attempts",
    "receptions": "receptions",
    "receivingTargets": "targets",
}
# GROUP-SCOPED, AND THE SCOPE IS THE WHOLE POINT. ESPN carries `interceptions`
# in TWO groups: `passing` (interceptions THROWN -- the QB's prop) and a
# separate `interceptions` group (picks CAUGHT, by the defender). Measured on
# event 401872656 (NE @ SEA, 2026-09-09): Drake Maye's passing line reads
# `interceptions: 3` while SEA's `interceptions` group lists the three defenders
# who caught them. A name-only map would credit each defender with a thrown
# interception and grade an interceptions prop off the wrong player.
_PASSING_GROUP = "passing"
_PASS_INT_KEY = "interceptions"
# Completions and attempts share ONE key and ONE cell: "23/33".
_COMP_ATT_KEY = "completions/passingAttempts"

# Every numeric field a merged row carries, zero-initialised. The first six are
# the card's, in the card's order; the rest exist for settlement.
_ROW_FIELDS = (
    "pass_yards",
    "rush_yards",
    "rec_yards",
    "pass_td",
    "rush_td",
    "rec_td",
    "completions",
    "pass_attempts",
    "pass_int",
    "rush_attempts",
    "receptions",
    "targets",
)
# EXACTLY what the card rendered before the counting stats existed, in the same
# order. `player_rows_from_summary` projects onto this so the card payload is
# byte-identical -- the settlement fields must not leak onto a page nobody
# asked to change.
_DISPLAY_FIELDS = (
    "player_name",
    "team_abbr",
    "pass_yards",
    "rush_yards",
    "rec_yards",
    "pass_td",
    "rush_td",
    "rec_td",
    "td_scored",
    "total_yards",
)


def _number(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _fetch_summary(event_id: str) -> Mapping[str, Any] | None:
    url = f"{_SUMMARY_URL}?event={urllib.parse.quote(str(event_id))}"
    # See the module docstring: no custom headers.
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url), timeout=_FETCH_TIMEOUT_SECONDS
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        # Fail SOFT and named-to-the-caller by returning None: a summary
        # outage must degrade the box tab, never the board.
        return None
    return payload if isinstance(payload, Mapping) else None


def _split_pair(value: Any) -> tuple[float | None, float | None]:
    """"23/33" -> (23.0, 33.0). Either half None when it does not parse."""
    text = str(value if value is not None else "").strip()
    if "/" not in text:
        return None, None
    left, _, right = text.partition("/")
    return _number(left), _number(right)


def player_rows_from_summary(summary: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
    """`boxscore.players[]` -> one row per player with a real stat line.

    Returns None when the payload carries no player block at all -- which is a
    DIFFERENT fact from "the block was there and empty", and the caller renders
    the two differently. ESPN publishes `boxscore.teams` long before
    `boxscore.players` on a game that has just kicked off, so this distinction
    is the normal early-game state, not an error.

    THE CARD'S VIEW, AND UNCHANGED BY SETTLEMENT'S NEEDS. Rows are filtered to
    players with yards or a touchdown and projected onto `_DISPLAY_FIELDS`, so
    the payload is byte-identical to what it was before the counting stats were
    parsed. Settlement reads `player_stat_rows_from_summary` instead.
    """
    rows = _merged_player_rows(summary)
    if rows is None:
        return None
    # A player who appeared in a group with no yards and no touchdown has no
    # line to show; keeping them would bury the ones who do under a roster.
    shown = [row for row in rows if row["total_yards"] or row["td_scored"] or row["pass_td"]]
    return [{field: row[field] for field in _DISPLAY_FIELDS} for row in shown]


def player_stat_rows_from_summary(summary: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
    """EVERY athlete in the box, with EVERY parsed field -- for grading, not display.

    Unfiltered on purpose. A player listed in ANY stat group took the field, so a
    zero in one of his fields is a real zero -- a receiver with one carry and no
    targets genuinely caught nothing. The card's filter would drop him and turn
    that real zero into an absence, which a grader must treat as "did not play".
    None keeps the card's meaning: no player block at all.
    """
    return _merged_player_rows(summary)


def _merged_player_rows(summary: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
    """One merged row per (team, athlete) across every stat group, unfiltered."""
    if not isinstance(summary, Mapping):
        return None
    boxscore = summary.get("boxscore")
    if not isinstance(boxscore, Mapping):
        return None
    team_blocks = boxscore.get("players")
    if not isinstance(team_blocks, list):
        return None

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for team_block in team_blocks:
        if not isinstance(team_block, Mapping):
            continue
        team = team_block.get("team") if isinstance(team_block.get("team"), Mapping) else {}
        abbr = str(team.get("abbreviation") or team.get("shortDisplayName") or "").strip().upper()
        groups = team_block.get("statistics")
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            # The group NAME is read only to scope the two keys that need it
            # (`completions/passingAttempts`, `interceptions`); every other key
            # is unique across groups and maps by name alone.
            group_name = str(group.get("name") or "").strip()
            # `keys`, never `labels`: labels are display strings ("YDS") and
            # are neither stable nor unique across groups.
            keys = [str(key or "").strip() for key in (group.get("keys") or [])]
            if not keys:
                continue
            athletes = group.get("athletes")
            if not isinstance(athletes, list):
                continue
            for entry in athletes:
                if not isinstance(entry, Mapping):
                    continue
                athlete = entry.get("athlete") if isinstance(entry.get("athlete"), Mapping) else {}
                name = str(athlete.get("displayName") or athlete.get("shortName") or "").strip()
                if not name:
                    continue
                stats = entry.get("stats")
                stats = stats if isinstance(stats, list) else []
                row = merged.setdefault(
                    (abbr, str(athlete.get("id") or name)),
                    {"player_name": name, "team_abbr": abbr, **{field: 0.0 for field in _ROW_FIELDS}},
                )
                for position, key in enumerate(keys):
                    if position >= len(stats):
                        break
                    cell = stats[position]
                    if key == _COMP_ATT_KEY:
                        if group_name == _PASSING_GROUP:
                            completions, attempts = _split_pair(cell)
                            if completions is not None:
                                row["completions"] = completions
                            if attempts is not None:
                                row["pass_attempts"] = attempts
                        continue
                    if key == _PASS_INT_KEY:
                        # THROWN only. The same key in the `interceptions`
                        # group is picks CAUGHT and must not land here.
                        if group_name == _PASSING_GROUP:
                            value = _number(cell)
                            if value is not None:
                                row["pass_int"] = value
                        continue
                    field = _YARD_KEYS.get(key) or _TD_KEYS.get(key) or _COUNT_KEYS.get(key)
                    if field is None:
                        continue
                    value = _number(cell)
                    if value is not None:
                        row[field] = value

    rows = list(merged.values())
    for row in rows:
        # ANYTIME TOUCHDOWN, which is the market this board prices. A passing
        # touchdown is the SAME score as its receiver's receiving touchdown, so
        # summing all three would double-count every one of them.
        row["td_scored"] = row["rush_td"] + row["rec_td"]
        row["total_yards"] = row["pass_yards"] + row["rush_yards"] + row["rec_yards"]
    # UNFILTERED. The card's filter lives in `player_rows_from_summary`.
    return rows


def _cached(event_id: str) -> tuple[bool, list[dict[str, Any]] | None]:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(event_id)
        if entry is not None and entry[0] > now:
            return True, entry[1]
    return False, None


def _store(event_id: str, rows: list[dict[str, Any]] | None, *, final: bool) -> None:
    if rows is None:
        ttl = _FAILURE_TTL_SECONDS
    else:
        ttl = _FINAL_TTL_SECONDS if final else _LIVE_TTL_SECONDS
    with _cache_lock:
        _cache[event_id] = (time.monotonic() + ttl, rows)
        if len(_cache) > 64:
            oldest = min(_cache, key=lambda key: _cache[key][0])
            _cache.pop(oldest, None)


def nfl_player_box_index(
    events: Iterable[tuple[str, bool]],
) -> dict[str, list[dict[str, Any]]]:
    """`[(event_id, is_final), ...]` -> `{event_id: rows}` for what came back.

    An event id ABSENT from the result means "not read" -- a failed fetch, a
    payload with no player block, or the batch budget running out. That is not
    the same as an event mapped to `[]`, which means "read, and nobody has a
    line yet", and the card renders the two differently. Collapsing them would
    put the confident empty state on a game whose box simply never arrived.
    """
    wanted: list[tuple[str, bool]] = []
    out: dict[str, list[dict[str, Any]]] = {}
    for event_id, final in events:
        event_id = str(event_id or "").strip()
        if not event_id or any(event_id == pending for pending, _ in wanted) or event_id in out:
            continue
        hit, rows = _cached(event_id)
        if hit:
            if rows is not None:
                out[event_id] = rows
            continue
        wanted.append((event_id, bool(final)))
    if not wanted:
        return out
    # The refusal cap, applied before any HTTP happens.
    wanted = wanted[:_MAX_EVENTS_PER_BUILD]

    warn_if_compute_in_request_path("nfl_espn_player_box_fetch")
    deadline = time.monotonic() + _BATCH_BUDGET_SECONDS

    def _one(item: tuple[str, bool]) -> tuple[str, list[dict[str, Any]] | None, bool, bool]:
        event_id, final = item
        if time.monotonic() >= deadline:
            # Budget already gone. Report it as NOT ATTEMPTED, so the caller
            # does not cache a failure the feed never had a chance to cause --
            # that would turn one slow board into 45 seconds of stated-empty
            # boxes on a feed that was working the whole time.
            return event_id, None, final, False
        return event_id, player_rows_from_summary(_fetch_summary(event_id)), final, True

    try:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(wanted))) as pool:
            for event_id, rows, final, attempted in pool.map(_one, wanted):
                if attempted:
                    _store(event_id, rows, final=final)
                if rows is not None:
                    out[event_id] = rows
    except Exception as exc:  # noqa: BLE001 -- a box must never cost the board
        print(f"NFL_PLAYER_BOX_FETCH_FAILED error={type(exc).__name__}: {exc}", flush=True)
    return out


def fetch_player_stat_rows(event_id: str) -> list[dict[str, Any]] | None:
    """One game's full ESPN box for SETTLEMENT: every athlete, every field.

    Deliberately NOT routed through `nfl_player_box_index`. Its cache, batch
    budget and request-path warning exist for a web page assembling up to
    thirteen boxes under an 8s budget; settlement runs on refresh-worker, reads
    one game at a time, and caches per resolver (`bet_status_nfl`). It must also
    never share the card cache, which holds the FILTERED display rows -- a
    grader reading those would turn every real zero into an absence and refuse
    a bet it could have settled.

    None means NOT READ: the fetch failed, or ESPN has not published a player
    block yet.
    """
    event_id = str(event_id or "").strip()
    if not event_id:
        return None
    return player_stat_rows_from_summary(_fetch_summary(event_id))
