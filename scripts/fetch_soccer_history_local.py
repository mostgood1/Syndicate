"""Fetch soccer team/league match history and player per-90 history locally.

Match history: football-data.co.uk season CSVs (big five + Eredivisie,
Primeira Liga, Championship, Belgian Pro League). Player history: Understat
league tables (big five), American Soccer Analysis (MLS), or ESPN
season-aggregated appearance rates (any other league with a
LEAGUE_ESPN_SLUGS entry -- see espn_player_stats.py for the appearance-
rate-vs-per-90 caveat).

Usage:
    python scripts/fetch_soccer_history_local.py --league epl --kind matches --seasons 2023,2024,2025
    python scripts/fetch_soccer_history_local.py --league epl --kind players --seasons 2025
    python scripts/fetch_soccer_history_local.py --league mls --kind players --seasons 2026
    python scripts/fetch_soccer_history_local.py --league eredivisie --kind players --espn-date-windows 20250801-20250831,20250901-20250930,...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.ingestion.espn_player_stats import aggregate_season_player_stats
from syndicate.features.soccer.ingestion.match_history import LEAGUE_HISTORY_CODES
from syndicate.features.soccer.ingestion.match_history import fetch_match_history_csv
from syndicate.features.soccer.ingestion.match_history import normalize_match_history
from syndicate.features.soccer.ingestion.player_history import UNDERSTAT_LEAGUES
from syndicate.features.soccer.ingestion.player_history import fetch_asa_mls_players
from syndicate.features.soccer.ingestion.player_history import fetch_understat_league_data
from syndicate.features.soccer.ingestion.player_history import fetch_understat_players
from syndicate.features.soccer.ingestion.player_history import normalize_asa_players
from syndicate.features.soccer.ingestion.player_history import normalize_understat_players
from syndicate.features.soccer.ingestion.player_history import normalize_understat_team_history


def _write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(frame.to_csv(index=False), encoding="utf-8")
    tmp.replace(out_path)
    print(f"Wrote {len(frame)} rows to {out_path}")


def fetch_matches(league: str, seasons: list[int], out_dir: Path) -> None:
    if league not in LEAGUE_HISTORY_CODES:
        raise SystemExit(f"match history not available for league '{league}' (supported: {sorted(LEAGUE_HISTORY_CODES)})")
    for season in seasons:
        csv_text = fetch_match_history_csv(league, season)
        rows = normalize_match_history(csv_text, league=league, season=season)
        _write_csv(rows, out_dir / f"matches_{season}.csv")


def fetch_players(league: str, seasons: list[int], out_dir: Path, *, espn_date_windows: list[str] | None = None) -> None:
    for season in seasons:
        if league == "mls":
            raw = fetch_asa_mls_players(season)
            rows = normalize_asa_players(raw, season=season)
        elif league in UNDERSTAT_LEAGUES:
            raw = fetch_understat_players(league, season)
            rows = normalize_understat_players(raw, league=league, season=season)
        elif espn_date_windows:
            rows = aggregate_season_player_stats(league, date_windows=espn_date_windows)
        else:
            raise SystemExit(
                f"player history not available for league '{league}' via Understat/ASA; "
                "pass --espn-date-windows to use ESPN's season-aggregated appearance rates instead"
            )
        _write_csv(rows, out_dir / f"players_{season}.csv")


def fetch_teams(league: str, seasons: list[int], out_dir: Path) -> None:
    if league not in UNDERSTAT_LEAGUES:
        raise SystemExit(f"team xG history not available for league '{league}' (supported: {sorted(UNDERSTAT_LEAGUES)})")
    for season in seasons:
        league_data = fetch_understat_league_data(league, season)
        rows = normalize_understat_team_history(league_data, league=league, season=season)
        _write_csv(rows, out_dir / f"teams_{season}.csv")


_KIND_DIRS = {"matches": "history", "players": "players", "teams": "team_history"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=str, required=True)
    parser.add_argument("--kind", type=str, choices=("matches", "players", "teams"), required=True)
    parser.add_argument("--seasons", type=str, required=True, help="Comma-separated season start years (e.g. 2024,2025)")
    parser.add_argument("--out-dir", type=str, default=None)
    parser.add_argument(
        "--espn-date-windows",
        type=str,
        default=None,
        help="Comma-separated YYYYMMDD-YYYYMMDD windows for --kind players on leagues without Understat/ASA coverage",
    )
    args = parser.parse_args()

    league = args.league.strip().lower()
    seasons = [int(season.strip()) for season in args.seasons.split(",") if season.strip()]
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "data" / "soccer_source" / league / _KIND_DIRS[args.kind]
    espn_date_windows = [w.strip() for w in args.espn_date_windows.split(",") if w.strip()] if args.espn_date_windows else None

    if args.kind == "matches":
        fetch_matches(league, seasons, out_dir)
    elif args.kind == "teams":
        fetch_teams(league, seasons, out_dir)
    else:
        fetch_players(league, seasons, out_dir, espn_date_windows=espn_date_windows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
