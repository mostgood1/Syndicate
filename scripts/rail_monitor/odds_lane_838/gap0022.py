"""Why no ok NHL odds refresh between 00:22:15Z and 00:48:59Z on 11-19? Run from ~/syndicate-prod."""
import datetime as dt, glob, json, os, re
UTC = dt.timezone.utc
A = dt.datetime(2026, 11, 19, 0, 10, tzinfo=UTC)
B = dt.datetime(2026, 11, 19, 0, 55, tzinfo=UTC)


def ts(v):
    try:
        x = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=UTC)
    except Exception:
        return None


print("== manifests launched 00:10-00:55Z ==")
for d in sorted(glob.glob("data/reports/migration_runs/2026-11-1[89]/odds_refresh_2026111[89]_00*")):
    m = re.search(r"odds_refresh_(\d{8}_\d{6})", d)
    t = dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
    if not (A <= t <= B):
        continue
    try:
        doc = json.load(open(os.path.join(d, "odds_refresh.json")))
    except Exception as e:
        print(os.path.basename(d), "unreadable", e)
        continue
    s = doc["result"] if isinstance(doc.get("result"), dict) else doc
    sports = [r.get("sport") for r in s.get("results") or []]
    st = [(r.get("sport"), x) for r in s.get("results") or [] for x in r.get("refresh_steps") or []]
    tt = [(ts(x.get("started_at")), ts(x.get("finished_at"))) for _, x in st]
    tt = [(a, b) for a, b in tt if a and b]
    sec = (max(b for _, b in tt) - min(a for a, _ in tt)).total_seconds() if tt else -1
    nhl = [(x.get("name"), x.get("ok"), ts(x.get("finished_at"))) for sp, x in st if sp == "nhl"]
    if "nhl" in sports or sec > 60:
        print(f"{t:%H:%M:%S} {d.split('/')[-2]} phase={s.get('phase')} sports={sports} sec={sec:.0f} ok={s.get('ok')} nhl={[(n, o, f'{f:%H:%M:%S}' if f else None) for n, o, f in nhl]}")

print("== live-odds-worker sweep lines 00:10-00:55Z ==")
pat = re.compile(r"ODDS_SWEEP_(LAUNCHED|REFUSED|SKIP|DEFER)|odds_sweep|sweep_due|nhl", re.I)
for f in ("logs/live-odds-worker.log.1", "logs/live-odds-worker.log"):
    try:
        fh = open(f, errors="replace")
    except OSError:
        continue
    for line in fh:
        if "ODDS_SWEEP" not in line:
            continue
        mm = re.search(r"(20\d\d-\d\d-\d\d[T ]\d\d:\d\d:\d\d)", line)
        if not mm:
            continue
        t = dt.datetime.fromisoformat(mm.group(1).replace(" ", "T")).replace(tzinfo=UTC)
        if A <= t <= B:
            print(line.rstrip()[:260])
