"""Generate the standalone SmartSim 2.0 NFL PRESEASON projection artifact
for one real preseason week.

Writes data/nfl_source/smartsim2_preseason_projections_{season}_wk{week}.csv,
one row per real scheduled preseason game for that week (from
data/nfl_source/schedule_preseason_{season}.csv -- see
scripts/fetch_nfl_preseason_schedule.py; this script's ONLY schedule
source, since nflverse has zero preseason data of any kind, confirmed
structural).

Team ratings are anchored at the real PRIOR-season rolling EPA rating --
this reuses scripts/generate_smartsim2_nfl_projections.py::team_rating()
UNMODIFIED, called with current_plays=[] so it always takes the existing
"prior_season_fallback" branch (exactly its real meaning: "no
current-season pbp exists yet", which is always true for a preseason
game -- there is no in-preseason play-by-play at all).

Because most of the real players who will actually see the most snaps in
a given preseason week (depth_rank 3+, deep camp bodies, many with no
real career pbp) have no data the prior-season EPA rating reflects, this
script does NOT claim precision it doesn't have. Instead it applies a
real, documented shrinkage-toward-league-neutral adjustment scaled by how
non-starter-heavy that real preseason week is expected to be (see
syndicate.features.nfl.preseason_depth.NONSTARTER_PARTICIPATION_SHARE),
and widens the reported margin/total stdev to honestly disclose higher
real uncertainty rather than presenting a falsely tight distribution.

This script does not modify SmartSim 2.0 or the regular-season generation
script -- it only imports team_rating()/load_pbp_plays() from the latter
as a library.

Usage:
  python scripts/generate_smartsim2_nfl_preseason_projections.py --season 2026 --week 2
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

from scripts.fetch_nfl_preseason_schedule import preseason_schedule_path
from scripts.generate_smartsim2_nfl_projections import SEEDS_PER_GAME
from scripts.generate_smartsim2_nfl_projections import load_pbp_plays
from scripts.generate_smartsim2_nfl_projections import team_rating
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.nfl.preseason_depth import NONSTARTER_PARTICIPATION_SHARE
from syndicate.features.nfl.preseason_depth import PRESEASON_WEEK_LABELS
from syndicate.features.nfl.preseason_projection import SmartSimNflPreseasonProjection
from syndicate.features.nfl.preseason_projection import write_preseason_projection_artifact
from syndicate.features.nfl.sources import default_nfl_source_root

DATA_ROOT = default_nfl_source_root()
PROFILE_NAME = "nfl_preseason_v1"

# Regression target for the shrinkage below -- same convention as
# team_rating()'s own "neutral_no_data" fallback (0.0), not a new magic
# number invented for this script.
LEAGUE_NEUTRAL_RATING = 0.0


def preseason_schedule_rows(season: int, week: int) -> list[dict[str, str]]:
    path = preseason_schedule_path(season, source_root=DATA_ROOT)
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                row_week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            if row_week != week:
                continue
            game_id = (row.get("game_id") or "").strip()
            home_team = (row.get("home_team") or "").strip()
            away_team = (row.get("away_team") or "").strip()
            if not game_id or not home_team or not away_team:
                continue
            rows.append({"game_id": game_id, "home_team": home_team, "away_team": away_team})
    return rows


# Real, live sportsbook and user-facing spot-check both surfaced the same
# real problem: shrinking the MEAN by the full real non-starter
# participation share (0.55-0.92) collapsed genuine team-quality spread
# almost to nothing -- e.g. real 2025 NE (off +0.158 EPA/play) vs TEN
# (off -0.160) shrank to +0.032 vs -0.032 at an 80% share, so every game's
# projected score converged on the same ~21-23 baseline regardless of who
# was playing. That conflated two different real things: "what fraction
# of snaps come from backups" (the participation share -- a legitimate,
# real driver of UNCERTAINTY) does not mean "the team's expected quality
# moves that same fraction toward league-average" -- a strong
# organization's backups still tend to outperform a weak organization's
# backups (correlated coaching/scheme/depth-building quality), so full
# shrinkage-to-neutral overcorrects the POINT ESTIMATE. Fix: the full
# participation share still drives the honest uncertainty WIDTH
# (widened_stdev, unchanged below); only a scaled-down fraction of it
# drives how far the MEAN moves, so real team identity survives in the
# projected score even for the most backup-heavy weeks.
MEAN_SHRINKAGE_SCALE = 0.35


def shrunk_rating(base_rating: float, *, nonstarter_share: float) -> tuple[float, float]:
    """Real, legitimate regression-to-mean, scaled down from the raw
    participation share by MEAN_SHRINKAGE_SCALE (see the comment above
    for why the raw share alone overcorrects the mean). shrunk =
    base*(1-mean_share) + LEAGUE_NEUTRAL_RATING*mean_share. Returns
    (shrunk_rating, mean_share_applied) -- the second value is the real
    fraction actually applied to the mean, not the raw participation
    share (that's recorded separately as
    nonstarter_participation_share)."""
    mean_share = nonstarter_share * MEAN_SHRINKAGE_SCALE
    shrunk = base_rating * (1.0 - mean_share) + LEAGUE_NEUTRAL_RATING * mean_share
    return shrunk, mean_share


def widened_stdev(base_stdev: float, *, nonstarter_share: float) -> float:
    """Widen variance instead of narrowing it -- honest disclosure of real
    higher uncertainty in a backup/bubble-heavy game, rather than a
    tighter false-precision band."""
    return base_stdev * (1.0 + nonstarter_share)


def build_preseason_projection(
    *,
    season: int,
    week: int,
    home_team: str,
    away_team: str,
    game_id: str,
    prior_season_plays: list[tuple[int, str, str, str, float]],
    seeds: int = SEEDS_PER_GAME,
) -> SmartSimNflPreseasonProjection:
    # current_plays=[] forces team_rating()'s own existing
    # prior_season_fallback branch -- reused verbatim, not reimplemented,
    # for exactly its real meaning here: no current-season pbp exists.
    home_off, home_def, home_source = team_rating(home_team, week=1, current_plays=[], prior_plays=prior_season_plays)
    away_off, away_def, away_source = team_rating(away_team, week=1, current_plays=[], prior_plays=prior_season_plays)

    share = NONSTARTER_PARTICIPATION_SHARE[week]
    home_off, _ = shrunk_rating(home_off, nonstarter_share=share)
    home_def, _ = shrunk_rating(home_def, nonstarter_share=share)
    away_off, _ = shrunk_rating(away_off, nonstarter_share=share)
    away_def, shrinkage_applied = shrunk_rating(away_def, nonstarter_share=share)

    rating_source = f"nflverse_pbp_epa_prior_season_shrunk[{home_source}/{away_source}]"

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

    uncertainty_note = (
        f"Preseason projection for {PRESEASON_WEEK_LABELS[week]} -- ratings nudged toward "
        f"league-neutral by {shrinkage_applied:.0%} (real 2025 team identity is mostly kept; "
        f"a strong organization's backups still tend to outperform a weak one's) and the "
        f"variance widened to reflect {share:.0%} expected backup/bubble-player participation "
        f"this week; treat with much lower confidence than a regular-season projection."
    )

    return SmartSimNflPreseasonProjection(
        game_id=game_id,
        season=season,
        week=week,
        home_team=home_team,
        away_team=away_team,
        home_score_mean=round(statistics.fmean(home_scores), 3),
        away_score_mean=round(statistics.fmean(away_scores), 3),
        margin_mean=round(statistics.fmean(margins), 3),
        total_mean=round(statistics.fmean(totals), 3),
        margin_stdev=round(widened_stdev(statistics.pstdev(margins), nonstarter_share=share), 3),
        total_stdev=round(widened_stdev(statistics.pstdev(totals), nonstarter_share=share), 3),
        home_win_rate=round(home_win_rate, 4),
        seeds_used=seeds,
        profile_name=PROFILE_NAME,
        rating_source=rating_source,
        generated_at=datetime.now(timezone.utc).isoformat(),
        nonstarter_participation_share=share,
        shrinkage_applied=round(shrinkage_applied, 4),
        uncertainty_note=uncertainty_note,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True, choices=[1, 2, 3, 4])
    parser.add_argument("--seeds", type=int, default=SEEDS_PER_GAME)
    parser.add_argument("--progress-log", type=Path, default=None)
    args = parser.parse_args()

    def log(message: str) -> None:
        if args.progress_log:
            with args.progress_log.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")

    start = time.time()
    log(f"START season={args.season} week={args.week} seeds={args.seeds}")

    prior_season_plays = load_pbp_plays(args.season - 1)
    log(f"PBP_LOADED prior_season_plays={len(prior_season_plays)}")

    schedule_rows = preseason_schedule_rows(args.season, args.week)
    log(f"SCHEDULE rows={len(schedule_rows)}")

    projections: list[SmartSimNflPreseasonProjection] = []
    for row in schedule_rows:
        projection = build_preseason_projection(
            season=args.season,
            week=args.week,
            home_team=row["home_team"],
            away_team=row["away_team"],
            game_id=row["game_id"],
            prior_season_plays=prior_season_plays,
            seeds=args.seeds,
        )
        projections.append(projection)
        log(f"PROJECTED {row['away_team']} @ {row['home_team']} -> {projection.home_score_mean:.1f}-{projection.away_score_mean:.1f} (shrinkage={projection.shrinkage_applied:.2f})")

    path = write_preseason_projection_artifact(projections, season=args.season, week=args.week, data_root=DATA_ROOT)
    elapsed = time.time() - start

    log(f"WRITE_DONE path={path} projections={len(projections)} elapsed={elapsed:.1f}s")
    print(f"schedule_rows={len(schedule_rows)}")
    print(f"projections_written={len(projections)}")
    print(f"elapsed_seconds={elapsed:.1f}")
    print(f"artifact_path={path}")


if __name__ == "__main__":
    main()
