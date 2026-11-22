"""One ALL_PROCESS_MEMORY line of a role log at/after a UTC time: its keys, and any per-process list. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/apm_peek.py live-odds-worker 2026-11-21T19:46:39
"""
import json, re, subprocess, sys

role, at = sys.argv[1], sys.argv[2][:19]
out = subprocess.run(["grep", "-a", "ALL_PROCESS_MEMORY {", "logs/%s.log" % role], capture_output=True, text=True, errors="replace").stdout
for l in out.splitlines():
    if not re.match(r"20\d\d-", l) or l[:19] < at:
        continue
    body = json.loads(l[l.index("{"):])
    print(l[:24])
    for k, v in body.items():
        if isinstance(v, list):
            print(k, "list", len(v))
            for item in v[:40]:
                print("   ", json.dumps(item)[:260])
        elif isinstance(v, dict):
            print(k, json.dumps(v)[:400])
        else:
            print(k, v)
    break
