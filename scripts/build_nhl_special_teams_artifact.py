#!/usr/bin/env python3
"""Producer: real finished-game results -> `team_special_teams_{season}.csv` / `_latest.csv`.

Closes the `HockeyTeamFeatures.special_teams` gap documented in
`docs/ai_context/hockeysim_engine_reference.md`: `pp_pct`/`pk_pct`/`committed_per_game` are
CONSUMED by `engine.py` (via `st_home`/`st_away`, NOT the separate `special_teams_cal` parameter --
see the reference doc for that distinction) and had no producer anywhere. This script is that
producer, using the same real, cached truth data (1,312 games) the Phase-3 baseline and the Elo
producer already read.

`docs/ai_context/hockeysim_engine_reference.md` §2f/§2g: ALSO writes `pp_shot_index`/
`pk_shot_index_allowed`/`block_rate_index` when a `boxscore` cache is present
(`scripts/fetch_nhl_boxscore_cache.py`) -- real per-team shot-GENERATION intensity (distinct from
`pp_pct`/`pk_pct`, which differentiate GOAL conversion) and blocked-shot tendency (distinct from
either -- and never checked against a real rate at all before §2g). Degrades gracefully to the
neutral default (1.0) when no boxscore cache exists, same "never break" discipline as every other
loader in this package -- the extra columns are additive, not a second artifact.

§2m: ALSO writes `faceoff_ev_index` when a `playbyplay` cache is present
(`scripts/fetch_nhl_playbyplay_cache.py`) -- closes a real mismatch between `engine.py`'s
`faceoff_ev_only=True` gate and the all-situations `faceoff_win_pct` blend it was fed (see
`historical_truth/faceoff_ev_index.py`'s own docstring). Same graceful-degrade discipline.

§2n: ALSO writes `faceoff_oz_index` from the SAME `playbyplay` cache -- an offensive-zone-specific
refinement of `faceoff_ev_index` (not every faceoff win is equally valuable for shot generation;
an OZ win matters more than a DZ win). `engine.py` prefers this over the flat EV index when both
are present.

Usage:
  py -3 scripts/build_nhl_special_teams_artifact.py
  py -3 scripts/build_nhl_special_teams_artifact.py --season 2025-2026 --fetch
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
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_block_rate import (  # noqa: E402
    DEFAULT_BLOCK_INDEX,
    compute_team_block_rate_index,
    parse_boxscore_block_rate,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_shot_strength import (  # noqa: E402
    DEFAULT_SHOT_INDEX,
    compute_team_shot_rate_index,
    parse_boxscore_shot_strength,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_ev_index import (  # noqa: E402
    DEFAULT_FACEOFF_EV_INDEX,
    DEFAULT_FACEOFF_OZ_INDEX,
    compute_team_faceoff_ev_index,
    compute_team_faceoff_oz_index,
    parse_playbyplay_faceoffs_by_zone,
    parse_playbyplay_faceoffs_ev,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import (  # noqa: E402
    NhlStatsWebTruthLoader,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.special_teams_builder import (  # noqa: E402
    compute_special_teams_rates,
)


def _nhl_source_root() -> Path:
    import os
    env = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    return REPO / "data" / "nhl_source"


def _load_regular_season_boxscores(root: Path) -> List[Dict]:
    """One read pass over the `boxscore` cache, shared by both the shot-index and block-index
    computations below (each parses the SAME payload differently) -- avoids reading 1,300+ files
    twice. Returns `[]` (a signal to fall back to neutral everywhere) if no cache exists."""
    cache_dir = root / "data" / "ingestion_cache"
    files = sorted(glob.glob(str(cache_dir / "boxscore_*.json")))
    if not files:
        print(f"  (no boxscore cache under {cache_dir} -- pp_shot_index/pk_shot_index_allowed/"
              f"block_rate_index will be neutral. Run scripts/fetch_nhl_boxscore_cache.py to "
              f"populate them.)")
        return []
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


def _load_regular_season_playbyplay(root: Path) -> List[Dict]:
    """One read pass over the `playbyplay` cache (same substrate the xG model already
    bulk-fetched -- no new fetch needed here). Returns `[]` (neutral fallback) if absent."""
    cache_dir = root / "data" / "ingestion_cache"
    files = sorted(glob.glob(str(cache_dir / "playbyplay_*.json")))
    if not files:
        print(f"  (no playbyplay cache under {cache_dir} -- faceoff_ev_index will be neutral. "
              f"Run scripts/fetch_nhl_playbyplay_cache.py to populate it.)")
        return []
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


def _write_csv(path: Path, rates: dict, shot_idx: dict, block_idx: dict, faceoff_idx: dict,
                faceoff_oz_idx: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rates.items())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["abbr", "pp_pct", "pk_pct", "committed_per_game", "pp_shot_index",
                    "pk_shot_index_allowed", "block_rate_index", "faceoff_ev_index",
                    "faceoff_oz_index", "games", "pp_opportunities", "pp_goals",
                    "pk_opportunities", "pp_goals_against"])
        for abbr, r in rows:
            sidx = shot_idx.get(abbr)
            pp_shot_index = sidx.pp_shot_index if sidx is not None else DEFAULT_SHOT_INDEX
            pk_shot_index = sidx.pk_shot_index_allowed if sidx is not None else DEFAULT_SHOT_INDEX
            bidx = block_idx.get(abbr)
            block_rate_index = bidx.block_index if bidx is not None else DEFAULT_BLOCK_INDEX
            fidx = faceoff_idx.get(abbr)
            faceoff_ev_index = fidx.index if fidx is not None else DEFAULT_FACEOFF_EV_INDEX
            fozidx = faceoff_oz_idx.get(abbr)
            faceoff_oz_index = fozidx.index if fozidx is not None else DEFAULT_FACEOFF_OZ_INDEX
            w.writerow([abbr, r.pp_pct, r.pk_pct, r.committed_per_game, pp_shot_index,
                        pk_shot_index, block_rate_index, faceoff_ev_index, faceoff_oz_index,
                        r.games, r.pp_opportunities, r.pp_goals, r.pk_opportunities,
                        r.pp_goals_against])
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", default=None)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    loader = NhlStatsWebTruthLoader(offline=not args.fetch)
    games = loader.load_from_cache()
    if not games:
        print(f"REFUSED: no cached truth games under {loader.cache_dir}", file=sys.stderr)
        return 1
    regular = [g for g in games if int(g.game_type) == 2]
    if not regular:
        print("REFUSED: cache has games but none are regular-season (game_type==2)", file=sys.stderr)
        return 1

    rates = compute_special_teams_rates(regular)
    dates = sorted({g.date[:10] for g in regular if g.date})
    season = args.season or (season_code_for_date(dates[-1]) if dates else "")

    boxscores = _load_regular_season_boxscores(root)
    shot_idx: dict = {}
    block_idx: dict = {}
    if boxscores:
        shot_recs = [r for d in boxscores if (r := parse_boxscore_shot_strength(d)) is not None]
        block_recs = [r for d in boxscores if (r := parse_boxscore_block_rate(d)) is not None]
        if shot_recs:
            pp_opp = {t: r.pp_opportunities for t, r in rates.items()}
            pk_opp = {t: r.pk_opportunities for t, r in rates.items()}
            shot_idx = compute_team_shot_rate_index(shot_recs, pp_opp, pk_opp)
            print(f"  shot-rate index: {len(shot_recs)} boxscore games, {len(shot_idx)} teams")
        if block_recs:
            block_idx = compute_team_block_rate_index(block_recs)
            print(f"  block-rate index: {len(block_recs)} boxscore games, {len(block_idx)} teams")

    playbyplay = _load_regular_season_playbyplay(root)
    faceoff_idx: dict = {}
    faceoff_oz_idx: dict = {}
    if playbyplay:
        fo_recs = [r for d in playbyplay if (r := parse_playbyplay_faceoffs_ev(d)) is not None]
        if fo_recs:
            faceoff_idx = compute_team_faceoff_ev_index(fo_recs)
            print(f"  faceoff-EV index: {len(fo_recs)} playbyplay games, {len(faceoff_idx)} teams")
        fo_zone_recs = [r for d in playbyplay if (r := parse_playbyplay_faceoffs_by_zone(d)) is not None]
        if fo_zone_recs:
            faceoff_oz_idx = compute_team_faceoff_oz_index(fo_zone_recs)
            print(f"  faceoff-OZ index: {len(fo_zone_recs)} playbyplay games, {len(faceoff_oz_idx)} teams")

    out_dir = root / "data" / "processed"
    written = []
    if season:
        p = out_dir / f"team_special_teams_{season}.csv"
        written.append((p, _write_csv(p, rates, shot_idx, block_idx, faceoff_idx, faceoff_oz_idx)))
    p_latest = out_dir / "team_special_teams_latest.csv"
    written.append((p_latest, _write_csv(p_latest, rates, shot_idx, block_idx, faceoff_idx, faceoff_oz_idx)))

    league_pp = sum(r.pp_goals for r in rates.values()) / max(1, sum(r.pp_opportunities for r in rates.values()))
    print(f"games: {len(regular)} regular-season ({dates[0] if dates else '?'}..{dates[-1] if dates else '?'})")
    print(f"teams rated: {len(rates)}   league avg PP% = {league_pp:.1%}")
    for path, n in written:
        print(f"wrote {path} ({n} teams)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
