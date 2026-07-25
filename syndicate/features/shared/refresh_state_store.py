"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Reads and writes refresh state, manifests, and latest reports across filesystem or key-value storage.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from syndicate.features.shared.timezone import normalize_timestamped_payload
from syndicate.features.shared.source_roots import repo_root_from


REPO_ROOT = repo_root_from(__file__)
REPORTS_ROOT = REPO_ROOT / "reports"
REFRESH_STATE_PATH = REPORTS_ROOT / "refresh_state.json"


def _refresh_state_backend_name() -> str:
    value = str(os.environ.get("SYNDICATE_REFRESH_STATE_BACKEND") or "").strip().lower()
    if value:
        return value
    hosted = _strict_hosted_storage_enabled() or bool(str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"})
    if hosted and str(os.environ.get("SYNDICATE_REFRESH_STATE_URL") or os.environ.get("REDIS_URL") or "").strip():
        return "keyvalue"
    return "filesystem"

def _strict_hosted_storage_enabled() -> bool:
    raw_value = str(os.environ.get("SYNDICATE_REQUIRE_HOSTED_STORAGE") or "").strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    return str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}


def _state_backend_kind() -> str:
    value = _refresh_state_backend_name()
    if value in {"filesystem", "local_file"}:
        return "filesystem"
    if value in {"redis", "keyvalue", "valkey"}:
        return "keyvalue"
    return "filesystem"


def _state_namespace() -> str:
    value = str(os.environ.get("SYNDICATE_REFRESH_STATE_NAMESPACE") or "syndicate").strip()
    return value or "syndicate"


# Root-caused 2026-07-25: redis.Redis.from_url with no socket_timeout/
# socket_connect_timeout blocks indefinitely (Python's default "no timeout"
# socket behavior) on a stalled or half-open connection -- confirmed live as
# the source of multi-minute silent stalls appearing at different, seemingly
# random points in the board-publication cycle, since this one shared client
# (lru_cache(maxsize=1)) backs every read_json_file/write_json_file call in
# the keyvalue-backed pipeline. read_json_file_result already wraps its
# _execute_keyvalue_operation call in a broad except Exception, so a fast
# TimeoutError here is already handled gracefully by every caller -- the fix
# is bounding how long a single stuck operation can block before that
# exception handling ever gets a chance to run.
_KEYVALUE_SOCKET_TIMEOUT_SECONDS = 5.0
_KEYVALUE_SOCKET_CONNECT_TIMEOUT_SECONDS = 5.0


@lru_cache(maxsize=1)
def _get_keyvalue_client() -> Any:
    url = str(os.environ.get("SYNDICATE_REFRESH_STATE_URL") or os.environ.get("REDIS_URL") or "").strip()
    if not url:
        raise RuntimeError("SYNDICATE_REFRESH_STATE_URL or REDIS_URL must be set when SYNDICATE_REFRESH_STATE_BACKEND uses keyvalue.")
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError("redis package is required when SYNDICATE_REFRESH_STATE_BACKEND uses keyvalue.") from exc
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=_KEYVALUE_SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=_KEYVALUE_SOCKET_CONNECT_TIMEOUT_SECONDS,
    )


def _execute_keyvalue_operation(operation):
    try:
        import redis
    except ImportError:
        redis = None

    last_error: Exception | None = None
    for attempt in range(2):
        client = _get_keyvalue_client()
        try:
            return operation(client)
        except Exception as exc:
            last_error = exc
            # TimeoutError is a RedisError subclass, not a ConnectionError
            # subclass -- a stalled socket that now fails fast via the
            # timeout above needs its own retry branch, or the one retry
            # this function already had for genuine connection drops would
            # never apply to it.
            is_retryable = redis is not None and isinstance(exc, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError))
            if is_retryable:
                _get_keyvalue_client.cache_clear()
                continue
            break
    if last_error is not None:
        raise last_error
    raise RuntimeError("keyvalue operation failed")


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


def _known_refresh_lanes_key() -> str:
    return f"{_state_namespace()}:refresh-state-known-lanes"


def record_known_refresh_lane(lane_key: str) -> None:
    # With the keyvalue backend, "latest" manifest files aren't necessarily
    # materialized on any single service's local disk -- a raw filesystem
    # glob over refresh_status/latest/ (as list_latest_refresh_manifests_by_lane
    # used to do) finds nothing there. Mirrors _record_refresh_status_history's
    # existing index-key pattern so per-lane discovery works the same way.
    lane_key = str(lane_key or "").strip()
    if not lane_key or _state_backend_kind() != "keyvalue":
        return

    def _write_lanes(client):
        raw_lanes = client.get(_known_refresh_lanes_key())
        try:
            existing_lanes = json.loads(raw_lanes) if raw_lanes else []
        except Exception:
            existing_lanes = []
        if not isinstance(existing_lanes, list):
            existing_lanes = []
        if lane_key in existing_lanes:
            return
        client.set(_known_refresh_lanes_key(), json.dumps([*existing_lanes, lane_key]))

    _execute_keyvalue_operation(_write_lanes)


def known_refresh_lanes() -> list[str]:
    if _state_backend_kind() != "keyvalue":
        return []

    def _read_lanes(client):
        raw_lanes = client.get(_known_refresh_lanes_key())
        try:
            lanes = json.loads(raw_lanes) if raw_lanes else []
        except Exception:
            return []
        return lanes if isinstance(lanes, list) else []

    try:
        return _execute_keyvalue_operation(_read_lanes)
    except Exception:
        return []


def assert_refresh_state_backend_ready(*, process_name: str | None = None) -> str:
    backend_name = _refresh_state_backend_name()
    print(f"REFRESH_STATE_BACKEND = {backend_name}")
    hosted = _strict_hosted_storage_enabled() or bool(str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"})
    if hosted and backend_name not in {"redis", "keyvalue", "valkey"}:
        owner = f" for {process_name}" if process_name else ""
        raise RuntimeError(f"Local state backend not allowed in multi-service deployment{owner}: {backend_name}")
    return backend_name


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
    def _write_history(client):
        raw_paths = client.get(_history_index_key())
        try:
            existing_paths = json.loads(raw_paths) if raw_paths else []
        except Exception:
            existing_paths = []
        if not isinstance(existing_paths, list):
            existing_paths = []
        updated_paths = [relative_path, *[item for item in existing_paths if item != relative_path]]
        client.set(_history_index_key(), json.dumps(updated_paths[:50]))

    _execute_keyvalue_operation(_write_history)


def _atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        temp_path.write_text(str(payload or ""), encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass


def reports_root() -> Path:
    override = str(os.environ.get("SYNDICATE_REPORTS_ROOT") or os.environ.get("SYNDICATE_STATE_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if _strict_hosted_storage_enabled():
        if str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}:
            return REPORTS_ROOT
        raise RuntimeError("SYNDICATE_REPORTS_ROOT or SYNDICATE_STATE_ROOT must be set when hosted storage is required.")
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
    if _strict_hosted_storage_enabled():
        raise RuntimeError("SYNDICATE_DATA_ROOT must be set when hosted storage is required.")
    return REPO_ROOT / "data"


def read_json_file(path: Path) -> dict[str, Any] | None:
    return read_json_file_result(path)[0]


def read_json_file_result(path: Path) -> tuple[dict[str, Any] | None, bool]:
    # Same data as read_json_file, but also reports whether the read itself
    # succeeded. read_json_file collapses "key/file genuinely doesn't exist"
    # and "the read failed" into the same None -- callers that use "no
    # manifest recorded" as a safety-relevant signal (e.g. the refresh-run
    # concurrency guard) need to tell those apart: a transient keyvalue-store
    # hiccup must not be treated the same as "nothing is running." The second
    # element is False only when the read could not be completed/trusted
    # (backend error, malformed JSON) -- never for a confirmed-absent key.
    if _state_backend_kind() == "keyvalue":
        try:
            payload_text = _execute_keyvalue_operation(lambda client: client.get(_state_key_for_path(path)))
        except Exception:
            return None, False
        if not payload_text:
            return None, True
        try:
            payload = json.loads(str(payload_text))
        except Exception:
            return None, False
        return (payload if isinstance(payload, dict) else None), True
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, True
    except Exception:
        return None, False
    return (payload if isinstance(payload, dict) else None), True


def read_text_file(path: Path) -> str | None:
    if _state_backend_kind() == "keyvalue":
        try:
            payload_text = _execute_keyvalue_operation(lambda client: client.get(_state_key_for_path(path)))
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
    normalized_payload = normalize_timestamped_payload(payload)
    if _state_backend_kind() == "keyvalue":
        def _write_json(client):
            client.set(_state_key_for_path(path), json.dumps(normalized_payload, indent=2))
            _record_refresh_status_history(path)

        _execute_keyvalue_operation(_write_json)
        return
    _atomic_write_text(path, json.dumps(normalized_payload, indent=2))


def write_text_file(path: Path, payload: str) -> None:
    if _state_backend_kind() == "keyvalue":
        _execute_keyvalue_operation(lambda client: client.set(_state_key_for_path(path), str(payload or "")))
        return
    _atomic_write_text(path, payload)


def delete_text_file(path: Path) -> None:
    # write_text_file has no counterpart on the keyvalue backend -- every
    # caller that writes a stale-content-must-not-persist artifact (e.g.
    # WNBA's game_cards_{date}.csv, deleted on a genuinely empty slate) only
    # ever unlinked the filesystem copy, leaving the keyvalue-stored copy
    # (written by the same call site) stale forever on any deployment using
    # the keyvalue backend. Confirmed live 2026-07-23: game_cards's
    # filesystem file was correctly cleared, but the served board kept
    # showing the same stale slate because the read path resolves through
    # the keyvalue store first.
    if _state_backend_kind() == "keyvalue":
        try:
            _execute_keyvalue_operation(lambda client: client.delete(_state_key_for_path(path)))
        except Exception:
            pass
        return
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def path_exists(path: Path) -> bool:
    if _state_backend_kind() == "keyvalue":
        try:
            return bool(_execute_keyvalue_operation(lambda client: client.exists(_state_key_for_path(path))))
        except Exception:
            return False
    return path.exists()


def path_size(path: Path) -> int:
    if _state_backend_kind() == "keyvalue":
        try:
            payload_text = _execute_keyvalue_operation(lambda client: client.get(_state_key_for_path(path)))
        except Exception:
            return 0
        if payload_text is None:
            return 0
        return len(str(payload_text).encode("utf-8"))
    return path.stat().st_size if path.exists() else 0


def list_refresh_status_manifest_paths(*, limit: int = 6) -> list[Path]:
    if _state_backend_kind() == "keyvalue":
        try:
            raw_paths = _execute_keyvalue_operation(lambda client: client.get(_history_index_key()))
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