"""Generate the standalone SmartSim 2.0 NFL projection artifact for one week.

Writes data/nfl_source/smartsim2_projections_{season}_wk{week}.csv, one row
per real scheduled game for that week -- schedule and team ratings are both
derived directly from real nflverse play-by-play
(data/nfl_source/tracking/nflverse/pbp/pbp_{season}.csv), since no external
rating API (equivalent to CFBD for NCAAF) exists for the NFL.

Team ratings are a pre-game, rolling, EPA/play figure: offense = mean EPA on
that team's own offensive plays in all weeks strictly before the target
week (regular season, pass/run plays only); defense = -mean EPA allowed on
plays they defended, same filter (sign-flipped so higher is always better,
matching the same convention the NCAAF script uses for CFBD PPA). Week 1 (or
any team with no qualifying plays yet this season) falls back to the same
computation over the ENTIRE prior season -- same idea as
generate_smartsim2_ncaaf_projections.py's season-level PPA fallback, just
computed locally instead of from an external API.

This script does not modify SmartSim 2.0 -- it only calls
syndicate.features.football.sim_engine.smartsim2 as a library, using
NFL_CALIBRATION_PROFILE (the simulator's own default -- no NFL-specific
calibration file exists or is needed).

Usage:
  python scripts/generate_smartsim2_nfl_projections.py --season 2025 --week 10
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.nfl.smartsim2_projection import SmartSimNflProjection
from syndicate.features.nfl.smartsim2_projection import write_projection_artifact
from syndicate.features.nfl.sources import default_nfl_source_root

DATA_ROOT = default_nfl_source_root()
SEEDS_PER_GAME = 300
PROFILE_NAME = "nfl_v1"
OFFENSIVE_PLAY_TYPES = frozenset({"pass", "run"})


def _pbp_path(season: int) -> Path:
    return DATA_ROOT / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"


def load_pbp_plays(season: int) -> list[tuple[int, str, str, str, float]]:
    """Lightweight (week, posteam, defteam, play_type, epa) tuples for every
    regular-season offensive play -- not full row dicts, since a season's
    pbp file has 300+ columns and ~45k rows; only these 5 fields are ever
    used downstream."""
    path = _pbp_path(season)
    if not path.exists():
        return []
    plays: list[tuple[int, str, str, str, float]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("season_type") != "REG":
                continue
            play_type = row.get("play_type") or ""
            if play_type not in OFFENSIVE_PLAY_TYPES:
                continue
            posteam = (row.get("posteam") or "").strip()
            defteam = (row.get("defteam") or "").strip()
            if not posteam or not defteam:
                continue
            epa_text = row.get("epa")
            if not epa_text:
                continue
            try:
                epa = float(epa_text)
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            plays.append((week, posteam, defteam, play_type, epa))
    return plays


def _mean_epa(plays: list[tuple[int, str, str, str, float]], *, team: str, side: str, before_week: int | None) -> float | None:
    """side='offense' filters posteam==team, side='defense' filters defteam==team."""
    values = [
        epa
        for week, posteam, defteam, _play_type, epa in plays
        if (before_week is None or week < before_week) and (posteam == team if side == "offense" else defteam == team)
    ]
    if not values:
        return None
    return statistics.fmean(values)


def team_rating(
    team: str,
    *,
    week: int,
    current_plays: list[tuple[int, str, str, str, float]],
    prior_plays: list[tuple[int, str, str, str, float]] | None,
) -> tuple[float, float, str]:
    """Returns (offense_rating, defense_rating, rating_source_tag). Falls
    back to the entire prior season when this season has no qualifying
    plays yet for this team (week 1, or an early bye); defaults to neutral
    0.0 when neither source has data, rather than raising."""
    offense = _mean_epa(current_plays, team=team, side="offense", before_week=week)
    defense_allowed = _mean_epa(current_plays, team=team, side="defense", before_week=week)
    if offense is not None and defense_allowed is not None:
        return offense, -defense_allowed, "current_season_rolling"
    if prior_plays:
        prior_offense = _mean_epa(prior_plays, team=team, side="offense", before_week=None)
        prior_defense_allowed = _mean_epa(prior_plays, team=team, side="defense", before_week=None)
        if prior_offense is not None and prior_defense_allowed is not None:
            return prior_offense, -prior_defense_allowed, "prior_season_fallback"
    return 0.0, 0.0, "neutral_no_data"


def week_schedule(season: int, week: int, plays: list[tuple[int, str, str, str, float]]) -> list[dict[str, str]]:
    """One entry per real game at this week, derived from the pbp's own
    home/away columns -- read once here directly (not via load_pbp_plays,
    which strips those columns) since only this function needs them.

    Includes POST (playoff) games, unlike the team-rating computation
    itself (team_rating/_mean_epa read load_pbp_plays, which stays
    REG-only -- a playoff team's rating should reflect their real regular
    season, not be diluted by a small number of playoff plays). This
    schedule lookup is a separate concern: which real games exist for a
    given week, and playoff games are real games a board should be able
    to show."""
    path = _pbp_path(season)
    if not path.exists():
        return []
    seen: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("season_type") not in ("REG", "POST"):
                continue
            try:
                row_week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            if row_week != week:
                continue
            game_id = (row.get("game_id") or "").strip()
            if not game_id or game_id in seen:
                continue
            home_team = (row.get("home_team") or "").strip()
            away_team = (row.get("away_team") or "").strip()
            if not home_team or not away_team:
                continue
            seen[game_id] = {"game_id": game_id, "home_team": home_team, "away_team": away_team}
    return list(seen.values())


def build_projection(
    *,
    season: int,
    week: int,
    home_team: str,
    away_team: str,
    game_id: str,
    current_plays: list[tuple[int, str, str, str, float]],
    prior_plays: list[tuple[int, str, str, str, float]] | None,
    seeds: int = SEEDS_PER_GAME,
) -> SmartSimNflProjection:
    home_off, home_def, home_source = team_rating(home_team, week=week, current_plays=current_plays, prior_plays=prior_plays)
    away_off, away_def, away_source = team_rating(away_team, week=week, current_plays=current_plays, prior_plays=prior_plays)
    rating_source = f"nflverse_pbp_epa_rolling[{home_source}/{away_source}]"

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
        output = simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE)
        home_scores.append(output.final_score["home"])
        away_scores.append(output.final_score["away"])

    margins = [h - a for h, a in zip(home_scores, away_scores)]
    totals = [h + a for h, a in zip(home_scores, away_scores)]
    home_win_rate = sum(1 for m in margins if m > 0) / seeds

    return SmartSimNflProjection(
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

    current_plays = load_pbp_plays(args.season)
    prior_plays = load_pbp_plays(args.season - 1)
    log(f"PBP_LOADED current_plays={len(current_plays)} prior_plays={len(prior_plays)}")

    schedule_rows = week_schedule(args.season, args.week, current_plays)
    log(f"SCHEDULE rows={len(schedule_rows)}")

    projections: list[SmartSimNflProjection] = []
    for row in schedule_rows:
        projection = build_projection(
            season=args.season,
            week=args.week,
            home_team=row["home_team"],
            away_team=row["away_team"],
            game_id=row["game_id"],
            current_plays=current_plays,
            prior_plays=prior_plays,
            seeds=args.seeds,
        )
        projections.append(projection)
        log(f"PROJECTED {row['away_team']} @ {row['home_team']} -> {projection.home_score_mean:.1f}-{projection.away_score_mean:.1f}")

    path = write_projection_artifact(projections, season=args.season, week=args.week, data_root=DATA_ROOT)
    elapsed = time.time() - start

    log(f"WRITE_DONE path={path} projections={len(projections)} elapsed={elapsed:.1f}s")
    print(f"schedule_rows={len(schedule_rows)}")
    print(f"projections_written={len(projections)}")
    print(f"elapsed_seconds={elapsed:.1f}")
    print(f"artifact_path={path}")


if __name__ == "__main__":
    main()
