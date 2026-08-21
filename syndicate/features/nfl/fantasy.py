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

from syndicate.features.nfl.fantasy_artifact import artifact_substrate
from syndicate.features.nfl.fantasy_artifact import load_projection_artifact
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
from syndicate.features.nfl.fantasy_scoring import ScoringProfile
from syndicate.features.nfl.fantasy_scoring import score_stat_line
from syndicate.features.nfl.fantasy_scoring import resolve_scoring
from syndicate.features.nfl.fantasy_scoring import scoring_profile_summary
from syndicate.features.nfl.fantasy_usage import usage_substrate


#: The season this surface projects. NFL "season" here is the calendar year the
#: regular season starts in, matching every other NFL artifact in this repo.
DEFAULT_FANTASY_SEASON = 2026

POSITION_ORDER: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DST")


#: z-score for the 10th/90th percentile of a normal. Mirrors the engine's own
#: constant; the artifact stores a per-game sd and the band is rebuilt here
#: because its width depends on the scoring profile.
_P10_Z = 1.2815515655446004


def _serving_mode() -> str:
    """How this process is allowed to answer a projection request.

    ``artifact`` is the only mode the web service may use. ``compute`` runs the
    full engine in-process -- ~3 s and ~61 MB of raw nflverse input -- which is
    the heavy computation the worker-split rule keeps out of a request handler,
    and is enabled only by an explicit opt-in for local development.
    """
    import os

    if str(os.environ.get("SYNDICATE_NFL_FANTASY_ALLOW_REQUEST_COMPUTE") or "").strip() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return "compute"
    return "artifact"


def score_projections(
    projections: list[PlayerProjection],
    scoring: ScoringProfile,
    config: EngineConfig,
) -> list[PlayerProjection]:
    """Apply a scoring profile to unscored artifact rows.

    THE REASON THE ARTIFACT STORES STAT LINES RATHER THAN POINTS. Scoring is a
    pure function of a line, so one published artifact serves PPR, half-PPR and
    standard, and a league that changes its rules needs no rebuild. This is
    "light transformation for display" -- the only kind of work the web service
    is allowed to do.
    """
    import math

    scored: list[PlayerProjection] = []
    for entry in projections:
        games = entry.games or 0.0
        # SCORE THE PER-GAME LINE, THEN MULTIPLY THE POINTS -- never score a
        # scaled line. Every scoring term is linear except the D/ST
        # points-allowed ladder, and running that ladder on a season total
        # reads a defense as allowing ~380 points in a game. See
        # `fantasy_artifact._encode_rows`.
        per_game_line = entry.basis.get("_per_game_line")
        multiplier = entry.basis.get("_multiplier")
        if per_game_line is None or multiplier is None:
            # Rows straight from the engine (local compute path) are already
            # scaled and carry no per-game line; fall back to the engine's own
            # values, which were computed correctly upstream.
            scored.append(entry)
            continue
        per_game = score_stat_line(per_game_line, scoring)
        total = per_game * float(multiplier)
        if entry.week is not None:
            season_sd = entry.points_per_game_sd
        else:
            availability = games / max(config.games_in_season, 1)
            games_variance = config.games_in_season * availability * (1.0 - availability)
            season_sd = math.sqrt(
                max(games, 0.0) * entry.points_per_game_sd**2 + (per_game**2) * games_variance
            )
        scored.append(
            dataclasses.replace(
                entry,
                fantasy_points=total,
                points_per_game=per_game,
                season_points_sd=season_sd,
                floor=max(total - _P10_Z * season_sd, 0.0) if entry.position != "DST" else total - _P10_Z * season_sd,
                ceiling=total + _P10_Z * season_sd,
            )
        )
    scored.sort(key=lambda entry: -entry.fantasy_points)
    return scored


def _resolve_projections(
    season: int,
    scoring: ScoringProfile,
    config: EngineConfig,
    week: int | None,
    news: Any,
    use_news: bool,
) -> tuple[list[PlayerProjection], dict[str, Any]]:
    """Projections plus a `source` block saying where they came from.

    Returns an EMPTY list rather than raising when nothing is available. That
    is the contract: "if data is missing at request time, the correct behavior
    is a degraded/empty UI state, not an on-request backfill" (`CLAUDE.md`).
    The pre-artifact version raised here and all three routes 500'd on
    production, where the web dyno has none of the engine's raw inputs.
    """
    artifact = load_projection_artifact(season)
    if artifact is not None:
        rows = score_projections(artifact.to_projections(week), scoring, config)
        return rows, {
            "mode": "artifact",
            "generated_at": artifact.generated_at,
            "path": artifact.path,
            "note": "precomputed on the worker; scoring applied per request",
        }

    if _serving_mode() == "compute":
        try:
            rows = project_season(season, scoring, config, news if use_news else None, week=week)
        except Exception as error:  # noqa: BLE001 -- degrade, never 500
            return [], {
                "mode": "unavailable",
                "reason": f"in-process compute failed: {type(error).__name__}: {error}",
            }
        return rows, {
            "mode": "request_compute",
            "note": (
                "SYNDICATE_NFL_FANTASY_ALLOW_REQUEST_COMPUTE is on. Local development "
                "only -- this runs the full engine inside the request."
            ),
        }

    return [], {
        "mode": "unavailable",
        "reason": (
            f"no published projection artifact for {season} on this substrate, and "
            "in-request compute is off. Run "
            "scripts/build_nfl_fantasy_projection_artifact.py --publish on the worker."
        ),
        "expected_path": artifact_substrate(season)["path"],
    }


#: Every projected stat, grouped and ordered for the FULL stat view. The
#: artifact carries all of these per player and per week; the default view
#: shows only the handful that matter for a position, which is readable but
#: hides that the projection is a complete stat line rather than a score.
FULL_STAT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("pass_attempts", "Pass att"),
    ("passing_yards", "Pass yd"),
    ("passing_tds", "Pass TD"),
    ("interceptions", "INT"),
    ("passing_2pt", "Pass 2pt"),
    ("carries", "Car"),
    ("rushing_yards", "Rush yd"),
    ("rushing_tds", "Rush TD"),
    ("rushing_2pt", "Rush 2pt"),
    ("targets", "Tgt"),
    ("receptions", "Rec"),
    ("receiving_yards", "Rec yd"),
    ("receiving_tds", "Rec TD"),
    ("receiving_2pt", "Rec 2pt"),
    ("fumbles_lost", "Fum lost"),
    ("fg_made_0_39", "FG 0-39"),
    ("fg_made_40_49", "FG 40-49"),
    ("fg_made_50_plus", "FG 50+"),
    ("fg_missed", "FG miss"),
    ("pat_made", "PAT"),
    ("pat_missed", "PAT miss"),
    ("dst_sacks", "Sacks"),
    ("dst_interceptions", "Def INT"),
    ("dst_fumble_recoveries", "Fum rec"),
    ("dst_safeties", "Safety"),
    ("dst_touchdowns", "Def TD"),
    ("dst_blocked_kicks", "Blk"),
    ("dst_points_allowed", "Pts allowed"),
)


def populated_stat_columns(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """The full-stat columns that actually carry a value for these rows.

    A quarterback has no field goals and a kicker has no targets, so rendering
    all 28 columns for every group would be 28 columns of mostly zeros. Asking
    the DATA which columns are live keeps the full view honest -- a column that
    appears is a column with something in it -- and it adapts by itself if a
    future projection starts populating a stat that is empty today.
    """
    live: list[tuple[str, str]] = []
    for key, label in FULL_STAT_COLUMNS:
        for row in rows:
            value = row.get("stat_line", {}).get(key)
            if value:
                live.append((key, label))
                break
    return live


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
    """What actually fed this projection run.

    Every probe here reads a raw engine input, and on the web service those do
    not exist -- so each is guarded. An unreadable substrate must render as
    "unknown", never as an exception: this function is called on the degraded
    path too, and a `basis` block that raises would turn a legitimately empty
    page into a 500.
    """
    history = _history_seasons(season, len(config.season_recency_weights))
    try:
        ratings_block = {
            "games_with_line": market_team_ratings(season).total_lined_games,
            "league_mean_points": round(market_team_ratings(season).league_mean, 2),
            "home_field_points": round(market_team_ratings(season).home_field, 2),
        }
    except Exception:  # noqa: BLE001
        ratings_block = {"games_with_line": None, "unavailable": True}
    try:
        schedule = schedule_substrate(season)
    except Exception:  # noqa: BLE001
        schedule = {"unavailable": True}
    try:
        roster = roster_substrate(season)
    except Exception:  # noqa: BLE001
        roster = {"unavailable": True}
    return {
        "engine": "nfl_fantasy_opportunity_v1",
        "history_seasons": list(history),
        "season_recency_weights": list(config.season_recency_weights),
        "usage_substrate": [usage_substrate(value) for value in history],
        "schedule": schedule,
        "artifact": artifact_substrate(season),
        "market": {
            **ratings_block,
            "regular_season_games": schedule.get("regular_season_games"),
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

    projections, source = _resolve_projections(season, scoring, config, week, news, use_news)

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
        "source": source,
        "available": bool(rows),
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

    projections, source = _resolve_projections(season, scoring, config, None, news, use_news)
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
        "source": source,
        "available": bool(board),
        "basis": build_basis(season, config, news, applied_news=use_news),
    }


#: Rows rendered per position group when one is selected. Generous, because a
#: position view is what a mid-draft or waiver-wire question actually reads.
POSITION_VIEW_LIMIT = 120

#: Rows in the all-up board. The whole-league view is for the top of the draft;
#: past this it is the position views that answer the question, and every extra
#: row costs page weight on a page that reached 267 KB before this control
#: existed.
BOARD_VIEW_LIMIT = 200


def build_fantasy_page_context(
    season: int = DEFAULT_FANTASY_SEASON,
    scoring_key: str | None = None,
    week: int | None = None,
    use_news: bool = False,
    league: LeagueSettings | None = None,
    position: str | None = None,
    stat_view: str | None = None,
) -> dict[str, Any]:
    """Context for the Fantasy Football page.

    ``position`` selects a single positional grouping. It filters SERVER-SIDE
    rather than hiding rows in the browser: the all-up page carries every
    position at once and had grown to 267 KB, and a position view is a
    different question ("who is left at running back") than the board answers,
    not a subset of it that happens to be scrolled to.

    The board is still priced against the FULL pool whichever view is shown --
    replacement level is a property of the league, not of what is on screen --
    so a filtered view's VOR and tier numbers stay comparable to the all-up
    board's.
    """
    settings = league or DEFAULT_LEAGUE
    payload = build_fantasy_payload(
        season=season,
        scoring_key=scoring_key,
        week=week,
        limit=2000,
        use_news=use_news,
        league=settings,
    )
    # MULTISELECT. `position` is a comma-separated set, so "RB,WR" is one
    # question ("what is left in my flex") rather than two page loads. An empty
    # or unrecognised set means every position -- an unknown value must widen
    # the board, never empty it.
    requested = {
        value.strip().upper()
        for value in (position or "").replace("+", ",").split(",")
        if value.strip()
    }
    selected_positions = [name for name in POSITION_ORDER if name in requested]
    showing_all = not selected_positions
    selected = "ALL" if showing_all else ",".join(selected_positions)

    by_position: dict[str, list[dict[str, Any]]] = {name: [] for name in POSITION_ORDER}
    for row in payload["rows"]:
        by_position.setdefault(row["position"], []).append(row)
    for rows in by_position.values():
        rows.sort(key=lambda row: -row["fantasy_points"])

    board = [row for row in payload["rows"] if row.get("draft")]
    board.sort(key=lambda row: row["draft"]["rank"])
    if not showing_all:
        board = [row for row in board if row["position"] in selected_positions]

    full_stats = (stat_view or "").strip().lower() in {"full", "all", "1", "true"}
    counts = {name: len(rows) for name, rows in by_position.items()}
    if showing_all:
        shown = {name: rows[:60] for name, rows in by_position.items()}
    else:
        shown = {
            name: by_position.get(name, [])[:POSITION_VIEW_LIMIT]
            for name in selected_positions
        }

    stat_columns = (
        {name: populated_stat_columns(rows) for name, rows in shown.items()}
        if full_stats
        else {}
    )
    # THE DRAFT BOARD GETS THE STAT COLUMNS TOO. It is the all-up list, and
    # "all projected stats" that widened only the per-position tables read as a
    # filter that does nothing -- the board is the first table on the page and
    # it stayed at 12 columns.
    board_stat_columns = populated_stat_columns(board) if full_stats else []

    return {
        "title": "Fantasy Football",
        "season": season,
        "week": week,
        "full_stats": full_stats,
        "stat_columns": stat_columns,
        "scoring": payload["scoring"],
        "scoring_label": payload["scoring_label"],
        "available_scoring": payload["available_scoring"],
        "league_label": settings.label,
        "use_news": use_news,
        "positions": POSITION_ORDER,
        "selected_position": selected,
        "selected_positions": selected_positions,
        "showing_all_positions": showing_all,
        "board_stat_columns": board_stat_columns,
        "position_counts": counts,
        "by_position": shown,
        "board": board[:BOARD_VIEW_LIMIT],
        "board_summary": payload["board_summary"],
        "source": payload["source"],
        "available": payload["available"],
        "basis": payload["basis"],
        "payload": payload,
    }
