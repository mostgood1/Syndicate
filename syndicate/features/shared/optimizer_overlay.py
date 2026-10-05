"""The daily optimizer's rank/stake factor, read at score time and at stake time.

Lane `daily-optimizer` phase 2 `[2026-10-05, USER DECISION: "yes fast-forward the fleet and wire
phase 2"]`. The `model-scorecard` cron publishes `daily_optimizer.OVERLAY_PATH`; this module turns it
into ONE multiplier per Layer 2 row, applied at exactly two places:

- `layer2_board._apply_skill_reliability` -- the row's SCORE (rank). `value_pct` and admission are
  untouched, so no line can be withheld by it.
- `portfolio_commit._sizing_skill_factor` -- the model edge the STAKE is sized from.

THE 2026-10-05 PRIME DIRECTIVE: "no market is withheld; accuracy ranks, it never hides". So the
factor is always in [FACTOR_FLOOR, 1.0]: it lowers rank and stake on validated evidence and never
raises either, never zeroes either, and never gates.

RAILS (the same ones `skill_overlay` has, for the same reasons):
- VALIDATED ONLY. `daily_optimizer.validate_overlay` re-checks source, expiry, entry count, each
  factor's bounds and each entry's sample floor; one bad entry rejects the whole file.
- EXPIRES. 72 h after the cron wrote it; a dead cron degrades to factor 1.0, never to a frozen table.
- KILL SWITCH. `SYNDICATE_OPTIMIZER_OVERLAY=off` returns 1.0 immediately.
- NEVER RAISES. Any error is logged once and reads as 1.0.

THE CELL is the scorecard's `sport|market|segment|phase`, built by `measured_bucket_skill.view_from_candidate`
-- the same view `bucket_factor` scores by, whose `view_from_record` twin built the cell at grading time.
The two factors in a cell combine as their product, floored at FACTOR_FLOOR.

ONE DISK. Production is the local fleet since 2026-09-30: the cron writes onto the data root that web
and refresh-worker read, so there is no pull path (contrast `skill_overlay._pull_in_background`).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from syndicate.features.shared import daily_optimizer as opt

ENV_SWITCH = "SYNDICATE_OPTIMIZER_OVERLAY"
CHECK_INTERVAL_SECONDS = 600.0
_OFF_VALUES = frozenset({"off", "0", "false", "no"})
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"checked_at": None, "table": None, "meta": {"reason": "not_checked"}, "logged": None}


def enabled() -> bool:
    return str(os.environ.get(ENV_SWITCH) or "").strip().lower() not in _OFF_VALUES


def _overlay_file() -> Path | None:
    try:
        from syndicate.features.shared.refresh_state_store import data_root

        return Path(data_root()) / opt.OVERLAY_PATH
    except Exception:
        return None


def _log(meta: Mapping[str, Any]) -> None:
    signature = (meta.get("reason"), meta.get("edge_shrink"), meta.get("stake_scale"), meta.get("generated_at"))
    if _STATE["logged"] == signature:
        return
    _STATE["logged"] = signature
    print("[optimizer_overlay] reason=%s edge_shrink=%s stake_scale=%s generated_at=%s expires_at=%s"
          % (meta.get("reason"), meta.get("edge_shrink"), meta.get("stake_scale"), meta.get("generated_at"),
             meta.get("expires_at")), flush=True)


def active_table(*, now: datetime | None = None, path: Path | None = None) -> dict[str, dict[str, float]] | None:
    """The validated table, or None (switch off, absent, expired, invalid). Cached CHECK_INTERVAL_SECONDS."""
    if not enabled():
        _STATE["meta"] = {"reason": "switch_off"}
        return None
    clock = time.monotonic()
    with _LOCK:
        checked = _STATE["checked_at"]
        # None, never 0.0: monotonic counts from boot (skill_overlay's 2026-09-28 lesson).
        if checked is not None and clock - float(checked) < CHECK_INTERVAL_SECONDS and path is None and now is None:
            return _STATE["table"]
        _STATE["checked_at"] = clock
        target = path or _overlay_file()
        table, meta = None, {"reason": "overlay_absent"}
        try:
            if target is not None and target.is_file():
                payload = json.loads(target.read_text(encoding="utf-8"))
                table, reason = opt.validate_overlay(payload, now=now)
                meta = {"reason": reason, "generated_at": payload.get("generated_at"),
                        "expires_at": payload.get("expires_at")}
                if table is not None:
                    meta.update(edge_shrink=len(table["edge_shrink"]), stake_scale=len(table["stake_scale"]))
        except Exception as exc:
            table, meta = None, {"reason": f"error:{type(exc).__name__}"}
        _STATE["table"], _STATE["meta"] = table, meta
        _log(meta)
        return table


def cell_of_row(row: Mapping[str, Any], *, now: Any = None) -> str:
    from syndicate.features.shared.measured_bucket_skill import bucket_prefix, view_from_candidate

    return bucket_prefix(view_from_candidate(row, now=now))


def factor_for_row(row: Any, *, now: datetime | None = None, path: Path | None = None) -> float:
    """The row's rank/stake multiplier in [FACTOR_FLOOR, 1.0]; 1.0 when nothing validated applies."""
    try:
        if not isinstance(row, Mapping):
            return 1.0
        table = active_table(now=now, path=path)
        if not table:
            return 1.0
        cell = cell_of_row(row, now=now)
        factor = float(table["edge_shrink"].get(cell, 1.0)) * float(table["stake_scale"].get(cell, 1.0))
        return max(opt.FACTOR_FLOOR, min(1.0, factor))
    except Exception as exc:
        meta = {"reason": f"error:{type(exc).__name__}"}
        _STATE["meta"] = meta
        _log(meta)
        return 1.0


def status() -> dict[str, Any]:
    return dict(_STATE["meta"])


def reset_cache() -> None:
    """Tests only."""
    _STATE.update({"checked_at": None, "table": None, "meta": {"reason": "not_checked"}, "logged": None})
