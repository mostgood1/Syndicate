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
import json
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
from syndicate.features.nfl.injury_adjustment import adjust_team_rating_for_injuries
from syndicate.features.nfl.smartsim2_projection import SmartSimNflProjection
from syndicate.features.nfl.smartsim2_projection import write_projection_artifact
from syndicate.features.nfl.sources import default_nfl_source_root
from syndicate.features.nfl.sources import nfl_pbp_path
from syndicate.features.nfl.sources import nfl_artifact_output_root
# Reused rather than reimplemented: the reader already decides what counts as
# degenerate (`98950c6d`), and a second copy of that predicate here would let
# the writer's idea of "worthless" drift from the reader's.
from syndicate.features.shared.nfl_game_projections import _is_degenerate_rating_source

DATA_ROOT = default_nfl_source_root()
SEEDS_PER_GAME = 300
PROFILE_NAME = "nfl_v1"
OFFENSIVE_PLAY_TYPES = frozenset({"pass", "run"})

# THE SCHEDULE AND THE PLAY-BY-PLAY SPELL TWO CLUBS DIFFERENTLY, and the only
# symptom is a silently league-average projection for those games.
#
# Measured 2026-08-13 by diffing the two code sets directly:
#     schedule_preseason_2026.csv : ... LAC LAR ... WSH   (32)
#     nflverse pbp_2025.csv       : ... LA  LAC ... WAS   (32)
#     in schedule, absent from pbp: ['LAR', 'WSH']
#     in pbp, absent from schedule: ['LA',  'WAS']
#
# `team_rating` matches `posteam`/`defteam` by exact string, so Washington and
# the LA Rams found zero qualifying plays in either season and fell through to
# the `neutral_no_data` branch -- a real 0.0/0.0 rating that produces a
# confident-looking projection carrying no team information at all. Confirmed
# on production the same day: every club reported `prior_season_fallback`
# except exactly these two (`[neutral_no_data/prior_season_fallback]` on
# MIA@WSH, `[prior_season_fallback/neutral_no_data]` on LAR@KC).
#
# Applied inside `team_rating`, which is the one function BOTH generators use
# (the preseason script imports it rather than reimplementing it), so the
# regular-season and preseason paths cannot drift apart on this.
#
# Deliberately narrow: only codes that provably differ between the two feeds
# on real data. This is not a general alias table -- `team_aliases` is that,
# and reaching for it here would pull display-name resolution into a numeric
# ratings path.
_PBP_TEAM_CODE_ALIASES: dict[str, str] = {
    "LAR": "LA",
    "WSH": "WAS",
}


def pbp_team_code(team: str) -> str:
    """The schedule's code translated into the play-by-play's spelling."""
    key = str(team or "").strip().upper()
    return _PBP_TEAM_CODE_ALIASES.get(key, key)


class DegenerateProjectionRun(RuntimeError):
    """A run that has no ratings data and would write league constants.

    Raised INSTEAD of writing. The failure this prevents is not a crash, it is
    a silently plausible artifact: with no play-by-play, `team_rating` returns
    `(0.0, 0.0, "neutral_no_data")` for every club, and 300 seeds over two
    identical league-average teams produce byte-identical rows for every game.
    Measured on production 2026-08-13 -- the board served `margin 0.96`,
    `total 44.38`, `home_win 0.5267` on ALL 16 preseason games across FOUR
    dates, and it looked exactly like a real projection.

    `98950c6d` made the READER immune to such a file. This makes the WRITER
    unable to produce one, which matters because writing it OVERWRITES the
    healthy artifact -- the reader's immunity is no help once the good copy is
    gone.
    """


def assert_ratings_data_available(
    *,
    season: int,
    current_plays: list[tuple[int, str, str, str, float]],
    prior_plays: list[tuple[int, str, str, str, float]] | None,
) -> None:
    """PRECONDITION guard: refuse before simulating, not after.

    Placed ahead of the sim loop deliberately. The same outage caught at write
    time would have burned 300 seeds x N games first, and -- worse -- the
    operator would read the failure as something about the projections rather
    than about a missing input file.

    Names the resolved path, because the cause is almost always root
    resolution rather than a genuinely absent file: `data/nfl_source/tracking/`
    is GITIGNORED, so the pbp exists on the mounted disk and NOT in the repo
    checkout, and a run whose DATA_ROOT resolved to the checkout finds nothing.
    """
    if current_plays or prior_plays:
        return
    raise DegenerateProjectionRun(
        "NO PLAY-BY-PLAY DATA: refusing to generate projections that would be "
        f"identical for every game.\n"
        f"  looked for : {_pbp_path(season)}\n"
        f"          and : {_pbp_path(season - 1)}\n"
        f"  DATA_ROOT  : {DATA_ROOT}\n"
        "  Both loaded ZERO plays, so every team would rate neutral_no_data "
        "and every game would receive the same league-average projection.\n"
        "  NOTE: data/nfl_source/tracking/ is gitignored -- the pbp lives on "
        "the mounted disk and is absent from the repo checkout. If DATA_ROOT "
        "points at the checkout, that is the bug, not a missing download."
    )


def assert_projections_carry_information(
    projections: list,
    *,
    season: int,
    week: int,
) -> None:
    """PRE-WRITE guard: never truncate a healthy artifact with a worthless one.

    Fires only when EVERY projection is degenerate. A PARTIAL degenerate run
    still carries real information for its other games, and the deployed
    reader already drops the bad rows -- refusing on a partial would blank a
    mostly-good board, which is a worse failure than the one being fixed.
    (Production carries exactly that partial case whenever a club's
    abbreviation does not resolve.)

    An EMPTY list is not an outage and is deliberately allowed through: no
    games is a different condition from no data, and conflating them would
    make an out-of-season run look like a broken pipeline.
    """
    if not projections:
        return
    degenerate = [
        projection
        for projection in projections
        if _is_degenerate_rating_source(getattr(projection, "rating_source", ""))
    ]
    if len(degenerate) < len(projections):
        return
    raise DegenerateProjectionRun(
        f"EVERY projection for season={season} week={week} is degenerate "
        f"({len(degenerate)}/{len(projections)} rated neutral_no_data on BOTH "
        "sides): refusing to write.\n"
        "  Such a file is byte-identical for every game and would OVERWRITE "
        "the last good artifact, which is how a league constant reached the "
        "board on 2026-08-13.\n"
        f"  DATA_ROOT: {DATA_ROOT}\n"
        "  Nothing was written; the previous artifact is intact."
    )


def _pbp_path(season: int) -> Path:
    """`#441`. Resolves across candidate roots, NOT under `DATA_ROOT`.

    `DATA_ROOT` is `default_nfl_source_root()`, which picks a root by probing for
    `upcoming_recs_*.csv`. On refresh-worker that selects the ephemeral repo
    CHECKOUT, because the checkout ships those 5 tracked files while
    `data/nfl_source/tracking/` is gitignored and the pbp exists only on the
    mounted disk. Measured in production 2026-08-16: zero plays loaded, the
    degenerate-run guard refused (correctly), and the artifact went 2.36 days
    stale while relaunching ~107x/day.

    Deliberately NOT fixed by changing `default_nfl_source_root()`: that function
    is load-bearing for every other NFL reader, and `#389` set the precedent of
    giving each path its own resolver rather than re-pointing the shared one.
    """
    return nfl_pbp_path(season)


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
    0.0 when neither source has data, rather than raising.

    The team code is translated into the play-by-play's spelling first --
    see `_PBP_TEAM_CODE_ALIASES`. Without it Washington and the LA Rams match
    zero plays and land on the neutral branch, which is indistinguishable
    downstream from a genuine data outage.
    """
    team = pbp_team_code(team)
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


def _real_schedule_path(season: int) -> Path:
    return DATA_ROOT / f"schedule_{season}.csv"


def week_schedule_from_real_schedule(season: int, week: int) -> list[dict[str, str]]:
    """Fallback game list for a season with no pbp yet (the season hasn't
    been played) -- data/nfl_source/schedule_{season}.csv is real (confirmed:
    272 real 2026 games, real spread/total/moneyline already posted) but
    isn't otherwise read by this script, which normally derives its game
    list from real play-by-play. Same idea as
    generate_smartsim2_ncaaf_projections.py's games_from_cfbd_when_engine_schedule_empty --
    a second, independent real source, used only when the primary one is
    empty, never silently blended with it."""
    path = _real_schedule_path(season)
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
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
    apply_injury_adjustment: bool = False,
) -> tuple[SmartSimNflProjection, list[dict]]:
    # Defaults OFF -- backtested against the real, completed 2025 season
    # (scripts/backtest_nfl_injury_adjustment.py,
    # scripts/analyze_nfl_injury_adjustment_sides.py) and confirmed to
    # HURT full-season win accuracy (60.98% -> 56.44% on the 264 games
    # with a modeled injury), driven almost entirely by the offense side:
    # both its methods (excluding a player's plays, and comparing
    # starter-vs-backup rates) are simple historical averages, not causal
    # estimates, and get confounded by opponent strength / game script
    # (e.g. Darren Waller ruled out showed a *positive* delta for MIA's
    # offense in the real 2025 data -- implausible read literally, but
    # explainable as confounding). Defense alone is much closer to neutral
    # (59.47%) but still not an improvement. Left wired in and tested as a
    # validated experiment, not deleted -- pass apply_injury_adjustment=True
    # (or the CLI's --injury-adjustment flag) to opt back in.
    home_off, home_def, home_source = team_rating(home_team, week=week, current_plays=current_plays, prior_plays=prior_plays)
    away_off, away_def, away_source = team_rating(away_team, week=week, current_plays=current_plays, prior_plays=prior_plays)
    rating_source = f"nflverse_pbp_epa_rolling[{home_source}/{away_source}]"

    injury_diagnostics: list[dict] = []
    if apply_injury_adjustment:
        home_off, home_off_notes = adjust_team_rating_for_injuries(season=season, week=week, team=home_team, side="offense", base_rating=home_off)
        home_def, home_def_notes = adjust_team_rating_for_injuries(season=season, week=week, team=home_team, side="defense", base_rating=home_def)
        away_off, away_off_notes = adjust_team_rating_for_injuries(season=season, week=week, team=away_team, side="offense", base_rating=away_off)
        away_def, away_def_notes = adjust_team_rating_for_injuries(season=season, week=week, team=away_team, side="defense", base_rating=away_def)
        for team_name, notes in ((home_team, home_off_notes + home_def_notes), (away_team, away_off_notes + away_def_notes)):
            for note in notes:
                injury_diagnostics.append({"game_id": game_id, "team": team_name, **note})

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

    projection = SmartSimNflProjection(
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
    return projection, injury_diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--seeds", type=int, default=SEEDS_PER_GAME)
    parser.add_argument("--progress-log", type=Path, default=None)
    parser.add_argument("--injury-adjustment", action="store_true", help="Apply the real injury-rating adjustment (syndicate.features.nfl.injury_adjustment) -- OFF by default, backtested to hurt full-season win accuracy (60.98%% -> 56.44%% on real 2025 games with a modeled injury). Opt in only for further experimentation.")
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
    # Before the sim loop, so an outage names the missing input rather than
    # surfacing as suspiciously round numbers 300 seeds later.
    assert_ratings_data_available(season=args.season, current_plays=current_plays, prior_plays=prior_plays)

    schedule_rows = week_schedule(args.season, args.week, current_plays)
    used_real_schedule_fallback = False
    if not schedule_rows:
        schedule_rows = week_schedule_from_real_schedule(args.season, args.week)
        used_real_schedule_fallback = True
        log(f"PBP_SCHEDULE_EMPTY falling back to real schedule_{args.season}.csv rows={len(schedule_rows)}")
    log(f"SCHEDULE rows={len(schedule_rows)} used_real_schedule_fallback={used_real_schedule_fallback}")

    projections: list[SmartSimNflProjection] = []
    all_injury_diagnostics: list[dict] = []
    for row in schedule_rows:
        projection, injury_diagnostics = build_projection(
            season=args.season,
            week=args.week,
            home_team=row["home_team"],
            away_team=row["away_team"],
            game_id=row["game_id"],
            current_plays=current_plays,
            prior_plays=prior_plays,
            seeds=args.seeds,
            apply_injury_adjustment=args.injury_adjustment,
        )
        projections.append(projection)
        all_injury_diagnostics.extend(injury_diagnostics)
        log(f"PROJECTED {row['away_team']} @ {row['home_team']} -> {projection.home_score_mean:.1f}-{projection.away_score_mean:.1f}")

    # `#389` follow-up: READS stay on DATA_ROOT (the probed root -- find the
    # root that actually holds the input). The WRITE goes to the configured
    # root. Measured 2026-08-12: this script wrote to
    # /opt/render/project/src/data (the ephemeral repo checkout) while the
    # staleness guard read /opt/render/project/data (the mounted disk), so
    # every artifact was invisible and discarded on the next deploy.
    # Resolved HERE, not at import, so the value follows the environment
    # rather than freezing whatever it was when the module loaded.
    output_root = nfl_artifact_output_root()
    # LAST THING BEFORE THE WRITE. A degenerate file would replace the last
    # good artifact, so the check has to sit between the sim and the write --
    # not earlier, where the projections do not exist yet, and not after.
    assert_projections_carry_information(projections, season=args.season, week=args.week)
    path = write_projection_artifact(projections, season=args.season, week=args.week, data_root=output_root)
    injury_notes_path = DATA_ROOT / f"smartsim2_projections_{args.season}_wk{args.week}_injury_notes.json"
    if all_injury_diagnostics:
        injury_notes_path.write_text(json.dumps(all_injury_diagnostics, indent=2), encoding="utf-8")
    elif injury_notes_path.exists():
        injury_notes_path.unlink()
    elapsed = time.time() - start

    log(f"WRITE_DONE path={path} projections={len(projections)} elapsed={elapsed:.1f}s injury_adjustments={len(all_injury_diagnostics)}")
    print(f"schedule_rows={len(schedule_rows)}")
    print(f"used_real_schedule_fallback={used_real_schedule_fallback}")
    print(f"injury_adjustments_applied={len(all_injury_diagnostics)}")
    print(f"projections_written={len(projections)}")
    print(f"elapsed_seconds={elapsed:.1f}")
    print(f"artifact_path={path}")


if __name__ == "__main__":
    main()
