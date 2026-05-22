from __future__ import annotations

from typing import Any

from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.ladders_common import format_num
from syndicate.features.mlb.ladders_common import format_pct
from syndicate.features.mlb.ladders_common import parse_iso_date
from syndicate.features.mlb.sources import load_json_file
from syndicate.features.mlb.sources import season_betting_card_day_path


def _market_title(market: dict[str, Any], fallback_game: str) -> str:
    player_name = str(market.get("player_name") or market.get("player") or market.get("pitcher") or "").strip()
    selection = str(market.get("selection") or market.get("side") or "pick").strip().title()
    line = market.get("line")
    market_name = str(market.get("market") or "bet").strip().replace("_", " ").title()
    if player_name:
        line_piece = f" {format_num(line)}" if line is not None else ""
        return f"{player_name} {selection}{line_piece} {market_name}".strip()
    if market_name.lower() == "ml":
        team = str(market.get("away_abbr") if str(market.get("selection") or "").strip().lower() == "away" else market.get("home_abbr") or "").strip()
        return f"{team or fallback_game} Moneyline"
    if market_name.lower() == "totals":
        line_piece = f" {format_num(line)}" if line is not None else ""
        return f"{selection}{line_piece} Total".strip()
    return f"{fallback_game} {selection} {market_name}".strip()


def _card_from_market(market: dict[str, Any], fallback_game: str, eyebrow: str) -> dict[str, Any]:
    reasons = market.get("baseball_reasons") if isinstance(market.get("baseball_reasons"), list) else []
    if not reasons:
        reasons = market.get("reasons") if isinstance(market.get("reasons"), list) else []
    return {
        "title": _market_title(market, fallback_game),
        "eyebrow": eyebrow,
        "badge": f"{format_num(market.get('stake_u'))}u @ {str(market.get('odds') or market.get('price') or '-').strip()}",
        "meta": fallback_game,
        "metrics": [
            {"label": "Model", "value": format_pct(market.get("selected_side_model_prob") if market.get("selected_side_model_prob") is not None else market.get("model_prob"))},
            {"label": "Market", "value": format_pct(market.get("selected_side_market_prob") if market.get("selected_side_market_prob") is not None else market.get("market_no_vig_prob"))},
            {"label": "Edge", "value": format_pct(market.get("edge"))},
            {"label": "Stake", "value": f"{format_num(market.get('stake_u'))}u"},
        ],
        "summary": str(market.get("reason_summary") or market.get("reasons", ["No summary available."])[0] if isinstance(market.get("reasons"), list) and market.get("reasons") else "No summary available.").strip(),
        "list_items": [str(item).strip() for item in reasons if str(item).strip()][:4],
    }


def _rank_cards_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    games = payload.get("games") if isinstance(payload.get("games"), dict) else {}
    cards: list[dict[str, Any]] = []
    for game_payload in games.values():
        if not isinstance(game_payload, dict):
            continue
        markets = game_payload.get("markets") if isinstance(game_payload.get("markets"), dict) else {}
        ml = markets.get("ml") if isinstance(markets.get("ml"), dict) else None
        totals = markets.get("totals") if isinstance(markets.get("totals"), dict) else None
        fallback_game = " @ ".join(
            [
                str((ml or totals or {}).get("away_abbr") or (ml or totals or {}).get("away") or "AWY").strip(),
                str((ml or totals or {}).get("home_abbr") or (ml or totals or {}).get("home") or "HOM").strip(),
            ]
        )
        if ml:
            cards.append(_card_from_market(ml, fallback_game, "Moneyline"))
        if totals:
            cards.append(_card_from_market(totals, fallback_game, "Total"))
        for key, eyebrow in (
            ("pitcherProps", "Pitcher prop"),
            ("hitterProps", "Hitter prop"),
            ("extraPitcherProps", "Extra pitcher prop"),
            ("extraHitterProps", "Extra hitter prop"),
        ):
            rows = markets.get(key) if isinstance(markets.get(key), list) else []
            for row in rows:
                if isinstance(row, dict):
                    cards.append(_card_from_market(row, fallback_game, eyebrow))
    return cards


def build_betting_card_page_context(season: int, selected_date: str, *, profile: str = "retuned") -> dict[str, Any]:
    parsed_date = parse_iso_date(selected_date)
    prev_date = parsed_date.fromordinal(parsed_date.toordinal() - 1).isoformat()
    next_date = parsed_date.fromordinal(parsed_date.toordinal() + 1).isoformat()

    payload_path = season_betting_card_day_path(int(season), selected_date, profile=profile)
    payload = load_json_file(payload_path)
    rank_cards = _rank_cards_from_payload(payload or {}) if payload else []
    using_sample_data = False

    selected_counts = (payload or {}).get("selected_counts") if isinstance((payload or {}).get("selected_counts"), dict) else {}
    summary = (payload or {}).get("summary") if isinstance((payload or {}).get("summary"), dict) else {}
    warnings = summary.get("warnings") if isinstance(summary.get("warnings"), list) else []

    return {
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "rank_cards": rank_cards,
        "using_sample_data": using_sample_data,
        "source_path": str(payload_path),
        "source_title": "MLB official betting card" if rank_cards else "MLB betting card unavailable",
        "header_stats": [
            {"label": "Selected", "value": str(selected_counts.get("combined") or len(rank_cards))},
            {"label": "Profile", "value": str((payload or {}).get("profile") or profile).strip() or profile},
            {"label": "Unresolved", "value": str(summary.get("unresolved_n") or 0)},
        ],
        "route_path": f"/mlb/season/{int(season)}/betting-card",
        "intro_title": f"MLB {int(season)} Betting Card",
        "intro_body": "This first Syndicate pass maps the official MLB betting-card day payload into the shared ranked-board so the existing cards navigation lands on a real, artifact-backed page instead of a 404.",
        "aria_label": "MLB betting card board",
        "module_links": build_module_links(selected_date, "Betting card"),
        "warning_panel": {
            "eyebrow": "Publish diagnostics",
            "title": "Card warnings",
            "body": "These warnings come directly from the season betting day payload.",
            "list_items": [str(item).strip() for item in warnings if str(item).strip()][:5],
        },
        "empty_state": {
            "eyebrow": "MLB betting card",
            "title": "No stored MLB betting card was available for this date",
            "body": "The official betting-card board only renders saved season day payloads, and none were available for the requested date.",
            "list_items": ["Choose another stored MLB date or refresh the season betting-card artifacts."],
        } if not rank_cards else None,
    }