"""Paper bet optimization -- the pre-registered study (prereg_bet_optimization.md). Reads ledger.json only.

usage: py -3 scripts/paper_bet_optimization.py LEDGER_JSON REPO_ROOT [--forward SINCE_ISO]

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
LIVE = ("kalshi", "polymarket")
BOOK_OF = {"paper:kalshi": "kalshi", "paper:polymarket": "polymarket", "paper:prophetx": "prophetx", "paper:novig": "novig", "paper": None,
           "kalshi": "kalshi", "polymarket": "polymarket"}


def dec(a):
    """Decimal odds from American odds OR a live venue contract price (0 < p < 1).

    LIVE kalshi/polymarket rows record `fill_price` as the contract price, and read as
    American a 0.65 fill is 1.0065 (todo #719). Unit rule: `paper_settlement.profit_per_dollar`.
    """
    from syndicate.features.shared.paper_settlement import profit_per_dollar

    profit = profit_per_dollar(a)
    if profit is None:
        raise ValueError(f"unusable price {a!r}")
    return 1 + profit


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
        if v not in PRIMARY + SECONDARY + LIVE or r.get("outcome") not in ("won", "lost") or r.get("ev_pct") is None:
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
        # The fair comes out of the price ev_pct was STAMPED at -- `requested_price`, American on a
        # live row (venue_scope.py) -- not the contract fill; a paper fill copies it, so paper is unchanged.
        p_fair = (1 + float(r["ev_pct"]) / 100) / (dec(r["requested_price"]) if r.get("requested_price") not in (None, 0) else d)
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
            "stake": stake, "pnl": float(r.get("pnl_dollars") or 0.0),
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


def diff(a, b):
    """Flat-ROI difference a - b (points) and its SE, treating the two groups as independent."""
    ma, sa, na, _ = clustered(a)
    mb, sb, nb, _ = clustered(b)
    return ma - mb, math.sqrt(sa * sa + sb * sb), na, nb


def forward(rows, since):
    """The FORWARD test pre-registered 2026-10-20 (findings_2026-10-20_paper_bet_optimization.md, 'Forward test')."""
    pop = [r for r in rows if r["sub"] >= since]
    venue = [r for r in pop if r["venue"] in PRIMARY + LIVE]
    other = [r for r in pop if r["venue"] in SECONDARY]
    live = [r for r in pop if r["venue"] in LIVE]
    dates = sorted({r["date"] for r in pop})
    print(f"FORWARD since {since}: dates {dates[0] if dates else None}..{dates[-1] if dates else None} ({len(dates)}), "
          f"venue+live {len(venue)} (paper:kalshi {sum(r['venue']=='paper:kalshi' for r in venue)}, paper:polymarket "
          f"{sum(r['venue']=='paper:polymarket' for r in venue)}, live {len(live)}), other books {len(other)}")
    for name, group in (("H3 venue+live", venue), ("other books", other), ("live only", live)):
        print(f"  {name:14s} {fmt(group)}")
    if live:
        st = sum(r["stake"] for r in live); pnl = sum(r["pnl"] for r in live)
        print(f"  live dollars: staked ${st:.2f}, pnl ${pnl:+.2f}, stake ROI {100*pnl/st if st else float('nan'):+.1f}%")
    for name, group in (("venue+live", venue), ("other books", other)):
        d, se, na, nb = diff([r for r in group if r["live"]], [r for r in group if not r["live"]])
        print(f"  H1 {name:11s} in-play minus pregame {d:+6.1f} ± {se:4.1f} pts (n {na} / {nb})")
        d, se, na, nb = diff([r for r in group if r["imp"] < .5], [r for r in group if r["imp"] >= .5])
        print(f"  H2 {name:11s} underdog minus favourite {d:+6.1f} ± {se:4.1f} pts (n {na} / {nb})")
    m, se, n, e = clustered(venue)
    print("  DECISION (pre-registered):")
    if n < 300:
        print(f"    INSUFFICIENT: {n} venue+live bets < 300 -- no decision; keep collecting")
    elif m + 2 * se < 0:
        print(f"    BAND: venue+live ROI {m:+.1f} ± {se:.1f} is >= 2 SE below zero -- recommend the user turn the $5-$10 band OFF")
    elif m - 2 * se > 0:
        print(f"    BAND: venue+live ROI {m:+.1f} ± {se:.1f} is >= 2 SE above zero -- band supported; consider widening only per cell")
    else:
        print(f"    BAND: venue+live ROI {m:+.1f} ± {se:.1f} straddles zero -- no change; keep collecting")
    for name, group in (("venue+live", venue), ("other books", other)):
        d, se, na, nb = diff([r for r in group if r["live"]], [r for r in group if not r["live"]])
        if min(na, nb) >= 100 and d + 2 * se < 0:
            print(f"    IN-PLAY ({name}): in-play is >= 2 SE worse than pregame -- propose a per-cell in-play EV floor via the min_ev tuner (never a ban)")


rows = load()
if len(sys.argv) > 4 and sys.argv[3] == "--forward":
    forward(rows, sys.argv[4])
    sys.exit(0)
prim = [r for r in rows if r["venue"] in PRIMARY]
sec = [r for r in rows if r["venue"] in SECONDARY]
report(prim, "PRIMARY: paper:kalshi + paper:polymarket")
segments(prim, "PRIMARY")
report(sec, "SECONDARY: paper:prophetx + paper:novig + paper (unrestricted)")
segments(sec, "SECONDARY")
