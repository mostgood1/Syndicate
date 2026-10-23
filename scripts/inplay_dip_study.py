"""Does "buying the dip" pay on Kalshi sports contracts in play? (lane in-game-trading)

Read-only study over scripts/inplay_recorder.py output (C:/tmp/inplay_<date>/). For every
full-game Kalshi market (GAME / SPREAD / TOTAL) of the chosen sports while ESPN shows its
game in progress, both legs (YES, and NO = 1 - YES), on the recorder's 10 s quotes:

  TAKER DIP  : the leg's mid fell by >= D within 60 s. Buy at the ask right then.
  MAKER DIP  : every 5 min per (ticker, leg), rest a bid at mid - k. It FILLS if the leg's
               ask trades down to the bid within 5 min; we buy at the bid, maker fee 0
               (Kalshi quadratic series; a fill shows the market came to us).
  RANDOM     : the same 5-min grid, buying at the ask: the cost baseline.

Each entry: markout = leg mid at +60/+300/+900 s minus price minus fee (the in-play CLV
stand-in), and settled P&L per contract (Kalshi `result`). Split by whether an ESPN score
change happened within +-90 s of the trigger ("news") or not ("noise"). One event per
(ticker, leg) per 5 min; ladder rungs of one game move together, so games are printed
beside n and the CI is a plain normal one (treat it as optimistic).

    py -3 scripts/inplay_dip_study.py --nights C:/tmp/inplay_2026-10-20 C:/tmp/inplay_2026-10-22
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from syndicate.features.shared.venue_fees import kalshi_taker_fee_dollars  # noqa: E402

FAMILIES = {"nhl": ("KXNHLGAME", "KXNHLSPREAD", "KXNHLTOTAL"), "nba": ("KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL"),
            "ncaaf": ("KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL"), "nfl": ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL")}
HORIZONS = (60, 300, 900)
NEWS_WINDOW = 90.0
GRID_S = 300.0


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fee(p):
    return kalshi_taker_fee_dollars(10, p, fee_multiplier=1.0) / 10 if 0 < p < 1 else 0.0


def load(d: Path, sports):
    pref = tuple(p for s in sports for p in FAMILIES[s])
    live_from, live_to, changes, abbrs = {}, {}, defaultdict(list), {}
    last = {}
    for line in open(d / "espn.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sport") not in sports:
            continue
        ab = tuple(sorted((x.get("abbr") or "") for x in r.get("teams") or []))
        k = (r["sport"], ab)
        abbrs[k] = ab
        t = ts(r["ts"])
        sc = tuple(sorted(((x.get("abbr") or ""), x.get("score")) for x in r.get("teams") or []))
        if r.get("state") == "in":
            live_from.setdefault(k, t)
            live_to[k] = t
            if k in last and last[k] != sc:
                changes[k].append(t)
        last[k] = sc
    series, result = defaultdict(list), {}
    for line in open(d / "kalshi.jsonl", encoding="utf-8"):
        r = json.loads(line)
        tk = r.get("t") or ""
        if not tk.startswith(pref):
            continue
        if r.get("res") in ("yes", "no"):
            result[tk] = r["res"]
        if r.get("st") != "active":
            continue
        ya, yb, na, nb = f(r.get("ya")), f(r.get("yb")), f(r.get("na")), f(r.get("nb"))
        if ya is None or yb is None or not (0 < yb <= ya < 1):
            continue
        series[tk].append((ts(r["ts"]), ya, yb, na if na is not None else 1 - yb, nb if nb is not None else 1 - ya))

    def gkey(tk):
        sport = next(s for s in sports if tk.startswith(FAMILIES[s]))
        code = tk.split("-")[1][7:] if "-" in tk else ""
        hits = [k for k in abbrs if k[0] == sport and k[1] and all(a and a in code for a in k[1])]
        return (max(hits, key=lambda k: sum(len(a) for a in k[1])) if hits else None), sport

    out = []
    for tk, rows in series.items():
        gk, sport = gkey(tk)
        if gk is None or gk not in live_from:
            continue
        rows.sort()
        rows = [x for x in rows if live_from[gk] <= x[0] <= live_to[gk] + 60]
        if len(rows) < 10:
            continue
        out.append({"ticker": tk, "sport": sport, "fam": tk.split("-")[0], "game": f"{d.name}:{sport}:{'|'.join(gk[1])}",
                    "rows": rows, "res": result.get(tk), "changes": changes[gk]})
    return out


def leg_view(rows, leg):
    """(t, mid, ask, bid) for the leg; NO uses the NO book."""
    if leg == "yes":
        return [(t, (ya + yb) / 2, ya, yb) for t, ya, yb, na, nb in rows]
    return [(t, (na + nb) / 2, na, nb) for t, ya, yb, na, nb in rows]


def grade(view, times, t0, price, fee_paid, leg, res):
    e = {}
    for h in HORIZONS:
        j = bisect.bisect_left(times, t0 + h)
        e[f"mk{h}"] = (view[j][1] - price - fee_paid) if j < len(view) and view[j][0] - (t0 + h) <= 60 else None
    e["pnl"] = None if res is None else ((1.0 if res == leg else 0.0) - price - fee_paid)
    return e


def near_news(changes, t):
    return any(abs(c - t) <= NEWS_WINDOW for c in changes)


def study(markets, drops=(0.05, 0.10, 0.15), offsets=(0.03, 0.05, 0.10)):
    ev = defaultdict(list)  # (strategy, param) -> entries
    for m in markets:
        for leg in ("yes", "no"):
            view = leg_view(m["rows"], leg)
            times = [v[0] for v in view]
            # TAKER DIP
            for D in drops:
                last_fire = -1e18
                for i, (t, mid, ask, bid) in enumerate(view):
                    if t - last_fire < GRID_S or not (0.05 <= ask <= 0.95):
                        continue
                    j = bisect.bisect_left(times, t - 60)
                    hi = max(v[1] for v in view[j:i + 1])
                    if hi - mid >= D:
                        last_fire = t
                        g = grade(view, times, t, ask, fee(ask), leg, m["res"])
                        ev[("taker_dip", D)].append({**g, "game": m["game"], "sport": m["sport"], "fam": m["fam"],
                                                     "news": near_news(m["changes"], t)})
            # MAKER DIP + RANDOM on a 5-min grid
            t_start = view[0][0]
            k = 0
            while True:
                t0 = t_start + k * GRID_S
                k += 1
                i0 = bisect.bisect_left(times, t0)
                if i0 >= len(view):
                    break
                _, mid0, ask0, _ = view[i0]
                if not (0.08 <= mid0 <= 0.92):
                    continue
                g = grade(view, times, view[i0][0], ask0, fee(ask0), leg, m["res"])
                ev[("random_taker", 0)].append({**g, "game": m["game"], "sport": m["sport"], "fam": m["fam"],
                                                "news": near_news(m["changes"], view[i0][0])})
                for off in offsets:
                    bid_px = round(mid0 - off, 2)
                    if bid_px <= 0.02:
                        continue
                    i_end = bisect.bisect_right(times, view[i0][0] + GRID_S)
                    fill = next((v for v in view[i0 + 1:i_end] if v[2] <= bid_px), None)
                    if fill is None:
                        continue
                    g = grade(view, times, fill[0], bid_px, 0.0, leg, m["res"])
                    ev[("maker_bid", off)].append({**g, "game": m["game"], "sport": m["sport"], "fam": m["fam"],
                                                   "news": near_news(m["changes"], fill[0])})
    return ev


def stat(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "      -          "
    m = statistics.mean(vals)
    se = statistics.stdev(vals) / math.sqrt(len(vals)) if len(vals) > 1 else float("nan")
    return f"{m:+.4f} [{m - 1.96 * se:+.3f},{m + 1.96 * se:+.3f}] n={len(vals)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", nargs="+", required=True)
    ap.add_argument("--sports", default="nhl,nba,ncaaf,nfl")
    a = ap.parse_args()
    sports = [s for s in a.sports.split(",") if s]
    markets = []
    for n in sorted(a.nights):
        ms = load(Path(n), sports)
        print(f"NIGHT {Path(n).name}: {len(ms)} in-play markets, {len({m['game'] for m in ms})} games", flush=True)
        markets += ms
    ev = study(markets)
    print(f"\nTOTAL {len(markets)} markets, {len({m['game'] for m in markets})} games, sports={sports}")
    print("Values are $ per contract after fee: mean [95% CI] n.  mk = leg mid later minus price minus fee.\n")
    for key in sorted(ev, key=lambda k: (k[0], k[1])):
        es = ev[key]
        for label, grp in (("ALL", es), ("noise (no score +-90s)", [e for e in es if not e["news"]]),
                           ("news  (score +-90s)", [e for e in es if e["news"]])):
            if not grp:
                continue
            print(f"{key[0]:12s} {key[1]:<5} {label:22s} games={len({e['game'] for e in grp}):3d}"
                  f" mk60 {stat([e['mk60'] for e in grp])}  mk300 {stat([e['mk300'] for e in grp])}"
                  f"  mk900 {stat([e['mk900'] for e in grp])}  settled {stat([e['pnl'] for e in grp])}")
        print()
    print("BY SPORT (taker_dip 0.10 and maker_bid 0.05, ALL):")
    for key in (("taker_dip", 0.10), ("maker_bid", 0.05), ("random_taker", 0)):
        for s in sports:
            grp = [e for e in ev.get(key, []) if e["sport"] == s]
            if grp:
                print(f"  {key[0]:12s} {key[1]:<5} {s:6s} games={len({e['game'] for e in grp}):3d}"
                      f" mk300 {stat([e['mk300'] for e in grp])}  settled {stat([e['pnl'] for e in grp])}")


if __name__ == "__main__":
    main()
