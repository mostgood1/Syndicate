from __future__ import annotations

from typing import Any

from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.mlb.cards import _betting_payload_by_game
from syndicate.features.mlb.cards import _daily_actual_by_game
from syndicate.features.mlb.cards import _daily_sim_by_game
from syndicate.features.mlb.cards import _games_from_daily_summary
from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.ladders_common import format_num
from syndicate.features.mlb.ladders_common import format_pct
from syndicate.features.mlb.ladders_common import parse_iso_date
from syndicate.features.mlb.sources import daily_artifact_path
from syndicate.features.mlb.sources import load_json_file
from syndicate.features.mlb.sources import season_eval_manifest_path
from syndicate.features.mlb.sources import season_frontend_day_path


def _market_counts(betting: dict[str, Any]) -> tuple[int, int, int]:
    markets = betting.get("markets") if isinstance(betting.get("markets"), dict) else {}
    official = int(isinstance(markets.get("ml"), dict)) + int(isinstance(markets.get("totals"), dict))
    official += len(markets.get("pitcherProps") or []) + len(markets.get("hitterProps") or [])
    extra = len(markets.get("extraPitcherProps") or []) + len(markets.get("extraHitterProps") or [])
    shadow = len(markets.get("shadowPitcherProps") or []) + len(markets.get("shadowHitterProps") or [])
    return official, extra, shadow


def _top_pick_items(betting: dict[str, Any], *, limit: int = 3) -> list[str]:
    markets = betting.get("markets") if isinstance(betting.get("markets"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("ml", "totals"):
        row = markets.get(key)
        if isinstance(row, dict):
            rows.append(row)
    for key in ("pitcherProps", "hitterProps"):
        values = markets.get(key) if isinstance(markets.get(key), list) else []
        rows.extend([row for row in values if isinstance(row, dict)])
    items: list[str] = []
    for row in rows[:limit]:
        player = str(row.get("pitcher_name") or row.get("player_name") or row.get("away_abbr") or "Pick").strip()
        selection = str(row.get("selection") or "pick").strip().title()
        market = str(row.get("prop") or row.get("market") or "bet").strip().replace("_", " ")
        line = row.get("market_line") if row.get("market_line") is not None else row.get("line")
        if line is not None:
            items.append(f"{player} {selection} {format_num(line)} {market}".strip())
        else:
            items.append(f"{player} {selection} {market}".strip())
    return items


def _games_from_day_payload(day_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = day_payload.get("games") if isinstance(day_payload.get("games"), list) else []
    games: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
        official_count, extra_count, shadow_count = _market_counts(betting)
        starter_names = row.get("starter_names") if isinstance(row.get("starter_names"), dict) else {}
        games.append(
            {
                "gamePk": int(row.get("game_pk") or 0),
                "away": {
                    "abbr": str(((row.get("away") or {}).get("abbr") if isinstance(row.get("away"), dict) else "") or "AWY").strip() or "AWY",
                    "name": str(((row.get("away") or {}).get("name") if isinstance(row.get("away"), dict) else "") or "Away").strip() or "Away",
                },
                "home": {
                    "abbr": str(((row.get("home") or {}).get("abbr") if isinstance(row.get("home"), dict) else "") or "HOM").strip() or "HOM",
                    "name": str(((row.get("home") or {}).get("name") if isinstance(row.get("home"), dict) else "") or "Home").strip() or "Home",
                },
                "status": str(((row.get("status") or {}).get("detailed") if isinstance(row.get("status"), dict) else "") or "Season review").strip() or "Season review",
                "detail": str(row.get("start_time") or row.get("official_date") or "Scheduled").strip() or "Scheduled",
                "summary": f"{str(starter_names.get('away') or 'TBD').strip() or 'TBD'} vs {str(starter_names.get('home') or 'TBD').strip() or 'TBD'}",
                "metrics": [
                    {"label": "Official", "value": str(official_count)},
                    {"label": "Extra", "value": str(extra_count)},
                    {"label": "Shadow", "value": str(shadow_count)},
                    {"label": "Cards", "value": "Yes" if day_payload.get("cards_available") else "No"},
                ],
                "panels": [
                    {
                        "eyebrow": "Starters",
                        "title": f"{str(starter_names.get('away') or 'TBD').strip() or 'TBD'} vs {str(starter_names.get('home') or 'TBD').strip() or 'TBD'}",
                        "body": "Starter names are coming from the season-day frontend artifact.",
                    },
                    {
                        "eyebrow": "Official picks",
                        "title": "Top season-day plays",
                        "body": "These are the first official picks surfaced for this game in the season-day payload.",
                        "items": _top_pick_items(betting),
                    },
                ],
            }
        )
    return games


def build_season_page_context(season: int, selected_date: str, *, profile: str = "retuned") -> dict[str, Any]:
    parsed_date = parse_iso_date(selected_date)
    prev_date = parsed_date.fromordinal(parsed_date.toordinal() - 1).isoformat()
    next_date = parsed_date.fromordinal(parsed_date.toordinal() + 1).isoformat()

    manifest_path = season_eval_manifest_path(int(season))
    day_path = season_frontend_day_path(int(season), selected_date, profile=profile)
    summary_path = daily_artifact_path(selected_date)
    manifest = load_json_file(manifest_path)
    day_payload = load_json_file(day_path)
    summary = load_json_file(summary_path)
    betting_games = _betting_payload_by_game(selected_date) if summary else {}
    output_rows = summary.get("outputs") if isinstance((summary or {}).get("outputs"), list) else []
    game_pks = [int(row.get("game_pk") or 0) for row in output_rows if isinstance(row, dict) and int(row.get("game_pk") or 0)]
    sim_games = _daily_sim_by_game(selected_date, game_pks) if game_pks else {}
    actual_games = _daily_actual_by_game(selected_date, game_pks) if game_pks else {}
    games = _games_from_daily_summary(summary, betting_games=betting_games, sim_games=sim_games, actual_games=actual_games) if summary else []
    if not games:
        games = _games_from_day_payload(day_payload or {}) if day_payload else []
    using_sample_data = False

    overview = (manifest or {}).get("overview") if isinstance((manifest or {}).get("overview"), dict) else {}
    full_game = ((manifest or {}).get("recap") or {}).get("full_game") if isinstance(((manifest or {}).get("recap") or {}).get("full_game"), dict) else {}
    moneyline = full_game.get("moneyline") if isinstance(full_game.get("moneyline"), dict) else {}
    totals = full_game.get("totals") if isinstance(full_game.get("totals"), dict) else {}
    betting = (day_payload or {}).get("betting") if isinstance((day_payload or {}).get("betting"), dict) else {}
    betting_counts = betting.get("selected_counts") if isinstance(betting.get("selected_counts"), dict) else {}

    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["detail"],
        }
        for game in games
    ]

    return apply_game_board_contract({
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "module_links": build_module_links(selected_date, "Season review"),
        "games": games,
        "scoreboard_items": scoreboard_items,
        "source_path": f"{manifest_path} | {day_path} | {summary_path}",
        "using_sample_data": using_sample_data,
        "source_title": "MLB season review artifacts" if games else "MLB season review unavailable",
        "header_stats": [
            {"label": "Days", "value": str(overview.get("days") or "-")},
            {"label": "Games", "value": str(overview.get("total_games") or len(games))},
            {"label": "ML Acc", "value": format_pct(moneyline.get("accuracy"))},
            {"label": "Totals MAE", "value": format_num(totals.get("mae"))},
            {"label": "Today's picks", "value": str(betting_counts.get("combined") or 0)},
        ],
        "route_path": f"/mlb/season/{int(season)}",
        "intro_title": f"MLB {int(season)} Season Review",
        "intro_body": "This first Syndicate season-review pass combines the season eval manifest with the selected season-day frontend artifact so MLB season navigation points to a real artifact-backed page instead of a missing route.",
        "show_app_header": False,
        "show_intro": False,
        "show_source_summary": False,
        "page_body_class": "cards-body syndicate-mlb-cards-page",
        "page_shell_class": "syndicate-mlb-cards-shell",
        "cards_grid_class": "mlb-cards-grid",
        "cards_stylesheet": "mlb/cards.css",
        # No `cards_script`: this page's only script was static/mlb/board.js,
        # which was the first 52 lines of shared/game_board.js with the IIFE
        # closed early -- a pure copy. game_cards_board.html already loads the
        # shared script unconditionally and had a special case skipping this
        # one, so the file has been dead code at this route. Deleted 2026-08-14
        # with that special case; behaviour here is unchanged.
        "teaser": {
            "label": "Official betting card",
            "body": "Jump from the season review into the official MLB betting-card page for this date.",
            "href": f"/mlb/season/{int(season)}/betting-card?date={selected_date}",
            "cta": "Open betting card",
        },
    }, sport="mlb", module="season_review")