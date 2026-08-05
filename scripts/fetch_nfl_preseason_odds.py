"""Fetch real NFL preseason market odds from OddsAPI.

Confirmed live 2026-08-05: `americanfootball_nfl_preseason` is a real,
active OddsAPI sport key (`GET /v4/sports` lists it, `active: true`) --
NOT the same key as the regular season (`americanfootball_nfl`). A real
call returned 1 real event (the Hall of Fame Game, CAR @ ARI) with 9 real
bookmakers already posting moneyline/spread/total lines.

Writes data/nfl_source/preseason_odds_{season}.csv -- one row per real
game with a real posted line, joined to the real preseason schedule
(schedule_preseason_{season}.csv, see fetch_nfl_preseason_schedule.py) by
team-pair for a real week number and game_id. Reuses
fetch_nfl_team_odds_local.py's team-name normalization, bookmaker
selection, and quota-recording helpers directly rather than duplicating
them.

Usage:
  python scripts/fetch_nfl_preseason_odds.py --season 2026
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.fetch_nfl_preseason_schedule import preseason_schedule_path
from scripts.fetch_nfl_team_odds_local import _env
from scripts.fetch_nfl_team_odds_local import choose_bookmaker
from scripts.fetch_nfl_team_odds_local import fetch_odds
from scripts.fetch_nfl_team_odds_local import normalize_team_name
from syndicate.features.nfl.sources import default_nfl_source_root

DATA_ROOT = default_nfl_source_root()
PRESEASON_SPORT_KEY = "americanfootball_nfl_preseason"

ODDS_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "week",
    "home_team",
    "away_team",
    "home_moneyline",
    "away_moneyline",
    "spread_home",
    "total_line",
    "book",
    "fetched_at",
)


def preseason_odds_path(season: int, *, data_root: Path | None = None) -> Path:
    root = data_root if data_root is not None else DATA_ROOT
    return root / f"preseason_odds_{season}.csv"


def load_schedule_lookup(season: int) -> dict[tuple[str, str], dict[str, str]]:
    """{(normalized_away_name, normalized_home_name): {game_id, week,
    home_team (real abbr), away_team (real abbr)}} from the real
    preseason schedule -- the join key is the normalized full team name
    (shared vocabulary between ESPN's schedule and OddsAPI's odds), the
    stored value keeps the real abbreviation so this script's own output
    stays consistent with every other preseason CSV's team-code
    convention."""
    path = preseason_schedule_path(season, source_root=DATA_ROOT)
    lookup: dict[tuple[str, str], dict[str, str]] = {}
    if not path.exists():
        return lookup
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            away_abbr = (row.get("away_team") or "").strip()
            home_abbr = (row.get("home_team") or "").strip()
            if not away_abbr or not home_abbr:
                continue
            away = normalize_team_name(away_abbr)
            home = normalize_team_name(home_abbr)
            lookup[(away, home)] = {
                "game_id": row.get("game_id", ""),
                "week": row.get("week", ""),
                "away_team": away_abbr,
                "home_team": home_abbr,
            }
    return lookup


def build_odds_rows(events: list[dict[str, Any]], schedule_lookup: dict[tuple[str, str], dict[str, str]], season: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    for event in events:
        away = normalize_team_name(event.get("away_team") or "")
        home = normalize_team_name(event.get("home_team") or "")
        matched = schedule_lookup.get((away, home))
        if not matched:
            continue
        bookmaker = choose_bookmaker(event.get("bookmakers") or [])
        if not bookmaker:
            continue

        moneyline_home = moneyline_away = spread_home = total_line = None
        for market in bookmaker.get("markets") or []:
            key = market.get("key")
            outcomes = market.get("outcomes", []) or []
            if key == "h2h":
                for outcome in outcomes:
                    name = normalize_team_name(outcome.get("name", ""))
                    if name == home:
                        moneyline_home = outcome.get("price")
                    elif name == away:
                        moneyline_away = outcome.get("price")
            elif key == "spreads":
                for outcome in outcomes:
                    name = normalize_team_name(outcome.get("name", ""))
                    if name == home:
                        spread_home = outcome.get("point")
            elif key == "totals":
                for outcome in outcomes:
                    if str(outcome.get("name") or "").strip().lower().startswith("over"):
                        total_line = outcome.get("point")

        rows.append(
            {
                "game_id": matched["game_id"],
                "season": str(season),
                "week": matched["week"],
                "home_team": matched["home_team"],
                "away_team": matched["away_team"],
                "home_moneyline": "" if moneyline_home is None else str(moneyline_home),
                "away_moneyline": "" if moneyline_away is None else str(moneyline_away),
                "spread_home": "" if spread_home is None else str(spread_home),
                "total_line": "" if total_line is None else str(total_line),
                "book": str(bookmaker.get("key") or ""),
                "fetched_at": fetched_at,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    api_key = _env("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ODDS_API_KEY environment variable")

    events = fetch_odds(api_key=api_key, sport_key=PRESEASON_SPORT_KEY, region="us", odds_format="american")
    schedule_lookup = load_schedule_lookup(args.season)
    rows = build_odds_rows(events, schedule_lookup, args.season)

    path = preseason_odds_path(args.season)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ODDS_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"events_fetched={len(events)}")
    print(f"rows_matched={len(rows)}")
    print(f"odds_path={path}")


if __name__ == "__main__":
    main()
