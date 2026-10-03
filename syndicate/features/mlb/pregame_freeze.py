"""Freeze each MLB per-game sim at first pitch, so the engine can be measured AS-OF.

WHY. `daily/sims/<date>/sim_*.json` is rewritten in place once a game starts:
the vendored daily sim's started-game repair re-simulates it
(`vendor/mlb_bettingv2/tools/daily_update.py`, `started_game_repairs`) and
`daily_summary_<date>.json` follows. Measured 2026-09-14: 326 of 326 scored games
were post-start re-sims. The pregame projection the board priced from was kept
nowhere, so no engine change since 09-01 could be backtested as-of (lane
`mlb-lines-props-backtest`, findings 2026-10-02, ranked plan step 1).

WHAT. Copy every sim whose OWN recorded status at sim time
(`schedule.status.detailed`) is Scheduled / Pre-Game / Warmup into
`daily/sims_pregame/<date>/sim_pk<gamePk>_g<n>.json`. The key is the gamePk and
game number, not the vendor filename, whose leading slate index can shift
between runs. The latest pregame copy wins (by the source file's mtime). A
post-start sim is NEVER copied, so it can never replace a frozen one.

The wrapper calls this BEFORE each run (to catch the previous run's pregame
files before this run can overwrite them) and AFTER it. Everything stays
outside `vendor/`, so a vendor re-pull cannot revert it. Each frozen copy carries
a `_freeze` block naming its source, the source mtime and the status at sim time.
A backtest can then compare the freeze time to first pitch itself.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PREGAME_STATUSES = frozenset({"Scheduled", "Pre-Game", "Warmup"})
FROZEN_DIRNAME = "sims_pregame"


def frozen_dir(data_dir: Path | str, date_str: str) -> Path:
    return Path(data_dir) / "daily" / FROZEN_DIRNAME / str(date_str)


def _status(record: dict[str, Any]) -> str | None:
    return (((record.get("schedule") or {}).get("status") or {}).get("detailed")) or None


def frozen_name(record: dict[str, Any]) -> str | None:
    try:
        pk = int(record.get("game_pk"))
    except (TypeError, ValueError):
        return None
    try:
        gn = int((record.get("schedule") or {}).get("game_number") or 1)
    except (TypeError, ValueError):
        gn = 1
    return f"sim_pk{pk}_g{gn}.json"


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def freeze_pregame_sims(data_dir: Path | str, date_str: str) -> dict[str, int]:
    """Freeze this date's pregame sims. Returns counters; never raises on a bad file."""
    src = Path(data_dir) / "daily" / "sims" / str(date_str)
    dst = frozen_dir(data_dir, date_str)
    counts = {"seen": 0, "frozen_new": 0, "frozen_updated": 0, "unchanged": 0,
              "not_pregame": 0, "unreadable": 0}
    if not src.is_dir():
        return counts
    for path in sorted(src.glob("sim_*.json")):
        counts["seen"] += 1
        try:
            mtime = path.stat().st_mtime
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            counts["unreadable"] += 1
            continue
        if not isinstance(record, dict):
            counts["unreadable"] += 1
            continue
        status = _status(record)
        name = frozen_name(record)
        if status not in PREGAME_STATUSES or name is None:
            counts["not_pregame"] += 1
            continue
        target = dst / name
        existed = target.exists()
        if existed:
            try:
                prior = json.loads(target.read_text(encoding="utf-8"))
                prior_mtime = float(((prior.get("_freeze") or {}).get("source_mtime")) or 0.0)
            except (OSError, ValueError, TypeError, AttributeError):
                prior_mtime = 0.0
            if prior_mtime >= mtime:
                counts["unchanged"] += 1
                continue
        record["_freeze"] = {
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "source_file": path.name,
            "source_mtime": mtime,
            "source_mtime_utc": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
            "status_at_sim": status,
        }
        _write_atomic(target, record)
        counts["frozen_updated" if existed else "frozen_new"] += 1
    return counts


def log_line(phase: str, date_str: str, counts: dict[str, int]) -> str:
    body = " ".join(f"{k}={v}" for k, v in counts.items())
    return f"MLB_PREGAME_FREEZE phase={phase} date={date_str} {body}"
