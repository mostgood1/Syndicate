"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Central odds refresh orchestrator that dispatches sport-specific source commands.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

import atexit
import argparse
import gc
import multiprocessing
import json
import os
import re
import subprocess
import sys
import shutil
import threading
import time
import traceback
import faulthandler
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from threading import enumerate as enumerate_threads
from threading import Lock
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

try:
    import psutil
except Exception:  # pragma: no cover - psutil is optional in local test environments
    psutil = None


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.odds_control_plane import write_odds_control_plane_snapshot
from syndicate.features.shared.publish_parity import build_publish_parity_summary
from syndicate.features.shared.odds_refresh_tracking import sync_sport_post_refresh_tracking
from syndicate.features.shared.manifest import publish_sport_manifest
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.memory_observability import log_all_process_memory
from syndicate.features.shared.memory_observability import log_runtime_memory
from syndicate.features.mlb.sources import available_daily_summary_dates as mlb_available_daily_summary_dates
from syndicate.features.nba.sources import available_dates as nba_available_dates
from syndicate.features.ncaab.sources import available_dates as ncaab_available_dates
from syndicate.features.ncaaf.sources import default_season as ncaaf_default_season
from syndicate.features.ncaaf.sources import week_summaries as ncaaf_week_summaries
from syndicate.features.nfl.sources import latest_season as nfl_latest_season
from syndicate.features.nfl.sources import week_summaries as nfl_week_summaries
from syndicate.features.nhl.sources import available_dates as nhl_available_dates
from syndicate.features.wnba.sources import available_dates as wnba_available_dates


_PUBLISH_MANIFEST_LOCK = Lock()

_DEFAULT_INTERVAL_MARKETS = "h2h,spreads,totals,spreads_h1,totals_h1,spreads_h2,totals_h2"
_WNBA_PLAYER_PROP_MARKETS = "player_points,player_rebounds,player_assists,player_points_rebounds_assists,player_threes,player_steals,player_blocks,player_turnovers,player_points_rebounds,player_points_assists,player_rebounds_assists,player_double_double,player_triple_double"
_DEFAULT_REFRESH_STEP_TIMEOUT_SECONDS = 1800
_ALL_PROCESS_MEMORY_HEARTBEAT_SECONDS = 60
_MEMORY_TRACE_LAST_RSS_BYTES: int | None = None
_SPORT_REFRESH_REQUIRED_ARTIFACTS = ("snapshot", "snapshot_alias", "game_slate", "predictions", "board_contract", "manifest")
_SPORT_REFRESH_OPTIONAL_ARTIFACTS = ("smart_sim", "recommendations", "edges", "live_lens", "advanced_analytics", "simulation_detail")
_ALL_PROCESS_MEMORY_HEARTBEAT_STOP = threading.Event()


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _elapsed_seconds(started_at: str, finished_at: str | None = None) -> int | None:
    started = _parse_utc_timestamp(started_at)
    if started is None:
        return None
    finished = _parse_utc_timestamp(finished_at) or datetime.now(timezone.utc)
    elapsed = int((finished - started).total_seconds())
    return elapsed if elapsed >= 0 else 0


@dataclass(frozen=True)
class RefreshStep:
    name: str
    phases: tuple[str, ...]
    cwd: Path
    command: tuple[str, ...]
    env_updates: dict[str, str] | None = None
    description: str | None = None


@dataclass(frozen=True)
class SportSpec:
    slug: str
    source_repo_name: str
    mirror_script_name: str
    step_builder: Callable[[argparse.Namespace], list[RefreshStep]]
    ingest_contract_kind: str
    ingest_contract_notes: str = ""
    notes: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _memory_trace_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_TRACE") or "").strip().lower() in {"1", "true", "yes", "on"}


def _rss_bytes() -> int | None:
    if psutil is None:
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            process = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0400, False, os.getpid())
            if not process:
                return None
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
                return int(counters.WorkingSetSize)
        except Exception:
            try:
                with open("/proc/self/status", encoding="utf-8", errors="ignore") as handle:
                    for line in handle:
                        if line.startswith("VmRSS:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return int(parts[1]) * 1024
            except Exception:
                pass
            return None
        return None
    try:
        return int(psutil.Process().memory_info().rss)
    except Exception:
        try:
            with open("/proc/self/status", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024
        except Exception:
            pass
        return None


def _object_summary(value: Any, *, name: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"name": name, "type": type(value).__name__}
    try:
        summary["shallow_size_bytes"] = int(sys.getsizeof(value))
    except Exception:
        summary["shallow_size_bytes"] = None
    try:
        summary["len"] = len(value) if hasattr(value, "__len__") else None
    except Exception:
        summary["len"] = None
    return summary


def _largest_gc_object_summary() -> dict[str, Any] | None:
    largest: dict[str, Any] | None = None
    largest_size = -1
    try:
        for obj in gc.get_objects():
            try:
                size = sys.getsizeof(obj)
            except Exception:
                continue
            if size <= largest_size:
                continue
            largest_size = size
            largest = {
                "type": type(obj).__name__,
                "size_bytes": int(size),
            }
            try:
                if hasattr(obj, "__len__"):
                    largest["len"] = len(obj)
            except Exception:
                pass
    except Exception:
        return None
    return largest


def _largest_gc_container_summary(container_type: type[Any]) -> dict[str, Any] | None:
    largest: dict[str, Any] | None = None
    largest_size = -1
    try:
        for obj in gc.get_objects():
            if not isinstance(obj, container_type):
                continue
            try:
                size = sys.getsizeof(obj)
            except Exception:
                continue
            if size <= largest_size:
                continue
            largest_size = size
            largest = {"type": type(obj).__name__, "size_bytes": int(size)}
            try:
                if hasattr(obj, "__len__"):
                    largest["len"] = len(obj)
            except Exception:
                pass
    except Exception:
        return None
    return largest


def _phase_memory_snapshot() -> dict[str, Any]:
    return {
        "rss_bytes": _rss_bytes(),
        "largest_gc_object": _largest_gc_object_summary(),
        "largest_list": _largest_gc_container_summary(list),
        "largest_dict": _largest_gc_container_summary(dict),
    }


def _extract_count_candidates(text: str | None) -> dict[str, int]:
    if not isinstance(text, str) or not text:
        return {}
    patterns = {
        "rows_loaded": r'"rows_loaded"\s*:\s*(\d+)',
        "loaded_rows": r'"loaded_rows"\s*:\s*(\d+)',
        "row_count": r'"row_count"\s*:\s*(\d+)',
        "games_loaded": r'"games_loaded"\s*:\s*(\d+)',
        "odds_history_rows": r'"odds_history_rows"\s*:\s*(\d+)',
        "payload_rows": r'"payload_rows"\s*:\s*(\d+)',
    }
    counts: dict[str, int] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            try:
                counts[key] = int(match.group(1))
            except Exception:
                continue
    return counts


def _rows_loaded_total(row_counts: dict[str, Any] | None) -> int | None:
    if not isinstance(row_counts, dict):
        return None
    total = 0
    found = False
    for value in row_counts.values():
        try:
            total += int(value)
            found = True
        except Exception:
            continue
    return total if found else None


def _step_rows_loaded(step_result: dict[str, Any] | None) -> int | None:
    if not isinstance(step_result, dict):
        return None
    row_counts = step_result.get("row_counts")
    return _rows_loaded_total(row_counts if isinstance(row_counts, dict) else None)


def _sport_rows_loaded(sport_result: dict[str, Any]) -> int | None:
    refresh_steps = sport_result.get("refresh_steps")
    if not isinstance(refresh_steps, list):
        return None
    total = 0
    found = False
    for step_result in refresh_steps:
        rows = _step_rows_loaded(step_result if isinstance(step_result, dict) else None)
        if rows is None:
            continue
        total += int(rows)
        found = True
    return total if found else None


def _log_memory(stage: str, **extra: Any) -> None:
    if not _memory_trace_enabled():
        return
    global _MEMORY_TRACE_LAST_RSS_BYTES
    before = extra.pop("before", None)
    after = extra.pop("after", None)
    snapshot = after if isinstance(after, dict) else before if isinstance(before, dict) else _phase_memory_snapshot()
    payload: dict[str, Any] = {
        "stage": stage,
        **extra,
    }
    payload.update({key: value for key, value in snapshot.items() if value is not None})
    if isinstance(before, dict):
        payload["memory_before"] = before
    if isinstance(after, dict):
        payload["memory_after"] = after
    current_rss = snapshot.get("rss_bytes") if isinstance(snapshot, dict) else None
    if isinstance(before, dict) and isinstance(after, dict):
        before_rss = before.get("rss_bytes")
        after_rss = after.get("rss_bytes")
        if isinstance(before_rss, int) and isinstance(after_rss, int):
            payload["rss_delta_bytes"] = int(after_rss - before_rss)
            payload["rss_growth_ratio"] = round(after_rss / before_rss, 4) if before_rss > 0 else None
    elif isinstance(current_rss, int) and isinstance(_MEMORY_TRACE_LAST_RSS_BYTES, int):
        payload["rss_delta_from_previous_bytes"] = int(current_rss - _MEMORY_TRACE_LAST_RSS_BYTES)
    if isinstance(current_rss, int):
        _MEMORY_TRACE_LAST_RSS_BYTES = current_rss
    print(f"LIVE_ODDS_WORKER_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)


def _dump_child_runtime_state(*, label: str) -> None:
    current_process = None
    child_processes: list[dict[str, Any]] = []
    if psutil is not None:
        try:
            current_process = psutil.Process()
            for child in current_process.children(recursive=True):
                try:
                    child_processes.append(
                        {
                            "pid": child.pid,
                            "ppid": child.ppid(),
                            "name": child.name(),
                            "status": child.status(),
                            "cmdline": child.cmdline(),
                        }
                    )
                except Exception as child_exc:
                    child_processes.append({"pid": child.pid, "error": f"{type(child_exc).__name__}: {child_exc}"})
        except Exception as exc:
            child_processes.append({"error": f"{type(exc).__name__}: {exc}"})

    threads = enumerate_threads()
    thread_snapshot = [
        {
            "name": thread.name,
            "daemon": thread.daemon,
            "alive": thread.is_alive(),
        }
        for thread in threads
    ]
    print(
        f"[refresh_odds_sources] RUNTIME_SNAPSHOT label={label} ts={_utc_now()} pid={os.getpid()} ppid={os.getppid()} child_count={len(child_processes)}",
        file=sys.stderr,
        flush=True,
    )
    print(f"[refresh_odds_sources] THREADS label={label} data={json.dumps(thread_snapshot, default=str)}", file=sys.stderr, flush=True)
    print(f"[refresh_odds_sources] CHILD_PROCESSES label={label} data={json.dumps(child_processes, default=str)}", file=sys.stderr, flush=True)


def _dump_main_thread_stack(*, label: str) -> None:
    main_thread = threading.main_thread()
    frame = sys._current_frames().get(main_thread.ident) if main_thread.ident is not None else None
    if frame is None:
        print(
            f"[refresh_odds_sources] MAIN_THREAD_STACK label={label} ts={_utc_now()} pid={os.getpid()} status=unavailable",
            file=sys.stderr,
            flush=True,
        )
        return

    stack = traceback.extract_stack(frame)
    current = stack[-1] if stack else None
    frame_payload = {
        "function": current.name if current is not None else None,
        "file": current.filename if current is not None else None,
        "line": current.lineno if current is not None else None,
    }
    print(
        f"[refresh_odds_sources] MAIN_THREAD_STACK label={label} ts={_utc_now()} pid={os.getpid()} frame={json.dumps(frame_payload, sort_keys=True)} stack={json.dumps([str(item) for item in stack])}",
        file=sys.stderr,
        flush=True,
    )


def _shutdown_snapshot_payload() -> dict[str, object]:
    thread_snapshot = []
    for thread in enumerate_threads():
        thread_snapshot.append(
            {
                "name": thread.name,
                "daemon": thread.daemon,
                "alive": thread.is_alive(),
            }
        )

    active_children_snapshot = []
    try:
        for child in multiprocessing.active_children():
            active_children_snapshot.append(
                {
                    "pid": getattr(child, "pid", None),
                    "name": getattr(child, "name", None),
                    "daemon": getattr(child, "daemon", None),
                    "alive": bool(child.is_alive()),
                }
            )
    except Exception as exc:
        active_children_snapshot.append({"error": f"{type(exc).__name__}: {exc}"})

    descendant_snapshot = []
    if psutil is not None:
        try:
            current_process = psutil.Process()
            for descendant in current_process.children(recursive=True):
                try:
                    descendant_snapshot.append(
                        {
                            "pid": descendant.pid,
                            "ppid": descendant.ppid(),
                            "name": descendant.name(),
                            "status": descendant.status(),
                            "daemon": None,
                            "cmdline": descendant.cmdline(),
                        }
                    )
                except Exception as child_exc:
                    descendant_snapshot.append(
                        {
                            "pid": getattr(descendant, "pid", None),
                            "error": f"{type(child_exc).__name__}: {child_exc}",
                        }
                    )
        except Exception as exc:
            descendant_snapshot.append({"error": f"{type(exc).__name__}: {exc}"})

    return {
        "timestamp": _utc_now(),
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "threads": thread_snapshot,
        "multiprocessing_active_children": active_children_snapshot,
        "subprocess_descendants": descendant_snapshot,
    }


def _log_shutdown_snapshot(*, stage: str) -> None:
    payload = _shutdown_snapshot_payload()
    payload["stage"] = stage
    print(f"[refresh_odds_sources] SHUTDOWN_SNAPSHOT {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)


def _start_json_watchdog(*, label: str, delay_seconds: int = 10) -> None:
    started_at = _utc_now()

    def _watchdog() -> None:
        time.sleep(delay_seconds)
        print(
            f"[refresh_odds_sources] JSON_WATCHDOG ts={_utc_now()} started_at={started_at} label={label} pid={os.getpid()}",
            file=sys.stderr,
            flush=True,
        )
        _dump_child_runtime_state(label=f"watchdog:{label}")
        _dump_main_thread_stack(label=f"watchdog:{label}")
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)

    threading.Thread(target=_watchdog, name=f"json-watchdog:{label}", daemon=True).start()


def _stop_all_process_memory_heartbeat() -> None:
    _ALL_PROCESS_MEMORY_HEARTBEAT_STOP.set()


def _start_all_process_memory_heartbeat(*, label: str, interval_seconds: int = _ALL_PROCESS_MEMORY_HEARTBEAT_SECONDS) -> None:
    if interval_seconds <= 0:
        return

    started_at = _utc_now()

    def _heartbeat() -> None:
        next_tick = time.monotonic() + interval_seconds
        while not _ALL_PROCESS_MEMORY_HEARTBEAT_STOP.wait(max(0.0, next_tick - time.monotonic())):
            log_all_process_memory(
                "heartbeat",
                label=label,
                pid=os.getpid(),
                started_at=started_at,
                interval_seconds=int(interval_seconds),
            )
            next_tick += interval_seconds

    threading.Thread(target=_heartbeat, name=f"all-process-memory-heartbeat:{label}", daemon=True).start()


def _source_root_env_var(slug: str) -> str:
    return f"SYNDICATE_SOURCE_ROOT_{slug.upper()}"


def _hosted_data_root() -> Path:
    return data_root()


def _hosted_data_source_root(slug: str) -> Path:
    return _hosted_data_root() / f"{slug}_source"


def _render_data_root_text() -> str | None:
    value = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return value or None


def _source_repo_root(slug: str, source_repo_name: str) -> Path:
    override = str(os.environ.get(_source_root_env_var(slug)) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    hosted_root = _hosted_data_source_root(slug)
    if hosted_root.exists() or _render_data_root_text():
        return hosted_root.resolve()
    return (WORKSPACE_ROOT / source_repo_name).resolve()


def _looks_usable_python(path_text: str | None) -> bool:
    candidate = str(path_text or "").strip()
    if not candidate:
        return False
    lowered = candidate.lower()
    if "windowsapps" in lowered:
        return False
    return Path(candidate).exists()


def _venv_python(source_root: Path) -> str:
    override = str(os.environ.get("SYNDICATE_PYTHON_EXE") or "").strip()
    if _looks_usable_python(override):
        return override
    if _looks_usable_python(sys.executable):
        return str(sys.executable)
    for candidate in (
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "python.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311-arm64" / "python.exe",
    ):
        if candidate.exists():
            return str(candidate)
    candidate = source_root / ".venv" / "Scripts" / "python.exe"
    if _looks_usable_python(str(candidate)):
        return str(candidate)
    return sys.executable or "python"


def _powershell() -> str:
    override = str(os.environ.get("SYNDICATE_POWERSHELL_EXE") or "").strip()
    if override:
        return override
    if os.name == "nt":
        return "powershell.exe"
    for candidate in ("pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "pwsh"


def _merge_pythonpath(existing: str | None, extra: str) -> str:
    if existing:
        return extra + os.pathsep + existing
    return extra


def _json_payload(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"))


def _date_span(values: Sequence[str]) -> dict[str, Any]:
    cleaned = sorted({str(value).strip() for value in values if str(value).strip()})
    return {
        "count": len(cleaned),
        "earliest": cleaned[0] if cleaned else None,
        "latest": cleaned[-1] if cleaned else None,
        "dates": cleaned,
    }


def _week_span(values: Sequence[int], *, season_label: str | None = None) -> dict[str, Any]:
    cleaned = sorted({int(value) for value in values if str(value).strip()})
    label = season_label or "season"
    return {
        "count": len(cleaned),
        "earliest": f"{label} Week {cleaned[0]}" if cleaned else None,
        "latest": f"{label} Week {cleaned[-1]}" if cleaned else None,
        "weeks": cleaned,
    }


def _coverage_report_for_sport(sport: str, *, requested_date: str) -> dict[str, Any]:
    slug = str(sport or "").strip().lower()
    today_text = str(requested_date or "").strip()
    coverage_kind = "dates"
    if slug == "mlb":
        span = _date_span(mlb_available_daily_summary_dates())
    elif slug == "nba":
        span = _date_span(nba_available_dates())
    elif slug == "wnba":
        span = _date_span(wnba_available_dates())
    elif slug == "nhl":
        span = _date_span(nhl_available_dates())
    elif slug == "ncaab":
        span = _date_span(ncaab_available_dates())
    elif slug == "nfl":
        season = nfl_latest_season()
        weeks = [item.get("week") for item in nfl_week_summaries() if int(item.get("season") or 0) == int(season)]
        span = _week_span([int(value) for value in weeks if value is not None], season_label=str(season))
        coverage_kind = "weeks"
    elif slug == "ncaaf":
        season = ncaaf_default_season()
        weeks = [item.get("week") for item in ncaaf_week_summaries() if int(item.get("season") or season) == int(season) and item.get("has_data")]
        span = _week_span([int(value) for value in weeks if value is not None], season_label=str(season))
        coverage_kind = "weeks"
    else:
        span = {"count": 0, "earliest": None, "latest": None}

    latest_value = span.get("latest")
    future_available = bool(latest_value and today_text and coverage_kind == "dates" and str(latest_value) > today_text)
    return {
        "sport": slug,
        "requested_date": today_text or None,
        "coverage_kind": coverage_kind,
        "earliest_collected": span.get("earliest"),
        "latest_collected": span.get("latest"),
        "count": int(span.get("count") or 0),
        "future_available": future_available,
        "details": span,
    }


def _build_odds_coverage_audit(*, requested_date: str) -> dict[str, Any]:
    sports = list(REGISTRY.keys())
    sport_reports = [_coverage_report_for_sport(sport, requested_date=requested_date) for sport in sports]
    future_supported = [item["sport"] for item in sport_reports if item.get("future_available")]
    return {
        "requested_date": requested_date,
        "sports": sport_reports,
        "future_supported_sports": future_supported,
        "all_sports_have_future_coverage": len(future_supported) == len(sport_reports) and bool(sport_reports),
    }


def _infer_nfl_context(source_root: Path | None, artifact_root: Path, season: int | None, week: int | None) -> tuple[int, int]:
    if season is not None and week is not None:
        return int(season), int(week)
    current_week_path = artifact_root / "current_week.json"
    if (not current_week_path.exists()) and source_root is not None:
        current_week_path = source_root / "nfl_compare" / "data" / "current_week.json"
    payload: dict[str, Any] = {}
    if current_week_path.exists():
        try:
            payload = json.loads(current_week_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    resolved_season = int(season if season is not None else payload.get("season") or datetime.now().year)
    resolved_week = int(week if week is not None else payload.get("week") or 1)
    return resolved_season, resolved_week


def _build_mlb_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = REPO_ROOT / "data" / "mlb_source"
    python_exe = _venv_python(REPO_ROOT)
    artifact_root = _local_source_artifact_root("mlb")
    return [
        RefreshStep(
            name="mlb_oddsapi_refresh",
            phases=("pregame", "live"),
            cwd=REPO_ROOT,
            command=(
                python_exe,
                "scripts/refresh_mlb_oddsapi.py",
                "--date",
                args.date,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--regions",
                args.regions,
                "--overwrite",
                "on",
            ),
            description="Refresh MLB markets and live-lens artifacts into a Syndicate-owned bundle.",
        ),
    ]


def _build_nba_payload(args: argparse.Namespace, *, env_key: str) -> dict[str, str]:
    log_dir = _local_source_bundle_root("nba" if env_key == "NBA_BETTING_ODDSAPI_PROPS_JOB" else "wnba") / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"syndicate_refresh_oddsapi_props_{args.date}.log"
    payload = {
        "date_str": args.date,
        "regions": args.regions,
        "bookmakers": str(args.bookmakers or ""),
        "markets": str(args.markets or ""),
        "do_edges": True,
        "do_export": True,
        "do_push": False,
        "started_at": _utc_now(),
        "log_file": str(log_file),
    }
    return {env_key: _json_payload(payload)}


def _effective_markets(slug: str, requested_markets: str) -> str:
    cleaned = str(requested_markets or "").strip()
    if cleaned:
        return cleaned
    if slug in {"nba", "wnba", "ncaab"}:
        return _DEFAULT_INTERVAL_MARKETS
    return ""


def _local_source_artifact_root(slug: str) -> Path:
    hosted_root = _render_data_root_text()
    if hosted_root:
        return Path(hosted_root).expanduser().resolve() / f"{slug}_source"
    return REPO_ROOT / "data" / f"{slug}_source" / "source_artifacts"


def _local_source_bundle_root(slug: str) -> Path:
    hosted_root = _render_data_root_text()
    if hosted_root:
        return Path(hosted_root).expanduser().resolve() / f"{slug}_source"
    return REPO_ROOT / "data" / f"{slug}_source"


def _post_refresh_root(spec: SportSpec) -> Path:
    if spec.slug == "mlb":
        return _local_mlb_bundle_root()
    if spec.slug in {"nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab"}:
        return _local_source_bundle_root(spec.slug)
    return _source_repo_root(spec.slug, spec.source_repo_name)


def _basketball_source_root(slug: str, vendor_repo_name: str) -> Path:
    override = str(os.environ.get(_source_root_env_var(slug)) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    hosted_root = _hosted_data_source_root(slug)
    if hosted_root.exists() or _render_data_root_text():
        return hosted_root.resolve()
    vendor_root = REPO_ROOT / "vendor" / vendor_repo_name
    if vendor_root.exists():
        return vendor_root.resolve()
    return _local_source_bundle_root(slug)


def _local_mlb_bundle_root() -> Path:
    hosted_root = _render_data_root_text()
    if hosted_root:
        return Path(hosted_root).expanduser().resolve() / "mlb_source"
    return REPO_ROOT / "data" / "mlb_source"


def _source_root_resolution(spec: SportSpec) -> dict[str, Any]:
    if spec.slug == "mlb":
        chosen_root = _local_mlb_bundle_root()
        origin = "render_data_root" if _render_data_root_text() else "repo_data_root"
    elif spec.slug in {"nba", "wnba"}:
        vendor_repo_name = "nba_betting_repo" if spec.slug == "nba" else "wnba_betting_repo"
        chosen_root = _basketball_source_root(spec.slug, vendor_repo_name)
        origin = "render_data_root" if _render_data_root_text() else ("vendor_repo" if (REPO_ROOT / "vendor" / vendor_repo_name).exists() else "repo_data_root")
    else:
        chosen_root = _source_repo_root(spec.slug, spec.source_repo_name)
        origin = "sport_env_override" if str(os.environ.get(_source_root_env_var(spec.slug)) or "").strip() else ("render_data_root" if _render_data_root_text() else "workspace_repo")

    return {
        "root": chosen_root,
        "root_text": str(chosen_root),
        "exists": chosen_root.exists(),
        "origin": origin,
        "render_data_root": _render_data_root_text(),
        "source_root_env_var": _source_root_env_var(spec.slug),
    }


def _build_nba_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = _basketball_source_root("nba", "nba_betting_repo")
    python_exe = _venv_python(REPO_ROOT)
    payload = _build_nba_payload(args, env_key="NBA_BETTING_ODDSAPI_PROPS_JOB")["NBA_BETTING_ODDSAPI_PROPS_JOB"]
    payload_data = json.loads(payload)
    artifact_root = _local_source_artifact_root("nba")
    markets = _effective_markets("nba", args.markets)
    command = [
        python_exe,
        "scripts/refresh_nba_oddsapi_props.py",
        "--date",
        args.date,
        "--regions",
        args.regions,
        "--source-root",
        str(source_root),
        "--artifact-root",
        str(artifact_root),
        "--log-file",
        str(payload_data.get("log_file") or ""),
        "--started-at",
        str(payload_data.get("started_at") or ""),
        "--do-edges",
        "--do-export",
    ]
    if args.bookmakers:
        command.extend(["--bookmakers", str(args.bookmakers)])
    if markets:
        command.extend(["--markets", markets])
    return [
        RefreshStep(
            name="nba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=REPO_ROOT,
            command=tuple(command),
            description="Refresh NBA OddsAPI props snapshot, edges, and recommendations.",
        )
    ]


def _build_wnba_steps(args: argparse.Namespace) -> list[RefreshStep]:
    source_root = _basketball_source_root("wnba", "wnba_betting_repo")
    python_exe = _venv_python(REPO_ROOT)
    payload = _build_nba_payload(args, env_key="WNBA_BETTING_ODDSAPI_PROPS_JOB")["WNBA_BETTING_ODDSAPI_PROPS_JOB"]
    payload_data = json.loads(payload)
    artifact_root = _local_source_artifact_root("wnba")
    markets = str(args.markets or "").strip() or _WNBA_PLAYER_PROP_MARKETS
    command = [
        python_exe,
        "scripts/refresh_wnba_oddsapi_props.py",
        "--date",
        args.date,
        "--regions",
        args.regions,
        "--source-root",
        str(source_root),
        "--artifact-root",
        str(artifact_root),
        "--log-file",
        str(payload_data.get("log_file") or ""),
        "--started-at",
        str(payload_data.get("started_at") or ""),
        "--do-edges",
        "--do-export",
    ]
    if args.bookmakers:
        command.extend(["--bookmakers", str(args.bookmakers)])
    if markets:
        command.extend(["--markets", markets])
    return [
        RefreshStep(
            name="wnba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=REPO_ROOT,
            command=tuple(command),
            description="Refresh WNBA OddsAPI props snapshot, edges, and recommendations.",
        )
    ]


def _build_nhl_steps(args: argparse.Namespace) -> list[RefreshStep]:
    python_exe = _venv_python(REPO_ROOT)
    artifact_root = _local_source_artifact_root("nhl")
    return [
        RefreshStep(
            name="nhl_oddsapi_refresh",
            phases=("pregame", "live"),
            cwd=REPO_ROOT,
            command=(
                python_exe,
                "scripts/refresh_nhl_oddsapi.py",
                "--date",
                args.date,
                "--artifact-root",
                str(artifact_root),
            ),
            description="Refresh NHL team odds and player props lines into a Syndicate-owned artifact bundle.",
        ),
    ]


def _build_nfl_steps(args: argparse.Namespace) -> list[RefreshStep]:
    python_exe = _venv_python(REPO_ROOT)
    artifact_root = _local_source_artifact_root("nfl")
    source_root = _source_repo_root("nfl", "NFL-Betting")
    season, week = _infer_nfl_context(source_root, artifact_root, args.season, args.week)
    return [
        RefreshStep(
            name="nfl_oddsapi_refresh",
            phases=("pregame", "live"),
            cwd=REPO_ROOT,
            command=(
                python_exe,
                "scripts/refresh_nfl_oddsapi.py",
                "--artifact-root",
                str(artifact_root),
                "--season",
                str(season),
                "--week",
                str(week),
            ),
            description="Refresh NFL team odds and player props into a Syndicate-owned artifact bundle.",
        ),
    ]


def _build_ncaab_steps(args: argparse.Namespace) -> list[RefreshStep]:
    python_exe = _venv_python(REPO_ROOT)
    raw_outputs_root = REPO_ROOT / "data" / "ncaab_source" / "raw_outputs" / "by_date" / args.date
    markets = _effective_markets("ncaab", args.markets)
    return [
        RefreshStep(
            name="ncaab_odds_history_snapshot",
            phases=("pregame", "live"),
            cwd=REPO_ROOT,
            command=(
                python_exe,
                "scripts/refresh_ncaab_odds_history.py",
                "--date",
                args.date,
                "--region",
                args.regions,
                "--out-dir",
                str(raw_outputs_root),
                "--mode",
                "current",
                "--markets",
                markets,
            ),
            description="Refresh NCAAB current-day odds snapshot with full-game and derivative markets.",
        )
    ]


def _build_ncaaf_steps(args: argparse.Namespace) -> list[RefreshStep]:
    python_exe = _venv_python(REPO_ROOT)
    artifact_root = _local_source_artifact_root("ncaaf")
    command = [
        python_exe,
        "scripts/refresh_ncaaf_oddsapi.py",
        "--artifact-root",
        str(artifact_root),
    ]
    if args.week is not None:
        command.extend(["--week", str(args.week)])
    return [
        RefreshStep(
            name="ncaaf_lines_snapshot",
            phases=("pregame", "live"),
            cwd=REPO_ROOT,
            command=tuple(command),
            description="Refresh NCAAF lines and bundle source recommendation artifacts through a Syndicate-owned runner.",
        )
    ]


REGISTRY: dict[str, SportSpec] = {
    "mlb": SportSpec(
        slug="mlb",
        source_repo_name="mlb_source",
        mirror_script_name="refresh_mlb_source_mirror.ps1",
        step_builder=_build_mlb_steps,
        ingest_contract_kind="artifact_bundle_or_existing_mirror",
        ingest_contract_notes="Hosted-safe ingest can rebuild from existing files under data/mlb_source or from a published MLB artifact bundle root via SYNDICATE_ARTIFACT_ROOT_MLB.",
        notes="Uses the source OddsAPI and live-lens helpers through a Syndicate-owned runner that materializes the MLB artifact bundle contract.",
    ),
    "nba": SportSpec(
        slug="nba",
        source_repo_name="Syndicate/vendor/nba_betting_repo",
        mirror_script_name="refresh_nba_source_mirror.ps1",
        step_builder=_build_nba_steps,
        ingest_contract_kind="artifact_bundle_or_existing_mirror",
        ingest_contract_notes="Hosted-safe ingest can rebuild from existing files under data/nba_source or from a published NBA artifact bundle root via SYNDICATE_ARTIFACT_ROOT_NBA.",
        notes="Uses the Syndicate NBA props runner, which reuses local source outputs or an existing artifact bundle, regenerates the raw OddsAPI snapshot locally, runs both prediction branches through Syndicate-owned helpers, uses a fully local SmartSim compatibility bridge, and writes props_predictions_<date>.csv, props_edges_<date>.csv, props_recommendations_<date>.csv, and supporting SmartSim artifacts without importing source runtime modules.",
    ),
    "nhl": SportSpec(
        slug="nhl",
        source_repo_name="nhl_source",
        mirror_script_name="refresh_nhl_source_mirror.ps1",
        step_builder=_build_nhl_steps,
        ingest_contract_kind="artifact_bundle_or_existing_mirror",
        ingest_contract_notes="Hosted-safe ingest can rebuild from existing files under data/nhl_source or from a published NHL artifact bundle root via SYNDICATE_ARTIFACT_ROOT_NHL.",
        notes="Refreshes both team odds and player props using the source CLI instead of a new Syndicate fetcher.",
    ),
    "nfl": SportSpec(
        slug="nfl",
        source_repo_name="NFL-Betting",
        mirror_script_name="refresh_nfl_source_mirror.ps1",
        step_builder=_build_nfl_steps,
        ingest_contract_kind="artifact_bundle_or_existing_mirror",
        ingest_contract_notes="Hosted-safe ingest can rebuild from existing files under data/nfl_source or from a published NFL artifact bundle root via SYNDICATE_ARTIFACT_ROOT_NFL.",
        notes="Uses the source team's JSON odds snapshot plus weekly player-props CSV flow.",
    ),
    "wnba": SportSpec(
        slug="wnba",
        source_repo_name="Syndicate/vendor/wnba_betting_repo",
        mirror_script_name="refresh_wnba_source_mirror.ps1",
        step_builder=_build_wnba_steps,
        ingest_contract_kind="artifact_bundle_or_existing_mirror",
        ingest_contract_notes="Hosted-safe ingest can rebuild from existing files under data/wnba_source or from a published WNBA artifact bundle root via SYNDICATE_ARTIFACT_ROOT_WNBA.",
        notes="Uses the Syndicate WNBA props runner, which reuses local source outputs or an existing artifact bundle, regenerates the raw OddsAPI snapshot locally, runs both prediction branches through Syndicate-owned helpers, uses the same fully local SmartSim compatibility bridge, and writes props_predictions_<date>.csv, props_edges_<date>.csv, props_recommendations_<date>.csv, and supporting SmartSim artifacts without importing source runtime modules.",
    ),
    "ncaab": SportSpec(
        slug="ncaab",
        source_repo_name="NCAAB",
        mirror_script_name="refresh_ncaab_source_mirror.ps1",
        step_builder=_build_ncaab_steps,
        ingest_contract_kind="existing_raw_outputs",
        ingest_contract_notes="Hosted-safe ingest can rebuild the local API bundle from the mirrored raw bundle under data/ncaab_source/raw_outputs.",
        notes="Uses the existing TheOddsAPI adapter through a Syndicate-owned runner so period markets keep the same event-level fetch behavior while the planner stops shelling directly into the source CLI.",
    ),
    "ncaaf": SportSpec(
        slug="ncaaf",
        source_repo_name="NCAAFCompare",
        mirror_script_name="refresh_ncaaf_source_mirror.ps1",
        step_builder=_build_ncaaf_steps,
        ingest_contract_kind="artifact_bundle_or_existing_mirror",
        ingest_contract_notes="Hosted-safe ingest can rebuild from existing files under data/ncaaf_source or from a published NCAAF artifact bundle root via SYNDICATE_ARTIFACT_ROOT_NCAAF.",
        notes="Uses a Syndicate-owned NCAAF lines runner that reads and writes the local artifact bundle contract instead of calling the sibling fetch script directly.",
    ),
}


def _ingest_is_hosted_safe(spec: SportSpec) -> bool:
    return spec.ingest_contract_kind in {"existing_mirror_artifacts", "existing_raw_outputs", "artifact_bundle_or_existing_mirror"}


def _generation_payload(spec: SportSpec, *, execution_mode: str, source_root: Path) -> dict[str, Any]:
    if execution_mode == "source" and spec.slug == "mlb":
        return {
            "kind": "local_artifact_bundle",
            "source_dependency": "local_artifact_bundle",
            "hosted_safe": True,
            "source_repo": str(source_root),
            "steps": [],
        }
    if execution_mode == "source" and spec.slug in {"nba", "wnba"}:
        return {
            "kind": "local_artifact_bundle",
            "source_dependency": "local_artifact_bundle",
            "hosted_safe": True,
            "source_repo": str(source_root),
            "steps": [],
        }
    if execution_mode == "source" and spec.slug == "nhl":
        return {
            "kind": "local_artifact_bundle",
            "source_dependency": "local_artifact_bundle",
            "hosted_safe": True,
            "source_repo": str(source_root),
            "steps": [],
        }
    if execution_mode == "source" and spec.slug == "ncaab":
        return {
            "kind": "local_raw_outputs",
            "source_dependency": "local_raw_outputs",
            "hosted_safe": True,
            "source_repo": str(source_root),
            "steps": [],
        }
    if execution_mode == "source" and spec.slug == "ncaaf":
        return {
            "kind": "local_artifact_bundle",
            "source_dependency": "local_artifact_bundle",
            "hosted_safe": True,
            "source_repo": str(source_root),
            "steps": [],
        }
    return {
        "kind": "source_repo" if execution_mode == "source" else "none",
        "source_dependency": "source_repo" if execution_mode == "source" else "none",
        "hosted_safe": execution_mode != "source",
        "source_repo": str(source_root),
        "steps": [],
    }


def _ingestion_payload(spec: SportSpec, *, skip_mirror: bool, execution_mode: str) -> dict[str, Any] | None:
    if skip_mirror:
        return None
    source_dependency = "source_repo_artifacts"
    if execution_mode == "ingest" and _ingest_is_hosted_safe(spec):
        source_dependency = "local_artifacts"
    elif execution_mode == "source" and spec.slug == "ncaab":
        source_dependency = "local_artifacts"
    elif execution_mode == "source" and spec.slug in {"mlb", "nba", "wnba", "nhl", "nfl", "ncaaf"}:
        source_dependency = "local_artifact_bundle"
    return {
        "kind": "mirror_script",
        "source_dependency": source_dependency,
        "hosted_safe": execution_mode == "ingest" and _ingest_is_hosted_safe(spec),
        "contract": {
            "kind": spec.ingest_contract_kind,
            "notes": spec.ingest_contract_notes,
        },
        "step": None,
    }


def _parse_sports(raw: str) -> list[str]:
    cleaned = [part.strip().lower() for part in str(raw or "all").split(",") if part.strip()]
    if not cleaned or cleaned == ["all"]:
        return list(REGISTRY.keys())
    unknown = [sport for sport in cleaned if sport not in REGISTRY]
    if unknown:
        raise ValueError(f"Unknown sport(s): {', '.join(sorted(unknown))}")
    return cleaned


def _resolve_execution_mode(raw: str | None, *, mirror_only: bool = False) -> str:
    if mirror_only:
        return "ingest"
    value = str(raw or "source").strip().lower()
    if value in {"source", "ingest"}:
        return value
    raise ValueError("execution_mode must be 'source' or 'ingest'.")


def _serial_sport_refresh_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_SERIAL_SPORT_REFRESH") or "").strip().lower() in {"1", "true", "yes", "on"}


def _refresh_step_timeout_seconds() -> int:
    timeout_value = str(os.environ.get("SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS") or "").strip()
    if timeout_value:
        try:
            return max(1, int(timeout_value))
        except ValueError:
            pass
    return _DEFAULT_REFRESH_STEP_TIMEOUT_SECONDS


def _run_command(step: RefreshStep, *, dry_run: bool = False) -> dict[str, Any]:
    env = os.environ.copy()
    if step.env_updates:
        env.update({key: value for key, value in step.env_updates.items() if value is not None})
    started = _utc_now()
    timeout_seconds = _refresh_step_timeout_seconds()
    print(f"PRE_STEP_LOG name={step.name}", file=sys.stderr, flush=True)
    print(f"STEP_START name={step.name} cwd={step.cwd} command={json.dumps(list(step.command))}", file=sys.stderr, flush=True)
    print(f"POST_STEP_LOG name={step.name}", file=sys.stderr, flush=True)
    print(f"[refresh_odds_sources] START step={step.name} cwd={step.cwd}", flush=True)
    _log_memory("step_start", step=step.name, dry_run=bool(dry_run), cwd=str(step.cwd))
    _dump_child_runtime_state(label=f"step_start:{step.name}")
    if dry_run:
        print(f"STEP_END name={step.name} status=dry_run runtime_seconds=0", file=sys.stderr, flush=True)
        print(f"[refresh_odds_sources] END step={step.name} dry_run=true", flush=True)
        _dump_child_runtime_state(label=f"step_end:{step.name}:dry_run")
        _log_memory("step_end_dry_run", step=step.name)
        return {
            "name": step.name,
            "description": step.description,
            "cwd": str(step.cwd),
            "command": list(step.command),
            "return_code": 0,
            "started_at": started,
            "finished_at": started,
            "stdout": "",
            "stderr": "",
            "ok": True,
            "dry_run": True,
        }
    result = None
    try:
        log_runtime_memory("before_sport_launch", step=step.name, cwd=str(step.cwd), dry_run=bool(dry_run))
        result = subprocess.run(
            list(step.command),
            cwd=str(step.cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        log_runtime_memory("after_sport_launch", step=step.name, cwd=str(step.cwd), status="timeout")
        finished = _utc_now()
        runtime_seconds = _elapsed_seconds(started, finished)
        print(
            f"STEP_FAIL name={step.name} status=timeout runtime_seconds={runtime_seconds if runtime_seconds is not None else 'unknown'} timeout_seconds={timeout_seconds}",
            file=sys.stderr,
            flush=True,
        )
        print(
            f"STEP_END name={step.name} status=timeout runtime_seconds={runtime_seconds if runtime_seconds is not None else 'unknown'} timeout_seconds={timeout_seconds if timeout_seconds is not None else 'none'}",
            file=sys.stderr,
            flush=True,
        )
        print(f"[refresh_odds_sources] FAIL step={step.name} reason=timeout timeout_seconds={timeout_seconds}", flush=True)
        raise
    finally:
        if result is not None:
            log_runtime_memory(
                "after_sport_launch",
                step=step.name,
                cwd=str(step.cwd),
                return_code=int(result.returncode),
                dry_run=bool(dry_run),
            )

    finished = _utc_now()
    stdout_text = str(result.stdout or "")
    stderr_text = str(result.stderr or "")
    row_counts = {
        **_extract_count_candidates(stdout_text),
        **_extract_count_candidates(stderr_text),
    }
    runtime_seconds = _elapsed_seconds(started, finished)
    print(
        f"STEP_END name={step.name} status=ok runtime_seconds={runtime_seconds if runtime_seconds is not None else 'unknown'} return_code={result.returncode} timeout_seconds={timeout_seconds if timeout_seconds is not None else 'none'}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[refresh_odds_sources] END step={step.name} return_code={result.returncode} timeout_seconds={timeout_seconds if timeout_seconds is not None else 'none'}",
        flush=True,
    )
    _log_memory(
        "step_end",
        step=step.name,
        return_code=int(result.returncode),
        stdout=_object_summary(stdout_text, name="stdout"),
        stderr=_object_summary(stderr_text, name="stderr"),
        row_counts=row_counts or None,
        rows_loaded=_rows_loaded_total(row_counts),
    )
    _dump_child_runtime_state(label=f"step_end:{step.name}:rc={result.returncode}")
    return {
        "name": step.name,
        "description": step.description,
        "cwd": str(step.cwd),
        "command": list(step.command),
        "return_code": int(result.returncode),
        "started_at": started,
        "finished_at": finished,
        "row_counts": row_counts or None,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "ok": result.returncode == 0,
        "dry_run": False,
    }


def _compact_step_result(step_result: dict[str, Any]) -> None:
    if not isinstance(step_result, dict):
        return
    if isinstance(step_result.get("stdout"), str):
        step_result["stdout"] = ""
    if isinstance(step_result.get("stderr"), str):
        step_result["stderr"] = ""


def _compact_step_result_view(step_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(step_result, dict):
        return None
    compact = {
        "name": step_result.get("name"),
        "return_code": step_result.get("return_code"),
        "ok": bool(step_result.get("ok")),
        "dry_run": bool(step_result.get("dry_run")),
        "started_at": step_result.get("started_at"),
        "finished_at": step_result.get("finished_at"),
    }
    row_counts = step_result.get("row_counts")
    if isinstance(row_counts, dict) and row_counts:
        compact["row_counts"] = row_counts
    rows_loaded = _step_rows_loaded(step_result)
    if rows_loaded is not None:
        compact["rows_loaded"] = rows_loaded
    if step_result.get("description"):
        compact["description"] = step_result.get("description")
    return compact


def _compact_artifact_paths(value: Any) -> list[str]:
    compact: list[str] = []
    seen: set[str] = set()
    if isinstance(value, (list, tuple, set)):
        for item in value:
            path_text = str(item or "").strip()
            if not path_text or path_text in seen:
                continue
            seen.add(path_text)
            compact.append(path_text)
    return compact


def _compact_sport_result(sport_result: dict[str, Any]) -> dict[str, Any]:
    artifact_paths = _compact_artifact_paths(sport_result.get("artifact_paths"))
    refresh_steps = sport_result.get("refresh_steps") if isinstance(sport_result.get("refresh_steps"), list) else []
    compact_refresh_steps = [item for item in (_compact_step_result_view(step) for step in refresh_steps) if isinstance(item, dict)]

    compact_generation: dict[str, Any] = {}
    generation = sport_result.get("generation") if isinstance(sport_result.get("generation"), dict) else {}
    if isinstance(generation, dict):
        for key in ("kind", "source_dependency", "hosted_safe", "source_repo"):
            if key in generation:
                compact_generation[key] = generation.get(key)
    compact_generation["steps"] = compact_refresh_steps
    post_refresh = sport_result.get("post_refresh")
    if isinstance(post_refresh, dict):
        compact_post_refresh = {
            "name": post_refresh.get("name"),
            "ok": bool(post_refresh.get("ok")),
            "dry_run": bool(post_refresh.get("dry_run")),
            "return_code": post_refresh.get("return_code"),
        }
        if post_refresh.get("meta"):
            compact_post_refresh["meta"] = post_refresh.get("meta")
        compact_generation["post_refresh"] = compact_post_refresh
    ingestion = sport_result.get("ingestion") if isinstance(sport_result.get("ingestion"), dict) else None
    compact_ingestion: dict[str, Any] | None = None
    if isinstance(ingestion, dict):
        compact_ingestion = {}
        for key in ("kind", "source_dependency", "hosted_safe", "contract"):
            if key in ingestion:
                compact_ingestion[key] = ingestion.get(key)
        if ingestion.get("step"):
            compact_ingestion["step"] = _compact_step_result_view(ingestion.get("step"))

    mirror = sport_result.get("mirror")
    compact_mirror = _compact_step_result_view(mirror if isinstance(mirror, dict) else None)
    sport_manifest = sport_result.get("sport_manifest") if isinstance(sport_result.get("sport_manifest"), dict) else None
    compact_manifest = None
    if isinstance(sport_manifest, dict):
        compact_manifest = {
            "path": sport_manifest.get("path"),
            "artifact_count": len(artifact_paths),
        }

    compact_result: dict[str, Any] = {
        "sport": sport_result.get("sport"),
        "source_repo": sport_result.get("source_repo"),
        "source_root_origin": sport_result.get("source_root_origin"),
        "source_root_exists": bool(sport_result.get("source_root_exists")),
        "source_root_env_var": sport_result.get("source_root_env_var"),
        "notes": sport_result.get("notes"),
        "generation_mode": sport_result.get("generation_mode"),
        "ingestion_mode": sport_result.get("ingestion_mode"),
        "ok": bool(sport_result.get("ok")),
        "artifact_paths": artifact_paths,
        "refresh_steps": compact_refresh_steps,
        "generation": compact_generation,
        "mirror": compact_mirror,
    }
    for key in ("error", "warning", "warnings", "required_artifact_failures", "optional_artifact_failures"):
        if key in sport_result and sport_result.get(key) is not None:
            compact_result[key] = sport_result.get(key)
    if compact_ingestion is not None:
        compact_result["ingestion"] = compact_ingestion
    if compact_manifest is not None:
        compact_result["sport_manifest"] = compact_manifest
    if sport_result.get("post_refresh") is not None:
        compact_result["post_refresh"] = _compact_step_result_view(sport_result.get("post_refresh"))
    if sport_result.get("rows_loaded") is not None:
        compact_result["rows_loaded"] = sport_result.get("rows_loaded")
    return compact_result


def _finalize_sport_result(sport_result: dict[str, Any]) -> dict[str, Any]:
    compacted_sport_result = _compact_sport_result(sport_result)
    sport_result.clear()
    sport_result.update(compacted_sport_result)
    del compacted_sport_result
    gc.collect()
    return sport_result


def _sync_post_refresh_tracking_step(*, sport: str, source_root: Path, date_str: str, dry_run: bool = False) -> dict[str, Any]:
    started = _utc_now()
    if dry_run:
        return {
            "name": f"{sport}_post_refresh_tracking_sync",
            "description": "Persist Syndicate-owned post-refresh tracking artifacts.",
            "cwd": str(source_root),
            "command": [],
            "return_code": 0,
            "started_at": started,
            "finished_at": started,
            "stdout": "",
            "stderr": "",
            "ok": True,
            "dry_run": True,
            "meta": {
                "ok": True,
                "skipped": False,
                "reason": None,
                "sport": sport,
                "date": date_str,
            },
        }
    try:
        meta = sync_sport_post_refresh_tracking(sport=sport, source_root=source_root, date_str=date_str)
        finished = _utc_now()
        return {
            "name": f"{sport}_post_refresh_tracking_sync",
            "description": "Persist Syndicate-owned post-refresh tracking artifacts.",
            "cwd": str(source_root),
            "command": [],
            "return_code": 0 if bool(meta.get("ok")) else 1,
            "started_at": started,
            "finished_at": finished,
            "stdout": "",
            "stderr": "" if bool(meta.get("ok")) else str(meta.get("error") or "post refresh tracking sync failed"),
            "ok": bool(meta.get("ok")),
            "dry_run": False,
            "meta": meta,
        }
    except Exception as exc:
        finished = _utc_now()
        return {
            "name": f"{sport}_post_refresh_tracking_sync",
            "description": "Persist Syndicate-owned post-refresh tracking artifacts.",
            "cwd": str(source_root),
            "command": [],
            "return_code": 1,
            "started_at": started,
            "finished_at": finished,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "ok": False,
            "dry_run": False,
            "meta": {"ok": False, "sport": sport, "date": date_str, "error": f"{type(exc).__name__}: {exc}"},
        }


def _sport_artifact_paths(sport_result: dict[str, Any]) -> list[str]:
    explicit_paths = sport_result.get("artifact_paths") if isinstance(sport_result, dict) else None
    if isinstance(explicit_paths, (list, tuple, set)):
        compact_paths = _compact_artifact_paths(explicit_paths)
        if compact_paths:
            return compact_paths

    paths: list[str] = []
    seen: set[str] = set()

    def add_path(value: Any) -> None:
        path_text = str(value or "").strip()
        if not path_text or path_text in seen:
            return
        seen.add(path_text)
        paths.append(path_text)

    def walk_json_text(value: Any) -> None:
        if not isinstance(value, str):
            return
        text = value.strip()
        if not text or text[0] not in "[{":
            return
        try:
            parsed = json.loads(text)
        except Exception:
            return
        walk(parsed)

    def walk(value: Any, key_name: str = "") -> None:
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                nested_key_text = str(nested_key or "").strip().lower()
                if nested_key_text in {
                    "path",
                    "manifest_path",
                    "latest_path",
                    "run_summary_path",
                    "stdout_path",
                    "stderr_path",
                    "output_path",
                    "source_manifest",
                    "artifact_root",
                    "source_root",
                    "cwd",
                }:
                    add_path(nested_value)
                    walk_json_text(nested_value)
                elif nested_key_text == "artifact_bundle_files" and isinstance(nested_value, dict):
                    for bundle_value in nested_value.values():
                        if isinstance(bundle_value, list):
                            for item in bundle_value:
                                add_path(item)
                        elif isinstance(bundle_value, str):
                            add_path(bundle_value)
                elif nested_key_text in {"artifact_paths", "updated_files", "signal_paths"} and isinstance(nested_value, list):
                    for item in nested_value:
                        add_path(item)
                walk(nested_value, nested_key_text)
        elif isinstance(value, list):
            for item in value:
                walk(item, key_name)
        elif key_name == "stdout":
            walk_json_text(value)
        elif isinstance(value, str) and (
            key_name in {"output", "file", "manifest", "artifact", "path"} or key_name.endswith("_path") or key_name.endswith("_paths")
        ):
            add_path(value)

    walk(sport_result)
    return paths


def _sport_refresh_contract() -> dict[str, list[str]]:
    return {
        "required": list(_SPORT_REFRESH_REQUIRED_ARTIFACTS),
        "optional": list(_SPORT_REFRESH_OPTIONAL_ARTIFACTS),
    }


def _sport_refresh_failure_lists(sport_result: dict[str, Any]) -> tuple[list[str], list[str]]:
    required_failures: list[str] = []
    optional_failures: list[str] = []

    for field in ("required_artifact_failures", "requiredFailures"):
        values = sport_result.get(field)
        if isinstance(values, list):
            for value in values:
                text = str(value or "").strip()
                if text and text not in required_failures:
                    required_failures.append(text)

    for field in ("optional_artifact_failures", "optionalFailures"):
        values = sport_result.get(field)
        if isinstance(values, list):
            for value in values:
                text = str(value or "").strip()
                if text and text not in optional_failures:
                    optional_failures.append(text)

    warning = str(sport_result.get("warning") or "").strip()
    if warning and warning not in optional_failures:
        optional_failures.append(warning)

    warnings = sport_result.get("warnings") if isinstance(sport_result.get("warnings"), list) else []
    for value in warnings:
        text = str(value or "").strip()
        if text and text not in optional_failures:
            optional_failures.append(text)

    error = str(sport_result.get("error") or "").strip()
    if not required_failures:
        if error:
            required_failures.append(error)
        elif not bool(sport_result.get("ok")):
            sport_name = str(sport_result.get("sport") or "sport").strip() or "sport"
            required_failures.append(f"{sport_name} required artifact failure")

    return required_failures, optional_failures


def _sport_control_plane_metadata(sport_result: dict[str, Any], *, date: str, phase: str, execution_mode: str, refresh_mode: str) -> dict[str, Any]:
    artifact_paths = _sport_artifact_paths(sport_result)
    required_artifact_failures, optional_artifact_failures = _sport_refresh_failure_lists(sport_result)
    return {
        "date": date,
        "phase": phase,
        "execution_mode": execution_mode,
        "refresh_mode": refresh_mode,
        "refresh_contract": _sport_refresh_contract(),
        "required_artifact_failures": required_artifact_failures,
        "optional_artifact_failures": optional_artifact_failures,
        "ok": bool(sport_result.get("ok")),
        "post_refresh_ok": bool((sport_result.get("post_refresh") or {}).get("ok")) if isinstance(sport_result.get("post_refresh"), dict) else None,
        "mirror_ok": bool((sport_result.get("mirror") or {}).get("ok")) if isinstance(sport_result.get("mirror"), dict) else None,
        "odds_control_plane": {
            "source_precedence": ["shared_history", "artifact_history", "tracking_history"],
            "artifact_paths": artifact_paths,
            "has_post_refresh": bool(sport_result.get("post_refresh")),
        },
    }


def _validate_source_root(spec: SportSpec) -> str | None:
    resolution = _source_root_resolution(spec)
    source_root = resolution["root"] if isinstance(resolution.get("root"), Path) else Path(str(resolution.get("root_text") or ""))
    if bool(resolution.get("exists")):
        return None
    render_data_root = str(resolution.get("render_data_root") or "").strip()
    origin = str(resolution.get("origin") or "workspace_repo").strip()
    if render_data_root and origin == "render_data_root":
        return (
            f"Render data disk is missing the expected {spec.slug} source root: {source_root}. "
            f"Verify the mounted disk at {render_data_root} contains {source_root.name} before launching refresh."
        )
    if origin == "sport_env_override":
        return f"Source root override not found for {spec.slug}: {source_root}."
    if spec.slug == "mlb":
        return f"Local MLB bundle root not found: {source_root}."
    if spec.slug in {"nba", "wnba"}:
        return f"Local {spec.slug.upper()} source root not found: {source_root}."
    env_var = str(resolution.get("source_root_env_var") or _source_root_env_var(spec.slug))
    return (
        f"Source repo root not found for {spec.slug}: {source_root}. "
        f"Set {env_var} to an absolute path for this sport or use --execution-mode ingest / --mirror-only."
    )


def _step_requires_source_root(step: RefreshStep) -> bool:
    return any(str(part) == "--source-root" for part in step.command)


def _step_command_with_mode(step: RefreshStep, mode: str) -> tuple[str, ...]:
    normalized_mode = str(mode or "full").strip().lower() or "full"
    command = list(step.command)
    if normalized_mode != "full":
        refresh_script_names = {
            "refresh_mlb_oddsapi.py",
            "refresh_nba_oddsapi_props.py",
            "refresh_wnba_oddsapi_props.py",
            "refresh_nhl_oddsapi.py",
            "refresh_nfl_oddsapi.py",
            "refresh_ncaaf_oddsapi.py",
        }
        if any(str(part).endswith(tuple(refresh_script_names)) for part in command):
            command.extend(["--mode", normalized_mode])
    return tuple(command)


def _mirror_command(script_name: str, *, date: str, sport: str | None = None, mirror_only: bool = False) -> RefreshStep:
    command = [_powershell(), "-ExecutionPolicy", "Bypass", "-File", str(REPO_ROOT / "scripts" / script_name)]
    if script_name not in {"refresh_nfl_source_mirror.ps1", "refresh_ncaaf_source_mirror.ps1"}:
        command.extend(["-Date", date])
    if sport == "mlb":
        artifact_root = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_MLB") or "").strip()
        if (not artifact_root) and (not mirror_only):
            artifact_root = str(_local_source_artifact_root("mlb"))
        if artifact_root:
            command.extend(["-SourceArtifactRoot", artifact_root])
    if sport == "nba":
        artifact_root = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NBA") or "").strip()
        if (not artifact_root) and (not mirror_only):
            artifact_root = str(_local_source_artifact_root("nba"))
        if artifact_root:
            command.extend(["-SourceArtifactRoot", artifact_root])
    if sport == "nhl":
        artifact_root = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
        if (not artifact_root) and (not mirror_only):
            artifact_root = str(_local_source_artifact_root("nhl"))
        if artifact_root:
            command.extend(["-SourceArtifactRoot", artifact_root])
    if sport == "nfl":
        artifact_root = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NFL") or "").strip()
        if (not artifact_root) and (not mirror_only):
            artifact_root = str(_local_source_artifact_root("nfl"))
        if artifact_root:
            command.extend(["-SourceArtifactRoot", artifact_root])
    if sport == "ncaaf":
        artifact_root = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NCAAF") or "").strip()
        if (not artifact_root) and (not mirror_only):
            artifact_root = str(_local_source_artifact_root("ncaaf"))
        if artifact_root:
            command.extend(["-SourceArtifactRoot", artifact_root])
    if sport == "wnba":
        artifact_root = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_WNBA") or "").strip()
        if (not artifact_root) and (not mirror_only):
            artifact_root = str(_local_source_artifact_root("wnba"))
        if artifact_root:
            command.extend(["-SourceArtifactRoot", artifact_root])
    if mirror_only and sport == "ncaab":
        command.append("-UseExistingRawOutputs")
    if mirror_only and sport == "mlb":
        command.append("-UseExistingMirrorArtifacts")
    if mirror_only and sport == "nba":
        command.append("-UseExistingMirrorArtifacts")
    if mirror_only and sport == "nhl":
        command.append("-UseExistingMirrorArtifacts")
    if mirror_only and sport == "nfl":
        command.append("-UseExistingMirrorArtifacts")
    if mirror_only and sport == "ncaaf":
        command.append("-UseExistingMirrorArtifacts")
    if mirror_only and sport == "wnba":
        command.append("-UseExistingMirrorArtifacts")
    return RefreshStep(
        name=script_name.replace(".ps1", ""),
        phases=("pregame", "live", "all"),
        cwd=REPO_ROOT,
        command=tuple(command),
        description="Mirror refreshed source artifacts into Syndicate.",
    )


def _hosted_source_mode_writes_directly(*, spec: SportSpec, execution_mode: str, mirror_only: bool) -> bool:
    if mirror_only or execution_mode != "source":
        return False
    if not str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip():
        return False
    return spec.slug in {"mlb", "nba", "nhl", "nfl", "wnba", "ncaaf"}


def _filter_steps(steps: Sequence[RefreshStep], phase: str) -> list[RefreshStep]:
    if phase == "all":
        return list(steps)
    return [step for step in steps if phase in step.phases]


def _publish_sport_manifest_threadsafe(*, sport: str, artifact_paths: list[str], metadata: dict[str, Any]) -> dict[str, Any]:
    with _PUBLISH_MANIFEST_LOCK:
        return publish_sport_manifest(
            sport=sport,
            artifact_paths=artifact_paths,
            metadata=metadata,
        )


def _run_sport_refresh(args: argparse.Namespace, sport: str, execution_mode: str) -> dict[str, Any]:
    spec = REGISTRY[sport]
    refresh_mode = str(getattr(args, "mode", "full") or "full").strip().lower() or "full"
    source_root_resolution = _source_root_resolution(spec)
    source_root = source_root_resolution["root"] if isinstance(source_root_resolution.get("root"), Path) else Path(str(source_root_resolution.get("root_text") or ""))

    generation_mode = "source_repo"
    if execution_mode == "source" and spec.slug == "mlb":
        generation_mode = "local_artifact_bundle"
    if execution_mode == "source" and spec.slug in {"ncaaf", "nhl", "nba", "wnba"}:
        generation_mode = "local_artifact_bundle"
    elif execution_mode == "source" and spec.slug == "ncaab":
        generation_mode = "local_raw_outputs"

    sport_result: dict[str, Any] = {
        "sport": sport,
        "source_repo": str(source_root),
        "source_root_origin": str(source_root_resolution.get("origin") or "unknown"),
        "source_root_exists": bool(source_root.exists()),
        "source_root_env_var": _source_root_env_var(spec.slug),
        "notes": spec.notes,
        "generation_mode": generation_mode if execution_mode == "source" else "none",
        "ingestion_mode": None if args.skip_mirror else "mirror_script",
        "generation": _generation_payload(spec, execution_mode=execution_mode, source_root=source_root),
        "ingestion": _ingestion_payload(spec, skip_mirror=bool(args.skip_mirror), execution_mode=execution_mode),
        "artifact_paths": [],
        "refresh_steps": [],
        "mirror": None,
        "ok": True,
    }
    sport_start_memory = _phase_memory_snapshot()
    _log_memory(
        "sport_start",
        sport=sport,
        execution_mode=execution_mode,
        generation_mode=generation_mode,
        rows_loaded=0,
        refresh_steps=_object_summary(sport_result["refresh_steps"], name="refresh_steps"),
        generation_steps=_object_summary(sport_result["generation"]["steps"], name="generation_steps"),
        same_object=bool(sport_result["refresh_steps"] is sport_result["generation"]["steps"]),
        before=sport_start_memory,
        after=sport_start_memory,
    )

    refresh_steps = [] if execution_mode == "ingest" else _filter_steps(spec.step_builder(args), args.phase)
    if refresh_steps and any(_step_requires_source_root(step) for step in refresh_steps):
        source_error = _validate_source_root(spec)
        if source_error is not None:
            sport_result["ok"] = False
            sport_result["error"] = source_error
            _log_memory(
                f"{sport}_refresh",
                sport=sport,
                rows_loaded=_sport_rows_loaded(sport_result),
                refresh_steps=_object_summary(sport_result["refresh_steps"], name="refresh_steps"),
                generation_steps=_object_summary(sport_result["generation"]["steps"], name="generation_steps"),
                same_object=bool(sport_result["refresh_steps"] is sport_result["generation"]["steps"]),
                error=source_error,
                before=sport_start_memory,
                after=_phase_memory_snapshot(),
            )
            return _finalize_sport_result(sport_result)

    for step in refresh_steps:
        step_result = _run_command(
            RefreshStep(
                name=step.name,
                phases=step.phases,
                cwd=step.cwd,
                command=_step_command_with_mode(step, refresh_mode),
                env_updates=step.env_updates,
                description=step.description,
            ),
            dry_run=bool(args.dry_run),
        )
        sport_result["refresh_steps"].append(step_result)
        sport_result["generation"]["steps"].append(step_result)
        for artifact_path in _sport_artifact_paths(step_result):
            if artifact_path not in sport_result["artifact_paths"]:
                sport_result["artifact_paths"].append(artifact_path)
        _log_memory(
            "sport_step_appended",
            sport=sport,
            step=step.name,
            step_result_id=id(step_result),
            refresh_steps_len=len(sport_result["refresh_steps"]),
            generation_steps_len=len(sport_result["generation"]["steps"]),
            same_object=bool(sport_result["refresh_steps"][-1] is sport_result["generation"]["steps"][-1]),
            step_payload=_object_summary(step_result, name="step_result"),
            rows_loaded=_step_rows_loaded(step_result),
        )
        _compact_step_result(step_result)
        if not step_result["ok"]:
            sport_result["ok"] = False
            if not args.continue_on_error:
                _log_memory(
                    f"{sport}_refresh",
                    sport=sport,
                    rows_loaded=_sport_rows_loaded(sport_result),
                    refresh_steps=_object_summary(sport_result["refresh_steps"], name="refresh_steps"),
                    generation_steps=_object_summary(sport_result["generation"]["steps"], name="generation_steps"),
                    same_object=bool(sport_result["refresh_steps"] is sport_result["generation"]["steps"]),
                    failed_step=step.name,
                    before=sport_start_memory,
                    after=_phase_memory_snapshot(),
                )
                return _finalize_sport_result(sport_result)

    if refresh_mode == "fast":
        published_manifest = _publish_sport_manifest_threadsafe(
            sport=spec.slug,
            artifact_paths=_sport_artifact_paths(sport_result),
            metadata=_sport_control_plane_metadata(
                sport_result,
                date=args.date,
                phase=args.phase,
                execution_mode=execution_mode,
                refresh_mode=refresh_mode,
            ),
        )
        sport_result["sport_manifest"] = published_manifest
        _log_memory("sport_fast_publish", sport=sport, manifest=_object_summary(published_manifest, name="sport_manifest"))
        _log_memory(
            f"{sport}_refresh",
            sport=sport,
            rows_loaded=_sport_rows_loaded(sport_result),
            refresh_steps=_object_summary(sport_result["refresh_steps"], name="refresh_steps"),
            generation_steps=_object_summary(sport_result["generation"]["steps"], name="generation_steps"),
            same_object=bool(sport_result["refresh_steps"] is sport_result["generation"]["steps"]),
            before=sport_start_memory,
            after=_phase_memory_snapshot(),
        )
        return _finalize_sport_result(sport_result)

    if execution_mode == "source" and spec.slug in {"mlb", "nba", "wnba", "nhl", "nfl", "ncaab", "ncaaf"} and sport_result["ok"]:
        tracking_result = _sync_post_refresh_tracking_step(
            sport=spec.slug,
            source_root=_post_refresh_root(spec),
            date_str=args.date,
            dry_run=bool(args.dry_run),
        )
        sport_result["post_refresh"] = tracking_result
        sport_result["generation"]["post_refresh"] = tracking_result
        _log_memory("sport_post_refresh", sport=sport, tracking=_object_summary(tracking_result, name="post_refresh"))
        if not tracking_result["ok"]:
            sport_result["ok"] = False
            if not args.continue_on_error:
                _log_memory(
                    f"{sport}_refresh",
                    sport=sport,
                    rows_loaded=_sport_rows_loaded(sport_result),
                    refresh_steps=_object_summary(sport_result["refresh_steps"], name="refresh_steps"),
                    generation_steps=_object_summary(sport_result["generation"]["steps"], name="generation_steps"),
                    same_object=bool(sport_result["refresh_steps"] is sport_result["generation"]["steps"]),
                    failed_stage="post_refresh",
                    before=sport_start_memory,
                    after=_phase_memory_snapshot(),
                )
                return _finalize_sport_result(sport_result)

    if not args.skip_mirror and (execution_mode == "ingest" or sport_result["ok"]):
        if _hosted_source_mode_writes_directly(spec=spec, execution_mode=execution_mode, mirror_only=execution_mode == "ingest"):
            timestamp = _utc_now()
            mirror_result = {
                "name": spec.mirror_script_name.replace(".ps1", ""),
                "description": "Skipped mirror script because source mode already writes directly into SYNDICATE_DATA_ROOT.",
                "cwd": str(REPO_ROOT),
                "command": [],
                "return_code": 0,
                "started_at": timestamp,
                "finished_at": timestamp,
                "stdout": "",
                "stderr": "",
                "ok": True,
                "dry_run": bool(args.dry_run),
                "skipped": True,
            }
        else:
            mirror_result = _run_command(
                _mirror_command(
                    spec.mirror_script_name,
                    date=args.date,
                    sport=spec.slug,
                    mirror_only=execution_mode == "ingest",
                ),
                dry_run=bool(args.dry_run),
            )
        sport_result["mirror"] = mirror_result
        if isinstance(sport_result.get("ingestion"), dict):
            sport_result["ingestion"]["step"] = mirror_result
        _log_memory("sport_mirror", sport=sport, mirror=_object_summary(mirror_result, name="mirror"))
        _compact_step_result(mirror_result)
        if not mirror_result["ok"]:
            sport_result["ok"] = False
            if not args.continue_on_error:
                _log_memory(
                    f"{sport}_refresh",
                    sport=sport,
                    rows_loaded=_sport_rows_loaded(sport_result),
                    refresh_steps=_object_summary(sport_result["refresh_steps"], name="refresh_steps"),
                    generation_steps=_object_summary(sport_result["generation"]["steps"], name="generation_steps"),
                    same_object=bool(sport_result["refresh_steps"] is sport_result["generation"]["steps"]),
                    failed_stage="mirror",
                    before=sport_start_memory,
                    after=_phase_memory_snapshot(),
                )
                return _finalize_sport_result(sport_result)

    published_manifest = _publish_sport_manifest_threadsafe(
        sport=spec.slug,
        artifact_paths=_sport_artifact_paths(sport_result),
        metadata=_sport_control_plane_metadata(
            sport_result,
            date=args.date,
            phase=args.phase,
            execution_mode=execution_mode,
            refresh_mode=refresh_mode,
        ),
    )
    sport_result["sport_manifest"] = published_manifest
    _log_memory("sport_end", sport=sport, result=_object_summary(sport_result, name="sport_result"))
    _log_memory(
        f"{sport}_refresh",
        sport=sport,
        rows_loaded=_sport_rows_loaded(sport_result),
        refresh_steps=_object_summary(sport_result["refresh_steps"], name="refresh_steps"),
        generation_steps=_object_summary(sport_result["generation"]["steps"], name="generation_steps"),
        same_object=bool(sport_result["refresh_steps"] is sport_result["generation"]["steps"]),
        artifact_paths_len=len(_sport_artifact_paths(sport_result)),
        before=sport_start_memory,
        after=_phase_memory_snapshot(),
    )
    _finalize_sport_result(sport_result)
    del published_manifest
    return sport_result


def _build_summary(args: argparse.Namespace) -> dict[str, Any]:
    selected = _parse_sports(args.sports)
    execution_mode = _resolve_execution_mode(getattr(args, "execution_mode", None), mirror_only=bool(args.mirror_only))
    summary_start_memory = _phase_memory_snapshot()
    summary: dict[str, Any] = {
        "date": args.date,
        "phase": args.phase,
        "sports": selected,
        "skip_mirror": bool(args.skip_mirror),
        "mirror_only": execution_mode == "ingest",
        "execution_mode": execution_mode,
        "dry_run": bool(args.dry_run),
        "results": [],
        "started_at": _utc_now(),
    }
    _log_memory(
        "summary_start",
        sports=selected,
        execution_mode=execution_mode,
        summary=_object_summary(summary, name="summary"),
        results=_object_summary(summary["results"], name="results"),
        rows_loaded=0,
        before=summary_start_memory,
        after=summary_start_memory,
    )

    any_failure = False
    serial_sport_refresh_raw = os.environ.get("SYNDICATE_SERIAL_SPORT_REFRESH")
    serial_sport_refresh_enabled = _serial_sport_refresh_enabled()
    max_workers = 1 if serial_sport_refresh_enabled else min(len(selected), 4)
    print(
        "[refresh_odds_sources] serial_gate "
        f"raw={serial_sport_refresh_raw!r} "
        f"enabled={serial_sport_refresh_enabled} "
        f"selected={selected} "
        f"max_workers={max_workers}",
        flush=True,
    )
    if max_workers <= 1:
        for sport in selected:
            log_all_process_memory("before_sport_launch", sport=sport, execution_mode=execution_mode, concurrency="sequential")
            log_runtime_memory("before_sport_launch", sport=sport, execution_mode=execution_mode, concurrency="sequential")
            sport_result = _run_sport_refresh(args, sport, execution_mode)
            log_all_process_memory(
                "after_sport_launch",
                sport=sport,
                execution_mode=execution_mode,
                concurrency="sequential",
                ok=bool(sport_result.get("ok")) if isinstance(sport_result, dict) else None,
            )
            log_runtime_memory(
                "after_sport_launch",
                sport=sport,
                execution_mode=execution_mode,
                concurrency="sequential",
                ok=bool(sport_result.get("ok")) if isinstance(sport_result, dict) else None,
            )
            if not sport_result.get("ok"):
                any_failure = True
            summary["results"].append(sport_result)
            _log_memory("summary_append_sequential", sport=sport, results_len=len(summary["results"]), result=_object_summary(sport_result, name="sport_result"))
            sport_ok = bool(sport_result.get("ok"))
            del sport_result
            gc.collect()
            if not args.continue_on_error and not sport_ok:
                summary["finished_at"] = _utc_now()
                summary["ok"] = False
                return summary
    else:
        results_by_sport: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for sport in selected:
                log_all_process_memory("before_sport_launch", sport=sport, execution_mode=execution_mode, concurrency="parallel")
                log_runtime_memory("before_sport_launch", sport=sport, execution_mode=execution_mode, concurrency="parallel")
                futures[executor.submit(_run_sport_refresh, args, sport, execution_mode)] = sport
            for future in as_completed(futures):
                sport = futures[future]
                try:
                    sport_result = future.result()
                except Exception as exc:
                    sport_result = {
                        "sport": sport,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                results_by_sport[sport] = sport_result
                log_all_process_memory(
                    "after_sport_launch",
                    sport=sport,
                    execution_mode=execution_mode,
                    concurrency="parallel",
                    ok=bool(sport_result.get("ok")) if isinstance(sport_result, dict) else None,
                )
                log_runtime_memory(
                    "after_sport_launch",
                    sport=sport,
                    execution_mode=execution_mode,
                    concurrency="parallel",
                    ok=bool(sport_result.get("ok")) if isinstance(sport_result, dict) else None,
                )
                if not sport_result.get("ok"):
                    any_failure = True
                _log_memory(
                    "summary_future_complete",
                    sport=sport,
                    results_by_sport_len=len(results_by_sport),
                    result=_object_summary(sport_result, name="sport_result"),
                    rows_loaded=_sport_rows_loaded(sport_result) if isinstance(sport_result, dict) else None,
                )
                sport_ok = bool(sport_result.get("ok"))
                del sport_result
                gc.collect()
                if not args.continue_on_error and not sport_ok:
                    break

        for sport in selected:
            sport_result = results_by_sport.get(sport)
            if sport_result is None:
                sport_result = {"sport": sport, "ok": False, "error": "Refresh did not complete."}
                any_failure = True
            summary["results"].append(sport_result)
            _log_memory(
                "summary_append_parallel",
                sport=sport,
                results_len=len(summary["results"]),
                result=_object_summary(sport_result, name="sport_result"),
                rows_loaded=_sport_rows_loaded(sport_result) if isinstance(sport_result, dict) else None,
            )
            sport_ok = bool(sport_result.get("ok"))
            del sport_result
            gc.collect()
            if not args.continue_on_error and not sport_ok:
                summary["finished_at"] = _utc_now()
                summary["ok"] = False
                _log_memory(
                    "summary_end",
                    summary=_object_summary(summary, name="summary"),
                    results=_object_summary(summary["results"], name="results"),
                    results_by_sport=_object_summary(results_by_sport, name="results_by_sport"),
                    rows_loaded=sum((_sport_rows_loaded(item) or 0) for item in summary["results"] if isinstance(item, dict)),
                    before=summary_start_memory,
                    after=_phase_memory_snapshot(),
                )
                return summary

        results_by_sport.clear()
        del results_by_sport
        gc.collect()

    summary["finished_at"] = _utc_now()
    summary["ok"] = not any_failure
    summary_rows_loaded = sum((_sport_rows_loaded(item) or 0) for item in summary.get("results", []) if isinstance(item, dict))
    _log_memory(
        "summary_before_parity",
        summary=_object_summary(summary, name="summary"),
        results=_object_summary(summary.get("results", []), name="results"),
        rows_loaded=summary_rows_loaded,
        before=summary_start_memory,
        after=_phase_memory_snapshot(),
    )
    publish_parity_paths: list[str] = []
    for sport_result in summary.get("results", []) if isinstance(summary.get("results"), list) else []:
        if not isinstance(sport_result, dict):
            continue
        publish_parity_paths.extend(_sport_artifact_paths(sport_result))
    summary["publish_parity"] = build_publish_parity_summary(
        date=summary.get("date"),
        forced_paths=publish_parity_paths,
        intelligence_paths=[],
    )
    summary["coverage_audit"] = _build_odds_coverage_audit(requested_date=str(summary.get("date") or "").strip())
    _log_memory(
        "summary_end",
        summary=_object_summary(summary, name="summary"),
        results=_object_summary(summary.get("results", []), name="results"),
        publish_parity_paths_count=len(publish_parity_paths),
        rows_loaded=summary_rows_loaded,
        before=summary_start_memory,
        after=_phase_memory_snapshot(),
    )
    return summary


def main() -> int:
    child_pid = os.getpid()
    startup_memory = _phase_memory_snapshot()

    def _emit_child_exit() -> None:
        _stop_all_process_memory_heartbeat()
        print(f"CHILD_PROCESS_EXIT ts={_utc_now()} pid={child_pid} ppid={os.getppid()}", file=sys.stderr, flush=True)
        _dump_main_thread_stack(label="child_exit")
        _dump_child_runtime_state(label="atexit")

    def _emit_exit_memory() -> None:
        _stop_all_process_memory_heartbeat()
        log_all_process_memory("before_exit", script="refresh_odds_sources", pid=child_pid)
        log_runtime_memory("before_exit", script="refresh_odds_sources", pid=child_pid)

    atexit.register(_emit_child_exit)
    atexit.register(_emit_exit_memory)

    _log_shutdown_snapshot(stage="main_start")

    parser = argparse.ArgumentParser(
        description="Refresh pregame/live odds in the source sport repos, then optionally mirror the refreshed artifacts into Syndicate.",
    )
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="Target date (YYYY-MM-DD) for date-based sports.")
    parser.add_argument("--sports", default="all", help="Comma-separated sport slugs or 'all'.")
    parser.add_argument("--phase", choices=("pregame", "live", "all"), default="all")
    parser.add_argument("--mode", choices=("fast", "full"), default="full", help="Fast mode skips expensive rebuild steps; full preserves existing behavior.")
    parser.add_argument("--regions", default="us", help="Odds regions forwarded to source refresh commands where supported.")
    parser.add_argument("--bookmakers", default="", help="Optional bookmaker filter forwarded to source refresh commands where supported.")
    parser.add_argument("--markets", default="", help="Optional market filter forwarded to source refresh commands where supported.")
    parser.add_argument("--season", type=int, default=None, help="Optional season override for weekly sports like NFL.")
    parser.add_argument("--week", type=int, default=None, help="Optional week override for weekly sports like NFL/NCAAF.")
    parser.add_argument("--skip-mirror", action="store_true", help="Refresh source repos only; do not run the Syndicate mirror scripts.")
    parser.add_argument("--execution-mode", choices=("source", "ingest"), default="source", help="Choose whether to run source-owned refresh generation or ingest-only mirror/import steps.")
    parser.add_argument("--mirror-only", action="store_true", help="Skip source refresh and only run the Syndicate mirror scripts.")
    parser.add_argument("--continue-on-error", action="store_true", default=True, help="Continue across sports even when one refresh fails.")
    parser.add_argument("--no-continue-on-error", action="store_false", dest="continue_on_error")
    parser.add_argument("--dry-run", action="store_true", help="Resolve commands and source roots without executing refresh or mirror steps.")
    parser.add_argument("--audit-coverage", action="store_true", help="Print a cross-sport odds coverage audit without running refresh commands.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    parser.add_argument("--list", action="store_true", help="List supported sports and exit.")
    args = parser.parse_args()

    if args.list:
        payload = {
            "sports": [
                {
                    "sport": spec.slug,
                    "source_repo": spec.source_repo_name,
                    "source_root_env_var": _source_root_env_var(spec.slug),
                    "mirror_script": spec.mirror_script_name,
                    "notes": spec.notes,
                }
                for spec in REGISTRY.values()
            ]
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.audit_coverage:
        payload = {
            "ok": True,
            "date": args.date,
            "coverage_audit": _build_odds_coverage_audit(requested_date=args.date),
        }
        print(json.dumps(payload, indent=2))
        return 0

    try:
        _log_memory("startup", child_pid=child_pid, argv=list(sys.argv), before=startup_memory, after=_phase_memory_snapshot())
        log_all_process_memory("startup", script="refresh_odds_sources", pid=child_pid, argv=list(sys.argv))
        log_runtime_memory("startup", script="refresh_odds_sources", pid=child_pid, argv=list(sys.argv))
        _start_all_process_memory_heartbeat(label="refresh_odds_sources")
        _log_shutdown_snapshot(stage="before_build_summary")
        summary = _build_summary(args)
        _log_shutdown_snapshot(stage="after_build_summary")
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(f"CHILD_PROCESS_STARTED argv={json.dumps(sys.argv)} cwd={os.getcwd()} pid={os.getpid()}", file=sys.stderr, flush=True)
        _dump_child_runtime_state(label="json_exception_before_write")
        _dump_main_thread_stack(label="json_exception_before_write")
        print("CHILD_JSON_WRITE_BEGIN", file=sys.stderr, flush=True)
        print(json.dumps(payload, indent=2))
        print(f"CHILD_JSON_WRITE_END ts={_utc_now()} pid={os.getpid()} ppid={os.getppid()}", file=sys.stderr, flush=True)
        _dump_child_runtime_state(label="json_exception_after_write")
        _dump_main_thread_stack(label="json_exception_after_write")
        _start_json_watchdog(label="json_exception_after_write")
        return 1

    summary["odds_control_plane"] = write_odds_control_plane_snapshot(summary)
    _log_memory(
        "artifact_write",
        summary=_object_summary(summary, name="summary"),
        rows_loaded=sum((_sport_rows_loaded(item) or 0) for item in summary.get("results", []) if isinstance(item, dict)),
        before=_phase_memory_snapshot(),
        after=_phase_memory_snapshot(),
    )

    print(f"CHILD_PROCESS_STARTED argv={json.dumps(sys.argv)} cwd={os.getcwd()} pid={os.getpid()}", file=sys.stderr, flush=True)
    if args.json:
        _dump_child_runtime_state(label="json_before_write")
        _dump_main_thread_stack(label="json_before_write")
        _log_shutdown_snapshot(stage="before_final_json_write")
        print("CHILD_JSON_WRITE_BEGIN", file=sys.stderr, flush=True)
        print(json.dumps(summary, indent=2))
        print(f"CHILD_JSON_WRITE_END ts={_utc_now()} pid={os.getpid()} ppid={os.getppid()}", file=sys.stderr, flush=True)
        print(f"CHILD_JSON_RETURN ts={_utc_now()} pid={os.getpid()} ppid={os.getppid()}", file=sys.stderr, flush=True)
        _dump_child_runtime_state(label="json_after_write")
        _dump_main_thread_stack(label="json_after_write")
        _start_json_watchdog(label="json_after_write")
        _log_shutdown_snapshot(stage="after_final_json_write")
    else:
        _dump_child_runtime_state(label="non_json_before_write")
        _dump_main_thread_stack(label="non_json_before_write")
        for sport_result in summary.get("results", []):
            sport = sport_result["sport"]
            status = "ok" if sport_result.get("ok") else "failed"
            print(f"[{sport}] {status}")
            if sport_result.get("error"):
                print(f"  - error: {sport_result['error']}")
            for step_result in sport_result.get("refresh_steps", []):
                marker = "dry-run" if step_result.get("dry_run") else ("ok" if step_result.get("ok") else "failed")
                print(f"  - refresh {step_result['name']}: {marker}")
            post_refresh = sport_result.get("post_refresh")
            if isinstance(post_refresh, dict):
                marker = "dry-run" if post_refresh.get("dry_run") else ("ok" if post_refresh.get("ok") else "failed")
                print(f"  - post-refresh {post_refresh['name']}: {marker}")
            mirror = sport_result.get("mirror")
            if isinstance(mirror, dict):
                marker = "dry-run" if mirror.get("dry_run") else ("ok" if mirror.get("ok") else "failed")
                print(f"  - mirror: {marker}")

        _dump_child_runtime_state(label="non_json_after_write")
        _dump_main_thread_stack(label="non_json_after_write")
        _log_shutdown_snapshot(stage="after_final_non_json_write")

    _log_memory("finalization", child_pid=child_pid, before=_phase_memory_snapshot(), after=_phase_memory_snapshot())
    print(f"MAIN_RETURN ts={_utc_now()} pid={os.getpid()} ppid={os.getppid()}", file=sys.stderr, flush=True)
    _dump_main_thread_stack(label="main_return")
    _log_shutdown_snapshot(stage="before_process_exit")
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())