"""Rail Watch tick: one Claude-free reading of the Layer 2 Games Rail, rendered as a self-contained HTML page.

Run by the Windows task "SyndicateRailWatch" every ~20 min (pythonw, no window). Read-only on the fleet: the probe
reads the served APIs, the WSL helpers read logs and Redis at nice 19. Writes:
  C:\\tmp\\railmon\\dash\\rows_<D>.jsonl          one row per reading (dash_update.py, the same rows the monitor uses)
  C:\\tmp\\railmon\\railwatch\\extra_<D>.jsonl    memory-guard counts, parent RSS, games with no live model
  C:\\tmp\\railmon\\railwatch\\index.html         the page (also copied to ~/syndicate-prod/data/reports/rail_watch/)
  C:\\tmp\\railmon\\railwatch\\tick.log           one line per tick
Quiet hours 2:00-10:00 AM CST are skipped unless --force. The slate day D rolls at 5 AM CST.

  pythonw C:\\tmp\\railmon\\railwatch\\tick.py [--force] [--render-only]
"""
import datetime as dt
import glob
import html
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
UTC = dt.timezone.utc
R = r"C:\tmp\railmon"
OUT = os.path.join(R, "railwatch")
DASH = os.path.join(R, "dash")
READINGS = os.path.join(R, "readings")
REPOS = [r"C:\Users\tempadmin\Coding\Syndicate", r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"]
PY = sys.executable  # pythonw under the task; its children get no console either
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FLEET_PAGE = "~/syndicate-prod/data/reports/rail_watch/index.html"
os.makedirs(OUT, exist_ok=True)


def log(msg):
    with open(os.path.join(OUT, "tick.log"), "a", encoding="utf-8") as f:
        f.write(dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") + " " + msg + "\n")


def run(cmd, timeout, cwd=None, stdout_path=None):
    t0 = time.time()
    try:
        if stdout_path:
            with open(stdout_path, "w", encoding="utf-8") as so:
                p = subprocess.run(cmd, cwd=cwd, stdout=so, stderr=subprocess.PIPE, timeout=timeout,
                                   creationflags=NOWIN, text=True, errors="replace")
            return p.returncode, "", p.stderr[-400:], time.time() - t0
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout, creationflags=NOWIN, text=True,
                           errors="replace")
        return p.returncode, p.stdout, p.stderr[-400:], time.time() - t0
    except subprocess.TimeoutExpired:
        return -9, "", "timeout", time.time() - t0


def wsl(cmd, timeout):
    return run(["wsl", "--", "bash", "-c", cmd], timeout)


def slate_day(now_ct):
    return (now_ct - dt.timedelta(hours=5)).date().isoformat()


def rows_path(day):
    return os.path.join(DASH, "rows.jsonl" if day == "2026-11-18" else f"rows_{day}.jsonl")


def read_jsonl(path):
    out = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def tick(day, now_utc):
    rows = read_jsonl(rows_path(day))
    n = max([r.get("n", 0) for r in rows] or [0]) + 1
    if rows:
        prev = max(r["at"] for r in rows)
    else:
        prev = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(10, 0), CT).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    dd = day[5:7] + day[8:10]
    probe_out = os.path.join(OUT, f"auto_{dd}r{n}_probe.txt")
    metrics_out = os.path.join(DASH, f"m_auto_{dd}_{n}.json")
    repo = next((p for p in REPOS if os.path.exists(os.path.join(p, "scripts", "layer2_rail_monitor_probe.py"))), None)
    if not repo:
        log("no repo with the probe; skipped")
        return
    before = set(glob.glob(os.path.join(READINGS, "20*")))
    rc, _, err, secs = run([PY, "scripts/layer2_rail_monitor_probe.py", "--no-page", "--log-minutes", "25"], 300,
                           cwd=repo, stdout_path=probe_out)
    if rc != 0:
        log(f"probe rc={rc} {secs:.0f}s {err.strip()[:200]}")
        return
    new = sorted(set(glob.glob(os.path.join(READINGS, "20*"))) - before)
    if not new:
        log("probe wrote no readings dir")
        return
    rdir = new[-1]
    rc, _, err, _ = run(["wsl", "--", "nice", "-n", "19", "python3", "/mnt/c/tmp/railmon/dash/d4metrics.py", prev, day],
                        300, stdout_path=metrics_out)
    if rc != 0:
        log(f"d4metrics rc={rc} {err.strip()[:200]}")
        return
    since_ct = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(5, 0), CT).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    rc7, p7, _, _ = wsl(f"cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p7count.py {since_ct}", 240)
    rc29, p29, _, _ = wsl("cd ~/syndicate-prod && nice -n 19 ~/.venvs/syndicate/bin/python /mnt/c/tmp/railmon/p29_orient.py", 120)
    rcps, ps, _, _ = wsl("ps -eo pid,rss,etimes,args | grep -E 'run_refresh_worker.py|board_build_process --serve' | grep -v grep", 30)
    note = "auto"
    rc, out, err, _ = run([PY, os.path.join(DASH, "dash_update.py"), "row", "--n", str(n), "--day", day, "--probe", probe_out,
                           "--metrics", metrics_out, "--dir", rdir, "--note", note], 120)
    if rc != 0:
        log(f"dash_update rc={rc} {err.strip()[:200]}")
        return
    run([PY, os.path.join(DASH, "dash_update.py"), "build", "--day", day], 60)
    extra = {"n": n, "at": os.path.basename(rdir), "p7": p7.strip().splitlines()[1:] if rc7 == 0 else None,
             "ps": [l.split()[:3] + [("board child" if "board_build" in l else "parent")] for l in ps.splitlines()] if rcps == 0 else [],
             "orient": [json.loads(l) for l in p29.splitlines() if l.startswith("{")] if rc29 == 0 else []}
    with open(os.path.join(OUT, f"extra_{day}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(extra) + "\n")
    log(f"reading {day} n={n} ok ({os.path.basename(rdir)})")


def prune():
    """The probe saves a ~23 MB query.json per reading that nothing downstream reads. Drop it after 6 h; drop whole
    reading dirs after 10 days (the grader reads rail.json / reading.json for the slate day only)."""
    cut_q = time.time() - 6 * 3600
    cut_d = time.time() - 10 * 86400
    for d in glob.glob(os.path.join(READINGS, "20*")):
        try:
            m = os.path.getmtime(d)
            if m < cut_d:
                shutil.rmtree(d, ignore_errors=True)
                continue
            q = os.path.join(d, "query.json")
            if os.path.exists(q) and os.path.getmtime(q) < cut_q:
                os.remove(q)
        except OSError:
            pass


# ---------------------------------------------------------------- page

def fmt_ct(z):
    try:
        t = dt.datetime.strptime(z, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(CT)
    except (TypeError, ValueError):
        return "?"
    return t.strftime("%#I:%M %p") if os.name == "nt" else t.strftime("%-I:%M %p")


def num(v, nd=0, suf=""):
    if v is None:
        return "–"
    try:
        return f"{float(v):,.{nd}f}{suf}"
    except (TypeError, ValueError):
        return html.escape(str(v))


def chart(rows):
    rows = [r for r in rows if r.get("at")]
    if len(rows) < 2:
        return '<p class="note">The chart starts after the second reading.</p>'
    W, H, L, B, T = 900, 260, 40, 30, 14
    xs = [L + i * (W - L - 12) / (len(rows) - 1) for i in range(len(rows))]
    series = [("live games", "live_games", "var(--s1)"), ("flags shown", "flags_shown", "var(--s2)"),
              ("games with no live model", "live_games_no_model", "var(--bad)")]
    top = max([max(r.get(k) or 0 for r in rows) for _, k, _ in series] + [5])
    top = int((top + 4) // 5 * 5)
    y = lambda v: H - B - (v or 0) * (H - B - T) / top
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Live games, flags and games with no live model per reading">']
    for g in range(0, top + 1, max(1, top // 5)):
        parts.append(f'<line x1="{L}" x2="{W - 12}" y1="{y(g):.1f}" y2="{y(g):.1f}" class="grid"/>'
                     f'<text x="{L - 6}" y="{y(g) + 4:.1f}" class="ax" text-anchor="end">{g}</text>')
    for label, k, c in series:
        pts = " ".join(f"{x:.1f},{y(r.get(k)):.1f}" for x, r in zip(xs, rows))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2.5" stroke-linejoin="round"/>')
    step = max(1, len(rows) // 8)
    for i in range(0, len(rows), step):
        parts.append(f'<text x="{xs[i]:.1f}" y="{H - 8}" class="ax" text-anchor="middle">{html.escape(fmt_ct(rows[i]["at"]))}</text>')
    parts.append("</svg>")
    legend = "".join(f'<span><i style="background:{c}"></i>{label}</span>' for label, _, c in series)
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def render(day):
    rows = sorted(read_jsonl(rows_path(day)), key=lambda r: r["at"])
    extra = read_jsonl(os.path.join(OUT, f"extra_{day}.jsonl"))
    last_x = extra[-1] if extra else {}
    last = rows[-1] if rows else {}
    try:
        results = json.load(open(os.path.join(DASH, "rail_results.json"), encoding="utf-8"))
    except (OSError, ValueError):
        results = []
    tot = lambda k: sum(int(r.get(k) or 0) for r in rows)
    eve = [r for r in rows if "23:30" <= r["at"][11:16] or r["at"][11:16] <= "04:30"]
    eve_gap = max([r.get("board_pub_gap_max_s") or 0 for r in eve] or [0])
    tiles = [
        ("Live games now", num(last.get("live_games")), ""),
        ("Flags shown now", num(last.get("flags_shown")), ""),
        ("False / missed today", f"{tot('flags_false')} / {tot('flags_missed')}", "good" if tot("flags_false") + tot("flags_missed") == 0 else "bad"),
        ("Games with no live model now", num(last.get("live_games_no_model")), "warn" if (last.get("live_games_no_model") or 0) else "good"),
        ("Score-floor violations today", str(tot("floor_violations")), "good" if tot("floor_violations") == 0 else "bad"),
        ("Card contradictions today", str(tot("ours_contradictions")), "good" if tot("ours_contradictions") == 0 else "bad"),
        ("Longest board gap, evening", num(eve_gap, 0, " s") if eve else "–", "good" if eve and eve_gap <= 1800 else ("bad" if eve else "")),
        ("Board query now", num(last.get("query_s"), 1, " s"), "warn" if (last.get("query_s") or 0) > 8 else ""),
    ]
    tile_html = "".join(f'<div class="tile {c}"><div class="v">{v}</div><div class="k">{html.escape(k)}</div></div>' for k, v, c in tiles)
    dark = [o for o in (last_x.get("orient") or []) if o.get("matchup") and not o.get("with_model")]
    dark_html = "".join(f"<li>{html.escape(o['sport'].upper())} {html.escape(o['matchup'])}: {o.get('rows')} rows, "
                        f"{'teams REVERSED vs the re-sim (I-29)' if o.get('resim') == 'REVERSED' else ('not in the re-sim yet' if o.get('resim') == 'not_in_resim' else 're-sim refused it')}</li>"
                        for o in dark) or "<li>None among college games.</li>"
    mem = "<br>".join(html.escape(l) for l in (last_x.get("p7") or [])) or "–"
    ps_html = ", ".join(f"{html.escape(p[3])} {int(p[1]) / 1024 / 1024:.2f} GB" for p in (last_x.get("ps") or []) if len(p) >= 4 and p[1].isdigit()) or "–"
    trs = []
    for r in reversed(rows[-40:]):
        trs.append("<tr>" + "".join(f"<td>{c}</td>" for c in [
            html.escape(fmt_ct(r["at"])), num(r.get("live_games")), num(r.get("flags_shown")),
            f"{num(r.get('flags_false'))} / {num(r.get('flags_missed'))}", num(r.get("dark_rows")), num(r.get("live_games_no_model")),
            num(r.get("floor_violations")), f"{num(r.get('board_pub_gap_median_s'))} / {num(r.get('board_pub_gap_max_s'))}",
            num(r.get("query_s"), 1), num(r.get("live_rows")), num(r.get("host_load"), 1)]) + "</tr>")
    res = [x for x in results if x.get("kind") == "all"]
    res_rows = "".join(
        f"<tr><td>{html.escape(x['day'])}</td><td>{num(x.get('flags'))}</td><td>{num(x.get('won'))}-{num(x.get('lost'))}</td>"
        f"<td>{num(x.get('hit_pct'), 1, '%')}</td><td>{num(x.get('fair_pct'), 1, '%')}</td><td>{num(x.get('edge_pp'), 1)}</td>"
        f"<td>{'[' + num(x.get('ci90_lo_pp'), 1) + ', ' + num(x.get('ci90_hi_pp'), 1) + ']' if x.get('ci90_lo_pp') is not None else '–'}</td></tr>"
        for x in sorted(res, key=lambda x: x["day"], reverse=True))
    updated = dt.datetime.now(CT).strftime("%a %b %d, %#I:%M %p CST" if os.name == "nt" else "%a %b %d, %-I:%M %p CST")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300"><title>Rail Watch</title>
<style>
:root {{ --bg:#f7f6f2; --card:#fff; --ink:#1d1c1a; --mute:#6b6862; --line:#e4e1da; --s1:#2f6fd0; --s2:#c77d10; --bad:#c2402a; --good:#2f8a4f; --warn:#b7791f; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141413; --card:#1e1d1b; --ink:#ecebe7; --mute:#a19e97; --line:#33312d; --s1:#6aa1f0; --s2:#e3a447; --bad:#e86f5a; --good:#5cc27f; --warn:#e0a84a; }} }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif; }}
.wrap {{ max-width:1100px; margin:0 auto; padding:20px 16px 40px; }} h1 {{ font-size:26px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:26px 0 10px; }}
.sub {{ color:var(--mute); font-size:13px; }} .tiles {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:10px; margin-top:16px; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; }} .tile .v {{ font-size:24px; font-weight:700; font-variant-numeric:tabular-nums; }}
.tile .k {{ color:var(--mute); font-size:12px; margin-top:2px; }} .tile.good .v {{ color:var(--good); }} .tile.bad .v {{ color:var(--bad); }} .tile.warn .v {{ color:var(--warn); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; overflow-x:auto; }}
svg {{ width:100%; height:auto; display:block; }} .grid {{ stroke:var(--line); }} .ax {{ fill:var(--mute); font-size:11px; }}
.legend {{ display:flex; gap:16px; flex-wrap:wrap; font-size:12px; color:var(--mute); margin-bottom:6px; }} .legend i {{ display:inline-block; width:12px; height:3px; margin-right:6px; vertical-align:middle; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; font-variant-numeric:tabular-nums; }} th,td {{ text-align:right; padding:5px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }}
th:first-child,td:first-child {{ text-align:left; }} th {{ color:var(--mute); font-weight:600; }} ul {{ margin:6px 0; padding-left:20px; }} .note {{ color:var(--mute); font-size:13px; }}
</style></head><body><div class="wrap">
<h1>Rail Watch</h1><div class="sub">Layer 2 Games Rail on the fleet · slate {html.escape(day)} · updated {html.escape(updated)} · {len(rows)} readings today · refreshes itself every ~20 min, no Claude involved</div>
<div class="tiles">{tile_html}</div>
<h2>Through the day</h2><div class="card">{chart(rows)}</div>
<h2>Live games with no live model (latest reading)</h2><div class="card"><ul>{dark_html}</ul>
<p class="note">NHL coverage flicker (I-30) and NFL totals (no distribution) also leave games unpriced; the readings table counts every sport.</p></div>
<h2>Board memory guard today (#850)</h2><div class="card"><div class="note">{mem}</div><p class="note">Processes: {ps_html}</p></div>
<h2>Readings</h2><div class="card"><table><thead><tr><th>Time</th><th>Live</th><th>Flags</th><th>False / missed</th><th>Dark rows</th><th>No-model games</th><th>Floor viol.</th><th>Board gap med / max s</th><th>Query s</th><th>Rail rows</th><th>Host load</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div>
<h2>Flag results by day (graded on finals each night)</h2><div class="card"><table><thead><tr><th>Day</th><th>Flags</th><th>W-L</th><th>Hit</th><th>Fair</th><th>Edge pp</th><th>90% CI pp</th></tr></thead><tbody>{res_rows}</tbody></table></div>
<p class="note">Read-only probe of the served APIs plus fleet logs. Built by C:\\tmp\\railmon\\railwatch\\tick.py (backup: scripts/rail_monitor/railwatch_tick.py). The nightly grade comes from the Claude close.</p>
</div></body></html>"""


def publish(day):
    page = render(day)
    path = os.path.join(OUT, "index.html")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(path + ".tmp", path)
    wsl(f"mkdir -p ~/syndicate-prod/data/reports/rail_watch && cp /mnt/c/tmp/railmon/railwatch/index.html {FLEET_PAGE}.tmp && mv -f {FLEET_PAGE}.tmp {FLEET_PAGE}", 60)


def main():
    force = "--force" in sys.argv
    now_utc = dt.datetime.now(UTC)
    now_ct = now_utc.astimezone(CT)
    day = slate_day(now_ct)
    try:
        if "--render-only" not in sys.argv:
            if not force and 2 <= now_ct.hour < 10:
                return
            tick(day, now_utc)
            prune()
        publish(day)
    except Exception:
        log("ERROR " + traceback.format_exc().replace("\n", " | ")[-800:])


if __name__ == "__main__":
    main()
