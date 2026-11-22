"""Lines of one role log in a UTC window that match a regex (case-insensitive). Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/logwin.py live-odds-worker 2026-11-21T19:44 2026-11-21T19:47 "soccer|LIVE_LENS" [max_lines] [maxlen]
"""
import re, subprocess, sys

role, lo, hi, pat = sys.argv[1], sys.argv[2][:19], sys.argv[3][:19], sys.argv[4]
cap = int(sys.argv[5]) if len(sys.argv) > 5 else 200
maxlen = int(sys.argv[6]) if len(sys.argv) > 6 else 400
rx = re.compile(pat, re.I)
n = shown = 0
for f in ("logs/%s.log.1" % role, "logs/%s.log" % role):
    try:
        out = subprocess.run(["grep", "-a", "-E", "-i", pat, f], capture_output=True, text=True, errors="replace").stdout
    except Exception as exc:
        print("read failed", f, exc)
        continue
    for l in out.splitlines():
        if not re.match(r"20\d\d-\d\d-\d\dT", l) or not (lo <= l[:19] <= hi) or not rx.search(l):
            continue
        n += 1
        if shown < cap:
            print(l[:maxlen])
            shown += 1
print("matched", n, "shown", shown)
