"""Favourite-longshot / late-game ("Yogi Berra") bias on Kalshi sports, in play (lane in-game-trading).

Read-only, over scripts/inplay_recorder.py output. Uses inplay_dip_study.load() for the same
markets and live windows. On a 5-min grid per (ticker, leg) while the game is in progress, BUY
the leg at its ask (taker fee) and settle it; report mean settled P&L per contract by
ask-price bucket x game phase:
  phase = early / mid / LATE, where LATE is the final period (NHL period >= 3, NBA/NFL/NCAAF
  quarter >= 4) from ESPN's own period field at the entry time.
Also the maker view: buying at the BID (no fee), i.e. what a resting bid at the touch earns
if filled immediately (an upper bound on maker returns: real fills are adversely selected).

Literature this tests (agent review 2026-10-23): Burgi, Deng & Whelan (Kalshi, 2025/26):
contracts <= 10c lose > 60% after fees, > 70c earn small positive returns; Page (2012) and
Whelan (2025): calibration breaks down late in games, losing teams overpriced.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("inplay_dip_study", ROOT / "scripts" / "inplay_dip_study.py")
dip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dip)

BUCKETS = [(0.0, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 0.90), (0.90, 0.97), (0.97, 1.0)]
LATE_PERIOD = {"nhl": 3, "nba": 4, "nfl": 4, "ncaaf": 4}


def periods(d: Path, sports):
    """(sport, abbr-set) -> sorted [(t, period)] from ESPN."""
    out = defaultdict(list)
    for line in open(d / "espn.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sport") not in sports or r.get("state") != "in":
            continue
        ab = tuple(sorted((x.get("abbr") or "") for x in r.get("teams") or []))
        try:
            out[(r["sport"], ab)].append((dip.ts(r["ts"]), int(r.get("period") or 0)))
        except (TypeError, ValueError):
            continue
    for k in out:
        out[k].sort()
    return out


def phase_at(per, t, sport):
    if not per:
        return "unknown"
    import bisect
    i = bisect.bisect_right([p[0] for p in per], t) - 1
    p = per[max(i, 0)][1]
    late = LATE_PERIOD[sport]
    return "LATE" if p >= late else ("early" if p <= 1 else "mid")


def stat(v):
    v = [x for x in v if x is not None]
    if len(v) < 2:
        return f"{'-':>8} n={len(v)}"
    m = statistics.mean(v)
    se = statistics.stdev(v) / math.sqrt(len(v))
    return f"{m:+.4f} [{m - 1.96 * se:+.3f},{m + 1.96 * se:+.3f}] n={len(v):5d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", nargs="+", required=True)
    ap.add_argument("--sports", default="nhl,nba,ncaaf,nfl")
    a = ap.parse_args()
    sports = [s for s in a.sports.split(",") if s]
    taker = defaultdict(list)
    maker = defaultdict(list)
    games = defaultdict(set)
    for n in sorted(a.nights):
        d = Path(n)
        per = periods(d, sports)
        for m in dip.load(d, sports):
            if m["res"] is None:
                continue
            key = next((k for k in per if m["game"].endswith("|".join(k[1])) and k[0] == m["sport"]), None)
            for leg in ("yes", "no"):
                view = dip.leg_view(m["rows"], leg)
                won = 1.0 if m["res"] == leg else 0.0
                t_next = -1e18
                for t, mid, ask, bid in view:
                    if t < t_next:
                        continue
                    t_next = t + dip.GRID_S
                    ph = phase_at(per.get(key), t, m["sport"])
                    b = next((bk for bk in BUCKETS if bk[0] <= ask < bk[1]), None)
                    if b is None or ph == "unknown":
                        continue
                    taker[(ph, b)].append(won - ask - dip.fee(ask))
                    games[(ph, b)].add(m["game"])
                    if 0 < bid < 1:
                        maker[(ph, b)].append(won - bid)
    print("SETTLED P&L per contract, buying the leg. TAKER = at the ask after fee; MAKER = at the bid, no fee")
    print("(maker is an UPPER bound: an instant fill at the touch; real resting fills are adversely selected)\n")
    for ph in ("early", "mid", "LATE"):
        print(f"--- phase {ph}")
        for b in BUCKETS:
            if (ph, b) not in taker:
                continue
            print(f"  ask {b[0]:.2f}-{b[1]:.2f}  games={len(games[(ph, b)]):3d}  TAKER {stat(taker[(ph, b)])}"
                  f"   MAKER(bid) {stat(maker[(ph, b)])}")
    print("\nNOTE: samples on one game's ladder are correlated; the CI is per-sample (optimistic). Read signs across"
          " buckets/phases and the games count, not the third decimal.")


if __name__ == "__main__":
    main()
