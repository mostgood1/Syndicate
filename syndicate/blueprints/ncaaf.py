from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from syndicate.features.ncaaf.archive import build_archive_api_payload
from syndicate.features.ncaaf.archive import build_archive_page_context
from syndicate.features.ncaaf.cards import build_cards_page_context
from syndicate.features.ncaaf.cards import build_ncaaf_market_board
from syndicate.features.ncaaf.cards import build_smartsim_cards_page_context
from syndicate.features.ncaaf.game_detail import build_game_detail_page_context
from syndicate.features.ncaaf.live_lens import build_live_lens_page_context
from syndicate.features.ncaaf.live_lens import build_smartsim_live_lens_page_context
from syndicate.features.ncaaf.picks import build_picks_page_context
from syndicate.features.ncaaf.picks import build_betting_card_page_context
from syndicate.features.ncaaf.picks import build_smartsim_picks_page_context
from syndicate.features.ncaaf.sources import default_season
from syndicate.features.ncaaf.sources import default_week
from syndicate.features.ncaaf.sources import week_summaries
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.shared.rank_board import build_rank_api_payload


ncaaf_bp = Blueprint("syndicate_ncaaf", __name__, url_prefix="/ncaaf")


def _selected_week() -> int:
    try:
        return int((request.args.get("week") or "").strip())
    except Exception:
        return default_week()


@ncaaf_bp.get("/hub")
def hub():
    weeks = week_summaries()
    available = [week for week in weeks if week["has_data"]]
    unavailable = [week for week in weeks if not week["has_data"]]
    launch_week = available[-1]["week"] if available else default_week()
    launch_season = default_season()
    return render_template(
        "ncaaf/hub.html",
        launch_season=launch_season,
        launch_week=launch_week,
        available_weeks=available,
        unavailable_weeks=unavailable,
        summary_stats=[
            {"label": "Weeks with data", "value": str(len(available))},
            {"label": "Tracked weeks", "value": str(len(weeks))},
        ],
    )


@ncaaf_bp.get("")
def root_cards():
    return cards()


@ncaaf_bp.get("/cards")
def cards():
    context = build_smartsim_cards_page_context(_selected_week())
    return render_template("shared/game_cards_board.html", **context)


@ncaaf_bp.get("/api/cards")
def api_cards():
    context = build_smartsim_cards_page_context(_selected_week())
    return jsonify(build_game_board_api_payload(context))


@ncaaf_bp.get("/game/<game_pk>")
def game_detail(game_pk: str):
    context = build_game_detail_page_context(_selected_week(), game_pk)
    return render_template("shared/game_cards_board.html", **context)


@ncaaf_bp.get("/api/game/<game_pk>")
def api_game_detail(game_pk: str):
    context = build_game_detail_page_context(_selected_week(), game_pk)
    return jsonify(build_game_board_api_payload(context))


@ncaaf_bp.get("/api/weeks")
def api_weeks():
    weeks = week_summaries()
    return jsonify(
        {
            "weeks": weeks,
            "available_weeks": [week["week"] for week in weeks if week["has_data"]],
        }
    )


@ncaaf_bp.get("/archive")
def archive():
    context = build_archive_page_context(_selected_week())
    return render_template("shared/rank_board.html", **context)


@ncaaf_bp.get("/api/archive")
def api_archive():
    return jsonify(build_archive_api_payload(_selected_week()))


@ncaaf_bp.get("/picks")
def picks():
    context = build_smartsim_picks_page_context(_selected_week())
    return render_template("shared/rank_board.html", **context)


@ncaaf_bp.get("/live-lens")
def live_lens():
    context = build_smartsim_live_lens_page_context(_selected_week())
    return render_template("shared/rank_board.html", **context)


@ncaaf_bp.get("/api/live-lens")
def api_live_lens():
    context = build_smartsim_live_lens_page_context(_selected_week())
    payload = build_rank_api_payload(context)
    payload["week"] = context["week"]
    payload["available_weeks"] = context["available_weeks"]
    payload["season"] = context["season"]
    return jsonify(payload)

@ncaaf_bp.get("/season/<int:season>/betting-card")
def betting_card(season: int):
    context = build_betting_card_page_context(season, _selected_week())
    return render_template("shared/rank_board.html", **context)

@ncaaf_bp.get("/api/season/<int:season>/betting-card")
def api_betting_card(season: int):
    context = build_betting_card_page_context(season, _selected_week())
    payload = build_rank_api_payload(context)
    payload["season"] = season
    payload["week"] = context["week"]
    payload["available_weeks"] = context["available_weeks"]
    return jsonify(payload)


@ncaaf_bp.get("/api/picks")
def api_picks():
    context = build_smartsim_picks_page_context(_selected_week())
    payload = build_rank_api_payload(context)
    payload["week"] = context["week"]
    payload["available_weeks"] = context["available_weeks"]
    return jsonify(payload)


@ncaaf_bp.get("/market-board")
def market_board():
    selected_week = _selected_week()
    weeks = [week["week"] for week in week_summaries()]
    prev_week, next_week = neighboring_values(weeks, selected_week, fallback=selected_week)
    return render_template(
        "ncaaf/market_board.html",
        sport_label="NCAAF",
        sport_slug="ncaaf",
        api_endpoint=f"/ncaaf/api/market-board?week={selected_week}",
        selected_week=selected_week,
        prev_week=prev_week,
        next_week=next_week,
        cards_href=f"/ncaaf/cards?week={selected_week}",
    )


@ncaaf_bp.get("/api/market-board")
def api_market_board():
    return jsonify(build_ncaaf_market_board(_selected_week()))