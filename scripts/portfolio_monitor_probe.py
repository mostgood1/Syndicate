"""Read-only: one reading of the fleet's portfolio endpoint (lane portfolio-monitor).

One run = one reading. It never writes to production: every request is a plain GET.

What it measures, each with its denominator:
  * ENDPOINTS: status, seconds and size of /portfolio and the /api/portfolio/* reads below, against a latency
    budget each. The web access log adds every OTHER caller's requests to the same paths in the window (count,
    status mix, p50/p95/max ms), and the window's gunicorn WORKER TIMEOUT kills.
  * BANNER: the live page's own health verdict and its six fields, the kill switch, and the worker state age
    against the page's own stale threshold.
  * PLAN FUNNEL: board rows -> suggested -> plan rows_in -> sized -> positions, refusals by reason, the plan's
    age, the CLV join's match rate, sim coverage, staked share of the slate ceiling.
  * EXECUTION: per venue over the window, the workers' `[execute_portfolio] EXECUTED` ticks (live mode):
    placed / filled / failed / refused by reason, and the newest `LIVE_PLAN_WRITTEN` funnel per venue.
  * ORDER FLOW + LEDGER: today's live orders by status, failed/rejected share, resting orders and their age,
    unknown submits, unreconciled rows, grade conflicts, balances age, filled bets still unsettled more than
    SETTLE_LAG_H after their start.
  * CAP USE: today's live dollars and orders per venue against the venue's day caps.
  * GATE: the adopted scale-up gate on the betting-change clock (`live_book_edge_readout`).

NEVER READ, by design: /api/portfolio/summary and /api/portfolio/paper. On 2026-11-17 ~16:10Z one GET of
/api/portfolio/paper ran ~177 s and its web worker was SIGKILLed by the gunicorn timeout (summary dropped
the connection the same minute). A monitor must not cost production a worker; those two are read from the
access log only.

Money: the text report carries counts, rates and percentages of caps, never balances. The JSON reading (and
the raw payloads) stay in --out-dir, outside the repo, which is public.

Usage:  py -3 scripts/portfolio_monitor_probe.py [--out-dir C:\\tmp\\pfmon\\readings] [--log-minutes 60]
It lowers its own priority to IDLE (the fleet shares this host) and runs its log reads at nice 19.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# PRODUCTION IS THE FLEET, ONLY (user 2026-11-15). Pinned; a non-loopback --base-url is refused.
FLEET_BASE_URL = "http://127.0.0.1:10000"
CT = ZoneInfo("America/Chicago")

# name, path, latency budget (s). Budgets are ~3x the 2026-11-17 16:10Z first reading, rounded up.
ENDPOINTS: tuple[tuple[str, str, float], ...] = (
    ("live_today", "/api/portfolio/live", 3.0),
    ("live_all", "/api/portfolio/live?on=all&show=all", 5.0),
    ("plan", "/api/portfolio/plan", 6.0),
    ("limits", "/api/portfolio/limits", 2.0),
    ("settings", "/api/portfolio/settings", 2.0),
    ("books", "/api/portfolio/books", 2.0),
    ("page", "/portfolio", 3.0),
)
NEVER_READ = ("/api/portfolio/summary", "/api/portfolio/paper")
SETTLE_LAG_H = 8.0      # a filled bet still unsettled this long after its start is late
RESTING_OLD_MIN = 120.0  # a resting order older than this is worth naming
PLAN_STALE_MIN = 45.0    # the refresh-worker rewrites the plan every ~15 min; three missed is stale
PLAN_SERIES_H = 6  # how far back the per-date plan-write series reads
PLAN_COMMIT_GAP_S = 180  # LIVE_PLAN_WRITTEN lines of one date closer than this are one commit


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_ts(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    m = re.match(r"^(.*?\.\d{1,6})\d*([+-]\d\d:\d\d)?$", text)
    if m:  # Python's fromisoformat takes at most 6 fraction digits
        text = m.group(1) + (m.group(2) or "")
    try:
        out = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=dt.timezone.utc)


def ct_label(t: dt.datetime) -> str:
    local = t.astimezone(CT)
    return local.strftime("%a %m-%d %I:%M %p CST").replace(" 0", " ")


def pct(values: Sequence[float], q: float) -> float | None:
    v = sorted(values)
    if not v:
        return None
    k = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return round(v[k], 1)


def rate(n: int, d: int) -> str:
    return f"{n}/{d}" + (f" ({100.0 * n / d:.1f}%)" if d else "")


# ---------------------------------------------------------------- pure readings over payloads


def banner(live: Mapping[str, Any]) -> dict[str, Any]:
    health = dict(live.get("health") or {})
    age, stale = live.get("state_age_seconds"), live.get("stale_after_seconds") or 900
    switch = live.get("kill_switch") or {}
    bad = sorted(k for k, v in health.items() if k != "ok" and v is False)
    return {
        "ok": bool(health.get("ok")),
        "bad_fields": bad,
        "kill_switch_engaged": bool(switch.get("engaged")),
        "kill_switch_source": switch.get("source"),
        "state_age_s": age,
        "stale_after_s": stale,
        "state_stale": age is None or age > stale,
        "state_recorded_by": live.get("state_recorded_by"),
        "execution_mode": live.get("execution_mode"),
        "live_armed": live.get("live_armed"),
        "balances_age_s": (live.get("balances") or {}).get("age_seconds"),
    }


def order_flow(orders: Iterable[Mapping[str, Any]], today: str, now: dt.datetime) -> dict[str, Any]:
    """Today's live orders (by selected_date) by status; resting age."""
    todays = [o for o in orders if str(o.get("selected_date") or "") == today and o.get("mode", "live") == "live"]
    status = collections.Counter(str(o.get("status")) for o in todays)
    resting, overdue = [], []
    for o in todays:
        if o.get("status") != "submitted":
            continue
        sub = parse_ts(o.get("submitted_at"))
        age = round((now - sub).total_seconds() / 60.0, 1) if sub else None
        resting.append(age)
        why = resting_overdue_reason(o, now, age)
        if why:
            overdue.append({"key": str(o.get("idempotency_key") or "")[:8], "style": o.get("execution_style") or "taker",
                            "age_min": age, "why": why})
    n = len(todays)
    # A maker-pilot post the venue cancelled unfilled at its kickoff expiry is recorded `rejected` (the status
    # that frees its budget), which is the post's normal ending, not a failure. First seen 2026-11-17 00:00:07Z.
    expired_posts = sum(1 for o in todays if is_expired_maker_post(o))
    bad = status.get("failed", 0) + status.get("rejected", 0) - expired_posts
    return {
        "orders": n,
        "by_status": dict(status),
        "maker_posts_expired_unfilled": expired_posts,
        "failed_or_rejected": bad,
        "failed_or_rejected_rate": round(bad / n, 4) if n else None,
        "resting": len(resting),
        "resting_age_min": sorted((a for a in resting if a is not None), reverse=True),
        "resting_overdue": overdue,
    }


def is_expired_maker_post(order: Mapping[str, Any]) -> bool:
    """A maker-pilot post that ended unfilled at the venue (cancelled or expired): its designed ending."""
    return (order.get("execution_style") == "maker_pilot" and order.get("status") == "rejected"
            and str(order.get("error") or "") in ("venue_canceled", "venue_cancelled", "venue_expired")
            and not order.get("contracts"))


MAKER_KICKOFF_GRACE_MIN = 10.0   # Kalshi expires a pilot post at commence; allow the next reconcile pass
UNREAD_RESTING_MIN = 30.0        # a resting order the reconciler has not read this long is not being watched


def resting_overdue_reason(order: Mapping[str, Any], now: dt.datetime, age_min: float | None) -> str | None:
    """Why a resting order is a problem, or None while it is resting as designed.

    A MAKER-PILOT post rests ON PURPOSE until it fills, the fair price moves, or kickoff: it is sent
    `good_till_canceled` with a venue expiry at commence, and `cancel_stale_resting_orders` exempts it from the
    900 s stale cancel (lane kalshi-maker-pilot). On 2026-11-17 this probe flagged one such post (NCAAF, posted
    00:12 CST for a 6 PM kickoff) as "resting > 120 min" at every reading; it was working as designed.
    So a pilot post is overdue only when it is still resting after its kickoff (plus a grace for the reconcile
    pass), or when the reconciler has stopped reading it. Any other resting order keeps the 120-min rule.
    """
    read = parse_ts(order.get("reconciled_at"))
    if read is not None and (now - read).total_seconds() / 60.0 > UNREAD_RESTING_MIN:
        return f"not reconciled for {round((now - read).total_seconds() / 60.0)} min"
    if order.get("execution_style") == "maker_pilot":
        start = parse_ts(order.get("commence_time"))
        if start is None:
            return "maker-pilot post with no commence time"
        past = (now - start).total_seconds() / 60.0
        return f"maker-pilot post still resting {round(past)} min after kickoff" if past > MAKER_KICKOFF_GRACE_MIN else None
    if age_min is not None and age_min > RESTING_OLD_MIN:
        return f"resting {age_min:.0f} min (> {RESTING_OLD_MIN:.0f})"
    return None


def settlement_lag(orders: Iterable[Mapping[str, Any]], now: dt.datetime, lag_h: float = SETTLE_LAG_H) -> dict[str, Any]:
    """Filled live bets with no outcome, by how long after their start they are."""
    late, pending_started, no_start = [], 0, 0
    for o in orders:
        if o.get("status") != "filled" or o.get("outcome") not in (None, "", "pending"):
            continue
        start = parse_ts(o.get("commence_time"))
        if start is None:
            no_start += 1
            continue
        hours = (now - start).total_seconds() / 3600.0
        if hours < 0:
            continue
        pending_started += 1
        if hours >= lag_h:
            late.append({"sport": o.get("sport"), "venue": o.get("venue"), "hours": round(hours, 1),
                         "selected_date": o.get("selected_date")})
    late.sort(key=lambda r: -r["hours"])
    return {"started_unsettled": pending_started, "late": len(late), "late_rows": late[:10],
            "no_start_time": no_start, "lag_h": lag_h}


def cap_use(orders: Iterable[Mapping[str, Any]], limits: Mapping[str, Any], today: str) -> dict[str, Any]:
    """Today's live dollars and orders per venue against the day caps. Percentages only leave this function's
    caller in the text report; dollars stay in the JSON reading."""
    spent: dict[str, dict[str, float]] = collections.defaultdict(lambda: {"dollars": 0.0, "orders": 0})
    for o in orders:
        if str(o.get("selected_date") or "") != today or o.get("status") in ("rejected",):
            continue
        if o.get("status") == "failed":
            continue
        venue = str(o.get("venue") or "?")
        stake = o.get("fill_stake_dollars")
        if stake in (None, 0) and o.get("status") == "submitted":
            stake = o.get("requested_stake_dollars")
        spent[venue]["dollars"] += float(stake or 0.0)
        spent[venue]["orders"] += 1
    out = {}
    cap_d = limits.get("max_day_dollars_by_venue") or {}
    cap_n = limits.get("max_day_orders_by_venue") or {}
    for venue in sorted(set(spent) | set(cap_d)):
        d, n = spent[venue]["dollars"], int(spent[venue]["orders"])
        cd, cn = cap_d.get(venue), cap_n.get(venue)
        out[venue] = {
            "dollars": round(d, 2), "orders": n, "cap_dollars": cd, "cap_orders": cn,
            "dollars_pct": round(100.0 * d / cd, 1) if cd else None,
            "orders_pct": round(100.0 * n / cn, 1) if cn else None,
        }
    return out


def ledger_flags(live: Mapping[str, Any]) -> dict[str, Any]:
    unrec = list(live.get("unreconciled") or [])
    return {
        "unknown_submits": len(live.get("unknown_submits") or []),
        "unreconciled": len(unrec),
        "unreconciled_keys": sorted(str(u.get("idempotency_key") or "")[:8] for u in unrec),
        "grade_conflicts": len(live.get("grade_conflicts") or []),
        "ledger_error": live.get("ledger_error"),
        "settlement_error": live.get("settlement_error"),
        "hidden_open_dated": live.get("hidden_open_dated"),
        "book_count": live.get("book_count"),
    }


def plan_funnel(plan: Mapping[str, Any], now: dt.datetime) -> dict[str, Any]:
    gen = parse_ts(plan.get("generated_at"))
    sg = plan.get("suggested_gate") or {}
    totals = plan.get("totals") or {}
    join = plan.get("clv_join") or {}
    cov = plan.get("sim_coverage") or {}
    ceiling = totals.get("slate_exposure_ceiling_dollars")
    staked = totals.get("staked_dollars")
    return {
        "plan_present": bool(plan.get("plan_present")),
        "age_min": round((now - gen).total_seconds() / 60.0, 1) if gen else None,
        "board_rows": sg.get("rows_in"),
        "suggested": sg.get("suggested"),
        "rows_in": plan.get("rows_in"),
        "sized": plan.get("sized"),
        "positions": totals.get("positions"),
        "refusals": dict(plan.get("refusals") or {}),
        "ceiling_used_pct": round(100.0 * staked / ceiling, 1) if ceiling and staked is not None else None,
        "clv_join_match_rate": join.get("match_rate"),
        "clv_join_positions": join.get("positions"),
        "sim_edge_share": cov.get("share_with_sim_edge"),
        "positions_sim_picked_side": totals.get("positions_where_sim_picked_the_side"),
    }


ACCESS_RE = re.compile(
    r'^(?P<ts>\S+Z) \S+ - - \[[^\]]+\] "(?P<method>[A-Z]+) (?P<path>/(?:api/)?portfolio\S*) HTTP/[\d.]+" '
    r'(?P<status>\d{3}) (?P<bytes>\d+|-) "[^"]*" "(?P<ua>[^"]*)" (?P<ms>\d+)ms'
)


def path_group(path: str) -> str:
    base = path.split("?", 1)[0]
    if base.startswith("/api/portfolio/live") and "on=all" in path:
        return "/api/portfolio/live?on=all"
    return base


def web_access(lines: Iterable[str], cutoff: str) -> dict[str, Any]:
    """Per path group over the window: n, statuses, p50/p95/max ms, and callers (browser vs script)."""
    rows: dict[str, dict[str, Any]] = {}
    timeouts = 0
    for line in lines:
        if line[:24] < cutoff:
            continue
        if "WORKER TIMEOUT" in line:
            timeouts += 1
            continue
        m = ACCESS_RE.match(line)
        if not m:
            continue
        g = rows.setdefault(path_group(m["path"]), {"n": 0, "status": collections.Counter(), "ms": [], "browser": 0})
        g["n"] += 1
        g["status"][m["status"]] += 1
        g["ms"].append(float(m["ms"]))
        if "Mozilla" in m["ua"]:
            g["browser"] += 1
    out = {k: {"n": v["n"], "status": dict(v["status"]), "browser": v["browser"],
               "p50_ms": pct(v["ms"], 0.5), "p95_ms": pct(v["ms"], 0.95), "max_ms": max(v["ms"]) if v["ms"] else None}
           for k, v in sorted(rows.items())}
    return {"paths": out, "worker_timeouts": timeouts}


_KV_DICT = re.compile(r"(\w+)=(\{[^}]*\})")
_KV = re.compile(r"(\w+)=([^\s{]+)")


def _kv(line: str) -> dict[str, str]:
    out = {k: v for k, v in _KV.findall(line)}
    out.update({k: v for k, v in _KV_DICT.findall(line)})
    return out


def _dict(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        import ast

        val = ast.literal_eval(text)
        return dict(val) if isinstance(val, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def execution(lines: Iterable[str], cutoff: str) -> dict[str, Any]:
    """LIVE-mode EXECUTED ticks per venue in the window, and the newest LIVE_PLAN_WRITTEN per venue."""
    venues: dict[str, dict[str, Any]] = {}
    plans: dict[str, dict[str, Any]] = {}
    unrec_keys: set[str] = set()
    paper_record: dict[str, Any] | None = None
    for line in lines:
        if line[:24] < cutoff:
            continue
        if "[execute_portfolio] EXECUTED " in line:
            kv = _kv(line)
            if kv.get("mode") != "live":
                continue
            v = venues.setdefault(kv.get("venue", "?"), {"ticks": 0, "placed": 0, "filled": 0, "failed": 0,
                                                          "refused": collections.Counter(), "armed_false": 0})
            v["ticks"] += 1
            for f in ("placed", "filled", "failed"):
                try:
                    v[f] += int(kv.get(f, "0"))
                except ValueError:
                    pass
            v["refused"].update(_dict(kv.get("refused")))
            if kv.get("armed") == "False":
                v["armed_false"] += 1
        elif "[portfolio_commit] LIVE_PLAN_WRITTEN " in line:
            kv = _kv(line)
            plans[kv.get("venue", "?")] = {
                "at": line[:24], "rows_in": kv.get("rows_in"), "placeable_in": kv.get("placeable_in"),
                "positions": kv.get("positions"), "refusals": _dict(kv.get("refusals")),
            }
        elif "[execution_ledger] UNRECONCILABLE_ORDER " in line:
            m = re.search(r"key='([0-9a-f]+)'", line)
            if m:
                unrec_keys.add(m.group(1)[:8])
        elif "[paper_settlement] PAPER_ALL_TIME_WRITTEN " in line:
            # The paper BOOK's all-dates record, which the refresh-worker's settle pass prints at most
            # every 10 min (the /portfolio/paper page that showed it was retired 2026-11-17). Newest wins.
            kv = _kv(line)
            paper_record = {"at": kv.get("at") or line[:24]}
            for f in ("rows", "settled", "pending", "won", "lost", "push", "roi_pct", "win_pct"):
                raw = kv.get(f)
                try:
                    paper_record[f] = None if raw in (None, "None") else (float(raw) if "." in raw else int(raw))
                except ValueError:
                    paper_record[f] = None
    for v in venues.values():
        v["refused"] = dict(v["refused"])
    return {"live_ticks": venues, "plans": plans, "unreconcilable_keys": sorted(unrec_keys),
            "paper_record": paper_record}


def plan_commits(lines: Iterable[str], now: dt.datetime, today: str | None = None) -> dict[str, Any]:
    """TONIGHT's plan cadence: when `portfolio_commit` last wrote the live plan for today's Central date.

    One commit writes one LIVE_PLAN_WRITTEN line per venue within ~1 min, so lines of a date less than
    PLAN_COMMIT_GAP_S apart are one commit. The board loop alternates dates (on 11-17 its 7:51 PM CST cycle built
    11-18), so a write for TOMORROW is not a fresh plan for tonight; that is why the series is per date. Asked
    for by lane layer2-board-process-split as the portfolio-side before/after for its switch (2026-11-18)."""
    today = today or now.astimezone(CT).date().isoformat()
    stamps: dict[str, list[dt.datetime]] = collections.defaultdict(list)
    for line in lines:
        ts = parse_ts(line[:24])
        date = _kv(line).get("date")
        if ts and date:
            stamps[date].append(ts)
    out: dict[str, Any] = {"today": today, "series_h": PLAN_SERIES_H, "by_date": {}}
    for date, ts_list in sorted(stamps.items()):
        commits: list[dt.datetime] = []
        for ts in sorted(set(ts_list)):
            if not commits or (ts - last).total_seconds() > PLAN_COMMIT_GAP_S:
                commits.append(ts)
            last = ts
        gaps = [(b - a).total_seconds() / 60.0 for a, b in zip(commits, commits[1:])]
        out["by_date"][date] = {
            "commits": len(commits), "first": commits[0].strftime("%H:%M:%SZ"),
            "newest": commits[-1].strftime("%H:%M:%SZ"),
            "max_gap_min": round(max(gaps), 1) if gaps else None,
            "gaps_min": [round(g, 1) for g in gaps],
        }
    t = stamps.get(today)
    out["today_newest_age_min"] = round((now - max(t)).total_seconds() / 60.0, 1) if t else None
    return out


# ---------------------------------------------------------------- anomalies


def anomalies(reading: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for name, ep in (reading.get("endpoints") or {}).items():
        if ep.get("status") != 200:
            out.append(f"ENDPOINT {name} status {ep.get('status')} ({ep.get('error') or ''})".rstrip(" ()"))
        elif ep.get("seconds") is not None and ep["seconds"] > ep["budget_s"]:
            out.append(f"ENDPOINT {name} slow: {ep['seconds']:.2f}s > budget {ep['budget_s']}s")
    web = reading.get("web") or {}
    if web.get("worker_timeouts"):
        out.append(f"WEB {web['worker_timeouts']} gunicorn WORKER TIMEOUT kill(s) in the window")
    for path, g in (web.get("paths") or {}).items():
        errs = sum(n for s, n in g["status"].items() if s.startswith("5"))
        if errs:
            out.append(f"WEB {path}: {rate(errs, g['n'])} answered 5xx")
    b = reading.get("banner") or {}
    if b and not b.get("ok"):
        out.append(f"BANNER not ok: {', '.join(b.get('bad_fields') or ['?'])}")
    if b.get("kill_switch_engaged"):
        out.append(f"KILL SWITCH engaged (source {b.get('kill_switch_source')})")
    if b.get("state_stale"):
        out.append(f"WORKER STATE stale: {b.get('state_age_s')}s > {b.get('stale_after_s')}s")
    if (b.get("balances_age_s") or 0) > 900:
        out.append(f"BALANCES stale: {b.get('balances_age_s')}s")
    p = reading.get("plan") or {}
    if p and (p.get("age_min") is None or p["age_min"] > PLAN_STALE_MIN):
        out.append(f"PLAN stale: {p.get('age_min')} min old (> {PLAN_STALE_MIN})")
    if p.get("clv_join_match_rate") is not None and p["clv_join_match_rate"] < 1.0:
        out.append(f"CLV JOIN match rate {p['clv_join_match_rate']} on {p.get('clv_join_positions')} positions")
    led = reading.get("ledger") or {}
    for key in ("unknown_submits", "grade_conflicts"):
        if led.get(key):
            out.append(f"LEDGER {key}: {led[key]}")
    if led.get("unreconciled"):
        out.append(f"LEDGER unreconciled: {led['unreconciled']} ({', '.join(led.get('unreconciled_keys') or [])})")
    for key in ("ledger_error", "settlement_error"):
        if led.get(key):
            out.append(f"LEDGER {key}: {str(led[key])[:120]}")
    flow = reading.get("orders_today") or {}
    if flow.get("failed_or_rejected"):
        out.append(f"ORDERS failed or rejected today: {rate(flow['failed_or_rejected'], flow['orders'])}")
    for o in flow.get("resting_overdue") or []:
        out.append(f"ORDERS resting order {o['key']} ({o['style']}): {o['why']}")
    lag = reading.get("settlement") or {}
    if lag.get("late"):
        oldest = lag["late_rows"][0]
        out.append(f"SETTLEMENT late: {rate(lag['late'], lag['started_unsettled'])} started bets unsettled > "
                   f"{lag['lag_h']:.0f} h (oldest {oldest['hours']} h, {oldest['sport']})")
    for venue, c in (reading.get("cap_use") or {}).items():
        for f in ("dollars_pct", "orders_pct"):
            if (c.get(f) or 0) >= 90.0:
                out.append(f"CAP {venue} {f.split('_')[0]} at {c[f]}% of the day cap")
    for venue, v in ((reading.get("execution") or {}).get("live_ticks") or {}).items():
        if v.get("failed"):
            out.append(f"EXECUTION {venue}: {v['failed']} failed order(s) over {v['ticks']} live ticks")
        if v.get("armed_false"):
            out.append(f"EXECUTION {venue}: {v['armed_false']} of {v['ticks']} live ticks ran unarmed")
    clock = (reading.get("gate") or {}).get("clock") or {}
    if clock.get("pending"):
        out.append("GATE clock PENDING a load: the count is 0")
    if clock.get("unclassified"):
        out.append(f"GATE {clock['unclassified']} deploys.md load(s) unclassified: the clock may be wrong")
    return out


# ---------------------------------------------------------------- I/O


def fetch(base: str, path: str, token: str | None, timeout: float = 60.0) -> tuple[dict[str, Any], bytes]:
    if any(path.startswith(p) for p in NEVER_READ):
        raise ValueError(f"{path} is never read by the monitor (it cost the fleet a web worker on 2026-11-17)")
    req = urllib.request.Request(base + path, headers={"X-Admin-Token": token} if token else {})
    t0 = time.monotonic()
    meta: dict[str, Any] = {}
    body = b""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            meta["status"] = r.status
    except urllib.error.HTTPError as e:
        meta["status"] = e.code
    except Exception as e:  # noqa: BLE001 -- a failed read is a reading
        meta["status"] = None
        meta["error"] = f"{type(e).__name__}: {str(e)[:100]}"
    meta["seconds"] = round(time.monotonic() - t0, 3)
    meta["kb"] = round(len(body) / 1024.0, 1)
    return meta, body


LOG_SH = r"""#!/bin/bash
# $1 = cutoff ISO (lines start with an ISO timestamp). tail bounds the cost.
# Each role log rotates at 200 MB to <name>.1 (local_production.rotate_running_log). A window that spans a
# rotation lost its first part on 2026-11-17 (reading 5: live-odds-worker.log began 17:56Z, inside a 50-min
# window), so the rotated file's tail is read first; the cutoff filter keeps only the window.
cd ~/syndicate-prod/logs || exit 0
{ tail -c 6000000 web.log.1 2>/dev/null; tail -c 6000000 web.log; } | grep -a -E 'portfolio|WORKER TIMEOUT' | awk -v c="$1" '$1 >= c'
echo '@@WORKERS@@'
for f in live-odds-worker.log refresh-worker.log; do
  { tail -c 40000000 "$f.1" 2>/dev/null; tail -c 40000000 "$f"; } | grep -a -E '\[execute_portfolio\] EXECUTED |\[portfolio_commit\] LIVE_PLAN_WRITTEN |\[execution_ledger\] UNRECONCILABLE_ORDER |\[paper_settlement\] PAPER_ALL_TIME_WRITTEN ' | awk -v c="$1" '$1 >= c'
done
# $2 = the plan-write series' cutoff (PLAN_SERIES_H back): a gap between plan writes can outlast the window.
echo '@@PLANS@@'
for f in live-odds-worker.log refresh-worker.log; do
  { tail -c 40000000 "$f.1" 2>/dev/null; tail -c 40000000 "$f"; } | grep -a '\[portfolio_commit\] LIVE_PLAN_WRITTEN ' | awk -v c="$2" '$1 >= c'
done
"""


def to_wsl_path(p: Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    return f"/mnt/{s[0].lower()}{s[2:]}" if len(s) > 2 and s[1] == ":" else s


def fleet_logs(cutoff: str, work_dir: Path, plan_cutoff: str | None = None
               ) -> tuple[list[str], list[str], list[str], str | None]:
    """(web lines, worker lines, plan-write lines since `plan_cutoff`, error)."""
    sh = work_dir / "portfolio_monitor_logs.sh"
    sh.write_bytes(LOG_SH.encode())  # LF only: bash rejects CRLF
    try:
        r = subprocess.run(["wsl", "--", "nice", "-n", "19", "bash", to_wsl_path(sh), cutoff, plan_cutoff or cutoff],
                           capture_output=True, timeout=240)
        text = r.stdout.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 -- the log half is optional; the HTTP half stands alone
        return [], [], [], f"{type(exc).__name__}: {exc}"
    web, _, rest = text.partition("@@WORKERS@@")
    workers, _, plans = rest.partition("@@PLANS@@")
    return web.splitlines(), workers.splitlines(), plans.splitlines(), None


def set_idle_priority() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)  # IDLE
    except Exception:  # noqa: BLE001
        pass


def gate_reading(orders: list[dict[str, Any]]) -> dict[str, Any]:
    sys.path.insert(0, str(HERE))
    import live_book_edge_readout as rb

    clock = rb.read_clock(ROOT / ".syndicate" / "betting_changes.md", ROOT / ".syndicate" / "deploys.md")
    report = rb.build_report(orders, clock=clock)
    focus_row = next((w for w in report["windows"] if w["window"] == report["focus"]["window"]), {})
    last30 = next((w for w in report["windows"] if w["window"] == "last 30"), {})
    focus = {k: focus_row.get(k) for k in ("window", "from", "bets", "events", "roi_pct", "roi_lo95_pct", "excess_wins")}
    # An empty window summarises to no row at all: that is 0 bets and 0 events, not unknown.
    focus["bets"] = focus["bets"] or 0
    focus["events"] = focus["events"] or 0
    return {
        "clock": report.get("clock"),
        "focus": focus,
        "last30": {k: last30.get(k) for k in ("window", "bets", "events", "roi_pct", "roi_lo95_pct", "excess_wins")},
        "conditions": [{"name": c["name"], "pass": c["pass"], "reading": c["reading"]}
                       for c in report["gate"]["conditions"]],
        "all_pass": report["gate"]["all_pass"],
    }


def render(r: Mapping[str, Any]) -> str:
    lines = [f"PORTFOLIO READING {r['label']} ({r['at']}), log window {r['log_minutes']} min"]
    for name, ep in r["endpoints"].items():
        lines.append(f"  {name:10s} {str(ep.get('status')):>4}  {ep.get('seconds', 0):6.2f}s / {ep['budget_s']}s"
                     f"  {ep.get('kb', 0):8.1f} KB {ep.get('error') or ''}")
    w = r.get("web") or {}
    lines.append(f"  web log: {w.get('worker_timeouts', '?')} worker timeout(s); "
                 + "; ".join(f"{p} n={g['n']} {g['status']} p50={g['p50_ms']} p95={g['p95_ms']} max={g['max_ms']}"
                             f" browser={g['browser']}" for p, g in (w.get("paths") or {}).items()))
    b = r.get("banner") or {}
    lines.append(f"  banner ok={b.get('ok')} bad={b.get('bad_fields')} kill={b.get('kill_switch_engaged')} "
                 f"state {b.get('state_age_s')}s/{b.get('stale_after_s')}s by {b.get('state_recorded_by')} "
                 f"mode={b.get('execution_mode')} armed={b.get('live_armed')} balances {b.get('balances_age_s')}s")
    p = r.get("plan") or {}
    lines.append(f"  plan age {p.get('age_min')} min: board {p.get('board_rows')} -> suggested {p.get('suggested')}"
                 f" -> rows_in {p.get('rows_in')} -> sized {p.get('sized')} -> positions {p.get('positions')};"
                 f" ceiling used {p.get('ceiling_used_pct')}%; sim edge share {p.get('sim_edge_share')};"
                 f" clv join {p.get('clv_join_match_rate')}; refusals {p.get('refusals')}")
    ex = r.get("execution") or {}
    for venue, v in (ex.get("live_ticks") or {}).items():
        lines.append(f"  exec {venue}: {v['ticks']} live ticks placed {v['placed']} filled {v['filled']}"
                     f" failed {v['failed']} refused {v['refused']}")
    pr = ex.get("paper_record")
    lines.append("  paper book (all dates): " + (
        f"{pr.get('won')}W-{pr.get('lost')}L-{pr.get('push')}P of {pr.get('settled')} settled, ROI {pr.get('roi_pct')}%,"
        f" win {pr.get('win_pct')}% ({pr.get('rows')} rows, {pr.get('pending')} pending) at {pr.get('at')}"
        if pr else "no PAPER_ALL_TIME_WRITTEN line in the window (refresh-worker not on the writer yet, or no settle pass)"))
    pc = r.get("plan_commits") or {}
    td = (pc.get("by_date") or {}).get(pc.get("today")) or {}
    lines.append(f"  plan writes for tonight ({pc.get('today')}, last {pc.get('series_h')} h): "
                 + (f"{td.get('commits')} commits, newest {td.get('newest')} ({pc.get('today_newest_age_min')} min ago),"
                    f" max gap {td.get('max_gap_min')} min; other dates "
                    + (", ".join(f"{d} newest {v['newest']}" for d, v in pc["by_date"].items() if d != pc.get("today"))
                       or "none")
                    if td else "none in the series"))
    for venue, pl in (ex.get("plans") or {}).items():
        lines.append(f"  live plan {venue} @{pl['at'][11:19]}Z: rows_in {pl['rows_in']} placeable {pl['placeable_in']}"
                     f" positions {pl['positions']} refusals {pl['refusals']}")
    f = r.get("orders_today") or {}
    lines.append(f"  orders today {f.get('orders')} {f.get('by_status')}; resting {f.get('resting')}"
                 f" ages(min) {f.get('resting_age_min')}")
    s = r.get("settlement") or {}
    lines.append(f"  settlement: {s.get('started_unsettled')} started & unsettled, {s.get('late')} late (> {s.get('lag_h')} h)")
    for venue, c in (r.get("cap_use") or {}).items():
        lines.append(f"  cap {venue}: dollars {c.get('dollars_pct')}% orders {c.get('orders_pct')}% of day cap")
    led = r.get("ledger") or {}
    lines.append(f"  ledger: unknown_submits {led.get('unknown_submits')} unreconciled {led.get('unreconciled')}"
                 f" grade_conflicts {led.get('grade_conflicts')} book {led.get('book_count')}")
    g = r.get("gate") or {}
    if g:
        c = g.get("clock") or {}
        fo = g.get("focus") or {}
        lines.append(f"  gate: clock {c.get('change_id')} from {c.get('start')} -> {fo.get('events')} of"
                     f" {c.get('need')} events ({fo.get('bets')} bets); all_pass={g.get('all_pass')}")
    lines.append("  ANOMALIES: " + ("none" if not r["anomalies"] else ""))
    lines += [f"    - {a}" for a in r["anomalies"]]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--base-url", default=FLEET_BASE_URL)
    ap.add_argument("--out-dir", default=r"C:\tmp\pfmon\readings")
    ap.add_argument("--log-minutes", type=int, default=60)
    ap.add_argument("--no-logs", action="store_true")
    args = ap.parse_args(argv)
    if not re.match(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$", args.base_url.rstrip("/")):
        print(f"refused: {args.base_url} is not the fleet (loopback only)", file=sys.stderr)
        return 2
    set_idle_priority()
    sys.path.insert(0, str(HERE))
    from _base_url import admin_token

    base = args.base_url.rstrip("/")
    token = admin_token(base)
    now = utcnow()
    out_dir = Path(args.out_dir)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    rdir = out_dir / stamp
    rdir.mkdir(parents=True, exist_ok=True)

    endpoints: dict[str, dict[str, Any]] = {}
    bodies: dict[str, Any] = {}
    for name, path, budget in ENDPOINTS:
        meta, body = fetch(base, path, token)
        meta["budget_s"] = budget
        endpoints[name] = meta
        if body and path.startswith("/api/"):
            try:
                bodies[name] = json.loads(body)
            except ValueError:
                meta["error"] = "not JSON"
            (rdir / f"{name}.json").write_bytes(body)

    today = now.astimezone(CT).date().isoformat()
    live_today = bodies.get("live_today") or {}
    live_all = bodies.get("live_all") or {}
    all_orders = list(live_all.get("orders") or [])
    reading: dict[str, Any] = {
        "at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "label": ct_label(now),
        "log_minutes": args.log_minutes,
        "endpoints": endpoints,
        "never_read": list(NEVER_READ),
        "banner": banner(live_today) if live_today else {},
        "plan": plan_funnel(bodies["plan"], now) if bodies.get("plan") else {},
        "orders_today": order_flow(all_orders, today, now),
        "settlement": settlement_lag(all_orders, now),
        "cap_use": cap_use(all_orders, live_all.get("limits") or {}, today),
        "ledger": ledger_flags(live_today) if live_today else {},
    }
    if all_orders:
        try:
            reading["gate"] = gate_reading(all_orders)
        except Exception as exc:  # noqa: BLE001 -- the gate half is optional
            reading["gate"] = {"error": f"{type(exc).__name__}: {exc}"}
    if not args.no_logs:
        cutoff = (now - dt.timedelta(minutes=args.log_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
        plan_cutoff = (now - dt.timedelta(hours=PLAN_SERIES_H)).strftime("%Y-%m-%dT%H:%M:%S")
        web_lines, worker_lines, plan_lines, err = fleet_logs(cutoff, rdir, plan_cutoff)
        reading["web"] = web_access(web_lines, cutoff)
        reading["execution"] = execution(worker_lines, cutoff)
        reading["plan_commits"] = plan_commits(plan_lines, now)
        if err:
            reading["log_error"] = err
    reading["anomalies"] = anomalies(reading)
    (rdir / "reading.json").write_text(json.dumps(reading, indent=1, default=str), encoding="utf-8")
    with (out_dir / "readings.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(reading, default=str) + "\n")
    print(render(reading), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
