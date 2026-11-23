"""Self-contained Portfolio Watch: one HTML file with its data inside, rebuilt locally with no Claude involved.

Reads the page data `build_page_data.py` writes (paths.PAGE / {readings,performance,findings}.json) and the S8
collector's heartbeat, and publishes dashboard.html atomically to paths.PAGE, paths.LOCAL_PAGE_COPY and paths.FLEET_PAGE. Open it in any browser; it
reloads itself every 5 minutes and says when its data is stale. Counts and percentages only, like the source data.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import paths  # noqa: E402
PAGE = paths.PAGE
OUT = PAGE / "dashboard.html"


def load(name: str):
    try:
        return json.loads((PAGE / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"rows": [], "meta": []}


def publish(html: str, target: Path) -> str:
    """Atomic: write <target>.tmp in the same folder, then rename it over the target, so a reader never sees half a
    page. A target that cannot be written (e.g. WSL not running, for the fleet copy) is reported, not fatal."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(html, encoding="utf-8")
        os.replace(tmp, target)
        return f"wrote {target}"
    except OSError as e:
        return f"FAILED {target}: {e}"


def load_history():
    try:
        return json.loads((paths.HISTORY / "daily_rollup.json").read_text(encoding="utf-8")).get("rows", [])
    except (OSError, ValueError):
        return []


def main() -> int:
    s8 = {}
    try:
        s8 = json.loads(paths.S8_HEARTBEAT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    readings, performance, findings = load("readings"), load("performance"), load("findings")
    try:
        hist_meta = json.loads((paths.HISTORY / "daily_rollup.json").read_text(encoding="utf-8")).get("meta", [])
    except (OSError, ValueError):
        hist_meta = []
    # Sources: each dataset's own notes, as the original page's Sources panel showed them (code entries left out).
    sources = [{"dataset": name, "label": m.get("label"), "value": m.get("value")}
               for name, meta in (("readings", readings.get("meta")), ("performance", performance.get("meta")),
                                  ("findings", findings.get("meta")), ("daily history", hist_meta))
               for m in (meta or []) if m.get("type") != "code"]
    data = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        # Every reading (the original page drew all of them), capped so the page stays small.
        "readings": readings.get("rows", [])[-1500:],
        "performance": performance.get("rows", []),
        "findings": findings.get("rows", []),
        "s8": s8,
        "history": load_history(),
        "sources": sources,
    }
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", blob)
    for target in (OUT, paths.LOCAL_PAGE_COPY, paths.FLEET_PAGE):
        print(publish(html, target))
    print(f"{len(html) // 1024} KB, {len(data['readings'])} readings, {len(data['history'])} history days")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Portfolio Watch</title>
<style>
:root { --bg:#faf9f6; --panel:#ffffff; --fg:#1f1e1c; --muted:#6b6862; --line:#e4e1da; --ok:#2f7d4f; --warn:#a86a00; --bad:#b3372f;
  --s1:#3b6fb6; --s2:#c2702d; --s3:#7a5aa6; --s4:#2f8f8a; --band:rgba(59,111,182,.14); }
@media (prefers-color-scheme: dark) { :root { --bg:#1b1a18; --panel:#24231f; --fg:#ecebe6; --muted:#a29f97; --line:#3a3833;
  --ok:#5fbf86; --warn:#e0a43a; --bad:#ef7b70; --s1:#7aa7e6; --s2:#e69a5c; --s3:#b294dc; --s4:#62c2bc; --band:rgba(122,167,230,.18); } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1180px; margin:0 auto; padding:20px 16px 48px; display:grid; gap:22px; }
h1 { font:400 1.7rem/1.2 Georgia,"Times New Roman",serif; margin:0; }
h2 { font-size:.8rem; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); margin:0 0 8px; font-weight:600; }
.muted { color:var(--muted); font-size:.85rem; }
.take { margin:6px 0 0; max-width:75ch; line-height:1.5; }
.take b { font-variant-numeric:tabular-nums; }
section > .muted { margin:0 0 10px; max-width:95ch; }
.stale { color:var(--bad); font-weight:600; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; }
.tile { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; display:grid; gap:4px; min-width:0; }
.tile h3 { margin:0; font-size:.72rem; letter-spacing:.05em; text-transform:uppercase; color:var(--muted); font-weight:600; }
.big { font:400 1.65rem/1.15 Georgia,serif; font-variant-numeric:tabular-nums; }
.sub { font-size:.82rem; color:var(--muted); font-variant-numeric:tabular-nums; }
.ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
section { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px; min-width:0; }
.chart { width:100%; height:auto; display:block; }
.legend { display:flex; flex-wrap:wrap; gap:14px; font-size:.8rem; color:var(--muted); margin-top:6px; }
.legend i { display:inline-block; width:12px; height:3px; vertical-align:middle; margin-right:5px; border-radius:2px; }
.tablewrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:.84rem; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); font-weight:600; white-space:nowrap; }
td.num { text-align:right; white-space:nowrap; }
.anoms { margin:6px 0 0; padding-left:18px; }
.pill { display:inline-block; padding:1px 7px; border-radius:999px; font-size:.72rem; border:1px solid var(--line); }
#tip { position:fixed; pointer-events:none; background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:5px 8px;
  font-size:.8rem; display:none; box-shadow:0 2px 8px rgba(0,0,0,.15); z-index:5; }
</style>
</head>
<body>
<main>
  <header id="summary">
    <h1>Portfolio Watch</h1>
    <p class="take" id="take1"></p>
    <p class="take" id="take2"></p>
    <p class="muted">A read-only watch of the fleet's portfolio page and its APIs, one reading every 30 minutes, built
      without Claude. Counts, rates and percentages only; no balances or stakes.</p>
    <div class="muted" id="asof"></div>
  </header>
  <div>
    <h2>Live book results (ROI on stake, net of fees, 95% range clustered by event)</h2>
    <div class="tiles" id="perf"></div>
  </div>
  <div>
    <h2>System</h2>
    <div class="tiles" id="status"></div>
  </div>
  <section id="alignment"><h2>Purchaser vs Layer 2 board and rail</h2>
    <p class="muted">What the purchaser buys, against what the board recommends and the rail shows. Suggested rows are
      the board's picks; a live plan buys any row that clears the venue's fee at the venue's own price, Suggested or
      not, and stakes follow price until a model is shown to beat the market. Today's orders are matched to the board
      as it is now, so a row that moved after the purchase reads as another line or off the board. Informational:
      no anomaly is raised from this panel.</p>
    <div class="tiles" id="align-tiles"></div>
    <svg class="chart" id="align" style="margin-top:12px"></svg><div class="legend" id="align-legend"></div></section>
  <section id="history"><h2 id="hist-title">History</h2><svg class="chart" id="hist"></svg><div class="legend" id="hist-legend"></div>
    <div class="tablewrap" style="margin-top:12px"><table id="hist-table"></table></div></section>
  <section><h2>30-day ROI over readings</h2><svg class="chart" id="roi"></svg><div class="legend" id="roi-legend"></div></section>
  <section id="latency"><h2>Response time per reading</h2>
    <p class="muted">Seconds for each portfolio read the probe makes. Budgets: live 3 s, all-dates ledger 5 s, plan 6 s,
      page 3 s. Point at the chart for every series against its budget.</p>
    <svg class="chart" id="lat"></svg><div class="legend" id="lat-legend"></div></section>
  <section id="performance"><h2>Where the live book makes and loses money</h2>
    <p class="muted">Graded live bets. ROI is profit over stake, net of venue fees, with a 95% range clustered by game
      (bets on one game count as one draw). Window rows cover yesterday, the last 7 and 30 days and all time; slices
      cover the last 30 days and show only groups of 10 or more bets. Green = profitable beyond noise, red = losing
      beyond noise. A slice is evidence for fixing individual lines, never for switching off a sport or market.</p>
    <div class="tablewrap"><table id="slices"></table></div></section>
  <section id="findings-sec"><h2>Findings, anomalies and performance signals</h2>
    <p class="muted">Findings are diagnosed problems with an owner; anomalies are what the latest reading flagged;
      performance signals are 30-day slices whose result is beyond noise.</p>
    <div class="tablewrap"><table id="findings"></table></div></section>
  <section id="readings-sec"><h2>Readings</h2>
    <p class="muted">Newest first, every reading. Live ticks are the workers' live-mode execution passes in the
      reading's log window; refusals are summed over them.</p>
    <div class="tablewrap"><table id="readings"></table></div></section>
  <section id="sources"><h2>Sources</h2><div class="tablewrap"><table id="sources-table"></table></div></section>
</main>
<div id="tip"></div>
<script type="application/json" id="data">__DATA__</script>
<script>
(function () {
  const D = JSON.parse(document.getElementById("data").textContent);
  const R = D.readings || [];
  const last = R[R.length - 1] || {};
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const num = (v, d = 1) => (v == null || v === "" || isNaN(+v)) ? "—" : (+v).toFixed(d);
  const pct = (v, d = 2) => (v == null || isNaN(+v)) ? "—" : ((+v > 0 ? "+" : "") + (+v).toFixed(d) + "%");
  const cls = (lo, hi) => (hi != null && +hi < 0) ? "bad" : (lo != null && +lo > 0) ? "ok" : "";
  const ct = (iso) => { try { return new Date(iso).toLocaleString("en-US", { timeZone: "America/Chicago", month: "2-digit", day: "2-digit", hour: "numeric", minute: "2-digit" }); } catch (e) { return iso; } };

  // header
  const gen = new Date(D.generated_at), lastAt = last.at ? new Date(last.at) : null;
  const ageMin = lastAt ? (Date.now() - lastAt) / 60000 : Infinity;
  const asof = document.getElementById("asof");
  const bannerOk = last.banner_ok === "ok";
  const b = (t, c) => { const e = el("b", c || null, t); return e; };
  const take1 = document.getElementById("take1");
  take1.append("Latest reading ", b(last.label || "none"), ": ", b(String(last.endpoints_ok ?? "—")), " of ",
    b(String(last.endpoints ?? "—")), " portfolio endpoints answered, the live banner is ",
    b(last.banner_ok == null ? "—" : String(last.banner_ok), bannerOk ? "ok" : "bad"), ", and ",
    b(String(last.anomalies ?? "—"), (+last.anomalies) > 0 ? "warn" : "ok"), " anomalies are open.");
  const take2 = document.getElementById("take2");
  take2.append("Live book, last 30 days: ROI ", b(pct(last.d30_roi_pct), cls(last.d30_roi_lo95, last.d30_roi_hi95)),
    " (95% range ", b(num(last.d30_roi_lo95) + "%"), " to ", b(num(last.d30_roi_hi95) + "%"), ") on ",
    b(String(last.d30_events ?? "—")), " games, and ", b(String(last.perf_signals ?? "—")),
    " performance signals beyond noise.");
  asof.textContent = "Page built " + ct(D.generated_at) + " CT · " + R.length + " readings since " + (R[0] ? R[0].label : "—") + " · reloads every 5 min · no Claude involved";
  if (ageMin > 75) { const s = el("div", "stale", "Stale: the last reading is " + Math.round(ageMin) + " min old. Check the SyndicatePortfolioWatch task."); asof.after(s); }

  // performance tiles
  const perf = document.getElementById("perf");
  [["30 days", "d30"], ["7 days", "d7"], ["Yesterday", "yday"], ["All time", "all"]].forEach(([name, k]) => {
    const t = el("div", "tile");
    t.append(el("h3", null, name));
    t.append(el("div", "big " + cls(last[k + "_roi_lo95"], last[k + "_roi_hi95"]), pct(last[k + "_roi_pct"])));
    t.append(el("div", "sub", "[" + num(last[k + "_roi_lo95"]) + ", " + num(last[k + "_roi_hi95"]) + "] · " + (last[k + "_bets"] ?? "—") + " bets / " + (last[k + "_events"] ?? "—") + " events"));
    t.append(el("div", "sub", "won " + num(last[k + "_win_pct"]) + "% vs breakeven " + num(last[k + "_breakeven_pct"]) + "%"));
    perf.append(t);
  });
  const clv = el("div", "tile");
  clv.append(el("h3", null, "Fee-net CLV"));
  clv.append(el("div", "big " + ((+last.d30_clv_net_pp) < 0 ? "warn" : "ok"), (last.d30_clv_net_pp == null ? "—" : num(last.d30_clv_net_pp, 2) + " pp")));
  clv.append(el("div", "sub", "30 d; gross " + num(last.d30_clv_gross_pp, 2) + " pp · 7 d net " + num(last.d7_clv_net_pp, 2) + " pp"));
  perf.append(clv);

  // status tiles
  const st = document.getElementById("status");
  const tile = (name, big, bigCls, ...subs) => { const t = el("div", "tile"); t.append(el("h3", null, name)); t.append(el("div", "big " + (bigCls || ""), big)); subs.forEach(s => t.append(el("div", "sub", s))); st.append(t); return t; };
  tile("Live banner", last.banner_ok == null ? "—" : String(last.banner_ok).toUpperCase(), bannerOk ? "ok" : "bad", "worker state " + num(last.state_age_s, 0) + " s old (stale after 900 s)");
  tile("Plan positions", String(last.positions ?? "—"), "", (last.board_rows ?? "—") + " board rows, " + (last.suggested ?? "—") + " suggested, " + (last.sized ?? "—") + " sized", "plan " + num(last.plan_age_min) + " min old · max write gap " + num(last.tonight_plan_max_gap_min) + " min");
  tile("Orders today", String(last.orders_today ?? "—"), (+last.failed_or_rejected_today) > 0 ? "warn" : "", "failed/rejected " + (last.failed_or_rejected_today ?? 0) + " · resting " + (last.resting ?? 0), "late settlements " + (last.late_settlements ?? 0));
  tile("Scale-up gate", (last.gate_events ?? "—") + " of 800 events", "", "counted since " + (last.gate_clock || "—") + ", the last betting change");
  tile("Web worker kills", String(last.worker_timeouts ?? "—"), (+last.worker_timeouts) > 0 ? "bad" : "ok", "in the last " + (last.window_min ?? "—") + " min of the web log");
  tile("Cap use", num(last.kalshi_cap_pct) + "%", "", "Kalshi of day cap · Polymarket " + num(last.polymarket_cap_pct) + "%");
  tile("Paper book, all dates", num(last.paper_win_pct) + "% won", "", (last.paper_won ?? "—") + " won, " + (last.paper_lost ?? "—") + " lost of " + (last.paper_settled ?? "—") + " settled; ROI " + pct(last.paper_roi_pct), "Simulated, no money moves.");
  const anoms = (D.findings || []).filter(f => (f.kind || "").toLowerCase() === "anomaly");
  const at = tile("Open anomalies", String(last.anomalies ?? anoms.length), (+last.anomalies) > 0 ? "warn" : "ok", "late settlements " + (last.late_settlements ?? 0) + " · in the last reading");
  if (anoms.length) { const ul = el("ul", "anoms sub"); anoms.slice(0, 5).forEach(a => ul.append(el("li", null, a.title))); at.append(ul); }
  if (D.s8 && D.s8.at) {
    const age = (Date.now() - new Date(D.s8.at)) / 60000;
    tile("S8 collector", age < 5 ? "running" : "stalled?", age < 5 ? "ok" : "bad", "heartbeat " + Math.round(age) + " min ago (at page build)", "cycle " + D.s8.cycle + " · " + D.s8.markets + " markets · " + D.s8.errors + " errors");
  }

  // charts
  const tip = document.getElementById("tip");
  function lineChart(svgId, legendId, series, opts) {
    const R = opts.rows || D.readings || [], lab = opts.label || (r => ct(r.at));
    const svg = document.getElementById(svgId), W = Math.max(320, svg.parentNode.clientWidth - 28), H = 220, m = { l: 42, r: 10, t: 10, b: 26 };
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    const pts = R.map((r, i) => i), n = R.length;
    if (!n) return;
    const okS = (s, r) => !s.when || s.when(r);
    let ys = []; series.forEach(s => R.forEach(r => { const v = r[s.key]; if (okS(s, r) && v != null && !isNaN(+v)) ys.push(+v); }));
    (opts.bands || []).forEach(b => R.forEach(r => { if (!okS(b, r)) return; [b.lo, b.hi].forEach(k => { const v = r[k]; if (v != null && !isNaN(+v)) ys.push(+v); }); }));
    (opts.refs || []).forEach(rf => ys.push(rf.y));
    let lo = Math.min(...ys, opts.floor ?? Infinity), hi = Math.max(...ys);
    if (lo === hi) { lo -= 1; hi += 1; }
    // opts.time: place readings on a real time axis (gaps show as gaps), as the original chart did.
    const tv = opts.time ? R.map(r => new Date(r.at).getTime()) : null;
    const t0 = tv ? Math.min(...tv) : 0, t1 = tv ? Math.max(...tv) : 1;
    const x = i => tv ? m.l + (t1 === t0 ? 0 : (tv[i] - t0) * (W - m.l - m.r) / (t1 - t0)) : m.l + (n === 1 ? 0 : i * (W - m.l - m.r) / (n - 1)), y = v => m.t + (hi - v) * (H - m.t - m.b) / (hi - lo);
    const NS = "http://www.w3.org/2000/svg", mk = (t, a) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
    svg.textContent = "";
    for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; svg.append(mk("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: "var(--line)" })); const t = mk("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--muted)" }); t.textContent = v.toFixed(opts.dec ?? 1); svg.append(t); }
    (opts.bands || []).forEach(b => { let up = [], dn = []; R.forEach((r, i) => { if (okS(b, r) && r[b.lo] != null && r[b.hi] != null) { up.push(x(i) + "," + y(+r[b.hi])); dn.unshift(x(i) + "," + y(+r[b.lo])); } }); if (up.length) svg.append(mk("polygon", { points: up.concat(dn).join(" "), fill: "var(--band)" })); });
    (opts.refs || []).forEach(rf => { svg.append(mk("line", { x1: m.l, x2: W - m.r, y1: y(rf.y), y2: y(rf.y), stroke: rf.color, "stroke-dasharray": "4 4", "stroke-width": 1 })); });
    series.forEach(s => { const p = []; R.forEach((r, i) => { const v = r[s.key]; if (okS(s, r) && v != null && !isNaN(+v)) { p.push(x(i) + "," + y(+v)); if (opts.dots) svg.append(mk("circle", { cx: x(i), cy: y(+v), r: 2.2, fill: s.color })); } }); svg.append(mk("polyline", { points: p.join(" "), fill: "none", stroke: s.color, "stroke-width": 1.8 })); });
    [0, Math.floor((n - 1) / 2), n - 1].forEach(i => { const t = mk("text", { x: x(i), y: H - 6, "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle", "font-size": 11, fill: "var(--muted)" }); t.textContent = lab(R[i]); svg.append(t); });
    const hit = mk("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
    hit.addEventListener("mousemove", ev => { const rect = svg.getBoundingClientRect(), px = (ev.clientX - rect.left) * W / rect.width; let i = 0; for (let k = 1; k < n; k++) if (Math.abs(x(k) - px) < Math.abs(x(i) - px)) i = k; const r = R[i]; tip.textContent = lab(r) + " · " + series.map(s => s.name + " " + num(r[s.key], opts.dec ?? 2) + (s.budget ? " (budget " + s.budget + ")" : "")).join(" · "); tip.style.display = "block"; tip.style.left = Math.min(ev.clientX + 12, innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = (ev.clientY + 12) + "px"; });
    hit.addEventListener("mouseleave", () => tip.style.display = "none");
    svg.append(hit);
    const lg = document.getElementById(legendId); lg.textContent = "";
    series.forEach(s => { const sp = el("span"); const i = el("i"); i.style.background = s.color; sp.append(i, document.createTextNode(s.name)); lg.append(sp); });
    (opts.refs || []).forEach(rf => { const sp = el("span"); const i = el("i"); i.style.background = rf.color; sp.append(i, document.createTextNode(rf.name)); lg.append(sp); });
  }
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  function draw() {
    lineChart("roi", "roi-legend", [{ key: "d30_roi_pct", name: "30-day ROI %", color: css("--s1") }, { key: "d7_roi_pct", name: "7-day ROI %", color: css("--s2") }],
      { time: true, bands: [{ lo: "d30_roi_lo95", hi: "d30_roi_hi95" }], refs: [{ y: 0, name: "breakeven", color: css("--muted") }], dec: 1 });
    lineChart("lat", "lat-legend", [{ key: "live_all_s", name: "All-dates ledger (5 s)", color: css("--s4"), budget: "5 s" }, { key: "live_s", name: "Live today (3 s)", color: css("--s1"), budget: "3 s" }, { key: "plan_s", name: "Plan (6 s)", color: css("--s3"), budget: "6 s" }, { key: "page_s", name: "Portfolio page (3 s)", color: css("--s2"), budget: "3 s" }],
      { time: true, dots: true, refs: [{ y: 3, name: "3 s budget (live, page)", color: css("--bad") }], floor: 0, dec: 2 });
    const AR = R.filter(r => r.al_suggested != null);
    if (AR.length) lineChart("align", "align-legend", [
        { key: "al_same_row_pct", name: "today's orders on the board's row %", color: css("--s1") },
        { key: "al_suggested_bought_pct", name: "board picks bought today %", color: css("--s4") },
        { key: "al_sim_disagrees_pct", name: "sim disagreed at purchase, 7 d %", color: css("--s2") },
        { key: "al_rail_model_pct", name: "rail rows with a model %", color: css("--s3") }],
      { rows: AR, time: true, dots: true, floor: 0, dec: 0 });
  }
  // the purchaser against the board and the rail (probe `alignment`, 11-23 on)
  (function () {
    const box = document.getElementById("align-tiles");
    const at = (name, big, ...subs) => { const t = el("div", "tile"); t.append(el("h3", null, name)); t.append(el("div", "big", big)); subs.forEach(s => t.append(el("div", "sub", s))); box.append(t); };
    const of = (a, b) => (a == null || b == null) ? "—" : a + " of " + b;
    const v = (x) => x ?? "—";
    if (last.al_error) { at("Alignment", "—", "not read this reading: " + last.al_error); return; }
    if (last.al_suggested == null) { at("Alignment", "—", "no alignment reading yet"); return; }
    at("Board picks bought", of(last.al_suggested_bought, last.al_suggested),
      "Suggested rows bought today; " + v(last.al_suggested_planned) + " in a live plan now",
      "Kalshi lists " + v(last.al_kalshi_listed) + ", " + v(last.al_kalshi_listed_positions) + " clear its price · Polymarket lists " + v(last.al_polymarket_listed) + ", " + v(last.al_polymarket_listed_positions) + " clear");
    at("Today's orders on the board", last.al_board_read === false ? "—" : of(last.al_same_row, last.al_orders_today),
      "same row now: " + v(last.al_same_row_suggested) + " Suggested, board EV > 0 on " + v(last.al_same_row_ev_pos) + ", model edge > 0 on " + v(last.al_same_row_me_pos),
      "other side only " + v(last.al_other_side) + " · other line " + v(last.al_other_line) + " · off board " + v(last.al_off_board));
    at("Sim at purchase, 7 days", num(last.al_sim_agrees_pct, 0) + "% agree",
      num(last.al_sim_disagrees_pct, 0) + "% disagree, of " + v(last.al_week_orders) + " orders",
      "in play " + num(last.al_inplay_week_pct, 0) + "% of orders; rejected " + num(last.al_inplay_rejected_pct, 0) + "% in play vs " + num(last.al_pregame_rejected_pct, 0) + "% pregame");
    at("Live plans now", "K " + v(last.al_kalshi_live_positions) + " · P " + v(last.al_polymarket_live_positions),
      "positions; Suggested among them: Kalshi " + v(last.al_kalshi_live_suggested) + ", Polymarket " + v(last.al_polymarket_live_suggested));
    at("Rail rows with a model", of(last.al_rail_model, last.al_rail_rows),
      v(last.al_rail_on_board) + " also on the board · today's orders on a rail game " + v(last.al_rail_orders));
  })();
  const H = (D.history || []);
  if (H.length) {
    document.getElementById("hist-title").textContent = "History since " + H[0].date + " (rolling ROI ending each day, 95% range shaded)";
  }
  const drawAll = () => { draw(); if (H.length) lineChart("hist", "hist-legend",
      [{ key: "r30_roi_pct", name: "30-day ROI % (plotted at 20+ events)", color: css("--s1"), when: r => (+r.r30_events) >= 20 },
       { key: "r7_roi_pct", name: "7-day ROI % (10+ events)", color: css("--s2"), when: r => (+r.r7_events) >= 10 }],
      { rows: H, label: r => r.date.slice(5), bands: [{ lo: "r30_roi_lo95", hi: "r30_roi_hi95", when: r => (+r.r30_events) >= 20 }], refs: [{ y: 0, name: "breakeven", color: css("--muted") }], dec: 1 }); };
  drawAll(); addEventListener("resize", () => { clearTimeout(window.__rz); window.__rz = setTimeout(drawAll, 150); });

  // tables
  function table(id, cols, rows) {
    const t = document.getElementById(id), tr = el("tr");
    cols.forEach(c => tr.append(el("th", null, c.h))); const th = el("thead"); th.append(tr); t.append(th);
    const tb = el("tbody");
    rows.forEach(r => { const row = el("tr"); cols.forEach(c => { const td = el("td", c.num ? "num" : ""); const v = c.f ? c.f(r) : r[c.k]; td.textContent = v == null ? "—" : v; if (c.cls) { const k = c.cls(r); if (k) td.classList.add(k); } row.append(td); }); tb.append(row); });
    t.append(tb);
  }
  table("hist-table", [
    { h: "Day", k: "date" }, { h: "Bets / events", num: 1, f: r => r.bets + " / " + r.events },
    { h: "Day ROI", num: 1, f: r => pct(r.roi_pct), cls: r => cls(r.roi_lo95, r.roi_hi95) },
    { h: "Won vs breakeven", num: 1, f: r => num(r.win_pct) + "% / " + num(r.breakeven_pct) + "%" },
    { h: "Fees", num: 1, f: r => num(r.fee_pct) + "%" }, { h: "CLV net", num: 1, f: r => r.clv_net_pp == null ? "—" : num(r.clv_net_pp, 2) + " pp" },
    { h: "30 d ROI", num: 1, f: r => pct(r.r30_roi_pct), cls: r => cls(r.r30_roi_lo95, r.r30_roi_hi95) },
    { h: "30 d range", num: 1, f: r => "[" + num(r.r30_roi_lo95) + ", " + num(r.r30_roi_hi95) + "]" },
    { h: "Orders", num: 1, k: "orders" }, { h: "Distinct anomalies", num: 1, f: r => r.readings ? r.anomalies : "—" },
    { h: "Live > 3 s", num: 1, f: r => r.readings ? r.live_over_3s : "—" },
  ], H.filter(r => r.bets).slice().reverse());
  table("slices", [
    { h: "Group", f: r => r.group }, { h: "Slice", f: r => r.key },
    { h: "Bets", k: "bets", num: 1 }, { h: "Games", k: "events", num: 1 },
    { h: "ROI %", num: 1, f: r => num(r.roi_pct, 2), cls: r => cls(r.roi_lo95_pct, r.roi_hi95_pct) },
    { h: "95% low", num: 1, f: r => num(r.roi_lo95_pct, 2) }, { h: "95% high", num: 1, f: r => num(r.roi_hi95_pct, 2) },
    { h: "Won %", num: 1, f: r => num(r.win_pct) }, { h: "Breakeven %", num: 1, f: r => num(r.breakeven_win_pct) },
    { h: "Excess wins", num: 1, f: r => num(r.excess_wins) }, { h: "Predicted EV %", num: 1, f: r => num(r.predicted_ev_pct, 2) },
  ], D.performance || []);
  table("findings", [{ h: "ID", k: "id" }, { h: "Kind", k: "kind" }, { h: "What", k: "title" }, { h: "Status", k: "status" }, { h: "Owner", k: "owner" }, { h: "First seen", k: "first_seen" }],
    D.findings || []);
  const nz = v => v == null ? "—" : String(v);
  table("readings", [
    { h: "Reading (CST)", f: r => r.label },
    { h: "Live ticks", num: 1, f: r => nz(r.live_ticks) }, { h: "Placed", num: 1, f: r => nz(r.placed) },
    { h: "Failed", num: 1, f: r => nz(r.failed), cls: r => (+r.failed) > 0 ? "bad" : "" },
    { h: "Outside price band", num: 1, f: r => nz(r.refused_price_band) }, { h: "Held on another slate", num: 1, f: r => nz(r.refused_held_other_slate) },
    { h: "Game started", num: 1, f: r => nz(r.refused_game_started) }, { h: "Other refusals", num: 1, f: r => nz(r.refused_other) },
    { h: "Kalshi cap %", num: 1, f: r => num(r.kalshi_cap_pct) }, { h: "Polymarket cap %", num: 1, f: r => num(r.polymarket_cap_pct) },
    { h: "Orders", num: 1, f: r => nz(r.orders_today) }, { h: "Positions", num: 1, f: r => nz(r.positions) },
    { h: "Plan age (min)", num: 1, f: r => num(r.plan_age_min) }, { h: "Live s", num: 1, f: r => num(r.live_s, 2), cls: r => (+r.live_s) > 3 ? "bad" : "" },
    { h: "Worker kills", num: 1, f: r => nz(r.worker_timeouts), cls: r => (+r.worker_timeouts) > 0 ? "bad" : "" },
    { h: "Gate", num: 1, f: r => nz(r.gate_events) }, { h: "30 d ROI %", num: 1, f: r => num(r.d30_roi_pct, 2) },
    { h: "Anomalies", num: 1, f: r => nz(r.anomalies), cls: r => (+r.anomalies) > 1 ? "warn" : "" },
  ], R.slice().reverse());
  table("sources-table", [{ h: "Dataset", k: "dataset" }, { h: "Item", k: "label" }, { h: "Value", f: r => r.value == null ? "—" : String(r.value) }],
    D.sources || []);
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
