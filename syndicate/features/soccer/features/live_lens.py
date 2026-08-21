"""Live-lens: project a match forward from any current state.

Built on ``match_simulator.simulate_match``'s ``initial_state`` hook (a
match can now be resumed from any half/clock/score instead of always
starting at kickoff) and ``ingestion/espn_live_state.build_live_state``
(which reconstructs that current state from ESPN, symmetric between a
truly in-progress match and a completed one truncated at a cutoff for
backtesting -- see ``scripts/backtest_soccer_live_lens.py``).

Three live markets, all from the same resumed Monte Carlo loop:

- ``project_live_match``: updated three-way, totals, BTTS, and corners for
  the *whole* match -- combining what already happened with the simulated
  remainder. Goals/score come for free (the resume state already carries
  the current score forward through every simulated possession); corners
  don't (the resumed possession log only covers the remainder), so those
  are explicitly "already + projected remainder."
- ``project_live_player_props``: same already+remainder combination at the
  player level, allocating the remainder's team shot volume across players
  via ``build_usage_profiles`` (starter-aware when the confirmed lineup is
  known -- it is, this is mid-match).
- ``goal_in_window_probability``: probability of at least one goal in the
  next N minutes, by truncating the resumed simulation's clock instead of
  letting it run to full time.

Red cards get a documented **prior**, not a measured adjustment (unlike
the shot-location work, deriving this from real red-card before/after
data wasn't done this session -- flagged as a natural next step, same
method as the shot-location calibration).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from random import Random
from statistics import mean
from typing import Any

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import CalibrationProfile
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match
from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles
from syndicate.features.soccer.sim_engine.soccersim.player_props import poisson_at_least
from syndicate.features.soccer.sim_engine.soccersim.possession_state import build_initial_possession_state

_RATING_CAP = 0.35
# Measured (not just assumed) from a within-match natural experiment: 55
# single-red-card EPL matches, full 2025-26 season (before/after the card,
# same match/opponent/day -- see
# data/soccer_source/epl/validation/red_card_before_after_samples.csv).
# Opponent scoring rate rose from 0.932 to 1.721 goals/90 after the card
# (1.846x raw). Discounting the generic late-match scoring increase (EPL's
# own half_1/half_2 truth split implies ~1.292x independent of cards)
# leaves an estimated residual, card-specific effect of ~1.428x on the
# opponent's scoring rate.
#
# That residual target turned out to exceed what a rating-shift can
# reproduce within the engine's normal bounds: simulating a fixed mid-match
# scenario at increasing defense penalties tops out around a 1.13x ratio at
# the rating cap (0.35) -- a real, documented limitation, not something
# this session solved. -0.30 is the strongest defensible value within that
# ceiling (directionally correct, uses most of the available lever, but
# undershoots the full measured effect). A more direct mechanism -- e.g.
# suppressing the carded team's possession-retention/turnover priors while
# a man down, rather than only shifting the input rating -- is flagged as
# the way to close the remaining gap, not attempted here.
#
# The attack-side number is NOT set from this measurement: a naive
# before/after comparison showed the carded team's OWN scoring rate more
# than doubling post-card, which is not a usable signal -- red cards
# disproportionately occur when a team is already chasing the game, so
# "after" mixes true man-down effects with normal chasing-a-deficit
# behavior in a way this session's data can't cleanly separate. Kept as a
# documented prior, moderately increased from the original guess to stay
# directionally consistent with general soccer knowledge.
_RED_CARD_ATTACK_PENALTY = 0.18
_RED_CARD_DEFENSE_PENALTY = 0.30


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def apply_red_card_penalty(rating: dict[str, float], red_cards: int) -> dict[str, float]:
    """A red-carded team's rating for the rest of the match. Stacks for a
    (rare) double red; capped at the engine's normal rating bound."""
    if red_cards <= 0:
        return dict(rating)
    adjusted = dict(rating)
    adjusted["attack_rating"] = _clamp(
        rating.get("attack_rating", 0.0) - _RED_CARD_ATTACK_PENALTY * red_cards, -_RATING_CAP, _RATING_CAP
    )
    adjusted["defense_rating"] = _clamp(
        rating.get("defense_rating", 0.0) - _RED_CARD_DEFENSE_PENALTY * red_cards, -_RATING_CAP, _RATING_CAP
    )
    return adjusted


def build_resume_state(live_state: dict[str, Any], *, possession_owner: str = "home", pitch_position: int = 50):
    """A ``PossessionState`` seeded from a live/cutoff state's half, clock,
    and score. Who actually has the ball right now isn't derivable from
    ESPN's event feed, so the starting possession owner/pitch position are
    a neutral default -- across many simulations this single assumption
    washes out; it's not worth the complexity of trying to infer it from
    the most recent event."""
    return build_initial_possession_state(
        home_team=live_state["home_team"],
        away_team=live_state["away_team"],
        owner=possession_owner,
        pitch_position=pitch_position,
        half=int(live_state["half"]),
        clock_remaining=int(round(live_state["clock_remaining"])),
        score_home=int(live_state["score_home"]),
        score_away=int(live_state["score_away"]),
    )


def _possession_owner_corners(possession_log: tuple[dict[str, Any], ...]) -> tuple[int, int]:
    home_corners = 0
    away_corners = 0
    for possession in possession_log:
        start_state = possession.get("start_state") or {}
        owner = str(start_state.get("possession_owner") or "")
        count = int(possession.get("corner_count") or 0)
        if owner == "home":
            home_corners += count
        elif owner == "away":
            away_corners += count
    return home_corners, away_corners


@dataclass(frozen=True)
class LiveMatchProjection:
    simulations: int
    home_win_probability: float
    draw_probability: float
    away_win_probability: float
    projected_final_home_goals: float
    projected_final_away_goals: float
    projected_final_total: float
    over_2_5_probability: float
    both_teams_scored_probability: float
    projected_home_corners: float
    projected_away_corners: float
    projected_total_corners: float
    home_red_card_applied: bool
    away_red_card_applied: bool
    # THE SHAPE, NOT JUST P(OVER 2.5). The resumed sim already produces an exact
    # final scoreline per run and was discarding all of it after counting one
    # threshold, so the live board could price 2.5 and nothing else -- the same
    # limitation the PREGAME artifact had until `scoreline_probabilities` was
    # summed there. Live lines move off 2.5 constantly (a 2-0 at 60' is quoted
    # at 3.5/4.5), so a single-threshold answer is least useful exactly when the
    # live tier matters most.
    scoreline_probabilities: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulations": self.simulations,
            "home_win_probability": self.home_win_probability,
            "draw_probability": self.draw_probability,
            "away_win_probability": self.away_win_probability,
            "projected_final_home_goals": self.projected_final_home_goals,
            "projected_final_away_goals": self.projected_final_away_goals,
            "projected_final_total": self.projected_final_total,
            "over_2_5_probability": self.over_2_5_probability,
            "both_teams_scored_probability": self.both_teams_scored_probability,
            "projected_home_corners": self.projected_home_corners,
            "projected_away_corners": self.projected_away_corners,
            "projected_total_corners": self.projected_total_corners,
            "home_red_card_applied": self.home_red_card_applied,
            "away_red_card_applied": self.away_red_card_applied,
            "scoreline_probabilities": dict(self.scoreline_probabilities),
        }


def project_live_match(
    live_state: dict[str, Any],
    *,
    home_rating: dict[str, float],
    away_rating: dict[str, float],
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
    simulations: int = 300,
    seed: int = 1,
    possession_owner: str = "home",
) -> LiveMatchProjection:
    home_rating = apply_red_card_penalty(home_rating, int(live_state.get("home_red_cards") or 0))
    away_rating = apply_red_card_penalty(away_rating, int(live_state.get("away_red_cards") or 0))
    already_home_corners = int(live_state.get("home_corners_so_far") or 0)
    already_away_corners = int(live_state.get("away_corners_so_far") or 0)

    home_wins = draws = away_wins = over_2_5 = both_scored = 0
    scorelines: dict[str, int] = {}
    final_home_goals: list[float] = []
    final_away_goals: list[float] = []
    final_home_corners: list[float] = []
    final_away_corners: list[float] = []

    for offset in range(max(1, simulations)):
        run_seed = seed + offset
        resume_state = build_resume_state(live_state, possession_owner=possession_owner)
        simulation_input = SoccerSimSimulationInput(
            home_team=live_state["home_team"],
            away_team=live_state["away_team"],
            seed=run_seed,
            home_attack_rating=home_rating.get("attack_rating", 0.0),
            home_defense_rating=home_rating.get("defense_rating", 0.0),
            away_attack_rating=away_rating.get("attack_rating", 0.0),
            away_defense_rating=away_rating.get("defense_rating", 0.0),
        )
        output = simulate_match(simulation_input, rng=Random(run_seed), profile=profile, initial_state=resume_state)
        final_home = int(output.final_score["home"])
        final_away = int(output.final_score["away"])
        final_home_goals.append(float(final_home))
        final_away_goals.append(float(final_away))
        if final_home > final_away:
            home_wins += 1
        elif final_away > final_home:
            away_wins += 1
        else:
            draws += 1
        scorelines[f"{final_home}-{final_away}"] = scorelines.get(f"{final_home}-{final_away}", 0) + 1
        if final_home + final_away >= 3:
            over_2_5 += 1
        if final_home > 0 and final_away > 0:
            both_scored += 1
        remainder_home_corners, remainder_away_corners = _possession_owner_corners(output.possession_log)
        final_home_corners.append(float(already_home_corners + remainder_home_corners))
        final_away_corners.append(float(already_away_corners + remainder_away_corners))

    n = max(1, simulations)
    mean_home_goals = mean(final_home_goals)
    mean_away_goals = mean(final_away_goals)
    return LiveMatchProjection(
        simulations=n,
        home_win_probability=round(home_wins / n, 4),
        draw_probability=round(draws / n, 4),
        away_win_probability=round(away_wins / n, 4),
        projected_final_home_goals=round(mean_home_goals, 4),
        projected_final_away_goals=round(mean_away_goals, 4),
        projected_final_total=round(mean_home_goals + mean_away_goals, 4),
        over_2_5_probability=round(over_2_5 / n, 4),
        both_teams_scored_probability=round(both_scored / n, 4),
        projected_home_corners=round(mean(final_home_corners), 4),
        projected_away_corners=round(mean(final_away_corners), 4),
        projected_total_corners=round(mean(final_home_corners) + mean(final_away_corners), 4),
        home_red_card_applied=int(live_state.get("home_red_cards") or 0) > 0,
        away_red_card_applied=int(live_state.get("away_red_cards") or 0) > 0,
        # Rounded to the same 4dp as every other probability here, and NOT
        # pruned: a scoreline the sim never produced is absent rather than
        # zero, so a consumer can tell "outside the simulated support" from
        # "simulated and never happened" -- the distinction
        # `_total_prob_from_scorelines` refuses a line on.
        scoreline_probabilities={k: round(v / n, 4) for k, v in sorted(scorelines.items())},
    )


def goal_in_window_probability(
    live_state: dict[str, Any],
    *,
    home_rating: dict[str, float],
    away_rating: dict[str, float],
    window_seconds: float,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
    simulations: int = 300,
    seed: int = 1,
    possession_owner: str = "home",
) -> float:
    """P(at least one goal in the next ``window_seconds``), from the live
    state forward. Truncates the resumed clock at
    ``min(clock_remaining, window_seconds)`` and caps ``halves`` at the
    current half, so the simulation stops at the window's edge instead of
    continuing into a later half -- windows that would cross a half
    boundary are silently clamped to "rest of this half" rather than
    spanning into the next one (a scope boundary, not a bug: "goal in the
    next N minutes" asks are normally well within a half).
    """
    home_rating = apply_red_card_penalty(home_rating, int(live_state.get("home_red_cards") or 0))
    away_rating = apply_red_card_penalty(away_rating, int(live_state.get("away_red_cards") or 0))
    truncated_clock = min(float(live_state["clock_remaining"]), max(0.0, window_seconds))
    already_home = int(live_state["score_home"])
    already_away = int(live_state["score_away"])

    scored = 0
    n = max(1, simulations)
    for offset in range(n):
        run_seed = seed + offset
        resume_state = build_resume_state(
            {**live_state, "clock_remaining": truncated_clock}, possession_owner=possession_owner
        )
        simulation_input = SoccerSimSimulationInput(
            home_team=live_state["home_team"],
            away_team=live_state["away_team"],
            seed=run_seed,
            halves=int(live_state["half"]),  # don't simulate beyond the current (truncated) half
            home_attack_rating=home_rating.get("attack_rating", 0.0),
            home_defense_rating=home_rating.get("defense_rating", 0.0),
            away_attack_rating=away_rating.get("attack_rating", 0.0),
            away_defense_rating=away_rating.get("defense_rating", 0.0),
        )
        output = simulate_match(simulation_input, rng=Random(run_seed), profile=profile, initial_state=resume_state)
        if int(output.final_score["home"]) > already_home or int(output.final_score["away"]) > already_away:
            scored += 1
    return round(scored / n, 4)


@dataclass(frozen=True)
class LivePlayerPropProjection:
    player_id: str
    player_name: str
    side: str
    shots_so_far: int
    projected_remainder_shots: float
    projected_final_shots: float
    shots_over_probabilities: dict[str, float] = field(default_factory=dict)
    # LIVE PARITY WITH PREGAME. The pregame artifact prices shots, shots on
    # target AND assists per line; live carried shots only, so a board that
    # priced three prop markets before kickoff silently dropped to one the
    # moment a match went in play -- the opposite of what a live tier is for.
    shots_on_target_so_far: int = 0
    projected_final_shots_on_target: float = 0.0
    shots_on_target_over_probabilities: dict[str, float] = field(default_factory=dict)
    assists_so_far: int = 0
    projected_final_assists: float = 0.0
    assists_over_probabilities: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "side": self.side,
            "shots_so_far": self.shots_so_far,
            "projected_remainder_shots": self.projected_remainder_shots,
            "projected_final_shots": self.projected_final_shots,
            "shots_over_probabilities": dict(self.shots_over_probabilities),
            "shots_on_target_so_far": self.shots_on_target_so_far,
            "projected_final_shots_on_target": self.projected_final_shots_on_target,
            "shots_on_target_over_probabilities": dict(self.shots_on_target_over_probabilities),
            "assists_so_far": self.assists_so_far,
            "projected_final_assists": self.projected_final_assists,
            "assists_over_probabilities": dict(self.assists_over_probabilities),
        }


_SHOT_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
# IMPORTED, NOT RESTATED. These define what the PREGAME tier means by an
# assist line and by "share of goals that are assisted". A second copy here
# would let the two tiers drift into answering the same market with different
# constants, which is the failure mode this repo has paid for repeatedly --
# `live_gameline_join` says it plainly: "a second copy of this rule is how the
# first one rotted".
from syndicate.features.soccer.sim_engine.soccersim.player_props import (  # noqa: E402
    _ASSIST_LINES,
    _ASSISTED_GOAL_SHARE,
)


def project_live_player_props(
    live_state: dict[str, Any],
    *,
    home_rating: dict[str, float],
    away_rating: dict[str, float],
    home_player_rows: list[dict[str, Any]],
    away_player_rows: list[dict[str, Any]],
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
    simulations: int = 300,
    seed: int = 1,
    possession_owner: str = "home",
) -> tuple[LivePlayerPropProjection, ...]:
    """Already-accumulated shots this match + a starter-aware allocation of
    the *projected remainder* team shot volume from a resumed Monte Carlo
    loop. Uses the confirmed lineup automatically: mid-match, who started
    is no longer in question, so every player in ``*_player_rows`` who
    accumulated any minutes is treated as a starter for allocation
    purposes (pass only players who actually appeared)."""
    home_rating = apply_red_card_penalty(home_rating, int(live_state.get("home_red_cards") or 0))
    away_rating = apply_red_card_penalty(away_rating, int(live_state.get("away_red_cards") or 0))

    home_remainder_shots: list[float] = []
    away_remainder_shots: list[float] = []
    # Assists derive from GOALS, not shots -- pregame computes
    # `team_goals * _ASSISTED_GOAL_SHARE * assist_share`, and reusing that
    # formula is what keeps the two tiers answering the same question. The
    # resumed sim's final score minus the score already on the board is the
    # REMAINDER, which is the only part still to be allocated.
    home_remainder_goals: list[float] = []
    away_remainder_goals: list[float] = []
    score_home_now = int(live_state.get("score_home") or 0)
    score_away_now = int(live_state.get("score_away") or 0)
    for offset in range(max(1, simulations)):
        run_seed = seed + offset
        resume_state = build_resume_state(live_state, possession_owner=possession_owner)
        simulation_input = SoccerSimSimulationInput(
            home_team=live_state["home_team"],
            away_team=live_state["away_team"],
            seed=run_seed,
            home_attack_rating=home_rating.get("attack_rating", 0.0),
            home_defense_rating=home_rating.get("defense_rating", 0.0),
            away_attack_rating=away_rating.get("attack_rating", 0.0),
            away_defense_rating=away_rating.get("defense_rating", 0.0),
        )
        output = simulate_match(simulation_input, rng=Random(run_seed), profile=profile, initial_state=resume_state)
        home_shots = sum(
            1
            for p in output.possession_log
            if str((p.get("start_state") or {}).get("possession_owner")) == "home" and p.get("shot_taken")
        )
        away_shots = sum(
            1
            for p in output.possession_log
            if str((p.get("start_state") or {}).get("possession_owner")) == "away" and p.get("shot_taken")
        )
        home_remainder_shots.append(float(home_shots))
        away_remainder_shots.append(float(away_shots))
        home_remainder_goals.append(max(0.0, float(int(output.final_score["home"]) - score_home_now)))
        away_remainder_goals.append(max(0.0, float(int(output.final_score["away"]) - score_away_now)))

    mean_home_remainder = mean(home_remainder_shots) if home_remainder_shots else 0.0
    mean_away_remainder = mean(away_remainder_shots) if away_remainder_shots else 0.0
    mean_home_remainder_goals = mean(home_remainder_goals) if home_remainder_goals else 0.0
    mean_away_remainder_goals = mean(away_remainder_goals) if away_remainder_goals else 0.0

    projections: list[LivePlayerPropProjection] = []
    for side, rows, team_remainder, team_remainder_goals in (
        ("home", home_player_rows, mean_home_remainder, mean_home_remainder_goals),
        ("away", away_player_rows, mean_away_remainder, mean_away_remainder_goals),
    ):
        if not rows:
            continue
        starters = {str(row.get("player_id")) for row in rows}
        usage_profiles = build_usage_profiles(rows, side=side, starters=starters)
        for profile_row in usage_profiles:
            stats = live_state.get("player_stats", {}).get(profile_row.player_id, {}) or {}
            already = int(stats.get("shots_so_far") or 0)
            remainder = team_remainder * profile_row.shot_share
            final_mean = already + remainder

            # SHOTS ON TARGET. Pregame:
            # `expected_shots_on_target = expected_shots * on_target_rate`,
            # with the player's own rate clamped to [0.05, 0.80] and a 0.33
            # fallback. Reused verbatim so the two tiers cannot answer the same
            # market with different arithmetic.
            rate = profile_row.on_target_rate
            on_target_rate = min(0.80, max(0.05, float(rate))) if rate is not None else 0.33
            sot_already = int(stats.get("shots_on_target_so_far") or 0)
            sot_remainder = remainder * on_target_rate

            # ASSISTS come from GOALS, not shots. Pregame:
            # `team_goals * _ASSISTED_GOAL_SHARE * assist_share`. Applied to the
            # sim's REMAINDER goals, because assists already recorded are
            # banked and only the rest is still to be allocated.
            assists_already = int(stats.get("assists_so_far") or 0)
            assist_remainder = (
                team_remainder_goals
                * _ASSISTED_GOAL_SHARE
                * min(1.0, max(0.0, float(profile_row.assist_share or 0.0)))
            )

            def _over(remaining: float, banked: int, lines) -> dict[str, float]:
                # `int(line + 0.5)` is the smallest whole count that CLEARS the
                # line; subtracting what is banked leaves what still has to
                # happen. A player already past the line needs 0 more, and
                # `poisson_at_least(x, 0)` is 1.0 -- which is correct and is why
                # this is not clamped away.
                return {
                    f"{line:g}": round(poisson_at_least(remaining, max(0, int(line + 0.5) - banked)), 4)
                    for line in lines
                }

            projections.append(
                LivePlayerPropProjection(
                    player_id=profile_row.player_id,
                    player_name=profile_row.player_name,
                    side=side,
                    shots_so_far=already,
                    projected_remainder_shots=round(remainder, 4),
                    projected_final_shots=round(final_mean, 4),
                    shots_over_probabilities=_over(remainder, already, _SHOT_LINES),
                    shots_on_target_so_far=sot_already,
                    projected_final_shots_on_target=round(sot_already + sot_remainder, 4),
                    shots_on_target_over_probabilities=_over(sot_remainder, sot_already, _SHOT_LINES),
                    assists_so_far=assists_already,
                    projected_final_assists=round(assists_already + assist_remainder, 4),
                    assists_over_probabilities=_over(assist_remainder, assists_already, _ASSIST_LINES),
                )
            )
    return tuple(projections)


__all__ = [
    "LiveMatchProjection",
    "LivePlayerPropProjection",
    "apply_red_card_penalty",
    "build_resume_state",
    "goal_in_window_probability",
    "project_live_match",
    "project_live_player_props",
]
