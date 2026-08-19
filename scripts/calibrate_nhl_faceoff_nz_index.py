#!/usr/bin/env python3
"""Calibration CHECK for the neutral-zone faceoff index -- and, as a side effect, for the
already-shipped EV/OZ/DZ indices too. Answers: does a team's SEASON-AGGREGATE faceoff win rate (at
any zone) actually correlate with their SEASON-AGGREGATE real shot generation?

WHY THIS IS A "CALIBRATION" SCRIPT, NOT JUST ANOTHER INDEX BUILDER. Every prior faceoff-zone pass
this session (EV, OZ, DZ) built a per-team index and verified it was CORRECTLY NORMALIZED (mean
~1.0) and did not disturb the ENGINE's own simulated league-wide average -- neither check asks
whether the index reflects something REAL about shot generation in the first place. This script
asks that question directly: Pearson correlation between each index and real `shots_per_60`
(`team_game_rates.py`'s own real per-team data, `team_rates_latest.csv`), team-season aggregated.

WHY A NULL RESULT HERE DOES NOT DISPROVE THE ENGINE'S SEGMENT-LEVEL MECHANISM. `_faceoff_multipliers`
models a LOCAL, MOMENT-TO-MOMENT effect (does winning THIS draw shift shot generation in the
following seconds of THIS segment) -- a real effect could exist at that timescale and still wash
out completely in a SEASON-LONG aggregate correlation, diluted by everything else that happens in
the other ~58 minutes of each game. This script cannot distinguish "no real effect" from "a real
but small/local effect invisible at this level of aggregation" -- it answers the narrower, still
useful question of whether SEASON-AGGREGATE faceoff performance predicts SEASON-AGGREGATE shot
volume, which is the only comparison the currently-available data supports (matching shots to the
~15 seconds after each specific real draw would need full event-sequence time-delta analysis, out
of scope for this pass).

Usage:
  py -3 scripts/calibrate_nhl_faceoff_nz_index.py
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_ev_index import (  # noqa: E402
    MIN_GAMES_FOR_FACEOFF_INDEX,
    compute_team_faceoff_dz_index,
    compute_team_faceoff_ev_index,
    compute_team_faceoff_nz_index,
    compute_team_faceoff_oz_index,
    parse_playbyplay_faceoffs_by_zone,
    parse_playbyplay_faceoffs_ev,
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


def _load_real_shots_per_60(root: Path) -> Dict[str, float]:
    path = root / "data" / "processed" / "team_rates_latest.csv"
    if not path.exists():
        print(f"REFUSED: {path} does not exist -- run scripts/build_nhl_team_rates_artifact.py first", file=sys.stderr)
        sys.exit(1)
    out: Dict[str, float] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                out[row["abbr"]] = float(row["shots_per_60"])
            except (KeyError, ValueError):
                continue
    return out


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    if not sx or not sy:
        return None
    return cov / (len(xs) * sx * sy)


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

    zone_recs = [r for d in playbyplay if (r := parse_playbyplay_faceoffs_by_zone(d)) is not None]
    ev_recs = [r for d in playbyplay if (r := parse_playbyplay_faceoffs_ev(d)) is not None]
    print(f"parsed {len(zone_recs)} zone-split games, {len(ev_recs)} EV-only games from {len(playbyplay)} playbyplay payloads")

    nz_idx = compute_team_faceoff_nz_index(zone_recs)
    oz_idx = compute_team_faceoff_oz_index(zone_recs)
    dz_idx = compute_team_faceoff_dz_index(zone_recs)
    ev_idx = compute_team_faceoff_ev_index(ev_recs)

    real_shots = _load_real_shots_per_60(root)
    league_mean_shots = statistics.mean(real_shots.values())
    print(f"league mean shots_per_60 (real): {league_mean_shots:.4f}")

    common = sorted(set(nz_idx) & set(real_shots))
    qualified = [t for t in common if nz_idx[t].games >= MIN_GAMES_FOR_FACEOFF_INDEX]
    print(f"teams in common set: {len(common)}, qualified (>= {MIN_GAMES_FOR_FACEOFF_INDEX} games): {len(qualified)}")

    shot_dev = [real_shots[t] - league_mean_shots for t in qualified]
    results = {}
    for label, idx in (("nz", nz_idx), ("oz", oz_idx), ("dz", dz_idx), ("ev", ev_idx)):
        vals = [idx[t].index for t in qualified]
        r = _pearson(vals, shot_dev)
        results[label] = r
        print(f"  corr({label}_index, real_shots_per_60_deviation) = {r}")

    print("\n" + "=" * 88)
    print("RESULT: does any faceoff-zone index correlate with real season-aggregate shot generation?")
    print("=" * 88)
    max_abs = max(abs(r) for r in results.values() if r is not None)
    if max_abs < 0.15:
        print(f"NO -- every |correlation| is under 0.15 (largest: {max_abs:.4f}). This is consistent")
        print("with faceoffs having little to no SEASON-AGGREGATE relationship to shot generation in")
        print("real hockey (a well-documented finding in public NHL analytics), though it cannot rule")
        print("out a real but small/local segment-level effect invisible at this aggregation level.")
        print("CONCLUSION: do NOT wire faceoff_nz_index -- no real evidence supports it, and the same")
        print("null result for the ALREADY-SHIPPED ev/oz/dz indices is a real, separate finding worth")
        print("recording: none of them have season-aggregate validation either, only the internal")
        print("(does the index normalize correctly, does the engine's own simulated output move as")
        print("expected) checks each already passed.")
    else:
        print(f"Largest |correlation| = {max_abs:.4f} -- worth investigating further before a wiring")
        print("decision either way.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "teams_qualified": len(qualified),
            "league_mean_shots_per_60": round(league_mean_shots, 4),
            "correlations": {k: (round(v, 4) if v is not None else None) for k, v in results.items()},
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
