from __future__ import annotations

from typing import Any

from syndicate.features.shared.game_board_contract import build_single_game_board_context
from syndicate.features.mlb.cards import _betting_payload_by_game
from syndicate.features.mlb.cards import _daily_actual_by_game
from syndicate.features.mlb.cards import _daily_sim_by_game
from syndicate.features.mlb.cards import _metrics_for_output
from syndicate.features.mlb.cards import _panels_for_output
from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.ladders_common import format_num
from syndicate.features.mlb.ladders_common import format_pct
from syndicate.features.mlb.ladders_common import parse_iso_date
from syndicate.features.mlb.sources import daily_artifact_path
from syndicate.features.mlb.sources import load_json_file


def _format_signed_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{format_num(number)}"


def _find_output(summary: dict[str, Any], game_pk: int) -> dict[str, Any] | None:
    outputs = summary.get("outputs") if isinstance(summary.get("outputs"), list) else []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        try:
            current_pk = int(output.get("game_pk") or 0)
        except Exception:
            current_pk = 0
        if current_pk == int(game_pk):
            return output
    return None


def _top_hr_items(output: dict[str, Any], *, team: str | None = None, limit: int = 4) -> list[str]:
    block = output.get("hitter_hr_likelihood_all") if isinstance(output.get("hitter_hr_likelihood_all"), dict) else {}
    rows = block.get("overall") if isinstance(block.get("overall"), list) else []
    items: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if team and str(row.get("team") or "").strip() != str(team):
            continue
        name = str(row.get("name") or "").strip()
        prob = format_pct(row.get("p_hr_1plus_cal") if row.get("p_hr_1plus_cal") is not None else row.get("p_hr_1plus"))
        if name:
            items.append(f"{name} - {prob}")
        if len(items) >= limit:
            break
    return items


def _panels(output: dict[str, Any]) -> list[dict[str, Any]]:
    full = output.get("full") if isinstance(output.get("full"), dict) else {}
    first5 = output.get("first5") if isinstance(output.get("first5"), dict) else {}
    first3 = output.get("first3") if isinstance(output.get("first3"), dict) else {}
    first1 = output.get("first1") if isinstance(output.get("first1"), dict) else {}
    starters = output.get("starter_names") if isinstance(output.get("starter_names"), dict) else {}
    away = str(output.get("away") or "AWY").strip() or "AWY"
    home = str(output.get("home") or "HOM").strip() or "HOM"
    return [
        {
            "eyebrow": "Projected starters",
            "title": f"{str(starters.get('away') or 'TBD').strip() or 'TBD'} vs {str(starters.get('home') or 'TBD').strip() or 'TBD'}",
            "body": "Starter names are coming directly from the MLB daily summary artifact.",
        },
        {
            "eyebrow": "Run environment",
            "title": f"Full {_format_signed_num((full.get('home_runs_mean') or 0) - (full.get('away_runs_mean') or 0))} | F5 {_format_signed_num((first5.get('home_runs_mean') or 0) - (first5.get('away_runs_mean') or 0))}",
            "body": f"Full mean: {away} {format_num(full.get('away_runs_mean'))} - {home} {format_num(full.get('home_runs_mean'))}. F3 mean: {away} {format_num(first3.get('away_runs_mean'))} - {home} {format_num(first3.get('home_runs_mean'))}. F1 tie: {format_pct(first1.get('tie_prob'))}.",
        },
        {
            "eyebrow": f"{away} HR looks",
            "title": "Top away-side HR targets",
            "body": "These hitters come from the artifact's calibrated HR likelihood block.",
            "items": _top_hr_items(output, team=away),
        },
        {
            "eyebrow": f"{home} HR looks",
            "title": "Top home-side HR targets",
            "body": "These hitters come from the artifact's calibrated HR likelihood block.",
            "items": _top_hr_items(output, team=home),
        },
    ]


def _metrics(output: dict[str, Any]) -> list[dict[str, str]]:
    full = output.get("full") if isinstance(output.get("full"), dict) else {}
    first5 = output.get("first5") if isinstance(output.get("first5"), dict) else {}
    first3 = output.get("first3") if isinstance(output.get("first3"), dict) else {}
    first1 = output.get("first1") if isinstance(output.get("first1"), dict) else {}
    return [
        {"label": "Away win", "value": format_pct(full.get("away_win_prob"))},
        {"label": "Home win", "value": format_pct(full.get("home_win_prob"))},
        {"label": "Full mean", "value": f"{format_num(full.get('away_runs_mean'))} - {format_num(full.get('home_runs_mean'))}"},
        {"label": "F5 mean", "value": f"{format_num(first5.get('away_runs_mean'))} - {format_num(first5.get('home_runs_mean'))}"},
        {"label": "F3 mean", "value": f"{format_num(first3.get('away_runs_mean'))} - {format_num(first3.get('home_runs_mean'))}"},
        {"label": "F1 tie", "value": format_pct(first1.get("tie_prob"))},
    ]


def build_game_detail_page_context(selected_date: str, game_pk: int) -> dict[str, Any]:
    parsed_date = parse_iso_date(selected_date)
    prev_date = parsed_date.fromordinal(parsed_date.toordinal() - 1).isoformat()
    next_date = parsed_date.fromordinal(parsed_date.toordinal() + 1).isoformat()

    summary_path = daily_artifact_path(selected_date)
    summary = load_json_file(summary_path)
    output = _find_output(summary or {}, int(game_pk)) if summary else None
    betting_game = None
    sim_payload = None
    actual_payload = None
    if isinstance(output, dict):
        betting_game = _betting_payload_by_game(selected_date).get(int(game_pk))
        sim_payload = _daily_sim_by_game(selected_date, [int(game_pk)]).get(int(game_pk))
        actual_payload = _daily_actual_by_game(selected_date, [int(game_pk)]).get(int(game_pk))
    using_sample_data = False
    game = {
        "gamePk": int(game_pk),
        "card_variant": "mlb_main",
        "away": {"abbr": "AWY", "name": "Unavailable"},
        "home": {"abbr": "HOM", "name": "Unavailable"},
        "status": "MLB game unavailable",
        "detail": selected_date,
        "summary": "No MLB daily summary artifact was available for this date and game id.",
        "status_badge": "Unavailable",
        "hero_note": "No stored single-game MLB artifact was available for this route.",
        "metrics": [
            {"label": "Game", "value": str(game_pk)},
            {"label": "Date", "value": selected_date},
            {"label": "Source", "value": "No data"},
        ],
        "panels": [
            {
                "eyebrow": "Game unavailable",
                "title": "No saved game detail artifact",
                "body": "Syndicate could not find a stored MLB game card for this date and game id.",
                "items": ["Return to the MLB cards board to pick a date with stored artifacts."],
            }
        ],
    } if not isinstance(output, dict) else {
        "gamePk": int(output.get("game_pk") or game_pk),
        "card_variant": "mlb_main",
        "away": {
            "abbr": str(output.get("away") or "AWY").strip() or "AWY",
            "name": str(output.get("away") or "Away").strip() or "Away",
        },
        "home": {
            "abbr": str(output.get("home") or "HOM").strip() or "HOM",
            "name": str(output.get("home") or "Home").strip() or "Home",
        },
        "status": "Game detail",
        "detail": str(summary.get("date") or selected_date).strip() or selected_date,
        "summary": "Artifact-backed single-game MLB board.",
        "status_badge": "Game detail",
        "hero_note": "Single-game MLB board view with official, props, sim, and archived box lanes",
        "metrics": _metrics_for_output(output),
        "panels": _panels_for_output(
            output,
            betting_game=betting_game,
            sim_payload=sim_payload,
            actual_payload=actual_payload,
            selected_date=selected_date,
        ),
    }

    return build_single_game_board_context(
        selected_date=selected_date,
        prev_date=prev_date,
        next_date=next_date,
        game=game,
        game_pk=int(game_pk),
        module_links=build_module_links(selected_date, "Cards"),
        source_path=str(summary_path),
        source_title="MLB daily summary artifact" if game.get("status") != "MLB game unavailable" else "MLB game unavailable",
        using_sample_data=using_sample_data,
        route_path=f"/mlb/game/{int(game_pk)}",
        intro_title=f"MLB Game {int(game_pk)}",
        intro_body="This first Syndicate pass turns the MLB game route into a real artifact-backed detail page for a single matchup, rather than leaving the source app’s game navigation as a dead link.",
        cards_grid_class="mlb-cards-grid",
        cards_stylesheet="mlb/cards.css",
        teaser={
            "label": "Related MLB modules",
            "body": "Use the ladders and betting-card modules for broader board context around this game date.",
            "href": f"/mlb/season/{selected_date[:4]}/betting-card?date={selected_date}",
            "cta": "Open betting card",
        },
        sport="mlb",
        module="game_detail",
        header_stats=[
            {"label": "Game", "value": str(int(game_pk))},
            {"label": "Away", "value": game['away']['abbr']},
            {"label": "Home", "value": game['home']['abbr']},
        ],
    )