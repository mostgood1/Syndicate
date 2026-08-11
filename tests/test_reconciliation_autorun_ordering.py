"""`#341` — the settlement autorun was enabled, correct, and structurally mute.

`_launch_autorun_reconciliation` sat 6th in an exclusive if/elif chain behind
mlb_refresh, weekly_sports and soccer_weekly. Every branch is `elif`, so it only
ran on a tick where all three declined -- and during a slate mlb_refresh keeps
winning. Production evidence: RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN=true
with interval 86400, and `chunk_diagnostics` exists=false for 2026-07-17..08-04,
true for 08-05. /api/portfolio/summary read settled_count 0, avg_clv null.
"""

from __future__ import annotations

import pathlib
import re

SRC = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")


def _autorun_order() -> list[str]:
    return re.findall(r"elif (_launch_autorun_\w+)\(", SRC)


def test_reconciliation_runs_before_the_high_frequency_refresh_autoruns():
    order = _autorun_order()
    assert "_launch_autorun_reconciliation" in order
    rec = order.index("_launch_autorun_reconciliation")
    for later in ("_launch_autorun_mlb_refresh",
                  "_launch_autorun_weekly_sports_refresh",
                  "_launch_autorun_soccer_weekly_refresh"):
        assert rec < order.index(later), (
            f"{later} precedes reconciliation; an elif chain means reconciliation "
            "only runs on a tick where it declines, which is how #341 stayed mute"
        )


def test_the_gate_says_why_it_declined():
    # A conjunction silent about which term denied it is how this hid for weeks:
    # an enabled job that declines every tick and an enabled job that never gets
    # a tick look identical from outside.
    assert "RECONCILIATION_AUTORUN_GATED" in SRC
    assert "RECONCILIATION_AUTORUN_RUNNING" in SRC
    # print, not logger.info -- logger.info does not reach Render's collector.
    assert re.search(r"RECONCILIATION_AUTORUN_GATED[\s\S]{0,400}?flush=True", SRC)


def test_a_failed_run_does_not_consume_the_whole_day():
    # The status epoch is written on the error path too, so a single transient
    # failure blocked every retry for 24h and produced nothing.
    assert re.search(r'last_status.*?\.get\("error"\)', SRC)
    assert "min(interval, 3600.0)" in SRC
