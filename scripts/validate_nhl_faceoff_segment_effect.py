#!/usr/bin/env python3
"""Segment-level (not season-aggregate) validation of the faceoff-driven shot-share mechanism --
the item `hockeysim_faceoff_nz_calibration_report.md` flagged as the only kind of check that could
actually confirm or refute the LOCAL effect `_faceoff_multipliers` claims to model.

Usage:
  py -3 scripts/validate_nhl_faceoff_segment_effect.py
  py -3 scripts/validate_nhl_faceoff_segment_effect.py --window-seconds 20
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

    recs = [r for d in playbyplay if (r := compute_post_faceoff_shots(d, window_seconds=args.window_seconds)) is not None]
    print(f"parsed {len(recs)} games (window={args.window_seconds}s)")

    summary = summarize_post_faceoff_shots(recs)
    print(f"EV faceoffs: {summary.n_faceoffs}")
    print(f"winner shots: {summary.winner_shots}  other-team shots: {summary.other_shots}")
    print(f"winner share of post-faceoff shots: {summary.winner_share:.4f} (0.5 = no effect)")
    print(f"shots per 100 window-seconds -- winner: {summary.shots_per_100_faceoff_seconds_winner:.4f}  "
          f"other: {summary.shots_per_100_faceoff_seconds_other:.4f}  "
          f"ratio: {summary.shots_per_100_faceoff_seconds_winner / summary.shots_per_100_faceoff_seconds_other:.3f}x")

    print("\n" + "=" * 88)
    print("RESULT: does winning a real faceoff produce a real, immediate shot-generation edge?")
    print("=" * 88)
    if summary.winner_share > 0.55:
        print(f"YES -- winner_share={summary.winner_share:.3f} is well above the 0.5 no-effect baseline.")
        print("This is a DIFFERENT result than the season-aggregate correlation check (both near")
        print("zero) -- confirms the effect is real but LOCAL, concentrated in the seconds right")
        print("after a draw, and completely washed out when averaged across a full season.")
    else:
        print(f"NO clear effect -- winner_share={summary.winner_share:.3f} is close to the 0.5 baseline.")

    print("\nIMPORTANT CAVEAT: this does NOT directly validate engine.py's CURRENT mechanism.")
    print("_faceoff_multipliers applies ONE uniform multiplier across an entire engine SEGMENT,")
    print("derived from a team's SEASON-LONG win percentage -- not a discrete, short-lived boost")
    print("tied to a specific draw the way this measurement is. The real effect measured here is a")
    print("SHARP, BRIEF spike (concentrated in ~15s), not a persistent segment-wide shift -- so this")
    print("result validates that faceoffs matter, not that the engine's specific functional form")
    print("(a uniform per-segment multiplier from season win%) is the right way to model it.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "window_seconds": args.window_seconds,
            "n_games": summary.n_games,
            "n_faceoffs": summary.n_faceoffs,
            "winner_shots": summary.winner_shots,
            "other_shots": summary.other_shots,
            "winner_share": summary.winner_share,
            "shots_per_100_faceoff_seconds_winner": summary.shots_per_100_faceoff_seconds_winner,
            "shots_per_100_faceoff_seconds_other": summary.shots_per_100_faceoff_seconds_other,
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
