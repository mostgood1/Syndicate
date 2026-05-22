from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from syndicate.features.shared.source_roots import repo_root_from


REPO_ROOT = repo_root_from(__file__)
REPORTS_ROOT = REPO_ROOT / "reports"


def reports_root() -> Path:
    override = str(os.environ.get("SYNDICATE_REPORTS_ROOT") or os.environ.get("SYNDICATE_STATE_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return REPORTS_ROOT


def data_root() -> Path:
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return REPO_ROOT / "data"


def read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def latest_refresh_manifest_context() -> dict[str, Any]:
    refresh_manifest_path = reports_root() / "refresh_status" / "latest" / "refresh_status_latest.json"
    manifest = read_json_file(refresh_manifest_path) or {}
    artifacts_dir_raw = str(manifest.get("artifactsDir") or "").strip()
    artifacts_dir = Path(artifacts_dir_raw) if artifacts_dir_raw else None
    run_summary_path = Path(str(manifest.get("runSummaryPath") or "").strip()) if str(manifest.get("runSummaryPath") or "").strip() else None
    if run_summary_path is None and artifacts_dir is not None:
        candidate = artifacts_dir / "refresh_and_gate_run.json"
        run_summary_path = candidate
    return {
        "manifest_path": refresh_manifest_path,
        "manifest": manifest,
        "artifacts_dir": artifacts_dir,
        "run_summary_path": run_summary_path,
    }


def load_mirror_manifest_summaries() -> list[dict[str, Any]]:
    root = data_root()
    if not root.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for source_dir in sorted((path for path in root.iterdir() if path.is_dir() and path.name.endswith("_source")), key=lambda item: item.name):
        manifest_path = source_dir / "manifests" / "mirror_refresh_latest.json"
        manifest = read_json_file(manifest_path)
        slug = source_dir.name[: -len("_source")]
        artifact_groups = manifest.get("artifactGroups") if isinstance(manifest, dict) else None
        summaries.append(
            {
                "sport": slug,
                "path": str(manifest_path),
                "exists": manifest_path.exists(),
                "manifest": manifest,
                "date": (manifest or {}).get("date"),
                "copied_artifact_count": (manifest or {}).get("copiedArtifactCount"),
                "artifact_groups": artifact_groups if isinstance(artifact_groups, dict) else {},
            }
        )
    return summaries