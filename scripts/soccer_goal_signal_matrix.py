"""Every event type, alone and combined, crossed with time -- full match.

WHAT THE EARLIER SWEEPS GOT WRONG, and both were my own limits rather than the
data's:

1. THE MATCH DID NOT END AT 85'. Sampling ran `start=300, end=5100`, so the
   final minutes -- the densest scoring period in football -- were never a
   decision point at all. Now sampled to 5700s (95'), stoppage included.
2. EVENT TYPES WERE NEVER TESTED INDIVIDUALLY. The weight variants moved four
   shot families together, so a type that mattered on its own could not be
   seen, and several types (`penalty---scored`, `free-kick`, `own-goal`) were
   silently unweighted because the names were GUESSED rather than read from the
   feed.

TRUNCATION IS REAL AND IS NOT CORRECTED FOR. A sample at 88' has a 10-minute
window that the final whistle cuts short. That is exactly what a bettor faces,
so the label stays "a goal actually happened in that window" -- shortening the
window is the bet getting worse, not the measurement being wrong. The
`window_minutes_available` column makes it visible rather than hidden.

EVERY NUMBER HERE IS HOLDOUT. Fit matches are used only to fix decile
boundaries, never scored.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.soccer_momentum_goal_fit import _is_holdout

_MATCH_END = 5700.0          # 95': nominal 90 plus typical stoppage
_HALF = 2700.0


def load(cache: Path) -> list[dict]:
    return json.loads(cache.read_text(encoding="utf-8"))["matches"]


def type_pressure(events: list[dict], t: float, half_life: float, types: set[str]) -> float:
    """Decayed count of the named types, BOTH sides, at or before t."""
    total = 0.0
    for e in events:
        if e["t"] > t or e["type"] not in types:
            continue
        total += math.pow(0.5, (t - e["t"]) / max(1.0, half_life))
    return total


def samples_for(matches: list[dict], types: set[str], *, half_life: float,
                window: float, step: float) -> list[dict]:
    out: list[dict] = []
    for m in matches:
        ev, goals = m["events"], m["goals"]
        # The real end of THIS match: last event or goal, whichever is later.
        # Sampling past it would invent decision points that never existed.
        last = max([e["t"] for e in ev] + [g["t"] for g in goals] + [0.0])
        end = min(_MATCH_END, last)
        t = 60.0
        while t <= end:
            avail = max(0.0, min(window, end - t))
            if avail >= 120.0:      # a window under 2 min is not a bet
                out.append({
                    "t": t,
                    "p": type_pressure(ev, t, half_life, types),
                    "label": 1 if any(t < g["t"] <= t + window for g in goals) else 0,
                    "window_avail": avail,
                })
            t += step
    return out


def top_decile_hit(rows: list[dict]) -> tuple[float, float, int]:
    """(base, top-decile hit, n) -- the slice a bet would actually fire on."""
    if not rows:
        return 0.0, 0.0, 0
    base = statistics.mean([r["label"] for r in rows])
    ordered = sorted(rows, key=lambda r: r["p"])
    top = ordered[int(len(ordered) * 0.9):]
    return base, (statistics.mean([r["label"] for r in top]) if top else 0.0), len(top)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default="reports/soccer_backtest/momentum_events_cache.json")
    ap.add_argument("--window", type=float, default=600.0)
    ap.add_argument("--step", type=float, default=60.0)
    ap.add_argument("--half-life", type=float, default=900.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    matches = load(Path(args.cache))
    hold = [m for m in matches if _is_holdout(m["event_id"])]
    print(f"holdout matches {len(hold)}  window {args.window:.0f}s  "
          f"half-life {args.half_life:.0f}s  sampled to {_MATCH_END:.0f}s")

    all_types = sorted({e["type"] for m in matches for e in m["events"]})
    counts = {t: sum(1 for m in matches for e in m["events"] if e["type"] == t) for t in all_types}

    # --- TIME, across the WHOLE match including the closing minutes ---
    ref = samples_for(hold, set(all_types), half_life=args.half_life,
                      window=args.window, step=args.step)
    base_all = statistics.mean([r["label"] for r in ref]) if ref else 0.0
    print(f"\nholdout samples {len(ref)}   base rate {base_all:.4f}")
    print("\n=== TIME, FULL MATCH (4-minute buckets) ===")
    print(f"  {'clock':>12}{'n':>7}{'hit':>9}{'lift':>7}{'win avail':>11}")
    tb: dict[int, list[dict]] = {}
    for r in ref:
        tb.setdefault(int(r["t"] // 240), []).append(r)
    time_rows = []
    for b in sorted(tb):
        rows = tb[b]
        if len(rows) < 150:
            continue
        hit = statistics.mean([x["label"] for x in rows])
        avail = statistics.mean([x["window_avail"] for x in rows]) / 60.0
        flag = "  <<<" if hit >= base_all * 1.25 else ""
        lo, hi = b * 4, (b + 1) * 4
        print(f"  {lo:>5}-{hi:<6}{len(rows):>7}{hit:>9.4f}{hit/base_all:>7.2f}{avail:>10.1f}m{flag}")
        time_rows.append({"lo": lo, "hi": hi, "n": len(rows), "hit": round(hit, 4),
                          "lift": round(hit / base_all, 3), "window_avail_min": round(avail, 2)})

    # --- EACH EVENT TYPE ALONE ---
    print("\n=== EACH EVENT TYPE ALONE (top-decile hit rate, holdout) ===")
    print(f"  {'type':<34}{'count':>8}{'top-dec':>9}{'lift':>7}")
    solo = []
    for t in all_types:
        if counts[t] < 200:
            continue
        rows = samples_for(hold, {t}, half_life=args.half_life,
                           window=args.window, step=args.step)
        base, hit, n = top_decile_hit(rows)
        if not n:
            continue
        solo.append({"type": t, "count": counts[t], "top_decile_hit": round(hit, 4),
                     "lift": round(hit / base, 3) if base else None})
        flag = "  <<<" if base and hit / base >= 1.20 else ""
        print(f"  {t:<34}{counts[t]:>8}{hit:>9.4f}{(hit/base if base else 0):>7.2f}{flag}")

    # --- COMBINATIONS, ranked by what the solo pass found ---
    print("\n=== COMBINATIONS (top-decile hit rate, holdout) ===")
    best_solo = [s["type"] for s in sorted(solo, key=lambda s: -(s["lift"] or 0))[:4]]
    combos: list[tuple[str, set[str]]] = [
        ("all types", set(all_types)),
        ("shots only", {"shot-on-target", "shot-off-target", "shot-blocked", "shot-hit-woodwork"}),
        ("shots+corners", {"shot-on-target", "shot-off-target", "shot-blocked",
                           "shot-hit-woodwork", "corner-awarded"}),
        ("set pieces", {"corner-awarded", "free-kick", "penalty---scored", "penalty---saved"}),
        ("cards+subs", {"yellow-card", "red-card", "substitution"}),
        ("fouls only", {"foul"}),
        ("top-4 solo", set(best_solo)),
    ]
    combo_rows = []
    for name, ts in combos:
        ts = {t for t in ts if t in counts}
        if not ts:
            continue
        rows = samples_for(hold, ts, half_life=args.half_life,
                           window=args.window, step=args.step)
        base, hit, n = top_decile_hit(rows)
        combo_rows.append({"combo": name, "types": sorted(ts), "top_decile_hit": round(hit, 4),
                           "lift": round(hit / base, 3) if base else None})
        flag = "  <<<" if base and hit / base >= 1.20 else ""
        print(f"  {name:<34}{len(ts):>8}{hit:>9.4f}{(hit/base if base else 0):>7.2f}{flag}")

    # --- BEST COMBO x TIME: does any event feature ADD to the clock? ---
    if combo_rows:
        best = max(combo_rows, key=lambda c: c["lift"] or 0)
        ts = set(best["types"])
        rows = samples_for(hold, ts, half_life=args.half_life,
                           window=args.window, step=args.step)
        print(f"\n=== '{best['combo']}' WITHIN each time bucket ===")
        print("  (time-only hit vs top-decile-of-feature hit INSIDE that bucket)")
        print(f"  {'clock':>12}{'n':>7}{'time only':>11}{'+feature':>10}{'delta':>9}")
        cross = []
        buckets: dict[int, list[dict]] = {}
        for r in rows:
            buckets.setdefault(int(r["t"] // 240), []).append(r)
        for b in sorted(buckets):
            rws = buckets[b]
            if len(rws) < 300:
                continue
            t_only = statistics.mean([x["label"] for x in rws])
            ordered = sorted(rws, key=lambda x: x["p"])
            top = ordered[int(len(ordered) * 0.75):]
            with_f = statistics.mean([x["label"] for x in top]) if top else 0.0
            lo, hi = b * 4, (b + 1) * 4
            d = with_f - t_only
            flag = "  <<<" if d >= 0.05 else ""
            print(f"  {lo:>5}-{hi:<6}{len(rws):>7}{t_only:>11.4f}{with_f:>10.4f}{d:>+9.4f}{flag}")
            cross.append({"lo": lo, "hi": hi, "n": len(rws), "time_only": round(t_only, 4),
                          "with_feature": round(with_f, 4), "delta": round(d, 4)})

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(
            {"holdout_matches": len(hold), "base_rate": round(base_all, 5),
             "time": time_rows, "solo": solo, "combos": combo_rows,
             "cross": cross if combo_rows else []}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
