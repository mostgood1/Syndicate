"""Rebuild Rail Watch rows for slate days that predate the dashboard rows (11-15..11-17) from the saved readings.

  py -3 C:\\tmp\\railmon\\railwatch\\backfill.py <repo> [day ...]
Each saved reading dir keeps the probe's raw reading.json; the probe's own `summary()` turns it into the same shape the
live probe prints, and `dash_update.py row` makes the row. Fleet-log metrics (board cadence, sweeps) are not
recoverable for those days (the logs rotated), so the metrics file is empty and those columns stay blank.
Writes C:\\tmp\\railmon\\dash\\rows_<day>.jsonl only when that file does not exist yet.
"""
import datetime as dt
import glob
import importlib.util
import json
import os
import subprocess
import sys
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
R = r"C:\tmp\railmon"
repo = sys.argv[1]
days = sys.argv[2:] or ["2026-11-15", "2026-11-16", "2026-11-17"]
spec = importlib.util.spec_from_file_location("probe", os.path.join(repo, "scripts", "layer2_rail_monitor_probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

by_day = {}
for d in sorted(glob.glob(os.path.join(R, "readings", "20*"))):
    stamp = os.path.basename(d)
    try:
        t = dt.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).astimezone(CT)
    except ValueError:
        continue
    by_day.setdefault((t - dt.timedelta(hours=5)).date().isoformat(), []).append(d)

empty_metrics = os.path.join(R, "railwatch", "backfill_empty_metrics.json")
json.dump({}, open(empty_metrics, "w", encoding="utf-8"))
for day in days:
    out = os.path.join(R, "dash", f"rows_{day}.jsonl")
    if os.path.exists(out):
        print(day, "rows file exists; skipped")
        continue
    ok = bad = 0
    for n, d in enumerate(by_day.get(day, []), 1):
        try:
            reading = json.load(open(os.path.join(d, "reading.json"), encoding="utf-8"))
            summ = probe.summary(reading)
        except Exception as exc:  # an older probe version may lack a field the summary reads
            print(day, os.path.basename(d), "summary failed:", type(exc).__name__, str(exc)[:120])
            bad += 1
            continue
        pfile = os.path.join(R, "railwatch", "backfill_probe.json")
        json.dump(summ, open(pfile, "w", encoding="utf-8"), default=str)
        p = subprocess.run([sys.executable, os.path.join(R, "dash", "dash_update.py"), "row", "--n", str(n), "--day", day,
                            "--probe", pfile, "--metrics", empty_metrics, "--dir", d, "--note", "backfilled from saved reading"],
                           capture_output=True, text=True)
        if p.returncode == 0:
            ok += 1
        else:
            bad += 1
            print(day, os.path.basename(d), "row failed:", p.stderr.strip()[-200:])
    print(day, "rows", ok, "failed", bad)
