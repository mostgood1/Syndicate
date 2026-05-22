from __future__ import annotations

from typing import Any
from syndicate.features.ncaab.cards import _group_rows
from syndicate.features.ncaab.sources import available_dates
from syndicate.features.ncaab.sources import build_module_links
from syndicate.features.ncaab.sources import default_season_date
from syndicate.features.ncaab.sources import mirrored_recommendations_payload
from syndicate.features.ncaab.sources import mirrored_results_by_date_payload
from syndicate.features.ncaab.sources import mirrored_results_dates
from syndicate.features.ncaab.sources import mirrored_schedule_dates
from syndicate.features.ncaab.sources import mirrored_season_dates
from syndicate.features.ncaab.sources import schedule_dates
from syndicate.features.ncaab.sources import season_dates
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context


recommendations_payload = mirrored_recommendations_payload
results_by_date_payload = mirrored_results_by_date_payload
results_dates = mirrored_results_dates
schedule_dates = mirrored_schedule_dates
season_dates = mirrored_season_dates


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _fmt_num(value: Any, digits: int = 1) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _fmt_score(row: dict[str, Any]) -> str:
    away_score = row.get("away_score")
    home_score = row.get("home_score")
    if away_score is None or home_score is None:
        return "Final"
    return f"Final {away_score}-{home_score}"


def _actual_total(row: dict[str, Any]) -> float | None:
    total = _safe_float(row.get("actual_total"))
    if total is not None:
        return total
    away_score = _safe_float(row.get("away_score"))
    home_score = _safe_float(row.get("home_score"))
    if away_score is None or home_score is None:
        return None
    return away_score + home_score


def _actual_margin(row: dict[str, Any]) -> float | None:
    margin = _safe_float(row.get("actual_margin"))
    if margin is not None:
        return margin
    away_score = _safe_float(row.get("away_score"))
    home_score = _safe_float(row.get("home_score"))
    if away_score is None or home_score is None:
        return None
    return home_score - away_score


def _results_summary(row: dict[str, Any]) -> str:
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    away_score = row.get("away_score")
    home_score = row.get("home_score")
    actual_total = _actual_total(row)
    pred_total = row.get("pred_total")
    pred_margin = row.get("pred_margin")
    actual_margin = _actual_margin(row)
    score_text = f"{away_team} {away_score}, {home_team} {home_score}" if away_score is not None and home_score is not None else f"{away_team} at {home_team}"
    return (
        f"{score_text}. Actual total {_fmt_num(actual_total, 0)} against predicted total {_fmt_num(pred_total, 1)}, "
        f"with actual margin {_fmt_num(actual_margin, 1)} versus predicted margin {_fmt_num(pred_margin, 1)}."
    )


def _results_only_game(row: dict[str, Any], selected_date: str) -> dict[str, Any]:
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    game_id = str(row.get("game_id") or f"results-{selected_date}-{away_team}-{home_team}").strip()
    return {
        "gamePk": game_id,
        "card_variant": "shared_default",
        "away": {"abbr": away_team[:3].upper(), "name": away_team, "logo": row.get("away_logo")},
        "home": {"abbr": home_team[:3].upper(), "name": home_team, "logo": row.get("home_logo")},
        "status": selected_date,
        "detail": _fmt_score(row),
        "summary": _results_summary(row),
        "metrics": [
            {"label": "ATS", "value": str(row.get("actual_ats") or "-").strip() or "-"},
            {"label": "OU", "value": str(row.get("actual_ou") or row.get("ou_result_full") or "-").strip() or "-"},
            {"label": "Pred margin", "value": _fmt_num(row.get("pred_margin"))},
            {"label": "Actual margin", "value": _fmt_num(_actual_margin(row))},
            {"label": "Actual total", "value": _fmt_num(_actual_total(row), 0)},
        ],
        "panels": [
            {
                "eyebrow": "Final result",
                "title": _fmt_score(row),
                "body": _results_summary(row),
                "items": [
                    f"ATS correct: {str(row.get('ats_correct') if row.get('ats_correct') is not None else '-').strip()}",
                    f"OU correct: {str(row.get('ou_correct') if row.get('ou_correct') is not None else '-').strip()}",
                ],
            },
            {
                "eyebrow": "Prediction recap",
                "title": f"Pred margin {_fmt_num(row.get('pred_margin'))} | Pred total {_fmt_num(row.get('pred_total'))}",
                "body": "This season-review row is sourced from the settled NCAAB daily results payload for the selected date.",
                "items": [
                    f"Pred ATS: {str(row.get('pred_ats') or '-').strip() or '-'}",
                    f"Pred OU: {str(row.get('pred_ou') or '-').strip() or '-'}",
                ],
            },
        ],
    }


def _results_by_game(results_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in results_rows:
        if not isinstance(row, dict):
            continue
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            continue
        out[game_id] = row
    return out


def _merge_games(selected_date: str, recommendation_rows: list[dict[str, Any]], results_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recommendation_games = _group_rows(recommendation_rows) if recommendation_rows else []
    results_map = _results_by_game(results_rows)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for card in recommendation_games:
        game_id = str(card.get("gamePk") or "").strip()
        if not game_id:
            continue
        merged_card = dict(card)
        result = results_map.get(game_id)
        if result:
            merged_card["status"] = selected_date
            merged_card["detail"] = _fmt_score(result)
            merged_card["summary"] = _results_summary(result)
            merged_card["metrics"] = [
                {"label": "Top bet", "value": ((card.get("metrics") or [{}])[0]).get("value") if isinstance(card.get("metrics"), list) else "-"},
                {"label": "ATS", "value": str(result.get("actual_ats") or "-").strip() or "-"},
                {"label": "OU", "value": str(result.get("actual_ou") or result.get("ou_result_full") or "-").strip() or "-"},
                {"label": "Actual margin", "value": _fmt_num(_actual_margin(result))},
                {"label": "Actual total", "value": _fmt_num(_actual_total(result), 0)},
            ]
            panels = list(merged_card.get("panels") or [])
            panels.append(
                {
                    "eyebrow": "Final result",
                    "title": _fmt_score(result),
                    "body": "Season review overlays the settled daily results payload onto the source recommendation card for this matchup.",
                    "items": [
                        f"Pred ATS: {str(result.get('pred_ats') or '-').strip() or '-'}",
                        f"Pred OU: {str(result.get('pred_ou') or '-').strip() or '-'}",
                        f"ATS correct: {str(result.get('ats_correct') if result.get('ats_correct') is not None else '-').strip()}",
                        f"OU correct: {str(result.get('ou_correct') if result.get('ou_correct') is not None else '-').strip()}",
                    ],
                }
            )
            merged_card["panels"] = panels[:3]
        merged.append(merged_card)
        seen.add(game_id)

    for game_id, result in results_map.items():
        if game_id in seen:
            continue
        merged.append(_results_only_game(result, selected_date))

    merged.sort(key=lambda game: (0 if str(game.get("gamePk") or "").strip() in results_map else 1, str(game.get("detail") or ""), str(game.get("gamePk") or "")))
    return merged


def _season_rank_card(game: dict[str, Any], season: int, selected_date: str) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    game_pk = str(game.get("gamePk") or "").strip()
    href = f"/ncaab/game/{game_pk}?date={selected_date}" if game_pk and not game_pk.startswith("results-") else f"/ncaab/season/{int(season)}?date={selected_date}"
    return {
        "title": f"{str(away.get('abbr') or away.get('name') or 'AWY').strip() or 'AWY'} @ {str(home.get('abbr') or home.get('name') or 'HOM').strip() or 'HOM'}",
        "eyebrow": str(game.get("detail") or selected_date).strip() or selected_date,
        "badge": str(((game.get("metrics") or [{}])[0]).get("value") or "-").strip() if isinstance(game.get("metrics"), list) else "-",
        "meta": str(game.get("summary") or "").strip() or "Historical season-review matchup.",
        "metrics": list(game.get("metrics") or [])[:5],
        "summary": str(game.get("summary") or "").strip() or "Historical season-review matchup.",
        "list_items": [
            str(panel.get("title") or "").strip()
            for panel in (game.get("panels") or [])
            if isinstance(panel, dict) and str(panel.get("title") or "").strip()
        ][:4],
        "href": href,
        "href_label": "Open game detail" if game_pk and not game_pk.startswith("results-") else "Open season review",
    }


def _season_data(season: int, selected_date: str) -> dict[str, Any]:
    dates = season_dates(season)
    resolved_date = resolve_selected_value(selected_date or default_season_date(season), dates, default_season_date(season))
    recommendation_payload = recommendations_payload(resolved_date) or {}
    recommendation_rows = recommendation_payload.get("data") if isinstance(recommendation_payload.get("data"), list) else []
    results_payload = results_by_date_payload(resolved_date) or {}
    results_rows = results_payload.get("rows") if isinstance(results_payload.get("rows"), list) else []
    games = _merge_games(resolved_date, recommendation_rows, results_rows)
    using_sample_data = False
    prev_date, next_date = neighboring_values(dates, resolved_date, fallback=resolved_date)
    return {
        "dates": dates,
        "resolved_date": resolved_date,
        "recommendation_rows": recommendation_rows,
        "results_rows": results_rows,
        "games": games,
        "using_sample_data": using_sample_data,
        "prev_date": prev_date,
        "next_date": next_date,
        "schedule_count": len(schedule_dates()),
        "result_date_count": len(results_dates()),
    }


def build_season_page_context(season: int, selected_date: str) -> dict[str, Any]:
    data = _season_data(season, selected_date)
    resolved_date = data["resolved_date"]
    games = data["games"]
    season_label = int(season)
    return apply_game_board_contract(
        {
            "date": resolved_date,
            "requested_date": selected_date or resolved_date,
            "prev_date": data["prev_date"],
            "next_date": data["next_date"],
            "control_action": f"/ncaab/season/{int(season)}",
            "controls_prev_href": f"/ncaab/season/{int(season)}?date={data['prev_date']}",
            "controls_next_href": f"/ncaab/season/{int(season)}?date={data['next_date']}",
            "control_value": resolved_date,
            "module_links": build_module_links(resolved_date, "Season Review"),
            "games": games,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["detail"],
                }
                for game in games
            ],
            "source_path": f"Syndicate data/ncaab_source/api/dates.json | data/ncaab_source/api/recommendations/recommendations_{resolved_date}.json | data/ncaab_source/api/results_by_date/results_{resolved_date}.json",
            "source_title": f"NCAAB {season_label} season review data",
            "using_sample_data": data["using_sample_data"],
            "route_path": f"/ncaab/season/{season_label}",
            "intro_title": f"NCAAB {season_label} Season Review",
            "intro_body": f"This NCAAB season-review board uses mirrored schedule dates, grouped recommendation rows, and settled daily results so {season_label} navigation lands on a real historical page instead of a dead route.",
            "header_stats": [
                {"label": "Season dates", "value": str(len(data['dates']))},
                {"label": "Schedule dates", "value": str(data['schedule_count'])},
                {"label": "Results dates", "value": str(data['result_date_count'])},
                {"label": "Recommendations", "value": str(len(data['recommendation_rows']))},
                {"label": "Finals", "value": str(len(data['results_rows']))},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "empty_state": (
                {
                    "eyebrow": "Season review",
                    "title": "No season-review rows were available for this date",
                    "body": "The season-review board only renders saved recommendation and results rows, and none were available for the selected NCAAB date.",
                    "list_items": [
                        f"Season {season_label}",
                        f"Date {resolved_date}",
                    ],
                }
                if not games
                else None
            ),
            "teaser": {
                "label": "Pregame cards",
                "body": "Open the same date on the NCAAB cards board to compare the pregame recommendation surface against this historical season-review view.",
                "href": f"/ncaab/cards?date={resolved_date}",
                "cta": "Open NCAAB cards",
            },
        },
        sport="ncaab",
        module="season_review",
        source_kind="artifact_backed",
        live_lens_integrated=False,
    )


def build_season_betting_card_page_context(season: int, selected_date: str) -> dict[str, Any]:
    data = _season_data(season, selected_date)
    resolved_date = data["resolved_date"]
    rank_cards = [_season_rank_card(game, season, resolved_date) for game in data["games"]]
    context = build_rank_page_context(
        selected_date=resolved_date,
        route_path=f"/ncaab/season/{int(season)}/betting-card",
        intro_title=f"NCAAB {int(season)} Betting Card",
        intro_body="This historical betting-card view reprojects the season-review merge into a ranked board so settled NCAAB dates have a compact, card-first lane alongside the full season-review board.",
        aria_label="NCAAB historical betting card",
        source_path=f"Syndicate data/ncaab_source/api/dates.json | data/ncaab_source/api/recommendations/recommendations_{resolved_date}.json | data/ncaab_source/api/results_by_date/results_{resolved_date}.json",
        source_title="NCAAB mirrored historical betting card data",
        rank_cards=rank_cards,
        using_sample_data=data["using_sample_data"],
        header_stats=[
            {"label": "Cards", "value": str(len(rank_cards))},
            {"label": "Recommendations", "value": str(len(data['recommendation_rows']))},
            {"label": "Finals", "value": str(len(data['results_rows']))},
            {"label": "Results dates", "value": str(data['result_date_count'])},
        ],
        module_links=build_module_links(resolved_date, "Betting Card"),
        empty_state=(
            {
                "eyebrow": "Historical lane",
                "title": "No betting-card rows were available for this date",
                "body": "The NCAAB historical betting-card view only renders saved recommendation and results rows, and none were available for the selected date.",
                "list_items": [
                    f"Season {int(season)}",
                    f"Date {resolved_date}",
                ],
            }
            if not rank_cards
            else None
        ),
        warning_panel={
            "eyebrow": "Historical lane",
            "title": "Season review and betting card now share the same settled-date source merge",
            "body": "Use this compact board when you want ranked historical cards first, then drill back into season review for the denser matchup board.",
            "list_items": [
                "Cards come from the same merged recommendation and results data as season review.",
                "Recommendation-backed rows can still drill into game detail from this ranked board.",
            ],
        },
    )
    context["teaser"] = {
        "label": "Season review",
        "body": "Open the full season-review board for the same date when you want the denser game-board layout and scoreboard navigation.",
        "href": f"/ncaab/season/{int(season)}?date={resolved_date}",
        "cta": "Open season review",
    }
    return context


def build_season_betting_card_api_payload(season: int, selected_date: str) -> dict[str, Any]:
    return build_rank_api_payload(build_season_betting_card_page_context(season, selected_date))