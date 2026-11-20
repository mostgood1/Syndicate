"""Portfolio Watch runner (Windows task `SyndicatePortfolioWatch`): probe -> page data -> history -> dashboard -> prune.

No Claude involved, so it spends no credits. Every step is read-only against the fleet (loopback GETs and web-log
greps through the probe). Output: dashboard.html published by build_dashboard.py (see paths.py). Log: paths.LOG.
"""
from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import sys
import time
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import paths  # noqa: E402
HERE = _Path(__file__).resolve().parent
PROBE = paths.PROBE
LOG = paths.LOG
KEEP_READING_DIRS_H = paths.KEEP_READING_DIRS_H


def log(msg: str) -> None:
    line = f"{dt.datetime.now().strftime('%m-%d %H:%M:%S')} {msg}"
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(name: str, args: list[str], timeout: int) -> bool:
    t0 = time.time()
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        log(f"{name}: TIMEOUT after {timeout} s")
        return False
    tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
    log(f"{name}: rc {p.returncode} in {time.time() - t0:.1f} s {tail[0][:160]}"
        + (f" | stderr {(p.stderr or '').strip()[-200:]}" if p.returncode else ""))
    return p.returncode == 0


def prune() -> None:
    cutoff = time.time() - KEEP_READING_DIRS_H * 3600
    gone = 0
    for d in paths.READINGS.glob("2026*"):
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
    if gone:
        log(f"prune: removed {gone} reading folders older than {KEEP_READING_DIRS_H} h")


def main() -> int:
    py = sys.executable
    ok = run("probe", [py, str(PROBE), "--log-minutes", "30", "--out-dir", str(paths.READINGS)], 600)
    run("page data", [py, str(HERE / "build_page_data.py")], 180)
    run("history", [py, str(HERE / "build_history.py")], 300)  # durable daily rollup from the ledger (never pruned)
    run("dashboard", [py, str(HERE / "build_dashboard.py")], 180)
    prune()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
