"""SoccerSim player prop projections.

Allocates the Monte Carlo team-level distribution (goals, shots, shots on
target, penalties) down to individual players using each player's usage
profile, and prices the standard soccer player-prop markets:

- anytime / 2+ goalscorer
- player shots and shots on target (0.5 / 1.5 / 2.5 / 3.5 lines)
- player assists
- goalkeeper saves

Counts are modeled as Poisson around the allocated player mean, which is
the standard pricing model for low-count soccer player markets. Usage
shares are minutes-adjusted shares of team volume that sum to ~1.0 across
the squad (``build_usage_profiles`` produces them from per-90 rates and
expected minutes), so allocating ``team_volume * share`` distributes the
whole simulated team output with rotation risk already priced in.
``expected_minutes_share`` only rescales goalkeeper saves (and is carried
through for reporting); it must not be re-applied to outfield shares.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from math import exp
from typing import Any

from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary

_SHOT_LINES = (0.5, 1.5, 2.5, 3.5)
_SOT_LINES = (0.5, 1.5, 2.5)
_ASSIST_LINES = (0.5, 1.5)
_SAVE_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)

# Share of goals that are assisted (league-typical), used to convert team
# goals into an assistable pool.
_ASSISTED_GOAL_SHARE = 0.72
#: The rate keys `assist_share` and `on_pitch_assist_share` both read, in order.
_ASSIST_RATE_KEYS = ("xa_per90", "assists_per90", "xa", "assists")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def poisson_at_least(mean: float, k: int) -> float:
    """P(X >= k) for X ~ Poisson(mean)."""
    if mean <= 0.0:
        return 0.0 if k > 0 else 1.0
    cumulative = 0.0
    term = exp(-mean)
    for i in range(k):
        if i > 0:
            term *= mean / i
        cumulative += term
    return _clamp(1.0 - cumulative, 0.0, 1.0)


def _over_probabilities(mean: float, lines: tuple[float, ...]) -> dict[str, float]:
    return {f"{line:g}": round(poisson_at_least(mean, int(line + 0.5)), 4) for line in lines}


# CONDITIONAL-ON-APPEARING shot ladder (lane soccer-player-role-allocation).
# Books void a shot prop on a DNP, so the price is P(over | the player appears):
# a START/SUB MIXTURE, not a Poisson over the unconditional mean, which carries
# the DNP mass and under-states every player who does appear.
#
# Minutes per start and per sub appearance: least squares over 1,240 ESPN-league
# outfield players (2026 files). Substitute intensity: fitted on dates before
# 2026-08-26 and scored after. Held out, on production's own inputs, the mixture
# beat the unconditional ladder in 9/10 leagues:
#   shots log loss at P(>=1) / P(>=2): 0.611 / 0.469, against 0.641 / 0.517
#   shots on target:                   0.493 / 0.199, against 0.512 / 0.215
_MINUTES_PER_START = 83.1
_MINUTES_PER_SUB_APPEARANCE = 15.6
_SUB_SHOT_INTENSITY = 1.8
#: Substitute scoring intensity per minute, relative to a starter's. Fitted for
#: GOALS by H17 and separate from the shot constant on purpose: they happen to
#: share a value today, and tying them would silently move one when the other is
#: re-fitted.
_SUB_GOAL_INTENSITY = 1.8
#: Substitute ASSIST intensity per minute, relative to a starter's. H33 reused the
#: goals value rather than fitting one, and a TRAIN-fitted level scale on top of it
#: landed on exactly 1.00. Its own constant for the reason the goal one is.
_SUB_ASSIST_INTENSITY = 1.8
_START_PRIOR_WEIGHT = 2.0

#: WHICH QUESTION A PROBABILITY ANSWERS (`#673`). A book voids a player prop on a
#: DNP, so the settled quantity is P(over | the player appears). Every probability
#: field is stamped with one of these in `PlayerPropProjection.ladder_conditioning`,
#: so a reader never has to infer it from the numbers.
CONDITIONAL_ON_APPEARING = "appearing"
UNCONDITIONAL = "unconditional"


def _mixture_over_probabilities(
    components: tuple[tuple[float, float], ...], lines: tuple[float, ...]
) -> dict[str, float]:
    """P(X > line) for X a weighted mixture of Poissons, given ((weight, mean), ...)."""
    return {
        f"{line:g}": round(
            _clamp(sum(weight * poisson_at_least(mean, int(line + 0.5)) for weight, mean in components), 0.0, 1.0),
            4,
        )
        for line in lines
    }


@dataclass(frozen=True)
class PlayerUsageProfile:
    player_id: str
    player_name: str
    side: str  # "home" | "away"
    position: str = ""
    team: str = ""
    expected_minutes_share: float = 1.0
    shot_share: float = 0.0
    goal_share: float = 0.0
    assist_share: float = 0.0
    on_target_rate: float | None = None
    penalty_taker: bool = False
    set_piece_taker: bool = False
    is_goalkeeper: bool = False
    # Conditional-on-appearing inputs, both set by `build_usage_profiles`.
    # `start_probability` is P(start | appears). `on_pitch_shot_share` is the
    # player's share of team shots PER FULL MATCH ON THE PITCH: his rate over the
    # side's minutes-weighted rate, with minutes scoped to one season. If either
    # is None, `project_player_props` prices the unconditional ladder.
    start_probability: float | None = None
    on_pitch_shot_share: float | None = None
    # `on_pitch_goal_share` is the same quantity for GOALS, and it exists for the
    # same reason: dividing by the minutes share recovers a full-match allocation
    # only if the player plays full matches. H17 measured the mixture against that
    # division on held-out dates: pooled log loss 0.2716 -> 0.2673 and the level
    # 1.14 -> 0.96 (MLS 1.36 -> 1.04), in 9 of 10 leagues.
    on_pitch_goal_share: float | None = None
    # And for ASSISTS (`#673`, H33): the assists ladder is priced on the same
    # mixture, over the same season-scoped on-pitch minutes.
    on_pitch_assist_share: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "side": self.side,
            "position": self.position,
            "team": self.team,
            "expected_minutes_share": self.expected_minutes_share,
            "shot_share": self.shot_share,
            "goal_share": self.goal_share,
            "assist_share": self.assist_share,
            "on_target_rate": self.on_target_rate,
            "penalty_taker": self.penalty_taker,
            "set_piece_taker": self.set_piece_taker,
            "is_goalkeeper": self.is_goalkeeper,
            "start_probability": self.start_probability,
            "on_pitch_shot_share": self.on_pitch_shot_share,
            "on_pitch_goal_share": self.on_pitch_goal_share,
            "on_pitch_assist_share": self.on_pitch_assist_share,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PlayerPropProjection:
    player_id: str
    player_name: str
    side: str
    position: str
    team: str
    expected_minutes_share: float
    expected_shots: float
    expected_shots_on_target: float
    expected_goals: float
    expected_assists: float
    anytime_scorer_probability: float
    two_or_more_scorer_probability: float
    goal_or_assist_probability: float
    shots_over_probabilities: dict[str, float]
    shots_on_target_over_probabilities: dict[str, float]
    assists_over_probabilities: dict[str, float]
    expected_saves: float | None = None
    saves_over_probabilities: dict[str, float] = field(default_factory=dict)
    # Conditional-on-appearing means. Books void player props on a DNP, so
    # market prices are conditional on the player playing. When the profile
    # carries role inputs, shots, shots on target, goals and assists are the
    # start/sub mixture's mean, and the shots, shots-on-target and assists ladders
    # above are P(over | appears) as well. Without role inputs each is the
    # unconditional allocation divided by the player's expected minutes share.
    expected_shots_if_playing: float = 0.0
    expected_shots_on_target_if_playing: float = 0.0
    expected_goals_if_playing: float = 0.0
    expected_assists_if_playing: float = 0.0
    anytime_scorer_probability_if_playing: float = 0.0
    # `#673`: probability field -> CONDITIONAL_ON_APPEARING or UNCONDITIONAL, as
    # computed for THIS row. The two answer different questions, and the
    # artifact never said which it held.
    ladder_conditioning: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "side": self.side,
            "position": self.position,
            "team": self.team,
            "expected_minutes_share": self.expected_minutes_share,
            "expected_shots": self.expected_shots,
            "expected_shots_on_target": self.expected_shots_on_target,
            "expected_goals": self.expected_goals,
            "expected_assists": self.expected_assists,
            "anytime_scorer_probability": self.anytime_scorer_probability,
            "two_or_more_scorer_probability": self.two_or_more_scorer_probability,
            "goal_or_assist_probability": self.goal_or_assist_probability,
            "shots_over_probabilities": dict(self.shots_over_probabilities),
            "shots_on_target_over_probabilities": dict(self.shots_on_target_over_probabilities),
            "assists_over_probabilities": dict(self.assists_over_probabilities),
            "expected_saves": self.expected_saves,
            "saves_over_probabilities": dict(self.saves_over_probabilities),
            "expected_shots_if_playing": self.expected_shots_if_playing,
            "expected_shots_on_target_if_playing": self.expected_shots_on_target_if_playing,
            "expected_goals_if_playing": self.expected_goals_if_playing,
            "expected_assists_if_playing": self.expected_assists_if_playing,
            "anytime_scorer_probability_if_playing": self.anytime_scorer_probability_if_playing,
            "ladder_conditioning": dict(self.ladder_conditioning),
        }


def _team_volumes(distribution: MatchDistributionSummary, side: str) -> tuple[float, float, float]:
    if side == "home":
        return distribution.mean_home_goals, distribution.mean_home_shots, distribution.mean_home_shots_on_target
    return distribution.mean_away_goals, distribution.mean_away_shots, distribution.mean_away_shots_on_target


def _opponent_volumes(distribution: MatchDistributionSummary, side: str) -> tuple[float, float]:
    if side == "home":
        return distribution.mean_away_goals, distribution.mean_away_shots_on_target
    return distribution.mean_home_goals, distribution.mean_home_shots_on_target


def project_player_props(
    distribution: MatchDistributionSummary,
    usage_profile: PlayerUsageProfile,
) -> PlayerPropProjection:
    minutes = _clamp(float(usage_profile.expected_minutes_share), 0.0, 1.0)
    team_goals, team_shots, team_shots_on_target = _team_volumes(distribution, usage_profile.side)

    if usage_profile.is_goalkeeper:
        opponent_goals, opponent_on_target = _opponent_volumes(distribution, usage_profile.side)
        expected_saves = max(0.0, (opponent_on_target - opponent_goals)) * minutes
        return PlayerPropProjection(
            player_id=usage_profile.player_id,
            player_name=usage_profile.player_name,
            side=usage_profile.side,
            position=usage_profile.position or "GK",
            team=usage_profile.team,
            expected_minutes_share=round(minutes, 4),
            expected_shots=0.0,
            expected_shots_on_target=0.0,
            expected_goals=0.0,
            expected_assists=0.0,
            anytime_scorer_probability=0.0,
            two_or_more_scorer_probability=0.0,
            goal_or_assist_probability=0.0,
            shots_over_probabilities={},
            shots_on_target_over_probabilities={},
            assists_over_probabilities={},
            expected_saves=round(expected_saves, 4),
            saves_over_probabilities=_over_probabilities(expected_saves, _SAVE_LINES),
            # Opponent shots on target scaled by the keeper's minutes share.
            ladder_conditioning={"saves_over_probabilities": UNCONDITIONAL},
        )

    # THE SINGLE CHOKE POINT FOR THE SHOT MEAN. Everything shot-derived below
    # reads `expected_shots`: shots-on-target (`* on_target_rate`), the
    # conditional-on-appearing rescale, and every `_over_probabilities` ladder.
    #
    # NO DIVISOR. A 1.393 shrinkage divided this from 2026-08-31 to 2026-09-15.
    # Its fit read stale squads as a level error. On appeared players, season to
    # date, it made the shot ladder WORSE in 10/10 leagues (log loss 0.690 / 0.570
    # at 0.5 / 1.5, against 0.632 / 0.498 without it), so it was retired with its
    # loader and fitter. Lane soccer-player-role-allocation;
    # `tests/test_soccer_player_role_ladder.py` keeps the old artifact inert.
    expected_shots = team_shots * _clamp(usage_profile.shot_share, 0.0, 1.0)
    team_on_target_rate = (team_shots_on_target / team_shots) if team_shots > 0 else 0.33
    on_target_rate = (
        _clamp(float(usage_profile.on_target_rate), 0.05, 0.80)
        if usage_profile.on_target_rate is not None
        else _clamp(team_on_target_rate, 0.05, 0.80)
    )
    expected_shots_on_target = expected_shots * on_target_rate

    expected_goals = team_goals * _clamp(usage_profile.goal_share, 0.0, 1.0)
    if usage_profile.penalty_taker:
        # Penalty takers absorb the team's spot-kick expectation; a modest
        # additive nudge reflecting ~0.1 penalty goals/team/match at even
        # allocation elsewhere in the goal_share.
        expected_goals += 0.03
    expected_assists = team_goals * _ASSISTED_GOAL_SHARE * _clamp(usage_profile.assist_share, 0.0, 1.0)
    if usage_profile.set_piece_taker:
        expected_assists += 0.02

    anytime = poisson_at_least(expected_goals, 1)
    two_plus = poisson_at_least(expected_goals, 2)
    # Goal and assist means are correlated through team goals; the additive
    # union bound is close enough at these magnitudes for a projection seam.
    goal_or_assist = _clamp(1.0 - (1.0 - anytime) * (1.0 - poisson_at_least(expected_assists, 1)), 0.0, 1.0)

    # Conditional-on-appearing rescale for goals and assists. Shares already
    # embed expected minutes, so dividing by the minutes share recovers the
    # full-match allocation. Floored to avoid inflating fringe players whose
    # tiny samples make the division meaningless.
    conditioning = max(minutes, 0.25)

    # ASSISTS ARE PRICED ON THE SAME START/SUB MIXTURE AS GOALS (`#673`, H33).
    # They were the one count ladder still priced on the UNCONDITIONAL mean, so
    # the board priced shots "if he plays" and assists "whether or not he plays"
    # beside each other, for markets a book settles the same way (void on a DNP).
    # H33, pre-registered and held out (dates >= 2026-08-26, 9,810 appeared
    # outfield rows, `scripts/soccer_season_audit/assists_conditioning.py`):
    # P(assists >= 1) log loss 0.2366 unconditional -> 0.2309 mixture, 0.2331 for
    # the division below; better in 9 of 10 leagues (EPL the loss); level
    # 0.74 -> 0.93; line 1.5 0.0313 -> 0.0293. The substitute intensity is the
    # GOALS constant reused, not re-fitted: the TRAIN fit of a level scale landed
    # on exactly 1.00. The set-piece bonus stays on the unconditional mean only,
    # as the penalty bonus does for goals.
    if usage_profile.start_probability is not None and usage_profile.on_pitch_assist_share is not None:
        full_match_assists = team_goals * _ASSISTED_GOAL_SHARE * _clamp(float(usage_profile.on_pitch_assist_share), 0.0, 1.0)
        assist_p_start = _clamp(float(usage_profile.start_probability), 0.0, 1.0)
        assist_components = (
            (assist_p_start, full_match_assists * _MINUTES_PER_START / 90.0),
            (1.0 - assist_p_start, _SUB_ASSIST_INTENSITY * full_match_assists * _MINUTES_PER_SUB_APPEARANCE / 90.0),
        )
        expected_assists_if_playing = sum(weight * mean for weight, mean in assist_components)
        assists_ladder = _mixture_over_probabilities(assist_components, _ASSIST_LINES)
        assists_conditioning = CONDITIONAL_ON_APPEARING
    else:
        expected_assists_if_playing = expected_assists / conditioning
        assists_ladder = _over_probabilities(expected_assists, _ASSIST_LINES)
        assists_conditioning = UNCONDITIONAL

    # GOALS ARE PRICED ON THE SAME START/SUB MIXTURE AS SHOTS whenever the role
    # inputs exist. The division below cannot be right for a substitute: it asks
    # what a player would score in a FULL match and then prices it as though he is
    # certain to play one. H17, held out: pooled log loss 0.2716 -> 0.2673 in 9 of
    # 10 leagues, and the level 1.14 -> 0.96 -- the over-prediction was the
    # conditioning, not a scale, which is why H18 (a fitted level constant) was
    # FALSIFIED at c = 1.05 and no constant ships.
    #
    # TWO DELIBERATE DIFFERENCES from the unconditional path, both stated because
    # they are the kind of thing that otherwise looks like a bug later:
    #   * the penalty taker's +0.03 stays on the unconditional mean only. The arm
    #     H17 measured built the mixture from rates alone.
    #   * assists were deliberately left on the old division by this change, because
    #     H17 measured goals only. They moved to the mixture later, on their own
    #     measurement (H33, `#673`; the assists block above).
    if usage_profile.start_probability is not None and usage_profile.on_pitch_goal_share is not None:
        full_match_goals = team_goals * _clamp(float(usage_profile.on_pitch_goal_share), 0.0, 1.0)
        goal_p_start = _clamp(float(usage_profile.start_probability), 0.0, 1.0)
        goal_components = (
            (goal_p_start, full_match_goals * _MINUTES_PER_START / 90.0),
            (1.0 - goal_p_start, _SUB_GOAL_INTENSITY * full_match_goals * _MINUTES_PER_SUB_APPEARANCE / 90.0),
        )
        expected_goals_if_playing = sum(weight * mean for weight, mean in goal_components)
        anytime_if_playing = sum(weight * poisson_at_least(mean, 1) for weight, mean in goal_components)
    else:
        expected_goals_if_playing = expected_goals / conditioning
        anytime_if_playing = poisson_at_least(expected_goals_if_playing, 1)

    # SHOTS AND SHOTS ON TARGET are priced CONDITIONAL ON APPEARING whenever
    # `build_usage_profiles` supplied the role inputs: a start/sub mixture at the
    # player's on-pitch rate. So `shots_over_probabilities` is P(over | appears),
    # the quantity a book settles. A profile built without role inputs keeps the
    # unconditional ladder and the old `/ max(minutes, 0.25)` mean.
    if usage_profile.start_probability is not None and usage_profile.on_pitch_shot_share is not None:
        full_match_shots = team_shots * _clamp(float(usage_profile.on_pitch_shot_share), 0.0, 1.0)
        p_start = _clamp(float(usage_profile.start_probability), 0.0, 1.0)
        shot_components = (
            (p_start, full_match_shots * _MINUTES_PER_START / 90.0),
            (1.0 - p_start, _SUB_SHOT_INTENSITY * full_match_shots * _MINUTES_PER_SUB_APPEARANCE / 90.0),
        )
        sot_components = tuple((weight, mean * on_target_rate) for weight, mean in shot_components)
        expected_shots_if_playing = sum(weight * mean for weight, mean in shot_components)
        expected_shots_on_target_if_playing = expected_shots_if_playing * on_target_rate
        shots_ladder = _mixture_over_probabilities(shot_components, _SHOT_LINES)
        shots_on_target_ladder = _mixture_over_probabilities(sot_components, _SOT_LINES)
        shots_conditioning = CONDITIONAL_ON_APPEARING
    else:
        expected_shots_if_playing = expected_shots / conditioning
        expected_shots_on_target_if_playing = expected_shots_on_target / conditioning
        shots_ladder = _over_probabilities(expected_shots, _SHOT_LINES)
        shots_on_target_ladder = _over_probabilities(expected_shots_on_target, _SOT_LINES)
        shots_conditioning = UNCONDITIONAL

    return PlayerPropProjection(
        player_id=usage_profile.player_id,
        player_name=usage_profile.player_name,
        side=usage_profile.side,
        position=usage_profile.position,
        team=usage_profile.team,
        expected_minutes_share=round(minutes, 4),
        expected_shots=round(expected_shots, 4),
        expected_shots_on_target=round(expected_shots_on_target, 4),
        expected_goals=round(expected_goals, 4),
        expected_assists=round(expected_assists, 4),
        anytime_scorer_probability=round(anytime, 4),
        two_or_more_scorer_probability=round(two_plus, 4),
        goal_or_assist_probability=round(goal_or_assist, 4),
        shots_over_probabilities=shots_ladder,
        shots_on_target_over_probabilities=shots_on_target_ladder,
        assists_over_probabilities=assists_ladder,
        expected_shots_if_playing=round(expected_shots_if_playing, 4),
        expected_shots_on_target_if_playing=round(expected_shots_on_target_if_playing, 4),
        expected_goals_if_playing=round(expected_goals_if_playing, 4),
        expected_assists_if_playing=round(expected_assists_if_playing, 4),
        anytime_scorer_probability_if_playing=round(anytime_if_playing, 4),
        ladder_conditioning={
            "shots_over_probabilities": shots_conditioning,
            "shots_on_target_over_probabilities": shots_conditioning,
            "assists_over_probabilities": assists_conditioning,
            # Poisson on the unconditional goal mean, always. The board prices this
            # field by user decision (2026-09-15/16); `_if_playing` is the other one.
            "anytime_scorer_probability": UNCONDITIONAL,
            "anytime_scorer_probability_if_playing": CONDITIONAL_ON_APPEARING,
            "two_or_more_scorer_probability": UNCONDITIONAL,
            "goal_or_assist_probability": UNCONDITIONAL,
        },
    )


def project_team_player_props(
    distribution: MatchDistributionSummary,
    usage_profiles: list[PlayerUsageProfile] | tuple[PlayerUsageProfile, ...],
) -> tuple[PlayerPropProjection, ...]:
    return tuple(project_player_props(distribution, profile) for profile in usage_profiles)


def player_row_key(row: dict[str, Any], index: int, side: str) -> str:
    """The identity key ``build_usage_profiles`` uses per row -- exported so
    callers building a ``starters`` set (e.g. a lineup-confirmation source,
    or a depth-chart heuristic) can key it identically."""
    player_id = row.get("player_id") or row.get("id")
    if player_id:
        return str(player_id)
    name = row.get("player_name") or row.get("name")
    if name:
        return f"name:{str(name).strip().lower()}"
    return f"{side}_{index}"


def build_usage_profiles(
    players: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    side: str,
    team: str = "",
    starters: set[str] | None = None,
    bench_minutes_share: float = 0.15,
) -> tuple[PlayerUsageProfile, ...]:
    """Build normalized usage profiles from raw per-90 player rows.

    Expected row keys (all optional, sensible fallbacks): ``player_id``,
    ``player_name``, ``position``, ``expected_minutes_share`` (or
    ``minutes_share``), ``shots_per90``, ``xg_per90`` (or ``goals_per90``),
    ``xa_per90`` (or ``assists_per90``), ``shot_on_target_rate``,
    ``penalty_taker``, ``set_piece_taker``, ``is_goalkeeper``, ``is_starter``.

    Shares are normalized across the provided squad weighted by expected
    minutes, so the rows only need to be internally comparable rates.

    **Starter awareness.** Season-long per-90 rates alone dilute a squad's
    volume across everyone who saw the field that season, including fringe
    players who won't feature in this match -- validated against live MLS
    prop lines, this was the single largest source of the model's remaining
    level gap versus books (which price against the actual expected
    lineup). Two ways to correct it, in priority order:

    1. Pass ``starters``: a set of player_id values (or, for rows without
       an id, ``"name:<lowercased player_name>"``) for this fixture's
       confirmed/projected lineup. Bench rows get scaled down to
       ``bench_minutes_share`` of their season rate instead of being
       dropped, so unexpected minutes (an early sub) still get a small
       nonzero projection rather than none.
    2. If ``starters`` is omitted but any row carries an ``is_starter``
       flag (a lineup source tagged the data upstream), that flag is used
       the same way automatically.

    With neither, minutes shares fall back to season rates unmodified --
    identical to the pre-starter-awareness behavior.
    """

    def _rate(row: dict[str, Any], keys: tuple[str, ...]) -> float:
        for key in keys:
            value = row.get(key)
            try:
                if value is None or str(value).strip() == "":
                    continue
                return max(0.0, float(value))
            except Exception:
                continue
        return 0.0

    def _minutes(row: dict[str, Any]) -> float:
        value = _rate(row, ("expected_minutes_share", "minutes_share", "minutes_pct"))
        return _clamp(value if value > 0 else 1.0, 0.0, 1.0)

    row_keys = [player_row_key(row, index, side) for index, row in enumerate(players)]
    starter_set = starters
    if starter_set is None and any(row.get("is_starter") is not None for row in players):
        starter_set = {key for key, row in zip(row_keys, players) if row.get("is_starter")}
    bench_discount = _clamp(bench_minutes_share, 0.0, 1.0)

    def _lineup_adjusted_minutes(row: dict[str, Any], key: str) -> float:
        season_minutes = _minutes(row)
        if starter_set is None:
            return season_minutes
        if key in starter_set:
            return max(season_minutes, 0.75)
        return season_minutes * bench_discount

    weighted_shots = []
    weighted_goals = []
    weighted_assists = []
    for row, key in zip(players, row_keys):
        minutes = _lineup_adjusted_minutes(row, key)
        weighted_shots.append(_rate(row, ("shots_per90", "shots")) * minutes)
        weighted_goals.append(_rate(row, ("xg_per90", "goals_per90", "xg", "goals")) * minutes)
        weighted_assists.append(_rate(row, _ASSIST_RATE_KEYS) * minutes)
    shot_total = sum(weighted_shots) or 1.0
    goal_total = sum(weighted_goals) or 1.0
    assist_total = sum(weighted_assists) or 1.0

    # ROLE INPUTS FOR THE CONDITIONAL SHOT LADDER, kept OFF the shares above.
    # Team-minutes weights made the UNCONDITIONAL ladder worse (big five 0.644 ->
    # 0.664). The shares above also allocate goals and assists, which were not
    # re-measured.
    #
    # On-pitch minutes share: a row with `games` and `minutes` (Understat) is
    # measured against its SIDE'S match count IN ITS OWN SEASON. A side mixes a
    # current row with prior-season rows. Taking one match count across all of
    # them (a 38-game season against a 4-game player) pushed the big five's shot
    # means to 1.15-1.67x actual; scoped per season they read 0.75-0.93x. Other
    # rows' `expected_minutes_share` is already a team share (ESPN, ASA).
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number == number else None

    season_match_count: dict[str, float] = {}
    for row in players:
        games = _number(row.get("games"))
        if games:
            season_key = str(row.get("season"))
            season_match_count[season_key] = max(season_match_count.get(season_key, 0.0), games)

    on_pitch_minutes: list[float] = []
    for row in players:
        games, played = _number(row.get("games")), _number(row.get("minutes"))
        matches = season_match_count.get(str(row.get("season")), 0.0)
        if games and played is not None and matches > 0:
            on_pitch_minutes.append(_minutes({"expected_minutes_share": played / (matches * 90.0)}))
        else:
            on_pitch_minutes.append(_minutes(row))
    on_pitch_total = sum(
        _rate(row, ("shots_per90", "shots")) * share for row, share in zip(players, on_pitch_minutes)
    )
    # The goal equivalent, over the SAME season-scoped on-pitch minutes. Kept off
    # `goal_share` above, which still allocates the unconditional mean.
    on_pitch_goal_total = sum(
        _rate(row, ("xg_per90", "goals_per90", "xg", "goals")) * share
        for row, share in zip(players, on_pitch_minutes)
    )
    # And for assists, with the same keys `assist_share` reads (`#673`, H33).
    on_pitch_assist_total = sum(
        _rate(row, _ASSIST_RATE_KEYS) * share for row, share in zip(players, on_pitch_minutes)
    )

    def _start_probability(row: dict[str, Any], key: str, on_pitch_share: float) -> float:
        """P(start | appears). A confirmed lineup decides it outright."""
        if starter_set is not None:
            return 1.0 if key in starter_set else 0.0
        prior = _clamp(on_pitch_share / (_MINUTES_PER_START / 90.0), 0.05, 0.95)
        appearances, starts = _number(row.get("appearances")), _number(row.get("starts"))
        if appearances and starts is not None:
            return (starts + _START_PRIOR_WEIGHT * prior) / (appearances + _START_PRIOR_WEIGHT)
        games, played = _number(row.get("games")), _number(row.get("minutes"))
        if games and played is not None:
            return _clamp(
                (played / games - _MINUTES_PER_SUB_APPEARANCE) / (_MINUTES_PER_START - _MINUTES_PER_SUB_APPEARANCE),
                0.02,
                0.98,
            )
        return prior

    profiles: list[PlayerUsageProfile] = []
    for index, row in enumerate(players):
        on_target = row.get("shot_on_target_rate")
        try:
            on_target_rate = float(on_target) if on_target is not None and str(on_target).strip() != "" else None
        except Exception:
            on_target_rate = None
        profiles.append(
            PlayerUsageProfile(
                player_id=str(row.get("player_id") or row.get("id") or f"{side}_{index}"),
                player_name=str(row.get("player_name") or row.get("name") or f"Player {index + 1}"),
                side=side,
                position=str(row.get("position") or ""),
                team=team or str(row.get("team") or ""),
                expected_minutes_share=_lineup_adjusted_minutes(row, row_keys[index]),
                shot_share=weighted_shots[index] / shot_total,
                goal_share=weighted_goals[index] / goal_total,
                assist_share=weighted_assists[index] / assist_total,
                on_target_rate=on_target_rate,
                penalty_taker=bool(row.get("penalty_taker")),
                set_piece_taker=bool(row.get("set_piece_taker")),
                is_goalkeeper=bool(row.get("is_goalkeeper")) or str(row.get("position") or "").upper() == "GK",
                start_probability=_start_probability(row, row_keys[index], on_pitch_minutes[index]),
                on_pitch_shot_share=(
                    _rate(row, ("shots_per90", "shots")) / on_pitch_total if on_pitch_total > 0 else 0.0
                ),
                on_pitch_goal_share=(
                    _rate(row, ("xg_per90", "goals_per90", "xg", "goals")) / on_pitch_goal_total
                    if on_pitch_goal_total > 0
                    else 0.0
                ),
                on_pitch_assist_share=(
                    _rate(row, _ASSIST_RATE_KEYS) / on_pitch_assist_total if on_pitch_assist_total > 0 else 0.0
                ),
                metadata={key: value for key, value in row.items() if key not in {"player_id", "player_name"}},
            )
        )
    return tuple(profiles)


__all__ = [
    "PlayerPropProjection",
    "PlayerUsageProfile",
    "build_usage_profiles",
    "poisson_at_least",
    "project_player_props",
    "project_team_player_props",
]
