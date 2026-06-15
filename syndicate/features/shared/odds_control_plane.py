from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import repo_root_from


REPO_ROOT = repo_root_from(__file__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def odds_control_plane_root() -> Path:
    return reports_root() / "odds_control_plane"


def odds_control_plane_snapshot_path() -> Path:
    return odds_control_plane_root() / "latest.json"


def odds_history_roots_for_sport(sport_slug: str) -> list[Path]:
    slug = str(sport_slug or "").strip().lower()
    roots: list[Path] = []
    for base in (
        REPO_ROOT / "data" / f"{slug}_source",
        REPO_ROOT / f"{slug}_source",
    ):
        if base.exists() and base not in roots:
            roots.append(base)
    return roots


def odds_history_paths_for_sport(sport_slug: str) -> list[Path]:
    paths: list[Path] = []
    for root in odds_history_roots_for_sport(sport_slug):
        for candidate in (root / "artifacts" / str(sport_slug).strip().lower() / "odds_history.json", root / "tracking" / "odds_history.json"):
            if candidate not in paths:
                paths.append(candidate)
    return paths


def load_odds_history_payload_for_sport(sport_slug: str) -> dict[str, Any] | None:
    for path in odds_history_paths_for_sport(sport_slug):
        if not path.exists():
            continue
        payload = read_json_file(path)
        if isinstance(payload, dict):
            return payload
    return None


def odds_history_path_status_for_sport(sport_slug: str) -> dict[str, Any]:
    candidate_paths = odds_history_paths_for_sport(sport_slug)
    active_path = None
    active_payload: dict[str, Any] | None = None
    for candidate_path in candidate_paths:
        payload = read_json_file(candidate_path)
        if isinstance(payload, dict):
            active_path = candidate_path
            active_payload = payload
            break

    return {
        "sport": str(sport_slug or "").strip().lower(),
        "candidate_paths": [str(path) for path in candidate_paths],
        "active_path": str(active_path) if active_path is not None else None,
        "has_payload": bool(active_payload),
        "source_precedence": ["artifact_history", "tracking_history"],
    }


def build_odds_control_plane_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    results = summary.get("results") if isinstance(summary, dict) else []
    sport_snapshots: list[dict[str, Any]] = []
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        sport = str(result.get("sport") or "").strip().lower()
        odds_history_status = odds_history_path_status_for_sport(sport)
        sport_snapshots.append(
            {
                "sport": sport,
                "ok": bool(result.get("ok")),
                "generation_mode": result.get("generation_mode"),
                "ingestion_mode": result.get("ingestion_mode"),
                "source_repo": result.get("source_repo"),
                "source_root_env_var": result.get("source_root_env_var"),
                "artifact_paths": list(result.get("artifact_paths") or []),
                "post_refresh_ok": (result.get("sport_manifest") or {}).get("payload", {}).get("metadata", {}).get("post_refresh_ok") if isinstance(result.get("sport_manifest"), dict) else None,
                "mirror_ok": (result.get("sport_manifest") or {}).get("payload", {}).get("metadata", {}).get("mirror_ok") if isinstance(result.get("sport_manifest"), dict) else None,
                "odds_history": odds_history_status,
            }
        )

    return {
        "generated_at": _utc_now(),
        "date": summary.get("date") if isinstance(summary, dict) else None,
        "phase": summary.get("phase") if isinstance(summary, dict) else None,
        "execution_mode": summary.get("execution_mode") if isinstance(summary, dict) else None,
        "dry_run": bool(summary.get("dry_run")) if isinstance(summary, dict) else False,
        "publish_parity": summary.get("publish_parity") if isinstance(summary, dict) else None,
        "sports": sport_snapshots,
        "source_precedence": ["artifact_history", "tracking_history"],
        "summary_ok": bool(summary.get("ok")) if isinstance(summary, dict) else False,
    }


def write_odds_control_plane_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    snapshot = build_odds_control_plane_snapshot(summary)
    snapshot_path = odds_control_plane_snapshot_path()
    write_json_file(snapshot_path, snapshot)
    return {
        "path": str(snapshot_path),
        "payload": snapshot,
    }


def load_odds_control_plane_snapshot() -> dict[str, Any] | None:
    payload = read_json_file(odds_control_plane_snapshot_path())
    return payload if isinstance(payload, dict) else None