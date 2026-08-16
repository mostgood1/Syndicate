"""Baseline watcher: how often do the soccer and MLB branches run at the SAME time?

Phase 0, measurement 4 of `.syndicate/plan_2026-08-16_sim_scheduling.md`. Phase 1
changes soccer's refresh cadence to remove that overlap, and the claim "it worked"
is only checkable against a baseline taken BEFORE the change. Lane
`odds-cadence-off-the-mlb-peak` has an hour table from 2026-08-16; a handed-down
baseline expires, so this re-takes it on a schedule and appends, building a real
distribution instead of one evening's snapshot.

WHAT IT MEASURES, and why it is the combined figure.

    worst_container_mb   -- the peak `container_memory_mb` in the hour.

That is the number the OOM killer acts on. A per-PROCESS peak is what made the
margin read as 578 MB when it was actually 124 MB, so this deliberately never
reports a per-process maximum as if it were headroom.

    both_samples         -- samples where a soccer branch AND an MLB branch are
                            both running. The quantity Phase 1 is trying to cut.

RUNS OFF-BOX. It reads Render's logs API from a developer machine and touches no
worker thread -- `learnings.md`: "never run a heavyweight census ON the thread
that is doing the measuring."

ATTRIBUTABLE ZEROES. "No samples in the window" and "samples present, no overlap"
are different facts and are reported differently. A watcher that prints 0 for
both is how a broken instrument passes as good news.

Usage:
    py -3 scripts/watch_branch_overlap.py --hours 6
    py -3 scripts/watch_branch_overlap.py --hours 24 --out reports/branch_overlap/baseline.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]

# Branch classifiers, matched against each sampled process's cmdline. Kept as
# explicit substrings rather than a clever regex so that adding a branch is a
# one-line change and so a miss is debuggable by eye.
SOCCER_MARKERS = ("build_soccer_artifacts", "--soccer-leagues", "build_soccer_picks", "poll_soccer_live_state")
MLB_MARKERS = ("run_mlb_daily_sim_job", "refresh_mlb_oddsapi", "fetch_mlb_oddsapi_local")

_SAMPLE_RE = re.compile(r"ALL_PROCESS_MEMORY\s+(\{.*\})\s*$")


def _read_logs(service: str, start_iso: str, tail: int) -> list[str]:
    """Delegate to scripts/render_logs.py -- it already pages BACKWARD correctly.

    Reimplementing the pager here is exactly the mistake that tool's docstring
    documents three sessions making: a forward pager re-reads the same tail and
    silently covers 1.2s of a 51s window.
    """
    # --width is REQUIRED here and defaults to 200 in that tool, which truncates
    # every sample mid-key at `"pro` -- the `processes` array this script exists
    # to read never survives the default. Measured: a real line is ~15-40 KB and
    # arrived as 232 chars, so the JSON never closed and NOTHING parsed. The
    # failure looked exactly like "the emitter is off".
    command = [
        sys.executable, str(REPO_ROOT / "scripts" / "render_logs.py"),
        "--service", service, "--text", "ALL_PROCESS_MEMORY",
        "--start", start_iso, "--tail", str(tail), "--width", "200000",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise SystemExit(f"render_logs failed ({result.returncode}): {result.stderr[-800:]}")
    return result.stdout.splitlines()


def _classify(processes: list[dict]) -> tuple[bool, bool, float, float]:
    soccer_mb = mlb_mb = 0.0
    soccer = mlb = False
    for item in processes:
        if not isinstance(item, dict):
            continue
        cmdline = str(item.get("cmdline") or "")
        try:
            rss = float(item.get("rss_mb") or 0.0)
        except (TypeError, ValueError):
            rss = 0.0
        if any(marker in cmdline for marker in SOCCER_MARKERS):
            soccer, soccer_mb = True, soccer_mb + rss
        elif any(marker in cmdline for marker in MLB_MARKERS):
            mlb, mlb_mb = True, mlb_mb + rss
    return soccer, mlb, soccer_mb, mlb_mb


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="refresh-worker")
    parser.add_argument("--hours", type=int, default=6, help="how far back to read")
    parser.add_argument("--tail", type=int, default=4000)
    parser.add_argument("--tz", default="America/Chicago")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "reports" / "branch_overlap" / "baseline.jsonl")
    args = parser.parse_args()

    tz = ZoneInfo(args.tz)
    start = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = _read_logs(args.service, start_iso, args.tail)

    buckets: dict[str, dict] = defaultdict(
        lambda: {"samples": 0, "soccer": 0, "mlb": 0, "both": 0,
                 "worst_container_mb": 0.0, "worst_both_container_mb": 0.0}
    )
    parsed = malformed = 0
    covered_lo = covered_hi = None

    for line in lines:
        if line.startswith("#"):
            continue
        match = _SAMPLE_RE.search(line)
        if not match:
            continue
        stamp_text = line.split()[0] if line.split() else ""
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            malformed += 1
            continue
        try:
            stamp = datetime.fromisoformat(stamp_text.replace("Z", "+00:00"))
        except ValueError:
            malformed += 1
            continue
        parsed += 1
        covered_lo = stamp if covered_lo is None or stamp < covered_lo else covered_lo
        covered_hi = stamp if covered_hi is None or stamp > covered_hi else covered_hi

        local_hour = stamp.astimezone(tz).strftime("%Y-%m-%d %H")
        bucket = buckets[local_hour]
        soccer, mlb, _, _ = _classify(payload.get("processes") or [])
        try:
            container = float(payload.get("container_memory_mb") or 0.0)
        except (TypeError, ValueError):
            container = 0.0
        bucket["samples"] += 1
        bucket["soccer"] += int(soccer)
        bucket["mlb"] += int(mlb)
        bucket["worst_container_mb"] = max(bucket["worst_container_mb"], container)
        if soccer and mlb:
            bucket["both"] += 1
            bucket["worst_both_container_mb"] = max(bucket["worst_both_container_mb"], container)

    # ATTRIBUTABLE ZERO. These three are different facts.
    if not lines:
        print("NO LOG LINES RETURNED -- the reader failed or the window is empty. NOT a measurement.")
        return 2
    if parsed == 0:
        print(f"LOG LINES PRESENT ({len(lines)}) BUT NO ALL_PROCESS_MEMORY SAMPLES PARSED "
              f"(malformed={malformed}). The emitter may be off, or the format changed. NOT a measurement.")
        return 2

    print(f"BRANCH-OVERLAP BASELINE   service={args.service}   tz={args.tz}")
    print(f"requested window: last {args.hours}h from {start_iso}")
    print(f"COVERED         : {covered_lo} .. {covered_hi}   samples={parsed} malformed={malformed}")
    print()
    header = f"{'hour (local)':<16}{'n':>5}{'soccer':>8}{'mlb':>6}{'BOTH':>6}{'worst MB':>10}{'worst@BOTH':>12}"
    print(header)
    print("-" * len(header))
    for hour in sorted(buckets):
        b = buckets[hour]
        print(f"{hour:<16}{b['samples']:>5}{b['soccer']:>8}{b['mlb']:>6}{b['both']:>6}"
              f"{b['worst_container_mb']:>10.1f}{(b['worst_both_container_mb'] or 0):>12.1f}")

    total_both = sum(b["both"] for b in buckets.values())
    worst_overall = max((b["worst_container_mb"] for b in buckets.values()), default=0.0)
    worst_both = max((b["worst_both_container_mb"] for b in buckets.values()), default=0.0)
    print()
    print(f"TOTAL both-branches-live samples : {total_both} of {parsed} ({100.0*total_both/parsed:.1f}%)")
    print(f"WORST container (any sample)     : {worst_overall:.1f} MB")
    print(f"WORST container while BOTH live  : {worst_both:.1f} MB")
    if total_both == 0:
        print("NOTE: zero overlap in this window. That is a real reading, NOT an instrument "
              "failure -- samples parsed above. It may simply be an off-peak window.")

    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "service": args.service,
        "tz": args.tz,
        "requested_hours": args.hours,
        "covered_from": covered_lo.isoformat() if covered_lo else None,
        "covered_to": covered_hi.isoformat() if covered_hi else None,
        "samples": parsed,
        "malformed": malformed,
        "total_both": total_both,
        "worst_container_mb": worst_overall,
        "worst_both_container_mb": worst_both,
        "hours": {h: dict(b) for h, b in sorted(buckets.items())},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    print(f"\nappended to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
