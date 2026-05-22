from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from syndicate.features.nhl.cards import build_cards_page_context
from syndicate.features.nhl.sources import build_module_links
from syndicate.features.nhl.sources import format_num
from syndicate.features.nhl.sources import format_pct
from syndicate.features.nhl.sources import scoreboard_snapshot_path
from syndicate.features.nhl.sources import slate_summaries
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _best_edges(game: dict[str, Any]) -> list[tuple[float, str]]:
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
    first10 = sim.get("first10") if isinstance(sim.get("first10"), dict) else {}
    candidates = [
        (_safe_float(betting.get("home_ml_ev")), f"Home ML {format_pct(betting.get('home_ml_ev'))}"),
        (_safe_float(betting.get("away_ml_ev")), f"Away ML {format_pct(betting.get('away_ml_ev'))}"),
        (_safe_float(betting.get("over_ev")), f"Over {format_pct(betting.get('over_ev'))}"),
        (_safe_float(betting.get("under_ev")), f"Under {format_pct(betting.get('under_ev'))}"),
        (_safe_float(betting.get("home_puck_line_ev")), f"Home -1.5 {format_pct(betting.get('home_puck_line_ev'))}"),
        (_safe_float(betting.get("away_puck_line_ev")), f"Away +1.5 {format_pct(betting.get('away_puck_line_ev'))}"),
        (_safe_float(first10.get("ev_yes")), f"First 10 yes {format_pct(first10.get('ev_yes'))}"),
        (_safe_float(first10.get("ev_no")), f"First 10 no {format_pct(first10.get('ev_no'))}"),
    ]
    return [(value, label) for value, label in candidates if value is not None]


def _load_scoreboard_index(selected_date: str) -> dict[tuple[str, str], dict[str, Any]]:
    path = scoreboard_snapshot_path(selected_date)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return {}
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        away = str(row.get("away") or "").strip()
        home = str(row.get("home") or "").strip()
        if not away or not home:
            continue
        index[(away, home)] = row
    return index


def _live_lens_card(game: dict[str, Any], selected_date: str, scoreboard_row: dict[str, Any] | None = None) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
    score = sim.get("score") if isinstance(sim.get("score"), dict) else {}
    first10 = sim.get("first10") if isinstance(sim.get("first10"), dict) else {}
    ranked_edges = sorted(_best_edges(game), key=lambda item: item[0], reverse=True)
    best_edge_value, best_edge_label = ranked_edges[0] if ranked_edges else (None, "No edge stored")
    away_goals = _safe_float((scoreboard_row or {}).get("away_goals"))
    home_goals = _safe_float((scoreboard_row or {}).get("home_goals"))
    game_state = str((scoreboard_row or {}).get("gameState") or "").strip().upper()
    score_text = None
    if away_goals is not None and home_goals is not None:
        score_text = f"{int(round(away_goals))}-{int(round(home_goals))}"
    panel_titles = [
        str(panel.get("title") or "").strip()
        for panel in (game.get("panels") or [])
        if isinstance(panel, dict) and str(panel.get("title") or "").strip()
    ]
    game_pk = str(game.get("gamePk") or "").strip()
    metrics = []
    if score_text:
        metrics.append({"label": "Score", "value": score_text})
    metrics.extend(
        [
            {"label": "Best edge", "value": best_edge_label},
            {"label": "Model total", "value": format_num(score.get("total_mean"))},
            {"label": "Margin", "value": format_num(score.get("margin_mean"))},
            {"label": "First 10 yes", "value": format_pct(first10.get("prob_yes"))},
        ]
    )
    return {
        "title": f"{str(away.get('abbr') or away.get('name') or 'AWY').strip() or 'AWY'} @ {str(home.get('abbr') or home.get('name') or 'HOM').strip() or 'HOM'}",
        "eyebrow": ("Live" if game_state in {"LIVE", "CRIT"} else "Final" if game_state == "OFF" else str(game.get("status") or "Stored slate lens")).strip() or "Stored slate lens",
        "badge": format_pct(best_edge_value) if best_edge_value is not None else "Watch",
        "meta": (game_state or str(game.get("detail") or selected_date)).strip() or selected_date,
        "metrics": metrics,
        "summary": str(game.get("summary") or "Stored NHL slate lens row.").strip() or "Stored NHL slate lens row.",
        "list_items": [label for _, label in ranked_edges[:3]] or panel_titles[:3] or ["No stored lens signals for this matchup."],
        "href": f"/nhl/game/{game_pk}?date={selected_date}" if game_pk else f"/nhl/cards?date={selected_date}",
        "href_label": "Open game detail" if game_pk else "Open cards",
    }


def build_live_lens_page_context(selected_date: str | None) -> dict[str, Any]:
    cards_context = build_cards_page_context(selected_date)
    requested_date = str(cards_context.get("requested_date") or selected_date or "").strip()
    resolved_date = str(cards_context.get("date") or requested_date).strip()
    games = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    scoreboard_index = _load_scoreboard_index(resolved_date)
    rank_cards = [
        _live_lens_card(
            game,
            resolved_date,
            scoreboard_row=scoreboard_index.get(
                (
                    str((game.get("away") or {}).get("name") or game.get("away_name") or "").strip(),
                    str((game.get("home") or {}).get("name") or game.get("home_name") or "").strip(),
                )
            ),
        )
        for game in games
        if isinstance(game, dict)
    ]
    using_sample_data = False
    latest_date = (slate_summaries()[-1]["date"] if slate_summaries() else resolved_date)
    warning_panel = {
        "eyebrow": "Stored slate lens",
        "title": "NHL live lens currently projects the active slate from stored predictions",
        "body": "This first NHL live-lens surface upgrades the old stub into a real ranked board by turning the persisted processed predictions slate into a compact lens view.",
        "list_items": [
            "The route stays artifact-backed until a stronger live source workflow is promoted into Syndicate.",
            f"Latest detected stored slate: {latest_date}",
        ],
    }
    if not rank_cards:
        warning_panel = {
            "eyebrow": "Stored slate lens",
            "title": "No NHL slate cards were available for this date",
            "body": "The live-lens board can only project stored slate rows that already exist in the NHL processed predictions artifact.",
            "list_items": [f"Requested date: {cards_context.get('requested_date') or resolved_date}"],
        }

    context = build_rank_page_context(
        selected_date=requested_date,
        route_path="/nhl/live-lens",
        intro_title="NHL Live Lens",
        intro_body="This first NHL live-lens surface reuses the shared ranked-board shell and the stored processed predictions slate, so the module gains a real live-lens family before a deeper source-side monitor is migrated.",
        aria_label="NHL live lens board",
        source_path=str(cards_context.get("source_path") or "NHL processed predictions"),
        source_title="NHL processed predictions lens" if rank_cards else "NHL live lens unavailable",
        rank_cards=rank_cards,
        using_sample_data=using_sample_data,
        header_stats=[
            {"label": "Cards", "value": str(len(rank_cards))},
            {"label": "Games", "value": str(len(games))},
            {"label": "Source", "value": Path(str(cards_context.get('source_path') or '')).name if cards_context.get("source_path") else "Fallback"},
        ],
        module_links=build_module_links(requested_date, "Live Lens"),
        warning_panel=warning_panel,
        source_date_display=resolved_date,
        prev_href=f"/nhl/live-lens?date={cards_context.get('prev_date') or requested_date}",
        next_href=f"/nhl/live-lens?date={cards_context.get('next_date') or requested_date}",
    )
    context["available_dates"] = [item["date"] for item in slate_summaries()]
    return context


def build_live_lens_api_payload(selected_date: str | None) -> dict[str, Any]:
    context = build_live_lens_page_context(selected_date)
    payload = build_rank_api_payload(context)
    payload["available_dates"] = context.get("available_dates")
    return payload