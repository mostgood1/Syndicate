from __future__ import annotations

from typing import Any

from syndicate.features.nba.sources import build_module_links
from syndicate.features.nba.sources import format_moneyline
from syndicate.features.nba.sources import format_num
from syndicate.features.nba.sources import load_json
from syndicate.features.nba.sources import processed_path
from syndicate.features.shared.rank_board import build_rank_page_context


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
            win_prob = pick.get("win_prob")
            try:
                win_prob_text = f"{float(win_prob) * 100:.1f}%"
            except Exception:
                win_prob_text = "-"
            cards.append(
                {
                    "title": str(pick.get("display_pick") or "NBA pick").strip() or "NBA pick",
                    "eyebrow": str(pick.get("team") or pick.get("market") or "NBA picks").strip() or "NBA picks",
                    "badge": f"{format_num(pick.get('ev_pct'))}% EV",
                    "meta": str(pick.get("matchup") or game.get("matchup") or "-").strip() or "-",
                    "metrics": [
                        {"label": "Win prob", "value": win_prob_text},
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
            )
            if len(cards) >= limit:
                return cards
    return cards


def build_picks_page_context(selected_date: str) -> dict[str, Any]:
    summary_path = processed_path(f"recommendations_slate_{selected_date}.json")
    summary = load_json(summary_path)
    cards = _cards_from_summary(summary or {})
    using_sample_data = False
    counts = (summary or {}).get("counts") if isinstance((summary or {}).get("counts"), dict) else {}
    games_count = counts.get("games") or "-"
    picks_count = counts.get("picks") or len(cards)
    summary_stats = [
        {"label": "Top cards", "value": str(len(cards))},
        {"label": "Games", "value": str(games_count)},
        {"label": "Stored picks", "value": str(picks_count)},
    ]

    return build_rank_page_context(
        selected_date=selected_date,
        route_path="/nba/picks",
        intro_title="NBA Picks",
        intro_body="This page turns stored NBA recommendation slates into a standalone picks surface, so the top plays stay readable without dropping back to the shared ranked-board shell.",
        aria_label="NBA picks board",
        source_path=summary_path,
        source_title="NBA recommendations slate" if cards else "NBA picks unavailable",
        rank_cards=cards,
        using_sample_data=using_sample_data,
        header_stats=[
            {"label": "Cards", "value": str(len(cards))},
            {"label": "Games", "value": str(games_count)},
        ],
        module_links=build_module_links(selected_date, "Picks"),
        warning_panel={
            "eyebrow": "Recommendation lane",
            "title": "Stored slates keep the top NBA plays readable",
            "body": "Use the picks lane when you want the saved recommendation slate for one day, then jump into cards, props, or betting-card views for the same date.",
            "list_items": [
                "Each card reflects a processed pick from the saved recommendations artifact.",
                "The side panel keeps the source artifact visible for debugging and verification.",
            ],
        },
        summary_panel={"summary_stats": summary_stats},
        reset_href="/nba/picks",
        empty_state={
            "eyebrow": "NBA picks",
            "title": "No stored NBA picks were available for this date",
            "body": "The picks board only renders saved NBA recommendation-slate artifacts, and none were available for the requested date.",
            "list_items": ["Choose another stored NBA date from the calendar control."],
        } if not cards else None,
    )
