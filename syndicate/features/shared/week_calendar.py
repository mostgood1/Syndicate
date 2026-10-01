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


_SOURCE_GLOBS: dict[str, tuple[tuple[str, ...], str]] = {
    # slug -> (sub-roots searched, glob); same roots and globs the readers use.
    "nfl": (("", "source_artifacts"), "upcoming_recs_*.csv"),
    "ncaaf": (("source_artifacts", ""), "college_football_schedule_*_predicted_totals_enhanced*.csv"),
}
_WINDOW_CACHE_MAX_ROOTS = 32
_window_cache: dict[tuple[str, str], tuple[tuple[tuple[str, int, int], ...], list[dict[str, Any]]]] = {}


def _source_signature(slug: str, source_root: Path) -> tuple[tuple[str, int, int], ...]:
    subdirs, pattern = _SOURCE_GLOBS[slug]
    signature: list[tuple[str, int, int]] = []
    for sub in subdirs:
        root = source_root / sub if sub else source_root
        if not root.exists():
            continue
        for path in root.glob(pattern):
            try:
                stat = path.stat()
            except OSError:
                continue
            signature.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(signature))


def week_windows_for_sport(sport_slug: str, *, source_root: Path) -> list[dict[str, Any]]:
    # Cached on the source files' (path, mtime, size). Measured 2026-10-01 on
    # the local production fleet: _ncaaf_week_windows re-parsed ~300k schedule
    # CSV rows on EVERY call, and score_candidate reaches it once per candidate
    # (build_market_history_view -> resolve_current_shard_key -> week_for_date),
    # so it was ~100% of NCAAF scoring: 11-15s per candidate, 632s for 273, and
    # 440-590s of every refresh-worker board build. A changed, added or removed
    # file changes the signature, so a stale window is never served; the cost
    # left per call is one glob + stat over the schedule files.
    slug = str(sport_slug or "").strip().lower()
    if slug not in _SOURCE_GLOBS:
        return []
    key = (slug, str(source_root))
    signature = _source_signature(slug, source_root)
    cached = _window_cache.get(key)
    if cached is None or cached[0] != signature:
        windows = _nfl_week_windows(source_root) if slug == "nfl" else _ncaaf_week_windows(source_root)
        if key not in _window_cache and len(_window_cache) >= _WINDOW_CACHE_MAX_ROOTS:
            _window_cache.clear()
        _window_cache[key] = cached = (signature, windows)
    # Copies, so a caller mutating a window cannot corrupt the cache.
    return [dict(window) for window in cached[1]]


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
