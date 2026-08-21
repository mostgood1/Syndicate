"""The NFL fantasy projection engine.

The shape of the model
----------------------
Fantasy points are the product of two things that behave completely
differently, so the engine keeps them apart end to end:

    OPPORTUNITY  (how many carries / targets / attempts)  -- sticky, predictable
    EFFICIENCY   (yards and touchdowns per opportunity)   -- noisy, regresses hard

Opportunity is modelled as a CLOSED SYSTEM per team. A team has so many plays,
so many of them are passes, and every one of those targets exactly one player.
So each player's projection is a SHARE of his team's pool, and the shares on a
team are normalised to sum to one. That single property is what makes the
engine react correctly to roster change: when a team's WR1 leaves, nothing has
to be told to promote the WR2 -- his share rises because the denominator no
longer includes the player who left.

Efficiency is shrunk toward a position/league mean by the player's own sample
size, reusing ``player_stats.shrink_count_mean`` -- the conjugate shrinkage
already tuned and measured out-of-sample for the NFL prop model (`#471`,
``state.md [nfl-player-props-model]``), rather than a second implementation of
the same idea.

Where the numbers come from
---------------------------
    scoring environment   market lines  -> fantasy_schedule.team_environments
    team volume           pbp history   -> fantasy_usage.TeamSeasonUsage
    player share          pbp history   -> fantasy_usage.PlayerSeasonUsage
    role (no history)     depth chart   -> fantasy_players.FantasyPlayer
    availability          pbp history   -> games played, shrunk to position

Every projected row carries a ``basis`` block naming which of these fed it, so
a reader can tell a market-fed row from a fitted one and a history-fed player
from a role-prior one. ``model_engine_standard.md`` s3b: a claim that does not
name its substrate is not yet a claim.

What this engine deliberately does NOT use
------------------------------------------
smartsim2, Syndicate's own NFL game simulator. See ``fantasy_schedule`` for the
measurement (w = -0.028 over 751 out-of-sample games); a model dominated by the
market is a bad input here for the same reason it is a bad input to a bet.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from functools import lru_cache
import math
from typing import Any
from typing import Iterable
from typing import Mapping

from syndicate.features.nfl.fantasy_players import FantasyPlayer
from syndicate.features.nfl.fantasy_players import latest_depth_chart
from syndicate.features.nfl.fantasy_players import load_fantasy_players
from syndicate.features.nfl.fantasy_schedule import GameEnvironment
from syndicate.features.nfl.fantasy_schedule import market_team_ratings
from syndicate.features.nfl.fantasy_schedule import team_environments
from syndicate.features.nfl.fantasy_scoring import ScoringProfile
from syndicate.features.nfl.fantasy_scoring import score_stat_line
from syndicate.features.nfl.fantasy_usage import PlayerSeasonUsage
from syndicate.features.nfl.fantasy_usage import TeamSeasonUsage
from syndicate.features.nfl.fantasy_usage import load_season_usage
from syndicate.features.nfl.player_stats import shrink_count_mean


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EngineConfig:
    """Every tunable in the engine, in one place.

    Declared as FIELDS rather than module constants for two reasons the
    standard names directly: ``dataclasses.fields()`` lets the input checklist
    enumerate them without guessing names (s4.1), and a flagged behaviour has
    to be a declared field for ``dataclasses.replace`` to reach it, which is
    what the reachability tests use (s4.3).

    ``scripts/calibrate_nfl_fantasy_projections.py`` swept all nine of these on
    the FIT season (2024, projected from 2022-2023) and nothing here was ever
    selected on 2025, which is the report season -- the same discipline as the
    prop model's six tuned constants (``state.md [nfl-player-props-model]``).

    **THREE ARE FITTED. SIX ARE NOT, AND SAYING SO IS THE POINT.** The sweep
    produced a "best" value for all nine, but six of them moved the objective
    by less than the noise floor: after the first two changes the fit-season
    MAE went 48.95 -> 48.83 across six more parameters, roughly a quarter of a
    point on n=303, with several landing on a grid edge. Shipping those as
    "tuned" would be banking noise and claiming a measurement, so they stay at
    their defaults and are labelled UNFITTED. That follows this repo's own
    precedent, where three of seven prop-model constants were left at their
    safe values rather than forced through (two marked UNSTABLE, one capped).

    Marked FITTED = selected on 2024, material effect. Marked UNFITTED = swept,
    no effect distinguishable from noise, left at its default. Marked
    STRUCTURAL = a definition, not an estimate.
    """

    #: How many prior seasons feed a player's history, most recent first, and
    #: how much each counts. UNFITTED -- the sweep preferred this default
    #: over four alternatives, but by 0.02 MAE over the next best.
    season_recency_weights: tuple[float, ...] = (1.0, 0.55, 0.30)

    #: Games of a player's own history at which his usage share is trusted
    #: half as much as the role prior. FITTED: 8.0 -> 12.0, fit-season MAE
    #: 49.34 -> 48.95, monotone improvement across 2/4/6/8/12 before
    #: turning back at 18. Trust a player's own record MORE, not less.
    share_history_half_games: float = 12.0

    #: Prior weight (in opportunities) pulling a player's efficiency toward the
    #: position mean. Separate per stat because the underlying noise differs by
    #: an order of magnitude -- yards per carry is famously unstable, catch
    #: rate is not. UNFITTED: the sweep moved fit MAE by <0.1 across a
    #: 30-250 range and landed on a grid edge, which is what a flat
    #: objective looks like, not an optimum.
    ypc_prior_opportunities: float = 90.0
    ypt_prior_opportunities: float = 45.0
    catch_rate_prior_opportunities: float = 40.0
    ypa_prior_opportunities: float = 180.0

    #: Prior weight pulling a team's own volume rates toward the league mean.
    #: In team-games. UNFITTED: monotone over 2..32 but worth 0.1 MAE in
    #: total, and it selected the largest value in the grid -- an edge
    #: selection on a 0.1-point gradient is not a measurement.
    team_volume_prior_games: float = 8.0

    #: How much of a receiver's touchdown share comes from RED-ZONE target
    #: share rather than overall target share. FITTED: 0.55 -> 1.0,
    #: monotone across all five grid points (fit MAE 49.15 -> 48.81). Red
    #: zone targets carry the touchdown signal on their own; adding overall
    #: target share to them only dilutes it.
    rz_weight_receiving: float = 1.0
    #: Same for rushers, off GOAL-LINE carry share. UNFITTED: non-monotone
    #: and worth 0.05 MAE end to end. Not the same answer as the receiving
    #: term, and not evidence that it should be.
    gl_weight_rushing: float = 0.65

    #: Prior weight pulling a player's availability rate toward his position's
    #: mean, in games. UNFITTED: 4/8/12/20 are within 0.001 objective of
    #: each other.
    availability_prior_games: float = 12.0

    #: Pass-rate response to game script: added pass rate per point of
    #: expected MARGIN against the team. NOT YET FITTED AND THEREFORE INERT
    #: AT 0.0. A non-zero value here would be a mechanism added to an engine
    #: whose other rates were fitted without it, which
    #: ``model_engine_standard.md`` s4.4 measured producing a NEGATIVE
    #: interaction in 4 of 4 markets. It ships off, and `use_game_script_
    #: pass_rate` is therefore a no-op until this is estimated and the team
    #: volume rates are re-fitted alongside it.
    pass_rate_per_point_of_spread: float = 0.0

    #: How hard a team's opportunity split is pulled toward the league's
    #: measured role-concentration SHAPE.
    #:
    #: FITTED TO ZERO, and this is the sweep's most useful result. Pulling
    #: shares toward the league-average shape was the single largest
    #: ACCURACY LOSS in the engine: turning it off took fit-season MAE from
    #: 51.11 to 49.34, more than every other parameter combined. Real teams
    #: are not the average team, and overwriting a measured split with a
    #: canonical one discards exactly the information a projection is for.
    #:
    #: It is kept as a lever at 0.0 rather than deleted because the same
    #: measurement is what justifies leaving it off, and because the OTHER
    #: half of the same curve -- `role_games_curve`, which sets expected
    #: games from role -- is load-bearing and stays on. The two were built
    #: together and are easy to confuse; separating their verdicts here is
    #: the point.
    role_curve_strength: float = 0.0

    #: STRUCTURAL. Games in an NFL regular season for one team.
    games_in_season: int = 17

    #: Feature flags. Each has a reachability test asserting off != on.
    use_market_environment: bool = True
    use_game_script_pass_rate: bool = True
    use_red_zone_touchdown_share: bool = True
    use_role_curve: bool = True
    use_news_adjustments: bool = False


DEFAULT_CONFIG = EngineConfig()


# ---------------------------------------------------------------------------
# Projected rows
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayerProjection:
    """One player's projection under one scoring profile."""

    player_id: str
    name: str
    team: str
    position: str
    season: int
    games: float
    stat_line: dict[str, float]
    fantasy_points: float
    points_per_game: float
    points_per_game_sd: float
    season_points_sd: float
    floor: float
    ceiling: float
    basis: dict[str, Any]
    week: int | None = None
    opponent: str | None = None


def _mean(values: Iterable[float]) -> float:
    collected = list(values)
    return sum(collected) / len(collected) if collected else 0.0


def _safe_divide(numerator: float, denominator: float, fallback: float = 0.0) -> float:
    return numerator / denominator if denominator else fallback


# ---------------------------------------------------------------------------
# League-wide reference rates (the shrinkage priors)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LeagueRates:
    """Population means every per-player rate is shrunk toward.

    Measured over the seasons actually available on this substrate, never
    hardcoded -- a hardcoded league mean is the ``.get(key, 1.0)`` failure with
    extra steps: it keeps working when its input disappears.
    """

    seasons: tuple[int, ...]
    team_games: int
    plays_per_game: float
    pass_rate: float
    sack_rate: float
    targets_per_attempt: float
    yards_per_attempt: float
    completion_rate: float
    interception_rate: float
    yards_per_carry: float
    yards_per_target: float
    catch_rate: float
    #: offensive touchdowns per game as a + b * points per game
    td_intercept: float
    td_slope: float
    #: field-goal attempts per game as a + b * points per game
    fg_intercept: float
    fg_slope: float
    fg_bucket_share: dict[str, float]
    fg_make_rate: dict[str, float]
    pat_rate: float
    #: extra-point attempts per offensive touchdown -- below 1.0 because some
    #: touchdowns are followed by a two-point try instead
    pat_attempts_per_td: float
    #: successful two-point conversions per touchdown, league-wide
    two_point_per_td: float
    pass_td_fraction: float
    fumbles_per_touch: float
    #: The shape of a real team's opportunity split: mean share of the 1st,
    #: 2nd, 3rd... busiest player in each pool, over every team-season
    #: available. See `_role_curves` for why this is the identifiable form
    #: of the depth-chart question.
    role_curve: dict[str, tuple[float, ...]]
    #: mean GAMES PLAYED by the 1st, 2nd, 3rd... busiest player in each
    #: pool. The other half of the role curve, and the term that makes the
    #: opportunity system close -- see `_expected_games`.
    role_games_curve: dict[str, tuple[float, ...]]
    role_curve_team_seasons: int
    #: per-position efficiency means, the priors each player is shrunk toward.
    #: A tight end and a running back catching the same number of passes are
    #: not the same bet on yards, so one league-wide mean would bias both.
    efficiency_by_position: dict[str, dict[str, float]]
    #: mean games played, by position, among players who held a real role
    availability: dict[str, float]
    #: per-game fantasy-point sd as a + b * per-game mean, by position
    variance_fit: dict[str, tuple[float, float]]


def _linear_fit(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Ordinary least squares slope/intercept. Returns ``(intercept, slope)``.

    Stdlib arithmetic on purpose, matching the prop model's stated
    "deliberately stdlib-only, no scipy" decision -- this is a two-parameter
    fit, not a numerical-methods problem.
    """
    if len(points) < 3:
        return (_mean(y for _, y in points), 0.0)
    mean_x = _mean(x for x, _ in points)
    mean_y = _mean(y for _, y in points)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in points)
    variance = sum((x - mean_x) ** 2 for x, _ in points)
    if variance <= 0:
        return (mean_y, 0.0)
    slope = covariance / variance
    return (mean_y - slope * mean_x, slope)


def _history_seasons(season: int, count: int) -> tuple[int, ...]:
    """The *count* seasons before *season* that actually have usage on this
    substrate, most recent first."""
    from syndicate.features.nfl.fantasy_usage import usage_artifact_path
    from syndicate.features.nfl.fantasy_usage import usage_substrate

    found: list[int] = []
    candidate = season - 1
    while candidate > season - 12 and len(found) < count:
        if usage_artifact_path(candidate).is_file() or usage_substrate(candidate)["exists"]:
            found.append(candidate)
        candidate -= 1
    return tuple(found)



#: How many players per team hold a real ROLE at each position, and which
#: opportunity ranks them. Used only to decide whose games-played counts toward
#: the availability mean -- never to filter a projection.
_ROLE_SLOTS: dict[str, tuple[str, int]] = {
    "QB": ("pass_attempts", 1),
    "RB": ("carries", 2),
    "WR": ("targets", 3),
    "TE": ("targets", 1),
    "K": ("fg_att", 1),
}


def _role_holders(
    players: dict[str, PlayerSeasonUsage],
    roster: dict[str, FantasyPlayer],
) -> set[str]:
    """Player ids who were their team's primary at their position that season.

    Availability has to be measured over this population and no other, and
    getting the population wrong is the failure this function exists to
    prevent. Two weaker definitions were tried first and both are wrong in the
    same direction:

    * a SEASON-TOTAL floor ("at least 50 touches") admits a backup quarterback
      who started three games. His three games describe his ROLE, not his
      health. Measured: QB availability 10.3 games -- which would have
      projected every starting quarterback in the league for ten.
    * an opportunity SHARE floor is no better, because share is a per-game
      quantity: a replacement who starts the last six games at a 100% share
      passes it with six games. Measured: 11.0, barely moved.

    Ranking WITHIN a team-season is the definition that matches the question a
    draft actually asks -- how many games does the guy who ends up being his
    team's primary play? A residual bias remains and runs the other way: when a
    genuine starter is lost early, the player who replaced him can out-rank him
    and is counted with his own high games total. That inflates the mean
    slightly. It is stated here rather than corrected, because correcting it
    needs a "who was the intended starter in September" signal that no local
    artifact carries.
    """
    by_team: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for player_id, usage in players.items():
        entry = roster.get(player_id)
        if entry is None or not usage.games:
            continue
        spec = _ROLE_SLOTS.get(entry.position)
        if spec is None:
            continue
        opportunity_field, _ = spec
        by_team.setdefault((usage.team, entry.position), []).append(
            (getattr(usage, opportunity_field), player_id)
        )

    holders: set[str] = set()
    for (_, position), ranked in by_team.items():
        slots = _ROLE_SLOTS[position][1]
        ranked.sort(reverse=True)
        for opportunity, player_id in ranked[:slots]:
            if opportunity > 0:
                holders.add(player_id)
    return holders



#: How many ordinal slots the role curve models per pool. Past this the shares
#: are indistinguishable from zero and the ordering is noise.
_ROLE_CURVE_DEPTH = 8

#: The three opportunity pools, as (label, player field, team field).
_OPPORTUNITY_POOLS: tuple[tuple[str, str, str], ...] = (
    ("target", "targets", "targets"),
    ("carry", "carries", "carries"),
    ("pass", "pass_attempts", "pass_attempts"),
    ("kick", "fg_att", "fg_att"),
)


def _role_curves(
    seasons: tuple[int, ...],
) -> tuple[dict[str, tuple[float, ...]], dict[str, tuple[float, ...]], int]:
    """Measure the SHAPE of a team's opportunity split, by pool.

    For every team-season, sort the players in a pool by their share of it and
    average the sorted vectors. The result says what a real NFL team looks
    like: one quarterback takes ~0.9 of the attempts, the backfield splits
    carries a particular way, the receiver room has a particular taper.

    THIS IS THE IDENTIFIABLE FORM OF THE DEPTH-CHART QUESTION, and it is here
    because the direct form is not. Fitting "what does a rank-2 quarterback
    get" needs a depth chart CONTEMPORANEOUS with the usage, and nflverse
    publishes depth charts for the current season only. Joining the 2026 chart
    to 2025 usage measures something else entirely -- many of 2026's backups
    were 2025's starters, which is why that table read a 0.45 pass share for
    rank-2 quarterbacks and let a displaced starter keep stealing his
    replacement's attempts after normalisation.

    A curve indexed by ORDINAL needs no depth chart at all, and is measured
    over every team-season on the substrate rather than one join. The
    player-level model still decides WHO occupies which slot; the curve only
    constrains HOW CONCENTRATED the slots are.
    """
    accumulated: dict[str, list[list[float]]] = {label: [] for label, _, _ in _OPPORTUNITY_POOLS}
    accumulated_games: dict[str, list[list[float]]] = {
        label: [] for label, _, _ in _OPPORTUNITY_POOLS
    }
    team_seasons = 0
    for season in seasons:
        players, teams = load_season_usage(season)
        by_team: dict[str, list[PlayerSeasonUsage]] = {}
        for usage in players.values():
            if usage.team and usage.games:
                by_team.setdefault(usage.team, []).append(usage)
        for team_name, roster in by_team.items():
            team = teams.get(team_name)
            if team is None or not team.games:
                continue
            team_seasons += 1
            for label, player_field, team_field in _OPPORTUNITY_POOLS:
                team_rate = getattr(team, team_field) / team.games
                if team_rate <= 0:
                    continue
                # WHILE-ACTIVE share, matching `PlayerHistory` exactly. Using a
                # season-total share here instead was a real bug: the curve then
                # embedded games missed (a quarterback who played nine games
                # showed a ~0.47 season share), while the projection ALSO
                # multiplies by expected games -- so availability was counted
                # twice and every starting quarterback came out ~30% light.
                ranked = sorted(
                    (
                        ((getattr(usage, player_field) / usage.games) / team_rate, float(usage.games))
                        for usage in roster
                        if getattr(usage, player_field) > 0
                    ),
                    key=lambda pair: -(pair[0] * pair[1]),
                )[:_ROLE_CURVE_DEPTH]
                shares = [share for share, _ in ranked]
                played = [games for _, games in ranked]
                shares += [0.0] * (_ROLE_CURVE_DEPTH - len(shares))
                played += [0.0] * (_ROLE_CURVE_DEPTH - len(played))
                accumulated[label].append(shares)
                accumulated_games[label].append(played)

    def average(source: dict[str, list[list[float]]]) -> dict[str, tuple[float, ...]]:
        out: dict[str, tuple[float, ...]] = {}
        for label, vectors in source.items():
            if not vectors:
                out[label] = tuple([0.0] * _ROLE_CURVE_DEPTH)
                continue
            out[label] = tuple(
                _mean(vector[index] for vector in vectors) for index in range(_ROLE_CURVE_DEPTH)
            )
        return out

    return average(accumulated), average(accumulated_games), team_seasons


@lru_cache(maxsize=8)
def league_rates(seasons: tuple[int, ...]) -> LeagueRates:
    """Fit every population-level rate from real usage over *seasons*."""
    from syndicate.features.nfl.fantasy_scoring import ESPN_PPR
    from syndicate.features.nfl.fantasy_usage import load_season_game_lines

    team_totals: list[TeamSeasonUsage] = []
    player_totals: list[PlayerSeasonUsage] = []
    for season in seasons:
        players, teams = load_season_usage(season)
        team_totals.extend(teams.values())
        player_totals.extend(players.values())

    if not team_totals:
        raise RuntimeError(
            f"no NFL usage on this substrate for seasons {seasons}. This is UNMEASURED, "
            "not a league with zero plays -- run scripts/build_nfl_fantasy_usage.py."
        )

    team_games = sum(entry.games for entry in team_totals)
    plays = sum(entry.off_plays for entry in team_totals)
    dropbacks = sum(entry.dropbacks for entry in team_totals)
    attempts = sum(entry.pass_attempts for entry in team_totals)
    carries = sum(entry.carries for entry in team_totals)
    targets = sum(entry.targets for entry in team_totals)
    sacks = sum(entry.sacks_taken for entry in team_totals)
    pass_yards = sum(entry.pass_yards for entry in team_totals)
    rush_yards = sum(entry.rush_yards for entry in team_totals)
    pass_tds = sum(entry.pass_tds for entry in team_totals)
    rush_tds = sum(entry.rush_tds for entry in team_totals)
    interceptions = sum(entry.interceptions_thrown for entry in team_totals)
    fumbles = sum(entry.fumbles_lost for entry in team_totals)
    fg_att = sum(entry.fg_att for entry in team_totals)
    pat_att = sum(entry.pat_att for entry in team_totals)
    pat_made = sum(entry.pat_made for entry in team_totals)

    two_point = sum(
        entry.pass_2pt + entry.rush_2pt + entry.rec_2pt for entry in player_totals
    )
    completions = sum(entry.pass_completions for entry in player_totals)
    receptions = sum(entry.receptions for entry in player_totals)
    receiving_yards = sum(entry.rec_yards for entry in player_totals)

    td_fit = _linear_fit(
        [
            (entry.points_for / entry.games, (entry.pass_tds + entry.rush_tds) / entry.games)
            for entry in team_totals
            if entry.games
        ]
    )
    fg_fit = _linear_fit(
        [(entry.points_for / entry.games, entry.fg_att / entry.games) for entry in team_totals if entry.games]
    )

    fg_buckets = {"0_39": 0.0, "40_49": 0.0, "50_plus": 0.0}
    fg_makes = {"0_39": 0.0, "40_49": 0.0, "50_plus": 0.0}
    for entry in player_totals:
        for bucket in fg_buckets:
            fg_buckets[bucket] += getattr(entry, f"fg_att_{bucket}")
            fg_makes[bucket] += getattr(entry, f"fg_made_{bucket}")
    total_fg = sum(fg_buckets.values()) or 1.0

    # Availability and per-game variance need position labels, which usage does
    # not carry -- join through the roster of each season that has one.
    position_games: dict[str, list[float]] = {}
    variance_points: dict[str, list[tuple[float, float]]] = {}
    position_efficiency: dict[str, dict[str, float]] = {}
    _EFFICIENCY_FIELDS = (
        "rec_yards",
        "targets",
        "receptions",
        "rush_yards",
        "carries",
        "pass_yards",
        "pass_attempts",
    )
    for season in seasons:
        roster = {player.player_id: player for player in load_fantasy_players(season) if player.player_id}
        if not roster:
            continue
        players, teams_for_season = load_season_usage(season)
        holders = _role_holders(players, roster)
        player_lines, _ = load_season_game_lines(season)
        lines_by_player: dict[str, list[PlayerSeasonUsage]] = {}
        for line in player_lines:
            lines_by_player.setdefault(line.player_id, []).append(line)
        for player_id, usage in players.items():
            entry = roster.get(player_id)
            if entry is None:
                continue
            slot = position_efficiency.setdefault(
                entry.position, dict.fromkeys(_EFFICIENCY_FIELDS, 0.0)
            )
            for name in _EFFICIENCY_FIELDS:
                slot[name] += getattr(usage, name)
            # Kickers have no targets, carries or attempts, so the touch
            # floor would silently drop every one of them and leave the
            # position with no availability mean at all.
            opportunity = (
                usage.fg_att
                if entry.position == "K"
                else usage.targets + usage.carries + usage.pass_attempts
            )
            if opportunity < (10 if entry.position == "K" else 50):
                continue
            # Availability is measured ONLY over role-holders. See
            # `_role_holders` for why the two obvious weaker definitions are
            # both wrong, and by how much.
            if player_id in holders:
                position_games.setdefault(entry.position, []).append(float(usage.games))
            lines = lines_by_player.get(player_id) or []
            if len(lines) >= 4:
                per_game = [score_stat_line(_usage_to_stat_line(line), ESPN_PPR) for line in lines]
                mean_points = _mean(per_game)
                sd = math.sqrt(_mean((value - mean_points) ** 2 for value in per_game))
                variance_points.setdefault(entry.position, []).append((mean_points, sd))

    curve, games_curve, curve_team_seasons = _role_curves(seasons)

    return LeagueRates(
        seasons=seasons,
        team_games=team_games,
        plays_per_game=_safe_divide(plays, team_games),
        pass_rate=_safe_divide(dropbacks, plays),
        sack_rate=_safe_divide(sacks, dropbacks),
        targets_per_attempt=_safe_divide(targets, attempts),
        yards_per_attempt=_safe_divide(pass_yards, attempts),
        completion_rate=_safe_divide(completions, attempts),
        interception_rate=_safe_divide(interceptions, attempts),
        yards_per_carry=_safe_divide(rush_yards, carries),
        yards_per_target=_safe_divide(receiving_yards, targets),
        catch_rate=_safe_divide(receptions, targets),
        td_intercept=td_fit[0],
        td_slope=td_fit[1],
        fg_intercept=fg_fit[0],
        fg_slope=fg_fit[1],
        fg_bucket_share={key: value / total_fg for key, value in fg_buckets.items()},
        fg_make_rate={key: _safe_divide(fg_makes[key], fg_buckets[key], 0.8) for key in fg_buckets},
        pat_rate=_safe_divide(pat_made, pat_att, 0.95),
        pat_attempts_per_td=_safe_divide(pat_att, pass_tds + rush_tds, 0.94),
        two_point_per_td=_safe_divide(two_point, pass_tds + rush_tds),
        pass_td_fraction=_safe_divide(pass_tds, pass_tds + rush_tds, 0.62),
        fumbles_per_touch=_safe_divide(fumbles, carries + receptions),
        availability={
            position: _mean(values) for position, values in position_games.items() if values
        },
        variance_fit={
            position: _linear_fit(values) for position, values in variance_points.items() if values
        },
        role_curve=curve,
        role_games_curve=games_curve,
        role_curve_team_seasons=curve_team_seasons,
        efficiency_by_position={
            position: {
                "yards_per_target": _safe_divide(totals["rec_yards"], totals["targets"]),
                "catch_rate": _safe_divide(totals["receptions"], totals["targets"]),
                "yards_per_carry": _safe_divide(totals["rush_yards"], totals["carries"]),
                "yards_per_attempt": _safe_divide(totals["pass_yards"], totals["pass_attempts"]),
            }
            for position, totals in position_efficiency.items()
        },
    )


def _usage_to_stat_line(usage: PlayerSeasonUsage) -> dict[str, float]:
    """A usage record in the key vocabulary ``score_stat_line`` reads."""
    return {
        "passing_yards": usage.pass_yards,
        "passing_tds": usage.pass_tds,
        "interceptions": usage.interceptions,
        "passing_2pt": usage.pass_2pt,
        "rushing_yards": usage.rush_yards,
        "rushing_tds": usage.rush_tds,
        "rushing_2pt": usage.rush_2pt,
        "receptions": usage.receptions,
        "receiving_yards": usage.rec_yards,
        "receiving_tds": usage.rec_tds,
        "receiving_2pt": usage.rec_2pt,
        "fumbles_lost": usage.fumbles_lost,
        "fg_made_0_39": usage.fg_made_0_39,
        "fg_made_40_49": usage.fg_made_40_49,
        "fg_made_50_plus": usage.fg_made_50_plus,
        "fg_missed": (
            (usage.fg_att_0_39 - usage.fg_made_0_39)
            + (usage.fg_att_40_49 - usage.fg_made_40_49)
            + (usage.fg_att_50_plus - usage.fg_made_50_plus)
        ),
        "pat_made": usage.pat_made,
        "pat_missed": usage.pat_att - usage.pat_made,
    }


def _team_usage_to_dst_line(usage: TeamSeasonUsage) -> dict[str, float]:
    return {
        "dst_sacks": usage.def_sacks,
        "dst_interceptions": usage.def_interceptions,
        "dst_fumble_recoveries": usage.def_fumble_recoveries,
        "dst_safeties": usage.def_safeties,
        "dst_touchdowns": usage.def_touchdowns,
        "dst_blocked_kicks": usage.def_blocked_kicks,
        "dst_points_allowed": usage.points_against,
    }


# ---------------------------------------------------------------------------
# Player history: shares and efficiency, blended across seasons
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayerHistory:
    """A player's multi-season usage profile, in SHARES rather than counts.

    Shares are "while active": a player's per-game usage divided by his team's
    per-game usage over the games he actually played. That separates ROLE from
    AVAILABILITY, which matters because they project differently -- a running
    back who missed six games still held a bell-cow role in the eleven he
    played, and next season's projection should carry the role forward and the
    injury risk separately, not multiply them together into one muddy number.
    """

    player_id: str
    seasons_used: tuple[int, ...]
    weighted_games: float
    raw_games: float

    pass_share: float
    carry_share: float
    target_share: float
    rz_target_share: float
    gl_carry_share: float
    rec_td_share: float
    rush_td_share: float
    fg_share: float

    yards_per_attempt: float
    completion_rate: float
    interception_rate: float
    yards_per_carry: float
    yards_per_target: float
    catch_rate: float
    fumbles_per_touch: float

    attempt_sample: float
    carry_sample: float
    target_sample: float

    availability_rate: float


def _blank_history(player_id: str) -> PlayerHistory:
    return PlayerHistory(
        player_id=player_id,
        seasons_used=(),
        weighted_games=0.0,
        raw_games=0.0,
        pass_share=0.0,
        carry_share=0.0,
        target_share=0.0,
        rz_target_share=0.0,
        gl_carry_share=0.0,
        rec_td_share=0.0,
        rush_td_share=0.0,
        fg_share=0.0,
        yards_per_attempt=0.0,
        completion_rate=0.0,
        interception_rate=0.0,
        yards_per_carry=0.0,
        yards_per_target=0.0,
        catch_rate=0.0,
        fumbles_per_touch=0.0,
        attempt_sample=0.0,
        carry_sample=0.0,
        target_sample=0.0,
        availability_rate=0.0,
    )


@lru_cache(maxsize=4)
def _history_index(seasons: tuple[int, ...]) -> dict[str, PlayerHistory]:
    """Build every player's blended history over *seasons*, most recent first."""
    weights = DEFAULT_CONFIG.season_recency_weights
    per_player: dict[str, list[tuple[float, PlayerSeasonUsage, TeamSeasonUsage]]] = {}

    for index, season in enumerate(seasons):
        weight = weights[index] if index < len(weights) else weights[-1]
        players, teams = load_season_usage(season)
        for player_id, usage in players.items():
            team = teams.get(usage.team)
            if team is None or not team.games or not usage.games:
                continue
            per_player.setdefault(player_id, []).append((weight, usage, team))

    index_out: dict[str, PlayerHistory] = {}
    for player_id, records in per_player.items():
        weighted_games = sum(weight * usage.games for weight, usage, _ in records)
        if weighted_games <= 0:
            continue

        def share(numerator: str, denominator: str) -> float:
            """Weighted mean of per-game share, weighted by season weight x games."""
            total = 0.0
            for weight, usage, team in records:
                team_rate = getattr(team, denominator) / team.games
                if team_rate <= 0:
                    continue
                player_rate = getattr(usage, numerator) / usage.games
                total += weight * usage.games * (player_rate / team_rate)
            return total / weighted_games

        def ratio(numerator: str, denominator: str) -> float:
            """Weighted efficiency: sum of weighted numerator over weighted
            denominator. NOT a mean of per-season ratios -- that would give a
            three-target season the same say as a 150-target one."""
            top = sum(weight * getattr(usage, numerator) for weight, usage, _ in records)
            bottom = sum(weight * getattr(usage, denominator) for weight, usage, _ in records)
            return _safe_divide(top, bottom)

        def sample(name: str) -> float:
            return sum(weight * getattr(usage, name) for weight, usage, _ in records)

        touches = sample("carries") + sample("receptions")
        availability_weight = sum(weight for weight, _, _ in records)
        availability = (
            sum(weight * min(usage.games, 17) / 17.0 for weight, usage, _ in records)
            / availability_weight
            if availability_weight
            else 0.0
        )

        index_out[player_id] = PlayerHistory(
            player_id=player_id,
            seasons_used=tuple(usage.season for _, usage, _ in records),
            weighted_games=weighted_games,
            raw_games=sum(float(usage.games) for _, usage, _ in records),
            pass_share=share("pass_attempts", "pass_attempts"),
            carry_share=share("carries", "carries"),
            target_share=share("targets", "targets"),
            rz_target_share=share("rz_targets", "rz_targets"),
            gl_carry_share=share("gl_carries", "gl_carries"),
            rec_td_share=share("rec_tds", "pass_tds"),
            rush_td_share=share("rush_tds", "rush_tds"),
            fg_share=share("fg_att", "fg_att"),
            yards_per_attempt=ratio("pass_yards", "pass_attempts"),
            completion_rate=ratio("pass_completions", "pass_attempts"),
            interception_rate=ratio("interceptions", "pass_attempts"),
            yards_per_carry=ratio("rush_yards", "carries"),
            yards_per_target=ratio("rec_yards", "targets"),
            catch_rate=ratio("receptions", "targets"),
            fumbles_per_touch=_safe_divide(sample("fumbles_lost"), touches),
            attempt_sample=sample("pass_attempts"),
            carry_sample=sample("carries"),
            target_sample=sample("targets"),
            availability_rate=availability,
        )
    return index_out


def player_history(season: int, config: EngineConfig = DEFAULT_CONFIG) -> dict[str, PlayerHistory]:
    seasons = _history_seasons(season, len(config.season_recency_weights))
    if not seasons:
        return {}
    return _history_index(seasons)


# ---------------------------------------------------------------------------
# Role priors: what a player with no NFL history is worth
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RolePriors:
    """Expected opportunity share by position, depth-chart rank and experience.

    Keyed ``(position, rank_bucket, experience_bucket)``. Fitted over every
    season before the target that has BOTH a preseason depth chart and usage --
    locally 2022-2025 for a 2026 projection. See ``role_priors`` for the two
    earlier versions of this table that were wrong, and for the real players
    that made each one obvious.

    Only load-bearing for rookies and players who have never held a role;
    anyone with real history has it blended away by
    ``share_history_half_games``.
    """

    season: int
    fitted_from_season: int | None
    fitted_seasons: tuple[int, ...]
    target_share: dict[tuple[str, int, str], float]
    carry_share: dict[tuple[str, int, str], float]
    pass_share: dict[tuple[str, int, str], float]
    kick_share: dict[tuple[str, int, str], float]
    sample_size: dict[tuple[str, str, int, str], int]


#: Depth ranks past this are pooled into one bucket -- below the third or
#: fourth player at a position the share is indistinguishable from zero and the
#: per-rank sample gets too thin to mean anything.
_MAX_MODELLED_RANK = 4

#: Draft-capital buckets for the rookie prior. Round boundaries, not tuned.
_DRAFT_BUCKETS: tuple[tuple[str, int], ...] = (
    ("round_1", 32),
    ("round_2", 64),
    ("round_3", 105),
    ("day_3", 262),
    ("undrafted", 10_000),
)


def _draft_bucket(draft_number: int | None) -> str:
    if draft_number is None:
        return "undrafted"
    for label, bound in _DRAFT_BUCKETS:
        if draft_number <= bound:
            return label
    return "undrafted"


def _rank_bucket(rank: int | None) -> int:
    if rank is None:
        return _MAX_MODELLED_RANK
    return min(max(rank, 1), _MAX_MODELLED_RANK)


#: How a player's PRIOR-SEASON standing is bucketed when fitting the role
#: prior. The three groups behave completely differently at the same depth-chart
#: slot, and pooling them is what made a quarterback who has never taken an NFL
#: snap look like a 45% share.
_EXPERIENCE_BUCKETS: tuple[str, ...] = ("rookie", "no_prior_role", "prior_role")

#: Opportunities in a pool last season above which a player counts as having
#: held a role in it. Deliberately low -- this separates "was on the field" from
#: "was not", not starters from backups.
_PRIOR_ROLE_FLOOR: dict[str, float] = {"target": 20.0, "carry": 20.0, "pass": 50.0, "kick": 5.0}


def _experience_bucket(
    player: FantasyPlayer,
    pool: str,
    prior_usage: PlayerSeasonUsage | None,
) -> str:
    if player.is_rookie:
        return "rookie"
    if prior_usage is None:
        return "no_prior_role"
    field = {"target": "targets", "carry": "carries", "pass": "pass_attempts", "kick": "fg_att"}[pool]
    return (
        "prior_role"
        if getattr(prior_usage, field, 0.0) >= _PRIOR_ROLE_FLOOR[pool]
        else "no_prior_role"
    )


@lru_cache(maxsize=4)
def role_priors(season: int) -> RolePriors:
    """Fit the role prior CONTEMPORANEOUSLY, and conditioned on experience.

    THE QUESTION THIS HAS TO ANSWER is "a player is listed second on the depth
    chart and I know nothing else about him -- what share does he get?". Two
    earlier versions got it wrong in ways that were invisible until a real
    player made them obvious:

    1. **Fitted only over players who PLAYED.** Skipping zero-usage rostered
       players priced a rank-2 quarterback at a 0.466 pass share. Because shares
       normalise within a team that crushed the STARTER -- Josh Allen at 12.09
       PPR points per game against a real figure near 24.

    2. **Fitted on the CURRENT chart against the PREVIOUS season's usage.** That
       pairing is not the question being asked: many of a season's backups were
       last season's starters, so "rank-2 quarterback" was priced off a
       population of displaced starters. Measured 2026-08-21 on a real board:
       **Stetson Bennett, who has never taken an NFL snap, drew a 0.374 pass
       share** on the strength of a QB2 listing and pulled Matthew Stafford from
       ~0.90 down to 0.815. Brady Russell, a fullback, drew a 0.282 carry share
       the same way.

    Both are fixed by the same two changes, and both were only possible once
    ``scripts/fetch_nfl_rosters_depth_charts.py`` brought the historical charts
    local -- before that there was exactly one depth chart on disk and no
    contemporaneous fit was available at all:

    * **CONTEMPORANEOUS**: season S's preseason chart against season S's own
      usage, pooled over every season strictly BEFORE the target (so a backtest
      of 2025 fits on 2022-2024 and cannot see itself).
    * **CONDITIONED ON EXPERIENCE**: a rookie, a player with no prior role, and
      a returning role-holder get different tables at the same slot, because
      they are different populations wearing the same number.

    Zero-usage rostered players are counted as the zeros they were, which is
    what makes the prior an expectation rather than a survivor's average.
    """
    charted: list[int] = []
    candidate = season - 1
    while candidate > season - 6:
        if latest_depth_chart(candidate)[0]:
            charted.append(candidate)
        candidate -= 1

    empty = RolePriors(
        season=season,
        fitted_from_season=None,
        fitted_seasons=(),
        target_share={},
        carry_share={},
        pass_share={},
        kick_share={},
        sample_size={},
    )
    if not charted:
        return empty

    pools = (
        ("target", "targets", "targets"),
        ("carry", "carries", "carries"),
        ("pass", "pass_attempts", "pass_attempts"),
        ("kick", "fg_att", "fg_att"),
    )
    buckets: dict[tuple[str, str, int, str], list[float]] = {}

    for fit_season in charted:
        players, teams = load_season_usage(fit_season)
        if not players:
            continue
        prior_players, _ = load_season_usage(fit_season - 1)
        league_rate = {
            team_field: _safe_divide(
                sum(getattr(entry, team_field) for entry in teams.values()),
                sum(entry.games for entry in teams.values()),
            )
            for _, _, team_field in pools
        }
        for entry in load_fantasy_players(fit_season):
            if not entry.player_id:
                continue
            usage = players.get(entry.player_id)
            prior_usage = prior_players.get(entry.player_id)
            for pool, player_field, team_field in pools:
                key = (
                    pool,
                    entry.position,
                    _rank_bucket(entry.depth_rank),
                    _experience_bucket(entry, pool, prior_usage),
                )
                if usage is None or not usage.games:
                    buckets.setdefault(key, []).append(0.0)
                    continue
                team = teams.get(usage.team)
                team_rate = (
                    getattr(team, team_field) / team.games
                    if team is not None and team.games
                    else league_rate[team_field]
                )
                if team_rate <= 0:
                    continue
                buckets.setdefault(key, []).append(
                    (getattr(usage, player_field) / usage.games) / team_rate
                )

    tables: dict[str, dict[tuple[str, int, str], float]] = {pool: {} for pool, _, _ in pools}
    sample_size: dict[tuple[str, str, int, str], int] = {}
    for (pool, position, rank, experience), values in buckets.items():
        if not values:
            continue
        tables[pool][(position, rank, experience)] = _mean(values)
        sample_size[(pool, position, rank, experience)] = len(values)

    return RolePriors(
        season=season,
        fitted_from_season=charted[0],
        fitted_seasons=tuple(sorted(charted)),
        target_share=tables["target"],
        carry_share=tables["carry"],
        pass_share=tables["pass"],
        kick_share=tables["kick"],
        sample_size=sample_size,
    )


def _role_prior_share(
    player: FantasyPlayer,
    priors: RolePriors,
    kind: str,
    prior_usage: PlayerSeasonUsage | None = None,
) -> float:
    """The prior share for one player in one opportunity pool.

    Falls back along the experience axis before the rank axis: an unseen
    (position, rank, experience) cell is better answered by the same slot's
    ``no_prior_role`` group than by a different slot's exact experience match.
    """
    table = {
        "target": priors.target_share,
        "carry": priors.carry_share,
        "pass": priors.pass_share,
        "kick": priors.kick_share,
    }[kind]
    rank = _rank_bucket(player.depth_rank)
    experience = _experience_bucket(player, kind, prior_usage)
    for candidate in (experience, "no_prior_role", "prior_role", "rookie"):
        value = table.get((player.position, rank, candidate))
        if value is not None:
            return max(value, 0.0)
    return 0.0


# ---------------------------------------------------------------------------
# Team volume: how big each opportunity pool is
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TeamVolume:
    """A team's projected per-game opportunity pool and scoring."""

    team: str
    season: int
    games: int
    plays_per_game: float
    pass_rate: float
    pass_attempts_per_game: float
    carries_per_game: float
    targets_per_game: float
    sack_rate: float
    points_per_game: float
    points_allowed_per_game: float
    offensive_tds_per_game: float
    pass_tds_per_game: float
    rush_tds_per_game: float
    fg_attempts_per_game: float
    mean_spread: float
    environment_basis: str
    market_lined_games: int


def _shrink(observed: float, sample: float, prior: float, prior_weight: float) -> float:
    """Conjugate shrinkage toward a prior, reusing the NFL prop model's own
    implementation rather than re-deriving the same formula.

    ``player_stats.shrink_count_mean`` is ``(observed*n + prior*k) / (n+k)``,
    tuned and measured out-of-sample for `#471`. Using it keeps one shrinkage
    in the NFL module instead of two that can drift.
    """
    return shrink_count_mean(observed, sample, prior, prior_weight)


def team_volume(
    season: int,
    team: str,
    league: LeagueRates,
    config: EngineConfig = DEFAULT_CONFIG,
    week: int | None = None,
) -> TeamVolume:
    """Project one team's per-game opportunity pool for *season*.

    With *week* set, the scoring environment narrows to that single game --
    that opponent's implied total, that spread -- while every rate learned from
    history (plays per game, pass rate, sack rate) stays at its season value.
    That split is deliberate: what changes week to week is the OPPONENT and the
    game script, not how fast a team plays or how often it drops back. Letting
    the volume rates wobble weekly would be fitting noise, since a single game
    is one observation.

    Returns ``games=0`` when the team does not play that week, which is how a
    bye reaches the caller as a fact rather than as a missing row.
    """
    history_seasons = _history_seasons(season, len(config.season_recency_weights))
    weights = config.season_recency_weights

    weighted_games = 0.0
    totals = {
        "off_plays": 0.0,
        "dropbacks": 0.0,
        "pass_attempts": 0.0,
        "carries": 0.0,
        "targets": 0.0,
        "sacks_taken": 0.0,
        "pass_tds": 0.0,
        "rush_tds": 0.0,
    }
    for index, history_season in enumerate(history_seasons):
        weight = weights[index] if index < len(weights) else weights[-1]
        _, teams = load_season_usage(history_season)
        entry = teams.get(team)
        if entry is None or not entry.games:
            continue
        weighted_games += weight * entry.games
        for name in totals:
            totals[name] += weight * getattr(entry, name)

    plays_per_game = _shrink(
        _safe_divide(totals["off_plays"], weighted_games, league.plays_per_game),
        weighted_games,
        league.plays_per_game,
        config.team_volume_prior_games,
    )
    pass_rate = _shrink(
        _safe_divide(totals["dropbacks"], totals["off_plays"], league.pass_rate),
        weighted_games,
        league.pass_rate,
        config.team_volume_prior_games,
    )
    sack_rate = _shrink(
        _safe_divide(totals["sacks_taken"], totals["dropbacks"], league.sack_rate),
        weighted_games,
        league.sack_rate,
        config.team_volume_prior_games,
    )
    pass_td_fraction = _shrink(
        _safe_divide(
            totals["pass_tds"], totals["pass_tds"] + totals["rush_tds"], league.pass_td_fraction
        ),
        weighted_games,
        league.pass_td_fraction,
        config.team_volume_prior_games,
    )

    # ---- scoring environment
    environments = team_environments(season).get(team) or []
    if week is not None:
        environments = [game for game in environments if game.week == week]
        if not environments:
            return TeamVolume(
                team=team,
                season=season,
                games=0,
                plays_per_game=plays_per_game,
                pass_rate=pass_rate,
                pass_attempts_per_game=0.0,
                carries_per_game=0.0,
                targets_per_game=0.0,
                sack_rate=sack_rate,
                points_per_game=0.0,
                points_allowed_per_game=0.0,
                offensive_tds_per_game=0.0,
                pass_tds_per_game=0.0,
                rush_tds_per_game=0.0,
                fg_attempts_per_game=0.0,
                mean_spread=0.0,
                environment_basis="bye_week",
                market_lined_games=0,
            )
    if environments and config.use_market_environment:
        points_per_game = _mean(game.implied_points for game in environments)
        points_allowed_per_game = _mean(game.opponent_implied_points for game in environments)
        mean_spread = _mean(game.spread for game in environments)
        lined = sum(1 for game in environments if game.basis == "market_line")
        basis = "market_line" if lined else "fitted_rating"
        games = len(environments)
    else:
        # No market at all: fall back to the team's own scoring history. This is
        # the UNMEASURED branch and it says so in `environment_basis`.
        history_points: list[float] = []
        for history_season in history_seasons:
            _, teams = load_season_usage(history_season)
            entry = teams.get(team)
            if entry is not None and entry.games:
                history_points.append(entry.points_for / entry.games)
        points_per_game = _mean(history_points) if history_points else 22.5
        points_allowed_per_game = points_per_game
        mean_spread = 0.0
        lined = 0
        basis = "history_no_market"
        games = config.games_in_season

    if config.use_game_script_pass_rate:
        # A team expected to trail throws more. `mean_spread` is the team's own
        # expected margin, so a NEGATIVE spread (underdog) raises the pass rate
        # -- hence the minus sign. Clamped to the range real NFL team seasons
        # actually occupy, so a wild line cannot produce a 90%-pass offense.
        pass_rate = min(max(pass_rate - config.pass_rate_per_point_of_spread * mean_spread, 0.30), 0.75)

    dropbacks_per_game = plays_per_game * pass_rate
    pass_attempts_per_game = dropbacks_per_game * (1.0 - sack_rate)
    carries_per_game = plays_per_game * (1.0 - pass_rate)
    targets_per_game = pass_attempts_per_game * league.targets_per_attempt

    offensive_tds_per_game = max(league.td_intercept + league.td_slope * points_per_game, 0.0)
    fg_attempts_per_game = max(league.fg_intercept + league.fg_slope * points_per_game, 0.0)

    return TeamVolume(
        team=team,
        season=season,
        games=games,
        plays_per_game=plays_per_game,
        pass_rate=pass_rate,
        pass_attempts_per_game=pass_attempts_per_game,
        carries_per_game=carries_per_game,
        targets_per_game=targets_per_game,
        sack_rate=sack_rate,
        points_per_game=points_per_game,
        points_allowed_per_game=points_allowed_per_game,
        offensive_tds_per_game=offensive_tds_per_game,
        pass_tds_per_game=offensive_tds_per_game * pass_td_fraction,
        rush_tds_per_game=offensive_tds_per_game * (1.0 - pass_td_fraction),
        fg_attempts_per_game=fg_attempts_per_game,
        mean_spread=mean_spread,
        environment_basis=basis,
        market_lined_games=lined,
    )


# ---------------------------------------------------------------------------
# Assembly: from shares and rates to a projected stat line
# ---------------------------------------------------------------------------

#: z-score for the 10th/90th percentile of a normal. STRUCTURAL.
_P10_Z = 1.2815515655446004


def _blend(history_value: float, prior_value: float, sample: float, half_sample: float) -> float:
    """Blend a player's own history with the role prior by how much history he
    has. Arithmetic, not geometric, so a zero on either side is a real number
    rather than a collapse to zero."""
    if half_sample <= 0:
        return history_value
    alpha = sample / (sample + half_sample)
    return alpha * history_value + (1.0 - alpha) * prior_value


def _health_ratio(
    player: FantasyPlayer,
    history: PlayerHistory | None,
    league: LeagueRates,
    config: EngineConfig,
) -> float:
    """How durable this player is RELATIVE to his position's average.

    Deliberately a ratio and not a games count. Availability is shrunk hard
    toward the position mean because per-player injury rates are among the
    least stable quantities in football: a player who missed six games last
    year is only slightly likelier than his peers to miss six again, and a
    model that carries that forward at full weight buries exactly the players
    who are cheapest to draft.
    """
    position_games = league.availability.get(player.position, 15.0)
    position_rate = min(position_games / config.games_in_season, 1.0)
    if position_rate <= 0:
        return 1.0
    if history is None or history.raw_games <= 0:
        return 1.0
    rate = _shrink(
        history.availability_rate,
        history.raw_games,
        position_rate,
        config.availability_prior_games,
    )
    return max(min(rate / position_rate, 1.35), 0.5)


def _expected_games(
    player: FantasyPlayer,
    history: PlayerHistory | None,
    league: LeagueRates,
    config: EngineConfig,
    role_games: float | None,
) -> float:
    """Projected games played, from ROLE first and health second.

    THIS IS THE TERM THAT MAKES THE OPPORTUNITY SYSTEM CLOSE, and getting it
    from the position mean instead was the single largest error in this engine.

    Playing time is mostly a fact about role, not about the position. A backup
    quarterback's low games are not an injury signal -- he is healthy and on
    the sideline. Handing him the QB position mean of 14.3 games gave him
    fourteen games at a backup's (correctly high) while-active share, so the
    normalisation that conserves a team's season pool had to take those
    attempts from somebody, and it took them from the starter. Measured: Josh
    Allen at 2,797 passing yards over a full season, roughly 70 yards a game
    light, with nothing anywhere reporting a problem.

    So games come from ``role_games`` -- the mean games played by the Nth
    busiest player in that pool, measured over every team-season available --
    scaled by the player's own durability relative to his position. The role
    curve already embeds average health at that role, so the scaling is a
    ratio, never a second absolute term.

    ``role_games`` is ``None`` only before an ordinal is known (the first pass
    over a roster), in which case the position mean is the right answer.
    """
    ratio = _health_ratio(player, history, league, config)
    if role_games is None:
        base = league.availability.get(player.position, 15.0)
    else:
        base = role_games
    return max(min(base * ratio, float(config.games_in_season)), 0.0)


def _role_games_for(
    key: str,
    ordinals: dict[str, dict[str, int]],
    league: LeagueRates,
) -> float | None:
    """Games implied by the BEST role a player holds across the three pools.

    A pass-catching back is ordinal 2 in carries and ordinal 4 in targets; his
    playing time is set by the better of the two, not the average, because a
    player is on the field for both.
    """
    best: float | None = None
    for pool, ranks in ordinals.items():
        ordinal = ranks.get(key)
        if ordinal is None:
            continue
        curve = league.role_games_curve.get(pool, ())
        if not curve:
            continue
        value = curve[ordinal] if ordinal < len(curve) else 0.0
        if best is None or value > best:
            best = value
    return best


def _apply_role_curve(
    weights: dict[str, float],
    curve: tuple[float, ...],
    strength: float,
) -> dict[str, float]:
    """Pull a team's raw weights toward the league's role-concentration shape.

    The player model decides the ORDER; the curve decides the LEVELS. A weight
    of ``strength=0`` leaves the raw shares untouched and ``strength=1``
    replaces them with the canonical shape entirely, so a team with a genuine
    committee still reads as one -- it is a shrinkage toward the league's
    concentration, not a template stamped over the top.
    """
    if strength <= 0.0 or not curve:
        return dict(weights)
    if sum(max(weight, 0.0) for weight in weights.values()) <= 0:
        return dict(weights)
    # BOTH SIDES ARE WHILE-ACTIVE SHARES, on the same scale, and neither is
    # rescaled here. They do not sum to one and they are not supposed to: a
    # while-active share is measured only over the games a player actually
    # played, so a team whose starter misses time legitimately has shares
    # summing above one. Forcing this vector to sum to one was a real bug --
    # it dragged the canonical 0.97 first-string pass share down to 0.59 and
    # took ~70 passing yards a game off every starting quarterback.
    #
    # The level is set once, downstream, by `_normalise_games_weighted`.
    ordered = sorted(weights.items(), key=lambda item: -item[1])
    adjusted: dict[str, float] = {}
    for ordinal, (key, weight) in enumerate(ordered):
        canonical = curve[ordinal] if ordinal < len(curve) else 0.0
        adjusted[key] = (1.0 - strength) * max(weight, 0.0) + strength * canonical
    return adjusted


def _normalise_games_weighted(
    weights: dict[str, float],
    games: dict[str, float],
    season_games: int,
) -> dict[str, float]:
    """Scale per-game shares so the team's SEASON pool is exactly consumed.

    The constraint is ``sum_i share_i * games_i = season_games``, not
    ``sum_i share_i = 1``. The difference matters: shares here are "while
    active", so a roster that collectively misses games leaves pool unclaimed
    unless the shares of whoever IS on the field rise to absorb it. That is the
    right direction -- someone does take those carries -- though it does
    over-attribute the absorption to the most durable players rather than
    spreading it. A stated approximation, not a hidden one.
    """
    denominator = sum(weight * games.get(key, 0.0) for key, weight in weights.items())
    if denominator <= 0:
        return {key: 0.0 for key in weights}
    scale = season_games / denominator
    return {key: weight * scale for key, weight in weights.items()}


def _projection_inputs(
    season: int,
    team: str,
    league: LeagueRates,
    config: EngineConfig,
    week: int | None,
    depth_chart_as_of: str | None = None,
) -> tuple[list[FantasyPlayer], dict[str, PlayerHistory], RolePriors, TeamVolume]:
    roster = [
        player
        for player in load_fantasy_players(season, depth_chart_as_of=depth_chart_as_of)
        if player.team == team and player.is_active
    ]
    return roster, player_history(season, config), role_priors(season), team_volume(
        season, team, league, config, week
    )


def project_team(
    season: int,
    team: str,
    scoring: ScoringProfile,
    league: LeagueRates | None = None,
    config: EngineConfig = DEFAULT_CONFIG,
    news: Any | None = None,
    week: int | None = None,
    depth_chart_as_of: str | None = None,
) -> list[PlayerProjection]:
    """Project every fantasy-relevant player on one team, plus its D/ST.

    With *week* set the result is a ONE-GAME projection: shares, efficiency and
    role are unchanged, the opponent and game environment are that week's, and
    `games` becomes the probability the player is available rather than a
    season count.
    """
    if league is None:
        league = league_rates(_history_seasons(season, len(config.season_recency_weights)))
    roster, histories, priors, volume = _projection_inputs(
        season, team, league, config, week, depth_chart_as_of
    )
    # Prior-season usage decides which experience group a player's role prior
    # is drawn from -- see `_experience_bucket`.
    history_seasons = _history_seasons(season, 1)
    prior_players = load_season_usage(history_seasons[0])[0] if history_seasons else {}
    if not roster:
        return []
    if week is not None and volume.games == 0:
        return []

    # Shares are always normalised over the SEASON pool -- a one-game
    # projection is a season-rate projection evaluated at one opponent, not a
    # re-solve of the roster over a single game.
    season_games = config.games_in_season
    week_opponent: str | None = None
    if week is not None:
        for game in team_environments(season).get(team) or []:
            if game.week == week:
                week_opponent = game.opponent
                break

    # Resolved up front: the second pass over the roster (expected games) reads
    # `news_availability`, and it runs before the share block below.
    news_share: dict[str, float] = {}
    news_availability: dict[str, float] = {}
    if config.use_news_adjustments and news is not None:
        news_share = dict(getattr(news, "share_multipliers", None) or {})
        news_availability = dict(getattr(news, "availability_multipliers", None) or {})

    games: dict[str, float] = {}
    raw_target: dict[str, float] = {}
    raw_carry: dict[str, float] = {}
    raw_pass: dict[str, float] = {}
    raw_kick: dict[str, float] = {}
    raw_rz_target: dict[str, float] = {}
    raw_gl_carry: dict[str, float] = {}

    for player in roster:
        key = player.player_id or f"noid::{player.name}"
        history = histories.get(player.player_id) if player.player_id else None
        sample = history.weighted_games if history else 0.0
        half = config.share_history_half_games

        raw_target[key] = _blend(
            history.target_share if history else 0.0,
            _role_prior_share(player, priors, "target", prior_players.get(player.player_id)),
            sample,
            half,
        )
        raw_carry[key] = _blend(
            history.carry_share if history else 0.0,
            _role_prior_share(player, priors, "carry", prior_players.get(player.player_id)),
            sample,
            half,
        )
        raw_pass[key] = _blend(
            history.pass_share if history else 0.0,
            _role_prior_share(player, priors, "pass", prior_players.get(player.player_id)),
            sample,
            half,
        )
        # High-leverage shares fall back to the ordinary share when a player has
        # never been in the red zone -- NOT to zero, which would silently make
        # every unproven player touchdown-proof.
        # A kicker has no useful role prior beyond "is he the kicker": teams
        # carry one, and the depth chart's own K rows are sparse. History plus
        # the ordinal curve settles it.
        raw_kick[key] = (
            _blend(
                history.fg_share if history else 0.0,
                _role_prior_share(player, priors, "kick", prior_players.get(player.player_id)),
                sample,
                half,
            )
            if player.position == "K"
            else 0.0
        )
        raw_rz_target[key] = (history.rz_target_share if history and history.rz_target_share > 0 else raw_target[key])
        raw_gl_carry[key] = (history.gl_carry_share if history and history.gl_carry_share > 0 else raw_carry[key])

    # ---- second pass: games come from ROLE, and role is only known once every
    # player on the roster has a raw share to be ranked against. See
    # `_expected_games` for why the position mean is the wrong answer here.
    by_player = {
        (player.player_id or f"noid::{player.name}"): player for player in roster
    }
    ordinals: dict[str, dict[str, int]] = {}
    for pool, weights in (
        ("target", raw_target),
        ("carry", raw_carry),
        ("pass", raw_pass),
        ("kick", raw_kick),
    ):
        ordered = sorted(
            (key for key, weight in weights.items() if weight > 0),
            key=lambda key: -weights[key],
        )
        ordinals[pool] = {key: ordinal for ordinal, key in enumerate(ordered)}

    for key, player in by_player.items():
        history = histories.get(player.player_id) if player.player_id else None
        games[key] = _expected_games(
            player, history, league, config, _role_games_for(key, ordinals, league)
        )
        # Injury designations scale AVAILABILITY and never share. A doubtful
        # running back is not a committee back; he is the same back, less often.
        # Keeping the two apart is why `fantasy_news` returns two mappings.
        injury = news_availability.get(player.player_id)
        if injury is not None:
            games[key] *= injury

    if config.use_news_adjustments and news is not None:
        # Applied BEFORE normalisation, so one player's promotion is paid for by
        # his team-mates rather than inventing volume out of nothing. The pool
        # stays closed either way.
        for key in list(raw_target):
            multiplier = news_share.get(key)
            if multiplier is None:
                continue
            raw_target[key] *= multiplier
            raw_carry[key] *= multiplier
            raw_pass[key] *= multiplier
            raw_rz_target[key] *= multiplier
            raw_gl_carry[key] *= multiplier
            raw_kick[key] *= multiplier

    strength = config.role_curve_strength if config.use_role_curve else 0.0
    shaped_target = _apply_role_curve(raw_target, league.role_curve.get("target", ()), strength)
    shaped_carry = _apply_role_curve(raw_carry, league.role_curve.get("carry", ()), strength)
    shaped_pass = _apply_role_curve(raw_pass, league.role_curve.get("pass", ()), strength)

    target_share = _normalise_games_weighted(shaped_target, games, season_games)
    carry_share = _normalise_games_weighted(shaped_carry, games, season_games)
    pass_share = _normalise_games_weighted(shaped_pass, games, season_games)

    # Touchdown weights: high-leverage opportunity blended with overall volume.
    rz_weight = config.rz_weight_receiving if config.use_red_zone_touchdown_share else 0.0
    gl_weight = config.gl_weight_rushing if config.use_red_zone_touchdown_share else 0.0
    shaped_rz = _apply_role_curve(raw_rz_target, league.role_curve.get("target", ()), strength)
    shaped_gl = _apply_role_curve(raw_gl_carry, league.role_curve.get("carry", ()), strength)
    rec_td_weight = {
        key: rz_weight * shaped_rz[key] + (1.0 - rz_weight) * shaped_target[key]
        for key in shaped_target
    }
    rush_td_weight = {
        key: gl_weight * shaped_gl[key] + (1.0 - gl_weight) * shaped_carry[key]
        for key in shaped_carry
    }
    rec_td_share = _normalise_games_weighted(rec_td_weight, games, season_games)
    rush_td_share = _normalise_games_weighted(rush_td_weight, games, season_games)

    shaped_kick = _apply_role_curve(raw_kick, league.role_curve.get("kick", ()), strength)
    kicker_share = _normalise_games_weighted(shaped_kick, games, season_games)

    projections: list[PlayerProjection] = []
    for player in roster:
        key = player.player_id or f"noid::{player.name}"
        history = histories.get(player.player_id) if player.player_id else None
        player_games = games[key]
        if player_games <= 0:
            continue

        efficiency = league.efficiency_by_position.get(player.position, league.efficiency_by_position.get("WR", {}))

        # ---- volume, per game
        targets = target_share[key] * volume.targets_per_game
        carries = carry_share[key] * volume.carries_per_game
        attempts = pass_share[key] * volume.pass_attempts_per_game

        # ---- efficiency, shrunk to the position mean by the player's own sample
        yards_per_target = _shrink(
            history.yards_per_target if history else 0.0,
            history.target_sample if history else 0.0,
            efficiency.get("yards_per_target", league.yards_per_target),
            config.ypt_prior_opportunities,
        )
        catch_rate = _shrink(
            history.catch_rate if history else 0.0,
            history.target_sample if history else 0.0,
            efficiency.get("catch_rate", league.catch_rate),
            config.catch_rate_prior_opportunities,
        )
        yards_per_carry = _shrink(
            history.yards_per_carry if history else 0.0,
            history.carry_sample if history else 0.0,
            efficiency.get("yards_per_carry", league.yards_per_carry),
            config.ypc_prior_opportunities,
        )
        yards_per_attempt = _shrink(
            history.yards_per_attempt if history else 0.0,
            history.attempt_sample if history else 0.0,
            efficiency.get("yards_per_attempt", league.yards_per_attempt),
            config.ypa_prior_opportunities,
        )
        interception_rate = _shrink(
            history.interception_rate if history else 0.0,
            history.attempt_sample if history else 0.0,
            league.interception_rate,
            config.ypa_prior_opportunities,
        )
        fumble_rate = _shrink(
            history.fumbles_per_touch if history else 0.0,
            (history.carry_sample + history.target_sample) if history else 0.0,
            league.fumbles_per_touch,
            config.ypc_prior_opportunities,
        )

        # ---- touchdowns
        receiving_tds = rec_td_share[key] * volume.pass_tds_per_game
        rushing_tds = rush_td_share[key] * volume.rush_tds_per_game
        passing_tds = pass_share[key] * volume.pass_tds_per_game

        # ---- kicking
        fg_attempts = kicker_share[key] * volume.fg_attempts_per_game
        pat_attempts = kicker_share[key] * volume.offensive_tds_per_game * league.pat_attempts_per_td

        per_game = {
            "passing_yards": attempts * yards_per_attempt,
            "passing_tds": passing_tds,
            "interceptions": attempts * interception_rate,
            "rushing_yards": carries * yards_per_carry,
            "rushing_tds": rushing_tds,
            "receptions": targets * catch_rate,
            "receiving_yards": targets * yards_per_target,
            "receiving_tds": receiving_tds,
            "fumbles_lost": (carries + targets * catch_rate) * fumble_rate,
            "carries": carries,
            "targets": targets,
            "pass_attempts": attempts,
        }
        total_tds = passing_tds + rushing_tds + receiving_tds
        per_game["passing_2pt"] = passing_tds * league.two_point_per_td
        per_game["rushing_2pt"] = rushing_tds * league.two_point_per_td
        per_game["receiving_2pt"] = receiving_tds * league.two_point_per_td
        for bucket in ("0_39", "40_49", "50_plus"):
            bucket_attempts = fg_attempts * league.fg_bucket_share.get(bucket, 0.0)
            per_game[f"fg_made_{bucket}"] = bucket_attempts * league.fg_make_rate.get(bucket, 0.8)
        per_game["fg_missed"] = fg_attempts - sum(
            per_game[f"fg_made_{bucket}"] for bucket in ("0_39", "40_49", "50_plus")
        )
        per_game["pat_made"] = pat_attempts * league.pat_rate
        per_game["pat_missed"] = pat_attempts * (1.0 - league.pat_rate)

        points_per_game = score_stat_line(per_game, scoring)
        if points_per_game <= 0 and total_tds <= 0 and targets + carries + attempts < 0.25:
            # Nothing projects him into a role at all. Dropping him here is safe
            # because normalisation already happened -- his (near-zero) share was
            # counted in the denominator, so removing the ROW does not inflate
            # anyone else.
            continue

        # A one-game projection is scaled by the PROBABILITY he plays, not by a
        # games count -- 15.8 season games means a ~93% chance of suiting up in
        # any given week.
        scale = (player_games / config.games_in_season) if week is not None else player_games
        stat_line = {name: value * scale for name, value in per_game.items()}
        season_points = points_per_game * scale

        variance_intercept, variance_slope = league.variance_fit.get(player.position, (4.0, 0.55))
        points_sd = max(variance_intercept + variance_slope * points_per_game, 0.5)
        availability_rate = player_games / config.games_in_season
        games_variance = config.games_in_season * availability_rate * (1.0 - availability_rate)
        season_sd = math.sqrt(
            player_games * points_sd**2 + (points_per_game**2) * games_variance
        )

        projections.append(
            PlayerProjection(
                player_id=player.player_id or key,
                name=player.name,
                team=team,
                position=player.position,
                season=season,
                games=player_games,
                stat_line=stat_line,
                fantasy_points=season_points,
                points_per_game=points_per_game,
                points_per_game_sd=points_sd,
                season_points_sd=season_sd,
                floor=max(season_points - _P10_Z * season_sd, 0.0),
                ceiling=season_points + _P10_Z * season_sd,
                basis={
                    "environment": volume.environment_basis,
                    "market_lined_games": volume.market_lined_games,
                    "team_points_per_game": round(volume.points_per_game, 2),
                    "share_source": "history" if (history and history.weighted_games >= 4) else "role_prior",
                    "history_seasons": list(history.seasons_used) if history else [],
                    "history_weighted_games": round(history.weighted_games, 1) if history else 0.0,
                    "depth_rank": player.depth_rank,
                    "depth_chart_as_of": player.depth_chart_as_of,
                    "is_rookie": player.is_rookie,
                    "target_share": round(target_share[key], 4),
                    "carry_share": round(carry_share[key], 4),
                    "pass_share": round(pass_share[key], 4),
                    "availability": round(player_games / config.games_in_season, 3),
                },
                week=week,
                opponent=week_opponent,
            )
        )

    projections.append(
        _project_dst(season, team, scoring, league, config, volume, week, week_opponent)
    )
    projections.sort(key=lambda entry: -entry.fantasy_points)
    return projections


def _project_dst(
    season: int,
    team: str,
    scoring: ScoringProfile,
    league: LeagueRates,
    config: EngineConfig,
    volume: TeamVolume,
    week: int | None = None,
    week_opponent: str | None = None,
) -> PlayerProjection:
    """Project one team's D/ST.

    Points allowed comes from the MARKET (the opponent's implied total), which
    is the single largest term in ESPN's D/ST scoring and the one a model has
    least business guessing at. The event rates -- sacks, takeaways, defensive
    touchdowns -- come from the team's own history shrunk to the league mean,
    because they are far noisier year to year than the points-allowed ladder.
    """
    history_seasons = _history_seasons(season, len(config.season_recency_weights))
    weights = config.season_recency_weights
    weighted_games = 0.0
    totals = {
        "def_sacks": 0.0,
        "def_interceptions": 0.0,
        "def_fumble_recoveries": 0.0,
        "def_safeties": 0.0,
        "def_touchdowns": 0.0,
        "def_blocked_kicks": 0.0,
    }
    league_totals = dict.fromkeys(totals, 0.0)
    league_games = 0.0
    for index, history_season in enumerate(history_seasons):
        weight = weights[index] if index < len(weights) else weights[-1]
        _, teams = load_season_usage(history_season)
        for name, entry in teams.items():
            if not entry.games:
                continue
            league_games += weight * entry.games
            for stat in league_totals:
                league_totals[stat] += weight * getattr(entry, stat)
            if name == team:
                weighted_games += weight * entry.games
                for stat in totals:
                    totals[stat] += weight * getattr(entry, stat)

    per_game: dict[str, float] = {}
    for stat in totals:
        league_rate = _safe_divide(league_totals[stat], league_games)
        observed = _safe_divide(totals[stat], weighted_games, league_rate)
        per_game[stat] = _shrink(observed, weighted_games, league_rate, config.team_volume_prior_games)

    line = {
        "dst_sacks": per_game["def_sacks"],
        "dst_interceptions": per_game["def_interceptions"],
        "dst_fumble_recoveries": per_game["def_fumble_recoveries"],
        "dst_safeties": per_game["def_safeties"],
        "dst_touchdowns": per_game["def_touchdowns"],
        "dst_blocked_kicks": per_game["def_blocked_kicks"],
        "dst_points_allowed": volume.points_allowed_per_game,
    }
    points_per_game = score_stat_line(line, scoring)
    games = 1.0 if week is not None else float(volume.games or config.games_in_season)
    season_points = points_per_game * games
    variance_intercept, variance_slope = league.variance_fit.get("DST", (4.5, 0.35))
    points_sd = max(variance_intercept + variance_slope * abs(points_per_game), 0.5)
    season_sd = math.sqrt(games) * points_sd

    return PlayerProjection(
        player_id=f"DST-{team}",
        name=f"{team} D/ST",
        team=team,
        position="DST",
        season=season,
        games=games,
        stat_line={name: value * games for name, value in line.items() if name != "dst_points_allowed"}
        | {"dst_points_allowed": volume.points_allowed_per_game * games},
        fantasy_points=season_points,
        points_per_game=points_per_game,
        points_per_game_sd=points_sd,
        season_points_sd=season_sd,
        floor=season_points - _P10_Z * season_sd,
        ceiling=season_points + _P10_Z * season_sd,
        basis={
            "environment": volume.environment_basis,
            "market_lined_games": volume.market_lined_games,
            "opponent_points_per_game": round(volume.points_allowed_per_game, 2),
            "share_source": "team_history",
            "history_seasons": list(history_seasons),
            "history_weighted_games": round(weighted_games, 1),
        },
        week=week,
        opponent=week_opponent,
    )


def project_season(
    season: int,
    scoring: ScoringProfile,
    config: EngineConfig = DEFAULT_CONFIG,
    news: Any | None = None,
    week: int | None = None,
) -> list[PlayerProjection]:
    """Project every fantasy-relevant player in the league for *season*.

    With *week* set this is the weekly board -- start/sit and waiver-wire
    decisions -- and teams on bye simply produce no rows.
    """
    league = league_rates(_history_seasons(season, len(config.season_recency_weights)))
    teams = sorted({player.team for player in load_fantasy_players(season) if player.team})
    projections: list[PlayerProjection] = []
    for team in teams:
        projections.extend(project_team(season, team, scoring, league, config, news, week))
    projections.sort(key=lambda entry: -entry.fantasy_points)
    return projections


def project_week(
    season: int,
    week: int,
    scoring: ScoringProfile,
    config: EngineConfig = DEFAULT_CONFIG,
    news: Any | None = None,
) -> list[PlayerProjection]:
    """Every player's projection for ONE week of *season*."""
    return project_season(season, scoring, config, news, week=week)
