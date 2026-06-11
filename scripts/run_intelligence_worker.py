from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.app import create_app


def main() -> int:
    stop_requested = False

    def _stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    try:
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
    except Exception:
        pass

    create_app()

    while not stop_requested:
        time.sleep(30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())