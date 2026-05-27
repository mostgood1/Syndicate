from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from datetime import datetime
from datetime import timezone
import re
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import json

from flask import Blueprint, current_app, jsonify, render_template, request

from syndicate.features.mlb.ladders_common import build_module_links as build_mlb_module_links
from syndicate.features.mlb.sources import available_daily_summary_dates
from syndicate.features.mlb.sources import load_json_or_gz_file
from syndicate.features.mlb.sources import raw_feed_live_path
from syndicate.features.nba.sources import available_dates as nba_available_dates
from syndicate.features.nba.sources import build_module_links as build_nba_module_links
from syndicate.features.nhl.sources import build_module_links as build_nhl_module_links
from syndicate.features.nhl.sources import scoreboard_snapshot_path
from syndicate.features.nhl.sources import slate_summaries as nhl_slate_summaries
from syndicate.features.wnba.sources import available_dates as wnba_available_dates
from syndicate.features.wnba.sources import build_module_links as build_wnba_module_links
from syndicate.features.nfl.sources import build_module_links as build_nfl_module_links
from syndicate.features.nfl.sources import default_week as nfl_default_week
from syndicate.features.nfl.sources import latest_season as nfl_latest_season
from syndicate.features.nfl.sources import tracked_week as nfl_tracked_week
from syndicate.features.nfl.sources import week_summaries as nfl_week_summaries
from syndicate.features.ncaaf.sources import build_module_links as build_ncaaf_module_links
from syndicate.features.ncaaf.sources import default_season as ncaaf_default_season
from syndicate.features.ncaaf.sources import default_week as ncaaf_default_week
from syndicate.features.ncaaf.sources import week_summaries as ncaaf_week_summaries
from syndicate.features.ncaab.sources import available_dates as ncaab_available_dates
from syndicate.features.ncaab.sources import build_module_links as build_ncaab_module_links
from syndicate.features.ncaab.sources import latest_date as ncaab_latest_date
from syndicate.features.ncaab.sources import season_for_date as ncaab_season_for_date
from syndicate.features.shared.timezone import central_datetime_from_epoch
from syndicate.features.shared.timezone import CENTRAL_TIMEZONE
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.timezone import central_year


home_bp = Blueprint("syndicate_home", __name__)

_HOME_OVERVIEW_TTL_SEC = 10.0
_HOME_OVERVIEW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_HOME_PAYLOAD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _sport_matchup(game: dict[str, Any]) -> str:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    away_label = str(away.get("abbr") or game.get("away_tri") or game.get("away_name") or "Away").strip()
    home_label = str(home.get("abbr") or game.get("home_tri") or game.get("home_name") or "Home").strip()
    return f"{away_label} @ {home_label}"


def _score_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except Exception:
        return text
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _numeric_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _extract_numeric_tail(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*$", text)
    if not match:
        match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _metric_or_tile_value(game: dict[str, Any], labels: list[str]) -> float | None:
    wanted = {label.strip().lower() for label in labels if label.strip()}
    market_tiles = game.get("market_tiles") if isinstance(game.get("market_tiles"), list) else []
    for tile in market_tiles:
        if not isinstance(tile, dict):
            continue
        label = str(tile.get("label") or "").strip().lower()
        if label in wanted:
            value = _numeric_value(tile.get("value"))
            if value is not None:
                return value
            value = _extract_numeric_tail(tile.get("title"))
            if value is not None:
                return value
    metrics = game.get("metrics") if isinstance(game.get("metrics"), list) else []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or "").strip().lower()
        if label in wanted:
            value = _numeric_value(metric.get("value"))
            if value is not None:
                return value
            value = _extract_numeric_tail(metric.get("value"))
            if value is not None:
                return value
    return None


def _is_liveish(status_badge: Any, status_line: Any) -> bool:
    text = f"{status_badge or ''} {status_line or ''}".strip().lower()
    return any(token in text for token in ("live", "in progress", "top ", "bot ", "q1", "q2", "q3", "q4", "ot", "halftime"))


def _central_scheduled_datetime(game: dict[str, Any]) -> datetime | None:
    candidates = [
        game.get("scheduled_start_utc"),
        game.get("start_time_utc"),
        game.get("gameDate"),
        game.get("game_date"),
        game.get("scheduled"),
        game.get("scheduled_start"),
        game.get("commence_time"),
        game.get("detail"),
    ]
    for value in candidates:
        text = str(value or "").strip()
        if not text or "T" not in text:
            continue
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except Exception:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(CENTRAL_TIMEZONE)
    return None


def _scheduled_status_line(game: dict[str, Any], fallback: str) -> str:
    scheduled_dt = _central_scheduled_datetime(game)
    if scheduled_dt is not None:
        time_text = scheduled_dt.strftime("%I:%M %p").lstrip("0")
        if scheduled_dt.date().isoformat() == central_today_iso():
            return f"{time_text} CT"
        return f"{scheduled_dt.strftime('%b')} {scheduled_dt.day} {time_text} CT"
    fallback_text = str(fallback or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fallback_text):
        if fallback_text == central_today_iso():
            return "Scheduled today"
        return f"Scheduled {fallback_text}"
    if fallback_text.upper() in {"FUT", "PRE"}:
        return "Scheduled"
    return fallback_text or "Board update pending"


def _scoreboard_state(game: dict[str, Any]) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    score = status.get("score") if isinstance(status.get("score"), dict) else {}

    away_label = str(away.get("abbr") or game.get("away_tri") or game.get("away_name") or "Away").strip() or "Away"
    home_label = str(home.get("abbr") or game.get("home_tri") or game.get("home_name") or "Home").strip() or "Home"

    away_score = (
        _score_value(away.get("score"))
        or _score_value(status.get("away_score"))
        or _score_value(score.get("away"))
        or _score_value(live_state.get("away_pts"))
    )
    home_score = (
        _score_value(home.get("score"))
        or _score_value(status.get("home_score"))
        or _score_value(score.get("home"))
        or _score_value(live_state.get("home_pts"))
    )

    is_live = bool(status.get("is_live") or status.get("in_progress") or live_state.get("in_progress"))
    is_final = bool(status.get("is_final") or status.get("final") or live_state.get("final"))
    suppress_zero_zero = not is_live and not is_final and away_score == "0" and home_score == "0"
    has_scores = bool(away_score and home_score and not suppress_zero_zero)

    raw_status_badge = str(
        status.get("abstract")
        or status.get("status")
        or game.get("status_badge")
        or ("Live" if is_live else "Final" if is_final else "Scheduled")
    ).strip()
    raw_status_line = str(
        status.get("detailed")
        or live_state.get("status")
        or game.get("detail")
        or game.get("summary")
        or "Board update pending"
    ).strip()
    status_badge = raw_status_badge
    status_line = raw_status_line
    if not is_live and not is_final:
        if raw_status_badge.lower() in {"processed artifact", "tracked", "stored slate lens"}:
            status_badge = "Scheduled"
        status_line = _scheduled_status_line(game, raw_status_line)
    return {
        "away_label": away_label,
        "home_label": home_label,
        "away_score": away_score if has_scores else None,
        "home_score": home_score if has_scores else None,
        "has_scores": has_scores,
        "score_kind": "Live score" if is_live else "Final score" if is_final else None,
        "status_badge": status_badge or "Scheduled",
        "status_line": status_line or "Board update pending",
    }


def _team_logo(game: dict[str, Any], side: str) -> str | None:
    container = game.get(side) if isinstance(game.get(side), dict) else {}
    matchup = game.get("matchup") if isinstance(game.get("matchup"), dict) else {}
    matchup_side = matchup.get(side) if isinstance(matchup.get(side), dict) else {}
    for value in [
        game.get(f"{side}_logo"),
        container.get("logo"),
        container.get("logo_url"),
        container.get("badge"),
        matchup_side.get("logo"),
        matchup_side.get("logo_url"),
        matchup_side.get("badge"),
    ]:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _pct_text(value: Any) -> str | None:
    number = _numeric_value(value)
    if number is None:
        return None
    if abs(number) <= 1.0:
        number *= 100.0
    return f"{number:.1f}%"


def _game_market_recommendation_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    rows = game.get("game_market_recommendations") if isinstance(game.get("game_market_recommendations"), list) else []
    values: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pick = _safe_text(row.get("display_pick") or row.get("selection") or row.get("market_label"), "Market")
        parts = [pick]
        ev_pct = _pct_text(row.get("ev_pct"))
        p_win = _pct_text(row.get("p_win"))
        if ev_pct:
            parts.append(f"EV {ev_pct}")
        if p_win:
            parts.append(f"Win {p_win}")
        values.append(" | ".join(parts))
        if len(values) >= limit:
            break
    return values


def _betting_signal_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    values: list[str] = []
    for label, field_names in [
        ("ML", ["ml_pick", "moneyline_pick", "moneyline"]),
        ("Spread", ["spread_pick", "spread"]),
        ("Total", ["total_pick", "total"]),
    ]:
        text = ""
        for field_name in field_names:
            text = str(betting.get(field_name) or "").strip()
            if text:
                break
        if not text:
            continue
        values.append(f"{label}: {text}")
        if len(values) >= limit:
            break
    return values


def _market_chip_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    chips: list[str] = []
    game_recs = game.get("game_market_recommendations") if isinstance(game.get("game_market_recommendations"), list) else []
    prop_recs = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), list) else []
    if game_recs:
        chips.append(f"{len(game_recs)} game looks")
    if prop_recs:
        chips.append(f"{len(prop_recs)} prop looks")
    live_status = str(game.get("live_status") or "").strip()
    if live_status:
        chips.append(live_status)
    return chips[:limit]


def _summary_text(game: dict[str, Any]) -> str:
    for value in [game.get("writeup"), game.get("summary")]:
        text = str(value or "").strip()
        if text:
            return text
    return "No market summary available yet."


def _edge_text(value: Any) -> str | None:
    number = _numeric_value(value)
    if number is None:
        return None
    if abs(number) <= 1.0:
        return _pct_text(number)
    text = _score_value(number)
    if text is None:
        return None
    return text if str(text).startswith("-") else f"+{text}"


def _mlb_live_game_signal_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    values: list[str] = []
    lenses = game.get("gameLens") if isinstance(game.get("gameLens"), list) else []
    for lens in lenses:
        if not isinstance(lens, dict) or bool(lens.get("closed")):
            continue
        lens_label = _safe_text(lens.get("label"), "Live")
        markets = lens.get("markets") if isinstance(lens.get("markets"), dict) else {}
        for market_key, market_label in [("moneyline", "ML"), ("spread", "SPR"), ("total", "TOT")]:
            market = markets.get(market_key) if isinstance(markets.get(market_key), dict) else {}
            pick = str(market.get("pick") or "").strip()
            if not pick:
                continue
            edge = _edge_text(market.get("edge"))
            line = _score_value(market.get("line") if market_key == "total" else market.get("homeLine"))
            parts = [f"{lens_label} {market_label}", pick.upper()]
            if line and market_key in {"spread", "total"}:
                parts.append(f"Line {line}")
            if edge:
                parts.append(f"Edge {edge}")
            values.append(" | ".join(parts))
            if len(values) >= limit:
                return values
    return values


def _sort_compact_game_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _is_completed(item: dict[str, Any]) -> bool:
        text = f"{item.get('status_badge') or ''} {item.get('detail') or ''} {item.get('score_kind') or ''}".lower()
        return any(token in text for token in ("final", "game over", "completed", "off"))

    ordered = sorted(enumerate(items), key=lambda pair: (_is_completed(pair[1]), pair[0]))
    return [item for _, item in ordered]


def _prop_metric_text(value: Any) -> str | None:
    text = _score_value(value)
    if text is not None:
        return text
    raw = str(value or "").strip()
    return raw or None


def _metric_value(metrics: list[dict[str, Any]], labels: list[str]) -> str | None:
    wanted = [label.strip().lower() for label in labels if label.strip()]
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or "").strip().lower()
        if not label:
            continue
        if any(label == item or item in label for item in wanted):
            value = _prop_metric_text(metric.get("value"))
            if value:
                return value
    return None


def _pct_number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", text)
    if match:
        try:
            return float(match.group(1))
        except Exception:
            return None
    numeric = _numeric_value(value)
    if numeric is None:
        return None
    if abs(numeric) <= 1.0:
        numeric *= 100.0
    return float(numeric)


def _format_home_timestamp(epoch: float | None) -> str:
    try:
        if not epoch:
            return "-"
        return central_datetime_from_epoch(float(epoch)).strftime("%I:%M %p").lstrip("0")
    except Exception:
        return "-"


def _first_present_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _market_label_from_pick_text(text: str) -> str:
    lowered = text.lower()
    if "total" in lowered or lowered.startswith("over") or lowered.startswith("under"):
        return "Total"
    if "+1.5" in lowered or "-1.5" in lowered or "spread" in lowered or "puck" in lowered:
        return "Spread"
    if "moneyline" in lowered or lowered.startswith("ml"):
        return "Moneyline"
    if "first 10" in lowered:
        return "First 10"
    return "Game bet"


def _game_row_updated_epoch(game: dict[str, Any], fallback_epoch: float) -> float:
    for value in [
        game.get("updated_at"),
        game.get("updatedAt"),
        game.get("generatedAt"),
        game.get("generated_at"),
        game.get("lastSeenAt"),
        game.get("last_seen_at"),
    ]:
        parsed = _parse_timestamp_epoch(value)
        if parsed > 0:
            return parsed
    return fallback_epoch


def _append_game_bet_candidate(candidates: list[dict[str, Any]], *, sport: dict[str, Any], game: dict[str, Any], market: str, pick: str, line: Any = None, odds: Any = None, edge: Any = None, confidence: Any = None, detail: str | None = None, fallback_epoch: float) -> None:
    pick_text = _safe_text(pick, "-")
    if pick_text == "-":
        return
    line_text = _prop_metric_text(line) if line is not None else None
    odds_text = _prop_metric_text(odds) if odds is not None else None
    edge_text = _pct_text(edge) if edge is not None and _numeric_value(edge) is not None else _safe_text(edge, "-") if edge is not None else "-"
    confidence_text = _pct_text(confidence) if confidence is not None and _numeric_value(confidence) is not None else _safe_text(confidence, "-") if confidence is not None else "-"
    edge_value = _pct_number(edge_text)
    confidence_value = _pct_number(confidence_text)
    updated_epoch = _game_row_updated_epoch(game, fallback_epoch)
    href = str(game.get("href") or sport.get("hub_href") or sport.get("primary_href") or "").strip() or None
    candidates.append(
        {
            "sport": _safe_text(sport.get("name"), str(sport.get("slug") or "").upper()),
            "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
            "matchup": _sport_matchup(game),
            "market": _safe_text(market, _market_label_from_pick_text(pick_text)),
            "pick": pick_text,
            "line": line_text or "-",
            "odds": odds_text or "-",
            "edge": edge_text,
            "confidence": confidence_text,
            "updated_at": _format_home_timestamp(updated_epoch),
            "updated_epoch": updated_epoch,
            "detail": _safe_text(detail or game.get("summary") or game.get("detail"), "No game-bet summary available."),
            "href": href,
            "href_label": _safe_text(game.get("href_label"), "Open game"),
            "score": float((edge_value or 0.0) * 1.8 + (confidence_value or 0.0) + (20.0 if odds_text and odds_text != "-" else 0.0)),
        }
    )


def _game_bet_candidates_from_game(sport: dict[str, Any], game: dict[str, Any], *, fallback_epoch: float) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    game_recs = game.get("game_market_recommendations") if isinstance(game.get("game_market_recommendations"), list) else []
    for row in game_recs:
        if not isinstance(row, dict):
            continue
        _append_game_bet_candidate(
            candidates,
            sport=sport,
            game=game,
            market=_first_present_text(row.get("market_label"), row.get("market"), row.get("label")) or "Game bet",
            pick=_first_present_text(row.get("display_pick"), row.get("selection"), row.get("pick")) or "-",
            line=row.get("line") if row.get("line") is not None else row.get("market_line"),
            odds=_first_present_text(row.get("odds"), row.get("price"), row.get("american_odds")),
            edge=row.get("ev_pct") if row.get("ev_pct") is not None else row.get("edge"),
            confidence=row.get("p_win") if row.get("p_win") is not None else row.get("confidence"),
            detail=_first_present_text(row.get("summary"), row.get("reason"), game.get("summary")),
            fallback_epoch=fallback_epoch,
        )
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    if betting:
        _append_game_bet_candidate(candidates, sport=sport, game=game, market="Moneyline", pick=f"Away ML", odds=betting.get("away_ml"), edge=betting.get("away_ml_ev"), confidence=betting.get("p_away_win"), detail=game.get("summary"), fallback_epoch=fallback_epoch)
        _append_game_bet_candidate(candidates, sport=sport, game=game, market="Moneyline", pick=f"Home ML", odds=betting.get("home_ml"), edge=betting.get("home_ml_ev"), confidence=betting.get("p_home_win"), detail=game.get("summary"), fallback_epoch=fallback_epoch)
        if betting.get("total") is not None:
            _append_game_bet_candidate(candidates, sport=sport, game=game, market="Total", pick=f"Over { _prop_metric_text(betting.get('total')) or '-' }", line=betting.get("total"), edge=betting.get("over_ev"), confidence=betting.get("p_total_over"), detail=game.get("summary"), fallback_epoch=fallback_epoch)
            _append_game_bet_candidate(candidates, sport=sport, game=game, market="Total", pick=f"Under { _prop_metric_text(betting.get('total')) or '-' }", line=betting.get("total"), edge=betting.get("under_ev"), confidence=betting.get("p_total_under"), detail=game.get("summary"), fallback_epoch=fallback_epoch)
        if betting.get("home_puck_line") is not None or betting.get("away_puck_line") is not None:
            _append_game_bet_candidate(candidates, sport=sport, game=game, market="Spread", pick=f"Away { _prop_metric_text(betting.get('away_puck_line')) or '' }".strip(), line=betting.get("away_puck_line"), edge=betting.get("away_puck_line_ev"), detail=game.get("summary"), fallback_epoch=fallback_epoch)
            _append_game_bet_candidate(candidates, sport=sport, game=game, market="Spread", pick=f"Home { _prop_metric_text(betting.get('home_puck_line')) or '' }".strip(), line=betting.get("home_puck_line"), edge=betting.get("home_puck_line_ev"), detail=game.get("summary"), fallback_epoch=fallback_epoch)
    top_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    for row in top_rows:
        if not isinstance(row, dict):
            continue
        name = _safe_text(row.get("name"), "-")
        if name == "-":
            continue
        edge_match = re.search(r"([+-]?\d+(?:\.\d+)?)%", name)
        odds_match = re.search(r"at\s+([+-]?\d+(?:\.\d+)?)", name, re.IGNORECASE)
        _append_game_bet_candidate(
            candidates,
            sport=sport,
            game=game,
            market=_safe_text(row.get("heading"), _market_label_from_pick_text(name)),
            pick=name,
            odds=odds_match.group(1) if odds_match else None,
            edge=edge_match.group(1) if edge_match else None,
            detail=row.get("detail"),
            fallback_epoch=fallback_epoch,
        )
    lenses = game.get("gameLens") if isinstance(game.get("gameLens"), list) else []
    for lens in lenses:
        if not isinstance(lens, dict) or bool(lens.get("closed")):
            continue
        lens_label = _safe_text(lens.get("label"), "Live")
        markets = lens.get("markets") if isinstance(lens.get("markets"), dict) else {}
        for market_key, market_label in [("moneyline", "Moneyline"), ("spread", "Spread"), ("total", "Total")]:
            market = markets.get(market_key) if isinstance(markets.get(market_key), dict) else {}
            pick = _first_present_text(market.get("pick"), market.get("selection"))
            if not pick:
                continue
            _append_game_bet_candidate(
                candidates,
                sport=sport,
                game=game,
                market=f"{lens_label} {market_label}",
                pick=pick,
                line=market.get("line") if market_key == "total" else market.get("homeLine"),
                odds=_first_present_text(market.get("odds"), market.get("price")),
                edge=market.get("edge"),
                confidence=market.get("p_win"),
                detail=game.get("summary"),
                fallback_epoch=fallback_epoch,
            )
    filtered = [row for row in candidates if row.get("edge") not in {"-", None} or row.get("confidence") not in {"-", None}]
    return sorted(filtered or candidates, key=lambda row: row.get("score", 0.0), reverse=True)


def _dashboard_prop_count(sport: dict[str, Any]) -> int:
    props_bar = sport.get("props_bar") if isinstance(sport.get("props_bar"), dict) else {}
    base_count = len(props_bar.get("items") or []) if isinstance(props_bar.get("items"), list) else 0
    if str(sport.get("slug") or "").strip().lower() != "mlb":
        return base_count
    mlb_home = sport.get("mlb_home") if isinstance(sport.get("mlb_home"), dict) else {}
    counts = [
        base_count,
        len(mlb_home.get("live_props_items") or []) if isinstance(mlb_home.get("live_props_items"), list) else 0,
        len(mlb_home.get("pregame_props_items") or []) if isinstance(mlb_home.get("pregame_props_items"), list) else 0,
        len(mlb_home.get("hr_targets_items") or []) if isinstance(mlb_home.get("hr_targets_items"), list) else 0,
    ]
    return max(counts)


def _build_game_watch_row(sport: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    status_badge = _safe_text(item.get("status_badge"), "Tracked")
    detail = _safe_text(item.get("detail"), "Board update pending")
    signals = [str(value).strip() for value in (item.get("signals") or []) if str(value).strip()]
    chips = [str(value).strip() for value in (item.get("market_chips") or []) if str(value).strip()]
    primary_signal = signals[0] if signals else (chips[0] if chips else "No market signal surfaced")
    confidence = _pct_number(primary_signal)
    live_flag = _is_liveish(status_badge, detail)
    return {
        "sport": _safe_text(sport.get("name"), str(sport.get("slug") or "").upper()),
        "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
        "matchup": _safe_text(item.get("matchup"), "Game"),
        "status": status_badge,
        "detail": detail,
        "signal": primary_signal,
        "summary": _safe_text(item.get("summary"), "No board read surfaced."),
        "href": str(item.get("href") or sport.get("hub_href") or "").strip() or None,
        "href_label": _safe_text(item.get("href_label"), "Open board"),
        "is_live": live_flag,
        "score": (80.0 if live_flag else 25.0) + float(len(signals) * 8 + len(chips) * 4) + float(confidence or 0.0),
    }


def _build_prop_dashboard_row(sport: dict[str, Any], item: dict[str, Any], *, default_surface: str) -> dict[str, Any]:
    heading = _safe_text(item.get("heading"), default_surface)
    detail = _safe_text(item.get("detail"), "No prop summary available.")
    confidence = _safe_text(item.get("confidence") or item.get("value"), "-")
    edge = _safe_text(item.get("edge"), "-")
    explicit_live = item.get("is_live")
    if isinstance(explicit_live, bool):
        live_flag = explicit_live
    else:
        live_tokens = [
            heading.lower(),
            str(default_surface or "").strip().lower(),
            detail.lower(),
        ]
        live_flag = any(
            token
            for token in live_tokens
            if any(marker in token for marker in ["live props", "prop live", "live lens", "in-game", "live audit"])
        )
    confidence_value = _pct_number(confidence)
    edge_value = _pct_number(edge)
    score = float((confidence_value or 0.0) + (edge_value or 0.0) * 1.5 + (55.0 if live_flag else 20.0))
    return {
        "sport": _safe_text(sport.get("name"), str(sport.get("slug") or "").upper()),
        "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
        "surface": heading,
        "name": _safe_text(item.get("name"), "Prop"),
        "market": _safe_text(item.get("market"), heading),
        "pick": _safe_text(item.get("pick"), detail.split("|")[0].strip() if detail else heading),
        "matchup": _safe_text(item.get("matchup"), "-"),
        "actual": _safe_text(item.get("actual"), "-"),
        "projected": _safe_text(item.get("projected"), "-"),
        "line": _safe_text(item.get("line"), "-"),
        "odds": _safe_text(item.get("odds"), "-"),
        "edge": edge,
        "confidence": confidence,
        "detail": detail,
        "href": str(item.get("href") or sport.get("hub_href") or "").strip() or None,
        "is_live": live_flag,
        "score": score,
    }


def _build_home_dashboard(overview: list[dict[str, Any]], *, selected_date: str, polled_at: float) -> dict[str, Any]:
    live_watch: list[dict[str, Any]] = []
    game_bets: list[dict[str, Any]] = []
    prop_rows: list[dict[str, Any]] = []
    sport_summaries: list[dict[str, Any]] = []
    for sport in overview:
        if not isinstance(sport, dict):
            continue
        game_bar = sport.get("game_bar") if isinstance(sport.get("game_bar"), dict) else {}
        props_bar = sport.get("props_bar") if isinstance(sport.get("props_bar"), dict) else {}
        game_items = game_bar.get("items") if isinstance(game_bar.get("items"), list) else []
        dashboard_games = sport.get("dashboard_games") if isinstance(sport.get("dashboard_games"), list) else []
        prop_items = props_bar.get("items") if isinstance(props_bar.get("items"), list) else []
        for item in game_items:
            if isinstance(item, dict):
                live_watch.append(_build_game_watch_row(sport, item))
        for game in dashboard_games:
            if isinstance(game, dict):
                game_bets.extend(_game_bet_candidates_from_game(sport, game, fallback_epoch=polled_at)[:3])
        for item in prop_items:
            if isinstance(item, dict):
                prop_rows.append(_build_prop_dashboard_row(sport, item, default_surface=_safe_text(props_bar.get("title"), "Props")))
        if str(sport.get("slug") or "").strip().lower() == "mlb":
            mlb_home = sport.get("mlb_home") if isinstance(sport.get("mlb_home"), dict) else {}
            for item in mlb_home.get("live_props_items") if isinstance(mlb_home.get("live_props_items"), list) else []:
                if isinstance(item, dict):
                    prop_rows.append(_build_prop_dashboard_row(sport, item, default_surface="Live props"))
            for item in mlb_home.get("pregame_props_items") if isinstance(mlb_home.get("pregame_props_items"), list) else []:
                if isinstance(item, dict):
                    prop_rows.append(_build_prop_dashboard_row(sport, item, default_surface="Pregame props"))
            for item in mlb_home.get("hr_targets_items") if isinstance(mlb_home.get("hr_targets_items"), list) else []:
                if isinstance(item, dict):
                    prop_rows.append(_build_prop_dashboard_row(sport, item, default_surface="HR targets"))
        sport_slug = _safe_text(sport.get("slug"), "").lower()
        summary_signals = next((row.get("signal") for row in live_watch if row.get("sport_slug") == sport_slug), "-")
        top_game_bet = next((row for row in game_bets if row.get("sport_slug") == sport_slug), None)
        top_prop = next((row for row in prop_rows if row.get("sport_slug") == _safe_text(sport.get("slug"), "").lower()), None)
        sport_summaries.append(
            {
                "sport": _safe_text(sport.get("name"), str(sport.get("slug") or "").upper()),
                "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
                "context": _safe_text(sport.get("context_label"), selected_date),
                "status": _safe_text(sport.get("status"), "Tracked"),
                "is_live": bool(sport.get("active_today")),
                "games": len(game_items),
                "props": _dashboard_prop_count(sport),
                "best_signal": summary_signals,
                "top_game_bet": top_game_bet.get("pick") if isinstance(top_game_bet, dict) else "-",
                "top_prop": top_prop.get("name") if isinstance(top_prop, dict) else "-",
                "hub_href": str(sport.get("hub_href") or sport.get("primary_href") or "").strip() or None,
            }
        )

    live_watch = sorted(live_watch, key=lambda row: row.get("score", 0.0), reverse=True)
    game_bets = sorted(game_bets, key=lambda row: row.get("score", 0.0), reverse=True)
    prop_rows = sorted(prop_rows, key=lambda row: row.get("score", 0.0), reverse=True)
    live_props = [row for row in prop_rows if bool(row.get("is_live"))]
    live_sports = sum(1 for sport in overview if bool((sport or {}).get("active_today")))
    summary_cards = [
        {"label": "Board date", "value": selected_date, "meta": f"Polled {_format_home_timestamp(polled_at)}"},
        {"label": "Live sports", "value": str(live_sports), "meta": f"{len(live_watch)} game reads surfaced"},
        {"label": "Game bets", "value": str(len(game_bets)), "meta": "Structured sides and totals surfaced"},
        {"label": "Props surfaced", "value": str(len(prop_rows)), "meta": f"{len(live_props)} live props in focus"},
        {"label": "Sports tracked", "value": str(len(overview)), "meta": "Cross-sport board"},
    ]
    return {
        "summary_cards": summary_cards,
        "top_game_bets": game_bets[:12],
        "live_watch": live_watch[:10],
        "top_props": prop_rows[:14],
        "sport_summaries": sport_summaries,
    }


def _parse_timestamp_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0


def _mlb_prop_state_rank(game: dict[str, Any], prop: dict[str, Any]) -> int:
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    detail_text = " ".join(
        str(value or "").strip().lower()
        for value in [status.get("detailed"), status.get("abstract"), game.get("detail"), game.get("summary"), prop.get("status")]
        if str(value or "").strip()
    )
    if any(token in detail_text for token in ("final", "game over", "completed")):
        return 0
    if any(token in detail_text for token in ("delayed", "suspended", "challenge", "review")):
        return 1
    if any(token in detail_text for token in ("live", "in progress", "top ", "bot ")):
        return 3
    return 2


def _fetch_mlb_feed_live(game_pk: int) -> dict[str, Any] | None:
    try:
        with urlopen(f"https://statsapi.mlb.com/api/v1.1/game/{int(game_pk)}/feed/live", timeout=5) as response:
            if int(getattr(response, "status", 200) or 200) >= 400:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, URLError):
        return None


def _mlb_feed_live_payload(selected_date: str, game_pk: int) -> dict[str, Any] | None:
    payload = load_json_or_gz_file(raw_feed_live_path(selected_date, int(game_pk)))
    if isinstance(payload, dict):
        return payload
    if selected_date == central_today_iso():
        return _fetch_mlb_feed_live(game_pk)
    return None


def _mlb_feed_live_state(selected_date: str, game_pk: int) -> dict[str, Any] | None:
    payload = _mlb_feed_live_payload(selected_date, game_pk)
    if not isinstance(payload, dict):
        return None
    game_data = payload.get("gameData") if isinstance(payload.get("gameData"), dict) else {}
    live_data = payload.get("liveData") if isinstance(payload.get("liveData"), dict) else {}
    status = game_data.get("status") if isinstance(game_data.get("status"), dict) else {}
    linescore = live_data.get("linescore") if isinstance(live_data.get("linescore"), dict) else {}
    teams = linescore.get("teams") if isinstance(linescore.get("teams"), dict) else {}
    away_score = ((teams.get("away") or {}) if isinstance(teams.get("away"), dict) else {}).get("runs")
    home_score = ((teams.get("home") or {}) if isinstance(teams.get("home"), dict) else {}).get("runs")
    abstract = str(status.get("abstractGameState") or "").strip()
    detailed = str(status.get("detailedState") or "").strip()
    inning = linescore.get("currentInningOrdinal") or linescore.get("currentInning")
    half = str(linescore.get("inningHalf") or "").strip().lower()
    outs = linescore.get("outs")
    status_bits = [bit for bit in [detailed, f"{half.title()} {inning}".strip() if inning and half else None, f"{outs} out" if outs == 1 else f"{outs} outs" if outs not in {None, ''} else None] if bit]
    return {
        "away_pts": away_score,
        "home_pts": home_score,
        "in_progress": abstract.lower() == "live",
        "final": abstract.lower() == "final",
        "status": " | ".join(status_bits) if status_bits else detailed or abstract or None,
    }


def _apply_mlb_live_scores(games: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_pk = int(game.get("gamePk") or 0)
        live_state = _mlb_feed_live_state(selected_date, game_pk) if game_pk else None
        if not live_state:
            enriched.append(game)
            continue
        updated = dict(game)
        away = dict(game.get("away") or {}) if isinstance(game.get("away"), dict) else {}
        home = dict(game.get("home") or {}) if isinstance(game.get("home"), dict) else {}
        if live_state.get("away_pts") is not None:
            away["score"] = live_state.get("away_pts")
        if live_state.get("home_pts") is not None:
            home["score"] = live_state.get("home_pts")
        updated["away"] = away
        updated["home"] = home
        status = dict(game.get("status") or {}) if isinstance(game.get("status"), dict) else {}
        if live_state.get("away_pts") is not None:
            status["away_score"] = live_state.get("away_pts")
        if live_state.get("home_pts") is not None:
            status["home_score"] = live_state.get("home_pts")
        status["is_live"] = bool(live_state.get("in_progress"))
        status["in_progress"] = bool(live_state.get("in_progress"))
        status["is_final"] = bool(live_state.get("final"))
        status["final"] = bool(live_state.get("final"))
        if live_state.get("in_progress"):
            status["abstract"] = "Live"
        elif live_state.get("final"):
            status["abstract"] = "Final"
        if live_state.get("status"):
            status["detailed"] = live_state.get("status")
        updated["status"] = status
        updated["live_state"] = live_state
        enriched.append(updated)
    return enriched


def _apply_nba_live_scores(games: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    try:
        from syndicate.features.nba.cards import _games_from_live_state_fallback
    except Exception:
        return games

    live_games, _ = _games_from_live_state_fallback(selected_date)
    if not live_games:
        return games

    keyed_live: dict[tuple[str, str], dict[str, Any]] = {}
    for game in live_games:
        if not isinstance(game, dict):
            continue
        away_key = str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")).strip().upper()
        home_key = str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")).strip().upper()
        if away_key and home_key:
            keyed_live[(away_key, home_key)] = game

    enriched: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        away_key = str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")).strip().upper()
        home_key = str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")).strip().upper()
        live_game = keyed_live.get((away_key, home_key)) if away_key and home_key else None
        if not live_game:
            enriched.append(game)
            continue
        seen.add((away_key, home_key))
        updated = dict(game)
        away = dict(game.get("away") or {}) if isinstance(game.get("away"), dict) else {}
        home = dict(game.get("home") or {}) if isinstance(game.get("home"), dict) else {}
        live_state = dict(live_game.get("live_state") or {}) if isinstance(live_game.get("live_state"), dict) else {}
        if live_state.get("away_pts") is not None:
            away["score"] = live_state.get("away_pts")
        if live_state.get("home_pts") is not None:
            home["score"] = live_state.get("home_pts")
        updated["away"] = away
        updated["home"] = home
        status = dict(game.get("status") or {}) if isinstance(game.get("status"), dict) else {}
        if live_state.get("away_pts") is not None:
            status["away_score"] = live_state.get("away_pts")
        if live_state.get("home_pts") is not None:
            status["home_score"] = live_state.get("home_pts")
        status["is_live"] = bool(live_state.get("in_progress"))
        status["in_progress"] = bool(live_state.get("in_progress"))
        status["is_final"] = bool(live_state.get("final"))
        status["final"] = bool(live_state.get("final"))
        if live_state.get("in_progress"):
            status["abstract"] = "Live"
        elif live_state.get("final"):
            status["abstract"] = "Final"
        detail_text = str(live_state.get("status") or live_game.get("detail") or "").strip()
        if detail_text:
            status["detailed"] = detail_text
        updated["status"] = status
        updated["live_state"] = live_state
        enriched.append(updated)

    for key, live_game in keyed_live.items():
        if key not in seen:
            enriched.append(live_game)
    return enriched


def _load_nhl_scoreboard_rows(selected_date: str) -> list[dict[str, Any]]:
    path = scoreboard_snapshot_path(selected_date)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "gamePk": row.get("gamePk") or row.get("game_id"),
                "away": row.get("away") or row.get("away_team"),
                "home": row.get("home") or row.get("home_team"),
                "away_abbr": row.get("away_abbr") or row.get("away_tri"),
                "home_abbr": row.get("home_abbr") or row.get("home_tri"),
                "away_goals": row.get("away_goals") or row.get("awayScore") or row.get("away_score"),
                "home_goals": row.get("home_goals") or row.get("homeScore") or row.get("home_score"),
                "gameState": row.get("gameState") or row.get("game_state") or row.get("state"),
                "period": row.get("period") or row.get("web_period"),
                "clock": row.get("clock") or row.get("web_clock"),
            }
        )
    return out


def _apply_nhl_live_scores(games: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    rows = _load_nhl_scoreboard_rows(selected_date)
    if not rows:
        return games

    keyed_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        row_keys = {
            (
                str(row.get("away_abbr") or "").strip().upper(),
                str(row.get("home_abbr") or "").strip().upper(),
            ),
            (
                str(row.get("away") or "").strip().upper(),
                str(row.get("home") or "").strip().upper(),
            ),
        }
        for key in row_keys:
            if key[0] and key[1]:
                keyed_rows[key] = row

    enriched: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_keys = [
            (
                str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")).strip().upper(),
                str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")).strip().upper(),
            ),
            (
                str(game.get("away_name") or ((game.get("away") or {}).get("name") if isinstance(game.get("away"), dict) else "")).strip().upper(),
                str(game.get("home_name") or ((game.get("home") or {}).get("name") if isinstance(game.get("home"), dict) else "")).strip().upper(),
            ),
        ]
        row = next((keyed_rows.get(key) for key in game_keys if key[0] and key[1] and keyed_rows.get(key)), None)
        if not row:
            enriched.append(game)
            continue
        updated = dict(game)
        away = dict(game.get("away") or {}) if isinstance(game.get("away"), dict) else {}
        home = dict(game.get("home") or {}) if isinstance(game.get("home"), dict) else {}
        away_goals = _numeric_value(row.get("away_goals"))
        home_goals = _numeric_value(row.get("home_goals"))
        if away_goals is not None:
            away["score"] = away_goals
        if home_goals is not None:
            home["score"] = home_goals
        updated["away"] = away
        updated["home"] = home
        state = str(row.get("gameState") or "").strip().upper()
        period = str(row.get("period") or "").strip()
        clock = str(row.get("clock") or "").strip()
        detail_bits = [bit for bit in [state, f"P{period}" if period else None, clock or None] if bit]
        live_state = {
            "away_pts": away_goals,
            "home_pts": home_goals,
            "in_progress": state in {"LIVE", "CRIT"},
            "final": state == "OFF",
            "status": " | ".join(detail_bits) if detail_bits else selected_date,
        }
        status = dict(game.get("status") or {}) if isinstance(game.get("status"), dict) else {}
        if away_goals is not None:
            status["away_score"] = away_goals
        if home_goals is not None:
            status["home_score"] = home_goals
        status["is_live"] = bool(live_state["in_progress"])
        status["in_progress"] = bool(live_state["in_progress"])
        status["is_final"] = bool(live_state["final"])
        status["final"] = bool(live_state["final"])
        if live_state["in_progress"]:
            status["abstract"] = "Live"
        elif live_state["final"]:
            status["abstract"] = "Final"
        status["detailed"] = live_state["status"]
        updated["status"] = status
        updated["live_state"] = live_state
        updated["shared_is_live"] = bool(live_state["in_progress"])
        enriched.append(updated)
    return enriched


def _market_based_projected_scores(game: dict[str, Any]) -> tuple[str | None, str | None]:
    total = _metric_or_tile_value(game, ["total", "full total", "model total"])
    home_line = _metric_or_tile_value(game, ["spread", "home spread"])
    if total is None or home_line is None:
        return None, None
    margin = -home_line
    home_score = (total + margin) / 2.0
    away_score = total - home_score
    away_text = _score_value(away_score)
    home_text = _score_value(home_score)
    if away_text and home_text:
        return away_text, home_text
    return None, None


def _projected_scores(game: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    predictions = game.get("predictions") if isinstance(game.get("predictions"), dict) else {}
    full = predictions.get("full") if isinstance(predictions.get("full"), dict) else predictions
    away_mean = full.get("away_runs_mean") if isinstance(full, dict) else None
    home_mean = full.get("home_runs_mean") if isinstance(full, dict) else None
    if away_mean is None or home_mean is None:
        sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
        score = sim.get("score") if isinstance(sim.get("score"), dict) else sim
        if isinstance(score, dict):
            away_mean = score.get("away_mean", away_mean)
            home_mean = score.get("home_mean", home_mean)
    away_score = _score_value(away_mean)
    home_score = _score_value(home_mean)
    if away_score and home_score:
        return away_score, home_score, "Projection"
    market_away, market_home = _market_based_projected_scores(game)
    if market_away and market_home:
        return market_away, market_home, "Market projection"
    return None, None, None


def _prop_item_from_rank_card(card: dict[str, Any], *, fallback_href: str | None = None, heading_override: str | None = None) -> dict[str, Any] | None:
    if not isinstance(card, dict):
        return None
    title = _safe_text(card.get("title"), "Prop")
    meta = _safe_text(card.get("meta"), "Props board")
    detail = _safe_text(card.get("summary"), "No prop summary available.")
    badge = str(card.get("badge") or "").strip()
    metrics = card.get("metrics") if isinstance(card.get("metrics"), list) else []
    value = badge or _safe_text((((card.get("metrics") or [None])[0] or {}).get("value") if isinstance(card.get("metrics"), list) else None), "Top play")
    href = str(card.get("href") or fallback_href or "").strip() or None
    return {
        "matchup": meta,
        "heading": _safe_text(heading_override or card.get("eyebrow"), "Props"),
        "name": title,
        "detail": detail,
        "value": value,
        "is_live": False,
        "market": _metric_value(metrics, ["market", "stat"]),
        "pick": badge or _metric_value(metrics, ["pick", "lean", "selection", "side"]),
        "actual": _metric_value(metrics, ["actual"]),
        "projected": _metric_value(metrics, ["projected", "projection", "model", "mean", "median"]),
        "line": _metric_value(metrics, ["line", "market line", "threshold"]),
        "odds": _metric_value(metrics, ["odds", "price"]),
        "edge": _metric_value(metrics, ["edge", "ev"]),
        "confidence": _metric_value(metrics, ["confidence", "win prob", "probability", "hit rate"]),
        "href": href,
    }


def _rank_card_score_values(card: dict[str, Any]) -> tuple[str | None, str | None]:
    metrics = card.get("metrics") if isinstance(card.get("metrics"), list) else []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or "").strip().lower()
        value = str(metric.get("value") or "").strip()
        if label != "score" or "-" not in value:
            continue
        away_text, home_text = [part.strip() for part in value.split("-", 1)]
        return away_text or None, home_text or None
    return None, None


def _compact_game_items_from_rank_cards(cards: list[dict[str, Any]], *, fallback_href: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        title = _safe_text(card.get("title"), "Lens card")
        if " @ " in title:
            away_label, home_label = [part.strip() or "-" for part in title.split(" @ ", 1)]
        else:
            away_label, home_label = title, "-"
        away_score, home_score = _rank_card_score_values(card)
        items.append(
            {
                "matchup": title,
                "detail": _safe_text(card.get("meta"), "Live lens"),
                "status_badge": _safe_text(card.get("eyebrow"), "Live lens"),
                "away_label": away_label,
                "away_logo": _safe_text(card.get("away_logo"), None),
                "home_label": home_label,
                "home_logo": _safe_text(card.get("home_logo"), None),
                "away_score": away_score,
                "home_score": home_score,
                "has_scores": bool(away_score and home_score),
                "score_kind": "Live score" if away_score and home_score else "Live lens",
                "is_projected_score": False,
                "summary": _safe_text(card.get("summary"), "No live-lens summary available."),
                "signals": [
                    _safe_text(card.get("badge"), "Watch")
                ] + [
                    f"{_safe_text(metric.get('label'))}: {_safe_text(metric.get('value'))}"
                    for metric in (card.get("metrics") if isinstance(card.get("metrics"), list) else [])[:3]
                    if isinstance(metric, dict)
                ],
                "href": str(card.get("href") or fallback_href or "").strip() or None,
                "href_label": str(card.get("href_label") or "Open live lens").strip() or "Open live lens",
            }
        )
        if limit is not None and len(items) >= limit:
            break
    return items


def _load_home_game_items(
    slug: str,
    *,
    context_label: str,
    season: int | None = None,
    week: int | None = None,
    is_active_today: bool,
) -> tuple[list[dict[str, Any]], int]:
    home_games = _load_home_games(slug, context_label=context_label, season=season, week=week, is_active_today=is_active_today) if is_active_today else []
    if slug == "mlb" and home_games:
        home_games = _apply_mlb_live_scores(home_games, context_label)
    if not is_active_today:
        return [], len(home_games)
    try:
        if slug == "mlb":
            from syndicate.features.mlb.live_lens import build_live_lens_page_context

            live_games = list(build_live_lens_page_context(context_label).get("games") or [])
            if live_games:
                live_games = _apply_mlb_live_scores(live_games, context_label)
            if live_games:
                return _compact_game_cards(live_games), len(live_games)
        if slug == "nba":
            if home_games:
                return _compact_game_cards(home_games), len(home_games)
        if slug == "wnba":
            if home_games:
                return _compact_game_cards(home_games), len(home_games)
        if slug == "nhl":
            if home_games:
                return _compact_game_cards(home_games), len(home_games)
        if slug == "ncaab":
            from syndicate.features.ncaab.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context(context_label)
            cards = list(context.get("rank_cards") or [])
            if cards:
                return _compact_game_items_from_rank_cards(cards, fallback_href=f"/ncaab/live-lens?date={context_label}"), len(cards)
        if slug == "nfl" and week is not None:
            from syndicate.features.nfl.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context(week, season=int(season or central_year()))
            cards = list(context.get("rank_cards") or [])
            if cards:
                return _compact_game_items_from_rank_cards(cards, fallback_href=f"/nfl/live-lens?season={int(season or central_year())}&week={week}"), len(cards)
        if slug == "ncaaf" and week is not None:
            from syndicate.features.ncaaf.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context(week)
            cards = list(context.get("rank_cards") or [])
            if cards:
                return _compact_game_items_from_rank_cards(cards, fallback_href=f"/ncaaf/live-lens?week={week}"), len(cards)
    except Exception:
        pass
    return _compact_game_cards(home_games), len(home_games)


def _prop_rows_from_rank_cards(cards: list[dict[str, Any]], *, fallback_href: str | None = None, limit: int = 18, heading_override: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        item = _prop_item_from_rank_card(card, fallback_href=fallback_href, heading_override=heading_override)
        if not item:
            continue
        rows.append(item)
        if len(rows) >= limit:
            break
    return rows


def _interleave_rows(*groups: list[dict[str, Any]], limit: int = 18) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions = [0 for _ in groups]
    while len(merged) < limit:
        advanced = False
        for index, group in enumerate(groups):
            if positions[index] >= len(group):
                continue
            merged.append(group[positions[index]])
            positions[index] += 1
            advanced = True
            if len(merged) >= limit:
                break
        if not advanced:
            break
    return merged


def _prop_rows_from_nhl_cards(cards: list[dict[str, Any]], *, fallback_href: str | None = None, limit: int = 18) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        player = _safe_text(card.get("player"), "NHL prop")
        side = _safe_text(card.get("side"), "Play")
        line = _score_value(card.get("line")) or _safe_text(card.get("line"), "-")
        market = _safe_text(card.get("market"), "Market")
        team = _safe_text(card.get("team"), "Team")
        opp = _safe_text(card.get("opp"), "Opp")
        prob = _numeric_value(card.get("prob"))
        prob_text = f"{prob * 100:.1f}% win" if prob is not None else _safe_text(card.get("tracking_note"), "Tracked")
        rows.append(
            {
                "matchup": f"{team} vs {opp}",
                "heading": "Live props",
                "name": player,
                "is_live": True,
                "market": market,
                "pick": side,
                "detail": f"{side} {line} {market} | {_safe_text(card.get('reason_summary'), 'No stored prop summary available.')}",
                "value": prob_text,
                "projected": _prop_metric_text(card.get("projection") if card.get("projection") is not None else card.get("mean")),
                "line": line,
                "odds": _prop_metric_text(card.get("odds") if card.get("odds") is not None else card.get("price")),
                "edge": _pct_text(card.get("edge") if card.get("edge") is not None else card.get("ev")),
                "confidence": prob_text,
                "href": fallback_href,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _prop_rows_from_mlb_live_games(games: list[dict[str, Any]], *, limit: int = 18) -> list[dict[str, Any]]:
    candidates: list[tuple[tuple[int, float, float], dict[str, Any]]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        matchup = _sport_matchup(game)
        href = str(game.get("href") or "").strip() or None
        live_props = game.get("liveProps") if isinstance(game.get("liveProps"), list) else []
        archived_props = game.get("archivedLiveProps") if isinstance(game.get("archivedLiveProps"), list) else []
        for prop in [value for value in [*live_props, *archived_props] if isinstance(value, dict)]:
            selection = str(prop.get("selection") or "").strip().title()
            line = _score_value(prop.get("line")) or _safe_text(prop.get("line"), "-")
            market = _safe_text(prop.get("marketLabel") or prop.get("market"), "Market")
            player = _safe_text(prop.get("playerName"), "MLB prop")
            probability = _numeric_value(prop.get("estimatedWinProb"))
            if probability is None and str(prop.get("selection") or "").strip().lower() == "over":
                probability = _numeric_value(prop.get("modelProbOver"))
            value = f"{probability * 100:.1f}% win" if probability is not None else _safe_text(prop.get("odds"), "Live")
            row = {
                "matchup": matchup,
                "heading": "Live props",
                "name": player,
                "is_live": True,
                "market": market,
                "pick": selection,
                "detail": f"{selection} {line} {market}",
                "value": value,
                "actual": _prop_metric_text(prop.get("actual")),
                "projected": _prop_metric_text(prop.get("liveProjection") if prop.get("liveProjection") is not None else prop.get("modelMean")),
                "line": _prop_metric_text(prop.get("line")),
                "odds": _prop_metric_text(prop.get("odds")),
                "edge": _pct_text(prop.get("estimatedEdge") if prop.get("estimatedEdge") is not None else prop.get("ev")),
                "confidence": _pct_text(probability),
                "href": href,
            }
            rank = (
                _mlb_prop_state_rank(game, prop),
                _parse_timestamp_epoch(prop.get("lastSeenAt") or prop.get("firstSeenAt")),
                float(probability or 0.0),
            )
            candidates.append((rank, row))
    rows = [row for _, row in sorted(candidates, key=lambda item: item[0], reverse=True)[:limit]]
    return rows


def _prop_rows_from_nba_live_lens(games: list[dict[str, Any]], *, fallback_href: str | None = None, limit: int = 18) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        status = game.get("status") if isinstance(game.get("status"), dict) else {}
        matchup = f"{_safe_text(game.get('away'), 'Away')} @ {_safe_text(game.get('home'), 'Home')}"
        for row in game.get("rows") if isinstance(game.get("rows"), list) else []:
            if not isinstance(row, dict):
                continue
            score = _numeric_value(row.get("recommendation_priority_score"))
            if score is None:
                score = _numeric_value(row.get("bettable_score"))
                if score is not None:
                    score *= 100.0
            if score is None:
                score = _numeric_value(row.get("strength")) or 0.0
            payload = dict(row)
            payload["__matchup"] = matchup
            payload["__status"] = status
            candidates.append((score, game, payload))
    for _, game, row in sorted(candidates, key=lambda item: item[0], reverse=True):
        status = row.get("__status") if isinstance(row.get("__status"), dict) else {}
        status_bits = []
        period = status.get("period")
        clock = str(status.get("clock") or "").strip()
        if period not in {None, ""}:
            status_bits.append(f"Q{period}")
        if clock:
            status_bits.append(clock)
        heading = " | ".join(status_bits) if status_bits else "Live props"
        player = _safe_text(row.get("player"), "NBA prop")
        team = _safe_text(row.get("team_tri"), "Team")
        side = _safe_text(row.get("lean") or row.get("ev_side"), "Watch")
        line = _score_value(row.get("line_live") if row.get("line_live") is not None else row.get("line")) or _safe_text(row.get("line"), "-")
        market = _safe_text(row.get("stat"), "Market").upper()
        probability = _pct_text(row.get("win_prob") or row.get("live_rank_probability"))
        ev_pct = _pct_text(row.get("ev"))
        value = probability or (f"EV {ev_pct}" if ev_pct else _safe_text(row.get("klass"), "Watch"))
        rows.append(
            {
                "matchup": str(row.get("__matchup") or "").strip() or _sport_matchup(game),
                "heading": heading,
                "name": f"{player} ({team})",
                "is_live": True,
                "market": market,
                "pick": side,
                "detail": f"{side} {line} {market} | {_safe_text(row.get('basketball_summary') or row.get('shape_summary'), 'Live prop signal')}",
                "value": value,
                "actual": _prop_metric_text(row.get("actual")),
                "projected": _prop_metric_text(row.get("sim_mu_adjusted") if row.get("sim_mu_adjusted") is not None else row.get("sim_mu")),
                "line": _prop_metric_text(row.get("line_live") if row.get("line_live") is not None else row.get("line")),
                "odds": _prop_metric_text(row.get("odds_live") if row.get("odds_live") is not None else row.get("odds")),
                "edge": _pct_text(row.get("ev") if row.get("ev") is not None else row.get("edge")),
                "confidence": probability,
                "href": fallback_href or (str(game.get("href") or "").strip() or None),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _compact_game_items_from_nhl_live_payload(games: list[dict[str, Any]], *, selected_date: str, limit: int | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        score = game.get("score") if isinstance(game.get("score"), dict) else {}
        guidance = game.get("guidance") if isinstance(game.get("guidance"), dict) else {}
        signals = game.get("signals") if isinstance(game.get("signals"), list) else []
        state = str(game.get("gameState") or "").strip().upper()
        period = game.get("period")
        clock = str(game.get("clock") or "").strip()
        detail_bits = []
        if state:
            detail_bits.append(state)
        if period not in {None, ""}:
            detail_bits.append(f"P{period}")
        if clock:
            detail_bits.append(clock)
        signal_values: list[str] = []
        for signal in signals[:3]:
            if not isinstance(signal, dict):
                continue
            label = _safe_text(signal.get("label"), "Signal")
            action = str(signal.get("action") or "").strip()
            market = str(signal.get("market") or "").strip().replace("_", " ").title()
            parts = [label]
            if action:
                parts.append(action)
            if market:
                parts.append(market)
            signal_values.append(" | ".join(parts))
        chip_values: list[str] = []
        lean_total = str(guidance.get("lean_total") or "").strip().lower()
        if lean_total and lean_total != "neutral":
            chip_values.append(f"Total lean {lean_total.title()}")
        live_total_line = _score_value(guidance.get("live_total_line"))
        if live_total_line:
            chip_values.append(f"Live total {live_total_line}")
        total_goals = _score_value(guidance.get("total_goals"))
        if total_goals:
            chip_values.append(f"Goals {total_goals}")
        away_score = _score_value(score.get("away"))
        home_score = _score_value(score.get("home"))
        items.append(
            {
                "matchup": f"{_safe_text(game.get('away'), 'Away')} @ {_safe_text(game.get('home'), 'Home')}",
                "detail": " | ".join(detail_bits) if detail_bits else selected_date,
                "status_badge": "Live" if state in {"LIVE", "CRIT"} else "Final" if state == "OFF" else "Tracked",
                "away_label": _safe_text(game.get("away"), "Away"),
                "home_label": _safe_text(game.get("home"), "Home"),
                "away_score": away_score,
                "home_score": home_score,
                "has_scores": bool(away_score and home_score),
                "score_kind": "Live score" if state in {"LIVE", "CRIT"} else "Final score" if state == "OFF" else None,
                "is_projected_score": False,
                "summary": _safe_text((guidance.get("notes") or [None])[0], "No live lens summary available."),
                "signals": signal_values,
                "market_chips": chip_values,
                "href": f"/nhl/game/{str(game.get('gamePk') or '').strip()}?date={selected_date}" if str(game.get("gamePk") or "").strip() else f"/nhl/live-lens?date={selected_date}",
                "href_label": "Open game detail",
            }
        )
        if limit is not None and len(items) >= limit:
            break
    return items


def _load_home_prop_items(
    slug: str,
    *,
    context_label: str,
    home_games: list[dict[str, Any]],
    season: int | None = None,
    week: int | None = None,
    is_active_today: bool,
) -> list[dict[str, Any]]:
    try:
        if slug == "mlb":
            if is_active_today:
                from syndicate.features.mlb.live_lens import build_live_lens_page_context

                live_games = list(build_live_lens_page_context(context_label).get("games") or [])
                live_rows = _prop_rows_from_mlb_live_games(live_games)
                if live_rows:
                    return live_rows
            from syndicate.features.mlb.top_props import build_top_props_page_context

            pitcher_context = build_top_props_page_context(context_label, group="pitcher")
            hitter_context = build_top_props_page_context(context_label, group="hitter")
            pitcher_rows = _prop_rows_from_rank_cards(
                list(pitcher_context.get("rank_cards") or []),
                fallback_href=f"/mlb/pitcher-top-props?date={context_label}",
                limit=9,
                heading_override="Pitcher Top Props",
            )
            hitter_rows = _prop_rows_from_rank_cards(
                list(hitter_context.get("rank_cards") or []),
                fallback_href=f"/mlb/hitter-top-props?date={context_label}",
                limit=9,
                heading_override="Hitter Top Props",
            )
            top_rows = _interleave_rows(pitcher_rows, hitter_rows, limit=18)
            if top_rows:
                return top_rows
        if slug == "nhl":
            from syndicate.features.nhl.cards import build_props_cards_payload

            payload = build_props_cards_payload(context_label, top=18)
            nhl_rows = _prop_rows_from_nhl_cards(list(payload.get("cards") or []), fallback_href=f"/nhl/live-lens?date={context_label}")
            if nhl_rows:
                return nhl_rows
        if slug == "nba":
            if is_active_today:
                from syndicate.features.nba.cards import build_live_player_lens_payload
                from syndicate.features.nba.cards import build_live_state_payload

                live_state = build_live_state_payload(context_label, ttl=12)
                event_ids = [
                    str((game or {}).get("event_id") or "").strip()
                    for game in (live_state.get("games") if isinstance(live_state.get("games"), list) else [])
                    if str((game or {}).get("event_id") or "").strip()
                ]
                if event_ids:
                    payload = build_live_player_lens_payload(context_label, event_ids, ttl=20)
                    rows = _prop_rows_from_nba_live_lens(list(payload.get("games") or []), fallback_href=f"/nba/live-lens?date={context_label}")
                    if rows:
                        return rows
            from syndicate.features.nba.props import build_props_page_context

            context = build_props_page_context(context_label)
            nba_rows = _prop_rows_from_rank_cards(list(context.get("rank_cards") or []), fallback_href=f"/nba/prop-ladders?date={context_label}")
            if nba_rows:
                return nba_rows
        if slug == "wnba":
            from syndicate.features.wnba.props import build_props_page_context

            context = build_props_page_context(context_label)
            wnba_rows = _prop_rows_from_rank_cards(list(context.get("rank_cards") or []), fallback_href=f"/wnba/props?date={context_label}")
            if wnba_rows:
                return wnba_rows
    except Exception:
        pass
    rows = _compact_prop_rows(home_games)
    if rows:
        return rows
    return []


def _load_mlb_home_hr_target_items(context_label: str, *, limit: int = 10) -> list[dict[str, Any]]:
    try:
        from syndicate.features.mlb.hr_targets import build_hr_targets_page_context

        context = build_hr_targets_page_context(context_label)
        targets = list(context.get("targets") or [])
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for target in targets[:limit]:
        if not isinstance(target, dict):
            continue
        reasons = [str(item).strip() for item in (target.get("reasons") or []) if str(item).strip()]
        rows.append(
            {
                "heading": _safe_text(target.get("team"), "HR target"),
                "name": _safe_text(target.get("player_name"), "Unknown hitter"),
                "value": _safe_text(target.get("probability"), "-"),
                "matchup": _safe_text(target.get("matchup"), "-"),
                "detail": reasons[0] if reasons else _safe_text(target.get("summary"), "No HR-target summary available."),
                "line": _safe_text(target.get("support"), "-"),
                "href": f"/mlb/hr-targets?date={context_label}",
            }
        )
    return rows


def _tile_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for display in _game_market_recommendation_strings(game, limit=limit):
        if display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    market_tiles = game.get("market_tiles") if isinstance(game.get("market_tiles"), list) else []
    for tile in market_tiles:
        if not isinstance(tile, dict):
            continue
        label = str(tile.get("label") or "").strip()
        title = str(tile.get("title") or tile.get("value") or "").strip()
        if not label and not title:
            continue
        display = f"{label}: {title}" if label and title else (label or title)
        if display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    top_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    for row in top_rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        value = str(row.get("value") or "").strip()
        detail = str(row.get("detail") or "").strip()
        display = name or detail
        if value and display:
            display = f"{display} | {value}"
        if display and display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    for display in _betting_signal_strings(game, limit=limit):
        if display and display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    for display in _mlb_live_game_signal_strings(game, limit=limit):
        if display and display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    return values


def _compact_game_cards(games: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        scoreboard = _scoreboard_state(game)
        projected_away, projected_home, projected_kind = _projected_scores(game)
        if scoreboard.get("away_score") and scoreboard.get("home_score"):
            display_away = scoreboard.get("away_score")
            display_home = scoreboard.get("home_score")
            display_kind = scoreboard.get("score_kind")
        elif _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line")):
            display_away = None
            display_home = None
            display_kind = None
        else:
            display_away = projected_away
            display_home = projected_home
            display_kind = projected_kind if projected_away and projected_home else None
        cards.append(
            {
                "matchup": _sport_matchup(game),
                "detail": _safe_text(scoreboard.get("status_line"), "Board update pending"),
                "status_badge": _safe_text(scoreboard.get("status_badge"), "Scheduled"),
                "away_label": scoreboard.get("away_label"),
                "away_logo": _team_logo(game, "away"),
                "home_label": scoreboard.get("home_label"),
                "home_logo": _team_logo(game, "home"),
                "away_score": display_away,
                "home_score": display_home,
                "has_scores": bool(display_away and display_home),
                "score_kind": display_kind,
                "is_projected_score": bool(display_kind == "Projection"),
                "summary": _summary_text(game),
                "signals": _tile_strings(game),
                "market_chips": _market_chip_strings(game),
                "href": str(game.get("href") or "").strip() or None,
                "href_label": str(game.get("href_label") or "Open game").strip() or "Open game",
            }
        )
        if limit is not None and len(cards) >= limit:
            break
    return _sort_compact_game_items(cards)


def _compact_prop_rows(games: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        matchup = _sport_matchup(game)
        prop_rows = game.get("shared_prop_rows") if isinstance(game.get("shared_prop_rows"), list) else []
        for row in prop_rows:
            if not isinstance(row, dict):
                continue
            name = _safe_text(row.get("name"), "Prop")
            detail = _safe_text(row.get("detail"), "")
            value = _safe_text(row.get("value"), "-")
            key = (matchup, name, value)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "matchup": matchup,
                    "heading": _safe_text(row.get("heading"), "Props"),
                    "name": name,
                    "detail": detail,
                    "value": value,
                    "href": str(game.get("href") or "").strip() or None,
                }
            )
            if limit is not None and len(rows) >= limit:
                return rows
    return rows


def _load_home_games(slug: str, *, context_label: str, season: int | None = None, week: int | None = None, is_active_today: bool = False) -> list[dict[str, Any]]:
    try:
        if slug == "mlb":
            from syndicate.features.mlb.cards import build_cards_page_context

            payload = build_cards_page_context(context_label)
            games = list(payload.get("games") or [])
            return _apply_mlb_live_scores(games, context_label) if is_active_today else games
        if slug == "nba":
            from syndicate.features.nba.cards import build_cards_page_context

            payload = build_cards_page_context(context_label)
            if str(payload.get("requested_date") or context_label).strip() == str(context_label).strip() and str(payload.get("date") or context_label).strip() != str(context_label).strip():
                return []
            games = list(payload.get("games") or [])
            return _apply_nba_live_scores(games, context_label) if is_active_today else games
        if slug == "nhl":
            from syndicate.features.nhl.cards import build_cards_page_context

            payload = build_cards_page_context(context_label)
            if str(payload.get("requested_date") or context_label).strip() == str(context_label).strip() and str(payload.get("date") or context_label).strip() != str(context_label).strip():
                return []
            games = list(payload.get("games") or [])
            return _apply_nhl_live_scores(games, context_label) if is_active_today else games
        if slug == "wnba":
            from syndicate.features.wnba.cards import build_cards_page_context

            payload = build_cards_page_context(context_label)
            if str(payload.get("requested_date") or context_label).strip() == str(context_label).strip() and str(payload.get("date") or context_label).strip() != str(context_label).strip():
                return []
            return list(payload.get("games") or [])
        if slug == "ncaab":
            from syndicate.features.ncaab.cards import build_cards_page_context

            payload = build_cards_page_context(context_label)
            if str(payload.get("requested_date") or context_label).strip() == str(context_label).strip() and str(payload.get("date") or context_label).strip() != str(context_label).strip():
                return []
            return list(payload.get("games") or [])
        if slug == "nfl" and week is not None:
            from syndicate.features.nfl.cards import build_cards_page_context

            return list(build_cards_page_context(week, season=season).get("games") or [])
        if slug == "ncaaf" and week is not None:
            from syndicate.features.ncaaf.cards import build_cards_page_context

            return list(build_cards_page_context(week).get("games") or [])
    except Exception:
        return []
    return []


def _prefer_today_or_latest(values: list[str], today_value: str, *, preserve_requested: bool = False) -> str:
    if preserve_requested:
        return today_value
    if today_value in values:
        return today_value
    return values[-1] if values else today_value


def _link_lookup(links: list[dict[str, Any]], label: str) -> str | None:
    for link in links:
        if str(link.get("label") or "").strip().lower() == label.strip().lower():
            href = str(link.get("href") or "").strip()
            if href:
                return href
    return None


def _link_lookup_any(links: list[dict[str, Any]], labels: list[str]) -> tuple[str | None, str | None]:
    targets = [label.strip().lower() for label in labels if label.strip()]
    for link in links:
        label = str(link.get("label") or "").strip()
        href = str(link.get("href") or "").strip()
        if href and label.lower() in targets:
            return href, label
    return None, None


def _secondary_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded = {"cards", "betting card", "hub"}
    return [link for link in links if str(link.get("label") or "").strip().lower() not in excluded]


def _football_in_season(today_value: str) -> bool:
    month = int(today_value[5:7]) if len(today_value) >= 7 and today_value[5:7].isdigit() else 0
    return month in {1, 8, 9, 10, 11, 12}


def _is_active_today(slug: str, today_value: str, context_label: str) -> bool:
    if slug in {"mlb", "nba", "nhl", "wnba", "ncaab"}:
        return context_label == today_value
    if slug in {"nfl", "ncaaf"}:
        return _football_in_season(today_value)
    return False


def _sport_cache_key(slug: str, today_value: str) -> str:
    return f"{slug}:{today_value}"


def _choose_game_bar(links: list[dict[str, Any]], *, is_active_today: bool, fallback_href: str, fallback_label: str) -> dict[str, str | None]:
    live_href, _ = _link_lookup_any(links, ["Live Lens", "Live Prop Audit"])
    cards_href, cards_label = _link_lookup_any(links, ["Cards"])
    betting_href, betting_label = _link_lookup_any(links, ["Betting Card"])

    primary_href = live_href if is_active_today and live_href else (cards_href or fallback_href)
    primary_label = "Open Live Lens" if is_active_today and live_href else (f"Open {cards_label}" if cards_label else fallback_label)
    secondary_href = betting_href or cards_href or fallback_href
    secondary_label = f"Open {betting_label}" if betting_label else (f"Open {cards_label}" if cards_label else fallback_label)
    status_label = "Live lanes on" if is_active_today and live_href else "Pregame board"
    return {
        "eyebrow": "Game board",
        "title": "Live market view" if is_active_today and live_href else "Main card lane",
        "kicker": "Active games route through Live Lens" if is_active_today and live_href else "Pregame slate route",
        "summary": "Route active games through Live Lens first, then fall back to the main cards board for the full slate context."
        if is_active_today and live_href
        else "Lead with the main cards board, then use the betting-card lane for the pregame market read.",
        "status_label": status_label,
        "opportunity_tags": ["Live Lens", "Moneyline", "Spread", "Total"] if is_active_today and live_href else ["Cards", "Betting Card", "Moneyline", "Spread", "Total"],
        "primary_href": primary_href,
        "primary_label": primary_label,
        "secondary_href": secondary_href,
        "secondary_label": secondary_label,
        "items": [],
    }


def _choose_props_bar(links: list[dict[str, Any]], *, is_active_today: bool) -> dict[str, str | None]:
    live_href, _ = _link_lookup_any(links, ["Live Lens", "Live Prop Audit"])
    props_href, props_label = _link_lookup_any(links, ["Props", "Top props", "Prop Ladders", "Pitcher ladders", "Hitter ladders", "HR targets"])
    fallback_href, fallback_label = _link_lookup_any(links, ["Picks", "Season Review", "Betting Card", "Hub"])

    if is_active_today and live_href:
        return {
            "eyebrow": "Props board",
            "title": "Prop live lane",
            "kicker": "In-game prop checks for active slates",
            "summary": "When the slate is active, reuse the sport's live lane for in-game prop opportunity checks instead of sending users back to pregame ladders.",
            "status_label": "Live prop lens",
            "opportunity_tags": ["Prop Live Lens", "Live props", "Tracked props"],
            "primary_href": live_href,
            "primary_label": "Open Prop Live Lens",
            "secondary_href": props_href or fallback_href,
            "secondary_label": f"Open {props_label}" if props_label else (f"Open {fallback_label}" if fallback_label else None),
            "extra_links": [],
            "items": [],
        }

    if props_href:
        return {
            "eyebrow": "Props board",
            "title": props_label or "Props",
            "kicker": "Pregame props route",
            "summary": "Start from the sport's stored props or ladder lane, then jump to the broader module family only when you need adjacent views.",
            "status_label": "Pregame props",
            "opportunity_tags": [str(props_label or "Props"), "Pregame props"],
            "primary_href": props_href,
            "primary_label": f"Open {props_label}" if props_label else "Open Props",
            "secondary_href": fallback_href,
            "secondary_label": f"Open {fallback_label}" if fallback_label else None,
            "extra_links": [],
            "items": [],
        }

    return {
        "eyebrow": "Props board",
        "title": "Props migration gap",
        "kicker": "Fallback route until props parity lands",
        "summary": "This sport still needs a first-class props lane in Syndicate. Use the nearest migrated board for now.",
        "status_label": "Needs props lane",
        "opportunity_tags": ["Props gap", "Fallback lane"],
        "primary_href": fallback_href,
        "primary_label": f"Open {fallback_label}" if fallback_label else "Open Hub",
        "secondary_href": _link_lookup(links, "Hub") or fallback_href,
        "secondary_label": "Open Hub",
        "extra_links": [],
        "items": [],
    }


def _build_sport_overview(
    sport: dict[str, Any],
    today_value: str,
    *,
    force_refresh: bool = False,
    preserve_requested_date: bool = False,
) -> dict[str, Any]:
    slug = str(sport.get("slug") or "").strip().lower()
    cache_key = _sport_cache_key(slug, today_value)
    now = time.monotonic()
    cached = _HOME_OVERVIEW_CACHE.get(cache_key)
    if cached and not force_refresh and (now - cached[0]) < _HOME_OVERVIEW_TTL_SEC:
        return dict(cached[1])

    links: list[dict[str, Any]] = []
    context_label = today_value
    overview_stats: list[dict[str, str]] = []
    primary_href = str(sport.get("primary_href") or f"/{slug}")
    hub_href = f"/{slug}/hub"
    season: int | None = None
    selected_week: int | None = None

    if slug == "mlb":
        dates = available_daily_summary_dates()
        selected_date = _prefer_today_or_latest(dates, today_value, preserve_requested=preserve_requested_date)
        links = build_mlb_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/mlb?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Tracked dates", "value": str(len(dates))},
            {"label": "Focus", "value": "Cards + betting"},
        ]
    elif slug == "nba":
        dates = nba_available_dates()
        selected_date = _prefer_today_or_latest(dates, today_value, preserve_requested=preserve_requested_date)
        links = build_nba_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/nba?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Tracked dates", "value": str(len(dates))},
            {"label": "Focus", "value": "Cards + betting"},
        ]
    elif slug == "nhl":
        slates = nhl_slate_summaries()
        dates = [str(item.get("date") or "").strip() for item in slates if str(item.get("date") or "").strip()]
        selected_date = _prefer_today_or_latest(dates, today_value, preserve_requested=preserve_requested_date)
        links = build_nhl_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/nhl?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Tracked slates", "value": str(len(slates))},
            {"label": "Focus", "value": "Cards + betting"},
        ]
    elif slug == "wnba":
        dates = wnba_available_dates()
        selected_date = _prefer_today_or_latest(dates, today_value, preserve_requested=preserve_requested_date)
        links = build_wnba_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/wnba?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Tracked dates", "value": str(len(dates))},
            {"label": "Focus", "value": "Cards + betting"},
        ]
    elif slug == "nfl":
        season = nfl_latest_season()
        tracked = nfl_tracked_week() or {}
        selected_week = int(tracked.get("week") or nfl_default_week(season))
        links = build_nfl_module_links(selected_week, "Cards", season=season)
        context_label = f"{season} Week {selected_week}"
        primary_href = f"/nfl?season={season}&week={selected_week}"
        overview_stats = [
            {"label": "Season", "value": str(season)},
            {"label": "Week", "value": str(selected_week)},
            {"label": "Snapshots", "value": str(len(nfl_week_summaries()))},
        ]
    elif slug == "ncaaf":
        season = ncaaf_default_season()
        selected_week = ncaaf_default_week()
        weeks = [week for week in ncaaf_week_summaries() if bool(week.get("has_data"))]
        links = build_ncaaf_module_links(selected_week, "Cards", season=season)
        context_label = f"{season} Week {selected_week}"
        primary_href = f"/ncaaf?week={selected_week}"
        overview_stats = [
            {"label": "Season", "value": str(season)},
            {"label": "Week", "value": str(selected_week)},
            {"label": "Tracked weeks", "value": str(len(weeks))},
        ]
    elif slug == "ncaab":
        dates = ncaab_available_dates()
        selected_date = _prefer_today_or_latest(
            dates,
            today_value if preserve_requested_date else (ncaab_latest_date() or today_value),
            preserve_requested=preserve_requested_date,
        )
        links = build_ncaab_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/ncaab?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Season", "value": str(ncaab_season_for_date(selected_date))},
            {"label": "Tracked dates", "value": str(len(dates))},
        ]

    active_today = _is_active_today(slug, today_value, context_label)
    game_bar = _choose_game_bar(
        links,
        is_active_today=active_today,
        fallback_href=primary_href,
        fallback_label=str(sport.get("primary_label") or f"Open {sport.get('name') or slug.upper()} cards"),
    )
    props_bar = _choose_props_bar(links, is_active_today=active_today)
    if slug == "mlb":
        pitcher_top_props_href = _link_lookup(links, "Pitcher top props")
        hitter_top_props_href = _link_lookup(links, "Hitter top props")
        if active_today:
            if pitcher_top_props_href:
                props_bar["secondary_href"] = pitcher_top_props_href
                props_bar["secondary_label"] = "Open Pitcher Top Props"
            if hitter_top_props_href:
                props_bar["extra_links"] = [{"href": hitter_top_props_href, "label": "Open Hitter Top Props"}]
            props_bar["title"] = "Live props + top props"
            props_bar["summary"] = "Use Live Lens for in-game MLB props, then jump directly into the pitcher and hitter top-props lanes that mirror the standalone app's module split."
            props_bar["opportunity_tags"] = ["Live props", "Pitcher top props", "Hitter top props"]
        else:
            if pitcher_top_props_href:
                props_bar["primary_href"] = pitcher_top_props_href
                props_bar["primary_label"] = "Open Pitcher Top Props"
            if hitter_top_props_href:
                props_bar["secondary_href"] = hitter_top_props_href
                props_bar["secondary_label"] = "Open Hitter Top Props"
            props_bar["title"] = "Pitcher + hitter top props"
            props_bar["summary"] = "Mirror the standalone MLB pregame props structure by keeping pitcher and hitter top-props lanes distinct on the main Syndicate page."
            props_bar["opportunity_tags"] = ["Pitcher top props", "Hitter top props", "Pregame props"]
    game_items, game_count = _load_home_game_items(
        slug,
        context_label=context_label,
        season=season,
        week=selected_week,
        is_active_today=active_today,
    )
    home_games = _load_home_games(slug, context_label=context_label, season=season, week=selected_week, is_active_today=active_today) if active_today else []
    game_bar["items"] = game_items
    props_bar["items"] = _load_home_prop_items(
        slug,
        context_label=context_label,
        home_games=home_games,
        season=season,
        week=selected_week,
        is_active_today=active_today,
    )
    if game_bar["items"]:
        overview_stats = [{"label": "Games", "value": str(game_count)}] + overview_stats[1:]
    if props_bar["items"]:
        props_bar["summary"] = f"{len(props_bar['items'])} props surfaced from the best available {sport.get('name') or slug.upper()} live or stored props lane."
    else:
        if active_today:
            props_bar["status_label"] = "Live prop lens unavailable"
            props_bar["summary"] = "No prop rows were available from live, stored, or card-level fallback sources for this slate."
        else:
            props_bar["summary"] = "No prop rows were available from the current mirrored board payload for this slate."

    games_count = len(game_bar.get("items") or []) if isinstance(game_bar.get("items"), list) else 0
    overview = {
        **sport,
        "primary_href": primary_href,
        "hub_href": hub_href,
        "betting_href": _link_lookup(links, "Betting Card"),
        "context_label": context_label,
        "slate_label": "Live today" if active_today else "Scheduled board",
        "overview_stats": overview_stats,
        "feature_links": _secondary_links(links),
        "active_today": active_today,
        "show_on_home": active_today,
        "game_bar": game_bar,
        "props_bar": props_bar,
        "dashboard_games": home_games,
        "home_anchor": f"home-sport-{slug}",
        "games_count": games_count,
    }
    if slug == "mlb":
        overview["mlb_home"] = {
            "cards_href": f"/mlb/cards?date={context_label}&client=source",
            "cards_embed_src": f"/mlb/cards?date={context_label}&client=source&embed=home-cards",
            "live_lens_href": _link_lookup(links, "Live Lens") or f"/mlb/live-lens?date={context_label}",
            "betting_href": _link_lookup(links, "Betting Card"),
            "hub_href": hub_href,
            "hr_targets_href": _link_lookup(links, "HR targets") or f"/mlb/hr-targets?date={context_label}",
            "hr_targets_items": _load_mlb_home_hr_target_items(context_label, limit=10),
            "pregame_props_href": _link_lookup(links, "Pitcher top props") or f"/mlb/pitcher-top-props?date={context_label}",
            "pregame_props_secondary_href": _link_lookup(links, "Hitter top props") or f"/mlb/hitter-top-props?date={context_label}",
            "pregame_props_items": _load_home_prop_items(
                "mlb",
                context_label=context_label,
                home_games=[],
                season=season,
                week=selected_week,
                is_active_today=False,
            ),
            "live_props_href": _link_lookup(links, "Live Lens") or f"/mlb/live-lens?date={context_label}",
            "live_props_items": _load_home_prop_items(
                "mlb",
                context_label=context_label,
                home_games=home_games,
                season=season,
                week=selected_week,
                is_active_today=True,
            ),
        }
    props_count = _dashboard_prop_count(overview)
    overview["props_count"] = props_count
    overview["show_on_home"] = bool(active_today and games_count > 0)
    data_warnings: list[str] = []
    if active_today and games_count <= 0:
        data_warnings.append("No game rows surfaced")
    if props_count <= 0:
        data_warnings.append("No prop rows surfaced")
    overview["data_warnings"] = data_warnings
    overview["data_health"] = "healthy" if not data_warnings else ("stale" if active_today and games_count <= 0 else "partial")
    _HOME_OVERVIEW_CACHE[cache_key] = (time.monotonic(), overview)
    return dict(overview)


def build_home_overview(
    sports: list[dict[str, Any]],
    *,
    selected_date: str | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    today_value = str(selected_date or central_today_iso()).strip() or central_today_iso()
    preserve_requested_date = selected_date is not None
    sport_items = [sport for sport in sports if isinstance(sport, dict)]
    if len(sport_items) <= 1:
        overview = [
            _build_sport_overview(
                sport,
                today_value,
                force_refresh=force_refresh,
                preserve_requested_date=preserve_requested_date,
            )
            for sport in sport_items
        ]
    else:
        overview: list[dict[str, Any] | None] = [None] * len(sport_items)
        max_workers = min(4, len(sport_items))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _build_sport_overview,
                    sport,
                    today_value,
                    force_refresh=force_refresh,
                    preserve_requested_date=preserve_requested_date,
                ): index
                for index, sport in enumerate(sport_items)
            }
            for future, index in futures.items():
                try:
                    overview[index] = future.result()
                except Exception:
                    overview[index] = _build_sport_overview(
                        sport_items[index],
                        today_value,
                        force_refresh=force_refresh,
                        preserve_requested_date=preserve_requested_date,
                    )
        overview = [sport for sport in overview if isinstance(sport, dict)]
    active = [sport for sport in overview if bool(sport.get("show_on_home"))]
    return active


def _home_payload(*, selected_date: str | None = None, cached_only: bool = False, force_refresh: bool = False) -> dict[str, Any]:
    effective_date = str(selected_date or central_today_iso()).strip() or central_today_iso()
    cache_key = effective_date
    now = time.monotonic()
    cached = _HOME_PAYLOAD_CACHE.get(cache_key)
    if cached and not force_refresh and (cached_only or (now - cached[0]) < _HOME_OVERVIEW_TTL_SEC):
        return dict(cached[1])
    if cached_only:
        sports: list[dict[str, Any]] = []
        return {
            "sports": sports,
            "html": render_template("shared/_home_sport_stack.html", sports=sports),
            "polled_at": time.time(),
        }
    sports = current_app.config["SYNDICATE_SPORTS"]
    overview = build_home_overview(sports, selected_date=effective_date, force_refresh=force_refresh)
    polled_at = time.time()
    polled_label = _format_home_timestamp(polled_at)
    for sport in overview:
        if not isinstance(sport, dict):
            continue
        sport["freshness_label"] = f"Live \u00b7 {polled_label}" if bool(sport.get("active_today")) else "Stored slate"
    dashboard = _build_home_dashboard(overview, selected_date=effective_date, polled_at=polled_at)
    payload = {
        "sports": overview,
        "dashboard": dashboard,
        "selected_date": effective_date,
        "html": render_template("shared/_home_dashboard.html", sports=overview, dashboard=dashboard),
        "polled_at": polled_at,
    }
    _HOME_PAYLOAD_CACHE[cache_key] = (time.monotonic(), payload)
    return dict(payload)


@home_bp.get("/")
def home():
    payload = _home_payload(selected_date=request.args.get("date"))
    return render_template(
        "home.html",
        sports=payload["sports"],
        dashboard=payload["dashboard"],
        selected_home_date=payload.get("selected_date"),
        tracker_sports=current_app.config["SYNDICATE_SPORTS"],
        show_app_header=True,
        page_body_class="syndicate-home-page",
        page_shell_class="syndicate-home-shell",
    )


@home_bp.get("/api/home")
def api_home():
    payload = _home_payload(selected_date=request.args.get("date"), force_refresh=True)
    return jsonify(
        {
            "ok": True,
            "sports": payload["sports"],
            "dashboard": payload.get("dashboard"),
            "selected_date": payload.get("selected_date"),
            "html": payload["html"],
            "polled_at": payload["polled_at"],
        }
    )