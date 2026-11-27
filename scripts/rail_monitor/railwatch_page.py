"""Rail Watch page renderer (Claude-free). Imported by tick.py; reads only local files the tick and the nightly close
write. One self-contained HTML file: a day picker (Today, every slate day since 11-15, All days, Product).

Sections, per the original Rail Watch day pages and the claude.ai live dashboard (user 11-20: "the rail watch looks very
trimeed down from the original rail watch dashbaord"):
  day strip · decisions waiting (latest write-up) · charts (flags / dark / no-model, fresh-quote share) · did the flags carry
  anything (grading by population + P3/P4/P5 + over-confidence) · games with no live model · memory guard · refresh · load ·
  teams on the rail · the day's write-up (rendered from the findings DAILY SUMMARY) · readings
  Product tab: board / shortlist / suggested / staked results · cheat sheets · optimization levers · findings · loads
"""
import datetime as dt
import glob
import html
import json
import os
import re
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
UTC = dt.timezone.utc
R = r"C:\tmp\railmon"
DASH = os.path.join(R, "dash")
OUT = os.path.join(R, "railwatch")
DAY_PAGES = {
    "2026-11-15": "https://claude.ai/artifact/BJwFByJoeonxBCHPeRTnP7",
    "2026-11-16": "https://claude.ai/artifact/NatuXkAdpFRR3RN5EmBjRq",
    "2026-11-17": "https://claude.ai/artifact/HBPdAGfJxCjGcAF76iNx2f",
    "2026-11-18": "https://claude.ai/artifact/ESGaWMYhR7JH6EWfeqiViY",
    "2026-11-19": "https://claude.ai/artifact/XxP9SEsLj9NFebk8G1YEs3",
}
LIVE_DASH = "https://claude.ai/artifact/HoJ2n52ewHZnVDbN2LpxaJ"


# ------------------------------------------------------------------ data

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


def load_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def rows_path(day):
    return os.path.join(DASH, "rows.jsonl" if day == "2026-11-18" else f"rows_{day}.jsonl")


def grade_for(day):
    for p in (os.path.join(R, f"grade_{day}_out.json"), os.path.join(R, f"grade{day[5:7]}{day[8:10]}_out.json")):
        g = load_json(p, None)
        if isinstance(g, dict):
            return g
    return None


def findings_text(day):
    for p in (os.path.join(OUT, f"findings_{day}.md"),):
        try:
            return open(p, encoding="utf-8").read()
        except OSError:
            pass
    return ""


def summary_md(text):
    m = re.search(r"^#{1,2} DAILY SUMMARY.*$", text, re.M)
    if not m:
        return ""
    rest = text[m.start():]
    nxt = re.search(r"^## Reading ", rest[1:], re.M)
    return rest[: nxt.start() + 1] if nxt else rest


def subsection(md, title_re):
    m = re.search(r"^(#{2,4}) " + title_re + r".*$", md, re.M | re.I)
    if not m:
        return ""
    level = len(m.group(1))
    rest = md[m.end():]
    nxt = re.search(r"^#{1,%d} " % level, rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


# ------------------------------------------------------------------ markdown (display only)

def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    s = re.sub(r"(?<![\"'>=])(https://claude\.ai/artifact/[A-Za-z0-9]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', s)
    return s


def md_to_html(md):
    out, lines, i = [], md.splitlines(), 0
    stack = []  # open <ul>/<ol> by indent

    def close_lists(to=0):
        while len(stack) > to:
            out.append("</li></%s>" % stack.pop()[1])

    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            close_lists()
            head = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append('<div class="tblwrap"><table><thead><tr>' + "".join(f"<th>{_inline(h)}</th>" for h in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table></div>")
            continue
        h = re.match(r"^(#{1,4}) (.*)$", line)
        if h:
            close_lists()
            lvl = min(len(h.group(1)) + 2, 6)
            out.append(f"<h{lvl}>{_inline(h.group(2))}</h{lvl}>")
            i += 1
            continue
        b = re.match(r"^(\s*)([-*]|\d+\.) (.*)$", line)
        if b:
            indent = len(b.group(1)) // 2
            kind = "ol" if b.group(2)[0].isdigit() else "ul"
            if len(stack) <= indent:
                while len(stack) <= indent:
                    out.append(f"<{kind}><li>")
                    stack.append((indent, kind))
            else:
                close_lists(indent + 1)
                out.append("</li><li>")
            out.append(_inline(b.group(3)))
            i += 1
            continue
        if stack and line.startswith("  "):
            out.append(" " + _inline(line.strip()))
            i += 1
            continue
        close_lists()
        para = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(\s*([-*]|\d+\.) |#{1,4} |\s*\|)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>" + _inline(" ".join(para)) + "</p>")
    close_lists()
    return "".join(out)


# ------------------------------------------------------------------ helpers

def fmt_ct(z):
    try:
        t = dt.datetime.strptime(z, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(CT)
    except (TypeError, ValueError):
        return "?"
    return t.strftime("%#I:%M %p") if os.name == "nt" else t.strftime("%-I:%M %p")


def num(v, nd=0, suf=""):
    if v is None or v == "":
        return "–"
    try:
        return f"{float(v):,.{nd}f}{suf}"
    except (TypeError, ValueError):
        return html.escape(str(v))


def day_label(day):
    d = dt.date.fromisoformat(day)
    return d.strftime("%a %b ") + str(d.day)


def g(rows, k):
    return [r.get(k) for r in rows if r.get(k) is not None]


def p50(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def esc(s):
    return html.escape(str(s if s is not None else ""))


def line_chart(rows, series, *, ymin=0, ymax=None, suffix="", label=""):
    """rows need "at" (UTC stamp, labelled in CST) or "xl" (a ready x label)."""
    rows = [r for r in rows if r.get("at") or r.get("xl")]
    if len(rows) < 2:
        return '<p class="note">The chart starts after the second reading.</p>'
    W, H, L, B, T = 900, 230, 48, 28, 12
    xs = [L + i * (W - L - 14) / (len(rows) - 1) for i in range(len(rows))]
    vals = [[f(r) for r in rows] for _, f, _ in series]
    top = ymax if ymax is not None else max([max([v for v in vs if v is not None] or [0]) for vs in vals] + [5])
    if ymax is None:
        top = int((top + 4) // 5 * 5)
    span = (top - ymin) or 1
    y = lambda v: H - B - ((v if v is not None else ymin) - ymin) * (H - B - T) / span
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(label)}">']
    step = max(1, int(round(span / 5)))
    gv = ymin
    while gv <= top + 1e-9:
        parts.append(f'<line x1="{L}" x2="{W - 14}" y1="{y(gv):.1f}" y2="{y(gv):.1f}" class="grid{" zero" if gv == 0 and ymin < 0 else ""}"/>'
                     f'<text x="{L - 6}" y="{y(gv) + 4:.1f}" class="ax" text-anchor="end">{gv:g}{suffix}</text>')
        gv += step
    for (name, _, color), vs in zip(series, vals):
        segs, cur = [], []
        for x, v in zip(xs, vs):
            if v is None:
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append(f"{x:.1f},{y(v):.1f}")
        if cur:
            segs.append(cur)
        for sgm in segs:
            parts.append(f'<polyline points="{" ".join(sgm)}" fill="none" stroke="{color}" stroke-width="2.3" stroke-linejoin="round"/>')
    stepx = max(1, len(rows) // 8)
    for i in range(0, len(rows), stepx):
        parts.append(f'<text x="{xs[i]:.1f}" y="{H - 8}" class="ax" text-anchor="middle">{esc(rows[i].get("xl") or fmt_ct(rows[i]["at"]))}</text>')
    parts.append("</svg>")
    legend = "".join(f'<span><i style="background:{c}"></i>{esc(n)}</span>' for n, _, c in series)
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def fresh_share(r):
    lr = r.get("live_rows") or 0
    return round(100.0 * (r.get("priced_le_120") or 0) / lr, 1) if lr else None


def card(title, inner, note=""):
    return f'<h2>{esc(title)}</h2><div class="card">{inner}' + (f'<p class="note">{note}</p>' if note else "") + "</div>"


def kv_table(pairs):
    return "<table class='kv'><tbody>" + "".join(f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in pairs) + "</tbody></table>"


# ------------------------------------------------------------------ day sections

def strip_tiles(day, rows, extra, results, is_today):
    last = rows[-1] if rows else {}
    res = next((x for x in results if x.get("day") == day and x.get("kind") == "all"), None)
    fm = sum(int(x or 0) for x in g(rows, "flags_false")) + sum(int(x or 0) for x in g(rows, "flags_missed"))
    floor = sum(int(x or 0) for x in g(rows, "floor_violations")) if g(rows, "floor_violations") else None
    contra = sum(int(x or 0) for x in g(rows, "ours_contradictions")) if g(rows, "ours_contradictions") else None
    reversed_games = sorted({o["matchup"] for x in extra for o in (x.get("orient") or []) if o.get("resim") == "REVERSED"})
    exits = None
    for x in reversed(extra):
        for l in x.get("p7") or []:
            m = re.search(r"BOARD_PROCESS_EXITED rc \[(.*?)\]", l)
            if m:
                exits = len([t for t in m.group(1).split(",") if t.strip()])
                break
        if exits is not None:
            break
    tiles = []
    if is_today:
        tiles += [("Live games now", num(last.get("live_games")), ""), ("Flags shown now", num(last.get("flags_shown")), "")]
    else:
        tiles += [("Peak live games", num(max(g(rows, "live_games") or [0])), ""), ("Peak flags shown", num(max(g(rows, "flags_shown") or [0])), "")]
    tiles += [
        ("False / missed flags", f"{sum(int(x or 0) for x in g(rows, 'flags_false'))} / {sum(int(x or 0) for x in g(rows, 'flags_missed'))}", "good" if fm == 0 else "bad"),
        ("Graded on finals", (f"{num(res.get('won'))}-{num(res.get('lost'))}" if res else "after the close"),
         "" if not res else ("good" if (res.get("hit_pct") or 0) >= (res.get("fair_pct") or 0) else "warn")),
        ("Hit vs book fair", (f"{num(res.get('hit_pct'), 1, '%')} vs {num(res.get('fair_pct'), 1, '%')}" if res else "–"), ""),
        ("Board-process crashes", "–" if exits is None else str(exits), "" if exits is None else ("good" if exits == 0 else "warn")),
        ("Reversed neutral-site games (no model)", str(len(reversed_games)) if extra else "–", "" if not extra else ("good" if not reversed_games else "warn")),
        ("College totals below the score", "–" if floor is None else str(floor), "" if floor is None else ("good" if floor == 0 else "bad")),
        ("Card contradictions", "–" if contra is None else str(contra), "" if contra is None else ("good" if contra == 0 else "bad")),
    ]
    return '<div class="tiles">' + "".join(f'<div class="tile {c}"><div class="v">{v}</div><div class="k">{esc(k)}</div></div>' for k, v, c in tiles) + "</div>"


def charts(rows):
    main = line_chart(rows, [("live games", lambda r: r.get("live_games"), "var(--s1)"),
                             ("flags shown", lambda r: r.get("flags_shown"), "var(--s2)"),
                             ("dark rows (flag's price > 300 s old)", lambda r: r.get("dark_rows"), "var(--s3)"),
                             ("games with no live model", lambda r: r.get("live_games_no_model"), "var(--bad)")],
                      label="Live games, flags, dark rows and games with no live model per reading")
    fresh = line_chart(rows, [("live rows priced on a quote <= 120 s, %", fresh_share, "var(--good)")], ymax=100, suffix="%",
                       label="Share of live rail rows priced on a quote at most 120 s old")
    return card("Flags and fresh quotes through the day", main + '<div style="height:10px"></div>' + fresh)


GRADE_SPLITS = [("P3_first_reading:yes", "P3 · flags on a game's first reading"), ("P3_first_reading:no", "P3 · later readings"),
                ("P4_fair:lt_0.40", "P4 · book fair under 40%"), ("P4_fair:ge_0.40", "P4 · book fair 40% or more"),
                ("P5_ncaab_full_totals:ALL", "P5 · men's college full-game totals, calibrated"),
                ("P5_ncaab_full_totals:under", "P5 · of which unders"), ("P5_ncaab_full_totals:over", "P5 · of which overs")]


def grading(day, results, label_day=None):
    rs = [x for x in results if x.get("day") == day]
    if not rs:
        return card("Did the flags carry anything?", '<p class="note">Graded on the finals at the nightly close.</p>')
    order = {"all": 0, "sport": 1, "market": 2}
    rs.sort(key=lambda x: (order.get(x.get("kind"), 3), -(x.get("flags") or 0)))
    gr = grade_for(day)

    def row(name, flags, games, won, lost, hit, fair, lo, hi, strong=False):
        ci = f"[{num(lo, 1)}, {num(hi, 1)}]" if lo is not None else "–"
        n = f"<b>{esc(name)}</b>" if strong else esc(name)
        return f"<tr><td>{n}</td><td>{num(flags)}</td><td>{num(games)}</td><td>{num(won)}-{num(lost)}</td><td>{num(hit, 1, '%')} vs {num(fair, 1, '%')}</td><td>{ci}</td></tr>"

    trs = [row(x["scope"], x.get("flags"), x.get("games"), x.get("won"), x.get("lost"), x.get("hit_pct"), x.get("fair_pct"),
               x.get("ci90_lo_pp"), x.get("ci90_hi_pp"), x.get("kind") == "all") for x in rs]
    note = "Brackets are 90% intervals on hit rate minus book fair, in points, resampled by game."
    if gr:
        b = gr.get("buckets") or {}
        splits = [(lbl, b[k]) for k, lbl in GRADE_SPLITS if isinstance(b.get(k), dict) and b[k].get("graded")]
        if splits:
            trs.append('<tr><td colspan="6"><b>Registered in advance</b></td></tr>')
            for lbl, v in splits:
                ci = v.get("hit_minus_fair_ci90")
                trs.append(row(lbl, v.get("graded"), v.get("games"), v.get("win"), v.get("loss"),
                               (v.get("hit_rate") or 0) * 100, (v.get("mean_fair_p") or 0) * 100,
                               ci[0] * 100 if ci else None, ci[1] * 100 if ci else None))
        a = b.get("ALL") or {}
        if a.get("mean_model_p") and a.get("hit_rate") is not None:
            gap = (a["mean_model_p"] - a["hit_rate"]) * 100
            note = (f"<b>Calibration:</b> the model's own average probability on these flags was {a['mean_model_p'] * 100:.1f}% against a "
                    f"{a['hit_rate'] * 100:.1f}% hit rate, {gap:+.1f} points ({'over' if gap > 0 else 'under'}-confident on the flagged side). " + note)
        if gr.get("p5_flagged_lines_went_over"):
            note += f" P5's flagged lines went over {esc(gr['p5_flagged_lines_went_over'])}."
    title = "Did the flags carry anything?" + (f" (latest graded day, {day_label(day)})" if label_day else "")
    return card(title, '<div class="tblwrap"><table><thead><tr><th>Population</th><th>Flags</th><th>Games</th><th>Record</th>'
                       '<th>Hit vs book fair</th><th>90% CI, pp</th></tr></thead><tbody>' + "".join(trs) + "</tbody></table></div>", note)


def nomodel(extra, rows):
    last = extra[-1] if extra else {}
    # priced rows only from 11-21 (the same rule as the row's live_games_no_model); older lines count every row
    dark = [o for o in (last.get("orient") or []) if o.get("matchup")
            and ((o.get("priced") and not o.get("priced_with_model")) if "priced" in o else not o.get("with_model"))]
    items = "".join(
        f"<li>{esc(o['sport'].upper())} {esc(o['matchup'])}: {o.get('rows')} rows, "
        + ("teams REVERSED against the re-sim (I-29: the slate reoriented a neutral-site game)" if o.get("resim") == "REVERSED"
           else ("not matched in the re-sim snapshot" if o.get("resim") == "not_in_resim"
                 else esc("the live snapshot is stale, so a game that started since is absent: " + str(o.get("detail") or ""))
                 if o.get("resim") == "snapshot_stale"
                 else "re-simmed, but no row carries its model (join defect?)" if o.get("reason") == "resimmed"
                 else esc("the re-sim refused it: " + str(o.get("reason") or "reason not recorded (before 11-21)")
                          + (f" ({o['detail']})" if o.get("detail") else "")))) + "</li>"
        for o in dark)
    rev = sorted({o["matchup"] for x in extra for o in (x.get("orient") or []) if o.get("resim") == "REVERSED"})
    peak = max(g(rows, "live_games_no_model") or [0]) if g(rows, "live_games_no_model") else None
    inner = (f"<ul>{items or '<li>None at the latest reading.</li>'}</ul>" if extra else
             f"<p>Peak live games with no model on any line: {num(peak)}. Per-game causes are recorded from 11-20 on.</p>")
    if rev:
        inner += "<p><b>Reversed neutral-site games today:</b> " + ", ".join(esc(x) for x in rev) + ".</p>"
    return card("Games with no live model", inner,
                "Causes seen: the neutral-site orientation miss (I-29, fix #854 in the 11-24 window), NHL live lanes that flicker between builds (I-30), "
                "NFL totals with no distribution, and women's college games refused for a missing pregame anchor.")


def memory(extra):
    if not extra:
        return ""
    last = extra[-1]
    lines = "<br>".join(esc(l) for l in (last.get("p7") or [])) or "–"
    procs = ", ".join(f"{esc(p[3])} {int(p[1]) / 1024 / 1024:.2f} GB" for p in (last.get("ps") or []) if len(p) >= 4 and str(p[1]).isdigit()) or "–"
    return card("Board memory guard (#850)", f"<div class='mono'>{lines}</div><p class='note'>Processes now: {procs}</p>",
                "Counted since 5 AM CST. The owner's evening prediction: refusals <= 1 an hour and <= 3 in total; <= 2 exits, all clean (rc 75); "
                "longest gap between builds <= 900 s.")


def refresh_load(rows):
    eve = [r for r in rows if "23:30" <= r["at"][11:16] or r["at"][11:16] <= "04:30"]
    eg = g(eve, "board_pub_gap_max_s")
    em = g(eve, "board_pub_gap_median_s")
    ref = [("Live-price gaps over 360 s", num(sum(int(x or 0) for x in g(rows, "overlay_gaps_over_360"))) + f" (longest {num(max(g(rows, 'overlay_gap_max_s') or [0]))} s)"),
           ("Board rebuild, median / longest", f"{num(p50(g(rows, 'board_wall_median_s')))} s / {num(max(g(rows, 'board_wall_max_s') or [0]))} s"),
           ("Board publication gap, evening median / longest", f"{num(p50(em))} s / {num(max(eg) if eg else None)} s"),
           ("Longest publication gap, any time", f"{num(max(g(rows, 'board_pub_gap_max_s') or [0]))} s"),
           ("Live odds refreshes turned away, per reading", f"{num(min(g(rows, 'sweeps_refused_pct') or [0]))}–{num(max(g(rows, 'sweeps_refused_pct') or [0]))}%"),
           ("Longest live odds run", f"{num(max(g(rows, 'live_run_max_s') or [0]))} s")]
    ld = [("Page's board query", f"{num(min(g(rows, 'query_s') or [0]), 1)}–{num(max(g(rows, 'query_s') or [0]), 1)} s (median {num(p50(g(rows, 'query_s')), 1)})"),
          ("Board page (/intelligence)", f"{num(min(g(rows, 'page_s') or [0]), 1)}–{num(max(g(rows, 'page_s') or [0]), 1)} s" if g(rows, "page_s") else "–"),
          ("Shortlist", f"up to {num(max(g(rows, 'shortlist_s') or [0]), 1)} s"),
          ("Game chips", f"up to {num(max(g(rows, 'chips_s') or [0]), 1)} s")]
    return (f'<div class="two"><div>{card("Refresh", kv_table(ref))}</div><div>{card("Load", kv_table(ld), "Cold board reads after web worker restarts drive most of the query time (I-28; fix #853 in the 11-24 batch).")}</div></div>')


def teams(rows):
    defects = sum(int(x or 0) for x in g(rows, "team_defects"))
    contra = sum(int(x or 0) for x in g(rows, "ours_contradictions")) if g(rows, "ours_contradictions") else None
    below = sum(int(x or 0) for x in g(rows, "ours_below_points")) if g(rows, "ours_below_points") else None
    chips = max(g(rows, "chips_today") or [0])
    txt = (f"<p>{num(chips)} game cards on the slate. Flipped, chip-less or detail defects across {len(rows)} readings: <b>{defects}</b>. "
           f"Cards with \"ours\" on the wrong side of the flagged line: <b>{num(contra)}</b>. College cards whose \"ours\" total sat below the score already scored: <b>{num(below)}</b>.</p>")
    return card("Teams on the rail", txt)


def readings_table(rows, limit=80):
    trs = []
    for r in reversed(rows[-limit:]):
        trs.append("<tr>" + "".join(f"<td>{c}</td>" for c in [
            esc(fmt_ct(r["at"])), num(r.get("live_games")), num(r.get("flags_shown")),
            f"{num(r.get('flags_false'))} / {num(r.get('flags_missed'))}", num(r.get("dark_rows")), num(r.get("live_games_no_model")),
            num(fresh_share(r), 0, "%"), num(r.get("floor_violations")), f"{num(r.get('board_pub_gap_median_s'))} / {num(r.get('board_pub_gap_max_s'))}",
            num(r.get("query_s"), 1), num(r.get("live_rows")), num(r.get("host_load"), 1)]) + "</tr>")
    return card("Readings", '<div class="tblwrap"><table><thead><tr><th>Time (CST)</th><th>Live</th><th>Flags</th><th>False / missed</th><th>Dark rows</th>'
                            '<th>No-model games</th><th>Fresh quotes</th><th>Floor viol.</th><th>Board gap med / max s</th><th>Query s</th><th>Rail rows</th>'
                            f'<th>Host load</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>')


def writeup(day):
    md = summary_md(findings_text(day))
    if not md:
        return ""
    page = DAY_PAGES.get(day)
    link = f' · <a href="{page}" target="_blank" rel="noopener">the day page</a>' if page else ""
    return (f'<h2>The day\'s write-up</h2><div class="card"><details><summary>Daily summary from the monitor\'s findings{link}</summary>'
            f'<div class="md">{md_to_html(md)}</div></details></div>')


def decisions(days):
    for d in reversed(days):
        md = summary_md(findings_text(d))
        sec = subsection(md, r"Open user decisions") if md else ""
        if sec:
            return card(f"Decisions waiting on you (from the {day_label(d)} close)", f'<div class="md">{md_to_html(sec)}</div>')
    return ""


def day_section(day, today, rows, extra, results, days):
    is_today = day == today
    parts = [strip_tiles(day, rows, extra, results, is_today)]
    if is_today:
        parts.append(decisions([d for d in days if d < today]))
    parts.append(charts(rows))
    graded = [x["day"] for x in results if x.get("kind") == "all" and x["day"] <= day]
    gday = day if any(x.get("day") == day for x in results) else (max(graded) if is_today and graded else day)
    parts.append(grading(gday, results, label_day=(gday != day)))
    parts.append(nomodel(extra, rows))
    parts.append(memory(extra))
    parts.append(refresh_load(rows))
    parts.append(teams(rows))
    if not is_today:
        parts.append(writeup(day))
    parts.append(readings_table(rows))
    return "".join(p for p in parts if p)


# ------------------------------------------------------------------ product (the live dashboard's other sections)

def board_section():
    br = load_json(os.path.join(DASH, "board_results.json"), [])
    if not br:
        return ""
    sets = ["Whole board", "Published to the shortlist", "Suggested by the board", "Staked by the portfolio (paper)"]
    days = sorted({x["day"] for x in br})
    last = days[-1]
    # bet-weighted across sports, per day and set
    agg = {}
    for x in br:
        if x.get("roi_pct") is None or not x.get("bets"):
            continue
        a = agg.setdefault((x["day"], x["set"]), [0.0, 0])
        a[0] += x["roi_pct"] * x["bets"]
        a[1] += x["bets"]
    recent = days[-30:]
    pts = [{"xl": d[5:], **{s: (agg[(d, s)][0] / agg[(d, s)][1] if (d, s) in agg and agg[(d, s)][1] else None) for s in sets}} for d in recent]
    vals = [p[s] for p in pts for s in sets if p.get(s) is not None]
    lo = min(-5, int((min(vals) if vals else -5) // 5 * 5))
    hi = max(5, int(-(-(max(vals) if vals else 5) // 5) * 5))
    colors = ["var(--s1)", "var(--s2)", "var(--good)", "var(--bad)"]
    ch = line_chart(pts, [(s, (lambda r, s=s: r.get(s)), c) for s, c in zip(sets, colors)], ymin=lo, ymax=hi, suffix="%",
                    label="28-day ROI by set, bet-weighted across sports, per scorecard day")
    rows = [x for x in br if x["day"] == last]
    rows.sort(key=lambda x: (sets.index(x["set"]) if x["set"] in sets else 9, x["sport"]))
    trs = "".join(f"<tr><td>{esc(x['set'])}</td><td>{esc(x['sport'])}</td><td>{num(x.get('bets'))}</td><td>{num(x.get('roi_pct'), 1, '%')}</td>"
                  f"<td>{('[' + num(x.get('roi_ci95_lo_pct'), 1) + ', ' + num(x.get('roi_ci95_hi_pct'), 1) + ']') if x.get('roi_ci95_lo_pct') is not None else '–'}</td>"
                  f"<td>{num(x.get('predicted_ev_pct'), 1, '%')}</td></tr>" for x in rows)
    return card("Board, shortlist, suggested and staked results", ch +
                f'<p class="note">Bet-weighted 28-day ROI across sports, one point per scorecard day ({esc(recent[0])} to {esc(last)}). The darker grid line is 0%.</p>'
                f'<div class="tblwrap"><table><thead><tr><th>Set</th><th>Sport</th><th>Bets</th><th>ROI</th><th>95% CI</th><th>Predicted EV</th></tr></thead><tbody>{trs}</tbody></table></div>',
                f"Scorecard day {esc(last)} (28-day rolling, from the fleet's daily model scorecard and the suggested-set grader).")


def cheat_section():
    cs = load_json(os.path.join(DASH, "cheat_sections.json"), [])
    if not cs:
        return ""
    trs = "".join(f"<tr><td>{esc(x.get('section'))}</td><td>{esc(x.get('season_record'))}</td><td>{num(x.get('season_roi_pct'), 1, '%')}</td>"
                  f"<td>{esc(x.get('season_verdict'))}</td><td>{esc(x.get('last7_record'))}</td><td>{num(x.get('last7_roi_pct'), 1, '%')}</td>"
                  f"<td>{esc(x.get('last7_verdict'))}</td><td>{num(x.get('vs_fair_pts'), 1)} [{num(x.get('vs_fair_lo'), 1)}, {num(x.get('vs_fair_hi'), 1)}]</td></tr>" for x in cs)
    return card("Cheat sheet picks", '<div class="tblwrap"><table><thead><tr><th>Section</th><th>Season</th><th>ROI</th><th>Verdict</th><th>Last 7</th>'
                                     f'<th>ROI</th><th>Verdict</th><th>vs fair, pts</th></tr></thead><tbody>{trs}</tbody></table></div>',
                f"From the cheat sheets' daily review, {esc(cs[0].get('day'))}.")


def static_table(path, title, cols, note=""):
    data = load_json(os.path.join(DASH, path), [])
    if not data:
        return ""
    trs = "".join("<tr>" + "".join(f"<td>{esc(x.get(k))}</td>" for k, _ in cols) + "</tr>" for x in data)
    return card(title, '<div class="tblwrap"><table class="txt"><thead><tr>' + "".join(f"<th>{esc(h)}</th>" for _, h in cols)
                + f"</tr></thead><tbody>{trs}</tbody></table></div>", note)


def product_section():
    loads = load_json(os.path.join(DASH, "loads.json"), [])
    loads_html = ""
    if loads:
        trs = "".join(f"<tr><td>{esc(x.get('at', '')[:10])} {esc(x.get('time'))}</td><td>{esc(x.get('change'))}</td><td>{esc(x.get('betting_change'))}</td><td>{esc(x.get('how'))}</td></tr>"
                      for x in sorted(loads, key=lambda x: x.get("at", ""), reverse=True))
        loads_html = card("Loads on the fleet", '<div class="tblwrap"><table class="txt"><thead><tr><th>When (CST)</th><th>Change</th><th>Betting change</th><th>How</th></tr></thead>'
                                              f"<tbody>{trs}</tbody></table></div>", "Kept by the monitor's nightly close from deploys.md.")
    return (board_section() + cheat_section()
            + static_table("levers.json", "Optimization levers", [("id", "#"), ("tier", "Tier"), ("lever", "Lever"), ("evidence", "Evidence"),
                                                                    ("clears", "Clears noise?"), ("betting_change", "Betting change"), ("owner", "Owner")],
                           "From the optimization program's ranked levers.")
            + static_table("findings.json", "Monitor findings and predictions", [("id", "#"), ("kind", "Kind"), ("title", "Finding"), ("status", "Status"), ("owner", "Owner")],
                           "The live dashboard's findings list (kept through 11-19); newer findings are in each day's write-up.")
            + loads_html)


# ------------------------------------------------------------------ all days

def all_days_section(days, rows_by, results):
    trs, pts = [], []
    for d in reversed(days):
        rows = rows_by[d]
        res = next((x for x in results if x.get("day") == d and x.get("kind") == "all"), None)
        eve = [r.get("board_pub_gap_max_s") for r in rows if r.get("board_pub_gap_max_s") is not None and ("23:30" <= r["at"][11:16] or r["at"][11:16] <= "04:30")]
        page = DAY_PAGES.get(d)
        trs.append("<tr>" + "".join(f"<td>{c}</td>" for c in [
            f'<a href="#day-{d}" data-day="{d}">{esc(day_label(d))}</a>', num(len(rows)), num(max(g(rows, "live_games") or [0])),
            num(max(g(rows, "flags_shown") or [0])), f"{sum(int(x or 0) for x in g(rows, 'flags_false'))} / {sum(int(x or 0) for x in g(rows, 'flags_missed'))}",
            num(max(g(rows, "live_games_no_model")) if g(rows, "live_games_no_model") else None),
            num(sum(int(x or 0) for x in g(rows, "floor_violations")) if g(rows, "floor_violations") else None),
            num(max(eve) if eve else None, 0, " s"), num(p50(g(rows, "query_s")), 1, " s"),
            (f"{num(res.get('won'))}-{num(res.get('lost'))}" if res else "–"),
            (f"{num(res.get('hit_pct'), 1, '%')} vs {num(res.get('fair_pct'), 1, '%')}" if res else "–"),
            (f"[{num(res.get('ci90_lo_pp'), 1)}, {num(res.get('ci90_hi_pp'), 1)}]" if res and res.get("ci90_lo_pp") is not None else "–"),
            (f'<a href="{page}" target="_blank" rel="noopener">page</a>' if page else "–")]) + "</tr>")
        if res and res.get("hit_pct") is not None:
            pts.append((d, res))
    pts.reverse()
    chart = ""
    if len(pts) >= 2:
        fake = [{"xl": d[5:], "hit": r["hit_pct"], "fair": r["fair_pct"]} for d, r in pts]
        chart = line_chart(fake, [("flags won, %", lambda r: r["hit"], "var(--s1)"), ("book fair (break-even), %", lambda r: r["fair"], "var(--mute)")],
                           ymin=30, ymax=70, suffix="%", label="Graded flag hit rate against book fair, by day")
    return (f'<h2>All days, {esc(days[0])} to {esc(days[-1])}</h2><div class="card">{chart}</div>'
            '<div class="card" style="margin-top:12px"><div class="tblwrap"><table><thead><tr><th>Day</th><th>Readings</th><th>Peak live</th>'
            '<th>Peak flags</th><th>False / missed</th><th>Peak no-model</th><th>Floor viol.</th><th>Board gap, evening max</th>'
            f'<th>Query p50</th><th>Graded W-L</th><th>Hit vs fair</th><th>90% CI pp</th><th>Day page</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>'
            '<p class="note">Graded columns come from the nightly close (finals by date, first sighting of each flag). 11-15..11-17 rows were rebuilt '
            'from the saved readings, without the fleet-log columns (board gaps, sweeps), which had rotated.</p></div>')


# ------------------------------------------------------------------ page

CSS = """
:root { --bg:#f7f6f2; --card:#fff; --ink:#1d1c1a; --mute:#6b6862; --line:#e4e1da; --s1:#2f6fd0; --s2:#c77d10; --s3:#8a5cc7; --bad:#c2402a; --good:#2f8a4f; --warn:#b7791f; }
@media (prefers-color-scheme: dark) { :root { --bg:#141413; --card:#1e1d1b; --ink:#ecebe7; --mute:#a19e97; --line:#33312d; --s1:#6aa1f0; --s2:#e3a447; --s3:#b48ef0; --bad:#e86f5a; --good:#5cc27f; --warn:#e0a84a; } }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif; }
.wrap { max-width:1150px; margin:0 auto; padding:18px 16px 40px; } h1 { font-size:26px; margin:0 0 4px; } h2 { font-size:17px; margin:24px 0 10px; }
.sub { color:var(--mute); font-size:13px; } a { color:var(--s1); }
.days { display:flex; flex-wrap:wrap; gap:6px; margin:12px 0 4px; } .days a { padding:5px 11px; border:1px solid var(--line); border-radius:999px; color:var(--ink); text-decoration:none; font-size:13px; background:var(--card); } .days a.on { background:var(--ink); color:var(--bg); }
.tiles { display:grid; grid-template-columns:repeat(auto-fill,minmax(165px,1fr)); gap:10px; margin-top:14px; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; } .tile .v { font-size:22px; font-weight:700; font-variant-numeric:tabular-nums; }
.tile .k { color:var(--mute); font-size:12px; margin-top:2px; } .tile.good .v { color:var(--good); } .tile.bad .v { color:var(--bad); } .tile.warn .v { color:var(--warn); }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; } .tblwrap { overflow-x:auto; }
svg { width:100%; height:auto; display:block; } .grid { stroke:var(--line); } .grid.zero { stroke:var(--mute); } .ax { fill:var(--mute); font-size:11px; }
.legend { display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--mute); margin-bottom:6px; } .legend i { display:inline-block; width:12px; height:3px; margin-right:6px; vertical-align:middle; }
table { border-collapse:collapse; width:100%; font-size:13px; font-variant-numeric:tabular-nums; } th,td { text-align:right; padding:5px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th:first-child,td:first-child { text-align:left; } th { color:var(--mute); font-weight:600; white-space:nowrap; }
table.kv td:last-child { text-align:right; white-space:nowrap; } table.txt td, table.txt th { text-align:left; } .md table td, .md table th { text-align:left; white-space:normal; }
.md { font-size:14px; } .md h3,.md h4,.md h5 { font-size:15px; margin:14px 0 6px; } .md ul,.md ol { margin:4px 0; padding-left:20px; } .md code, .mono { font-family:ui-monospace,Consolas,monospace; font-size:12px; }
.mono { white-space:pre-wrap; color:var(--mute); } ul { margin:6px 0; padding-left:20px; } .note { color:var(--mute); font-size:13px; margin:8px 0 0; }
.two { display:grid; grid-template-columns:1fr 1fr; gap:14px; } @media (max-width:760px) { .two { grid-template-columns:1fr; } }
details summary { cursor:pointer; color:var(--s1); }
"""

JS = ("<script>(function(){function show(k){document.querySelectorAll('section.day').forEach(function(s){s.hidden=(s.dataset.day!==k)});"
      "document.querySelectorAll('nav.days a').forEach(function(a){a.classList.toggle('on',a.dataset.day===k)})}"
      "function fromHash(){var h=(location.hash||'').replace('#day-','');show(h&&document.querySelector('section.day[data-day=\"'+h+'\"]')?h:'today')}"
      "document.addEventListener('click',function(e){var a=e.target.closest('a[data-day]');if(!a)return;e.preventDefault();"
      "try{history.replaceState(null,'','#day-'+a.dataset.day)}catch(x){}show(a.dataset.day);window.scrollTo(0,0)});"
      "window.addEventListener('hashchange',fromHash);fromHash()})();</script>")


def all_days(today):
    days = {today}
    for p in glob.glob(os.path.join(DASH, "rows_20*.jsonl")):
        days.add(os.path.basename(p)[5:15])
    if os.path.exists(os.path.join(DASH, "rows.jsonl")):
        days.add("2026-11-18")
    return sorted(d for d in days if d <= today)


def render_all(today):
    results = load_json(os.path.join(DASH, "rail_results.json"), [])
    days = all_days(today)
    rows_by = {d: sorted(read_jsonl(rows_path(d)), key=lambda r: r["at"]) for d in days}
    extra_by = {d: read_jsonl(os.path.join(OUT, f"extra_{d}.jsonl")) for d in days}
    updated = dt.datetime.now(CT).strftime("%a %b %d, %#I:%M %p CST" if os.name == "nt" else "%a %b %d, %-I:%M %p CST")
    nav = ('<nav class="days"><a href="#day-today" data-day="today" class="on">Today</a>'
           + "".join(f'<a href="#day-{d}" data-day="{d}">{esc(d[5:])}</a>' for d in reversed(days) if d != today)
           + '<a href="#day-all" data-day="all">All days</a><a href="#day-product" data-day="product">Product</a></nav>')
    sections = [f'<section class="day" data-day="today"><div class="sub">Slate {esc(today)} · {len(rows_by[today])} readings so far</div>'
                + day_section(today, today, rows_by[today], extra_by[today], results, days) + "</section>"]
    for d in reversed(days):
        if d == today:
            continue
        sections.append(f'<section class="day" data-day="{d}" hidden><h2 style="margin-top:6px">{esc(day_label(d))}</h2>'
                        + day_section(d, today, rows_by[d], extra_by[d], results, days) + "</section>")
    sections.append('<section class="day" data-day="all" hidden>' + all_days_section(days, rows_by, results) + "</section>")
    sections.append('<section class="day" data-day="product" hidden>' + product_section() + "</section>")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta http-equiv="refresh" content="300"><title>Rail Watch</title><style>{CSS}</style></head><body><div class="wrap">'
            f'<h1>Rail Watch</h1><div class="sub">Layer 2 Games Rail on the fleet · updated {esc(updated)} · rewritten every ~20 min by the SyndicateRailWatch task, '
            f'no Claude involved · the original live dashboard (frozen 11-19): <a href="{LIVE_DASH}" target="_blank" rel="noopener">Rail Watch (live)</a></div>'
            + nav + "".join(sections) + "</div>" + JS + "</body></html>")
