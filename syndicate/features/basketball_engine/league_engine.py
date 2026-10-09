"""One league's possession engine as a single object: its switches, its helpers, its lineup sampler.

THE SEAM PRODUCTION AND TOOLING SHARE (lane basketball-native-engine, plan P1).
``basketball_props_smart_sim._engine_for_league_local(code)`` returns one of
these per league. The smart sim calls ``engine.simulate_pbp_game_boxscore(...)``
on every draw.

Vendored code used to reach the engine through ``<pkg>.sim.events``: tests and
the calibration sweep toggled its module globals (``events.BLOCK_MODE =
"legacy"``) and production patched its ``_sample_lineup``. This object keeps the
first idiom against the engine that actually runs. Each switch is an attribute
under its vendored name, and assigning one swaps in
``dataclasses.replace(params, ...)``. The lineup sampler is a constructor
argument, passed into every call, so no global is patched. An attribute that is
neither a switch, a helper nor an engine entrypoint RAISES. A misspelt switch
used to be a silent no-op on a module, and it cannot be one here.
"""

from __future__ import annotations

from dataclasses import field, fields, make_dataclass, replace
from functools import partial
from typing import Any, Callable, Optional

from . import engine as _engine
from .league import LeagueParams

# Vendored module-global name -> LeagueParams field.
SWITCHES: dict[str, str] = {
    "SHOOTER_FT_RATE": "shooter_ft_rate",
    "FOULED_MISS_NOT_FGA": "fouled_miss_not_fga",
    "EXACT_TARGET_CALIBRATION": "exact_target_calibration",
    "TEAM_PRIOR_STACKS_ON_TARGET": "team_prior_stacks_on_target",
    "TOV_PER_ATTEMPT": "tov_per_attempt",
    "PLAYER_REBOUND_CREDIT": "player_rebound_credit",
    "OREB_PLAYER_CREDIT": "oreb_player_credit",
    "DREB_PLAYER_CREDIT": "dreb_player_credit",
    "BLOCK_MODE": "block_mode",
    "LEAGUE_BLOCKS_PER_MISSED_2PA": "league_blocks_per_missed_2pa",
    "BLOCK_RATE_ASSUMED_FG3_PCT": "block_rate_assumed_fg3_pct",
    "BLOCK_ALLOC_BY_RATE": "block_alloc_by_rate",
    "BLOCK_ALLOC_FLOOR_PM": "block_alloc_floor_pm",
}
assert set(SWITCHES.values()) <= {f.name for f in fields(LeagueParams)}

# Helpers that take the league (bound here); the rest are league-free and exposed as-is.
_LEAGUE_BOUND = ("_team_rates_from_priors", "_rotation_windows", "_team_block_rate_on_missed_2pa", "_block_drawn", "_player_rebound_credited", "_player_usage_weights")
_LEAGUE_FREE = (
    "EventSimConfig",
    "sample_lineup_minutes_weighted",
    "_safe_series",
    "_pick_weighted",
    "_starter_like_scores",
    "_scoring_like_scores",
    "_contextual_minutes_weights",
    "_contextual_duration_scale",
    "_player_pct",
    "_ft_rate_multipliers",
    "_iterations_per_possession",
    "_loop_points_per_possession",
    "_loop_shot_share",
    "_solve_eff_mult",
    "_expected_points_per_possession",
)
_ENTRYPOINTS = ("simulate_pbp_game_boxscore", "simulate_event_level_boxscore")


_CONFIG_CLASSES: dict[float, type] = {}


def _league_config_class(pace: float) -> type:
    """EventSimConfig with the league's default pace. The vendored WNBA EventSimConfig defaulted to LEAGUE.baseline_pace."""
    if pace not in _CONFIG_CLASSES:
        if pace == 98.0:
            _CONFIG_CLASSES[pace] = _engine.EventSimConfig
        else:
            _CONFIG_CLASSES[pace] = make_dataclass(
                f"EventSimConfig_pace{str(pace).replace('.', '_')}",
                [("possessions_per_game", float, field(default=pace))],
                bases=(_engine.EventSimConfig,),
            )
    return _CONFIG_CLASSES[pace]


class LeagueEngine:
    def __init__(self, params: LeagueParams, *, sample_lineup: Optional[Callable[..., Any]] = None):
        object.__setattr__(self, "params", params)
        object.__setattr__(self, "sample_lineup", sample_lineup)

    def __getattr__(self, name: str) -> Any:
        params: LeagueParams = object.__getattribute__(self, "params")
        if name in SWITCHES:
            return getattr(params, SWITCHES[name])
        if name in _ENTRYPOINTS:
            return partial(getattr(_engine, name), league=params, sample_lineup=object.__getattribute__(self, "sample_lineup"))
        if name in _LEAGUE_BOUND:
            return partial(getattr(_engine, name), lp=params)
        if name == "EventSimConfig":
            return _league_config_class(float(params.default_possessions_per_game))
        if name in _LEAGUE_FREE:
            return getattr(_engine, name)
        raise AttributeError(f"LeagueEngine({params.code}) has no switch, helper or entrypoint {name!r}")

    def __setattr__(self, name: str, value: Any) -> None:
        if name in SWITCHES:
            object.__setattr__(self, "params", replace(object.__getattribute__(self, "params"), **{SWITCHES[name]: value}))
            return
        if name in ("params", "sample_lineup"):
            object.__setattr__(self, name, value)
            return
        raise AttributeError(f"{name!r} is not an engine switch; switches are {sorted(SWITCHES)}")

    def __repr__(self) -> str:
        return f"LeagueEngine({self.params.code})"
