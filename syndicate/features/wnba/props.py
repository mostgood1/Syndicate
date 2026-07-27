from __future__ import annotations

import ast
import csv
from pathlib import Path
from typing import Any

from syndicate.features.shared.basketball_market_board import basketball_game_state
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.top_props_board import build_top_props_page_context
from syndicate.features.wnba.cards import build_cards_page_context
from syndicate.features.wnba.cards import build_live_player_lens_payload
from syndicate.features.wnba.sources import build_module_links
from syndicate.features.wnba.sources import available_dates
from syndicate.features.wnba.sources import central_today_iso
from syndicate.features.wnba.sources import format_moneyline
from syndicate.features.wnba.sources import format_num
from syndicate.features.wnba.sources import format_pct
from syndicate.features.wnba.sources import market_label
from syndicate.features.wnba.sources import load_json
from syndicate.features.wnba.sources import processed_root


def _cards_from_summary(summary: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    rows = summary.get("data") if isinstance(summary.get("data"), list) else []
    cards: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
        player = str(row.get("player") or "WNBA prop").strip() or "WNBA prop"
        side = str(top_play.get("side") or "").strip().title()
        line = format_num(top_play.get("line"))
        market = market_label(top_play.get("market"))
        title = f"{player} {side} {line} {market}".strip()
        cards.append(
            {
                "title": title,
                "eyebrow": str(row.get("tier") or row.get("team") or "WNBA props").strip() or "WNBA props",
                "badge": f"{format_num(top_play.get('ev_pct'))}% EV",
                "meta": f"{str(row.get('team_tricode') or row.get('team') or '-').strip()} vs {str(row.get('opponent') or '-').strip()}",
                "metrics": [
                    {"label": "EV", "value": f"{format_num(top_play.get('ev_pct'))}%"},
                    {"label": "Edge", "value": format_pct(top_play.get("edge"))},
                    {"label": "Price", "value": format_moneyline(top_play.get("price"))},
                    {"label": "Book", "value": str(top_play.get("book") or "-").strip() or "-"},
                ],
                "summary": str(top_play.get("basketball_summary") or row.get("player") or "No summary available.").strip(),
                "list_items": [
                    str(item).strip()
                    for item in (top_play.get("basketball_reasons") or row.get("top_play_reasons") or [])
                    if str(item).strip()
                ][:4],
            }
        )
        if len(cards) >= limit:
            return cards
    return cards


def _summary_from_props_recommendations_rows(raw_rows: list[dict[str, Any]], *, selected_date: str) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        top_play_text = str(raw.get("top_play") or "").strip()
        if not top_play_text:
            continue
        try:
            top_play = ast.literal_eval(top_play_text)
        except Exception:
            continue
        if not isinstance(top_play, dict):
            continue
        top_play_row = dict(top_play)
        reasons_raw = raw.get("top_play_reasons")
        if isinstance(reasons_raw, str):
            try:
                parsed_reasons = ast.literal_eval(reasons_raw)
                reasons_list = [str(item).strip() for item in parsed_reasons if str(item).strip()] if isinstance(parsed_reasons, list) else []
            except Exception:
                reasons_list = []
        elif isinstance(reasons_raw, list):
            reasons_list = [str(item).strip() for item in reasons_raw if str(item).strip()]
        else:
            reasons_list = []
        rows.append(
            {
                "player": str(raw.get("player") or "WNBA prop").strip() or "WNBA prop",
                "team": str(raw.get("team") or "Team").strip() or "Team",
                "team_tricode": str(raw.get("team_tricode") or raw.get("team") or "").strip().upper() or None,
                "opponent": str(raw.get("opponent") or "-").strip() or "-",
                "tier": raw.get("tier"),
                "top_play": top_play_row,
                "top_play_explain": str(raw.get("top_play_explain") or "").strip(),
                "top_play_baseline": str(raw.get("top_play_baseline") or "").strip(),
                "top_play_reasons": reasons_list,
                "top_play_consensus": raw.get("top_play_consensus"),
                "top_play_line_adv": raw.get("top_play_line_adv"),
            }
        )
    if not rows:
        return None
    return {
        "ok": True,
        "date": selected_date,
        "requested_date": selected_date,
        "data": rows,
    }


def _load_props_recommendations_summary(path):
    try:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8", newline="") as handle:
                raw_rows = list(csv.DictReader(handle))
            selected_date = path.stem.rsplit("_", 1)[-1]
            return _summary_from_props_recommendations_rows(raw_rows, selected_date=selected_date)
    except Exception:
        return None
    return load_json(path)


def _resolve_top_by_game_source_path(selected_date: str) -> Path:
    file_name = f"props_recommendations_top_by_game_{selected_date}.json"
    # processed_root() unconditionally prefers a "source_artifacts" candidate
    # root, whether or not that location actually has anything written to it.
    # The refresh pipeline writes this file straight into the WNBA source
    # root's data/processed dir, so if that's not where processed_root()
    # landed, search every candidate root and use whichever one actually has
    # the file rather than silently reporting the props board as empty.
    default_path = processed_root() / file_name
    if default_path.exists():
        return default_path
    for root in preferred_artifact_roots(__file__, env_var="SYNDICATE_WNBA_SOURCE_ROOT", local_dir_name="wnba_source"):
        candidate = root / "data" / "processed" / file_name
        if candidate.exists():
            return candidate
    return default_path


def _live_team_context(selected_date: str) -> dict[str, dict[str, Any]]:
    """Team abbr (upper) -> {event_id, opponent_tri} for every WNBA game
    currently live on this date. Empty for a pregame-only or historical
    slate -- callers should treat that as "no live overlay to apply", not
    an error.
    """
    try:
        cards_context = build_cards_page_context(selected_date, allow_stored_date_fallback=False)
    except Exception:
        return {}
    games = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    live_teams: dict[str, dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, dict) or basketball_game_state(game) != "live":
            continue
        event_id = str(game.get("event_id") or "").strip()
        if not event_id:
            continue
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_tri = str(away.get("abbr") or game.get("away_tri") or "").strip().upper()
        home_tri = str(home.get("abbr") or game.get("home_tri") or "").strip().upper()
        if away_tri:
            live_teams[away_tri] = {"event_id": event_id, "opponent_tri": home_tri}
        if home_tri:
            live_teams[home_tri] = {"event_id": event_id, "opponent_tri": away_tri}
    return live_teams


def _live_prop_cards(selected_date: str, live_teams: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Build prop cards from live-modeled projections vs live lines for
    games currently in progress, mirroring _cards_from_summary's card shape
    but sourced from build_live_player_lens_payload's per-game rows instead
    of the pregame recommendation slate. Only rows carrying a real live
    edge (ev_side present -- the model and the live line actually
    disagree) are surfaced, matching this board's "opportunities" framing
    rather than listing every tracked player regardless of edge.
    """
    event_ids = sorted({info["event_id"] for info in live_teams.values()})
    if not event_ids:
        return []
    try:
        payload = build_live_player_lens_payload(selected_date, event_ids, ttl=20)
    except Exception:
        return []
    games = payload.get("games") if isinstance(payload.get("games"), list) else []
    cards: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        rows = game.get("rows") if isinstance(game.get("rows"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ev_side = str(row.get("ev_side") or "").strip().upper()
            if ev_side not in ("OVER", "UNDER"):
                continue
            player = str(row.get("player") or "WNBA prop").strip() or "WNBA prop"
            team_tri = str(row.get("team_tri") or "").strip().upper()
            opponent_tri = str(live_teams.get(team_tri, {}).get("opponent_tri") or "-")
            stat = market_label(row.get("stat"))
            line = format_num(row.get("line_live"))
            live_projection = row.get("live_projection")
            live_edge = row.get("live_edge")
            price = row.get("price_over") if ev_side == "OVER" else row.get("price_under")
            cards.append(
                {
                    "title": f"{player} {ev_side.title()} {line} {stat}".strip(),
                    "eyebrow": "Live",
                    "badge": f"Live edge {format_num(live_edge)}" if live_edge is not None else "Live",
                    "meta": f"{team_tri or '-'} vs {opponent_tri}",
                    "metrics": [
                        {"label": "Live proj", "value": format_num(live_projection)},
                        {"label": "Line", "value": line},
                        {"label": "Live edge", "value": format_num(live_edge)},
                        {"label": "Price", "value": format_moneyline(price)},
                    ],
                    "summary": f"Live-modeled {stat.lower()} projection for {player} vs the current live line.",
                    "list_items": [
                        item
                        for item in [
                            f"Actual so far: {format_num(row.get('actual'))}" if row.get("actual") is not None else None,
                            f"Book: {str(row.get('book') or '').strip()}" if row.get("book") else None,
                        ]
                        if item
                    ],
                }
            )
            if len(cards) >= limit:
                return cards
    return cards


def build_props_page_context(selected_date: str) -> dict[str, Any]:
    source_path = str(_resolve_top_by_game_source_path(selected_date))
    live_teams = _live_team_context(selected_date) if selected_date == central_today_iso() else {}

    def _build_cards(summary: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        if not live_teams:
            return _cards_from_summary(summary, limit)
        # Live games get their pregame rows dropped in favor of live-modeled
        # cards below, so the same game never shows a stale pregame pick
        # next to a fresh live one.
        rows = summary.get("data") if isinstance(summary.get("data"), list) else []
        pregame_rows = [
            row
            for row in rows
            if not isinstance(row, dict)
            or str(row.get("team_tricode") or "").strip().upper() not in live_teams
        ]
        pregame_cards = _cards_from_summary({**summary, "data": pregame_rows}, limit)
        live_cards = _live_prop_cards(selected_date, live_teams, limit)
        return (live_cards + pregame_cards)[:limit]

    return build_top_props_page_context(
        selected_date=selected_date,
        route_path="/wnba/props",
        intro_title="WNBA Props",
        intro_body="This standalone props surface keeps the top WNBA player props workflow on one stored slate.",
        aria_label="WNBA props board",
        source_path=source_path,
        source_title="WNBA top props by game",
        active_label="Props",
        load_summary=_load_props_recommendations_summary,
        build_cards=_build_cards,
        build_module_links=build_module_links,
        available_dates=available_dates(),
        allow_previous_date_fallback=selected_date != central_today_iso(),
        empty_state={
            "eyebrow": "WNBA props",
            "title": "No stored WNBA props were available for this date",
            "body": "The props board only renders saved WNBA top-by-game props artifacts, and none were available for the requested date.",
            "list_items": ["Choose another stored WNBA date from the calendar control."],
        },
    )
