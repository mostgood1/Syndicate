"""Matchweek computation for soccer schedules.

No source this pipeline uses (ESPN's site API, football-data.co.uk) publishes
an official matchday/round number for a fixture -- confirmed by inspection,
not assumed. This derives one instead: bucket a league-season's full fixture
list into 7-day windows from the season's start date, then renumber
sequentially so only weeks that actually have a fixture get a number. This is
the same practical effect as how NFL's weeks are literally defined (a fixed
Tue-Mon window) -- close enough for "which week is this match in" browsing,
though a fixture rearranged across a week boundary (postponements, makeup
midweek dates) can land in a bucket a fan wouldn't call its "official"
matchday. Documented limitation, not treated as ground truth for anything
that needs exact round numbers (e.g. standings).
"""

from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import timedelta
from typing import Any

# MLS runs a single calendar-year season (Feb-Dec); the rest of the leagues
# this pipeline covers run the European Aug-May calendar, labeled by the
# start year (matching the existing `season` column convention in
# data/soccer_source/*/history/matches_{season}.csv).
_CALENDAR_YEAR_LEAGUES = {"mls"}


def season_date_range(league: str, season: int) -> tuple[date, date]:
    season = int(season)
    if str(league).strip().lower() in _CALENDAR_YEAR_LEAGUES:
        return date(season, 2, 1), date(season, 12, 15)
    return date(season, 8, 1), date(season + 1, 5, 31)


def default_season(league: str, *, today: date | None = None) -> int:
    today = today or date.today()
    if str(league).strip().lower() in _CALENDAR_YEAR_LEAGUES:
        return today.year
    # European calendar: Jan-Jun belongs to the season that started the
    # previous August.
    return today.year if today.month >= 7 else today.year - 1


def _parse_match_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        return None


def compute_matchweeks(matches: list[dict[str, Any]], *, league: str, season: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (matches-with-week-attached, week-index).

    ``week-index`` is ``[{"week": 1, "start_date": "...", "end_date": "...",
    "match_count": N}, ...]`` sorted by week number.
    """
    season_start, _season_end = season_date_range(league, season)
    bucket_by_match: dict[int, int] = {}
    raw_bucket_dates: dict[int, date] = {}
    for index, match in enumerate(matches):
        match_date = _parse_match_date(match.get("date"))
        if match_date is None:
            continue
        offset_days = (match_date - season_start).days
        bucket = offset_days // 7
        bucket_by_match[index] = bucket
        raw_bucket_dates.setdefault(bucket, match_date)

    ordered_buckets = sorted(set(bucket_by_match.values()))
    week_number_by_bucket = {bucket: week for week, bucket in enumerate(ordered_buckets, start=1)}

    annotated: list[dict[str, Any]] = []
    week_dates: dict[int, list[date]] = {}
    for index, match in enumerate(matches):
        bucket = bucket_by_match.get(index)
        week = week_number_by_bucket.get(bucket) if bucket is not None else None
        row = dict(match)
        row["week"] = week
        annotated.append(row)
        match_date = _parse_match_date(match.get("date"))
        if week is not None and match_date is not None:
            week_dates.setdefault(week, []).append(match_date)

    week_index = [
        {
            "week": week,
            "start_date": min(dates).isoformat(),
            "end_date": max(dates).isoformat(),
            "match_count": len(dates),
        }
        for week, dates in sorted(week_dates.items())
    ]
    return annotated, week_index


__all__ = ["compute_matchweeks", "default_season", "season_date_range"]
