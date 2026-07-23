from __future__ import annotations

from collections import deque
from datetime import date
from datetime import timedelta
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for

from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.wnba.archive import build_archive_api_payload
from syndicate.features.wnba.archive import build_archive_page_context
from syndicate.features.wnba.cards import build_cards_page_context
from syndicate.features.wnba.cards import build_wnba_market_board
from syndicate.features.wnba.cards import build_source_cards_payload
from syndicate.features.wnba.cards import build_source_cards_sim_detail_payload
from syndicate.features.wnba.cards import _public_scoreboard_source_cards_payload
from syndicate.features.wnba.cards import build_live_lens_tuning_payload
from syndicate.features.wnba.cards import build_live_lines_payload
from syndicate.features.wnba.cards import build_live_pbp_stats_payload
from syndicate.features.wnba.cards import build_live_player_boxscore_payload
from syndicate.features.wnba.cards import build_live_player_lens_payload
from syndicate.features.wnba.cards import build_live_state_payload
from syndicate.features.wnba.game_detail import build_game_detail_page_context
from syndicate.features.wnba.live_game_accuracy import build_live_game_accuracy_payload
from syndicate.features.wnba.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload
from syndicate.features.wnba.live_lens import build_live_lens_api_payload
from syndicate.features.wnba.live_lens import build_live_lens_page_context
from syndicate.features.wnba.live_prop_accuracy import build_live_prop_accuracy_payload
from syndicate.features.wnba.live_prop_audit import build_live_prop_audit_payload
from syndicate.features.wnba.market_accuracy import build_market_accuracy_payload
from syndicate.features.wnba.picks import build_betting_card_page_context
from syndicate.features.wnba.picks import build_picks_page_context
from syndicate.features.wnba.props import build_props_page_context
from syndicate.features.wnba.source_proxy import source_web_text
from syndicate.features.wnba.source_proxy import build_source_base_styles
from syndicate.features.wnba.source_proxy import build_source_cards_script
from syndicate.features.wnba.source_proxy import build_source_cards_styles
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.wnba.sources import available_dates
from syndicate.features.wnba.sources import default_date
from syndicate.features.wnba.sources import default_date_for_season
from syndicate.features.shared.timezone import central_now
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.timezone import central_year


wnba_bp = Blueprint("syndicate_wnba", __name__, url_prefix="/wnba")


_WNBA_API_THROTTLE_LOCK = threading.Lock()
_WNBA_API_THROTTLE_STATE: dict[str, dict[str, object]] = {}
_WNBA_API_THROTTLE_WINDOW_SECONDS = 8.0
_WNBA_API_THROTTLE_MAX_REQUESTS = 1


_WNBA_OFFICIAL_LOGO_TEAM_IDS: dict[str, int] = {
    "ATL": 1611661330,
    "CHI": 1611661329,
    "CON": 1611661323,
    "DAL": 1611661321,
    "GSV": 1611661331,
    "IND": 1611661325,
    "LA": 1611661320,
    "LAS": 1611661320,
    "LVA": 1611661319,
    "MIN": 1611661324,
    "NYL": 1611661313,
    "PHX": 1611661317,
    "POR": 1611661327,
    "SEA": 1611661328,
    "TOR": 1611661332,
    "WSH": 1611661322,
}


def _selected_date() -> str:
    return (request.args.get("date") or default_date()).strip()


def _allow_stored_date_fallback() -> bool:
    return True


def _official_wnba_logo_team_id(team_ref: str) -> int | None:
    raw_ref = str(team_ref or "").strip().upper()
    if not raw_ref:
        return None
    if raw_ref.isdigit():
        return int(raw_ref)
    return _WNBA_OFFICIAL_LOGO_TEAM_IDS.get(raw_ref)


def _selected_season_date(season: int) -> str:
    requested = (request.args.get("date") or "").strip()
    if requested:
        return requested
    return default_date_for_season(season)


def _rank_payload(context: dict) -> dict:
    return build_rank_api_payload(context)


def _snapshot_unavailable_payload() -> dict:
    return {
        "ok": False,
        "error": "snapshot_unavailable",
        "cards": [],
    }


def _throttled_api_payload(selected_date: str, endpoint_name: str, retry_after_seconds: int = 8) -> dict[str, object]:
    return {
        "ok": False,
        "error": "throttled",
        "status": "throttled",
        "endpoint": endpoint_name,
        "date": selected_date,
        "requested_date": selected_date,
        "cards": [],
        "games": [],
        "retry_after_seconds": int(retry_after_seconds),
    }


def _throttle_request_key(endpoint_name: str, selected_date: str) -> str:
    query = request.query_string.decode("utf-8") if request.query_string else ""
    return f"{endpoint_name}:{selected_date}:{query}"


def _acquire_wnba_api_throttle(endpoint_name: str, selected_date: str) -> tuple[str | None, Response | None]:
    now = time.monotonic()
    throttle_key = _throttle_request_key(endpoint_name, selected_date)
    with _WNBA_API_THROTTLE_LOCK:
        state = _WNBA_API_THROTTLE_STATE.setdefault(
            throttle_key,
            {"recent": deque(), "in_flight": 0},
        )
        recent = state["recent"]
        if not isinstance(recent, deque):
            recent = deque()
            state["recent"] = recent
        while recent and now - float(recent[0]) > _WNBA_API_THROTTLE_WINDOW_SECONDS:
            recent.popleft()
        in_flight = int(state.get("in_flight") or 0)
        if in_flight > 0 or len(recent) >= _WNBA_API_THROTTLE_MAX_REQUESTS:
            response = jsonify(_throttled_api_payload(selected_date, endpoint_name))
            response.status_code = 429
            response.headers["Retry-After"] = "8"
            response.headers["Cache-Control"] = "no-store"
            return None, response
        recent.append(now)
        state["in_flight"] = in_flight + 1
    return throttle_key, None


def _release_wnba_api_throttle(throttle_key: str | None) -> None:
    if not throttle_key:
        return
    with _WNBA_API_THROTTLE_LOCK:
        state = _WNBA_API_THROTTLE_STATE.get(throttle_key)
        if not isinstance(state, dict):
            return
        in_flight = int(state.get("in_flight") or 0)
        if in_flight > 0:
            state["in_flight"] = in_flight - 1


def _query_string() -> str:
    return request.query_string.decode("utf-8") if request.query_string else ""


def _source_text_response(content: str | None, mimetype: str):
    if content is None:
        return Response("source asset unavailable", status=502, mimetype="text/plain")
    return Response(content, mimetype=mimetype)


def _source_betting_card_asset_version() -> str:
    contents = []
    for name in ("betting-card-v2.css", "betting-card-v2.js"):
        content = source_web_text(name)
        if content:
            contents.append(content)
    if not contents:
        return "missing"
    return str(abs(hash("".join(contents))))


def _cards_source_asset_version() -> str:
    static_root = Path(__file__).resolve().parents[1] / "static" / "wnba"
    paths = [
        Path(__file__).resolve().parents[1] / "static" / "shared" / "standalone_shell.css",
        static_root / "styles.css",
        static_root / "cards-parity.css",
        static_root / "cards-parity.js",
    ]
    mtimes: list[int] = []
    for path in paths:
        try:
            mtimes.append(int(path.stat().st_mtime_ns))
        except OSError:
            continue
    if mtimes:
        return str(max(mtimes))
    return "missing"


def _live_lens_template_context(selected_date: str) -> dict[str, object]:
    season = date.fromisoformat(selected_date).year if len(selected_date) == 10 else central_year()
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/wnba/api/live-player-props-audit",
        "api_label": "/api/live-player-props-audit",
        "back_href": f"/wnba/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": f"/wnba/market-accuracy?date={selected_date}",
        "self_href": f"/wnba/live-player-props-audit?date={selected_date}",
        "accuracy_href": f"/wnba/live-player-props-lens-accuracy?date={selected_date}",
    }


def _live_lens_accuracy_template_context(selected_date: str) -> dict[str, object]:
    season = date.fromisoformat(selected_date).year if len(selected_date) == 10 else central_year()
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/wnba/api/live-player-props-lens-accuracy",
        "api_label": "/api/live-player-props-lens-accuracy",
        "back_href": f"/wnba/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": f"/wnba/market-accuracy?date={selected_date}",
        "daily_accuracy_href": f"/wnba/live-lens-accuracy?date={selected_date}",
        "game_accuracy_href": f"/wnba/live-game-lens-accuracy?date={selected_date}",
        "audit_href": f"/wnba/live-player-props-audit?date={selected_date}",
        "self_href": f"/wnba/live-player-props-lens-accuracy?date={selected_date}",
    }


def _live_game_accuracy_template_context(selected_date: str) -> dict[str, object]:
    season = date.fromisoformat(selected_date).year if len(selected_date) == 10 else central_year()
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/wnba/api/live-game-lens-accuracy",
        "api_label": "/api/live-game-lens-accuracy",
        "back_href": f"/wnba/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": f"/wnba/market-accuracy?date={selected_date}",
        "daily_accuracy_href": f"/wnba/live-lens-accuracy?date={selected_date}",
        "props_accuracy_href": f"/wnba/live-player-props-lens-accuracy?date={selected_date}",
        "self_href": f"/wnba/live-game-lens-accuracy?date={selected_date}",
    }


def _live_lens_daily_accuracy_template_context(selected_date: str) -> dict[str, object]:
    season = date.fromisoformat(selected_date).year if len(selected_date) == 10 else central_year()
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/wnba/api/live-lens-accuracy",
        "api_label": "/api/live-lens-accuracy",
        "back_href": f"/wnba/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": f"/wnba/market-accuracy?date={selected_date}",
        "game_accuracy_href": f"/wnba/live-game-lens-accuracy?date={selected_date}",
        "props_accuracy_href": f"/wnba/live-player-props-lens-accuracy?date={selected_date}",
        "self_href": f"/wnba/live-lens-accuracy?date={selected_date}",
    }


def _market_accuracy_template_context(selected_date: str) -> dict[str, object]:
    season = date.fromisoformat(selected_date).year if len(selected_date) == 10 else central_year()
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/wnba/api/market-accuracy",
        "api_label": "/api/market-accuracy",
        "back_href": f"/wnba/cards?date={selected_date}",
        "back_label": "Cards",
        "daily_accuracy_href": f"/wnba/live-lens-accuracy?date={selected_date}",
        "game_accuracy_href": f"/wnba/live-game-lens-accuracy?date={selected_date}",
        "props_accuracy_href": f"/wnba/live-player-props-lens-accuracy?date={selected_date}",
        "self_href": f"/wnba/market-accuracy?date={selected_date}",
    }


@wnba_bp.get("/hub")
def hub():
    dates = available_dates()
    latest_date = dates[-1] if dates else default_date()
    today_date = central_today_iso()
    recent_slates = list(reversed(dates[-12:]))
    if not dates:
        availability_note = "No stored WNBA slates are available yet, so the game, props, and live-lens lanes remain empty."
    elif latest_date == today_date:
        availability_note = f"Latest stored slate is {latest_date}; open that date to populate the WNBA game, props, and live-lens lanes."
    else:
        availability_note = f"Latest stored slate is {latest_date}; WNBA game, props, and live-lens lanes are date-specific and stay archive-first until a fresh slate is processed."
    return render_template(
        "wnba/hub.html",
        latest_date=latest_date,
        today_date=today_date,
        recent_slates=recent_slates,
        availability_note=availability_note,
        summary_stats=[
            {"label": "Stored slates", "value": str(len(dates))},
            {"label": "Latest", "value": latest_date},
            {"label": "Launch date", "value": today_date},
        ],
    )


@wnba_bp.get("")
def root_cards():
    return cards()


@wnba_bp.get("/cards")
def cards():
    selected_date = _selected_date()
    client = (request.args.get("client") or "").strip().lower()
    if client == "board":
        context = build_cards_page_context(
            selected_date,
            allow_stored_date_fallback=_allow_stored_date_fallback(),
        )
        return render_template("shared/game_cards_board.html", **context)
    return render_template(
        "wnba/cards_source.html",
        date=selected_date,
        asset_version=_cards_source_asset_version(),
        cards_payload_path="/wnba/api/source/cards",
    )


@wnba_bp.get("/market-board")
def market_board():
    # Layer 1 (see ~/.claude/plans/expressive-wiggling-engelbart.md, Phase
    # 3b): every quoted moneyline/spread/total/prop line per game, not just
    # the ones the recommendation engine chose to surface.
    selected_date = _selected_date()
    board = build_wnba_market_board(selected_date)
    parsed_date = date.fromisoformat(selected_date)
    return render_template(
        "shared/basketball_market_board.html",
        sport_label="WNBA",
        selected_date=selected_date,
        board=board,
        prev_date=(parsed_date - timedelta(days=1)).isoformat(),
        next_date=(parsed_date + timedelta(days=1)).isoformat(),
        cards_href=f"/wnba/cards?date={selected_date}",
        show_home_link=False,
    )


@wnba_bp.get("/api/market-board")
def api_market_board():
    selected_date = _selected_date()
    return jsonify(build_wnba_market_board(selected_date))


def _live_lens_cards_shell_context(selected_date: str) -> dict[str, object]:
    return {
        "date": selected_date,
        "asset_version": _cards_source_asset_version(),
        "page_title": "WNBA Live Lens",
        "page_heading": "WNBA Live Lens",
        "cards_base_path": "/wnba/live-lens",
        "cards_payload_path": "/wnba/api/live-lens",
        "embed_mode": str(request.args.get("embed") or "").strip().lower(),
    }


@wnba_bp.get("/cards/source")
def cards_source_alias():
    params = request.args.to_dict(flat=True)
    params["client"] = "source"
    return redirect(url_for("syndicate_wnba.cards", **params), code=302)


@wnba_bp.get("/cards/board")
def cards_board_alias():
    params = request.args.to_dict(flat=True)
    params["client"] = "board"
    return redirect(url_for("syndicate_wnba.cards", **params), code=302)


@wnba_bp.get("/cards-parity.js")
def cards_parity_script():
    return _source_text_response(build_source_cards_script(), "application/javascript")


@wnba_bp.get("/cards-parity.css")
def cards_parity_styles():
    return _source_text_response(build_source_cards_styles(), "text/css")


@wnba_bp.get("/styles.css")
def styles_css():
    return _source_text_response(build_source_base_styles(), "text/css")


@wnba_bp.get("/web/assets/logos-wnba/<team_code>.svg")
def team_logo_badge(team_code: str):
    code = "".join(ch for ch in str(team_code or "").upper() if ch.isalnum())[:6] or "WNBA"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="14" fill="#10243d" />'
        f'<text x="32" y="37" text-anchor="middle" font-family="Georgia, Times New Roman, serif" font-size="22" font-weight="700" fill="#f5efe2">{code}</text>'
        "</svg>"
    )
    return Response(svg, mimetype="image/svg+xml")


@wnba_bp.get("/api/source/team-logo/<team_id>")
def api_source_team_logo(team_id: str):
    official_team_id = _official_wnba_logo_team_id(team_id)
    if official_team_id is None:
        return team_logo_badge(team_id)
    request_obj = Request(
        f"https://cdn.wnba.com/logos/wnba/{official_team_id}/primary/L/logo.svg",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/svg+xml,image/*;q=0.8,*/*;q=0.5",
        },
    )
    try:
        with urlopen(request_obj, timeout=10) as response:
            data = response.read()
    except (HTTPError, URLError, OSError, ValueError):
        return team_logo_badge(team_id)
    if not data:
        return team_logo_badge(team_id)
    output = Response(data, mimetype="image/svg+xml")
    output.headers["Cache-Control"] = "public, max-age=86400"
    return output


@wnba_bp.get("/api/source/cards")
def api_source_cards():
    selected_date = _selected_date()
    try:
        payload = build_source_cards_payload(selected_date, allow_stored_date_fallback=True)
        if isinstance(payload, dict) and payload.get("games"):
            return jsonify(payload)
        if selected_date == central_today_iso():
            public_payload = _public_scoreboard_source_cards_payload(selected_date)
            if isinstance(public_payload, dict) and public_payload.get("games"):
                return jsonify(public_payload)
        return jsonify(payload)
    except Exception:
        return jsonify(_snapshot_unavailable_payload())


@wnba_bp.get("/api/source/cards/sim-detail")
def api_source_cards_sim_detail():
    away_tri = str(request.args.get("away") or "").strip().upper()
    home_tri = str(request.args.get("home") or "").strip().upper()
    if not away_tri or not home_tri:
        return jsonify({"error": "missing home/away"}), 400
    selected_date = _selected_date()
    return jsonify(build_source_cards_sim_detail_payload(selected_date, away_tri, home_tri))


@wnba_bp.get("/game/<game_pk>")
def game_detail(game_pk: str):
    selected_date = _selected_date()
    context = build_game_detail_page_context(selected_date, game_pk)
    return render_template("shared/game_cards_board.html", **context)


@wnba_bp.get("/api/game/<game_pk>")
def api_game_detail(game_pk: str):
    selected_date = _selected_date()
    context = build_game_detail_page_context(selected_date, game_pk)
    return jsonify(build_game_board_api_payload(context))


@wnba_bp.get("/api/cards")
def api_cards():
    selected_date = _selected_date()
    try:
        context = build_cards_page_context(selected_date, allow_stored_date_fallback=_allow_stored_date_fallback())
        return jsonify(build_game_board_api_payload(context))
    except Exception as error:
        print("WNBA SNAPSHOT ERROR:", error)
        return jsonify(_snapshot_unavailable_payload())


@wnba_bp.get("/picks")
def picks():
    selected_date = _selected_date()
    context = build_picks_page_context(selected_date)
    return render_template("wnba/picks.html", show_app_header=False, **context)


@wnba_bp.get("/api/picks")
def api_picks():
    selected_date = _selected_date()
    context = build_picks_page_context(selected_date)
    return jsonify(_rank_payload(context))


@wnba_bp.get("/props")
def props():
    selected_date = _selected_date()
    context = build_props_page_context(selected_date)
    return render_template("wnba/prop_ladders.html", **context)


@wnba_bp.get("/api/props")
def api_props():
    selected_date = _selected_date()
    context = build_props_page_context(selected_date)
    return jsonify(_rank_payload(context))


@wnba_bp.get("/live-lens")
def live_lens():
    selected_date = _selected_date()
    return render_template("wnba/cards_source.html", **_live_lens_cards_shell_context(selected_date))


@wnba_bp.get("/live-player-props-audit")
def live_player_props_audit():
    selected_date = _selected_date()
    return render_template("wnba/live_prop_audit.html", **_live_lens_template_context(selected_date))


@wnba_bp.get("/live-player-props-lens-accuracy")
def live_player_props_lens_accuracy():
    selected_date = _selected_date()
    return render_template("wnba/live_prop_accuracy.html", **_live_lens_accuracy_template_context(selected_date))


@wnba_bp.get("/live-game-lens-accuracy")
def live_game_lens_accuracy():
    selected_date = _selected_date()
    return render_template("wnba/live_game_accuracy.html", **_live_game_accuracy_template_context(selected_date))


@wnba_bp.get("/live-lens-accuracy")
def live_lens_accuracy():
    selected_date = _selected_date()
    return render_template("wnba/live_lens_daily_accuracy.html", **_live_lens_daily_accuracy_template_context(selected_date))


@wnba_bp.get("/market-accuracy")
def market_accuracy():
    selected_date = _selected_date()
    return render_template("wnba/market_accuracy.html", **_market_accuracy_template_context(selected_date))


@wnba_bp.get("/api/live-lens")
def api_live_lens():
    selected_date = _selected_date()
    throttle_key, throttle_response = _acquire_wnba_api_throttle("api_live_lens", selected_date)
    if throttle_response is not None:
        return throttle_response
    try:
        return jsonify(build_live_lens_api_payload(selected_date))
    except Exception as error:
        print("WNBA SNAPSHOT ERROR:", error)
        return jsonify(_snapshot_unavailable_payload())
    finally:
        _release_wnba_api_throttle(throttle_key)


@wnba_bp.get("/api/live-player-props-audit")
@wnba_bp.get("/api/live_player_props_projection_audit")
def api_live_player_props_audit():
    selected_date = _selected_date()
    throttle_key, throttle_response = _acquire_wnba_api_throttle("api_live_player_props_audit", selected_date)
    if throttle_response is not None:
        return throttle_response
    try:
        payload = build_live_prop_audit_payload(_query_string())
    finally:
        _release_wnba_api_throttle(throttle_key)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live player props audit"}), 502
    return jsonify(payload)


@wnba_bp.get("/api/live-player-props-lens-accuracy")
@wnba_bp.get("/api/live_player_props_lens_analytics")
def api_live_player_props_lens_accuracy():
    selected_date = _selected_date()
    throttle_key, throttle_response = _acquire_wnba_api_throttle("api_live_player_props_lens_accuracy", selected_date)
    if throttle_response is not None:
        return throttle_response
    try:
        payload = build_live_prop_accuracy_payload(_query_string())
    finally:
        _release_wnba_api_throttle(throttle_key)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live player props lens accuracy"}), 502
    return jsonify(payload)


@wnba_bp.get("/api/live-game-lens-accuracy")
@wnba_bp.get("/api/live_game_lens_analytics")
@wnba_bp.get("/api/live_lens_analytics")
def api_live_game_lens_accuracy():
    payload = build_live_game_accuracy_payload(_query_string())
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live game lens accuracy"}), 502
    return jsonify(payload)


@wnba_bp.get("/api/live-lens-accuracy")
@wnba_bp.get("/api/live_lens_accuracy")
def api_live_lens_accuracy():
    payload = build_live_lens_daily_accuracy_payload(_query_string())
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live lens daily accuracy"}), 502
    return jsonify(payload)


@wnba_bp.get("/api/market-accuracy")
@wnba_bp.get("/api/accuracy-market")
def api_market_accuracy():
    payload = build_market_accuracy_payload(_query_string())
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load market accuracy"}), 502
    return jsonify(payload)


@wnba_bp.get("/api/live_state")
def api_live_state():
    selected_date = _selected_date()
    try:
        ttl = int((request.args.get("ttl") or "12").strip())
    except Exception:
        ttl = 12
    ttl = max(1, min(300, ttl))
    try:
        return jsonify(build_live_state_payload(selected_date, ttl=ttl, allow_stored_date_fallback=True))
    except Exception:
        return jsonify({"ok": True, "ttl": int(ttl), "date": selected_date or None, "games": [], "generated_at": central_now().isoformat(timespec="seconds")})


@wnba_bp.get("/api/live_player_boxscore")
def api_live_player_boxscore():
    selected_date = _selected_date()
    event_ids_raw = str(request.args.get("event_ids") or "").strip()
    event_ids = [item.strip() for item in event_ids_raw.split(",") if item.strip()] if event_ids_raw else []
    try:
        ttl = int((request.args.get("ttl") or "20").strip())
    except Exception:
        ttl = 20
    ttl = max(1, min(300, ttl))
    try:
        return jsonify(
            build_live_player_boxscore_payload(
                selected_date,
                event_ids,
                ttl=ttl,
                allow_stored_date_fallback=True,
            )
        )
    except Exception:
        return jsonify({"ok": True, "ttl": int(ttl), "date": selected_date or None, "games": [], "generated_at": central_now().isoformat(timespec="seconds")})


@wnba_bp.get("/api/live_player_lens")
def api_live_player_lens():
    selected_date = _selected_date()
    event_ids_raw = str(request.args.get("event_ids") or "").strip()
    event_ids = [item.strip() for item in event_ids_raw.split(",") if item.strip()] if event_ids_raw else []
    try:
        ttl = int((request.args.get("ttl") or "20").strip())
    except Exception:
        ttl = 20
    ttl = max(1, min(300, ttl))
    try:
        return jsonify(
            build_live_player_lens_payload(
                selected_date,
                event_ids,
                ttl=ttl,
                allow_stored_date_fallback=True,
            )
        )
    except Exception:
        return jsonify({"ok": True, "ttl": int(ttl), "date": selected_date or None, "games": [], "generated_at": central_now().isoformat(timespec="seconds")})


@wnba_bp.get("/api/live_lines")
def api_live_lines():
    selected_date = _selected_date()
    event_ids_raw = str(request.args.get("event_ids") or "").strip()
    event_ids = [item.strip() for item in event_ids_raw.split(",") if item.strip()] if event_ids_raw else []
    try:
        ttl = int((request.args.get("ttl") or "20").strip())
    except Exception:
        ttl = 20
    ttl = max(1, min(300, ttl))
    include_period_totals = str(request.args.get("include_period_totals") or "1").strip().lower() in {"1", "true", "yes", "on"}
    try:
        return jsonify(
            build_live_lines_payload(
                selected_date,
                event_ids,
                ttl=ttl,
                include_period_totals=include_period_totals,
                allow_stored_date_fallback=True,
            )
        )
    except Exception:
        return jsonify({"ok": True, "ttl": int(ttl), "date": selected_date or None, "include_period_totals": bool(include_period_totals), "games": [], "generated_at": central_now().isoformat(timespec="seconds")})


@wnba_bp.get("/api/live_pbp_stats")
def api_live_pbp_stats():
    selected_date = _selected_date()
    event_ids_raw = str(request.args.get("event_ids") or "").strip()
    event_ids = [item.strip() for item in event_ids_raw.split(",") if item.strip()] if event_ids_raw else []
    try:
        ttl = int((request.args.get("ttl") or "20").strip())
    except Exception:
        ttl = 20
    ttl = max(1, min(300, ttl))
    try:
        return jsonify(
            build_live_pbp_stats_payload(
                selected_date,
                event_ids,
                ttl=ttl,
                allow_stored_date_fallback=True,
            )
        )
    except Exception:
        return jsonify({"ok": True, "ttl": int(ttl), "date": selected_date or None, "games": [], "generated_at": central_now().isoformat(timespec="seconds")})


@wnba_bp.get("/api/live_lens_tuning")
def api_live_lens_tuning():
    try:
        ttl = int((request.args.get("ttl") or "300").strip())
    except Exception:
        ttl = 300
    ttl = max(1, min(300, ttl))
    return jsonify(build_live_lens_tuning_payload(ttl=ttl))


@wnba_bp.get("/archive")
def archive():
    selected_date = _selected_date()
    context = build_archive_page_context(selected_date)
    return render_template("wnba/archive.html", show_app_header=False, **context)


@wnba_bp.get("/api/archive")
def api_archive():
    selected_date = _selected_date()
    return jsonify(build_archive_api_payload(selected_date))


@wnba_bp.get("/season/<int:season>/betting-card")
def season_betting_card(season: int):
    selected_date = _selected_season_date(season)
    context = build_betting_card_page_context(season, selected_date)
    return render_template("wnba/betting_card.html", asset_version=_source_betting_card_asset_version(), **context)


@wnba_bp.get("/api/season/<int:season>/betting-card")
def api_season_betting_card(season: int):
    context = build_betting_card_page_context(season, _selected_season_date(season))
    return jsonify(_rank_payload(context))


@wnba_bp.get("/assets/betting-card-v2.css")
def betting_card_styles():
    return _source_text_response(source_web_text("betting-card-v2.css"), "text/css")


@wnba_bp.get("/assets/betting-card-v2.js")
def betting_card_script():
    return _source_text_response(source_web_text("betting-card-v2.js"), "application/javascript")