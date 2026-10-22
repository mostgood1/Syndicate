"""The min_ev tuner's daily readout as a dated artifact -- the fleet job `min-ev-tuner-readout`.

    python scripts/min_ev_tuner_daily_readout.py            # with refresh-worker's state env (the supervisor job)

WHY. The readouts that precede the user's apply decision were taken by a Claude
scheduled task whose timer never fired on this host (0 automatic runs on 10-20,
10-21 and 10-22), then by a session-only cron that dies with its session. The
supervisor's scheduled jobs run with no session at all, so the readout is one.

WHAT. Runs `min_ev_tuner_readout.py state` in-process (same text a human gets)
and writes it, with the state's structured summary, to
`<reports root>/intelligence/min_ev_tuner_readout/<UTC date>.json` as a PLAIN
file (never the keyvalue store), so the watchdog and a person can read it from
the disk. Runs at 13:15Z, after the worker's 12:00Z pass.

EXIT. 0 when the state was read and its `last_run_date` is today; 2 when the
state is absent or stale (the artifact is still written, saying so). The
supervisor records the rc, and the watchdog's `job:min-ev-tuner-readout` check
warns on a non-zero one.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

READOUT_SUBDIR = ("intelligence", "min_ev_tuner_readout")


def readout_dir(reports_root: Path) -> Path:
    return reports_root.joinpath(*READOUT_SUBDIR)


def summarize(state: Mapping[str, Any], today: str) -> dict[str, Any]:
    """The structured fields of one readout (pure)."""
    audit = list(state.get("audit") or [])
    moves_today = [m for m in audit if str((m or {}).get("at") or "").startswith(today)]
    return {
        "state_present": bool(state),
        "mode": state.get("mode"),
        "last_run_date": state.get("last_run_date"),
        "last_run_at": state.get("last_run_at"),
        "state_is_today": state.get("last_run_date") == today,
        "base_min_ev_pct": state.get("base_min_ev_pct"),
        "actions": state.get("actions"),
        "skipped": state.get("skipped"),
        "pooling": state.get("pooling"),
        "pooled_actions": state.get("pooled_actions"),
        "cells": len(state.get("cells") or {}),
        "audit_moves_total": len(audit),
        "moves_today": moves_today,
    }


def write_readout(directory: Path, payload: Mapping[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['date']}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=25, help="cells / audit moves in the text readout")
    parser.add_argument("--reports-root", help="default: refresh_state_store.reports_root()")
    args = parser.parse_args(argv)

    from scripts import min_ev_tuner_readout as readout
    from syndicate.features.shared import min_ev_tuner as T
    from syndicate.features.shared.refresh_state_store import reports_root

    now = dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            readout_rc = int(readout.main(["state", "--limit", str(args.limit)]) or 0)
        except Exception as exc:  # noqa: BLE001 -- the artifact must still say what happened
            print(f"READOUT_FAILED {type(exc).__name__}: {exc}")
            readout_rc = 3
    try:
        state = T.load_state()
    except Exception:  # noqa: BLE001
        state = {}
    payload = {
        "date": today,
        "written_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "readout_rc": readout_rc,
        **summarize(state, today),
        "text": buffer.getvalue(),
    }
    root = Path(args.reports_root) if args.reports_root else reports_root()
    path = write_readout(readout_dir(root), payload)
    print(buffer.getvalue(), end="")
    print(
        f"MIN_EV_TUNER_READOUT date={today} mode={payload['mode']} last_run_date={payload['last_run_date']} "
        f"state_is_today={payload['state_is_today']} moves_today={len(payload['moves_today'])} wrote={path}",
        flush=True,
    )
    return 0 if payload["state_is_today"] and readout_rc == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
