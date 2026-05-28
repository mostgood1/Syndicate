from __future__ import annotations

import csv
import json
from pathlib import Path
import re
from typing import Any

from syndicate.features.shared.formatters import format_pct
from syndicate.features.shared.formatters import format_signed_price
from syndicate.features.shared.source_roots import repo_root_from


_SNAPSHOT_RE = re.compile(r"^upcoming_recs_(?P<season>\d{4})_wk(?P<week>\d+)(?P<publish>_publish)?\.csv$")


def _source_roots() -> list[Path]:
    env_value = str(__import__('os').environ.get("SYNDICATE_NFL_SOURCE_ROOT") or "").strip()
    if env_value:
        return [Path(env_value).resolve()]

    repo_root = repo_root_from(__file__)
    data_root = str(__import__('os').environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    roots: list[Path] = []
    if data_root:
        roots.append((Path(data_root).resolve() / "nfl_source").resolve())
    roots.append((repo_root / "data" / "nfl_source").resolve())

    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        deduped.append(root)
    return deduped


def default_nfl_source_root() -> Path:
    for root in _source_roots():
        if root.exists():
            return root
    return _source_roots()[0]


def data_path(*parts: str) -> Path:
    return default_nfl_source_root().joinpath(*parts)


def _count_csv_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except Exception:
        return 0


def tracked_week() -> dict[str, int] | None:
    path = data_path("current_week.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        season = int(payload.get("season"))
        week = int(payload.get("week"))
    except Exception:
        return None
    return {"season": season, "week": week}


def week_summaries() -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    for path in sorted(default_nfl_source_root().glob("upcoming_recs_*.csv")):
        match = _SNAPSHOT_RE.match(path.name)
        if not match:
            continue
        season = int(match.group("season"))
        week = int(match.group("week"))
        is_publish = bool(match.group("publish"))
        key = (season, week)
        summary = grouped.setdefault(
            key,
            {
                "season": season,
                "week": week,
                "count": 0,
                "path": str(path),
                "has_publish": False,
                "has_full": False,
            },
        )
        row_count = _count_csv_rows(path)
        if not is_publish:
            summary["path"] = str(path)
            summary["count"] = row_count
            summary["has_full"] = True
        else:
            summary["has_publish"] = True
            summary["publish_path"] = str(path)
            summary["publish_count"] = row_count
            if not summary["has_full"]:
                summary["path"] = str(path)
                summary["count"] = row_count
    return sorted(grouped.values(), key=lambda item: (item["season"], item["week"]))


def latest_season() -> int:
    weeks = week_summaries()
    return weeks[-1]["season"] if weeks else 2025


def available_weeks(season: int | None = None) -> list[int]:
    resolved_season = int(season or latest_season())
    return [item["week"] for item in week_summaries() if item["season"] == resolved_season]


def default_week(season: int | None = None) -> int:
    weeks = available_weeks(season)
    return weeks[-1] if weeks else 1


def recommendation_path(week: int, season: int | None = None) -> Path:
    resolved_season = int(season or latest_season())
    full = data_path(f"upcoming_recs_{resolved_season}_wk{week}.csv")
    if full.exists():
        return full
    publish = data_path(f"upcoming_recs_{resolved_season}_wk{week}_publish.csv")
    return publish


def build_module_links(selected_week: int, active_label: str, *, season: int | None = None) -> list[dict[str, Any]]:
    resolved_season = int(season or latest_season())
    links = [
        ("Cards", f"/nfl/cards?season={resolved_season}&week={selected_week}"),
        ("Betting Card", f"/nfl/season/{resolved_season}/betting-card?week={selected_week}"),
        ("Picks", f"/nfl/picks?season={resolved_season}&week={selected_week}"),
        ("Live Lens", f"/nfl/live-lens?season={resolved_season}&week={selected_week}"),
        ("Daily Archive", f"/nfl/archive?season={resolved_season}&week={selected_week}"),
        ("Hub", "/nfl/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]


def format_odds(value: Any) -> str:
    return format_signed_price(value)
