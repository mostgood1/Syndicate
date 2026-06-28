from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.live_refresh_loop import _live_refresh_loop_interval_seconds
from syndicate.features.shared.live_refresh_loop import _run_live_refresh_tick
from syndicate.features.shared.live_refresh_loop import _acquire_process_lock
from syndicate.features.shared.live_refresh_loop import _release_process_lock
from syndicate.features.shared.live_refresh_loop import _LIVE_REFRESH_LOOP_STOP


def _handle_stop(_signum: int, _frame: object) -> None:
    _LIVE_REFRESH_LOOP_STOP.set()


def _run_tick() -> None:
    try:
        meta = _run_live_refresh_tick()
        print(f"LIVE ODDS REFRESH TICK: {meta.get('ok', False)}")
    except Exception as exc:
        print(f"LIVE ODDS REFRESH ERROR: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Syndicate live odds refresh worker loop.")
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()

    try:
        signal.signal(signal.SIGTERM, _handle_stop)
        signal.signal(signal.SIGINT, _handle_stop)
    except Exception:
        pass

    if not _acquire_process_lock():
        print("LIVE ODDS REFRESH WORKER SKIPPED: lock_unavailable")
        return 0

    try:
        interval_seconds = max(5, int(_live_refresh_loop_interval_seconds()))
    except Exception:
        interval_seconds = 30

    if args.run_once:
        try:
            _run_tick()
            return 0
        finally:
            _release_process_lock()

    try:
        while not _LIVE_REFRESH_LOOP_STOP.is_set():
            _run_tick()
            time.sleep(interval_seconds)
    finally:
        _release_process_lock()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())