"""Build WNBA final player boxscores for a date, Syndicate-owned, from ESPN.

WHY THIS EXISTS. `wnba_source/data/processed/boxscores_<date>.csv` is the
post-game player stat line several things join against -- basketball home-court
advantage, sim calibration, the smart-sim roster augmentation -- and it is the
only source that can tell WNBA settlement a game is OVER. It stopped being
produced. MEASURED 2026-08-26 against production
(`/api/ops/artifacts/export?pattern=wnba_source/data/processed/boxscores_2*.csv`):

    2026-04:  5 files
    2026-05: 18 files   <- coverage ends 2026-05-24
    2026-06:  0
    2026-07:  0
    2026-08:  1         <- a lone 2026-08-18 orphan, three months later

Prior seasons ran 21-31 files a month, continuously. This one stopped in May.

**NOTHING IN SYNDICATE EVER PRODUCED IT.** Every caller of the vendor's
`fetch_boxscores_for_date` lives inside `vendor/*_betting_repo/`.
`scripts/artifact_freshness.py:67` MONITORS the family ("wnba boxscores") while
nothing writes it, so the gap was being reported to nobody for three months.

WHY NATIVE AND NOT THE VENDOR CLI `[user decision 2026-08-26]`: "everything runs
on render production of syndicate -- we should NOT be using the vendored items."
That is also CLAUDE.md's stated direction (vendor exit, Syndicate-owned artifact
generation per sport), and the standalone WNBA-Betting service is suspended, so
reviving it would have been a step backwards on both counts.

WHAT MAKES THIS THE FINAL SOURCE. ESPN's scoreboard marks each event
`status.type.completed` / `state: "post"`, and this writes ONLY completed games.
`bet_status_wnba` currently hardcodes `is_final=False` because the LIVE player
box carries no game status -- so an over that never crosses its line can never
decide, and only WINNING overs settle. MEASURED on the 2026-08-25 slate: Sonia
Citron 1 rebound against over 3.5 and Georgia Amoore 3 assists against over 3.5
are both LOSSES that will never be recorded, while Natasha Mack's over 7.5 (8
rebounds) graded within minutes. Any WNBA performance number built on that is
wins-only by construction.

Exit codes:  0 wrote  1 nothing final on the slate (not a failure)  2 fetched but empty
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from datetime import date as _date
from datetime import timedelta as _timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
_SUMMARY = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"

# The column contract, taken VERBATIM from an existing artifact
# (`boxscores_2026-06-04.csv`) rather than invented, so the readers that already
# join against this file keep working. `game_id` and `gameId` are both present
# and identical in the real files; both are kept for the same reason.
COLUMNS: tuple[str, ...] = (
    "game_id", "gameId", "TEAM_ABBREVIATION", "PLAYER_ID", "PLAYER_NAME",
    "MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "OREB", "DREB", "PF",
    "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "PLUS_MINUS",
    "STARTER", "START_POSITION", "source", "date",
)

# ESPN's own key names, READ FROM A REAL SUMMARY rather than guessed
# (event 401857175, 2026-08-26):
#   ['minutes','points','fieldGoalsMade-fieldGoalsAttempted',
#    'threePointFieldGoalsMade-threePointFieldGoalsAttempted',
#    'freeThrowsMade-freeThrowsAttempted','rebounds','assists','turnovers',
#    'steals','blocks','offensiveRebounds','defensiveRebounds','fouls','plusMinus']
_SCALARS = {
    "MIN": "minutes", "PTS": "points", "REB": "rebounds", "AST": "assists",
    "STL": "steals", "BLK": "blocks", "TOV": "turnovers",
    "OREB": "offensiveRebounds", "DREB": "defensiveRebounds", "PF": "fouls",
    "PLUS_MINUS": "plusMinus",
}
# The made-attempted pairs arrive as one "5-12" string.
_PAIRS = {
    ("FGM", "FGA"): "fieldGoalsMade-fieldGoalsAttempted",
    ("FG3M", "FG3A"): "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
    ("FTM", "FTA"): "freeThrowsMade-freeThrowsAttempted",
}


def _get(url: str, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def completed_event_ids(date_str: str) -> list[str]:
    """Event ids for games ESPN reports as FINISHED. Only these may be written.

    `status.type.completed` is the authority; `state == "post"` is accepted as
    the same claim because the scoreboard sets them together. A game still in
    progress is EXCLUDED rather than written with partial stats -- a boxscore
    that grows is worse than one that is absent, because a consumer cannot tell
    a half-game from a low-scoring one.
    """
    payload = _get(f"{_SCOREBOARD}?dates={str(date_str).replace('-', '')}")
    out: list[str] = []
    for event in payload.get("events") or []:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        status = ((event.get("status") or {}).get("type")) or {}
        if bool(status.get("completed")) or str(status.get("state") or "").lower() == "post":
            out.append(event_id)
    return out


def _split_pair(raw: Any) -> tuple[str, str]:
    text = str(raw or "").strip()
    if "-" not in text:
        return ("", "")
    made, _, attempted = text.partition("-")
    return (made.strip(), attempted.strip())


def rows_for_event(event_id: str, date_str: str) -> list[dict[str, Any]]:
    """One row per player with a stat line, from the OFFICIAL box."""
    summary = _get(f"{_SUMMARY}?event={urllib.request.quote(str(event_id))}")
    out: list[dict[str, Any]] = []
    for team_block in (summary.get("boxscore") or {}).get("players") or []:
        team = team_block.get("team") if isinstance(team_block.get("team"), dict) else {}
        abbreviation = str(team.get("abbreviation") or "").strip().upper()
        for stat_block in team_block.get("statistics") or []:
            keys = [str(k) for k in (stat_block.get("keys") or [])]
            index = {name: position for position, name in enumerate(keys)}
            for athlete in stat_block.get("athletes") or []:
                stats = athlete.get("stats") or []
                if not stats:
                    # A DNP carries no stat line. Skipped rather than written as
                    # zeros: "did not play" and "played and scored nothing" are
                    # different facts and a prop settles differently on each.
                    continue
                info = athlete.get("athlete") if isinstance(athlete.get("athlete"), dict) else {}
                row: dict[str, Any] = {column: "" for column in COLUMNS}
                row["game_id"] = event_id
                row["gameId"] = event_id
                row["TEAM_ABBREVIATION"] = abbreviation
                row["PLAYER_ID"] = str(info.get("id") or "").strip()
                row["PLAYER_NAME"] = str(info.get("displayName") or "").strip()
                row["STARTER"] = str(bool(athlete.get("starter")))
                position = athlete.get("position") if isinstance(athlete.get("position"), dict) else {}
                row["START_POSITION"] = str(position.get("abbreviation") or "").strip()
                row["source"] = "espn"
                row["date"] = date_str
                for column, key in _SCALARS.items():
                    at = index.get(key)
                    if at is not None and at < len(stats):
                        row[column] = str(stats[at]).strip()
                for (made_column, attempted_column), key in _PAIRS.items():
                    at = index.get(key)
                    if at is not None and at < len(stats):
                        made, attempted = _split_pair(stats[at])
                        row[made_column], row[attempted_column] = made, attempted
                if not row["PLAYER_NAME"]:
                    continue
                out.append(row)
    return out


def artifact_relative_path(date_str: str) -> str:
    return f"wnba_source/data/processed/boxscores_{date_str}.csv"


def to_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in COLUMNS})
    return buffer.getvalue()



def web_base_url() -> str:
    """Where the final box is fetched from when we cannot reach ESPN ourselves.

    Same env chain as `live_lens_loop._wnba_live_box_base_url`, because it is
    the same hop for the same reason: the worker-to-web hostname is internal in
    production and public everywhere else.
    """
    import os

    return str(
        os.environ.get("SYNDICATE_WNBA_LIVE_BOX_BASE_URL")
        or os.environ.get("SYNDICATE_INTERNAL_WEB_BASE_URL")
        or "https://syndicate-an21.onrender.com"
    ).strip().rstrip("/")


def fetch_via_web(base_url: str, date_str: str, *, count_only: bool = False) -> dict[str, Any]:
    """Ask WEB for the date's completed games, and optionally their rows.

    ESPN REFUSES RENDER'S EGRESS. Measured 2026-08-26 from `intelligence_state`
    on refresh-worker:

        WNBA_BOXSCORES_SCOREBOARD_FAILED date=2026-08-25 HTTP Error 403: Forbidden

    on every attempt, while the same call from a laptop returned 3 games and 66
    rows. Web is not refused -- `WNBA_LIVE_BOX_CAPTURED date=2026-08-25 games=3
    players=66` is the live capture making this exact hop successfully. So the
    producer asks web, exactly as `capture_wnba_live_player_box.py` does.

    `count_only` costs ONE scoreboard call and no per-event fetches, which is
    what makes the every-3-minute gate cheap.
    """
    import urllib.parse

    query = urllib.parse.urlencode(
        {"date": date_str, **({"count_only": "1"} if count_only else {})}
    )
    payload = _get(f"{base_url}/wnba/api/final_player_boxscore?{query}", timeout=90)
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "web refused the final box"))
    return payload


def build_date(date_str: str, *, dry_run: bool = False,
               base_url: str | None = None) -> dict[str, Any]:
    """Fetch, assemble and persist one slate. Returns a summary, never raises."""
    from syndicate.features.shared.refresh_state_store import data_root, write_text_file

    rows: list[dict[str, Any]] = []
    if base_url:
        # VIA WEB, because ESPN 403s Render's egress. See `fetch_via_web`.
        try:
            payload = fetch_via_web(base_url, date_str)
        except Exception as exc:  # noqa: BLE001
            print(f"[wnba_boxscores] WEB_FETCH_FAILED date={date_str} "
                  f"{type(exc).__name__}: {exc}", flush=True)
            return {"date": date_str, "status": "web_fetch_failed", "games": 0, "rows": 0}
        event_ids = [""] * int(payload.get("games") or 0)
        rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
        for failure in payload.get("failed_events") or []:
            # Surfaced rather than hidden: a partial slate must not be mistaken
            # for a complete one, or the rebuild gate stops rebuilding.
            print(f"[wnba_boxscores] EVENT_FAILED date={date_str} "
                  f"event={failure.get('event_id')} {failure.get('error')}", flush=True)
    else:
        try:
            event_ids = completed_event_ids(date_str)
        except Exception as exc:  # noqa: BLE001
            print(f"[wnba_boxscores] SCOREBOARD_FAILED date={date_str} "
                  f"{type(exc).__name__}: {exc}", flush=True)
            return {"date": date_str, "status": "scoreboard_failed", "games": 0, "rows": 0}

        for event_id in event_ids:
            try:
                rows.extend(rows_for_event(event_id, date_str))
            except Exception as exc:  # noqa: BLE001
                # One event's failure must not cost the rest of the slate.
                print(f"[wnba_boxscores] EVENT_FAILED date={date_str} event={event_id} "
                      f"{type(exc).__name__}: {exc}", flush=True)

    if not event_ids:
        print(f"[wnba_boxscores] NO_FINAL_GAMES date={date_str} -- nothing written", flush=True)
        return {"date": date_str, "status": "no_final_games", "games": 0, "rows": 0}
    if not rows:
        # REFUSES TO STORE AN EMPTY CAPTURE, same rule as
        # `capture_wnba_live_player_box`: a well-formed file carrying no data
        # reads as an answer to every consumer, and a persisted empty is served
        # in preference to real data afterwards.
        print(f"[wnba_boxscores] EMPTY date={date_str} games={len(event_ids)} "
              "-- nothing written", flush=True)
        return {"date": date_str, "status": "empty", "games": len(event_ids), "rows": 0}

    payload = to_csv(rows)
    relative = artifact_relative_path(date_str)
    if dry_run:
        print(f"[wnba_boxscores] DRY_RUN date={date_str} games={len(event_ids)} "
              f"rows={len(rows)} bytes={len(payload)} path={relative}", flush=True)
        return {"date": date_str, "status": "dry_run", "games": len(event_ids),
                "rows": len(rows), "bytes": len(payload), "csv": payload}

    write_text_file(data_root() / relative, payload)
    print(f"[wnba_boxscores] WROTE date={date_str} games={len(event_ids)} "
          f"rows={len(rows)} bytes={len(payload)} path={relative}", flush=True)
    return {"date": date_str, "status": "ok", "games": len(event_ids), "rows": len(rows)}


def _dates(start: str, end: str) -> list[str]:
    first, last = _date.fromisoformat(start), _date.fromisoformat(end)
    out: list[str] = []
    while first <= last:
        out.append(first.isoformat())
        first += _timedelta(days=1)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--date", help="single slate, YYYY-MM-DD")
    parser.add_argument("--start", help="backfill start, YYYY-MM-DD")
    parser.add_argument("--end", help="backfill end, YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and report, write nothing")
    parser.add_argument("--via-web", action="store_true",
                        help="fetch through the web service instead of ESPN directly"
                             " -- required on Render, where ESPN returns 403")
    args = parser.parse_args(argv)

    if args.start and args.end:
        targets = _dates(args.start, args.end)
    elif args.date:
        targets = [args.date]
    else:
        targets = [(_date.today() - _timedelta(days=1)).isoformat()]

    wrote = 0
    empty = 0
    for date_str in targets:
        result = build_date(date_str, dry_run=bool(args.dry_run),
                            base_url=web_base_url() if args.via_web else None)
        if result.get("status") in {"ok", "dry_run"}:
            wrote += 1
        elif result.get("status") == "empty":
            empty += 1

    print(f"[wnba_boxscores] SUMMARY dates={len(targets)} wrote={wrote} empty={empty}",
          flush=True)
    if wrote:
        return 0
    return 2 if empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
