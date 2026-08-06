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

``--season-kind preseason`` (added 2026-08-05) switches every input to its
real preseason analog: schedule_preseason_{season}.csv instead of
schedule_{season}.csv, read_preseason_projection_artifact() instead of
read_projection_artifact(), and PRESEASON_PERFORMANCE_LOG_PATH instead of
PERFORMANCE_LOG_PATH -- a fully separate log, never mixed with real
regular-season records. Unlike the regular season, ESPN's preseason
schedule (schedule_preseason_{season}.csv) carries no market line columns
at all, so preseason market_margin/market_total instead come from the
dated odds snapshot written by
scripts/fetch_nfl_preseason_odds.py::write_preseason_odds_snapshot -- the
only durable source, since preseason_odds_{season}.csv itself is fully
overwritten on every refresh and will not still contain a played game's
line by the time this backfill runs.

Usage:
    python scripts/backfill_nfl_performance.py --season 2025 --weeks 1,2,3
    python scripts/backfill_nfl_performance.py --season 2025 --weeks all
    python scripts/backfill_nfl_performance.py --season 2026 --weeks all --season-kind preseason
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.cards import nfl_projection_available_weeks  # noqa: E402
from syndicate.features.nfl.preseason_projection import preseason_seasons_and_weeks  # noqa: E402
from syndicate.features.nfl.preseason_projection import read_preseason_projection_artifact  # noqa: E402
from syndicate.features.nfl.smartsim2_performance_tracking import (  # noqa: E402
    PERFORMANCE_LOG_PATH,
    PRESEASON_PERFORMANCE_LOG_PATH,
    build_game_performance_record,
    record_game_performance,
)
from syndicate.features.nfl.smartsim2_projection import read_projection_artifact  # noqa: E402
from syndicate.features.nfl.sources import default_nfl_source_root  # noqa: E402

NFL_SOURCE_ROOT = default_nfl_source_root()

_SNAPSHOT_FILENAME_RE = re.compile(r"^preseason_odds_snapshot_(?P<season>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})\.csv$")


def load_completed_games(
    season: int,
    week: int,
    *,
    source_root: Path = NFL_SOURCE_ROOT,
    season_kind: str = "regular",
) -> dict[str, dict]:
    if season_kind == "preseason":
        return _load_completed_preseason_games(season, week, source_root=source_root)
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


def _parse_gameday(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _load_completed_preseason_games(season: int, week: int, *, source_root: Path) -> dict[str, dict]:
    """Preseason analog of load_completed_games -- reads
    schedule_preseason_{season}.csv (ESPN-sourced, see
    scripts/fetch_nfl_preseason_schedule.py) instead of the nflverse-backed
    schedule_{season}.csv. That schedule carries no spread_line/total_line
    columns at all (ESPN's scoreboard API has no market data), so
    market_margin/market_total are left None here and filled in by
    backfill_week() from the dated odds snapshot
    (load_preseason_market_snapshots below), keyed off this game's real
    gameday.
    """
    path = source_root / f"schedule_preseason_{season}.csv"
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
            index[str(row["game_id"])] = {
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "away_score": float(away_score),
                "home_score": float(home_score),
                "gameday": _parse_gameday(row.get("gameday")),
                "market_margin": None,
                "market_total": None,
            }
    return index


def load_preseason_market_snapshots(season: int, *, source_root: Path = NFL_SOURCE_ROOT) -> dict[str, list[tuple[date, dict]]]:
    """Every real dated preseason-odds snapshot row for this season,
    indexed by game_id and paired with the calendar date that snapshot was
    taken on (see
    scripts/fetch_nfl_preseason_odds.py::write_preseason_odds_snapshot).
    backfill_week() uses this to pick, per game, the snapshot dated closest
    to (at or before) that game's own kickoff date -- the closing-line
    proxy -- instead of reading preseason_odds_{season}.csv, which is fully
    overwritten on every refresh and will not reliably still hold a played
    game's real line by the time a backfill runs.
    """
    index: dict[str, list[tuple[date, dict]]] = {}
    if not source_root.exists():
        return index
    for path in source_root.glob(f"preseason_odds_snapshot_{season}_*.csv"):
        match = _SNAPSHOT_FILENAME_RE.match(path.name)
        if not match:
            continue
        snapshot_date = date(season, int(match.group("month")), int(match.group("day")))
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                game_id = str(row.get("game_id") or "").strip()
                if not game_id:
                    continue
                index.setdefault(game_id, []).append((snapshot_date, row))
    return index


def _best_market_snapshot_row(entries: list[tuple[date, dict]], *, game_date: date | None) -> dict | None:
    if not entries:
        return None
    if game_date is not None:
        on_or_before = [entry for entry in entries if entry[0] <= game_date]
        if on_or_before:
            return max(on_or_before, key=lambda entry: entry[0])[1]
    return max(entries, key=lambda entry: entry[0])[1]


def load_smartsim_projections(
    season: int,
    week: int,
    *,
    source_root: Path = NFL_SOURCE_ROOT,
    season_kind: str = "regular",
) -> dict[str, dict]:
    if season_kind == "preseason":
        projections = read_preseason_projection_artifact(season=season, week=week, data_root=source_root)
    else:
        projections = read_projection_artifact(season=season, week=week, data_root=source_root)
    return {p.game_id: {"model_margin": p.margin_mean, "model_total": p.total_mean} for p in projections}


def backfill_week(
    season: int,
    week: int,
    *,
    source_root: Path = NFL_SOURCE_ROOT,
    log_path: Path = PERFORMANCE_LOG_PATH,
    season_kind: str = "regular",
) -> dict[str, int]:
    completed_games = load_completed_games(season, week, source_root=source_root, season_kind=season_kind)
    smartsim_index = load_smartsim_projections(season, week, source_root=source_root, season_kind=season_kind)

    market_snapshots: dict[str, list[tuple[date, dict]]] = {}
    if season_kind == "preseason":
        market_snapshots = load_preseason_market_snapshots(season, source_root=source_root)

    written = 0
    skipped_no_projection = 0
    for game_id, game in completed_games.items():
        model = smartsim_index.get(game_id)
        if model is None:
            skipped_no_projection += 1
            continue

        market_margin = game["market_margin"]
        market_total = game["market_total"]
        if season_kind == "preseason":
            snapshot_row = _best_market_snapshot_row(market_snapshots.get(game_id, []), game_date=game.get("gameday"))
            if snapshot_row is not None:
                spread_home = str(snapshot_row.get("spread_home") or "").strip()
                total_line = str(snapshot_row.get("total_line") or "").strip()
                # spread_home is the same bet-notation convention as
                # schedule_{season}.csv's spread_line (home negative =
                # favored), so the outcome-sense negation above applies
                # identically here.
                market_margin = -float(spread_home) if spread_home else None
                market_total = float(total_line) if total_line else None

        record = build_game_performance_record(
            game_id=game_id,
            season=season,
            week=week,
            home_team=game["home_team"],
            away_team=game["away_team"],
            market_margin=market_margin,
            market_total=market_total,
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
    parser.add_argument(
        "--season-kind",
        type=str,
        choices=("regular", "preseason"),
        default="regular",
        help=(
            "Which schedule/projection/log family to backfill. 'regular' (default) is the "
            "original, unchanged behavior. 'preseason' reads schedule_preseason_{season}.csv, "
            "SmartSim2 preseason projections, and the dated preseason odds snapshot, and writes "
            "to the separate PRESEASON_PERFORMANCE_LOG_PATH."
        ),
    )
    args = parser.parse_args()

    season_kind = args.season_kind
    log_path = PRESEASON_PERFORMANCE_LOG_PATH if season_kind == "preseason" else PERFORMANCE_LOG_PATH

    if args.reset and log_path.exists():
        log_path.unlink()

    if args.weeks.strip().lower() == "all":
        if season_kind == "preseason":
            weeks = preseason_seasons_and_weeks(NFL_SOURCE_ROOT).get(args.season, [])
        else:
            weeks = nfl_projection_available_weeks(args.season)
    else:
        weeks = [int(w) for w in args.weeks.split(",") if w.strip()]

    totals = {"completed_games": 0, "written": 0, "skipped_no_projection": 0}
    for week in weeks:
        result = backfill_week(args.season, week, log_path=log_path, season_kind=season_kind)
        print(f"week={week} {result}")
        for key in totals:
            totals[key] += result[key]
    print(f"TOTAL {totals}")
    print(f"log_path={log_path}")


if __name__ == "__main__":
    main()
