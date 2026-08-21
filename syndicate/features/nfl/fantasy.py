"""The Fantasy Football surface: payload and page context.

The request-path entry point for everything under ``/nfl/fantasy``. Kept thin
on purpose -- it resolves arguments, calls the engine, and shapes a payload.
Every expensive step it depends on (parsing play-by-play into usage) happens in
a worker and is read here from an artifact, per the worker-split rule in
``CLAUDE.md``: the web service reads precomputed artifacts and does light
transformation for display, never heavy computation inside a route handler.

Every payload carries a ``basis`` block naming what fed it -- which seasons of
usage, how many games carried a real market line, when the depth chart was
taken, whether news was applied. A projection that cannot say where it came
from is not auditable, and ``model_engine_standard.md`` s3b is explicit that a
claim without a named substrate is not yet a claim.
"""

from __future__ import annotations

import dataclasses
from dataclasses import asdict
from typing import Any

from syndicate.features.nfl.fantasy_draft_board import DEFAULT_LEAGUE
from syndicate.features.nfl.fantasy_draft_board import LeagueSettings
from syndicate.features.nfl.fantasy_draft_board import board_summary
from syndicate.features.nfl.fantasy_draft_board import build_draft_board
from syndicate.features.nfl.fantasy_news import load_news_adjustments
from syndicate.features.nfl.fantasy_players import roster_substrate
from syndicate.features.nfl.fantasy_projection import DEFAULT_CONFIG
from syndicate.features.nfl.fantasy_projection import EngineConfig
from syndicate.features.nfl.fantasy_projection import PlayerProjection
from syndicate.features.nfl.fantasy_projection import _history_seasons
from syndicate.features.nfl.fantasy_projection import project_season
from syndicate.features.nfl.fantasy_schedule import market_team_ratings
from syndicate.features.nfl.fantasy_schedule import schedule_substrate
from syndicate.features.nfl.fantasy_scoring import SCORING_PROFILES
from syndicate.features.nfl.fantasy_scoring import resolve_scoring
from syndicate.features.nfl.fantasy_scoring import scoring_profile_summary
from syndicate.features.nfl.fantasy_usage import usage_substrate


#: The season this surface projects. NFL "season" here is the calendar year the
#: regular season starts in, matching every other NFL artifact in this repo.
DEFAULT_FANTASY_SEASON = 2026

POSITION_ORDER: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DST")


def resolve_league(
    teams: int | None = None,
    superflex: bool = False,
    ppr_key: str | None = None,
) -> LeagueSettings:
    """League settings from request arguments, defaulting to 12-team 1QB."""
    settings = DEFAULT_LEAGUE
    if teams and 4 <= teams <= 32:
        settings = dataclasses.replace(settings, teams=teams)
    if superflex:
        settings = dataclasses.replace(settings, superflex=1)
    return settings


def _projection_payload(entry: PlayerProjection) -> dict[str, Any]:
    return {
        "player_id": entry.player_id,
        "name": entry.name,
        "team": entry.team,
        "position": entry.position,
        "games": round(entry.games, 1),
        "fantasy_points": round(entry.fantasy_points, 1),
        "points_per_game": round(entry.points_per_game, 2),
        "points_per_game_sd": round(entry.points_per_game_sd, 2),
        "floor": round(entry.floor, 1),
        "ceiling": round(entry.ceiling, 1),
        "week": entry.week,
        "opponent": entry.opponent,
        "stat_line": {name: round(value, 1) for name, value in entry.stat_line.items()},
        "basis": entry.basis,
    }


def build_basis(season: int, config: EngineConfig, news: Any, applied_news: bool) -> dict[str, Any]:
    """What actually fed this projection run."""
    history = _history_seasons(season, len(config.season_recency_weights))
    ratings = market_team_ratings(season)
    schedule = schedule_substrate(season)
    roster = roster_substrate(season)
    return {
        "engine": "nfl_fantasy_opportunity_v1",
        "history_seasons": list(history),
        "season_recency_weights": list(config.season_recency_weights),
        "usage_substrate": [usage_substrate(value) for value in history],
        "schedule": schedule,
        "market": {
            "games_with_line": ratings.total_lined_games,
            "regular_season_games": schedule.get("regular_season_games"),
            "league_mean_points": round(ratings.league_mean, 2),
            "home_field_points": round(ratings.home_field, 2),
            "note": (
                "Team scoring environment comes from posted spreads/totals, not from "
                "smartsim2 -- state.md [football-smartsim2] measured the sim strictly "
                "dominated by the close (w=-0.028 over 751 out-of-sample games)."
            ),
        },
        "roster": roster,
        "news": (news.summary() | {"applied": applied_news}) if news is not None else {"applied": False},
        "config": {
            field.name: getattr(config, field.name)
            for field in dataclasses.fields(config)
            if field.name != "season_recency_weights"
        },
        "validation": {
            "backtest": "reports/nfl_fantasy_backtest.json",
            "calibration": "reports/nfl_fantasy_calibration.json",
            "held_out_season": 2025,
            "note": (
                "Constants selected on 2024 only; 2025 is the report season and was "
                "never used to select anything."
            ),
        },
    }


def build_fantasy_payload(
    season: int = DEFAULT_FANTASY_SEASON,
    scoring_key: str | None = None,
    week: int | None = None,
    position: str | None = None,
    limit: int = 400,
    use_news: bool = False,
    league: LeagueSettings | None = None,
) -> dict[str, Any]:
    """Projections plus the draft board, as one payload."""
    scoring = resolve_scoring(scoring_key)
    settings = league or DEFAULT_LEAGUE
    config = DEFAULT_CONFIG
    news = load_news_adjustments(season)
    if use_news:
        config = dataclasses.replace(config, use_news_adjustments=True)

    projections = project_season(season, scoring, config, news if use_news else None, week=week)

    wanted = (position or "").strip().upper()
    if wanted and wanted != "ALL":
        selected = [entry for entry in projections if entry.position == wanted]
    else:
        selected = projections

    # The board is always priced against the FULL pool: replacement level is a
    # property of the league, not of whichever position is being displayed.
    board = build_draft_board(projections, settings) if week is None else []
    board_index = {row.player_id: row for row in board}

    rows = []
    for entry in selected[: max(limit, 1)]:
        payload = _projection_payload(entry)
        row = board_index.get(entry.player_id)
        if row is not None:
            payload["draft"] = {
                "rank": row.rank,
                "position_rank": row.position_rank,
                "tier": row.tier,
                "value_over_replacement": row.value_over_replacement,
                "replacement_points": row.replacement_points,
                "projected_round": row.projected_round,
            }
        rows.append(payload)

    return {
        "sport": "nfl",
        "surface": "fantasy",
        "season": season,
        "week": week,
        "scoring": scoring.key,
        "scoring_label": scoring.label,
        "scoring_rules": scoring_profile_summary(scoring),
        "available_scoring": sorted(SCORING_PROFILES),
        "position": wanted or "ALL",
        "count": len(rows),
        "total_projected": len(projections),
        "rows": rows,
        "board_summary": board_summary(board, settings) if board else None,
        "basis": build_basis(season, config, news, applied_news=use_news),
    }


def build_draft_board_payload(
    season: int = DEFAULT_FANTASY_SEASON,
    scoring_key: str | None = None,
    limit: int = 250,
    use_news: bool = False,
    league: LeagueSettings | None = None,
) -> dict[str, Any]:
    """The draft board on its own -- ordered by value over replacement."""
    scoring = resolve_scoring(scoring_key)
    settings = league or DEFAULT_LEAGUE
    config = DEFAULT_CONFIG
    news = load_news_adjustments(season)
    if use_news:
        config = dataclasses.replace(config, use_news_adjustments=True)

    projections = project_season(season, scoring, config, news if use_news else None)
    board = build_draft_board(projections, settings, limit=limit)
    return {
        "sport": "nfl",
        "surface": "fantasy_draft_board",
        "season": season,
        "scoring": scoring.key,
        "scoring_label": scoring.label,
        "league": settings.label,
        "count": len(board),
        "rows": [asdict(row) for row in board],
        "board_summary": board_summary(board, settings),
        "basis": build_basis(season, config, news, applied_news=use_news),
    }


def build_fantasy_page_context(
    season: int = DEFAULT_FANTASY_SEASON,
    scoring_key: str | None = None,
    week: int | None = None,
    use_news: bool = False,
    league: LeagueSettings | None = None,
) -> dict[str, Any]:
    """Context for the Fantasy Football page."""
    settings = league or DEFAULT_LEAGUE
    payload = build_fantasy_payload(
        season=season,
        scoring_key=scoring_key,
        week=week,
        limit=400,
        use_news=use_news,
        league=settings,
    )
    by_position: dict[str, list[dict[str, Any]]] = {name: [] for name in POSITION_ORDER}
    for row in payload["rows"]:
        by_position.setdefault(row["position"], []).append(row)
    board = [row for row in payload["rows"] if row.get("draft")]
    board.sort(key=lambda row: row["draft"]["rank"])
    return {
        "title": "Fantasy Football",
        "season": season,
        "week": week,
        "scoring": payload["scoring"],
        "scoring_label": payload["scoring_label"],
        "available_scoring": payload["available_scoring"],
        "league_label": settings.label,
        "use_news": use_news,
        "positions": POSITION_ORDER,
        "by_position": by_position,
        "board": board[:200],
        "board_summary": payload["board_summary"],
        "basis": payload["basis"],
        "payload": payload,
    }
