from __future__ import annotations

import csv
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from syndicate.features.nhl.cards import build_cards_page_context
from syndicate.features.nhl.sources import build_module_links
from syndicate.features.nhl.sources import format_num
from syndicate.features.nhl.sources import format_pct
from syndicate.features.nhl.sources import format_price
from syndicate.features.nhl.sources import scoreboard_snapshot_path
from syndicate.features.nhl.sources import slate_summaries
from syndicate.features.nhl.sources import team_abbreviation
from syndicate.features.nhl.sources import team_odds_snapshot_path
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


def _lookup_keys(*, game_pk: Any = None, away: Any = None, home: Any = None) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    pk = str(game_pk or "").strip()
    if pk:
        keys.append(("gamepk", pk))

    away_name = str(away or "").strip()
    home_name = str(home or "").strip()
    if away_name and home_name:
        keys.append((away_name.lower(), home_name.lower()))
        away_abbr = team_abbreviation(away_name)
        home_abbr = team_abbreviation(home_name)
        if away_abbr and home_abbr:
            keys.append((away_abbr.lower(), home_abbr.lower()))
    return keys


def _file_timestamp(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


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
        game_pk = str(row.get("gamePk") or "").strip()
        if not away or not home:
            continue
        for key in _lookup_keys(game_pk=game_pk, away=away, home=home):
            index[key] = row
    return index


def _load_team_odds_index(selected_date: str) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], str | None]:
    path = team_odds_snapshot_path(selected_date)
    if not path.exists():
        return ({}, None)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return ({}, None)

    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        away = str(row.get("away") or "").strip()
        home = str(row.get("home") or "").strip()
        if not away or not home:
            continue
        for key in _lookup_keys(away=away, home=home):
            index.setdefault(key, []).append(row)

    refreshed_at = None
    for row in rows:
        candidate = str(row.get("book_last_update") or "").strip()
        if candidate:
            refreshed_at = max(refreshed_at or candidate, candidate)
    return (index, refreshed_at or _file_timestamp(path))


def _bookmaker_rank(value: str) -> int:
    order = {
        "draftkings": 0,
        "fanduel": 1,
        "betmgm": 2,
        "williamhill_us": 3,
        "caesars": 3,
        "betrivers": 4,
        "betonlineag": 5,
        "fanatics": 6,
        "lowvig": 7,
        "bovada": 8,
        "mybookieag": 9,
    }
    return order.get(str(value or "").strip().lower(), 99)


def _summarize_team_odds(rows: list[dict[str, Any]], *, away_team: str, home_team: str, fallback_refreshed_at: str | None = None) -> dict[str, Any] | None:
    if not rows:
        return None
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bookmaker_key = str(row.get("bookmaker_key") or row.get("bookmaker") or "unknown").strip().lower()
        grouped.setdefault(bookmaker_key, []).append(row)
    preferred_key = sorted(grouped.keys(), key=_bookmaker_rank)[0]
    preferred_rows = grouped.get(preferred_key, [])
    away_name = str(away_team or "").strip().lower()
    home_name = str(home_team or "").strip().lower()
    summary: dict[str, Any] = {
        "bookmaker": str((preferred_rows[0].get("bookmaker") if preferred_rows else "") or preferred_key).strip() or None,
        "odds_refreshed_at": fallback_refreshed_at,
    }
    for row in preferred_rows:
        market = str(row.get("market") or "").strip().lower()
        outcome_name = str(row.get("outcome_name") or "").strip().lower()
        price = row.get("outcome_price")
        point = row.get("outcome_point")
        refreshed_at = str(row.get("book_last_update") or "").strip()
        if refreshed_at:
            summary["odds_refreshed_at"] = refreshed_at
        if market == "h2h":
            if outcome_name == away_name:
                summary["away_ml"] = price
            elif outcome_name == home_name:
                summary["home_ml"] = price
        elif market == "totals":
            if outcome_name == "over":
                summary["over_odds"] = price
                summary["total"] = point
            elif outcome_name == "under":
                summary["under_odds"] = price
                summary["total"] = summary.get("total") or point
        elif market == "spreads":
            if outcome_name == away_name:
                summary["away_puck_line"] = point
                summary["away_puck_odds"] = price
            elif outcome_name == home_name:
                summary["home_puck_line"] = point
                summary["home_puck_odds"] = price
    if not any(summary.get(key) is not None for key in ("away_ml", "home_ml", "total", "away_puck_line", "home_puck_line")):
        return None
    return summary


def _source_title(cards_context: dict[str, Any], matched_scoreboard_rows: list[dict[str, Any]]) -> str:
    cards_source_title = str(cards_context.get("source_title") or "").strip()
    if cards_source_title == "NHL archived scoreboard":
        return "NHL live scoreboard fallback"
    if matched_scoreboard_rows:
        return "NHL shared cards + scoreboard lens"
    if cards_context.get("games"):
        return "NHL shared cards lens"
    return "NHL live lens unavailable"


def _warning_panel(
    *,
    requested_date: str,
    resolved_date: str,
    latest_date: str,
    cards_context: dict[str, Any],
    rank_cards: list[dict[str, Any]],
    matched_scoreboard_rows: list[dict[str, Any]],
    matched_odds_rows: int,
) -> dict[str, Any]:
    if not rank_cards:
        return {
            "eyebrow": "NHL live lens",
            "title": "No NHL slate cards were available for this date",
            "body": "The live-lens board needs either Syndicate NHL cards artifacts or a saved scoreboard snapshot for the selected date.",
            "list_items": [f"Requested date: {requested_date or resolved_date}"],
        }
    source_name = Path(str(cards_context.get("source_path") or "")).name or "unknown"
    scoreboard_states = sorted(
        {
            str(row.get("gameState") or "").strip().upper()
            for row in matched_scoreboard_rows
            if isinstance(row, dict) and str(row.get("gameState") or "").strip()
        }
    )
    return {
        "eyebrow": "Artifact-backed lens",
        "title": "NHL live lens runs on the shared Syndicate game board artifacts",
        "body": "This board reads the same NHL cards artifact lane and overlays scoreboard state when that snapshot is available, keeping the live-lens route self-contained inside Syndicate.",
        "list_items": [
            f"Primary artifact: {source_name}",
            f"Matched scoreboard rows: {len(matched_scoreboard_rows)}",
            f"Matched live odds rows: {matched_odds_rows}",
            *( [f"Observed game states: {', '.join(scoreboard_states)}"] if scoreboard_states else [f"Latest detected NHL slate: {latest_date}"] ),
        ],
    }


def _live_lens_card(game: dict[str, Any], selected_date: str, scoreboard_row: dict[str, Any] | None = None, team_odds: dict[str, Any] | None = None) -> dict[str, Any]:
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
    period_text = str((scoreboard_row or {}).get("period") or "").strip()
    clock_text = str((scoreboard_row or {}).get("clock") or "").strip()
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
    if period_text or clock_text:
        metrics.append({"label": "State", "value": " ".join(bit for bit in [f"P{period_text}" if period_text else "", clock_text] if bit).strip() or game_state})
    metrics.extend(
        [
            {"label": "Best edge", "value": best_edge_label},
            {"label": "Model total", "value": format_num(score.get("total_mean"))},
            {"label": "Margin", "value": format_num(score.get("margin_mean"))},
            {"label": "First 10 yes", "value": format_pct(first10.get("prob_yes"))},
        ]
    )
    if isinstance(team_odds, dict):
        away_ml = team_odds.get("away_ml")
        home_ml = team_odds.get("home_ml")
        total = team_odds.get("total")
        over_odds = team_odds.get("over_odds")
        under_odds = team_odds.get("under_odds")
        bookmaker = str(team_odds.get("bookmaker") or "").strip()
        if away_ml is not None or home_ml is not None:
            metrics.append(
                {
                    "label": "Live ML",
                    "value": f"{str(away.get('abbr') or away.get('name') or 'AWY').strip()} {format_price(away_ml)} | {str(home.get('abbr') or home.get('name') or 'HOM').strip()} {format_price(home_ml)}",
                }
            )
        if total is not None or over_odds is not None or under_odds is not None:
            metrics.append(
                {
                    "label": "Live total",
                    "value": f"{format_num(total)} | O {format_price(over_odds)} / U {format_price(under_odds)}",
                }
            )
        if bookmaker:
            metrics.append({"label": "Book", "value": bookmaker})

    meta_parts = []
    if game_state:
        meta_parts.append(game_state)
    if period_text:
        meta_parts.append(f"P{period_text}")
    if clock_text:
        meta_parts.append(clock_text)
    if isinstance(team_odds, dict) and str(team_odds.get("bookmaker") or "").strip():
        meta_parts.append(str(team_odds.get("bookmaker") or "").strip())

    list_items = [label for _, label in ranked_edges[:3]] or panel_titles[:3] or ["No stored lens signals for this matchup."]
    if isinstance(team_odds, dict):
        live_bits = []
        if team_odds.get("away_ml") is not None or team_odds.get("home_ml") is not None:
            live_bits.append(f"Live ML {str(away.get('abbr') or 'AWY').strip()} {format_price(team_odds.get('away_ml'))} | {str(home.get('abbr') or 'HOM').strip()} {format_price(team_odds.get('home_ml'))}")
        if team_odds.get("total") is not None:
            live_bits.append(f"Live total {format_num(team_odds.get('total'))} (O {format_price(team_odds.get('over_odds'))} / U {format_price(team_odds.get('under_odds'))})")
        list_items = live_bits[:2] + list_items

    return {
        "title": f"{str(away.get('abbr') or away.get('name') or 'AWY').strip() or 'AWY'} @ {str(home.get('abbr') or home.get('name') or 'HOM').strip() or 'HOM'}",
        "eyebrow": ("Live" if game_state in {"LIVE", "CRIT"} else "Final" if game_state == "OFF" else str(game.get("status") or "Stored slate lens")).strip() or "Stored slate lens",
        "badge": format_pct(best_edge_value) if best_edge_value is not None else "Watch",
        "meta": " | ".join(bit for bit in meta_parts if bit).strip() or (game_state or str(game.get("detail") or selected_date)).strip() or selected_date,
        "away_logo": str(away.get("logo") or game.get("away_logo") or "").strip() or None,
        "home_logo": str(home.get("logo") or game.get("home_logo") or "").strip() or None,
        "metrics": metrics,
        "summary": str(game.get("summary") or "Stored NHL slate lens row.").strip() or "Stored NHL slate lens row.",
        "list_items": list_items,
        "href": f"/nhl/game/{game_pk}?date={selected_date}" if game_pk else f"/nhl/cards?date={selected_date}",
        "href_label": "Open game detail" if game_pk else "Open cards",
        "gamePk": game_pk or None,
        "game_state": game_state or None,
        "period": period_text or None,
        "clock": clock_text or None,
        "live_odds": team_odds,
        "odds_refreshed_at": (team_odds or {}).get("odds_refreshed_at") if isinstance(team_odds, dict) else None,
        "oddsRefreshedAt": (team_odds or {}).get("odds_refreshed_at") if isinstance(team_odds, dict) else None,
    }


def build_live_lens_page_context(selected_date: str | None) -> dict[str, Any]:
    cards_context = build_cards_page_context(selected_date)
    requested_date = str(cards_context.get("requested_date") or selected_date or "").strip()
    resolved_date = str(cards_context.get("date") or requested_date).strip()
    games = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    scoreboard_index = _load_scoreboard_index(resolved_date)
    team_odds_index, odds_refreshed_at = _load_team_odds_index(resolved_date)
    matched_odds_rows = 0
    rank_cards = [
        _live_lens_card(
            game,
            resolved_date,
            scoreboard_row=next(
                (
                    scoreboard_index.get(key)
                    for key in _lookup_keys(
                        game_pk=game.get("gamePk"),
                        away=(game.get("away") or {}).get("name") or game.get("away_name"),
                        home=(game.get("home") or {}).get("name") or game.get("home_name"),
                    )
                    if scoreboard_index.get(key) is not None
                ),
                None,
            ),
            team_odds=next(
                (
                    _summarize_team_odds(
                        rows,
                        away_team=str((game.get("away") or {}).get("name") or game.get("away_name") or ""),
                        home_team=str((game.get("home") or {}).get("name") or game.get("home_name") or ""),
                        fallback_refreshed_at=odds_refreshed_at,
                    )
                    for key in _lookup_keys(
                        away=(game.get("away") or {}).get("name") or game.get("away_name"),
                        home=(game.get("home") or {}).get("name") or game.get("home_name"),
                    )
                    for rows in [team_odds_index.get(key)]
                    if rows
                ),
                None,
            ),
        )
        for game in games
        if isinstance(game, dict)
    ]
    matched_odds_rows = sum(1 for row in rank_cards if isinstance(row.get("live_odds"), dict))
    using_sample_data = False
    latest_date = (slate_summaries()[-1]["date"] if slate_summaries() else resolved_date)
    matched_scoreboard_rows = [
        row
        for game in games
        if isinstance(game, dict)
        for row in [
            scoreboard_index.get(
                next(
                    (
                        key
                        for key in _lookup_keys(
                            game_pk=game.get("gamePk"),
                            away=(game.get("away") or {}).get("name") or game.get("away_name"),
                            home=(game.get("home") or {}).get("name") or game.get("home_name"),
                        )
                        if scoreboard_index.get(key) is not None
                    ),
                    ("", ""),
                )
            )
        ]
        if isinstance(row, dict)
    ]
    live_count = sum(1 for row in matched_scoreboard_rows if str(row.get("gameState") or "").strip().upper() in {"LIVE", "CRIT"})
    final_count = sum(1 for row in matched_scoreboard_rows if str(row.get("gameState") or "").strip().upper() == "OFF")
    warning_panel = _warning_panel(
        requested_date=requested_date,
        resolved_date=resolved_date,
        latest_date=latest_date,
        cards_context=cards_context,
        rank_cards=rank_cards,
        matched_scoreboard_rows=matched_scoreboard_rows,
        matched_odds_rows=matched_odds_rows,
    )
    source_title = _source_title(cards_context, matched_scoreboard_rows)

    context = build_rank_page_context(
        selected_date=requested_date,
        route_path="/nhl/live-lens",
        intro_title="NHL Live Lens",
        intro_body="The NHL live lens reuses the shared ranked-board shell on top of the Syndicate cards artifact lane, adding scoreboard state when that snapshot is available for the selected date.",
        aria_label="NHL live lens board",
        source_path=str(cards_context.get("source_path") or "NHL processed predictions"),
        source_title=source_title,
        rank_cards=rank_cards,
        using_sample_data=using_sample_data,
        header_stats=[
            {"label": "Cards", "value": str(len(rank_cards))},
            {"label": "Games", "value": str(len(games))},
            {"label": "Live", "value": str(live_count)},
            {"label": "Final", "value": str(final_count)},
            {"label": "Source", "value": Path(str(cards_context.get('source_path') or '')).name if cards_context.get("source_path") else "Fallback"},
        ],
        module_links=build_module_links(requested_date, "Live Lens"),
        warning_panel=warning_panel,
        source_date_display=resolved_date,
        prev_href=f"/nhl/live-lens?date={cards_context.get('prev_date') or requested_date}",
        next_href=f"/nhl/live-lens?date={cards_context.get('next_date') or requested_date}",
    )
    context["available_dates"] = [item["date"] for item in slate_summaries()]
    context["odds_refreshed_at"] = odds_refreshed_at
    context["oddsRefreshedAt"] = odds_refreshed_at
    return context


def build_live_lens_api_payload(selected_date: str | None) -> dict[str, Any]:
    context = build_live_lens_page_context(selected_date)
    payload = build_rank_api_payload(context)
    payload["available_dates"] = context.get("available_dates")
    return payload