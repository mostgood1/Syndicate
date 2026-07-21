"""Generate the standalone SmartSim 2.0 NCAAF projection artifact for one week.

Writes data/ncaaf_source/data/smartsim2_projections_{season}_wk{week}.csv,
one row per FBS-vs-FBS game on the current engine's own schedule for that
week (read from the predicted-totals snapshot, so SmartSim only ever
projects games the legacy engine already covers).

This script does not modify SmartSim 2.0 or the legacy engine -- it only
calls syndicate.features.football.sim_engine.smartsim2 as a library, using
NCAAF_CALIBRATION_PROFILE exactly as shipped.

Usage:
  python scripts/generate_smartsim2_ncaaf_projections.py --season 2025 --week 8
  # Requires CFBD_API_KEY in environment (team ratings, real game ids).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from datetime import timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE
from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection
from syndicate.features.ncaaf.smartsim2_projection import write_projection_artifact
from syndicate.features.ncaaf.sources import default_ncaaf_source_root

DATA_ROOT = default_ncaaf_source_root() / "data"
ENHANCED_CSV = DATA_ROOT / "college_football_schedule_2025_predicted_totals_enhanced.csv"

CFBD_API_BASE = "https://api.collegefootballdata.com"
CFBD_ENV_VARS = ("CFBD_API_KEY", "COLLEGEFOOTBALLDATA_API_KEY", "COLLEGE_FOOTBALL_DATA_API_KEY")
SEEDS_PER_GAME = 300
PROFILE_NAME = "ncaaf_v2"


def _api_key() -> str:
    for env_var in CFBD_ENV_VARS:
        value = os.environ.get(env_var)
        if value:
            return value
    raise RuntimeError("Missing CFBD API key. Set CFBD_API_KEY, COLLEGEFOOTBALLDATA_API_KEY, or COLLEGE_FOOTBALL_DATA_API_KEY.")


def _cfbd_get(path: str, params: dict[str, object]) -> object:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    url = f"{CFBD_API_BASE}{path}?{query}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {_api_key()}", "User-Agent": "syndicate-smartsim2-shadow/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def norm(name: str) -> str:
    text = (name or "").strip().lower()
    text = text.replace("state", "st").replace("&", "and")
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def load_engine_schedule(season: int, week: int) -> list[dict[str, str]]:
    with ENHANCED_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("week") == str(week) and row.get("season") == str(season)]
    return rows


def load_cfbd_games(season: int, week: int) -> dict[tuple[str, str], dict]:
    payload = _cfbd_get("/games", {"year": season, "week": week, "seasonType": "regular", "classification": "fbs"})
    index: dict[tuple[str, str], dict] = {}
    if isinstance(payload, list):
        for game in payload:
            index[(norm(game.get("homeTeam", "")), norm(game.get("awayTeam", "")))] = game
    return index


def load_ppa_ratings(season: int) -> dict[str, dict]:
    payload = _cfbd_get("/ppa/teams", {"year": season, "excludeGarbageTime": "true"})
    index: dict[str, dict] = {}
    if isinstance(payload, list):
        for row in payload:
            index[norm(row.get("team", ""))] = row
    return index


def load_ppa_ratings_with_fallback(season: int) -> tuple[dict[str, dict], str]:
    """PPA ratings are season-aggregate stats computed from games actually
    played that season -- for the first week(s) of a brand-new season, CFBD
    has nothing yet (confirmed empty for a pre-season 2026 request). Fall
    back to the prior season's final ratings as a preseason proxy for team
    strength, same idea real prediction systems use for week 1 of a new
    season. The fallback is whole-index (not per-team): PPA data for a
    season is either fully populated (games have been played) or entirely
    empty (none have), not partially populated.
    """
    index = load_ppa_ratings(season)
    if index:
        return index, f"cfbd_ppa_season_{season}"
    fallback_index = load_ppa_ratings(season - 1)
    if fallback_index:
        return fallback_index, f"cfbd_ppa_season_{season - 1}_fallback_for_{season}"
    return index, f"cfbd_ppa_season_{season}"


def offense_defense_rating(team: str, ppa_index: dict[str, dict]) -> tuple[float, float]:
    row = ppa_index.get(norm(team))
    if row is None:
        return 0.0, 0.0
    offense = float((row.get("offense") or {}).get("overall") or 0.0)
    defense_allowed = float((row.get("defense") or {}).get("overall") or 0.0)
    return offense, -defense_allowed


def games_from_cfbd_when_engine_schedule_empty(cfbd_games: dict[tuple[str, str], dict]) -> list[dict[str, str]]:
    """Fallback game list for a season the legacy engine has no schedule for
    (its predicted-totals CSV is a single, non-season-partitioned file that
    is only ever refreshed for the engine's own season). Reuses the same
    real CFBD game data already fetched for cross-referencing -- filtered to
    strict FBS-vs-FBS, matching the same check the normal engine-schedule
    path applies downstream."""
    rows = []
    for game in cfbd_games.values():
        if game.get("homeClassification") != "fbs" or game.get("awayClassification") != "fbs":
            continue
        home_team = str(game.get("homeTeam") or "").strip()
        away_team = str(game.get("awayTeam") or "").strip()
        if not home_team or not away_team:
            continue
        rows.append({"home_team": home_team, "away_team": away_team})
    return rows


def build_projection(
    *,
    season: int,
    week: int,
    home_team: str,
    away_team: str,
    game_id: str,
    ppa_index: dict[str, dict],
    rating_source: str,
    seeds: int = SEEDS_PER_GAME,
) -> SmartSimNcaafProjection:
    home_off, home_def = offense_defense_rating(home_team, ppa_index)
    away_off, away_def = offense_defense_rating(away_team, ppa_index)

    home_scores: list[int] = []
    away_scores: list[int] = []
    for seed in range(1, seeds + 1):
        sim_input = SmartSim2SimulationInput(
            home_team=home_team,
            away_team=away_team,
            seed=seed,
            home_offense_rating=home_off,
            home_defense_rating=home_def,
            away_offense_rating=away_off,
            away_defense_rating=away_def,
        )
        output = simulate_game(sim_input, profile=NCAAF_CALIBRATION_PROFILE)
        home_scores.append(output.final_score["home"])
        away_scores.append(output.final_score["away"])

    margins = [h - a for h, a in zip(home_scores, away_scores)]
    totals = [h + a for h, a in zip(home_scores, away_scores)]
    home_win_rate = sum(1 for m in margins if m > 0) / seeds

    return SmartSimNcaafProjection(
        game_id=game_id,
        season=season,
        week=week,
        home_team=home_team,
        away_team=away_team,
        home_score_mean=round(statistics.fmean(home_scores), 3),
        away_score_mean=round(statistics.fmean(away_scores), 3),
        margin_mean=round(statistics.fmean(margins), 3),
        total_mean=round(statistics.fmean(totals), 3),
        margin_stdev=round(statistics.pstdev(margins), 3),
        total_stdev=round(statistics.pstdev(totals), 3),
        home_win_rate=round(home_win_rate, 4),
        seeds_used=seeds,
        profile_name=PROFILE_NAME,
        rating_source=rating_source,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--seeds", type=int, default=SEEDS_PER_GAME)
    parser.add_argument("--progress-log", type=Path, default=None)
    args = parser.parse_args()

    def log(message: str) -> None:
        if args.progress_log:
            with args.progress_log.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")

    start = time.time()
    log(f"START season={args.season} week={args.week} seeds={args.seeds}")

    schedule_rows = load_engine_schedule(args.season, args.week)
    log(f"ENGINE_SCHEDULE rows={len(schedule_rows)}")

    cfbd_games = load_cfbd_games(args.season, args.week)
    log(f"CFBD_GAMES fbs_vs_any={len(cfbd_games)}")

    used_cfbd_schedule_fallback = False
    if not schedule_rows:
        schedule_rows = games_from_cfbd_when_engine_schedule_empty(cfbd_games)
        used_cfbd_schedule_fallback = True
        log(f"ENGINE_SCHEDULE_EMPTY falling back to CFBD games directly rows={len(schedule_rows)}")

    ppa_index, rating_source = load_ppa_ratings_with_fallback(args.season)
    log(f"PPA_RATINGS teams={len(ppa_index)} rating_source={rating_source}")

    projections: list[SmartSimNcaafProjection] = []
    skipped_no_cfbd_match: list[str] = []
    skipped_not_fbs_vs_fbs: list[str] = []

    for row in schedule_rows:
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if not home_team or not away_team:
            continue
        cfbd_game = cfbd_games.get((norm(home_team), norm(away_team)))
        if cfbd_game is None:
            skipped_no_cfbd_match.append(f"{away_team} @ {home_team}")
            continue
        if cfbd_game.get("homeClassification") != "fbs" or cfbd_game.get("awayClassification") != "fbs":
            skipped_not_fbs_vs_fbs.append(f"{away_team} @ {home_team}")
            continue
        game_id = str(cfbd_game.get("id") or f"{args.season}_{args.week}_{home_team}_{away_team}".replace(" ", "_"))
        projection = build_projection(
            season=args.season,
            week=args.week,
            home_team=home_team,
            away_team=away_team,
            game_id=game_id,
            ppa_index=ppa_index,
            rating_source=rating_source,
            seeds=args.seeds,
        )
        projections.append(projection)
        log(f"PROJECTED {away_team} @ {home_team} -> {projection.home_score_mean:.1f}-{projection.away_score_mean:.1f}")

    path = write_projection_artifact(projections, season=args.season, week=args.week, data_root=DATA_ROOT)
    elapsed = time.time() - start

    log(f"WRITE_DONE path={path} projections={len(projections)} elapsed={elapsed:.1f}s")
    log(f"SKIPPED_NO_CFBD_MATCH count={len(skipped_no_cfbd_match)} {skipped_no_cfbd_match}")
    log(f"SKIPPED_NOT_FBS_VS_FBS count={len(skipped_not_fbs_vs_fbs)} {skipped_not_fbs_vs_fbs}")
    print(f"engine_schedule_rows={len(schedule_rows)}")
    print(f"used_cfbd_schedule_fallback={used_cfbd_schedule_fallback}")
    print(f"rating_source={rating_source}")
    print(f"projections_written={len(projections)}")
    print(f"skipped_no_cfbd_match={len(skipped_no_cfbd_match)}: {skipped_no_cfbd_match}")
    print(f"skipped_not_fbs_vs_fbs={len(skipped_not_fbs_vs_fbs)}: {skipped_not_fbs_vs_fbs}")
    print(f"elapsed_seconds={elapsed:.1f}")
    print(f"artifact_path={path}")


if __name__ == "__main__":
    main()
