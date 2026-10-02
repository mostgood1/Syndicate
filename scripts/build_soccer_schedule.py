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
    python scripts/build_soccer_schedule.py --league mls --near

`--near` (lane `layer2-freshness-1h`, 2026-10-02) refetches only the window
around today -- `NEAR_DAYS_BACK` before to `NEAR_DAYS_AHEAD` after -- and merges
it into the existing file by `event_id`, recomputing matchweeks over the result.
WHY: the soccer pregame refresh rebuilt all ten leagues' FULL seasons on every
run. Measured on the fleet that night (run 20261002_223521): schedule steps
were 1,327 of the run's 1,416 seconds (championship 241s, primeira_liga 197s,
epl 164s ...) against 11s of odds, so a run held the refresh lane ~24 min and
a 45-min soccer cadence would block every other sport's sweep half the time.
The near window keeps what changes on a match day current -- `status_state`
(a postponement voids the card: `sources.py` 2026-09-17) and scores -- in one
ESPN window instead of ~15. A fixture moved OUT of the window keeps its old
date until the next full rebuild, which the caller schedules
(`refresh_odds_sources._soccer_schedule_step`). No prior file, or an
unreadable one, falls back to a full build.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
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
NEAR_DAYS_BACK = 2
NEAR_DAYS_AHEAD = 7
# The fields a match row is built from; `week` is added by `compute_matchweeks`
# and is stripped before a merge so it is recomputed over the merged season.
_MATCH_FIELDS = ("event_id", "date", "home_team", "away_team", "home_score", "away_score", "status_state")


def _date_windows(league: str, season: int) -> list[str]:
    start, end = season_date_range(league, season)
    windows: list[str] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=_WINDOW_DAYS - 1), end)
        windows.append(f"{cursor.strftime('%Y%m%d')}-{window_end.strftime('%Y%m%d')}")
        cursor = window_end + timedelta(days=1)
    return windows


def schedule_file(out_root: Path, league: str, season: int) -> Path:
    return out_root / league / "api" / "schedule" / f"schedule_{season}.json"


def _match_rows(events: list[dict]) -> list[dict]:
    return [
        {field: event.get(field) for field in _MATCH_FIELDS}
        for event in events
        if event.get("home_team") and event.get("away_team")
    ]


def _write(league: str, season: int, matches: list[dict], *, out_root: Path, extra: dict) -> dict:
    matches = sorted(matches, key=lambda row: str(row.get("date") or ""))
    annotated_matches, week_index = compute_matchweeks(matches, league=league, season=season)
    payload = {
        "league": league,
        "season": season,
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        **extra,
        "match_count": len(annotated_matches),
        "weeks": week_index,
        "matches": annotated_matches,
    }
    out_path = schedule_file(out_root, league, season)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def build_schedule(league: str, season: int, *, out_root: Path) -> dict:
    windows = _date_windows(league, season)
    events = fetch_events(league, date_windows=windows)
    stamp = pd.Timestamp.now("UTC").isoformat()
    payload = _write(
        league, season, _match_rows(events), out_root=out_root,
        extra={"generated_at": stamp, "build_mode": "full", "full_generated_at": stamp},
    )
    print(
        f"wrote {schedule_file(out_root, league, season)} ({payload['match_count']} matches across "
        f"{len(payload['weeks'])} weeks, {len(windows)} ESPN windows queried)"
    )
    return payload


def near_window(league: str, season: int, today: date) -> str | None:
    """`YYYYMMDD-YYYYMMDD` around `today`, clamped to the season; None outside it."""
    start, end = season_date_range(league, season)
    lo = max(start, today - timedelta(days=NEAR_DAYS_BACK))
    hi = min(end, today + timedelta(days=NEAR_DAYS_AHEAD))
    if lo > hi:
        return None
    return f"{lo.strftime('%Y%m%d')}-{hi.strftime('%Y%m%d')}"


def build_schedule_near(league: str, season: int, *, out_root: Path, today: date | None = None) -> dict | None:
    """Refetch the window around today and merge it into the existing schedule.

    Returns the written payload, the prior one when the season has no near
    window (nothing written), or a FULL build when there is no usable prior file.
    """
    path = schedule_file(out_root, league, season)
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
        prior_matches = prior.get("matches") if isinstance(prior, dict) else None
        if not isinstance(prior_matches, list) or not prior_matches:
            raise ValueError("no matches")
    except Exception as exc:
        print(f"near: no usable prior schedule at {path} ({type(exc).__name__}); full build")
        return build_schedule(league, season, out_root=out_root)
    window = near_window(league, season, today or datetime.now(timezone.utc).date())
    if window is None:
        print(f"near: {league} {season} has no window around today; schedule unchanged")
        return prior
    fresh = _match_rows(fetch_events(league, date_windows=[window]))
    merged: dict[str, dict] = {}
    unkeyed: list[dict] = []
    for row in prior_matches:
        if not isinstance(row, dict):
            continue
        base = {field: row.get(field) for field in _MATCH_FIELDS}
        if base.get("event_id"):
            merged[str(base["event_id"])] = base
        else:
            unkeyed.append(base)
    replaced = added = 0
    for row in fresh:
        key = str(row.get("event_id") or "")
        if not key:
            unkeyed.append(row)
            continue
        if key in merged:
            replaced += 1
        else:
            added += 1
        merged[key] = row
    payload = _write(
        league, season, list(merged.values()) + unkeyed, out_root=out_root,
        extra={
            "build_mode": "near",
            "near_window": window,
            # The age the caller schedules the next FULL rebuild from.
            "full_generated_at": prior.get("full_generated_at") or prior.get("generated_at"),
        },
    )
    print(
        f"wrote {path} (near {window}: {len(fresh)} fetched, {replaced} replaced, {added} added; "
        f"{payload['match_count']} matches total, 1 ESPN window queried)"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(LEAGUE_ESPN_SLUGS))
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--out-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    parser.add_argument("--near", action="store_true", help="refetch only the window around today and merge")
    args = parser.parse_args()
    season = args.season or default_season(args.league)
    if args.near:
        build_schedule_near(args.league, season, out_root=Path(args.out_root))
    else:
        build_schedule(args.league, season, out_root=Path(args.out_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
