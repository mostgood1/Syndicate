from __future__ import annotations

from typing import Any

from syndicate.features.shared.rank_board import build_rank_page_context
from syndicate.features.wnba.sources import build_module_links
from syndicate.features.wnba.sources import default_date
from syndicate.features.wnba.sources import format_moneyline
from syndicate.features.wnba.sources import format_num
from syndicate.features.wnba.sources import format_pct
from syndicate.features.wnba.sources import parse_iso_date
from syndicate.features.wnba.sources import load_json
from syndicate.features.wnba.sources import processed_path_or_default


def _summary_for_date(selected_date: str) -> dict[str, Any]:
    summary = load_json(processed_path_or_default(f"recommendations_slate_{selected_date}.json"))
    return summary if isinstance(summary, dict) else {}


def _card_from_pick(game: dict[str, Any], pick: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(pick.get("display_pick") or "WNBA pick").strip() or "WNBA pick",
        "eyebrow": str(pick.get("team") or pick.get("market") or "WNBA picks").strip() or "WNBA picks",
        "badge": f"{format_num(pick.get('ev_pct'))}% EV",
        "meta": str(pick.get("matchup") or game.get("matchup") or "-").strip() or "-",
        "metrics": [
            {"label": "Win prob", "value": format_pct(pick.get("win_prob"))},
            {"label": "EV", "value": f"{format_num(pick.get('ev_pct'))}%"},
            {"label": "Price", "value": format_moneyline(pick.get("price"))},
            {"label": "Score", "value": format_num(pick.get("score"))},
        ],
        "summary": str(pick.get("basketball_summary") or pick.get("display_pick") or "No summary available.").strip(),
        "list_items": [
            str(item).strip()
            for item in (pick.get("top_play_reasons") or pick.get("reasons") or [])
            if str(item).strip()
        ][:4],
    }


def _cards_from_summary(summary: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    per_game = summary.get("per_game") if isinstance(summary.get("per_game"), list) else []
    cards: list[dict[str, Any]] = []
    for game in per_game:
        if not isinstance(game, dict):
            continue
        picks = game.get("picks") if isinstance(game.get("picks"), list) else []
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            cards.append(_card_from_pick(game, pick))
            if len(cards) >= limit:
                return cards
    return cards


def _sections_from_summary(summary: dict[str, Any], *, limit_games: int = 8, limit_per_game: int = 4) -> list[dict[str, Any]]:
    per_game = summary.get("per_game") if isinstance(summary.get("per_game"), list) else []
    sections: list[dict[str, Any]] = []
    for game in per_game[:limit_games]:
        if not isinstance(game, dict):
            continue
        picks = game.get("picks") if isinstance(game.get("picks"), list) else []
        cards = [_card_from_pick(game, pick) for pick in picks[:limit_per_game] if isinstance(pick, dict)]
        if not cards:
            continue
        sections.append(
            {
                "title": str(game.get("matchup") or f"{game.get('away') or '-'} @ {game.get('home') or '-'}").strip() or "WNBA game",
                "meta": f"{len(cards)} pick{'s' if len(cards) != 1 else ''}",
                "cards": cards,
            }
        )
    return sections


def build_picks_page_context(selected_date: str) -> dict[str, Any]:
    summary_path = processed_path_or_default(f"recommendations_slate_{selected_date}.json")
    summary = _summary_for_date(selected_date)
    cards = _cards_from_summary(summary)
    using_sample_data = False

    context = build_rank_page_context(
        selected_date=selected_date,
        route_path="/wnba/picks",
        intro_title="WNBA Picks",
        intro_body="This standalone picks surface keeps the top WNBA recommendation slate on one stored date with grouped matchup sections.",
        aria_label="WNBA picks board",
        source_path=summary_path,
        source_title="WNBA recommendations slate" if cards else "WNBA picks unavailable",
        rank_cards=cards,
        using_sample_data=using_sample_data,
        header_stats=[
            {"label": "Cards", "value": str(len(cards))},
            {"label": "Games", "value": str(((summary or {}).get("counts") or {}).get("games") or "-")},
        ],
        module_links=build_module_links(selected_date, "Picks"),
        empty_state={
            "eyebrow": "WNBA picks",
            "title": "No stored WNBA picks were available for this date",
            "body": "The picks board only renders saved WNBA recommendation-slate artifacts, and none were available for the requested date.",
            "list_items": ["Choose another stored WNBA date from the calendar control."],
        } if not cards else None,
    )
    counts = (summary.get("counts") or {}) if isinstance(summary, dict) else {}
    context["summary_panel"] = {
        "eyebrow": "Slate snapshot",
        "title": f"{counts.get('games') or 0} games and {len(cards)} ranked picks",
        "body": "The picks page keeps grouped recommendation-slate sections and readable local navigation without falling back to the generic rank-board shell.",
        "summary_stats": [
            {"label": "Date", "value": selected_date},
            {"label": "Games", "value": str(counts.get("games") or 0)},
            {"label": "Markets", "value": str(counts.get("markets") or 0)},
            {"label": "Cards", "value": str(len(cards))},
        ],
    }
    context["card_sections"] = _sections_from_summary(summary)
    context["warning_panel"] = {
        "eyebrow": "Stored slates",
        "title": "WNBA picks stay anchored to saved recommendation artifacts",
        "body": "This page keeps the picks workflow on one stored WNBA slate while preserving direct links into cards, betting-card, props, and archive views for the same date.",
        "list_items": [
            "Grouped matchup sections come directly from the stored recommendation slate.",
            "Use the date control to move across available local WNBA slates without switching surfaces.",
        ],
    }
    return context


def build_betting_card_page_context(season: int, selected_date: str) -> dict[str, Any]:
    context = dict(build_picks_page_context(selected_date or default_date()))
    resolved_date = str(context.get("date") or selected_date or default_date())
    resolved_season = int(season)
    summary = _summary_for_date(resolved_date)
    counts = (summary.get("counts") or {}) if isinstance(summary, dict) else {}
    context["route_path"] = f"/wnba/season/{resolved_season}/betting-card"
    context["intro_title"] = f"WNBA {resolved_season} Betting Card"
    context["intro_body"] = "This historical WNBA betting-card view reuses the stored recommendation-slate lane under an MLB-shaped season betting-card route family."
    context["source_title"] = "WNBA season betting-card snapshot" if context.get("rank_cards") else "WNBA betting card unavailable"
    context["source_date_display"] = resolved_date
    context["module_links"] = build_module_links(resolved_date, "Betting Card", season=resolved_season)
    context["summary_panel"] = {
        "eyebrow": "Slate snapshot",
        "title": f"{counts.get('games') or 0} games and {len(context.get('rank_cards') or [])} ranked picks",
        "body": "This standalone page keeps the WNBA season betting-card route visually distinct while it is still backed by local recommendation-slate artifacts.",
        "summary_stats": [
            {"label": "Season", "value": str(resolved_season)},
            {"label": "Date", "value": resolved_date},
            {"label": "Games", "value": str(counts.get("games") or 0)},
            {"label": "Markets", "value": str(counts.get("markets") or 0)},
        ],
    }
    context["card_sections"] = _sections_from_summary(summary)
    context["warning_panel"] = {
        "eyebrow": "Stored slates",
        "title": "WNBA betting card currently reuses processed recommendation slates",
        "body": "This route gives WNBA an MLB-shaped betting-card family without inventing a second recommendation pipeline before richer season surfaces are ready.",
        "list_items": [
            "The ranked cards on this page are the same recommendation artifacts surfaced on the picks board.",
            "Date navigation stays anchored to processed slate dates already present in the source repo.",
        ],
    }
    return context