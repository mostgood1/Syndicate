#!/usr/bin/env python3
"""Producer: real boxscore + play-by-play data -> `team_rates_{season}.csv`.

Closes 2 of the (originally 4) team-level `HockeyTeamFeatures` fields `docs/ai_context/
hockeysim_engine_reference.md` §5 flagged as genuinely absent: `shots_per_60`, `faceoff_win_pct`
(`player_props.py`'s `TeamRates` construction reads these as flat per-team constants; ALL 32 teams
were reading the SAME hardcoded `HockeyTeamFeatures` dataclass default unconditionally, every game).

`blocks_per_60` and `penalties_per_60` are DELIBERATELY NOT produced here (§2l). Both were built in
an earlier pass of this script and then REMOVED from `HockeyTeamFeatures`/`TeamRates` entirely once
proven a confirmed dead gate -- `engine.py` never read either field once populated. Block volume is
already fully governed by the truth-calibrated per-shot `block_rate_*` mechanism
(`historical_truth/boxscore_block_rate.py`, §2g, still alive and consumed); penalty rate already
drives PP/PK segment generation via `special_teams`'s `committed_per_game`
(`historical_truth/special_teams_builder.py`, already written to `team_special_teams_{season}.csv`
and already read by `loaders.load_team_special_teams_map`). A parallel flat per-game-rate input for
either would have been a pure duplicate of already-live real data.

Uses the SAME boxscore + play-by-play caches §2e/§2g/§2i already bulk-fetched (no new fetch).

Usage:
  py -3 scripts/build_nhl_team_rates_artifact.py
  py -3 scripts/build_nhl_team_rates_artifact.py --season 2025-2026
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import season_code_for_date  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import (  # noqa: E402
    NhlStatsWebTruthLoader,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.team_game_rates import (  # noqa: E402
    build_game_team_rates, compute_team_rate_aggregates,
)


def _nhl_source_root() -> Path:
    import os
    env = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    return REPO / "data" / "nhl_source"


def _load_cached_json(root: Path, prefix: str, game_ids: List[str]) -> Dict[str, Dict]:
    cache_dir = root / "data" / "ingestion_cache"
    out: Dict[str, Dict] = {}
    for gid in game_ids:
        p = cache_dir / f"{prefix}_{gid}.json"
        if not p.exists():
            continue
        try:
            out[gid] = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _write_csv(path: Path, aggregates: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(aggregates.items())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["abbr", "shots_per_60", "faceoff_win_pct", "games", "faceoffs"])
        for abbr, agg in rows:
            w.writerow([abbr, agg.shots_per_60, agg.faceoff_win_pct, agg.games, agg.faceoffs])
    return len(rows)


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

    boxscores_by_id = _load_cached_json(root, "boxscore", game_ids)
    playbyplay_by_id = _load_cached_json(root, "playbyplay", game_ids)
    if not boxscores_by_id or not playbyplay_by_id:
        print(f"REFUSED: missing boxscore or play-by-play cache under {root}/data/ingestion_cache "
              f"-- run scripts/fetch_nhl_boxscore_cache.py and scripts/fetch_nhl_playbyplay_cache.py "
              f"first", file=sys.stderr)
        return 1
    print(f"loaded {len(boxscores_by_id)} boxscores, {len(playbyplay_by_id)} play-by-play payloads "
          f"({len(game_ids)} truth game ids)")

    game_rates = build_game_team_rates(list(boxscores_by_id.values()), playbyplay_by_id)
    print(f"joined {len(game_rates)}/{len(game_ids)} games (both sources present + faceoff data parsed)")

    aggregates = compute_team_rate_aggregates(list(game_rates.values()))
    league_sog = sum(a.shots_per_60 for a in aggregates.values()) / max(1, len(aggregates))
    league_fo = sum(a.faceoff_win_pct for a in aggregates.values()) / max(1, len(aggregates))
    print(f"teams rated: {len(aggregates)}  league avg shots/60={league_sog:.2f}  "
          f"league avg faceoff_win_pct={league_fo:.4f}")
    print("(sanity check: faceoff_win_pct should average close to 0.5 by construction -- every "
          "faceoff has exactly one winner and one loser league-wide)")

    out_dir = root / "data" / "processed"
    written = []
    if season:
        p = out_dir / f"team_rates_{season}.csv"
        written.append((p, _write_csv(p, aggregates)))
    p_latest = out_dir / "team_rates_latest.csv"
    written.append((p_latest, _write_csv(p_latest, aggregates)))
    for path, n in written:
        print(f"wrote {path} ({n} teams)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
