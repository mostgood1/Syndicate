"""Build the CONDITIONAL PITCH MIX artifact: pitcher x count-bucket x batter hand. `#440`.

**The gap this closes.** The engine draws pitch type from ONE season-long vector
(`PitcherProfile.arsenal`, applied at `simulate.py:1066` and `:2803`),
unconditional on count and on batter handedness. Measured on 1,472,453 pitches
(`scripts/measure_pitch_mix_conditioning.py`): real 3-0 counts are 94.5%
fastball against a 55.2% season mix, and lefty-on-lefty the changeup collapses
from 14.1% to 3.8%. The engine throws the season mix in both.

**Why this is not just a league rule.** Tilting each pitcher's season vector by
the LEAGUE count shift -- the best a single global rule can do -- removes only
14-45% of the per-pitcher deviation. **55-86% is irreducibly per-pitcher.**

THREE DECISIONS, each of which could have been got wrong quietly:

1. **SHRINKAGE IS MANDATORY, NOT OPTIONAL.** ~1,135 pitches per pitcher over
   ~10 cells is ~113 per cell, and the thin tail is far worse. A raw per-pitcher
   conditional mix fits noise. Each cell is a Dirichlet posterior:

       posterior = (n_cell * observed + k * prior) / (n_cell + k)
       prior     = normalise(own season mix x league cell tilt)

   The prior is the *best global rule*, so shrinkage degrades gracefully to
   "league pattern" for a pitcher with no cell data, and approaches his true
   conditional mix as evidence accumulates.

2. **`k` IS FITTED OUT-OF-SAMPLE, NOT CHOSEN.** Held-out multinomial log-loss on
   a DATE-disjoint split, scored against two baselines (season vector alone;
   season x league tilt). If the fitted model does not beat both, the script
   **REFUSES to write** -- an artifact that loses to the thing it replaces is
   worse than no artifact, and it would look like a feature.

3. **BUCKETS ARE CUT BY MEASURED TVD, NOT BY INTUITION.** Counts are clustered
   agglomeratively on the distance between their league mixes. "Ahead" and
   "behind" are things the data says, not things baseball commentary says.

Full arsenals: codes are canonicalised through `sim_engine/data/pitch_codes.py`,
which is where the sweeper (8.20% of pitches, previously `OTHER` or dropped) is
finally a slider.

Usage:
  py -3 scripts/build_mlb_conditional_mix_artifact.py --season 2026
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor" / "mlb_bettingv2"))

REL = "mlb_source/source_artifacts/data/conditional_mix"
RAW = "vendor/mlb_bettingv2/data/raw/statcast/pitches/{season}/*.csv.gz"

ALL_COUNTS = [f"{b}-{s}" for b in range(4) for s in range(3)]
EPS = 0.01          # league floor, applied to every candidate equally
MIN_PITCHER = 100   # season pitches to publish a pitcher at all
K_GRID = [1, 2, 5, 10, 20, 35, 50, 75, 100, 150, 250, 400, 700]


def _root() -> Path:
    o = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(o).expanduser().resolve() if o else (REPO / "data")


def _norm(c) -> dict:
    t = sum(c.values())
    return {k: v / t for k, v in c.items()} if t > 0 else {}


def _tvd(a: dict, b: dict) -> float:
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


def _load(season: int, max_files: int):
    """-> rows of (date, pitcher, count, hand, pitch_type_value)"""
    from sim_engine.data.pitch_codes import canon_pitch_type

    files = sorted(glob.glob(str(REPO / RAW.format(season=season))))[:max_files]
    if not files:
        print(f"REFUSED: no statcast pitch files for {season}")
        return None, None
    rows, dropped = [], Counter()
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                pt = canon_pitch_type(r.get("pitch_type") or "")
                if pt is None:
                    dropped["not_a_pitch"] += 1
                    continue
                try:
                    b, s = int(float(r["balls"])), int(float(r["strikes"]))
                    pid = int(float(r["pitcher"]))
                except Exception:
                    dropped["unparseable"] += 1
                    continue
                stand = (r.get("stand") or "").strip().upper()
                if not (0 <= b <= 3 and 0 <= s <= 2) or stand not in ("L", "R"):
                    dropped["out_of_domain"] += 1
                    continue
                rows.append(((r.get("game_date") or "").strip(), pid,
                             f"{b}-{s}", stand, pt.value))
    print(f"  {len(files)} files, {len(rows):,} usable pitches, "
          f"dropped {dict(dropped)}")
    return rows, files


def _buckets(rows, n_buckets: int) -> dict:
    """Agglomerative clustering of counts on TVD between their league mixes."""
    mix = {c: Counter() for c in ALL_COUNTS}
    for _d, _p, c, _h, pt in rows:
        mix[c][pt] += 1
    live = [[c] for c in ALL_COUNTS if sum(mix[c].values()) >= 500]
    if not live:
        return {}

    def group_mix(g):
        agg = Counter()
        for c in g:
            agg.update(mix[c])
        return _norm(agg)

    while len(live) > n_buckets:
        best, bi, bj = None, 0, 1
        for i in range(len(live)):
            for j in range(i + 1, len(live)):
                d = _tvd(group_mix(live[i]), group_mix(live[j]))
                if best is None or d < best:
                    best, bi, bj = d, i, j
        live[bi] = live[bi] + live[bj]
        live.pop(bj)

    out = {}
    for g in live:
        name = "|".join(sorted(g))
        for c in g:
            out[c] = name
    print(f"\n  {len(live)} buckets, cut by TVD:")
    for g in sorted(live, key=lambda x: -sum(sum(mix[c].values()) for c in x)):
        n = sum(sum(mix[c].values()) for c in g)
        gm = group_mix(g)
        top = sorted(gm.items(), key=lambda kv: -kv[1])[:3]
        label = "|".join(sorted(g))
        print(f"    {label:<30} {n:>8,}  "
              + "  ".join(f"{k} {100*v:4.1f}%" for k, v in top))
    return out


def _tally(rows, buckets):
    season = defaultdict(Counter)                       # pid -> mix
    league_cell = defaultdict(Counter)                  # (bucket,hand) -> mix
    league = Counter()
    cell = defaultdict(lambda: defaultdict(Counter))    # pid -> (b,h) -> mix
    for _d, pid, c, h, pt in rows:
        b = buckets.get(c)
        if b is None:
            continue
        key = (b, h)
        season[pid][pt] += 1
        league[pt] += 1
        league_cell[key][pt] += 1
        cell[pid][key][pt] += 1
    return season, league, league_cell, cell


def _tilts(league, league_cell) -> dict:
    """Multiplicative league tilt per cell per pitch type."""
    ln = _norm(league)
    out = {}
    for key, c in league_cell.items():
        cn = _norm(c)
        out[key] = {pt: (cn.get(pt, 0.0) / ln[pt]) for pt in ln if ln[pt] > 0}
    return out


def _prior(season_mix: dict, tilt: dict) -> dict:
    p = {pt: v * tilt.get(pt, 1.0) for pt, v in season_mix.items()}
    return _norm(p) if sum(p.values()) > 0 else dict(season_mix)


def _blend(dist: dict, floor: dict) -> dict:
    return {k: (1 - EPS) * dist.get(k, 0.0) + EPS * floor.get(k, 0.0)
            for k in set(dist) | set(floor)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--buckets", type=int, default=5)
    ap.add_argument("--max-files", type=int, default=999)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    print(f"reading {args.season} statcast corpus")
    rows, files = _load(args.season, args.max_files)
    if not rows:
        return 1

    buckets = _buckets(rows, args.buckets)
    if not buckets:
        print("REFUSED: no count cell cleared the sample floor")
        return 1

    # date-disjoint split. A random split would leak: the same game appears on
    # both sides and a pitcher's start is highly autocorrelated within a game.
    dates = sorted({d for d, *_ in rows if d})
    if len(dates) < 10:
        print("REFUSED: too few distinct dates to validate out-of-sample")
        return 1
    cut = dates[int(0.8 * len(dates))]
    train = [r for r in rows if r[0] and r[0] < cut]
    test = [r for r in rows if r[0] and r[0] >= cut]
    print(f"\n  split at {cut}: train {len(train):,}  test {len(test):,}")

    s_tr, l_tr, lc_tr, c_tr = _tally(train, buckets)
    tilt_tr = _tilts(l_tr, lc_tr)
    league_n = _norm(l_tr)

    def score(k):
        """Held-out mean negative log-likelihood. Lower is better."""
        cache, tot, n = {}, 0.0, 0
        for _d, pid, c, h, pt in test:
            b = buckets.get(c)
            if b is None:
                continue
            key = (pid, b, h)
            dist = cache.get(key)
            if dist is None:
                smix = _norm(s_tr.get(pid, Counter()))
                if not smix:
                    dist = league_n
                else:
                    pr = _prior(smix, tilt_tr.get((b, h), {}))
                    if k is None:                      # baseline: season only
                        dist = _blend(smix, league_n)
                    elif k == "prior":                 # baseline: + league tilt
                        dist = _blend(pr, league_n)
                    else:
                        obs = c_tr.get(pid, {}).get((b, h), Counter())
                        nc = sum(obs.values())
                        on = _norm(obs)
                        post = {p: (nc * on.get(p, 0.0) + k * pr.get(p, 0.0)) / (nc + k)
                                for p in set(on) | set(pr)}
                        dist = _blend(post, league_n)
                cache[key] = dist
            tot -= math.log(max(dist.get(pt, 0.0), 1e-9))
            n += 1
        return tot / n if n else float("inf")

    print("\n" + "=" * 66)
    print("OUT-OF-SAMPLE VALIDATION (held-out mean neg log-likelihood)")
    print("=" * 66)
    base_season = score(None)
    base_prior = score("prior")
    print(f"  baseline  season vector only      {base_season:.5f}   <- the engine today")
    print(f"  baseline  season x league tilt    {base_prior:.5f}   <- best global rule")
    best_k, best_s = None, float("inf")
    for k in K_GRID:
        s = score(k)
        mark = ""
        if s < best_s:
            best_k, best_s, mark = k, s, "  *"
        print(f"  shrinkage k={k:<4}                  {s:.5f}{mark}")

    print(f"\n  best k = {best_k}   {best_s:.5f}")
    print(f"  vs season vector   {100*(base_season-best_s)/base_season:+.2f}%")
    print(f"  vs best global     {100*(base_prior-best_s)/base_prior:+.2f}%")

    if not (best_s < base_season and best_s < base_prior):
        print("\nREFUSED: the fitted model does not beat BOTH baselines "
              "out-of-sample. Not writing an artifact that loses to what it replaces.")
        return 1

    # refit on everything with the chosen k
    s_all, l_all, lc_all, c_all = _tally(rows, buckets)
    tilt_all = _tilts(l_all, lc_all)
    league_all = _norm(l_all)

    pitchers, cells, thin = {}, 0, 0
    for pid, smix_c in s_all.items():
        if sum(smix_c.values()) < MIN_PITCHER:
            thin += 1
            continue
        smix = _norm(smix_c)
        entry = {}
        for (b, h), obs in c_all.get(pid, {}).items():
            pr = _prior(smix, tilt_all.get((b, h), {}))
            nc = sum(obs.values())
            on = _norm(obs)
            post = {p: (nc * on.get(p, 0.0) + best_k * pr.get(p, 0.0)) / (nc + best_k)
                    for p in set(on) | set(pr)}
            post = {p: v for p, v in post.items() if v >= 0.005}
            t = sum(post.values())
            if not t:
                continue
            entry[f"{b}|{h}"] = {p: round(v / t, 4) for p, v in post.items()}
            cells += 1
        if entry:
            pitchers[str(pid)] = entry

    artifact = {
        "schema_version": 1,
        "season": args.season,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": f"statcast raw pitches, {len(files)} files, {len(rows)} pitches",
        "method": "Dirichlet shrinkage toward (own season mix x league cell tilt)",
        "shrinkage_k": best_k,
        "league_floor_eps": EPS,
        "count_to_bucket": buckets,
        "validation": {
            "split_date": cut,
            "n_test": len(test),
            "nll_season_vector": round(base_season, 5),
            "nll_season_x_league_tilt": round(base_prior, 5),
            "nll_shrunk": round(best_s, 5),
            "improvement_vs_season_pct": round(100 * (base_season - best_s) / base_season, 3),
            "improvement_vs_global_pct": round(100 * (base_prior - best_s) / base_prior, 3),
        },
        "league": {f"{b}|{h}": {p: round(v, 4) for p, v in _norm(c).items()}
                   for (b, h), c in lc_all.items()},
        "league_overall": {p: round(v, 4) for p, v in league_all.items()},
        "counts": {"pitchers": len(pitchers), "cells": cells, "thin_skipped": thin},
        "pitchers": pitchers,
    }
    out = args.out or (_root() / REL / f"conditional_mix_{args.season}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, separators=(",", ":")), encoding="utf-8")

    print(f"\n  {len(pitchers)} pitchers, {cells} cells, {thin} thin-skipped")
    if pitchers:
        pid = next(iter(pitchers))
        k0 = next(iter(pitchers[pid]))
        print(f"  sample {pid} {k0}: {json.dumps(pitchers[pid][k0])}")
    print(f"\nwrote {out}  ({out.stat().st_size/1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
