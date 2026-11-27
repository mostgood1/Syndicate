"""Read-only reader for the rail card OURS fix (fe46fb249, lane layer2-rail-monitor).

  py -3 read_ours_fix.py <reading_dir> <page.html> [<label>]

P1: the page carries the fix (`flaggedOwn` and the "from another re-sim tick" tooltip).
P2: the page's OWN rail code (scripts/layer2_rail_monitor_run.mjs, as the probe runs it) over that reading's saved
    inputs: for every flagged FULL-GAME total whose flagged row is not calibrated and has its own live_total, does
    OURS equal that row's own live_total to one decimal? Prints N, equal, differ (with the PROJ box beside each).
Exit 0 always; the verdict is in the output. Nothing is fetched: run it on a saved page and a saved reading.
"""
import json, os, subprocess, sys

RUNNER = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a\scripts\layer2_rail_monitor_run.mjs"
rdir, page = sys.argv[1], sys.argv[2]
label = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(page)
html = open(page, encoding="utf-8", errors="replace").read()
print(f"[{label}] P1 page carries flaggedOwn: {'flaggedOwn' in html}; tooltip text: {'from another re-sim tick' in html}")

stamp = os.path.basename(rdir.rstrip("\\/"))  # 20261127T040310Z
now = f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"
saved = json.load(open(os.path.join(rdir, "rail.json"), encoding="utf-8"))
rail_date = saved.get("railDate") or "all"
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"rail_{label}_{stamp}.json")
p = subprocess.run(["node", RUNNER, page, os.path.join(rdir, "query.json"), os.path.join(rdir, "chips.json"),
                    os.path.join(rdir, "liverail_2.json"), now, out, str(rail_date)], capture_output=True, text=True)
if p.returncode != 0:
    print(f"[{label}] runner rc {p.returncode}: {(p.stdout + p.stderr)[-400:]}")
    raise SystemExit(0)
cards = json.load(open(out, encoding="utf-8"))["cards"]


def rows_of(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    for k in ("rows", "items", "recommendations"):
        if isinstance(d.get(k), list):
            return d[k]
    resp = d.get("response") if isinstance(d.get("response"), dict) else {}
    for k in ("rows", "items", "recommendations"):
        if isinstance(resp.get(k), list):
            return resp[k]
    return []


fresh = rows_of(os.path.join(rdir, "liverail_2.json"))
board = rows_of(os.path.join(rdir, "query.json"))
TOT = {"totals", "total", "totals_alt", "alternate_totals"}


def own_row(card, side, line):
    for src in (fresh, board):  # the rail merges fresh rows over the board's when they are as new
        for r in src:
            if not isinstance(r, dict) or r.get("player_name"):
                continue
            if str(r.get("segment") or "full") != "full" or str(r.get("market") or "").lower() not in TOT:
                continue
            if str(r.get("away_key")) != str(card.get("awayKey")) or str(r.get("home_key")) != str(card.get("homeKey")):
                continue
            if str(r.get("side") or "").lower()[:1] != side[:1]:
                continue
            try:
                if abs(float(r.get("line")) - line) > 1e-9:
                    continue
            except Exception:
                continue
            return r
    return None


n = eq = ne = cal = no_own = unmatched = 0
lines = []
for c in cards:
    if not c.get("live"):
        continue
    box = ((c.get("chip") or {}).get("intervals") or {}).get("final", {}) if isinstance(c.get("chip"), dict) else {}
    for m in c.get("markets") or []:
        e = m.get("edge")
        if m.get("key") != "totals" or m.get("segment") != "full" or not e:
            continue
        side = str(e.get("side") or "")
        try:
            line = float(side[1:])
        except Exception:
            continue
        r = own_row(c, side, line)
        if r is None:
            unmatched += 1
            continue
        if r.get("live_total_basis") == "calibrated":
            cal += 1
            continue
        if r.get("live_total") is None:
            no_own += 1
            continue
        n += 1
        own = f"{float(r['live_total']):.1f}"
        same = m.get("ours") == own
        eq += same
        ne += not same
        lines.append(f"   {'=' if same else 'X'} {c.get('sport')} {c.get('matchup')} {side}: ours {m.get('ours')} own {own}"
                     f" box {box.get('total') if isinstance(box, dict) else None} tip {bool(e.get('oursTip'))}")
print(f"[{label}] P2 reading {stamp} (now {now}, railDate {rail_date}): flagged uncalibrated full-game totals with own "
      f"live_total N={n}, OURS == own {eq}, OURS != own {ne}; also calibrated {cal}, no own {no_own}, row not found {unmatched}")
for x in lines:
    print(x)
