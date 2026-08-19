#!/usr/bin/env python3
"""Build the MARGINAL (per-bucket) post-faceoff shot-rate decay curve, extending
`hockeysim_faceoff_segment_validation_report.md`'s cumulative-window measurement out to the
engine's actual segment length (~40-45s, `engine.py`'s `target_seg`) and beyond -- the real-data
input `historical_truth/faceoff_decay_model.py`'s discrete-event mechanism is calibrated against.

WHY MARGINAL, NOT CUMULATIVE. The validation report measured shots/100s AVERAGED OVER [0, W] for
several W -- useful for showing the effect is real and decays, but not directly usable as a
per-second multiplier curve (a segment straddling multiple buckets needs to know the rate AT each
sub-interval, not the average up to various endpoints). This script loads the `playbyplay` cache
ONCE (unlike calling `validate_nhl_faceoff_segment_effect.py` once per window, which re-reads 1,312
files from disk per window) and computes shots in each of a sequence of ADJACENT, non-overlapping
buckets -- (0,5], (5,10], (10,15], (15,20], (20,30], (30,45], (45,60], (60,90] -- using the SAME
truncation-at-next-faceoff discipline the validation report already established, so a shot is never
double-counted across two buckets either.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_segment_effect import (  # noqa: E402
    _PERIOD_LENGTH_SECONDS,
    _extract_timed_events,
)

# Adjacent, non-overlapping bucket boundaries in seconds since the draw.
_BUCKETS: List[Tuple[float, float]] = [
    (0.0, 5.0), (5.0, 10.0), (10.0, 15.0), (15.0, 20.0),
    (20.0, 30.0), (30.0, 45.0), (45.0, 60.0), (60.0, 90.0),
]


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


def _bucket_counts_for_game(payload: Dict) -> Tuple[List[int], List[int], List[float], int]:
    """Per-bucket (winner_shots, other_shots, actual_seconds_covered) for one game, plus the
    game's own EV faceoff count. A bucket's actual coverage is truncated at the next EV faceoff
    (same discipline as `compute_post_faceoff_shots`), so a faceoff late in a shift contributes
    less than the full bucket width to the denominator -- avoiding a rate that's biased toward
    zero just because most of that bucket's nominal width was never actually "available".
    """
    events = _extract_timed_events(payload)
    n_buckets = len(_BUCKETS)
    winner = [0] * n_buckets
    other = [0] * n_buckets
    covered = [0.0] * n_buckets
    n_faceoffs = 0

    for i, ev in enumerate(events):
        if not ev.is_faceoff or ev.team_id is None:
            continue
        n_faceoffs += 1
        next_faceoff_time: Optional[float] = None
        for later in events[i + 1:]:
            if later.period != ev.period:
                break
            if later.is_faceoff:
                next_faceoff_time = later.seconds
                break
        hard_end = min(ev.seconds + _BUCKETS[-1][1], _PERIOD_LENGTH_SECONDS)
        actual_end = hard_end if next_faceoff_time is None else min(hard_end, next_faceoff_time)

        for b, (lo, hi) in enumerate(_BUCKETS):
            bucket_lo = ev.seconds + lo
            bucket_hi = min(ev.seconds + hi, actual_end)
            if bucket_hi <= bucket_lo:
                continue
            covered[b] += bucket_hi - bucket_lo
            for later in events[i + 1:]:
                if later.period != ev.period or later.seconds > bucket_hi:
                    break
                if later.seconds < bucket_lo:
                    continue
                if later.is_shot and later.team_id is not None:
                    if later.team_id == ev.team_id:
                        winner[b] += 1
                    else:
                        other[b] += 1

    return winner, other, covered, n_faceoffs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    playbyplay = _load_regular_season_playbyplay(root)
    if not playbyplay:
        print(f"REFUSED: no playbyplay cache under {root} -- run scripts/fetch_nhl_playbyplay_cache.py first", file=sys.stderr)
        return 1
    print(f"loaded {len(playbyplay)} regular-season playbyplay payloads")

    n_buckets = len(_BUCKETS)
    total_winner = [0] * n_buckets
    total_other = [0] * n_buckets
    total_covered = [0.0] * n_buckets
    total_faceoffs = 0

    for payload in playbyplay:
        w, o, c, n = _bucket_counts_for_game(payload)
        for b in range(n_buckets):
            total_winner[b] += w[b]
            total_other[b] += o[b]
            total_covered[b] += c[b]
        total_faceoffs += n

    print(f"total EV faceoffs: {total_faceoffs}\n")
    print(f"{'bucket':>12}  {'winner/100s':>12}  {'other/100s':>11}  {'ratio':>7}  {'covered_s':>12}")
    curve = []
    for b, (lo, hi) in enumerate(_BUCKETS):
        cov = total_covered[b]
        rw = (total_winner[b] / cov * 100.0) if cov else 0.0
        ro = (total_other[b] / cov * 100.0) if cov else 0.0
        ratio = (rw / ro) if ro else None
        print(f"  ({lo:>4.0f},{hi:>4.0f}]  {rw:12.4f}  {ro:11.4f}  "
              f"{(f'{ratio:.3f}x' if ratio is not None else 'n/a'):>7}  {cov:12.1f}")
        curve.append({
            "lo": lo, "hi": hi, "winner_shots": total_winner[b], "other_shots": total_other[b],
            "covered_seconds": round(cov, 1),
            "winner_per_100s": round(rw, 4), "other_per_100s": round(ro, 4),
            "ratio": round(ratio, 4) if ratio is not None else None,
        })

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"total_ev_faceoffs": total_faceoffs, "buckets": curve}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
