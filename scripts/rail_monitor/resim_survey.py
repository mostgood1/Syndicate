"""Survey the live re-sim / live-lens snapshots in the keyvalue: per key, games, per-game keys, refusal-ish fields. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/resim_survey.py
"""
import collections, json, subprocess

keys = subprocess.run(["redis-cli", "--scan", "--pattern", "syndicate:refresh-state:/home/amyn/syndicate-prod/data/live/*"],
                      capture_output=True, text=True).stdout.split()
for k in sorted(set(keys)):
    if not ("resim" in k or "lens" in k):
        continue
    raw = subprocess.run(["redis-cli", "--raw", "GET", k], capture_output=True, text=True, errors="replace").stdout
    try:
        d = json.loads(raw)
    except Exception as e:
        print(k.rsplit("/", 1)[1], "unparsable", type(e).__name__, len(raw))
        continue
    if isinstance(d, dict) and isinstance(d.get("payload"), dict):
        d = d["payload"]
    games = d.get("games") if isinstance(d, dict) else None
    print("==", k.rsplit("/", 1)[1], "bytes", len(raw), "top", list(d.keys())[:20] if isinstance(d, dict) else type(d).__name__)
    print("   generatedAt", d.get("generatedAt") if isinstance(d, dict) else None, "games", len(games) if isinstance(games, list) else type(games).__name__)
    if not isinstance(games, list) or not games:
        continue
    gk = collections.Counter(kk for g in games if isinstance(g, dict) for kk in g)
    print("   game keys", dict(gk))
    ref = collections.Counter()
    for g in games:
        if not isinstance(g, dict):
            continue
        for kk, v in g.items():
            if "refus" in kk.lower() or kk in ("status", "state", "resimStatus", "liveResim"):
                ref[(kk, json.dumps(v, default=str)[:80])] += 1
        for lens in g.get("gameLens") or []:
            if isinstance(lens, dict):
                for kk, v in lens.items():
                    if "refus" in kk.lower() or kk in ("source",):
                        ref[("gameLens." + kk, json.dumps(v, default=str)[:80])] += 1
    for (kk, v), c in ref.most_common(25):
        print(f"   {c:4d} {kk} = {v}")
    for top in ("refusalsByReason", "coverage", "counts"):
        if top in d:
            print("  ", top, json.dumps(d[top], default=str)[:400])
