"""Board query cold reads: share of /api/intelligence/query requests whose board_read stage is cold (> 2 s).

  cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/qstage.py <from_utc> <to_utc>
"""
import datetime as dt, glob, json, subprocess, sys

a = sys.argv[1][:19]
b = sys.argv[2][:19]
rows = []
for f in sorted(glob.glob("logs/web.log*")):
    out = subprocess.run(["grep", "-a", "QUERY_STAGE_MS", f], capture_output=True, text=True, errors="replace").stdout
    for l in out.splitlines():
        if "ALL_PROCESS_MEMORY" in l or "{" not in l:
            continue
        t = l[:19]
        if not (a <= t < b):
            continue
        try:
            d = json.loads(l[l.index("{"):])
        except Exception:
            continue
        rows.append((t, d.get("stages", {}).get("board_read", 0.0), d.get("total_ms", 0.0)))
rows = sorted(set(rows))


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


cold = [r for r in rows if r[1] > 2000]
warm = [r for r in rows if r[1] <= 2000]
print(json.dumps(dict(window=[a, b], queries=len(rows), cold=len(cold),
                      cold_pct=round(100 * len(cold) / len(rows), 1) if rows else None,
                      cold_board_read_p50_ms=q([r[1] for r in cold], .5), cold_total_p50_ms=q([r[2] for r in cold], .5),
                      warm_total_p50_ms=q([r[2] for r in warm], .5), warm_total_p90_ms=q([r[2] for r in warm], .9),
                      all_total_p50_ms=q([r[2] for r in rows], .5), all_total_p90_ms=q([r[2] for r in rows], .9))))
