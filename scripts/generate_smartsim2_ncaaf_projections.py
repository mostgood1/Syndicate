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
    """Rows for this season/week from the legacy engine's predicted-totals CSV.

    RETURNS EMPTY WHEN THE FILE IS ABSENT, DELIBERATELY. `#445`.

    `games_from_cfbd_when_engine_schedule_empty` below is the intended handling
    for a season this file does not cover, and its own docstring says so: "a
    single, non-season-partitioned file that is only ever refreshed for the
    engine's own season". `main` already calls it on an empty result. But this
    function OPENED the path unguarded, so an absent file raised
    FileNotFoundError and killed the run before that fallback could engage --
    the fallback has been unreachable for exactly the case it was written for.

    Measured 2026-08-16 on refresh-worker: every launch for season=2026 week=1
    died here on
    `.../ncaaf_source/data/college_football_schedule_2025_predicted_totals_enhanced.csv`,
    and the staleness gate relaunched it indefinitely
    (`SEASON_PROJECTION_ARTIFACT_MISSING sport=ncaaf ... since_launch_seconds=2866`).
    All 278 of these files in the checkout are season 2025; there is no 2026 one
    and nothing writes one.

    NOTE THE FILENAME IS PINNED TO 2025 WHILE THE FILTER BELOW IS SEASON-AWARE.
    That is left alone on purpose: pointing it at a 2026 file would be worse, not
    better, because no such file exists and inventing one would rate the 2026
    season from 2025 predicted totals. CFBD is the correct source for a season
    the legacy engine never covered.
    """
    if not ENHANCED_CSV.is_file():
        # Attributable, not silent: "no rows for this week" and "the file is not
        # there at all" are different facts, and the caller's fallback log line
        # cannot tell them apart on its own.
        print(
            f"ENGINE_SCHEDULE_ABSENT path={ENHANCED_CSV} season={season} week={week} "
            "-- falling back to CFBD games",
            flush=True,
        )
        return []
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


# Minimum prior games before a team's as-of PPA is trusted. Below this the
# team falls back to the prior season rather than being rated on two games --
# and it is reported as fallback, never silently averaged.
_MIN_ASOF_GAMES = 3


def load_ppa_games_week(season: int, week: int) -> list[dict]:
    """Per-GAME PPA for one REGULAR-SEASON week.

    `seasonType=regular` IS LOAD-BEARING AND ITS ABSENCE IS A WORSE LEAK THAN
    THE ONE THIS FILE EXISTS TO FIX. Without it, `/ppa/games?week=1` returns
    regular week 1 AND the postseason's "week 1" -- the College Football Playoff.
    Measured 2026-08-19: Ohio State came back with FIVE rows for 2024 week 1,
    one against Akron (the real week-1 game) and four against Texas, Notre Dame,
    Oregon and Tennessee, all played the following JANUARY. Aggregating
    "weeks < 8" was therefore importing games from months AFTER the target week,
    which is strictly worse than the season-aggregate leak it replaced.

    The tell was an impossible count, not a failing test: 10 prior games through
    week 7 for a team that plays once a week, and 231 rows in week 1 against
    ~100-127 in every other week. A postseason row is otherwise indistinguishable
    from a regular one -- same shape, same fields, plausible values.
    """
    payload = _cfbd_get("/ppa/games", {
        "year": season, "week": week,
        "seasonType": "regular", "excludeGarbageTime": "true",
    })
    return [row for row in (payload if isinstance(payload, list) else [])
            if str(row.get("seasonType") or "regular") == "regular"]


def load_ppa_ratings_asof(season: int, week: int) -> tuple[dict[str, dict], str]:
    """Team PPA aggregated over weeks STRICTLY BEFORE `week`.

    WHY THIS REPLACES `/ppa/teams`. That endpoint returns season-aggregate PPA --
    its own docstring below says so -- which for a completed season includes the
    game being predicted. Measured 2026-08-19 over 558 games of 2024:

        r(full-season PPA differential, margin) = 0.663   <- leaked
        r(as-of      PPA differential, margin) = 0.487   <- this function

    a 0.176 gap, inflating apparent skill by 36%. The as-of value sits in the
    0.3-0.5 band expected of honest prior form, which is the same frame that
    caught the NFL in-game leak at r = 0.988.

    AND THE OBVIOUS FIX IS A SILENT NO-OP, which is why this takes the longer
    route. `/ppa/teams` ACCEPTS `week=N` AND IGNORES IT -- measured, identical
    134 rows and identical 0.42 for Ohio State with and without `week=5`. Adding
    a week parameter there yields the same leaked number, a clean diff and a
    false all-clear. `/ppa/games` is the only week-scoped source.

    Returns the SAME SHAPE as `/ppa/teams` ({"offense": {"overall": x}, ...})
    so `offense_defense_rating` is unchanged.

    Cost: week-1 CFBD calls instead of 1. CFBD is not the OddsAPI budget and a
    full season is ~15 calls.
    """
    offs: dict[str, list[float]] = {}
    defs: dict[str, list[float]] = {}
    for wk in range(1, max(1, int(week))):
        for row in load_ppa_games_week(season, wk):
            team = row.get("team")
            o = (row.get("offense") or {}).get("overall")
            d = (row.get("defense") or {}).get("overall")
            if team is None or o is None or d is None:
                continue
            offs.setdefault(norm(team), []).append(float(o))
            defs.setdefault(norm(team), []).append(float(d))

    index: dict[str, dict] = {}
    for key, values in offs.items():
        if len(values) < _MIN_ASOF_GAMES:
            continue
        index[key] = {
            "offense": {"overall": sum(values) / len(values)},
            "defense": {"overall": sum(defs[key]) / len(defs[key])},
            "_asof_games": len(values),
        }
    if index:
        return index, f"cfbd_ppa_asof_{season}_through_wk{int(week) - 1}"

    # No usable in-season history (week 1, or a season that has not started).
    # The prior season's FULL aggregate is a legitimate preseason proxy and is
    # not a leak: it contains no information about the season being predicted.
    prior = load_ppa_ratings(season - 1)
    if prior:
        return prior, f"cfbd_ppa_season_{season - 1}_fallback_for_{season}"
    return {}, f"cfbd_ppa_asof_{season}_unavailable"


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


# SP+ -> engine-rating scale. CALIBRATED EMPIRICALLY, not derived.
#
# `build_drive_priors` does `clamp(0.5 + rating, 0.05, 0.95)`, so a rating
# outside about +/-0.45 CLAMPS. SP+ component ratings are points-per-game in the
# 10-40 band, so passing them raw would clamp every team to 0.95 and destroy
# exactly the discrimination they are here to provide.
#
# The divisor converts a centred SP+ component into that band. It is set so the
# projected margin SD across a real slate lands near the market's, which is the
# only defensible target: the model should be LESS dispersed than realised
# margins (SD ~20.4, that gap is game-day variance) and about as dispersed as
# the market (SD ~14.5).
SP_RATING_SCALE = 10.0


def load_sp_ratings(season: int) -> dict[str, tuple[float, float]]:
    """`{norm(team): (offense_rating, defense_rating)}` from SP+, in POINTS.

    WHY SP+ REPLACES PPA AS THE RATING SOURCE. Backtested 2026-08-19 on ~740
    games per season, prior-season rating against the NEXT season's realised
    margins, so no leakage:

        prior->target   rating      r       residual SD
        2023 -> 2024    SP+         0.442   18.25   <- better
                        PPA diff    0.348   19.08
        2024 -> 2025    SP+         0.506   17.63   <- better
                        PPA diff    0.372   18.97

    SP+ wins on correlation and residual SD in BOTH independent pairs.

    It also fixes a units problem PPA could not. PPA `overall` is a PER-PLAY
    rate with SD 0.089; across the 51-game 2026 wk1 slate the resulting
    differential had SD 0.136, which the engine rendered as margin SD **1.74
    against a market SD of 14.46**. SP+ is already denominated in points per
    game (SD ~13), which is the quantity a margin model needs.

    `defense.rating` is POINTS ALLOWED -- lower is better -- so it is negated
    for the engine, whose `defense_rating` means "how good this defense is".
    """
    payload = _cfbd_get("/ratings/sp", {"year": season})
    index: dict[str, tuple[float, float]] = {}
    if isinstance(payload, list):
        for row in payload:
            team = row.get("team")
            if not team or team == "nationalAverages":
                continue
            off = (row.get("offense") or {}).get("rating")
            dfn = (row.get("defense") or {}).get("rating")
            if off is None or dfn is None:
                continue
            index[norm(team)] = (float(off), float(dfn))
    return index


def sp_offense_defense_rating(team: str, sp_index: dict[str, tuple[float, float]],
                              means: tuple[float, float]) -> tuple[float, float] | None:
    """SP+ components -> engine ratings, centred on the league mean.

    CENTRING IS NOT COSMETIC. The engine treats 0.0 as an average team
    (`0.5 + rating`), and SP+ components are absolute points-per-game around a
    non-zero league mean. Feeding them uncentred would shift EVERY team the same
    way, which is the same bias that put the NFL payload's league-mean
    offense_index at 0.405 against a neutral 0.500.

    Returns None for an unmatched team rather than (0.0, 0.0). A neutral default
    is indistinguishable from a genuinely average team, and the caller needs to
    know to fall back rather than silently rate an unknown team as league-average.
    """
    row = sp_index.get(norm(team))
    if row is None:
        return None
    off_mean, def_mean = means
    offense = (row[0] - off_mean) / SP_RATING_SCALE
    # negate: SP+ defense is points ALLOWED, engine wants defensive STRENGTH
    defense = -(row[1] - def_mean) / SP_RATING_SCALE
    return offense, defense


def sp_league_means(sp_index: dict[str, tuple[float, float]]) -> tuple[float, float]:
    if not sp_index:
        return (0.0, 0.0)
    offs = [v[0] for v in sp_index.values()]
    defs = [v[1] for v in sp_index.values()]
    return (sum(offs) / len(offs), sum(defs) / len(defs))


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
    sp_index: dict[str, tuple[float, float]] | None = None,
    sp_means: tuple[float, float] = (0.0, 0.0),
) -> SmartSimNcaafProjection:
    # SP+ FIRST, PPA AS FALLBACK. SP+ is points-per-game and backtests better on
    # margin (r 0.506 vs 0.372, residual SD 17.63 vs 18.97 over 740 games); PPA
    # is a per-play rate whose differential SD of 0.136 produced margin SD 1.74
    # against a market 14.46. Per team, so one unrated team does not discard the
    # whole slate's SP+ ratings.
    home_sp = sp_offense_defense_rating(home_team, sp_index or {}, sp_means)
    away_sp = sp_offense_defense_rating(away_team, sp_index or {}, sp_means)
    if home_sp is not None and away_sp is not None:
        (home_off, home_def), (away_off, away_def) = home_sp, away_sp
    else:
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


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--seeds", type=int, default=SEEDS_PER_GAME)
    parser.add_argument("--leaked-season-ppa", action="store_true",
                        help="use season-aggregate PPA (LEAKED for a completed season). "
                             "Reproduces pre-2026-08-19 behaviour for comparison only.")
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

    # AS-OF, not season-aggregate. `load_ppa_ratings_with_fallback` is retained
    # below for reference and for the `--leaked-season-ppa` escape hatch, but the
    # default is now leak-free. See `load_ppa_ratings_asof`.
    if args.leaked_season_ppa:
        ppa_index, rating_source = load_ppa_ratings_with_fallback(args.season)
        print("WARNING: --leaked-season-ppa in use. Ratings contain the games "
              "being predicted; any accuracy number from this run is an UPPER "
              "BOUND, not a measurement.", flush=True)
    else:
        ppa_index, rating_source = load_ppa_ratings_asof(args.season, args.week)
    log(f"PPA_RATINGS teams={len(ppa_index)} rating_source={rating_source}")

    # SP+ is the primary rating source; PPA above stays as the per-team fallback.
    sp_index = load_sp_ratings(args.season)
    sp_means = sp_league_means(sp_index)
    if sp_index:
        rating_source = f"cfbd_sp_plus_{args.season}[scale={SP_RATING_SCALE:g}]+{rating_source}"
    log(f"SP_RATINGS teams={len(sp_index)} off_mean={sp_means[0]:.2f} def_mean={sp_means[1]:.2f}")

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
            sp_index=sp_index,
            sp_means=sp_means,
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
