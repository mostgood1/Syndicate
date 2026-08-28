"""Capture NFL game state for one DATE, so NFL bets can be graded.

    reports_root()/nfl_source/api/live_state/live_state_{date}.json

--------------------------------------------------------------------------
WHY THIS EXISTS: NFL BETS COULD NEVER SETTLE, AND THE READER WAS THE HALF
THAT WAS MISSING TWICE OVER
--------------------------------------------------------------------------

`paper_settlement._default_resolver` had builders for `mlb`, `wnba` and
`soccer` only, so every NFL order returned `no_resolver_for_nfl` forever.
Measured on refresh-worker 2026-08-28T02:37-02:50Z:

    SETTLED date=2026-08-28 orders=21 graded=0
      ungraded={..., 'no_resolver_for_nfl': 6, ...}          6 of 21 = 29%
    SETTLED date=2026-08-27 orders=158 graded=2
      ungraded={..., 'no_resolver_for_nfl': 8, ...}
    BET_STATUS orders=158 resolved=98
      reasons={..., 'no_resolver_for_nfl': 16, ...}

That is `#547` repeating -- soccer sat on `no_resolver_for_soccer` with ZERO
settled all-time while being ~97% of the board by row count. A bet that is
taken and can never be graded is worse than one never taken: it consumes
bankroll and is invisible to every performance number.

BUT WRITING ONLY THE RESOLVER WOULD HAVE SHIPPED A READER WITH NO PRODUCER.
`poll_soccer_live_state.py` was the ONLY live-state poller in `scripts/`.
`syndicate/features/nfl/live_game_state.py` exists but cannot serve
settlement: it fetches ESPN at call time rather than persisting anything, it
is keyed by `(season, week, seasontype)` while a resolver is handed a DATE,
and its only callers are in `preseason_cards.py`, always with
`SEASONTYPE_PRESEASON` -- the regular season is not wired at all. So this
file is the missing producer, and the resolver reads what it writes.

--------------------------------------------------------------------------
KEYED BY DATE, WHICH IS ALSO HOW THE WEEK PROBLEM IS AVOIDED
--------------------------------------------------------------------------

ESPN's scoreboard accepts `?dates=YYYYMMDD` as well as season/week, and this
uses the date form on purpose. Settlement's unit is `selected_date`, so a
`(season, week)` capture would need a date->week mapping that this repo has
had trouble with before (an August end-to-end assessment recorded NFL week
self-pinning to 1; not reproduced here, and deliberately not depended upon).
A date-keyed fetch cannot inherit that bug because it never asks the question.

--------------------------------------------------------------------------
WRITTEN THROUGH `refresh_state_store`, NOT TO THE FILESYSTEM
--------------------------------------------------------------------------

**Settlement runs on refresh-worker** (`pipeline/intelligence_state.py` calls
`settle_orders`), and Render cannot share a disk between services. Soccer's
resolver documents what that costs: finished matches reach it only because the
poll publishes into the cross-service aggregate, and "without that, this would
grade nothing in production while passing every test on a dev box" -- the
inert-feature shape `model_engine_standard.md` exists to prevent.

`write_json_file` puts this in the KEYVALUE store when
`SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` (both services run it against one
Redis namespace), and on disk otherwise. `bet_status_nfl` reads with the
matching `read_json_file`, so producer and reader cannot land in different
places. The path is also allowlisted in `HOT_ARTIFACT_PATTERNS` for the
filesystem case; that entry is inert under the keyvalue backend and is there
so a backend change does not silently strand the artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

__all__ = ["poll_nfl_live_state", "live_state_path", "ARTIFACT_PARTS"]

_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# Matches `nfl/live_game_state.py`. Short on purpose: a scoreboard outage must
# cost the capture, never the caller.
_FETCH_TIMEOUT_SECONDS = 6.0

ARTIFACT_PARTS = ("nfl_source", "api", "live_state")


def live_state_path(iso_date: str):
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root().joinpath(*ARTIFACT_PARTS, f"live_state_{iso_date}.json")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _score_or_none(value: Any) -> int | None:
    """ESPN ships scores as STRINGS ("17"). A string compares wrong downstream
    without ever raising -- the same field `board_enrichment` records a bug
    for."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _fetch_scoreboard(iso_date: str) -> dict[str, Any] | None:
    """One GET for one date, or None. Never raises.

    No custom headers: urllib's own default User-Agent is what ESPN accepts
    from Render, which `nfl/live_game_state.py` records and this must not
    diverge from.
    """
    compact = iso_date.replace("-", "")
    url = f"{_SCOREBOARD_URL}?dates={compact}"
    try:
        request = urllib.request.Request(url)
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _game_from_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """One scoreboard event -> the record the resolver joins against.

    BOTH THE DISPLAY NAME AND THE ABBREVIATION ARE KEPT. The resolver joins on
    the team PAIR through `team_aliases` (never on `event_id` -- the order's id
    is OddsAPI's namespace and ESPN's is not the same, the trap
    `bet_status_soccer` documents and `bet_status_wnba` says cost MLB a day).
    `canonical_team` resolves NFL tri-codes AND full names, so carrying both
    means the join does not depend on which one the board happened to store.
    """
    competitions = event.get("competitions")
    competitions = competitions if isinstance(competitions, list) else []
    competition = competitions[0] if competitions and isinstance(competitions[0], Mapping) else {}
    competitors = competition.get("competitors")
    competitors = competitors if isinstance(competitors, list) else []

    home_row: Mapping[str, Any] = {}
    away_row: Mapping[str, Any] = {}
    for row in competitors:
        if not isinstance(row, Mapping):
            continue
        side = _text(row.get("homeAway")).lower()
        if side == "home":
            home_row = row
        elif side == "away":
            away_row = row
    if not home_row or not away_row:
        return None

    home_team = home_row.get("team") if isinstance(home_row.get("team"), Mapping) else {}
    away_team = away_row.get("team") if isinstance(away_row.get("team"), Mapping) else {}

    status = event.get("status") if isinstance(event.get("status"), Mapping) else {}
    status_type = status.get("type") if isinstance(status.get("type"), Mapping) else {}
    espn_state = _text(status_type.get("state")).lower()
    in_progress = espn_state == "in"
    # BOTH SIGNALS, not just `completed`: a game can be `state=post` with
    # `completed` absent on some payload shapes, and reading only one would
    # leave a finished game ungraded all night. Copied deliberately from
    # `nfl/live_game_state._state_from_event`, which measured it.
    final = bool(status_type.get("completed")) or espn_state == "post"

    # A 0-0 "score" on a game that has not kicked off is a schedule
    # placeholder, not a result. Emitting it would let the grader settle every
    # pregame total as an under.
    home_score = _score_or_none(home_row.get("score")) if (in_progress or final) else None
    away_score = _score_or_none(away_row.get("score")) if (in_progress or final) else None

    return {
        "event_id": _text(event.get("id")),
        "home_team": _text(home_team.get("displayName")),
        "away_team": _text(away_team.get("displayName")),
        "home_abbr": _text(home_team.get("abbreviation")).upper(),
        "away_abbr": _text(away_team.get("abbreviation")).upper(),
        "home_score": home_score,
        "away_score": away_score,
        "in_progress": in_progress,
        "final": final,
        "status": _text(status_type.get("shortDetail")) or _text(status_type.get("description")),
        "start_time": _text(event.get("date")),
    }


def poll_nfl_live_state(iso_date: str, *, persist: bool = True) -> dict[str, Any]:
    """Capture one date's NFL games. Returns a named result, never raises.

    `status="error"` with a reason rather than an exception, matching every
    other capture in this tree: a venue or feed being unreachable must degrade
    to a NAMED refusal that a counter can show, not to a traceback that takes
    the settlement pass down with it.
    """
    payload = _fetch_scoreboard(iso_date)
    if payload is None:
        return {"status": "error", "reason": "scoreboard_unreachable", "date": iso_date, "games": []}

    events = payload.get("events")
    events = events if isinstance(events, list) else []
    games: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        game = _game_from_event(event)
        if game is not None:
            games.append(game)

    record = {
        "date": iso_date,
        "games": games,
        "count": len(games),
        "finals": sum(1 for game in games if game.get("final")),
    }
    if persist:
        try:
            from syndicate.features.shared.refresh_state_store import write_json_file

            write_json_file(live_state_path(iso_date), record)
        except Exception as exc:  # noqa: BLE001 -- named, never fatal to the caller
            # The capture still SUCCEEDED; only the persist failed. Reporting
            # those as one thing would make a Redis hiccup indistinguishable
            # from ESPN being down, and they need opposite responses.
            record["persist_error"] = f"{type(exc).__name__}: {exc}"
    record["status"] = "ok"
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="ISO date, e.g. 2026-08-28")
    parser.add_argument("--no-persist", action="store_true", help="fetch and print, write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = poll_nfl_live_state(args.date, persist=not args.no_persist)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"[poll_nfl_live_state] date={result.get('date')} status={result.get('status')}"
            f" games={result.get('count')} finals={result.get('finals')}"
            f" reason={result.get('reason')} persist_error={result.get('persist_error')}",
            flush=True,
        )
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
