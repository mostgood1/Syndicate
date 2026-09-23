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
import os
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
from syndicate.features.shared.football_segment_distributions import FootballSegmentAccumulator
from syndicate.features.shared.football_segment_distributions import segment_distributions_enabled
from syndicate.features.shared.football_segment_distributions import write_segment_distributions_artifact
from syndicate.features.nfl.smartsim2_projection import write_projection_artifact
from syndicate.features.nfl.smartsim2_projection import write_ratings_artifact
from syndicate.features.nfl.sources import default_nfl_source_root
from syndicate.features.nfl.sources import nfl_pbp_diagnostic
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
        # `#441`, third diagnosis. THE PATHS ABOVE CANNOT DISTINGUISH "absent"
        # FROM "never looked for": both `looked for` lines print the resolver's
        # FALLBACK when no candidate has the file, so a process that cannot see
        # the mounted disk prints exactly what a genuinely missing file prints.
        # Two diagnoses were already wrong on this, the second one shipped.
        # The candidate list and the env AS THIS PROCESS SEES THEM settle it.
        "  RESOLUTION (this process):\n"
        f"{nfl_pbp_diagnostic(season)}\n"
        "  READ IT LIKE THIS: candidates under /opt/render/project/data/ mean the "
        "env is fine and the file is genuinely absent (an ingestion gap). "
        "Candidates only under /src/data/ mean the env is NOT reaching this "
        "subprocess, the mounted disk was never consulted, and THAT is the bug.\n"
        "  NOTE: data/nfl_source/tracking/ is gitignored, so the pbp cannot ship "
        "in the repo checkout -- it exists only on the mounted disk. This NOTE "
        "previously asserted the file WAS on that disk; that was a hypothesis, "
        "never a measurement, and it sent one fix in the wrong direction."
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


# THE RATING MUST BE DENOMINATED IN POINTS PER GAME, NOT POINTS PER PLAY.
#
# MEASURED 2026-09-06, and the symptom was that this model could not tell NFL
# teams apart at all:
#
#     across-game `margin_mean` stdev   NFL 2.16   vs   NCAAF 15.37
#     games at P(home) 0.35..0.65       NFL 93.8%  vs   NCAAF 13.7%
#     market `spread_line` stdev        5.69       (2023-2025 pooled, n=656)
#
# So the model differentiated 2.6x LESS than the market it is priced against.
# Localised to the RATINGS INPUT rather than the shared engine, because the
# WITHIN-game numbers are near-identical across the two sports (margin_stdev
# 13.66 vs 13.14, total_stdev 11.87 vs 12.21) -- the same code shapes one game's
# spread in both and does it consistently.
#
# THIS REPO ALREADY MADE THIS DIAGNOSIS FOR THE OTHER SPORT. `state_football.md`
# records CFBD's `PPA overall` as "a PER-PLAY rate with SD 0.089 ... which the
# engine rendered as margin SD 1.74 against a market SD of 14.46", and the fix
# was SP+, "already denominated in points per game, which is the quantity a
# margin model needs". NFL's 2.16 sits in that neighbourhood. NFL was one sport
# behind a fix already made here.
#
# WHY THIS IS A UNITS CORRECTION AND NOT A TUNED MULTIPLIER, which is what makes
# it shippable without a fitted backtest: EPA *is* expected points added. Summed
# over a game's plays it IS points per game -- the same data, aggregated at the
# level the margin model consumes, rather than a coefficient chosen to move a
# number. Measured on 2025 pbp: 60.6 offensive plays/game, EPA/play stdev 0.0918
# -> EPA/game stdev 5.47 POINTS. Best offense NE +9.52 pts/game, worst LV -11.93,
# which are recognisable NFL magnitudes.
#
# CENTRED AND SCALED EXACTLY AS NCAAF IS. The engine treats 0.0 as a league
# AVERAGE team, so an uncentred rating shifts every team the same way -- the bias
# `[nfl-game-context]` already records as "the NFL payload's league-mean
# offense_index at 0.405 against a neutral 0.500".
#
# IT NO LONGER MIRRORS NCAAF's `SP_RATING_SCALE`. It did, on the reasoning
# "same engine, same units, so the same divisor" -- and the units half of that
# was wrong. NCAAF's SP+ is points per game as published; this is EPA summed to
# a game, and the two do not share a spread just because they share a
# dimension. The divisor is now set from this sport's own data.
# SET TO 20.0 ON 2026-09-07 FROM AN OUT-OF-SAMPLE FIT, superseding the 10.0
# that mirrored NCAAF's divisor. Walk-forward ratings (a week-w game rates only
# from plays BEFORE week w), OLS of ACTUAL MARGIN on the rating differential
# fitted on 2023-24 and scored on a 2025 the fit never saw, wants a slope of
# 0.404 -- which through this engine is a scale of ~20.9. Reproduce with
# `scripts/backtest_nfl_rating_units.py`.
#
# THE SLOPE IS NOT PRECISE: 0.322 (fit 2023) to 0.493 (fit 2024). 20.0 is the
# round number inside that band, not a fitted decimal, and nothing here should
# be read as knowing the scale to better than about +/-20%.
NFL_RATING_SCALE = 20.0


def _points_per_game_ratings_enabled() -> bool:
    """OFF BY DEFAULT, and the measurement is why.

    The per-game conversion is dimensionally CORRECT -- EPA is expected points
    added, so summed over a game it is points per game -- and it cures the
    pathology it was built for. Measured on real 2025 week 10, 300 seeds:

        margin_mean stdev   2.16 -> 11.44
        games at P .35-.65  93.8% -> 3/14
        exactly 0.0/1.0     0 -> 0

    BUT THE MARKET'S OWN SPREAD IS 5.69 (`spread_line` stdev, 2023-2025 pooled,
    n=656). So this trades a model that differentiates 2.6x TOO LITTLE for one
    that differentiates 2.0x TOO MUCH, and an over-confident model that prices
    is more dangerous than a flat one that cannot.

    THAT OBJECTION HAS NOW BEEN ANSWERED, and the paragraph that used to sit
    here refused 20.0 for a good reason that no longer applies. It was refused
    because 20.0 had been chosen to make the output SD match the market's 5.69
    -- fitting a coefficient to a target, the move this ledger's soccer
    precedent warns about. On 2026-09-07 the same value was reached from a
    DIFFERENT basis: OLS against REALISED MARGINS, fitted on 2023-24 and scored
    on a held-out 2025. Same answer, honest derivation.

    THE UNITS STORY ABOVE IS ALSO HALF WRONG and is kept only because the
    conclusion survives. Per-play and per-game differentials correlate at
    r = 0.9967, so the conversion adds NO information -- it is a linear
    rescaling, and with each given its own fitted coefficient the two are
    indistinguishable out-of-sample (MAE 10.58 vs 10.60). What was really wrong
    was the SCALE, not the denominator.

    AND IT STILL MUST NOT PRICE. The corrected model loses to the close (MAE
    10.58 vs 9.79, straight-up 60.2% vs 64.2%), reproducing the refusal audit's
    t = +3.34 from a second implementation. This makes the BOARD honest -- it
    was showing 93.8% of games as coin flips -- and licenses nothing more.


    So the correction ships INERT and testable:
    `SYNDICATE_NFL_PPG_RATINGS=1` turns it on for a backtest run. Absent means
    the OLD behaviour, stated explicitly because "absent != off" is a documented
    trap here and the default is what decides.
    """
    raw = str(os.environ.get("SYNDICATE_NFL_PPG_RATINGS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _epa_per_game(
    plays: list[tuple[int, str, str, str, float]],
    *,
    team: str,
    side: str,
    before_week: int | None,
) -> float | None:
    """Expected points added PER GAME for one team, or None with no data.

    Sibling of `_mean_epa`, which divides by PLAYS and is what produced a
    per-play rate. Games are counted as DISTINCT WEEKS actually seen rather than
    assumed, so a bye, a short season or a mid-season call sizes itself.
    """
    total = 0.0
    weeks: set[int] = set()
    for week, posteam, defteam, _play_type, epa in plays:
        owner = posteam if side == "offense" else defteam
        if owner != team:
            continue
        if before_week is not None and week >= before_week:
            continue
        total += epa
        weeks.add(week)
    if not weeks:
        return None
    return total / len(weeks)


def _league_epa_per_game(
    plays: list[tuple[int, str, str, str, float]],
    *,
    side: str,
    before_week: int | None,
) -> float:
    """League mean of per-game EPA, for centring. 0.0 when there is no data.

    Averaged over TEAMS, not over plays: the engine's neutral is an average
    TEAM, and a play-weighted mean would let a high-volume offence pull the
    centre it is being measured against.
    """
    totals: dict[str, float] = {}
    weeks: dict[str, set[int]] = {}
    for week, posteam, defteam, _play_type, epa in plays:
        owner = posteam if side == "offense" else defteam
        if not owner:
            continue
        if before_week is not None and week >= before_week:
            continue
        totals[owner] = totals.get(owner, 0.0) + epa
        weeks.setdefault(owner, set()).add(week)
    per_game = [totals[t] / len(weeks[t]) for t in totals if weeks.get(t)]
    return sum(per_game) / len(per_game) if per_game else 0.0


def _rating_pair(
    plays: list[tuple[int, str, str, str, float]],
    *,
    team: str,
    before_week: int | None,
) -> tuple[float, float] | None:
    """(offense, defense) in engine units, or None when this team has no plays.

    `defense` is NEGATED: the raw figure is expected points ALLOWED per game, and
    the engine's `defense_rating` means "how good this defence is". Getting that
    backwards would rate the best defence as the worst, and the sign is the one
    thing here no amount of scaling would reveal.
    """
    off = _epa_per_game(plays, team=team, side="offense", before_week=before_week)
    dfn = _epa_per_game(plays, team=team, side="defense", before_week=before_week)
    if off is None or dfn is None:
        return None
    off_mean = _league_epa_per_game(plays, side="offense", before_week=before_week)
    def_mean = _league_epa_per_game(plays, side="defense", before_week=before_week)
    return ((off - off_mean) / NFL_RATING_SCALE, -((dfn - def_mean) / NFL_RATING_SCALE))


# LAST SEASON COUNTS AS THIS MANY GAMES OF EVIDENCE in a team's rating, and this
# season's games take over as they are played: rating = (n*current + K*prior)/(n+K).
#
# THE DEFECT, measured on production 2026-09-21: the PPG path switched from the
# whole prior season (week 1) to ONLY this season's games from week 2, so a
# week-2 rating was ONE game of EPA through `NFL_RATING_SCALE`. The served week-2
# file put NYG @ LA at NYG by 17.8 against a close of LA -8.5, JAX @ DEN at -26.6
# against +2.5, IND @ KC at +27.6 against +6.5.
#
# FITTED WALK-FORWARD, against ACTUAL MARGINS, not against the market. Ratings
# for week w use plays before w; K chosen on 2023-24 with the slope FIXED at the
# 0.547 the engine applies at scale 20 (measured on production's own 2026 wk1
# file, n=16, residual SD 0.88); scored on a 2025 the fit never saw
# (`scripts/backtest_nfl_rating_units.py --prior-games`):
#
#                        K=0 (old)   K=4     market
#     weeks 2-4 MAE      13.17       10.16   9.81    (n=48, delta -3.00 +- 0.78)
#     all weeks MAE      10.86       10.36   9.72    (n=272, delta -0.50 +- 0.20)
#     weeks 10+ MAE      10.18       10.32   9.56    (+0.13 +- 0.15, inside noise)
#
# The train optimum is flat over K=3..5; 4 is its centre. A prior-season
# regression factor was also searched and did not beat plain K=4 on train, so it
# is not here. The blended model STILL LOSES TO THE CLOSE and must not price --
# this makes the display sane, the same disposition as `NFL_RATING_SCALE`.
#
# K=0 restores the old estimator exactly. Week 1 (n=0) is unchanged by
# construction, which keeps the preseason generator's output unchanged too.
NFL_RATING_PRIOR_GAMES = 4.0


def _rating_prior_games() -> float:
    """`SYNDICATE_NFL_RATING_PRIOR_GAMES` overrides; ABSENT means 4.0 (the blend
    is ON). Stated because "absent != off" is a documented trap here: this one
    is on when absent, and `0` is the kill switch back to the old estimator."""
    raw = str(os.environ.get("SYNDICATE_NFL_RATING_PRIOR_GAMES") or "").strip()
    try:
        value = float(raw) if raw else NFL_RATING_PRIOR_GAMES
    except ValueError:
        value = NFL_RATING_PRIOR_GAMES
    return max(0.0, value)


# HOW MUCH OF THE TWO TEAMS' COMMON LEVEL THE TOTAL KEEPS. The margin reads the
# DIFFERENCE between the two teams' ratings and the total reads their LEVEL (the
# sum), and until now one gain served both: `NFL_RATING_SCALE` was fitted by OLS
# of ACTUAL MARGIN on the rating DIFFERENTIAL, and the level inherited it.
#
# THE DEFECT, measured on production's served 2026 wk3 board (n=16): model total
# SD 9.02 against a market SD of 2.51 -- 3.60x -- with mean bias only +0.29 and
# corr +0.652 to the market. Unbiased, correlated, over-amplified: a GAIN defect,
# not a level or a sign one. CIN @ PIT priced at 33.2 against a close of 47.5 and
# BAL @ DAL at 62.4 against 51.5. The MARGIN over the same 16 games was fine
# (SD 5.58 vs market 4.86, MAE 2.38), which is what localises this to the level.
#
# FITTED AGAINST ACTUAL TOTALS, NOT THE MARKET, walk-forward, train 2023-24 and
# scored on a 2025 the fit never saw (`--total-level`). Regressing actual totals
# on the two level components over 544 games:
#
#     total = 44.67 + 0.3525*(off_h+off_a) + 0.0148*(def_h+def_a)   R2 = 0.042
#
# against the 0.797 / 0.764 the ENGINE applies. Offence is over-applied ~2.3x;
# DEFENCE is over-applied by ~50x -- historically a team's defensive EPA says
# almost NOTHING about a game's total, and the engine weights it nearly like
# offence. R2 = 0.042 is the honest headline: the level barely predicts a total
# at all, which is why the market's own totals sit in a 12-point band.
#
# 1.0 RESTORES TODAY'S BEHAVIOUR EXACTLY and is the kill switch. Week 1 and the
# neutral/no-data branches are unaffected in KIND -- they shrink the same way,
# because a level nobody has evidence for is exactly the case for shrinking.
#
# MEASURED END TO END on 2025 wk10, 300 seeds (lambda 1.0 -> 0.3, n=14):
# SD(total_mean) 4.76 -> 2.33, mean total 43.41 -> 43.73 (the LEVEL is kept, the
# SPREAD of levels is not), and lambda=1.0 reproduced the pre-change file on all
# 14 games and all five projected fields -- the kill switch is exact, not close.
#
# THE RESIDUAL IS NOT REACHABLE FROM HERE. The shrink scales only the part of
# the total the ratings explain, so SD_after/SD_before = sqrt(lambda^2*R2 +
# 1-R2): 0.52 predicted against 0.49 measured on wk10 (R2 0.80). On production's
# wk3 (R2 0.89) that predicts 9.02 -> ~3.9 against a market 2.51, and even
# lambda=0 would only reach ~3.0. The rest is the sim's own non-level variance
# and needs a different lever.
#
# THIS IS AN ESTIMATOR CHANGE, NOT A NEW MECHANISM: it re-fits a gain that was
# never fitted in this direction.
NFL_TOTAL_LEVEL_SHRINK = 0.3


def _total_level_shrink() -> float:
    """`SYNDICATE_NFL_TOTAL_LEVEL_SHRINK` overrides; ABSENT means the fitted
    value (the shrink is ON). "Absent != off" is a documented trap here, so:
    this one is ON when absent, and `1` is the kill switch back to the old gain."""
    raw = str(os.environ.get("SYNDICATE_NFL_TOTAL_LEVEL_SHRINK") or "").strip()
    try:
        value = float(raw) if raw else NFL_TOTAL_LEVEL_SHRINK
    except ValueError:
        value = NFL_TOTAL_LEVEL_SHRINK
    return max(0.0, value)


def shrink_rating_level(
    home_off: float, home_def: float, away_off: float, away_def: float, shrink: float,
) -> tuple[float, float, float, float]:
    """Scale the two teams' COMMON level by `shrink`, leaving every DIFFERENCE
    between them untouched.

    Each side splits into level +/- half-difference; scaling only the level is
    what leaves every DIFFERENCE exactly intact. Ratings are CENTRED on the
    league, so shrinking toward 0 shrinks toward the league-average total --
    the right target for a quantity the evidence says is barely knowable.

    THIS IS EXACT IN THE RATINGS AND ONLY STATISTICAL IN THE OUTPUT, and the
    difference matters. The sim is not linear in its ratings, so a shrunk level
    sends each seed down a different play path and `margin_mean` moves. Measured
    on 2025 wk10, 300 seeds, lambda 1.0 -> 0.3 (n=14): mean SIGNED margin change
    +0.108 (t = +0.61, no systematic shift), RMS of the per-game change over
    that game's OWN seed standard error 0.86, where 1.0 is exactly seed noise,
    and 1 game over 2 SE against 0.7 expected by chance. So the margin is
    unchanged in expectation and wobbles only as far as 300 seeds already wobble
    it (+/- ~0.75 pts/game). Do not read `margin_mean` differences below about
    1.5 points between two runs as an effect of anything.
    """
    if shrink == 1.0:
        return home_off, home_def, away_off, away_def
    out = []
    for home, away in ((home_off, away_off), (home_def, away_def)):
        level, half = (home + away) / 2.0, (home - away) / 2.0
        out.append((shrink * level + half, shrink * level - half))
    (new_home_off, new_away_off), (new_home_def, new_away_def) = out
    return new_home_off, new_home_def, new_away_off, new_away_def


# THE ENGINE ADDS POINTS TO A GAME'S TOTAL PURELY BECAUSE THE TEAMS ARE
# MISMATCHED, AND NOTHING IN THE DATA SUPPORTS THAT. `#686`.
#
# The stated model cannot do this. Scoring is `offense_rating*3.0 -
# defense_rating*2.2` per possession (play_simulator.py:429), so
# `total = 3.0*(off_h+off_a) - 2.2*(def_h+def_a)` -- a function of SUMS only,
# in which the difference cannot appear. It appears anyway, through a
# nonlinearity in the drive/possession machinery.
#
# MEASURED CAUSALLY, not inferred from a regression on live games: `simulate_game`
# called directly on a 5x5 grid of (off_diff, def_diff) with BOTH SUMS PINNED AT
# EXACTLY ZERO, 150 seeds/cell, so nothing but the mismatch varies:
#
#     total_shift = +7.3493 * off_diff - 4.8940 * def_diff     R2 0.933
#
# residual SD 0.67 against a per-cell seed SE of 0.97 -- the linear form captures
# all of the signal there is. The response is ODD (checked at +/-0.2/0.4/0.8: the
# sign of the difference flips the sign of the shift), so this is linear in the
# SIGNED difference and not in `abs()`. Over a typical game that is ~4.5 points
# of total per 1 SD of mismatch.
#
# REALITY GIVES THIS DIRECTION A COEFFICIENT OF ZERO, which is why the whole
# response is removed rather than rescaled: `corr(|market spread|, ACTUAL total)`
# on 2025 = -0.032, and adding difference terms to an actual-total fit (train
# 2023-24, scored on a held-out 2025) moves MAE 10.709 -> 10.679, i.e. nothing.
# Lopsidedness does not predict a total.
#
# APPLIED TO THE TWO SCORE MEANS, NOT TO `total_mean`. Half comes off each side,
# so `total = home + away` is corrected while `margin = home - away` is
# UNCHANGED -- and every field in the artifact still agrees with every other.
# Editing `total_mean` alone would have left `home_score_mean + away_score_mean
# != total_mean` in the file for the next reader to trip over.
#
# `total_stdev` IS DELIBERATELY UNTOUCHED: this is a bias in the LOCATION, not
# in the dispersion, and the over/under price is
# `1 - normal_cdf((line - mean)/stdev)` (`nfl_game_projections.py:545`,
# `basis=smartsim2_total_normal`) -- verified against the served board on all 16
# wk3 games at max |diff| 0.0000 -- so correcting the mean carries the
# probability with it exactly.
#
# THIS IS A POST-HOC CALIBRATION OF AN ENGINE DEFECT AND SHOULD NOT BE THE LAST
# WORD. The nonlinearity lives in `smartsim2`, which NCAAF also uses; fixing it
# at source is the right repair and needs that sport's own actual-outcome fit
# first. `#686` carries both options.
NFL_TOTAL_DIFF_RESPONSE_OFFENSE = 7.3493
NFL_TOTAL_DIFF_RESPONSE_DEFENSE = -4.8940


def total_difference_response(
    home_off: float, home_def: float, away_off: float, away_def: float,
) -> float:
    """Points of TOTAL the engine adds purely because the two teams differ."""
    return (
        NFL_TOTAL_DIFF_RESPONSE_OFFENSE * (home_off - away_off)
        + NFL_TOTAL_DIFF_RESPONSE_DEFENSE * (home_def - away_def)
    )


def _total_diff_correction() -> float:
    """How much of that spurious response to REMOVE. **OFF BY DEFAULT.**

    `SYNDICATE_NFL_TOTAL_DIFF_CORRECTION` overrides; ABSENT means 0.0, so this
    ships INERT and `=1` arms it. Absent is OFF here, unlike
    `SYNDICATE_NFL_TOTAL_LEVEL_SHRINK` two screens up, where absent is ON --
    the two knobs in this one file default opposite ways and the reason is
    entirely in the evidence, not in taste.

    WHY IT SHIPS DISABLED, when the mechanism it removes is definitely real and
    definitely unsupported by the data. Because REMOVING it bought nothing
    measurable. Paired on 272 held-out 2025 games (train 2023-24, n=544):

        today -> correction alone       delta -0.076 +- 0.172  t=-0.44  142/272
        correction + lambda 0.3 -> 0.5  delta -0.071 +- 0.072  t=-0.99  141/272
        today -> BOTH                   delta -0.147 +- 0.185  t=-0.79  139/272

    139 of 272 is a coin flip. And the bucket that matters in September is the
    WRONG SIGN: weeks 2-4 move +0.531 +- 0.475, i.e. worse.

    IT ALSO MAKES THE BOARD LESS USEFUL, which is the argument that actually
    decided it. On 2025 wk10 the correction takes the model's total SD to 1.58
    against a market ~4.2. A model that never disagrees with the market by more
    than a point is not a safer model, it is an unreadable one -- the same
    pathology as the `2.6x too little` differentiation this file's
    `NFL_RATING_SCALE` comment was written about, approached from the other side.

    KEEP IT, DO NOT DELETE IT. The defect is real and measured (`#686`), the
    correction is exact and reversible, and the RIGHT repair is the engine
    nonlinearity itself -- which `smartsim2` shares with NCAAF and which needs
    that sport's own actual-outcome fit first. This is the scaffolding for that
    work, not a failed experiment.
    """
    raw = str(os.environ.get("SYNDICATE_NFL_TOTAL_DIFF_CORRECTION") or "").strip()
    try:
        value = float(raw) if raw else 0.0
    except ValueError:
        value = 0.0
    return max(0.0, value)


def nfl_calibration_profile():
    """`NFL_CALIBRATION_PROFILE`, optionally with blowout damping armed.

    `SYNDICATE_NFL_BLOWOUT_DAMPING` is the strength; ABSENT or `0` means the
    shipped profile is returned UNCHANGED (`is`-identical, so nothing can be
    perturbed by merely importing this). `#686`, lane
    `smartsim2-total-nonlinearity`.

    **DO NOT ARM THIS IN PRODUCTION WITHOUT RE-FITTING FIRST.** The mechanism is
    real and the defect it addresses is measured, but it is a MECHANISM added to
    a CALIBRATED engine: it moves the MARGIN in exactly the blowout games, and
    the NFL margin is currently calibrated (2026 wk3 spread MAE 1.89 vs the
    market). `model_engine_standard.md` requires re-fitting the rates that were
    absorbing it, and this ledger records two mechanisms interacting NEGATIVELY
    in 4 of 4 markets. The knob exists so the fit can be RUN, not so the
    behaviour can be switched on.
    """
    raw = str(os.environ.get("SYNDICATE_NFL_BLOWOUT_DAMPING") or "").strip()
    try:
        strength = float(raw) if raw else 0.0
    except ValueError:
        strength = 0.0
    if strength <= 0.0:
        return NFL_CALIBRATION_PROFILE
    import dataclasses as _dc

    return _dc.replace(NFL_CALIBRATION_PROFILE, blowout_damping_strength=strength)


def _games_before(plays: list[tuple[int, str, str, str, float]], *, team: str, before_week: int | None) -> int:
    """Distinct weeks this team had offensive plays before `before_week` -- the
    same game count `_epa_per_game` divides by."""
    return len({week for week, posteam, _defteam, _play_type, _epa in plays
                if posteam == team and (before_week is None or week < before_week)})


def _drive_priors_enabled() -> bool:
    """OFF by default. `SYNDICATE_NFL_DRIVE_PRIORS=1` turns it on.

    WHY A FLAG RATHER THAN JUST WIRING IT. `model_engine_standard.md`: adding a
    MECHANISM to a calibrated engine requires re-fitting the rates that were
    absorbing it, and measured here, two mechanisms together produced a NEGATIVE
    interaction in 4 of 4 markets. Every drive-prior block has been at its
    neutral default on every NFL game this script has ever projected, so the
    calibration profile was fitted with them inert -- switching them on changes
    every projection at once, on a live sport, unmeasured.

    And this engine is ALREADY measured to lose: walk-forward on 816 games
    (train 2023-24, test 2025), test MAE 10.495 against the closing line's 9.722,
    **t = +3.34**, model closer on 118/272 (43.4%). A change that moves every
    number on a model in that state has to be scored before it is trusted, not
    after.

    So this lands INERT and reachable, exactly as `SYNDICATE_NFL_PPG_RATINGS`
    did. The wiring defect is fixed; enabling it is a separate, evidenced call.
    """
    raw = str(os.environ.get("SYNDICATE_NFL_DRIVE_PRIORS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _offense_feature_block(
    plays: list[tuple[int, str, str, str, float]], *, team: str, before_week: int | None
) -> dict[str, float]:
    """`offensive_epa`, `success_rate` and `pass_rate` for one team's OFFENSE.

    KEY NAMES ARE NOT FREE CHOICES. `drive_priors._offense_strength` reads
    `["offensive_epa", "epa_play", "home_offensive_epa", "away_offensive_epa",
    "epa"]` for the first, `["success_rate", ...]` for the second and
    `["pass_rate_over_expectation", "proe", "home_pass_rate", "away_pass_rate"]`
    for the third, taking the FIRST that exists. A block with the right numbers
    under the wrong names is the same silent no-op as no block at all -- which is
    the defect being fixed, reintroduced one layer down.

    SUCCESS RATE IS `epa > 0`, the standard definition, and it is derivable from
    what `load_pbp_plays` already yields. Nothing here adds I/O: the loader
    returns (week, posteam, defteam, play_type, epa) and reads 5 of the pbp
    file's 300+ columns, so every metric below comes from tuples already in
    memory. Pace, red-zone and explosive-play rates are NOT here for exactly that
    reason -- they would need new columns, and inventing them from what is loaded
    would be worse than leaving the engine on its documented neutral default.
    """
    rows = [
        (w, pt, epa)
        for (w, po, _de, pt, epa) in plays
        if po == team and (before_week is None or w < before_week)
    ]
    if not rows:
        return {}
    n = float(len(rows))
    return {
        "offensive_epa": round(sum(r[2] for r in rows) / n, 6),
        "success_rate": round(sum(1 for r in rows if r[2] > 0.0) / n, 6),
        "pass_rate": round(sum(1 for r in rows if r[1] == "pass") / n, 6),
    }


def _defense_feature_block(
    plays: list[tuple[int, str, str, str, float]], *, team: str, before_week: int | None
) -> dict[str, float]:
    """The same three, from the DEFENCE's side of the ball.

    SIGN CONVENTION, stated because getting it backwards is silent. `epa` in the
    pbp is always from the OFFENSE's perspective, so EPA allowed is NEGATED here
    to make "higher is better" hold for a defence, matching `_rating_pair`'s
    treatment of the same quantity. `drive_priors._defense_strength` reads
    `defensive_epa`, and a defence whose sign is inverted reads as elite when it
    is poor -- the shape that produced 19-28 point phantom edges on the spread
    frame in 2026-08.
    """
    rows = [
        (w, pt, epa)
        for (w, _po, de, pt, epa) in plays
        if de == team and (before_week is None or w < before_week)
    ]
    if not rows:
        return {}
    n = float(len(rows))
    return {
        "defensive_epa": round(-sum(r[2] for r in rows) / n, 6),
        "success_rate_allowed": round(sum(1 for r in rows if r[2] > 0.0) / n, 6),
    }


def build_feature_generation_payload(
    *,
    home_team: str,
    away_team: str,
    week: int | None,
    current_plays: list[tuple[int, str, str, str, float]],
    prior_plays: list[tuple[int, str, str, str, float]] | None = None,
) -> dict[str, object]:
    """The payload `drive_priors.build_drive_priors` has never been given.

    HOME-FRAMED, DELIBERATELY, because the consumer is. `build_drive_priors`
    produces ONE profile per game and its own fallback is
    `0.5 + source.home_offense_rating` -- home-framed. Publishing an away-framed
    `offensive_epa` would silently swap which team the drive priors describe. The
    `home_*` / `away_*` variants are published ALONGSIDE so a future per-team
    consumer has both, but the bare keys stay home-framed to match the fallback
    this replaces.

    LEAKAGE: `before_week=week` everywhere, so a projection for week W uses only
    weeks < W, the same contract `team_rating` already keeps. Falls back to the
    prior season when the current one has nothing yet.
    """
    def _blocks(team: str) -> tuple[dict[str, float], dict[str, float]]:
        off = _offense_feature_block(current_plays, team=team, before_week=week)
        dfn = _defense_feature_block(current_plays, team=team, before_week=week)
        if not off and prior_plays:
            off = _offense_feature_block(prior_plays, team=team, before_week=None)
        if not dfn and prior_plays:
            dfn = _defense_feature_block(prior_plays, team=team, before_week=None)
        return off, dfn

    home_off, home_def = _blocks(pbp_team_code(home_team))
    away_off, away_def = _blocks(pbp_team_code(away_team))
    if not home_off and not away_off and not home_def and not away_def:
        # NOTHING MEASURED IS NOT A NEUTRAL PAYLOAD. Returning {} keeps the
        # engine on the documented default rather than handing it a block of
        # zeros, which would read as "measured, and average".
        return {}

    offensive_metrics: dict[str, float] = {}
    offensive_metrics.update({f"home_{k}": v for k, v in home_off.items()})
    offensive_metrics.update({f"away_{k}": v for k, v in away_off.items()})
    offensive_metrics.update(home_off)          # bare keys = HOME frame

    defensive_metrics: dict[str, float] = {}
    defensive_metrics.update({f"home_{k}": v for k, v in home_def.items()})
    defensive_metrics.update({f"away_{k}": v for k, v in away_def.items()})
    defensive_metrics.update(home_def)

    payload: dict[str, object] = {}
    if offensive_metrics:
        payload["offensive_metrics"] = offensive_metrics
    if defensive_metrics:
        payload["defensive_metrics"] = defensive_metrics
    return payload


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
    0.0 when neither source has data, rather than raising. On the per-game
    path, once this season has games they are BLENDED with the prior season
    (`current_season_blend`, see `NFL_RATING_PRIOR_GAMES`) rather than
    replacing it outright.

    The team code is translated into the play-by-play's spelling first --
    see `_PBP_TEAM_CODE_ALIASES`. Without it Washington and the LA Rams match
    zero plays and land on the neutral branch, which is indistinguishable
    downstream from a genuine data outage.
    """
    team = pbp_team_code(team)
    if not _points_per_game_ratings_enabled():
        # THE OLD PER-PLAY PATH, still the DEFAULT. See
        # `_points_per_game_ratings_enabled` for why the fix is not on yet.
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
    current = _rating_pair(current_plays, team=team, before_week=week)
    prior = _rating_pair(prior_plays, team=team, before_week=None) if prior_plays else None
    if current is not None:
        prior_games = _rating_prior_games()
        if prior is not None and prior_games > 0:
            played = _games_before(current_plays, team=team, before_week=week)
            weight = played / (played + prior_games)
            return (
                weight * current[0] + (1.0 - weight) * prior[0],
                weight * current[1] + (1.0 - weight) * prior[1],
                "current_season_blend",
            )
        return current[0], current[1], "current_season_rolling"
    if prior is not None:
        return prior[0], prior[1], "prior_season_fallback"
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
    a second, independent real source. It is now the PRIMARY game list, unioned
    with the pbp's by game_id in week_game_list(): used only as a fallback for
    an EMPTY pbp week, it dropped every unplayed game once one had been played."""
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


def week_game_list(
    season: int, week: int, plays: list[tuple[int, str, str, str, float]]
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Every game of the week: the real schedule's rows, plus any game the pbp
    has that the schedule lacks (a playoff game not yet in schedule_{season}.csv),
    deduplicated by game_id.

    The pbp alone is the wrong list for a week in progress: it only holds games
    already PLAYED. The real schedule used to be read only when the pbp week was
    EMPTY, so once one game had been played every unplayed game dropped out of
    the file. Measured on production 2026-09-20/21: 2026 week 2 served 1 game
    (Thursday's) from Friday night until Sunday night, then 8 of 16, with that
    night's Monday game absent; week 1 lost its Monday game on 2026-09-14 the
    same way. A union can never list fewer games than either source."""
    pbp_rows = week_schedule(season, week, plays)
    real_rows = week_schedule_from_real_schedule(season, week)
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in real_rows:
        if row["game_id"] not in seen:
            seen.add(row["game_id"])
            merged.append(row)
    pbp_only = [row for row in pbp_rows if row["game_id"] not in seen]
    merged.extend(pbp_only)
    return merged, {"pbp_rows": len(pbp_rows), "real_schedule_rows": len(real_rows), "pbp_only_rows": len(pbp_only)}


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
    segment_accumulator: FootballSegmentAccumulator | None = None,
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

    # AFTER the injury adjustment, not before: this is the last point every
    # rating path shares, so it is the one place that governs what the engine
    # actually receives. Shrinking earlier would let the injury deltas put an
    # un-shrunk level back -- and injuries are one-sided downgrades, so they
    # land almost entirely in the level rather than the difference.
    level_shrink = _total_level_shrink()
    home_off, home_def, away_off, away_def = shrink_rating_level(
        home_off, home_def, away_off, away_def, level_shrink
    )
    if level_shrink != 1.0:
        # THE ARTIFACT RECORDS ITS OWN SETTING. Reading `current_season_blend`
        # off the served wk3 CSV is what proved the K=4 blend had reached
        # production; a shrink that left no trace in the file would have to be
        # taken on faith from a deploy log instead.
        rating_source += f"+level_shrink_{level_shrink:g}"

    # BUILT ONCE PER GAME, NOT PER SEED. It does not vary with the seed, and
    # rebuilding it inside the loop would scan every play 300 times per game.
    feature_payload = (
        build_feature_generation_payload(
            home_team=home_team,
            away_team=away_team,
            week=week,
            current_plays=current_plays,
            prior_plays=prior_plays,
        )
        if _drive_priors_enabled()
        else {}
    )

    # Resolved ONCE per game, not per seed: it reads the environment, and the
    # shipped profile is returned `is`-identical when the knob is absent.
    sim_profile = nfl_calibration_profile()
    if getattr(sim_profile, "blowout_damping_strength", 0.0):
        rating_source += f"+blowout_damp_{sim_profile.blowout_damping_strength:g}"

    home_scores: list[int] = []
    away_scores: list[int] = []
    for seed in range(1, seeds + 1):
        sim_input = SmartSim2SimulationInput(
            feature_generation_payload=feature_payload,
            home_team=home_team,
            away_team=away_team,
            seed=seed,
            home_offense_rating=home_off,
            home_defense_rating=home_def,
            away_offense_rating=away_off,
            away_defense_rating=away_def,
        )
        output = simulate_game(sim_input, profile=sim_profile)
        home_scores.append(output.final_score["home"])
        away_scores.append(output.final_score["away"])
        # STOP DISCARDING `quarter_log`. `#S1`. The sim computed a per-quarter
        # record for this seed and the two lines above were the whole of what
        # survived it, so no half/quarter market could ever be priced or
        # measured. Folding is counts-only and does not touch `final_score`
        # handling above; `segment_accumulator` is None unless
        # `SYNDICATE_FOOTBALL_SEGMENT_DISTRIBUTIONS` is on, so OFF is a
        # None-check per seed and nothing else.
        if segment_accumulator is not None:
            segment_accumulator.add(output)

    margins = [h - a for h, a in zip(home_scores, away_scores)]
    totals = [h + a for h, a in zip(home_scores, away_scores)]
    home_win_rate = sum(1 for m in margins if m > 0) / seeds

    # `#686`. HALF OFF EACH SIDE, so the TOTAL moves and the MARGIN cannot.
    # Uses the ratings the engine actually received (post level-shrink, post
    # injury adjustment) -- the level shrink leaves differences untouched by
    # construction, so this reads the same either way, but the ratings the sim
    # SAW are the only defensible input to a correction of what the sim DID.
    diff_correction = _total_diff_correction() * total_difference_response(
        home_off, home_def, away_off, away_def
    )
    home_score_mean = statistics.fmean(home_scores) - diff_correction / 2.0
    away_score_mean = statistics.fmean(away_scores) - diff_correction / 2.0
    if diff_correction:
        rating_source += f"+diff_corr_{_total_diff_correction():g}"

    projection = SmartSimNflProjection(
        game_id=game_id,
        season=season,
        week=week,
        home_team=home_team,
        away_team=away_team,
        home_score_mean=round(home_score_mean, 3),
        away_score_mean=round(away_score_mean, 3),
        # DERIVED from the two corrected sides rather than recomputed from
        # `totals`, so `home + away == total` holds in the written row. The
        # margin stays `fmean(margins)`: the correction takes the SAME amount
        # off both sides, so it cancels there exactly.
        margin_mean=round(statistics.fmean(margins), 3),
        total_mean=round(home_score_mean + away_score_mean, 3),
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

    schedule_rows, schedule_counts = week_game_list(args.season, args.week, current_plays)
    schedule_detail = " ".join(f"{key}={value}" for key, value in schedule_counts.items())
    log(f"SCHEDULE rows={len(schedule_rows)} {schedule_detail}")

    projections: list[SmartSimNflProjection] = []
    all_injury_diagnostics: list[dict] = []
    # ABSENT => OFF => `segment_blocks` stays empty, no accumulator is built,
    # no sidecar is written, and the projections CSV is byte-identical to the
    # one this script wrote before segment capture existed.
    segments_enabled = segment_distributions_enabled()
    segment_blocks: dict[str, dict] = {}
    for row in schedule_rows:
        segment_accumulator = FootballSegmentAccumulator() if segments_enabled else None
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
            segment_accumulator=segment_accumulator,
        )
        projections.append(projection)
        all_injury_diagnostics.extend(injury_diagnostics)
        if segment_accumulator is not None:
            block = segment_accumulator.payload()
            if block is not None:
                segment_blocks[str(row["game_id"])] = block
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

    # THE RATINGS THE LIVE RE-SIM WILL READ, from the SAME plays these
    # projections were built from, in the same run.
    #
    # `team_rating` is deterministic in (team, week, plays), so recomputing it
    # here yields exactly what `build_projection` used above -- and writing it
    # is what makes that guarantee available to a different process. The
    # alternative was a live tick calling `load_pbp_plays` itself: measured
    # 98 MB / 48,771 rows / 2.29 s per season, twice, which is `#241` on a
    # cadence AND would let the re-sim's ratings drift from the pregame number
    # it exists to update. Neither the re-sim flag nor `UNINFORMATIVE_BAND`
    # would catch that drift: they gate the probability, not its provenance.
    #
    # Every team in the SCHEDULE, not every team with plays -- the re-sim can
    # only ever ask about a scheduled game, and a team on `neutral_no_data`
    # must appear rather than be absent, so the reader can tell "rated
    # neutral" from "not in the file".
    ratings_for_artifact: dict[str, tuple[float, float, str]] = {}
    for row in schedule_rows:
        for team in (row["home_team"], row["away_team"]):
            if team in ratings_for_artifact:
                continue
            offense, defense, source = team_rating(
                team, week=args.week, current_plays=current_plays, prior_plays=prior_plays
            )
            ratings_for_artifact[team] = (offense, defense, source)
    ratings_path = write_ratings_artifact(
        ratings_for_artifact, season=args.season, week=args.week, data_root=output_root
    )
    # Same `output_root` as the projections and the ratings -- `#389`: reads
    # probe, writes go to the CONFIGURED root, or the artifact lands in the
    # ephemeral checkout and every deploy discards it.
    if segments_enabled:
        segment_path = write_segment_distributions_artifact(
            segment_blocks, season=args.season, week=args.week, data_root=output_root
        )
        log(f"SEGMENT_DISTRIBUTIONS path={segment_path} games={len(segment_blocks)} bytes={segment_path.stat().st_size}")
        print(f"segment_distributions_path={segment_path}", flush=True)
        print(f"segment_distributions_games={len(segment_blocks)}", flush=True)
        print(f"segment_distributions_bytes={segment_path.stat().st_size}", flush=True)
    else:
        print("segment_distributions=off", flush=True)
    _sources = {}
    for _o, _d, _s in ratings_for_artifact.values():
        _sources[_s] = _sources.get(_s, 0) + 1
    log(f"RATINGS_ARTIFACT path={ratings_path} teams={len(ratings_for_artifact)} sources={_sources}")
    injury_notes_path = DATA_ROOT / f"smartsim2_projections_{args.season}_wk{args.week}_injury_notes.json"
    if all_injury_diagnostics:
        injury_notes_path.write_text(json.dumps(all_injury_diagnostics, indent=2), encoding="utf-8")
    elif injury_notes_path.exists():
        injury_notes_path.unlink()
    elapsed = time.time() - start

    log(f"WRITE_DONE path={path} projections={len(projections)} elapsed={elapsed:.1f}s injury_adjustments={len(all_injury_diagnostics)}")
    print(f"schedule_rows={len(schedule_rows)}")
    for key, value in schedule_counts.items():
        print(f"{key}={value}")
    print(f"injury_adjustments_applied={len(all_injury_diagnostics)}")
    print(f"projections_written={len(projections)}")
    print(f"elapsed_seconds={elapsed:.1f}")
    print(f"artifact_path={path}")

    # PUBLISH TO WEB -- same gap as NCAAF, measured there 2026-08-19: the
    # worker regenerates this artifact on its own disk, web reads a DIFFERENT
    # disk, and nothing pushes it across, so the run is inert for the board.
    # Fixed in both generators together because the allowlist pattern covers
    # both and leaving one half-fixed would leave the same defect live.
    #
    # Best-effort: publish_hot_artifact never raises and returns False when
    # unconfigured (every local run), unallowlisted, or on a network error.
    # The artifact on disk is correct regardless; a failed transfer must not
    # fail generation.
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = publish_hot_artifact(Path(path))
        # The ratings artifact goes the same way. A worker that regenerates
        # projections on its own disk must also hand web the ratings, or the
        # live re-sim reads a file that only exists on the generating service.
        published_ratings = publish_hot_artifact(Path(ratings_path))
        print(f"ratings_artifact_published={published_ratings}", flush=True)
    except Exception as exc:  # noqa: BLE001 - transfer must never fail generation
        published = False
        print(f"artifact_publish_error={type(exc).__name__}: {exc}", flush=True)
    print(f"artifact_published={published}", flush=True)


if __name__ == "__main__":
    main()
