from __future__ import annotations

from datetime import date

from syndicate.blueprints.layer1_page import render_layer1_board
from flask import Blueprint, jsonify, render_template, request

from syndicate.features.ncaab.cards import build_cards_page_context
from syndicate.features.ncaab.game_detail import build_game_detail_page_context
from syndicate.features.ncaab.live_lens import build_live_lens_api_payload
from syndicate.features.ncaab.live_lens import build_live_lens_page_context
from syndicate.features.ncaab.results_archive import build_results_archive_api_payload
from syndicate.features.ncaab.results_archive import build_results_archive_page_context
from syndicate.features.ncaab.sources import available_dates
from syndicate.features.ncaab.sources import default_date
from syndicate.features.ncaab.sources import latest_date
from syndicate.features.ncaab.sources import default_season_date
from syndicate.features.ncaab.sources import season_for_date
from syndicate.features.ncaab.sources import season_dates
from syndicate.features.ncaab.season import build_season_page_context
from syndicate.features.ncaab.season import build_season_betting_card_api_payload
from syndicate.features.ncaab.season import build_season_betting_card_page_context
from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.shared.hub_summary import build_hub_bettor_summary
from syndicate.features.shared.timezone import central_today_iso


ncaab_bp = Blueprint("syndicate_ncaab", __name__, url_prefix="/ncaab")


def _selected_date() -> str:
    return (request.args.get("date") or "").strip() or default_date()


def _selected_live_date() -> str:
    return (request.args.get("date") or "").strip() or central_today_iso()


def _selected_season_date(season: int) -> str:
    return (request.args.get("date") or "").strip() or default_season_date(season)


@ncaab_bp.get("/hub")
def hub():
    dates = available_dates()
    launch_date = central_today_iso()
    launch_season = season_for_date(launch_date)
    available_date_cards = [
        {"date": selected_date, "season": season_for_date(selected_date)}
        for selected_date in dates[-8:]
    ]
    return render_template(
        "ncaab/hub.html",
        launch_date=launch_date,
        today_date=central_today_iso(),
        launch_season=launch_season,
        season_launch_date=default_season_date(launch_season),
        season_dates_count=len(season_dates(launch_season)),
        available_dates=dates,
        available_date_cards=available_date_cards,
        summary_stats=[
            {"label": "Tracked dates", "value": str(len(dates))},
            {"label": "Latest date", "value": latest_date()},
            {"label": "Launch date", "value": launch_date},
        ],
        hub_summary=build_hub_bettor_summary("ncaab", today_value=launch_date),
    )


@ncaab_bp.get("")
def root_cards():
    return cards()


@ncaab_bp.get("/market-board")
def market_board():
    """`#329`. This route did not exist: /ncaab/market-board returned 404 on
    production 2026-08-10 while /api/board/book-grid served ncaab by
    parameter. Out of season it renders an empty board that says WHY (`#296`),
    which is a different and more useful answer than "no such page".
    """
    return render_layer1_board("ncaab")


@ncaab_bp.get("/cards")
def cards():
    context = build_cards_page_context(_selected_date())
    return render_template("shared/game_cards_board.html", **context)


@ncaab_bp.get("/api/cards")
def api_cards():
    context = build_cards_page_context(_selected_date())
    return jsonify(build_game_board_api_payload(context))


@ncaab_bp.get("/live-lens")
def live_lens():
    context = build_live_lens_page_context(_selected_live_date())
    return render_template("shared/rank_board.html", **context)


@ncaab_bp.get("/api/live-lens")
def api_live_lens():
    return jsonify(build_live_lens_api_payload(_selected_live_date()))


@ncaab_bp.get("/results")
def results_archive():
    context = build_results_archive_page_context(_selected_date())
    return render_template("shared/rank_board.html", **context)


@ncaab_bp.get("/archive")
def daily_archive():
    context = build_results_archive_page_context(_selected_date())
    return render_template("shared/rank_board.html", **context)


@ncaab_bp.get("/api/results")
def api_results_archive():
    return jsonify(build_results_archive_api_payload(_selected_date()))


@ncaab_bp.get("/api/archive")
def api_daily_archive():
    return jsonify(build_results_archive_api_payload(_selected_date()))


@ncaab_bp.get("/season/<int:season>")
def season_review(season: int):
    context = build_season_page_context(season, _selected_season_date(season))
    return render_template("shared/game_cards_board.html", **context)


@ncaab_bp.get("/api/season/<int:season>")
def api_season_review(season: int):
    context = build_season_page_context(season, _selected_season_date(season))
    return jsonify(build_game_board_api_payload(context))


@ncaab_bp.get("/season/<int:season>/betting-card")
def season_betting_card(season: int):
    context = build_season_betting_card_page_context(season, _selected_season_date(season))
    return render_template("shared/rank_board.html", **context)


@ncaab_bp.get("/api/season/<int:season>/betting-card")
def api_season_betting_card(season: int):
    return jsonify(build_season_betting_card_api_payload(season, _selected_season_date(season)))


@ncaab_bp.get("/game/<game_pk>")
def game_detail(game_pk: str):
    context = build_game_detail_page_context(_selected_date(), game_pk)
    return render_template("shared/game_cards_board.html", **context)


@ncaab_bp.get("/api/game/<game_pk>")
def api_game_detail(game_pk: str):
    context = build_game_detail_page_context(_selected_date(), game_pk)
    return jsonify(build_game_board_api_payload(context))