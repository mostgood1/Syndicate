from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from syndicate.features.shared.source_roots import preferred_artifact_roots


def _football_artifact_roots(*, sport: str) -> list[Path]:
    env_var = {
        "nfl": "SYNDICATE_NFL_SOURCE_ROOT",
        "ncaaf": "SYNDICATE_NCAAF_SOURCE_ROOT",
    }.get(str(sport or "").strip().lower(), "SYNDICATE_DATA_ROOT")
    local_dir_name = f"{str(sport or '').strip().lower()}_source"
    return preferred_artifact_roots(__file__, env_var=env_var, local_dir_name=local_dir_name)


def football_source_artifacts_root(*, sport: str) -> Path:
    roots = _football_artifact_roots(sport=sport)
    return roots[0]


def football_daily_artifacts_dir(*, sport: str, date: str) -> Path:
    return football_source_artifacts_root(sport=sport) / "data" / "daily" / str(date).replace("-", "_")


def football_artifact_path(*, sport: str, date: str, name: str) -> Path:
    filename = f"{str(name or '').strip()}.json"
    return football_daily_artifacts_dir(sport=sport, date=date) / filename


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def persist_football_artifacts(*, sport: str, date: str, artifacts: dict[str, Any]) -> dict[str, str]:
    persisted: dict[str, str] = {}
    for name in ("daily_summary", "profile_bundle", "locked_policy_card", "top_props", "ladders", "season_manifest"):
        payload = artifacts.get(name)
        if not isinstance(payload, dict):
            continue
        path = football_artifact_path(sport=sport, date=date, name=name)
        persisted[name] = str(_write_json(path, payload))
    return persisted