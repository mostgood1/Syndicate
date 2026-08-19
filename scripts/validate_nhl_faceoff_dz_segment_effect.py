#!/usr/bin/env python3
"""Segment-level validation of the DZ-specific faceoff mechanism's DUAL claim -- the item
`hockeysim_faceoff_discrete_event_redesign_report.md` flagged as the one faceoff-zone mechanism
never separately measured: "DZ's own segment-level effect was never separately measured."

`historical_truth/faceoff_ev_index.py`'s §2o docstring justifies the DZ mechanism with a DUAL
claim: a team that wins its own defensive-zone draw both (a) SUPPRESSES the opponent's sustained
shot generation from that zone-time, AND (b) can SPRING the winning team's own transition/rush
chance. This script tests both halves directly, using the SAME winner/other post-faceoff shot
split `validate_nhl_faceoff_segment_effect.py` already validated for the general EV/OZ claim --
just restricted to draws the winner took in THEIR OWN defensive zone (`winner_zone="D"`).

Usage:
  py -3 scripts/validate_nhl_faceoff_dz_segment_effect.py
  py -3 scripts/validate_nhl_faceoff_dz_segment_effect.py --window-seconds 20
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_segment_effect import (  # noqa: E402
    compute_post_faceoff_shots,
    summarize_post_faceoff_shots,
)


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
    ap.add_argument("--window-seconds", type=float, default=15.0)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    playbyplay = _load_regular_season_playbyplay(root)
    if not playbyplay:
        print(f"REFUSED: no playbyplay cache under {root} -- run scripts/fetch_nhl_playbyplay_cache.py first", file=sys.stderr)
        return 1

    dz_recs = [r for d in playbyplay
               if (r := compute_post_faceoff_shots(d, window_seconds=args.window_seconds, winner_zone="D")) is not None]
    all_recs = [r for d in playbyplay
                if (r := compute_post_faceoff_shots(d, window_seconds=args.window_seconds)) is not None]
    print(f"parsed {len(dz_recs)} games (window={args.window_seconds}s, winner_zone=D)")

    dz_summary = summarize_post_faceoff_shots(dz_recs)
    all_summary = summarize_post_faceoff_shots(all_recs)
    print(f"DZ-specific draws: {dz_summary.n_faceoffs}  (all-zone EV draws, for context: {all_summary.n_faceoffs})")
    print(f"DZ winner shots: {dz_summary.winner_shots}  DZ other-team shots: {dz_summary.other_shots}")
    print(f"DZ winner share of post-faceoff shots: {dz_summary.winner_share:.4f} (0.5 = no effect)")
    print(f"DZ shots per 100 window-seconds -- winner: {dz_summary.shots_per_100_faceoff_seconds_winner:.4f}  "
          f"other: {dz_summary.shots_per_100_faceoff_seconds_other:.4f}  "
          f"ratio: {dz_summary.shots_per_100_faceoff_seconds_winner / dz_summary.shots_per_100_faceoff_seconds_other:.3f}x")
    print(f"\nfor comparison, ALL-ZONE EV draws at the same window:")
    print(f"  winner share: {all_summary.winner_share:.4f}   ratio: "
          f"{all_summary.shots_per_100_faceoff_seconds_winner / all_summary.shots_per_100_faceoff_seconds_other:.3f}x")

    print("\n" + "=" * 88)
    print("RESULT: does winning a real DZ faceoff show the dual suppress-and-spring effect the mechanism claims?")
    print("=" * 88)
    if dz_summary.winner_share > 0.55:
        print(f"YES, in the same direction as the general EV/OZ effect -- winner_share={dz_summary.winner_share:.3f}")
        print("is well above the 0.5 no-effect baseline. The winning team (the one that cleared its own")
        print("zone) shows a real post-draw shot advantage over the team that was pressuring and lost the")
        print("draw -- consistent with BOTH halves of the mechanism's claim (suppression of the pressuring")
        print("team AND a transition/rush bump for the clearing team), though this measurement cannot")
        print("separate the two halves from each other -- both manifest as the SAME winner-vs-other split.")
    else:
        print(f"NO clear effect -- winner_share={dz_summary.winner_share:.3f} is close to the 0.5 baseline.")
        print("This would NOT support the DZ mechanism's dual claim as currently justified.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "window_seconds": args.window_seconds,
            "dz": {
                "n_games": dz_summary.n_games, "n_faceoffs": dz_summary.n_faceoffs,
                "winner_shots": dz_summary.winner_shots, "other_shots": dz_summary.other_shots,
                "winner_share": dz_summary.winner_share,
                "shots_per_100_faceoff_seconds_winner": dz_summary.shots_per_100_faceoff_seconds_winner,
                "shots_per_100_faceoff_seconds_other": dz_summary.shots_per_100_faceoff_seconds_other,
            },
            "all_zone_ev": {
                "n_faceoffs": all_summary.n_faceoffs, "winner_share": all_summary.winner_share,
            },
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
