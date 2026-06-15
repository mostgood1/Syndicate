from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Iterable


SPORT_ROOT_PREFIXES = OrderedDict(
    (
        ("mlb", "data/mlb_source/"),
        ("nba", "data/nba_source/"),
        ("wnba", "data/wnba_source/"),
        ("nhl", "data/nhl_source/"),
        ("nfl", "data/nfl_source/"),
        ("ncaaf", "data/ncaaf_source/"),
        ("ncaab", "data/ncaab_source/"),
    )
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_paths(paths: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for path in paths or []:
        text = str(path or "").strip().replace("\\", "/")
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _count_prefixed_paths(paths: list[str], prefix: str) -> int:
    return sum(1 for path in paths if path.startswith(prefix))


def build_publish_parity_summary(
    *,
    date: str | None,
    forced_paths: Iterable[str] | None,
    intelligence_paths: Iterable[str] | None,
) -> dict[str, Any]:
    forced = _normalize_paths(forced_paths)
    intelligence = _normalize_paths(intelligence_paths)
    sports: list[dict[str, Any]] = []
    for sport, root_prefix in SPORT_ROOT_PREFIXES.items():
        sport_forced_count = _count_prefixed_paths(forced, root_prefix)
        sport_intelligence_count = _count_prefixed_paths(intelligence, root_prefix)
        sports.append(
            {
                "sport": sport,
                "rootPrefix": root_prefix,
                "forcedPublishPathCount": sport_forced_count,
                "intelligencePublishPathCount": sport_intelligence_count,
                "totalPublishPathCount": len(
                    {
                        path
                        for path in forced + intelligence
                        if path.startswith(root_prefix)
                    }
                ),
            }
        )

    return {
        "generatedAt": _utc_now(),
        "date": str(date or "").strip() or None,
        "totalForcedPublishPaths": len(forced),
        "totalIntelligencePublishPaths": len(intelligence),
        "totalPublishPaths": len(set(forced + intelligence)),
        "sports": sports,
    }


__all__ = ["SPORT_ROOT_PREFIXES", "build_publish_parity_summary"]