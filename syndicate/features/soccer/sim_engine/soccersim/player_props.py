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
    # Conditional-on-appearing means: unconditional allocation divided by the
    # player's expected minutes share. Books void player props on DNP, so
    # market prices are conditional on the player playing — these are the
    # values to compare against posted lines.
    expected_shots_if_playing: float = 0.0
    expected_shots_on_target_if_playing: float = 0.0
    expected_goals_if_playing: float = 0.0
    expected_assists_if_playing: float = 0.0
    anytime_scorer_probability_if_playing: float = 0.0

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
        )

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

    # Conditional-on-appearing rescale. Shares already embed expected
    # minutes, so dividing by the minutes share recovers the full-match
    # allocation books price against. Floored to avoid inflating fringe
    # players whose tiny samples make the division meaningless.
    conditioning = max(minutes, 0.25)
    expected_shots_if_playing = expected_shots / conditioning
    expected_shots_on_target_if_playing = expected_shots_on_target / conditioning
    expected_goals_if_playing = expected_goals / conditioning
    expected_assists_if_playing = expected_assists / conditioning

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
        shots_over_probabilities=_over_probabilities(expected_shots, _SHOT_LINES),
        shots_on_target_over_probabilities=_over_probabilities(expected_shots_on_target, _SOT_LINES),
        assists_over_probabilities=_over_probabilities(expected_assists, _ASSIST_LINES),
        expected_shots_if_playing=round(expected_shots_if_playing, 4),
        expected_shots_on_target_if_playing=round(expected_shots_on_target_if_playing, 4),
        expected_goals_if_playing=round(expected_goals_if_playing, 4),
        expected_assists_if_playing=round(expected_assists_if_playing, 4),
        anytime_scorer_probability_if_playing=round(poisson_at_least(expected_goals_if_playing, 1), 4),
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
        weighted_assists.append(_rate(row, ("xa_per90", "assists_per90", "xa", "assists")) * minutes)
    shot_total = sum(weighted_shots) or 1.0
    goal_total = sum(weighted_goals) or 1.0
    assist_total = sum(weighted_assists) or 1.0

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
