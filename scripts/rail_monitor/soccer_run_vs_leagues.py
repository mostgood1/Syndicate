"""Soccer live/fast odds runs (lane live-odds-worker-soccer-live): run length against the number of leagues in play at
launch (SOCCER_LIVE_AUTORUN_LAUNCHED in_play=...), joined by launch second. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/soccer_run_vs_leagues.py 2026-11-21
"""
import collections, datetime as dt, json, re, statistics as st, subprocess, sys

date = sys.argv[1]
launches = []
for f in ("logs/live-odds-worker.log.1", "logs/live-odds-worker.log"):
    out = subprocess.run(["grep", "-a", "SOCCER_LIVE_AUTORUN_LAUNCHED", f], capture_output=True, text=True, errors="replace").stdout
    for l in out.splitlines():
        m = re.search(r"in_play=(\S+)", l)
        if re.match(r"20\d\d-", l) and m:
            launches.append((dt.datetime.fromisoformat(l[:19]).replace(tzinfo=dt.timezone.utc), m.group(1).split(",")))
pattern = "syndicate:refresh-state:*/reports/refresh_status/%s/*/refresh_status_manifest.json" % date
paths = subprocess.run(["redis-cli", "--raw", "--scan", "--pattern", pattern], capture_output=True, text=True).stdout.split()
runs = []
for p in paths:
    try:
        m = json.loads(subprocess.run(["redis-cli", "--raw", "GET", p], capture_output=True, text=True, errors="replace").stdout)
    except Exception:
        continue
    if not isinstance(m, dict) or m.get("lane") != "live-odds-worker-soccer-live":
        continue
    try:
        a = dt.datetime.fromisoformat(str(m["generatedAt"])).astimezone(dt.timezone.utc)
        b = dt.datetime.fromisoformat(str(m["finishedAt"]).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except Exception:
        continue
    runs.append((a, b))
runs.sort()
joined = []
for a, b in runs:
    best = min(launches, key=lambda x: abs((x[0] - a).total_seconds()), default=None)
    if best is None or abs((best[0] - a).total_seconds()) > 5:
        continue
    alive_before = sum(1 for a2, b2 in runs if a2 < a < b2)
    joined.append((len(best[1]), (b - a).total_seconds(), alive_before, a))
print("runs", len(runs), "joined to a launch line", len(joined))
by = collections.defaultdict(list)
for n, secs, alive, a in joined:
    by[n].append((secs, alive))
print("leagues in play | runs | seconds median / p90 / max | share over the 120 s interval | share launched onto a live run")
for n in sorted(by):
    s = sorted(x for x, _ in by[n])
    print("  %2d | %3d | %4.0f / %4.0f / %4.0f | %.2f | %.2f" % (
        n, len(s), st.median(s), s[int(0.9 * (len(s) - 1))], s[-1], sum(1 for x in s if x > 120) / len(s),
        sum(1 for _, al in by[n] if al) / len(by[n])))
