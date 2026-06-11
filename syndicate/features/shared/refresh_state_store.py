from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from syndicate.features.shared.source_roots import repo_root_from


REPO_ROOT = repo_root_from(__file__)
REPORTS_ROOT = REPO_ROOT / "reports"
REFRESH_STATE_PATH = REPORTS_ROOT / "refresh_state.json"


def _state_backend_kind() -> str:
    value = str(os.environ.get("SYNDICATE_REFRESH_STATE_BACKEND") or "filesystem").strip().lower()
    if value in {"redis", "keyvalue", "valkey"}:
        return "keyvalue"
    return "filesystem"


def _state_namespace() -> str:
    value = str(os.environ.get("SYNDICATE_REFRESH_STATE_NAMESPACE") or "syndicate").strip()
    return value or "syndicate"


@lru_cache(maxsize=1)
def _get_keyvalue_client() -> Any:
    url = str(os.environ.get("SYNDICATE_REFRESH_STATE_URL") or os.environ.get("REDIS_URL") or "").strip()
    if not url:
        raise RuntimeError("SYNDICATE_REFRESH_STATE_URL or REDIS_URL must be set when SYNDICATE_REFRESH_STATE_BACKEND uses keyvalue.")
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError("redis package is required when SYNDICATE_REFRESH_STATE_BACKEND uses keyvalue.") from exc
    return redis.Redis.from_url(url, decode_responses=True)


def _normalize_state_path(path: Path) -> str:
    try:
        normalized = path.expanduser().resolve()
    except Exception:
        normalized = path.expanduser()
    return str(normalized).replace("\\", "/")


def _state_key_for_path(path: Path) -> str:
    return f"{_state_namespace()}:refresh-state:{_normalize_state_path(path)}"


def _history_index_key() -> str:
    return f"{_state_namespace()}:refresh-state-history"


def _refresh_status_history_relative_path(path: Path) -> str | None:
    try:
        relative = path.expanduser().resolve().relative_to(reports_root())
    except Exception:
        return None
    parts = relative.parts
    if len(parts) != 4:
        return None
    if parts[0] != "refresh_status" or parts[1] == "latest" or parts[3] != "refresh_status_manifest.json":
        return None
    return "/".join(parts)


def _record_refresh_status_history(path: Path) -> None:
    if _state_backend_kind() != "keyvalue":
        return
    relative_path = _refresh_status_history_relative_path(path)
    if not relative_path:
        return
    client = _get_keyvalue_client()
    raw_paths = client.get(_history_index_key())
    try:
        existing_paths = json.loads(raw_paths) if raw_paths else []
    except Exception:
        existing_paths = []
    if not isinstance(existing_paths, list):
        existing_paths = []
    updated_paths = [relative_path, *[item for item in existing_paths if item != relative_path]]
    client.set(_history_index_key(), json.dumps(updated_paths[:50]))


def reports_root() -> Path:
    override = str(os.environ.get("SYNDICATE_REPORTS_ROOT") or os.environ.get("SYNDICATE_STATE_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return REPORTS_ROOT


def refresh_state_path() -> Path:
    return reports_root() / "refresh_state.json"


def _load_refresh_state() -> dict[str, Any]:
    state = read_json_file(refresh_state_path())
    if isinstance(state, dict):
        return state
    return {"steps": {}}


def _write_refresh_state(state: dict[str, Any]) -> None:
    write_json_file(refresh_state_path(), state)


def build_input_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def path_fingerprint(path: Path) -> dict[str, Any]:
    candidate = Path(path)
    try:
        stat_result = candidate.stat()
    except Exception:
        return {"path": _normalize_state_path(candidate), "missing": True}
    return {
        "path": _normalize_state_path(candidate),
        "mtime_ns": int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
        "size": int(stat_result.st_size),
    }


def should_recompute(step_name: str, input_hash: str) -> bool:
    step_key = str(step_name or "").strip()
    if not step_key:
        return True
    current_hash = str(input_hash or "").strip()
    if not current_hash:
        return True
    state = _load_refresh_state()
    steps = state.get("steps") if isinstance(state.get("steps"), dict) else {}
    entry = steps.get(step_key) if isinstance(steps, dict) else None
    if not isinstance(entry, dict):
        return True
    return str(entry.get("inputHash") or "").strip() != current_hash


def record_refresh_state(step_name: str, input_hash: str, *, outputs: list[str] | None = None, metadata: dict[str, Any] | None = None) -> None:
    step_key = str(step_name or "").strip()
    current_hash = str(input_hash or "").strip()
    if not step_key or not current_hash:
        return
    state = _load_refresh_state()
    steps = state.get("steps") if isinstance(state.get("steps"), dict) else {}
    if not isinstance(steps, dict):
        steps = {}
    steps[step_key] = {
        "inputHash": current_hash,
        "updatedAt": __import__("datetime").datetime.utcnow().isoformat(),
        "outputs": [str(item) for item in outputs or [] if str(item or "").strip()],
        "metadata": metadata or {},
    }
    state["steps"] = steps
    _write_refresh_state(state)


def data_root() -> Path:
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return REPO_ROOT / "data"


def read_json_file(path: Path) -> dict[str, Any] | None:
    if _state_backend_kind() == "keyvalue":
        try:
            payload_text = _get_keyvalue_client().get(_state_key_for_path(path))
        except Exception:
            return None
        if not payload_text:
            return None
        try:
            payload = json.loads(str(payload_text))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def read_text_file(path: Path) -> str | None:
    if _state_backend_kind() == "keyvalue":
        try:
            payload_text = _get_keyvalue_client().get(_state_key_for_path(path))
        except Exception:
            return None
        if payload_text is None:
            return None
        return str(payload_text).strip()
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    if _state_backend_kind() == "keyvalue":
        _get_keyvalue_client().set(_state_key_for_path(path), json.dumps(payload, indent=2))
        _record_refresh_status_history(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_text_file(path: Path, payload: str) -> None:
    if _state_backend_kind() == "keyvalue":
        _get_keyvalue_client().set(_state_key_for_path(path), str(payload or ""))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(payload or ""), encoding="utf-8")


def path_exists(path: Path) -> bool:
    if _state_backend_kind() == "keyvalue":
        try:
            return bool(_get_keyvalue_client().exists(_state_key_for_path(path)))
        except Exception:
            return False
    return path.exists()


def path_size(path: Path) -> int:
    if _state_backend_kind() == "keyvalue":
        try:
            payload_text = _get_keyvalue_client().get(_state_key_for_path(path))
        except Exception:
            return 0
        if payload_text is None:
            return 0
        return len(str(payload_text).encode("utf-8"))
    return path.stat().st_size if path.exists() else 0


def list_refresh_status_manifest_paths(*, limit: int = 6) -> list[Path]:
    if _state_backend_kind() == "keyvalue":
        try:
            raw_paths = _get_keyvalue_client().get(_history_index_key())
        except Exception:
            raw_paths = None
        try:
            relative_paths = json.loads(raw_paths) if raw_paths else []
        except Exception:
            relative_paths = []
        if not isinstance(relative_paths, list):
            return []
        output: list[Path] = []
        for item in relative_paths:
            if not isinstance(item, str) or not item.strip():
                continue
            output.append(reports_root() / Path(item))
            if len(output) >= limit:
                break
        return output

    refresh_root = reports_root() / "refresh_status"
    if not refresh_root.exists():
        return []
    manifest_paths: list[Path] = []
    for date_dir in sorted((path for path in refresh_root.iterdir() if path.is_dir() and path.name != "latest"), reverse=True):
        for run_dir in sorted((path for path in date_dir.iterdir() if path.is_dir()), reverse=True):
            manifest_path = run_dir / "refresh_status_manifest.json"
            if manifest_path.exists():
                manifest_paths.append(manifest_path)
                if len(manifest_paths) >= limit:
                    return manifest_paths
    return manifest_paths


def reset_state_store_caches() -> None:
    _get_keyvalue_client.cache_clear()


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