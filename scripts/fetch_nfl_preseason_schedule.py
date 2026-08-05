"""Fetch and cache the real NFL preseason schedule for one season from
ESPN's public scoreboard API.

nflverse -- this repo's entire NFL data backbone (schedule_{season}.csv,
pbp_{season}.csv, the whole generate_smartsim2_nfl_projections.py rating
pipeline) has ZERO preseason data of any kind. Confirmed live against the
real nflverse games.csv release for both 2025 and 2026: only
REG/WC/DIV/CON/SB game types exist, PRE never appears -- this is
structural, not a publishing lag, so this script deliberately does not
try nflverse at all.

ESPN's public scoreboard API does have the real preseason schedule,
verified live 2026-08-05: a single date-range query against
`.../football/nfl/scoreboard?dates=YYYYMMDD-YYYYMMDD` returns every real
preseason game in that window, with ESPN's own `week.number` (1-4)
already correctly bucketing Hall of Fame Weekend / Preseason Week 1/2/3.
This mirrors scripts/fetch_nfl_schedule.py's structure (SCHEDULE_COLUMNS
tuple, a `..._path()` function, argparse CLI) but sources ESPN instead of
nflverse, and reuses the exact request shape already proven in production
by syndicate/features/shared/schedule_adapter.py::_fetch_espn_football_schedule
-- critically, NO custom User-Agent header (ESPN 403s any browser-like/
spoofed UA from Render's outbound IP; only urllib's bare default UA
works).

Writes data/nfl_source/schedule_preseason_{season}.csv -- a separate file
from schedule_{season}.csv (the real regular-season schedule), never
merged with it, so nothing regular-season-scoped (nfl_target_week(),
week_summaries(), the SmartSim2 filename regex) ever sees these rows.

Usage:
    python scripts/fetch_nfl_preseason_schedule.py --season 2026
    python scripts/fetch_nfl_preseason_schedule.py --season 2025 --date-start 2025-08-01 --date-end 2025-09-10
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.sources import default_nfl_source_root  # noqa: E402

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# 2021+ is the practical floor for a 3-preseason-game backfill (the CBA
# change that dropped the 4th preseason game) -- noted here, not enforced,
# since ESPN's real data is the actual source of truth either way.
SCHEDULE_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "game_type",
    "week",
    "gameday",
    "gametime",
    "away_team",
    "home_team",
    "away_score",
    "home_score",
    "status",
    "venue",
)


def preseason_schedule_path(season: int, *, source_root: Path | None = None) -> Path:
    root = source_root if source_root is not None else default_nfl_source_root()
    return root / f"schedule_preseason_{season}.csv"


def fetch_espn_preseason_events(*, date_start: str, date_end: str, timeout: int = 12) -> list[dict[str, Any]]:
    """Real events from ESPN's scoreboard API for one date range,
    YYYY-MM-DD in, ESPN's own compact YYYYMMDD-YYYYMMDD out. Byte-identical
    request shape to schedule_adapter.py::_fetch_espn_football_schedule
    (no custom headers, broad catch-and-empty) -- deliberately not reusing
    that function directly since it only extracts a minimal row shape
    (home/away display name + start time) for the 15-minute live-refresh
    cache it feeds; this script needs the richer real fields (week number,
    scores, status, venue, tricodes) for a durable season artifact."""
    try:
        compact_start = datetime.strptime(date_start, "%Y-%m-%d").strftime("%Y%m%d")
        compact_end = datetime.strptime(date_end, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return []
    url = f"{ESPN_SCOREBOARD_URL}?dates={compact_start}-{compact_end}"
    request_obj = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return []
    events = payload.get("events") if isinstance(payload, dict) else None
    return [event for event in (events or []) if isinstance(event, dict)]


def rows_from_events(events: list[dict[str, Any]], season: int) -> list[dict[str, str]]:
    """One real row per preseason game. Only real events whose own
    season.type == 1 (ESPN's preseason marker) are kept -- a date-range
    query can span into real regular-season games at the tail end, so this
    is the actual filter, not the date range itself."""
    rows: list[dict[str, str]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        season_info = event.get("season") if isinstance(event.get("season"), dict) else {}
        if season_info.get("type") != 1:
            continue
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions else {}
        if not isinstance(competition, dict):
            continue
        competitors = competition.get("competitors") or []
        home = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "away"), {})
        game_id = str(event.get("id") or "").strip()
        week_info = event.get("week") if isinstance(event.get("week"), dict) else {}
        week = week_info.get("number")
        if not game_id or week not in (1, 2, 3, 4):
            continue
        status_info = competition.get("status") if isinstance(competition.get("status"), dict) else {}
        status_type = status_info.get("type") if isinstance(status_info.get("type"), dict) else {}
        venue_info = competition.get("venue") if isinstance(competition.get("venue"), dict) else {}
        raw_date = str(event.get("date") or "")
        gameday, _, gametime = raw_date.partition("T")
        rows.append(
            {
                "game_id": game_id,
                "season": str(season),
                "game_type": "PRE",
                "week": str(week),
                "gameday": gameday,
                "gametime": gametime.rstrip("Z"),
                "away_team": str((away.get("team") or {}).get("abbreviation") or "").strip(),
                "home_team": str((home.get("team") or {}).get("abbreviation") or "").strip(),
                "away_score": str(away.get("score") or ""),
                "home_score": str(home.get("score") or ""),
                "status": str(status_type.get("description") or ""),
                "venue": str(venue_info.get("fullName") or ""),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--date-start", type=str, default=None, help="YYYY-MM-DD, defaults to Aug 1 of --season")
    parser.add_argument("--date-end", type=str, default=None, help="YYYY-MM-DD, defaults to Sep 10 of --season")
    args = parser.parse_args()

    date_start = args.date_start or f"{args.season}-08-01"
    date_end = args.date_end or f"{args.season}-09-10"

    events = fetch_espn_preseason_events(date_start=date_start, date_end=date_end)
    rows = rows_from_events(events, args.season)

    path = preseason_schedule_path(args.season)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEDULE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    weeks = sorted({int(row["week"]) for row in rows})
    print(f"games_written={len(rows)}")
    print(f"weeks={weeks}")
    print(f"schedule_path={path}")


if __name__ == "__main__":
    main()
