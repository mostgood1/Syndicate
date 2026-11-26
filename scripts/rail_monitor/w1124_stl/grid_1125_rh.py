"""R-H (read-only): the NHL book grid per market (limit 2000 each, asserting len == total_rows), full-game moneyline +
puck-line rows per game, which are live, and how many carry a live model (live_gameline). The rail is a capped
selection, so it cannot show N of N; the grid can."""
import collections, json, urllib.request

base = "http://127.0.0.1:10000/api/board/book-grid?sport=nhl&date=2026-11-25&limit=2000&market="
sample_done = False
by = collections.defaultdict(lambda: [0, 0, 0, collections.Counter()])
stl_rows = []
for mk in ("h2h", "spreads", "alternate_spreads"):
    g = json.load(urllib.request.urlopen(base + mk, timeout=60))
    rows = g.get("rows") or []
    print("market", mk, "rows", len(rows), "total_rows", g.get("total_rows"), "generated", g.get("generated_at"),
          "read", g.get("read_at"), "COMPLETE" if len(rows) == g.get("total_rows") else "TRUNCATED")
    gs = g.get("game_state")
    if mk == "h2h" and isinstance(gs, dict):
        for k, v in gs.items():
            if "louis" in json.dumps(v, default=str).lower() or "louis" in str(k).lower():
                print("  game_state St. Louis:", k, json.dumps(v, default=str)[:400])
    for r in rows:
        if r.get("player_name") or str(r.get("segment") or "full") != "full":
            continue
        gm = r.get("game") if isinstance(r.get("game"), dict) else {}
        mu = ("%s %s [%s-%s]" % (gm.get("matchup"), gm.get("status_token"), gm.get("away_score"), gm.get("home_score"))) if gm else ("%s @ %s" % (r.get("away_team"), r.get("home_team")))
        lg = r.get("live_gameline")
        if not sample_done and lg:
            print("  sample live_gameline:", json.dumps(lg, default=str)[:700])
            print("  sample live_display:", json.dumps(r.get("live_display"), default=str)[:300])
            sample_done = True
        b = by[str(mu)]
        b[0] += 1
        if isinstance(lg, dict):
            b[1] += 1
            st = lg.get("withheld_reason")
            b[2] += lg.get("model_prob") is not None
            if st:
                b[3][str(st)] += 1
        if "louis" in str(mu).lower() or "STL @" in str(mu) or "@ STL" in str(mu):
            stl_rows.append((mk, r.get("line"), json.dumps(lg, default=str)[:400] if lg else None,
                             json.dumps(r.get("live_display"), default=str)[:200]))
print()
for mu, (n, nlg, m, why) in sorted(by.items()):
    flag = "  <-- St. Louis" if ("louis" in mu.lower() or "STL @" in mu or "@ STL" in mu) else ""
    print("  %-48s rows %d, live_gameline %d, with a model %d %s%s" % (mu, n, nlg, m, dict(why) or "", flag))
print("St. Louis rows:", len(stl_rows))
for x in stl_rows[:12]:
    print("   ", x)
