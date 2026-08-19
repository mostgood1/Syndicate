#!/usr/bin/env python3
"""Producer: real boxscore + playbyplay per-player stats -> `player_rates_{season}.csv`.

Closes the last 3 genuinely-absent `HockeyPlayerFeatures` fields
`docs/ai_context/hockeysim_engine_reference.md` §5 tracked: `shot_weight`/`goal_weight`/
`block_weight`. UNLIKE the team-rates dead gate (§2j), these three are ALREADY reachable --
`engine.py`'s `_weighted_choice` reads them to decide which on-ice skater gets credited for a
shot/goal/block, with a documented position/TOI heuristic fallback when absent. This producer
replaces that heuristic with real, individually differentiated per-player data where available.

Uses the SAME `boxscore` cache §2e/§2g/§2j already bulk-fetched (no new fetch) --
`playerByGameStats.{home,away}Team.{forwards,defense}[]` already carries `sog`/`goals`/
`blockedShots` per skater per game.

§2zz: ALSO writes `faceoff_weight` from the SAME `playbyplay` cache the zone/role/joint faceoff
work already bulk-fetched -- the FIRST player-level dimension the faceoff mechanism has ever had.
NOT sourced from the boxscore (unlike the three fields above) -- see
`historical_truth/player_game_rates.py`'s own docstring for the real, measured artifact (22% of
per-game `faceoffWinningPctg` values are an exact 0.0/1.0, almost always a low-draw game) that
made a naive boxscore-average approach unusable, and why TRUE win/total counts from `playbyplay`
are used instead.

Usage:
  py -3 scripts/build_nhl_player_rates_artifact.py
  py -3 scripts/build_nhl_player_rates_artifact.py --season 2025-2026
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import season_code_for_date  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import (  # noqa: E402
    NhlStatsWebTruthLoader,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.player_game_rates import (  # noqa: E402
    MIN_GAMES_FOR_PLAYER_WEIGHT, build_player_game_dataset, compute_player_faceoff_aggregates,
    compute_player_rate_aggregates, parse_playbyplay_player_faceoffs, parse_playbyplay_roster_names,
)


def _nhl_source_root() -> Path:
    import os
    env = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    return REPO / "data" / "nhl_source"


def _load_boxscores(root: Path, game_ids: List[str]) -> List[dict]:
    cache_dir = root / "data" / "ingestion_cache"
    out = []
    for gid in game_ids:
        p = cache_dir / f"boxscore_{gid}.json"
        if not p.exists():
            continue
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _load_playbyplay(root: Path, game_ids: List[str]) -> List[dict]:
    cache_dir = root / "data" / "ingestion_cache"
    out = []
    for gid in game_ids:
        p = cache_dir / f"playbyplay_{gid}.json"
        if not p.exists():
            continue
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _write_csv(path: Path, aggregates: dict, faceoff_aggregates: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    all_ids = sorted(set(aggregates.keys()) | set(faceoff_aggregates.keys()))
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["player_id", "full_name", "position", "shot_weight", "goal_weight",
                    "block_weight", "games", "faceoff_weight", "faceoff_draws", "faceoff_games"])
        for pid in all_ids:
            agg = aggregates.get(pid)
            fagg = faceoff_aggregates.get(pid)
            full_name = agg.full_name if agg else (fagg.full_name if fagg else "")
            position = agg.position if agg else (fagg.position if fagg else "")
            w.writerow([
                pid, full_name, position,
                agg.shot_weight if agg else "", agg.goal_weight if agg else "",
                agg.block_weight if agg else "", agg.games if agg else "",
                fagg.faceoff_weight if fagg else "", fagg.draws if fagg else "",
                fagg.games if fagg else "",
            ])
    return len(all_ids)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", default=None)
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    truth_loader = NhlStatsWebTruthLoader(offline=True)
    truth_games = truth_loader.load_from_cache()
    regular = [g for g in truth_games if int(g.game_type) == 2]
    if not regular:
        print("REFUSED: no cached regular-season truth games", file=sys.stderr)
        return 1
    game_ids = sorted({g.game_id for g in regular})
    dates = sorted({g.date[:10] for g in regular if g.date})
    season = args.season or (season_code_for_date(dates[-1]) if dates else "")

    boxscores = _load_boxscores(root, game_ids)
    if not boxscores:
        print(f"REFUSED: no boxscore cache under {root}/data/ingestion_cache -- run "
              f"scripts/fetch_nhl_boxscore_cache.py first", file=sys.stderr)
        return 1
    print(f"loaded {len(boxscores)}/{len(game_ids)} boxscores")

    records = build_player_game_dataset(boxscores)
    print(f"parsed {len(records)} skater-game records")

    aggregates = compute_player_rate_aggregates(records)
    print(f"players rated (>= {MIN_GAMES_FOR_PLAYER_WEIGHT} games): {len(aggregates)}")

    top = sorted(aggregates.values(), key=lambda a: -a.shot_weight)[:5]
    print("top-5 shot_weight (sanity check against known elite scorers):")
    for a in top:
        print(f"  {a.full_name:20s} pos={a.position} games={a.games:3d} "
              f"shot_weight={a.shot_weight:.4f} goal_weight={a.goal_weight:.4f} "
              f"block_weight={a.block_weight:.4f}")

    playbyplay = _load_playbyplay(root, game_ids)
    faceoff_aggregates: dict = {}
    if playbyplay:
        per_game_records = [parse_playbyplay_player_faceoffs(g) for g in playbyplay]
        per_game_names = [parse_playbyplay_roster_names(g) for g in playbyplay]
        faceoff_aggregates = compute_player_faceoff_aggregates(per_game_records, per_game_names)
        print(f"  faceoff_weight (§2zz): {len(playbyplay)} playbyplay games, "
              f"{len(faceoff_aggregates)} players rated")
        ftop = sorted(faceoff_aggregates.values(), key=lambda a: -a.faceoff_weight)[:5]
        print("  top-5 faceoff_weight (sanity check against known real faceoff specialists):")
        for a in ftop:
            print(f"    {a.full_name:20s} pos={a.position} games={a.games:3d} draws={a.draws:4d} "
                  f"faceoff_weight={a.faceoff_weight:.4f}")
    else:
        print(f"  (no playbyplay cache under {root / 'data' / 'ingestion_cache'} -- "
              f"faceoff_weight will be absent. Run scripts/fetch_nhl_playbyplay_cache.py to "
              f"populate it.)")

    out_dir = root / "data" / "processed"
    written = []
    if season:
        p = out_dir / f"player_rates_{season}.csv"
        written.append((p, _write_csv(p, aggregates, faceoff_aggregates)))
    p_latest = out_dir / "player_rates_latest.csv"
    written.append((p_latest, _write_csv(p_latest, aggregates, faceoff_aggregates)))
    for path, n in written:
        print(f"wrote {path} ({n} players)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
