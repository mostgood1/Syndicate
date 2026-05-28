from __future__ import annotations

import csv
from datetime import date
from datetime import timedelta
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request

from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.nhl.archive import build_archive_api_payload
from syndicate.features.nhl.archive import build_archive_page_context
from syndicate.features.nhl.betting_recap import build_betting_recap_payload
from syndicate.features.nhl.cards import build_source_bundle_payload
from syndicate.features.nhl.cards import build_cards_page_context
from syndicate.features.nhl.cards import build_props_cards_payload
from syndicate.features.nhl.cards import build_sim_boxscores_payload
from syndicate.features.nhl.cards import build_sim_summary_payload
from syndicate.features.nhl.live_game_accuracy import build_live_game_accuracy_payload
from syndicate.features.nhl.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload
from syndicate.features.nhl.live_lens import build_live_lens_api_payload
from syndicate.features.nhl.live_lens import build_live_lens_page_context
from syndicate.features.nhl.market_accuracy import build_market_accuracy_payload
from syndicate.features.nhl.picks import build_betting_card_page_context
from syndicate.features.nhl.picks import build_picks_page_context
from syndicate.features.nhl.player_props_reconciliation import build_player_props_reconciliation_payload
from syndicate.features.nhl.props_lines import build_props_lines_payload
from syndicate.features.nhl.sources import default_date
from syndicate.features.nhl.sources import parse_iso_date
from syndicate.features.nhl.sources import scoreboard_snapshot_path
from syndicate.features.nhl.sources import slate_summaries
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.timezone import central_today
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.timezone import central_year


nhl_bp = Blueprint("syndicate_nhl", __name__, url_prefix="/nhl")


def _cards_source_asset_version() -> str:
    static_root = Path(__file__).resolve().parents[1] / "static"
    paths = [
        static_root / "shared" / "standalone_shell.css",
        static_root / "shared" / "polling.js",
        static_root / "nhl" / "cards_source_base.css",
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


def _selected_date() -> str:
    return (request.args.get("date") or "").strip() or default_date()


def _query_string() -> str:
    return request.query_string.decode("utf-8") if request.query_string else ""


def _load_scoreboard_rows(selected_date: str) -> list[dict[str, object]]:
    path = scoreboard_snapshot_path(selected_date)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []

    out: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "gamePk": row.get("gamePk") or row.get("game_id"),
                "away": row.get("away") or row.get("away_team"),
                "home": row.get("home") or row.get("home_team"),
                "away_abbr": row.get("away_abbr") or row.get("away_tri"),
                "home_abbr": row.get("home_abbr") or row.get("home_tri"),
                "away_goals": row.get("away_goals") or row.get("awayScore") or row.get("away_score"),
                "home_goals": row.get("home_goals") or row.get("homeScore") or row.get("home_score"),
                "gameState": row.get("gameState") or row.get("game_state") or row.get("state"),
                "period": row.get("period") or row.get("web_period"),
                "clock": row.get("clock") or row.get("web_clock"),
                "period_disp": row.get("period_disp") or row.get("periodDisp"),
                "intermission": row.get("intermission") or row.get("inIntermission"),
            }
        )
    return out


def _selected_season_date(season: int) -> str:
    requested = (request.args.get("date") or "").strip()
    if requested:
        return requested
    season_dates = [date_str for date_str in [item["date"] for item in slate_summaries()] if date_str.startswith(f"{int(season)}-")]
    return season_dates[-1] if season_dates else _selected_date()


def _live_lens_daily_accuracy_template_context(selected_date: str) -> dict[str, object]:
    season = parse_iso_date(selected_date).year if len(selected_date) == 10 else central_today().year
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/nhl/api/live-lens-accuracy",
        "api_label": "/api/live-lens-accuracy",
        "back_href": f"/nhl/cards?date={selected_date}",
        "back_label": "Cards",
        "self_href": f"/nhl/live-lens-accuracy?date={selected_date}",
        "live_lens_href": f"/nhl/live-lens?date={selected_date}",
        "game_accuracy_href": f"/nhl/live-game-lens-accuracy?date={selected_date}",
        "market_accuracy_href": f"/nhl/market-accuracy?date={selected_date}",
        "reconciliation_href": f"/nhl/reconciliation?date={selected_date}",
    }


def _live_game_accuracy_template_context(selected_date: str) -> dict[str, object]:
    season = parse_iso_date(selected_date).year if len(selected_date) == 10 else central_year()
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/nhl/api/live-game-lens-accuracy",
        "api_label": "/api/live-game-lens-accuracy",
        "back_href": f"/nhl/cards?date={selected_date}",
        "back_label": "Cards",
        "daily_accuracy_href": f"/nhl/live-lens-accuracy?date={selected_date}",
        "self_href": f"/nhl/live-game-lens-accuracy?date={selected_date}",
        "live_lens_href": f"/nhl/live-lens?date={selected_date}",
        "market_accuracy_href": f"/nhl/market-accuracy?date={selected_date}",
        "reconciliation_href": f"/nhl/reconciliation?date={selected_date}",
    }


def _market_accuracy_template_context(selected_date: str) -> dict[str, object]:
    season = parse_iso_date(selected_date).year if len(selected_date) == 10 else central_year()
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/nhl/api/market-accuracy",
        "api_label": "/api/market-accuracy",
        "back_href": f"/nhl/cards?date={selected_date}",
        "back_label": "Cards",
        "self_href": f"/nhl/market-accuracy?date={selected_date}",
        "daily_accuracy_href": f"/nhl/live-lens-accuracy?date={selected_date}",
        "game_accuracy_href": f"/nhl/live-game-lens-accuracy?date={selected_date}",
        "reconciliation_href": f"/nhl/reconciliation?date={selected_date}",
    }


def _betting_recap_template_context(selected_date: str) -> dict[str, object]:
    season = parse_iso_date(selected_date).year if len(selected_date) == 10 else central_year()
    try:
        until_date = parse_iso_date(selected_date)
    except ValueError:
        until_date = central_today()
    since_date = (until_date - timedelta(days=13)).isoformat()
    until_value = until_date.isoformat()
    return {
        "date": selected_date,
        "season": season,
        "default_since": since_date,
        "default_until": until_value,
        "default_days": 14,
        "api_path": "/nhl/api/betting-recap",
        "api_label": "/api/betting-recap",
        "back_href": f"/nhl/cards?date={selected_date}",
        "back_label": "Cards",
        "market_accuracy_href": f"/nhl/market-accuracy?date={selected_date}",
        "live_lens_href": f"/nhl/live-lens?date={selected_date}",
        "props_reconciliation_href": f"/nhl/props/reconciliation?date={selected_date}",
        "self_href": f"/nhl/reconciliation?date={selected_date}",
    }


def _player_props_reconciliation_template_context(selected_date: str) -> dict[str, object]:
    return {
        "date": selected_date,
        "api_path": "/nhl/api/player-props-reconciliation",
        "back_href": f"/nhl/cards?date={selected_date}",
        "back_label": "Cards",
        "props_lines_href": f"/nhl/props/lines?date={selected_date}",
        "reconciliation_href": f"/nhl/reconciliation?date={selected_date}",
        "market_accuracy_href": f"/nhl/market-accuracy?date={selected_date}",
        "self_href": f"/nhl/props/reconciliation?date={selected_date}",
    }


def _props_lines_template_context(selected_date: str) -> dict[str, object]:
    return {
        "date": selected_date,
        "api_path": "/nhl/api/props/lines.json",
        "back_href": f"/nhl/cards?date={selected_date}",
        "back_label": "Cards",
        "props_reconciliation_href": f"/nhl/props/reconciliation?date={selected_date}",
        "reconciliation_href": f"/nhl/reconciliation?date={selected_date}",
        "self_href": f"/nhl/props/lines?date={selected_date}",
    }


@nhl_bp.get("/hub")
def hub():
    slates = slate_summaries()
    latest_date = slates[-1]["date"] if slates else default_date()
    recent_slates = list(reversed(slates[-12:]))
    return render_template(
        "nhl/hub.html",
        latest_date=latest_date,
        today_date=central_today_iso(),
        recent_slates=recent_slates,
        summary_stats=[
            {"label": "Stored slates", "value": str(len(slates))},
            {"label": "Latest", "value": latest_date},
            {"label": "Launch date", "value": central_today_iso()},
        ],
    )


@nhl_bp.get("")
def root_cards():
    return cards()


@nhl_bp.get("/cards")
def cards():
    context = build_cards_page_context(_selected_date())
    client = (request.args.get("client") or "").strip().lower()
    if client == "board":
        return render_template("shared/game_cards_board.html", **context)
    return render_template("nhl/cards_source.html", initial_date=context["date"], asset_version=_cards_source_asset_version())


@nhl_bp.get("/api/cards")
def api_cards():
    context = build_cards_page_context(_selected_date())
    return jsonify(build_game_board_api_payload(context))


@nhl_bp.get("/api/dates")
def api_dates():
    slates = slate_summaries()
    return jsonify(
        {
            "dates": [item["date"] for item in slates],
            "slates": slates,
        }
    )


@nhl_bp.get("/api/cards/dates")
def api_cards_dates():
    dates = [item["date"] for item in slate_summaries()]
    latest = dates[-1] if dates else None
    today = parse_iso_date(_selected_date())
    trio = [
        (today - timedelta(days=1)).isoformat(),
        today.isoformat(),
        (today + timedelta(days=1)).isoformat(),
    ]
    return jsonify({"ok": True, "dates": dates, "latest": latest, "trio": trio})


@nhl_bp.get("/api/cards/bundle")
def api_cards_bundle():
    return jsonify(build_source_bundle_payload(request.args.get("date")))


@nhl_bp.get("/api/cards/sim-boxscores")
def api_cards_sim_boxscores():
    return jsonify(build_sim_boxscores_payload(request.args.get("date")))


@nhl_bp.get("/api/cards/sim-summary")
def api_cards_sim_summary():
    return jsonify(build_sim_summary_payload(request.args.get("date")))


@nhl_bp.get("/api/scoreboard")
def api_scoreboard():
    return jsonify(_load_scoreboard_rows(_selected_date()))


@nhl_bp.get("/api/cards/odds-movement")
def api_cards_odds_movement():
    return jsonify({"ok": True, "date": str(request.args.get("date") or _selected_date()), "games": []})


@nhl_bp.get("/live-lens")
def live_lens():
    selected_date = _selected_date()
    context = build_live_lens_page_context(selected_date)
    return render_template("shared/rank_board.html", **context)


@nhl_bp.get("/live-lens-accuracy")
def live_lens_accuracy():
    selected_date = _selected_date()
    return render_template("nhl/live_lens_daily_accuracy.html", **_live_lens_daily_accuracy_template_context(selected_date))


@nhl_bp.get("/live-game-lens-accuracy")
def live_game_lens_accuracy():
    selected_date = _selected_date()
    return render_template("nhl/live_game_accuracy.html", **_live_game_accuracy_template_context(selected_date))


@nhl_bp.get("/market-accuracy")
def market_accuracy():
    selected_date = _selected_date()
    return render_template("nhl/market_accuracy.html", **_market_accuracy_template_context(selected_date))


@nhl_bp.get("/betting-recap")
@nhl_bp.get("/reconciliation")
def reconciliation_alias():
    selected_date = _selected_date()
    return render_template("nhl/reconciliation.html", **_betting_recap_template_context(selected_date))


@nhl_bp.get("/player-props-reconciliation")
@nhl_bp.get("/props/reconciliation")
def player_props_reconciliation():
    selected_date = _selected_date()
    return render_template("nhl/player_props_reconciliation.html", **_player_props_reconciliation_template_context(selected_date))


@nhl_bp.get("/props/lines")
def props_lines():
    selected_date = _selected_date()
    return render_template("nhl/props_lines.html", **_props_lines_template_context(selected_date))


@nhl_bp.get("/archive")
def archive():
    context = build_archive_page_context(_selected_date())
    return render_template("nhl/archive.html", show_app_header=False, **context)


@nhl_bp.get("/api/live-lens")
def api_live_lens():
    selected_date = _selected_date()
    return jsonify(build_live_lens_api_payload(selected_date))


@nhl_bp.get("/api/live-lens-accuracy")
def api_live_lens_accuracy():
    payload = build_live_lens_daily_accuracy_payload(_query_string())
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live lens daily accuracy"}), 502
    return jsonify(payload)


@nhl_bp.get("/api/live-game-lens-accuracy")
@nhl_bp.get("/api/live_game_lens_analytics")
@nhl_bp.get("/api/live_lens_analytics")
def api_live_game_lens_accuracy():
    payload = build_live_game_accuracy_payload(_query_string())
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live game lens accuracy"}), 502
    return jsonify(payload)


@nhl_bp.get("/api/market-accuracy")
@nhl_bp.get("/api/accuracy-market")
def api_market_accuracy():
    payload = build_market_accuracy_payload(_query_string())
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load market accuracy"}), 502
    return jsonify(payload)


@nhl_bp.get("/api/betting-recap")
@nhl_bp.get("/api/reconciliation")
def api_betting_recap():
    payload = build_betting_recap_payload(_query_string())
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load betting recap"}), 502
    return jsonify(payload)


@nhl_bp.get("/api/player-props-reconciliation")
def api_player_props_reconciliation():
    payload = build_player_props_reconciliation_payload(_query_string())
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load player props reconciliation"}), 502
    return jsonify(payload)


@nhl_bp.get("/api/props/lines")
@nhl_bp.get("/api/props/lines.json")
def api_props_lines():
    payload = build_props_lines_payload(_query_string())
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load props lines"}), 502
    return jsonify(payload)


@nhl_bp.get("/api/archive")
def api_archive():
    return jsonify(build_archive_api_payload(_selected_date()))


@nhl_bp.get("/season/<int:season>/betting-card")
def season_betting_card(season: int):
    context = build_betting_card_page_context(season, _selected_season_date(season))
    return render_template("nhl/betting_card.html", show_app_header=False, **context)


@nhl_bp.get("/api/season/<int:season>/betting-card")
def api_season_betting_card(season: int):
    context = build_betting_card_page_context(season, _selected_season_date(season))
    payload = build_rank_api_payload(context)
    payload["available_dates"] = context.get("available_dates")
    return jsonify(payload)


@nhl_bp.get("/api/cards/props")
def api_cards_props():
    return jsonify(build_props_cards_payload(request.args.get("date"), top=request.args.get("top", 12)))


@nhl_bp.get("/game/<game_pk>")
def game_redirect(game_pk: str):
    date = (request.args.get("date") or "").strip() or _selected_date()
    return redirect(f"/nhl/cards?date={date}&gamePk={game_pk}")


@nhl_bp.get("/picks")
def picks():
    context = build_picks_page_context(_selected_date())
    return render_template("nhl/picks.html", show_app_header=False, **context)


@nhl_bp.get("/api/picks")
def api_picks():
    context = build_picks_page_context(_selected_date())
    payload = build_rank_api_payload(context)
    payload["available_dates"] = context["available_dates"]
    return jsonify(payload)