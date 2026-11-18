"""Per-market Kalshi poll gaps over one in-play recorder night (lane inplay-recorder-discovery). Read-only.

    py -3 scripts/inplay_poll_gaps.py C:/tmp/inplay_2026-11-14 [--json out.json]

A gap is the time between two consecutive recorded quotes of one ticker in `kalshi.jsonl`.
It prints the pooled gap p50 / p90 / p99 / max, each market's largest gap, the share of markets
with any gap > 120 s, and per sport.

Every gap > 120 s is given a CAUSE by rebuilding the poll loop's cycles. A cycle walks the
sorted ticker list in batches, and a new cycle starts when a batch's first ticker sorts before
the previous batch's last. Over the complete cycles that fall inside the gap:
  * list   -- a cycle got PAST the ticker's place in the sorted order without returning it, so
              the ticker was not in the polled list (the capture file had dropped it);
  * starve -- every cycle stopped before reaching it (a 429 ended the cycle, or the cycle never
              got that far).
A ticker missing from the list in a region no cycle reached reads `starve`, so `list` is a floor.
Do not compare a cycle-resuming recorder (2026-11-17 on) by cause: its cycles start mid-list.
The pooled and per-market numbers hold for any version.

Two traps this tool cannot see past:
  * a gap ending at the recorder's stop is not counted; `tail_unresolved` counts markets whose
    last quote came > 120 s before the stop without a result;
  * a whole-loop stall (`loop_stalls`, > 60 s between any two batches) gaps every market at once.
"""

from __future__ import annotations

import bisect
import json
import sys
from collections import defaultdict
from datetime import datetime

SPORT_PREFIX = (("KXNCAAF", "ncaaf"), ("KXNBA", "nba"), ("KXNHL", "nhl"), ("KXNFL", "nfl"))


def _ep(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]


def _r1(x):
    return None if x is None else round(x, 1)


def sport_of(ticker: str) -> str:
    return next((s for p, s in SPORT_PREFIX if ticker.startswith(p)), "other")


class _RangeMax:
    """Sparse table: max over xs[lo:hi] in O(1)."""

    def __init__(self, xs):
        self.st = [list(xs)]
        k = 1
        while (1 << k) <= len(xs):
            prev, h = self.st[-1], 1 << (k - 1)
            self.st.append([max(prev[i], prev[i + h]) for i in range(len(prev) - h)])
            k += 1

    def q(self, lo: int, hi: int) -> int:
        if hi <= lo:
            return -1
        j = (hi - lo).bit_length() - 1
        return max(self.st[j][lo], self.st[j][hi - (1 << j)])


def analyse(night_dir: str) -> dict:
    d = night_dir.rstrip("/\\")
    obs: dict[str, list[float]] = defaultdict(list)
    resolved: set[str] = set()
    bmin: dict[float, str] = {}
    bmax: dict[float, str] = {}
    tcache: dict[str, float] = {}
    rows = 0
    with open(f"{d}/kalshi.jsonl", encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ts, t = r.get("ts"), r.get("t")
            if not ts or not t:
                continue
            e = tcache.get(ts)
            if e is None:
                e = tcache[ts] = _ep(ts)
            obs[t].append(e)
            if r.get("res"):
                resolved.add(t)
            if t > bmax.get(e, ""):
                bmax[e] = t
            if e not in bmin or t < bmin[e]:
                bmin[e] = t
            rows += 1
    stop, errors_429 = None, 0
    try:
        with open(f"{d}/log.jsonl", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("event") == "stopped":
                    stop = _ep(r["ts"])
                elif r.get("event") == "kalshi_error" and "429" in str(r.get("err")):
                    errors_429 += 1
    except FileNotFoundError:
        pass
    rank = {t: i for i, t in enumerate(sorted(obs))}
    batches = sorted(bmax)
    stalls = [b - a for a, b in zip(batches, batches[1:]) if b - a > 60]
    cyc_start: list[float] = []
    cyc_end: list[float] = []
    cyc_reach: list[int] = []
    prev_max = None
    for b in batches:
        if prev_max is None or bmin[b] < prev_max:
            cyc_start.append(b)
            cyc_end.append(b)
            cyc_reach.append(rank[bmax[b]])
        else:
            cyc_end[-1] = b
            cyc_reach[-1] = max(cyc_reach[-1], rank[bmax[b]])
        prev_max = bmax[b]
    reach = _RangeMax(cyc_reach)

    gaps: list[float] = []
    per_market_max: dict[str, float] = {}
    over: set[str] = set()
    cause: dict[str, list] = defaultdict(lambda: [0, 0.0])
    sport_gaps: dict[str, list[float]] = defaultdict(list)
    sport_markets: dict[str, set] = defaultdict(set)
    sport_over: dict[str, set] = defaultdict(set)
    tail = 0
    for t, xs in obs.items():
        xs.sort()
        sp = sport_of(t)
        sport_markets[sp].add(t)
        mx = 0.0
        for a, b in zip(xs, xs[1:]):
            g = b - a
            gaps.append(g)
            sport_gaps[sp].append(g)
            mx = max(mx, g)
            if g > 120:
                over.add(t)
                sport_over[sp].add(t)
                lo = bisect.bisect_right(cyc_start, a)  # cycles that start after a ...
                hi = bisect.bisect_left(cyc_end, b)     # ... and end before b
                c = "list" if reach.q(lo, hi) > rank[t] else "starve"
                bucket = "120-300" if g < 300 else "300-600" if g < 600 else "600-1200" if g < 1200 else "1200+"
                for key in (c, f"{c}|{sp}", f"{c}|{bucket}"):
                    cause[key][0] += 1
                    cause[key][1] += g
        per_market_max[t] = mx
        if stop and t not in resolved and stop - xs[-1] > 120:
            tail += 1
    series: dict[str, int] = defaultdict(int)
    for t in obs:
        series[t.split("-", 1)[0]] += 1
    mm = list(per_market_max.values())
    span = (batches[-1] - batches[0]) if len(batches) > 1 else 0.0
    return {
        "dir": d, "rows": rows, "markets": len(obs), "gaps": len(gaps), "span_s": round(span),
        "kalshi_429": errors_429, "loop_stalls": len(stalls), "loop_stall_s": round(sum(stalls)),
        "cycles": len(cyc_start),
        "gap_p50": _r1(_pct(gaps, 0.5)), "gap_p90": _r1(_pct(gaps, 0.9)), "gap_p99": _r1(_pct(gaps, 0.99)),
        "gap_max": _r1(max(gaps) if gaps else None),
        "market_maxgap_p50": _r1(_pct(mm, 0.5)), "market_maxgap_p90": _r1(_pct(mm, 0.9)),
        "markets_any_gap_over_120": len(over),
        "share_any_gap_over_120": round(len(over) / len(obs), 4) if obs else None,
        "gaps_over_120_by_cause": {k: {"n": v[0], "seconds": round(v[1])} for k, v in sorted(cause.items())},
        "tail_unresolved": tail,
        "by_sport": {sp: {"markets": len(sport_markets[sp]), "gap_p50": _r1(_pct(g, 0.5)),
                          "gap_p90": _r1(_pct(g, 0.9)), "gap_max": _r1(max(g) if g else None),
                          "share_any_gap_over_120": round(len(sport_over[sp]) / len(sport_markets[sp]), 4)}
                     for sp, g in sorted(sport_gaps.items())},
        "by_series_markets": dict(sorted(series.items())),
    }


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    rep = analyse(argv[0])
    print(json.dumps(rep, indent=1))
    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
