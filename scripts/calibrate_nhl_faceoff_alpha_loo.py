#!/usr/bin/env python3
"""Leave-one-out refit of `calibrate_nhl_faceoff_alpha.py` -- closes the one item that report's own
"What this does NOT do" section disclosed but did not fix: each player's `faceoff_weight` used
there was a SEASON-long average that includes the very game being predicted, not a true held-out
fit. That report judged the leakage small enough not to change the conclusion (a single game is a
small fraction of a 20-80+ game season sample) but never actually re-ran it to confirm.

METHODOLOGY. For EVERY game G, this excludes G's own faceoff win/loss counts from each dressed
player's rate before computing that game's lineup percentage -- a true per-game held-out fit, not
an approximation. Efficient by construction, not by re-aggregating per game (which would be
O(games^2)): the full-season win/total counts are accumulated ONCE, then each game's own
contribution is SUBTRACTED per player for that game's prediction only (`_LOO_INDEX`) -- O(games)
total, not O(games^2). Same `MIN_DRAWS_FOR_PLAYER_FACEOFF_WEIGHT` floor as the production
`compute_player_faceoff_aggregates`, just applied to each game's OWN held-out total rather than the
full-season total.

Usage:
  py -3 scripts/calibrate_nhl_faceoff_alpha_loo.py
  py -3 scripts/calibrate_nhl_faceoff_alpha_loo.py --json reports/phase7/nhl_faceoff_alpha_loo.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import (  # noqa: E402
    compute_lineup_faceoff_pct,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.player_game_rates import (  # noqa: E402
    MIN_DRAWS_FOR_PLAYER_FACEOFF_WEIGHT, parse_playbyplay_player_faceoffs,
)

from scripts.calibrate_nhl_faceoff_alpha import (  # noqa: E402
    _load_boxscores, _nhl_source_root, _ols_slope_and_r2, _skater_rows_with_real_toi,
)


def _load_regular_season_playbyplay_indexed(root: Path) -> Dict[str, Dict]:
    """`{game_id: payload}` for every regular-season `playbyplay` file -- keyed so a game's
    faceoff records can be looked up and subtracted by id, matching that same game's boxscore."""
    cache_dir = root / "data" / "ingestion_cache"
    files = sorted(glob.glob(str(cache_dir / "playbyplay_*.json")))
    out: Dict[str, Dict] = {}
    for p in files:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if int(data.get("gameType") or 0) != 2:
            continue
        gid = str(data.get("id") or "")
        if gid:
            out[gid] = data
    return out


def _team_sog(team_stats: Dict) -> int:
    total = 0
    for group in ("forwards", "defense"):
        for p in team_stats.get(group) or []:
            try:
                total += int(p.get("sog") or 0)
            except (TypeError, ValueError):
                continue
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    boxscores = _load_boxscores(root)
    playbyplay_by_id = _load_regular_season_playbyplay_indexed(root)
    if not boxscores or not playbyplay_by_id:
        print("REFUSED: need both boxscore and playbyplay caches", file=sys.stderr)
        return 1

    # Per-game faceoff records, keyed by game id -- also the exclusion unit.
    per_game_faceoffs: Dict[str, List] = {
        gid: parse_playbyplay_player_faceoffs(payload) for gid, payload in playbyplay_by_id.items()
    }

    # Full-season accumulation, ONCE.
    season_wins: Dict[int, int] = {}
    season_total: Dict[int, int] = {}
    for recs in per_game_faceoffs.values():
        for r in recs:
            if r.total <= 0:
                continue
            season_wins[r.player_id] = season_wins.get(r.player_id, 0) + r.wins
            season_total[r.player_id] = season_total.get(r.player_id, 0) + r.total

    n_boxscores_matched = 0
    diffs: List[float] = []
    shares: List[float] = []
    skipped = 0

    for box in boxscores:
        gid = str(box.get("id") or "")
        game_recs = per_game_faceoffs.get(gid)
        if game_recs is None:
            skipped += 1
            continue
        n_boxscores_matched += 1
        this_game_wins = {r.player_id: r.wins for r in game_recs}
        this_game_total = {r.player_id: r.total for r in game_recs}

        # Held-out rate map: subtract THIS game's own contribution from the season totals before
        # computing each player's rate -- O(1) per player, no re-aggregation over other games.
        loo_map: Dict[int, Dict[str, float]] = {}
        for pid, s_total in season_total.items():
            held_out_total = s_total - this_game_total.get(pid, 0)
            if held_out_total < MIN_DRAWS_FOR_PLAYER_FACEOFF_WEIGHT:
                continue
            held_out_wins = season_wins.get(pid, 0) - this_game_wins.get(pid, 0)
            loo_map[pid] = {"faceoff_weight": round(held_out_wins / held_out_total, 4)}

        pbg = box.get("playerByGameStats") or {}
        home_stats, away_stats = pbg.get("homeTeam") or {}, pbg.get("awayTeam") or {}
        home_rows = _skater_rows_with_real_toi(home_stats)
        away_rows = _skater_rows_with_real_toi(away_stats)
        home_pct = compute_lineup_faceoff_pct(home_rows, loo_map)
        away_pct = compute_lineup_faceoff_pct(away_rows, loo_map)
        if home_pct is None or away_pct is None:
            skipped += 1
            continue

        home_sog, away_sog = _team_sog(home_stats), _team_sog(away_stats)
        if home_sog + away_sog <= 0:
            skipped += 1
            continue

        diffs.append(home_pct - away_pct)
        shares.append(home_sog / (home_sog + away_sog))

    n = len(diffs)
    print(f"boxscores: {len(boxscores)}  matched to a playbyplay game id: {n_boxscores_matched}  "
          f"usable (real held-out lineup pct on both sides): {n}  skipped: {skipped}")
    if n < 30:
        print("REFUSED: fewer than 30 usable games", file=sys.stderr)
        return 1

    intercept, slope, r2 = _ols_slope_and_r2(diffs, shares)
    alpha_fitted = 2.0 * slope
    print(f"\nLEAVE-ONE-OUT OLS fit: shot_share = {intercept:.4f} + {slope:.4f} * lineup_pct_diff   "
          f"(R^2={r2:.4f})")
    print(f"implied alpha (leave-one-out) = {alpha_fitted:.4f}   (vendor default: 0.35, "
          f"in-sample fit from calibrate_nhl_faceoff_alpha.py: 0.2171)")

    result = {
        "n_games": n, "n_skipped": skipped,
        "intercept": round(intercept, 6), "slope": round(slope, 6), "r_squared": round(r2, 6),
        "alpha_fitted_loo": round(alpha_fitted, 6),
        "alpha_fitted_in_sample": 0.2171, "alpha_vendor_default": 0.35,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
