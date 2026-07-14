from __future__ import annotations

import ast
import csv
from pathlib import Path
from typing import Any

from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.top_props_board import build_top_props_page_context
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


def build_props_page_context(selected_date: str) -> dict[str, Any]:
    source_path = str(_resolve_top_by_game_source_path(selected_date))
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
        build_cards=_cards_from_summary,
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
