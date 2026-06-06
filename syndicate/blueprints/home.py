from __future__ import annotations

import ast
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import os
import re
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import json

from flask import Blueprint, current_app, jsonify, render_template, request

from syndicate.features.mlb.ladders_common import build_module_links as build_mlb_module_links
from syndicate.features.mlb.sources import available_daily_summary_dates
from syndicate.features.mlb.sources import daily_top_props_path
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
_BASKETBALL_PLAYER_ID_CACHE: dict[str, dict[tuple[str, str], int]] = {}


def _public_version_payload() -> dict[str, str] | None:
    commit = str(
        os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
        or ""
    ).strip()
    branch = str(
        os.environ.get("RENDER_GIT_BRANCH")
        or os.environ.get("GIT_BRANCH")
        or ""
    ).strip()
    if not commit and not branch:
        return None
    payload: dict[str, str] = {}
    if commit:
        payload["commit"] = commit
    if branch:
        payload["branch"] = branch
    return payload


@home_bp.get("/healthz")
def healthz():
    payload: dict[str, Any] = {"ok": True, "service": "syndicate"}
    version = _public_version_payload()
    if version:
        payload["version"] = version
    return jsonify(payload)


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _sport_matchup(game: dict[str, Any]) -> str:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    away_label = str(away.get("abbr") or game.get("away_tri") or game.get("away_name") or "Away").strip()
    home_label = str(home.get("abbr") or game.get("home_tri") or game.get("home_name") or "Home").strip()
    return f"{away_label} @ {home_label}"


def _game_team_label(game: dict[str, Any], side: str) -> str | None:
    payload = game.get(side) if isinstance(game.get(side), dict) else {}
    value = (
        payload.get("abbr")
        or payload.get("name")
        or game.get(f"{side}_tri")
        or game.get(f"{side}_name")
        or game.get(side)
    )
    text = str(value or "").strip()
    return text or None


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


def _looks_terminal_status_text(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(
        token in lowered
        for token in (
            "final",
            "finished",
            "complete",
            "full time",
            "ft",
            "postponed",
            "cancelled",
            "canceled",
            "suspended",
        )
    )


def _nba_live_state_games(selected_date: str) -> list[dict[str, Any]]:
    try:
        from syndicate.features.nba.cards import build_live_state_payload

        payload = build_live_state_payload(selected_date, ttl=12, allow_stored_date_fallback=False)
    except Exception:
        return []
    rows = payload.get("games") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    games: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        away_label = _safe_text(row.get("away"), "Away")
        home_label = _safe_text(row.get("home"), "Home")
        games.append(
            {
                "gamePk": str(row.get("game_id") or "").strip() or f"{away_label}@{home_label}",
                "away": {"abbr": away_label, "name": away_label, "score": row.get("away_pts")},
                "home": {"abbr": home_label, "name": home_label, "score": row.get("home_pts")},
                "status": {
                    "abstract": str(row.get("status") or "").strip() or "Scheduled",
                    "detailed": str(row.get("status") or "").strip() or "Scheduled",
                    "in_progress": bool(row.get("in_progress")),
                    "final": bool(row.get("final")),
                },
                "live_state": dict(row),
                "detail": str(row.get("status") or "").strip() or selected_date,
                "summary": "NBA live-state fallback",
                "href": f"/nba/cards?date={selected_date}",
            }
        )
    return games


def _nba_has_live_games(selected_date: str) -> bool:
    return len(_nba_live_state_games(selected_date)) > 0


def _wnba_live_state_games(selected_date: str) -> list[dict[str, Any]]:
    try:
        from syndicate.features.wnba.cards import build_live_state_payload

        payload = build_live_state_payload(selected_date, ttl=12, allow_stored_date_fallback=False)
    except Exception:
        return []
    rows = payload.get("games") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    games: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        away_label = _safe_text(row.get("away"), "Away")
        home_label = _safe_text(row.get("home"), "Home")
        games.append(
            {
                "gamePk": str(row.get("game_id") or "").strip() or f"{away_label}@{home_label}",
                "event_id": row.get("event_id"),
                "away": {"abbr": away_label, "name": away_label, "score": row.get("away_pts")},
                "home": {"abbr": home_label, "name": home_label, "score": row.get("home_pts")},
                "status": {
                    "abstract": str(row.get("status") or "").strip() or "Scheduled",
                    "detailed": str(row.get("status") or "").strip() or "Scheduled",
                    "in_progress": bool(row.get("in_progress")),
                    "final": bool(row.get("final")),
                },
                "live_state": dict(row),
                "detail": str(row.get("status") or "").strip() or selected_date,
                "summary": "WNBA live-state fallback",
                "href": f"/wnba/cards?date={selected_date}",
            }
        )
    return games


def _wnba_has_live_games(selected_date: str) -> bool:
    return len(_wnba_live_state_games(selected_date)) > 0


def _mlb_schedule_fallback_games(selected_date: str) -> list[dict[str, Any]]:
    try:
        with urlopen(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={selected_date}", timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    dates = payload.get("dates") if isinstance(payload, dict) else []
    if not isinstance(dates, list) or not dates:
        return []
    events = dates[0].get("games") if isinstance(dates[0], dict) else []
    if not isinstance(events, list):
        return []
    games: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        teams = event.get("teams") if isinstance(event.get("teams"), dict) else {}
        away = teams.get("away") if isinstance(teams.get("away"), dict) else {}
        home = teams.get("home") if isinstance(teams.get("home"), dict) else {}
        away_team = away.get("team") if isinstance(away.get("team"), dict) else {}
        home_team = home.get("team") if isinstance(home.get("team"), dict) else {}
        away_abbr = _safe_text(away_team.get("abbreviation") or away_team.get("name"), "Away")
        home_abbr = _safe_text(home_team.get("abbreviation") or home_team.get("name"), "Home")
        game_pk = int(event.get("gamePk") or 0)
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        games.append(
            {
                "gamePk": game_pk,
                "away": {
                    "abbr": away_abbr,
                    "name": _safe_text(away_team.get("name"), away_abbr),
                    "score": away.get("score"),
                },
                "home": {
                    "abbr": home_abbr,
                    "name": _safe_text(home_team.get("name"), home_abbr),
                    "score": home.get("score"),
                },
                "status": {
                    "abstract": _safe_text(status.get("abstractGameState"), "Scheduled"),
                    "detailed": _safe_text(status.get("detailedState"), "Scheduled"),
                },
                "scheduled_start_utc": event.get("gameDate"),
                "detail": _safe_text(status.get("detailedState"), selected_date),
                "summary": "MLB schedule fallback",
                "href": f"/mlb/game/{game_pk}?date={selected_date}" if game_pk else f"/mlb/cards?date={selected_date}",
                "href_label": "Open MLB game",
            }
        )
    return games


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

    is_live = bool(game.get("shared_is_live") or status.get("is_live") or status.get("in_progress") or live_state.get("in_progress"))
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

    # If the game start is well in the past but source status is still a placeholder,
    # force terminal handling so home cards do not remain stuck on "Scheduled".
    scheduled_dt = _central_scheduled_datetime(game)
    if not is_live and not is_final and scheduled_dt is not None and not _looks_terminal_status_text(raw_status_line):
        now_central = datetime.now(CENTRAL_TIMEZONE)
        if scheduled_dt <= now_central - timedelta(hours=3):
            is_final = True

    status_badge = raw_status_badge
    status_line = raw_status_line
    if not is_live and not is_final:
        if raw_status_badge.lower() in {"processed artifact", "tracked", "stored slate lens"}:
            status_badge = "Scheduled"
        status_line = _scheduled_status_line(game, raw_status_line)
    elif is_final and not _looks_terminal_status_text(raw_status_line):
        status_badge = "Final"
        status_line = "Final update pending"
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


def _split_matchup_labels(value: Any) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    parts = re.split(r"\s+(?:@|vs\.?|v|at)\s+", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None, None
    away_label = parts[0].strip() or None
    home_label = parts[1].strip() or None
    return away_label, home_label


def _logo_from_team_label(slug: str, team_label: str | None) -> str | None:
    text = str(team_label or "").strip()
    if not text:
        return None
    try:
        if slug == "nba":
            from syndicate.features.nba.cards import _nba_logo_url

            return _nba_logo_url(text.upper())
        if slug == "wnba":
            from syndicate.features.wnba.cards import _source_logo_url

            logo = _source_logo_url(text.upper())
            return str(logo or "").strip() or None
        if slug == "nhl":
            from syndicate.features.nhl.sources import team_logo_url

            return team_logo_url(text.upper())
        if slug == "mlb":
            from syndicate.features.mlb.cards import _MLB_TEAM_META_BY_ABBR
            from syndicate.features.mlb.cards import _mlb_logo_url

            meta = _MLB_TEAM_META_BY_ABBR.get(text.upper()) or {}
            team_id = meta.get("team_id") if meta.get("team_id") is not None else meta.get("id")
            if team_id is None:
                return None
            return _mlb_logo_url(int(team_id))
    except Exception:
        return None
    return None


def _pill_value_text(value: Any) -> str | None:
    text = _prop_metric_text(value)
    if not text:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?%)", text)
    if match:
        return match.group(1)
    return text


def _is_placeholder_team_label(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return text in {"opp", "opponent", "home", "away", "team", "unknown"}


def _normalized_prop_lookup_key(*parts: Any) -> str:
    values = [re.sub(r"\s+", " ", str(part or "").strip().lower()) for part in parts]
    return "|".join(value for value in values if value)


def _home_prop_game_index(home_games: list[dict[str, Any]] | None) -> dict[str, dict[Any, dict[str, Any]]]:
    by_pk: dict[Any, dict[str, Any]] = {}
    by_labels: dict[Any, dict[str, Any]] = {}
    by_team: dict[Any, dict[str, Any]] = {}
    for game in home_games or []:
        if not isinstance(game, dict):
            continue
        game_pk = _int_or_none(game.get("gamePk") or game.get("game_pk") or game.get("game_id"))
        if game_pk is not None:
            by_pk[game_pk] = game
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_label = str(away.get("abbr") or away.get("name") or game.get("away_tri") or game.get("away_name") or "").strip()
        home_label = str(home.get("abbr") or home.get("name") or game.get("home_tri") or game.get("home_name") or "").strip()
        if away_label or home_label:
            by_labels[_normalized_prop_lookup_key(away_label, home_label)] = game
        for team_label in (away_label, home_label):
            if not team_label or _is_placeholder_team_label(team_label):
                continue
            by_team.setdefault(_normalized_prop_lookup_key(team_label), game)
        matchup = str(game.get("matchup") or _sport_matchup(game)).strip()
        if matchup:
            parsed_away, parsed_home = _split_matchup_labels(matchup)
            by_labels[_normalized_prop_lookup_key(parsed_away, parsed_home)] = game
            for team_label in (parsed_away, parsed_home):
                if not team_label or _is_placeholder_team_label(team_label):
                    continue
                by_team.setdefault(_normalized_prop_lookup_key(team_label), game)
    return {"by_pk": by_pk, "by_labels": by_labels, "by_team": by_team}


def _home_prop_matched_game(item: dict[str, Any], game_index: dict[str, dict[Any, dict[str, Any]]]) -> dict[str, Any] | None:
    game_pk = _int_or_none(item.get("game_pk") or item.get("gamePk") or item.get("game_id"))
    if game_pk is not None:
        matched = (game_index.get("by_pk") or {}).get(game_pk)
        if isinstance(matched, dict):
            return matched
    away_label = str(item.get("away_label") or item.get("team") or "").strip()
    home_label = str(item.get("home_label") or item.get("opponent") or "").strip()
    if away_label or home_label:
        matched = (game_index.get("by_labels") or {}).get(_normalized_prop_lookup_key(away_label, home_label))
        if isinstance(matched, dict):
            return matched
    matchup = str(item.get("matchup") or "").strip()
    parsed_away, parsed_home = _split_matchup_labels(matchup)
    if parsed_away or parsed_home:
        matched = (game_index.get("by_labels") or {}).get(_normalized_prop_lookup_key(parsed_away, parsed_home))
        if isinstance(matched, dict):
            return matched
    for team_label in [
        item.get("team"),
        item.get("opponent"),
        item.get("away_label"),
        item.get("home_label"),
        parsed_away,
        parsed_home,
    ]:
        if _is_placeholder_team_label(team_label):
            continue
        matched = (game_index.get("by_team") or {}).get(_normalized_prop_lookup_key(team_label))
        if isinstance(matched, dict):
            return matched
    return None


def _display_prop_market_label(value: Any) -> str:
    raw_text = re.sub(r"[_/]+", " ", str(value or "").strip())
    raw_text = re.sub(r"\s+", " ", raw_text).strip()
    lowered = raw_text.lower()
    while True:
        stripped = False
        for prefix in ("batter ", "hitter ", "pitcher ", "player "):
            if lowered.startswith(prefix):
                raw_text = raw_text[len(prefix):].strip()
                lowered = raw_text.lower()
                stripped = True
                break
        if not stripped:
            break
    replacements = {
        "batter hits": "Hits",
        "batter total bases": "Total Bases",
        "batter runs scored": "Runs Scored",
        "batter rbi": "RBI",
        "batter rbis": "RBI",
        "hits": "Hits",
        "total bases": "Total Bases",
        "runs scored": "Runs Scored",
        "rbis": "RBI",
        "rbi": "RBI",
        "outs": "Outs",
        "strikeouts": "Strikeouts",
        "hits allowed": "Hits Allowed",
        "walks allowed": "Walks Allowed",
        "earned runs": "Earned Runs",
        "pts": "PTS",
        "points": "Points",
        "reb": "REB",
        "rebounds": "Rebounds",
        "ast": "AST",
        "assists": "Assists",
        "pra": "PRA",
        "pr": "PTS+REB",
        "pa": "PTS+AST",
        "ra": "REB+AST",
        "threes": "3PM",
        "points rebounds assists": "Points + Rebounds + Assists",
        "points rebounds": "Points + Rebounds",
        "points assists": "Points + Assists",
        "rebounds assists": "Rebounds + Assists",
        "three pointers made": "3PT Made",
        "threes made": "3PT Made",
        "shots on goal": "Shots on Goal",
        "saves": "Saves",
    }
    if lowered in replacements:
        return replacements[lowered]
    tokens: list[str] = []
    for token in raw_text.split():
        upper = token.upper()
        if upper in {"RBI", "PRA", "PTS", "REB", "AST", "3PT", "3PM", "SOG"}:
            tokens.append(upper)
        else:
            tokens.append(token.capitalize())
    return " ".join(tokens) or "Prop"


def _display_prop_title_parts(name: Any, market_label: str) -> tuple[str, str]:
    raw_name = re.sub(r"\s+", " ", str(name or "").strip()) or "Prop"
    player_name = raw_name
    market_suffix = re.search(r"^(?P<player>.+?)\s+(?:Batter|Hitter|Pitcher|Player)[ _].+$", raw_name)
    if market_suffix:
        player_name = market_suffix.group("player").strip() or raw_name
    title = player_name
    if market_label and market_label.lower() not in title.lower():
        title = f"{title} {market_label}".strip()
    return player_name, title


def _home_prop_status_display(item: dict[str, Any], matched_game: dict[str, Any] | None) -> str | None:
    if isinstance(matched_game, dict):
        scoreboard = _scoreboard_state(matched_game)
        liveish = _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line"))
        if scoreboard.get("has_scores"):
            score_text = f"{scoreboard.get('away_score')}-{scoreboard.get('home_score')}"
            if liveish:
                return f"{score_text} | {scoreboard.get('status_line')}"
            if str(scoreboard.get("status_badge") or "").strip().lower() == "final":
                return f"{score_text} | Final"
        return _safe_text(scoreboard.get("status_line"), None)
    return _safe_text(item.get("game_state"), None)


def _home_prop_live_total(item: dict[str, Any], matched_game: dict[str, Any] | None) -> str | None:
    liveish = bool(item.get("is_live"))
    finalish = False
    if isinstance(matched_game, dict):
        scoreboard = _scoreboard_state(matched_game)
        liveish = liveish or _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line"))
        finalish = str(scoreboard.get("status_badge") or "").strip().lower() == "final"
    if not liveish and not finalish:
        return None
    actual_total = _prop_metric_text(
        item.get("actual")
        if item.get("actual") not in {None, "", "-"}
        else (item.get("actual_value") if item.get("actual_value") not in {None, "", "-"} else item.get("actual_so_far"))
    )
    if actual_total and actual_total != "-":
        return actual_total
    return None


def _home_prop_stat_suffix(market_label: str | None) -> str | None:
    lowered = str(market_label or "").strip().lower()
    if not lowered:
        return None
    mapping = {
        "hits allowed": "H",
        "hits": "H",
        "total bases": "TB",
        "runs scored": "R",
        "rbi": "RBI",
        "outs": "Outs",
        "strikeouts": "K",
        "walks allowed": "BB",
        "earned runs": "ER",
        "home runs": "HR",
        "points rebounds assists": "PRA",
        "points rebounds": "PR",
        "points assists": "PA",
        "rebounds assists": "RA",
        "points": "Pts",
        "rebounds": "Reb",
        "assists": "Ast",
        "three pointers made": "3PM",
        "threes made": "3PM",
        "3pt made": "3PM",
        "shots on goal": "SOG",
        "saves": "Saves",
        "goals": "Goals",
        "blocks": "Blk",
        "steals": "Stl",
    }
    return mapping.get(lowered, market_label)


def _home_prop_metric_line(raw_value: Any, market_label: str | None) -> str | None:
    metric = _prop_metric_text(raw_value)
    if not metric or metric == "-":
        return None
    if re.search(r"[A-Za-z]", metric):
        return metric
    suffix = _home_prop_stat_suffix(market_label)
    return f"{metric} {suffix}".strip() if suffix else metric


def _home_prop_hero_metrics(item: dict[str, Any]) -> tuple[str | None, str | None]:
    market_label = _safe_text(item.get("market_display") or item.get("market"), None)
    live_box = _home_prop_metric_line(item.get("actual"), market_label)
    if not live_box:
        live_box = _home_prop_metric_line(item.get("live_total"), market_label)

    sim_box = _home_prop_metric_line(
        item.get("projected") if item.get("projected") not in {None, "", "-"} else item.get("live_projection"),
        market_label,
    )
    if not sim_box:
        sim_box = _home_prop_metric_line(item.get("line") or item.get("market_line"), market_label)
    return live_box, sim_box


def _home_prop_writeup(item: dict[str, Any], *, player_name: str, market_label: str) -> str:
    raw_writeup = str(item.get("writeup") or "").strip()
    if raw_writeup and "_" not in raw_writeup:
        return raw_writeup
    pick = _safe_text(item.get("pick") or item.get("selection"), "Play")
    line = _prop_metric_text(item.get("line") or item.get("market_line"))
    base_sentence = f"{'Live lean' if item.get('is_live') else 'Recommended'} {pick} for {player_name} {market_label}".strip()
    if line and line != "-":
        base_sentence = f"{base_sentence} at {line}."
    else:
        base_sentence = f"{base_sentence}."
    detail = str(item.get("detail") or item.get("summary") or "").strip()
    detail_tail = detail.split("|", 1)[1].strip() if "|" in detail else ""
    if detail_tail:
        return f"{base_sentence} {detail_tail.rstrip('.')} .".replace(" .", ".")
    confidence = _safe_text(item.get("confidence"), None)
    raw_value = _safe_text(item.get("value"), None)
    edge = _safe_text(item.get("edge"), None)
    if not edge and raw_value and "win" not in raw_value.lower():
        edge = raw_value
    if confidence and edge:
        return f"{base_sentence} Model gives {confidence} win probability with {edge} edge."
    if confidence:
        return f"{base_sentence} Model gives {confidence} win probability."
    return base_sentence


def _home_prop_ladder_groups(item: dict[str, Any]) -> list[dict[str, Any]]:
    groups = item.get("ladder_groups") if isinstance(item.get("ladder_groups"), list) else []
    normalized: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        label = str(group.get("short_label") or group.get("label") or group.get("stat") or "").strip()
        targets = [int(total) for total in (group.get("targets") or []) if _int_or_none(total) is not None]
        if not label or not targets:
            continue
        normalized.append({"label": label, "targets": sorted(dict.fromkeys(targets))})
    return normalized


def _home_prop_display_pills(item: dict[str, Any], *, live_total: str | None) -> list[str]:
    live_flag = bool(item.get("is_live")) or _is_liveish(item.get("heading"), item.get("status_display"))
    values: list[str] = []
    market_label = _safe_text(item.get("market_display") or item.get("market"), None)
    stat_suffix = _home_prop_stat_suffix(market_label)
    for label, raw_value in [
        ("Line", item.get("line")),
        ("Odds", item.get("odds")),
        ("Sim%", item.get("confidence") or item.get("value")),
        (f"Pregame {stat_suffix or 'Proj'} Proj", _home_prop_metric_line(item.get("projected"), market_label)),
        (f"Live {stat_suffix or 'Total'} Total", _home_prop_metric_line(live_total, market_label) if live_flag else None),
        (f"Live {stat_suffix or 'Proj'} Proj", _home_prop_metric_line(item.get("live_projection"), market_label) if live_flag else None),
    ]:
        value = _pill_value_text(raw_value)
        if value and value != "-":
            values.append(f"{label} {value}")
    for group in _home_prop_ladder_groups(item):
        target_label = "/".join(str(total) for total in (group.get("targets") or []))
        if target_label:
            values.append(f"Ladder {group.get('label')} {target_label}")
    return values


def _finalize_home_prop_rows(rows: list[dict[str, Any]], *, slug: str, context_label: str | None = None, home_games: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    actual_cache: dict[int, dict[str, Any] | None] = {}
    game_index = _home_prop_game_index(home_games)
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        game_pk = _int_or_none(item.get("game_pk") or item.get("gamePk") or item.get("game_id"))
        matchup = str(item.get("matchup") or "").strip()
        away_label = str(item.get("away_label") or "").strip() or None
        home_label = str(item.get("home_label") or "").strip() or None
        away_label = away_label or _safe_text(item.get("team"), None)
        home_label = home_label or _safe_text(item.get("opponent"), None)
        parsed_away, parsed_home = _split_matchup_labels(matchup)
        away_label = away_label or parsed_away
        home_label = home_label or parsed_home
        matched_game = _home_prop_matched_game(item, game_index)
        if isinstance(matched_game, dict):
            matched_away = matched_game.get("away") if isinstance(matched_game.get("away"), dict) else {}
            matched_home = matched_game.get("home") if isinstance(matched_game.get("home"), dict) else {}
            matched_away_label = str(matched_away.get("abbr") or matched_away.get("name") or matched_game.get("away_tri") or matched_game.get("away_name") or "").strip() or None
            matched_home_label = str(matched_home.get("abbr") or matched_home.get("name") or matched_game.get("home_tri") or matched_game.get("home_name") or "").strip() or None
            if matched_away_label and matched_home_label:
                away_label = matched_away_label
                home_label = matched_home_label
        away_logo = str(item.get("away_logo") or item.get("team_logo_url") or "").strip() or None
        home_logo = str(item.get("home_logo") or item.get("opponent_logo_url") or "").strip() or None
        if isinstance(matched_game, dict):
            away_logo = away_logo or _team_logo(matched_game, "away")
            home_logo = home_logo or _team_logo(matched_game, "home")
        away_logo = away_logo or _logo_from_team_label(slug, away_label)
        home_logo = home_logo or _logo_from_team_label(slug, home_label)
        if not isinstance(item.get("pills"), list):
            pills: list[dict[str, str]] = []
            for label, raw_value in [
                ("Line", item.get("line")),
                ("Sim", item.get("confidence")),
                ("Odds", item.get("odds")),
            ]:
                value = _pill_value_text(raw_value)
                if value:
                    pills.append({"label": label, "value": value})
            item["pills"] = pills
        if not item.get("writeup"):
            item["writeup"] = _safe_text(item.get("detail") or item.get("summary"), "No prop summary available.")
        if not item.get("headshot_url") and slug in {"nba", "wnba"}:
            resolved_player_id = _basketball_resolve_player_id(
                slug,
                player_name=item.get("player_name") or item.get("name"),
                team_tri=item.get("team") or away_label or home_label,
                player_id=item.get("player_id"),
            )
            headshot_url = _basketball_best_headshot_url(player_id=resolved_player_id, photo=item.get("photo"))
            if headshot_url:
                item["headshot_url"] = headshot_url
                item["photo"] = headshot_url
        item["away_label"] = away_label
        item["home_label"] = home_label
        item["away_logo"] = away_logo
        item["home_logo"] = home_logo

        market_label = _display_prop_market_label(item.get("market") or item.get("name"))
        player_name, display_name = _display_prop_title_parts(item.get("name"), market_label)
        item["name"] = display_name
        item["market_display"] = market_label
        item["player_name"] = player_name
        item["meta_line"] = _safe_text(
            " ".join(part for part in [str(item.get("pick") or "").strip().upper(), _prop_metric_text(item.get("line") or item.get("market_line")) or ""] if part).strip(),
            _safe_text(item.get("detail"), None),
        )
        item["status_display"] = _home_prop_status_display(item, matched_game)
        if isinstance(matched_game, dict):
            scoreboard = _scoreboard_state(matched_game)
            item["is_live"] = bool(item.get("is_live")) or _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line"))

        if slug == "mlb" and game_pk is not None and context_label:
            actual_payload = _mlb_actual_payload_for_game(context_label, int(game_pk), actual_cache)
            if not item.get("headshot_url"):
                headshot_url = _mlb_headshot_from_actual_payload(item.get("player_name") or item.get("name"), actual_payload)
                if headshot_url:
                    item["headshot_url"] = headshot_url
                    item["photo"] = headshot_url
            final_state = _mlb_actual_payload_is_final(actual_payload)
            actual_value = _mlb_prop_actual_value(item, actual_payload)
            if actual_value is not None:
                item["actual"] = _score_value(actual_value)
            selection = str(item.get("pick") or item.get("selection") or "").strip().lower()
            line_value = _numeric_value(item.get("line") or item.get("market_line"))
            state = _mlb_prop_result_state(
                actual_value=actual_value,
                line_value=line_value,
                selection=selection,
                final_state=final_state,
                is_hr_target=str(item.get("heading") or "").strip().lower() == "hr targets",
            )
            if state:
                item["outcome_state"] = state
                item["outcome_label"] = _mlb_prop_result_label(state)
            if actual_payload:
                live_total = _mlb_live_total_text(actual_payload)
                if live_total:
                    item["live_total"] = live_total
        item["live_total"] = _home_prop_live_total(item, matched_game) or _safe_text(item.get("live_total"), None)
        item["writeup"] = _home_prop_writeup(item, player_name=player_name, market_label=market_label)
        item["display_pills"] = _home_prop_display_pills(item, live_total=item.get("live_total"))
        matchup_summary = " at ".join(part for part in [away_label, home_label] if part)
        item["matchup_summary"] = matchup_summary or _safe_text(item.get("matchup"), None)
        status_context = _safe_text(item.get("status_display"), None)
        if status_context and status_context == item.get("matchup_summary"):
            status_context = None
        item["status_context"] = status_context
        hero_live_box, hero_sim_box = _home_prop_hero_metrics(item)
        item["hero_live_box"] = hero_live_box
        item["hero_sim_box"] = hero_sim_box
        finalized.append(item)
    return finalized


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


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _mlb_actual_payload_for_game(context_label: str, game_pk: int, cache: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    if game_pk in cache:
        return cache[game_pk]
    try:
        path = raw_feed_live_path(context_label, int(game_pk))
        payload = load_json_or_gz_file(path)
    except Exception:
        payload = None
    cache[game_pk] = payload if isinstance(payload, dict) else None
    return cache[game_pk]


def _mlb_actual_payload_is_final(actual_payload: dict[str, Any] | None) -> bool:
    if not isinstance(actual_payload, dict):
        return False
    status = (actual_payload.get("gameData") or {}).get("status") if isinstance(actual_payload.get("gameData"), dict) else {}
    abstract = str((status or {}).get("abstractGameState") or "").strip().lower()
    detailed = str((status or {}).get("detailedState") or "").strip().lower()
    return abstract == "final" or detailed in {"final", "game over", "completed"}


def _mlb_name_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _mlb_headshot_from_actual_payload(player_name: Any, actual_payload: dict[str, Any] | None) -> str | None:
    target_name = _mlb_name_key(player_name)
    if not target_name or not isinstance(actual_payload, dict):
        return None
    try:
        from syndicate.features.mlb.cards import _mlb_headshot_url
    except Exception:
        return None

    boxscore = (actual_payload.get("liveData") or {}).get("boxscore") if isinstance(actual_payload.get("liveData"), dict) else {}
    teams = boxscore.get("teams") if isinstance(boxscore, dict) else {}
    for side in ("away", "home"):
        team = teams.get(side) if isinstance(teams, dict) else {}
        players = team.get("players") if isinstance(team, dict) else {}
        if not isinstance(players, dict):
            continue
        for player_obj in players.values():
            if not isinstance(player_obj, dict):
                continue
            person = player_obj.get("person") if isinstance(player_obj.get("person"), dict) else {}
            if _mlb_name_key(person.get("fullName")) != target_name:
                continue
            return _mlb_headshot_url(_int_or_none(person.get("id")))
    return None


def _basketball_headshot_url(player_id: Any) -> str | None:
    pid = _int_or_none(player_id)
    if pid is None:
        return None
    return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png"


def _basketball_espn_headshot_url(player_id: Any) -> str | None:
    pid = _int_or_none(player_id)
    if pid is None:
        return None
    return f"https://a.espncdn.com/i/headshots/nba/players/full/{pid}.png"


def _basketball_best_headshot_url(*, player_id: Any = None, photo: Any = None) -> str | None:
    photo_url = str(photo or "").strip() or None
    return _basketball_headshot_url(player_id) or photo_url or _basketball_espn_headshot_url(player_id)


def _basketball_canonical_team(sport_slug: str, team_tri: Any) -> str:
    raw_value = str(team_tri or "").strip().upper()
    if not raw_value:
        return ""
    try:
        if sport_slug == "nba":
            from syndicate.features.nba.cards import _canonical_nba_tri

            return _canonical_nba_tri(raw_value)
        if sport_slug == "wnba":
            from syndicate.features.wnba.cards import _canonical_wnba_tri

            return _canonical_wnba_tri(raw_value)
    except Exception:
        return raw_value
    return raw_value


def _basketball_player_id_index(sport_slug: str) -> dict[tuple[str, str], int]:
    cached = _BASKETBALL_PLAYER_ID_CACHE.get(sport_slug)
    if cached is not None:
        return cached

    index: dict[tuple[str, str], int] = {}
    try:
        if sport_slug == "nba":
            from syndicate.features.nba.sources import processed_path

            player_ids_path = processed_path("player_ids.csv")
            if player_ids_path.exists():
                with player_ids_path.open("r", encoding="utf-8", newline="") as handle:
                    for row in csv.DictReader(handle):
                        name_key = _mlb_name_key(row.get("player_name") or row.get("PLAYER_NAME"))
                        player_id = _int_or_none(row.get("player_id") or row.get("PLAYER_ID"))
                        team_key = _basketball_canonical_team(sport_slug, row.get("team") or row.get("TEAM_ABBREVIATION"))
                        if not name_key or player_id is None:
                            continue
                        if team_key:
                            index[(team_key, name_key)] = player_id
                        index.setdefault(("", name_key), player_id)
        elif sport_slug == "wnba":
            from syndicate.features.wnba.sources import processed_path

            processed_root = processed_path("boxscores_placeholder.csv").parent
            for boxscore_path in sorted(processed_root.glob("boxscores_*.csv"), reverse=True):
                with boxscore_path.open("r", encoding="utf-8", newline="") as handle:
                    for row in csv.DictReader(handle):
                        name_key = _mlb_name_key(row.get("player_name") or row.get("PLAYER_NAME"))
                        player_id = _int_or_none(row.get("player_id") or row.get("PLAYER_ID"))
                        team_key = _basketball_canonical_team(sport_slug, row.get("team") or row.get("TEAM_ABBREVIATION"))
                        if not name_key or player_id is None:
                            continue
                        if team_key:
                            index.setdefault((team_key, name_key), player_id)
                        index.setdefault(("", name_key), player_id)
    except Exception:
        index = {}

    _BASKETBALL_PLAYER_ID_CACHE[sport_slug] = index
    return index


def _basketball_resolve_player_id(sport_slug: str, *, player_name: Any, team_tri: Any = None, player_id: Any = None) -> int | None:
    resolved_player_id = _int_or_none(player_id)
    if resolved_player_id is not None:
        return resolved_player_id
    name_key = _mlb_name_key(player_name)
    if not name_key:
        return None
    team_key = _basketball_canonical_team(sport_slug, team_tri)
    index = _basketball_player_id_index(sport_slug)
    if team_key:
        by_team = index.get((team_key, name_key))
        if by_team is not None:
            return by_team
    return index.get(("", name_key))


def _player_name_from_prop_title(title: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    if not text:
        return None
    match = re.match(r"^(?P<player>.+?)\s+(?:Over|Under)\s+[+-]?\d", text, flags=re.IGNORECASE)
    if match:
        return match.group("player").strip() or None
    return None


def _mlb_prop_result_state(*, actual_value: float | None, line_value: float | None, selection: str, final_state: bool, is_hr_target: bool = False) -> str | None:
    if actual_value is None:
        return None
    if is_hr_target:
        if float(actual_value) >= 1.0:
            return "hit"
        return "miss" if final_state else None
    if line_value is None:
        return "hit" if float(actual_value) > 0.0 and final_state else None
    pick = str(selection or "").strip().lower()
    if pick == "over":
        if float(actual_value) > float(line_value):
            return "hit"
        return "miss" if final_state and float(actual_value) < float(line_value) else None
    if pick == "under":
        if float(actual_value) < float(line_value):
            return "hit"
        return "miss" if final_state and float(actual_value) > float(line_value) else None
    if final_state:
        return "hit" if float(actual_value) > float(line_value) else "miss"
    return None


def _mlb_prop_result_label(state: str | None) -> str | None:
    if state == "hit":
        return "Hit"
    if state == "miss":
        return "Miss"
    return None


def _mlb_prop_actual_value(item: dict[str, Any], actual_payload: dict[str, Any] | None) -> float | None:
    if not isinstance(item, dict) or not isinstance(actual_payload, dict):
        return None
    try:
        from syndicate.features.mlb.cards import _actual_batting_context_by_name
        from syndicate.features.mlb.cards import _actual_hitter_stat_value
        from syndicate.features.mlb.cards import _actual_pitcher_stat_value
    except Exception:
        return None

    batting_rows = _actual_batting_context_by_name(actual_payload)
    pitching_rows = None
    name = _mlb_name_key(item.get("name") or item.get("player_name") or item.get("playerName"))
    if not name:
        return None

    market_text = " ".join(
        str(value or "").lower()
        for value in [item.get("market"), item.get("heading"), item.get("market_label"), item.get("detail")]
    )
    prop_key = None
    pitcher_mode = False
    if "outs" in market_text:
        prop_key = "outs"
        pitcher_mode = True
    elif "strikeout" in market_text or market_text.startswith("k"):
        prop_key = "strikeouts"
        pitcher_mode = True
    elif "hits allowed" in market_text:
        prop_key = "hits_allowed"
        pitcher_mode = True
    elif "walk" in market_text:
        prop_key = "walks_allowed"
        pitcher_mode = True
    elif "earned run" in market_text:
        prop_key = "earned_runs"
        pitcher_mode = True
    elif "home run" in market_text or str(item.get("heading") or "").strip().lower() == "hr targets":
        prop_key = "home_runs"
    elif "total base" in market_text:
        prop_key = "total_bases"
    elif "run scored" in market_text:
        prop_key = "runs_scored"
    elif "rbi" in market_text:
        prop_key = "rbis"
    elif "hit" in market_text:
        prop_key = "hits"

    actual_row = batting_rows.get(name)
    if actual_row and not pitcher_mode:
        return _actual_hitter_stat_value(actual_row.get("stats") if isinstance(actual_row, dict) else None, prop_key or "hits")

    try:
        from syndicate.features.mlb.cards import _actual_pitching_context_by_name
    except Exception:
        return None
    pitching_rows = _actual_pitching_context_by_name(actual_payload)
    actual_row = pitching_rows.get(name)
    if actual_row and pitcher_mode:
        return _actual_pitcher_stat_value(actual_row.get("stats") if isinstance(actual_row, dict) else None, prop_key or "outs")
    return None


def _mlb_live_total_text(actual_payload: dict[str, Any] | None) -> str | None:
    if not isinstance(actual_payload, dict):
        return None
    linescore = ((actual_payload.get("liveData") or {}).get("linescore")) if isinstance(actual_payload.get("liveData"), dict) else {}
    teams = (linescore or {}).get("teams") if isinstance(linescore, dict) else {}
    away_runs = _numeric_value(((teams or {}).get("away") or {}).get("runs"))
    home_runs = _numeric_value(((teams or {}).get("home") or {}).get("runs"))
    if away_runs is None or home_runs is None:
        return None
    return _score_value(float(away_runs) + float(home_runs))


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


def _append_game_bet_candidate(candidates: list[dict[str, Any]], *, sport: dict[str, Any], game: dict[str, Any], market: str, pick: str, line: Any = None, odds: Any = None, edge: Any = None, confidence: Any = None, projected: Any = None, live_projection: Any = None, detail: str | None = None, fallback_epoch: float) -> None:
    pick_text = _safe_text(pick, "-")
    if pick_text == "-":
        return
    line_text = _prop_metric_text(line) if line is not None else None
    odds_text = _prop_metric_text(odds) if odds is not None else None
    edge_text = _pct_text(edge) if edge is not None and _numeric_value(edge) is not None else _safe_text(edge, "-") if edge is not None else "-"
    confidence_text = _pct_text(confidence) if confidence is not None and _numeric_value(confidence) is not None else _safe_text(confidence, "-") if confidence is not None else "-"
    projected_text = _prop_metric_text(projected) if projected is not None else "-"
    live_projection_text = _prop_metric_text(live_projection) if live_projection is not None else "-"
    is_live = bool(game.get("shared_is_live") or _is_liveish(game.get("status"), game.get("detail")) or "live" in _safe_text(market, "").lower())
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
            "is_live": is_live,
            "line": line_text or "-",
            "odds": odds_text or "-",
            "edge": edge_text,
            "confidence": confidence_text,
            "projected": projected_text,
            "live_projection": live_projection_text,
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
            projected=row.get("projected") if row.get("projected") is not None else row.get("projection") if row.get("projection") is not None else row.get("model") if row.get("model") is not None else row.get("mean"),
            live_projection=row.get("live_projection") if row.get("live_projection") is not None else row.get("liveProjection") if row.get("liveProjection") is not None else row.get("live_proj") if row.get("live_proj") is not None else row.get("projected_live"),
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
                projected=market.get("projected") if market.get("projected") is not None else market.get("projection") if market.get("projection") is not None else market.get("model") if market.get("model") is not None else market.get("mean"),
                live_projection=market.get("live_projection") if market.get("live_projection") is not None else market.get("liveProjection") if market.get("liveProjection") is not None else market.get("live_proj") if market.get("live_proj") is not None else market.get("projected_live"),
                detail=game.get("summary"),
                fallback_epoch=fallback_epoch,
            )
    filtered = [row for row in candidates if row.get("edge") not in {"-", None} or row.get("confidence") not in {"-", None}]
    return sorted(filtered or candidates, key=lambda row: row.get("score", 0.0), reverse=True)


def _dashboard_prop_count(sport: dict[str, Any]) -> int:
    home_rails = sport.get("home_rails") if isinstance(sport.get("home_rails"), dict) else {}
    pregame_items = (home_rails.get("pregame") or {}).get("items") if isinstance(home_rails.get("pregame"), dict) else []
    live_items = (home_rails.get("live") or {}).get("items") if isinstance(home_rails.get("live"), dict) else []
    rails_count = 0
    if isinstance(pregame_items, list):
        rails_count += len(pregame_items)
    if isinstance(live_items, list):
        rails_count += len(live_items)
    props_bar = sport.get("props_bar") if isinstance(sport.get("props_bar"), dict) else {}
    base_count = len(props_bar.get("items") or []) if isinstance(props_bar.get("items"), list) else 0
    if rails_count:
        return max(base_count, rails_count)
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
    outcome_state = _safe_text(item.get("outcome_state"), None)
    if not outcome_state:
        actual_value = _numeric_value(item.get("actual"))
        line_value = _numeric_value(item.get("line") or item.get("market_line"))
        selection = str(item.get("pick") or item.get("selection") or "").strip().lower()
        if actual_value is not None and line_value is not None:
            if selection == "under":
                outcome_state = "hit" if float(actual_value) < float(line_value) else "miss"
            elif selection == "over":
                outcome_state = "hit" if float(actual_value) > float(line_value) else "miss"
            elif str(item.get("heading") or "").strip().lower() == "hr targets":
                outcome_state = "hit" if float(actual_value) >= 1.0 else "miss"
    outcome_label = _safe_text(item.get("outcome_label"), None)
    if not outcome_label and outcome_state:
        outcome_label = "Hit" if outcome_state == "hit" else "Miss" if outcome_state == "miss" else None
    live_total = _prop_metric_text(item.get("live_total"))
    if not live_total:
        live_total = _score_value(item.get("live_total_line") or item.get("live_line_total") or item.get("total_goals"))
    return {
        "sport": _safe_text(sport.get("name"), str(sport.get("slug") or "").upper()),
        "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
        "surface": heading,
        "name": _safe_text(item.get("name"), "Prop"),
        "headshot_url": _safe_text(item.get("headshot_url") or item.get("photo"), None),
        "market": _safe_text(item.get("market"), heading),
        "pick": _safe_text(item.get("pick"), detail.split("|")[0].strip() if detail else heading),
        "matchup": _safe_text(item.get("matchup"), "-"),
        "actual": _prop_metric_text(item.get("actual")) or "-",
        "projected": _prop_metric_text(item.get("projected")) or "-",
        "live_projection": _prop_metric_text(item.get("live_projection")) or "-",
        "line": _prop_metric_text(item.get("line")) or "-",
        "odds": _prop_metric_text(item.get("odds")) or "-",
        "edge": edge,
        "confidence": confidence,
        "detail": detail,
        "href": str(item.get("href") or sport.get("hub_href") or "").strip() or None,
        "is_live": live_flag,
        "game_state": _safe_text(item.get("game_state"), None),
        "outcome_state": outcome_state,
        "outcome_label": outcome_label,
        "live_total": live_total,
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
        home_rails = sport.get("home_rails") if isinstance(sport.get("home_rails"), dict) else {}
        game_items = game_bar.get("items") if isinstance(game_bar.get("items"), list) else []
        dashboard_games = sport.get("dashboard_games") if isinstance(sport.get("dashboard_games"), list) else []
        prop_items = []
        if isinstance((home_rails.get("pregame") or {}).get("items"), list):
            prop_items.extend((home_rails.get("pregame") or {}).get("items") or [])
        if isinstance((home_rails.get("live") or {}).get("items"), list):
            prop_items.extend((home_rails.get("live") or {}).get("items") or [])
        if not prop_items:
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
        if not home_rails and str(sport.get("slug") or "").strip().lower() == "mlb":
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


def _apply_wnba_live_scores(games: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    try:
        from syndicate.features.wnba.cards import build_live_state_payload
    except Exception:
        return games

    payload = build_live_state_payload(selected_date, ttl=12, allow_stored_date_fallback=False)
    rows = payload.get("games") if isinstance(payload, dict) else []
    if not isinstance(rows, list) or not rows:
        return games

    keyed_live: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        away_key = str(row.get("away_tri") or row.get("away") or "").strip().upper()
        home_key = str(row.get("home_tri") or row.get("home") or "").strip().upper()
        if away_key and home_key:
            keyed_live[(away_key, home_key)] = row

    enriched: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        away_key = str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")).strip().upper()
        home_key = str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")).strip().upper()
        live_row = keyed_live.get((away_key, home_key)) if away_key and home_key else None
        if not live_row:
            enriched.append(game)
            continue

        updated = dict(game)
        away = dict(game.get("away") or {}) if isinstance(game.get("away"), dict) else {}
        home = dict(game.get("home") or {}) if isinstance(game.get("home"), dict) else {}
        live_state = {
            "away_pts": live_row.get("away_pts"),
            "home_pts": live_row.get("home_pts"),
            "in_progress": bool(live_row.get("in_progress")),
            "final": bool(live_row.get("final")),
            "status": str(live_row.get("status") or "").strip(),
        }

        live_away_pts = live_state.get("away_pts")
        live_home_pts = live_state.get("home_pts")
        if live_away_pts is not None:
            away["score"] = live_away_pts
        if live_home_pts is not None:
            home["score"] = live_home_pts
        updated["away"] = away
        updated["home"] = home

        status = dict(game.get("status") or {}) if isinstance(game.get("status"), dict) else {"abstract": str(game.get("status") or "").strip()}
        if live_away_pts is not None:
            status["away_score"] = live_away_pts
        if live_home_pts is not None:
            status["home_score"] = live_home_pts
        status["is_live"] = bool(live_state.get("in_progress"))
        status["in_progress"] = bool(live_state.get("in_progress"))
        status["is_final"] = bool(live_state.get("final"))
        status["final"] = bool(live_state.get("final"))
        if live_state.get("in_progress"):
            status["abstract"] = "Live"
        elif live_state.get("final"):
            status["abstract"] = "Final"
        detail_text = str(live_state.get("status") or game.get("detail") or "").strip()
        if detail_text:
            status["detailed"] = detail_text
        updated["status"] = status
        updated["live_state"] = live_state
        enriched.append(updated)
    return enriched


def _load_nhl_scoreboard_rows(selected_date: str) -> list[dict[str, Any]]:
    if selected_date == central_today_iso():
        try:
            from syndicate.local_nhl_odds import NhlWebClient

            rows = NhlWebClient().scoreboard_day(selected_date)
            if rows:
                def _coalesce_score(*values: Any) -> Any:
                    for value in values:
                        if value is None:
                            continue
                        if isinstance(value, str) and not value.strip():
                            continue
                        return value
                    return None

                return [
                    {
                        "gamePk": row.get("gamePk") or row.get("game_id"),
                        "away": row.get("away") or row.get("away_team"),
                        "home": row.get("home") or row.get("home_team"),
                        "away_abbr": row.get("away_abbr") or row.get("away_tri"),
                        "home_abbr": row.get("home_abbr") or row.get("home_tri"),
                        "away_goals": _coalesce_score(row.get("away_goals"), row.get("awayScore"), row.get("away_score")),
                        "home_goals": _coalesce_score(row.get("home_goals"), row.get("homeScore"), row.get("home_score")),
                        "gameState": row.get("gameState") or row.get("game_state") or row.get("state"),
                        "period": row.get("period") or row.get("web_period"),
                        "clock": row.get("clock") or row.get("web_clock"),
                    }
                    for row in rows
                    if isinstance(row, dict)
                ]
        except Exception:
            pass

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


def _prop_item_from_rank_card(
    card: dict[str, Any],
    *,
    sport_slug: str | None = None,
    fallback_href: str | None = None,
    heading_override: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(card, dict):
        return None
    title = _safe_text(card.get("title"), "Prop")
    meta = _safe_text(card.get("meta"), "Props board")
    detail = _safe_text(card.get("summary"), "No prop summary available.")
    badge = str(card.get("badge") or "").strip()
    metrics = card.get("metrics") if isinstance(card.get("metrics"), list) else []
    value = badge or _safe_text((((card.get("metrics") or [None])[0] or {}).get("value") if isinstance(card.get("metrics"), list) else None), "Top play")
    href = str(card.get("href") or fallback_href or "").strip() or None
    away_label, home_label = _split_matchup_labels(meta if meta != "Props board" else title)
    headshot_url = card.get("headshot_url") or card.get("photo") or card.get("player_photo")
    if not headshot_url and sport_slug in {"nba", "wnba"}:
        player_name = _player_name_from_prop_title(title) or _safe_text(card.get("summary"), None)
        resolved_player_id = _basketball_resolve_player_id(sport_slug, player_name=player_name, team_tri=away_label)
        headshot_url = _basketball_best_headshot_url(player_id=resolved_player_id)
    return {
        "matchup": meta,
        "heading": _safe_text(heading_override or card.get("eyebrow"), "Props"),
        "name": title,
        "detail": detail,
        "value": value,
        "photo": headshot_url,
        "headshot_url": headshot_url,
        "is_live": False,
        "market": _metric_value(metrics, ["market", "stat"]),
        "pick": badge or _metric_value(metrics, ["pick", "lean", "selection", "side"]),
        "actual": _metric_value(metrics, ["actual"]),
        "projected": _metric_value(metrics, ["projected", "projection", "model", "mean", "median"]),
        "live_projection": _metric_value(metrics, ["live projection", "live_proj"]),
        "line": _metric_value(metrics, ["line", "market line", "threshold"]),
        "odds": _metric_value(metrics, ["odds", "price"]),
        "edge": _metric_value(metrics, ["edge", "ev"]),
        "confidence": _metric_value(metrics, ["confidence", "win prob", "probability", "hit rate"]),
        "game_state": _metric_value(metrics, ["game state", "state", "status"]),
        "away_label": away_label,
        "home_label": home_label,
        "away_logo": _safe_text(card.get("away_logo"), None),
        "home_logo": _safe_text(card.get("home_logo"), None),
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


def _prop_rows_from_rank_cards(
    cards: list[dict[str, Any]],
    *,
    sport_slug: str | None = None,
    fallback_href: str | None = None,
    limit: int = 18,
    heading_override: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        item = _prop_item_from_rank_card(
            card,
            sport_slug=sport_slug,
            fallback_href=fallback_href,
            heading_override=heading_override,
        )
        if not item:
            continue
        rows.append(item)
        if len(rows) >= limit:
            break
    return rows


def _betting_card_rank_cards(slug: str, *, context_label: str, season: int | None = None, week: int | None = None) -> tuple[list[dict[str, Any]], str | None, str | None]:
    if slug == "mlb":
        from syndicate.features.mlb.betting_card import build_betting_card_page_context

        resolved_season = _int_or_none(str(context_label)[:4]) or central_year()
        context = build_betting_card_page_context(int(resolved_season), context_label)
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "nba":
        from syndicate.features.nba.betting_card import build_season_betting_card_day_payload

        resolved_season = _int_or_none(str(context_label)[:4]) or central_year()
        payload = build_season_betting_card_day_payload(int(resolved_season), context_label, "retuned") or {}
        return list(payload.get("rank_cards") or []), payload.get("route_path"), payload.get("date")
    if slug == "wnba":
        from syndicate.features.wnba.picks import build_betting_card_page_context

        resolved_season = _int_or_none(str(context_label)[:4]) or central_year()
        context = build_betting_card_page_context(int(resolved_season), context_label)
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "nhl":
        from syndicate.features.nhl.picks import build_betting_card_page_context

        resolved_season = int(season or (_int_or_none(str(context_label)[:4]) or central_year()))
        context = build_betting_card_page_context(resolved_season, context_label)
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "nfl" and week is not None and season is not None:
        from syndicate.features.nfl.picks import build_betting_card_page_context

        context = build_betting_card_page_context(int(season), int(week))
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "ncaaf" and week is not None and season is not None:
        from syndicate.features.ncaaf.picks import build_betting_card_page_context

        context = build_betting_card_page_context(int(season), int(week))
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "ncaab" and season is not None:
        from syndicate.features.ncaab.season import build_season_betting_card_page_context

        context = build_season_betting_card_page_context(int(season), context_label)
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    return [], None, None


def _pregame_prop_rows_from_mlb_recommendations(
    context_label: str,
    *,
    limit: int = 18,
    fallback_href: str | None = None,
) -> list[dict[str, Any]]:
    """Extract MLB player prop recommendations and convert to prop rows.
    
    Only includes pitcher and hitter props (no totals/ML).
    Formats with writeup and pills (line, sim mean, odds) similar to HR targets.
    """
    try:
        from syndicate.features.mlb.cards import _cards_recommendation_payload_by_game
        from syndicate.features.mlb.cards import _mlb_headshot_url
        from syndicate.features.mlb.cards import _mlb_logo_url

        recos_by_game = _cards_recommendation_payload_by_game(context_label)
        rows: list[dict[str, Any]] = []
        
        for game_pk, game_data in recos_by_game.items():
            if not isinstance(game_data, dict):
                continue
            
            markets = game_data.get("markets", {}) if isinstance(game_data.get("markets"), dict) else {}
            matchup_data = game_data.get("matchup") if isinstance(game_data.get("matchup"), dict) else {}
            away = game_data.get("away") if isinstance(game_data.get("away"), dict) else matchup_data.get("away") if isinstance(matchup_data.get("away"), dict) else {}
            home = game_data.get("home") if isinstance(game_data.get("home"), dict) else matchup_data.get("home") if isinstance(matchup_data.get("home"), dict) else {}
            away_label = str(away.get("abbr") or away.get("teamAbbr") or away.get("name") or away.get("teamName") or "").strip() or None
            home_label = str(home.get("abbr") or home.get("teamAbbr") or home.get("name") or home.get("teamName") or "").strip() or None
            away_logo = str(away.get("logo") or away.get("logo_url") or away.get("teamLogo") or "").strip() or None
            home_logo = str(home.get("logo") or home.get("logo_url") or home.get("teamLogo") or "").strip() or None
            fallback_matchup = " @ ".join(part for part in [away_label, home_label] if part) or f"Game {game_pk}"
            
            # Add pitcher props
            pitcher_props = [
                *([row for row in (markets.get("pitcherProps") or []) if isinstance(row, dict)]),
                *([row for row in (markets.get("extraPitcherProps") or []) if isinstance(row, dict)]),
            ]
            if isinstance(pitcher_props, list):
                for prop in pitcher_props:
                    if not isinstance(prop, dict):
                        continue
                    pitcher = str(prop.get("pitcher_name") or prop.get("player_name") or "Pitcher").strip()
                    prop_type = str(prop.get("prop") or "strikeouts").strip().title()
                    line_val = _score_value(prop.get("market_line")) or str(prop.get("market_line") or "-")
                    selection = str(prop.get("selection") or "").strip().upper()
                    matchup_text = str(prop.get("matchup") or "").strip()
                    if not matchup_text or re.fullmatch(r"Game\s+\d+", matchup_text, flags=re.IGNORECASE):
                        matchup_text = fallback_matchup
                    edge = _numeric_value(prop.get("edge"))
                    edge_text = f"{edge * 100:.1f}% EV" if edge is not None else "-"
                    model_prob = _numeric_value(prop.get("model_prob"))
                    if model_prob is None:
                        model_prob = _numeric_value(prop.get("model_prob_over") if selection == "OVER" else prop.get("model_prob_under"))
                    sim_mean_text = f"{model_prob * 100:.1f}%" if model_prob is not None else "-"
                    projected_text = _prop_metric_text(
                        prop.get("projection")
                        if prop.get("projection") is not None
                        else prop.get("mean")
                        if prop.get("mean") is not None
                        else prop.get("modelMean")
                        if prop.get("modelMean") is not None
                        else prop.get("sim_mean")
                        if prop.get("sim_mean") is not None
                        else prop.get("projected")
                        if prop.get("projected") is not None
                        else prop.get("baseline")
                    )
                    odds_text = _prop_metric_text(prop.get("odds") or prop.get("price"))
                    ladder_groups = []
                    for badge in (prop.get("pregameLadderBadges") or prop.get("ladderBadges") or []):
                        if not isinstance(badge, dict):
                            continue
                        targets = [int(total) for total in (badge.get("targets") or []) if _int_or_none(total) is not None]
                        if not targets:
                            continue
                        ladder_groups.append({
                            "short_label": str(badge.get("short_label") or badge.get("label") or prop_type).strip() or prop_type,
                            "targets": targets,
                        })
                    player_id = _int_or_none(prop.get("pitcher_id") or prop.get("player_id"))
                    row_away_label = away_label or str(prop.get("away_abbr") or prop.get("away") or "").strip() or None
                    row_home_label = home_label or str(prop.get("home_abbr") or prop.get("home") or "").strip() or None
                    row_matchup = " @ ".join(part for part in [row_away_label, row_home_label] if part) or fallback_matchup
                    row_away_logo = away_logo
                    row_home_logo = home_logo
                    if not row_away_logo:
                        row_away_logo = _mlb_logo_url(_int_or_none(away.get("team_id") or away.get("teamId")))
                    if not row_home_logo:
                        row_home_logo = _mlb_logo_url(_int_or_none(home.get("team_id") or home.get("teamId")))
                    
                    writeup = f"Recommended {selection} for {pitcher} {prop_type} at {line_val}. Model gives {sim_mean_text} win probability with {edge_text} edge."
                    pills = [
                        {"label": "Line", "value": line_val},
                        {"label": "Sim", "value": sim_mean_text},
                        {"label": "Odds", "value": odds_text},
                    ]
                    
                    rows.append({
                        "game_pk": _int_or_none(game_pk),
                        "matchup": row_matchup if re.fullmatch(r"Game\s+\d+", matchup_text, flags=re.IGNORECASE) else matchup_text,
                        "heading": "Betting Card",
                        "name": pitcher,
                        "player_name": pitcher,
                        "detail": f"{selection} {line_val}",
                        "value": edge_text,
                        "is_live": False,
                        "market": f"Pitcher {prop_type}",
                        "pick": selection,
                        "line": line_val,
                        "projected": projected_text,
                        "odds": odds_text,
                        "edge": edge_text,
                        "confidence": _pct_text(model_prob),
                        "writeup": writeup,
                        "pills": pills,
                        "away_label": row_away_label,
                        "home_label": row_home_label,
                        "away_logo": row_away_logo,
                        "home_logo": row_home_logo,
                        "headshot_url": _mlb_headshot_url(player_id),
                        "ladder_groups": ladder_groups,
                        "href": fallback_href,
                    })
                    if len(rows) >= limit:
                        return rows[:limit]
            
            # Add hitter props
            hitter_props = [
                *([row for row in (markets.get("hitterProps") or []) if isinstance(row, dict)]),
                *([row for row in (markets.get("extraHitterProps") or []) if isinstance(row, dict)]),
            ]
            if isinstance(hitter_props, list):
                for prop in hitter_props:
                    if not isinstance(prop, dict):
                        continue
                    hitter = str(prop.get("player_name") or "Hitter").strip()
                    prop_type = str(prop.get("prop") or "hits").strip().title()
                    line_val = _score_value(prop.get("market_line")) or str(prop.get("market_line") or "-")
                    selection = str(prop.get("selection") or "").strip().upper()
                    matchup_text = str(prop.get("matchup") or "").strip()
                    if not matchup_text or re.fullmatch(r"Game\s+\d+", matchup_text, flags=re.IGNORECASE):
                        matchup_text = fallback_matchup
                    edge = _numeric_value(prop.get("edge"))
                    edge_text = f"{edge * 100:.1f}% EV" if edge is not None else "-"
                    model_prob = _numeric_value(prop.get("model_prob"))
                    if model_prob is None:
                        model_prob = _numeric_value(prop.get("model_prob_over") if selection == "OVER" else prop.get("model_prob_under"))
                    sim_mean_text = f"{model_prob * 100:.1f}%" if model_prob is not None else "-"
                    projected_text = _prop_metric_text(
                        prop.get("projection")
                        if prop.get("projection") is not None
                        else prop.get("mean")
                        if prop.get("mean") is not None
                        else prop.get("modelMean")
                        if prop.get("modelMean") is not None
                        else prop.get("sim_mean")
                        if prop.get("sim_mean") is not None
                        else prop.get("projected")
                        if prop.get("projected") is not None
                        else prop.get("baseline")
                    )
                    odds_text = _prop_metric_text(prop.get("odds") or prop.get("price"))
                    ladder_groups = []
                    for badge in (prop.get("pregameLadderBadges") or prop.get("ladderBadges") or []):
                        if not isinstance(badge, dict):
                            continue
                        targets = [int(total) for total in (badge.get("targets") or []) if _int_or_none(total) is not None]
                        if not targets:
                            continue
                        ladder_groups.append({
                            "short_label": str(badge.get("short_label") or badge.get("label") or prop_type).strip() or prop_type,
                            "targets": targets,
                        })
                    player_id = _int_or_none(prop.get("batter_id") or prop.get("player_id"))
                    row_away_label = away_label or str(prop.get("away_abbr") or prop.get("away") or "").strip() or None
                    row_home_label = home_label or str(prop.get("home_abbr") or prop.get("home") or "").strip() or None
                    row_matchup = " @ ".join(part for part in [row_away_label, row_home_label] if part) or fallback_matchup
                    row_away_logo = away_logo
                    row_home_logo = home_logo
                    team_id = _int_or_none(prop.get("team_id"))
                    opponent_team_id = _int_or_none(prop.get("opponent_team_id"))
                    team_label = str(prop.get("team") or "").strip() or None
                    opponent_label = str(prop.get("opponent") or "").strip() or None
                    if team_label and opponent_label:
                        if row_away_label is None and row_home_label is None:
                            row_away_label = team_label
                            row_home_label = opponent_label
                        if row_away_label == opponent_label and row_home_label == team_label:
                            row_away_logo = row_away_logo or _mlb_logo_url(opponent_team_id)
                            row_home_logo = row_home_logo or _mlb_logo_url(team_id)
                        else:
                            row_away_logo = row_away_logo or _mlb_logo_url(team_id)
                            row_home_logo = row_home_logo or _mlb_logo_url(opponent_team_id)
                    
                    writeup = f"Recommended {selection} for {hitter} {prop_type} at {line_val}. Model gives {sim_mean_text} win probability with {edge_text} edge."
                    pills = [
                        {"label": "Line", "value": line_val},
                        {"label": "Sim", "value": sim_mean_text},
                        {"label": "Odds", "value": odds_text},
                    ]
                    
                    rows.append({
                        "game_pk": _int_or_none(game_pk),
                        "matchup": row_matchup if re.fullmatch(r"Game\s+\d+", matchup_text, flags=re.IGNORECASE) else matchup_text,
                        "heading": "Betting Card",
                        "name": hitter,
                        "player_name": hitter,
                        "detail": f"{selection} {line_val}",
                        "value": edge_text,
                        "is_live": False,
                        "market": f"Hitter {prop_type}",
                        "pick": selection,
                        "line": line_val,
                        "projected": projected_text,
                        "odds": odds_text,
                        "edge": edge_text,
                        "confidence": _pct_text(model_prob),
                        "writeup": writeup,
                        "pills": pills,
                        "away_label": row_away_label,
                        "home_label": row_home_label,
                        "away_logo": row_away_logo,
                        "home_logo": row_home_logo,
                        "headshot_url": _mlb_headshot_url(player_id),
                        "ladder_groups": ladder_groups,
                        "href": fallback_href,
                    })
                    if len(rows) >= limit:
                        return rows[:limit]
        
        return rows
    except Exception:
        return []


def _pregame_prop_rows_from_betting_card(
    slug: str,
    *,
    context_label: str,
    season: int | None = None,
    week: int | None = None,
    limit: int = 18,
) -> list[dict[str, Any]]:
    # For MLB, use recommendations from locked policy
    if slug == "mlb":
        fallback_href = f"/mlb/cards?date={context_label}"
        return _pregame_prop_rows_from_mlb_recommendations(context_label, limit=limit, fallback_href=fallback_href)
    
    # For other sports, use rank_cards from betting card
    cards, route_path, resolved_date = _betting_card_rank_cards(slug, context_label=context_label, season=season, week=week)
    if not cards:
        return []
    fallback_href = None
    if route_path:
        if slug in {"nfl", "ncaaf"} and week is not None:
            fallback_href = f"{route_path}?week={int(week)}"
        elif resolved_date:
            fallback_href = f"{route_path}?date={resolved_date}"
        else:
            fallback_href = route_path
    return _prop_rows_from_rank_cards(cards, sport_slug=slug, fallback_href=fallback_href, limit=limit, heading_override="Betting Card")


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
                "photo": str(card.get("headshot_url") or "").strip() or None,
                "headshot_url": str(card.get("headshot_url") or "").strip() or None,
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
                "away_label": team,
                "home_label": opp,
                "away_logo": str(card.get("team_logo") or "").strip() or None,
                "home_logo": str(card.get("opp_logo") or "").strip() or None,
                "href": fallback_href,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _prop_rows_from_mlb_live_games(games: list[dict[str, Any]], *, limit: int = 18) -> list[dict[str, Any]]:
    from syndicate.features.mlb.cards import _mlb_headshot_url

    candidates: list[tuple[tuple[int, float, float], dict[str, Any]]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        matchup = _sport_matchup(game)
        href = str(game.get("href") or "").strip() or None
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        live_props = game.get("liveProps") if isinstance(game.get("liveProps"), list) else []
        archived_props = game.get("archivedLiveProps") if isinstance(game.get("archivedLiveProps"), list) else []
        for prop in [value for value in [*live_props, *archived_props] if isinstance(value, dict)]:
            selection = str(prop.get("selection") or "").strip().title()
            line = _score_value(prop.get("line")) or _safe_text(prop.get("line"), "-")
            market = _safe_text(prop.get("marketLabel") or prop.get("market"), "Market")
            player = _safe_text(prop.get("playerName"), "MLB prop")
            player_id = _int_or_none(
                prop.get("playerId")
                or prop.get("player_id")
                or prop.get("batterId")
                or prop.get("batter_id")
                or prop.get("pitcherId")
                or prop.get("pitcher_id")
            )
            headshot_url = prop.get("headshotUrl") or prop.get("headshot_url") or prop.get("playerPhoto") or prop.get("photo") or _mlb_headshot_url(player_id)
            probability = _numeric_value(prop.get("estimatedWinProb"))
            if probability is None and str(prop.get("selection") or "").strip().lower() == "over":
                probability = _numeric_value(prop.get("modelProbOver"))
            value = f"{probability * 100:.1f}% win" if probability is not None else _safe_text(prop.get("odds"), "Live")
            row = {
                "game_pk": _int_or_none(game.get("gamePk") or game.get("game_pk")),
                "matchup": matchup,
                "heading": "Live props",
                "name": player,
                "player_name": player,
                "player_id": player_id,
                "photo": headshot_url,
                "headshot_url": headshot_url,
                "is_live": True,
                "market": market,
                "pick": selection,
                "detail": f"{selection} {line} {market}",
                "value": value,
                "actual": _prop_metric_text(prop.get("actual") if prop.get("actual") is not None else prop.get("actual_value") if prop.get("actual_value") is not None else prop.get("actualValue")),
                "projected": _prop_metric_text(prop.get("modelMean") if prop.get("modelMean") is not None else prop.get("liveProjection")),
                "live_projection": _prop_metric_text(prop.get("liveProjection") if prop.get("liveProjection") is not None else prop.get("modelMean")),
                "line": _prop_metric_text(prop.get("line")),
                "odds": _prop_metric_text(prop.get("odds")),
                "edge": _pct_text(prop.get("estimatedEdge") if prop.get("estimatedEdge") is not None else prop.get("ev")),
                "confidence": _pct_text(probability),
                "game_state": _safe_text(prop.get("status") or prop.get("gameState") or game.get("status"), None),
                "away_label": _safe_text(away.get("abbr") or away.get("name"), None),
                "home_label": _safe_text(home.get("abbr") or home.get("name"), None),
                "away_logo": _safe_text(away.get("logo") or away.get("teamLogo"), None),
                "home_logo": _safe_text(home.get("logo") or home.get("teamLogo"), None),
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


def _prop_rows_from_nba_live_lens(
    games: list[dict[str, Any]],
    *,
    sport_slug: str,
    fallback_href: str | None = None,
    limit: int = 18,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        status = game.get("status") if isinstance(game.get("status"), dict) else {}
        away_label = _game_team_label(game, "away") or "Away"
        home_label = _game_team_label(game, "home") or "Home"
        matchup = f"{away_label} @ {home_label}"
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
        away_label = _game_team_label(game, "away") or "Away"
        home_label = _game_team_label(game, "home") or "Home"
        opponent = _safe_text(row.get("opponent_tri"), None)
        market_label = _display_prop_market_label(row.get("stat"))
        resolved_player_id = _basketball_resolve_player_id(
            sport_slug,
            player_name=player,
            team_tri=team,
            player_id=row.get("player_id"),
        )
        headshot_url = _basketball_best_headshot_url(
            player_id=resolved_player_id,
            photo=row.get("player_photo") or row.get("photo") or row.get("headshot_url"),
        )
        side = _safe_text(row.get("lean") or row.get("ev_side"), "Watch")
        line = _score_value(row.get("line_live") if row.get("line_live") is not None else row.get("line")) or _safe_text(row.get("line"), "-")
        market = _safe_text(row.get("stat"), "Market")
        probability = _pct_text(row.get("win_prob") or row.get("live_rank_probability"))
        ev_pct = _pct_text(row.get("ev"))
        value = probability or (f"EV {ev_pct}" if ev_pct else _safe_text(row.get("klass"), "Watch"))
        projected = _prop_metric_text(row.get("sim_mu") if row.get("sim_mu") is not None else row.get("sim_mu_adjusted"))
        live_projection = _prop_metric_text(
            row.get("live_projection")
            if row.get("live_projection") is not None
            else (row.get("liveProjection") if row.get("liveProjection") is not None else row.get("sim_mu_adjusted") if row.get("sim_mu_adjusted") is not None else row.get("sim_mu"))
        )
        rows.append(
            {
                "matchup": str(row.get("__matchup") or "").strip() or _sport_matchup(game),
                "heading": heading,
                "name": player,
                "player_name": player,
                "is_live": True,
                "market": market,
                "pick": side,
                "detail": f"{side} {line} {market_label} | {_safe_text(row.get('basketball_summary') or row.get('shape_summary'), 'Live prop signal')}",
                "value": value,
                "actual": _prop_metric_text(row.get("actual")),
                "projected": projected,
                "live_projection": live_projection,
                "line": _prop_metric_text(row.get("line_live") if row.get("line_live") is not None else row.get("line")),
                "odds": _prop_metric_text(
                    row.get("odds_live")
                    if row.get("odds_live") is not None
                    else (row.get("price") if row.get("price") is not None else row.get("odds"))
                ),
                "edge": _pct_text(
                    row.get("live_edge")
                    if row.get("live_edge") is not None
                    else (row.get("liveEdge") if row.get("liveEdge") is not None else row.get("ev") if row.get("ev") is not None else row.get("edge"))
                ),
                "confidence": probability,
                "game_state": _safe_text(status_bits[-1] if status_bits else row.get("status_label") or "Live", None),
                "team": team,
                "opponent": opponent,
                "away_label": away_label,
                "home_label": home_label,
                "away_logo": _logo_from_team_label(sport_slug, away_label),
                "home_logo": _logo_from_team_label(sport_slug, home_label),
                "player_id": resolved_player_id,
                "photo": headshot_url,
                "headshot_url": headshot_url,
                "href": fallback_href or (str(game.get("href") or "").strip() or None),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _prop_rows_from_props_recommendations_csv(
    slug: str,
    *,
    context_label: str,
    fallback_href: str | None = None,
    limit: int = 18,
) -> list[dict[str, Any]]:
    sport_slug = str(slug or "").strip().lower()
    if sport_slug not in {"nba", "wnba"}:
        return []

    try:
        if sport_slug == "nba":
            from syndicate.features.nba.sources import processed_path
        else:
            from syndicate.features.wnba.sources import processed_path

        csv_path = processed_path(f"props_recommendations_{context_label}.csv")
    except Exception:
        return []

    if not csv_path.exists():
        return []

    rows: list[dict[str, Any]] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                if not isinstance(raw, dict):
                    continue
                player = _safe_text(raw.get("player"), "Prop")
                if player == "Prop":
                    continue
                team = _safe_text(raw.get("team"), "Team")
                top_play_raw = str(raw.get("top_play") or "").strip()
                if not top_play_raw:
                    continue
                try:
                    top_play = ast.literal_eval(top_play_raw)
                except Exception:
                    continue
                if not isinstance(top_play, dict):
                    continue
                market = _safe_text(top_play.get("market"), "Market").upper()
                side = _safe_text(top_play.get("side"), "Watch")
                line_text = _prop_metric_text(top_play.get("line"))
                summary = _safe_text(raw.get("top_play_explain") or raw.get("top_play_baseline"), "Top prop recommendation")
                ev_pct = _numeric_value(top_play.get("ev_pct"))
                edge_text = _pct_text(top_play.get("ev") if top_play.get("ev") is not None else top_play.get("edge"))
                rows.append(
                    {
                        "matchup": team,
                        "heading": "Props",
                        "name": f"{player} ({team})",
                        "is_live": False,
                        "market": market,
                        "pick": side,
                        "detail": f"{side} {line_text} {market} | {summary}",
                        "value": f"EV {ev_pct:.1f}%" if ev_pct is not None else edge_text,
                        "projected": _prop_metric_text(raw.get("top_play_baseline")),
                        "line": line_text,
                        "odds": _prop_metric_text(top_play.get("price")),
                        "edge": edge_text,
                        "confidence": _safe_text(raw.get("top_play_consensus"), "Model"),
                        "href": fallback_href or f"/{sport_slug}/props?date={context_label}",
                    }
                )
                if len(rows) >= limit:
                    break
    except Exception:
        return []

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


def _home_games_have_live_action(home_games: list[dict[str, Any]] | None) -> bool:
    for game in home_games or []:
        if not isinstance(game, dict):
            continue
        scoreboard = _scoreboard_state(game)
        if _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line")):
            return True
    return False


def _load_home_pregame_prop_items(
    slug: str,
    *,
    context_label: str,
    home_games: list[dict[str, Any]],
    season: int | None = None,
    week: int | None = None,
    is_active_today: bool,
) -> list[dict[str, Any]]:
    if slug in {"nfl", "ncaaf"} and not is_active_today:
        return []
    try:
        if slug == "nba":
            nba_rows = _pregame_prop_rows_from_betting_card(slug, context_label=context_label, season=season, week=week)
            if nba_rows:
                return nba_rows
            return _prop_rows_from_props_recommendations_csv(slug, context_label=context_label, fallback_href=f"/nba/cards?date={context_label}")
        if slug == "wnba":
            wnba_rows = _pregame_prop_rows_from_betting_card(slug, context_label=context_label, season=season, week=week)
            if wnba_rows:
                return wnba_rows
            return _prop_rows_from_props_recommendations_csv(slug, context_label=context_label, fallback_href=f"/wnba/cards?date={context_label}")
        if slug in {"mlb", "nhl", "nfl", "ncaaf", "ncaab"}:
            return _pregame_prop_rows_from_betting_card(slug, context_label=context_label, season=season, week=week)
    except Exception:
        return []
    return []


def _load_home_live_prop_items(
    slug: str,
    *,
    context_label: str,
    home_games: list[dict[str, Any]],
    season: int | None = None,
    week: int | None = None,
    is_active_today: bool,
) -> list[dict[str, Any]]:
    if not is_active_today:
        return []
    try:
        if slug == "mlb":
            from syndicate.features.mlb.live_lens import build_live_lens_page_context

            live_games = list(build_live_lens_page_context(context_label).get("games") or [])
            live_games = [game for game in live_games if isinstance(game, dict)]
            if not live_games:
                return []
            liveish_games = [
                game
                for game in live_games
                if _is_liveish(*(_scoreboard_state(game).get(key) for key in ["status_badge", "status_line"]))
            ]
            prop_backed_games = [
                game
                for game in (liveish_games or live_games)
                if isinstance(game.get("liveProps"), list) or isinstance(game.get("archivedLiveProps"), list)
            ]
            live_rows = _prop_rows_from_mlb_live_games(prop_backed_games)
            if live_rows:
                return live_rows
            return _load_mlb_home_top_prop_items(context_label)
        if not _home_games_have_live_action(home_games):
            return []
        if slug == "nhl":
            from syndicate.features.nhl.cards import build_props_cards_payload

            payload = build_props_cards_payload(context_label, top=18)
            return _prop_rows_from_nhl_cards(
                list(payload.get("cards") or []),
                fallback_href=f"/nhl/cards?date={payload.get('date') or context_label}",
            )
        if slug == "nba":
            from syndicate.features.nba.cards import build_live_player_lens_payload
            from syndicate.features.nba.cards import build_live_state_payload

            live_state = build_live_state_payload(context_label, ttl=12)
            event_ids = [
                str((game or {}).get("event_id") or "").strip()
                for game in (live_state.get("games") if isinstance(live_state.get("games"), list) else [])
                if str((game or {}).get("event_id") or "").strip()
            ]
            if not event_ids:
                return []
            payload = build_live_player_lens_payload(context_label, event_ids, ttl=20)
            return _prop_rows_from_nba_live_lens(
                list(payload.get("games") or []),
                sport_slug="nba",
                fallback_href=f"/nba/live-lens?date={context_label}",
            )
        if slug == "wnba":
            from syndicate.features.wnba.cards import build_live_player_lens_payload
            from syndicate.features.wnba.cards import build_live_state_payload

            live_state = build_live_state_payload(context_label, ttl=12)
            event_ids = [
                str((game or {}).get("event_id") or "").strip()
                for game in (live_state.get("games") if isinstance(live_state.get("games"), list) else [])
                if str((game or {}).get("event_id") or "").strip()
            ]
            if not event_ids:
                return []
            payload = build_live_player_lens_payload(context_label, event_ids, ttl=20)
            return _prop_rows_from_nba_live_lens(
                list(payload.get("games") or []),
                sport_slug="wnba",
                fallback_href=f"/wnba/live-lens?date={context_label}",
            )
    except Exception:
        return []
    return []


def _mlb_top_prop_rows_from_group(
    summary: dict[str, Any],
    *,
    group_key: str,
    fallback_href: str,
    limit: int,
) -> list[dict[str, Any]]:
    groups = summary.get("groups") if isinstance(summary.get("groups"), dict) else {}
    group = groups.get(group_key) if isinstance(groups.get(group_key), dict) else {}
    sections = group.get("sections") if isinstance(group.get("sections"), list) else []
    heading = "Pitcher top props" if group_key == "pitcher" else "Hitter top props"
    candidates: list[tuple[float, dict[str, Any]]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        values = section.get("rows") if isinstance(section.get("rows"), list) else []
        for value in values:
            if not isinstance(value, dict):
                continue
            probability = _numeric_value(value.get("simProb"))
            edge = _numeric_value(value.get("rawEdge"))
            matchup = _safe_text(value.get("matchup"), "-")
            away_label, home_label = _split_matchup_labels(matchup)
            team_label = str(value.get("team") or "").strip()
            opponent_label = str(value.get("opponent") or "").strip()
            team_logo = str(value.get("teamLogoUrl") or "").strip() or None
            opponent_logo = str(value.get("opponentLogoUrl") or "").strip() or None
            odds_value = _numeric_value(value.get("odds"))
            odds_text = None
            if odds_value is not None:
                odds_int = int(odds_value)
                odds_text = f"+{odds_int}" if odds_int > 0 else str(odds_int)
            selection = _safe_text(value.get("selectionLabel") or value.get("selection"), "Play")
            target_label = str(value.get("targetLabel") or "").strip()
            market = _safe_text(value.get("statLabel") or value.get("stat"), "Market")
            pick = f"{selection} {target_label}".strip()
            candidates.append(
                (
                    float(edge or probability or 0.0),
                    {
                        "game_pk": _int_or_none(value.get("gamePk")),
                        "matchup": matchup,
                        "heading": heading,
                        "name": _safe_text(value.get("playerName") or value.get("ownerName"), "MLB prop"),
                        "player_name": _safe_text(value.get("playerName") or value.get("ownerName"), "MLB prop"),
                        "player_id": _int_or_none(value.get("ownerId") or value.get("playerId")),
                        "photo": str(value.get("headshotUrl") or "").strip() or None,
                        "headshot_url": str(value.get("headshotUrl") or "").strip() or None,
                        "is_live": False,
                        "market": market,
                        "pick": pick,
                        "detail": f"{pick} {market} | Daily top props fallback".strip(),
                        "value": f"{probability * 100:.1f}% win" if probability is not None else heading,
                        "projected": _prop_metric_text(value.get("mean")),
                        "line": _prop_metric_text(value.get("line")) or _safe_text(value.get("line"), "-"),
                        "odds": odds_text or _prop_metric_text(value.get("odds")),
                        "edge": _pct_text(edge),
                        "confidence": _pct_text(probability),
                        "away_label": away_label,
                        "home_label": home_label,
                        "away_logo": opponent_logo if away_label == opponent_label else team_logo if away_label == team_label else None,
                        "home_logo": team_logo if home_label == team_label else opponent_logo if home_label == opponent_label else None,
                        "href": fallback_href,
                    },
                )
            )
    return [row for _, row in sorted(candidates, key=lambda item: item[0], reverse=True)[:limit]]


def _load_mlb_home_top_prop_items(context_label: str, *, limit: int = 18) -> list[dict[str, Any]]:
    summary = load_json_or_gz_file(daily_top_props_path(context_label))
    if not isinstance(summary, dict):
        return []
    per_group_limit = max(1, limit // 2)
    pitcher_rows = _mlb_top_prop_rows_from_group(
        summary,
        group_key="pitcher",
        fallback_href=f"/mlb/pitcher-top-props?date={context_label}",
        limit=per_group_limit,
    )
    hitter_rows = _mlb_top_prop_rows_from_group(
        summary,
        group_key="hitter",
        fallback_href=f"/mlb/hitter-top-props?date={context_label}",
        limit=per_group_limit,
    )
    return _interleave_rows(pitcher_rows, hitter_rows, limit=limit)


def _load_home_prop_items(
    slug: str,
    *,
    context_label: str,
    home_games: list[dict[str, Any]],
    season: int | None = None,
    week: int | None = None,
    is_active_today: bool,
    lane: str = "combined",
) -> list[dict[str, Any]]:
    lane_key = str(lane or "combined").strip().lower()
    if lane_key == "pregame":
        return _load_home_pregame_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=week,
            is_active_today=is_active_today,
        )
    if lane_key == "live":
        return _load_home_live_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=week,
            is_active_today=is_active_today,
        )
    if slug in {"nfl", "ncaaf"} and not is_active_today:
        return []
    try:
        live_rows = _load_home_live_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=week,
            is_active_today=is_active_today,
        )
        if live_rows:
            return live_rows
        pregame_rows = _load_home_pregame_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=week,
            is_active_today=is_active_today,
        )
        if pregame_rows:
            return pregame_rows
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
        writeup = str(target.get("writeup") or target.get("summary") or "").strip()
        matchup = _safe_text(target.get("matchup"), "-")
        away_label, home_label = _split_matchup_labels(matchup)
        team_label = _safe_text(target.get("team"), None)
        opponent_label = _safe_text(target.get("opponent"), None)
        team_logo = str(target.get("team_logo_url") or "").strip() or None
        opponent_logo = str(target.get("opponent_logo_url") or "").strip() or None
        away_logo = None
        home_logo = None
        if away_label and home_label and team_label and opponent_label:
            if away_label == team_label and home_label == opponent_label:
                away_logo = team_logo
                home_logo = opponent_logo
            elif away_label == opponent_label and home_label == team_label:
                away_logo = opponent_logo
                home_logo = team_logo
        rows.append(
            {
                "game_pk": _int_or_none(target.get("game_pk") or target.get("gamePk")),
                "heading": _safe_text(target.get("team"), "HR target"),
                "name": _safe_text(target.get("player_name"), "Unknown hitter"),
                "value": _safe_text(target.get("probability"), "-"),
                "matchup": matchup,
                "detail": reasons[0] if reasons else _safe_text(target.get("summary"), "No HR-target summary available."),
                "writeup": writeup or _safe_text(target.get("summary"), "No HR-target summary available."),
                "line": _safe_text(target.get("support"), "-"),
                "team": _safe_text(target.get("team"), "-"),
                "opponent": _safe_text(target.get("opponent"), "-"),
                "away_label": away_label,
                "home_label": home_label,
                "headshot_url": str(target.get("headshot_url") or "").strip() or None,
                "away_logo": away_logo,
                "home_logo": home_logo,
                "team_logo_url": team_logo,
                "opponent_logo_url": opponent_logo,
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
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
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
            live_heading = _safe_text(row.get("heading"), "Props")
            if bool(game.get("shared_is_live")) or _is_liveish(game.get("status"), game.get("detail")):
                live_heading = "Live props"
            rows.append(
                {
                    "matchup": matchup,
                    "heading": live_heading,
                    "name": name,
                    "detail": detail,
                    "value": value,
                    "photo": row.get("photo"),
                    "headshot_url": row.get("headshot_url") or row.get("photo"),
                    "away_label": _safe_text(away.get("abbr") or away.get("name"), None),
                    "home_label": _safe_text(home.get("abbr") or home.get("name"), None),
                    "away_logo": _team_logo(game, "away"),
                    "home_logo": _team_logo(game, "home"),
                    "pick": _safe_text(row.get("pick"), ""),
                    "market": _safe_text(row.get("market"), ""),
                    "line": row.get("line"),
                    "market_line": row.get("market_line") or row.get("line"),
                    "actual": row.get("actual"),
                    "projected": row.get("projected"),
                    "live_projection": row.get("live_projection"),
                    "odds": row.get("odds"),
                    "confidence": row.get("confidence"),
                    "selection": _safe_text(row.get("selection"), ""),
                    "game_state": _safe_text(row.get("game_state"), None),
                    "live_total": row.get("live_total") or row.get("live_total_line"),
                    "outcome_state": _safe_text(row.get("outcome_state"), None),
                    "outcome_label": _safe_text(row.get("outcome_label"), None),
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
            if is_active_today and not games:
                games = _mlb_schedule_fallback_games(context_label)
            return _apply_mlb_live_scores(games, context_label) if is_active_today else games
        if slug == "nba":
            from syndicate.features.nba.cards import build_cards_page_context

            payload = build_cards_page_context(context_label, allow_stored_date_fallback=False)
            if str(payload.get("requested_date") or context_label).strip() == str(context_label).strip() and str(payload.get("date") or context_label).strip() != str(context_label).strip():
                return _nba_live_state_games(context_label) if is_active_today else []
            games = list(payload.get("games") or [])
            if is_active_today and not games:
                games = _nba_live_state_games(context_label)
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

            payload = build_cards_page_context(context_label, allow_stored_date_fallback=False)
            if str(payload.get("requested_date") or context_label).strip() == str(context_label).strip() and str(payload.get("date") or context_label).strip() != str(context_label).strip():
                return _wnba_live_state_games(context_label) if is_active_today else []
            games = list(payload.get("games") or [])
            if is_active_today and not games:
                games = _wnba_live_state_games(context_label)
            return _apply_wnba_live_scores(games, context_label) if is_active_today else games
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


def _rail_links(*candidates: tuple[str | None, str | None]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for href, label in candidates:
        href_text = str(href or "").strip()
        label_text = str(label or "").strip()
        if not href_text or not label_text:
            continue
        key = (href_text, label_text)
        if key in seen:
            continue
        seen.add(key)
        links.append({"href": href_text, "label": label_text})
    return links


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
    betting_href, betting_label = _link_lookup_any(links, ["Betting Card"])
    fallback_href, fallback_label = _link_lookup_any(links, ["Picks", "Season Review", "Betting Card", "Hub"])

    if props_href:
        extra_links: list[dict[str, str]] = []
        if live_href and live_href != props_href:
            extra_links.append({"href": live_href, "label": "Open Prop Live Lens" if is_active_today else "Open Live Lens"})
        if betting_href and betting_href != props_href:
            extra_links.append({"href": betting_href, "label": f"Open {betting_label}" if betting_label else "Open Betting Card"})
        return {
            "eyebrow": "Props board",
            "title": props_label or "Props",
            "kicker": "Pregame props route",
            "summary": "Start from the sport's local props board when one exists, then use adjacent boards only when you need broader context.",
            "status_label": "Pregame props",
            "opportunity_tags": [str(props_label or "Props"), "Pregame props"] + (["Live Lens"] if live_href else []),
            "primary_href": props_href,
            "primary_label": f"Open {props_label}" if props_label else "Open Props",
            "secondary_href": betting_href or fallback_href,
            "secondary_label": f"Open {betting_label}" if betting_href and betting_label else (f"Open {fallback_label}" if fallback_label else None),
            "extra_links": extra_links,
            "items": [],
        }

    if betting_href:
        extra_links: list[dict[str, str]] = []
        if live_href and live_href != betting_href:
            extra_links.append({"href": live_href, "label": "Open Prop Live Lens" if is_active_today else "Open Live Lens"})
        return {
            "eyebrow": "Props board",
            "title": betting_label or "Betting Card",
            "kicker": "Pregame betting-card route",
            "summary": "Pregame prop rows on the home board now come from the same ranked recommendation payload used by the sport's betting card.",
            "status_label": "Betting-card props",
            "opportunity_tags": [str(betting_label or "Betting Card"), "Pregame props"] + (["Live Lens"] if live_href else []),
            "primary_href": betting_href,
            "primary_label": f"Open {betting_label}" if betting_label else "Open Betting Card",
            "secondary_href": fallback_href if fallback_href and fallback_href != betting_href else None,
            "secondary_label": f"Open {fallback_label}" if fallback_href and fallback_href != betting_href and fallback_label else None,
            "extra_links": extra_links,
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
        if selected_date != today_value and _nba_has_live_games(today_value):
            selected_date = today_value
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
        if selected_date != today_value and _wnba_has_live_games(today_value):
            selected_date = today_value
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
    live_href, live_label = _link_lookup_any(links, ["Live Lens", "Live Prop Audit"])
    cards_href, cards_label = _link_lookup_any(links, ["Cards"])
    props_href, props_label = _link_lookup_any(links, ["Props", "Top props", "Prop Ladders", "Pitcher top props", "Hitter top props", "Pitcher ladders", "Hitter ladders"])
    betting_href, betting_label = _link_lookup_any(links, ["Betting Card"])
    picks_href, picks_label = _link_lookup_any(links, ["Picks", "Season Review"])
    game_bar["items"] = game_items
    pregame_prop_items = _finalize_home_prop_rows(
        _load_home_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=selected_week,
            is_active_today=active_today,
            lane="pregame",
        ),
        slug=slug,
        context_label=context_label,
        home_games=home_games,
    )
    live_prop_items = _finalize_home_prop_rows(
        _load_home_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=selected_week,
            is_active_today=active_today,
            lane="live",
        ),
        slug=slug,
        context_label=context_label,
        home_games=home_games,
    )
    props_bar["items"] = list(pregame_prop_items)
    if game_bar["items"]:
        overview_stats = [{"label": "Games", "value": str(game_count)}] + overview_stats[1:]
    if pregame_prop_items:
        props_bar["summary"] = f"{len(pregame_prop_items)} pregame props surfaced from the {sport.get('name') or slug.upper()} betting card payload."
    else:
        props_bar["summary"] = "No pregame prop rows were available from the sport betting card payload for this slate."

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
        "home_rails": {
            "compact": {
                "title": "Compact game rail",
                "items": game_items,
                "links": _rail_links(
                    (live_href or cards_href or primary_href, f"Open {live_label}" if live_href and live_label else (f"Open {cards_label}" if cards_href and cards_label else "Open Cards")),
                    (betting_href or cards_href or primary_href, f"Open {betting_label}" if betting_href and betting_label else (f"Open {cards_label}" if cards_href and cards_label else "Open Board")),
                    (hub_href, f"Open {sport.get('name') or slug.upper()} Hub"),
                ),
                "empty_summary": f"No compact game cards were surfaced for {context_label}.",
            },
            "pregame": {
                "title": "Pregame props",
                "items": pregame_prop_items,
                "links": _rail_links(
                    (betting_href or props_href or primary_href, f"Open {betting_label}" if betting_href and betting_label else (f"Open {props_label}" if props_href and props_label else "Open Betting Card")),
                    (props_href if props_href != betting_href else picks_href, f"Open {props_label}" if props_href and props_href != betting_href and props_label else (f"Open {picks_label}" if picks_href and picks_label else None)),
                    (hub_href, f"Open {sport.get('name') or slug.upper()} Hub"),
                ),
                "empty_summary": "No pregame prop rows were available from the sport betting card payload for this slate.",
            },
            "live": {
                "title": "Top Live Props",
                "items": live_prop_items,
                "links": _rail_links(
                    (live_href or primary_href, f"Open {live_label}" if live_href and live_label else "Open Live Lens"),
                    (betting_href or props_href or hub_href, f"Open {betting_label}" if betting_href and betting_label else (f"Open {props_label}" if props_href and props_label else f"Open {sport.get('name') or slug.upper()} Hub")),
                ),
                "empty_summary": "Top live props only appear when games are in progress." if not live_prop_items else f"No live prop rows were available for {context_label}.",
            },
        },
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