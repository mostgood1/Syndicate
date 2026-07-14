from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


_WEEK_WINDOW_PADDING_DAYS = 3

_NFL_RECS_RE = re.compile(r"^upcoming_recs_(?P<season>\d{4})_wk(?P<week>\d+)(?:_publish)?\.csv$")
_NCAAF_SCHEDULE_RE = re.compile(r"^college_football_schedule_(?P<season>\d{4})_predicted_totals_enhanced.*\.csv$")


def _parse_date_token(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except Exception:
        pass
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _windows_from_grouped_dates(grouped: dict[tuple[int, int], list[date]]) -> list[dict[str, Any]]:
    padding = timedelta(days=_WEEK_WINDOW_PADDING_DAYS)
    windows: list[dict[str, Any]] = []
    for (season, week), dates in grouped.items():
        if not dates:
            continue
        windows.append(
            {
                "season": season,
                "week": week,
                "start": min(dates) - padding,
                "end": max(dates) + padding,
            }
        )
    windows.sort(key=lambda item: (item["season"], item["week"]))
    return windows


def _nfl_week_windows(source_root: Path) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[date]] = {}
    seen_paths: set[Path] = set()
    for root in (source_root, source_root / "source_artifacts"):
        if not root.exists():
            continue
        for path in root.glob("upcoming_recs_*.csv"):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            match = _NFL_RECS_RE.match(path.name)
            if not match:
                continue
            season = int(match.group("season"))
            week = int(match.group("week"))
            try:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    for row in csv.DictReader(handle):
                        parsed = _parse_date_token(row.get("game_date"))
                        if parsed is not None:
                            grouped.setdefault((season, week), []).append(parsed)
            except Exception:
                continue
    return _windows_from_grouped_dates(grouped)


def _ncaaf_week_windows(source_root: Path) -> list[dict[str, Any]]:
    # NCAAF's schedule feed sometimes labels bowl/postseason games with a
    # placeholder "week" (often 1) far outside the regular season -- this
    # widens that week's window rather than raising, matching the accepted
    # imperfection in this data source noted elsewhere in this codebase.
    grouped: dict[tuple[int, int], list[date]] = {}
    seen_paths: set[Path] = set()
    for root in (source_root / "source_artifacts", source_root):
        if not root.exists():
            continue
        for path in root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv"):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            if not _NCAAF_SCHEDULE_RE.match(path.name):
                continue
            try:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    for row in csv.DictReader(handle):
                        try:
                            season = int(row.get("season") or 0)
                            week = int(row.get("week") or 0)
                        except Exception:
                            continue
                        if not season or not week:
                            continue
                        parsed = _parse_date_token(row.get("start_date") or row.get("start_date_api"))
                        if parsed is not None:
                            grouped.setdefault((season, week), []).append(parsed)
            except Exception:
                continue
    return _windows_from_grouped_dates(grouped)


def week_windows_for_sport(sport_slug: str, *, source_root: Path) -> list[dict[str, Any]]:
    slug = str(sport_slug or "").strip().lower()
    if slug == "nfl":
        return _nfl_week_windows(source_root)
    if slug == "ncaaf":
        return _ncaaf_week_windows(source_root)
    return []


def week_for_date(sport_slug: str, target_date: date, *, source_root: Path) -> tuple[int, int] | None:
    windows = week_windows_for_sport(sport_slug, source_root=source_root)
    matches = [window for window in windows if window["start"] <= target_date <= window["end"]]
    if not matches:
        return None
    matches.sort(key=lambda item: (item["season"], item["week"]))
    best = matches[-1]
    return (int(best["season"]), int(best["week"]))


def shard_key_for_week(season: int, week: int) -> str:
    return f"{season}_wk{week}"
