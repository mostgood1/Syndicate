"""Read-only: every soccer refresh run 11-26..11-27 (migration_runs/<day>/odds_refresh_*/odds_refresh.json): ok or not,
and for the failed ones, which steps failed and why (the stderr_tail's leading token + source). WSL, nice 19:
  nice -n 19 python3 /mnt/c/tmp/railmon/soccer_fail_agg_1127.py"""
import collections, glob, json, os, re

base = os.path.expanduser("~/syndicate-prod/data/reports/migration_runs")
runs = ok = failed = 0
steps = collections.Counter()
reasons = collections.Counter()
by_hour = collections.Counter()
first = last = None
other_samples = []
for day in ("2026-11-26", "2026-11-27"):
    for p in sorted(glob.glob(os.path.join(base, day, "odds_refresh_*", "odds_refresh.json"))):
        try:
            d = json.load(open(p))
        except Exception:
            continue
        cmd = d.get("command") or []
        if "--sports" not in cmd or cmd[cmd.index("--sports") + 1] != "soccer":
            continue
        runs += 1
        if d.get("ok"):
            ok += 1
            continue
        failed += 1
        stamp = os.path.basename(os.path.dirname(p))[len("odds_refresh_"):]
        first = first or stamp
        last = stamp
        by_hour[stamp[:11]] += 1
        for fs in d.get("failureSummary") or []:
            for st in fs.get("failing_steps") or []:
                name = st.get("name")
                steps[name] += 1
                tail = str(st.get("stderr_tail") or "")
                m = re.search(r"\b([A-Z][A-Z_]{5,})\b[^\n]*?(?:reason=([a-z_]+))?", tail)
                key = (m.group(1) if m else "no_token") + (f" reason={m.group(2)}" if m and m.group(2) else "")
                if "come back soon" in tail:
                    key += " [maintenance page]"
                reasons[(re.sub(r"soccer_[a-z_0-9]+?_(history_current|players|[a-z_]+)$", r"\1", name or ""), key)] += 1
                if not m and len(other_samples) < 4:
                    other_samples.append((stamp, name, tail[-300:]))
print(f"soccer runs {runs}: ok {ok}, failed {failed}; failed first {first} last {last}")
print("failed runs per UTC hour (YYYYMMDD_HH):", dict(sorted(by_hour.items())))
print("failing steps:")
for k, v in steps.most_common():
    print(f"  {v:4d}  {k}")
print("step kind x reason:")
for k, v in reasons.most_common():
    print(f"  {v:4d}  {k}")
for s in other_samples:
    print("UNTOKENED", s)
