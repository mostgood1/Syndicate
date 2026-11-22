"""live-odds-worker's process tree at the first live_lens_tick_before_soccer sample at/after a UTC time: pid, ppid, RSS,
and the cmdline flags that tell runs apart. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/tree_at.py 2026-11-21T20:20
"""
import collections, json, re, subprocess, sys

at = sys.argv[1][:19]
stage = sys.argv[2] if len(sys.argv) > 2 else "live_lens_tick_before_soccer"
for f in ("logs/live-odds-worker.log.1", "logs/live-odds-worker.log"):
    out = subprocess.run(["grep", "-a", "ALL_PROCESS_MEMORY {", f], capture_output=True, text=True, errors="replace").stdout
    for l in out.splitlines():
        if not re.match(r"20\d\d-", l) or l[:19] < at:
            continue
        body = json.loads(l[l.index("{"):])
        if body.get("stage") != stage:
            continue
        procs = {p["pid"]: p for p in body.get("processes") or [] if isinstance(p, dict) and "pid" in p}
        root = [p for p in procs.values() if "run_live_odds_refresh_worker.py" in " ".join(p.get("cmdline") or [])][0]["pid"]
        kids = collections.defaultdict(list)
        for p in procs.values():
            kids[p.get("ppid")].append(p["pid"])
        print(l[:24], "container_mb", body.get("container_memory_mb"))
        total = 0.0

        def show(pid, depth):
            global total
            p = procs[pid]
            cmd = p.get("cmdline") or []
            keep = []
            for i, c in enumerate(cmd):
                if c.endswith(".py") or c in ("-m",) or (i and cmd[i - 1] == "-m"):
                    keep.append(c.split("/")[-1])
                elif c.startswith("--") and c in ("--sports", "--phase", "--mode", "--league", "--kind", "--lane", "--execution-mode", "--date"):
                    keep.append(c + "=" + (cmd[i + 1] if i + 1 < len(cmd) else ""))
                elif "refresh_status_manifest" in c:
                    keep.append("manifest=" + c.split("/")[-2])
            total += float(p.get("rss_mb") or 0)
            print("  " * depth + "%d rss %.0f  %s" % (pid, float(p.get("rss_mb") or 0), " ".join(keep)[:230]))
            for k in sorted(kids.get(pid, [])):
                show(k, depth + 1)

        show(root, 0)
        print("tree total %.0f" % total)
        sys.exit(0)
