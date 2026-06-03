from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.mlb.cards import build_cards_page_context
from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.ladders_common import format_num
from syndicate.features.mlb.ladders_common import format_pct
from syndicate.features.mlb.ladders_common import parse_iso_date
from syndicate.features.mlb.sources import live_lens_report_path
from syndicate.features.mlb.sources import load_json_file


def _format_signed_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{format_num(number)}"


def _score_text(row: dict[str, Any]) -> str:
    matchup = row.get("matchup") if isinstance(row.get("matchup"), dict) else {}
    score = matchup.get("score") if isinstance(matchup.get("score"), dict) else {}
    away = score.get("away")
    home = score.get("home")
    if away is None or home is None:
        return "-"
    return f"{away}-{home}"


def _structured_status(row: dict[str, Any], *, fallback_date: str) -> dict[str, str]:
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    abstract = str(status.get("abstract") or status.get("abstractGameState") or "").strip()
    detailed = str(status.get("detailed") or status.get("detailedState") or abstract or row.get("startTime") or fallback_date).strip()
    lowered = f"{abstract} {detailed}".strip().lower()
    if not abstract:
        if any(token in lowered for token in ("live", "in progress", "manager challenge", "warmup")):
            abstract = "Live"
        elif any(token in lowered for token in ("final", "game over", "completed early")):
            abstract = "Final"
        elif detailed:
            abstract = detailed
        else:
            abstract = "Pregame"
    if not detailed:
        detailed = abstract or fallback_date
    return {
        "abstract": abstract,
        "detailed": detailed,
    }


def _lens_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    values = row.get("gameLens") if isinstance(row.get("gameLens"), list) else []
    return [value for value in values if isinstance(value, dict)]


def _find_lens(row: dict[str, Any], key: str) -> dict[str, Any]:
    for lens in _lens_rows(row):
        if str(lens.get("key") or "").strip() == key:
            return lens
    return {}


def _segment_items(row: dict[str, Any], *, limit: int = 4) -> list[str]:
    order = ["live", "full", "first7", "first5", "first3", "first1"]
    items: list[str] = []
    for key in order:
        lens = _find_lens(row, key)
        if not lens:
            continue
        label = str(lens.get("label") or key).strip() or key
        markets = lens.get("markets") if isinstance(lens.get("markets"), dict) else {}
        projection = lens.get("projection") if isinstance(lens.get("projection"), dict) else {}
        total_market = markets.get("total") if isinstance(markets.get("total"), dict) else {}
        spread_market = markets.get("spread") if isinstance(markets.get("spread"), dict) else {}
        moneyline_market = markets.get("moneyline") if isinstance(markets.get("moneyline"), dict) else {}
        if total_market.get("pick") and total_market.get("line") is not None:
            items.append(
                f"{label}: {str(total_market.get('pick')).title()} {format_num(total_market.get('line'))} total, edge {_format_signed_num(total_market.get('edge'))}"
            )
        elif spread_market.get("pick") and spread_market.get("homeLine") is not None:
            items.append(
                f"{label}: {str(spread_market.get('pick')).title()} {format_num(spread_market.get('homeLine'))} spread, edge {_format_signed_num(spread_market.get('edge'))}"
            )
        elif moneyline_market.get("pick"):
            items.append(
                f"{label}: {str(moneyline_market.get('pick')).title()} moneyline, edge {_format_signed_num(moneyline_market.get('edge'))}"
            )
        elif projection.get("total") is not None or projection.get("homeMargin") is not None:
            items.append(
                f"{label}: projected total {format_num(projection.get('total'))}, home margin {_format_signed_num(projection.get('homeMargin'))}"
            )
        if len(items) >= limit:
            break
    return items


def _top_live_prop_items(row: dict[str, Any], *, limit: int = 4) -> list[str]:
    values = row.get("liveProps") if isinstance(row.get("liveProps"), list) else []
    props = [value for value in values if isinstance(value, dict)]
    props.sort(key=lambda value: float(value.get("rankingScore") or value.get("estimatedWinProb") or value.get("edge") or 0.0), reverse=True)
    items: list[str] = []
    for prop in props[:limit]:
        player = str(prop.get("playerName") or "Prop").strip() or "Prop"
        selection = str(prop.get("selection") or "").strip().title()
        market = str(prop.get("marketLabel") or prop.get("market") or "Market").strip() or "Market"
        line = format_num(prop.get("line")) if prop.get("line") is not None else "-"
        odds = prop.get("odds")
        odds_text = "-"
        if odds is not None:
            try:
                number = int(float(odds))
                odds_text = f"+{number}" if number > 0 else str(number)
            except Exception:
                odds_text = str(odds)
        prob = format_pct(prop.get("modelProbOver") if str(prop.get("selection") or "").strip().lower() == "over" else prop.get("estimatedWinProb"))
        items.append(f"{player} {selection} {line} {market} ({odds_text}, {prob})".strip())
    return items


def _game_panels(row: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    matchup = row.get("matchup") if isinstance(row.get("matchup"), dict) else {}
    live_text = str(matchup.get("liveText") or row.get("startTime") or "Live state unavailable").strip() or "Live state unavailable"
    live_lens = _find_lens(row, "live") or _find_lens(row, "full")
    live_markets = live_lens.get("markets") if isinstance(live_lens.get("markets"), dict) else {}
    total_market = live_markets.get("total") if isinstance(live_markets.get("total"), dict) else {}
    summary_reason = str(total_market.get("reason") or "Segment-level reasons come directly from the live-lens report artifact.").strip()
    prop_items = _top_live_prop_items(row)
    return [
        {
            "eyebrow": "Live state",
            "title": live_text,
            "body": f"Report snapshot generated at {generated_at}. Current score is {_score_text(row)}.",
        },
        {
            "eyebrow": "Segment looks",
            "title": "Current segment board",
            "body": summary_reason,
            "items": _segment_items(row),
        },
        {
            "eyebrow": "Top live props",
            "title": "Best in-game prop edges",
            "body": "These props are the highest-ranked live looks available in the selected report snapshot.",
            "items": prop_items or ["No live props were surfaced for this game in the selected report."],
        },
    ]


def _game_metrics(row: dict[str, Any]) -> list[dict[str, str]]:
    full_lens = _find_lens(row, "full")
    live_lens = _find_lens(row, "live")
    live_props = row.get("liveProps") if isinstance(row.get("liveProps"), list) else []
    counts = [lens for lens in _lens_rows(row) if not bool(lens.get("closed"))]
    return [
        {"label": "Score", "value": _score_text(row)},
        {"label": "Full home", "value": format_pct(full_lens.get("modelHomeWinProb"))},
        {"label": "Live home", "value": format_pct(live_lens.get("modelHomeWinProb"))},
        {"label": "Open segments", "value": str(len(counts))},
        {"label": "Live props", "value": str(len(live_props))},
        {"label": "Snapshot", "value": "Yes" if row.get("snapshotAvailable") else "No"},
    ]


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in raw and raw.get(key) is not None:
            return raw.get(key)
    return None


def _market_has_signal(market: dict[str, Any]) -> bool:
    if not isinstance(market, dict):
        return False
    return any(
        market.get(key) is not None
        for key in ("pick", "line", "selectedLine", "homeLine", "edge", "homeOdds", "awayOdds", "overOdds", "underOdds", "reason")
    )


def _normalize_game_market_entry(raw: dict[str, Any], *, kind: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    if kind == "moneyline":
        out = {
            "pick": _first_present(raw, ("pick", "selection", "side")),
            "edge": _coerce_float(_first_present(raw, ("edge", "edgePct", "winEdge"))),
            "homeOdds": _first_present(raw, ("homeOdds", "home_odds", "homePrice", "home_price", "homeAmerican", "home_american")),
            "awayOdds": _first_present(raw, ("awayOdds", "away_odds", "awayPrice", "away_price", "awayAmerican", "away_american")),
            "line": _coerce_float(_first_present(raw, ("line", "price", "ml"))),
            "reason": _first_present(raw, ("reason", "summary", "note")),
        }
    elif kind == "total":
        out = {
            "pick": _first_present(raw, ("pick", "selection", "side")),
            "edge": _coerce_float(_first_present(raw, ("edge", "edgePct", "winEdge"))),
            "line": _coerce_float(_first_present(raw, ("line", "total", "marketLine"))),
            "overOdds": _first_present(raw, ("overOdds", "over_odds", "overPrice", "over_price", "overAmerican", "over_american")),
            "underOdds": _first_present(raw, ("underOdds", "under_odds", "underPrice", "under_price", "underAmerican", "under_american")),
            "reason": _first_present(raw, ("reason", "summary", "note")),
        }
    else:
        out = {
            "pick": _first_present(raw, ("pick", "selection", "side")),
            "edge": _coerce_float(_first_present(raw, ("edge", "edgePct", "winEdge"))),
            "homeLine": _coerce_float(_first_present(raw, ("homeLine", "line", "spread", "runLine", "run_line"))),
            "selectedLine": _coerce_float(_first_present(raw, ("selectedLine", "line", "spread", "runLine", "run_line"))),
            "homeOdds": _first_present(raw, ("homeOdds", "home_odds", "homePrice", "home_price", "homeAmerican", "home_american")),
            "awayOdds": _first_present(raw, ("awayOdds", "away_odds", "awayPrice", "away_price", "awayAmerican", "away_american")),
            "reason": _first_present(raw, ("reason", "summary", "note")),
        }
    return {key: value for key, value in out.items() if value is not None}


def _normalized_game_markets(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("gameMarkets") if isinstance(row.get("gameMarkets"), dict) else {}
    totals_raw = raw.get("totals") if isinstance(raw.get("totals"), dict) else {}
    moneyline_raw = raw.get("ml") if isinstance(raw.get("ml"), dict) else {}
    spread_raw = raw.get("spread") if isinstance(raw.get("spread"), dict) else {}
    return {
        "moneyline": _normalize_game_market_entry(moneyline_raw, kind="moneyline"),
        "spread": _normalize_game_market_entry(spread_raw, kind="spread"),
        "total": _normalize_game_market_entry(totals_raw, kind="total"),
    }


def _with_market_fallback_lenses(row: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fallback_markets = _normalized_game_markets(row)
    lens_rows: list[dict[str, Any]] = []
    for lens in _lens_rows(row):
        current = lens.get("markets") if isinstance(lens.get("markets"), dict) else {}
        merged = {
            "moneyline": current.get("moneyline") if isinstance(current.get("moneyline"), dict) else {},
            "spread": current.get("spread") if isinstance(current.get("spread"), dict) else {},
            "total": current.get("total") if isinstance(current.get("total"), dict) else {},
        }
        for key in ("moneyline", "spread", "total"):
            if not _market_has_signal(merged[key]) and _market_has_signal(fallback_markets.get(key) if isinstance(fallback_markets.get(key), dict) else {}):
                merged[key] = dict(fallback_markets.get(key) or {})
        out_lens = dict(lens)
        out_lens["markets"] = merged
        lens_rows.append(out_lens)
    return lens_rows, fallback_markets


def _game_from_report_row(row: dict[str, Any], *, report_date: str, generated_at: str) -> dict[str, Any]:
    matchup = row.get("matchup") if isinstance(row.get("matchup"), dict) else {}
    away = matchup.get("away") if isinstance(matchup.get("away"), dict) else {}
    home = matchup.get("home") if isinstance(matchup.get("home"), dict) else {}
    status = _structured_status(row, fallback_date=report_date)
    summary = str(matchup.get("liveText") or "Live-lens snapshot loaded from artifact.").strip() or "Live-lens snapshot loaded from artifact."
    live_props = row.get("liveProps") if isinstance(row.get("liveProps"), list) else []
    lens_rows, fallback_markets = _with_market_fallback_lenses(row)
    live_lens = _find_lens({"gameLens": lens_rows}, "live") or _find_lens({"gameLens": lens_rows}, "full")
    top_level_markets = live_lens.get("markets") if isinstance(live_lens.get("markets"), dict) else {}
    if not any(_market_has_signal(top_level_markets.get(key) if isinstance(top_level_markets.get(key), dict) else {}) for key in ("moneyline", "spread", "total")):
        top_level_markets = fallback_markets
    return {
        "archivedLiveProps": row.get("archivedLiveProps") if isinstance(row.get("archivedLiveProps"), list) else [],
        "gameLens": lens_rows,
        "gameMarkets": row.get("gameMarkets") if isinstance(row.get("gameMarkets"), dict) else {},
        "markets": top_level_markets,
        "gamePk": int(row.get("gamePk") or 0),
        "prop_groups": row.get("prop_groups") if isinstance(row.get("prop_groups"), list) else [],
        "prop_lens": row.get("prop_lens") if isinstance(row.get("prop_lens"), dict) else {},
        "market_tiles": row.get("market_tiles") if isinstance(row.get("market_tiles"), list) else [],
        "liveProps": live_props,
        "matchup": matchup,
        "predictions": row.get("predictions") if isinstance(row.get("predictions"), dict) else {},
        "props": row.get("props") if isinstance(row.get("props"), list) else [],
        "simContextAvailable": bool(row.get("simContextAvailable")),
        "snapshotAvailable": bool(row.get("snapshotAvailable")),
        "startTime": str(row.get("startTime") or report_date).strip() or report_date,
        "trackedProps": row.get("trackedProps") if isinstance(row.get("trackedProps"), list) else [],
        "probable": row.get("probable") if isinstance(row.get("probable"), dict) else {},
        "actual_box_panel": row.get("actual_box_panel") if isinstance(row.get("actual_box_panel"), dict) else {},
        "first1BetSignal": row.get("first1BetSignal") if isinstance(row.get("first1BetSignal"), dict) else {},
        "card_variant": "mlb_main",
        "away": {
            "abbr": str(away.get("abbr") or "AWY").strip() or "AWY",
            "name": str(away.get("name") or away.get("abbr") or "Away").strip() or "Away",
        },
        "home": {
            "abbr": str(home.get("abbr") or "HOM").strip() or "HOM",
            "name": str(home.get("name") or home.get("abbr") or "Home").strip() or "Home",
        },
        "status": status,
        "detail": str(row.get("startTime") or report_date).strip() or report_date,
        "summary": summary,
        "status_badge": str(status.get("abstract") or "Live lens").strip() or "Live lens",
        "hero_note": f"{len(live_props)} live props | snapshot {'yes' if row.get('snapshotAvailable') else 'no'}",
        "metrics": _game_metrics(row),
        "panels": _game_panels(row, generated_at),
        "href": f"/mlb/game/{int(row.get('gamePk') or 0)}?date={report_date}",
        "href_label": "Open game detail",
    }


def _parse_number_text(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _normalize_live_prop_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    selection = str(row.get("selection") or row.get("side") or row.get("betSide") or row.get("marketSide") or row.get("over_under") or "").strip().title()
    return {
        "playerName": str(row.get("playerName") or row.get("player_name") or row.get("batter_name") or row.get("pitcher_name") or row.get("name") or row.get("title") or "Prop").strip() or "Prop",
        "selection": selection,
        "marketLabel": str(row.get("marketLabel") or row.get("market_label") or row.get("label") or row.get("market") or "Market").strip() or "Market",
        "market": str(row.get("market") or row.get("marketGroup") or row.get("group") or "").strip(),
        "line": row.get("line") if row.get("line") is not None else row.get("threshold") if row.get("threshold") is not None else row.get("market_line"),
        "odds": row.get("odds") if row.get("odds") is not None else row.get("price") if row.get("price") is not None else row.get("americanOdds") if row.get("americanOdds") is not None else row.get("american_odds"),
        "modelProbOver": row.get("modelProbOver") if row.get("modelProbOver") is not None else row.get("model_prob_over") if row.get("model_prob_over") is not None else row.get("estimatedWinProb") if row.get("estimatedWinProb") is not None else row.get("estimated_win_prob"),
        "estimatedWinProb": row.get("estimatedWinProb") if row.get("estimatedWinProb") is not None else row.get("estimated_win_prob") if row.get("estimated_win_prob") is not None else row.get("modelProbOver") if row.get("modelProbOver") is not None else row.get("model_prob_over"),
        "rankingScore": row.get("rankingScore") if row.get("rankingScore") is not None else row.get("ranking_score") if row.get("ranking_score") is not None else row.get("edge") if row.get("edge") is not None else row.get("live_edge"),
    }


def _live_props_from_card(card: dict[str, Any]) -> list[dict[str, Any]]:
    markets = card.get("markets") if isinstance(card.get("markets"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("extraHitterProps", "extraPitcherProps", "hitterProps", "pitcherProps"):
        values = markets.get(key) if isinstance(markets.get(key), list) else []
        for value in values:
            normalized = _normalize_live_prop_row(value)
            if normalized is not None:
                rows.append(normalized)
    if not rows:
        rows.extend(_live_props_from_prop_groups(card))
    rows.sort(
        key=lambda value: float(value.get("rankingScore") or value.get("estimatedWinProb") or value.get("modelProbOver") or value.get("odds") or 0.0),
        reverse=True,
    )
    return rows


def _card_score_from_card(card: dict[str, Any]) -> dict[str, Any]:
    score = card.get("score") if isinstance(card.get("score"), dict) else {}
    if score:
        return dict(score)
    matchup = card.get("matchup") if isinstance(card.get("matchup"), dict) else {}
    score = matchup.get("score") if isinstance(matchup.get("score"), dict) else {}
    if score:
        return dict(score)
    actual_box_panel = card.get("actual_box_panel") if isinstance(card.get("actual_box_panel"), dict) else {}
    actual_box = actual_box_panel.get("actual_box") if isinstance(actual_box_panel.get("actual_box"), dict) else {}
    totals = actual_box.get("totals") if isinstance(actual_box.get("totals"), list) else []
    score_by_team: dict[str, Any] = {}
    for row in totals:
        if not isinstance(row, dict):
            continue
        team = str(row.get("team") or "").strip().lower()
        total_info = row.get("totals") if isinstance(row.get("totals"), dict) else {}
        runs = total_info.get("R") if isinstance(total_info, dict) else None
        if team in {"away", "home"} and runs is not None:
            score_by_team[team] = runs
    return {"away": score_by_team.get("away"), "home": score_by_team.get("home")} if score_by_team else {}


def _live_lens_segments_from_card(card: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    overview_rows = card.get("segment_overview_cards") if isinstance(card.get("segment_overview_cards"), list) else []
    probability_rows = card.get("probability_rows") if isinstance(card.get("probability_rows"), list) else []
    row_order = ["live", "full", "first7", "first5", "first3", "first1"]
    for index, row in enumerate(overview_rows):
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or row_order[index] if index < len(row_order) else f"segment{index + 1}").strip() or f"segment{index + 1}"
        key_text = label.lower()
        if "live" in key_text:
            key = "live"
        elif "7" in key_text:
            key = "first7"
        elif "5" in key_text:
            key = "first5"
        elif "3" in key_text:
            key = "first3"
        elif "1" in key_text:
            key = "first1"
        else:
            key = row_order[index] if index < len(row_order) else "full"
        subtitle = str(row.get("subtitle") or "").strip()
        projection_total = _parse_number_text(subtitle.split("|")[-1] if "|" in subtitle else subtitle)
        projection_margin = _parse_number_text(row.get("foot_right"))
        if projection_margin is None:
            projection_margin = _parse_number_text(row.get("best_edge"))
        if projection_margin is None:
            projection_margin = _parse_number_text(row.get("home_win"))
        reason = str(row.get("reason") or row.get("main") or subtitle).strip()
        segment = {
            "key": key,
            "label": label,
            "closed": False,
            "badge": str(row.get("badge") or "").strip(),
            "score": str(row.get("score") or "").strip(),
            "subtitle": subtitle,
            "reason": reason,
            "projection": {
                "total": projection_total,
                "homeMargin": projection_margin,
            },
            "markets": {
                "total": {
                    "pick": None if str(row.get("badge") or "").strip().lower() in {"", "no bet", "nobet"} else str(row.get("main") or row.get("badge") or "").strip() or None,
                    "line": projection_total,
                    "reason": reason,
                },
                "spread": {
                    "pick": None,
                    "homeLine": projection_margin,
                    "reason": reason,
                },
                "moneyline": {
                    "pick": None,
                    "reason": reason,
                },
            },
        }
        segments.append(segment)

    probability_keys = ["first1", "first3", "first5", "full"]
    for index, row in enumerate(probability_rows):
        if not isinstance(row, dict):
            continue
        key = probability_keys[index] if index < len(probability_keys) else f"first{index + 1}"
        summary = str(row.get("summary") or "").strip()
        if not summary:
            continue
        segments.append(
            {
                "key": key,
                "label": str(row.get("label") or key.replace("first", "First ").title()).strip() or key,
                "closed": False,
                "badge": "",
                "score": summary,
                "subtitle": summary,
                "reason": summary,
                "projection": {
                    "total": _parse_number_text(summary),
                    "homeMargin": _parse_number_text(row.get("home_pct")),
                },
                "markets": {
                    "total": {
                        "pick": None,
                        "line": _parse_number_text(summary),
                        "reason": summary,
                    },
                    "spread": {},
                    "moneyline": {},
                },
            }
        )
    return segments


_CARD_PROP_TITLE_RE = re.compile(r"^(?P<player>.+?)\s+(?P<selection>Over|Under)\s+(?P<line>[-+]?\d+(?:\.\d+)?)\s+(?P<market>.+)$", re.IGNORECASE)


def _detail_edge_from_text(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"edge\s*([-+]?\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None
def _prop_row_from_card_item(item: dict[str, Any], *, group_variant: str, section_title: str) -> dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    match = _CARD_PROP_TITLE_RE.match(title)
    if not match:
        return None
    detail = str(item.get("detail") or "").strip()
    selection = str(match.group("selection") or "").strip().lower()
    market_label = str(match.group("market") or "").strip() or section_title or "Prop"
    line = _parse_number_text(match.group("line"))
    edge = _detail_edge_from_text(detail)
    odds = _parse_number_text(detail)
    return {
        "playerName": str(match.group("player") or "Prop").strip() or "Prop",
        "selection": selection,
        "marketLabel": market_label,
        "market": section_title.lower().replace(" ", "_") if section_title else "prop",
        "line": line,
        "odds": odds,
        "modelProbOver": None,
        "estimatedWinProb": None,
        "rankingScore": edge if edge is not None else line,
        "tier": "official" if group_variant == "official" else "playable",
        "status": "live" if group_variant == "official" else "tracked",
        "source": "cards_prop_groups",
        "reason_summary": detail or title,
        "reasons": [detail] if detail else [],
    }


def _live_props_from_prop_groups(card: dict[str, Any]) -> list[dict[str, Any]]:
    prop_groups = card.get("prop_groups") if isinstance(card.get("prop_groups"), list) else []
    rows: list[dict[str, Any]] = []
    for group in prop_groups:
        if not isinstance(group, dict):
            continue
        variant = str(group.get("variant") or "").strip().lower()
        sections = group.get("sections") if isinstance(group.get("sections"), list) else []
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_title = str(section.get("title") or "").strip()
            items = section.get("items") if isinstance(section.get("items"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = _prop_row_from_card_item(item, group_variant=variant, section_title=section_title)
                if normalized is not None:
                    rows.append(normalized)
    rows.sort(
        key=lambda value: float(value.get("rankingScore") or value.get("estimatedWinProb") or value.get("modelProbOver") or value.get("odds") or 0.0),
        reverse=True,
    )
    return rows


def _merge_cards_context_into_live_row(row: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    card_props = _live_props_from_card(card)
    card_segments = _live_lens_segments_from_card(card)
    card_score = _card_score_from_card(card)
    if card_segments:
        merged["gameLens"] = card_segments
    if card_props:
        merged["liveProps"] = card_props
    if card_props:
        merged["props"] = card_props
    if card_props:
        merged["trackedProps"] = card_props
    matchup = merged.get("matchup") if isinstance(merged.get("matchup"), dict) else {}
    card_matchup = {"away": card.get("away") if isinstance(card.get("away"), dict) else {}, "home": card.get("home") if isinstance(card.get("home"), dict) else {}}
    if card_matchup["away"]:
        matchup["away"] = card_matchup["away"]
    if card_matchup["home"]:
        matchup["home"] = card_matchup["home"]
    if card_score:
        matchup["score"] = card_score
    matchup["liveText"] = str(card.get("summary") or card.get("detail") or matchup.get("liveText") or "Live-lens snapshot loaded from the MLB cards artifact.").strip() or "Live-lens snapshot loaded from the MLB cards artifact."
    merged["matchup"] = matchup
    card_status = card.get("status") if isinstance(card.get("status"), dict) else {}
    if card_status:
        merged["status"] = {
            "abstract": str(card_status.get("abstract") or card_status.get("abstractGameState") or merged.get("status", {}).get("abstract") or "Live lens").strip() or "Live lens",
            "detailed": str(card_status.get("detailed") or card_status.get("detailedState") or card.get("detail") or merged.get("status", {}).get("detailed") or "Live lens").strip() or "Live lens",
        }
    elif not merged.get("status"):
        merged["status"] = {"abstract": str(card.get("status_badge") or "Live lens").strip() or "Live lens", "detailed": str(card.get("detail") or "").strip() or str(card.get("status_badge") or "Live lens").strip() or "Live lens"}
    if card_score:
        merged["score"] = card_score
    if isinstance(card.get("predictions"), dict) and card.get("predictions"):
        merged["predictions"] = card.get("predictions")
    if isinstance(card.get("markets"), dict) and card.get("markets"):
        merged["gameMarkets"] = card.get("markets")
    if isinstance(card.get("prop_groups"), list) and card.get("prop_groups"):
        merged["prop_groups"] = card.get("prop_groups")
    if isinstance(card.get("prop_lens"), dict) and card.get("prop_lens"):
        merged["prop_lens"] = card.get("prop_lens")
    if isinstance(card.get("market_tiles"), list) and card.get("market_tiles"):
        merged["market_tiles"] = card.get("market_tiles")
    if isinstance(card.get("probable"), dict) and card.get("probable"):
        merged["probable"] = card.get("probable")
    if isinstance(card.get("actual_box_panel"), dict) and card.get("actual_box_panel"):
        merged["actual_box_panel"] = card.get("actual_box_panel")
    if isinstance(card.get("first1BetSignal"), dict) and card.get("first1BetSignal"):
        merged["first1BetSignal"] = card.get("first1BetSignal")
    if not merged.get("markets") and isinstance(card.get("markets"), dict):
        merged["markets"] = card.get("markets")
    if isinstance(card.get("archivedLiveProps"), list) and card.get("archivedLiveProps"):
        merged["archivedLiveProps"] = [dict(prop) for prop in card.get("archivedLiveProps") if isinstance(prop, dict)]
    merged["snapshotAvailable"] = bool(card.get("snapshotAvailable", merged.get("snapshotAvailable", False)))
    merged["simContextAvailable"] = bool(card.get("simContextAvailable", merged.get("simContextAvailable", False)))
    return merged


def _card_status_bucket(card: dict[str, Any]) -> str:
    status = card.get("status") if isinstance(card.get("status"), dict) else {}
    abstract = str(status.get("abstract") or status.get("abstractGameState") or "").strip().lower()
    detailed = str(status.get("detailed") or status.get("detailedState") or card.get("detail") or "").strip().lower()
    text = f"{abstract} {detailed}".strip()
    if any(token in text for token in ("live", "in progress", "warmup")):
        return "live"
    if any(token in text for token in ("final", "game over", "completed")):
        return "final"
    return "pregame"


def _card_to_live_lens_row(card: dict[str, Any], *, report_date: str) -> dict[str, Any]:
    away = card.get("away") if isinstance(card.get("away"), dict) else {}
    home = card.get("home") if isinstance(card.get("home"), dict) else {}
    score = _card_score_from_card(card)
    card_props = _live_props_from_card(card)
    return {
        "gamePk": int(card.get("gamePk") or 0),
        "status": card.get("status") if isinstance(card.get("status"), dict) else {"abstract": _card_status_bucket(card).title(), "detailed": str(card.get("detail") or report_date).strip() or report_date},
        "startTime": str(card.get("startTime") or card.get("gameDate") or card.get("detail") or report_date).strip() or report_date,
        "matchup": {
            "away": away,
            "home": home,
            "score": score if score else {"away": None, "home": None},
            "liveText": str(card.get("summary") or card.get("detail") or "Live-lens snapshot loaded from the MLB cards artifact.").strip() or "Live-lens snapshot loaded from the MLB cards artifact.",
        },
        "score": score,
        "predictions": card.get("predictions") if isinstance(card.get("predictions"), dict) else {},
        "gameMarkets": card.get("markets") if isinstance(card.get("markets"), dict) else {},
        "gameLens": card.get("gameLens") if isinstance(card.get("gameLens"), list) else [],
        "prop_groups": card.get("prop_groups") if isinstance(card.get("prop_groups"), list) else [],
        "prop_lens": card.get("prop_lens") if isinstance(card.get("prop_lens"), dict) else {},
        "market_tiles": card.get("market_tiles") if isinstance(card.get("market_tiles"), list) else [],
        "props": card_props if card_props else (card.get("props") if isinstance(card.get("props"), list) else []),
        "liveProps": card_props if card_props else (card.get("liveProps") if isinstance(card.get("liveProps"), list) else []),
        "archivedLiveProps": card.get("archivedLiveProps") if isinstance(card.get("archivedLiveProps"), list) else [],
        "trackedProps": card_props if card_props else (card.get("trackedProps") if isinstance(card.get("trackedProps"), list) else []),
        "probable": card.get("probable") if isinstance(card.get("probable"), dict) else {},
        "actual_box_panel": card.get("actual_box_panel") if isinstance(card.get("actual_box_panel"), dict) else {},
        "first1BetSignal": card.get("first1BetSignal") if isinstance(card.get("first1BetSignal"), dict) else {},
        "simContextAvailable": bool(card.get("simContextAvailable")),
        "snapshotAvailable": bool(card.get("snapshotAvailable")),
    }


def _cards_backed_live_lens_report(selected_date: str) -> dict[str, Any] | None:
    try:
        cards_context = build_cards_page_context(selected_date)
    except Exception:
        return None

    cards = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    if not cards:
        return None

    report_path = live_lens_report_path(selected_date)
    report_games = [_card_to_live_lens_row(card, report_date=selected_date) for card in cards if isinstance(card, dict)]
    live_count = 0
    final_count = 0
    pregame_count = 0
    prop_count = 0
    for card in report_games:
        bucket = _card_status_bucket(card)
        if bucket == "live":
            live_count += 1
        elif bucket == "final":
            final_count += 1
        else:
            pregame_count += 1
        prop_count += len(card.get("liveProps") or card.get("props") or card.get("trackedProps") or [])

    payload = {
        "date": str(selected_date),
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataRoot": str(report_path.parent.parent),
        "liveLensDir": str(report_path.parent),
        "optimizationRegime": None,
        "counts": {
            "games": len(report_games),
            "live": live_count,
            "final": final_count,
            "pregame": pregame_count,
            "props": prop_count,
            "archivedLiveProps": 0,
        },
        "performance": {
            "marketsRefreshed": False,
            "marketRefreshMs": 0.0,
            "totalMs": 0.0,
            "snapshotLoadMs": 0.0,
            "simContextLoadMs": 0.0,
            "propEvalMs": 0.0,
            "gameLensMs": 0.0,
            "gameCount": len(report_games),
            "liveGameCount": live_count,
            "feedFetchCount": 0,
            "cardsFallback": True,
        },
        "games": report_games,
        "source_title": str(cards_context.get("source_title") or "MLB Game Cards").strip() or "MLB Game Cards",
        "source_path": str(report_path),
        "using_sample_data": bool(cards_context.get("using_sample_data", False)),
    }

    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        return None
    return payload


def _merge_cards_context_into_report(report: dict[str, Any], selected_date: str) -> dict[str, Any]:
    try:
        cards_context = build_cards_page_context(selected_date)
    except Exception:
        return report

    cards = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    if not cards:
        return report

    cards_by_game_pk = {int(card.get("gamePk") or 0): card for card in cards if isinstance(card, dict) and int(card.get("gamePk") or 0)}
    games = report.get("games") if isinstance(report.get("games"), list) else []
    merged_games: list[dict[str, Any]] = []
    for row in games:
        if not isinstance(row, dict):
            continue
        game_pk = int(row.get("gamePk") or 0)
        card = cards_by_game_pk.get(game_pk)
        merged_games.append(_merge_cards_context_into_live_row(row, card) if isinstance(card, dict) else row)
    merged_report = dict(report)
    if merged_games:
        merged_report["games"] = merged_games
    if not isinstance(merged_report.get("counts"), dict):
        merged_report["counts"] = {}
    merged_counts = dict(merged_report.get("counts") or {})
    merged_counts["games"] = len(merged_games) if merged_games else int(merged_counts.get("games") or 0)
    merged_counts["live"] = sum(1 for game in merged_games if str((game.get("status") or {}).get("abstract") or "").strip().lower() == "live")
    merged_counts["final"] = sum(1 for game in merged_games if str((game.get("status") or {}).get("abstract") or "").strip().lower() == "final")
    merged_counts["pregame"] = sum(1 for game in merged_games if str((game.get("status") or {}).get("abstract") or "").strip().lower() not in {"live", "final"})
    merged_counts["props"] = sum(len(game.get("liveProps") or game.get("props") or game.get("trackedProps") or []) for game in merged_games)
    merged_report["counts"] = merged_counts
    merged_report["source_title"] = str(cards_context.get("source_title") or merged_report.get("source_title") or "MLB Game Cards").strip() or "MLB Game Cards"
    return merged_report


def _persist_live_lens_report(selected_date: str) -> dict[str, Any] | None:
    report_path = live_lens_report_path(selected_date)
    try:
        from vendor.mlb_bettingv2.tools.web.flask_frontend import _live_lens_payload
    except Exception:
        return None

    try:
        payload = _live_lens_payload(selected_date, persist=True, refresh_markets=True)
    except Exception:
        return None

    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list) or not payload.get("games"):
        fallback_payload = _cards_backed_live_lens_report(selected_date)
        if fallback_payload is not None:
            return fallback_payload
        if not isinstance(payload, dict):
            return None
    payload = _merge_cards_context_into_report(payload, selected_date)

    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        return None
    return payload


def build_live_lens_page_context(selected_date: str, *, season: int | None = None, persist: bool = False) -> dict[str, Any]:
    parsed_date = parse_iso_date(selected_date)
    prev_date = parsed_date.fromordinal(parsed_date.toordinal() - 1).isoformat()
    next_date = parsed_date.fromordinal(parsed_date.toordinal() + 1).isoformat()

    report_path = live_lens_report_path(selected_date)
    report = _persist_live_lens_report(selected_date) if persist else None
    if not isinstance(report, dict):
        report = load_json_file(report_path)
    if (not isinstance(report, dict)) or not isinstance(report.get("games"), list) or not report.get("games"):
        fallback_report = _cards_backed_live_lens_report(selected_date)
        if fallback_report is not None:
            report = fallback_report
    elif isinstance(report, dict):
        report = _merge_cards_context_into_report(report, selected_date)
    runtime_live_lens_dir = str(report_path.parent)
    runtime_data_root = str(report_path.parent.parent)
    odds_refreshed_at = datetime.now().astimezone().isoformat(timespec="seconds") if persist else None
    generated_at = str((report or {}).get("generatedAt") or datetime.now().astimezone().isoformat(timespec="seconds")).strip() or selected_date
    rows = (report or {}).get("games") if isinstance((report or {}).get("games"), list) else []
    games = [_game_from_report_row(row, report_date=selected_date, generated_at=generated_at) for row in rows if isinstance(row, dict)]
    if persist and games:
        persisted_games = [dict(game) for game in games if isinstance(game, dict)]
        persisted_counts = {
            "games": len(persisted_games),
            "live": sum(1 for game in persisted_games if str((game.get("status") or {}).get("abstract") or "").strip().lower() == "live"),
            "final": sum(1 for game in persisted_games if str((game.get("status") or {}).get("abstract") or "").strip().lower() == "final"),
            "pregame": sum(1 for game in persisted_games if str((game.get("status") or {}).get("abstract") or "").strip().lower() not in {"live", "final"}),
            "props": sum(len(game.get("liveProps") or game.get("props") or game.get("trackedProps") or []) for game in persisted_games),
            "archivedLiveProps": 0,
        }
        persisted_report = dict(report or {})
        persisted_report.update({
            "date": str(selected_date),
            "generatedAt": generated_at,
            "oddsRefreshedAt": odds_refreshed_at,
            "odds_refreshed_at": odds_refreshed_at,
            "dataRoot": runtime_data_root,
            "liveLensDir": runtime_live_lens_dir,
            "counts": persisted_counts,
            "games": persisted_games,
            "source_title": str((persisted_report.get("source_title") or "MLB live-lens report artifact")).strip() or "MLB live-lens report artifact",
            "source_path": str(report_path),
        })
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(persisted_report, indent=2), encoding="utf-8")
            report = persisted_report
        except Exception:
            pass
    if odds_refreshed_at:
        if not isinstance(report, dict):
            report = {}
        report["oddsRefreshedAt"] = odds_refreshed_at
        report["odds_refreshed_at"] = odds_refreshed_at
    using_sample_data = False
    scoreboard_items = [
        {
            "target_id": f"game-{game.get('gamePk')}",
            "label": f"{((game.get('away') or {}).get('abbr') or 'AWY')} @ {((game.get('home') or {}).get('abbr') or 'HOM')}",
            "status": game.get("status"),
        }
        for game in games
        if isinstance(game, dict)
    ]

    counts = (report or {}).get("counts") if isinstance((report or {}).get("counts"), dict) else {
        "archivedLiveProps": 0,
        "final": 0,
        "games": 0,
        "live": 0,
        "pregame": 0,
        "props": 0,
    }
    route_path = f"/mlb/season/{int(season)}/live-lens" if season is not None else "/mlb/live-lens"
    intro_title = f"MLB {int(season)} Live Lens" if season is not None else "MLB Live Lens"
    intro_body = (
        "This first Syndicate live-lens pass reads the committed MLB live-lens report artifact and turns each game snapshot into the shared game-card surface, instead of leaving the old MLB live monitor outside the migration path."
    )
    teaser_href = f"/mlb/season/{int(season)}/betting-card?date={selected_date}" if season is not None else f"/mlb/cards?date={selected_date}"
    teaser_cta = "Open betting card" if season is not None else "Open cards"
    teaser_body = "Use the betting-card board for the official pregame slate, then compare it against the intraday live-lens monitor for the same date." if season is not None else "Use the MLB cards board to compare the pregame slate against this live-lens snapshot."

    return apply_game_board_contract({
        "season": season,
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "module_links": build_module_links(selected_date, "Live lens"),
        "games": games,
        "scoreboard_items": scoreboard_items,
        "source_path": str(report_path),
        "using_sample_data": using_sample_data,
        "source_title": "MLB live-lens report artifact" if games else "MLB live lens unavailable",
        "generatedAt": generated_at,
        "counts": counts,
        "app": (report or {}).get("app") if isinstance((report or {}).get("app"), dict) else {},
        "dataRoot": runtime_data_root,
        "liveLensDir": runtime_live_lens_dir,
        "optimizationRegime": (report or {}).get("optimizationRegime"),
        "performance": (report or {}).get("performance") if isinstance((report or {}).get("performance"), dict) else {},
        "header_stats": [
            {"label": "Games", "value": str(counts.get("games") or len(games))},
            {"label": "Live", "value": str(counts.get("live") or 0)},
            {"label": "Final", "value": str(counts.get("final") or 0)},
            {"label": "Props", "value": str(counts.get("props") or 0)},
        ],
        "empty_state": {
            "eyebrow": "MLB live lens",
            "title": "No live-lens games were available for this date",
            "body": "The live-lens report for this date did not surface any tracked games or live props.",
            "list_items": [
                f"Requested date: {selected_date}",
                f"Report artifact: {report_path.name}",
            ],
        } if not games else None,
        "route_path": route_path,
        "intro_title": intro_title,
        "intro_body": intro_body,
        "cards_grid_class": "mlb-cards-grid",
        "cards_stylesheet": "mlb/cards.css",
        "teaser": {
            "label": "Related MLB board",
            "body": teaser_body,
            "href": teaser_href,
            "cta": teaser_cta,
        },
    }, sport="mlb", module="live_lens")


def build_live_lens_api_payload(context: dict[str, Any]) -> dict[str, Any]:
    refreshed_at = context.get("odds_refreshed_at") or context.get("oddsRefreshedAt") or context.get("generatedAt")
    return {
        "date": context.get("date"),
        "requested_date": context.get("requested_date", context.get("date")),
        "season": context.get("season"),
        "games": context.get("games") if isinstance(context.get("games"), list) else [],
        "counts": context.get("counts") if isinstance(context.get("counts"), dict) else {},
        "generatedAt": context.get("generatedAt"),
        "odds_refreshed_at": refreshed_at,
        "oddsRefreshedAt": refreshed_at,
        "dataRoot": context.get("dataRoot"),
        "liveLensDir": context.get("liveLensDir"),
        "source_path": context.get("source_path"),
        "source_title": context.get("source_title"),
        "using_sample_data": bool(context.get("using_sample_data", False)),
    }