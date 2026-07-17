"""Backfill real-game performance records for SmartSim Production Monitoring Phase 1.

Joins, for each requested week: real completed-game actuals (historical truth
snapshot), real market lines (cached CFBD ``/lines`` responses), Enhanced
Totals Engine predictions (the enhanced schedule CSV), and SmartSim 2.0
projections (``smartsim2_projections_{season}_wk{week}.csv``) on normalized
(home, away) team names -- the same join methodology used in every prior
real-data backtest in this project (integration assessment, ensemble
evaluation, signal attribution, decision policy).

This script only reads existing artifacts and calls the unmodified
``smartsim2_performance_tracking`` recording API; it does not touch SmartSim
2.0, the Enhanced Totals Engine, or the blend.

Usage:
    python scripts/backfill_smartsim2_performance.py --season 2025 --weeks 1,5,8,10 \\
        --lines-dir /path/to/cached/cfbd_lines
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf.smartsim2_performance_tracking import (  # noqa: E402
    PERFORMANCE_LOG_PATH,
    build_game_performance_record,
    record_game_performance,
)
from syndicate.features.ncaaf.smartsim2_projection import read_projection_artifact  # noqa: E402
from syndicate.features.ncaaf.sources import default_ncaaf_source_root  # noqa: E402

NCAAF_SOURCE_ROOT = default_ncaaf_source_root()
DATA_ROOT = NCAAF_SOURCE_ROOT / "data"
TRUTH_PATH = NCAAF_SOURCE_ROOT / "historical_truth" / "games_2025.json.gz"
ENGINE_CSV_PATH = DATA_ROOT / "college_football_schedule_2025_predicted_totals_enhanced.csv"


def norm(name: str) -> str:
    text = (name or "").strip().lower()
    text = text.replace("state", "st").replace("&", "and")
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def load_truth_games(season: int, week: int) -> list[dict]:
    with gzip.open(TRUTH_PATH, "rt", encoding="utf-8") as handle:
        games = json.load(handle)
    return [
        g
        for g in games
        if g.get("season") == season
        and g.get("week") == week
        and g.get("seasonType") == "regular"
        and g.get("homeClassification") == "fbs"
        and g.get("awayClassification") == "fbs"
        and g.get("completed") is True
    ]


def load_market_lines(lines_dir: Path, week: int) -> dict[tuple[str, str], dict]:
    path = lines_dir / f"cfbd_lines_wk{week}.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        games = json.load(handle)
    index = {}
    for g in games:
        spreads = [line["spread"] for line in g.get("lines", []) if line.get("spread") is not None]
        totals = [line["overUnder"] for line in g.get("lines", []) if line.get("overUnder") is not None]
        market_margin = -statistics.mean(spreads) if spreads else None
        market_total = statistics.mean(totals) if totals else None
        key = (norm(g["homeTeam"]), norm(g["awayTeam"]))
        index[key] = {"market_margin": market_margin, "market_total": market_total}
    return index


def load_engine_predictions(season: int, week: int) -> dict[tuple[str, str], dict]:
    index = {}
    with ENGINE_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row["season"]) != season or int(row["week"]) != week:
                continue
            margin = row.get("predicted_win_margin", "")
            total = row.get("predicted_total_points", "")
            if margin in ("", None) or total in ("", None):
                continue
            key = (norm(row["home_team"]), norm(row["away_team"]))
            index[key] = {
                "engine_margin": float(margin),
                "engine_total": float(total),
                "conference_game": str(row.get("conference_game", "")).strip().lower() == "true",
            }
    return index


def load_smartsim_projections(season: int, week: int) -> dict[tuple[str, str], dict]:
    projections = read_projection_artifact(season=season, week=week, data_root=DATA_ROOT)
    return {
        (norm(p.home_team), norm(p.away_team)): {"smartsim_margin": p.margin_mean, "smartsim_total": p.total_mean}
        for p in projections
    }


def backfill_week(season: int, week: int, lines_dir: Path) -> dict[str, int]:
    truth_games = load_truth_games(season, week)
    lines_index = load_market_lines(lines_dir, week)
    engine_index = load_engine_predictions(season, week)
    smartsim_index = load_smartsim_projections(season, week)

    written = 0
    skipped_no_engine_or_smartsim = 0
    for game in truth_games:
        key = (norm(game["homeTeam"]), norm(game["awayTeam"]))
        engine = engine_index.get(key)
        smartsim = smartsim_index.get(key)
        if engine is None or smartsim is None:
            skipped_no_engine_or_smartsim += 1
            continue
        market = lines_index.get(key, {"market_margin": None, "market_total": None})
        record = build_game_performance_record(
            game_id=str(game["id"]),
            season=season,
            week=week,
            home_team=game["homeTeam"],
            away_team=game["awayTeam"],
            conference_game=bool(game.get("conferenceGame", engine["conference_game"])),
            market_margin=market["market_margin"],
            market_total=market["market_total"],
            engine_margin=engine["engine_margin"],
            engine_total=engine["engine_total"],
            smartsim_margin=smartsim["smartsim_margin"],
            smartsim_total=smartsim["smartsim_total"],
            actual_home_points=float(game["homePoints"]),
            actual_away_points=float(game["awayPoints"]),
        )
        record_game_performance(record)
        written += 1
    return {
        "truth_games": len(truth_games),
        "written": written,
        "skipped_no_engine_or_smartsim": skipped_no_engine_or_smartsim,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--weeks", type=str, required=True, help="Comma-separated week numbers, e.g. 1,5,8,10")
    parser.add_argument(
        "--lines-dir",
        type=Path,
        required=True,
        help="Directory containing cached cfbd_lines_wk{N}.json files",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete any existing performance log before backfilling (avoids duplicate records on rerun).",
    )
    args = parser.parse_args()

    if args.reset and PERFORMANCE_LOG_PATH.exists():
        PERFORMANCE_LOG_PATH.unlink()

    weeks = [int(w) for w in args.weeks.split(",") if w.strip()]
    totals = {"truth_games": 0, "written": 0, "skipped_no_engine_or_smartsim": 0}
    for week in weeks:
        result = backfill_week(args.season, week, args.lines_dir)
        print(f"week={week} {result}")
        for k in totals:
            totals[k] += result[k]
    print(f"TOTAL {totals}")
    print(f"log_path={PERFORMANCE_LOG_PATH}")


if __name__ == "__main__":
    main()
