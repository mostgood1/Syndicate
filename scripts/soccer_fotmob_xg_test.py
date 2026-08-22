"""Score FotMob xG against the bar the CLOCK already set.

THE BAR, from 370 ESPN matches pooled (holdout + fresh):
    80-84'  hit 0.3320  lift 1.35   <- clock alone
    best event feature increment over the clock: +0.02

xG either clears that or it does not. Same discipline as every prior pass:
strictly causal, goals excluded from the feature, held out by match-id hash,
and the do-nothing baseline reported beside every number -- the omission that
made an earlier prereg print WEAK PASS for a rule that lost to the base rate.
"""
from __future__ import annotations

import argparse, json, math, statistics, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.ingestion.fotmob_shots import matches_for_date, shots_for_match

_END = 5700.0


def harvest(dates: list[str], limit: int, out: Path) -> None:
    got: list[dict] = []
    for d in dates:
        try:
            fixtures = [m for m in matches_for_date(d) if m.get("finished")]
        except Exception as exc:
            print(f"  date {d} failed: {type(exc).__name__}", flush=True)
            continue
        tried = kept = 0
        for f in fixtures:
            if len(got) >= limit:
                break
            tried += 1
            row = shots_for_match(f["match_id"])
            if row and row["shots"]:
                # league AND date travel with the match. Without them a cache
                # cannot be split by competition or checked for overlap with
                # another sample -- both of which turned out to matter more
                # than any modelling choice in this analysis.
                row["league"] = f["league"]
                row["date"] = d
                got.append(row)
                kept += 1
        # Report per DATE, and report the MISS rate. The old print fired on
        # `len(got) % 25 == 0`, which re-printed the same total for every
        # failed match once the counter parked on a multiple of 25 -- a stalled
        # harvest and a fast one produced identical-looking output.
        print(f"  {d}: {kept}/{tried} had shotmaps   total {len(got)}/{limit}", flush=True)
        if len(got) >= limit:
            break
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"matches": got}), encoding="utf-8")
    print(f"harvested {len(got)} matches -> {out}", flush=True)


def _hold(mid) -> bool:
    return (sum(ord(c) for c in str(mid)) % 10) >= 7


def samples(matches: list[dict], *, half_life: float, window: float, step: float,
            feature: str) -> list[dict]:
    out = []
    for m in matches:
        shots, goals = m["shots"], m["goals"]
        last = max([s["t"] for s in shots] + [g["t"] for g in goals] + [0.0])
        end = min(_END, last)
        t = 60.0
        while t <= end:
            avail = max(0.0, min(window, end - t))
            if avail >= 120.0:
                acc = 0.0
                for s in shots:
                    if s["t"] > t:
                        continue
                    decay = math.pow(0.5, (t - s["t"]) / max(1.0, half_life))
                    if feature == "xg":
                        acc += s["xg"] * decay
                    elif feature == "count":
                        acc += decay
                    elif feature == "xg_inbox":
                        acc += (s["xg"] * decay) if s["in_box"] else 0.0
                    elif feature == "bigchance":
                        acc += decay if s["xg"] >= 0.20 else 0.0
                out.append({"t": t, "p": acc,
                            "label": 1 if any(t < g["t"] <= t + window for g in goals) else 0})
            t += step
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--harvest", action="store_true")
    ap.add_argument("--dates", default="")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--cache", default="reports/soccer_backtest/fotmob_xg_cache.json")
    ap.add_argument("--window", type=float, default=600.0)
    ap.add_argument("--step", type=float, default=60.0)
    ap.add_argument("--half-life", type=float, default=900.0)
    args = ap.parse_args()

    cache = Path(args.cache)
    if args.harvest:
        harvest([d.strip() for d in args.dates.split(",") if d.strip()], args.limit, cache)
    if not cache.exists():
        print("no cache"); return 2
    matches = json.loads(cache.read_text(encoding="utf-8"))["matches"]
    hold = [m for m in matches if _hold(m["match_id"])]
    print(f"matches {len(matches)}  holdout {len(hold)}")

    ref = samples(hold, half_life=args.half_life, window=args.window, step=args.step, feature="xg")
    base = statistics.mean([r["label"] for r in ref]) if ref else 0.0
    print(f"holdout samples {len(ref)}  base rate {base:.4f}")

    # THE CLOCK, on FotMob's own data -- the bar has to be re-established here,
    # not carried over from ESPN. A different sample has a different base rate.
    print("\n=== THE CLOCK on this sample ===")
    tb = {}
    for r in ref:
        tb.setdefault(int(r["t"] // 240), []).append(r)
    clock_best = None
    for b in sorted(tb):
        rows = tb[b]
        if len(rows) < 150:
            continue
        hit = statistics.mean([x["label"] for x in rows])
        lo, hi = b * 4, (b + 1) * 4
        mark = ""
        if lo == 80:
            mark = "  <== the bar"
            clock_best = (hit, len(rows))
        print(f"  {lo:>3}-{hi:<4} n={len(rows):<6} hit {hit:.4f}  lift {hit/base:.2f}{mark}")

    print("\n=== xG FEATURES, top decile (holdout) ===")
    print(f"  {'feature':<14}{'top-dec':>9}{'lift':>7}")
    results = {}
    for feat in ("xg", "count", "xg_inbox", "bigchance"):
        s = samples(hold, half_life=args.half_life, window=args.window, step=args.step, feature=feat)
        o = sorted(s, key=lambda r: r["p"])
        top = o[int(len(o) * 0.9):]
        hit = statistics.mean([x["label"] for x in top]) if top else 0.0
        results[feat] = hit
        print(f"  {feat:<14}{hit:>9.4f}{hit/base:>7.2f}")

    print("\n=== DOES xG ADD TO THE CLOCK AT 80-84'? ===")
    for feat in ("xg", "count", "bigchance"):
        s = samples(hold, half_life=args.half_life, window=args.window, step=args.step, feature=feat)
        b80 = [r for r in s if 4800 <= r["t"] < 5040]
        if len(b80) < 100:
            continue
        t_only = statistics.mean([x["label"] for x in b80])
        o = sorted(b80, key=lambda r: r["p"])
        top = o[int(len(o) * 0.75):]
        with_f = statistics.mean([x["label"] for x in top]) if top else 0.0
        d = with_f - t_only
        verdict = "CLEARS +0.02" if d >= 0.02 else "below +0.02"
        print(f"  {feat:<14} clock {t_only:.4f}  +feature {with_f:.4f}  delta {d:+.4f}  {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
