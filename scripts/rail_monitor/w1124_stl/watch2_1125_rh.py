"""R-H second pass (read-only, nice 19): poll the NHL grid every 60 s, at most 15 min, until the STL @ NYI full-game
moneyline row carries a live model probability; print its quote age and live basis each poll, then the per-game count
once (grid_1125_rh.py) and the kit."""
import datetime, json, subprocess, time, urllib.request

U = "http://127.0.0.1:10000/api/board/book-grid?sport=nhl&date=2026-11-25&limit=2000&market=h2h"


def poll():
    g = json.load(urllib.request.urlopen(U, timeout=60))
    for r in g.get("rows") or []:
        gm = r.get("game") if isinstance(r.get("game"), dict) else {}
        if str(gm.get("matchup") or "").startswith("STL @") and str(r.get("segment") or "full") == "full":
            lg = r.get("live_gameline") if isinstance(r.get("live_gameline"), dict) else {}
            ld = r.get("live_display") if isinstance(r.get("live_display"), dict) else {}
            return {
                "status": gm.get("status_token"), "score": "%s-%s" % (gm.get("away_score"), gm.get("home_score")),
                "age_s": r.get("age_seconds"), "seen_age_s": r.get("seen_age_seconds"),
                "model_prob": lg.get("model_prob"), "withheld": lg.get("withheld_reason"),
                "basis": ld.get("basis"), "lane": ld.get("lane"), "as_of": ld.get("as_of"),
                "grid": g.get("generated_at"),
            }
    return None


deadline = time.time() + 15 * 60
while True:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%SZ")
    try:
        p = poll()
    except Exception as e:  # noqa: BLE001
        p = {"error": repr(e)[:120]}
    print(now, json.dumps(p, default=str), flush=True)
    if p and p.get("model_prob") is not None:
        break
    if p and "FINAL" in str(p.get("status") or "").upper():
        print("stopped: final", flush=True)
        break
    if time.time() > deadline:
        print("stopped: 15-min deadline", flush=True)
        break
    time.sleep(60)

print("=== grid", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), flush=True)
subprocess.run(["python3", "/mnt/c/tmp/w1124_stl/grid_1125_rh.py"])
print("=== kit", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), flush=True)
subprocess.run(["bash", "/mnt/c/tmp/w1124_stl/kit_after_up_stl.sh"])
print("=== done", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), flush=True)
