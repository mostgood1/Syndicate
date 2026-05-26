from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qsl
from urllib.parse import urlencode

from flask import Blueprint, Response, jsonify, render_template, request

from syndicate.features.nba.betting_recap import build_betting_recap_payload
from syndicate.features.nba.betting_card import build_season_betting_card_day_payload
from syndicate.features.nba.betting_card import build_season_betting_card_manifest_payload
from syndicate.features.nba.betting_card import source_betting_card_asset_version
from syndicate.features.nba.betting_card import source_betting_card_css
from syndicate.features.nba.betting_card import source_betting_card_js
from syndicate.features.nba.archive import build_archive_api_payload
from syndicate.features.nba.archive import build_archive_page_context
from syndicate.features.nba.cards import build_cards_page_context
from syndicate.features.nba.cards import build_cards_api_payload
from syndicate.features.nba.cards import build_cards_sim_detail_payload
from syndicate.features.nba.cards import build_live_lens_tuning_payload
from syndicate.features.nba.cards import build_live_player_lens_payload
from syndicate.features.nba.cards import build_live_lines_payload
from syndicate.features.nba.cards import build_live_pbp_stats_payload
from syndicate.features.nba.cards import build_live_player_boxscore_payload
from syndicate.features.nba.cards import build_live_state_payload
from syndicate.features.nba.features import build_features_payload
from syndicate.features.nba.game_detail import build_game_detail_page_context
from syndicate.features.nba.live_game_accuracy import build_live_game_accuracy_payload
from syndicate.features.nba.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload
from syndicate.features.nba.live_prop_accuracy import build_live_prop_accuracy_payload
from syndicate.features.nba.live_prop_audit import build_live_prop_audit_payload
from syndicate.features.nba.market_accuracy import build_market_accuracy_payload
from syndicate.features.nba.picks import build_picks_page_context
from syndicate.features.nba.props import build_props_page_context
from syndicate.features.nba.sources import available_dates
from syndicate.features.nba.sources import default_date
from syndicate.features.nba.sources import default_date_for_season
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.timezone import central_today_iso


nba_bp = Blueprint("syndicate_nba", __name__, url_prefix="/nba")


def _cards_source_asset_version() -> str:
    static_root = Path(__file__).resolve().parents[1] / "static"
    paths = [
        static_root / "shared" / "standalone_shell.css",
        static_root / "nba" / "cards_source.css",
        static_root / "nba" / "cards_source.js",
    ]
    mtimes: list[int] = []
    for path in paths:
        try:
            mtimes.append(int(path.stat().st_mtime_ns))
        except OSError:
            continue
    if mtimes:
        return str(max(mtimes))
    return "1"


def _selected_date(season: int | None = None) -> str:
    fallback = default_date_for_season(int(season)) if season is not None else default_date()
    return (request.args.get("date") or fallback).strip()


def _live_lens_query_string(season: int | None = None) -> str:
    query_items = list(parse_qsl(request.query_string.decode("utf-8") if request.query_string else "", keep_blank_values=True))
    if season is None:
        return urlencode(query_items)
    keys = {key for key, _ in query_items}
    if {"date", "start", "end", "since", "until", "days"}.isdisjoint(keys):
        query_items.append(("date", default_date_for_season(int(season))))
    return urlencode(query_items)


def _season_window_query_string(season: int | None = None, *, default_days: int = 14) -> str:
    query_items = list(parse_qsl(request.query_string.decode("utf-8") if request.query_string else "", keep_blank_values=True))
    if season is None:
        return urlencode(query_items)
    keys = {key for key, _ in query_items}
    if {"since", "until", "days"}.isdisjoint(keys):
        query_map = dict(query_items)
        target_date = str(query_map.get("date") or default_date_for_season(int(season))).strip()
        try:
            until_date = date.fromisoformat(target_date)
        except ValueError:
            until_date = date.fromisoformat(default_date_for_season(int(season)))
        since_date = until_date - timedelta(days=max(1, default_days) - 1)
        query_items.extend(
            [
                ("since", since_date.isoformat()),
                ("until", until_date.isoformat()),
                ("days", str(default_days)),
            ]
        )
    return urlencode(query_items)


@nba_bp.get("/hub")
def hub():
    dates = available_dates()
    latest_date = dates[-1] if dates else default_date()
    today_date = central_today_iso()
    recent_slates = list(reversed(dates[-4:])) if dates else [latest_date]
    summary_stats = [
        {"label": "Stored dates", "value": str(len(dates))},
        {"label": "Latest date", "value": latest_date},
        {"label": "Launch surface", "value": "Cards"},
    ]
    return render_template(
        "nba/hub.html",
        latest_date=latest_date,
        today_date=today_date,
        recent_slates=recent_slates,
        summary_stats=summary_stats,
    )


@nba_bp.get("")
def root_cards():
    return cards()


@nba_bp.get("/archive")
def archive():
    selected_date = _selected_date()
    context = build_archive_page_context(selected_date)
    return render_template("nba/archive.html", show_app_header=False, **context)


@nba_bp.get("/cards")
def cards():
    selected_date = _selected_date()
    context = build_cards_page_context(selected_date)
    client = (request.args.get("client") or "").strip().lower()
    if client == "board":
        return render_template("shared/game_cards_board.html", **context)
    return render_template("nba/cards_source.html", asset_version=_cards_source_asset_version(), **context)


@nba_bp.get("/season/<int:season>/betting-card")
def season_betting_card(season: int):
    selected_date = _selected_date(season)
    profile = str(request.args.get("profile") or "retuned").strip().lower() or "retuned"
    return render_template(
        "nba/betting_card.html",
        season=season,
        date=selected_date,
        profile=profile,
        asset_version=source_betting_card_asset_version(),
    )


def _features_template_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, object]:
    resolved_season = int(season) if season is not None else (date.fromisoformat(selected_date).year if len(selected_date) == 10 else date.today().year)
    normalized_profile = str(profile or "").strip().lower() or ("retuned" if season is not None else None)
    if season is not None:
        betting_card_query = f"?profile={normalized_profile}&date={selected_date}" if normalized_profile else f"?date={selected_date}"
        route_query = f"?date={selected_date}&profile={normalized_profile}" if normalized_profile else f"?date={selected_date}"
        return {
            "date": selected_date,
            "season": resolved_season,
            "api_path": "/nba/api/features",
            "api_label": "/api/features",
            "back_href": f"/nba/season/{resolved_season}/betting-card{betting_card_query}",
            "back_label": "Betting Card",
            "recap_href": f"/nba/season/{resolved_season}/reconciliation{route_query}",
            "self_href": f"/nba/features{route_query}",
        }
    return {
        "date": selected_date,
        "season": resolved_season,
        "api_path": "/nba/api/features",
        "api_label": "/api/features",
        "back_href": f"/nba/cards?date={selected_date}",
        "back_label": "Cards",
        "recap_href": None,
        "self_href": f"/nba/features?date={selected_date}",
    }


def _betting_recap_template_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, object]:
    resolved_season = int(season) if season is not None else (date.fromisoformat(selected_date).year if len(selected_date) == 10 else date.today().year)
    normalized_profile = str(profile or "").strip().lower() or ("retuned" if season is not None else None)
    try:
        until_date = date.fromisoformat(selected_date)
    except ValueError:
        until_date = date.today()
    since_date = (until_date - timedelta(days=13)).isoformat()
    until_value = until_date.isoformat()
    if season is not None:
        betting_card_query = f"?profile={normalized_profile}&date={selected_date}" if normalized_profile else f"?date={selected_date}"
        route_query = f"?date={selected_date}&profile={normalized_profile}" if normalized_profile else f"?date={selected_date}"
        return {
            "date": selected_date,
            "season": resolved_season,
            "default_since": since_date,
            "default_until": until_value,
            "default_days": 14,
            "api_path": f"/nba/api/season/{resolved_season}/betting-recap",
            "api_label": f"/api/season/{resolved_season}/betting-recap",
            "back_href": f"/nba/season/{resolved_season}/betting-card{betting_card_query}",
            "back_label": "Betting Card",
            "market_accuracy_href": f"/nba/season/{resolved_season}/market-accuracy{route_query}",
            "live_lens_href": f"/nba/season/{resolved_season}/live-lens{route_query}",
            "self_href": f"/nba/season/{resolved_season}/reconciliation{route_query}",
        }
    return {
        "date": selected_date,
        "season": resolved_season,
        "default_since": since_date,
        "default_until": until_value,
        "default_days": 14,
        "api_path": "/nba/api/betting-recap",
        "api_label": "/api/betting-recap",
        "back_href": f"/nba/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": None,
        "live_lens_href": None,
        "self_href": f"/nba/reconciliation?date={selected_date}",
    }


def _live_lens_template_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, object]:
    resolved_season = int(season) if season is not None else (date.fromisoformat(selected_date).year if len(selected_date) == 10 else date.today().year)
    normalized_profile = str(profile or "").strip().lower() or ("retuned" if season is not None else None)
    if season is not None:
        betting_card_query = f"?profile={normalized_profile}&date={selected_date}" if normalized_profile else f"?date={selected_date}"
        self_query = f"?date={selected_date}&profile={normalized_profile}" if normalized_profile else f"?date={selected_date}"
        return {
            "date": selected_date,
            "season": resolved_season,
            "api_path": f"/nba/api/season/{resolved_season}/live-lens",
            "api_label": f"/api/season/{resolved_season}/live-lens",
            "back_href": f"/nba/season/{resolved_season}/betting-card{betting_card_query}",
            "back_label": "Betting Card",
            "market_accuracy_href": f"/nba/season/{resolved_season}/market-accuracy{self_query}",
            "self_href": f"/nba/season/{resolved_season}/live-lens{self_query}",
            "accuracy_href": f"/nba/season/{resolved_season}/live-lens-accuracy{self_query}",
        }
    return {
        "date": selected_date,
        "season": resolved_season,
        "api_path": "/nba/api/live-player-props-audit",
        "api_label": "/api/live-player-props-audit",
        "back_href": f"/nba/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": None,
        "self_href": f"/nba/live-player-props-audit?date={selected_date}",
        "accuracy_href": None,
    }


def _live_lens_accuracy_template_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, object]:
    resolved_season = int(season) if season is not None else (date.fromisoformat(selected_date).year if len(selected_date) == 10 else date.today().year)
    normalized_profile = str(profile or "").strip().lower() or ("retuned" if season is not None else None)
    if season is not None:
        betting_card_query = f"?profile={normalized_profile}&date={selected_date}" if normalized_profile else f"?date={selected_date}"
        route_query = f"?date={selected_date}&profile={normalized_profile}" if normalized_profile else f"?date={selected_date}"
        return {
            "date": selected_date,
            "season": resolved_season,
            "api_path": f"/nba/api/season/{resolved_season}/live-lens-accuracy",
            "api_label": f"/api/season/{resolved_season}/live-lens-accuracy",
            "back_href": f"/nba/season/{resolved_season}/betting-card{betting_card_query}",
            "back_label": "Betting Card",
            "market_accuracy_href": f"/nba/season/{resolved_season}/market-accuracy{route_query}",
            "daily_accuracy_href": f"/nba/season/{resolved_season}/live-lens-daily-accuracy{route_query}",
            "game_accuracy_href": f"/nba/season/{resolved_season}/live-game-lens-accuracy{route_query}",
            "audit_href": f"/nba/season/{resolved_season}/live-lens{route_query}",
            "self_href": f"/nba/season/{resolved_season}/live-lens-accuracy{route_query}",
        }
    return {
        "date": selected_date,
        "season": resolved_season,
        "api_path": "/nba/api/live-player-props-lens-accuracy",
        "api_label": "/api/live-player-props-lens-accuracy",
        "back_href": f"/nba/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": None,
        "daily_accuracy_href": None,
        "game_accuracy_href": None,
        "audit_href": f"/nba/live-player-props-audit?date={selected_date}",
        "self_href": f"/nba/live-player-props-lens-accuracy?date={selected_date}",
    }


def _live_game_accuracy_template_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, object]:
    resolved_season = int(season) if season is not None else (date.fromisoformat(selected_date).year if len(selected_date) == 10 else date.today().year)
    normalized_profile = str(profile or "").strip().lower() or ("retuned" if season is not None else None)
    if season is not None:
        betting_card_query = f"?profile={normalized_profile}&date={selected_date}" if normalized_profile else f"?date={selected_date}"
        route_query = f"?date={selected_date}&profile={normalized_profile}" if normalized_profile else f"?date={selected_date}"
        return {
            "date": selected_date,
            "season": resolved_season,
            "api_path": f"/nba/api/season/{resolved_season}/live-game-lens-accuracy",
            "api_label": f"/api/season/{resolved_season}/live-game-lens-accuracy",
            "back_href": f"/nba/season/{resolved_season}/betting-card{betting_card_query}",
            "back_label": "Betting Card",
            "market_accuracy_href": f"/nba/season/{resolved_season}/market-accuracy{route_query}",
            "daily_accuracy_href": f"/nba/season/{resolved_season}/live-lens-daily-accuracy{route_query}",
            "props_accuracy_href": f"/nba/season/{resolved_season}/live-lens-accuracy{route_query}",
            "self_href": f"/nba/season/{resolved_season}/live-game-lens-accuracy{route_query}",
        }
    return {
        "date": selected_date,
        "season": resolved_season,
        "api_path": "/nba/api/live-game-lens-accuracy",
        "api_label": "/api/live-game-lens-accuracy",
        "back_href": f"/nba/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": None,
        "daily_accuracy_href": None,
        "props_accuracy_href": None,
        "self_href": f"/nba/live-game-lens-accuracy?date={selected_date}",
    }


def _live_lens_daily_accuracy_template_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, object]:
    resolved_season = int(season) if season is not None else (date.fromisoformat(selected_date).year if len(selected_date) == 10 else date.today().year)
    normalized_profile = str(profile or "").strip().lower() or ("retuned" if season is not None else None)
    if season is not None:
        betting_card_query = f"?profile={normalized_profile}&date={selected_date}" if normalized_profile else f"?date={selected_date}"
        route_query = f"?date={selected_date}&profile={normalized_profile}" if normalized_profile else f"?date={selected_date}"
        return {
            "date": selected_date,
            "season": resolved_season,
            "api_path": f"/nba/api/season/{resolved_season}/live-lens-daily-accuracy",
            "api_label": f"/api/season/{resolved_season}/live-lens-daily-accuracy",
            "back_href": f"/nba/season/{resolved_season}/betting-card{betting_card_query}",
            "back_label": "Betting Card",
            "market_accuracy_href": f"/nba/season/{resolved_season}/market-accuracy{route_query}",
            "game_accuracy_href": f"/nba/season/{resolved_season}/live-game-lens-accuracy{route_query}",
            "props_accuracy_href": f"/nba/season/{resolved_season}/live-lens-accuracy{route_query}",
            "self_href": f"/nba/season/{resolved_season}/live-lens-daily-accuracy{route_query}",
        }
    return {
        "date": selected_date,
        "season": resolved_season,
        "api_path": "/nba/api/live-lens-accuracy",
        "api_label": "/api/live-lens-accuracy",
        "back_href": f"/nba/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": None,
        "game_accuracy_href": None,
        "props_accuracy_href": None,
        "self_href": f"/nba/live-lens-accuracy?date={selected_date}",
    }


def _market_accuracy_template_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, object]:
    resolved_season = int(season) if season is not None else (date.fromisoformat(selected_date).year if len(selected_date) == 10 else date.today().year)
    normalized_profile = str(profile or "").strip().lower() or ("retuned" if season is not None else None)
    if season is not None:
        betting_card_query = f"?profile={normalized_profile}&date={selected_date}" if normalized_profile else f"?date={selected_date}"
        route_query = f"?date={selected_date}&profile={normalized_profile}" if normalized_profile else f"?date={selected_date}"
        return {
            "date": selected_date,
            "season": resolved_season,
            "api_path": f"/nba/api/season/{resolved_season}/market-accuracy",
            "api_label": f"/api/season/{resolved_season}/market-accuracy",
            "back_href": f"/nba/season/{resolved_season}/betting-card{betting_card_query}",
            "back_label": "Betting Card",
            "daily_accuracy_href": f"/nba/season/{resolved_season}/live-lens-daily-accuracy{route_query}",
            "game_accuracy_href": f"/nba/season/{resolved_season}/live-game-lens-accuracy{route_query}",
            "props_accuracy_href": f"/nba/season/{resolved_season}/live-lens-accuracy{route_query}",
            "self_href": f"/nba/season/{resolved_season}/market-accuracy{route_query}",
        }
    return {
        "date": selected_date,
        "season": resolved_season,
        "api_path": "/nba/api/market-accuracy",
        "api_label": "/api/market-accuracy",
        "back_href": f"/nba/cards?date={selected_date}",
        "back_label": "Cards",
        "daily_accuracy_href": None,
        "game_accuracy_href": None,
        "props_accuracy_href": None,
        "self_href": f"/nba/market-accuracy?date={selected_date}",
    }


@nba_bp.get("/live-lens")
def live_lens():
    selected_date = _selected_date()
    return render_template("nba/live_prop_audit.html", **_live_lens_template_context(selected_date))


@nba_bp.get("/live-player-props-audit")
def live_player_props_audit():
    selected_date = _selected_date()
    return render_template("nba/live_prop_audit.html", **_live_lens_template_context(selected_date))


@nba_bp.get("/live-player-props-lens-accuracy")
def live_player_props_lens_accuracy():
    selected_date = _selected_date()
    return render_template("nba/live_prop_accuracy.html", **_live_lens_accuracy_template_context(selected_date))


@nba_bp.get("/live-lens-accuracy")
def live_lens_accuracy():
    selected_date = _selected_date()
    return render_template("nba/live_lens_daily_accuracy.html", **_live_lens_daily_accuracy_template_context(selected_date))


@nba_bp.get("/live-game-lens-accuracy")
def live_game_lens_accuracy():
    selected_date = _selected_date()
    return render_template("nba/live_game_accuracy.html", **_live_game_accuracy_template_context(selected_date))


@nba_bp.get("/market-accuracy")
def market_accuracy():
    selected_date = _selected_date()
    return render_template("nba/market_accuracy.html", **_market_accuracy_template_context(selected_date))


@nba_bp.get("/betting-recap")
@nba_bp.get("/reconciliation")
def reconciliation_alias():
    selected_date = _selected_date()
    return render_template("nba/reconciliation.html", **_betting_recap_template_context(selected_date))


@nba_bp.get("/season/<int:season>/live-lens")
def season_live_lens(season: int):
    selected_date = _selected_date(season)
    profile = str(request.args.get("profile") or "").strip().lower() or None
    return render_template("nba/live_prop_audit.html", **_live_lens_template_context(selected_date, season=season, profile=profile))


@nba_bp.get("/season/<int:season>/live-lens-accuracy")
def season_live_lens_accuracy(season: int):
    selected_date = _selected_date(season)
    profile = str(request.args.get("profile") or "").strip().lower() or None
    return render_template("nba/live_prop_accuracy.html", **_live_lens_accuracy_template_context(selected_date, season=season, profile=profile))


@nba_bp.get("/season/<int:season>/live-game-lens-accuracy")
def season_live_game_lens_accuracy(season: int):
    selected_date = _selected_date(season)
    profile = str(request.args.get("profile") or "").strip().lower() or None
    return render_template("nba/live_game_accuracy.html", **_live_game_accuracy_template_context(selected_date, season=season, profile=profile))


@nba_bp.get("/season/<int:season>/live-lens-daily-accuracy")
def season_live_lens_daily_accuracy(season: int):
    selected_date = _selected_date(season)
    profile = str(request.args.get("profile") or "").strip().lower() or None
    return render_template("nba/live_lens_daily_accuracy.html", **_live_lens_daily_accuracy_template_context(selected_date, season=season, profile=profile))


@nba_bp.get("/season/<int:season>/market-accuracy")
def season_market_accuracy(season: int):
    selected_date = _selected_date(season)
    profile = str(request.args.get("profile") or "").strip().lower() or None
    return render_template("nba/market_accuracy.html", **_market_accuracy_template_context(selected_date, season=season, profile=profile))


@nba_bp.get("/season/<int:season>/reconciliation")
def season_reconciliation(season: int):
    selected_date = _selected_date(season)
    profile = str(request.args.get("profile") or "").strip().lower() or None
    return render_template("nba/reconciliation.html", **_betting_recap_template_context(selected_date, season=season, profile=profile))


@nba_bp.get("/features")
def features():
    selected_date = _selected_date()
    season = date.fromisoformat(selected_date).year if len(selected_date) == 10 else date.today().year
    profile = str(request.args.get("profile") or "retuned").strip().lower() or "retuned"
    return render_template("nba/features.html", **_features_template_context(selected_date, season=season, profile=profile))


@nba_bp.get("/game/<game_pk>")
def game_detail(game_pk: str):
    selected_date = _selected_date()
    context = build_game_detail_page_context(selected_date, game_pk)
    return render_template("shared/game_cards_board.html", **context)


@nba_bp.get("/api/cards")
def api_cards():
    selected_date = _selected_date()
    return jsonify(build_cards_api_payload(selected_date))


@nba_bp.get("/api/archive")
def api_archive():
    selected_date = _selected_date()
    return jsonify(build_archive_api_payload(selected_date))


def _live_lens_payload_response(season: int | None = None):
    query_string = _live_lens_query_string(season)
    payload = build_live_prop_audit_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live player props audit"}), 502
    return jsonify(payload)


@nba_bp.get("/api/live-lens")
def api_live_lens():
    return _live_lens_payload_response()


@nba_bp.get("/api/live-player-props-audit")
def api_live_player_props_audit():
    return _live_lens_payload_response()


@nba_bp.get("/api/live-player-props-lens-accuracy")
def api_live_player_props_lens_accuracy():
    query_string = _live_lens_query_string()
    payload = build_live_prop_accuracy_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live player props lens accuracy"}), 502
    return jsonify(payload)


@nba_bp.get("/api/live-lens-accuracy")
def api_live_lens_accuracy():
    query_string = _live_lens_query_string()
    payload = build_live_lens_daily_accuracy_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live lens accuracy"}), 502
    return jsonify(payload)


@nba_bp.get("/api/live-game-lens-accuracy")
def api_live_game_lens_accuracy():
    query_string = _live_lens_query_string()
    payload = build_live_game_accuracy_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live game lens accuracy"}), 502
    return jsonify(payload)


@nba_bp.get("/api/market-accuracy")
def api_market_accuracy():
    query_string = _live_lens_query_string()
    payload = build_market_accuracy_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load market accuracy"}), 502
    return jsonify(payload)


@nba_bp.get("/api/betting-recap")
def api_betting_recap():
    query_string = _season_window_query_string()
    payload = build_betting_recap_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load betting recap"}), 502
    return jsonify(payload)


@nba_bp.get("/api/season/<int:season>/live-lens")
def api_season_live_lens(season: int):
    return _live_lens_payload_response(season)


@nba_bp.get("/api/season/<int:season>/live-lens-accuracy")
def api_season_live_lens_accuracy(season: int):
    query_string = _live_lens_query_string(season)
    payload = build_live_prop_accuracy_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live player props lens accuracy"}), 502
    return jsonify(payload)


@nba_bp.get("/api/season/<int:season>/live-game-lens-accuracy")
def api_season_live_game_lens_accuracy(season: int):
    query_string = _live_lens_query_string(season)
    payload = build_live_game_accuracy_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live game lens accuracy"}), 502
    return jsonify(payload)


@nba_bp.get("/api/season/<int:season>/live-lens-daily-accuracy")
def api_season_live_lens_daily_accuracy(season: int):
    query_string = _live_lens_query_string(season)
    payload = build_live_lens_daily_accuracy_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live lens daily accuracy"}), 502
    return jsonify(payload)


@nba_bp.get("/api/season/<int:season>/market-accuracy")
def api_season_market_accuracy(season: int):
    query_string = _live_lens_query_string(season)
    payload = build_market_accuracy_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load market accuracy"}), 502
    return jsonify(payload)


@nba_bp.get("/api/season/<int:season>/betting-recap")
def api_season_betting_recap(season: int):
    query_string = _season_window_query_string(season)
    payload = build_betting_recap_payload(query_string)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load betting recap"}), 502
    return jsonify(payload)


@nba_bp.get("/api/features")
def api_features():
    payload = build_features_payload()
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load features"}), 502
    return jsonify(payload)


@nba_bp.get("/api/season/<int:season>/betting-card")
def api_season_betting_card(season: int):
    selected_date = _selected_date(season)
    profile = str(request.args.get("profile") or "retuned").strip().lower() or "retuned"
    payload = build_season_betting_card_manifest_payload(season, profile, selected_date)
    if not isinstance(payload, dict):
        return jsonify({"error": "failed to load betting-card manifest", "season": season, "profile": profile}), 502
    return jsonify(payload)


@nba_bp.get("/api/season/<int:season>/betting-card/day/<date_str>")
def api_season_betting_card_day(season: int, date_str: str):
    profile = str(request.args.get("profile") or "retuned").strip().lower() or "retuned"
    include_prop_insights = str(request.args.get("include_prop_insights") or "").strip().lower() in {"1", "true", "yes", "on"}
    payload = build_season_betting_card_day_payload(
        season,
        date_str,
        profile,
        include_prop_insights=include_prop_insights,
    )
    if not isinstance(payload, dict):
        return jsonify({"error": "failed to load betting-card day", "season": season, "date": date_str, "profile": profile}), 502
    return jsonify(payload)


@nba_bp.get("/assets/betting-card-v2.css")
def betting_card_css():
    content = source_betting_card_css()
    if not content:
        return Response("/* missing betting-card css */", mimetype="text/css", status=404)
    return Response(content, mimetype="text/css")


@nba_bp.get("/assets/betting-card-v2.js")
def betting_card_js():
    content = source_betting_card_js()
    if not content:
        return Response("", mimetype="application/javascript", status=404)
    return Response(content, mimetype="application/javascript")


@nba_bp.get("/api/cards/sim-detail")
def api_cards_sim_detail():
    selected_date = _selected_date()
    away_tri = str(request.args.get("away") or "").strip().upper()
    home_tri = str(request.args.get("home") or "").strip().upper()
    if not away_tri or not home_tri:
        return jsonify({"error": "missing home/away"}), 400
    return jsonify(build_cards_sim_detail_payload(selected_date, away_tri, home_tri))


@nba_bp.get("/api/live_state")
def api_live_state():
    selected_date = _selected_date()
    try:
        ttl = int((request.args.get("ttl") or "12").strip())
    except Exception:
        ttl = 12
    ttl = max(1, min(300, ttl))
    return jsonify(build_live_state_payload(selected_date, ttl=ttl))


@nba_bp.get("/api/live_player_boxscore")
def api_live_player_boxscore():
    selected_date = _selected_date()
    event_ids_raw = str(request.args.get("event_ids") or "").strip()
    if not event_ids_raw:
        return jsonify({"error": "missing event_ids"}), 400
    event_ids = [item.strip() for item in event_ids_raw.split(",") if item.strip()]
    if not event_ids:
        return jsonify({"error": "missing event_ids"}), 400
    try:
        ttl = int((request.args.get("ttl") or "20").strip())
    except Exception:
        ttl = 20
    ttl = max(1, min(300, ttl))
    return jsonify(build_live_player_boxscore_payload(selected_date, event_ids, ttl=ttl))

@nba_bp.get("/api/live_player_lens")
def api_live_player_lens():
    selected_date = _selected_date()
    event_ids_raw = str(request.args.get("event_ids") or "").strip()
    if not event_ids_raw:
        return jsonify({"ok": True, "ttl": 20, "date": selected_date or None, "games": [], "generated_at": date.today().isoformat() + "T00:00:00Z"})
    event_ids = [item.strip() for item in event_ids_raw.split(",") if item.strip()]
    if not event_ids:
        return jsonify({"error": "missing event_ids"}), 400
    try:
        ttl = int((request.args.get("ttl") or "20").strip())
    except Exception:
        ttl = 20
    ttl = max(1, min(300, ttl))
    return jsonify(build_live_player_lens_payload(selected_date, event_ids, ttl=ttl))

@nba_bp.get("/api/live_lines")
def api_live_lines():
    selected_date = _selected_date()
    event_ids_raw = str(request.args.get("event_ids") or "").strip()
    if not event_ids_raw:
        return jsonify({"error": "missing event_ids"}), 400
    event_ids = [item.strip() for item in event_ids_raw.split(",") if item.strip()]
    if not event_ids:
        return jsonify({"error": "missing event_ids"}), 400
    try:
        ttl = int((request.args.get("ttl") or "20").strip())
    except Exception:
        ttl = 20
    ttl = max(1, min(300, ttl))
    include_period_totals = str(request.args.get("include_period_totals") or "").strip().lower() in {"1", "true", "yes", "on"}
    return jsonify(build_live_lines_payload(selected_date, event_ids, ttl=ttl, include_period_totals=include_period_totals))

@nba_bp.get("/api/live_pbp_stats")
def api_live_pbp_stats():
    selected_date = _selected_date()
    event_ids_raw = str(request.args.get("event_ids") or "").strip()
    if not event_ids_raw:
        return jsonify({"error": "missing event_ids"}), 400
    event_ids = [item.strip() for item in event_ids_raw.split(",") if item.strip()]
    if not event_ids:
        return jsonify({"error": "missing event_ids"}), 400
    try:
        ttl = int((request.args.get("ttl") or "20").strip())
    except Exception:
        ttl = 20
    ttl = max(1, min(300, ttl))
    return jsonify(build_live_pbp_stats_payload(selected_date, event_ids, ttl=ttl))

@nba_bp.get("/api/live_lens_tuning")
def api_live_lens_tuning():
    try:
        ttl = int((request.args.get("ttl") or "300").strip())
    except Exception:
        ttl = 300
    ttl = max(1, min(3600, ttl))
    return jsonify(build_live_lens_tuning_payload(ttl=ttl))


@nba_bp.get("/picks")
def picks():
    selected_date = _selected_date()
    context = build_picks_page_context(selected_date)
    return render_template("nba/picks.html", show_app_header=False, **context)


@nba_bp.get("/api/picks")
def api_picks():
    selected_date = _selected_date()
    context = build_picks_page_context(selected_date)
    return jsonify(build_rank_api_payload(context))


def _props_response():
    selected_date = _selected_date()
    context = build_props_page_context(
        selected_date,
        filters={
            "market": request.args.get("market"),
            "team": request.args.get("team"),
            "player": request.args.get("player"),
            "sort": request.args.get("sort"),
        },
    )
    return context


@nba_bp.get("/props")
@nba_bp.get("/prop-ladders")
def props():
    context = _props_response()
    return render_template("nba/prop_ladders.html", show_app_header=False, **context)


@nba_bp.get("/api/props")
@nba_bp.get("/api/prop-ladders")
def api_props():
    context = _props_response()
    return jsonify(build_rank_api_payload(context))


