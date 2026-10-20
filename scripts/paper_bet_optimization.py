"""Paper bet optimization -- the pre-registered study (prereg_bet_optimization.md). Reads ledger.json only.

usage: py -3 scripts/paper_bet_optimization.py LEDGER_JSON REPO_ROOT

LEDGER_JSON = `execution_ledger.full_history_orders()` dumped read-only on the fleet (nice 19).
Findings: .syndicate/findings_2026-10-20_paper_bet_optimization.md
"""
import collections, json, math, sys
from datetime import datetime

LEDGER, REPO = sys.argv[1], sys.argv[2]
sys.path.insert(0, REPO)
from syndicate.features.shared import venue_fees  # fee imputation for rows with no recorded fee

PRIMARY = ("paper:kalshi", "paper:polymarket")
SECONDARY = ("paper:prophetx", "paper:novig", "paper")
BOOK_OF = {"paper:kalshi": "kalshi", "paper:polymarket": "polymarket", "paper:prophetx": "prophetx", "paper:novig": "novig", "paper": None}


def dec(a):
    a = float(a)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def family(r):
    if str(r.get("player_name") or "").strip():
        return "prop"
    m = str(r.get("market") or "").lower()
    for key, fam in (("total", "total"), ("spread", "spread"), ("h2h", "h2h")):
        if key in m:
            return fam
    return "other"


def ts(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def load():
    orders = json.load(open(LEDGER))
    seen, rows = set(), []
    orders.sort(key=lambda r: str(r.get("submitted_at") or ""))
    for r in orders:
        v = str(r.get("venue"))
        if v not in PRIMARY + SECONDARY or r.get("outcome") not in ("won", "lost") or r.get("ev_pct") is None:
            continue
        if r.get("fill_price") in (None, 0) or not float(r.get("fill_stake_dollars") or 0):
            continue
        key = (v, r.get("opening_key") or r.get("position_key"))
        if key in seen:
            continue
        seen.add(key)
        d = dec(r["fill_price"])
        stake = float(r["fill_stake_dollars"])
        fee = float(r.get("fees_dollars") or 0.0)
        imputed = False
        if fee <= 0 and BOOK_OF[v]:
            try:
                per, _b, _u = venue_fees.taker_fee_per_contract(BOOK_OF[v], 1.0 / d, sport=r.get("sport"), market=r.get("market"), segment=r.get("segment"))
                fee = float(per or 0.0) * stake * d   # contracts = stake / price = stake * d
                imputed = fee > 0
            except Exception:
                pass
        fee_frac = fee / stake
        won = r["outcome"] == "won"
        ret = (d - 1 - fee_frac) if won else (-1 - fee_frac)   # per $1 staked, net of fee
        p_fair = (1 + float(r["ev_pct"]) / 100) / d
        q_cost = 1.0 / d + fee_frac / d                          # price + fee per $1 payout
        ev_net = 100 * (p_fair - q_cost) / q_cost
        wb, lb = d - 1 - fee_frac, 1 + fee_frac
        kelly = max(0.0, (p_fair * wb - (1 - p_fair) * lb) / (wb * lb)) if wb > 0 else 0.0
        sub, ko = ts(r.get("submitted_at")), ts(r.get("commence_time"))
        rows.append({
            "venue": v, "date": str(r.get("selected_date")), "sub": str(r.get("submitted_at") or ""),
            "event": str(r.get("event_id") or key[1]), "sport": str(r.get("sport") or "?").lower(), "fam": family(r),
            "ev": float(r["ev_pct"]), "ev_net": ev_net, "kelly": kelly, "ret": ret, "won": won, "d": d,
            "imp": 1.0 / d, "sim_view": str(r.get("sim_view") or "none"),
            "live": (sub is not None and ko is not None and sub >= ko), "fee_imputed": imputed,
            "hours": ((ko - sub).total_seconds() / 3600) if sub and ko else None,
        })
    return rows


def clustered(rows, f=lambda r: r["ret"]):
    n = len(rows)
    if not n:
        return float("nan"), float("nan"), 0, 0
    m = sum(f(r) for r in rows) / n
    g = collections.defaultdict(float)
    for r in rows:
        g[r["event"]] += f(r) - m
    return 100 * m, 100 * math.sqrt(sum(v * v for v in g.values())) / n, n, len(g)


def fmt(rows):
    m, se, n, e = clustered(rows)
    return f"ROI {m:+6.1f}% ± {se:4.1f}  (n {n}, events {e})"


def selection_rules():
    rules = {"S0 all": lambda r: True}
    for f in (0, 1, 2, 3, 4):
        rules[f"S1 ev_net>={f}"] = (lambda f: lambda r: r["ev_net"] >= f)(f)
    for f in (0, 2):
        for c in (6, 8):
            rules[f"S2 {f}<=ev_net<{c}"] = (lambda f, c: lambda r: f <= r["ev_net"] < c)(f, c)
    rules["S4 sim_view!=disagrees"] = lambda r: r["sim_view"] != "disagrees"
    return rules


def walk_forward_cell_floor(rows, floors=(0, 1, 2, 3, 4), min_train=30):
    """S3: per sport x family, the floor with the best TRAINING ROI on dates < d; scored on d."""
    dates = sorted({r["date"] for r in rows})
    chosen = []
    for d in dates[3:]:
        train = [r for r in rows if r["date"] < d]
        test = [r for r in rows if r["date"] == d]
        best = {}
        cells = collections.defaultdict(list)
        for r in train:
            cells[(r["sport"], r["fam"])].append(r)
        for cell, rs in cells.items():
            scored = [(clustered([x for x in rs if x["ev_net"] >= f])[0], f) for f in floors if len([x for x in rs if x["ev_net"] >= f]) >= min_train]
            best[cell] = max(scored)[1] if scored else 0
        chosen += [r for r in test if r["ev_net"] >= best.get((r["sport"], r["fam"]), 0)]
    return chosen


def sizing(rows, rule, bankroll=465.0):
    """Sequential log growth by submit time; returns final bankroll, staked, pnl, max drawdown."""
    b, peak, mdd, staked, pnl = bankroll, bankroll, 0.0, 0.0, 0.0
    for r in sorted(rows, key=lambda r: r["sub"]):
        s = rule(r, b)
        s = min(s, b)
        if s <= 0:
            continue
        gain = s * r["ret"]
        b += gain
        staked += s
        pnl += gain
        peak = max(peak, b)
        mdd = max(mdd, (peak - b) / peak)
    return b, staked, pnl, mdd


SIZERS = {
    "Z0 flat $1": lambda r, b: 1.0,
    "Z1 band $5-10": lambda r, b: min(10.0, 5.0 + 5.0 * r["kelly"] / 0.05),
    "Z2 quarter Kelly": lambda r, b: 0.25 * r["kelly"] * b,
    "Z3 flat $5": lambda r, b: 5.0,
}


def report(rows, title):
    print(f"\n### {title}")
    dates = sorted({r["date"] for r in rows})
    print(f"dates {dates[0]}..{dates[-1]} ({len(dates)}), rows {len(rows)}, events {len({r['event'] for r in rows})}, "
          f"fee imputed {sum(r['fee_imputed'] for r in rows)}, in-play {sum(r['live'] for r in rows)}")
    oos_dates = set(dates[3:])
    oos = [r for r in rows if r["date"] in oos_dates]
    print(f"out-of-sample window = dates[3:] {min(oos_dates)}..{max(oos_dates)}: {len(oos)} rows")
    base = clustered(oos)
    print(f"{'rule':28s} {fmt(oos)}  <- S0 baseline")
    for name, f in selection_rules().items():
        sel = [r for r in oos if f(r)]
        m, se, n, e = clustered(sel)
        print(f"{name:28s} {fmt(sel)}  diff vs S0 {m - base[0]:+5.1f}")
    s3 = walk_forward_cell_floor(rows)
    m, se, n, e = clustered(s3)
    print(f"{'S3 cell floor (walk-fwd)':28s} {fmt(s3)}  diff vs S0 {m - base[0]:+5.1f}")
    print("\nsizing on S0 (all rows, every date, $465 start):")
    for name, z in SIZERS.items():
        b, st, pnl, mdd = sizing(rows, z)
        print(f"  {name:18s} end ${b:8.2f}  staked ${st:9.2f}  pnl ${pnl:+8.2f}  ROI {100*pnl/st if st else float('nan'):+5.1f}%  maxDD {100*mdd:4.1f}%")


def segments(rows, title):
    print(f"\n### {title}: flat ROI by segment (all dates; descriptive, NOT a selection rule)")
    for key in ("venue", "sport", "fam", "sim_view", "live"):
        g = collections.defaultdict(list)
        for r in rows:
            g[r[key]].append(r)
        for k, rs in sorted(g.items(), key=lambda kv: -len(kv[1])):
            print(f"  {key:9s} {str(k):12s} {fmt(rs)}")
    g = collections.defaultdict(list)
    for r in rows:
        band = "<0" if r["ev_net"] < 0 else "0-2" if r["ev_net"] < 2 else "2-4" if r["ev_net"] < 4 else "4-6" if r["ev_net"] < 6 else "6+"
        g[band].append(r)
    for k in ("<0", "0-2", "2-4", "4-6", "6+"):
        if k in g:
            print(f"  ev_net    {k:12s} {fmt(g[k])}")
    g = collections.defaultdict(list)
    for r in rows:
        g["fav(imp>=.5)" if r["imp"] >= 0.5 else "dog(imp<.5)"].append(r)
    for k, rs in g.items():
        print(f"  price     {k:12s} {fmt(rs)}")


rows = load()
prim = [r for r in rows if r["venue"] in PRIMARY]
sec = [r for r in rows if r["venue"] in SECONDARY]
report(prim, "PRIMARY: paper:kalshi + paper:polymarket")
segments(prim, "PRIMARY")
report(sec, "SECONDARY: paper:prophetx + paper:novig + paper (unrestricted)")
segments(sec, "SECONDARY")
