"""Run-level context for the native smart-sim orchestrator (plan P6).

The vendored orchestrator read two module GLOBALS, and Syndicate patched both
for the length of every call:

  * ``paths``  -- the vendored ``config.paths`` singleton. The bridge pinned the
    smart_sim module's copy to the processed root. ``connected_game``,
    ``boxscores`` and ``prob_calibration`` read their OWN unpinned copy, which
    resolved ``NBA_BETTING_DATA_ROOT`` / ``WNBA_BETTING_DATA_ROOT``. On the fleet
    both resolve to ``<league>_source/data`` (measured 2026-10-09 on the
    refresh-worker env), the same root.
  * ``LEAGUE`` -- the WNBA fork's ``league.LEAGUE``. The NBA fork had none and
    wrote NBA numbers inline.

Here both are ONE explicit, hashable parameter, ``orch``: an ``OrchestratorEnv``
that every function needing either takes as a keyword. It is hashable so the
``lru_cache``d loaders key on it, which makes the processed root part of the
cache key. The vendored caches were keyed on arguments only and silently assumed
one root per process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SmartSimPaths:
    """The roots the orchestrator reads. All of them derive from the processed root."""

    root: Path  # <league>_source
    data_root: Path  # <league>_source/data
    data_processed: Path
    data_raw: Path

    @classmethod
    def from_processed_root(cls, processed_root: Path) -> "SmartSimPaths":
        processed_root = Path(processed_root)
        # The bridge's derivation, unchanged (`_build_local_smart_sim_module`).
        source_root = processed_root.parent.parent if processed_root.parent.name.lower() == "data" else processed_root.parent
        return cls(
            root=source_root,
            data_root=processed_root.parent,
            data_processed=processed_root,
            data_raw=source_root / "data" / "raw",
        )


@dataclass(frozen=True)
class OrchestratorLeague:
    """The orchestrator's league constants.

    Field names follow the WNBA fork's ``LeagueConfig`` wherever the vendored
    code read one (``regulation_team_minutes``, ``baseline_pace``, ...). The NBA
    fork inlined NBA literals in the same places; the NBA instance carries those
    literals, so each expression evaluates to the vendored NBA number.
    """

    code: str
    regulation_team_minutes: float
    regulation_period_seconds: int
    overtime_period_seconds: int
    # NBA fork: 98.0 / 112.0 / 112.0 inline (pace floor `max(90.0, ...)` == 98 - 8,
    # default `possessions_per_game` 98.0, fallback TeamContext 98 / 112 / 112).
    baseline_pace: float
    baseline_off_rating: float
    baseline_def_rating: float
    # The bound on `possessions_per_game * team_adv pace_mult`. NBA fork: np.clip(..., 88.0, 112.0);
    # WNBA fork: (baseline_pace - 8.0, baseline_pace + 10.0). Not one formula, so two fields.
    poss_clip_lo: float
    poss_clip_hi: float
    # ESPN (boxscores.py).
    espn_sport_path: str
    user_agent_product: str
    espn_tri_fix: tuple[tuple[str, str], ...]  # our tricode -> ESPN abbreviation (`_tri_to_espn`)
    espn_abbr_fix: tuple[tuple[str, str], ...]  # ESPN abbreviation -> our tricode (`_espn_to_tri`)
    # WNBA-fork-only steps. The NBA fork has neither.
    prune_pregame_pool: bool  # `_prune_pregame_rotation_pool` + `ctx.pregame_rotation_pool`
    stamp_team_opponent: bool  # `_stamp_team_opponent` on the players block


NBA = OrchestratorLeague(
    code="nba",
    regulation_team_minutes=240.0,
    regulation_period_seconds=12 * 60,
    overtime_period_seconds=5 * 60,
    baseline_pace=98.0,
    baseline_off_rating=112.0,
    baseline_def_rating=112.0,
    poss_clip_lo=88.0,
    poss_clip_hi=112.0,
    espn_sport_path="sports/basketball/nba",
    user_agent_product="nba-betting/1.0",
    espn_tri_fix=(("GSW", "GS"), ("NOP", "NO"), ("NYK", "NY"), ("UTA", "UTAH"), ("WAS", "WSH"), ("SAS", "SA"), ("PHX", "PHO")),
    espn_abbr_fix=(("GS", "GSW"), ("NO", "NOP"), ("NY", "NYK"), ("UTAH", "UTA"), ("WSH", "WAS"), ("SA", "SAS"), ("PHO", "PHX")),
    prune_pregame_pool=False,
    stamp_team_opponent=False,
)

# The vendored WNBA `league.LEAGUE` values (wnba_betting/league.py), copied by value.
WNBA = OrchestratorLeague(
    code="wnba",
    regulation_team_minutes=200.0,
    regulation_period_seconds=10 * 60,
    overtime_period_seconds=5 * 60,
    baseline_pace=79.5,
    baseline_off_rating=101.5,
    baseline_def_rating=101.5,
    poss_clip_lo=79.5 - 8.0,
    poss_clip_hi=79.5 + 10.0,
    espn_sport_path="sports/basketball/wnba",
    user_agent_product="wnba-betting/1.0",
    espn_tri_fix=(("GSV", "GS"), ("LVA", "LV"), ("LAS", "LA"), ("NYL", "NY")),
    espn_abbr_fix=(("GS", "GSV"), ("LV", "LVA"), ("LA", "LAS"), ("NY", "NYL"), ("WSH", "WSH")),
    prune_pregame_pool=True,
    stamp_team_opponent=True,
)


def orchestrator_league(code: str | None) -> OrchestratorLeague:
    """League constants by code. The bridge's mapping: "wnba" -> WNBA, anything else -> NBA.

    NCAAB is a HOOK, not a league yet: plan P4 has no player model, so there is nothing for a
    player-level orchestrator to aggregate. It refuses by name rather than borrowing NBA numbers.
    """
    c = str(code or "").strip().lower()
    if c == "ncaab":
        raise NotImplementedError("orchestrator_league('ncaab'): no NCAAB orchestrator constants (plan P4 has no player model)")
    return WNBA if c == "wnba" else NBA


@dataclass(frozen=True)
class OrchestratorEnv:
    """Everything the orchestrator used to read from module globals, passed explicitly.

    ``draw_sink`` collects one compact record per possession-engine draw (the
    bridge's ``_recording_sim_draws_local``). It is excluded from hashing and
    equality, so the cached loaders treat two runs on the same root alike.
    """

    league_code: str
    paths: SmartSimPaths
    league: OrchestratorLeague
    draw_sink: list = field(default_factory=list, compare=False, hash=False, repr=False)

    @classmethod
    def for_processed_root(cls, processed_root: Path, league_code: str, draw_sink: list[Any] | None = None) -> "OrchestratorEnv":
        # The code is kept as the caller gave it: the bridge's ports receive it verbatim, as they did when the
        # replacement lambdas closed over it.
        return cls(
            league_code=str(league_code or "nba"),
            paths=SmartSimPaths.from_processed_root(processed_root),
            league=orchestrator_league(league_code),
            draw_sink=draw_sink if draw_sink is not None else [],
        )
