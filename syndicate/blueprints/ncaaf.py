from __future__ import annotations

from syndicate.blueprints.layer1_page import render_layer1_board
from flask import Blueprint, jsonify, render_template, request

from syndicate.features.ncaaf.archive import build_archive_api_payload
from syndicate.features.ncaaf.archive import build_archive_page_context
from syndicate.features.ncaaf.cards import build_cards_page_context
from syndicate.features.ncaaf.cards import build_ncaaf_market_board
from syndicate.features.ncaaf.cards import build_smartsim_cards_page_context
from syndicate.features.ncaaf.cards import _resolve_ncaaf_active_season_and_weeks
from syndicate.features.ncaaf.game_detail import build_game_detail_page_context
from syndicate.features.ncaaf.live_lens import build_live_lens_page_context
from syndicate.features.ncaaf.live_lens import build_smartsim_live_lens_page_context
from syndicate.features.ncaaf.betting_card import build_ncaaf_betting_card_page_context
from syndicate.features.ncaaf.picks import build_picks_page_context
from syndicate.features.ncaaf.picks import build_smartsim_picks_page_context
from syndicate.features.ncaaf.sources import default_season
from syndicate.features.ncaaf.sources import default_week
from syndicate.features.ncaaf.sources import week_summaries
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.shared.hub_summary import build_hub_bettor_summary
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.timezone import central_today_iso


ncaaf_bp = Blueprint("syndicate_ncaaf", __name__, url_prefix="/ncaaf")


def _selected_week() -> int:
    try:
        return int((request.args.get("week") or "").strip())
    except Exception:
        return default_week()


@ncaaf_bp.get("/hub")
def hub():
    # week_summaries() keeps its own per-week "season" tag (a real,
    # tested capability: different tracked weeks can belong to different
    # seasons) -- preserved as-is. Merged in on top: the real active
    # season/week (unions the legacy engine's own weeks with real
    # SmartSim2 projection-artifact weeks, same resolver cards.py/
    # picks.py already use), for any week not already covered by
    # week_summaries(). Needed because week_summaries() is tied to the
    # old, single-season summary-index pipeline and would otherwise never
    # surface a real active season (e.g. 2026) week_summaries() has never
    # heard of -- confirmed a real season/week mismatch risk while fixing
    # default_season() (pairing a correct active season with a week
    # number that only ever made sense for the old index's own season).
    legacy_weeks = week_summaries()
    available = [dict(week) for week in legacy_weeks if week["has_data"]]
    unavailable = [week for week in legacy_weeks if not week["has_data"]]

    active_season, active_real_weeks = _resolve_ncaaf_active_season_and_weeks()
    already_covered = {(entry.get("week"), entry.get("season")) for entry in available}
    for week in active_real_weeks:
        if (week, active_season) not in already_covered:
            available.append({"week": week, "season": active_season, "has_data": True})

    launch_week = active_real_weeks[-1] if active_real_weeks else (available[-1]["week"] if available else default_week())
    launch_season = active_season or default_season()
    return render_template(
        "ncaaf/hub.html",
        launch_season=launch_season,
        launch_week=launch_week,
        available_weeks=available,
        unavailable_weeks=unavailable,
        summary_stats=[
            {"label": "Weeks with data", "value": str(len(available))},
            {"label": "Tracked weeks", "value": str(len(legacy_weeks) or len(available))},
        ],
        hub_summary=build_hub_bettor_summary("ncaaf", today_value=central_today_iso()),
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
    context = build_ncaaf_betting_card_page_context(season, _selected_week())
    return render_template("ncaaf/betting_card.html", **context)

@ncaaf_bp.get("/api/season/<int:season>/betting-card")
def api_betting_card(season: int):
    context = build_ncaaf_betting_card_page_context(season, _selected_week())
    return jsonify(
        {
            "season": context["season"],
            "week": context["week"],
            "available_weeks": context["available_weeks"],
            "date": context["date"],
            "week_summary": context["week_summary"],
            "days": context["days"],
            "using_sample_data": context["using_sample_data"],
            "source_path": context.get("source_path"),
            "source_title": context.get("source_title"),
            "route_path": context.get("route_path"),
            "prev_href": context.get("prev_href"),
            "next_href": context.get("next_href"),
            "header_stats": context.get("header_stats"),
        }
    )


@ncaaf_bp.get("/api/picks")
def api_picks():
    context = build_smartsim_picks_page_context(_selected_week())
    payload = build_rank_api_payload(context)
    payload["week"] = context["week"]
    payload["available_weeks"] = context["available_weeks"]
    return jsonify(payload)


@ncaaf_bp.get("/market-board")
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
    return render_layer1_board("ncaaf")

@ncaaf_bp.get("/api/market-board")
def api_market_board():
    return jsonify(build_ncaaf_market_board(_selected_week()))