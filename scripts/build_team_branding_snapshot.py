"""Build the team-branding snapshot (logo URL + hex colors) for one or all sports.

Fetches ESPN's public, unauthenticated site API and writes
``{sport}_source/source_artifacts/data/processed/team_branding/{sport}_team_branding.csv``
for each requested sport, using each sport's own existing source-root
resolution convention (``SYNDICATE_{SPORT}_SOURCE_ROOT`` env var, falling
back to ``data/{sport}_source`` -- the same convention every other snapshot
in this project already uses).

This script does not modify SmartSim, any calibration profile, or any
sport's card-rendering logic; it only produces a data snapshot that
``cards.py`` in each sport reads separately.

Usage:
    python scripts/build_team_branding_snapshot.py --sport ncaaf
    python scripts/build_team_branding_snapshot.py --all
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.source_roots import preferred_source_roots  # noqa: E402
from syndicate.features.shared.team_branding import fetch_espn_teams  # noqa: E402
from syndicate.features.shared.team_branding import write_team_branding_snapshot  # noqa: E402

# preferred_source_roots() derives the repo root as Path(file_path).resolve().parents[3],
# matching where every sport's own sources.py module lives (syndicate/features/{sport}/sources.py,
# 4 levels deep: sources.py -> {sport} -> features -> syndicate -> repo root). This script lives
# directly under scripts/ (1 level deep), so it must pass a synthetic path at that same 4-deep
# shape rather than its own __file__ -- the probe path needs a stand-in "{sport}" directory
# segment too, or parents[3] overshoots one directory above the repo root (verified: without the
# extra segment this silently wrote every branding snapshot outside the repo entirely).
_REPO_ROOT_PROBE_PATH = REPO_ROOT / "syndicate" / "features" / "_probe" / "_team_branding_probe.py"

# (espn_sport_path, env_var, local_dir_name) -- env_var/local_dir_name match
# each sport's own sources.py exactly (preferred_source_roots callers).
SPORT_CONFIG: dict[str, tuple[str, str, str]] = {
    "nfl": ("football/nfl", "SYNDICATE_NFL_SOURCE_ROOT", "nfl_source"),
    "ncaaf": ("football/college-football", "SYNDICATE_NCAAF_SOURCE_ROOT", "ncaaf_source"),
    "nba": ("basketball/nba", "SYNDICATE_NBA_SOURCE_ROOT", "nba_source"),
    "ncaab": ("basketball/mens-college-basketball", "SYNDICATE_NCAAB_SOURCE_ROOT", "ncaab_source"),
    "mlb": ("baseball/mlb", "SYNDICATE_MLB_SOURCE_ROOT", "mlb_source"),
    "nhl": ("hockey/nhl", "SYNDICATE_NHL_SOURCE_ROOT", "nhl_source"),
    "wnba": ("basketball/wnba", "SYNDICATE_WNBA_SOURCE_ROOT", "wnba_source"),
}

# Soccer is multi-league (one ESPN slug per domestic league, not one per
# sport), so each league gets its own SPORT_CONFIG entry keyed by the same
# league slug `syndicate/features/soccer/sources.py` already uses --
# `local_dir_name` nests under the shared `soccer_source` root the same way
# every other soccer artifact (schedule/rosters/recommendations) already
# does, just under `source_artifacts/` per this script's own convention
# rather than soccer's own `/api/` tree.
SPORT_CONFIG.update(
    {
        "epl": ("soccer/eng.1", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/epl"),
        "la_liga": ("soccer/esp.1", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/la_liga"),
        "bundesliga": ("soccer/ger.1", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/bundesliga"),
        "serie_a": ("soccer/ita.1", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/serie_a"),
        "ligue_1": ("soccer/fra.1", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/ligue_1"),
        "mls": ("soccer/usa.1", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/mls"),
        "eredivisie": ("soccer/ned.1", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/eredivisie"),
        "primeira_liga": ("soccer/por.1", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/primeira_liga"),
        "championship": ("soccer/eng.2", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/championship"),
        "belgian_pro_league": ("soccer/bel.1", "SYNDICATE_SOCCER_SOURCE_ROOT", "soccer_source/belgian_pro_league"),
    }
)


def branding_snapshot_path(sport: str) -> Path:
    _espn_path, env_var, local_dir_name = SPORT_CONFIG[sport]
    root = preferred_source_roots(_REPO_ROOT_PROBE_PATH, env_var=env_var, local_dir_name=local_dir_name)[0]
    return root / "source_artifacts" / "data" / "processed" / "team_branding" / f"{sport}_team_branding.csv"


def build_snapshot(sport: str) -> dict[str, object]:
    espn_path, _env_var, _local_dir_name = SPORT_CONFIG[sport]
    snapshot_date = time.strftime("%Y-%m-%d", time.gmtime())
    rows = fetch_espn_teams(espn_path, snapshot_date=snapshot_date)
    path = write_team_branding_snapshot(rows, path=branding_snapshot_path(sport))
    return {"sport": sport, "teams_written": len(rows), "path": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sport", choices=sorted(SPORT_CONFIG), help="Build the snapshot for one sport.")
    group.add_argument("--all", action="store_true", help="Build snapshots for every configured sport.")
    args = parser.parse_args()

    sports = sorted(SPORT_CONFIG) if args.all else [args.sport]
    for sport in sports:
        result = build_snapshot(sport)
        print(result)


if __name__ == "__main__":
    main()
