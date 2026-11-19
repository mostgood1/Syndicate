"""Owned reading R-E (#838, lane odds-lane-sport-deadline): has an NHL odds rebuild hit its time limit?

Run from ~/syndicate-prod on WSL, read-only:
  nice -n 19 python3 /mnt/c/tmp/railmon/p838_watch.py <since_utc, e.g. 2026-11-19T16:00:00Z>
Prints one JSON line:
  nhl_steps         NHL generation steps (nhl_live_generation / nhl_pregame_generation) in odds_refresh manifests launched since
  nhl_timed_out     those with timed_out true (each listed in "timeouts" with its run, step, start and seconds)
  markers           .nhl_live_generation_timeout_<date>.json files on disk (name, mtime UTC)
  cooldown_lines    NHL_LIVE_GENERATION_COOLDOWN lines in the live-odds-worker log since
A timeout (nhl_timed_out > 0, or a marker) triggers the full grade with C:/tmp/odds_lane_838/livewin.py (see the runbook).
"""
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

UTC = dt.timezone.utc
since = dt.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))


def ts(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


steps = 0
timeouts = []
for d in glob.glob("data/reports/migration_runs/*/odds_refresh_*"):
    m = re.search(r"odds_refresh_(\d{8}_\d{6})", d)
    if not m:
        continue
    launch = dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
    if launch < since:
        continue
    try:
        doc = json.load(open(os.path.join(d, "odds_refresh.json")))
    except Exception:
        continue
    s = doc["result"] if isinstance(doc.get("result"), dict) else doc
    for r in s.get("results") or []:
        for st in r.get("refresh_steps") or []:
            name = str(st.get("name") or "")
            if name not in ("nhl_live_generation", "nhl_pregame_generation"):
                continue
            steps += 1
            if st.get("timed_out"):
                a, b = ts(st.get("started_at")), ts(st.get("finished_at"))
                timeouts.append(dict(run=os.path.basename(d), step=name,
                                     start=a.strftime("%Y-%m-%dT%H:%M:%SZ") if a else None,
                                     sec=round((b - a).total_seconds()) if a and b else None))
markers = []
for f in glob.glob("data/nhl_source/data/processed/.nhl_live_generation_timeout_*.json"):
    markers.append(dict(name=os.path.basename(f),
                        mtime=dt.datetime.fromtimestamp(os.path.getmtime(f), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")))
cool = 0
for f in sorted(glob.glob("logs/live-odds-worker.log*")):
    out = subprocess.run(["grep", "-a", "NHL_LIVE_GENERATION_COOLDOWN", f], capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if "ALL_PROCESS_MEMORY" in line:  # quotes process cmdlines, including this watcher's own grep
            continue
        t = ts(line[:24]) if re.match(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z", line) else None
        if t and t >= since:
            cool += 1
print(json.dumps(dict(read_at=dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), since=sys.argv[1], nhl_steps=steps,
                      nhl_timed_out=len(timeouts), timeouts=timeouts[:5], markers=markers, cooldown_lines=cool)))
