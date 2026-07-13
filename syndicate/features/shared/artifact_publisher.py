"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Pushes a small allowlist of frequently-refreshed ("hot") artifacts from a worker
  process to the web service's local disk, over HTTP, so the web dyno can serve
  current data without sharing a disk with the workers (Render disks are per-service).

Constraints:
- Must never raise: publish failures are logged and swallowed so a refresh loop
  never breaks because the web service is briefly unreachable.
- Only ever touches the fixed, explicit allowlist below. Bulk/historical/evaluation
  data is intentionally excluded and stays worker-local.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger("artifact_publisher")

HOT_ARTIFACT_PATTERNS: tuple[str, ...] = (
    "*_source/source_artifacts/data/live_lens/live_lens_report_*.json",
    "*_source/source_artifacts/data/live_lens/render_sync/*.json",
    "*_source/source_artifacts/data/processed/recommendations*.json",
    "*_source/source_artifacts/data/processed/recommendations*.csv",
    "*_source/source_artifacts/data/processed/props_recommendations*.json",
    "*_source/source_artifacts/data/processed/props_recommendations*.csv",
    "*_source/source_artifacts/data/processed/game_cards_*.csv",
    "*_source/source_artifacts/data/processed/cards_sim_detail_*.json",
    "*_source/source_artifacts/data/processed/cards_props_snapshot_*.json",
    "*_source/source_artifacts/data/market/*.json",
    "reports/intelligence/board_snapshot.json",
    "reports/intelligence/intelligence_state.json",
)


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root()


def relative_to_data_root(path: Path) -> str | None:
    try:
        relative = Path(path).expanduser().resolve().relative_to(_data_root())
    except Exception:
        return None
    return str(relative).replace("\\", "/")


def is_hot_artifact_relative_path(relative_path: str) -> bool:
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return False
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in HOT_ARTIFACT_PATTERNS)


def _publish_url() -> str:
    base = _env("SYNDICATE_WEB_PUBLISH_URL")
    if not base:
        return ""
    return base.rstrip("/") + "/api/ops/artifacts/publish"


def _admin_token() -> str:
    return _env("ADMIN_TOKEN") or _env("SYNDICATE_ADMIN_TOKEN")


def publish_hot_artifact(path: Path, *, timeout_seconds: int = 10) -> bool:
    """Best-effort push of a single allowlisted artifact to the web service.

    Returns False (and never raises) on any condition that prevents publishing:
    not configured, not an allowlisted path, file missing, or a network error.
    """
    url = _publish_url()
    token = _admin_token()
    if not url or not token:
        return False

    relative_path = relative_to_data_root(Path(path))
    if not relative_path or not is_hot_artifact_relative_path(relative_path):
        return False

    file_path = Path(path)
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.debug("artifact_publisher: could not read %s: %s", file_path, exc)
        return False

    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    body = json.dumps(
        {"relative_path": relative_path, "content": content, "checksum": checksum}
    ).encode("utf-8")

    request_obj = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
            response.read()
        return True
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        logger.warning("artifact_publisher: publish failed for %s: %s", relative_path, exc)
        return False
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        logger.warning("artifact_publisher: unexpected publish error for %s: %s", relative_path, exc)
        return False


def publish_hot_artifacts(paths: Any) -> int:
    """Publish an iterable of paths, returning the count that succeeded."""
    published = 0
    for path in paths or ():
        if publish_hot_artifact(path):
            published += 1
    return published


def publish_changed_hot_artifacts(since_epoch_seconds: float) -> int:
    """Sweep the allowlisted hot-artifact locations under the data root and publish
    any file modified at or after ``since_epoch_seconds``.

    Used after a refresh tick that runs per-sport work in a detached subprocess,
    where we can't easily hook every downstream write site directly.
    """
    if not _publish_url() or not _admin_token():
        return 0
    root = _data_root()
    published = 0
    for pattern in HOT_ARTIFACT_PATTERNS:
        for candidate in root.glob(pattern):
            try:
                if not candidate.is_file() or candidate.stat().st_mtime < since_epoch_seconds:
                    continue
            except OSError:
                continue
            if publish_hot_artifact(candidate):
                published += 1
    return published
