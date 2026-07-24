from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, request

from syndicate.features.soccer.archive import build_archive_api_payload
from syndicate.features.soccer.archive import build_archive_page_context
from syndicate.features.soccer.cards import build_cards_page_context
from syndicate.features.soccer.game_detail import build_game_detail_page_context
from syndicate.features.soccer.live_lens import build_live_lens_api_payload
from syndicate.features.soccer.live_lens import build_live_lens_page_context
from syndicate.features.soccer.market_board import build_soccer_market_board
from syndicate.features.soccer.props import build_props_page_context
from syndicate.features.soccer.sources import DEFAULT_LEAGUE
from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES
from syndicate.features.soccer.sources import available_weeks
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import default_week
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import schedule_payload
from syndicate.features.soccer.sources import sparse_roster_teams
from syndicate.features.soccer.team import build_roster_api_payload
from syndicate.features.soccer.team import build_roster_page_context
from syndicate.features.soccer.team import build_team_schedule_api_payload
from syndicate.features.soccer.team import build_team_schedule_page_context
from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.timezone import central_today_iso


soccer_bp = Blueprint("syndicate_soccer", __name__, url_prefix="/soccer")


def _selected_season(league: str) -> int:
    raw = (request.args.get("season") or "").strip()
    if raw.isdigit():
        return int(raw)
    return default_season(league)


def _selected_week(league: str, season: int) -> int:
    raw = (request.args.get("week") or "").strip()
    if raw.isdigit():
        return int(raw)
    return default_week(league, season)


@soccer_bp.get("/hub")
def hub():
    today_date = central_today_iso()
    leagues = []
    for slug, name in LEAGUE_DISPLAY_NAMES.items():
        season = default_season(slug)
        weeks = available_weeks(slug, season)
        sparse = sparse_roster_teams(slug, season)
        leagues.append(
            {
                "slug": slug,
                "name": name,
                "season": season,
                "weeks": weeks,
                "current_week": default_week(slug, season) if weeks else None,
                "sparse_roster_count": len(sparse),
            }
        )
    leagues_with_data = [item for item in leagues if item["weeks"]]
    return render_template(
        "soccer/hub.html",
        today_date=today_date,
        default_league=DEFAULT_LEAGUE,
        leagues=leagues,
        leagues_with_data=leagues_with_data,
        summary_stats=[
            {"label": "Leagues covered", "value": str(len(leagues))},
            {"label": "Leagues with a stored schedule", "value": str(len(leagues_with_data))},
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
    season = _selected_season(league)
    week = _selected_week(league, season)
    context = build_cards_page_context(league, week, season)
    return render_template("shared/game_cards_board.html", **context)


@soccer_bp.get("/<league>/api/cards")
def api_cards(league: str):
    league = normalize_league(league)
    season = _selected_season(league)
    week = _selected_week(league, season)
    context = build_cards_page_context(league, week, season)
    return jsonify(build_game_board_api_payload(context))


@soccer_bp.get("/<league>/market-board")
def market_board(league: str):
    # Layer 1 (see ~/.claude/plans/expressive-wiggling-engelbart.md): every
    # quoted moneyline/total/spread/prop line for this league's slate on a
    # given date, joined against SoccerSim's projections where coverage
    # exists -- same shared card/bet-slip template MLB/NBA/WNBA use, with
    # row data fetched client-side from /soccer/<league>/api/market-board.
    league = normalize_league(league)
    selected_date = (request.args.get("date") or "").strip() or central_today_iso()
    parsed_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
    return render_template(
        "shared/market_board.html",
        sport_label=league_display_name(league),
        sport_slug=league,
        api_endpoint=f"/soccer/{league}/api/market-board?date={selected_date}",
        selected_date=selected_date,
        prev_date=(parsed_date - timedelta(days=1)).isoformat(),
        next_date=(parsed_date + timedelta(days=1)).isoformat(),
        cards_href=f"/soccer/{league}/cards",
    )


@soccer_bp.get("/<league>/api/market-board")
def api_market_board(league: str):
    league = normalize_league(league)
    selected_date = (request.args.get("date") or "").strip() or central_today_iso()
    return jsonify(build_soccer_market_board(league, selected_date))


@soccer_bp.get("/<league>/game/<game_pk>")
def game_detail(league: str, game_pk: str):
    league = normalize_league(league)
    season = _selected_season(league)
    week = _selected_week(league, season)
    context = build_game_detail_page_context(league, week, season, game_pk)
    return render_template("shared/game_cards_board.html", **context)


@soccer_bp.get("/<league>/api/game/<game_pk>")
def api_game_detail(league: str, game_pk: str):
    league = normalize_league(league)
    season = _selected_season(league)
    week = _selected_week(league, season)
    context = build_game_detail_page_context(league, week, season, game_pk)
    return jsonify(build_game_board_api_payload(context))


@soccer_bp.get("/<league>/live-lens")
def live_lens(league: str):
    league = normalize_league(league)
    season = _selected_season(league)
    week = _selected_week(league, season)
    context = build_live_lens_page_context(league, week, season)
    return render_template("shared/rank_board.html", **context)


@soccer_bp.get("/<league>/api/live-lens")
def api_live_lens(league: str):
    league = normalize_league(league)
    season = _selected_season(league)
    week = _selected_week(league, season)
    return jsonify(build_live_lens_api_payload(league, week, season))


@soccer_bp.get("/<league>/archive")
def archive(league: str):
    league = normalize_league(league)
    season = _selected_season(league)
    week = _selected_week(league, season)
    context = build_archive_page_context(league, week, season)
    return render_template("shared/rank_board.html", **context)


@soccer_bp.get("/<league>/api/archive")
def api_archive(league: str):
    league = normalize_league(league)
    season = _selected_season(league)
    week = _selected_week(league, season)
    return jsonify(build_archive_api_payload(league, week, season))


@soccer_bp.get("/<league>/props")
def props(league: str):
    league = normalize_league(league)
    season = _selected_season(league)
    week = _selected_week(league, season)
    context = build_props_page_context(
        league,
        week,
        season,
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
    season = _selected_season(league)
    week = _selected_week(league, season)
    context = build_props_page_context(
        league,
        week,
        season,
        filters={
            "team": request.args.get("team"),
            "player": request.args.get("player"),
            "sort": request.args.get("sort"),
        },
    )
    return jsonify(build_rank_api_payload(context))


@soccer_bp.get("/<league>/team/<team_id>/roster")
def team_roster(league: str, team_id: str):
    league = normalize_league(league)
    season = _selected_season(league)
    context = build_roster_page_context(league, team_id, season)
    return render_template("shared/rank_board.html", **context)


@soccer_bp.get("/<league>/api/team/<team_id>/roster")
def api_team_roster(league: str, team_id: str):
    league = normalize_league(league)
    season = _selected_season(league)
    return jsonify(build_roster_api_payload(league, team_id, season))


@soccer_bp.get("/<league>/team/<team_id>/schedule")
def team_schedule(league: str, team_id: str):
    league = normalize_league(league)
    season = _selected_season(league)
    context = build_team_schedule_page_context(league, team_id, season)
    return render_template("shared/rank_board.html", **context)


@soccer_bp.get("/<league>/api/team/<team_id>/schedule")
def api_team_schedule(league: str, team_id: str):
    league = normalize_league(league)
    season = _selected_season(league)
    return jsonify(build_team_schedule_api_payload(league, team_id, season))


@soccer_bp.get("/<league>/api/schedule")
def api_schedule(league: str):
    league = normalize_league(league)
    season = _selected_season(league)
    payload = schedule_payload(league, season) or {"league": league, "season": season, "weeks": [], "matches": []}
    return jsonify(payload)
