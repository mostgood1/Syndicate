#!/usr/bin/env python3
"""Calibration CHECK for the strength-state (PP/PK) faceoff mechanism's own "What this does NOT
do" limitation, §2z: does the ZONE a PP/PK draw happens to be won in have a measurable effect
DISTINCT from the role-only average already shipped (§2x/§2y)?

WHY THIS IS A "CALIBRATION" SCRIPT, NOT A CURVE BUILDER. Every prior faceoff pass this session that
found a real segment-level effect went straight to building a discrete-event decay curve for it.
This one measures FIRST and decides SECOND, matching the NZ precedent
(`docs/reports/hockeysim_faceoff_nz_calibration_report.md`) -- because the population counts for
this specific joint split are known up front to be lopsided (a PP-role draw is 83% offensive-zone,
17% neutral/defensive; a PK-role draw is 84% defensive-zone, 16% neutral/offensive -- most PP/PK
draws happen where you'd expect from the man-advantage itself), so before building six more curves
this script answers two questions a curve builder cannot skip:

1. Is the joint (role, zone) winner-share DIFFERENT from the role-only average -- a real, additional
   signal, not just restating what the role-only curve (§2x) already captures by construction (the
   role-only curve IS the zone-population-weighted average, since it was built from ALL non-EV
   draws for that role, zone-unstratified)?
2. Is there enough PER-TEAM data in each (role, zone) cell to ever build a per-team index for it,
   the way `faceoff_oz_index`/`faceoff_pp_role_index` etc. were built -- or does differentiating by
   BOTH role AND zone simultaneously divide the already-modest non-EV population too thin?

Usage:
  py -3 scripts/calibrate_nhl_faceoff_strength_zone_joint.py
  py -3 scripts/calibrate_nhl_faceoff_strength_zone_joint.py --json reports/phase7/nhl_faceoff_strength_zone_joint.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_segment_effect import (  # noqa: E402
    _PERIOD_LENGTH_SECONDS,
    _extract_timed_events,
)

_ROLES = ("PP", "PK")
_ZONES = ("O", "N", "D")
_WINDOWS = (10.0, 15.0, 30.0)


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


def _window_shots(events, i, ev, window_seconds: float) -> Tuple[int, int]:
    window_end = min(ev.seconds + window_seconds, _PERIOD_LENGTH_SECONDS)
    next_faceoff_time = None
    for later in events[i + 1:]:
        if later.period != ev.period:
            break
        if later.is_faceoff:
            next_faceoff_time = later.seconds
            break
    actual_end = window_end if next_faceoff_time is None else min(window_end, next_faceoff_time)
    w = o = 0
    for later in events[i + 1:]:
        if later.period != ev.period or later.seconds > actual_end:
            break
        if later.is_shot and later.team_id is not None:
            if later.team_id == ev.team_id:
                w += 1
            else:
                o += 1
    return w, o


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    games = _load_regular_season_playbyplay(root)
    if not games:
        print(f"REFUSED: no playbyplay cache under {root / 'data' / 'ingestion_cache'}", file=sys.stderr)
        return 1

    # Per (role, zone, window): winner_shots, other_shots, n_draws (league-wide).
    agg: Dict[Tuple[str, str, float], List[int]] = defaultdict(lambda: [0, 0, 0])
    # Per (role, zone, team_abbr): n_draws, for the per-team feasibility check (window-independent).
    per_team_n: Dict[Tuple[str, str, str], int] = defaultdict(int)

    for payload in games:
        home_abbr = str((payload.get("homeTeam") or {}).get("abbrev") or "").upper()
        away_abbr = str((payload.get("awayTeam") or {}).get("abbrev") or "").upper()
        home_id = (payload.get("homeTeam") or {}).get("id")
        away_id = (payload.get("awayTeam") or {}).get("id")
        events = _extract_timed_events(payload, include_non_ev=True)
        for i, ev in enumerate(events):
            if not ev.is_faceoff or ev.team_id is None or ev.role is None or ev.zone is None:
                continue
            key_team = home_abbr if ev.team_id == home_id else (away_abbr if ev.team_id == away_id else None)
            if key_team:
                per_team_n[(ev.role, ev.zone, key_team)] += 1
            for window in _WINDOWS:
                w, o = _window_shots(events, i, ev, window)
                cell = agg[(ev.role, ev.zone, window)]
                cell[0] += w
                cell[1] += o
                cell[2] += 1

    print(f"games: {len(games)}")
    print()
    print("--- winner share by (role, zone), vs the role-only average, at 3 window sizes ---")
    role_only: Dict[Tuple[str, float], List[int]] = defaultdict(lambda: [0, 0, 0])
    for (role, zone, window), (w, o, n) in agg.items():
        cell = role_only[(role, window)]
        cell[0] += w
        cell[1] += o
        cell[2] += n

    results = {"games": len(games), "cells": [], "role_only": [], "per_team_feasibility": []}
    for role in _ROLES:
        for window in _WINDOWS:
            rw, ro, rn = role_only[(role, window)]
            role_share = rw / (rw + ro) if (rw + ro) else 0.0
            print(f"{role} role-only @ {window:.0f}s: n={rn} winner_share={role_share:.4f}")
            results["role_only"].append({"role": role, "window": window, "n": rn, "winner_share": round(role_share, 4)})
        for zone in _ZONES:
            for window in _WINDOWS:
                w, o, n = agg.get((role, zone, window), [0, 0, 0])
                share = w / (w + o) if (w + o) else 0.0
                rw, ro, rn = role_only[(role, window)]
                role_share = rw / (rw + ro) if (rw + ro) else 0.0
                delta = share - role_share
                print(f"  {role}+{zone} @ {window:.0f}s: n={n} winner_share={share:.4f} "
                      f"(role-only={role_share:.4f}, delta={delta:+.4f})")
                results["cells"].append({
                    "role": role, "zone": zone, "window": window, "n": n,
                    "winner_share": round(share, 4), "role_only_winner_share": round(role_share, 4),
                    "delta": round(delta, 4),
                })
        print()

    print("--- per-team draw counts, (role, zone) cells -- the feasibility check for a per-team index ---")
    for role in _ROLES:
        for zone in _ZONES:
            counts = [per_team_n.get((role, zone, t), 0) for t in sorted({k[2] for k in per_team_n if k[0] == role and k[1] == zone})]
            if not counts:
                print(f"  {role}+{zone}: NO teams with any draws in this cell")
                results["per_team_feasibility"].append({"role": role, "zone": zone, "teams": 0, "min": 0, "median": 0, "max": 0})
                continue
            counts_sorted = sorted(counts)
            median = counts_sorted[len(counts_sorted) // 2]
            print(f"  {role}+{zone}: {len(counts)} teams with >=1 draw, "
                  f"min={counts_sorted[0]} median={median} max={counts_sorted[-1]} per team")
            results["per_team_feasibility"].append({
                "role": role, "zone": zone, "teams": len(counts),
                "min": counts_sorted[0], "median": median, "max": counts_sorted[-1],
            })

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
