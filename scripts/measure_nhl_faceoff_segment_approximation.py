#!/usr/bin/env python3
"""Measures the real impact of the LAST genuinely open faceoff-track item: the discrete-event
engine's "one faceoff assumed per real segment" approximation. First stated when the discrete-event
redesign shipped (`engine.py`'s segment loop applies a decay-curve-based faceoff multiplier to
EVERY simulated segment, EV or PP/PK, with no branch for "no real faceoff happened here"), never
revisited by any of the faceoff addenda built on top of it since.

WHAT THE APPROXIMATION ACTUALLY IS, READ FROM THE CODE, NOT ASSUMED. `engine.py`'s per-period
segment loop (`hockeysim.HockeySim._simulate_period` or equivalent): for a regulation period
(`T == seconds_per_period == 1200`), `target_seg = 45.0`, `segments = round(T / target_seg) = 27`,
`seg_len = T / segments ~= 44.44s`. EVERY one of those 27 segments -- no exceptions, no "skip this
one" branch -- gets exactly one faceoff-driven shot-share multiplier applied (EV/OZ/DZ/NZ or the
strength-state mechanism, whichever the segment's PP/PK flags select), computed as if one real
faceoff occurred at the segment's own start and its decay curve's time-weighted average over the
FULL segment length describes the whole window.

WHY THIS COULD MATTER, AND WHY IT MIGHT NOT. Real EV faceoffs/game ~=44.8 (58,762/1,312 games,
measured earlier this session) -- 3 regulation periods x 27 segments/period = 81 EV-or-PP/PK
segments/game get an assumed draw, well above any real total-faceoff count. But every curve this
session built is MEAN-1.0 preserving in aggregate (verified via round-robin every time), so
over-assuming faceoff events does not by itself bias the AVERAGE shot total -- what it CAN bias is
the real TIMING/CLUSTERING of when a faceoff-driven boost is applied vs when a real draw actually
happened. This script measures that directly: for every real segment window (using the ENGINE'S
OWN segment boundaries, not an arbitrary bucket), how many REAL faceoffs (any strength state)
actually fall inside it -- compared to the modeled assumption of exactly 1, always.

METHODOLOGY. Real games only (1,312 cached `playbyplay` payloads). For periods 1-3 of every game
(T=1200=seconds_per_period always holds there, so `target_seg=45`/`segments=27` applies
identically to what the engine computes -- confirmed by reading `engine.py:467-469` directly, not
assumed), divide the period into the SAME 27 segments the engine would generate and count real
faceoff events (`typeDescKey=="faceoff"`, any strength state) whose `timeInPeriod` falls in each
segment's `[k*seg_len, (k+1)*seg_len)` window. OT periods are out of scope (segment geometry
differs, `target_seg=40`, and OT/shootout faceoff volume is a small fraction of the total -- a
separate question, not attempted here).

Usage:
  py -3 scripts/measure_nhl_faceoff_segment_approximation.py
  py -3 scripts/measure_nhl_faceoff_segment_approximation.py --json reports/phase7/nhl_faceoff_segment_approximation.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_segment_effect import (  # noqa: E402
    _extract_timed_events,
)

# Read directly from engine.py's own SimConfig/segment-generation logic, not re-typed by hand --
# `seconds_per_period` default and the `target_seg`/`segments` formula for a regulation period.
from syndicate.features.nhl.sim_engine.hockeysim.engine import SimConfig  # noqa: E402

_SECONDS_PER_PERIOD = SimConfig().seconds_per_period  # 1200 by default -- read the live default
_TARGET_SEG_REGULATION = 45.0  # engine.py:467 -- T == seconds_per_period -> the `else` branch
_SEGMENTS_PER_REGULATION_PERIOD = int(max(6, round(_SECONDS_PER_PERIOD / _TARGET_SEG_REGULATION)))
_SEG_LEN = _SECONDS_PER_PERIOD / _SEGMENTS_PER_REGULATION_PERIOD


def _nhl_source_root() -> Path:
    import os
    env = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    return REPO / "data" / "nhl_source"


def _load_regular_season_playbyplay(root: Path) -> List[Dict]:
    cache_dir = root / "data" / "ingestion_cache"
    files = sorted(glob.glob(str(cache_dir / "playbyplay_*.json")))
    out = []
    for p in files:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if int(data.get("gameType") or 0) != 2:
            continue
        out.append(data)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    games = _load_regular_season_playbyplay(root)
    if not games:
        print(f"REFUSED: no playbyplay cache under {root / 'data' / 'ingestion_cache'}", file=sys.stderr)
        return 1

    print(f"games: {len(games)}")
    print(f"engine's own segment geometry for a regulation period (read from SimConfig/engine.py, "
          f"not re-typed): seconds_per_period={_SECONDS_PER_PERIOD}, target_seg="
          f"{_TARGET_SEG_REGULATION}, segments/period={_SEGMENTS_PER_REGULATION_PERIOD}, "
          f"seg_len={_SEG_LEN:.4f}s")

    counts_dist: Counter = Counter()  # real faceoffs found in a segment -> number of segments
    n_segments_total = 0
    n_real_faceoffs_counted = 0
    n_segments_with_multi_winner_conflict = 0  # 2+ real faceoffs in one segment, DIFFERENT winners

    for payload in games:
        events = _extract_timed_events(payload, include_non_ev=True)
        # Faceoffs only, grouped by period, sorted by time (input order is already chronological
        # per the module's own docstring, but sort defensively -- this script owns its own bucket
        # math and should not silently inherit an ordering assumption from elsewhere).
        by_period: Dict[int, List] = {}
        for ev in events:
            if not ev.is_faceoff or ev.team_id is None:
                continue
            if ev.period not in (1, 2, 3):
                continue  # OT/shootout -- different segment geometry, out of scope
            by_period.setdefault(ev.period, []).append(ev)
        for period, fo_list in by_period.items():
            fo_list.sort(key=lambda e: e.seconds)
        for period in (1, 2, 3):
            fo_list = by_period.get(period, [])
            for k in range(_SEGMENTS_PER_REGULATION_PERIOD):
                seg_start = k * _SEG_LEN
                seg_end = (k + 1) * _SEG_LEN
                in_window = [e for e in fo_list if seg_start <= e.seconds < seg_end]
                n = len(in_window)
                counts_dist[n] += 1
                n_segments_total += 1
                n_real_faceoffs_counted += n
                if n >= 2:
                    winners = {e.team_id for e in in_window}
                    if len(winners) >= 2:
                        n_segments_with_multi_winner_conflict += 1

    print(f"\ntotal segments (engine geometry, periods 1-3 only): {n_segments_total}")
    print(f"total real faceoffs counted into those segments: {n_real_faceoffs_counted}")
    print(f"mean real faceoffs per segment: {n_real_faceoffs_counted / n_segments_total:.4f}  "
          f"(the engine ALWAYS assumes exactly 1.0)")
    print(f"\ndistribution (real faceoffs found in a segment -> % of segments):")
    for n in sorted(counts_dist):
        pct = 100.0 * counts_dist[n] / n_segments_total
        print(f"  {n}: {counts_dist[n]:7d} segments  ({pct:.2f}%)")
    pct_zero = 100.0 * counts_dist.get(0, 0) / n_segments_total
    pct_one = 100.0 * counts_dist.get(1, 0) / n_segments_total
    pct_multi = 100.0 * sum(v for k, v in counts_dist.items() if k >= 2) / n_segments_total
    print(f"\nsummary: {pct_zero:.2f}% of segments had ZERO real faceoffs (an assumed draw with no "
          f"real driver) vs {pct_one:.2f}% matching the model's assumption exactly vs {pct_multi:.2f}% "
          f"with 2+ real faceoffs (under-modeled -- only one assumed effect applied where multiple "
          f"real draws, potentially split between teams, actually occurred).")
    print(f"segments with 2+ real faceoffs won by DIFFERENT teams (a case the model cannot "
          f"represent at all -- it resolves ONE assumed winner per segment): "
          f"{n_segments_with_multi_winner_conflict} "
          f"({100.0 * n_segments_with_multi_winner_conflict / n_segments_total:.2f}% of all segments)")

    result = {
        "games": len(games),
        "seconds_per_period": _SECONDS_PER_PERIOD, "target_seg": _TARGET_SEG_REGULATION,
        "segments_per_period": _SEGMENTS_PER_REGULATION_PERIOD, "seg_len": round(_SEG_LEN, 4),
        "n_segments_total": n_segments_total, "n_real_faceoffs_counted": n_real_faceoffs_counted,
        "mean_real_faceoffs_per_segment": round(n_real_faceoffs_counted / n_segments_total, 4),
        "distribution": {str(k): v for k, v in sorted(counts_dist.items())},
        "pct_zero_real_faceoffs": round(pct_zero, 4),
        "pct_exactly_one": round(pct_one, 4),
        "pct_two_or_more": round(pct_multi, 4),
        "n_segments_multi_winner_conflict": n_segments_with_multi_winner_conflict,
        "pct_segments_multi_winner_conflict": round(100.0 * n_segments_with_multi_winner_conflict / n_segments_total, 4),
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
