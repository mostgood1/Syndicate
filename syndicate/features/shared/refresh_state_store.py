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

from datetime import date
from datetime import datetime
from datetime import timezone
from functools import lru_cache
import hashlib
import json
import os
import re
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


# Board audit follow-up, 2026-07-31: root-caused live -- the shared keyvalue
# backend (one Redis instance, 256MB "starter" plan, shared across web +
# refresh-worker + live-odds-worker) was at 96% memory usage with 34,529
# LRU-evicted keys and a 44% keyspace miss rate, and (the key finding)
# `expired_keys: 0` -- literally nothing written here has ever carried a
# TTL. Most keyvalue-backed artifacts are scoped to one calendar date
# embedded in their own filename (game_cards_<date>.csv,
# recommendations_slate_<date>.json, live_state_<date>.jsonl, sim/props
# snapshots, refresh_status manifests, ...) and have no ongoing value once
# that date is genuinely old, but with no TTL they sat in memory forever,
# competing with today's actively-needed keys for the same fixed 256MB
# until LRU eventually evicted SOMETHING -- not necessarily the stale
# entry, since LRU evicts whichever key hasn't been touched most recently,
# not whichever is oldest by date. A plan upgrade isn't available, so this
# gives any recognizably date-scoped key a TTL, generous enough to cover
# every legitimate prev/next-day lookback and same-week ops/debugging use
# this codebase does, so Redis reclaims genuinely dead data on its own
# instead of relying entirely on LRU to eventually get to it.
_KEYVALUE_DATE_TOKEN_RE = re.compile(r"(?P<y>20\d{2})[-_]?(?P<m>\d{2})[-_]?(?P<d>\d{2})")
_KEYVALUE_DATE_SCOPED_TTL_SECONDS = 10 * 24 * 60 * 60  # 10 days

# The first real-production sweep (2026-07-31) found the actual bloat
# wasn't ONE-key-per-date artifacts (game_cards.csv and friends -- those
# are safe with the longer default above, since there's at most one active
# key per date) -- it was these ONE-key-per-RUN paths, where every single
# refresh/odds-refresh/sim tick writes a brand-new, never-reused key
# (e.g. reports/refresh_status/<date>/<run_id>/refresh_status_manifest.json,
# reports/migration_runs/<date>/odds_refresh_<timestamp>/...). Confirmed
# live: a 10-day TTL on this category alone would let it re-accumulate to
# roughly the same ~56MB/1,337-key backlog the first sweep just reclaimed
# within a day or two, given how often these run -- these need a much
# shorter TTL specifically because they're write-once, never-reused keys,
# not because the DATA is less important.
_KEYVALUE_RUN_SCOPED_PATH_MARKERS = ("refresh_status/", "migration_runs/", "live_refresh_loop/")
_KEYVALUE_RUN_SCOPED_TTL_SECONDS = 2 * 24 * 60 * 60  # 2 days


def _default_keyvalue_ttl_seconds(path: Path) -> int | None:
    normalized = _normalize_state_path(path)
    match = _KEYVALUE_DATE_TOKEN_RE.search(normalized)
    if not match:
        return None
    try:
        date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
    except ValueError:
        return None
    if any(marker in normalized for marker in _KEYVALUE_RUN_SCOPED_PATH_MARKERS):
        return _KEYVALUE_RUN_SCOPED_TTL_SECONDS
    return _KEYVALUE_DATE_SCOPED_TTL_SECONDS


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
    return read_text_file_result(path)[0]


def read_text_file_result(path: Path) -> tuple[str | None, bool]:
    # Board audit follow-up, 2026-07-31: mirrors read_json_file_result's
    # already-proven fix for the identical ambiguity (see its docstring) --
    # read_text_file collapsed "key genuinely doesn't exist" and "the read
    # failed" into the same None, so a caller had no way to tell a real,
    # confirmed-empty result from a transient keyvalue-backend hiccup.
    # Root-caused live: WNBA's game_cards.csv keyvalue read
    # (_load_game_cards_csv_rows_from_keyvalue) silently treated a failed
    # read the same as "no games today," and with no fallback for that
    # caller, wiped every WNBA game/prop candidate off the Layer 2 board
    # for that entire refresh cycle -- intermittently, with zero visibility
    # (no exception surfaced, no distinguishing signal), which is exactly
    # what made this take real log archaeology to trace instead of being
    # obvious from the first failure.
    if _state_backend_kind() == "keyvalue":
        try:
            payload_text = _execute_keyvalue_operation(lambda client: client.get(_state_key_for_path(path)))
        except Exception:
            return None, False
        if payload_text is None:
            return None, True
        return str(payload_text).strip(), True
    try:
        return path.read_text(encoding="utf-8").strip(), True
    except FileNotFoundError:
        return None, True
    except Exception:
        return None, False


class KeyValuePayloadTooLarge(ValueError):
    """A keyvalue write was refused because the value is too big to trust.

    Deliberately its own type so callers can distinguish "this payload is
    wrong" from a transient ConnectionError, which is exactly the confusion
    that hid #43.
    """


def _keyvalue_warn_bytes() -> int:
    return _positive_int_env("SYNDICATE_KEYVALUE_WARN_BYTES", 1 * 1024 * 1024)


def _keyvalue_max_bytes() -> int:
    # 8MB. Chosen between two measured points, not guessed: the intelligence
    # state at 8.9MB reproducibly gets "Connection closed by server", and the
    # same payload after #43's trim is 4.37MB and must keep working. A ceiling
    # below the legitimate payload would break the board this rule exists to
    # protect, so it sits above 4.37MB and below the known-failing size.
    return _positive_int_env("SYNDICATE_KEYVALUE_MAX_BYTES", 8 * 1024 * 1024)


def _positive_int_env(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(1024, value)


def _log_payload_composition(key: str, payload: Any, *, top_n: int = 10) -> None:
    """Say WHICH keys make an oversized payload oversized.

    #43/#66. The rejection line names the total, and that total turned out to
    be 37.8MB against an 8MB ceiling -- 8.6x the 4.37MB the last reduction was
    verified at. #43's listed next cuts (evaluation_record 2.21MB,
    candidate_pool 0.84MB) come to ~3MB against a ~29.5MB overage, so they
    cannot close it and the composition has to be measured rather than
    assumed. Only ever runs on the reject path.
    """
    try:
        if not isinstance(payload, dict):
            return

        def _size(value: Any) -> int:
            try:
                return len(json.dumps(value, default=str))
            except Exception:
                return -1

        rows = sorted(((k, _size(v)) for k, v in payload.items()), key=lambda r: -r[1])
        summary = " ".join(f"{k}={size}" for k, size in rows[:top_n])
        print(f"[refresh_state_store] KEYVALUE_PAYLOAD_COMPOSITION key={key} {summary}", flush=True)

        # One level into the biggest key -- that is usually where the real
        # offender is, and a second deploy to find it is a wasted cycle.
        if rows and isinstance(payload.get(rows[0][0]), dict):
            biggest = rows[0][0]
            nested = sorted(((k, _size(v)) for k, v in payload[biggest].items()), key=lambda r: -r[1])
            nested_summary = " ".join(f"{k}={size}" for k, size in nested[:top_n])
            print(
                f"[refresh_state_store] KEYVALUE_PAYLOAD_COMPOSITION key={key} under={biggest} {nested_summary}",
                flush=True,
            )
    except Exception:
        pass


def _guard_keyvalue_payload_size(path: Path, serialized: str, payload: Any = None) -> None:
    """Make an oversized keyvalue write loud instead of mysterious.

    #60. Three separate 2026-07-25 outages were one bug -- an unbounded
    payload crossing this boundary -- and every one of them presented as
    something else: an empty board (#43), a missing metric (#54), a memory
    leak (#50). The size was never the hard part; the silence was. #43 in
    particular threw ConnectionError from deep inside redis, got caught by a
    generic handler, and left a healthy-looking loop discarding a correctly
    computed 222-candidate board every cycle for hours.

    So: warn while a value is merely growing, and refuse it before it reaches
    the size that produces an opaque connection reset. A refusal that names
    the key, the size and the caller is recoverable in minutes. The
    alternative is what today cost.
    """
    size_bytes = len(serialized.encode("utf-8", errors="replace"))
    warn_bytes = _keyvalue_warn_bytes()
    if size_bytes < warn_bytes:
        return

    key = _state_key_for_path(path)
    max_bytes = _keyvalue_max_bytes()
    # Only walked on the rare warn/reject path, so the cost is irrelevant --
    # and knowing WHICH writer is responsible is most of the diagnosis.
    try:
        import traceback

        # Filter this module out rather than slicing a fixed number of frames:
        # a fixed slice empties the whole list on a shallow stack, which is
        # how this field came back blank the first time it was tested. The
        # caller is the single most useful thing in this log line.
        frames = [f for f in traceback.extract_stack() if "refresh_state_store" not in f.filename]
        caller = " <- ".join(f"{Path(f.filename).name}:{f.lineno}" for f in reversed(frames[-3:])) or "unknown"
    except Exception:
        caller = "unknown"

    if size_bytes >= max_bytes:
        print(
            f"[refresh_state_store] KEYVALUE_WRITE_REJECTED key={key} "
            f"size_bytes={size_bytes} max_bytes={max_bytes} caller={caller}",
            flush=True,
        )
        _log_payload_composition(key, payload)
        raise KeyValuePayloadTooLarge(
            f"Refusing keyvalue write for {key}: {size_bytes} bytes exceeds {max_bytes}. "
            "Shrink the payload (see docs/ai_context/todo.md #60) rather than raising the ceiling -- "
            "the store closes the connection above roughly 9MB, which surfaces as an unrelated ConnectionError."
        )

    print(
        f"[refresh_state_store] KEYVALUE_WRITE_LARGE key={key} "
        f"size_bytes={size_bytes} warn_bytes={warn_bytes} max_bytes={max_bytes} caller={caller}",
        flush=True,
    )


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    normalized_payload = normalize_timestamped_payload(payload)
    if _state_backend_kind() == "keyvalue":
        # #43: no human reads the keyvalue value, so indent=2 was spending a
        # third of a ceiling-constrained budget on whitespace. The rejected
        # production payload was 26,397,826 bytes indented against an 8MB
        # ceiling; its top-level keys summed to ~17.5MB compact. Disk writes
        # below keep indentation -- those are read by people.
        serialized = json.dumps(normalized_payload, separators=(",", ":"))
        _guard_keyvalue_payload_size(path, serialized, normalized_payload)
        ttl_seconds = _default_keyvalue_ttl_seconds(path)

        def _write_json(client):
            client.set(_state_key_for_path(path), serialized, ex=ttl_seconds)
            _record_refresh_status_history(path)

        _execute_keyvalue_operation(_write_json)
        return
    _atomic_write_text(path, json.dumps(normalized_payload, indent=2))


def write_text_file(path: Path, payload: str) -> None:
    if _state_backend_kind() == "keyvalue":
        serialized = str(payload or "")
        _guard_keyvalue_payload_size(path, serialized)
        ttl_seconds = _default_keyvalue_ttl_seconds(path)
        _execute_keyvalue_operation(lambda client: client.set(_state_key_for_path(path), serialized, ex=ttl_seconds))
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


# Board audit follow-up, 2026-07-31: read-only diagnostic for the exact
# question this session's WNBA-props-vanishing investigation couldn't
# answer from the app side alone -- is the shared keyvalue backend (one
# Redis instance, "starter" plan, allkeys_lru eviction, shared across web +
# refresh-worker + live-odds-worker) actually under memory/connection
# pressure? A high evicted_keys count would mean confirmed-good data is
# being silently pushed out under memory pressure (a genuine "successful"
# read of a key that's no longer there, not a connection failure --
# read_text_file_result's failure/absence distinction can't catch this,
# since Redis returning "key not found" for an evicted key is
# indistinguishable at the protocol level from a key that was never set).
_KEYVALUE_INFO_FIELDS = (
    "used_memory",
    "used_memory_human",
    "maxmemory",
    "maxmemory_human",
    "maxmemory_policy",
    "evicted_keys",
    "expired_keys",
    "connected_clients",
    "blocked_clients",
    "rejected_connections",
    "total_connections_received",
    "total_commands_processed",
    "instantaneous_ops_per_sec",
    "keyspace_hits",
    "keyspace_misses",
    "role",
    "redis_version",
    "uptime_in_seconds",
)


def keyvalue_diagnostics() -> dict[str, Any] | None:
    if _state_backend_kind() != "keyvalue":
        return None
    try:
        info = _execute_keyvalue_operation(lambda client: client.info())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if not isinstance(info, dict):
        return {"ok": False, "error": "unexpected INFO response shape"}
    stats = {field: info.get(field) for field in _KEYVALUE_INFO_FIELDS if field in info}
    keyspace = {key: value for key, value in info.items() if str(key).startswith("db")}
    return {"ok": True, "stats": stats, "keyspace": keyspace}


def _keyvalue_namespace_key_prefix() -> str:
    return f"{_state_namespace()}:refresh-state:"


def _keyvalue_scan_namespace_keys(client, *, max_keys: int = 20000) -> list[str]:
    # SCAN, not KEYS -- KEYS blocks the whole server for the duration of the
    # scan, which would be a genuinely bad thing to run against a shared
    # production Redis instance three services depend on continuously.
    prefix = _keyvalue_namespace_key_prefix()
    keys: list[str] = []
    cursor = 0
    while True:
        cursor, batch = client.scan(cursor=cursor, match=f"{prefix}*", count=500)
        keys.extend(batch)
        if len(keys) >= max_keys or cursor == 0:
            break
    return keys[:max_keys]


def _keyvalue_key_staleness(key: str, *, today: date, stale_after_days: int) -> tuple[bool, bool]:
    """Returns (has_date_token, is_stale) for one key."""
    match = _KEYVALUE_DATE_TOKEN_RE.search(key)
    if not match:
        return False, False
    try:
        token_date = date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
    except ValueError:
        return False, False
    return True, (today - token_date).days >= stale_after_days


# Board audit follow-up, 2026-07-31: the TTL fix above only applies to
# NEW writes going forward -- it does nothing for the roughly 245MB/2,736
# keys already sitting in the store today, many of which are old, dead
# dates from before this fix existed and will never be rewritten (a
# finished date's game_cards.csv has no future writer). A plan upgrade
# isn't available, so reclaiming THAT existing backlog needs an active
# sweep, not just waiting for organic rewrites. Preview (read-only, safe to
# run any time) and apply (mutating) are deliberately separate functions --
# see keyvalue_sweep_apply's own docstring for why apply sets a grace-
# period TTL rather than deleting outright.
def keyvalue_sweep_preview(*, stale_after_days: int = 2) -> dict[str, Any] | None:
    if _state_backend_kind() != "keyvalue":
        return None

    def _scan(client):
        keys = _keyvalue_scan_namespace_keys(client)
        today = datetime.now(timezone.utc).date()
        no_date_token_keys = 0
        fresh_or_already_ttl_keys = 0
        stale_no_ttl_keys: list[str] = []
        stale_no_ttl_bytes = 0
        sample_stale_keys: list[str] = []
        for key in keys:
            has_date_token, is_stale = _keyvalue_key_staleness(key, today=today, stale_after_days=stale_after_days)
            if not has_date_token:
                no_date_token_keys += 1
                continue
            if not is_stale:
                fresh_or_already_ttl_keys += 1
                continue
            try:
                ttl = client.ttl(key)
            except Exception:
                ttl = -1
            if ttl is not None and ttl >= 0:
                fresh_or_already_ttl_keys += 1
                continue
            stale_no_ttl_keys.append(key)
            try:
                size = client.memory_usage(key) or 0
            except Exception:
                size = 0
            stale_no_ttl_bytes += size
            if len(sample_stale_keys) < 20:
                sample_stale_keys.append(key)
        return {
            "total_keys_scanned": len(keys),
            "no_date_token_keys": no_date_token_keys,
            "fresh_or_already_ttl_keys": fresh_or_already_ttl_keys,
            "stale_no_ttl_key_count": len(stale_no_ttl_keys),
            "stale_no_ttl_estimated_bytes": stale_no_ttl_bytes,
            "stale_after_days": stale_after_days,
            "sample_stale_keys": sample_stale_keys,
        }

    try:
        return {"ok": True, **_execute_keyvalue_operation(_scan)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_KEYVALUE_USAGE_DATE_TOKEN = re.compile(r"^\d{4}[-_]?\d{2}[-_]?\d{2}")


def _keyvalue_usage_bucket(key: str) -> str:
    """Group a namespaced key into a reportable bucket.

    Keys are mostly filesystem-shaped
    (`syndicate:refresh-state:/opt/.../data/reports/<area>/<date>/<file>`),
    so the useful grouping is the first couple of path segments with date
    and run-stamp segments collapsed -- otherwise every run stamps its own
    bucket and the report is as unreadable as the raw key list.
    """
    text = str(key or "")
    marker = "/data/"
    if marker in text:
        text = text.split(marker, 1)[1]
    elif ":" in text:
        text = text.rsplit(":", 1)[1]
    segments = [segment for segment in text.split("/") if segment]
    bucket: list[str] = []
    for segment in segments:
        if _KEYVALUE_USAGE_DATE_TOKEN.match(segment):
            bucket.append("<date>")
        elif len(bucket) >= 2:
            break
        else:
            bucket.append(segment)
        if len(bucket) >= 3:
            break
    return "/".join(bucket) if bucket else "(unbucketed)"


def keyvalue_usage_by_prefix(*, top_keys: int = 15, max_keys: int = 20000) -> dict[str, Any] | None:
    """Read-only estimated memory usage grouped by key bucket, plus the
    single largest keys.

    Added 2026-08-03: the keyvalue instance was sitting at 230MB of a 256MB
    ceiling with `allkeys-lru` and 37k keys already evicted, and the
    existing sweep-preview only ever accounted for *stale, TTL-less* keys
    (183KB of that 230MB). There was no way to see which live payloads
    actually held the memory, and upgrading the instance is not an option --
    so the reduction work needed a measurement first.
    """
    if _state_backend_kind() != "keyvalue":
        return None

    def _scan(client):
        keys = _keyvalue_scan_namespace_keys(client)
        truncated = len(keys) > max_keys
        scanned = keys[:max_keys]
        buckets: dict[str, dict[str, int]] = {}
        largest: list[tuple[int, str]] = []
        total_bytes = 0
        unsized = 0
        for key in scanned:
            try:
                size = client.memory_usage(key) or 0
            except Exception:
                size = 0
                unsized += 1
            total_bytes += size
            bucket_key = _keyvalue_usage_bucket(key)
            bucket = buckets.setdefault(bucket_key, {"key_count": 0, "bytes": 0})
            bucket["key_count"] += 1
            bucket["bytes"] += size
            largest.append((size, key))
        largest.sort(key=lambda item: item[0], reverse=True)
        ranked = sorted(
            (
                {
                    "bucket": name,
                    "key_count": stats["key_count"],
                    "bytes": stats["bytes"],
                    "mb": round(stats["bytes"] / (1024 * 1024), 2),
                }
                for name, stats in buckets.items()
            ),
            key=lambda item: item["bytes"],
            reverse=True,
        )
        return {
            "keys_scanned": len(scanned),
            "keys_truncated": truncated,
            "keys_without_size": unsized,
            "total_estimated_bytes": total_bytes,
            "total_estimated_mb": round(total_bytes / (1024 * 1024), 2),
            "buckets": ranked,
            "largest_keys": [
                {"key": key, "bytes": size, "mb": round(size / (1024 * 1024), 3)}
                for size, key in largest[: max(0, top_keys)]
            ],
        }

    try:
        return {"ok": True, **_execute_keyvalue_operation(_scan)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_RUN_STAMP_PATTERN = re.compile(r"(\d{8})_(\d{6})")


def _run_stamp_age_hours(key: str, *, now: datetime) -> float | None:
    """Age in hours parsed from a `_YYYYMMDD_HHMMSS` run stamp in the key.
    None when the key carries no parseable stamp -- those are left alone
    rather than guessed at."""
    match = _RUN_STAMP_PATTERN.search(str(key or ""))
    if not match:
        return None
    try:
        stamped = datetime.strptime(f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - stamped).total_seconds() / 3600.0


def keyvalue_expire_run_artifacts(
    *,
    older_than_hours: int = 6,
    grace_period_seconds: int = 300,
    path_contains: str = "migration_runs",
    dry_run: bool = True,
) -> dict[str, Any] | None:
    """Force a short EXPIRE on old per-run diagnostic artifacts.

    The 2026-08-03 measurement found `migration_runs/**` holding 185.71MB
    of a 212.67MB keyvalue total (2,549 keys) on a 256MB instance already
    evicting under `allkeys-lru`. Truncating new writes (44b0f247) stops
    the growth but cannot reclaim the existing backlog, which carries ~37h
    TTLs -- leaving ~2 days of continued pressure during which LRU keeps
    dropping genuine coordination state. Upgrading the instance is not an
    option.

    These keys are per-run diagnostics (captured stdout/stderr, job status,
    gate reports); only the most recent run is read by
    /api/ops/odds-refresh/status, and a fresh one is written every few
    minutes. So expiring old ones is safe in a way expiring board or
    coordination state would not be -- which is exactly why this is scoped
    by `path_contains` and refuses an empty scope.

    EXPIRE rather than DELETE, matching keyvalue_sweep_apply: a reader
    mid-flight still gets its answer, and the memory comes back on the same
    timescale LRU would have taken anyway. Defaults to dry_run so the
    blast radius is always inspectable before anything is mutated.
    """
    if _state_backend_kind() != "keyvalue":
        return None
    scope = str(path_contains or "").strip()
    if not scope:
        # An unscoped sweep here would happily expire board state and
        # coordination keys; refuse rather than accept a dangerous default.
        return {"ok": False, "error": "path_contains is required -- refusing an unscoped run-artifact expiry."}

    def _scan(client):
        keys = _keyvalue_scan_namespace_keys(client)
        now = datetime.now(timezone.utc)
        matched = 0
        expired = 0
        skipped_recent = 0
        skipped_no_stamp = 0
        reclaimed_bytes = 0
        samples: list[str] = []
        for key in keys:
            if scope not in str(key):
                continue
            matched += 1
            age_hours = _run_stamp_age_hours(key, now=now)
            if age_hours is None:
                skipped_no_stamp += 1
                continue
            if age_hours < float(older_than_hours):
                skipped_recent += 1
                continue
            try:
                size = client.memory_usage(key) or 0
            except Exception:
                size = 0
            reclaimed_bytes += size
            if len(samples) < 10:
                samples.append(key)
            if not dry_run:
                try:
                    client.expire(key, int(max(60, grace_period_seconds)))
                except Exception:
                    continue
            expired += 1
        return {
            "dry_run": bool(dry_run),
            "path_contains": scope,
            "older_than_hours": int(older_than_hours),
            "grace_period_seconds": int(max(60, grace_period_seconds)),
            "matched_keys": matched,
            "expired_keys": expired,
            "skipped_recent": skipped_recent,
            "skipped_no_run_stamp": skipped_no_stamp,
            "estimated_reclaimed_bytes": reclaimed_bytes,
            "estimated_reclaimed_mb": round(reclaimed_bytes / (1024 * 1024), 2),
            "sample_keys": samples,
        }

    try:
        return {"ok": True, **_execute_keyvalue_operation(_scan)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def keyvalue_sweep_apply(*, stale_after_days: int = 2, grace_period_seconds: int = 3600) -> dict[str, Any] | None:
    # Sets a short grace-period EXPIRE (default 1 hour) rather than
    # deleting outright -- any reader mid-flight against a stale key still
    # gets its answer, while the memory is reclaimed promptly on the same
    # timescale LRU eviction would have gotten to it anyway, just
    # deliberately and measurably instead of at random. Uses the exact same
    # staleness logic as keyvalue_sweep_preview (same stale_after_days
    # default), so a preview call immediately before an apply call
    # describes what apply is about to do.
    if _state_backend_kind() != "keyvalue":
        return None

    def _sweep(client):
        keys = _keyvalue_scan_namespace_keys(client)
        today = datetime.now(timezone.utc).date()
        keys_touched = 0
        estimated_bytes_reclaimed = 0
        for key in keys:
            has_date_token, is_stale = _keyvalue_key_staleness(key, today=today, stale_after_days=stale_after_days)
            if not has_date_token or not is_stale:
                continue
            try:
                ttl = client.ttl(key)
            except Exception:
                ttl = -1
            if ttl is not None and ttl >= 0:
                continue
            try:
                size = client.memory_usage(key) or 0
            except Exception:
                size = 0
            client.expire(key, grace_period_seconds)
            keys_touched += 1
            estimated_bytes_reclaimed += size
        return {
            "keys_touched": keys_touched,
            "estimated_bytes_reclaimed": estimated_bytes_reclaimed,
            "stale_after_days": stale_after_days,
            "grace_period_seconds": grace_period_seconds,
        }

    try:
        return {"ok": True, **_execute_keyvalue_operation(_sweep)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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