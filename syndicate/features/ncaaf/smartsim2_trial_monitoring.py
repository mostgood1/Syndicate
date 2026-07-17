"""Operational monitoring for the SmartSim 2.0 public blend trial.

Captures one JSON-lines record per page view: which route, how many games
were shown, what fraction had a real SmartSim 2.0 projection available
(projection_availability_rate), what fraction actually rendered the
three-way comparison for this specific request (smartsim2_visibility_rate /
blend_visibility_rate -- these are 0 for any non-trial request, which is
itself a meaningful signal about real trial-vs-baseline traffic mix once
deployed), and the fallback rate (SmartSim 2.0 in scope for a game but
unavailable for this specific request/game).

This module does not touch projection generation, blend math, or the
visibility gate itself -- it only observes the scoreboard dicts those
already-built systems produce. Logging failures are swallowed (monitoring
must never be able to break a page render).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from typing import Sequence

from syndicate.features.ncaaf.sources import default_ncaaf_source_root

MONITORING_LOG_PATH = default_ncaaf_source_root() / "data" / "smartsim2_trial_monitoring.jsonl"


def record_trial_page_view(
    *,
    route: str,
    season: int,
    week: int,
    scoreboards: Sequence[dict[str, Any]],
    log_path: Path = MONITORING_LOG_PATH,
) -> dict[str, Any] | None:
    total = len(scoreboards)
    if total == 0:
        return None

    available_count = sum(1 for sb in scoreboards if sb.get("smartsim2_available"))
    visible_count = sum(1 for sb in scoreboards if sb.get("projection_sources_mode"))
    fallback_count = sum(
        1 for sb in scoreboards if sb.get("projection_sources_mode") and not sb.get("smartsim2_available")
    )
    modes = {sb.get("projection_sources_mode") for sb in scoreboards if sb.get("projection_sources_mode")}
    visibility_mode = sorted(modes)[0] if modes else None

    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "route": route,
        "season": season,
        "week": week,
        "total_games": total,
        "projection_availability_rate": round(available_count / total, 4),
        "smartsim2_visibility_rate": round(visible_count / total, 4),
        "blend_visibility_rate": round(visible_count / total, 4),
        "fallback_rate": round(fallback_count / total, 4),
        "visibility_mode": visibility_mode,
    }
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001 - monitoring must never break a page render
        pass
    return record


def read_monitoring_log(*, log_path: Path = MONITORING_LOG_PATH) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    records = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


__all__ = ["MONITORING_LOG_PATH", "read_monitoring_log", "record_trial_page_view"]
