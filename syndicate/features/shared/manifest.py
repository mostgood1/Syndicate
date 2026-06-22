"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Publishes per-sport artifact manifests and metadata.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_artifact_paths(artifact_paths: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for artifact_path in artifact_paths or []:
        path_text = str(artifact_path or "").strip()
        if not path_text:
            continue
        if path_text in seen:
            continue
        seen.add(path_text)
        normalized.append(path_text)
    return normalized


def publish_sport_manifest(sport: str, artifact_paths: list[str] | tuple[str, ...] | set[str] | None, metadata: dict[str, Any] | None) -> dict[str, Any]:
    sport_slug = str(sport or "").strip().lower()
    if not sport_slug:
        raise ValueError("sport is required")

    manifest_path = reports_root() / "manifests" / f"{sport_slug}.json"
    payload: dict[str, Any] = {
        "sport": sport_slug,
        "last_updated": _utc_now(),
        "artifact_paths": _normalize_artifact_paths(artifact_paths),
        "status": "complete",
    }
    if isinstance(metadata, dict) and metadata:
        payload["metadata"] = dict(metadata)

    write_json_file(manifest_path, payload)
    return {
        "path": str(manifest_path),
        "payload": payload,
    }