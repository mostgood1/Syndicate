from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from syndicate.features.nfl.archive import build_archive_api_payload
from syndicate.features.nfl.archive import build_archive_page_context
from syndicate.features.nfl.cards import build_cards_page_context
from syndicate.features.nfl.game_detail import build_game_detail_page_context
from syndicate.features.nfl.live_lens import build_live_lens_page_context
from syndicate.features.nfl.picks import build_betting_card_page_context
from syndicate.features.nfl.picks import build_picks_page_context
from syndicate.features.nfl.sources import default_week
from syndicate.features.nfl.sources import latest_season
from syndicate.features.nfl.sources import tracked_week
from syndicate.features.nfl.sources import week_summaries
from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.shared.rank_board import build_rank_api_payload


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