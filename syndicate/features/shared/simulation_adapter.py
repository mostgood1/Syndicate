from __future__ import annotations

from copy import deepcopy
from typing import Any
from typing import Callable
from typing import Mapping

from syndicate.features.shared.odds_lifecycle import build_market_features
from syndicate.features.shared.timezone import central_today_iso


AdapterLoader = Callable[[Any], dict[str, Any]]


def _log_sim_contract_memory(stage: str, **extra: Any) -> None:
    # #75. Worker-only, same guard and reasoning as the cards_context_* and
    # board_contract_* samples. See docs/ai_context/handoff_refresh_worker_oom.md.
    from syndicate.features.shared.game_board_contract import _render_web_dyno

    if _render_web_dyno():
        return
    try:
        from syndicate.features.shared.memory_observability import log_container_memory

        log_container_memory(f"sim_contract_{stage}", **extra)
    except Exception:
        pass


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text.replace("%", ""))
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _coerce_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalize_team(value: Any, fallback_abbr: str) -> dict[str, Any]:
    team = _copy_mapping(value)
    abbr = _safe_text(team.get("abbr") or team.get("tri") or team.get("code") or fallback_abbr, fallback_abbr)
    return {
        "abbr": abbr,
        "name": _safe_text(team.get("name") or team.get("full_name") or team.get("display_name"), abbr),
        "logo": _safe_text(team.get("logo") or team.get("logo_url"), "") or None,
        "score": _safe_float(team.get("score")),
    }


def _normalize_player_projections(game: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    sim = _copy_mapping(game.get("sim"))
    players = _copy_mapping(sim.get("players"))
    for side in ("home", "away"):
        side_players = players.get(side)
        if not isinstance(side_players, list):
            continue
        for player in side_players:
            if not isinstance(player, Mapping):
                continue
            candidates.append(dict(player))
    explicit = game.get("player_projections")
    if isinstance(explicit, list):
        for player in explicit:
            if isinstance(player, Mapping):
                candidates.append(dict(player))
    return candidates


def _log_advanced_context_size(bucket: str, key: str, value: Any) -> None:
    # #75. See _advanced_context. Worker-only; never let instrumentation be the
    # reason a board build fails.
    try:
        from syndicate.features.shared.game_board_contract import _render_web_dyno

        if _render_web_dyno():
            return
        if isinstance(value, (list, tuple, dict, str)):
            print(
                f"ADV_CTX_SIZE bucket={bucket} key={key} type={type(value).__name__} len={len(value)}",
                flush=True,
            )
    except Exception:
        pass


def _advanced_context(game: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    page: dict[str, Any] = {}
    game_adv: dict[str, Any] = {}
    context_keys = (
        "hr_targets_shelf",
        "hrTargets",
        "lineup_health",
        "workflow",
        "marketAvailability",
        "scoreboard_items",
        "module_links",
        "cards_control_links",
        "cards_header_meta",
        "cards_header_title",
        "latest_live_odds_refreshed_at",
        "source_path",
        "source_title",
        "wnba_advanced_contract",
    )
    game_keys = (
        "run_projection_rows",
        "segment_overview_cards",
        "first1BetSignal",
        "predictions",
        "markets",
        "gameMarkets",
        "gameLens",
        "market_tiles",
        "props",
        "liveProps",
        "trackedProps",
        "archivedLiveProps",
        "prop_groups",
        "prop_lens",
        "snapshotAvailable",
        "simContextAvailable",
        "probable",
        "score",
        "matchup",
        "hero_note",
        "status_badge",
    )

    # #75. Production dies inside the FIRST game's _normalize_game_context,
    # before build_market_features is reached (no ODDS_SHARD_SIZE line is ever
    # emitted), so the cost is here or in _normalize_player_projections. This
    # function deepcopies every key below, per game, and several of them --
    # liveProps, trackedProps, archivedLiveProps, gameLens -- accumulate over a
    # live game. Local cannot reproduce it because the pulled artifacts have no
    # live games.
    #
    # Element counts only, logged BEFORE the copy: computing a byte size of the
    # value would risk the same allocation that is killing the process.
    for key in context_keys:
        if key in context and context.get(key) is not None:
            _log_advanced_context_size("page", key, context.get(key))
            page[key] = deepcopy(context.get(key))
    for key in game_keys:
        if key in game and game.get(key) is not None:
            _log_advanced_context_size("game", key, game.get(key))
            game_adv[key] = deepcopy(game.get(key))

    return {
        "page": page,
        "game": game_adv,
        "available": bool(page or game_adv),
    }


def _normalize_game_context(game: dict[str, Any], *, context: dict[str, Any] | None = None, sport: str | None = None, odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    page_context = _copy_mapping(context)
    sim = _copy_mapping(game.get("sim"))
    betting = _copy_mapping(game.get("betting"))
    live_state = _copy_mapping(game.get("live_state"))
    player_projections = _normalize_player_projections(game)
    team_score = _copy_mapping(sim.get("score"))
    away_team = _normalize_team(game.get("away"), _safe_text(game.get("away_tri") or game.get("away"), "AWY"))
    home_team = _normalize_team(game.get("home"), _safe_text(game.get("home_tri") or game.get("home"), "HME"))

    team_projections = {
        "away": _safe_float(team_score.get("away_mean") or team_score.get("away") or away_team.get("score")),
        "home": _safe_float(team_score.get("home_mean") or team_score.get("home") or home_team.get("score")),
    }

    model_probability = _safe_float(
        game.get("model_probability")
        or sim.get("model_probability")
        or sim.get("win_probability")
        or betting.get("model_probability")
        or betting.get("win_probability")
    )
    confidence = _safe_float(game.get("confidence") or sim.get("confidence") or betting.get("confidence"))
    edge = _safe_float(game.get("edge") or sim.get("edge") or betting.get("edge"))
    advanced = _advanced_context(game, page_context)
    market_features = build_market_features(
        game,
        sport=_safe_text(sport or game.get("sport") or game.get("sport_slug") or page_context.get("sport") or "", "").lower() or None,
        end_date=_safe_text(
            game.get("date")
            or game.get("game_date")
            or game.get("requested_date")
            or page_context.get("date")
            or page_context.get("selected_date")
            or "",
            "",
        )
        or None,
        # #75. Without this every game re-loads and re-parses the same odds
        # history shards from disk: this function is called once per game, and
        # build_simulation_engine_context_from_candidate below already threads a
        # cache for exactly this reason. The omission here was the asymmetry.
        payload_cache=odds_payload_cache,
    )

    engine_context = {
        "sport": _safe_text(game.get("sport") or "", ""),
        "selection": _safe_text(game.get("selection") or game.get("date") or game.get("requested_date") or "", ""),
        "market": _safe_text(betting.get("market") or game.get("market") or game.get("type"), ""),
        "selection_label": _safe_text(game.get("summary") or game.get("detail") or game.get("status"), ""),
        "team_projections": team_projections,
        "player_projections": player_projections,
        "matchup_modifiers": {
            "live_state": deepcopy(live_state),
            "market": deepcopy(betting),
            "evaluation": deepcopy(_copy_mapping(game.get("evaluation"))),
            "advanced": deepcopy(advanced),
        },
        "model_probability": model_probability,
        "confidence": confidence,
        "edge": edge,
        "seed": _safe_int(game.get("seed") or sim.get("seed")),
    }

    return {
        "game_id": _safe_text(game.get("gamePk") or game.get("game_id") or game.get("event_id") or "", ""),
        "event_id": _safe_text(game.get("event_id") or game.get("gamePk") or game.get("game_id") or "", ""),
        "away": away_team,
        "home": home_team,
        "state": {
            "status": _safe_text(game.get("status") or live_state.get("status") or "Scheduled", "Scheduled"),
            "detail": _safe_text(game.get("detail") or live_state.get("detail") or game.get("status") or "Scheduled", "Scheduled"),
            "live": bool(live_state) and bool(live_state.get("in_progress") or live_state.get("live") or live_state.get("status") == "Live"),
            "final": bool(live_state.get("final") or game.get("final")),
        },
        "inputs": {
            "team": team_projections,
            "player": player_projections,
            "market": betting,
            "market_features": market_features,
            "live": live_state,
            "evaluation": _copy_mapping(game.get("evaluation")),
            "advanced": advanced,
        },
        "simulation": sim,
        "advanced": advanced,
        "market_features": market_features,
        "display": {
            "summary": _safe_text(game.get("summary") or "", ""),
            "detail": _safe_text(game.get("detail") or "", ""),
            "source_title": _safe_text(game.get("source_title") or "", ""),
            "source_path": _safe_text(game.get("source_path") or "", ""),
            "advanced": advanced,
        },
        "hrTargets": _copy_mapping(game.get("hrTargets")) if isinstance(game.get("hrTargets"), Mapping) else game.get("hrTargets"),
        "engine_context": engine_context,
    }


def _source_paths(context: dict[str, Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for key, value in context.items():
        if not isinstance(value, (str, int, float)):
            continue
        text = _safe_text(value, "")
        if text and ("path" in key.lower() or key.lower() in {"source", "cards_path", "recs_path", "source_title"}):
            paths[key] = text
    return paths


def _selection_kind(sport: str) -> str:
    return "week" if _safe_text(sport, "").lower() in {"nfl", "ncaaf"} else "date"


def _source_mode(context: dict[str, Any]) -> str:
    title = _safe_text(context.get("source_title"), "").lower()
    if "live scoreboard fallback" in title or "live fallback" in title:
        return "live_fallback"
    if "live scoreboard supplement" in title or "live supplement" in title:
        return "live_supplement"
    if "archive" in title:
        return "archive_fallback"
    if "snapshot" in title:
        return "snapshot_only"
    if "processed" in title or "recommendation" in title or "summary" in title:
        return "artifact_primary"
    return "unknown"


def _freshness(context: dict[str, Any], selection: Any, selection_kind: str) -> dict[str, Any]:
    requested = _safe_text(context.get("requested_date") or context.get("requested_week") or selection, "")
    resolved = _safe_text(context.get("date") or context.get("resolved_date") or context.get("season_week") or context.get("requested_date") or selection, "")
    is_current_day = selection_kind == "date" and resolved == central_today_iso()
    return {
        "requested": requested,
        "resolved": resolved,
        "selection_kind": selection_kind,
        "is_current_day": is_current_day,
        "is_stale": bool(requested and resolved and requested != resolved),
        "lookahead_applied": bool(context.get("lookahead_applied")),
    }


def _loader_mlb(selection: Any, **_: Any) -> dict[str, Any]:
    from syndicate.features.mlb.cards import build_cards_page_context

    return build_cards_page_context(_safe_text(selection, ""))


def _loader_nba(selection: Any, *, allow_stored_date_fallback: bool = False, **_: Any) -> dict[str, Any]:
    from syndicate.features.nba.cards import build_cards_page_context

    return build_cards_page_context(_safe_text(selection, ""), allow_stored_date_fallback=allow_stored_date_fallback)


def _loader_wnba(selection: Any, *, allow_stored_date_fallback: bool = False, **_: Any) -> dict[str, Any]:
    from syndicate.features.wnba.cards import build_cards_page_context

    return build_cards_page_context(_safe_text(selection, ""), allow_stored_date_fallback=allow_stored_date_fallback)


def _loader_nhl(selection: Any, **_: Any) -> dict[str, Any]:
    from syndicate.features.nhl.cards import build_cards_page_context

    return build_cards_page_context(_safe_text(selection, ""))


def _loader_nfl(selection: Any, *, season: int | None = None, **_: Any) -> dict[str, Any]:
    from syndicate.features.nfl.cards import build_cards_page_context

    return build_cards_page_context(_safe_int(selection) or 1, season=season)


def _loader_ncaab(selection: Any, **_: Any) -> dict[str, Any]:
    from syndicate.features.ncaab.cards import build_cards_page_context

    return build_cards_page_context(_safe_text(selection, ""))


def _loader_ncaaf(selection: Any, **_: Any) -> dict[str, Any]:
    from syndicate.features.ncaaf.cards import build_cards_page_context

    return build_cards_page_context(_safe_int(selection) or 1)


SPORT_ADAPTERS: dict[str, AdapterLoader] = {
    "mlb": _loader_mlb,
    "nba": _loader_nba,
    "wnba": _loader_wnba,
    "nhl": _loader_nhl,
    "nfl": _loader_nfl,
    "ncaab": _loader_ncaab,
    "ncaaf": _loader_ncaaf,
}


def build_unified_simulation_adapter(
    sport: str,
    selection: Any,
    *,
    season: int | None = None,
    allow_stored_date_fallback: bool = False,
) -> dict[str, Any]:
    sport_key = _safe_text(sport, "").lower()
    loader = SPORT_ADAPTERS.get(sport_key)
    if loader is None:
        raise ValueError(f"Unsupported sport adapter: {sport}")

    context = _copy_mapping(
        loader(
            selection,
            season=season,
            allow_stored_date_fallback=allow_stored_date_fallback,
        )
    )
    odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    normalized_games = [_normalize_game_context(game, context=context, sport=sport_key, odds_payload_cache=odds_payload_cache) for game in _coerce_list(context.get("games")) if isinstance(game, Mapping)]
    selection_kind = _selection_kind(sport_key)
    resolved_selection = _safe_text(context.get("date") or context.get("requested_date") or selection, "")

    return {
        "adapter_version": "v1",
        "sport": sport_key,
        "selection": {
            "kind": selection_kind,
            "requested": _safe_text(selection, ""),
            "resolved": resolved_selection,
        },
        "source_mode": _source_mode(context),
        "source_title": _safe_text(context.get("source_title"), ""),
        "source_paths": _source_paths(context),
        "freshness": _freshness(context, selection, selection_kind),
        "advanced": _advanced_context({}, context),
        "games": normalized_games,
        "game_count": len(normalized_games),
        "context": context,
    }


def build_simulation_contract_from_context(
    context: dict[str, Any],
    *,
    sport: str | None = None,
    selection: Any = None,
) -> dict[str, Any]:
    normalized_context = _copy_mapping(context)
    sport_key = _safe_text(sport, _safe_text(normalized_context.get("active_sport_slug") or normalized_context.get("sport") or normalized_context.get("sport_slug"), "")).lower()
    selection_value = selection if selection is not None else normalized_context.get("control_value") or normalized_context.get("date") or normalized_context.get("requested_date")
    selection_kind = _selection_kind(sport_key)
    # #75. Sampled per game because this loop is the suspected OOM: each
    # _normalize_game_context calls build_market_features with NO payload_cache
    # (unlike build_simulation_engine_context_from_candidate below, which
    # threads one), so every game re-enters _recent_history_rows ->
    # build_recent_market_history_index, which is not memoised and copies every
    # event under up to 9 aliases before sorting each bucket. If that is what
    # this is, memory climbs monotonically game by game here.
    source_games = [game for game in _coerce_list(normalized_context.get("games")) if isinstance(game, Mapping)]
    odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    normalized_games = []
    for index, game in enumerate(source_games):
        normalized_games.append(
            _normalize_game_context(game, context=normalized_context, sport=sport_key, odds_payload_cache=odds_payload_cache)
        )
        _log_sim_contract_memory("game_normalized", sport=sport_key, game_index=index, game_total=len(source_games))
    resolved_selection = _safe_text(normalized_context.get("date") or normalized_context.get("requested_date") or selection_value, "")

    return {
        "adapter_version": "v1",
        "sport": sport_key,
        "selection": {
            "kind": selection_kind,
            "requested": _safe_text(selection_value, ""),
            "resolved": resolved_selection,
        },
        "source_mode": _source_mode(normalized_context),
        "source_title": _safe_text(normalized_context.get("source_title"), ""),
        "source_paths": _source_paths(normalized_context),
        "freshness": _freshness(normalized_context, selection_value, selection_kind),
        "advanced": _advanced_context({}, normalized_context),
        "games": normalized_games,
        "game_count": len(normalized_games),
        "context": normalized_context,
    }


def build_simulation_engine_context_from_candidate(candidate: Mapping[str, Any], *, odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    row = _copy_mapping(candidate)
    market_data = _copy_mapping(row.get("market_data"))
    market_features = _copy_mapping(row.get("market_features"))
    if not market_features:
        market_features = build_market_features(
            row,
            sport=_safe_text(row.get("sport") or row.get("sport_slug") or "", "").lower() or None,
            end_date=_safe_text(row.get("date") or row.get("game_date") or row.get("selected_date") or "", "") or None,
            payload_cache=odds_payload_cache,
        )
    return {
        "sport": _safe_text(row.get("sport") or row.get("sport_slug") or "", ""),
        "market": _safe_text(row.get("market") or row.get("market_key") or "", ""),
        "selection": _safe_text(row.get("pick") or row.get("name") or row.get("selection") or "", ""),
        "line": row.get("line"),
        "current_line": market_data.get("current_line"),
        "opening_line": market_data.get("opening_line"),
        "movement_history": market_data.get("movement_history"),
        "movement": row.get("movement"),
        "odds": row.get("odds"),
        "confidence": row.get("confidence"),
        "edge": row.get("edge"),
        "model_probability": row.get("model_probability") or row.get("fair_probability"),
        "seed": row.get("seed"),
        "market_features": market_features,
    }


__all__ = [
    "SPORT_ADAPTERS",
    "build_simulation_contract_from_context",
    "build_simulation_engine_context_from_candidate",
    "build_unified_simulation_adapter",
]