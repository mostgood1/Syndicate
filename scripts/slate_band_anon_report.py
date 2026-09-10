"""refresh-worker's live-slate band, on the ANON axis, for `refresh-worker-anon-ratchet`.

WHY THIS EXISTS BESIDE `oom_band_report.py` RATHER THAN INSIDE IT. That tool
measures the OOM TRANSIENT -- excursions, amplitude, and the `inactive_file`
trough that discriminated the two kills from the survivals. This one measures
the RATCHET, which is a different phenomenon and was invisible to it: on
2026-09-09/10 the band reported **0 excursions and 0 kills** while `anon` peaked
at 3,138.7 MB against a recorded max of 1,877. A clean excursion count is not a
clean band.

THE BAND IS A FIXED TIMESTAMP RANGE, PASSED IN, NEVER "the last N hours".
`lastRunAt` is DISPATCH, not execution -- a scheduled run on this machine has
been observed stalling 9h13m under Modern Standby. A relative window would
silently describe the wrong hours when that happens; a fixed one describes the
band it was asked about no matter how late it fires.

WINDOWS ARE SPLIT ON DEPLOYS, for the reason `learnings.md` 2026-09-02 gives:
a query straddling a restart measures the reboot. Each deploy-free segment is
reported on its own line, and a segment shorter than `--min-minutes` is printed
but marked THIN rather than silently pooled.

COVERAGE IS PRINTED FOR EVERY SEGMENT. The Render logs API returns the NEWEST
lines inside a window, so a wide window can describe its last few seconds. A
segment whose covered span is far short of its asked span is not a sample of
that segment.

Usage:
    py -3 scripts/slate_band_anon_report.py --start 2026-09-10T22:00:00Z --end 2026-09-11T05:00:00Z
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# `state_worker.md [refresh-worker-headroom-2026-09-02]`, as corrected 2026-09-09.
RECORDED_BAND = (1518.0, 1877.0)
RATCHET_TEST_MB = 2500.0
# `oom_band_report.py`'s own discriminator, restated so this report can flag it.
INACTIVE_FILE_KILL_BAND = (26.3, 42.2)
INACTIVE_FILE_SURVIVED = (164.0, 240.0)


def _run(args: list[str]) -> str:
    proc = subprocess.run(
        [sys.executable, *args], capture_output=True, text=True,
        encoding="utf-8", cwd=str(REPO_ROOT))
    return proc.stdout or ""


def _deploys(start: str, end: str) -> list[str]:
    """Deploy `finishedAt` stamps inside the band, so segments can be cut on them."""
    out = _run(["scripts/render_events.py", "--service", "refresh-worker",
                "--since", start, "--end", end, "--type", "deploy_ended", "--json"])
    try:
        doc = json.loads(out)
    except Exception:
        return []
    stamps = []
    for row in (doc.get("events") or doc.get("rows") or doc.get("lines") or []):
        stamp = row.get("timestamp") or row.get("createdAt") or ""
        if stamp:
            stamps.append(str(stamp))
    return sorted(set(stamps))


def _watchdog(start: str, end: str) -> tuple[list[dict], dict]:
    out = _run(["scripts/render_logs.py", "--service", "refresh-worker",
                "--text", "MEMORY_WATCHDOG", "--start", start, "--end", end,
                "--tail", "400", "--json"])
    if not out.strip():
        return [], {}
    try:
        doc = json.loads(out)
    except Exception:
        return [], {}
    rows = []
    for line in doc.get("lines") or []:
        msg = line.get("message") or ""
        i = msg.find("MEMORY_WATCHDOG ")
        if i < 0:
            continue
        try:
            rows.append(json.loads(msg[i + len("MEMORY_WATCHDOG "):]))
        except Exception:
            pass
    return rows, doc.get("covered") or {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="band start, ISO Z")
    ap.add_argument("--end", required=True, help="band end, ISO Z")
    ap.add_argument("--min-minutes", type=float, default=20.0,
                    help="segments shorter than this are marked THIN")
    args = ap.parse_args()

    print(f"SLATE BAND (anon axis)  {args.start} .. {args.end}", flush=True)
    deploys = _deploys(args.start, args.end)
    print(f"  deploys in band: {len(deploys)} {deploys}", flush=True)
    print("  NOTE: segments are cut on deploys. A window straddling a restart "
          "measures the reboot.", flush=True)
    print(flush=True)

    edges = [args.start, *deploys, args.end]
    segments = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]

    print(f"  {'segment start':<22}{'segment end':<22}{'n':>6}{'anon min':>10}"
          f"{'anon mean':>11}{'ANON MAX':>10}{'headroom':>10}{'min inact':>11}  peak stage",
          flush=True)
    peaks = []
    for start, end in segments:
        rows, cov = _watchdog(start, end)
        anon = [r["memory_anon_mb"] for r in rows
                if isinstance(r.get("memory_anon_mb"), (int, float))]
        if not anon:
            print(f"  {start[11:19]:<22}{end[11:19]:<22}     0   "
                  f"NO SAMPLES -- no coverage, not no growth", flush=True)
            continue
        inact = [r.get("memory_inactive_file_mb") for r in rows
                 if isinstance(r.get("memory_inactive_file_mb"), (int, float))]
        stages = [r.get("last_stage") for r in rows]
        peak_stage = stages[anon.index(max(anon))] if len(stages) == len(anon) else "?"
        peaks.append(max(anon))
        print(f"  {start[11:19]:<22}{end[11:19]:<22}{len(anon):>6}{min(anon):>10.1f}"
              f"{sum(anon)/len(anon):>11.1f}{max(anon):>10.1f}{4096 - max(anon):>10.1f}"
              f"{(min(inact) if inact else float('nan')):>11.1f}  {peak_stage}", flush=True)
        print(f"  {'':<22}{'':<22}   covered {str(cov.get('start'))[11:19]}.."
              f"{str(cov.get('end'))[11:19]}", flush=True)
        if inact and min(inact) <= INACTIVE_FILE_KILL_BAND[1]:
            print(f"  {'':<44}   ** min inactive_file {min(inact):.1f} MB is INSIDE the "
                  f"kill band {INACTIVE_FILE_KILL_BAND} (survived: {INACTIVE_FILE_SURVIVED})",
                  flush=True)

    print(flush=True)
    if not peaks:
        print("  NO SEGMENT PRODUCED A SAMPLE. That is no coverage, not a quiet band.",
              flush=True)
        return 1
    worst = max(peaks)
    print(f"  recorded band [refresh-worker-headroom-2026-09-02]: anon "
          f"{RECORDED_BAND[0]:.0f}..{RECORDED_BAND[1]:.0f}", flush=True)
    print(f"  worst peak this band: {worst:.1f} MB  -> headroom {4096 - worst:.1f} MB",
          flush=True)
    if worst > RATCHET_TEST_MB:
        print(f"  RATCHET CONFIRMED AGAIN: worst peak > {RATCHET_TEST_MB:.0f} MB test",
              flush=True)
    else:
        print(f"  RATCHET NOT REPRODUCED in this band (worst peak <= "
              f"{RATCHET_TEST_MB:.0f} MB). Two clean bands would falsify it.", flush=True)
    print("  Also run: py -3 scripts/oom_band_report.py --start ... --end ...  "
          "(the TRANSIENT axis; 0 excursions there does not mean a clean band)",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
