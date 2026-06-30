from __future__ import annotations

import ast
from copy import deepcopy
import csv
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import lru_cache
import json
import math
import os
import re
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.basketball_live_artifacts import build_live_lines_payload_from_artifacts
from syndicate.features.shared.basketball_live_artifacts import build_live_player_lens_payload_from_artifacts
from syndicate.features.shared.basketball_live_artifacts import resolve_event_ids_from_games
from syndicate.features.shared.game_board_contract import _sim_payload
from syndicate.features.wnba.sources import available_dates
from syndicate.features.wnba.sources import build_module_links
from syndicate.features.wnba.sources import format_moneyline
from syndicate.features.wnba.sources import format_num
from syndicate.features.wnba.sources import format_signed_num
from syndicate.features.wnba.sources import load_json
from syndicate.features.wnba.sources import has_games_for_date
from syndicate.features.wnba.sources import live_snapshot_path
from syndicate.features.wnba.sources import market_label
from syndicate.features.wnba.sources import parse_iso_date
from syndicate.features.wnba.sources import processed_root
from syndicate.features.wnba.sources import processed_path
from syndicate.features.wnba.sources import _source_roots as _wnba_source_roots
from syndicate.features.shared.source_roots import repo_root_from as _repo_root_from
from syndicate.features.shared.timezone import central_now
from syndicate.features.shared.timezone import central_today_iso


_WNBA_CARDS_CONTEXT_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _render_web_dyno() -> bool:
    return bool(
        str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}
        or str(os.environ.get("RENDER_EXTERNAL_URL") or "").strip()
        or str(os.environ.get("RENDER_SERVICE_ID") or "").strip()
    )


def _path_cache_signature(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        if not path.exists() or not path.is_file():
            return 0
        stat = path.stat()
        return int((stat.st_mtime_ns << 16) ^ int(stat.st_size))
    except OSError:
        return 0


def _canonical_wnba_tri(team_tri: str) -> str:
    value = str(team_tri or "").strip().upper()
    compact = "".join(ch for ch in value if ch.isalnum())
    mapped = {
        "LA": "LAS",
        "LV": "LVA",
        "LVA": "LVA",
        "GS": "GSV",
        "GSW": "GSV",
        "NY": "NYL",
        "CONN": "CON",
        "WAS": "WSH",
        "LASVEGASACES": "LVA",
        "LOSANGELESSPARKS": "LAS",
        "NEWYORKLIBERTY": "NYL",
        "CONNECTICUTSUN": "CON",
        "WASHINGTONMYSTICS": "WSH",
        "INDIANAFEVER": "IND",
        "MINNESOTALYNX": "MIN",
        "SEATTLESTORM": "SEA",
        "PHOENIXMERCURY": "PHX",
        "DALLASWINGS": "DAL",
        "ATLANTADREAM": "ATL",
        "CHICAGOSKY": "CHI",
        "GOLDENSTATEVALKYRIES": "GSV",
    }
    return mapped.get(value, mapped.get(compact, value))


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _recommendation_index(summary: dict[str, Any] | None) -> dict[tuple[str, str], list[dict[str, Any]]]:
    per_game = summary.get("per_game") if isinstance((summary or {}).get("per_game"), list) else []
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in per_game:
        if not isinstance(item, dict):
            continue
        away = _canonical_wnba_tri(str(item.get("away") or "").strip().upper())
        home = _canonical_wnba_tri(str(item.get("home") or "").strip().upper())
        picks = item.get("picks") if isinstance(item.get("picks"), list) else []
        if away and home:
            index[(away, home)] = [pick for pick in picks if isinstance(pick, dict)]
    return index


def _artifact_games_index(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    payload = load_json(path)
    games = payload.get("games") if isinstance((payload or {}).get("games"), list) else []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        away = _canonical_wnba_tri(str(game.get("away_tri") or "").strip().upper())
        home = _canonical_wnba_tri(str(game.get("home_tri") or "").strip().upper())
        if away and home:
            index[(away, home)] = game
    return index


def _props_index_from_recommendations_rows(
    game_rows: list[dict[str, str]],
    prop_rows: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    games: dict[tuple[str, str], dict[str, Any]] = {}
    for row in game_rows:
        if not isinstance(row, dict):
            continue
        away_tri = _canonical_wnba_tri(
            str(
                row.get("away_tri")
                or row.get("visitor_team")
                or row.get("away_team")
                or row.get("away")
                or ""
            ).strip().upper()
        )
        home_tri = _canonical_wnba_tri(
            str(
                row.get("home_tri")
                or row.get("home_team")
                or row.get("home")
                or ""
            ).strip().upper()
        )
        if away_tri and home_tri:
            games[(away_tri, home_tri)] = {"prop_recommendations": {"away": [], "home": []}}

    for raw in prop_rows:
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

        team_tri = _canonical_wnba_tri(
            str(raw.get("team_tri") or raw.get("team_tricode") or raw.get("team") or "").strip().upper()
        )
        opponent_tri = _canonical_wnba_tri(
            str(raw.get("opponent_tri") or raw.get("opponent_tricode") or raw.get("opponent") or "").strip().upper()
        )
        if not team_tri or not opponent_tri:
            continue

        target_key: tuple[str, str] | None = None
        side_key: str | None = None
        if (team_tri, opponent_tri) in games:
            target_key = (team_tri, opponent_tri)
            side_key = "away"
        elif (opponent_tri, team_tri) in games:
            target_key = (opponent_tri, team_tri)
            side_key = "home"
        if target_key is None or side_key is None:
            continue

        row_payload = {
            "player": _safe_text(raw.get("player") or raw.get("player_name") or "Prop", "Prop"),
            "team": team_tri,
            "opponent": opponent_tri,
            "market": str(top_play.get("market") or raw.get("market") or "").strip(),
            "pick": str(top_play.get("side") or raw.get("side") or "").strip().upper(),
            "picks": [dict(top_play)],
            "best": dict(top_play),
            "score": _safe_float(raw.get("score") or raw.get("score_adj") or top_play.get("ev_pct") or top_play.get("ev")),
            "recommendation_priority_score": _safe_float(raw.get("score_adj") or raw.get("recommendation_priority_score") or top_play.get("ev_pct") or top_play.get("ev")),
            "tier": raw.get("tier"),
            "opponent": opponent_tri,
            "game_id": raw.get("game_id"),
        }
        games[target_key]["prop_recommendations"][side_key].append(row_payload)

    return games


def _raw_smart_sim_index(selected_date: str) -> dict[tuple[str, str], dict[str, Any]]:
    processed_root_path = processed_root()
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for path in processed_root_path.glob(f"smart_sim_{selected_date}_*.json"):
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        away = _canonical_wnba_tri(str(payload.get("away") or "").strip().upper())
        home = _canonical_wnba_tri(str(payload.get("home") or "").strip().upper())
        if away and home:
            index[(away, home)] = {"away_tri": away, "home_tri": home, "sim": payload}
    return index


def _merge_sim_indexes(cards_sim_index: dict[tuple[str, str], dict[str, Any]], raw_sim_index: dict[tuple[str, str], dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {
        key: dict(value) for key, value in cards_sim_index.items() if isinstance(value, dict)
    }
    for key, raw_game in raw_sim_index.items():
        raw_sim = _sim_payload(raw_game)
        existing = merged.get(key)
        if not isinstance(existing, dict):
            merged[key] = {"away_tri": key[0], "home_tri": key[1], "sim": dict(raw_sim)}
            continue
        existing_sim = existing.get("sim") if isinstance(existing.get("sim"), dict) else {}
        merged_sim = dict(existing_sim)
        for field_name in ("quarters", "players_summary", "players", "missing_prop_players", "injuries", "pregame_context"):
            if field_name in merged_sim:
                continue
            raw_value = raw_sim.get(field_name)
            if raw_value is not None:
                merged_sim[field_name] = deepcopy(raw_value)
        merged_game = dict(existing)
        merged_game["sim"] = merged_sim
        merged[key] = merged_game
    return merged


def _nearest_available_cards_date(selected_date: str) -> str | None:
    dates = available_dates()
    if not dates:
        return None
    if selected_date in dates:
        return selected_date
    parsed_selected = parse_iso_date(selected_date)
    dated_values = sorted((parse_iso_date(value), value) for value in dates)
    for parsed_value, value in dated_values:
        if parsed_value >= parsed_selected:
            return value
    return dated_values[-1][1]


def _resolved_source_cards_date(selected_date: str, *, allow_stored_date_fallback: bool = False) -> str:
    requested_date = str(selected_date or "").strip() or parse_iso_date(selected_date).isoformat()
    if has_games_for_date(requested_date) is False:
        if not allow_stored_date_fallback:
            return requested_date
    resolved_date = requested_date
    bundle = _artifact_bundle(resolved_date)
    if bundle["rows"]:
        return resolved_date
    if not allow_stored_date_fallback:
        return requested_date
    fallback_date = None
    dates = available_dates()
    if resolved_date == central_today_iso():
        earlier_dates = [value for value in dates if value and value != resolved_date and value < resolved_date]
        if earlier_dates:
            fallback_date = earlier_dates[-1]
    if fallback_date is None:
        fallback_date = _nearest_available_cards_date(resolved_date)
        if fallback_date == resolved_date and resolved_date in dates:
            prior_dates = [value for value in dates if value and value < resolved_date]
            if prior_dates:
                fallback_date = prior_dates[-1]
    return fallback_date if fallback_date else resolved_date


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback
def _wnba_generated_at() -> str:
    return central_now().isoformat(timespec="seconds")


def _parse_utc_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _looks_live_status_text(*values: Any) -> bool:
    text = " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())
    if not text:
        return False
    return any(token in text for token in ("live", "in progress", "q1", "q2", "q3", "q4", "ot", "halftime"))


def _looks_terminal_status_text(*values: Any) -> bool:
    text = " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())
    if not text:
        return False
    return any(
        token in text
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


def _normalized_game_status(
    *,
    status_text: Any,
    detail_text: Any,
    start_time_utc: Any,
    in_progress: Any,
    final: Any,
    away_pts: Any = None,
    home_pts: Any = None,
) -> dict[str, Any]:
    status_raw = str(status_text or "").strip()
    detail_raw = str(detail_text or "").strip()
    live = bool(in_progress)
    is_final = bool(final)

    if _looks_live_status_text(status_raw, detail_raw):
        live = True
    if _looks_terminal_status_text(status_raw, detail_raw):
        is_final = True

    if not live and not is_final:
        start_dt = _parse_utc_datetime(start_time_utc)
        if start_dt is not None and start_dt <= datetime.now(timezone.utc) - timedelta(hours=3):
            # Upstream feeds can lag terminal flags; settle stale past-start rows as final.
            is_final = True

    if live:
        is_final = False

    period, clock = _infer_period_clock_from_status_text(detail_raw or status_raw)

    away_val = _safe_float(away_pts)
    home_val = _safe_float(home_pts)

    if is_final:
        status_label = "Final"
    elif live:
        status_label = "Live"
    else:
        status_label = "Scheduled"

    if is_final:
        detail = detail_raw if _looks_terminal_status_text(detail_raw) else "Final"
    elif live:
        detail = detail_raw or status_raw or "Live"
    else:
        detail = detail_raw or status_raw or "Scheduled"

    return {
        "status": status_label,
        "detail": detail,
        "in_progress": bool(live),
        "final": bool(is_final),
        "has_score": bool(away_val is not None and home_val is not None),
        "period": period,
        "clock": clock,
    }


def _implied_prob_from_american(price: float | None) -> float | None:
    value = _safe_float(price)
    if value is None or value == 0:
        return None
    if value > 0:
        return 100.0 / (value + 100.0)
    return abs(value) / (abs(value) + 100.0)


def _american_from_prob(probability: float | None) -> float | None:
    prob = _safe_float(probability)
    if prob is None:
        return None
    prob = max(0.02, min(0.98, prob))
    if prob >= 0.5:
        return round(-100.0 * prob / max(0.001, 1.0 - prob), 0)
    return round(100.0 * (1.0 - prob) / max(0.001, prob), 0)


def _round_half(value: float | None) -> float | None:
    number = _safe_float(value)
    if number is None:
        return None
    return round(number * 2.0) / 2.0


def _remote_source_base_url() -> str:
    for name in (
        "SYNDICATE_WNBA_SOURCE_APP_BASE_URL",
        "SYNDICATE_SOURCE_APP_BASE_URL_WNBA",
        "WNBA_BETTING_BASE_URL",
        "NBA_BETTING_BASE_URL",
    ):
        value = str(os.environ.get(name) or "").strip()
        if value:
            if "://" not in value:
                return f"https://{value}".rstrip("/")
            return value.rstrip("/")
    return ""


def _remote_source_auth_token() -> str:
    for name in (
        "SYNDICATE_WNBA_SOURCE_APP_TOKEN",
        "SYNDICATE_SOURCE_APP_TOKEN_WNBA",
        "WNBA_BETTING_CRON_TOKEN",
        "WNBA_CRON_TOKEN",
        "CRON_TOKEN",
    ):
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _remote_source_fallback_enabled() -> bool:
    source_flag = str(os.environ.get("SYNDICATE_WNBA_SOURCE_APP_FALLBACK") or "").strip().lower()
    if source_flag in {"1", "true", "yes", "on"}:
        return True
    if source_flag in {"0", "false", "no", "off"}:
        return False
    value = str(os.environ.get("WNBA_LIVE_REMOTE_FALLBACK") or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return False


def _remote_live_snapshot_payload(
    kind: str,
    *,
    selected_date: str,
    event_ids: list[str] | None = None,
    include_period_totals: bool = False,
) -> dict[str, Any] | None:
    base_url = _remote_source_base_url()
    if not base_url:
        return None
    endpoint_map = {
        "live_state": "/api/live_state",
        "live_player_boxscore": "/api/live_player_boxscore",
        "live_player_lens": "/api/live_player_lens",
        "live_lines": "/api/live_lines",
        "live_pbp_stats": "/api/live_pbp_stats",
    }
    endpoint = endpoint_map.get(str(kind or "").strip().lower())
    if not endpoint:
        return None
    params: dict[str, str] = {}
    date_value = str(selected_date or "").strip()
    if date_value:
        params["date"] = date_value
    cleaned_event_ids = [str(item).strip() for item in (event_ids or []) if str(item).strip()]
    if cleaned_event_ids:
        params["event_ids"] = ",".join(dict.fromkeys(cleaned_event_ids))
    if str(kind).strip().lower() == "live_lines":
        params["include_period_totals"] = "1" if include_period_totals else "0"
    query = urllib_parse.urlencode(params)
    url = f"{base_url}{endpoint}{'?' + query if query else ''}"

    headers = {"User-Agent": "Syndicate-WNBA/1.0"}
    token = _remote_source_auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib_request.Request(url, headers=headers)
    try:
        with urllib_request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _sum_valid(values: list[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return round(sum(valid), 3)


def _margin_win_prob(margin_mean: float | None, scale: float = 3.4) -> float | None:
    margin = _safe_float(margin_mean)
    if margin is None:
        return None
    exponent = max(-60.0, min(60.0, -margin / max(scale, 0.001)))
    return 1.0 / (1.0 + math.exp(exponent))


def _quarter_values(players: list[dict[str, Any]], stat_key: str, quarter_index: int) -> list[float | None]:
    values: list[float | None] = []
    for row in players:
        buckets = row.get(stat_key) if isinstance(row.get(stat_key), list) else []
        if quarter_index < len(buckets):
            values.append(_safe_float(buckets[quarter_index]))
    return values


def _source_quarter_summary_periods(sim_game: dict[str, Any] | None) -> dict[str, dict[str, float | None]]:
    if not isinstance(sim_game, dict):
        return {}
    sim = _sim_payload(sim_game)
    periods_source = sim.get("periods") if isinstance(sim.get("periods"), dict) else {}
    if periods_source:
        periods: dict[str, dict[str, float | None]] = {}
        for period_key, period_payload in periods_source.items():
            period_name = str(period_key or "").strip().lower()
            if period_name not in {"q1", "q2", "q3", "q4"} or not isinstance(period_payload, dict):
                continue
            away_mean = _safe_float(period_payload.get("away_mean") or period_payload.get("away_pts_mu"))
            home_mean = _safe_float(period_payload.get("home_mean") or period_payload.get("home_pts_mu"))
            total_mean = _safe_float(period_payload.get("total_mean"))
            margin_mean = _safe_float(period_payload.get("margin_mean"))
            if away_mean is None or home_mean is None:
                if total_mean is None or margin_mean is None:
                    continue
                away_mean = round((total_mean - margin_mean) / 2.0, 3)
                home_mean = round((total_mean + margin_mean) / 2.0, 3)
            if total_mean is None:
                total_mean = round(away_mean + home_mean, 3)
            if margin_mean is None:
                margin_mean = round(home_mean - away_mean, 3)
            periods[period_name] = {
                "away_mean": away_mean,
                "home_mean": home_mean,
                "total_mean": total_mean,
                "margin_mean": margin_mean,
                "p_home_win": _margin_win_prob(margin_mean),
            }
        if periods:
            return periods
    quarters = sim.get("quarters") if isinstance(sim.get("quarters"), list) else []
    periods: dict[str, dict[str, float | None]] = {}
    for quarter in quarters:
        if not isinstance(quarter, dict):
            continue
        quarter_number = int(quarter.get("q") or 0)
        if quarter_number not in (1, 2, 3, 4):
            continue
        away_mean = _safe_float(quarter.get("away_pts_mu"))
        home_mean = _safe_float(quarter.get("home_pts_mu"))
        if away_mean is None and home_mean is None:
            continue
        total_mean = None if away_mean is None or home_mean is None else round(away_mean + home_mean, 3)
        margin_mean = None if away_mean is None or home_mean is None else round(home_mean - away_mean, 3)
        periods[f"q{quarter_number}"] = {
            "away_mean": away_mean,
            "home_mean": home_mean,
            "total_mean": total_mean,
            "margin_mean": margin_mean,
            "p_home_win": _margin_win_prob(margin_mean),
        }
    return periods


def _source_sim_periods(sim_game: dict[str, Any] | None) -> dict[str, dict[str, float | None]]:
    if not isinstance(sim_game, dict):
        return {}
    summary_periods = _source_quarter_summary_periods(sim_game)
    if summary_periods:
        return summary_periods
    sim = _sim_payload(sim_game)
    players = sim.get("players") if isinstance(sim.get("players"), dict) else {}
    away_players = [row for row in (players.get("away") or []) if isinstance(row, dict)]
    home_players = [row for row in (players.get("home") or []) if isinstance(row, dict)]
    periods: dict[str, dict[str, float | None]] = {}
    for quarter_index, quarter_key in enumerate(("q1", "q2", "q3", "q4")):
        away_values = _quarter_values(away_players, "q_pts", quarter_index)
        home_values = _quarter_values(home_players, "q_pts", quarter_index)
        if not any((value is not None and abs(value) > 1e-9) for value in (away_values + home_values)):
            continue
        away_mean = _sum_valid(away_values)
        home_mean = _sum_valid(home_values)
        if away_mean is None and home_mean is None:
            continue
        total_mean = None if away_mean is None or home_mean is None else round(away_mean + home_mean, 3)
        margin_mean = None if away_mean is None or home_mean is None else round(home_mean - away_mean, 3)
        periods[quarter_key] = {
            "away_mean": away_mean,
            "home_mean": home_mean,
            "total_mean": total_mean,
            "margin_mean": margin_mean,
            "p_home_win": _margin_win_prob(margin_mean),
        }
    return periods


def _format_pct_100(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.1f}%"


def _top_pick_items(picks: list[dict[str, Any]], *, limit: int = 4) -> tuple[list[str], list[dict[str, Any]]]:
    valid_picks = [pick for pick in picks if isinstance(pick, dict)]
    items = [str(pick.get("display_pick") or "").strip() for pick in valid_picks[:limit] if str(pick.get("display_pick") or "").strip()]
    rows = []
    for pick in valid_picks[:limit]:
        label = str(pick.get("player") or pick.get("display_pick") or "").strip()
        if not label:
            continue
        detail_bits = []
        market = market_label(pick.get("market"))
        line = format_num(pick.get("line"))
        side = str(pick.get("side") or pick.get("selection") or "").strip().upper()
        if market != "-" and line != "-":
            detail_bits.append(f"{side} {line} {market}".strip())
        ev_pct = _safe_float(pick.get("ev_pct"))
        if ev_pct is not None:
            detail_bits.append(f"EV {ev_pct:.1f}%")
        win_prob = _safe_float(pick.get("p_win"))
        value = f"{win_prob * 100:.1f}% win" if win_prob is not None else str(pick.get("tier") or "Top play")
        rows.append({"name": label, "detail": " | ".join(detail_bits), "value": value})
    return items, rows


def _sim_table_groups(sim_game: dict[str, Any] | None, away_tri: str, home_tri: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not isinstance(sim_game, dict):
        return [], []
    sim = _sim_payload(sim_game)
    summary = sim.get("players_summary") if isinstance(sim.get("players_summary"), dict) else {}
    stats = [
        {"label": "Away sims", "value": str(summary.get("away") or "-")},
        {"label": "Home sims", "value": str(summary.get("home") or "-")},
        {"label": "Missing", "value": f"{summary.get('missing_away') or 0}/{summary.get('missing_home') or 0}"},
        {"label": "Injured", "value": f"{summary.get('injured_away') or 0}/{summary.get('injured_home') or 0}"},
    ]
    table_groups = []
    players = sim.get("players") if isinstance(sim.get("players"), dict) else {}
    for side_key, label in (("away", away_tri), ("home", home_tri)):
        rows = players.get(side_key) if isinstance(players.get(side_key), list) else []
        top_rows = sorted(
            [row for row in rows if isinstance(row, dict)],
            key=lambda row: (_safe_float(row.get("pra_mean")) or 0.0, _safe_float(row.get("pts_mean")) or 0.0),
            reverse=True,
        )[:4]
        if not top_rows:
            continue
        table_groups.append(
            {
                "heading": f"{label} sim leaders",
                "rows": [
                    {
                        "name": str(row.get("player_name") or "Player").strip() or "Player",
                        "detail": (
                            f"PTS {format_num(row.get('pts_mean'))} | REB {format_num(row.get('reb_mean'))} | AST {format_num(row.get('ast_mean'))}"
                        ),
                        "value": f"PRA {format_num(row.get('pra_mean'))}",
                    }
                    for row in top_rows
                ],
            }
        )
    return table_groups, stats


def _props_table_groups(props_game: dict[str, Any] | None, away_tri: str, home_tri: str) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(props_game, dict):
        return [], []
    prop_recommendations = props_game.get("prop_recommendations") if isinstance(props_game.get("prop_recommendations"), dict) else {}
    table_groups = []
    items: list[str] = []
    for side_key, label in (("away", away_tri), ("home", home_tri)):
        rows = prop_recommendations.get(side_key) if isinstance(prop_recommendations.get(side_key), list) else []
        side_items, side_rows = _top_pick_items(rows)
        items.extend(side_items)
        if side_rows:
            table_groups.append({"heading": f"{label} props", "rows": side_rows})
    return table_groups, items[:4]


def _artifact_paths(selected_date: str) -> dict[str, Path]:
    return {
        "cards": processed_path(f"game_cards_{selected_date}.csv"),
        "recommendations": processed_path(f"recommendations_slate_{selected_date}.json"),
        "sim": processed_path(f"cards_sim_detail_{selected_date}.json"),
        "props": processed_path(f"cards_props_snapshot_{selected_date}.json"),
    }


def _artifact_root_paths(selected_date: str) -> dict[str, Path]:
    root = processed_root()
    return {
        "cards": root / f"game_cards_{selected_date}.csv",
        "recommendations": root / f"recommendations_slate_{selected_date}.json",
        "sim": root / f"cards_sim_detail_{selected_date}.json",
        "props": root / f"cards_props_snapshot_{selected_date}.json",
    }


def _artifact_bundle(selected_date: str) -> dict[str, Any]:
    csv_name = f"game_cards_{selected_date}.csv"
    repo_data_root = _repo_root_from(__file__) / "data" / "wnba_source"
    candidate_roots = list(_wnba_source_roots()) + [repo_data_root]

    if has_games_for_date(selected_date) is False:
        safe_paths = _artifact_root_paths(selected_date)
        return {
            "paths": safe_paths,
            "rows": [],
            "recommendations": {},
            "sim": {},
            "props": {},
        }

    paths = _artifact_root_paths(selected_date)
    rows = []
    for root in candidate_roots:
        alt_path = root / "data" / "processed" / csv_name
        if not alt_path.exists():
            continue
        alt_rows = _load_csv_rows(alt_path)
        if alt_rows:
            rows = alt_rows
            paths = {
                "cards": alt_path,
                "recommendations": root / "data" / "processed" / f"recommendations_slate_{selected_date}.json",
                "sim": root / "data" / "processed" / f"cards_sim_detail_{selected_date}.json",
                "props": root / "data" / "processed" / f"cards_props_snapshot_{selected_date}.json",
            }
            break

    # ✅ Existing
    rec_summary = load_json(paths["recommendations"]) if paths["recommendations"].exists() else None

    # Runtime WNBA fallback is disabled on Render so the deployed app only
    # serves published artifacts.
    if not rows and selected_date == central_today_iso() and not _render_web_dyno():
        try:
            rows, _ = _games_from_live_state_fallback(selected_date)
        except Exception:
            rows = []

    props_index = _artifact_games_index(paths["props"]) if paths["props"].exists() else {}
    if not props_index:
        props_rows_path = processed_root() / f"props_recommendations_{selected_date}.csv"
        if props_rows_path.exists():
            props_rows = _load_csv_rows(props_rows_path)
            if props_rows:
                props_index = _props_index_from_recommendations_rows(rows, props_rows)

    return {
        "paths": paths,
        "rows": rows,
        "recommendations": _recommendation_index(rec_summary),
        "sim": _merge_sim_indexes(
            _artifact_games_index(paths["sim"]) if paths["sim"].exists() else {},
            _raw_smart_sim_index(selected_date),
        ),
        "props": props_index,
    }

def _source_logo_url(team_tri: str) -> str:
    return f"/wnba/api/source/team-logo/{str(team_tri or '').strip().upper()}"


def _source_market_label(value: Any) -> str:
    code = str(value or "").strip().lower()
    return {
        "pts": "Points",
        "reb": "Rebounds",
        "ast": "Assists",
        "pra": "PRA",
        "pa": "PTS+AST",
        "pr": "PTS+REB",
        "ra": "REB+AST",
        "threes": "3PM",
        "blk": "Blocks",
        "stl": "Steals",
        "bs": "BLK+STL",
    }.get(code, market_label(value))


def _source_game_market_recommendations(picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        rows.append(
            {
                "market_label": _source_market_label(pick.get("market")),
                "display_pick": str(pick.get("display_pick") or pick.get("selection") or "").strip() or None,
                "selection": str(pick.get("selection") or pick.get("side") or "").strip().upper() or None,
                "p_win": _safe_float(pick.get("p_win") or pick.get("win_prob")),
                "ev_pct": _safe_float(pick.get("ev_pct")),
                "basketball_summary": str(pick.get("basketball_summary") or "").strip() or None,
                "why_explain": str(pick.get("basketball_summary") or pick.get("display_pick") or "").strip() or None,
                "card_bucket": "playable",
                "recommendation_priority_score": _safe_float(pick.get("recommendation_priority_score") or pick.get("basketball_priority_score") or pick.get("score")),
                "score": _safe_float(pick.get("score") or pick.get("ev_pct")),
                "stake_amount": None,
                "stake_units": None,
                "portfolio_rank": None,
                "portfolio_score": None,
            }
        )
    return rows


def _source_betting(row: dict[str, str]) -> dict[str, Any]:
    home_ml = _safe_float(row.get("home_ml"))
    away_ml = _safe_float(row.get("away_ml"))
    home_spread = _safe_float(row.get("home_spread"))
    total = _safe_float(row.get("total"))
    if total is not None and total <= 1.0:
        total = None

    home_win_prob = _safe_float(row.get("p_home_win") or row.get("prob_home_win"))
    away_win_prob = _safe_float(row.get("p_away_win") or row.get("prob_away_win"))
    if home_win_prob is None and away_win_prob is not None:
        home_win_prob = 1.0 - away_win_prob
    if away_win_prob is None and home_win_prob is not None:
        away_win_prob = 1.0 - home_win_prob

    if home_win_prob is None:
        home_win_prob = _implied_prob_from_american(home_ml)
    if away_win_prob is None:
        away_win_prob = _implied_prob_from_american(away_ml)

    if home_win_prob is None and away_win_prob is not None:
        home_win_prob = 1.0 - away_win_prob
    if away_win_prob is None and home_win_prob is not None:
        away_win_prob = 1.0 - home_win_prob

    if home_win_prob is None:
        margin_hint = _safe_float(row.get("pred_margin") or row.get("margin_mean"))
        home_win_prob = _margin_win_prob(margin_hint, scale=6.5)
        if home_win_prob is not None:
            away_win_prob = 1.0 - home_win_prob

    if home_ml is None and home_win_prob is not None:
        home_ml = _american_from_prob(home_win_prob)
    if away_ml is None and away_win_prob is not None:
        away_ml = _american_from_prob(away_win_prob)

    if home_spread is None:
        margin_hint = _safe_float(row.get("pred_margin") or row.get("margin_mean"))
        if margin_hint is not None:
            home_spread = _round_half(-margin_hint)

    if total is None:
        total_hint = _safe_float(row.get("pred_total") or row.get("total_mean"))
        if total_hint is not None and total_hint > 1.0:
            total = _round_half(total_hint)

    home_cover_prob = _safe_float(row.get("p_home_cover") or row.get("prob_home_cover"))
    away_cover_prob = _safe_float(row.get("p_away_cover") or row.get("prob_away_cover"))
    if home_cover_prob is None and away_cover_prob is not None:
        home_cover_prob = 1.0 - away_cover_prob
    if away_cover_prob is None and home_cover_prob is not None:
        away_cover_prob = 1.0 - home_cover_prob

    if home_cover_prob is None and home_spread is not None:
        margin_hint = _safe_float(row.get("pred_margin") or row.get("margin_mean"))
        if margin_hint is not None:
            home_cover_prob = _margin_win_prob(margin_hint + home_spread, scale=7.5)
            if home_cover_prob is not None:
                away_cover_prob = 1.0 - home_cover_prob

    total_over_prob = _safe_float(row.get("p_total_over") or row.get("prob_total_over"))
    total_under_prob = _safe_float(row.get("p_total_under") or row.get("prob_total_under"))
    if total_over_prob is None and total_under_prob is not None:
        total_over_prob = 1.0 - total_under_prob
    if total_under_prob is None and total_over_prob is not None:
        total_under_prob = 1.0 - total_over_prob

    if total_over_prob is None and total is not None:
        total_hint = _safe_float(row.get("pred_total") or row.get("total_mean"))
        if total_hint is not None:
            total_over_prob = _margin_win_prob(total_hint - total, scale=10.5)
            if total_over_prob is not None:
                total_under_prob = 1.0 - total_over_prob

    return {
        "home_ml": home_ml,
        "away_ml": away_ml,
        "home_spread": home_spread,
        "total": total,
        "home_ml_ev": None,
        "away_ml_ev": None,
        "home_spread_ev": None,
        "away_spread_ev": None,
        "over_ev": None,
        "under_ev": None,
        "p_home_win": home_win_prob,
        "p_away_win": away_win_prob,
        "p_home_cover": home_cover_prob,
        "p_away_cover": away_cover_prob,
        "p_total_over": total_over_prob,
        "p_total_under": total_under_prob,
    }


def _source_sim_score(sim_game: dict[str, Any] | None, row: dict[str, str]) -> dict[str, float | None]:
    sim = _sim_payload(sim_game)
    players = sim.get("players") if isinstance(sim.get("players"), dict) else {}

    def _team_total(side: str) -> float | None:
        rows = players.get(side) if isinstance(players.get(side), list) else []
        points = [_safe_float(item.get("pts_mean")) for item in rows if isinstance(item, dict)]
        valid = [value for value in points if value is not None]
        if not valid:
            return None
        return round(sum(valid), 3)

    away_mean = _team_total("away")
    home_mean = _team_total("home")
    total_mean = _safe_float(row.get("pred_total") or row.get("total_mean") or row.get("total"))
    if total_mean is not None and total_mean <= 1.0:
        total_mean = None
    margin_mean = _safe_float(row.get("pred_margin") or row.get("margin_mean") or row.get("home_spread"))
    if margin_mean is not None and abs(margin_mean) <= 1.0 and not row.get("pred_margin") and not row.get("margin_mean"):
        margin_mean = None
    if away_mean is None and home_mean is None and total_mean is not None and margin_mean is not None:
        away_mean = round((total_mean - margin_mean) / 2.0, 3)
        home_mean = round((total_mean + margin_mean) / 2.0, 3)
    if away_mean is not None and home_mean is not None:
        total_mean = round(away_mean + home_mean, 3)
    if away_mean is not None and home_mean is not None:
        margin_mean = round(home_mean - away_mean, 3)
    return {
        "away_mean": away_mean,
        "home_mean": home_mean,
        "total_mean": total_mean,
        "margin_mean": margin_mean,
    }


def _source_interval_summary(periods: dict[str, dict[str, float | None]], keys: tuple[str, ...]) -> dict[str, float | None] | None:
    selected = [periods.get(key) for key in keys if isinstance(periods.get(key), dict)]
    if not selected:
        return None
    away_values = [_safe_float(period.get("away_mean")) for period in selected]
    home_values = [_safe_float(period.get("home_mean")) for period in selected]
    away_mean = _sum_valid(away_values)
    home_mean = _sum_valid(home_values)
    if away_mean is None or home_mean is None:
        return None
    total_mean = round(away_mean + home_mean, 3)
    margin_mean = round(home_mean - away_mean, 3)
    return {
        "away_mean": away_mean,
        "home_mean": home_mean,
        "total_mean": total_mean,
        "margin_mean": margin_mean,
        "p_home_win": _margin_win_prob(margin_mean),
    }


def _source_interval_models(periods: dict[str, dict[str, float | None]]) -> dict[str, Any]:
    quarter_periods = {key: dict(value) for key, value in periods.items() if key in {"q1", "q2", "q3", "q4"} and isinstance(value, dict)}
    half_periods = {
        "h1": _source_interval_summary(periods, ("q1", "q2")),
        "h2": _source_interval_summary(periods, ("q3", "q4")),
    }
    half_periods = {key: value for key, value in half_periods.items() if isinstance(value, dict)}
    return {
        "quarters": quarter_periods,
        "halves": half_periods,
    }


def _source_mode(context: dict[str, Any] | None) -> str:
    source_title = str((context or {}).get("source_title") or "").strip().lower()
    if not source_title:
        return "unknown"
    if "live" in source_title:
        return "live"
    if "fallback" in source_title or "unavailable" in source_title:
        return "fallback"
    if "processed" in source_title or "cards" in source_title or "props" in source_title:
        return "processed"
    return "unknown"


def _source_sim_payload(game_id: str, sim_game: dict[str, Any] | None, row: dict[str, str]) -> dict[str, Any]:
    sim = _sim_payload(sim_game)
    players_summary = dict(sim.get("players_summary") or {}) if isinstance(sim, dict) else {}
    players = sim.get("players") if isinstance(sim.get("players"), dict) else {}
    missing_prop_players = sim.get("missing_prop_players") if isinstance(sim.get("missing_prop_players"), dict) else {}
    injuries = sim.get("injuries") if isinstance(sim.get("injuries"), dict) else {}
    pregame_context = sim.get("pregame_context") if isinstance(sim.get("pregame_context"), dict) else {}
    quarters = sim.get("quarters") if isinstance(sim.get("quarters"), list) else []
    score = _source_sim_score(sim_game, row)
    periods = _source_sim_periods(sim_game)
    return {
        "game_id": game_id,
        "players_loaded": bool(players.get("away") or players.get("home")),
        "players_summary": {
            "away": int(players_summary.get("away") or 0),
            "home": int(players_summary.get("home") or 0),
            "missing_away": int(players_summary.get("missing_away") or 0),
            "missing_home": int(players_summary.get("missing_home") or 0),
            "injured_away": int(players_summary.get("injured_away") or 0),
            "injured_home": int(players_summary.get("injured_home") or 0),
        },
        "players": {
            "away": [dict(item) for item in (players.get("away") or []) if isinstance(item, dict)],
            "home": [dict(item) for item in (players.get("home") or []) if isinstance(item, dict)],
        },
        "missing_prop_players": {
            "away": [dict(item) for item in (missing_prop_players.get("away") or []) if isinstance(item, dict)],
            "home": [dict(item) for item in (missing_prop_players.get("home") or []) if isinstance(item, dict)],
        },
        "injuries": {
            "away": [dict(item) for item in (injuries.get("away") or []) if isinstance(item, dict)],
            "home": [dict(item) for item in (injuries.get("home") or []) if isinstance(item, dict)],
        },
        "pregame_context": dict(pregame_context),
        "quarters": [dict(item) for item in quarters if isinstance(item, dict)],
        "score": score,
        "periods": periods,
        "intervals": _source_interval_models(periods),
        "market": {
            "market_home_spread": _safe_float(row.get("home_spread")),
            "market_total": _safe_float(row.get("total")),
        },
    }


def _source_sim_stub(game_id: str, sim_game: dict[str, Any] | None, row: dict[str, str]) -> dict[str, Any]:
    return _source_sim_payload(game_id, sim_game, row)


def _wnba_advanced_simulation_contract(sim_payload: dict[str, Any] | None) -> dict[str, Any]:
    sim = sim_payload if isinstance(sim_payload, dict) else {}
    players = sim.get("players") if isinstance(sim.get("players"), dict) else {}
    periods = _source_sim_periods({"sim": sim})
    intervals = sim.get("intervals") if isinstance(sim.get("intervals"), dict) else {}
    if not intervals:
        intervals = _source_interval_models(periods)
    players_summary = dict(sim.get("players_summary") or {}) if isinstance(sim.get("players_summary"), dict) else {}
    if not players_summary:
        players_summary = {
            "away": len(players.get("away") or []),
            "home": len(players.get("home") or []),
            "missing_away": 0,
            "missing_home": 0,
            "injured_away": 0,
            "injured_home": 0,
        }
    return {
        "score": dict(sim.get("score") or {}),
        "periods": periods,
        "intervals": intervals,
        "quarters": [dict(item) for item in (sim.get("quarters") or []) if isinstance(item, dict)],
        "players_summary": players_summary,
        "players": {
            "away": [dict(item) for item in (players.get("away") or []) if isinstance(item, dict)],
            "home": [dict(item) for item in (players.get("home") or []) if isinstance(item, dict)],
        },
        "missing_prop_players": {
            "away": [dict(item) for item in (sim.get("missing_prop_players", {}).get("away") or []) if isinstance(item, dict)] if isinstance(sim.get("missing_prop_players"), dict) else [],
            "home": [dict(item) for item in (sim.get("missing_prop_players", {}).get("home") or []) if isinstance(item, dict)] if isinstance(sim.get("missing_prop_players"), dict) else [],
        },
        "injuries": {
            "away": [dict(item) for item in (sim.get("injuries", {}).get("away") or []) if isinstance(item, dict)] if isinstance(sim.get("injuries"), dict) else [],
            "home": [dict(item) for item in (sim.get("injuries", {}).get("home") or []) if isinstance(item, dict)] if isinstance(sim.get("injuries"), dict) else [],
        },
        "pregame_context": dict(sim.get("pregame_context") or {}),
    }


def _wnba_advanced_game_contract(game: dict[str, Any]) -> dict[str, Any]:
    sim = _sim_payload(game)
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    prop_recommendations = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}
    game_market_recommendations = game.get("game_market_recommendations") if isinstance(game.get("game_market_recommendations"), list) else []
    return {
        "game_id": _safe_text(game.get("game_id") or game.get("gamePk") or "", ""),
        "event_id": _safe_text(game.get("event_id") or "", ""),
        "matchup": {
            "away": {
                "tri": _safe_text(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else ""), ""),
                "name": _safe_text(game.get("away_name") or ((game.get("away") or {}).get("name") if isinstance(game.get("away"), dict) else ""), ""),
            },
            "home": {
                "tri": _safe_text(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else ""), ""),
                "name": _safe_text(game.get("home_name") or ((game.get("home") or {}).get("name") if isinstance(game.get("home"), dict) else ""), ""),
            },
        },
        "status": {
            "status": _safe_text(game.get("status") or "", ""),
            "detail": _safe_text(game.get("detail") or "", ""),
            "live": bool((game.get("live_state") or {}).get("in_progress") if isinstance(game.get("live_state"), dict) else False),
            "final": bool((game.get("live_state") or {}).get("final") if isinstance(game.get("live_state"), dict) else False),
        },
        "market": {
            "home_ml": _safe_float(betting.get("home_ml")),
            "away_ml": _safe_float(betting.get("away_ml")),
            "home_spread": _safe_float(betting.get("home_spread")),
            "total": _safe_float(betting.get("total")),
            "p_home_win": _safe_float(betting.get("p_home_win")),
            "p_away_win": _safe_float(betting.get("p_away_win")),
            "p_home_cover": _safe_float(betting.get("p_home_cover")),
            "p_total_over": _safe_float(betting.get("p_total_over")),
        },
        "simulation": _wnba_advanced_simulation_contract(sim),
        "props": {
            "prop_recommendations": {
                "away": [dict(item) for item in (prop_recommendations.get("away") or []) if isinstance(item, dict)],
                "home": [dict(item) for item in (prop_recommendations.get("home") or []) if isinstance(item, dict)],
            },
            "game_market_recommendations": [dict(item) for item in game_market_recommendations if isinstance(item, dict)],
        },
        "coverage": {
            "has_simulation": bool(sim),
            "has_periods": bool((sim.get("periods") if isinstance(sim, dict) else None) or (sim.get("quarters") if isinstance(sim, dict) else None)),
            "has_intervals": bool((sim.get("intervals") if isinstance(sim, dict) else None) or _source_interval_models(_source_sim_periods({"sim": sim}))),
            "has_players": bool(players := (sim.get("players") if isinstance(sim.get("players"), dict) else {})),
            "has_injuries": bool((sim.get("injuries") if isinstance(sim.get("injuries"), dict) else None)),
            "has_pregame_context": bool((sim.get("pregame_context") if isinstance(sim.get("pregame_context"), dict) else None)),
        },
    }


def _wnba_advanced_contract(*, selected_date: str, requested_date: str, source_title: str, source_path: str, games: list[dict[str, Any]]) -> dict[str, Any]:
    advanced_games = [_wnba_advanced_game_contract(game) for game in games if isinstance(game, dict)]
    coverage = {
        "games_with_sim": sum(1 for game in advanced_games if bool((game.get("coverage") or {}).get("has_simulation"))),
        "games_with_periods": sum(1 for game in advanced_games if bool((game.get("coverage") or {}).get("has_periods"))),
        "games_with_intervals": sum(1 for game in advanced_games if bool((game.get("coverage") or {}).get("has_intervals"))),
        "games_with_players": sum(1 for game in advanced_games if bool((game.get("coverage") or {}).get("has_players"))),
        "games_with_injuries": sum(1 for game in advanced_games if bool((game.get("coverage") or {}).get("has_injuries"))),
        "games_with_props": sum(1 for game in advanced_games if bool(((game.get("props") or {}).get("prop_recommendations") or {}).get("away") or ((game.get("props") or {}).get("prop_recommendations") or {}).get("home"))),
    }
    return {
        "available": bool(advanced_games),
        "sport": "wnba",
        "selection": {
            "kind": "date",
            "requested": _safe_text(requested_date, ""),
            "resolved": _safe_text(selected_date, ""),
        },
        "source": {
            "title": _safe_text(source_title, ""),
            "path": _safe_text(source_path, ""),
            "mode": _source_mode({"source_title": source_title}),
        },
        "freshness": {
            "requested": _safe_text(requested_date, ""),
            "resolved": _safe_text(selected_date, ""),
            "selection_kind": "date",
            "is_current_day": _safe_text(selected_date, "") == central_today_iso(),
            "is_stale": _safe_text(requested_date, "") != _safe_text(selected_date, ""),
            "lookahead_applied": bool(_safe_text(requested_date, "") != _safe_text(selected_date, "")),
        },
        "coverage": coverage,
        "game_count": len(advanced_games),
        "games": advanced_games,
    }


def _wnba_row_game_id(row: dict[str, Any], *, idx: int, away_tri: str, home_tri: str) -> str:
    event_id = str(row.get("event_id") or "").strip()
    if event_id:
        return event_id
    game_id = str(row.get("game_id") or "").strip()
    if game_id and not game_id.isdigit() and game_id != str(idx):
        return game_id
    matchup_id = f"{away_tri}@{home_tri}"
    if matchup_id:
        return matchup_id
    return str(idx)


def _source_game_from_row(
    row: dict[str, str],
    *,
    idx: int,
    selected_date: str,
    rec_index: dict[tuple[str, str], list[dict[str, Any]]],
    sim_index: dict[tuple[str, str], dict[str, Any]],
    props_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    away_name = str(row.get("visitor_team") or "Away").strip() or "Away"
    home_name = str(row.get("home_team") or "Home").strip() or "Home"
    away_tri = _canonical_wnba_tri(str(row.get("away_tri") or away_name[:3]).strip().upper()) or "AWY"
    home_tri = _canonical_wnba_tri(str(row.get("home_tri") or home_name[:3]).strip().upper()) or "HOM"
    picks = rec_index.get((away_tri, home_tri), [])
    sim_game = sim_index.get((away_tri, home_tri))
    props_game = props_index.get((away_tri, home_tri)) if isinstance(props_index.get((away_tri, home_tri)), dict) else {}
    game_id = _wnba_row_game_id(row, idx=idx, away_tri=away_tri, home_tri=home_tri)
    sim_payload = _source_sim_payload(game_id, sim_game, row)
    score = sim_payload.get("score") if isinstance(sim_payload.get("score"), dict) else {}
    betting = _source_betting(
        {
            **row,
            "margin_mean": score.get("margin_mean"),
            "total_mean": score.get("total_mean"),
        }
    )
    return {
        "game_id": game_id,
        "gamePk": game_id,
        "away_tri": away_tri,
        "away_name": away_name,
        "home_tri": home_tri,
        "home_name": home_name,
        "away": away_tri,
        "home": home_tri,
        "away_logo": _source_logo_url(away_tri),
        "home_logo": _source_logo_url(home_tri),
        "start_time": str(row.get("commence_time") or "").strip() or None,
        "odds": {"commence_time": str(row.get("commence_time") or "").strip() or None},
        "status": {"detailed": str(row.get("commence_time") or "Scheduled").strip() or "Scheduled"},
        "summary": f"{row.get('bookmaker') or 'Consensus'} market snapshot",
        "betting": betting,
        "sim": sim_payload,
        "prop_recommendations": dict((props_game or {}).get("prop_recommendations") or {"away": [], "home": []}),
        "game_market_recommendations": _source_game_market_recommendations(picks),
        "live_state": None,
        "warnings": [],
    }


def build_source_cards_payload(selected_date: str, *, allow_stored_date_fallback: bool = False) -> dict[str, Any]:
    requested_date = str(selected_date or "").strip() or parse_iso_date(selected_date).isoformat()
    resolved_date = _resolved_source_cards_date(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    parsed_date = parse_iso_date(resolved_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()
    bundle = _artifact_bundle(resolved_date)
    rows = bundle["rows"]
    rec_index = bundle["recommendations"]
    sim_index = bundle["sim"]
    props_index = bundle["props"]
    used_public_scoreboard_fallback = False
    games = [
        _source_game_from_row(
            row,
            idx=idx,
            selected_date=resolved_date,
            rec_index=rec_index,
            sim_index=sim_index,
            props_index=props_index,
        )
        for idx, row in enumerate(rows, start=1)
    ]
    if not games and resolved_date == central_today_iso():
        public_games, _ = _games_from_public_scoreboard(resolved_date)
        if public_games:
            games = public_games
            used_public_scoreboard_fallback = True
    if resolved_date == central_today_iso() and not used_public_scoreboard_fallback:
        games, _, _, _ = _supplement_games_with_live_state(games, resolved_date)
    return {
        "date": resolved_date,
        "requested_date": requested_date,
        "lookahead_applied": bool(resolved_date != requested_date),
        "players_included": False,
        "pregame_portfolio": {"enabled": False, "selected": 0, "candidates": 0},
        "games": games,
        "module_links": build_module_links(resolved_date, "Cards"),
        "route_path": "/wnba/cards",
        "control_label": "Date",
        "control_type": "date",
        "control_name": "date",
        "control_value": resolved_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "board_contract": {
            "schema": "game_board_v1",
            "surface": "wnba_dense_board_v1",
            "sport": "wnba",
            "module": "cards",
            "source_kind": "artifact_backed",
            "live_lens_integrated": True,
        },
    }


def build_source_cards_sim_detail_payload(selected_date: str, away_tri: str, home_tri: str) -> dict[str, Any]:
    resolved_date = _resolved_source_cards_date(selected_date, allow_stored_date_fallback=True)
    away_key = _canonical_wnba_tri(str(away_tri or "").strip().upper())
    home_key = _canonical_wnba_tri(str(home_tri or "").strip().upper())
    bundle = _artifact_bundle(resolved_date)
    sim_detail = None
    if isinstance(bundle, dict) and isinstance(bundle.get("sim"), dict):
        sim_detail = bundle.get("sim", {}).get((away_key, home_key))
    if isinstance(sim_detail, dict):
        return {
            "date": resolved_date,
            "requested_date": selected_date,
            "players_included": True,
            "games": [
                {
                    "home_tri": home_key,
                    "away_tri": away_key,
                    "sim": {
                        **_source_sim_payload(f"{away_key}@{home_key}", sim_detail, {}),
                    },
                }
            ],
        }

    return {
        "date": resolved_date,
        "requested_date": selected_date,
        "players_included": False,
        "games": [],
    }


def get_wnba_overview(selected_date: str) -> dict[str, Any]:
    requested_date = str(selected_date or "").strip() or parse_iso_date(selected_date).isoformat()
    if has_games_for_date(requested_date) is False:
        return {
            "status": "no_games",
            "date": requested_date,
            "games": [],
            "prop_rows": [],
            "source_title": "WNBA cards unavailable",
            "source_path": str(processed_root() / f"game_cards_{requested_date}.csv"),
        }

    cards_context = build_cards_page_context(requested_date, allow_stored_date_fallback=False)
    games = list(cards_context.get("games") or [])
    if not games:
        return {
            "status": "no_games",
            "date": requested_date,
            "games": [],
            "prop_rows": [],
            "source_title": _safe_text(cards_context.get("source_title"), "WNBA cards unavailable"),
            "source_path": _safe_text(cards_context.get("source_path"), str(processed_root() / f"game_cards_{requested_date}.csv")),
        }

    return {
        "status": "ok",
        "date": str(cards_context.get("date") or requested_date).strip() or requested_date,
        "requested_date": requested_date,
        "games": games,
        "prop_rows": [],
        "source_title": _safe_text(cards_context.get("source_title"), "WNBA cards"),
        "source_path": _safe_text(cards_context.get("source_path"), str(processed_root() / f"game_cards_{requested_date}.csv")),
        "board_contract": cards_context.get("board_contract"),
    }


def _game_from_row(
    row: dict[str, str],
    *,
    idx: int,
    selected_date: str,
    rec_index: dict[tuple[str, str], list[dict[str, Any]]],
    sim_index: dict[tuple[str, str], dict[str, Any]],
    props_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    away_name = str(row.get("visitor_team") or "Away").strip() or "Away"
    home_name = str(row.get("home_team") or "Home").strip() or "Home"
    away_tri = _canonical_wnba_tri(str(row.get("away_tri") or away_name[:3]).strip().upper()) or "AWY"
    home_tri = _canonical_wnba_tri(str(row.get("home_tri") or home_name[:3]).strip().upper()) or "HOM"
    picks = rec_index.get((away_tri, home_tri), [])
    sim_game = sim_index.get((away_tri, home_tri))
    props_game = props_index.get((away_tri, home_tri))
    top_picks, pick_rows = _top_pick_items(picks)
    sim_groups, sim_stats = _sim_table_groups(sim_game, away_tri, home_tri)
    props_groups, prop_items = _props_table_groups(props_game, away_tri, home_tri)
    game_id = _wnba_row_game_id(row, idx=idx, away_tri=away_tri, home_tri=home_tri)
    sim_payload = _source_sim_stub(game_id, sim_game, row)
    score = sim_payload.get("score") if isinstance(sim_payload.get("score"), dict) else {}
    betting = _source_betting(
        {
            **row,
            "margin_mean": score.get("margin_mean"),
            "total_mean": score.get("total_mean"),
        }
    )
    prop_recommendations = dict((props_game or {}).get("prop_recommendations") or {"away": [], "home": []})
    game_market_recommendations = _source_game_market_recommendations(picks)
    normalized_status = _normalized_game_status(
        status_text=row.get("status"),
        detail_text=row.get("commence_time"),
        start_time_utc=row.get("commence_time"),
        in_progress=row.get("in_progress"),
        final=row.get("final"),
    )
    return {
        "game_id": game_id,
        "gamePk": game_id,
        "event_id": str(row.get("event_id") or game_id).strip() or game_id,
        "away_tri": away_tri,
        "away_name": away_name,
        "home_tri": home_tri,
        "home_name": home_name,
        "away_logo": _source_logo_url(away_tri),
        "home_logo": _source_logo_url(home_tri),
        "away": {"abbr": away_tri, "name": away_name, "logo": _source_logo_url(away_tri)},
        "home": {"abbr": home_tri, "name": home_name, "logo": _source_logo_url(home_tri)},
        "status": normalized_status["status"],
        "detail": normalized_status["detail"],
        "summary": f"{row.get('bookmaker') or 'Consensus'} market snapshot",
        "start_time": str(row.get("commence_time") or "").strip() or None,
        "odds": {"commence_time": str(row.get("commence_time") or "").strip() or None},
        "betting": betting,
        "sim": sim_payload,
        "prop_recommendations": prop_recommendations,
        "game_market_recommendations": game_market_recommendations,
        "live_state": {
            "in_progress": bool(normalized_status["in_progress"]),
            "final": bool(normalized_status["final"]),
            "status": normalized_status["detail"],
        },
        "warnings": [],
        "metrics": [
            {"label": "Away ML", "value": format_moneyline(row.get("away_ml"))},
            {"label": "Home ML", "value": format_moneyline(row.get("home_ml"))},
            {"label": "Spread", "value": f"{home_tri} {format_signed_num(row.get('home_spread'))}"},
            {"label": "Total", "value": format_num(row.get("total"))},
            {"label": "Books", "value": str(row.get("books_count") or "-")},
            {"label": "Tip win", "value": format_num(float(row.get("prob_home_tip") or 0) * 100) + "%"},
            {"label": "Early 3s", "value": _format_pct_100((_safe_float(row.get("early_threes_prob_ge_1")) or 0.0) * 100)},
        ],
        "href": f"/wnba/game/{game_id}?date={selected_date}",
        "href_label": "Open WNBA game",
        "panels": [
            {
                "eyebrow": "Market snapshot",
                "title": f"{row.get('bookmaker') or 'Consensus'} lines",
                "body": f"Spread {home_tri} {format_signed_num(row.get('home_spread'))} | total {format_num(row.get('total'))}.",
                "summary_stats": [
                    {"label": "Away ML", "value": format_moneyline(row.get("away_ml"))},
                    {"label": "Home ML", "value": format_moneyline(row.get("home_ml"))},
                    {"label": "Books", "value": str(row.get("books_count") or "-")},
                    {"label": "Tip", "value": format_num(float(row.get("prob_home_tip") or 0) * 100) + "%"},
                ],
            },
            {
                "eyebrow": "Top recommendations",
                "title": "Per-game playable looks",
                "body": "Top picks are pulled from the processed WNBA recommendation slate artifact.",
                "items": top_picks or ["No linked recommendations found for this matchup."],
                "table_groups": ([{"heading": "Top plays", "rows": pick_rows}] if pick_rows else None),
            },
            {
                "eyebrow": "Sim detail",
                "title": "Top player outcomes",
                "body": "SmartSim detail artifacts provide player-level median and mean expectation for this matchup.",
                "summary_stats": sim_stats or None,
                "table_groups": sim_groups or None,
                "items": [f"Game id {game_id}"] if not sim_groups else None,
            },
            {
                "eyebrow": "Props snapshot",
                "title": "Best available props",
                "body": "Cards props snapshots surface the strongest team-side recommendations saved for the board.",
                "table_groups": props_groups or None,
                "items": prop_items or ["No props snapshot was linked for this matchup."],
            },
        ],
    }


def _game_by_id_from_artifacts(selected_date: str, game_pk: str | int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    bundle = _artifact_bundle(selected_date)
    wanted = str(game_pk).strip()
    for idx, row in enumerate(bundle["rows"], start=1):
        away_tri = _canonical_wnba_tri(str(row.get("away_tri") or str(row.get("visitor_team") or "")[:3]).strip().upper()) or "AWY"
        home_tri = _canonical_wnba_tri(str(row.get("home_tri") or str(row.get("home_team") or "")[:3]).strip().upper()) or "HOM"
        if _wnba_row_game_id(row, idx=idx, away_tri=away_tri, home_tri=home_tri) != wanted:
            continue
        return (
            _game_from_row(
                row,
                idx=idx,
                selected_date=selected_date,
                rec_index=bundle["recommendations"],
                sim_index=bundle["sim"],
                props_index=bundle["props"],
            ),
            bundle,
        )
    return None, bundle


def _dedupe_wnba_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        event_id = str(game.get("event_id") or "").strip()
        away_tri = _canonical_wnba_tri(
            str(
                game.get("away_tri")
                or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")
                or ""
            ).strip().upper()
        )
        home_tri = _canonical_wnba_tri(
            str(
                game.get("home_tri")
                or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")
                or ""
            ).strip().upper()
        )
        key = (event_id, away_tri, home_tri)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(game)
    return deduped


def _games_from_artifacts(selected_date: str) -> tuple[list[dict[str, Any]], str, str]:
    bundle = _artifact_bundle(selected_date)
    rows = bundle["rows"]
    rec_index = bundle["recommendations"]
    sim_index = bundle["sim"]
    props_index = bundle["props"]
    games = [
        _game_from_row(
            row,
            idx=idx,
            selected_date=selected_date,
            rec_index=rec_index,
            sim_index=sim_index,
            props_index=props_index,
        )
        for idx, row in enumerate(rows, start=1)
    ]
    return _dedupe_wnba_games(games), str(bundle["paths"]["cards"]), str(bundle["paths"]["recommendations"])


def _games_from_public_scoreboard(selected_date: str) -> tuple[list[dict[str, Any]], str]:
    payload = _public_scoreboard_live_state_payload(selected_date)
    games_payload = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    games: list[dict[str, Any]] = []
    for idx, game in enumerate(games_payload, start=1):
        if not isinstance(game, dict):
            continue
        away_tri = _canonical_wnba_tri(str(game.get("away") or "").strip().upper())
        home_tri = _canonical_wnba_tri(str(game.get("home") or "").strip().upper())
        if not away_tri or not home_tri:
            continue
        row = {
            "event_id": game.get("event_id") or f"{away_tri}@{home_tri}",
            "visitor_team": away_tri,
            "home_team": home_tri,
            "away_tri": away_tri,
            "home_tri": home_tri,
            "bookmaker": "ESPN",
            "commence_time": selected_date,
            "status": game.get("status") or "Scheduled",
            "in_progress": bool(game.get("in_progress")),
            "final": bool(game.get("final")),
        }
        games.append(
            _game_from_row(
                row,
                idx=idx,
                selected_date=selected_date,
                rec_index={},
                sim_index={},
                props_index={},
            )
        )
    return _dedupe_wnba_games(games), "espn_scoreboard_fallback"


def _public_scoreboard_source_cards_payload(selected_date: str) -> dict[str, Any] | None:
    games, source_path = _games_from_public_scoreboard(selected_date)
    if not games:
        return None
    parsed_date = parse_iso_date(selected_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()
    return {
        "date": selected_date,
        "requested_date": selected_date,
        "lookahead_applied": False,
        "players_included": False,
        "pregame_portfolio": {"enabled": False, "selected": 0, "candidates": 0},
        "games": games,
        "module_links": build_module_links(selected_date, "Cards"),
        "route_path": "/wnba/cards",
        "control_label": "Date",
        "control_type": "date",
        "control_name": "date",
        "control_value": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "board_contract": {
            "schema": "game_board_v1",
            "surface": "wnba_dense_board_v1",
            "sport": "wnba",
            "module": "cards",
            "source_kind": "live_scoreboard_fallback",
            "live_lens_integrated": True,
        },
        "source_title": "WNBA live scoreboard fallback",
        "source_path": source_path,
    }


def _games_from_live_state_fallback(selected_date: str, ttl: int = 12) -> tuple[list[dict[str, Any]], str]:
    is_today = str(selected_date).strip() == central_today_iso()
    candidate_payloads: list[dict[str, Any] | None] = [_local_live_state_payload(selected_date)]
    payload: dict[str, Any] | None = None
    source_path = None
    for candidate_payload in candidate_payloads:
        if isinstance(candidate_payload, dict) and isinstance(candidate_payload.get("games"), list) and bool(candidate_payload.get("games")):
            payload = candidate_payload
            source_name = str(candidate_payload.get("source") or "").strip().lower()
            if source_name:
                source_path = source_name
            else:
                source_path = str(processed_root() / "live_snapshots" / f"live_state_{selected_date}.jsonl")
            break
    if payload is None:
        payload = {}
    rows = payload.get("games") if isinstance((payload or {}).get("games"), list) else []
    sim_index = _artifact_bundle(selected_date).get("sim", {})
    games: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        away_tri = _canonical_wnba_tri(str(row.get("away") or "").strip().upper())
        home_tri = _canonical_wnba_tri(str(row.get("home") or "").strip().upper())
        if not away_tri or not home_tri:
            continue
        away_pts = _safe_float(row.get("away_pts"))
        home_pts = _safe_float(row.get("home_pts"))
        status_id = int(_safe_float(row.get("status_id")) or 0)
        # Pregame rows often carry 0-0 placeholders; treat those as unknown.
        if status_id <= 1 and (away_pts or 0.0) == 0.0 and (home_pts or 0.0) == 0.0:
            away_pts = None
            home_pts = None
        normalized_status = _normalized_game_status(
            status_text=row.get("status"),
            detail_text=row.get("status"),
            start_time_utc=row.get("commence_time") or row.get("start_time") or row.get("game_date"),
            in_progress=row.get("in_progress"),
            final=row.get("final"),
            away_pts=away_pts,
            home_pts=home_pts,
        )
        away_lines = row.get("periods") if isinstance(row.get("periods"), list) else []
        away_pts, home_pts = _repair_final_score_from_periods(away_pts, home_pts, away_lines, bool(row.get("final")))
        game_id = str(row.get("game_id") or f"{away_tri}@{home_tri}")
        sim_game = sim_index.get((away_tri, home_tri)) if isinstance(sim_index, dict) else None
        sim_payload = _source_sim_payload(game_id, sim_game if isinstance(sim_game, dict) else None, {})
        score = sim_payload.get("score") if isinstance(sim_payload.get("score"), dict) else {}
        sim_away = _safe_float(score.get("away_mean"))
        sim_home = _safe_float(score.get("home_mean"))
        sim_total = _safe_float(score.get("total_mean"))
        sim_margin = _safe_float(score.get("margin_mean"))
        total_mean = (away_pts + home_pts) if away_pts is not None and home_pts is not None else sim_total
        margin_mean = (home_pts - away_pts) if away_pts is not None and home_pts is not None else sim_margin
        betting = _source_betting(
            {
                "margin_mean": margin_mean,
                "total_mean": total_mean,
            }
        )
        games.append(
            {
                "gamePk": game_id,
                "event_id": row.get("event_id"),
                "game_id": game_id,
                "away_tri": away_tri,
                "away_name": away_tri,
                "home_tri": home_tri,
                "home_name": home_tri,
                "away_logo": _source_logo_url(away_tri),
                "home_logo": _source_logo_url(home_tri),
                "away": {"abbr": away_tri, "name": away_tri, "logo": _source_logo_url(away_tri)},
                "home": {"abbr": home_tri, "name": home_tri, "logo": _source_logo_url(home_tri)},
                "status": normalized_status["status"],
                "detail": normalized_status["detail"],
                "summary": "Live scoreboard fallback",
                "betting": betting,
                "prop_recommendations": {"away": [], "home": []},
                "live_state": {
                    **dict(row),
                    "in_progress": bool(normalized_status["in_progress"]),
                    "final": bool(normalized_status["final"]),
                    "status": normalized_status["detail"],
                },
                "sim": {
                    **sim_payload,
                    "score": {
                        "away_mean": away_pts if away_pts is not None else sim_away,
                        "home_mean": home_pts if home_pts is not None else sim_home,
                        "total_mean": total_mean,
                        "margin_mean": margin_mean,
                    },
                },
            }
        )
    return _dedupe_wnba_games(games), str(source_path or f"live_state_{selected_date}.jsonl")


def _game_identity_key(game: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(game, dict):
        return ("", "", "")
    event_id = str(game.get("event_id") or "").strip()
    away_tri = _canonical_wnba_tri(str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "") or "").strip().upper())
    home_tri = _canonical_wnba_tri(str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "") or "").strip().upper())
    return (event_id, away_tri, home_tri)


def _game_matchup_key(game: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(game, dict):
        return ("", "")
    away_tri = _canonical_wnba_tri(str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "") or "").strip().upper())
    home_tri = _canonical_wnba_tri(str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "") or "").strip().upper())
    return (away_tri, home_tri)


def _supplement_games_with_live_state(games: list[dict[str, Any]], selected_date: str) -> tuple[list[dict[str, Any]], str | None, int, int]:
    live_games, live_source_path = _games_from_live_state_fallback(selected_date)
    if not live_games:
        return games, None, 0, 0

    live_by_identity = {
        _game_identity_key(game): game
        for game in live_games
        if isinstance(game, dict)
    }
    live_by_matchup = {
        _game_matchup_key(game): game
        for game in live_games
        if isinstance(game, dict)
    }

    merged_games: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    seen_matchups: set[tuple[str, str]] = set()
    updated_count = 0

    for game in games:
        if not isinstance(game, dict):
            continue
        identity = _game_identity_key(game)
        matchup = _game_matchup_key(game)
        seen_keys.add(identity)
        seen_matchups.add(matchup)

        live_game = live_by_identity.get(identity)
        if not isinstance(live_game, dict):
            live_game = live_by_matchup.get(matchup)
        if not isinstance(live_game, dict):
            merged_games.append(game)
            continue

        merged = dict(game)
        live_state_row = live_game.get("live_state") if isinstance(live_game.get("live_state"), dict) else {}
        live_event_id = str(
            live_game.get("event_id")
            or live_state_row.get("event_id")
            or merged.get("event_id")
            or ""
        ).strip()
        if live_event_id:
            merged["event_id"] = live_event_id
        if live_state_row:
            merged["live_state"] = dict(live_state_row)
            away_pts = _safe_float(live_state_row.get("away_pts"))
            home_pts = _safe_float(live_state_row.get("home_pts"))
            if away_pts is not None and home_pts is not None:
                away_team = merged.get("away") if isinstance(merged.get("away"), dict) else {}
                home_team = merged.get("home") if isinstance(merged.get("home"), dict) else {}
                merged["away"] = {**away_team, "score": away_pts}
                merged["home"] = {**home_team, "score": home_pts}

        live_status = str(live_game.get("status") or "").strip()
        live_detail = str(live_game.get("detail") or live_status).strip()
        if live_status:
            merged["status"] = live_status
            merged["detail"] = live_detail

        updated_count += 1
        merged_games.append(merged)

    extras = [
        game
        for key, game in live_by_identity.items()
        if key not in seen_keys and _game_matchup_key(game) not in seen_matchups
    ]
    if extras:
        merged_games.extend(extras)

    return merged_games, live_source_path, len(extras), updated_count


def build_cards_page_context(selected_date: str, *, allow_stored_date_fallback: bool = False) -> dict[str, Any]:
    requested_date = str(selected_date or "").strip() or parse_iso_date(selected_date).isoformat()
    schedule_has_games = has_games_for_date(requested_date)
    if schedule_has_games is False and not allow_stored_date_fallback:
        parsed_date = parse_iso_date(requested_date)
        prev_date = (parsed_date - timedelta(days=1)).isoformat()
        next_date = (parsed_date + timedelta(days=1)).isoformat()
        return apply_game_board_contract(
            {
                "date": requested_date,
                "requested_date": requested_date,
                "lookahead_applied": False,
                "prev_date": prev_date,
                "next_date": next_date,
                "games": [],
                "scoreboard_items": [],
                "using_sample_data": False,
                "source_path": str(processed_root() / f"game_cards_{requested_date}.csv"),
                "source_title": "WNBA cards unavailable",
                "empty_state": {
                    "eyebrow": "WNBA cards",
                    "title": "No WNBA games were scheduled for this date",
                    "body": "WNBA cards are only published when the slate has games, so there is nothing to validate or load for this date.",
                    "list_items": [
                        f"Requested date: {requested_date}",
                        "Choose another date with a published WNBA slate.",
                    ],
                },
                "header_stats": [
                    {"label": "Games", "value": "0"},
                    {"label": "Recommendations", "value": "No data"},
                ],
                "route_path": "/wnba/cards",
                "intro_title": "WNBA Cards",
                "intro_body": "This is the first non-MLB Syndicate module, mapped into the shared game-card shell from committed WNBA processed artifacts.",
                "cards_control_links": [
                    {"label": "Betting Card", "href": f"/wnba/season/{parse_iso_date(requested_date).year}/betting-card?date={requested_date}"},
                    {"label": "Props", "href": f"/wnba/props?date={requested_date}"},
                    {"label": "Live Lens", "href": f"/wnba/live-lens?date={requested_date}"},
                ],
                "cards_grid_class": "wnba-cards-grid",
                "cards_stylesheet": "wnba/cards.css",
                "teaser": {
                    "label": "WNBA picks",
                    "body": "Use the dedicated picks module for the strongest processed recommendation slate cards.",
                    "href": f"/wnba/picks?date={requested_date}",
                    "cta": "Open WNBA picks",
                },
                "module_links": build_module_links(requested_date, "Cards"),
                "active_sport_name": "WNBA",
                "wnba_advanced_contract": _wnba_advanced_contract(
                    selected_date=requested_date,
                    requested_date=requested_date,
                    source_title="WNBA cards unavailable",
                    source_path=str(processed_root() / f"game_cards_{requested_date}.csv"),
                    games=[],
                ),
            },
            sport="wnba",
            module="cards",
            source_kind="artifact_backed",
            live_lens_integrated=True,
        )
    cache_key = (
        requested_date,
        bool(allow_stored_date_fallback),
        tuple(available_dates()),
        _path_cache_signature(_artifact_root_paths(requested_date)["cards"]),
        _path_cache_signature(_artifact_root_paths(requested_date)["recommendations"]),
        _path_cache_signature(_artifact_root_paths(requested_date)["sim"]),
        _path_cache_signature(_artifact_root_paths(requested_date)["props"]),
        _path_cache_signature(processed_root() / "live_snapshots" / f"live_state_{requested_date}.jsonl"),
    )
    cached_context = _WNBA_CARDS_CONTEXT_CACHE.get(cache_key)
    if cached_context is not None:
        return deepcopy(cached_context)

    resolved_date = requested_date
    parsed_date = parse_iso_date(resolved_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()

    games, cards_path, recs_path = _games_from_artifacts(resolved_date)
    if not allow_stored_date_fallback and resolved_date == central_today_iso() and resolved_date not in str(cards_path):
        games = []
    source_title = "WNBA processed game cards"
    had_artifact_games = bool(games)
    used_public_scoreboard_fallback = False
    if not games and allow_stored_date_fallback and resolved_date == central_today_iso():
        public_games, public_source_path = _games_from_public_scoreboard(resolved_date)
        if public_games:
            games = public_games
            cards_path = public_source_path
            recs_path = public_source_path
            source_title = "WNBA live scoreboard fallback"
            had_artifact_games = False
            used_public_scoreboard_fallback = True
    if not _render_web_dyno() and not used_public_scoreboard_fallback:
        games, live_source_path, supplemented_count, updated_count = _supplement_games_with_live_state(games, resolved_date)
        if supplemented_count > 0 or updated_count > 0:
            if had_artifact_games:
                source_title = "WNBA processed game cards + live scoreboard supplement"
                cards_path = f"{cards_path} | {live_source_path}"
            else:
                source_title = "WNBA live scoreboard fallback"
                cards_path = str(live_source_path)
                recs_path = str(live_source_path)

        if not games and allow_stored_date_fallback and resolved_date == central_today_iso():
            live_games, live_source_path = _games_from_live_state_fallback(resolved_date)
            if live_games:
                games = live_games
                cards_path = live_source_path
                recs_path = live_source_path
                source_title = "WNBA live scoreboard fallback"
        if not games and allow_stored_date_fallback:
            fallback_date = _nearest_available_cards_date(resolved_date)
            if fallback_date and fallback_date != resolved_date:
                resolved_date = fallback_date
                games, cards_path, recs_path = _games_from_artifacts(resolved_date)
                source_title = "WNBA processed game cards"
                had_artifact_games = bool(games)
                games, live_source_path, supplemented_count, updated_count = _supplement_games_with_live_state(games, resolved_date)
                if supplemented_count > 0 or updated_count > 0:
                    if had_artifact_games:
                        source_title = "WNBA processed game cards + live scoreboard supplement"
                        cards_path = f"{cards_path} | {live_source_path}"
                    else:
                        source_title = "WNBA live scoreboard fallback"
                        cards_path = str(live_source_path)
                        recs_path = str(live_source_path)
                if not games:
                    if resolved_date == central_today_iso():
                        live_games, live_source_path = _games_from_live_state_fallback(resolved_date)
                        if live_games:
                            games = live_games
                            cards_path = live_source_path
                            recs_path = live_source_path
                            source_title = "WNBA live scoreboard fallback"

    parsed_date = parse_iso_date(resolved_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()
    using_sample_data = False

    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["detail"],
        }
        for game in games
    ]

    result = apply_game_board_contract(
        {
            "date": resolved_date,
            "requested_date": requested_date,
            "lookahead_applied": bool(resolved_date != requested_date),
            "prev_date": prev_date,
            "next_date": next_date,
            "games": games,
            "scoreboard_items": scoreboard_items,
            "using_sample_data": using_sample_data,
            "source_path": cards_path,
            "source_title": source_title if games else "WNBA cards unavailable",
            "empty_state": {
                "eyebrow": "WNBA cards",
                "title": "No game cards were available for this date",
                "body": "The cards board only renders saved WNBA processed artifact rows, and none were available for the requested date.",
                "list_items": [
                    f"Requested date: {requested_date}",
                    "Choose another stored WNBA date from the date control.",
                ],
            } if not games else None,
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Recommendations", "value": recs_path.split("\\")[-1] if games else "No data"},
            ],
            "route_path": "/wnba/cards",
            "intro_title": "WNBA Cards",
            "intro_body": "This is the first non-MLB Syndicate module, mapped into the shared game-card shell from committed WNBA processed artifacts.",
            "cards_control_links": [
                {"label": "Betting Card", "href": f"/wnba/season/{parse_iso_date(resolved_date).year}/betting-card?date={resolved_date}"},
                {"label": "Props", "href": f"/wnba/props?date={resolved_date}"},
                {"label": "Live Lens", "href": f"/wnba/live-lens?date={resolved_date}"},
            ],
            "cards_grid_class": "wnba-cards-grid",
            "cards_stylesheet": "wnba/cards.css",
            "teaser": {
                "label": "WNBA picks",
                "body": "Use the dedicated picks module for the strongest processed recommendation slate cards.",
                "href": f"/wnba/picks?date={resolved_date}",
                "cta": "Open WNBA picks",
            },
            "module_links": build_module_links(resolved_date, "Cards"),
            "active_sport_name": "WNBA",
            "wnba_advanced_contract": _wnba_advanced_contract(
                selected_date=resolved_date,
                requested_date=requested_date,
                source_title=source_title,
                source_path=str(cards_path),
                games=games,
            ),
        },
        sport="wnba",
        module="cards",
        source_kind="artifact_backed",
        live_lens_integrated=True,
    )
    _WNBA_CARDS_CONTEXT_CACHE[cache_key] = deepcopy(result)
    return deepcopy(result)


@lru_cache(maxsize=64)
def _local_live_state_payload_cached(selected_date: str, snapshot_mtime_ns: int | None, snapshot_size: int | None) -> dict[str, Any] | None:
    path = processed_root() / "live_snapshots" / f"live_state_{selected_date}.jsonl"
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except Exception:
            continue
        payload = record.get("payload") if isinstance(record, dict) and isinstance(record.get("payload"), dict) else None
        if isinstance(payload, dict):
            return payload
        if isinstance(record, dict) and isinstance(record.get("games"), list):
            return record
    return None


def _local_live_state_payload(selected_date: str) -> dict[str, Any] | None:
    path = processed_root() / "live_snapshots" / f"live_state_{selected_date}.jsonl"
    if not path.exists():
        return _local_live_state_payload_cached(selected_date, None, None)
    try:
        stat = path.stat()
    except Exception:
        return _local_live_state_payload_cached(selected_date, None, None)
    return _local_live_state_payload_cached(selected_date, int(stat.st_mtime_ns), int(stat.st_size))


_local_live_state_payload.cache_clear = _local_live_state_payload_cached.cache_clear  # type: ignore[attr-defined]
_local_live_state_payload.cache_info = _local_live_state_payload_cached.cache_info  # type: ignore[attr-defined]


def _public_scoreboard_live_state_payload(selected_date: str) -> dict[str, Any] | None:
    iso_date = str(selected_date or "").strip()
    parsed = parse_iso_date(iso_date)
    compact_date = parsed.strftime("%Y%m%d")
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
        f"?dates={urllib_parse.quote(compact_date)}"
    )
    request_obj = urllib_request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    try:
        with urllib_request.urlopen(request_obj, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list) or not events:
        return None

    games: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip() or None
        competitions = event.get("competitions") if isinstance(event.get("competitions"), list) else []
        competition = competitions[0] if competitions and isinstance(competitions[0], dict) else {}
        competitors = competition.get("competitors") if isinstance(competition.get("competitors"), list) else []
        away_row = None
        home_row = None
        for row in competitors:
            if not isinstance(row, dict):
                continue
            side = str(row.get("homeAway") or "").strip().lower()
            if side == "away":
                away_row = row
            elif side == "home":
                home_row = row
        if not isinstance(away_row, dict) or not isinstance(home_row, dict):
            continue

        away_team = away_row.get("team") if isinstance(away_row.get("team"), dict) else {}
        home_team = home_row.get("team") if isinstance(home_row.get("team"), dict) else {}
        away_tri = _canonical_wnba_tri(
            str(
                away_team.get("abbreviation")
                or away_team.get("shortDisplayName")
                or away_team.get("displayName")
                or away_team.get("name")
                or ""
            ).strip().upper()
        )
        home_tri = _canonical_wnba_tri(
            str(
                home_team.get("abbreviation")
                or home_team.get("shortDisplayName")
                or home_team.get("displayName")
                or home_team.get("name")
                or ""
            ).strip().upper()
        )
        if not away_tri or not home_tri:
            continue

        away_pts = _safe_float(away_row.get("score"))
        home_pts = _safe_float(home_row.get("score"))
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        status_type = status.get("type") if isinstance(status.get("type"), dict) else {}
        in_progress = str(status_type.get("state") or "").strip().lower() == "in"
        final = bool(status_type.get("completed"))
        period = int(_safe_float(status_type.get("period")) or 0) or None
        clock = str(status_type.get("displayClock") or "").strip()
        status_text = (
            str(status_type.get("shortDetail") or "").strip()
            or str(status_type.get("detail") or "").strip()
            or str(status_type.get("description") or "").strip()
            or "Scheduled"
        )
        inferred_period, inferred_clock = _infer_period_clock_from_status_text(status_text)
        if period is None and inferred_period is not None:
            period = inferred_period
        if not clock and inferred_clock:
            clock = inferred_clock
        normalized_status = _normalized_game_status(
            status_text=status_text,
            detail_text=status_text,
            start_time_utc=competition.get("date") or event.get("date"),
            in_progress=in_progress,
            final=final,
            away_pts=away_pts,
            home_pts=home_pts,
        )

        away_lines = away_row.get("linescores") if isinstance(away_row.get("linescores"), list) else []
        home_lines = home_row.get("linescores") if isinstance(home_row.get("linescores"), list) else []
        periods: list[dict[str, Any]] = []
        line_count = max(len(away_lines), len(home_lines))
        for idx in range(line_count):
            away_line = away_lines[idx] if idx < len(away_lines) and isinstance(away_lines[idx], dict) else {}
            home_line = home_lines[idx] if idx < len(home_lines) and isinstance(home_lines[idx], dict) else {}
            away_value = _safe_float(away_line.get("value"))
            home_value = _safe_float(home_line.get("value"))
            if away_value is None and home_value is None:
                continue
            periods.append({"period": idx + 1, "away": away_value, "home": home_value})

        if final and (away_pts is None or home_pts is None or ((away_pts or 0.0) == 0.0 and (home_pts or 0.0) == 0.0)):
            period_away = sum(_safe_float(period.get("away")) or 0.0 for period in periods)
            period_home = sum(_safe_float(period.get("home")) or 0.0 for period in periods)
            if period_away > 0.0 or period_home > 0.0:
                away_pts = period_away
                home_pts = period_home

        games.append(
            {
                "game_id": str(event_id or f"{away_tri}@{home_tri}"),
                "event_id": str(event_id or f"{away_tri}@{home_tri}"),
                "home": home_tri,
                "away": away_tri,
                "home_tri": home_tri,
                "away_tri": away_tri,
                "home_pts": home_pts,
                "away_pts": away_pts,
                "status_id": None,
                "status": normalized_status["detail"],
                "period": period,
                "clock": clock,
                "in_progress": bool(normalized_status["in_progress"]),
                "final": bool(normalized_status["final"]),
                "periods": periods,
            }
        )

    if not games:
        return None
    return {
        "date": iso_date or parsed.isoformat(),
        "ttl": 12,
        "source": "espn_scoreboard_fallback",
        "games": games,
        "generated_at": _wnba_generated_at(),
    }


@lru_cache(maxsize=256)
def _local_live_snapshot_payload_cached(kind: str, resolved_date: str, snapshot_mtime_ns: int | None, snapshot_size: int | None) -> dict[str, Any] | None:
    if not resolved_date:
        return None
    try:
        path = live_snapshot_path(f"{kind}_{resolved_date}.jsonl")
    except FileNotFoundError:
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except Exception:
            continue
        payload = record.get("payload") if isinstance(record, dict) and isinstance(record.get("payload"), dict) else None
        if isinstance(payload, dict):
            return payload
        if isinstance(record, dict) and isinstance(record.get("games"), list):
            return record
    return None


def _local_live_snapshot_payload(kind: str, selected_date: str) -> dict[str, Any] | None:
    resolved_date = str(selected_date or "").strip()
    if not resolved_date:
        return None
    try:
        path = live_snapshot_path(f"{kind}_{resolved_date}.jsonl")
    except FileNotFoundError:
        return _local_live_snapshot_payload_cached(kind, resolved_date, None, None)
    try:
        stat = path.stat()
    except Exception:
        return _local_live_snapshot_payload_cached(kind, resolved_date, None, None)
    return _local_live_snapshot_payload_cached(kind, resolved_date, int(stat.st_mtime_ns), int(stat.st_size))


_local_live_snapshot_payload.cache_clear = _local_live_snapshot_payload_cached.cache_clear  # type: ignore[attr-defined]
_local_live_snapshot_payload.cache_info = _local_live_snapshot_payload_cached.cache_info  # type: ignore[attr-defined]


def _filtered_local_live_snapshot_payload(kind: str, selected_date: str, event_ids: list[str]) -> dict[str, Any] | None:
    payload = _local_live_snapshot_payload(kind, selected_date)
    if not isinstance(payload, dict):
        return None
    games = payload.get("games") if isinstance(payload.get("games"), list) else None
    if games is None:
        return None
    cleaned = {str(item).strip() for item in event_ids if str(item).strip()}
    if not cleaned:
        return payload
    filtered_payload = dict(payload)
    filtered_payload["games"] = [
        game
        for game in games
        if isinstance(game, dict) and str(game.get("event_id") or "").strip() in cleaned
    ]
    if selected_date and "date" not in filtered_payload:
        filtered_payload["date"] = selected_date
    return filtered_payload


def _ensure_wnba_game_ids(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    games = payload.get("games") if isinstance(payload.get("games"), list) else None
    if not games:
        return payload
    normalized_payload = dict(payload)
    normalized_games: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        normalized_game = dict(game)
        game_id = str(
            normalized_game.get("game_id")
            or normalized_game.get("gamePk")
            or normalized_game.get("event_id")
            or ""
        ).strip()
        if not game_id:
            away_tri = str(normalized_game.get("away_tri") or normalized_game.get("away") or "").strip().upper()
            home_tri = str(normalized_game.get("home_tri") or normalized_game.get("home") or "").strip().upper()
            if away_tri and home_tri:
                game_id = f"{away_tri}@{home_tri}"
        if game_id:
            normalized_game.setdefault("game_id", game_id)
            normalized_game.setdefault("gamePk", game_id)
            normalized_game.setdefault("event_id", game_id)
        normalized_games.append(normalized_game)
    normalized_payload["games"] = normalized_games
    return normalized_payload


def _attach_odds_refresh_timestamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = _ensure_wnba_game_ids(dict(payload))
    source_generated_at = str(out.get("generated_at") or "").strip()
    timestamp = str(out.get("odds_refreshed_at") or source_generated_at or "").strip()
    if not timestamp:
        timestamp = central_now().isoformat(timespec="seconds")
    else:
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            timestamp = parsed.astimezone(central_now().tzinfo).isoformat(timespec="seconds")
        except Exception:
            pass
    out["odds_refreshed_at"] = timestamp
    out["generated_at"] = source_generated_at or timestamp
    return out


def _payload_games_by_event_id(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        event_id = str(game.get("event_id") or "").strip()
        if event_id:
            out[event_id] = game
    return out


def _merge_live_lines_game(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    merged["found"] = bool(primary.get("found")) or bool(secondary.get("found"))

    for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml"):
        if merged.get(key) is None and secondary.get(key) is not None:
            merged[key] = secondary.get(key)

    primary_lines = primary.get("lines") if isinstance(primary.get("lines"), dict) else {}
    secondary_lines = secondary.get("lines") if isinstance(secondary.get("lines"), dict) else {}
    merged_lines = dict(primary_lines)
    for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml"):
        if merged_lines.get(key) is None and secondary_lines.get(key) is not None:
            merged_lines[key] = secondary_lines.get(key)

    for key in ("period_totals", "period_spreads"):
        merged_periods = dict(primary_lines.get(key) or {}) if isinstance(primary_lines.get(key), dict) else {}
        secondary_periods = secondary_lines.get(key) if isinstance(secondary_lines.get(key), dict) else {}
        for period_key, period_value in secondary_periods.items():
            if period_key not in merged_periods and period_value is not None:
                merged_periods[period_key] = period_value
        merged_lines[key] = merged_periods

    merged["lines"] = merged_lines
    return merged


def _merge_live_lines_payloads(primary: dict[str, Any] | None, secondary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(primary, dict):
        return secondary if isinstance(secondary, dict) else None
    if not isinstance(secondary, dict):
        return primary

    primary_games = _payload_games_by_event_id(primary)
    secondary_games = _payload_games_by_event_id(secondary)
    if not primary_games:
        return secondary if secondary_games else primary
    if not secondary_games:
        return primary

    ordered_event_ids: list[str] = []
    for payload in (primary, secondary):
        games = payload.get("games") if isinstance(payload.get("games"), list) else []
        for game in games:
            if not isinstance(game, dict):
                continue
            event_id = str(game.get("event_id") or "").strip()
            if event_id and event_id not in ordered_event_ids:
                ordered_event_ids.append(event_id)

    merged_payload = dict(primary)
    merged_payload["games"] = [
        _merge_live_lines_game(primary_games[event_id], secondary_games[event_id])
        if event_id in primary_games and event_id in secondary_games
        else dict(primary_games.get(event_id) or secondary_games.get(event_id) or {})
        for event_id in ordered_event_ids
        if event_id in primary_games or event_id in secondary_games
    ]
    return merged_payload


def _payload_has_requested_live_line_coverage(
    payload: dict[str, Any] | None,
    event_ids: list[str],
    *,
    include_period_totals: bool,
) -> bool:
    coverage = _payload_games_by_event_id(payload)
    if not coverage:
        return False
    if event_ids and not all(event_id in coverage for event_id in event_ids):
        return False
    if not include_period_totals:
        return True
    for event_id in (event_ids or list(coverage.keys())):
        game = coverage.get(event_id) or {}
        lines = game.get("lines") if isinstance(game.get("lines"), dict) else {}
        period_totals = lines.get("period_totals") if isinstance(lines.get("period_totals"), dict) else {}
        period_spreads = lines.get("period_spreads") if isinstance(lines.get("period_spreads"), dict) else {}
        if period_totals or period_spreads:
            return True
    return False


def _finalize_live_lines_payload(payload: dict[str, Any], *, include_period_totals: bool) -> dict[str, Any]:
    finalized = dict(payload)
    finalized["include_period_totals"] = bool(include_period_totals)
    return finalized


def _payload_has_live_boxscore_players(payload: dict[str, Any] | None) -> bool:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    return any(
        isinstance(game, dict) and isinstance(game.get("players"), list) and bool(game.get("players"))
        for game in games
    )


def _payload_has_live_lens_rows(payload: dict[str, Any] | None) -> bool:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    return any(
        isinstance(game, dict) and isinstance(game.get("rows"), list) and bool(game.get("rows"))
        for game in games
    )


def _parse_payload_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cards_context_live_state_snapshot(game: dict[str, Any]) -> dict[str, Any]:
    away_info = game.get("away") if isinstance(game.get("away"), dict) else {}
    home_info = game.get("home") if isinstance(game.get("home"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    normalized_status = _normalized_game_status(
        status_text=live_state.get("status") or game.get("status"),
        detail_text=live_state.get("detail") or game.get("detail"),
        start_time_utc=game.get("start_time") or ((game.get("odds") or {}).get("commence_time") if isinstance(game.get("odds"), dict) else None),
        in_progress=bool(live_state.get("in_progress")),
        final=bool(live_state.get("final")),
        away_pts=away_info.get("score"),
        home_pts=home_info.get("score"),
    )
    return {
        "away_pts": _safe_float(away_info.get("score")),
        "home_pts": _safe_float(home_info.get("score")),
        "status": normalized_status["detail"],
        "period": normalized_status.get("period"),
        "clock": normalized_status.get("clock") or "",
        "in_progress": bool(normalized_status["in_progress"]),
        "final": bool(normalized_status["final"]),
    }


def _live_state_row_needs_cards_override(live_row: dict[str, Any], cards_state: dict[str, Any]) -> bool:
    if not isinstance(live_row, dict) or not isinstance(cards_state, dict):
        return False
    if cards_state.get("in_progress") and not bool(live_row.get("in_progress")):
        return True
    if cards_state.get("final") and not bool(live_row.get("final")):
        return True

    live_total = sum(
        value or 0.0
        for value in (
            _safe_float(live_row.get("away_pts")),
            _safe_float(live_row.get("home_pts")),
        )
        if value is not None
    )
    cards_total = sum(
        value or 0.0
        for value in (
            _safe_float(cards_state.get("away_pts")),
            _safe_float(cards_state.get("home_pts")),
        )
        if value is not None
    )
    if cards_total > live_total:
        return True
    if (cards_state.get("clock") or cards_state.get("period")) and not (live_row.get("clock") or live_row.get("period")):
        return bool(cards_state.get("in_progress") or cards_state.get("final"))
    return False


def _status_from_game(game: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalized_game_status(
        status_text=game.get("status"),
        detail_text=game.get("detail"),
        start_time_utc=game.get("start_time") or ((game.get("odds") or {}).get("commence_time") if isinstance(game.get("odds"), dict) else None),
        in_progress=((game.get("live_state") or {}).get("in_progress") if isinstance(game.get("live_state"), dict) else False),
        final=((game.get("live_state") or {}).get("final") if isinstance(game.get("live_state"), dict) else False),
        away_pts=((game.get("away") or {}).get("score") if isinstance(game.get("away"), dict) else None),
        home_pts=((game.get("home") or {}).get("score") if isinstance(game.get("home"), dict) else None),
    )
    return {
        "status": normalized["detail"],
        "in_progress": bool(normalized["in_progress"]),
        "final": bool(normalized["final"]),
        "period": normalized.get("period"),
        "clock": normalized.get("clock") or "",
    }


def _repair_final_score_from_periods(
    away_pts: float | None,
    home_pts: float | None,
    periods: list[dict[str, Any]],
    final: bool,
) -> tuple[float | None, float | None]:
    if not final:
        return away_pts, home_pts
    if away_pts is not None and home_pts is not None and (away_pts or 0.0) != 0.0 and (home_pts or 0.0) != 0.0:
        return away_pts, home_pts

    period_away = sum(_safe_float(period.get("away")) or 0.0 for period in periods if isinstance(period, dict))
    period_home = sum(_safe_float(period.get("home")) or 0.0 for period in periods if isinstance(period, dict))
    if period_away > 0.0 or period_home > 0.0:
        return period_away, period_home
    return away_pts, home_pts


def _cards_games_for_live_fallback(selected_date: str) -> list[dict[str, Any]]:
    context = build_cards_page_context(selected_date, allow_stored_date_fallback=True)
    return [game for game in (context.get("games") or []) if isinstance(game, dict)]


def _artifact_processed_root(selected_date: str) -> Path:
    return processed_path(f"game_cards_{selected_date}.csv").parent


def _artifact_live_player_lens_payload(
    selected_date: str,
    event_ids: list[str],
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any] | None:
    event_games = _resolve_games_for_event_ids(selected_date, event_ids)
    if not event_games:
        return None
    return build_live_player_lens_payload_from_artifacts(
        processed_root=_artifact_processed_root(selected_date),
        date_str=selected_date,
        event_games=event_games,
        source="syndicate_live_lens_projection_artifact",
    )


def _artifact_live_lines_payload(
    selected_date: str,
    event_ids: list[str],
    *,
    include_period_totals: bool,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any] | None:
    event_games = _resolve_games_for_event_ids(selected_date, event_ids)
    if not event_games:
        return None
    return build_live_lines_payload_from_artifacts(
        processed_root=_artifact_processed_root(selected_date),
        date_str=selected_date,
        event_games=event_games,
        include_period_totals=bool(include_period_totals),
        source="syndicate_live_lens_signals_artifact",
    )


def _game_index_by_event_id(selected_date: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for game in _cards_games_for_live_fallback(selected_date):
        event_id = str(game.get("event_id") or "").strip()
        if event_id:
            out[event_id] = game
    return out


def _games_by_matchup(selected_date: str) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for game in _cards_games_for_live_fallback(selected_date):
        if not isinstance(game, dict):
            continue
        away_tri = _canonical_wnba_tri(
            str(
                game.get("away_tri")
                or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")
                or ""
            ).strip().upper()
        )
        home_tri = _canonical_wnba_tri(
            str(
                game.get("home_tri")
                or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")
                or ""
            ).strip().upper()
        )
        if away_tri and home_tri:
            out[(away_tri, home_tri)] = game
    return out


def _resolve_games_for_event_ids(selected_date: str, event_ids: list[str]) -> dict[str, dict[str, Any]]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    if not normalized_event_ids:
        return {}

    by_event = _game_index_by_event_id(selected_date)
    matchup_index = _games_by_matchup(selected_date)

    unresolved = [event_id for event_id in normalized_event_ids if event_id not in by_event]
    if unresolved:
        live_payload = build_live_state_payload(selected_date, ttl=12, allow_stored_date_fallback=False)
        live_rows = live_payload.get("games") if isinstance(live_payload, dict) else []
        if isinstance(live_rows, list):
            wanted = set(unresolved)
            for row in live_rows:
                if not isinstance(row, dict):
                    continue
                event_id = str(row.get("event_id") or "").strip()
                if not event_id or event_id not in wanted or event_id in by_event:
                    continue
                away_tri = _canonical_wnba_tri(str(row.get("away_tri") or row.get("away") or "").strip().upper())
                home_tri = _canonical_wnba_tri(str(row.get("home_tri") or row.get("home") or "").strip().upper())
                game = matchup_index.get((away_tri, home_tri)) if away_tri and home_tri else None
                if isinstance(game, dict):
                    by_event[event_id] = game

    return {
        event_id: game
        for event_id in normalized_event_ids
        for game in [by_event.get(event_id)]
        if isinstance(game, dict)
    }


def _default_live_event_ids(selected_date: str, *, allow_stored_date_fallback: bool = True) -> list[str]:
    live_payload = build_live_state_payload(
        selected_date,
        ttl=12,
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
    games = live_payload.get("games") if isinstance(live_payload, dict) else []
    event_ids: list[str] = []
    for game in games if isinstance(games, list) else []:
        if not isinstance(game, dict):
            continue
        event_id = str(game.get("event_id") or "").strip()
        if not event_id:
            continue
        if bool(game.get("in_progress")) and not bool(game.get("final")):
            event_ids.append(event_id)
    if event_ids:
        return list(dict.fromkeys(event_ids))

    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    context_games = context.get("games") if isinstance(context.get("games"), list) else []
    visible_event_ids: list[str] = []
    for game in context_games:
        if not isinstance(game, dict):
            continue
        status = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
        event_id = str(game.get("event_id") or "").strip()
        if event_id and bool(status.get("in_progress")) and not bool(status.get("final")):
            event_ids.append(event_id)
        if event_id:
            visible_event_ids.append(event_id)
    if event_ids:
        return list(dict.fromkeys(event_ids))
    return list(dict.fromkeys(visible_event_ids))


def _player_sim_stat(player_row: dict[str, Any], market: str) -> float | None:
    key = str(market or "").strip().lower()
    pts = _safe_float(player_row.get("pts_mean"))
    reb = _safe_float(player_row.get("reb_mean"))
    ast = _safe_float(player_row.get("ast_mean"))
    if key == "pts":
        return pts
    if key == "reb":
        return reb
    if key == "ast":
        return ast
    if key == "threes":
        return _safe_float(player_row.get("threes_mean"))
    if key == "stl":
        return _safe_float(player_row.get("stl_mean"))
    if key == "blk":
        return _safe_float(player_row.get("blk_mean"))
    if key == "tov":
        return _safe_float(player_row.get("tov_mean"))
    if key == "pra":
        return None if pts is None or reb is None or ast is None else round(pts + reb + ast, 3)
    if key == "pr":
        return None if pts is None or reb is None else round(pts + reb, 3)
    if key == "pa":
        return None if pts is None or ast is None else round(pts + ast, 3)
    if key == "ra":
        return None if reb is None or ast is None else round(reb + ast, 3)
    return None


def _normalize_player_key(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9\s]", " ", str(value or "").upper())).strip()


def _live_player_row_key(row: dict[str, Any], event_id: str | None = None) -> tuple[str, str, str, str, str, str]:
    normalized_event_id = str(event_id or row.get("event_id") or "").strip()
    team_tri = str(row.get("team_tri") or "").strip().upper()
    player_key = _normalize_player_key(row.get("player"))
    stat_key = str(row.get("stat") or row.get("market") or "").strip().lower()
    side_key = str(row.get("ev_side") or row.get("lean") or row.get("side") or "").strip().upper()
    line_value = _safe_float(row.get("line_live") if row.get("line_live") is not None else row.get("line"))
    line_key = "" if line_value is None else f"{line_value:.4f}"
    return (normalized_event_id, team_tri, player_key, stat_key, side_key, line_key)


def _price_is_usable(value: Any) -> bool:
    price = _safe_float(value)
    return price is not None and price != 0


def _preferred_live_prop_side(row: dict[str, Any]) -> str:
    for candidate in (
        row.get("ev_side"),
        row.get("lean"),
        row.get("side"),
    ):
        side_value = str(candidate or "").strip().upper()
        if side_value in {"OVER", "UNDER"}:
            return side_value
    for candidate in (
        row.get("live_edge"),
        row.get("liveEdge"),
        row.get("pace_vs_line"),
        row.get("sim_vs_line_adjusted"),
        row.get("sim_vs_line"),
    ):
        edge_value = _safe_float(candidate)
        if edge_value is not None and abs(edge_value) > 0.01:
            return "OVER" if edge_value > 0 else "UNDER"
    return ""


def _oddsapi_market_to_stat(value: Any) -> str:
    market = str(value or "").strip().lower()
    return {
        "player_points": "pts",
        "player_rebounds": "reb",
        "player_assists": "ast",
        "player_threes": "threes",
        "player_points_rebounds": "pr",
        "player_points_assists": "pa",
        "player_rebounds_assists": "ra",
        "player_points_rebounds_assists": "pra",
        "player_blocks": "blk",
        "player_steals": "stl",
        "player_blocks_steals": "bs",
        "player_steals_blocks": "bs",
        "player_turnovers": "tov",
    }.get(market, "")


def _processed_live_player_odds_index(
    selected_date: str,
    games_by_event: dict[str, dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    processed_root = processed_path(f"game_cards_{selected_date}.csv").parent
    odds_path = processed_root / f"oddsapi_player_props_{selected_date}.csv"
    if not odds_path.exists():
        return {}

    matchup_to_event: dict[tuple[str, str], str] = {}
    for event_id, game in games_by_event.items():
        if not isinstance(game, dict):
            continue
        away_tri = _canonical_wnba_tri(str(game.get("away_tri") or game.get("away") or "").strip().upper())
        home_tri = _canonical_wnba_tri(str(game.get("home_tri") or game.get("home") or "").strip().upper())
        if away_tri and home_tri:
            matchup_to_event[(away_tri, home_tri)] = str(event_id or "").strip()

    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in _load_csv_rows(odds_path):
        away_tri = _canonical_wnba_tri(str(row.get("away_team") or "").strip().upper())
        home_tri = _canonical_wnba_tri(str(row.get("home_team") or "").strip().upper())
        event_id = matchup_to_event.get((away_tri, home_tri))
        if not event_id:
            continue
        stat_key = _oddsapi_market_to_stat(row.get("market"))
        player_key = _normalize_player_key(row.get("player_name"))
        line_value = _safe_float(row.get("point"))
        price_value = _safe_float(row.get("price"))
        if not stat_key or not player_key or line_value is None or not _price_is_usable(price_value):
            continue
        grouped_key = (event_id, player_key, stat_key, f"{line_value:.4f}")
        current = grouped.setdefault(
            grouped_key,
            {
                "event_id": event_id,
                "player_key": player_key,
                "stat": stat_key,
                "line": line_value,
                "price_over": None,
                "price_under": None,
                "book": str(row.get("bookmaker_title") or row.get("bookmaker") or "").strip() or None,
            },
        )
        outcome_name = str(row.get("outcome_name") or "").strip().upper()
        if outcome_name == "OVER" and not _price_is_usable(current.get("price_over")):
            current["price_over"] = price_value
        elif outcome_name == "UNDER" and not _price_is_usable(current.get("price_under")):
            current["price_under"] = price_value
        elif not current.get("book"):
            current["book"] = str(row.get("bookmaker_title") or row.get("bookmaker") or "").strip() or None

    index: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for grouped_key, payload in grouped.items():
        event_id, player_key, stat_key, _line_key = grouped_key
        index.setdefault((event_id, player_key, stat_key), []).append(payload)

    for values in index.values():
        values.sort(key=lambda item: abs(float(item.get("line") or 0.0)))
    return index


def _best_live_player_odds_match(
    odds_index: dict[tuple[str, str, str], list[dict[str, Any]]],
    row: dict[str, Any],
    event_id: str,
) -> dict[str, Any] | None:
    player_key = _normalize_player_key(row.get("player"))
    stat_key = str(row.get("stat") or row.get("market") or "").strip().lower()
    if not player_key or not stat_key:
        return None
    candidates = odds_index.get((event_id, player_key, stat_key)) or []
    if not candidates:
        return None
    row_line = _safe_float(row.get("line_live") if row.get("line_live") is not None else row.get("line"))
    if row_line is None:
        return None
    ranked = sorted(
        candidates,
        key=lambda item: (
            abs(float(item.get("line") or 0.0) - row_line),
            0 if _price_is_usable(item.get("price_over")) and _price_is_usable(item.get("price_under")) else 1,
        ),
    )
    best = ranked[0] if ranked else None
    return best if isinstance(best, dict) else None


def _median(values: list[float]) -> float | None:
    cleaned = sorted(float(value) for value in values if value is not None)
    if not cleaned:
        return None
    midpoint = len(cleaned) // 2
    if len(cleaned) % 2:
        return cleaned[midpoint]
    return (cleaned[midpoint - 1] + cleaned[midpoint]) / 2.0


@lru_cache(maxsize=1)
def _live_projection_calibration_index() -> dict[str, dict[Any, Any]]:
    processed_root_dir = processed_root()
    stat_samples: dict[str, list[float]] = {}
    player_stat_samples: dict[tuple[str, str], list[float]] = {}
    for path in processed_root_dir.glob("live_player_lens_tuning_*.csv"):
        for row in _load_csv_rows(path):
            stat_key = str(row.get("stat") or "").strip().lower()
            player_key = _normalize_player_key(row.get("player_name"))
            actual_value = _safe_float(row.get("actual"))
            pace_projection = _safe_float(row.get("pace_proj_final"))
            if not stat_key or actual_value is None or pace_projection is None or pace_projection <= 0:
                continue
            ratio = max(0.35, min(1.2, float(actual_value) / float(pace_projection)))
            stat_samples.setdefault(stat_key, []).append(ratio)
            if player_key:
                player_stat_samples.setdefault((player_key, stat_key), []).append(ratio)

    return {
        "stat": {
            key: {"factor": _median(values), "count": len(values)}
            for key, values in stat_samples.items()
            if values
        },
        "player_stat": {
            key: {"factor": _median(values), "count": len(values)}
            for key, values in player_stat_samples.items()
            if values
        },
    }


def _calibrate_live_projection(
    live_projection: Any,
    actual_value: Any,
    *,
    player_name: Any,
    stat_key: Any,
) -> float | None:
    projected_value = _safe_float(live_projection)
    if projected_value is None:
        return None
    stat = str(stat_key or "").strip().lower()
    player_key = _normalize_player_key(player_name)
    calibration_index = _live_projection_calibration_index()
    selected_factor = None
    player_entry = (calibration_index.get("player_stat") or {}).get((player_key, stat)) if player_key and stat else None
    if isinstance(player_entry, dict) and int(player_entry.get("count") or 0) >= 3:
        selected_factor = _safe_float(player_entry.get("factor"))
    if selected_factor is None:
        stat_entry = (calibration_index.get("stat") or {}).get(stat) if stat else None
        if isinstance(stat_entry, dict) and int(stat_entry.get("count") or 0) >= 10:
            selected_factor = _safe_float(stat_entry.get("factor"))
    if selected_factor is None:
        return round(projected_value, 3)
    calibrated_value = projected_value * selected_factor
    actual_numeric = _safe_float(actual_value)
    if actual_numeric is not None:
        calibrated_value = max(actual_numeric, calibrated_value)
    return round(calibrated_value, 3)


def _actual_stat_value(player_row: dict[str, Any], market: str) -> float | None:
    key = str(market or "").strip().lower()
    if not player_row:
        return None
    pts = _safe_float(player_row.get("pts"))
    reb = _safe_float(player_row.get("reb"))
    ast = _safe_float(player_row.get("ast"))
    if key == "pts":
        return pts
    if key == "reb":
        return reb
    if key == "ast":
        return ast
    if key == "threes":
        return _safe_float(player_row.get("threes_made"))
    if key == "stl":
        return _safe_float(player_row.get("stl"))
    if key == "blk":
        return _safe_float(player_row.get("blk"))
    if key == "tov":
        return _safe_float(player_row.get("tov"))
    if key == "pra":
        return None if pts is None or reb is None or ast is None else round(pts + reb + ast, 3)
    if key == "pr":
        return None if pts is None or reb is None else round(pts + reb, 3)
    if key == "pa":
        return None if pts is None or ast is None else round(pts + ast, 3)
    if key == "ra":
        return None if reb is None or ast is None else round(reb + ast, 3)
    return None


def _estimated_live_projection(actual: Any, minutes_played: Any, sim_minutes: Any, sim_value: Any) -> float | None:
    actual_value = _safe_float(actual)
    played = _safe_float(minutes_played)
    sim_min = _safe_float(sim_minutes)
    sim_mean = _safe_float(sim_value)
    if actual_value is None:
        return sim_mean
    if played is None or played <= 0:
        return sim_mean if sim_mean is not None else actual_value
    target_minutes = max(played, min(48.0, sim_min)) if sim_min is not None and sim_min > 0 else 48.0
    raw_projection = (actual_value / played) * target_minutes
    if sim_mean is None:
        return round(raw_projection, 3)
    blend_weight = max(0.25, min(0.85, played / max(target_minutes, 1.0)))
    return round(((1.0 - blend_weight) * sim_mean) + (blend_weight * raw_projection), 3)


def _boxscore_rows_by_player(boxscore_payload: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    games = []
    if isinstance(boxscore_payload, dict):
        if isinstance(boxscore_payload.get("players"), list):
            games = [boxscore_payload]
        elif isinstance(boxscore_payload.get("games"), list):
            games = [game for game in boxscore_payload.get("games") if isinstance(game, dict)]
    for game in games:
        if not isinstance(game, dict):
            continue
        players = game.get("players") if isinstance(game.get("players"), list) else []
        for player_row in players:
            if not isinstance(player_row, dict):
                continue
            team_tri = str(player_row.get("team_tri") or "").strip().upper()
            player_key = _normalize_player_key(player_row.get("player"))
            if team_tri and player_key:
                out[(team_tri, player_key)] = player_row
    return out


def _live_state_status_from_row(game: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(game, dict):
        return {}
    if isinstance(game.get("status"), dict):
        return dict(game.get("status") or {})
    event_status = str(game.get("status") or "").strip()
    return {
        "in_progress": bool(game.get("in_progress")),
        "final": bool(game.get("final")),
        "period": game.get("period"),
        "clock": game.get("clock"),
        "status": event_status,
    }


def _merge_live_status(existing_status: dict[str, Any] | None, incoming_status: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(existing_status or {}) if isinstance(existing_status, dict) else {}
    incoming = dict(incoming_status or {}) if isinstance(incoming_status, dict) else {}
    if not incoming:
        return current
    if bool(current.get("in_progress")) and not bool(incoming.get("in_progress")):
        return current
    if bool(current.get("final")) and not bool(incoming.get("final")):
        return current
    return incoming


def _live_player_row_rank(row: dict[str, Any]) -> tuple[int, int, int, float]:
    line_source = str(row.get("line_source") or "").strip().lower()
    has_price = any(_price_is_usable(row.get(price_key)) for price_key in ("price", "price_over", "price_under"))
    line_value = _safe_float(row.get("line_live") if row.get("line_live") is not None else row.get("line"))
    return (
        1 if has_price else 0,
        0 if line_source == "live_lens_projection_artifact" else 1,
        1 if line_value is not None else 0,
        abs(_safe_float(row.get("live_edge") if row.get("live_edge") is not None else row.get("liveEdge")) or 0.0),
    )


def _dedupe_live_player_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_key = (
            str(row.get("team_tri") or "").strip().upper(),
            _normalize_player_key(row.get("player")),
            str(row.get("stat") or row.get("market") or "").strip().lower(),
        )
        if not all(row_key):
            order.append((f"__index__{len(order)}", "", ""))
            best_by_key[order[-1]] = row
            continue
        current = best_by_key.get(row_key)
        if current is None:
            best_by_key[row_key] = row
            order.append(row_key)
            continue
        if _live_player_row_rank(row) > _live_player_row_rank(current):
            best_by_key[row_key] = row
    return [best_by_key[key] for key in order if key in best_by_key]


def _hydrate_live_player_lens_payload(
    payload: dict[str, Any],
    selected_date: str,
    event_ids: list[str],
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    games = payload.get("games") if isinstance(payload.get("games"), list) else None
    if games is None:
        return payload

    boxscore_payload = build_live_player_boxscore_payload(
        selected_date,
        event_ids,
        ttl=20,
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
    boxscore_by_event = {
        str(game.get("event_id") or "").strip(): _boxscore_rows_by_player(game)
        for game in (boxscore_payload.get("games") if isinstance(boxscore_payload.get("games"), list) else [])
        if isinstance(game, dict)
    }
    live_state_payload = build_live_state_payload(
        selected_date,
        ttl=12,
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
    live_state_by_event = {
        str(game.get("event_id") or "").strip(): _live_state_status_from_row(game)
        for game in (live_state_payload.get("games") if isinstance(live_state_payload.get("games"), list) else [])
        if isinstance(game, dict)
        and str(game.get("event_id") or "").strip()
    }
    fallback_games_by_event = _resolve_games_for_event_ids(selected_date, event_ids)
    fallback_rows_by_key: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    processed_odds_by_player = _processed_live_player_odds_index(selected_date, fallback_games_by_event)
    for fallback_event_id, fallback_game in fallback_games_by_event.items():
        if not isinstance(fallback_game, dict):
            continue
        fallback_payload_game = _fallback_live_player_lens_game(fallback_game, event_id=fallback_event_id)
        for fallback_row in fallback_payload_game.get("rows") if isinstance(fallback_payload_game.get("rows"), list) else []:
            if not isinstance(fallback_row, dict):
                continue
            fallback_rows_by_key[_live_player_row_key(fallback_row, fallback_event_id)] = fallback_row

    hydrated_games: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            hydrated_games.append(game)
            continue
        event_id = str(game.get("event_id") or "").strip()
        actual_rows = boxscore_by_event.get(event_id) or {}
        hydrated_game = dict(game)
        live_status = live_state_by_event.get(event_id)
        source_game_status = game.get("status") if isinstance(game.get("status"), dict) else {}
        game_status = _merge_live_status(source_game_status, live_status)
        if game_status:
            hydrated_game["status"] = dict(game_status)
        game_explicitly_not_live = bool(source_game_status) and not bool(source_game_status.get("in_progress"))
        rows: list[dict[str, Any]] = []
        for row in game.get("rows") if isinstance(game.get("rows"), list) else []:
            if not isinstance(row, dict):
                rows.append(row)
                continue
            hydrated_row = dict(row)
            team_tri = str(hydrated_row.get("team_tri") or "").strip().upper()
            player_key = _normalize_player_key(hydrated_row.get("player"))
            actual_row = actual_rows.get((team_tri, player_key)) if team_tri and player_key else None
            actual_value = _actual_stat_value(actual_row if isinstance(actual_row, dict) else {}, hydrated_row.get("stat") or hydrated_row.get("market") or "")
            if actual_value is not None:
                hydrated_row["actual"] = actual_value
            if isinstance(actual_row, dict):
                minutes_played = _safe_float(actual_row.get("mp") or actual_row.get("min"))
                sim_value = _safe_float(hydrated_row.get("sim_mu_adjusted") if hydrated_row.get("sim_mu_adjusted") is not None else hydrated_row.get("sim_mu"))
                sim_minutes = _safe_float(hydrated_row.get("min_mean") or hydrated_row.get("sim_minutes") or hydrated_row.get("sim_min"))
                existing_live_projection = _safe_float(
                    hydrated_row.get("live_projection") if hydrated_row.get("live_projection") is not None else hydrated_row.get("liveProjection")
                )
                if game_explicitly_not_live and actual_value is not None:
                    live_projection = actual_value
                else:
                    live_projection = existing_live_projection
                if live_projection is None:
                    live_projection = _estimated_live_projection(actual_value, minutes_played, sim_minutes, sim_value)
                    live_projection = _calibrate_live_projection(
                        live_projection,
                        actual_value,
                        player_name=hydrated_row.get("player"),
                        stat_key=hydrated_row.get("stat") or hydrated_row.get("market"),
                    )
                if live_projection is not None:
                    hydrated_row["live_projection"] = live_projection
                    hydrated_row["liveProjection"] = live_projection
                    line_value = _safe_float(hydrated_row.get("line_live") if hydrated_row.get("line_live") is not None else hydrated_row.get("line"))
                    if line_value is not None:
                        live_edge = round(live_projection - line_value, 3)
                        hydrated_row["live_edge"] = live_edge
                        hydrated_row["liveEdge"] = live_edge
                    if existing_live_projection is None:
                        hydrated_row["line_source"] = "boxscore_sim_fallback"
            status_period_value = _safe_float(game_status.get("period"))
            status_period = int(status_period_value) if status_period_value is not None else None
            status_clock = _normalize_status_clock_text(game_status.get("clock"))
            status_text = str(game_status.get("status") or "").strip()
            if bool(game_status.get("final")):
                status_label = "Final"
            elif bool(game_status.get("in_progress")) and status_period is not None:
                status_label = f"Q{status_period} {status_clock}".strip()
            elif bool(game_status.get("in_progress")):
                status_label = status_text or "Live"
            else:
                status_label = status_text or "Scheduled"
            existing_status_label = str(hydrated_row.get("status_label") or "").strip()
            if status_label and (not existing_status_label or existing_status_label in {"Live", "Scheduled"}):
                hydrated_row["status_label"] = status_label
            existing_status_display = str(hydrated_row.get("status_display") or "").strip()
            if status_label and (not existing_status_display or existing_status_display in {"Live", "Scheduled"}):
                hydrated_row["status_display"] = status_label
            existing_status_context = str(hydrated_row.get("status_context") or "").strip()
            if status_text and (not existing_status_context or existing_status_context in {"Live", "Scheduled"}):
                hydrated_row["status_context"] = status_text
            if status_period is not None:
                hydrated_row.setdefault("period", status_period)
                hydrated_row.setdefault("quarter", status_period)
            if status_clock:
                hydrated_row.setdefault("clock", status_clock)
            fallback_row = fallback_rows_by_key.get(_live_player_row_key(hydrated_row, event_id))
            processed_odds_row = _best_live_player_odds_match(processed_odds_by_player, hydrated_row, event_id)
            if isinstance(fallback_row, dict):
                fallback_price_over = _safe_float(fallback_row.get("price_over"))
                fallback_price_under = _safe_float(fallback_row.get("price_under"))
                fallback_price = _safe_float(fallback_row.get("price"))
                repaired_price = False
                if not _price_is_usable(hydrated_row.get("price_over")) and _price_is_usable(fallback_price_over):
                    hydrated_row["price_over"] = fallback_price_over
                    repaired_price = True
                if not _price_is_usable(hydrated_row.get("price_under")) and _price_is_usable(fallback_price_under):
                    hydrated_row["price_under"] = fallback_price_under
                    repaired_price = True
                if not _price_is_usable(hydrated_row.get("price")):
                    side_value = str(hydrated_row.get("ev_side") or hydrated_row.get("lean") or "").strip().upper()
                    if side_value == "OVER":
                        selected_price = fallback_price_over if _price_is_usable(fallback_price_over) else fallback_price_under
                    elif side_value == "UNDER":
                        selected_price = fallback_price_under if _price_is_usable(fallback_price_under) else fallback_price_over
                    else:
                        selected_price = fallback_price_under if _price_is_usable(fallback_price_under) else fallback_price_over
                    if not _price_is_usable(selected_price):
                        selected_price = fallback_price
                    if _price_is_usable(selected_price):
                        hydrated_row["price"] = selected_price
                        repaired_price = True
                if repaired_price:
                    fallback_book = str(fallback_row.get("book") or "").strip()
                    if fallback_book and not str(hydrated_row.get("book") or "").strip():
                        hydrated_row["book"] = fallback_book
                    if str(hydrated_row.get("line_source") or "").strip().lower() == "live_lens_projection_artifact":
                        hydrated_row["line_source"] = str(fallback_row.get("line_source") or "cards_fallback").strip() or "cards_fallback"
            if isinstance(processed_odds_row, dict):
                processed_price_over = _safe_float(processed_odds_row.get("price_over"))
                processed_price_under = _safe_float(processed_odds_row.get("price_under"))
                processed_book = str(processed_odds_row.get("book") or "").strip()
                repaired_price = False
                if not _price_is_usable(hydrated_row.get("price_over")) and _price_is_usable(processed_price_over):
                    hydrated_row["price_over"] = processed_price_over
                    repaired_price = True
                if not _price_is_usable(hydrated_row.get("price_under")) and _price_is_usable(processed_price_under):
                    hydrated_row["price_under"] = processed_price_under
                    repaired_price = True
                preferred_side = _preferred_live_prop_side(hydrated_row)
                if preferred_side and not str(hydrated_row.get("ev_side") or "").strip():
                    hydrated_row["ev_side"] = preferred_side
                if preferred_side and not str(hydrated_row.get("lean") or "").strip():
                    hydrated_row["lean"] = preferred_side
                if not _price_is_usable(hydrated_row.get("price")):
                    if preferred_side == "OVER":
                        selected_price = processed_price_over if _price_is_usable(processed_price_over) else processed_price_under
                    elif preferred_side == "UNDER":
                        selected_price = processed_price_under if _price_is_usable(processed_price_under) else processed_price_over
                    else:
                        selected_price = processed_price_under if _price_is_usable(processed_price_under) else processed_price_over
                    if not _price_is_usable(selected_price):
                        selected_price = processed_price_over if _price_is_usable(processed_price_over) else processed_price_under
                    if _price_is_usable(selected_price):
                        hydrated_row["price"] = selected_price
                        repaired_price = True
                if processed_book and not str(hydrated_row.get("book") or "").strip():
                    hydrated_row["book"] = processed_book
                if repaired_price and str(hydrated_row.get("line_source") or "").strip().lower() == "live_lens_projection_artifact":
                    hydrated_row["line_source"] = "oddsapi_player_props_fallback"
            if str(hydrated_row.get("line_source") or "").strip().lower() == "live_lens_projection_artifact" and not any(
                _price_is_usable(hydrated_row.get(price_key)) for price_key in ("price", "price_over", "price_under")
            ):
                line_value = _safe_float(hydrated_row.get("line_live") if hydrated_row.get("line_live") is not None else hydrated_row.get("line"))
                if line_value is None:
                    continue
            rows.append(hydrated_row)
        hydrated_game["rows"] = _dedupe_live_player_rows(rows)
        hydrated_games.append(hydrated_game)

    hydrated_payload = dict(payload)
    hydrated_payload["games"] = hydrated_games
    return hydrated_payload


def _fallback_live_lines_game(
    game: dict[str, Any],
    *,
    event_id: str | None = None,
    include_period_totals: bool,
) -> dict[str, Any]:
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    return {
        "event_id": event_id or game.get("event_id"),
        "found": True,
        "lines": {
            "total": _safe_float(betting.get("total")),
            "home_spread": _safe_float(betting.get("home_spread")),
            "away_spread": _safe_float(betting.get("away_spread")),
            "home_ml": _safe_float(betting.get("home_ml")),
            "away_ml": _safe_float(betting.get("away_ml")),
            "period_totals": {} if include_period_totals else {},
            "period_spreads": {},
        },
    }


def _fallback_live_player_boxscore_game(
    game: dict[str, Any],
    *,
    event_id: str | None = None,
    selected_date: str | None = None,
) -> dict[str, Any]:
    # Return empty players for pre-game games (fallback is only for games without live data)
    # The sim players should only show in the sim box section, not the live box
    return {"event_id": event_id or game.get("event_id"), "players": []}


def _public_live_player_boxscore_payload(selected_date: str, event_ids: list[str]) -> dict[str, Any] | None:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    if not normalized_event_ids:
        return None

    out_games: list[dict[str, Any]] = []
    for event_id in normalized_event_ids:
        request_url = (
            "https://site.web.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
            f"?event={urllib_parse.quote(event_id)}"
        )
        request_obj = urllib_request.Request(
            request_url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        try:
            with urllib_request.urlopen(request_obj, timeout=6) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue

        boxscore = payload.get("boxscore") if isinstance(payload, dict) else {}
        team_blocks = boxscore.get("players") if isinstance(boxscore, dict) and isinstance(boxscore.get("players"), list) else []
        players_out: list[dict[str, Any]] = []
        for team_block in team_blocks:
            if not isinstance(team_block, dict):
                continue
            team_info = team_block.get("team") if isinstance(team_block.get("team"), dict) else {}
            team_tri = _canonical_wnba_tri(
                str(
                    team_info.get("abbreviation")
                    or team_info.get("shortDisplayName")
                    or team_info.get("displayName")
                    or team_info.get("name")
                    or ""
                ).strip().upper()
            )
            if not team_tri:
                continue

            stat_groups = team_block.get("statistics") if isinstance(team_block.get("statistics"), list) else []
            for group in stat_groups:
                if not isinstance(group, dict):
                    continue
                keys = [str(key or "").strip().upper() for key in (group.get("keys") or [])]
                athletes = group.get("athletes") if isinstance(group.get("athletes"), list) else []
                for athlete_row in athletes:
                    if not isinstance(athlete_row, dict):
                        continue
                    athlete_info = athlete_row.get("athlete") if isinstance(athlete_row.get("athlete"), dict) else {}
                    player_name = str(athlete_info.get("displayName") or athlete_info.get("shortName") or "").strip()
                    if not player_name:
                        continue
                    athlete_position = athlete_info.get("position") if isinstance(athlete_info.get("position"), dict) else {}
                    raw_position = str(
                        athlete_position.get("abbreviation")
                        or athlete_position.get("displayName")
                        or athlete_position.get("name")
                        or athlete_row.get("position")
                        or ""
                    ).strip().upper()
                    stat_values = athlete_row.get("stats") if isinstance(athlete_row.get("stats"), list) else []
                    stat_map: dict[str, Any] = {}
                    for idx, key in enumerate(keys):
                        if not key:
                            continue
                        if idx >= len(stat_values):
                            continue
                        stat_map[key] = stat_values[idx]

                    def _first_stat(*aliases: str) -> Any:
                        for alias in aliases:
                            key = str(alias or "").strip().upper()
                            if key and key in stat_map:
                                return stat_map.get(key)
                        return None

                    minutes_value = _first_stat("MIN", "MINUTES")
                    points = _safe_float(_first_stat("PTS", "POINTS"))
                    rebounds = _safe_float(_first_stat("REB", "REBOUNDS"))
                    assists = _safe_float(_first_stat("AST", "ASSISTS"))
                    threes_made = _safe_float(_first_stat("3PM", "FG3M"))
                    if threes_made is None:
                        threes_text = str(
                            _first_stat(
                                "3PT",
                                "FG3",
                                "THREEPOINTFIELDGOALSMADE-THREEPOINTFIELDGOALSATTEMPTED",
                            )
                            or ""
                        ).strip()
                        if threes_text:
                            first_part = threes_text.split("-", 1)[0].strip()
                            threes_made = _safe_float(first_part)

                    has_box_stats = any(
                        value is not None
                        for value in (points, rebounds, assists, threes_made)
                    )
                    if not has_box_stats and not str(minutes_value or "").strip():
                        continue

                    players_out.append(
                        {
                            "player": player_name,
                            "team_tri": team_tri,
                            "pos": raw_position or None,
                            "mp": minutes_value,
                            "pts": points,
                            "reb": rebounds,
                            "ast": assists,
                            "threes_made": threes_made,
                        }
                    )

        if players_out:
            out_games.append({"event_id": event_id, "players": players_out})

    if not out_games:
        return None
    return {
        "ok": True,
        "ttl": 20,
        "date": selected_date,
        "requested_date": selected_date,
        "lookahead_applied": False,
        "source": "espn_summary_boxscore_fallback",
        "games": out_games,
        "generated_at": _wnba_generated_at(),
    }


def _fallback_live_player_lens_game(game: dict[str, Any], *, event_id: str | None = None) -> dict[str, Any]:
    sim = _sim_payload(game)
    sim_players = sim.get("players") if isinstance(sim.get("players"), dict) else {}
    away_tri = str(game.get("away_tri") or "").strip().upper()
    home_tri = str(game.get("home_tri") or "").strip().upper()
    player_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for side_key, team_tri in (("away", away_tri), ("home", home_tri)):
        side_rows = sim_players.get(side_key) if isinstance(sim_players.get(side_key), list) else []
        for row in side_rows:
            if not isinstance(row, dict):
                continue
            name_key = str(row.get("player_name") or "").strip().upper()
            if name_key and team_tri:
                player_lookup[(team_tri, name_key)] = row

    rows: list[dict[str, Any]] = []
    props = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}
    for side_key, team_tri, opp_tri in (("away", away_tri, home_tri), ("home", home_tri, away_tri)):
        side_rows = props.get(side_key) if isinstance(props.get(side_key), list) else []
        for pick in side_rows:
            if not isinstance(pick, dict):
                continue
            player_name = str(pick.get("player") or pick.get("display_pick") or "").strip()
            market = str(pick.get("market") or "").strip().lower()
            line_value = _safe_float(pick.get("line"))
            if not player_name or not market or line_value is None:
                continue
            side_value = str(pick.get("side") or pick.get("selection") or "").strip().upper()
            sim_row = player_lookup.get((team_tri, player_name.upper()), {})
            sim_mu = _player_sim_stat(sim_row if isinstance(sim_row, dict) else {}, market)
            if sim_mu is None:
                sim_mu = line_value
            pace_proj = sim_mu
            pace_vs_line = None if pace_proj is None else round(pace_proj - line_value, 3)
            ev_value = _safe_float(pick.get("ev_pct"))
            price_over = _safe_float(pick.get("price_over"))
            price_under = _safe_float(pick.get("price_under"))
            generic_price = _safe_float(pick.get("price") or pick.get("odds") or pick.get("price_american"))
            if price_over is None and side_value == "OVER":
                price_over = generic_price
            if price_under is None and side_value == "UNDER":
                price_under = generic_price
            selected_price = price_under if side_value == "UNDER" else price_over
            if selected_price is None:
                selected_price = generic_price
            klass = "NONE"
            if ev_value is not None:
                abs_ev = abs(ev_value)
                if abs_ev >= 8.0:
                    klass = "BET"
                elif abs_ev >= 4.0:
                    klass = "WATCH"
            rows.append(
                {
                    "player": player_name,
                    "player_id": sim_row.get("player_id") if isinstance(sim_row, dict) else None,
                    "player_photo": None,
                    "team_tri": team_tri,
                    "event_id": game.get("event_id"),
                    "stat": market,
                    "line": line_value,
                    "line_live": line_value,
                    "line_source": "cards_fallback",
                    "lean": side_value,
                    "ev_side": side_value,
                    "book": str(pick.get("book") or "").strip() or None,
                    "price_over": price_over,
                    "price_under": price_under,
                    "price": selected_price,
                    "ev": None if ev_value is None else round(ev_value / 100.0, 6),
                    "win_prob": _safe_float(pick.get("p_win")),
                    "recommendation_priority_score": ev_value,
                    "klass": klass,
                    "actual": None,
                    "pace_proj": pace_proj,
                    "pace_vs_line": pace_vs_line,
                    "sim_mu": sim_mu,
                    "sim_mu_adjusted": sim_mu,
                    "sim_vs_line": None if sim_mu is None else round(sim_mu - line_value, 3),
                    "sim_vs_line_adjusted": None if sim_mu is None else round(sim_mu - line_value, 3),
                    "status_label": "Live",
                    "opponent_tri": opp_tri,
                }
            )

    return {
        "event_id": event_id or game.get("event_id"),
        "game_id": game.get("gamePk"),
        "home": home_tri,
        "away": away_tri,
        "status": _status_from_game(game),
        "rows": rows,
    }


def build_live_state_payload(selected_date: str, ttl: int = 12, *, allow_stored_date_fallback: bool = True) -> dict[str, Any]:
    is_today = str(selected_date).strip() == central_today_iso()

    if _render_web_dyno():
        local_payload = _local_live_state_payload(selected_date)
        if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list) and bool(local_payload.get("games")):
            return _attach_odds_refresh_timestamp(local_payload)
        context_for_event_ids = build_cards_page_context(selected_date, allow_stored_date_fallback=False)
        context_games = context_for_event_ids.get("games") if isinstance(context_for_event_ids.get("games"), list) else []
        out_games: list[dict[str, Any]] = []
        for game in context_games:
            if not isinstance(game, dict):
                continue
            away_info = game.get("away") if isinstance(game.get("away"), dict) else {}
            home_info = game.get("home") if isinstance(game.get("home"), dict) else {}
            sim_score = (_sim_payload(game).get("score") or {})
            out_games.append(
                {
                    "game_id": game.get("gamePk"),
                    "event_id": game.get("event_id"),
                    "home": game.get("home_tri") or home_info.get("abbr"),
                    "away": game.get("away_tri") or away_info.get("abbr"),
                    "home_pts": _safe_float(sim_score.get("home_mean")),
                    "away_pts": _safe_float(sim_score.get("away_mean")),
                    "status_id": None,
                    "status": _safe_text(game.get("status"), _safe_text(game.get("detail"), "Scheduled")),
                    "period": None,
                    "clock": "",
                    "in_progress": bool((game.get("live_state") or {}).get("in_progress") if isinstance(game.get("live_state"), dict) else False),
                    "final": bool((game.get("live_state") or {}).get("final") if isinstance(game.get("live_state"), dict) else False),
                    "periods": [],
                }
            )
        return _attach_odds_refresh_timestamp({
            "date": selected_date,
            "ttl": int(ttl),
            "source": "wnba_artifacts",
            "games": out_games,
            "generated_at": _wnba_generated_at(),
        })

    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    games = context.get("games") if isinstance(context.get("games"), list) else []
    public_payload = _public_scoreboard_live_state_payload(selected_date) if is_today or allow_stored_date_fallback else None
    public_games = public_payload.get("games") if isinstance(public_payload, dict) and isinstance(public_payload.get("games"), list) else []
    public_by_event_id = {
        str(game.get("event_id") or "").strip(): game
        for game in public_games
        if isinstance(game, dict) and str(game.get("event_id") or "").strip()
    }
    out_games = []
    for game in games:
        if not isinstance(game, dict):
            continue
        event_id = str(game.get("event_id") or "").strip()
        public_row = public_by_event_id.get(event_id) if event_id else None
        if isinstance(public_row, dict):
            cards_state = _cards_context_live_state_snapshot(game)
            if _live_state_row_needs_cards_override(public_row, cards_state):
                public_row = {
                    **dict(public_row),
                    "away_pts": cards_state.get("away_pts"),
                    "home_pts": cards_state.get("home_pts"),
                    "status": cards_state.get("status") or public_row.get("status"),
                    "clock": cards_state.get("clock") or public_row.get("clock") or "",
                    "period": cards_state.get("period") or public_row.get("period"),
                    "in_progress": bool(cards_state.get("in_progress")),
                    "final": bool(cards_state.get("final")),
                }
        else:
            public_row = None
        normalized_status = _normalized_game_status(
            status_text=game.get("status"),
            detail_text=game.get("detail"),
            start_time_utc=game.get("start_time") or ((game.get("odds") or {}).get("commence_time") if isinstance(game.get("odds"), dict) else None),
            in_progress=((game.get("live_state") or {}).get("in_progress") if isinstance(game.get("live_state"), dict) else False),
            final=((game.get("live_state") or {}).get("final") if isinstance(game.get("live_state"), dict) else False),
            away_pts=((game.get("away") or {}).get("score") if isinstance(game.get("away"), dict) else None),
            home_pts=((game.get("home") or {}).get("score") if isinstance(game.get("home"), dict) else None),
        )
        away_info = game.get("away") if isinstance(game.get("away"), dict) else {}
        home_info = game.get("home") if isinstance(game.get("home"), dict) else {}
        sim_score = (_sim_payload(game).get("score") or {})
        source_row = public_row if isinstance(public_row, dict) else None
        source_away_pts = _safe_float(source_row.get("away_pts")) if source_row else _safe_float(sim_score.get("away_mean"))
        source_home_pts = _safe_float(source_row.get("home_pts")) if source_row else _safe_float(sim_score.get("home_mean"))
        source_status = str(source_row.get("status") or "").strip() if source_row else normalized_status["detail"]
        source_clock = str(source_row.get("clock") or "").strip() if source_row else normalized_status.get("clock") or ""
        source_period = source_row.get("period") if source_row else normalized_status.get("period")
        source_in_progress = bool(source_row.get("in_progress")) if source_row else bool(normalized_status["in_progress"])
        source_final = bool(source_row.get("final")) if source_row else bool(normalized_status["final"])
        out_games.append(
            {
                "game_id": game.get("gamePk"),
                "event_id": game.get("event_id"),
                "home": game.get("home_tri") or home_info.get("abbr"),
                "away": game.get("away_tri") or away_info.get("abbr"),
                "home_pts": source_home_pts,
                "away_pts": source_away_pts,
                "status_id": None,
                "status": source_status,
                "period": source_period,
                "clock": source_clock,
                "in_progress": source_in_progress,
                "final": source_final,
                "periods": [],
            }
        )

        if event_id:
            public_by_event_id.pop(event_id, None)

    for event_id, public_row in public_by_event_id.items():
        if not isinstance(public_row, dict):
            continue
        cards_state = {
            "away_pts": _safe_float(public_row.get("away_pts")),
            "home_pts": _safe_float(public_row.get("home_pts")),
            "status": str(public_row.get("status") or "").strip(),
            "period": public_row.get("period"),
            "clock": str(public_row.get("clock") or "").strip(),
            "in_progress": bool(public_row.get("in_progress")),
            "final": bool(public_row.get("final")),
        }
        merged_public_row = dict(public_row)
        if cards_state.get("status"):
            merged_public_row["status"] = cards_state["status"]
        if cards_state.get("clock"):
            merged_public_row["clock"] = cards_state["clock"]
        out_games.append(
            {
                "game_id": merged_public_row.get("game_id") or event_id,
                "event_id": event_id,
                "home": merged_public_row.get("home"),
                "away": merged_public_row.get("away"),
                "home_pts": _safe_float(merged_public_row.get("home_pts")),
                "away_pts": _safe_float(merged_public_row.get("away_pts")),
                "status_id": None,
                "status": str(merged_public_row.get("status") or "").strip() or "Scheduled",
                "period": merged_public_row.get("period"),
                "clock": str(merged_public_row.get("clock") or "").strip(),
                "in_progress": bool(merged_public_row.get("in_progress")),
                "final": bool(merged_public_row.get("final")),
                "periods": list(merged_public_row.get("periods") or []),
            }
        )

    return _attach_odds_refresh_timestamp({
        "date": selected_date,
        "ttl": int(ttl),
        "source": "syndicate_cards_fallback",
        "games": out_games,
        "generated_at": _wnba_generated_at(),
    })


def build_live_player_boxscore_payload(
    selected_date: str,
    event_ids: list[str],
    ttl: int = 20,
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    if not normalized_event_ids:
        normalized_event_ids = _default_live_event_ids(
            selected_date,
            allow_stored_date_fallback=allow_stored_date_fallback,
        )
    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    resolved_date = str(context.get("date") or selected_date).strip() or selected_date
    local_payload = _filtered_local_live_snapshot_payload("live_player_boxscore", resolved_date, normalized_event_ids)
    if _payload_has_live_boxscore_players(local_payload):
        return _attach_odds_refresh_timestamp(local_payload)

    public_payload = _public_live_player_boxscore_payload(resolved_date, normalized_event_ids)
    if _payload_has_live_boxscore_players(public_payload):
        return _attach_odds_refresh_timestamp(public_payload)

    game_index = _resolve_games_for_event_ids(resolved_date, normalized_event_ids)
    resolved_event_ids = resolve_event_ids_from_games(game_index, normalized_event_ids)
    if resolved_event_ids:
        local_payload = _filtered_local_live_snapshot_payload("live_player_boxscore", resolved_date, resolved_event_ids)
        if _payload_has_live_boxscore_players(local_payload):
            return _attach_odds_refresh_timestamp(local_payload)

        public_payload = _public_live_player_boxscore_payload(resolved_date, resolved_event_ids)
        if _payload_has_live_boxscore_players(public_payload):
            return _attach_odds_refresh_timestamp(public_payload)

    return _attach_odds_refresh_timestamp({
        "ok": True,
        "ttl": int(ttl),
        "date": resolved_date or None,
        "requested_date": selected_date,
        "lookahead_applied": bool(resolved_date != selected_date),
        "games": [{"event_id": event_id, "game_id": event_id, "players": []} for event_id in normalized_event_ids],
        "generated_at": _wnba_generated_at(),
    })


def build_live_player_lens_payload(
    selected_date: str,
    event_ids: list[str],
    ttl: int = 20,
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    if not normalized_event_ids:
        normalized_event_ids = _default_live_event_ids(
            selected_date,
            allow_stored_date_fallback=allow_stored_date_fallback,
        )
    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    resolved_date = str(context.get("date") or selected_date).strip() or selected_date
    local_payload = _filtered_local_live_snapshot_payload("live_player_lens", resolved_date, normalized_event_ids)
    is_today = str(selected_date).strip() == central_today_iso()
    local_timestamp = _parse_payload_timestamp((local_payload or {}).get("odds_refreshed_at") or (local_payload or {}).get("generated_at"))
    if is_today and local_timestamp and (datetime.now(timezone.utc) - local_timestamp) > timedelta(minutes=20):
        local_payload = None
    if _payload_has_live_lens_rows(local_payload):
        return _hydrate_live_player_lens_payload(
            _attach_odds_refresh_timestamp(local_payload),
            resolved_date,
            normalized_event_ids,
            allow_stored_date_fallback=allow_stored_date_fallback,
        )

    artifact_payload = _artifact_live_player_lens_payload(
        resolved_date,
        normalized_event_ids,
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
    if _payload_has_live_lens_rows(artifact_payload):
        return _hydrate_live_player_lens_payload(
            _attach_odds_refresh_timestamp(artifact_payload),
            resolved_date,
            normalized_event_ids,
            allow_stored_date_fallback=allow_stored_date_fallback,
        )

    game_index = _resolve_games_for_event_ids(resolved_date, normalized_event_ids)
    fallback_games = [
        _fallback_live_player_lens_game(game, event_id=event_id)
        for event_id in normalized_event_ids
        for game in [game_index.get(event_id)]
        if isinstance(game, dict)
    ]
    if fallback_games:
        return _hydrate_live_player_lens_payload(_attach_odds_refresh_timestamp({
            "ok": True,
            "ttl": int(ttl),
            "date": resolved_date or None,
            "requested_date": selected_date,
            "lookahead_applied": bool(resolved_date != selected_date),
            "games": fallback_games,
            "generated_at": _wnba_generated_at(),
        }), resolved_date, normalized_event_ids, allow_stored_date_fallback=allow_stored_date_fallback)
    return _attach_odds_refresh_timestamp({
        "ok": True,
        "ttl": int(ttl),
        "date": resolved_date or None,
        "requested_date": selected_date,
        "lookahead_applied": bool(resolved_date != selected_date),
        "games": [
            {
                "event_id": event_id,
                "game_id": event_id,
                "home": None,
                "away": None,
                "status": {"in_progress": False, "final": False, "period": None, "clock": ""},
                "rows": [],
            }
            for event_id in normalized_event_ids
        ],
        "generated_at": _wnba_generated_at(),
    })


def build_live_lines_payload(
    selected_date: str,
    event_ids: list[str],
    ttl: int = 20,
    include_period_totals: bool = False,
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    if not normalized_event_ids:
        normalized_event_ids = _default_live_event_ids(
            selected_date,
            allow_stored_date_fallback=allow_stored_date_fallback,
        )
    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    resolved_date = str(context.get("date") or selected_date).strip() or selected_date
    local_payload = _filtered_local_live_snapshot_payload("live_lines", resolved_date, normalized_event_ids)
    is_today = str(selected_date).strip() == central_today_iso()
    local_timestamp = _parse_payload_timestamp((local_payload or {}).get("odds_refreshed_at") or (local_payload or {}).get("generated_at"))
    if is_today and local_timestamp and (datetime.now(timezone.utc) - local_timestamp) > timedelta(minutes=20):
        local_payload = None
    merged_payload = local_payload if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list) and bool(local_payload.get("games")) else None
    if _payload_has_requested_live_line_coverage(
        merged_payload,
        normalized_event_ids,
        include_period_totals=bool(include_period_totals),
    ):
        return _attach_odds_refresh_timestamp(_finalize_live_lines_payload(merged_payload, include_period_totals=bool(include_period_totals)))

    artifact_payload = _artifact_live_lines_payload(
        resolved_date,
        normalized_event_ids,
        include_period_totals=bool(include_period_totals),
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
    if isinstance(artifact_payload, dict) and isinstance(artifact_payload.get("games"), list) and bool(artifact_payload.get("games")):
        merged_payload = _merge_live_lines_payloads(merged_payload, artifact_payload)
        if _payload_has_requested_live_line_coverage(
            merged_payload,
            normalized_event_ids,
            include_period_totals=bool(include_period_totals),
        ):
            return _attach_odds_refresh_timestamp(_finalize_live_lines_payload(merged_payload, include_period_totals=bool(include_period_totals)))

    game_index = _resolve_games_for_event_ids(resolved_date, normalized_event_ids)
    fallback_games = [
        _fallback_live_lines_game(game, event_id=event_id, include_period_totals=bool(include_period_totals))
        for event_id in normalized_event_ids
        for game in [game_index.get(event_id)]
        if isinstance(game, dict)
    ]
    if fallback_games:
        fallback_payload = {
            "ok": True,
            "ttl": int(ttl),
            "date": resolved_date,
            "requested_date": selected_date,
            "lookahead_applied": bool(resolved_date != selected_date),
            "include_period_totals": bool(include_period_totals),
            "games": fallback_games,
            "generated_at": _wnba_generated_at(),
        }
        merged_payload = _merge_live_lines_payloads(merged_payload, fallback_payload)
        return _attach_odds_refresh_timestamp(_finalize_live_lines_payload(merged_payload or fallback_payload, include_period_totals=bool(include_period_totals)))
    if merged_payload:
        return _attach_odds_refresh_timestamp(_finalize_live_lines_payload(merged_payload, include_period_totals=bool(include_period_totals)))
    return _attach_odds_refresh_timestamp({
        "ok": True,
        "ttl": int(ttl),
        "date": resolved_date,
        "requested_date": selected_date,
        "lookahead_applied": bool(resolved_date != selected_date),
        "include_period_totals": bool(include_period_totals),
        "games": [{"event_id": event_id, "game_id": event_id, "found": False} for event_id in normalized_event_ids],
        "generated_at": _wnba_generated_at(),
    })


def build_live_pbp_stats_payload(
    selected_date: str,
    event_ids: list[str],
    ttl: int = 20,
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    resolved_date = str(context.get("date") or selected_date).strip() or selected_date
    local_payload = _filtered_local_live_snapshot_payload("live_pbp_stats", resolved_date, normalized_event_ids)
    if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list) and bool(local_payload.get("games")):
        return _attach_odds_refresh_timestamp(local_payload)
    return _attach_odds_refresh_timestamp({
        "ok": True,
        "ttl": int(ttl),
        "date": resolved_date or None,
        "requested_date": selected_date,
        "lookahead_applied": bool(resolved_date != selected_date),
        "games": [
            {
                "event_id": event_id,
                "game_id": event_id,
                "home": None,
                "away": None,
                "pbp_attempts": {"home": {}, "away": {}, "unknown": {}, "total": {}},
                "pbp_attempts_periods": {},
                "pbp_possessions": {"home": {}, "away": {}, "unknown": {}, "total": {}},
                "pbp_possessions_periods": {},
                "pbp_quarters": {"q_totals": {"q1": None, "q2": None, "q3": None, "q4": None}, "current": {"period": None, "q_total": None}},
                "pbp_recent": {"window_sec": 180, "points_total": None, "attempts": None, "possessions": None, "current_scoring_run": {"team": None, "points": None}, "seconds_since_score": None},
            }
            for event_id in normalized_event_ids
        ],
        "generated_at": _wnba_generated_at(),
    })


def build_live_lens_tuning_payload(ttl: int = 300) -> dict[str, Any]:
    return {
        "ok": True,
        "ttl": int(ttl),
        "round_live_line_to_half": True,
        "logging": {"mode": "bet", "min_interval_sec": 60},
        "markets": {
            "total": {"watch": 3.0, "bet": 6.0},
            "half_total": {"watch": 3.0, "bet": 6.0},
            "quarter_total": {"watch": 2.0, "bet": 4.0},
            "ats": {"watch": 2.0, "bet": 4.0},
            "player_prop": {"watch": 2.0, "bet": 4.0},
        },
        "generated_at": _wnba_generated_at(),
    }


def _infer_period_clock_from_status_text(status_text: Any) -> tuple[int | None, str]:
    text = str(status_text or "").strip()
    if not text:
        return None, ""
    match = re.search(r"(?P<clock>\d{1,2}:\d{2}|\d{1,2}(?:\.\d)?)\s*-\s*(?P<period>(?:1st|2nd|3rd|4th|OT|\d+OT))", text, re.IGNORECASE)
    if not match:
        return None, ""
    clock = _normalize_status_clock_text(match.group("clock"))
    period_label = str(match.group("period") or "").strip().upper()
    if period_label == "1ST":
        return 1, clock
    if period_label == "2ND":
        return 2, clock
    if period_label == "3RD":
        return 3, clock
    if period_label == "4TH":
        return 4, clock
    if period_label == "OT":
        return 5, clock
    overtime_match = re.fullmatch(r"(\d+)OT", period_label)
    if overtime_match:
        overtime_index = int(overtime_match.group(1) or 1)
        return max(5, 4 + overtime_index), clock
    return None, clock


def _normalize_status_clock_text(clock_text: Any) -> str:
    raw = str(clock_text or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{1,2}:\d{2}", raw):
        return raw
    seconds_value = _safe_float(raw)
    if seconds_value is None:
        return raw
    whole_seconds = max(0, int(math.floor(seconds_value)))
    minutes = whole_seconds // 60
    seconds = whole_seconds % 60
    return f"{minutes}:{seconds:02d}"