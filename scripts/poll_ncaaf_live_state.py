"""Capture NCAAF game state for one DATE, so NCAAF bets can be graded.

    reports_root()/ncaaf_source/api/live_state/live_state_{date}.json

The sibling of `poll_nfl_live_state.py`, and the parsing is deliberately the
same code shape so the two cannot drift on ESPN payload handling. What differs
is the endpoint (`college-football`) and the JOIN downstream -- see
`bet_status_ncaaf` and `ncaaf_team_registry`, because NCAAF has no
`team_aliases` map and its name space is the dangerous part.

--------------------------------------------------------------------------
WHY THIS EXISTS: NCAAF IS ON THE BOARD AND CANNOT BE GRADED
--------------------------------------------------------------------------

`paper_settlement._default_resolver` gained `nfl` on 2026-08-28 and still has
nothing for ncaaf, so an NCAAF order returns `no_resolver_for_ncaaf`. That
counter is NOT yet visible in production -- NCAAF orders have not reached the
ledger -- but NCAAF reaches the board today: measured 2026-08-28T02:10Z in
`VENUE_REPRICE_KEYS`, kalshi offered **524 ncaaf quotes**, `wanted_overlap` 32,
**52 selected**. This is the `#547` shape being fixed BEFORE the volume lands
rather than after, which is the only time it is cheap.

A zero counter today is therefore NOT evidence that this works. The production
reading is future-dated and must be taken on a real NCAAF slate.

--------------------------------------------------------------------------
KEYED BY DATE, AND WRITTEN THROUGH `refresh_state_store`
--------------------------------------------------------------------------

Same two reasons as the NFL capture. Settlement's unit is `selected_date`, so
the fetch uses ESPN's `?dates=YYYYMMDD` form. And **settlement runs on
refresh-worker** while Render cannot share a disk between services, so this
persists via `write_json_file` (the keyvalue store under
`SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`, disk otherwise) and
`bet_status_ncaaf` reads with the matching `read_json_file`. A filesystem write
here would pass every test on a dev box and find nothing in production.

The path is allowlisted in `HOT_ARTIFACT_PATTERNS` for the filesystem case;
inert under keyvalue, and there so a backend change cannot silently strand it.
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

__all__ = ["poll_ncaaf_live_state", "live_state_path", "ARTIFACT_PARTS"]

_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
# Matches `nfl/live_game_state.py`. Short on purpose: a scoreboard outage must
# cost the capture, never the caller.
_FETCH_TIMEOUT_SECONDS = 6.0

ARTIFACT_PARTS = ("ncaaf_source", "api", "live_state")


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
    # `groups=80` is FBS and `limit=200` covers a full Saturday -- measured
    # 8 games on 2026-08-29 with and without them, but an opener weekend is
    # the SMALLEST slate of the season and a default page size that fits it
    # says nothing about a 60-game Saturday.
    url = f"{_SCOREBOARD_URL}?dates={compact}&groups=80&limit=200"
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


def poll_ncaaf_live_state(iso_date: str, *, persist: bool = True) -> dict[str, Any]:
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

    result = poll_ncaaf_live_state(args.date, persist=not args.no_persist)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"[poll_ncaaf_live_state] date={result.get('date')} status={result.get('status')}"
            f" games={result.get('count')} finals={result.get('finals')}"
            f" reason={result.get('reason')} persist_error={result.get('persist_error')}",
            flush=True,
        )
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
