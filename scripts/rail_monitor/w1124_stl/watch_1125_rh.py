"""R-H watcher (read-only, run at nice 19): poll the NHL grid's STL @ NYI game state every 60 s until it is in a
running period (not P1 0:00 / END / INT), at most 25 min, then run the kit and the grid count once."""
import datetime, json, subprocess, time, urllib.request

U = "http://127.0.0.1:10000/api/board/book-grid?sport=nhl&date=2026-11-25&limit=2000&market=h2h"


def stl_state():
    g = json.load(urllib.request.urlopen(U, timeout=60))
    for r in g.get("rows") or []:
        gm = r.get("game") if isinstance(r.get("game"), dict) else {}
        if str(gm.get("matchup") or "").startswith("STL @"):
            return gm.get("state"), str(gm.get("status_token") or ""), gm.get("away_score"), gm.get("home_score")
    return None, "", None, None


def running(tok):
    t = tok.upper()
    if not t or "END" in t or "INT" in t or "FINAL" in t:
        return False
    parts = t.split()
    if len(parts) == 2 and parts[0] in ("P1", "P2", "P3", "OT") and parts[1] not in ("0:00", "20:00"):
        return True
    return False


deadline = time.time() + 25 * 60
while True:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%SZ")
    try:
        st = stl_state()
    except Exception as e:  # noqa: BLE001
        st = ("error", repr(e)[:120], None, None)
    print(now, "STL @ NYI", st, flush=True)
    if st[0] == "live" and running(st[1]):
        break
    if st[0] == "final" or time.time() > deadline:
        print("stopped waiting:", "final" if st[0] == "final" else "25-min deadline", flush=True)
        break
    time.sleep(60)

print("=== kit", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), flush=True)
subprocess.run(["bash", "/mnt/c/tmp/w1124_stl/kit_after_up_stl.sh"])
print("=== grid", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), flush=True)
subprocess.run(["python3", "/mnt/c/tmp/w1124_stl/grid_1125_rh.py"])
print("=== done", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), flush=True)
