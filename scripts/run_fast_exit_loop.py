"""Run the stage 1 in-game fast exit loop (PAPER) as its own process.

Lane in-game-trading. The same `FastExitLoop` the worker thread would run, for
when wiring it into live-odds-worker is not wanted or not allowed. It needs the
worker's storage environment (SYNDICATE_REPORTS_ROOT /
SYNDICATE_REFRESH_STATE_BACKEND) to read the execution ledger and the slow
tick's exit document, and nothing else: no credential is read, and the module
it runs has no order path (`tests/test_execution_exits_fast.py` parses it).

    python scripts/run_fast_exit_loop.py --until 2026-10-21T07:00:00Z
    python scripts/run_fast_exit_loop.py --once

Exits by itself at --until (no persistence beyond the run).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one pass, print it, exit")
    ap.add_argument("--until", help="UTC stop time, ISO (required unless --once)")
    a = ap.parse_args()
    if not a.once and not a.until:
        ap.error("--until is required unless --once: this process must end by itself")
    if hasattr(os, "nice"):
        try:
            os.nice(19)  # the fleet shares the host
        except OSError:
            pass

    from syndicate.features.shared.execution_exits_fast import FastExitLoop, fast_loop_mode, fast_loop_seconds
    from syndicate.features.shared.timezone import central_today_iso

    if fast_loop_mode() != "paper":
        print("[execution_exits_fast] OFF: SYNDICATE_EXIT_FAST_LOOP turns it off", flush=True)
        return 2
    loop = FastExitLoop(today_fn=central_today_iso)
    if a.once:
        print(loop.step(), flush=True)
        return 0
    until = datetime.fromisoformat(a.until.replace("Z", "+00:00"))
    print(f"[execution_exits_fast] STARTED mode=paper interval_s={fast_loop_seconds():.0f} until={a.until}", flush=True)
    while datetime.now(timezone.utc) < until:
        try:
            loop.step()
        except Exception as exc:  # noqa: BLE001 -- a pass must never kill the loop
            print(f"[execution_exits_fast] PASS_FAILED {type(exc).__name__}: {exc}"[:400], flush=True)
            loop.state = None
        time.sleep(fast_loop_seconds())
    print("[execution_exits_fast] STOPPED at --until", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
