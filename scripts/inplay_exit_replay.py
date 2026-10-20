"""Replay the take-profit exit at FAST (every recorded quote, ~10 s) vs SLOW (every
--slow-seconds, the execution tick) cadence over a night of in-play Kalshi quotes.
Lane in-game-trading; reads scripts/inplay_recorder.py output only.

Population. Every recorded Kalshi game line (GAME/SPREAD/TOTAL), entered in
paper at the ASK of the first quote after ESPN shows the game in progress, on
BOTH legs (YES and NO are separate positions), --contracts contracts, plus a
taker entry fee. Asks outside [0.05, 0.95] are skipped. This is a synthetic
book whose purpose is to compare CADENCES on identical positions; it says
nothing about whether entering at kickoff is profitable.

Rule. execution_exits.evaluate_exit's take_profit: net bid (bid less the
taker exit fee per contract) minus entry cost per contract >= margin.

Outcome. Kalshi's own `result` on the finalized market (yes/no). Positions on
markets not finalized by the end of the recording are reported as unsettled
and left out of P&L.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from syndicate.features.shared.venue_fees import kalshi_taker_fee_dollars  # noqa: E402


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fee(c: float, p: float) -> float:
    return kalshi_taker_fee_dollars(c, p, fee_multiplier=1.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--contracts", type=float, default=10.0)
    ap.add_argument("--slow-seconds", type=float, default=360.0)
    ap.add_argument("--margins", default="0.04,0.08,0.15")
    a = ap.parse_args()
    d = Path(a.dir)
    margins = [float(x) for x in a.margins.split(",")]

    # ESPN: first in-progress time per game key "ABBR|ABBR".
    started: dict[str, float] = {}
    abbrs: dict[str, tuple] = {}
    for line in open(d / "espn.jsonl", encoding="utf-8"):
        r = json.loads(line)
        ab = tuple(sorted(x["abbr"] or "" for x in r["teams"]))
        k = "|".join(ab)
        abbrs[k] = ab
        if r.get("state") == "in" and k not in started:
            started[k] = ts(r["ts"])

    def start_for(ticker: str):
        code = ticker.split("-")[1][7:]
        cands = [k for k, ab in abbrs.items() if ab and all(x and x in code for x in ab)]
        if not cands:
            return None
        k = max(cands, key=lambda k: sum(len(x) for x in abbrs[k]))
        return started.get(k)

    series = defaultdict(list)
    result = {}
    for line in open(d / "kalshi.jsonl", encoding="utf-8"):
        r = json.loads(line)
        fam = r["t"].split("-")[0]
        if not fam.endswith(("GAME", "SPREAD", "TOTAL")):
            continue
        if r.get("res") in ("yes", "no"):
            result[r["t"]] = r["res"]
        if r.get("st") == "active":
            series[r["t"]].append((ts(r["ts"]), f(r.get("ya")), f(r.get("yb")), f(r.get("na")), f(r.get("nb"))))

    C = a.contracts
    stats = {m: defaultdict(float) for m in margins}
    n_pos, skipped = 0, defaultdict(int)
    for t, rows in series.items():
        st = start_for(t)
        if st is None:
            skipped["no_espn_start"] += 1
            continue
        rows.sort()
        live = [x for x in rows if x[0] >= st]
        if len(live) < 2:
            skipped["no_inplay_quotes"] += 1
            continue
        t0, ya, yb, na, nb = live[0]
        for leg, ask, bid_i in (("yes", ya, 2), ("no", na, 4)):
            if ask is None or not (0.05 <= ask <= 0.95):
                skipped["ask_out_of_band"] += 1
                continue
            n_pos += 1
            entry_fee = fee(C, ask)
            cost = ask + entry_fee / C
            settle = result.get(t)
            hold = None if settle is None else C * ((1.0 if settle == leg else 0.0) - ask) - entry_fee
            for m in margins:
                s = stats[m]
                fast_hit = None
                for x in live:
                    bid = x[bid_i]
                    if bid is None or bid <= 0:
                        continue
                    if bid - fee(C, bid) / C - cost >= m - 1e-9:
                        fast_hit = (x[0], bid)
                        break
                # SLOW: only the first quote at/after each tick boundary is looked at.
                slow_hit = None
                k = 1
                for x in live:
                    if x[0] < t0 + k * a.slow_seconds:
                        continue
                    k = int((x[0] - t0) // a.slow_seconds) + 1
                    bid = x[bid_i]
                    if bid is None or bid <= 0:
                        continue
                    net = bid - fee(C, bid) / C
                    if net - cost >= m - 1e-9:
                        slow_hit = (x[0], bid)
                        break
                s["positions"] += 1
                for name, hit in (("fast", fast_hit), ("slow", slow_hit)):
                    if hit:
                        s[f"{name}_triggers"] += 1
                        s[f"{name}_bid_sum"] += hit[1]
                        s[f"{name}_delay_sum"] += hit[0] - t0
                if fast_hit and slow_hit:
                    s["both"] += 1
                    s["bid_gap_sum"] += slow_hit[1] - fast_hit[1]
                    s["lag_sum"] += slow_hit[0] - fast_hit[0]
                if hold is not None:
                    s["settled"] += 1
                    s["hold_pnl"] += hold
                    for name, hit in (("fast", fast_hit), ("slow", slow_hit)):
                        pnl = hold if hit is None else (C * hit[1] - fee(C, hit[1]) - C * ask - entry_fee)
                        s[f"{name}_pnl"] += pnl
                    s["staked"] += C * ask + entry_fee

    print(f"POSITIONS (synthetic, both legs, {C:.0f} contracts, entered at the ask at ESPN in-progress): {n_pos}  skipped={dict(skipped)}")
    print(f"slow cadence = {a.slow_seconds:.0f}s; fast = every recorded quote")
    for m in margins:
        s = stats[m]
        ft, sl = s["fast_triggers"], s["slow_triggers"]
        print(f"\nMARGIN {m:.2f}: positions={int(s['positions'])}")
        print(f"  triggers: fast {int(ft)} ({ft/max(1,s['positions']):.1%})  slow {int(sl)} ({sl/max(1,s['positions']):.1%})")
        if s["both"]:
            print(f"  both triggered: {int(s['both'])}; slow sold {s['bid_gap_sum']/s['both']:+.4f}/contract vs fast, "
                  f"{s['lag_sum']/s['both']:.0f}s later on average")
        if s["settled"]:
            st = s["staked"]
            print(f"  settled {int(s['settled'])}: P&L hold {s['hold_pnl']:+.2f}  fast-exit {s['fast_pnl']:+.2f}  slow-exit {s['slow_pnl']:+.2f}"
                  f"  (staked {st:.2f}; ROI hold {s['hold_pnl']/st:+.2%} fast {s['fast_pnl']/st:+.2%} slow {s['slow_pnl']/st:+.2%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
