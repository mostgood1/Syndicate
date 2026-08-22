"""Score the PRE-REGISTERED xG rule on a fresh sample. No tuning knobs.

The rule -- feature, half-life, window, time band and threshold -- is read from
`fotmob_xg_prereg.json`, which was committed to main BEFORE this sample was
harvested (commit fdf1b892). This script cannot change it: there is no
threshold argument, and the band boundaries are not parameters. That is the
entire point. The previous pre-registration in this session was honoured in
form and then read loosely, and a rule that LOST to the base rate was reported
as a WEAK PASS.

PASS REQUIRES BOTH, and the second is the one that was missing before:
  (a) fresh hit >= clock-only(fresh) + 0.02   -- it beats the simpler feature
  (b) fresh hit >  base rate(fresh)           -- it beats doing nothing

`count` is scored alongside as the CONTROL. It is the ESPN-equivalent feature,
already available without a FotMob dependency. If count clears too, xG has not
earned the dependency; if neither clears, the discovery increment was noise.

CONTROL BUG, FOUND AND FIXED 2026-08-22 -- READ THIS BEFORE TRUSTING ANY
CONTROL IN THIS REPO. The first run applied xG's threshold (0.8905) to BOTH
features. But count-pressure ranges 1.55..13.76 while xG-pressure ranges
0.09..1.82, so that threshold fired on 100% of the band for count and 24% for
xG. The control selected the ENTIRE band, so its delta was +0.0000 by
arithmetic, before any data existed. It then read as "the control does not
clear" -- the single sentence that would have justified a FotMob dependency.

A control on a DIFFERENT SCALE must be matched by SELECTION RATE, never by
threshold value. Rebuilt that way, count scored +0.1447 and BEAT xG. The
conclusion inverted.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.soccer_fotmob_xg_test import samples, _hold

_PREREG = Path("reports/soccer_backtest/fotmob_xg_prereg.json")
_FRESH = Path("reports/soccer_backtest/fotmob_xg_fresh.json")
_DISC = Path("reports/soccer_backtest/fotmob_xg_cache.json")


def _wilson(k: int, n: int) -> tuple[float, float]:
    """95% interval. A point estimate with no interval is how n=90 got read as
    a result in the first place."""
    if n == 0:
        return 0.0, 0.0
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - m), min(1.0, c + m)


def _band(rows: list[dict], lo: float, hi: float) -> list[dict]:
    return [r for r in rows if lo <= r["t"] < hi]


def main() -> int:
    rule = json.loads(_PREREG.read_text(encoding="utf-8"))
    fresh = json.loads(_FRESH.read_text(encoding="utf-8"))["matches"]
    disc_ids = {str(m["match_id"]) for m in json.loads(_DISC.read_text(encoding="utf-8"))["matches"]}

    # OVERLAP CHECK. "Fresh" is a claim about the data, not about intent.
    overlap = [m for m in fresh if str(m["match_id"]) in disc_ids]
    print(f"fresh matches      {len(fresh)}")
    print(f"overlap with discovery  {len(overlap)}   <-- must be 0")
    if overlap:
        fresh = [m for m in fresh if str(m["match_id"]) not in disc_ids]
        print(f"  dropped; scoring on {len(fresh)}")

    lo, hi = rule["time_lo_s"], rule["time_hi_s"]
    thr = rule["xg_pressure_threshold"]
    print(f"\nPRE-REGISTERED RULE (committed before this sample existed)")
    print(f"  fire at {lo/60:.0f}-{hi/60:.0f} min when xG-pressure >= {thr}")
    d = rule["discovery_values"]
    print(f"  discovery said: clock {d['clock_only']:.4f} -> {d['with_feature']:.4f}"
          f"  (delta {d['delta']:+.4f})")

    # Each feature gets ITS OWN threshold at the same DISCOVERY percentile, so
    # both select the same share of the band. See the CONTROL BUG note above.
    disc_hold = [m for m in json.loads(_DISC.read_text(encoding="utf-8"))["matches"]
                 if _hold(m["match_id"])]

    results = {}
    for feature in ("xg", "count"):
        drows = [r for r in samples(disc_hold, half_life=rule["half_life"],
                                    window=rule["window"], step=rule["step"],
                                    feature=feature) if lo <= r["t"] < hi]
        dps = sorted(r["p"] for r in drows)
        thr = dps[int(len(dps) * 0.75)] if dps else rule["xg_pressure_threshold"]
        rows = samples(fresh, half_life=rule["half_life"], window=rule["window"],
                       step=rule["step"], feature=feature)
        base = statistics.mean([r["label"] for r in rows]) if rows else 0.0
        band = _band(rows, lo, hi)
        clock = statistics.mean([r["label"] for r in band]) if band else 0.0
        fired = [r for r in band if r["p"] >= thr]
        hit = statistics.mean([r["label"] for r in fired]) if fired else 0.0
        k = sum(r["label"] for r in fired)
        w = _wilson(k, len(fired))
        results[feature] = {
            "base": base, "clock": clock, "hit": hit, "n_fired": len(fired),
            "n_band": len(band), "delta": hit - clock, "ci": w,
            "beats_clock": (hit - clock) >= 0.02, "beats_base": hit > base,
        }

    print(f"\n{'':12}{'base':>8}{'clock':>9}{'FIRED':>9}{'n':>6}{'delta':>9}   95% CI")
    for f, r in results.items():
        tag = "  <- CONTROL" if f == "count" else ""
        print(f"  {f:<10}{r['base']:>8.4f}{r['clock']:>9.4f}{r['hit']:>9.4f}"
              f"{r['n_fired']:>6}{r['delta']:>+9.4f}   [{r['ci'][0]:.3f},{r['ci'][1]:.3f}]{tag}")

    x = results["xg"]
    c = results["count"]
    print(f"\n=== VERDICT, against the bands fixed in advance ===")
    print(f"  (a) xg beats clock by >= 0.02 : {'PASS' if x['beats_clock'] else 'FAIL'}"
          f"   ({x['delta']:+.4f})")
    print(f"  (b) xg beats base rate        : {'PASS' if x['beats_base'] else 'FAIL'}"
          f"   ({x['hit']:.4f} vs {x['base']:.4f})")
    print(f"  control: count beats clock    : {'yes' if c['beats_clock'] else 'no'}"
          f"   ({c['delta']:+.4f})")

    if x["beats_clock"] and x["beats_base"] and not c["beats_clock"]:
        v = "PASS -- xG clears and the ESPN-equivalent control does not. Dependency earned."
    elif x["beats_clock"] and x["beats_base"] and c["beats_clock"]:
        v = "AMBIGUOUS -- xG clears but so does count. No FotMob dependency justified."
    else:
        v = "FAIL -- the discovery increment did not survive. n was ~90; this is the expected outcome of reading a tail after the fact."
    print(f"\n  {v}")

    # Economic read, only if it passed. break-even at 2-1 is 33.3%.
    if x["beats_clock"] and x["beats_base"]:
        print(f"\n  vs break-even: 2-1 needs 0.3333 -> {'clears' if x['hit'] > 1/3 else 'BELOW'}")
        print(f"                 3-1 needs 0.2500 -> {'clears' if x['hit'] > 0.25 else 'BELOW'}")
        print(f"  CI LOWER BOUND {x['ci'][0]:.4f} -- if that is under break-even the edge is not established")

    out = Path("reports/soccer_backtest/fotmob_xg_prereg_result.json")
    out.write_text(json.dumps({"rule": rule, "n_fresh": len(fresh),
                               "overlap": len(overlap), "results": results,
                               "verdict": v}, indent=2, default=float), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
