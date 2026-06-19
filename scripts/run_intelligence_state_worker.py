from __future__ import annotations

import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.intelligence_state import get_intelligence_state_response as compute_intelligence_state_response
from pipeline.intelligence_state import write_latest_intelligence_state


def _contains_nan(value: Any) -> bool:
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, dict):
        return any(_contains_nan(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_nan(item) for item in value)
    return False


def _is_valid_intelligence_state(state: Any) -> bool:
    if not isinstance(state, dict):
        return False
    if "top_opportunities" not in state:
        return False
    return not _contains_nan(state)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    while True:
        state = None
        try:
            print(f"{_timestamp()} INTELLIGENCE WORKER RUN")
            state = compute_intelligence_state_response(
                {
                    "question": "top edges today",
                    "mode": "recommendation",
                    "timing": "all",
                    "sport": "all",
                }
            )
            if _is_valid_intelligence_state(state):
                write_latest_intelligence_state(state)
                candidate_count = state.get("candidate_count", 0)
                print(f"{_timestamp()} INTELLIGENCE STATE WRITTEN: {candidate_count}")
            else:
                print("INVALID INTELLIGENCE STATE")
        except Exception as exc:
            print(f"INTELLIGENCE STATE ERROR: {exc}")
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
