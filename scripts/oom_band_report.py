"""Measure refresh-worker's OOM signature across a window, deploy-free segment by segment.

WHY THIS EXISTS. The `#435`/`refresh-worker-oom-recurrence` lane produced three
fixes that are live and exercised and NONE of which has been shown to move the
transient, because every measurement was taken too early, too short, or in the
wrong part of the day. Kills cluster in the live-slate band (~22:00Z-05:00Z);
the daytime lull shows ZERO excursions on broken and fixed code alike, so a
clean afternoon says nothing. This tool exists so the band gets measured the
same way every time, without re-deriving the method at 5am.

WHAT IT MEASURES, and why these columns:
  - kills            from the EVENTS API only. A killed process emits no log
                     line, and `learnings.md` records a retracted "0 kills"
                     claim that came from a log grep. Never read this from logs.
  - excursions       a watchdog sample with climb <= -400 MB/s, i.e. the
                     COLLAPSE at the end of a ~2GB transient. The failure is a
                     transient, not a leak: trough returns to ~1.2-1.9GB every
                     cycle and nothing accumulates.
  - amplitude        peak-minus-trough per excursion. This is the quantity a
                     fix has to move. Night baseline: mean 1,950-2,235 MB.
  - min inactive_file  how much evictable page cache the kernel had left at the
                     worst moment. THE discriminator: the two windows that ended
                     in a kill bottomed at 26.3 and 42.2 MB; surviving windows
                     kept 164-240 MB.

WINDOWS ARE SPLIT ON DEPLOYS. Every deploy reboots the worker and re-runs
hydration cold, so a window spanning one measures the deploy, not the workload.
Each deploy-free segment is reported on its own line.

Usage:
    py -3 scripts/oom_band_report.py --start 2026-08-16T22:00:00Z --end 2026-08-17T05:00:00Z
    py -3 scripts/oom_band_report.py --start 2026-08-16T22:00:00Z          # to now
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_preflight import SERVICE_IDS, _api_key  # noqa: E402

# Night baselines from `.syndicate/deploys.md` (2026-08-16). Stated here so a
# change is judged against a number rather than a memory of one.
BASE_AMP = (1950.0, 2235.1)
BASE_INACT_KILL = (26.3, 42.2)
BASE_INACT_SURVIVED = (164.0, 240.0)
COLLAPSE_MB_S = -400.0


def _api(path: str, **params):
    url = "https://api.render.com" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + _api_key(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def events(service_id: str, start: str, end: str | None):
    """oomKills and deploy_starts inside the window, from the EVENTS API."""
    kills, deploys = [], []
    rows = _api("/v1/services/%s/events" % service_id, limit=100)
    for row in rows:
        ev = row.get("event", row)
        ts = str(ev.get("timestamp") or "")
        if not ts or ts < start or (end and ts > end):
            continue
        det = ev.get("details") or {}
        reason = det.get("reason") or {}
        if ev.get("type") == "server_failed" and reason.get("oomKilled"):
            kills.append(ts)
        if ev.get("type") == "deploy_started":
            deploys.append(ts)
    return sorted(kills), sorted(deploys)


def watchdog(start: str, end: str | None):
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "render_logs.py"),
           "--service", "refresh-worker", "--text", "MEMORY_WATCHDOG",
           "--start", start, "--width", "900"]
    if end:
        cmd += ["--end", end]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parent.parent)).stdout
    rows = []
    for line in out.splitlines():
        if line.startswith("#"):
            continue
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            d = json.loads(m.group(0))
        except Exception:
            continue
        if "memory_anon_mb" in d:
            rows.append((line.split()[0], d))
    return rows


def analyse(rows):
    amps, trough, peak = [], None, None
    for _ts, d in rows:
        anon = d.get("memory_anon_mb")
        climb = d.get("climb_mb_per_s") or 0
        if anon is None:
            continue
        if climb <= COLLAPSE_MB_S:
            if trough is not None and peak is not None:
                amps.append(peak - trough)
            trough = peak = anon
            continue
        if trough is None or anon < trough:
            trough = peak = anon
        if peak is None or anon > peak:
            peak = anon
    anon_vals = sorted((d.get("memory_anon_mb") or 0) for _, d in rows)
    inact = [d.get("memory_inactive_file_mb") for _, d in rows
             if d.get("memory_inactive_file_mb") is not None]
    return amps, (anon_vals[-1] if anon_vals else 0.0), (min(inact) if inact else -1.0)


def minutes(a: str, b: str) -> float:
    f = "%Y-%m-%dT%H:%M:%S"
    return (datetime.strptime(b[:19], f) - datetime.strptime(a[:19], f)).total_seconds() / 60.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end")
    args = ap.parse_args()
    svc = SERVICE_IDS["refresh-worker"]

    kills, deploys = events(svc, args.start, args.end)
    end = args.end or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    print("BAND %s .. %s" % (args.start, end))
    print("  kills (events API): %d %s" % (len(kills), kills or ""))
    print("  deploys in band   : %d %s" % (len(deploys), deploys or ""))
    print("  NOTE: a clean band is only meaningful if it is the LIVE-SLATE band."
          " The daytime lull shows 0 excursions on broken code too.")

    bounds = [args.start] + deploys + [end]
    segments = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    print("\n%-22s %-22s %6s %6s %7s %9s %9s" % (
        "segment start", "segment end", "mins", "exc", "exc/hr", "mean amp", "min inact"))
    tot_exc, all_amps = 0, []
    for s, e in segments:
        rows = watchdog(s, e)
        if not rows:
            print("  %-20s %-22s   no watchdog samples (below the 60%% emit floor, or down)" % (s[11:19], e[11:19]))
            continue
        amps, peak, inact = analyse(rows)
        dur = max(minutes(rows[0][0], rows[-1][0]), 0.1)
        tot_exc += len(amps)
        all_amps += amps
        print("  %-20s %-20s %6.1f %6d %7.1f %9.1f %9.1f" % (
            s[11:19], e[11:19], dur, len(amps), len(amps) / (dur / 60.0),
            (sum(amps) / len(amps)) if amps else 0.0, inact))

    print("\nVERDICT INPUTS")
    print("  total excursions in band : %d" % tot_exc)
    if all_amps:
        print("  amplitude mean           : %.1f MB   (night baseline %.0f-%.0f)"
              % (sum(all_amps) / len(all_amps), *BASE_AMP))
    print("  baseline min inactive_file: kills %s / survived %s"
          % (BASE_INACT_KILL, BASE_INACT_SURVIVED))
    print("  Excursions at the old amplitude => the three shipped fixes were NOT the 2GB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
