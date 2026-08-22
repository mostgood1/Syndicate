"""Two-stage goal-timing analysis on the 2-year, 10-league sample.

DESIGNED AROUND THE FOUR WAYS THIS ANALYSIS ALREADY FAILED TODAY. Each guard
below exists because its absence produced a wrong answer that got reported:

1. SELECT ON FIT, SCORE ON HOLDOUT -- ONCE. Every dead result (momentum 40.2%,
   xG +0.1028, xG-over-count) came from spotting a good cell and then reporting
   that same cell. Here the fit half RANKS candidates and the holdout half
   scores only the survivors. A cell scored on holdout is never re-selected.

2. MULTIPLE TESTING IS COUNTED, NOT IGNORED. ~10 leagues x ~19 bands x 4
   features is ~700 cells; at p=0.05 about 35 clear by chance alone. The report
   prints how many were SELECTED and how many SURVIVED, so "3 of 40 survived"
   cannot be read as three discoveries.

3. CONTROLS MATCHED BY SELECTION RATE, NEVER BY THRESHOLD VALUE. xG-pressure
   spans 0.09..1.82 and count-pressure spans 1.55..13.76; one shared threshold
   fired on 24% and 100% of the same band, making the control delta +0.0000 by
   arithmetic. Thresholds here are always percentiles.

4. INTERVALS ON EVERY RATE. A point estimate at n~90 has SE ~0.05, which is the
   entire size of the effects being chased. Wilson bounds are printed and the
   economic verdict keys off the LOWER bound, not the point.

The bar is economic, not statistical: 3-1 pays at 25.0%, 2-1 at 33.3%.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_MATCH_END = 5700.0
_BAND = 240.0            # 4-minute bands
_BE_31 = 0.25
_BE_21 = 1.0 / 3.0


def _hold(mid) -> bool:
    return (sum(ord(c) for c in str(mid)) % 10) >= 7


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - m), min(1.0, c + m)


# Every feature is STRICTLY CAUSAL: it may read only what happened at or before
# t. That is not a style preference -- a feature that peeks past t scores
# beautifully and is worthless live. Full-match `content.stats` is excluded
# from the cache's feature set for exactly this reason.
_SHOT_FEATURES = {"xg", "count", "ontarget", "inbox", "bigchance"}
_VENDOR_FEATURES = {"vmom_abs", "vmom_signed", "vmom_slope"}
_EVENT_FEATURES = {"red_adv", "subs"}


def _vendor_at(series: list[dict], t: float) -> float:
    """FotMob momentum at or before t. Their series is per MINUTE, so an
    interpolation would invent precision the source does not have."""
    val = 0.0
    for point in series:
        if point["t"] > t:
            break
        val = point["value"]
    return val


def pressure(match: dict, t: float, half_life: float, feature: str) -> float:
    if feature in _SHOT_FEATURES:
        tot = 0.0
        for s in match["shots"]:
            if s["t"] > t:
                continue
            w = math.pow(0.5, (t - s["t"]) / half_life)
            if feature == "xg":
                tot += w * s.get("xg", 0.0)
            elif feature == "count":
                tot += w
            elif feature == "ontarget":
                tot += w if s.get("on_target") else 0.0
            elif feature == "inbox":
                tot += w * (s.get("xg", 0.0) if s.get("in_box") else 0.0)
            elif feature == "bigchance":
                tot += w if s.get("xg", 0.0) >= 0.20 else 0.0
        return tot

    if feature in _VENDOR_FEATURES:
        series = match.get("vendor_momentum") or []
        if not series:
            return 0.0
        now = _vendor_at(series, t)
        if feature == "vmom_abs":
            return abs(now)
        if feature == "vmom_signed":
            return now
        # slope over the trailing 5 minutes: momentum BUILDING, not momentum high
        return now - _vendor_at(series, max(0.0, t - 300.0))

    if feature in _EVENT_FEATURES:
        ev = match.get("events") or []
        if feature == "subs":
            return float(sum(1 for e in ev if e["t"] <= t and e["type"] == "Substitution"))
        # red_adv: absolute numerical advantage either way. A team a man up
        # attacks more; a team a man down concedes more. For "does a goal
        # happen" the SIZE of the imbalance is the signal, not its direction.
        red_h = sum(1 for e in ev if e["t"] <= t and e["type"] == "Card"
                    and (e.get("card") or "").lower() == "red" and e["home"])
        red_a = sum(1 for e in ev if e["t"] <= t and e["type"] == "Card"
                    and (e.get("card") or "").lower() == "red" and not e["home"])
        return float(abs(red_h - red_a))

    raise ValueError("unknown feature %r" % feature)


def samples(matches: list[dict], *, half_life: float, window: float, step: float,
            feature: str) -> list[dict]:
    out = []
    for m in matches:
        shots, goals = m["shots"], m["goals"]
        last = max([s["t"] for s in shots] + [g["t"] for g in goals] + [0.0])
        end = min(_MATCH_END, last)
        t = 60.0
        while t <= end:
            if min(window, end - t) >= 120.0:
                out.append({
                    "t": t,
                    "league": m["league"],
                    "p": pressure(m, t, half_life, feature),
                    "label": 1 if any(t < g["t"] <= t + window for g in goals) else 0,
                })
            t += step
    return out


def cell_score(rows: list[dict], pct: float):
    """(clock-only, fired hit, n fired, CI) using a PERCENTILE threshold.

    TIES ARE INCLUDED, not sliced through. `red_adv` and `subs` are integer
    features whose value is 0 for most samples, so taking the top 25% BY SORT
    POSITION would split the tied block arbitrarily and report a difference
    between rows that are identical to the feature. Taking every row at or
    above the threshold VALUE can fire on more than `1-pct` of the sample --
    that is the honest consequence of a coarse feature, and `n` shows it.
    """
    if len(rows) < 40:
        return 0.0, 0.0, 0, (0.0, 0.0)
    clock = statistics.mean([r["label"] for r in rows])
    ordered = sorted(r["p"] for r in rows)
    thr = ordered[min(len(ordered) - 1, int(len(ordered) * pct))]
    fired = [r for r in rows if r["p"] >= thr]
    # A feature so coarse that "top quartile" swallows the whole cell cannot
    # discriminate at all; report it as no signal rather than as a match to the
    # clock, which is what a 100%-fire cell trivially equals.
    if not fired or len(fired) >= len(rows) * 0.95:
        return clock, 0.0, 0, (0.0, 0.0)
    k = sum(r["label"] for r in fired)
    return clock, k / len(fired), len(fired), wilson(k, len(fired))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default="reports/soccer_backtest/fotmob_2y.json")
    ap.add_argument("--window", type=float, default=600.0)
    ap.add_argument("--step", type=float, default=60.0)
    ap.add_argument("--half-life", type=float, default=900.0)
    ap.add_argument("--pct", type=float, default=0.75)
    ap.add_argument("--features",
                    default="xg,count,ontarget,inbox,bigchance,vmom_abs,vmom_slope,red_adv,subs")
    ap.add_argument("--out", default="reports/soccer_backtest/goal_timing_2y.json")
    args = ap.parse_args()

    data = json.loads(Path(args.cache).read_text(encoding="utf-8"))
    matches = data["matches"]
    fit = [m for m in matches if not _hold(m["match_id"])]
    hold = [m for m in matches if _hold(m["match_id"])]
    feats = [f.strip() for f in args.features.split(",") if f.strip()]

    by_league = {}
    for m in matches:
        by_league[m["league"]] = by_league.get(m["league"], 0) + 1
    print("matches %d   fit %d   holdout %d" % (len(matches), len(fit), len(hold)))
    for k, v in sorted(by_league.items(), key=lambda x: -x[1]):
        print("  %-22s%6d" % (k, v))

    leagues = sorted(by_league)

    # ---------- STAGE 0: the clock alone, on HOLDOUT ----------
    ref = samples(hold, half_life=args.half_life, window=args.window,
                  step=args.step, feature=feats[0])
    base = statistics.mean([r["label"] for r in ref]) if ref else 0.0
    print("\nholdout samples %d   base rate %.4f" % (len(ref), base))
    print("\n=== THE CLOCK ALONE (holdout, pooled) ===")
    print("  %11s%8s%9s%7s%18s" % ("band", "n", "hit", "lift", "95% CI"))
    bands = {}
    for r in ref:
        bands.setdefault(int(r["t"] // _BAND), []).append(r)
    clock_rows = []
    for b in sorted(bands):
        rows = bands[b]
        if len(rows) < 200:
            continue
        k = sum(r["label"] for r in rows)
        hit = k / len(rows)
        lo, hi = wilson(k, len(rows))
        star = "  <<<" if lo > _BE_31 else ""
        print("  %5d-%-5d%8d%9.4f%7.2f   [%.3f,%.3f]%s"
              % (b * 4, (b + 1) * 4, len(rows), hit, hit / base if base else 0, lo, hi, star))
        clock_rows.append({"lo_min": b * 4, "hi_min": (b + 1) * 4, "n": len(rows),
                           "hit": round(hit, 4), "lift": round(hit / base, 3) if base else None,
                           "ci": [round(lo, 4), round(hi, 4)]})

    # ---------- STAGE 1: SELECT on FIT ----------
    print("\n=== STAGE 1: selecting on the FIT half (%d matches) ===" % len(fit))
    print("  a cell is a (league, band, feature). selected if fired-hit beats")
    print("  its own clock by >= 0.02 AND the point estimate clears 3-1 (0.25).")
    cand = []
    tested = 0
    for feature in feats:
        fit_s = samples(fit, half_life=args.half_life, window=args.window,
                        step=args.step, feature=feature)
        for lg in leagues + ["_pooled"]:
            rows_lg = fit_s if lg == "_pooled" else [r for r in fit_s if r["league"] == lg]
            fb = {}
            for r in rows_lg:
                fb.setdefault(int(r["t"] // _BAND), []).append(r)
            for b in sorted(fb):
                rows = fb[b]
                if len(rows) < 200:
                    continue
                tested += 1
                clock, hit, n, _ = cell_score(rows, args.pct)
                if n >= 40 and (hit - clock) >= 0.02 and hit >= _BE_31:
                    cand.append({"league": lg, "band": b, "feature": feature,
                                 "fit_clock": round(clock, 4), "fit_hit": round(hit, 4),
                                 "fit_delta": round(hit - clock, 4), "fit_n": n})
    cand.sort(key=lambda c: -c["fit_delta"])
    print("  cells tested %d   selected %d" % (tested, len(cand)))
    print("  NOTE: at p=0.05, ~%d of %d clear by chance alone." % (int(tested * 0.05), tested))

    # ---------- STAGE 2: SCORE survivors on HOLDOUT, once ----------
    print("\n=== STAGE 2: scoring those on the HOLDOUT half ===")
    print("  %-20s%9s%10s%8s%8s%7s%8s   %s"
          % ("league", "band", "feat", "fit d", "HOLD", "n", "delta", "95% CI"))
    cache = {}
    survivors = []
    for c in cand[:60]:
        if c["feature"] not in cache:
            cache[c["feature"]] = samples(hold, half_life=args.half_life,
                                          window=args.window, step=args.step,
                                          feature=c["feature"])
        hs = cache[c["feature"]]
        rows = [r for r in hs if int(r["t"] // _BAND) == c["band"]
                and (c["league"] == "_pooled" or r["league"] == c["league"])]
        clock, hit, n, ci = cell_score(rows, args.pct)
        if n < 40:
            continue
        d = hit - clock
        ok = ci[0] > _BE_31 and d >= 0.02
        c.update({"hold_clock": round(clock, 4), "hold_hit": round(hit, 4),
                  "hold_n": n, "hold_delta": round(d, 4),
                  "ci": [round(ci[0], 4), round(ci[1], 4)], "survived": ok})
        if ok:
            survivors.append(c)
        mark = "  SURVIVES" if ok else ""
        print("  %-20s%5d-%-3d%10s%+8.3f%8.4f%7d%+8.3f   [%.3f,%.3f]%s"
              % (c["league"], c["band"] * 4, (c["band"] + 1) * 4, c["feature"],
                 c["fit_delta"], hit, n, d, ci[0], ci[1], mark))

    print("\n=== RESULT ===")
    print("  %d selected on fit -> %d survive on holdout" % (len(cand), len(survivors)))
    print("  (chance alone would pass ~%d of %d)" % (max(1, int(len(cand) * 0.05)), len(cand)))
    for s in survivors:
        print("    %s %d-%d' %s: %.4f CI[%.3f,%.3f] n=%d  2-1:%s"
              % (s["league"], s["band"] * 4, (s["band"] + 1) * 4, s["feature"],
                 s["hold_hit"], s["ci"][0], s["ci"][1], s["hold_n"],
                 "clears" if s["ci"][0] > _BE_21 else "no"))
    if not survivors:
        print("    none. the clock profile above is then the whole finding.")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"n_matches": len(matches), "by_league": by_league, "base_rate": base,
         "clock": clock_rows, "tested": tested, "selected": len(cand),
         "candidates": cand[:60], "survivors": survivors}, indent=2), encoding="utf-8")
    print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
