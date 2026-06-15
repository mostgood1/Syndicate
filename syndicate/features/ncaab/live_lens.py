from __future__ import annotations

from typing import Any

from syndicate.features.ncaab.sources import build_module_links
from syndicate.features.ncaab.sources import live_lines_payload
from syndicate.features.ncaab.sources import live_lens_tuning_payload
from syndicate.features.ncaab.sources import live_state_payload
from syndicate.features.shared.live_lens_contract import attach_live_lens_contract
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context


def _fmt_num(value: Any, digits: int = 1) -> str:
    try:
        if value is None or str(value).strip() == "":
            return "-"
        return f"{float(value):.{digits}f}"
    except Exception:
        return "-"


def _fmt_clock(period: Any, display_clock: Any, state: str) -> str:
    period_s = str(period or "").strip()
    clock_s = str(display_clock or "").strip()
    state_s = str(state or "").strip().lower()
    if state_s in {"post", "final"}:
        return "Final"
    if state_s in {"pre", "scheduled"}:
        return "Pregame"
    if period_s and clock_s:
        return f"P{period_s} {clock_s}"
    if period_s:
        return f"P{period_s}"
    return clock_s or "Live"


def _summary(game: dict[str, Any], line: dict[str, Any] | None) -> str:
    away = str(game.get("away_team") or "Away").strip() or "Away"
    home = str(game.get("home_team") or "Home").strip() or "Home"
    away_score = game.get("away_score")
    home_score = game.get("home_score")
    total = game.get("total_points")
    live_total = (line or {}).get("total") if isinstance(line, dict) else None
    if away_score is not None and home_score is not None:
        score_line = f"{away} {away_score}, {home} {home_score}"
        if live_total is not None and total is not None:
            diff = float(total) - float(live_total)
            direction = "above" if diff > 0 else "below"
            return f"{score_line}. Current points sit {abs(diff):.1f} {direction} the live total."
        return f"{score_line}. Live state is sourced from the NCAAB ESPN scoreboard feed."
    return f"{away} at {home}. Live state is sourced from the NCAAB ESPN scoreboard feed."


def _rank_cards(live_state: dict[str, Any], live_lines: dict[str, Any] | None) -> list[dict[str, Any]]:
    games_map = live_state.get("games") if isinstance(live_state.get("games"), dict) else {}
    lines_map = live_lines.get("lines") if isinstance((live_lines or {}).get("lines"), dict) else {}
    cards: list[dict[str, Any]] = []
    for game_id, raw_game in games_map.items():
        if not isinstance(raw_game, dict):
            continue
        game = dict(raw_game)
        if not bool(game.get("is_live")) and not bool(game.get("is_final")):
            continue
        line = lines_map.get(str(game_id)) if isinstance(lines_map, dict) else None
        away = str(game.get("away_team_short") or game.get("away_team") or "AWY").strip() or "AWY"
        home = str(game.get("home_team_short") or game.get("home_team") or "HOM").strip() or "HOM"
        cards.append(
            {
                "title": f"{away} @ {home}",
                "eyebrow": "Live game" if game.get("is_live") else "Recent final",
                "badge": _fmt_clock(game.get("period"), game.get("display_clock"), str(game.get("state") or "")),
                "meta": f"Event {game_id}",
                "metrics": [
                    {"label": "Score", "value": f"{game.get('away_score') if game.get('away_score') is not None else '-'}-{game.get('home_score') if game.get('home_score') is not None else '-'}"},
                    {"label": "Total pts", "value": _fmt_num(game.get("total_points"), 0)},
                    {"label": "Live total", "value": _fmt_num((line or {}).get("total"), 1)},
                    {"label": "Book", "value": str((line or {}).get("book") or "-").strip() or "-"},
                ],
                "summary": _summary(game, line if isinstance(line, dict) else None),
                "list_items": [
                    f"Regulation remaining: {_fmt_num((game.get('remaining_reg_seconds') or 0) / 60.0, 1)} min" if game.get("remaining_reg_seconds") is not None else "Regulation remaining: -",
                    f"1H remaining: {_fmt_num((game.get('remaining_1h_seconds') or 0) / 60.0, 1)} min" if game.get("remaining_1h_seconds") is not None else "1H remaining: -",
                    f"Spread: {_fmt_num((line or {}).get('spread_home'), 1)} home / {_fmt_num((line or {}).get('spread_away'), 1)} away",
                ],
            }
        )
    cards.sort(key=lambda item: (0 if item.get("eyebrow") == "Live game" else 1, str(item.get("title") or "")))
    return cards


def build_live_lens_page_context(selected_date: str) -> dict[str, Any]:
    live_state = live_state_payload(selected_date) or {}
    games_map = live_state.get("games") if isinstance(live_state.get("games"), dict) else {}
    event_ids = [str(game_id).strip() for game_id, game in games_map.items() if isinstance(game, dict) and bool(game.get("is_live"))]
    live_lines = live_lines_payload(selected_date, event_ids) if event_ids else {"status": "ok", "date": selected_date, "count": 0, "lines": {}}
    tuning = live_lens_tuning_payload() or {}
    rank_cards = _rank_cards(live_state, live_lines if isinstance(live_lines, dict) else None)

    warning_panel = None
    if not isinstance(live_state, dict) or str(live_state.get("status") or "") == "error":
        warning_panel = {
            "eyebrow": "Source status",
            "title": "Live state unavailable",
            "body": "The NCAAB source live-state endpoint did not return a usable payload, so this live-lens board has no current games to render.",
            "list_items": [str(live_state.get("message") or "Source live-state payload unavailable.")],
        }
    elif not rank_cards:
        warning_panel = {
            "eyebrow": "Current slate",
            "title": "No live NCAAB games on this date",
            "body": "This live-lens board stays source-backed and renders an empty state when the NCAAB scoreboard feed has no active or recently final games for the selected date.",
            "list_items": [
                f"Source live-state count: {int(live_state.get('count') or 0)}",
                f"Live lines mapped: {int((live_lines or {}).get('count') or 0)}",
            ],
        }

    header_stats = [
        {"label": "Live games", "value": str(len([item for item in rank_cards if item.get('eyebrow') == 'Live game']))},
        {"label": "Cards", "value": str(len(rank_cards))},
        {"label": "Pace hi", "value": _fmt_num(tuning.get("pace_hi"), 2)},
        {"label": "PPS hi", "value": _fmt_num(tuning.get("pps_hi"), 2)},
    ]

    context = build_rank_page_context(
        selected_date=selected_date,
        route_path="/ncaab/live-lens",
        intro_title="NCAAB Live Lens",
        intro_body="This first NCAAB live-lens surface keeps the MLB-shaped route contract but reads the mirrored live scoreboard and live-line artifacts instead of inventing a separate monitor.",
        aria_label="NCAAB live lens board",
        source_path=f"Syndicate data/ncaab_source/api/live_state/live_state_{selected_date}.json",
        source_title="NCAAB mirrored live scoreboard + live lines",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=header_stats,
        module_links=build_module_links(selected_date, "Live Lens"),
        warning_panel=warning_panel,
    )
    context["source_date_display"] = str(live_state.get("date") or selected_date)
    context["live_state_count"] = int(live_state.get("count") or 0)
    context["live_lines_count"] = int((live_lines or {}).get("count") or 0)
    refresh_ts = (
        live_lines.get("odds_refreshed_at")
        or live_lines.get("generated_at")
        or live_lines.get("generatedAt")
        or live_state.get("odds_refreshed_at")
        or live_state.get("generated_at")
        or live_state.get("generatedAt")
    ) if isinstance(live_lines, dict) and isinstance(live_state, dict) else None
    if refresh_ts:
        context["generatedAt"] = refresh_ts
        context["odds_refreshed_at"] = refresh_ts
        context["oddsRefreshedAt"] = refresh_ts
    return attach_live_lens_contract(context, sport="ncaab", module="live_lens")


def build_live_lens_api_payload(selected_date: str) -> dict[str, Any]:
    context = build_live_lens_page_context(selected_date)
    payload = build_rank_api_payload(context)
    payload["header_stats"] = context.get("header_stats", [])
    payload["warning_panel"] = context.get("warning_panel")
    payload["live_state_count"] = context.get("live_state_count")
    payload["live_lines_count"] = context.get("live_lines_count")
    return payload