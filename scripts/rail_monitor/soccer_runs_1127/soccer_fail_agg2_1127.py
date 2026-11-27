"""Read-only, nice 19: soccer refresh runs 11-20..11-27 per day (ok / failed / failed with an Understat step), the first
and last Understat failure, the Understat reasons, and every NON-Understat failing step classified (dns / other) with
its first and last run, so the steady-state failures can be told from the 11-26 network outage."""
import collections, glob, json, os, re

base = os.path.expanduser("~/syndicate-prod/data/reports/migration_runs")
per_day = collections.defaultdict(lambda: [0, 0, 0])
und_first = und_last = None
und_reason = collections.Counter()
other = collections.defaultdict(lambda: {"n": 0, "first": None, "last": None, "sample": ""})
for day in ("2026-11-20", "2026-11-21", "2026-11-22", "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27"):
    for p in sorted(glob.glob(os.path.join(base, day, "odds_refresh_*", "odds_refresh.json"))):
        try:
            d = json.load(open(p))
        except Exception:
            continue
        cmd = d.get("command") or []
        if "--sports" not in cmd or cmd[cmd.index("--sports") + 1] != "soccer":
            continue
        stamp = os.path.basename(os.path.dirname(p))[len("odds_refresh_"):]
        per_day[day][0] += 1
        if d.get("ok"):
            continue
        per_day[day][1] += 1
        has_und = False
        for fs in d.get("failureSummary") or []:
            for st in fs.get("failing_steps") or []:
                tail = str(st.get("stderr_tail") or "")
                name = str(st.get("name") or "")
                if "UNDERSTAT_UNAVAILABLE" in tail:
                    has_und = True
                    und_first = und_first or stamp
                    und_last = stamp
                    m = re.search(r"reason=(\S+)", tail)
                    r = m.group(1) if m else "?"
                    if "come back soon" in tail:
                        r += " (maintenance page)"
                    und_reason[r] += 1
                    continue
                kind = re.sub(r"^soccer_(.+?)_(history_current|players|artifacts|schedule|odds|props|live_state)$", r"\2", name)
                cls = ("dns" if "NameResolutionError" in tail or "name resolution" in tail
                       else "timeout" if "imed out" in tail or "Timeout" in tail else "other")
                o = other[(kind, cls)]
                o["n"] += 1
                o["first"] = o["first"] or stamp
                o["last"] = stamp
                if cls == "other" and not o["sample"]:
                    o["sample"] = f"{name}: {tail[-260:]}"
        if has_und:
            per_day[day][2] += 1
print("day: soccer runs / failed / failed with an Understat step")
for day, (n, f, u) in sorted(per_day.items()):
    print(f"  {day}: {n} / {f} / {u}")
print("Understat failures: first run", und_first, "last run", und_last)
for k, v in und_reason.most_common():
    print(f"  {v:4d}  reason={k}")
print("non-Understat failing steps (kind, class): n, first run, last run")
for (kind, cls), o in sorted(other.items(), key=lambda kv: -kv[1]["n"]):
    print(f"  {kind:16s} {cls:8s} {o['n']:4d}  {o['first']} .. {o['last']}")
    if o["sample"]:
        print("      sample:", o["sample"].replace("\n", " ")[:300])
