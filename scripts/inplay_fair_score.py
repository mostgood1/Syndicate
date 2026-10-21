"""Score an in-game MODEL fair against Kalshi's mid and the books, at settlement.
Lane in-game-trading, stage 2 measurement. Read-only.

Input: the NBA live re-sim's live_gameline_ledger_<date>.jsonl (fleet,
nba_source/data/live_gameline_ledger/) and scripts/inplay_recorder.py output.

Rows scored: segment `full`, markets `h2h` (P(home wins)) and `totals` /
`totals_alt` (P(over line)), with a model probability. Spreads are NOT scored:
the ledger's `line` sign convention for spreads was not verified.

For each row: the model prob, the books' no-vig (`market_fair_prob`), and the
Kalshi mid of the matching market at recorded_at (latest Kalshi sample at most
60 s before). Outcome from ESPN's final score. Brier per source over the rows
where all three exist, plus the mean |model - Kalshi| and the markout of
"model says buy" sides (model - ask - fee > 0) at +300 s vs Kalshi's mid.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from syndicate.features.shared.venue_fees import kalshi_taker_fee_dollars  # noqa: E402


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


CITY = {"New York Knicks": "New York", "San Antonio Spurs": "San Antonio", "Philadelphia 76ers": "Philadelphia",
        "Oklahoma City Thunder": "Oklahoma City", "Detroit Pistons": "Detroit", "Boston Celtics": "Boston"}
ESPN_ABBR = {"New York Knicks": "NY", "San Antonio Spurs": "SA", "Philadelphia 76ers": "PHI", "Oklahoma City Thunder": "OKC",
             "Detroit Pistons": "DET", "Boston Celtics": "BOS"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    d = Path(a.dir)
    txt = open(a.ledger, encoding="utf-8").read()
    rows = [json.loads(x) for x in txt.replace("}{", "}\n{").splitlines() if x.strip()]

    finals = {}
    for line in open(d / "espn.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("state") == "post":
            finals[frozenset(t["abbr"] for t in r["teams"])] = {t["abbr"]: int(t["score"]) for t in r["teams"]}

    kal = defaultdict(list)  # ticker -> [(t, ya, yb, na, nb)]
    meta = {}
    for line in open(d / "kalshi.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if not r["t"].startswith(("KXNBAGAME", "KXNBATOTAL")) or r.get("st") != "active":
            continue
        kal[r["t"]].append((ts(r["ts"]), f(r["ya"]), f(r["yb"]), f(r["na"]), f(r["nb"])))
        meta[r["t"]] = r
    for t in kal:
        kal[t].sort()
    times = {t: [x[0] for x in v] for t, v in kal.items()}

    def quote(t, when, max_age=60):
        i = bisect.bisect_right(times.get(t, []), when) - 1
        if i < 0 or when - kal[t][i][0] > max_age:
            return None
        return kal[t][i]

    out = []
    for r in rows:
        if r.get("segment") != "full" or r.get("model_home_win_prob") is None:
            continue
        home, away = r["home_team"], r["away_team"]
        fin = finals.get(frozenset((ESPN_ABBR.get(home), ESPN_ABBR.get(away))))
        if not fin:
            continue
        hs, as_ = fin[ESPN_ABBR[home]], fin[ESPN_ABBR[away]]
        t = ts(r["recorded_at"])
        if r["market"] == "h2h":
            tick = next((k for k, m in meta.items() if k.startswith("KXNBAGAME") and m.get("sub") == CITY.get(home)
                         and CITY.get(away, "?")[:3].upper() in k.replace("OKC", "OKL")), None)
            tick = tick or next((k for k, m in meta.items() if k.startswith("KXNBAGAME") and m.get("sub") == CITY.get(home)), None)
            outcome = 1.0 if hs > as_ else 0.0
        elif r["market"] in ("totals", "totals_alt"):
            L = f(r.get("line"))
            tick = next((k for k, m in meta.items() if k.startswith("KXNBATOTAL") and f(m.get("fs")) == L
                         and CITY.get(home, "?") and ESPN_ABBR.get(home) and any(x in k for x in ("NYK", "SAS")) and
                         (("NYK" in k) == (home == "New York Knicks"))), None)
            outcome = 1.0 if hs + as_ > L else 0.0
        else:
            continue
        q = quote(tick, t) if tick else None
        if not q or q[1] is None or q[2] is None:
            continue
        mid = (q[1] + q[2]) / 2
        later = quote(tick, t + 300)
        out.append({"t": t, "market": r["market"], "line": r.get("line"), "model": r["model_home_win_prob"],
                    "book": r.get("market_fair_prob"), "kalshi": mid, "ya": q[1], "na": q[3], "y": outcome,
                    "mid300": None if not later or later[2] is None else (later[1] + later[2]) / 2,
                    "home": home, "sims": r.get("sims_run")})

    print(f"ROWS scored: {len(out)} (full-game h2h + totals with a model prob, a Kalshi quote <=60 s old and a final)")
    for mk in ("h2h", "totals"):
        grp = [o for o in out if (o["market"] == "h2h") == (mk == "h2h") and o["book"] is not None]
        if not grp:
            continue
        b = {s: sum((o[s] - o["y"]) ** 2 for o in grp) / len(grp) for s in ("model", "book", "kalshi")}
        gap = sorted(abs(o["model"] - o["kalshi"]) for o in grp)
        snaps = len({o["t"] for o in grp})
        games = len({o["home"] for o in grp})
        print(f"{mk}: n={len(grp)} rows over {snaps} snapshots, {games} game(s). Brier model {b['model']:.4f} | books {b['book']:.4f} | Kalshi mid {b['kalshi']:.4f}"
              f"   |model-Kalshi| p50 {gap[len(gap)//2]:.3f} p90 {gap[int(len(gap)*0.9)]:.3f}")
        buys = []
        for o in grp:
            for side, ask, p, m300 in (("yes", o["ya"], o["model"], o["mid300"]), ("no", o["na"], 1 - o["model"], None if o["mid300"] is None else 1 - o["mid300"])):
                if ask is None or not (0 < ask < 1):
                    continue
                fee = kalshi_taker_fee_dollars(10, ask, fee_multiplier=1.0) / 10
                if p - ask - fee > 0:
                    won = o["y"] if side == "yes" else 1 - o["y"]
                    buys.append((m300 - ask - fee if m300 is not None else None, won - ask - fee))
        if buys:
            mk300 = [x[0] for x in buys if x[0] is not None]
            print(f"   model-says-buy sides: {len(buys)}; markout +300s mean {sum(mk300)/max(1,len(mk300)):+.4f} (n={len(mk300)}); "
                  f"settled P&L/contract mean {sum(x[1] for x in buys)/len(buys):+.4f}  (rows are repeated snapshots of the SAME games: not independent)")


if __name__ == "__main__":
    main()
