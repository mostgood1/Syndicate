#!/usr/bin/env python3
"""Calibration CHECK for `_faceoff_multipliers`'s own sensitivity constants
(`faceoff_alpha`/`faceoff_diff_clip`/`faceoff_mult_clip_*`) -- the ONE faceoff-track item every
session addendum has stated as open and NEVER closed (confirmed by an exhaustive re-check of
`hockeysim_engine_reference.md`, `nhl_model_inventory.md`, and every `#463` addendum in
`todo.md`). Still the vendor's original, never-calibrated defaults (`alpha=0.35`,
`diff_clip=0.12`, `mult_clip=[0.90, 1.10]`).

WHY THIS IS NOW CONSEQUENTIAL, NOT JUST HISTORICAL DEBT. `_faceoff_multipliers` used to be almost
entirely a rollback/fallback path once the discrete-event curves (§2r/§2u/§2v/§2w) became default
for EV/OZ/DZ/NZ. It is NOT a fallback for the two newest mechanisms this session built (§2zz, both
passes): `faceoff_lineup_model`/`faceoff_lineup_model_strength_state` call `_faceoff_multipliers`
DIRECTLY, unconditionally, as their ONLY mechanism -- no discrete-event alternative exists for a
persistent per-game roster-quality signal (there is no "event" to build a decay curve from). Every
game this session's own lineup-aware layers touch, in production, right now, is scaled by these
never-validated constants.

METHODOLOGY -- GAME-LEVEL, NOT SEASON-AGGREGATE. `calibrate_nhl_faceoff_nz_index.py` (§2p) already
checked whether SEASON-AGGREGATE faceoff performance predicts SEASON-AGGREGATE shot volume --
found |r| < 0.02 for all four zone indices, indistinguishable from noise. That result does NOT
settle this question: a SEASON aggregate blurs together everyone who ever dressed for a team, while
the lineup-aware signal this calibration targets is explicitly about TONIGHT's specific roster.
This script instead reconstructs, for each of 1,312 REAL games, what `compute_lineup_faceoff_pct`
would have computed from that GAME's own CONFIRMED dressed roster (real players who actually played,
real TOI, from the `boxscore` cache) combined with each player's SEASON-LONG `faceoff_weight`
(excluding no games -- a player's own season rate is not circular with a single game's shot count),
then regresses the real SHOT SHARE that game against the lineup-pct DIFFERENTIAL. Real statistical
power: up to 1,312 games, not 32 team-seasons.

DERIVING alpha FROM A FITTED SLOPE. `_faceoff_multipliers` is symmetric by construction
(`m_home + m_away == 2` always), so the shot share it implies is
`m_home / (m_home + m_away) == (1 + alpha*diff) / 2 == 0.5 + (alpha/2)*diff`. Fitting
`shot_share = 0.5 + k*diff` via OLS gives `alpha = 2*k` directly -- no unit-conversion guesswork.

Usage:
  py -3 scripts/calibrate_nhl_faceoff_alpha.py
  py -3 scripts/calibrate_nhl_faceoff_alpha.py --json reports/phase7/nhl_faceoff_alpha_calibration.json
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

from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import (  # noqa: E402
    compute_lineup_faceoff_pct, load_player_rates_map,
)


def _nhl_source_root() -> Path:
    import os
    env = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    return REPO / "data" / "nhl_source"


def _load_boxscores(root: Path) -> List[Dict]:
    cache_dir = root / "data" / "ingestion_cache"
    files = sorted(glob.glob(str(cache_dir / "boxscore_*.json")))
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


def _skater_rows_with_real_toi(team_stats: Dict) -> List[Dict[str, str]]:
    """`compute_lineup_faceoff_pct`'s expected row shape (`player_id`, `proj_toi`), fed from the
    boxscore's OWN confirmed `toi` field (real minutes actually played this game, `"MM:SS"`
    format) -- more accurate than a pregame projection, since this is the CONFIRMED outcome, not
    a forecast. Goalies excluded (never take faceoffs)."""
    rows: List[Dict[str, str]] = []
    for group in ("forwards", "defense"):
        for p in team_stats.get(group) or []:
            pid = p.get("playerId")
            toi_raw = str(p.get("toi") or "").strip()
            if pid is None or not toi_raw or ":" not in toi_raw:
                continue
            try:
                mm, ss = toi_raw.split(":")
                toi_minutes = int(mm) + int(ss) / 60.0
            except (ValueError, TypeError):
                continue
            rows.append({"player_id": str(pid), "proj_toi": str(toi_minutes)})
    return rows


def _game_shot_share_and_lineup_diff(
    boxscore: Dict, player_rates_map: Dict[int, Dict[str, float]],
) -> Optional[Tuple[float, float]]:
    """`(shot_share, lineup_pct_diff)` for one real game, or `None` if either side's lineup
    doesn't resolve (no qualifying player with real `faceoff_weight` data) or SOG is missing."""
    pbg = boxscore.get("playerByGameStats") or {}
    home_stats, away_stats = pbg.get("homeTeam") or {}, pbg.get("awayTeam") or {}
    home_rows = _skater_rows_with_real_toi(home_stats)
    away_rows = _skater_rows_with_real_toi(away_stats)
    home_lineup_pct = compute_lineup_faceoff_pct(home_rows, player_rates_map)
    away_lineup_pct = compute_lineup_faceoff_pct(away_rows, player_rates_map)
    if home_lineup_pct is None or away_lineup_pct is None:
        return None

    def _team_sog(team_stats: Dict) -> int:
        total = 0
        for group in ("forwards", "defense"):
            for p in team_stats.get(group) or []:
                try:
                    total += int(p.get("sog") or 0)
                except (TypeError, ValueError):
                    continue
        return total

    home_sog, away_sog = _team_sog(home_stats), _team_sog(away_stats)
    if home_sog + away_sog <= 0:
        return None
    shot_share = home_sog / (home_sog + away_sog)
    return shot_share, (home_lineup_pct - away_lineup_pct)


def _ols_slope_and_r2(xs: List[float], ys: List[float]) -> Tuple[float, float, float]:
    """`(intercept, slope, r_squared)` for a simple 2-parameter OLS fit -- no numpy dependency,
    plain arithmetic, so this stays inspectable end-to-end."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    if ss_xx <= 0:
        return mean_y, 0.0, 0.0
    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return intercept, slope, r2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    boxscores = _load_boxscores(root)
    if not boxscores:
        print(f"REFUSED: no boxscore cache under {root}/data/ingestion_cache", file=sys.stderr)
        return 1
    player_rates_map = load_player_rates_map("2026-06-01", root=root)  # season-latest either way
    if not player_rates_map:
        print(f"REFUSED: no player_rates CSV under {root}/data/processed -- run "
              f"scripts/build_nhl_player_rates_artifact.py first", file=sys.stderr)
        return 1
    print(f"loaded {len(boxscores)} regular-season boxscores, "
          f"{len(player_rates_map)} players with individual rate data")

    diffs: List[float] = []
    shares: List[float] = []
    skipped_no_lineup_data = 0
    for box in boxscores:
        result = _game_shot_share_and_lineup_diff(box, player_rates_map)
        if result is None:
            skipped_no_lineup_data += 1
            continue
        share, diff = result
        shares.append(share)
        diffs.append(diff)

    n = len(diffs)
    print(f"games with a resolvable lineup_pct on BOTH sides: {n} "
          f"({skipped_no_lineup_data} skipped -- no qualifying player or missing SOG)")
    if n < 30:
        print("REFUSED: fewer than 30 usable games -- not enough to fit anything meaningfully", file=sys.stderr)
        return 1

    intercept, slope, r2 = _ols_slope_and_r2(diffs, shares)
    alpha_fitted = 2.0 * slope
    diff_abs_p95 = sorted(abs(d) for d in diffs)[int(0.95 * (n - 1))]
    diff_abs_max = max(abs(d) for d in diffs)

    print(f"\nOLS fit: shot_share = {intercept:.4f} + {slope:.4f} * lineup_pct_diff   (R^2={r2:.4f})")
    print(f"implied alpha = 2 * slope = {alpha_fitted:.4f}   (vendor default: 0.35)")
    print(f"real |lineup_pct_diff| distribution: p95={diff_abs_p95:.4f}  max={diff_abs_max:.4f}")
    print(f"(vendor default faceoff_diff_clip=0.12 -- {'covers' if diff_abs_p95 <= 0.12 else 'is TIGHTER than'} "
          f"the real p95 spread)")

    result = {
        "n_games": n, "n_skipped": skipped_no_lineup_data,
        "intercept": round(intercept, 6), "slope": round(slope, 6), "r_squared": round(r2, 6),
        "alpha_fitted": round(alpha_fitted, 6), "alpha_vendor_default": 0.35,
        "diff_abs_p95": round(diff_abs_p95, 6), "diff_abs_max": round(diff_abs_max, 6),
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
