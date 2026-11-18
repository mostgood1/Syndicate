"""COMPATIBILITY SHIM: this tool is `scripts/fleet_logs.py` now.

Renamed 2026-11-17 (lane render-name-cleanup, todo #766 follow-up). It has read only the
fleet's own role logs since 2026-11-15; the Render name was all that was left. About fifty
ledger entries, scheduled tasks and session notes run it by this name, so the name stays:

    py -3 scripts/render_logs.py ...     # same arguments, same output as fleet_logs.py
    import render_logs                   # IS the fleet_logs module (same object)

New code and docs use `scripts/fleet_logs.py`.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fleet_logs as _fleet_logs  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_fleet_logs.main())

# `import render_logs` returns the fleet_logs module itself, private names included
# (callers and tests read `fetch_window`, `fetch_local_window`, `LAST_FETCH`, `_PREFIX`).
sys.modules[__name__] = _fleet_logs
