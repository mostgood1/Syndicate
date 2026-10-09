"""What the bridge's ports see as ``smart_sim_module``: a read-only VIEW, built per call.

The ports in ``basketball_props_smart_sim.py`` (``_apply_player_priors_local``,
``_rotation_sim_minutes_for_team_local``, ...) take a ``smart_sim_module`` and
``getattr`` helpers off it: ``_read_rotation_stints``, ``_frame_series``,
``paths``, ``LEAGUE``, and so on. They used to receive the vendored module,
mid-patch. During that patched call a getattr of a REPLACED name returned the
replacement, so ``getattr(m, "_derive_sim_minutes")`` gave the Syndicate port,
not the vendored body.

The view reproduces exactly that, without mutating anything:
  * a native helper that needs ``orch`` is bound to it (``functools.partial``);
  * a replaced name resolves to its ``hooks`` adapter, bound the same way;
  * ``paths`` is ``orch.paths``;
  * ``LEAGUE`` exists only for WNBA, as it did (only the WNBA fork exported it;
    ``_smart_sim_league_local`` falls back to the bridge's own config without it).
"""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace

from . import hooks, prop_ladders, smart_sim
from .league_config import LEAGUE as _WNBA_LEAGUE_CONFIG
from .runtime import OrchestratorEnv

# The names the bridge's ports read off ``smart_sim_module``
# (tests/test_basketball_orchestrator_reachability.py derives the set from the
# bridge's source and fails if a port reads a name the view does not carry).
VIEW_NAMES: tuple[str, ...] = (
    "_boolish_series",
    "_bounded_split_multiplier",
    "_build_player_minutes_from_stints",
    "_cap_and_redistribute_minutes",
    "_clean_id_str",
    "_first_minutes_signal",
    "_frame_numeric_series",
    "_frame_series",
    "_load_boxscores_history_processed",
    "_load_player_logs_processed",
    "_matchup_home_flag",
    "_matchup_opponent",
    "_minutes_caps_from_team_df",
    "_minutes_priors_from_player_logs",
    "_norm_player_key",
    "_normalize_position",
    "_opponent_position_rate_context_from_player_logs",
    "_parse_min_to_float",
    "_read_hist_any",
    "_read_rotation_stints",
    "_regularize_rotation_minutes",
    "_roll_minutes_unscaled",
    "_rotation_minutes_signal_guardrail",
    "_safe_float",
    "_scale_minutes_to_target",
    "_season_roster_positions",
    "_weighted_positive_mean",
)


# Not cached: `orch` equality ignores `draw_sink`, so a cached view could carry another game's sink.
def module_view(orch: OrchestratorEnv) -> SimpleNamespace:
    attrs: dict[str, object] = {}
    for name in VIEW_NAMES:
        fn = getattr(smart_sim, name)
        attrs[name] = partial(fn, orch=orch) if name in smart_sim.ORCH_THREADED else fn
    for name in hooks.HOOK_NAMES:
        attrs[name] = partial(getattr(hooks, name), orch=orch)
    attrs["paths"] = orch.paths
    attrs["build_exact_ladder_payload"] = prop_ladders.build_exact_ladder_payload
    attrs["simulate_smart_game"] = partial(smart_sim.simulate_smart_game, orch=orch)
    if orch.league.code == "wnba":
        attrs["LEAGUE"] = _WNBA_LEAGUE_CONFIG
    return SimpleNamespace(**attrs)
