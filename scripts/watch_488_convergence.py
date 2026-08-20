"""Watch for refresh-worker's `boxscores_history` to converge past 2026-06-30.

`#488`. THE TRAP THIS AVOIDS: `/api/ops/artifacts/export` serves web's SINGLE
copy of this path, and BOTH workers publish to it -- last writer wins. So
reading the export and seeing a recent max-date proves nothing about
refresh-worker: it may simply be live-odds-worker's copy, which has been
healthy since `#469`. Reading it twice ~20 minutes apart is exactly how this
lane first mistook divergence for data loss (6,755 rows through 08-18, then
3,889 rows through 06-30).

So the export alone CANNOT answer "has refresh-worker converged". This pairs
it with the per-service Render log, which is unambiguous:

  * `PUBLISH_OK` from refresh-worker means it pushed its own copy.
  * Reading the export IMMEDIATELY after that publish, and before any
    live-odds-worker publish, samples refresh-worker's copy specifically.

CONVERGED means: refresh-worker published, and the copy web holds at that
moment has a max game date past 2026-06-30. Anything else is either
"not yet" or "we sampled the wrong worker's copy", and those are reported
differently rather than collapsed.

Exit codes: 0 converged | 1 not yet | 2 ambiguous (could not attribute)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_BASE = "https://syndicate-an21.onrender.com"
_STALE = "2026-06-30"
_PATH = "wnba_source/data/processed/boxscores_history.csv"


def _tok() -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("ADMIN_TOKEN"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found")


def _export(tok: str, **kw):
    url = _BASE + "/api/ops/artifacts/export?" + urllib.parse.urlencode({"admin_token": tok, **kw})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def _last_publish(service: str, since: str, until: str) -> str | None:
    """Timestamp of this service's most recent PUBLISH_OK for the artifact."""
    try:
        out = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "render_logs.py"),
             "--service", service, "--text", "boxscores_history.csv",
             "--start", since, "--end", until, "--tail", "20"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=180,
        ).stdout
    except Exception:
        return None
    stamps = [l.split()[0] for l in out.splitlines() if "PUBLISH_OK" in l and l.strip()[:4].isdigit()]
    return stamps[-1] if stamps else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-08-20T16:50:00Z", help="deploy time of the convergence commit")
    args = ap.parse_args()
    tok = _tok()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{now}] #488 convergence check")

    rw = _last_publish("refresh-worker", args.since, now)
    lo = _last_publish("live-odds-worker", args.since, now)
    print(f"  refresh-worker   last PUBLISH_OK since deploy: {rw or 'none'}")
    print(f"  live-odds-worker last PUBLISH_OK since deploy: {lo or 'none'}")

    d = _export(tok, path=_PATH)
    if not d.get("count"):
        print("  artifact absent from web")
        return 1
    txt = list(d["artifacts"].values())[0]
    lines = txt.splitlines()
    cols = lines[0].split(",")
    if "date" not in cols:
        print("  no date column")
        return 2
    di = cols.index("date")
    dates = sorted({l.split(",")[di][:10] for l in lines[1:] if len(l.split(",")) > di})
    maxd, rows = (dates[-1] if dates else ""), len(lines) - 1
    print(f"  web copy: rows={rows} max_date={maxd} dates={len(dates)}")

    if not rw:
        print("  NOT YET: refresh-worker has not published since the convergence deploy")
        return 1
    # refresh-worker published; did it publish LAST? only then is the web copy attributable to it.
    if lo and lo > rw:
        print(f"  AMBIGUOUS: live-odds-worker published AFTER refresh-worker ({lo} > {rw}),")
        print("             so the copy above is not attributable to refresh-worker.")
        return 2
    if maxd > _STALE:
        print(f"  CONVERGED: refresh-worker's own copy reaches {maxd}, past the stale {_STALE}")
        return 0
    print(f"  NOT YET: refresh-worker published but its copy still stops at {maxd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
