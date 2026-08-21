from __future__ import annotations

from syndicate.blueprints.layer1_page import render_layer1_board
from flask import Blueprint, jsonify, render_template, request

from syndicate.features.nfl.archive import build_archive_api_payload
from syndicate.features.nfl.archive import build_archive_page_context
from syndicate.features.nfl.cards import build_cards_page_context
from syndicate.features.nfl.cards import build_nfl_market_board
from syndicate.features.nfl.cards import nfl_projection_available_weeks
from syndicate.features.nfl.fantasy import DEFAULT_FANTASY_SEASON
from syndicate.features.nfl.fantasy import build_draft_board_payload
from syndicate.features.nfl.fantasy import build_fantasy_page_context
from syndicate.features.nfl.fantasy import build_fantasy_payload
from syndicate.features.nfl.fantasy import resolve_league
from syndicate.features.nfl.game_detail import build_game_detail_page_context
from syndicate.features.nfl.live_lens import build_live_lens_page_context
from syndicate.features.nfl.picks import build_betting_card_page_context
from syndicate.features.nfl.picks import build_picks_page_context
from syndicate.features.nfl.preseason_cards import build_nfl_preseason_market_board
from syndicate.features.nfl.preseason_cards import build_preseason_cards_page_context
from syndicate.features.nfl.props import build_nfl_props_page_context
from syndicate.features.nfl.props import nfl_props_available_weeks
from syndicate.features.nfl.sources import available_weeks
from syndicate.features.nfl.sources import default_week
from syndicate.features.nfl.sources import latest_season
from syndicate.features.nfl.sources import preseason_target_week
from syndicate.features.nfl.sources import tracked_week
from syndicate.features.nfl.sources import week_summaries
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.shared.hub_summary import build_hub_bettor_summary
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.timezone import central_today_iso


nfl_bp = Blueprint("syndicate_nfl", __name__, url_prefix="/nfl")


def _selected_season() -> int:
    try:
        return int((request.args.get("season") or "").strip())
    except Exception:
        return latest_season()


def _selected_week(season: int | None = None) -> int:
    try:
        return int((request.args.get("week") or "").strip())
    except Exception:
        return default_week(season)


@nfl_bp.get("/hub")
def hub():
    weeks = week_summaries()
    current = tracked_week()
    season = latest_season()
    season_weeks = [int(item["week"]) for item in weeks if int(item.get("season") or 0) == season]
    latest_week = season_weeks[-1] if season_weeks else default_week(season)
    launch_week = latest_week
    if current and int(current.get("season") or 0) == season:
        try:
            tracked = int(current["week"])
            if tracked > 0 and tracked in season_weeks:
                launch_week = tracked
        except Exception:
            pass
    return render_template(
        "nfl/hub.html",
        launch_week=launch_week,
        current_week=current,
        available_weeks=weeks,
        season=season,
        summary_stats=[
            {"label": "Weeks with snapshots", "value": str(len(weeks))},
            {"label": "Latest season", "value": str(season)},
        ],
        hub_summary=build_hub_bettor_summary("nfl", today_value=central_today_iso()),
    )


@nfl_bp.get("")
def root_cards():
    return cards()


@nfl_bp.get("/api/weeks")
def api_weeks():
    weeks = week_summaries()
    return jsonify(
        {
            "season": latest_season(),
            "weeks": weeks,
            "available_weeks": [item["week"] for item in weeks if item["season"] == latest_season()],
        }
    )


@nfl_bp.get("/archive")
def archive():
    season = _selected_season()
    context = build_archive_page_context(_selected_week(season), season=season)
    return render_template("shared/rank_board.html", **context)


@nfl_bp.get("/api/archive")
def api_archive():
    season = _selected_season()
    return jsonify(build_archive_api_payload(_selected_week(season), season=season))


@nfl_bp.get("/cards")
def cards():
    season = _selected_season()
    context = build_cards_page_context(_selected_week(season), season=season)
    return render_template("shared/game_cards_board.html", **context)


@nfl_bp.get("/game/<game_pk>")
def game_detail(game_pk: str):
    season = _selected_season()
    context = build_game_detail_page_context(_selected_week(season), game_pk, season=season)
    return render_template("shared/game_cards_board.html", **context)


@nfl_bp.get("/api/cards")
def api_cards():
    season = _selected_season()
    context = build_cards_page_context(_selected_week(season), season=season)
    return jsonify(build_game_board_api_payload(context))


@nfl_bp.get("/api/game/<game_pk>")
def api_game_detail(game_pk: str):
    season = _selected_season()
    context = build_game_detail_page_context(_selected_week(season), game_pk, season=season)
    return jsonify(build_game_board_api_payload(context))


@nfl_bp.get("/live-lens")
def live_lens():
    season = _selected_season()
    context = build_live_lens_page_context(_selected_week(season), season=season)
    return render_template("shared/rank_board.html", **context)


@nfl_bp.get("/api/live-lens")
def api_live_lens():
    season = _selected_season()
    context = build_live_lens_page_context(_selected_week(season), season=season)
    payload = build_rank_api_payload(context)
    payload["season"] = context["season"]
    payload["week"] = context["week"]
    payload["available_weeks"] = context["available_weeks"]
    payload["rows"] = context.get("rows", 0)
    payload["data"] = context.get("data", [])
    payload["groups"] = context.get("groups", {})
    payload["have_data"] = context.get("have_data", False)
    return jsonify(payload)


@nfl_bp.get("/picks")
def picks():
    season = _selected_season()
    sort = str(request.args.get("sort") or "").strip().lower()
    context = build_picks_page_context(_selected_week(season), season=season, sort=sort)
    return render_template("shared/rank_board.html", **context)


@nfl_bp.get("/api/picks")
def api_picks():
    season = _selected_season()
    sort = str(request.args.get("sort") or "").strip().lower()
    context = build_picks_page_context(_selected_week(season), season=season, sort=sort)
    payload = build_rank_api_payload(context)
    payload["season"] = context["season"]
    payload["week"] = context["week"]
    payload["available_weeks"] = context["available_weeks"]
    payload["rows"] = context.get("rows", 0)
    payload["data"] = context.get("data", [])
    payload["groups"] = context.get("groups", {})
    payload["have_data"] = context.get("have_data", False)
    return jsonify(payload)


@nfl_bp.get("/season/<int:season>/betting-card")
def betting_card(season: int):
    sort = str(request.args.get("sort") or "").strip().lower()
    context = build_betting_card_page_context(season, _selected_week(season), sort=sort)
    return render_template("shared/rank_board.html", **context)


@nfl_bp.get("/api/season/<int:season>/betting-card")
def api_betting_card(season: int):
    sort = str(request.args.get("sort") or "").strip().lower()
    context = build_betting_card_page_context(season, _selected_week(season), sort=sort)
    payload = build_rank_api_payload(context)
    payload["season"] = context["season"]
    payload["week"] = context["week"]
    payload["available_weeks"] = context["available_weeks"]
    payload["rows"] = context.get("rows", 0)
    payload["data"] = context.get("data", [])
    payload["groups"] = context.get("groups", {})
    payload["have_data"] = context.get("have_data", False)
    return jsonify(payload)


def _selected_market_board_week(season: int) -> int:
    weeks = nfl_projection_available_weeks(season)
    raw = (request.args.get("week") or "").strip()
    if raw:
        try:
            requested = int(raw)
            if requested in weeks:
                return requested
        except ValueError:
            pass
    return weeks[-1] if weeks else default_week(season)


@nfl_bp.get("/market-board")
def market_board():
    """`#329`: the shared Layer 1 board.

    Swapped only AFTER the bet slip reached parity. The first attempt at this
    swap was reverted because tests/test_market_board_ui.py caught that it
    would have removed a working bet slip from six sports to gain sim
    enrichment -- a downgrade wearing an upgrade's name. The board now carries
    the slip, and stages a leg PER SIDE, which the merged over/under row makes
    possible and the old one-row-per-side board could not do.

    The old builder stays on /api/market-board: home.py and the live-refresh
    resim gates still import it.
    """
    return render_layer1_board("nfl")

@nfl_bp.get("/api/market-board")
def api_market_board():
    season = _selected_season()
    return jsonify(build_nfl_market_board(season, _selected_market_board_week(season)))


def _selected_props_week(season: int) -> int:
    weeks = nfl_props_available_weeks(season)
    raw = (request.args.get("week") or "").strip()
    if raw:
        try:
            requested = int(raw)
            if requested in weeks:
                return requested
        except ValueError:
            pass
    return weeks[-1] if weeks else default_week(season)


@nfl_bp.get("/props")
def props():
    season = _selected_season()
    context = build_nfl_props_page_context(season, _selected_props_week(season))
    return render_template("shared/rank_board.html", **context)


@nfl_bp.get("/api/props")
def api_props():
    season = _selected_season()
    context = build_nfl_props_page_context(season, _selected_props_week(season))
    payload = build_rank_api_payload(context)
    payload["season"] = season
    return jsonify(payload)


def _selected_preseason_week(season: int) -> int:
    # Deliberately its own resolver, not _selected_week() -- preseason's
    # week domain (1-4) and default (preseason_target_week(), the
    # real-schedule-driven "next unplayed preseason week") are completely
    # separate from the regular season's, never falls back to
    # default_week().
    raw = (request.args.get("week") or "").strip()
    if raw:
        try:
            requested = int(raw)
            if requested in (1, 2, 3, 4):
                return requested
        except ValueError:
            pass
    target = preseason_target_week(season)
    return target if target is not None else 1


@nfl_bp.get("/preseason")
def preseason_hub():
    return preseason_cards()


@nfl_bp.get("/preseason/cards")
def preseason_cards():
    season = _selected_season()
    context = build_preseason_cards_page_context(_selected_preseason_week(season), season=season)
    return render_template("shared/game_cards_board.html", **context)


@nfl_bp.get("/api/preseason/cards")
def api_preseason_cards():
    season = _selected_season()
    context = build_preseason_cards_page_context(_selected_preseason_week(season), season=season)
    return jsonify(build_game_board_api_payload(context))


@nfl_bp.get("/preseason/market-board")
def preseason_market_board():
    season = _selected_season()
    selected_week = _selected_preseason_week(season)
    prev_week, next_week = neighboring_values([1, 2, 3, 4], selected_week, fallback=selected_week)
    # Built directly here (not JS/API-only like the regular-season market
    # board) so the shrinkage/uncertainty disclosure can render server-side
    # on first paint -- same "build the page context directly in the route"
    # pattern preseason_cards() above already uses, and a cheap artifact
    # read/join, not a simulation, so it stays within the web service's
    # "light transformation for display" budget.
    board = build_nfl_preseason_market_board(season, selected_week)
    return render_template(
        "nfl/preseason_market_board.html",
        sport_label="NFL Preseason",
        sport_slug="nfl",
        api_endpoint=f"/nfl/api/preseason/market-board?season={season}&week={selected_week}",
        season=season,
        selected_week=selected_week,
        prev_week=prev_week,
        next_week=next_week,
        cards_href=f"/nfl/preseason/cards?season={season}&week={selected_week}",
        uncertainty_note=board.get("uncertainty_note"),
    )


@nfl_bp.get("/api/preseason/market-board")
def api_preseason_market_board():
    season = _selected_season()
    return jsonify(build_nfl_preseason_market_board(season, _selected_preseason_week(season)))


# ---------------------------------------------------------------------------
# Fantasy Football
# ---------------------------------------------------------------------------
#
# Its own season/week resolvers rather than `_selected_season()`/
# `_selected_week()`, for the reason the preseason block below already
# documents: a fantasy projection's week domain is the FULL 1-18 schedule of an
# upcoming season, while `available_weeks()` is driven by which projection
# artifacts happen to exist for the CURRENT one. Sharing the resolver would
# silently clamp a week-14 waiver question to whatever week the board last
# published.


def _fantasy_season() -> int:
    raw = (request.args.get("season") or "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_FANTASY_SEASON


def _fantasy_week() -> int | None:
    """None means "whole season", which is the draft view and the default."""
    raw = (request.args.get("week") or "").strip()
    if not raw:
        return None
    try:
        week = int(raw)
    except ValueError:
        return None
    return week if 1 <= week <= 18 else None


def _fantasy_flag(name: str) -> bool:
    return (request.args.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _fantasy_league():
    raw = (request.args.get("teams") or "").strip()
    try:
        teams = int(raw) if raw else None
    except ValueError:
        teams = None
    return resolve_league(teams=teams, superflex=_fantasy_flag("superflex"))


@nfl_bp.get("/fantasy")
def fantasy():
    context = build_fantasy_page_context(
        season=_fantasy_season(),
        scoring_key=request.args.get("scoring"),
        week=_fantasy_week(),
        use_news=_fantasy_flag("news"),
        league=_fantasy_league(),
    )
    return render_template("nfl/fantasy.html", **context)


@nfl_bp.get("/api/fantasy/projections")
def api_fantasy_projections():
    try:
        limit = int((request.args.get("limit") or "400").strip())
    except ValueError:
        limit = 400
    return jsonify(
        build_fantasy_payload(
            season=_fantasy_season(),
            scoring_key=request.args.get("scoring"),
            week=_fantasy_week(),
            position=request.args.get("position"),
            limit=max(1, min(limit, 2000)),
            use_news=_fantasy_flag("news"),
            league=_fantasy_league(),
        )
    )


@nfl_bp.get("/api/fantasy/draft-board")
def api_fantasy_draft_board():
    try:
        limit = int((request.args.get("limit") or "250").strip())
    except ValueError:
        limit = 250
    return jsonify(
        build_draft_board_payload(
            season=_fantasy_season(),
            scoring_key=request.args.get("scoring"),
            limit=max(1, min(limit, 2000)),
            use_news=_fantasy_flag("news"),
            league=_fantasy_league(),
        )
    )
