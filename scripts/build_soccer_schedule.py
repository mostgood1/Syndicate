"""Write a league's full-season fixture schedule, with computed matchweeks.

Pages through ESPN's scoreboard across the whole season in ~3-week windows
(its date-range query silently truncates around ~100 events per call, so a
whole season in one query would drop fixtures) via the same `fetch_events`
helper the rest of this pipeline already uses, then buckets the results into
matchweeks (see `features/soccer/features/schedule.py` for why this is
computed rather than sourced -- no upstream feed publishes a real matchday
number). Writes:

    data/soccer_source/{league}/api/schedule/schedule_{season}.json

This is what makes week-based navigation and a team's full-season schedule
page possible; `build_soccer_artifacts.py --week N` also reads it to resolve
a week to the dates it needs to simulate.

Usage:
    python scripts/build_soccer_schedule.py --league mls --season 2026
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.features.schedule import compute_matchweeks
from syndicate.features.soccer.features.schedule import default_season
from syndicate.features.soccer.features.schedule import season_date_range
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_lineups import fetch_events

_WINDOW_DAYS = 21


def _date_windows(league: str, season: int) -> list[str]:
    start, end = season_date_range(league, season)
    windows: list[str] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=_WINDOW_DAYS - 1), end)
        windows.append(f"{cursor.strftime('%Y%m%d')}-{window_end.strftime('%Y%m%d')}")
        cursor = window_end + timedelta(days=1)
    return windows


def build_schedule(league: str, season: int, *, out_root: Path) -> dict:
    windows = _date_windows(league, season)
    events = fetch_events(league, date_windows=windows)
    matches = [
        {
            "event_id": event.get("event_id"),
            "date": event.get("date"),
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "home_score": event.get("home_score"),
            "away_score": event.get("away_score"),
            "status_state": event.get("status_state"),
        }
        for event in events
        if event.get("home_team") and event.get("away_team")
    ]
    matches.sort(key=lambda row: str(row.get("date") or ""))
    annotated_matches, week_index = compute_matchweeks(matches, league=league, season=season)

    payload = {
        "league": league,
        "season": season,
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "match_count": len(annotated_matches),
        "weeks": week_index,
        "matches": annotated_matches,
    }
    out_path = out_root / league / "api" / "schedule" / f"schedule_{season}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(annotated_matches)} matches across {len(week_index)} weeks, {len(windows)} ESPN windows queried)")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(LEAGUE_ESPN_SLUGS))
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    args = parser.parse_args()
    season = args.season or default_season(args.league)
    build_schedule(args.league, season, out_root=Path(args.out_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
