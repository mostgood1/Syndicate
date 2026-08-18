"""Measure how much pitch MIX depends on count and on batter handedness. `#440`.

The engine draws pitch type from ONE season-long vector (`PitcherProfile.arsenal`,
simulate.py:1066 and :2803) -- unconditional on count and on handedness. This
asks how much information that discards, from the same corpus that produced the
count matrix.

Reports, league-wide and per-pitcher:
  * mix by count            (is 0-2 different from 3-0?)
  * mix by hand matchup     (does a RHP throw a LHB something different?)
  * TOTAL VARIATION DISTANCE from the unconditional mix -- the honest scalar for
    "how wrong is one vector", because it is the max probability error over any
    event, not an average that hides a big shift in a small cell.

Per-pitcher dispersion is the number that matters: a LEAGUE pattern is a constant
every model already prices, whereas per-pitcher spread is matchup information.
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = "vendor/mlb_bettingv2/data/raw/statcast/pitches/*/*.csv.gz"

# Families keep the tables legible. The per-pitch-type detail is still measured;
# families are only how it is PRINTED.
FAM = {
    "FF": "FB", "SI": "FB", "FC": "FB", "FA": "FB",
    "SL": "BR", "CU": "BR", "KC": "BR", "ST": "BR", "SV": "BR", "SC": "BR",
    "CH": "OS", "FS": "OS", "FO": "OS", "KN": "OS",
}
COUNTS = ["0-0", "0-2", "1-2", "2-2", "3-2", "3-0", "3-1", "2-0", "1-0", "0-1", "1-1", "2-1"]


def _tvd(a: Counter, b: Counter) -> float:
    """Total variation distance between two mixes. 0 = identical, 1 = disjoint."""
    na, nb = sum(a.values()), sum(b.values())
    if na <= 0 or nb <= 0:
        return float("nan")
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a[k] / na - b[k] / nb) for k in keys)


def _pct(c: Counter) -> dict:
    n = sum(c.values())
    return {k: 100.0 * v / n for k, v in c.items()} if n else {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-files", type=int, default=999)
    ap.add_argument("--min-pitches", type=int, default=300,
                    help="per-pitcher floor for the dispersion table")
    args = ap.parse_args()

    files = sorted(glob.glob(str(REPO / RAW)))[:args.max_files]
    if not files:
        print("REFUSED: no statcast pitch files found")
        return 1

    overall = Counter()
    by_count = defaultdict(Counter)
    by_hand = defaultdict(Counter)                     # (p_throws, stand)
    p_overall = defaultdict(Counter)                   # pitcher -> mix
    p_by_count = defaultdict(lambda: defaultdict(Counter))
    p_by_hand = defaultdict(lambda: defaultdict(Counter))
    n = 0

    for path in files:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                pt = (row.get("pitch_type") or "").strip().upper()
                fam = FAM.get(pt)
                if not fam:
                    continue
                try:
                    b, s = int(float(row["balls"])), int(float(row["strikes"]))
                    pid = int(float(row["pitcher"]))
                except Exception:
                    continue
                if not (0 <= b <= 3 and 0 <= s <= 2):
                    continue
                cnt = f"{b}-{s}"
                hand = ((row.get("p_throws") or "?").strip(),
                        (row.get("stand") or "?").strip())
                overall[pt] += 1
                by_count[cnt][pt] += 1
                by_hand[hand][pt] += 1
                p_overall[pid][pt] += 1
                p_by_count[pid][cnt][pt] += 1
                p_by_hand[pid][hand][pt] += 1
                n += 1

    if n == 0:
        print("REFUSED: parsed 0 pitches -- not printing an empty table")
        return 1
    print(f"{len(files)} files, {n:,} pitches, {len(p_overall)} pitchers\n")

    def fam_pct(c: Counter) -> str:
        f = Counter()
        for k, v in c.items():
            f[FAM[k]] += v
        t = sum(f.values()) or 1
        return "  ".join(f"{x} {100.0*f[x]/t:5.1f}%" for x in ("FB", "BR", "OS"))

    print("=" * 74)
    print("LEAGUE MIX BY COUNT     (TVD = distance from the unconditional mix)")
    print("=" * 74)
    print(f"{'count':>6}  {'n':>9}  {'families':<30}  TVD")
    print(f"{'ALL':>6}  {n:>9,}  {fam_pct(overall):<30}   ---")
    rows = []
    for c in COUNTS:
        if c not in by_count:
            continue
        d = _tvd(by_count[c], overall)
        rows.append((d, c))
        print(f"{c:>6}  {sum(by_count[c].values()):>9,}  {fam_pct(by_count[c]):<30}  {d:.4f}")
    rows.sort(reverse=True)
    print(f"\n  LARGEST count deviation: {rows[0][1]} at TVD {rows[0][0]:.4f}")

    print("\n" + "=" * 74)
    print("LEAGUE MIX BY HAND MATCHUP")
    print("=" * 74)
    for hand in sorted(by_hand):
        if "?" in hand:
            continue
        c = by_hand[hand]
        print(f"  {hand[0]}HP vs {hand[1]}HB  {sum(c.values()):>9,}  "
              f"{fam_pct(c):<30}  TVD {_tvd(c, overall):.4f}")

    print("\n" + "=" * 74)
    print("PER-PITCHER DISPERSION  --  the number that decides if this is EDGE")
    print("=" * 74)
    print("A league pattern is a constant every model prices. Per-pitcher spread")
    print("is matchup information the season vector cannot express.\n")

    for label, src, keys in (
        ("COUNT (0-2 vs own season mix)", p_by_count, ["0-2"]),
        ("COUNT (3-0 vs own season mix)", p_by_count, ["3-0"]),
        ("HAND  (vs own season mix)", p_by_hand, None),
    ):
        vals = []
        for pid, mix in p_overall.items():
            if sum(mix.values()) < args.min_pitches:
                continue
            sub = src[pid]
            if keys is None:
                for h, c in sub.items():
                    if "?" not in h and sum(c.values()) >= 100:
                        vals.append(_tvd(c, mix))
            else:
                for k in keys:
                    c = sub.get(k)
                    if c and sum(c.values()) >= 60:
                        vals.append(_tvd(c, mix))
        if not vals:
            print(f"  {label:<34}  no pitcher clears the sample floor")
            continue
        vals.sort()
        q = lambda p: vals[min(len(vals) - 1, int(p * len(vals)))]
        print(f"  {label:<34}  n={len(vals):>4}  median TVD {q(0.5):.4f}   "
              f"p90 {q(0.9):.4f}   max {max(vals):.4f}")

    print("\n  READ: TVD 0.10 means the true conditional mix differs from the")
    print("  season vector by 10 percentage points of probability mass. The sim")
    print("  applies vs_pitch_type multipliers against that error, every pitch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
