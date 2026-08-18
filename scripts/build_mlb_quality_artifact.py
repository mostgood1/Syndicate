"""Build the STATCAST QUALITY artifact — feeds `statcast_quality_mult`. `#440`.

CONTRACT, settled 2026-08-18 (see the comment on `BatterProfile` in models.py):

`statcast_quality_mult` is a **UNION bag, partial by design**. Three consumers
read it and each takes only the keys it recognises:

  * `_statcast_shape_rate_mults` (`simulate.py:163`) reads the RAW metrics and
    DERIVES `{k,bb,hr,inplay,pitch_count,xb}` from them;
  * the lookahead pressure term (`simulate.py:1400`) reads BOTH raw metrics and
    derived multipliers, guarding each with `isinstance`.

`_rate_ratio_mult` returns **1.0** for a missing or non-numeric value, so
supplying a SUBSET is legal and safe. **Verified in code before relying on it.**

**THIS FEEDER SUPPLIES RAW METRICS ONLY — never `k`/`bb`/`hr`/`inplay`.**
The shape function already derives those; supplying them too would let the
lookahead add pressure from a value the shape function has separately applied.
That is double-counting, the failure measured 2026-08-17 (two mechanisms,
interaction −0.00331, negative in 4 of 4).

WHAT IS SUPPLIED, and what is not:

    xwoba          <- expected_stats.est_woba          SUPPLIED  (0.249-0.461)
    ev_mean        <- exitvelo_barrels.avg_hit_speed    SUPPLIED  (81.5-96.0 mph)
    ev_max         <- exitvelo_barrels.max_hit_speed    SUPPLIED  (100.8-119.0)

**NOT `statcast_*_percentile_ranks`.** That endpoint returns PERCENTILE RANKS
(1.0-100.0), not metric values, and the name says so. A first draft of this file
used it and produced `xwoba: 1.0`, `ev_mean: 26.0`, `ev_max: 67.0` -- percentiles
fed into `_rate_ratio_mult(value, neutral=0.30, ...)`, which compares them to a
RATE. No error, no warning: the checklist would have gone GREEN on garbage. The
value RANGE is the check that caught it, and it is the check worth keeping.

    chase_swing_rate, zone_rate, csw_rate      NOT AVAILABLE from this source
    pulled_air_rate                            NOT AVAILABLE
    pitch_velo_mean, pitch_extension_mean      NOT AVAILABLE (pitcher-side)

Those six are **deliberately absent rather than guessed**. Each missing key costs
exactly one neutral term in the derivation; a fabricated one costs correctness.

Usage:
  vendor\\mlb_bettingv2\\.venv_x64\\Scripts\\python.exe scripts/build_mlb_quality_artifact.py --season 2026
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REL = "mlb_source/source_artifacts/data/quality"

# Keys the shape function reads. Recorded so a future feeder can see at a glance
# what is still missing rather than rediscovering it from simulate.py.
RAW_KEYS = ("chase_swing_rate", "zone_rate", "csw_rate", "contact_rate", "xwoba",
            "ev_mean", "ev_max", "pulled_air_rate", "pitch_velo_mean",
            "pitch_extension_mean")
DERIVED_KEYS = ("k", "bb", "hr", "inplay")   # NEVER written by this feeder


def _root() -> Path:
    o = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(o).expanduser().resolve() if o else (REPO / "data")


def _num(row, col):
    try:
        v = float(row[col])
        return None if v != v else v
    except Exception:
        return None


def _side(expected, exitvelo, label: str) -> dict:
    """Merge the two REAL-VALUE sources on player_id.

    Deliberately two sources: expected-stats carries xwOBA, exit-velo carries the
    EV pair. Neither alone covers the contract, and the percentile endpoint that
    appears to cover both does not carry values at all.
    """
    out: dict[str, dict] = {}
    if expected is not None:
        for _, r in expected.iterrows():
            try:
                pid = int(r["player_id"])
            except Exception:
                continue
            v = _num(r, "est_woba")
            # sanity: xwOBA lives in ~[0.15, 0.55]. A percentile would fail this.
            if v is not None and 0.10 <= v <= 0.60:
                out.setdefault(str(pid), {})["xwoba"] = round(v, 4)
    if exitvelo is not None:
        for _, r in exitvelo.iterrows():
            try:
                pid = int(r["player_id"])
            except Exception:
                continue
            e = out.setdefault(str(pid), {})
            mean = _num(r, "avg_hit_speed")
            if mean is not None and 60.0 <= mean <= 105.0:      # mph, not a rank
                e["ev_mean"] = round(mean, 2)
            mx = _num(r, "max_hit_speed")
            if mx is not None and 80.0 <= mx <= 130.0:
                e["ev_max"] = round(mx, 2)
    out = {k: v for k, v in out.items() if v}
    print(f"  {label}: {len(out)} players")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    try:
        import pybaseball as pb
    except Exception as exc:
        print(f"pybaseball unavailable ({type(exc).__name__}). Use the x64 venv.")
        return 1

    def _try(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:
            print(f"  {getattr(fn, '__name__', fn)} failed: {type(exc).__name__}")
            return None

    batters = _side(_try(pb.statcast_batter_expected_stats, args.season),
                    _try(pb.statcast_batter_exitvelo_barrels, args.season, minBBE=50),
                    "batters")
    pitchers = _side(_try(pb.statcast_pitcher_expected_stats, args.season),
                     _try(pb.statcast_pitcher_exitvelo_barrels, args.season, minBBE=50),
                     "pitchers")

    if not batters and not pitchers:
        print("REFUSED: both sides empty, not writing an artifact")
        return 1

    artifact = {
        "schema_version": 1,
        "season": args.season,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "statcast_{batter,pitcher}_expected_stats + _exitvelo_barrels "
                  "(NOT percentile_ranks -- those are ranks, not values)",
        "contract": "RAW metrics only -- k/bb/hr/inplay are DERIVED by "
                    "simulate.py:_statcast_shape_rate_mults and must not be fed",
        "keys_supplied": ["xwoba", "ev_mean", "ev_max"],
        "keys_not_available": ["chase_swing_rate", "zone_rate", "csw_rate", "contact_rate",
                               "pulled_air_rate", "pitch_velo_mean",
                               "pitch_extension_mean"],
        "counts": {"batters": len(batters), "pitchers": len(pitchers)},
        "batters": batters,
        "pitchers": pitchers,
    }
    out = args.out or (_root() / REL / f"quality_{args.season}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    print(f"\n  supplied  {artifact['keys_supplied']}")
    print(f"  ABSENT    {artifact['keys_not_available']}")
    print("  (absent keys cost one neutral term each; fabricating them would cost correctness)")
    if batters:
        pid, e = next(iter(batters.items()))
        print(f"\n  sample batter {pid}: {json.dumps(e)}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
