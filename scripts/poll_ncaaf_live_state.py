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
import time
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


def _board_fields_from_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """The four fields the BOARD needs and settlement does not.

    NOT ADDED TO `_game_from_event`, DELIBERATELY. That function is the single
    definition of what "in progress" and "final" mean, imported unmodified by
    `ncaaf/live_game_state.py`, `ncaaf/live_resim.py` and refresh-worker's
    NCAAF tick -- its own docstring and all three call sites say so. Widening
    it to carry board-only fields would make a board concern a settlement
    concern, which is the drift those warnings exist to prevent.

    So the extra fields ride ALONGSIDE it in the persisted record instead.
    This is the identical extraction `ncaaf/live_game_state._state_rows_for_date`
    performs on web today, moved to the producer so the board can READ the
    result instead of re-fetching ESPN to compute it -- read off the SAME
    `competitions[0]` mapping, so it cannot disagree with the state beside it.

    `home_id` / `away_id` are ESPN's team ids, which are the board index's join
    key (`"{away_id}@{home_id}"`). `period` and `clock` are the eyebrow.
    """
    out: dict[str, Any] = {}
    competitions = event.get("competitions")
    competitions = competitions if isinstance(competitions, list) else []
    competition = competitions[0] if competitions and isinstance(competitions[0], Mapping) else {}

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
            out[f"{side}_id"] = team_id

        # `location`, ALONGSIDE the displayName `_game_from_event` already keeps,
        # because the two are not interchangeable as a JOIN KEY. The NCAAF
        # projections artifact carries no ESPN id -- only `home_team`/`away_team`
        # -- and lane `ncaaf-live-resim-wire` measured the difference on the
        # live 2026-09-05 slate: ESPN `team.location` matched **35 of 51** board
        # games, `team.displayName` matched **0**. Verified here 2026-09-06:
        # location `'Washington'` vs displayName `'Washington Huskies'`. Keying
        # off displayName indexes NOTHING while looking perfectly healthy.
        location = str(team.get("location") or "").strip()
        if location:
            out[f"{side}_location"] = location

    status = event.get("status") if isinstance(event.get("status"), Mapping) else {}
    period = status.get("period")
    if isinstance(period, (int, float)) and period:
        out["period"] = int(period)
    clock = str(status.get("displayClock") or "").strip()
    if clock:
        out["clock"] = clock

    # `situation` RAW AND UNRESOLVED, ON PURPOSE. It is down / distance /
    # yardLine / possession, and `live_resim.resim_live_game` needs it: without
    # it every drive starts 1st-and-10 on the 25 with possession marginalised,
    # which is not a lost diagnostic but a WORSE PROBABILITY -- and an unfed
    # model input is indistinguishable from a working one at every level except
    # the data (`model_engine_standard.md`).
    #
    # NOT RESOLVED HERE. ESPN names the possessing TEAM BY ID
    # (`situation.possession = "2"`), never by side, and
    # `live_resim.possession_side_from_espn` already owns that resolution --
    # it takes a competition mapping and the two ids, both of which a consumer
    # can rebuild from this record. Resolving it here would make a SECOND
    # parser of the same field, which is the drift `_game_from_event`'s own
    # docstring exists to prevent.
    #
    # ABSENT ON PREGAME EVENTS AND THAT IS CORRECT -- verified 2026-09-06, a
    # `state="pre"` competition carries no `situation` at all. Consumers must
    # gate on in-progress; requiring it of a pregame row would refuse a correct
    # record forever.
    situation = competition.get("situation")
    if isinstance(situation, Mapping):
        out["situation"] = dict(situation)
    return out


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
            # Board fields ride alongside the settlement record -- see
            # `_board_fields_from_event` for why they are not IN it.
            game = {**game, **_board_fields_from_event(event)}
            games.append(game)

    record = {
        "date": iso_date,
        "games": games,
        "count": len(games),
        "finals": sum(1 for game in games if game.get("final")),
        # THE READER'S FRESHNESS TEST. Without it a consumer cannot tell a
        # record written 20 seconds ago from one written at yesterday's
        # kickoff, and a stale record pinning the board to old scores is worse
        # than the fetch this whole change removes.
        "fetched_at": time.time(),
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


def week_state_dates(season: int, week: int) -> tuple[str, ...]:
    """The dates the BOARD will ask for -- resolved here, at run time.

    THE PRODUCER MUST COVER THE READER'S DATE SET OR IT ONLY PARTLY WORKS.
    `ncaaf/live_game_state.ncaaf_game_state_index` iterates
    `past_or_current_dates(_ncaaf_week_kickoff_dates(season, week))`, and an
    NCAAF week is not a calendar window -- 2026 week 1 spans 08-29..09-07.
    Measured in production 2026-09-06: the board asked for **6 dates**
    (`source=fetch=6`). A producer writing only `--date` would have covered one
    of six and left web fetching the other five, which reads as "the fix
    works" on any check that only looks at today.

    Resolved in THIS subprocess rather than in `refresh_odds_sources`, so the
    orchestrator does not import the (large) cards module just to build a step.
    Returns `()` on any failure -- the caller then falls back to the single
    date it was given, which is strictly better than polling nothing.
    """
    try:
        from syndicate.features.ncaaf.cards import _ncaaf_week_kickoff_dates
        from syndicate.features.ncaaf.live_game_state import past_or_current_dates

        return tuple(past_or_current_dates(_ncaaf_week_kickoff_dates(int(season), int(week))))
    except Exception as exc:  # noqa: BLE001 -- named, never fatal
        print(
            f"[poll_ncaaf_live_state] WEEK_DATES_UNAVAILABLE season={season} week={week} "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        return ()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="ISO date, e.g. 2026-08-28")
    parser.add_argument("--season", type=int, default=None,
                        help="with --week, also poll every past-or-current kickoff date in that week")
    parser.add_argument("--week", type=int, default=None,
                        help="with --season, also poll every past-or-current kickoff date in that week")
    parser.add_argument("--no-persist", action="store_true", help="fetch and print, write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dates: list[str] = [args.date]
    if args.season is not None and args.week is not None:
        for iso in week_state_dates(args.season, args.week):
            if iso not in dates:
                dates.append(iso)

    results = [poll_ncaaf_live_state(iso, persist=not args.no_persist) for iso in dates]
    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=2))
    else:
        for result in results:
            print(
                f"[poll_ncaaf_live_state] date={result.get('date')} status={result.get('status')}"
                f" games={result.get('count')} finals={result.get('finals')}"
                f" reason={result.get('reason')} persist_error={result.get('persist_error')}",
                flush=True,
            )
        print(
            f"[poll_ncaaf_live_state] COVERAGE dates={len(results)} "
            f"ok={sum(1 for r in results if r.get('status') == 'ok')}",
            flush=True,
        )
    return 0 if all(r.get("status") == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
