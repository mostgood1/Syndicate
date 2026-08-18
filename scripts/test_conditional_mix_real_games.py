"""Test the conditional mix against REAL GAMES it never saw. `#440`.

**Why this test and not the market harness.** The market comparison
(`measure_all_inputs_effect.py`) has a measured noise floor of 0.00326 Brier
against effects of ~0.00138 -- it cannot resolve this feature, and a single-seed
run of it produced a clean-looking 20.4% gap closure that reversed at the second
seed. That harness measures a downstream binary through a Monte Carlo; this one
measures **the quantity that actually changed**, against reality, with no RNG in
the loop at all. There is no noise floor to clear because nothing is sampled.

**THE QUESTION:** for a real pitcher in a real game, facing a real batter in a
real count -- what did he actually throw, and which model predicts it better?

    A. the season vector        <- what the engine did before this lane
    B. season x league tilt     <- the best a single global count rule can do
    C. the conditional mix      <- per-pitcher, per-count-bucket, per-hand

**OUT OF SAMPLE BY CONSTRUCTION.** The artifact under test is built from files
1..31 (through 2026-06-30) and every game scored here starts on or after
2026-07-01. Scoring the shipped artifact instead would be in-sample, because the
builder refits on the full season -- pass `--artifact` to see that number, but it
is not evidence.

Two metrics, both proper:
  * **log-loss per pitch** -- the probability the model assigned to the pitch he
    actually threw. This is the same rule the builder fits on, so it is the one
    that can be compared to its +6.55% validation figure.
  * **TVD per pitcher-game** -- distance between the model's mix and the mix he
    actually threw that day. Reported as a distribution, because a mean TVD
    hides whether a model is broadly-slightly-better or occasionally-much-worse.

Usage:
  py -3 scripts/test_conditional_mix_real_games.py \
      --artifact reports/phase7/conditional_mix_TRAIN_ONLY.json --after 2026-07-01
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor" / "mlb_bettingv2"))

RAW = "vendor/mlb_bettingv2/data/raw/statcast/pitches/{season}/*.csv.gz"
EPS = 0.01


def _norm(c) -> dict:
    t = sum(c.values())
    return {k: v / t for k, v in c.items()} if t > 0 else {}


def _tvd(a: dict, b: dict) -> float:
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


def _blend(d: dict, floor: dict) -> dict:
    return {k: (1 - EPS) * d.get(k, 0.0) + EPS * floor.get(k, 0.0)
            for k in set(d) | set(floor)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--after", required=True, help="score games on/after this date")
    ap.add_argument("--show-game", action="store_true",
                    help="print one real game cell by cell")
    ap.add_argument("--min-pitches", type=int, default=40,
                    help="per pitcher-game floor for the TVD table")
    args = ap.parse_args()

    from sim_engine.data.pitch_codes import canon_pitch_type

    art = json.loads(args.artifact.read_text(encoding="utf-8"))
    buckets = art.get("count_to_bucket") or {}
    cond = art.get("pitchers") or {}
    league_overall = art.get("league_overall") or {}
    league_cell = art.get("league") or {}
    if not (buckets and cond):
        print("REFUSED: artifact carries no buckets or no pitchers")
        return 1
    print(f"artifact: k={art.get('shrinkage_k')}, {len(cond)} pitchers, "
          f"built from {art.get('source', '?')[:60]}")
    print(f"scoring real games on/after {args.after}\n")

    # season vectors are rebuilt from the SAME train window the artifact used,
    # so A and C see identical evidence and differ only in conditioning
    train_season = defaultdict(Counter)
    held = []            # (game_pk, date, pitcher, bucket, hand, pitch)
    games = set()
    for path in sorted(glob.glob(str(REPO / RAW.format(season=args.season)))):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                pt = canon_pitch_type(r.get("pitch_type") or "")
                if pt is None:
                    continue
                try:
                    b, s = int(float(r["balls"])), int(float(r["strikes"]))
                    pid = int(float(r["pitcher"]))
                    gpk = int(float(r["game_pk"]))
                except Exception:
                    continue
                stand = (r.get("stand") or "").strip().upper()
                date = (r.get("game_date") or "").strip()
                if not (0 <= b <= 3 and 0 <= s <= 2) or stand not in ("L", "R") or not date:
                    continue
                if date >= args.after:
                    bucket = buckets.get(f"{b}-{s}")
                    if bucket:
                        held.append((gpk, date, pid, bucket, stand, pt.value))
                        games.add(gpk)
                else:
                    train_season[pid][pt.value] += 1

    if not held:
        print("REFUSED: no held-out pitches. Check --after against the corpus.")
        return 1
    print(f"  {len(held):,} held-out pitches across {len(games)} real games, "
          f"{len({h[2] for h in held})} pitchers\n")

    def model_dists(pid, bucket, hand):
        """(season, season x league tilt, conditional) for this cell."""
        smix = _norm(train_season.get(pid, Counter()))
        if not smix:
            smix = dict(league_overall)
        cell = f"{bucket}|{hand}"
        lc = league_cell.get(cell) or league_overall
        tilt = {p: (lc.get(p, 0.0) / league_overall[p])
                for p in league_overall if league_overall[p] > 0}
        pr = _norm({p: v * tilt.get(p, 1.0) for p, v in smix.items()}) or smix
        cm = (cond.get(str(pid)) or {}).get(cell)
        return (_blend(smix, league_overall),
                _blend(pr, league_overall),
                _blend(cm, league_overall) if cm else _blend(smix, league_overall))

    # ---- log-loss over every held-out pitch
    tot = [0.0, 0.0, 0.0]
    n = 0
    covered = 0
    cache = {}
    per_game = defaultdict(lambda: [Counter(), None])   # (pid,gpk) -> [real, cellkeys]
    cells_seen = defaultdict(Counter)
    for gpk, _date, pid, bucket, hand, pt in held:
        key = (pid, bucket, hand)
        d = cache.get(key)
        if d is None:
            d = model_dists(pid, bucket, hand)
            cache[key] = d
        for i in range(3):
            tot[i] -= math.log(max(d[i].get(pt, 0.0), 1e-9))
        n += 1
        if (cond.get(str(pid)) or {}).get(f"{bucket}|{hand}"):
            covered += 1
        per_game[(pid, gpk)][0][pt] += 1
        cells_seen[(pid, gpk)][(bucket, hand)] += 1

    labels = ["A season vector      (the engine before this lane)",
              "B season x league    (best single global rule)",
              "C conditional mix    (per-pitcher, per-count, per-hand)"]
    print("=" * 74)
    print(f"LOG-LOSS PER HELD-OUT PITCH   n={n:,}   lower is better")
    print("=" * 74)
    for i, lab in enumerate(labels):
        v = tot[i] / n
        extra = ""
        if i:
            extra = f"   {100*(tot[0]/n - v)/(tot[0]/n):+.2f}% vs A"
        print(f"  {lab:<52}{v:.5f}{extra}")
    print(f"\n  C vs B (the part a global rule cannot reach): "
          f"{100*(tot[1]-tot[2])/tot[1]:+.2f}%")
    print(f"  cells with real conditional coverage: {100*covered/n:.1f}% of pitches")

    # ---- per pitcher-game TVD
    print("\n" + "=" * 74)
    print("PER PITCHER-GAME TVD vs what he ACTUALLY threw that day")
    print("=" * 74)
    tv = [[], [], []]
    for (pid, gpk), (real, _) in per_game.items():
        if sum(real.values()) < args.min_pitches:
            continue
        rn = _norm(real)
        agg = [Counter(), Counter(), Counter()]
        for (bucket, hand), cnt in cells_seen[(pid, gpk)].items():
            d = cache[(pid, bucket, hand)]
            for i in range(3):
                for p, v in d[i].items():
                    agg[i][p] += v * cnt
        for i in range(3):
            tv[i].append(_tvd(_norm(agg[i]), rn))
    if not tv[0]:
        print("  no pitcher-game cleared the floor")
        return 1
    print(f"  {len(tv[0])} pitcher-games with >= {args.min_pitches} pitches\n")
    print(f"  {'model':<54}{'median':>9}{'mean':>9}{'p90':>9}")
    for i, lab in enumerate(labels):
        s = sorted(tv[i])
        p90 = s[min(len(s) - 1, int(0.9 * len(s)))]
        print(f"  {lab:<54}{statistics.median(s):>9.4f}{statistics.mean(s):>9.4f}{p90:>9.4f}")

    print("\n** This aggregate TVD is WEAK BY CONSTRUCTION and is kept only to")
    print("  say so: summing a conditional model over the counts he actually faced")
    print("  reconstructs his MARGINAL mix, which is the thing all three models")
    print("  already agree on. It cannot see conditioning. The within-count table")
    print("  below is the one that answers the question.")

    print("\n" + "=" * 74)
    print("WITHIN-COUNT TVD -- per pitcher-game-cell, >= 8 real pitches in the cell")
    print("=" * 74)
    cv = [[], [], []]
    real_cell = defaultdict(Counter)
    for gpk, _d, pid, bucket, hand, pt in held:
        real_cell[(pid, gpk, bucket, hand)][pt] += 1
    for (pid, gpk, bucket, hand), real in real_cell.items():
        if sum(real.values()) < 8:
            continue
        rn = _norm(real)
        d = cache.get((pid, bucket, hand))
        if d is None:
            continue
        for i in range(3):
            cv[i].append(_tvd(d[i], rn))
    if cv[0]:
        print(f"  {len(cv[0]):,} pitcher-game-count cells\n")
        print(f"  {'model':<54}{'median':>9}{'mean':>9}{'p90':>9}")
        for i, lab in enumerate(labels):
            srt = sorted(cv[i])
            p90 = srt[min(len(srt) - 1, int(0.9 * len(srt)))]
            print(f"  {lab:<54}{statistics.median(srt):>9.4f}"
                  f"{statistics.mean(srt):>9.4f}{p90:>9.4f}")
        # Cells within a pitcher are NOT independent -- one pitcher contributes
        # many. A cell-level sign test overstates its own significance. Collapse
        # to one verdict per PITCHER before claiming anything.
        by_pitcher = defaultdict(lambda: [[], []])
        for (pid, gpk, bucket, hand), real in real_cell.items():
            if sum(real.values()) < 8:
                continue
            d = cache.get((pid, bucket, hand))
            if d is None:
                continue
            rn = _norm(real)
            by_pitcher[pid][0].append(_tvd(d[0], rn))
            by_pitcher[pid][1].append(_tvd(d[2], rn))
        p_wins = sum(1 for a, c in by_pitcher.values()
                     if statistics.mean(c) < statistics.mean(a))
        print("")
        print(f"  CLUSTERED BY PITCHER (one verdict each, {len(by_pitcher)} pitchers):")
        print(f"    C beats A for {p_wins}/{len(by_pitcher)} pitchers "
              f"({100*p_wins/max(1,len(by_pitcher)):.1f}%)")

        w_a = sum(1 for a, c in zip(cv[0], cv[2]) if c < a)
        w_b = sum(1 for b, c in zip(cv[1], cv[2]) if c < b)
        print(f"\nC closer than A in {w_a}/{len(cv[0])} cells ({100*w_a/len(cv[0]):.1f}%)")
        print(f"  C closer than B in {w_b}/{len(cv[0])} cells ({100*w_b/len(cv[0]):.1f}%)")

    if args.show_game:
        print("\n" + "=" * 74)
        print("ONE REAL GAME, ONE STARTER -- what he threw vs what each model said")
        print("=" * 74)
        best = max(((k, sum(v.values())) for k, v in real_cell.items()),
                   key=lambda kv: kv[1])
        pid0, gpk0 = best[0][0], best[0][1]
        tot0 = sum(sum(v.values()) for k, v in real_cell.items()
                   if k[0] == pid0 and k[1] == gpk0)
        print(f"  game_pk {gpk0}   pitcher {pid0}   {tot0} pitches\n")
        for (pid, gpk, bucket, hand), real in sorted(
                real_cell.items(), key=lambda kv: -sum(kv[1].values())):
            if pid != pid0 or gpk != gpk0 or sum(real.values()) < 6:
                continue
            rn = _norm(real)
            d = cache.get((pid, bucket, hand))
            if d is None:
                continue
            top = sorted(rn.items(), key=lambda kv: -kv[1])[:3]
            shown = [k for k, _ in top]
            fmt = lambda dd: "  ".join(f"{k} {100*dd.get(k,0.0):4.1f}%" for k in shown)
            print(f"  count {bucket:<18} vs {hand}HB   n={sum(real.values()):>3}")
            print(f"      REAL            {fmt(rn)}")
            print(f"      A season        {fmt(d[0])}    TVD {_tvd(d[0], rn):.3f}")
            print(f"      C conditional   {fmt(d[2])}    TVD {_tvd(d[2], rn):.3f}")

    wins = sum(1 for a, c in zip(tv[0], tv[2]) if c < a)
    wins_b = sum(1 for b, c in zip(tv[1], tv[2]) if c < b)
    print(f"\n  C closer than A in {wins}/{len(tv[0])} pitcher-games "
          f"({100*wins/len(tv[0]):.1f}%)")
    print(f"  C closer than B in {wins_b}/{len(tv[0])} pitcher-games "
          f"({100*wins_b/len(tv[0]):.1f}%)")
    print("\n  No RNG anywhere in this test -- nothing is sampled, so there is no")
    print("  noise floor to clear. Re-running gives identical numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
