import glob, io, json, os, statistics as st
# H7 control: pre-kickoff snapshot builds vs the post-kickoff rebuilds of the same artifacts.
S = os.environ.get("SOCCER_AUDIT_CACHE") or os.path.dirname(os.path.abspath(__file__))
def keyed(pattern):
    out = {}
    for f in glob.glob(pattern):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            j = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(j, dict) and j.get("league"):
            out[(j["league"], str(j.get("date")))] = f
    return out


snap = keyed(os.path.join(S, "recs_snapshot_0902", "*.json"))
fin = keyed(os.path.join(S, "prod", "recs", "*.json"))
print("snapshot", len(snap), "final", len(fin), "common", len(set(snap) & set(fin)))
rows, props = [], []
for name in sorted(set(snap) & set(fin)):
    a = json.load(io.open(snap[name], encoding="utf-8"))
    b = json.load(io.open(fin[name], encoding="utf-8"))
    am = {str(m.get("match_id")): m for m in a.get("matches") or []}
    bm = {str(m.get("match_id")): m for m in b.get("matches") or []}
    same_date = str(a.get("date")) >= "2026-09-02"
    print(" ", a.get("date"), a.get("league"), "snap_gen", str(a.get("generated_at"))[:16], "final_gen", str(b.get("generated_at"))[:16],
          "sims", a.get("simulations"), b.get("simulations"), "matches", len(am), len(bm), "PREKICKOFF" if same_date else "")
    for mid in set(am) & set(bm):
        x, y = am[mid], bm[mid]
        rows.append((same_date, abs(x["win_probability"]["home"] - y["win_probability"]["home"]),
                     abs((x.get("total_distribution") or {}).get("mean", 0) - (y.get("total_distribution") or {}).get("mean", 0)),
                     abs((x.get("volume_projection") or {}).get("home_corners", 0) - (y.get("volume_projection") or {}).get("home_corners", 0)),
                     x.get("kickoff")))
    ap = {(str(p.get("match_id")), p.get("player_name")): p for p in a.get("player_props") or []}
    bp = {(str(p.get("match_id")), p.get("player_name")): p for p in b.get("player_props") or []}
    for k in set(ap) & set(bp):
        props.append((same_date, abs((ap[k].get("expected_shots") or 0) - (bp[k].get("expected_shots") or 0))))
for flag in (False, True):
    r = [x for x in rows if x[0] == flag]
    p = [x[1] for x in props if x[0] == flag]
    if r:
        print("prekickoff" if flag else "post-match both", "matches", len(r), "mean|dHome|", round(st.mean(x[1] for x in r), 4),
              "identical", sum(1 for x in r if x[1] == 0), "mean|dTotal|", round(st.mean(x[2] for x in r), 3),
              "mean|dCornersH|", round(st.mean(x[3] for x in r), 3), "player rows", len(p),
              "mean|dShots|", round(st.mean(p), 4) if p else None)
print("kickoff sample", rows[0][4] if rows else None)
