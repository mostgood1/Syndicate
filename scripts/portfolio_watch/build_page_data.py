"""Build the Portfolio Watch page's two datasets from the probe's readings (lane portfolio-monitor).

  readings.json  one row per reading: latencies, banner, plan funnel, execution, order flow, settlement,
                 cap use (percent only), gate events, anomaly count. No dollar amounts.
  findings.json  the findings register (paths.REGISTRY, kept by hand) plus each open
                 anomaly of the latest reading.
Output: paths.PAGE / readings.json, performance.json, findings.json (each {rows, meta}).
"""
import json
import sys
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import paths  # noqa: E402
OUT = paths.PAGE
OUT.mkdir(parents=True, exist_ok=True)


def row(r: dict) -> dict:
    ep = r.get("endpoints") or {}
    ex = (r.get("execution") or {}).get("live_ticks") or {}
    refused: dict[str, int] = {}
    for v in ex.values():
        for k, n in (v.get("refused") or {}).items():
            refused[k] = refused.get(k, 0) + int(n)
    plan = r.get("plan") or {}
    banner = r.get("banner") or {}
    flow = r.get("orders_today") or {}
    caps = r.get("cap_use") or {}
    gate = r.get("gate") or {}
    web = r.get("web") or {}
    return {
        "at": r["at"],
        "label": r["label"],
        "window_min": r.get("log_minutes"),
        "live_s": (ep.get("live_today") or {}).get("seconds"),
        "live_all_s": (ep.get("live_all") or {}).get("seconds"),
        "plan_s": (ep.get("plan") or {}).get("seconds"),
        "page_s": (ep.get("page") or {}).get("seconds"),
        "endpoints_ok": sum(1 for e in ep.values() if e.get("status") == 200),
        "endpoints": len(ep),
        "worker_timeouts": web.get("worker_timeouts"),
        "browser_requests": sum(g.get("browser", 0) for g in (web.get("paths") or {}).values()),
        "banner_ok": "ok" if banner.get("ok") else "not ok",
        "state_age_s": banner.get("state_age_s"),
        "plan_age_min": plan.get("age_min"),
        "board_rows": plan.get("board_rows"),
        "suggested": plan.get("suggested"),
        "sized": plan.get("sized"),
        "positions": plan.get("positions"),
        "live_ticks": sum(v.get("ticks", 0) for v in ex.values()),
        "placed": sum(v.get("placed", 0) for v in ex.values()),
        "failed": sum(v.get("failed", 0) for v in ex.values()),
        "refused_price_band": refused.get("outside_price_band", 0),
        "refused_held_other_slate": refused.get("already_held_other_slate", 0),
        "refused_game_started": refused.get("game_started", 0),
        "refused_other": sum(n for k, n in refused.items()
                             if k not in ("outside_price_band", "already_held_other_slate", "game_started")),
        "orders_today": flow.get("orders"),
        "failed_or_rejected_today": flow.get("failed_or_rejected"),
        "resting": flow.get("resting"),
        "late_settlements": (r.get("settlement") or {}).get("late"),
        "kalshi_cap_pct": (caps.get("kalshi") or {}).get("dollars_pct"),
        "polymarket_cap_pct": (caps.get("polymarket") or {}).get("dollars_pct"),
        # The paper BOOK's all-dates record (the refresh-worker's PAPER_ALL_TIME_WRITTEN line; the
        # /portfolio/paper page that showed it was retired 2026-11-17). Counts and rates only.
        "paper_settled": ((r.get("execution") or {}).get("paper_record") or {}).get("settled"),
        "paper_won": ((r.get("execution") or {}).get("paper_record") or {}).get("won"),
        "paper_lost": ((r.get("execution") or {}).get("paper_record") or {}).get("lost"),
        "paper_roi_pct": ((r.get("execution") or {}).get("paper_record") or {}).get("roi_pct"),
        "paper_win_pct": ((r.get("execution") or {}).get("paper_record") or {}).get("win_pct"),
        "paper_at": ((r.get("execution") or {}).get("paper_record") or {}).get("at"),
        "gate_events": ((gate.get("focus") or {}).get("events")),
        "gate_clock": ((gate.get("clock") or {}).get("change_id")),
        # Tonight's plan cadence (probe plan_commits, 11-18 on): writes for today's Central date only.
        "tonight_plan_commits": _tonight(r).get("commits"),
        "tonight_plan_max_gap_min": _tonight(r).get("max_gap_min"),
        "tonight_plan_newest_age_min": (r.get("plan_commits") or {}).get("today_newest_age_min"),
        "anomalies": len(r.get("anomalies") or []),
        # The live book's results (probe `performance`, 11-18 on). Percentages and counts only.
        **_perf_fields(r),
    }


def _perf_fields(r: dict) -> dict:
    perf = r.get("performance") or {}
    w = perf.get("windows") or {}
    c = perf.get("clv") or {}
    out = {}
    for name, tag in (("yesterday", "yday"), ("last 7", "d7"), ("last 30", "d30"), ("all", "all")):
        win = w.get(name) or {}
        out[f"{tag}_bets"] = win.get("bets")
        out[f"{tag}_events"] = win.get("events")
        out[f"{tag}_roi_pct"] = win.get("roi_pct")
        out[f"{tag}_roi_lo95"] = win.get("roi_lo95_pct")
        out[f"{tag}_roi_hi95"] = win.get("roi_hi95_pct")
        out[f"{tag}_win_pct"] = win.get("win_pct")
        out[f"{tag}_breakeven_pct"] = win.get("breakeven_win_pct")
    out["d30_clv_net_pp"] = (c.get("last 30") or {}).get("clv_net_pp")
    out["d30_clv_gross_pp"] = (c.get("last 30") or {}).get("clv_gross_pp")
    out["d7_clv_net_pp"] = (c.get("last 7") or {}).get("clv_net_pp")
    out["perf_signals"] = len(perf.get("signals") or []) if perf.get("windows") else None
    return out


def _tonight(r: dict) -> dict:
    pc = r.get("plan_commits") or {}
    return (pc.get("by_date") or {}).get(pc.get("today")) or {}


readings = [json.loads(line) for line in (paths.READINGS / "readings.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
rows = [row(r) for r in readings]
code = Path(__file__).read_text(encoding="utf-8")
(OUT / "readings.json").write_text(json.dumps({"rows": rows, "meta": [
    {"label": "Probe", "value": "scripts/portfolio_monitor_probe.py (fleet 127.0.0.1:10000, read-only)"},
    {"label": "Readings", "value": f"{len(rows)}, {rows[0]['at']} .. {rows[-1]['at']}" if rows else "0"},
    {"label": "build_page_data.py", "value": code, "type": "code", "lang": "python"},
]}, indent=1), encoding="utf-8")

registry = json.loads(paths.REGISTRY.read_text(encoding="utf-8"))
latest = readings[-1] if readings else {}
anoms = [{"id": f"A{i + 1}", "kind": "anomaly", "title": a, "status": "open (latest reading)",
          "owner": "", "first_seen": latest.get("label", ""), "evidence": f"reading {latest.get('at', '')}"}
         for i, a in enumerate(latest.get("anomalies") or [])]
perf = latest.get("performance") or {}
signals = [{"id": f"S{i + 1}", "kind": "performance signal", "title": s, "status": "open (latest reading, 30 days)",
            "owner": "portfolio-monitor (evidence for per-line fixes only)", "first_seen": latest.get("label", ""),
            "evidence": f"reading {latest.get('at', '')}"}
           for i, s in enumerate(perf.get("signals") or [])]
perf_rows = []
for name, win in (perf.get("windows") or {}).items():
    perf_rows.append({"group": "window", "key": name, **{k: win.get(k) for k in (
        "bets", "events", "roi_pct", "roi_lo95_pct", "roi_hi95_pct", "win_pct", "breakeven_win_pct", "excess_wins")}})
for dim, rows_ in (perf.get("slices") or {}).items():
    for x in rows_:
        perf_rows.append({"group": f"30d {dim}", "key": x.get("key"), **{k: x.get(k) for k in (
            "bets", "events", "roi_pct", "roi_lo95_pct", "roi_hi95_pct", "win_pct", "breakeven_win_pct",
            "excess_wins", "predicted_ev_pct")}})
for q in perf.get("stake_quartiles") or []:
    perf_rows.append({"group": "30d stake quartile", "key": f"{q.get('quartile')} ({q.get('dollar_share_pct')}% of $)",
                      **{k: q.get(k) for k in ("bets", "events", "roi_pct", "roi_lo95_pct", "roi_hi95_pct")}})
for i, row_ in enumerate(perf_rows):
    row_["id"] = f"P{i + 1:03d}"
(OUT / "performance.json").write_text(json.dumps({"rows": perf_rows, "meta": [
    {"label": "Source", "value": "probe `performance` over /api/portfolio/live?on=all&show=all, via "
                                 "scripts/live_book_edge_readout.py (the adopted gate's instrument)"},
    {"label": "As of", "value": latest.get("label", "")},
    {"label": "Units", "value": "ROI on stake net of fees, event-clustered 95% band; percentages and counts only"},
]}, indent=1), encoding="utf-8")
(OUT / "findings.json").write_text(json.dumps({"rows": registry + anoms + signals, "meta": [
    {"label": "Register", "value": ".syndicate/findings_<date>_portfolio_monitor.md (lane portfolio-monitor)"},
]}, indent=1), encoding="utf-8")
print(f"readings {len(rows)}, findings {len(registry)} + anomalies {len(anoms)} + signals {len(signals)}, "
      f"performance rows {len(perf_rows)}")
