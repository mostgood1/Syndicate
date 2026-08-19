#!/usr/bin/env python3
"""Producer: real finished-game results -> `team_special_teams_{season}.csv` / `_latest.csv`.

Closes the `HockeyTeamFeatures.special_teams` gap documented in
`docs/ai_context/hockeysim_engine_reference.md`: `pp_pct`/`pk_pct`/`committed_per_game` are
CONSUMED by `engine.py` (via `st_home`/`st_away`, NOT the separate `special_teams_cal` parameter --
see the reference doc for that distinction) and had no producer anywhere. This script is that
producer, using the same real, cached truth data (1,312 games) the Phase-3 baseline and the Elo
producer already read.

`docs/ai_context/hockeysim_engine_reference.md` §2f: ALSO writes `pp_shot_index`/
`pk_shot_index_allowed` when a `boxscore` cache is present (`scripts/fetch_nhl_boxscore_cache.py`)
-- real per-team shot-GENERATION intensity, normalized by PP/PK opportunity count, distinct from
`pp_pct`/`pk_pct` (which differentiate GOAL conversion, not shot volume). Degrades gracefully to
the neutral default (1.0) when no boxscore cache exists, same "never break" discipline as every
other loader in this package -- the two extra columns are additive, not a second artifact.

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
from typing import Dict

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import season_code_for_date  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_shot_strength import (  # noqa: E402
    DEFAULT_SHOT_INDEX,
    compute_team_shot_rate_index,
    parse_boxscore_shot_strength,
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


def _load_shot_rate_index(root: Path) -> Dict[str, "object"]:
    """Best-effort: compute the shot-rate index from a local `boxscore` cache. Returns `{}` (a
    signal to fall back to the neutral default everywhere) if no cache exists -- this producer
    must still write a usable `pp_pct`/`pk_pct`/`committed_per_game` artifact even when nobody has
    run `fetch_nhl_boxscore_cache.py` yet."""
    cache_dir = root / "data" / "ingestion_cache"
    files = sorted(glob.glob(str(cache_dir / "boxscore_*.json")))
    if not files:
        print(f"  (no boxscore cache under {cache_dir} -- pp_shot_index/pk_shot_index_allowed "
              f"will be neutral. Run scripts/fetch_nhl_boxscore_cache.py to populate them.)")
        return {}
    shot_recs = []
    for p in files:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if int(data.get("gameType") or 0) != 2:
            continue
        rec = parse_boxscore_shot_strength(data)
        if rec is not None:
            shot_recs.append(rec)
    return shot_recs


def _write_csv(path: Path, rates: dict, shot_idx: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rates.items())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["abbr", "pp_pct", "pk_pct", "committed_per_game", "pp_shot_index",
                    "pk_shot_index_allowed", "games", "pp_opportunities", "pp_goals",
                    "pk_opportunities", "pp_goals_against"])
        for abbr, r in rows:
            idx = shot_idx.get(abbr)
            pp_shot_index = idx.pp_shot_index if idx is not None else DEFAULT_SHOT_INDEX
            pk_shot_index = idx.pk_shot_index_allowed if idx is not None else DEFAULT_SHOT_INDEX
            w.writerow([abbr, r.pp_pct, r.pk_pct, r.committed_per_game, pp_shot_index,
                        pk_shot_index, r.games, r.pp_opportunities, r.pp_goals,
                        r.pk_opportunities, r.pp_goals_against])
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

    shot_recs = _load_shot_rate_index(root)
    shot_idx: dict = {}
    if shot_recs:
        pp_opp = {t: r.pp_opportunities for t, r in rates.items()}
        pk_opp = {t: r.pk_opportunities for t, r in rates.items()}
        shot_idx = compute_team_shot_rate_index(shot_recs, pp_opp, pk_opp)
        print(f"  shot-rate index: {len(shot_recs)} boxscore games, {len(shot_idx)} teams")

    out_dir = root / "data" / "processed"
    written = []
    if season:
        p = out_dir / f"team_special_teams_{season}.csv"
        written.append((p, _write_csv(p, rates, shot_idx)))
    p_latest = out_dir / "team_special_teams_latest.csv"
    written.append((p_latest, _write_csv(p_latest, rates, shot_idx)))

    league_pp = sum(r.pp_goals for r in rates.values()) / max(1, sum(r.pp_opportunities for r in rates.values()))
    print(f"games: {len(regular)} regular-season ({dates[0] if dates else '?'}..{dates[-1] if dates else '?'})")
    print(f"teams rated: {len(rates)}   league avg PP% = {league_pp:.1%}")
    for path, n in written:
        print(f"wrote {path} ({n} teams)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
