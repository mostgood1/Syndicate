"""The orchestrator's calls into Syndicate's own ports: DIRECT calls, no patched globals.

Until plan P6, ``basketball_props_smart_sim._call_source_simulate_smart_game_local``
built a ``replacements`` dict of lambdas and ``setattr``-ed each one onto the
VENDORED ``smart_sim`` module for the length of one ``simulate_smart_game`` call,
restoring the originals in a ``finally``. The vendored bodies of those 29 names
never ran in production; the Syndicate ports did.

This module is that dict, written out as functions. Each one keeps the exact
signature its lambda had (which is the vendored call signature) plus a
keyword-only ``orch`` (``runtime.OrchestratorEnv``), and calls the same port with
the same arguments. The generated ``smart_sim.py`` imports these names in place
of its own dead definitions and passes ``orch=orch`` at every call.

The ports stay in ``basketball_props_smart_sim.py``, where their lanes own them.
That module imports this package, so it is imported here at CALL time
(``_b()``); the attribute is read at call time too, which keeps P1's per-draw
recorder (it rebinds ``_simulate_pbp_game_boxscore_local``) working.
"""

from __future__ import annotations

from typing import Any

from .runtime import OrchestratorEnv


def _b():
    from syndicate.features.shared import basketball_props_smart_sim

    return basketball_props_smart_sim


def _processed_root(orch: OrchestratorEnv):
    return orch.paths.data_processed


def _view(orch: OrchestratorEnv):
    from .view import module_view

    return module_view(orch)


def _period_lines_from_processed(date_str, home_tri, away_tri, *, orch: OrchestratorEnv):
    return _b()._period_lines_from_processed_local(processed_root=_processed_root(orch), date_str=date_str, home_tri=home_tri, away_tri=away_tri)


def _market_lines_from_processed_odds(date_str, home_tri, away_tri, *, orch: OrchestratorEnv):
    return _b()._market_lines_from_processed_odds_local(processed_root=_processed_root(orch), date_str=date_str, home_tri=home_tri, away_tri=away_tri)


def _load_smartsim_total_calibration(*, orch: OrchestratorEnv):
    return _b()._load_smartsim_total_calibration_local(processed_root=_processed_root(orch))


def _team_players_from_props(props_df, team_tri, opp_tri, *, orch: OrchestratorEnv):
    return _b()._team_players_from_props_local(props_df=props_df, team_tri=team_tri, opp_tri=opp_tri)


def _coalesce_team_player_frames(*frames, orch: OrchestratorEnv):
    return _b()._coalesce_team_player_frames_local(*frames)


def _infer_game_id(date_str, home_tri, away_tri, *, orch: OrchestratorEnv):
    return _b()._infer_game_id_local(processed_root=_processed_root(orch), date_str=date_str, home_tri=home_tri, away_tri=away_tri)


def _team_players_from_processed_boxscores(date_str, home_tri, away_tri, team_tri, game_id=None, *, orch: OrchestratorEnv):
    return _b()._team_players_from_processed_boxscores_local(
        processed_root=_processed_root(orch), date_str=date_str, home_tri=home_tri, away_tri=away_tri, team_tri=team_tri, game_id=game_id
    )


def _team_players_from_processed_rosters(date_str, home_tri, away_tri, team_tri, *, orch: OrchestratorEnv):
    return _b()._team_players_from_processed_rosters_local(
        processed_root=_processed_root(orch), date_str=date_str, home_tri=home_tri, away_tri=away_tri, team_tri=team_tri
    )


def _filter_team_players_against_processed_roster(team_df, date_str, home_tri, away_tri, team_tri, min_keep=5, *, orch: OrchestratorEnv):
    return _b()._filter_team_players_against_processed_roster_local(
        processed_root=_processed_root(orch),
        team_df=team_df,
        date_str=date_str,
        home_tri=home_tri,
        away_tri=away_tri,
        team_tri=team_tri,
        min_keep=min_keep,
    )


def _team_players_from_espn_boxscore(date_str, home_tri, away_tri, team_tri, event_id=None, *, orch: OrchestratorEnv):
    return _b()._team_players_from_espn_boxscore_local(
        processed_root=_processed_root(orch),
        league_code=orch.league_code,
        date_str=date_str,
        home_tri=home_tri,
        away_tri=away_tri,
        team_tri=team_tri,
        event_id=event_id,
    )


def _espn_name_to_id_map_for_game(date_str, home_tri, away_tri, event_id=None, *, orch: OrchestratorEnv):
    return _b()._espn_name_to_id_map_for_game_local(
        smart_sim_module=_view(orch), date_str=date_str, home_tri=home_tri, away_tri=away_tri, event_id=event_id
    )


def _merge_pregame_expected_minutes_for_team(team_df, date_str, team_tri, *, orch: OrchestratorEnv):
    return _b()._merge_pregame_expected_minutes_for_team_local(
        processed_root=_processed_root(orch), team_df=team_df, date_str=date_str, team_tri=team_tri
    )


def _prune_pregame_rotation_pool(team_df, team_tri, min_keep=8, max_keep=None, protected_names=None, *, orch: OrchestratorEnv):
    return _b()._prune_pregame_rotation_pool_local(
        team_df=team_df,
        team_tri=team_tri,
        min_keep=min_keep,
        max_keep=max_keep,
        protected_names=protected_names,
        league_code=orch.league_code,
    )


def _market_player_names_for_matchup(props_df, date_str=None, home_tri="", away_tri="", *, orch: OrchestratorEnv):
    processed_root = _processed_root(orch)
    return _b()._market_player_names_for_matchup_local(
        processed_root=processed_root,
        raw_root=processed_root.parent / "raw",
        props_df=props_df,
        date_str=date_str,
        home_tri=home_tri,
        away_tri=away_tri,
    )


def _rotation_sim_minutes_from_history(team_df, date_str, home_tri, away_tri, team_tri, lookback_days=28, *, orch: OrchestratorEnv):
    return _b()._rotation_sim_minutes_from_history_local(
        smart_sim_module=_view(orch),
        league_code=orch.league_code,
        team_df=team_df,
        date_str=date_str,
        home_tri=home_tri,
        away_tri=away_tri,
        team_tri=team_tri,
        lookback_days=lookback_days,
    )


def _player_split_rate_context(date_str, team_tri, lookback_days=120, *, orch: OrchestratorEnv):
    return _b()._player_split_rate_context_local(smart_sim_module=_view(orch), date_str=date_str, team_tri=team_tri, lookback_days=lookback_days)


def _player_career_opponent_rate_context(date_str, lookback_days=720, *, orch: OrchestratorEnv):
    return _b()._player_career_opponent_rate_context_local(smart_sim_module=_view(orch), date_str=date_str, lookback_days=lookback_days)


def _opponent_position_rate_context(date_str, lookback_days=120, *, orch: OrchestratorEnv):
    return _b()._opponent_position_rate_context_local(smart_sim_module=_view(orch), date_str=date_str, lookback_days=lookback_days)


def simulate_pbp_game_boxscore(*, orch: OrchestratorEnv, **inner_kwargs: Any):
    """One possession-engine draw (P1's native engine), recorded into ``orch.draw_sink``.

    The bridge publishes the distributions it rebuilds from these records
    (``_attach_sim_distributions_local``).
    """
    b = _b()
    league_code = orch.league_code
    draw = b._recording_sim_draws_local(
        lambda **kw: b._simulate_pbp_game_boxscore_local(league_code=league_code, **kw),
        orch.draw_sink,
    )
    return draw(**inner_kwargs)


def simulate_event_level_boxscore(*, orch: OrchestratorEnv, **inner_kwargs: Any):
    return _b()._simulate_event_level_boxscore_local(league_code=orch.league_code, **inner_kwargs)


def _rotation_sim_minutes_for_team(team_df, date_str, home_tri, away_tri, team_tri, side, game_id, *, orch: OrchestratorEnv):
    return _b()._rotation_sim_minutes_for_team_local(
        smart_sim_module=_view(orch),
        league_code=orch.league_code,
        team_df=team_df,
        date_str=date_str,
        home_tri=home_tri,
        away_tri=away_tri,
        team_tri=team_tri,
        side=side,
        game_id=game_id,
    )


def _apply_player_priors(team_df, priors, team_tri, sim_minutes=None, date_str=None, *, orch: OrchestratorEnv):
    return _b()._apply_player_priors_local(
        smart_sim_module=_view(orch),
        team_df=team_df,
        priors=priors,
        team_tri=team_tri,
        sim_minutes=sim_minutes,
        date_str=date_str,
        league_code=orch.league_code,
    )


def _compute_player_priors_cached(asof_date_str, days_back, *, orch: OrchestratorEnv):
    return _b()._compute_player_priors_cached_local(processed_root=_processed_root(orch), asof_date_str=asof_date_str, days_back=days_back)


def _derive_sim_minutes(team_df, date_str=None, team_tri=None, *, orch: OrchestratorEnv):
    """Bench-first shrink to regulation minutes (``_derive_sim_minutes_local``)."""
    return _b()._derive_sim_minutes_local(
        smart_sim_module=_view(orch), team_df=team_df, date_str=date_str, team_tri=team_tri, league_code=orch.league_code
    )


def _team_adj_from_advanced_stats(date_str, home_tri, away_tri, *, orch: OrchestratorEnv):
    b = _b()
    return b._team_adj_from_advanced_stats_local(
        processed_root=_processed_root(orch),
        date_str=date_str,
        home_tri=home_tri,
        away_tri=away_tri,
        league=b._league_for_code_local(orch.league_code),
    )


def simulate_quarters(inp, n_samples=3000, *, orch: OrchestratorEnv):
    """The ``quarters is None`` fallback, routed through the local port (no re-anchoring behind the market switch)."""
    return _b()._simulate_quarters_from_vendor_inputs_local(
        processed_root=_processed_root(orch), league_code=orch.league_code, inp=inp, n_samples=n_samples
    )


def _load_intervals_band_calibration(*, orch: OrchestratorEnv):
    return _b()._load_intervals_band_calibration_local(processed_root=_processed_root(orch))


def _load_intervals_time_profile(*, orch: OrchestratorEnv):
    return _b()._load_intervals_time_profile_local(processed_root=_processed_root(orch), league_code=orch.league_code)


def _load_player_stat_calibration(*, orch: OrchestratorEnv):
    return _b()._load_player_stat_calibration_local(processed_root=_processed_root(orch))


# Every name the vendored orchestrator called that Syndicate replaced. The port
# script imports exactly these into the generated smart_sim.py and refuses to
# emit a vendored body for any of them.
HOOK_NAMES: tuple[str, ...] = (
    "_period_lines_from_processed",
    "_market_lines_from_processed_odds",
    "_load_smartsim_total_calibration",
    "_team_players_from_props",
    "_coalesce_team_player_frames",
    "_infer_game_id",
    "_team_players_from_processed_boxscores",
    "_team_players_from_processed_rosters",
    "_filter_team_players_against_processed_roster",
    "_team_players_from_espn_boxscore",
    "_espn_name_to_id_map_for_game",
    "_merge_pregame_expected_minutes_for_team",
    "_prune_pregame_rotation_pool",
    "_market_player_names_for_matchup",
    "_rotation_sim_minutes_from_history",
    "_player_split_rate_context",
    "_player_career_opponent_rate_context",
    "_opponent_position_rate_context",
    "simulate_pbp_game_boxscore",
    "simulate_event_level_boxscore",
    "_rotation_sim_minutes_for_team",
    "_apply_player_priors",
    "_compute_player_priors_cached",
    "_derive_sim_minutes",
    "_team_adj_from_advanced_stats",
    "simulate_quarters",
    "_load_intervals_band_calibration",
    "_load_intervals_time_profile",
    "_load_player_stat_calibration",
)
