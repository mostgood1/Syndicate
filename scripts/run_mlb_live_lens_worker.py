from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.mlb.live_lens import LIVE_LENS_SNAPSHOT_PATH
from syndicate.features.mlb.live_lens import build_live_lens_snapshot_internal
from syndicate.features.mlb.live_lens import validate_live_lens_snapshot
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.timezone import central_today_iso

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
_PROCESS_LOCK_HANDLE = None
_STOP_REQUESTED = False

try:
    import fcntl  # type: ignore
except Exception:
    fcntl = None

try:
    import msvcrt  # type: ignore
except Exception:
    msvcrt = None


def _interval_seconds() -> int:
    raw = str(os.environ.get("MLB_LIVE_LENS_LOOP_INTERVAL_SECONDS") or "30").strip()
    try:
        value = int(raw)
    except Exception:
        value = 30
    return max(5, value)


def _lock_path() -> Path:
    return REPO_ROOT / "reports" / "mlb_live_lens" / "mlb_live_lens_worker.lock"


def _release_lock() -> None:
    global _PROCESS_LOCK_HANDLE
    handle = _PROCESS_LOCK_HANDLE
    if handle is None:
        return
    _PROCESS_LOCK_HANDLE = None
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass
    try:
        handle.close()
    except Exception:
        pass


def _acquire_lock() -> bool:
    global _PROCESS_LOCK_HANDLE
    if _PROCESS_LOCK_HANDLE is not None:
        return True
    lock_path = _lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = open(lock_path, "a+", encoding="utf-8")
    except Exception:
        return False
    try:
        handle.seek(0)
        handle.write(f"pid={os.getpid()}\n")
        handle.truncate()
        handle.flush()
    except Exception:
        pass
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        _PROCESS_LOCK_HANDLE = handle
        return True
    except Exception:
        try:
            handle.close()
        except Exception:
            pass
        return False


def _handle_stop(_signum: int, _frame: object) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


def _snapshot_path_text() -> str:
    return str(LIVE_LENS_SNAPSHOT_PATH).replace("\\", "/")


def _run_tick() -> dict[str, object]:
    snapshot = build_live_lens_snapshot_internal(central_today_iso())
    if not validate_live_lens_snapshot(snapshot):
        logger.warning("INVALID MLB LIVE LENS STATE", extra={"path": _snapshot_path_text(), "date": snapshot.get("date") if isinstance(snapshot, dict) else None})
        return snapshot
    write_json_file(LIVE_LENS_SNAPSHOT_PATH, snapshot)
    logger.info(
        "MLB LIVE LENS UPDATED",
        extra={
            "path": _snapshot_path_text(),
            "date": snapshot.get("date"),
            "games": len(snapshot.get("games") or []),
        },
    )
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the MLB live-lens snapshot on a fixed interval.")
    parser.add_argument("--poll-seconds", type=float, default=float(_interval_seconds()))
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()

    try:
        signal.signal(signal.SIGTERM, _handle_stop)
        signal.signal(signal.SIGINT, _handle_stop)
    except Exception:
        pass

    if not _acquire_lock():
        logger.info("MLB LIVE LENS UPDATED", extra={"status": "skipped", "reason": "lock_unavailable", "path": _snapshot_path_text()})
        return 0

    try:
        poll_seconds = max(5.0, float(args.poll_seconds))
    except Exception:
        poll_seconds = 30.0

    while not _STOP_REQUESTED:
        try:
            _run_tick()
        except Exception as exc:
            logger.exception("MLB live-lens worker tick failed: %s", exc)
        if args.run_once:
            break
        time.sleep(poll_seconds)
    _release_lock()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())