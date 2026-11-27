"""Replay R18 (21:43:02Z 11-27) through the NEW dash_update: rewrite R18's saved p29 lines the way the new p29 would
have (soccer snapshot 20:01:59Z, 6,063 s old at the reading -> snapshot_stale, resim_age_s on the summary line), run a
COPY of dash_update.py in a scratch dir (it writes rows next to itself), and print the soccer reason, detail and
stale_snapshots. Touches nothing the 20-minute task reads."""
import json, os, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone

D = r"C:\tmp\railmon\dash"
READ_AT = datetime(2026, 11, 27, 21, 43, 2, tzinfo=timezone.utc)
probe = os.path.join("C:/tmp/railmon/railwatch", "auto_1127r18_probe.txt")
for name in os.listdir(D):  # the tick's probe output for n=18 11-27
    if name.startswith("probe_auto_1127_18") or name == "p_auto_1127_18.txt":
        probe = os.path.join(D, name)
print("probe file", probe)
lines = open(os.path.join(D, "orient_auto_1127_18.txt"), encoding="utf-8").read().splitlines()
out = []
for l in lines:
    if not l.startswith("{"):
        out.append(l)
        continue
    o = json.loads(l)
    gen = o.get("resim_generated")
    if gen and not o.get("matchup"):
        age = (READ_AT - datetime.fromisoformat(gen)).total_seconds()
        o["resim_age_s"] = round(age)
    out.append(o)
ages = {o["sport"]: o.get("resim_age_s") for o in out if isinstance(o, dict) and not o.get("matchup") and o.get("sport")}
print("snapshot ages at R18 (s):", ages)
for o in out:
    if isinstance(o, dict) and o.get("matchup") and o.get("resim") == "not_in_resim" and (ages.get(o["sport"]) or 0) > 900:
        o["resim"] = "snapshot_stale"
        o["detail"] = f"{o.get('detail')}, {ages[o['sport']] / 60:.0f} min old: its writer has not rewritten it, so a game that started since is absent (not a name miss)"
tmpd = tempfile.mkdtemp(prefix="replay_r18_")
shutil.copyfile(os.path.join(D, "dash_update.py"), os.path.join(tmpd, "dash_update.py"))
orient = os.path.join(tmpd, "orient.txt")
with open(orient, "w", encoding="utf-8") as f:
    f.write("\n".join(json.dumps(x) if isinstance(x, dict) else x for x in out) + "\n")
print("scratch", tmpd)
args = [sys.executable, os.path.join(tmpd, "dash_update.py"), "row", "--n", "18", "--day", "2026-11-27",
        "--metrics", os.path.join(D, "m_auto_1127_18.json"), "--dir", r"C:\tmp\railmon\readings\20261127T214302Z",
        "--note", "replay", "--orient", orient, "--probe", probe or "MISSING"]
r = subprocess.run(args, capture_output=True, text=True)
print("rc", r.returncode, r.stderr[-400:])
row = json.loads(open(os.path.join(tmpd, "rows_2026-11-27.jsonl"), encoding="utf-8").read().splitlines()[-1])
for k, v in (row.get("live_games_no_model_reasons") or {}).items():
    print("reason:", k, "->", v)
    print("   detail:", (row.get("live_games_no_model_detail") or {}).get(k))
print("stale_snapshots:", row.get("stale_snapshots"))
