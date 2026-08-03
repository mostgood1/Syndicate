"""Backfill real-game performance records for NFL's SmartSim 2.0 model.

Joins, for each requested week: real completed games + the real closing
line (schedule_{season}.csv, which carries both in one file -- unlike
NCAAF, which needs a separate historical-truth snapshot and a separate
cached CFBD lines file) against real SmartSim 2.0 NFL projections
(smartsim2_projections_{season}_wk{week}.csv). Joined by game_id, which
schedule.csv and the projections CSV already share exactly
(e.g. "2026_01_NE_SEA") -- no team-name normalization needed, unlike
NCAAF's fuzzy (home, away) string join.

This script only reads existing artifacts and calls the unmodified
syndicate.features.nfl.smartsim2_performance_tracking recording API; it
does not touch SmartSim 2.0 or the projection generator.

Usage:
    python scripts/backfill_nfl_performance.py --season 2025 --weeks 1,2,3
    python scripts/backfill_nfl_performance.py --season 2025 --weeks all
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.cards import nfl_projection_available_weeks  # noqa: E402
from syndicate.features.nfl.smartsim2_performance_tracking import (  # noqa: E402
    PERFORMANCE_LOG_PATH,
    build_game_performance_record,
    record_game_performance,
)
from syndicate.features.nfl.smartsim2_projection import read_projection_artifact  # noqa: E402
from syndicate.features.nfl.sources import default_nfl_source_root  # noqa: E402

NFL_SOURCE_ROOT = default_nfl_source_root()


def load_completed_games(season: int, week: int, *, source_root: Path = NFL_SOURCE_ROOT) -> dict[str, dict]:
    path = source_root / f"schedule_{season}.csv"
    if not path.exists():
        return {}
    index: dict[str, dict] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                if int(row["season"]) != season or int(row["week"]) != week:
                    continue
            except (TypeError, ValueError):
                continue
            away_score = str(row.get("away_score") or "").strip()
            home_score = str(row.get("home_score") or "").strip()
            if not away_score or not home_score:
                continue
            spread_line = str(row.get("spread_line") or "").strip()
            total_line = str(row.get("total_line") or "").strip()
            index[str(row["game_id"])] = {
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "away_score": float(away_score),
                "home_score": float(home_score),
                # spread_line is bet notation (home -10.5 = home favored by
                # 10.5), so market_margin (home_points - away_points, the
                # expected-outcome sense) is its negation -- same convention
                # nfl/cards.py's _nfl_market_board_rows_for_game already
                # documents and NCAAF's backfill uses (market_margin =
                # -mean(spreads)).
                "market_margin": -float(spread_line) if spread_line else None,
                "market_total": float(total_line) if total_line else None,
            }
    return index


def load_smartsim_projections(season: int, week: int, *, source_root: Path = NFL_SOURCE_ROOT) -> dict[str, dict]:
    projections = read_projection_artifact(season=season, week=week, data_root=source_root)
    return {p.game_id: {"model_margin": p.margin_mean, "model_total": p.total_mean} for p in projections}


def backfill_week(
    season: int,
    week: int,
    *,
    source_root: Path = NFL_SOURCE_ROOT,
    log_path: Path = PERFORMANCE_LOG_PATH,
) -> dict[str, int]:
    completed_games = load_completed_games(season, week, source_root=source_root)
    smartsim_index = load_smartsim_projections(season, week, source_root=source_root)

    written = 0
    skipped_no_projection = 0
    for game_id, game in completed_games.items():
        model = smartsim_index.get(game_id)
        if model is None:
            skipped_no_projection += 1
            continue
        record = build_game_performance_record(
            game_id=game_id,
            season=season,
            week=week,
            home_team=game["home_team"],
            away_team=game["away_team"],
            market_margin=game["market_margin"],
            market_total=game["market_total"],
            model_margin=model["model_margin"],
            model_total=model["model_total"],
            actual_home_points=game["home_score"],
            actual_away_points=game["away_score"],
        )
        record_game_performance(record, log_path=log_path)
        written += 1
    return {
        "completed_games": len(completed_games),
        "written": written,
        "skipped_no_projection": skipped_no_projection,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument(
        "--weeks",
        type=str,
        required=True,
        help="Comma-separated week numbers (e.g. 1,5,8,10), or 'all' to use every week with a stored projection artifact.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete any existing performance log before backfilling (avoids duplicate records on rerun).",
    )
    args = parser.parse_args()

    if args.reset and PERFORMANCE_LOG_PATH.exists():
        PERFORMANCE_LOG_PATH.unlink()

    if args.weeks.strip().lower() == "all":
        weeks = nfl_projection_available_weeks(args.season)
    else:
        weeks = [int(w) for w in args.weeks.split(",") if w.strip()]

    totals = {"completed_games": 0, "written": 0, "skipped_no_projection": 0}
    for week in weeks:
        result = backfill_week(args.season, week)
        print(f"week={week} {result}")
        for key in totals:
            totals[key] += result[key]
    print(f"TOTAL {totals}")
    print(f"log_path={PERFORMANCE_LOG_PATH}")


if __name__ == "__main__":
    main()
