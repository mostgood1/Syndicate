from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request

from syndicate.features.soccer.archive import build_archive_api_payload
from syndicate.features.soccer.archive import build_archive_page_context
from syndicate.features.soccer.cards import build_cards_page_context
from syndicate.features.soccer.game_detail import build_game_detail_page_context
from syndicate.features.soccer.live_lens import build_live_lens_api_payload
from syndicate.features.soccer.live_lens import build_live_lens_page_context
from syndicate.features.soccer.props import build_props_page_context
from syndicate.features.soccer.sources import DEFAULT_LEAGUE
from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES
from syndicate.features.soccer.sources import available_dates
from syndicate.features.soccer.sources import default_date
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.timezone import central_today_iso


soccer_bp = Blueprint("syndicate_soccer", __name__, url_prefix="/soccer")


def _selected_date(league: str) -> str:
    return (request.args.get("date") or "").strip() or default_date(league)


@soccer_bp.get("/hub")
def hub():
    today_date = central_today_iso()
    leagues = [
        {
            "slug": slug,
            "name": name,
            "dates": available_dates(slug),
            "latest_date": (available_dates(slug) or [None])[-1],
        }
        for slug, name in LEAGUE_DISPLAY_NAMES.items()
    ]
    leagues_with_data = [item for item in leagues if item["dates"]]
    return render_template(
        "soccer/hub.html",
        today_date=today_date,
        default_league=DEFAULT_LEAGUE,
        leagues=leagues,
        leagues_with_data=leagues_with_data,
        summary_stats=[
            {"label": "Leagues covered", "value": str(len(leagues))},
            {"label": "Leagues with stored dates", "value": str(len(leagues_with_data))},
            {"label": "Launch league", "value": league_display_name(DEFAULT_LEAGUE)},
        ],
    )


@soccer_bp.get("")
def root():
    return redirect(f"/soccer/{DEFAULT_LEAGUE}/cards")


@soccer_bp.get("/<league>")
def league_root(league: str):
    return redirect(f"/soccer/{normalize_league(league)}/cards")


@soccer_bp.get("/<league>/cards")
def cards(league: str):
    league = normalize_league(league)
    context = build_cards_page_context(league, _selected_date(league))
    return render_template("shared/game_cards_board.html", **context)


@soccer_bp.get("/<league>/api/cards")
def api_cards(league: str):
    league = normalize_league(league)
    context = build_cards_page_context(league, _selected_date(league))
    return jsonify(build_game_board_api_payload(context))


@soccer_bp.get("/<league>/game/<game_pk>")
def game_detail(league: str, game_pk: str):
    league = normalize_league(league)
    context = build_game_detail_page_context(league, _selected_date(league), game_pk)
    return render_template("shared/game_cards_board.html", **context)


@soccer_bp.get("/<league>/api/game/<game_pk>")
def api_game_detail(league: str, game_pk: str):
    league = normalize_league(league)
    context = build_game_detail_page_context(league, _selected_date(league), game_pk)
    return jsonify(build_game_board_api_payload(context))


@soccer_bp.get("/<league>/live-lens")
def live_lens(league: str):
    league = normalize_league(league)
    context = build_live_lens_page_context(league, _selected_date(league))
    return render_template("shared/rank_board.html", **context)


@soccer_bp.get("/<league>/api/live-lens")
def api_live_lens(league: str):
    league = normalize_league(league)
    return jsonify(build_live_lens_api_payload(league, _selected_date(league)))


@soccer_bp.get("/<league>/archive")
def archive(league: str):
    league = normalize_league(league)
    context = build_archive_page_context(league, _selected_date(league))
    return render_template("shared/rank_board.html", **context)


@soccer_bp.get("/<league>/api/archive")
def api_archive(league: str):
    league = normalize_league(league)
    return jsonify(build_archive_api_payload(league, _selected_date(league)))


@soccer_bp.get("/<league>/props")
def props(league: str):
    league = normalize_league(league)
    context = build_props_page_context(
        league,
        _selected_date(league),
        filters={
            "team": request.args.get("team"),
            "player": request.args.get("player"),
            "sort": request.args.get("sort"),
        },
    )
    return render_template("shared/rank_board.html", **context)


@soccer_bp.get("/<league>/api/props")
def api_props(league: str):
    league = normalize_league(league)
    context = build_props_page_context(
        league,
        _selected_date(league),
        filters={
            "team": request.args.get("team"),
            "player": request.args.get("player"),
            "sort": request.args.get("sort"),
        },
    )
    return jsonify(build_rank_api_payload(context))
