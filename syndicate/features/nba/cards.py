from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import csv
import json
import math
import os
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from syndicate.features.nba.sources import build_module_links
from syndicate.features.nba.sources import available_dates
from syndicate.features.nba.sources import format_moneyline
from syndicate.features.nba.sources import format_num
from syndicate.features.nba.sources import format_signed_num
from syndicate.features.nba.sources import load_json
from syndicate.features.nba.sources import market_label
from syndicate.features.nba.sources import parse_iso_date
from syndicate.features.nba.sources import processed_path
from syndicate.features.nba.sources import live_snapshot_path
from syndicate.features.shared.basketball_live_artifacts import build_live_lines_payload_from_artifacts
from syndicate.features.shared.basketball_live_artifacts import build_live_player_lens_payload_from_artifacts
from syndicate.features.shared.basketball_market_board import basketball_odds_history_payload
from syndicate.features.shared.basketball_market_board import build_basketball_market_board
from syndicate.features.shared.basketball_market_board import parse_raw_basketball_player_props_rows
from syndicate.features.shared.basketball_live_artifacts import resolve_event_ids_from_games
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.team_branding import read_team_branding_snapshot
from syndicate.features.shared.team_branding import team_branding_index_by_abbreviation
from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.shared.game_board_contract import _sim_payload
from syndicate.features.shared.refresh_state_store import read_text_file as _keyvalue_read_text_file
from syndicate.features.shared.timezone import central_now
from syndicate.features.shared.timezone import central_today_iso


def _render_web_dyno() -> bool:
    # RENDER is injected by Render on every service type (web *and* background
    # workers), so it can't distinguish "am I the request-serving web dyno"
    # from "am I a worker script calling into this module directly" -- that
    # ambiguity let worker-side snapshot builders (refresh_nba_oddsapi_props.py's
    # _export_live_snapshot_artifacts calling build_live_state_payload) take the
    # "just return whatever's cached" branch meant only for actual web requests,
    # so a stale snapshot got read back and rewritten forever instead of ever
    # being recomputed. Same root cause and fix as WNBA (see wnba/cards.py).
    # SYNDICATE_WEB_DYNO is an explicit, unambiguous override set only on the
    # web service in render.yaml; fall back to the old heuristic when unset
    # (local dev, other hosts).
    explicit = str(os.environ.get("SYNDICATE_WEB_DYNO") or "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "on"}
    return str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}


_NBA_CARDS_CONTEXT_CACHE: "OrderedDict[tuple[Any, ...], dict[str, Any]]" = OrderedDict()
_NBA_CARDS_CONTEXT_CACHE_MAX_ENTRIES = 32


def _cache_get_context(cache_key: tuple[Any, ...]) -> dict[str, Any] | None:
    cached = _NBA_CARDS_CONTEXT_CACHE.get(cache_key)
    if cached is not None:
        _NBA_CARDS_CONTEXT_CACHE.move_to_end(cache_key)
    return cached


def _cache_put_context(cache_key: tuple[Any, ...], result: dict[str, Any]) -> None:
    _NBA_CARDS_CONTEXT_CACHE[cache_key] = result
    _NBA_CARDS_CONTEXT_CACHE.move_to_end(cache_key)
    while len(_NBA_CARDS_CONTEXT_CACHE) > _NBA_CARDS_CONTEXT_CACHE_MAX_ENTRIES:
        _NBA_CARDS_CONTEXT_CACHE.popitem(last=False)


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


def _live_snapshot_or_state_signature(path: Path | None) -> int:
    # live_state.jsonl / live_lines / live_player_lens / live_player_boxscore
    # / live_pbp_stats are written cross-service through the keyvalue store
    # (live-odds-worker computes them, the web service has a separate disk),
    # so under the keyvalue backend they no longer exist as real local files
    # -- _path_cache_signature would always see "file not found" and return
    # the same value forever, making the lru_cache below permanently stale.
    # Mirrors the identical fix already applied to WNBA's copy of this same
    # bug (_game_cards_or_live_state_signature / _local_live_snapshot_payload
    # in syndicate/features/wnba/cards.py) -- hash the actual keyvalue
    # content instead so the cache key changes whenever the underlying data
    # does.
    if path is not None:
        keyvalue_text = _keyvalue_read_text_file(path)
        if keyvalue_text is not None:
            return hash(keyvalue_text)
    return _path_cache_signature(path)


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _espn_logo_abbr(team_tri: str) -> str:
    value = str(team_tri or "").strip().upper()
    return {
        "GSW": "GS",
        "NOP": "NO",
        "NYK": "NY",
        "UTA": "UTAH",
        "WAS": "WSH",
        "SAS": "SA",
        "PHX": "PHO",
    }.get(value, value)


def _canonical_nba_tri(team_tri: str) -> str:
    value = str(team_tri or "").strip().upper()
    compact = "".join(ch for ch in value if ch.isalnum())
    mapped = {
        "GS": "GSW",
        "NO": "NOP",
        "NY": "NYK",
        "UTAH": "UTA",
        "WSH": "WAS",
        "PHO": "PHX",
        "SA": "SAS",
        "GOLDENSTATEWARRIORS": "GSW",
        "NEWORLEANSPELICANS": "NOP",
        "NEWYORKKNICKS": "NYK",
        "WASHINGTONWIZARDS": "WAS",
        "PHOENIXSUNS": "PHX",
        "SANANTONIOSPURS": "SAS",
        "LOSANGELESLAKERS": "LAL",
        "LOSANGELESCLIPPERS": "LAC",
        "BROOKLYNNETS": "BKN",
        "BOSTONCELTICS": "BOS",
        "MILWAUKEEBUCKS": "MIL",
        "PHILADELPHIA76ERS": "PHI",
        "MIAMIHEAT": "MIA",
        "CHICAGOBULLS": "CHI",
        "CLEVELANDCAVALIERS": "CLE",
        "INDIANAPACERS": "IND",
        "ATLANTAHAWKS": "ATL",
        "CHARLOTTEHORNETS": "CHA",
        "TORONTORAPTORS": "TOR",
        "DALLASMAVERICKS": "DAL",
        "DENVERNUGGETS": "DEN",
        "HOUSTONROCKETS": "HOU",
        "MEMPHISGRIZZLIES": "MEM",
        "MINNESOTATIMBERWOLVES": "MIN",
        "OKLAHOMACITYTHUNDER": "OKC",
        "PORTLANDTRAILBLAZERS": "POR",
        "SACRAMENTOKINGS": "SAC",
    }
    return mapped.get(value, mapped.get(compact, value))


@lru_cache(maxsize=1)
def _nba_team_branding_index() -> dict[str, Any]:
    root = preferred_source_roots(__file__, env_var="SYNDICATE_NBA_SOURCE_ROOT", local_dir_name="nba_source")[0]
    path = root / "source_artifacts" / "data" / "processed" / "team_branding" / "nba_team_branding.csv"
    return team_branding_index_by_abbreviation(read_team_branding_snapshot(path))


def _nba_branding(team_tri: str) -> Any | None:
    abbr = _espn_logo_abbr(team_tri)
    if not abbr:
        return None
    return _nba_team_branding_index().get(abbr.upper())


def _nba_logo_url(team_tri: str) -> str | None:
    branding = _nba_branding(team_tri)
    if branding and branding.logo_url:
        return branding.logo_url
    # Fallback to the same CDN URL pattern the branding snapshot itself uses,
    # in case the snapshot file is missing/stale in a given environment.
    abbr = _espn_logo_abbr(team_tri)
    if not abbr:
        return None
    return f"https://a.espncdn.com/i/teamlogos/nba/500/{abbr.lower()}.png"


def _nba_primary_color(team_tri: str) -> str | None:
    branding = _nba_branding(team_tri)
    return branding.primary_color if branding else None


def _nba_secondary_color(team_tri: str) -> str | None:
    branding = _nba_branding(team_tri)
    return branding.secondary_color if branding else None


def _recommendation_index(summary: dict[str, Any] | None) -> dict[tuple[str, str], list[dict[str, Any]]]:
    per_game = summary.get("per_game") if isinstance((summary or {}).get("per_game"), list) else []
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in per_game:
        if not isinstance(item, dict):
            continue
        home = str(item.get("home") or "").strip().upper()
        away = str(item.get("away") or "").strip().upper()
        picks = item.get("picks") if isinstance(item.get("picks"), list) else []
        if home and away:
            index[(home, away)] = [pick for pick in picks if isinstance(pick, dict)]
    return index


def _artifact_games_index(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    payload = load_json(path)
    games = payload.get("games") if isinstance((payload or {}).get("games"), list) else []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        home = str(game.get("home_tri") or "").strip().upper()
        away = str(game.get("away_tri") or "").strip().upper()
        if home and away:
            index[(home, away)] = game
    return index


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _parse_utc_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass

    match = re.match(r"^\s*(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*([A-Z]{2,3})?\s*$", text.upper())
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    hour = int(match.group(3))
    minute = int(match.group(4))
    meridiem = match.group(5)
    tz_code = (match.group(6) or "ET").upper()

    if hour == 12:
        hour = 0
    if meridiem == "PM":
        hour += 12

    year = datetime.now(timezone.utc).year
    try:
        naive = datetime(year, month, day, hour, minute)
    except Exception:
        return None

    offset_hours = {
        "ET": -4,
        "EDT": -4,
        "EST": -5,
        "CT": -5,
        "CDT": -5,
        "CST": -6,
    }.get(tz_code, -4)
    local_tz = timezone(timedelta(hours=offset_hours))
    return naive.replace(tzinfo=local_tz).astimezone(timezone.utc)


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


def _implied_prob_from_american(price: float | None) -> float | None:
    value = _safe_float(price)
    if value is None or value == 0:
        return None
    if value > 0:
        return 100.0 / (value + 100.0)
    return abs(value) / (abs(value) + 100.0)


def _normalize_two_way(first: Any, second: Any) -> tuple[float, float]:
    left = _safe_float(first)
    right = _safe_float(second)
    if left is not None and right is not None and (left + right) > 0:
        total = left + right
        return left / total, right / total
    if left is not None:
        clamped = max(0.0, min(1.0, left))
        return clamped, 1.0 - clamped
    if right is not None:
        clamped = max(0.0, min(1.0, right))
        return 1.0 - clamped, clamped
    return 0.5, 0.5


def _default_segment(total_mean: float | None, margin_mean: float | None, win_prob: float) -> dict[str, Any]:
    return {
        "total_mean": total_mean,
        "margin_mean": margin_mean,
        "p_home_win": win_prob,
    }


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
    prop_recommendations = props_game.get("prop_recommendations") if isinstance(props_game.get("prop_recommendations"), dict) else props_game
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


def _next_available_cards_date(selected_date: str, *, max_ahead_days: int = 14) -> str | None:
    _ = max_ahead_days
    dates = available_dates()
    future_dates = [value for value in dates if value > selected_date]
    if future_dates:
        return future_dates[0]
    past_dates = [value for value in dates if value < selected_date]
    if past_dates:
        return past_dates[-1]
    return None


def _artifact_bundle(selected_date: str) -> dict[str, Any]:
    paths = _artifact_paths(selected_date)
    rows = _load_csv_rows(paths["cards"])
    rec_summary = load_json(paths["recommendations"])
    return {
        "paths": paths,
        "rows": rows,
        "recommendations": _recommendation_index(rec_summary),
        "sim": _artifact_games_index(paths["sim"]),
        "props": _artifact_games_index(paths["props"]),
    }


def _read_live_snapshot_jsonl_payload(path: Path) -> dict[str, Any] | None:
    # Keyvalue-aware (not path.read_text()) -- live_state.jsonl and the
    # live_lines/live_player_lens/live_player_boxscore/live_pbp_stats
    # snapshots below are computed by live-odds-worker and read by whichever
    # process handles the request (often a different Render service, a
    # separate disk), so a plain local-disk read here only ever saw whatever
    # THIS process itself had already written. Same root cause already fixed
    # for WNBA's copy of this function (confirmed live 2026-07-22: WNBA live
    # player props stayed empty for exactly this reason).
    text = _keyvalue_read_text_file(path)
    if text is None:
        return None
    lines = text.splitlines()
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


@lru_cache(maxsize=64)
def _local_live_state_payload_cached(selected_date: str, signature: int) -> dict[str, Any] | None:
    try:
        path = live_snapshot_path(f"live_state_{selected_date}.jsonl")
    except FileNotFoundError:
        return None
    return _read_live_snapshot_jsonl_payload(path)


def _local_live_state_payload(selected_date: str) -> dict[str, Any] | None:
    try:
        path = live_snapshot_path(f"live_state_{selected_date}.jsonl")
    except FileNotFoundError:
        return _local_live_state_payload_cached(selected_date, 0)
    return _local_live_state_payload_cached(selected_date, _live_snapshot_or_state_signature(path))


_local_live_state_payload.cache_clear = _local_live_state_payload_cached.cache_clear  # type: ignore[attr-defined]
_local_live_state_payload.cache_info = _local_live_state_payload_cached.cache_info  # type: ignore[attr-defined]


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


def _payload_has_live_progress(payload: dict[str, Any] | None) -> bool:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    for game in games:
        if not isinstance(game, dict):
            continue
        status_id = int(_safe_float(game.get("status_id")) or 0)
        if bool(game.get("in_progress")) or bool(game.get("final")) or status_id > 1:
            return True
    return False


def _espn_live_state_payload(selected_date: str) -> dict[str, Any] | None:
    date_value = str(selected_date or "").strip()
    if not date_value:
        return None
    try:
        date_compact = parse_iso_date(date_value).strftime("%Y%m%d")
    except Exception:
        return None
    url = (
        "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
        f"?dates={date_compact}"
    )
    request = urllib_request.Request(url, headers={"User-Agent": "Syndicate-NBA/1.0"})
    try:
        with urllib_request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    events = payload.get("events") if isinstance(payload, dict) and isinstance(payload.get("events"), list) else []
    out_games: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip() or None
        competitions = event.get("competitions") if isinstance(event.get("competitions"), list) else []
        competition = competitions[0] if competitions and isinstance(competitions[0], dict) else {}
        competitors = competition.get("competitors") if isinstance(competition.get("competitors"), list) else []
        home_row = next((row for row in competitors if isinstance(row, dict) and str(row.get("homeAway") or "").lower() == "home"), None)
        away_row = next((row for row in competitors if isinstance(row, dict) and str(row.get("homeAway") or "").lower() == "away"), None)
        if not isinstance(home_row, dict) or not isinstance(away_row, dict):
            continue
        home_team = home_row.get("team") if isinstance(home_row.get("team"), dict) else {}
        away_team = away_row.get("team") if isinstance(away_row.get("team"), dict) else {}
        home_tri = str(home_team.get("abbreviation") or "").strip().upper()
        away_tri = str(away_team.get("abbreviation") or "").strip().upper()
        if not home_tri or not away_tri:
            continue

        status_block = competition.get("status") if isinstance(competition.get("status"), dict) else {}
        status_type = status_block.get("type") if isinstance(status_block.get("type"), dict) else {}
        state = str(status_type.get("state") or "").strip().lower()
        final = bool(status_type.get("completed") or (state == "post"))
        in_progress = bool((state == "in") and not final)
        status_id = 3 if final else (2 if in_progress else 1)
        status_text = str(
            status_type.get("shortDetail")
            or status_type.get("detail")
            or status_type.get("description")
            or ""
        ).strip() or ("Final" if final else ("Live" if in_progress else "Scheduled"))

        period_value = _safe_float(status_block.get("period"))
        period = int(period_value) if period_value is not None else None
        clock = str(status_block.get("displayClock") or status_block.get("clock") or "").strip()

        away_pts = _safe_float(away_row.get("score"))
        home_pts = _safe_float(home_row.get("score"))
        out_games.append(
            {
                "game_id": f"{away_tri}@{home_tri}",
                "event_id": event_id,
                "home": home_tri,
                "away": away_tri,
                "home_pts": home_pts,
                "away_pts": away_pts,
                "status_id": status_id,
                "status": status_text,
                "period": period,
                "clock": clock,
                "in_progress": in_progress,
                "final": final,
                "periods": [],
            }
        )

    return {
        "date": date_value,
        "games": out_games,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "espn_live_fetch",
        "ttl": 12,
    }


def _best_live_state_payload(selected_date: str) -> dict[str, Any] | None:
    local_payload = _local_live_state_payload(selected_date)
    parsed_selected_date = parse_iso_date(selected_date)
    today = datetime.now(timezone.utc).date()
    is_recent_day = parsed_selected_date in {today, (today - timedelta(days=1))}
    local_timestamp = _parse_payload_timestamp((local_payload or {}).get("generated_at"))
    local_stale = bool(local_timestamp and (datetime.now(timezone.utc) - local_timestamp) > timedelta(minutes=20))

    should_try_espn = bool(is_recent_day and (local_payload is None or local_stale or not _payload_has_live_progress(local_payload)))
    if should_try_espn:
        espn_payload = _espn_live_state_payload(selected_date)
        if isinstance(espn_payload, dict):
            if not isinstance(local_payload, dict):
                return espn_payload
            if _payload_has_live_progress(espn_payload) and not _payload_has_live_progress(local_payload):
                return espn_payload
            espn_timestamp = _parse_payload_timestamp(espn_payload.get("generated_at"))
            if espn_timestamp and local_timestamp and espn_timestamp > local_timestamp:
                return espn_payload
    return local_payload


def _games_from_live_state_fallback(selected_date: str, ttl: int = 12) -> tuple[list[dict[str, Any]], str]:
    payload = _best_live_state_payload(selected_date)
    source_path = None
    if isinstance(payload, dict):
        if str(payload.get("source") or "").strip().lower().startswith("espn"):
            source_path = "espn_live_fetch"
        else:
            try:
                source_path = str(live_snapshot_path(f"live_state_{selected_date}.jsonl"))
            except FileNotFoundError:
                source_path = None
    rows = payload.get("games") if isinstance((payload or {}).get("games"), list) else []
    games: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        away_tri = _canonical_nba_tri(str(row.get("away") or "").strip().upper())
        home_tri = _canonical_nba_tri(str(row.get("home") or "").strip().upper())
        if not away_tri or not home_tri:
            continue
        away_pts = _safe_float(row.get("away_pts"))
        home_pts = _safe_float(row.get("home_pts"))
        total_mean = (away_pts + home_pts) if away_pts is not None and home_pts is not None else None
        margin_mean = (home_pts - away_pts) if away_pts is not None and home_pts is not None else None
        normalized_status = _normalized_game_status(
            status_text=row.get("status"),
            detail_text=row.get("status"),
            start_time_utc=row.get("commence_time") or row.get("start_time") or row.get("game_date") or row.get("status"),
            in_progress=row.get("in_progress"),
            final=row.get("final"),
            away_pts=away_pts,
            home_pts=home_pts,
        )
        games.append(
            {
                "gamePk": str(row.get("game_id") or f"{away_tri}@{home_tri}"),
                "event_id": row.get("event_id"),
                "game_id": str(row.get("game_id") or f"{away_tri}@{home_tri}"),
                "away_tri": away_tri,
                "away_name": away_tri,
                "home_tri": home_tri,
                "home_name": home_tri,
                "away_logo": _nba_logo_url(away_tri),
                "home_logo": _nba_logo_url(home_tri),
                "away": {
                    "abbr": away_tri,
                    "name": away_tri,
                    "logo": _nba_logo_url(away_tri),
                    "primary_color": _nba_primary_color(away_tri),
                    "secondary_color": _nba_secondary_color(away_tri),
                },
                "home": {
                    "abbr": home_tri,
                    "name": home_tri,
                    "logo": _nba_logo_url(home_tri),
                    "primary_color": _nba_primary_color(home_tri),
                    "secondary_color": _nba_secondary_color(home_tri),
                },
                "status": normalized_status["status"],
                "detail": normalized_status["detail"],
                "summary": "Live scoreboard fallback",
                "gameType": "Live",
                "betting": {},
                "prop_recommendations": {"away": [], "home": []},
                "live_state": {
                    **dict(row),
                    "in_progress": bool(normalized_status["in_progress"]),
                    "final": bool(normalized_status["final"]),
                    "status": normalized_status["detail"],
                },
                "sim": {
                    "game_id": str(row.get("game_id") or f"{away_tri}@{home_tri}"),
                    "score": {
                        "away_mean": away_pts,
                        "home_mean": home_pts,
                        "total_mean": total_mean,
                        "margin_mean": margin_mean,
                    },
                    "market": {},
                    "players_summary": {
                        "away": 0,
                        "home": 0,
                        "missing_away": 0,
                        "missing_home": 0,
                        "injured_away": 0,
                        "injured_home": 0,
                    },
                    "players": {"away": [], "home": []},
                    "missing_prop_players": {"away": [], "home": []},
                    "injuries": {"away": [], "home": []},
                },
            }
        )
    return games, str(source_path or f"live_state_{selected_date}.jsonl")


def _game_identity_key(game: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(game, dict):
        return ("", "", "")
    event_id = str(game.get("event_id") or "").strip()
    away_tri = _canonical_nba_tri(
        str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "") or "").strip().upper()
    )
    home_tri = _canonical_nba_tri(
        str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "") or "").strip().upper()
    )
    return (event_id, away_tri, home_tri)


def _game_matchup_key(game: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(game, dict):
        return ("", "")
    away_tri = _canonical_nba_tri(
        str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "") or "").strip().upper()
    )
    home_tri = _canonical_nba_tri(
        str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "") or "").strip().upper()
    )
    return (away_tri, home_tri)


def _merge_games_with_live_state(games: list[dict[str, Any]], selected_date: str) -> tuple[list[dict[str, Any]], str | None, int, int]:
    live_games, live_source_path = _games_from_live_state_fallback(selected_date)
    if not live_games:
        return games, None, 0, 0

    live_by_key = {
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
        key = _game_identity_key(game)
        matchup = _game_matchup_key(game)
        seen_keys.add(key)
        seen_matchups.add(matchup)
        live_game = live_by_key.get(key)
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

        live_status = str(live_game.get("status") or "").strip()
        live_detail = str(live_game.get("detail") or live_status).strip()
        if live_status:
            merged["status"] = live_status
            merged["detail"] = live_detail

        updated_count += 1
        merged_games.append(merged)

    extras = [
        game
        for key, game in live_by_key.items()
        if key not in seen_keys and _game_matchup_key(game) not in seen_matchups
    ]
    if extras:
        merged_games.extend(extras)

    return merged_games, live_source_path, len(extras), updated_count


@lru_cache(maxsize=256)
def _local_live_snapshot_payload_cached(kind: str, resolved_date: str, signature: int) -> dict[str, Any] | None:
    if not resolved_date:
        return None
    try:
        path = live_snapshot_path(f"{kind}_{resolved_date}.jsonl")
    except FileNotFoundError:
        return None
    return _read_live_snapshot_jsonl_payload(path)


def _local_live_snapshot_payload(kind: str, selected_date: str) -> dict[str, Any] | None:
    resolved_date = str(selected_date or "").strip()
    if not resolved_date:
        return None
    try:
        path = live_snapshot_path(f"{kind}_{resolved_date}.jsonl")
    except FileNotFoundError:
        return _local_live_snapshot_payload_cached(kind, resolved_date, 0)
    return _local_live_snapshot_payload_cached(kind, resolved_date, _live_snapshot_or_state_signature(path))


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


def _artifact_processed_root(selected_date: str) -> Path:
    return processed_path(f"game_cards_{selected_date}.csv").parent


def _artifact_live_player_lens_payload(
    selected_date: str,
    event_ids: list[str],
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any] | None:
    event_games = _resolve_games_for_event_ids(
        selected_date,
        event_ids,
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
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
    event_games = _resolve_games_for_event_ids(
        selected_date,
        event_ids,
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
    if not event_games:
        return None
    return build_live_lines_payload_from_artifacts(
        processed_root=_artifact_processed_root(selected_date),
        date_str=selected_date,
        event_games=event_games,
        include_period_totals=bool(include_period_totals),
        source="syndicate_live_lens_signals_artifact",
    )


def _attach_odds_refresh_timestamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    timestamp = str(out.get("odds_refreshed_at") or out.get("generated_at") or "").strip()
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
    out.setdefault("generated_at", timestamp)
    return out


def _payload_has_live_boxscore_players(payload: dict[str, Any] | None) -> bool:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    return any(
        isinstance(game, dict) and isinstance(game.get("players"), list) and bool(game.get("players"))
        for game in games
    )


def _default_live_event_ids(selected_date: str, *, allow_stored_date_fallback: bool = True) -> list[str]:
    is_current_date = str(selected_date).strip() == central_today_iso()
    live_payload = build_live_state_payload(
        selected_date,
        ttl=12,
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
    games = live_payload.get("games") if isinstance(live_payload, dict) else []
    event_ids: list[str] = []
    historical_event_ids: list[str] = []
    for game in games if isinstance(games, list) else []:
        if not isinstance(game, dict):
            continue
        event_id = str(game.get("event_id") or "").strip()
        if not event_id:
            continue
        if bool(game.get("in_progress")) and not bool(game.get("final")):
            event_ids.append(event_id)
        elif not is_current_date:
            historical_event_ids.append(event_id)
    if event_ids:
        return list(dict.fromkeys(event_ids))
    if historical_event_ids:
        return list(dict.fromkeys(historical_event_ids))

    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    context_games = context.get("games") if isinstance(context.get("games"), list) else []
    historical_context_event_ids: list[str] = []
    for game in context_games:
        if not isinstance(game, dict):
            continue
        status = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
        event_id = str(game.get("event_id") or "").strip()
        if event_id and bool(status.get("in_progress")) and not bool(status.get("final")):
            event_ids.append(event_id)
        elif event_id and not is_current_date:
            historical_context_event_ids.append(event_id)
    if event_ids:
        return list(dict.fromkeys(event_ids))
    return list(dict.fromkeys(historical_context_event_ids))


def _public_live_player_boxscore_payload(selected_date: str, event_ids: list[str]) -> dict[str, Any] | None:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    if not normalized_event_ids:
        return None

    out_games: list[dict[str, Any]] = []
    for event_id in normalized_event_ids:
        request_url = (
            "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
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
            team_tri = _canonical_nba_tri(
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
                        if not key or idx >= len(stat_values):
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
                    steals = _safe_float(_first_stat("STL", "STEALS"))
                    blocks = _safe_float(_first_stat("BLK", "BLOCKS"))
                    turnovers = _safe_float(_first_stat("TO", "TOV", "TURNOVERS"))
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
                            threes_made = _safe_float(threes_text.split("-", 1)[0].strip())

                    has_box_stats = any(
                        value is not None
                        for value in (points, rebounds, assists, steals, blocks, turnovers, threes_made)
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
                            "stl": steals,
                            "blk": blocks,
                            "tov": turnovers,
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
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def _fallback_live_player_boxscore_game(
    game: dict[str, Any],
    *,
    event_id: str | None = None,
    selected_date: str | None = None,
) -> dict[str, Any]:
    return {"event_id": event_id or game.get("event_id"), "players": []}


def _normalize_player_key(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9\s]", " ", str(value or "").upper())).strip()


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
    processed_root = processed_path("game_cards_2000-01-01.csv").parent
    stat_samples: dict[str, list[float]] = {}
    player_stat_samples: dict[tuple[str, str], list[float]] = {}
    for path in processed_root.glob("live_player_lens_tuning_*.csv"):
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
    if key == "pra":
        return None if pts is None or reb is None or ast is None else round(pts + reb + ast, 3)
    if key == "pr":
        return None if pts is None or reb is None else round(pts + reb, 3)
    if key == "pa":
        return None if pts is None or ast is None else round(pts + ast, 3)
    if key == "ra":
        return None if reb is None or ast is None else round(reb + ast, 3)
    return {
        "pts": pts,
        "reb": reb,
        "ast": ast,
        "threes": _safe_float(player_row.get("threes_made")),
        "stl": _safe_float(player_row.get("stl")),
        "blk": _safe_float(player_row.get("blk")),
        "tov": _safe_float(player_row.get("tov")),
    }.get(key)


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
        "status": _normalized_game_status(
            status_text=game.get("status"),
            detail_text=game.get("detail"),
            start_time_utc=game.get("start_time") or ((game.get("odds") or {}).get("commence_time") if isinstance(game.get("odds"), dict) else None),
            in_progress=((game.get("live_state") or {}).get("in_progress") if isinstance(game.get("live_state"), dict) else False),
            final=((game.get("live_state") or {}).get("final") if isinstance(game.get("live_state"), dict) else False),
            away_pts=((game.get("away") or {}).get("score") if isinstance(game.get("away"), dict) else None),
            home_pts=((game.get("home") or {}).get("score") if isinstance(game.get("home"), dict) else None),
        ),
        "rows": rows,
    }


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


def _fallback_live_lines_game(game: dict[str, Any], *, include_period_totals: bool) -> dict[str, Any]:
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    return {
        "event_id": game.get("event_id"),
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


def _resolve_games_for_event_ids(selected_date: str, event_ids: list[str], *, allow_stored_date_fallback: bool = True) -> dict[str, dict[str, Any]]:
    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    context_games = context.get("games") if isinstance(context.get("games"), list) else []
    games_by_matchup: dict[tuple[str, str], dict[str, Any]] = {}
    for game in context_games:
        if not isinstance(game, dict):
            continue
        away_tri = _canonical_nba_tri(
            str(
                game.get("away_tri")
                or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")
                or ""
            ).strip().upper()
        )
        home_tri = _canonical_nba_tri(
            str(
                game.get("home_tri")
                or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")
                or ""
            ).strip().upper()
        )
        if away_tri and home_tri:
            games_by_matchup[(away_tri, home_tri)] = game

    live_state = build_live_state_payload(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    by_event: dict[str, dict[str, Any]] = {}
    for live_game in (live_state.get("games") if isinstance(live_state.get("games"), list) else []):
        if not isinstance(live_game, dict):
            continue
        event_id = str(live_game.get("event_id") or "").strip()
        away_tri = _canonical_nba_tri(str(live_game.get("away") or "").strip().upper())
        home_tri = _canonical_nba_tri(str(live_game.get("home") or "").strip().upper())
        if event_id and away_tri and home_tri:
            matched_game = games_by_matchup.get((away_tri, home_tri))
            if isinstance(matched_game, dict):
                by_event[event_id] = matched_game
    return by_event


_NBA_REGULATION_MINUTES = 48.0

# Per-game standard deviations for a rotation player's counting stats.
# Ported from syndicate/features/wnba/cards.py's _WNBA_LIVE_PROP_SIGMA_BASE
# and scaled up for NBA's longer game (48 min vs 40) and higher scoring
# environment. Like the WNBA numbers these are a principled starting point,
# NOT backtested against real NBA outcomes -- revisit once the settlement
# pipeline has graded enough live NBA props to calibrate against. Do not
# copy these into a third sport without doing the same reasoning.
_NBA_LIVE_PROP_SIGMA_BASE: dict[str, float] = {
    "pts": 9.0,
    "reb": 3.5,
    "ast": 3.0,
    "threes": 1.5,
    "pra": 11.0,
    "stl": 1.3,
    "blk": 1.3,
    "tov": 1.6,
}

_NBA_LIVE_PROP_SIGMA_COMBOS: dict[str, tuple[str, ...]] = {
    "pr": ("pts", "reb"),
    "pa": ("pts", "ast"),
    "ra": ("reb", "ast"),
}


def _nba_live_prop_sigma_for_stat(stat_key: Any) -> float | None:
    key = str(stat_key or "").strip().lower()
    if not key:
        return None
    direct = _NBA_LIVE_PROP_SIGMA_BASE.get(key)
    if direct is not None:
        return direct
    parts = _NBA_LIVE_PROP_SIGMA_COMBOS.get(key)
    if not parts:
        return None
    # Independent-sum approximation, matching how basketball_props_edges
    # derives its own pr/pa/ra sigmas.
    return math.sqrt(sum(_NBA_LIVE_PROP_SIGMA_BASE[part] ** 2 for part in parts))


def _nba_normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _nba_elapsed_minutes(period: Any, clock: Any) -> float | None:
    """Total elapsed game minutes. NBA quarters are 12 minutes (regulation
    48, not WNBA's 40); OT periods are 5 minutes each."""
    period_value = _safe_float(period)
    if period_value is None:
        return None
    period_int = int(period_value)
    if period_int <= 0:
        return None
    clock_text = _normalize_status_clock_text(clock)
    period_length = 12.0 if period_int <= 4 else 5.0
    remaining_in_period = None
    if clock_text:
        parts = clock_text.split(":")
        try:
            if len(parts) == 2:
                remaining_in_period = float(parts[0]) + (float(parts[1]) / 60.0)
            elif len(parts) == 1 and parts[0]:
                remaining_in_period = float(parts[0]) / 60.0
        except (TypeError, ValueError):
            remaining_in_period = None
    elapsed_in_period = period_length if remaining_in_period is None else max(0.0, period_length - remaining_in_period)
    prior_minutes = (period_int - 1) * 12.0 if period_int <= 4 else (4 * 12.0 + (period_int - 5) * 5.0)
    return prior_minutes + elapsed_in_period


def _nba_live_prop_over_probability(
    live_projection: Any,
    line_value: Any,
    stat_key: Any,
    minutes_remaining: float | None,
) -> tuple[float | None, float | None]:
    """Real P(final > line) for a live NBA player prop, plus the live sigma.

    Direct port of the WNBA fix. The NBA live path had the identical defect:
    `live_edge` is a raw projection-minus-line difference and `win_prob`
    stayed at its stale pregame value, so any probability derived from the
    live projection saturated to 0/1 the moment the projection sat either
    side of the line -- regardless of how much game was left to play.

    A counting stat's variance accumulates with playing time, so the
    remaining-game standard deviation scales with sqrt(minutes remaining /
    regulation): full sigma at tip-off, shrinking toward zero at the final
    buzzer.
    """
    projection = _safe_float(live_projection)
    line = _safe_float(line_value)
    if projection is None or line is None:
        return None, None
    base_sigma = _nba_live_prop_sigma_for_stat(stat_key)
    if base_sigma is None or base_sigma <= 0:
        return None, None
    remaining = _safe_float(minutes_remaining)
    if remaining is None:
        remaining = _NBA_REGULATION_MINUTES
    remaining = max(0.0, min(_NBA_REGULATION_MINUTES, remaining))
    live_sigma = base_sigma * math.sqrt(remaining / _NBA_REGULATION_MINUTES)
    if live_sigma <= 1e-6:
        # No time left -- the projection is the outcome.
        return (1.0 if projection > line else 0.0), 0.0
    return _nba_normal_cdf((projection - line) / live_sigma), round(live_sigma, 3)


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
        str(game.get("event_id") or "").strip(): dict(game.get("status") or {})
        for game in (live_state_payload.get("games") if isinstance(live_state_payload.get("games"), list) else [])
        if isinstance(game, dict)
        and str(game.get("event_id") or "").strip()
        and isinstance(game.get("status"), dict)
    }

    hydrated_games: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            hydrated_games.append(game)
            continue
        event_id = str(game.get("event_id") or "").strip()
        actual_rows = boxscore_by_event.get(event_id) or {}
        hydrated_game = dict(game)
        live_status = live_state_by_event.get(event_id)
        if isinstance(live_status, dict) and live_status:
            hydrated_game["status"] = dict(live_status)
        game_status = game.get("status") if isinstance(game.get("status"), dict) else {}
        if isinstance(live_status, dict) and live_status:
            game_status = dict(live_status)
        game_explicitly_not_live = bool(game_status) and not bool(game_status.get("in_progress"))
        game_is_in_progress = bool(game_status.get("in_progress"))
        game_elapsed_minutes = _nba_elapsed_minutes(game_status.get("period"), game_status.get("clock"))
        live_minutes_remaining = (
            max(0.0, _NBA_REGULATION_MINUTES - game_elapsed_minutes) if game_elapsed_minutes is not None else None
        )
        rows = []
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
                        if game_is_in_progress:
                            over_probability, live_sigma = _nba_live_prop_over_probability(
                                live_projection,
                                line_value,
                                hydrated_row.get("stat") or hydrated_row.get("market"),
                                live_minutes_remaining,
                            )
                            if over_probability is not None:
                                side_text = str(hydrated_row.get("ev_side") or hydrated_row.get("lean") or "").strip().upper()
                                side_probability = (1.0 - over_probability) if side_text == "UNDER" else over_probability
                                hydrated_row["live_over_probability"] = round(over_probability, 4)
                                hydrated_row["live_win_prob"] = round(side_probability, 4)
                                hydrated_row["live_sigma"] = live_sigma
                                # Override the stale pregame win_prob -- every
                                # downstream live-prop consumer (home.py's
                                # _prop_rows_from_nba_live_lens, and through it
                                # the Layer 2 candidate builder) reads win_prob,
                                # and a pregame probability pinned to a live
                                # projection is what produced the saturated
                                # board values on the WNBA side.
                                hydrated_row["win_prob"] = round(side_probability, 4)
                                hydrated_row["live_probability_source"] = "live_sigma_normal"
                    if existing_live_projection is None:
                        hydrated_row["line_source"] = str(hydrated_row.get("line_source") or "boxscore_sim_fallback").strip() or "boxscore_sim_fallback"
            status_period_value = _safe_float(game_status.get("period"))
            status_period = int(status_period_value) if status_period_value is not None else None
            status_clock = str(game_status.get("clock") or "").strip()
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
            rows.append(hydrated_row)
        hydrated_game["rows"] = rows
        hydrated_games.append(hydrated_game)

    hydrated_payload = dict(payload)
    hydrated_payload["games"] = hydrated_games
    return hydrated_payload


def _normalize_source_game(game: dict[str, Any], *, idx: int, selected_date: str) -> dict[str, Any]:
    away_tri = str(game.get("away_tri") or "AWY").strip().upper() or "AWY"
    home_tri = str(game.get("home_tri") or "HOM").strip().upper() or "HOM"
    away_name = str(game.get("away_name") or away_tri).strip() or away_tri
    home_name = str(game.get("home_name") or home_tri).strip() or home_tri
    game_id = str((_sim_payload(game).get("game_id") or idx)).strip()
    betting = dict(game.get("betting") or {}) if isinstance(game.get("betting"), dict) else {}
    odds = dict(game.get("odds") or {}) if isinstance(game.get("odds"), dict) else {}
    sim = _sim_payload(game)
    props = dict(game.get("prop_recommendations") or {}) if isinstance(game.get("prop_recommendations"), dict) else {"away": [], "home": []}
    game_recs = [row for row in (game.get("game_market_recommendations") or []) if isinstance(row, dict)]
    score = sim.get("score") if isinstance(sim.get("score"), dict) else {}
    return {
        **game,
        "gamePk": game_id,
        "away_tri": away_tri,
        "away_name": away_name,
        "home_tri": home_tri,
        "home_name": home_name,
        "away_logo": _nba_logo_url(away_tri),
        "home_logo": _nba_logo_url(home_tri),
        "away": {
            "abbr": away_tri,
            "name": away_name,
            "logo": _nba_logo_url(away_tri),
            "primary_color": _nba_primary_color(away_tri),
            "secondary_color": _nba_secondary_color(away_tri),
        },
        "home": {
            "abbr": home_tri,
            "name": home_name,
            "logo": _nba_logo_url(home_tri),
            "primary_color": _nba_primary_color(home_tri),
            "secondary_color": _nba_secondary_color(home_tri),
        },
        "status": str(game.get("live_status") or game.get("date") or "Source API").strip() or "Source API",
        "detail": str(game.get("date") or game.get("live_status") or "Scheduled").strip() or "Scheduled",
        "summary": str(game.get("writeup") or "Source API snapshot").strip() or "Source API snapshot",
        "gameType": "NBA",
        "odds": odds,
        "betting": betting,
        "sim": sim,
        "prop_recommendations": {
            "away": props.get("away") if isinstance(props.get("away"), list) else [],
            "home": props.get("home") if isinstance(props.get("home"), list) else [],
        },
        "game_market_recommendations": game_recs,
        "metrics": [
            {"label": "Away pts", "value": format_num(score.get("away_mean"))},
            {"label": "Home pts", "value": format_num(score.get("home_mean"))},
            {"label": "Away win", "value": _format_pct_100((_safe_float(betting.get("p_away_win")) or 0.0) * 100)},
            {"label": "Home win", "value": _format_pct_100((_safe_float(betting.get("p_home_win")) or 0.0) * 100)},
        ],
        "href": f"/nba/game/{game_id}?date={selected_date}",
        "href_label": "Open NBA game",
    }


def _game_by_id_from_artifacts(selected_date: str, game_pk: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    bundle = _artifact_bundle(selected_date)
    rows = bundle["rows"]
    rec_index = bundle["recommendations"]
    sim_index = bundle["sim"]
    props_index = bundle["props"]
    target = str(game_pk).strip()
    for idx, row in enumerate(rows, start=1):
        current_id = str(row.get("game_id") or idx).strip()
        if current_id != target:
            continue
        return (
            _game_from_row(
                row,
                idx=idx,
                selected_date=selected_date,
                rec_index=rec_index,
                sim_index=sim_index,
                props_index=props_index,
            ),
            bundle,
        )
    return None, bundle


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
    away_tri = str(row.get("away_tri") or away_name[:3]).strip().upper() or "AWY"
    home_tri = str(row.get("home_tri") or home_name[:3]).strip().upper() or "HOM"
    picks = rec_index.get((home_tri, away_tri), [])
    sim_game = sim_index.get((home_tri, away_tri))
    props_game = props_index.get((home_tri, away_tri))
    top_picks, pick_rows = _top_pick_items(picks)
    sim_groups, sim_stats = _sim_table_groups(sim_game, away_tri, home_tri)
    props_groups, prop_items = _props_table_groups(props_game, away_tri, home_tri)
    game_id = str(row.get("game_id") or idx)
    home_ml = _safe_float(row.get("home_ml"))
    away_ml = _safe_float(row.get("away_ml"))
    home_spread = _safe_float(row.get("home_spread"))
    away_spread = _safe_float(row.get("away_spread"))
    total = _safe_float(row.get("total"))
    home_spread_price = _safe_float(row.get("home_spread_price"))
    away_spread_price = _safe_float(row.get("away_spread_price"))
    total_over_price = _safe_float(row.get("total_over_price"))
    total_under_price = _safe_float(row.get("total_under_price"))
    sim_payload = _sim_payload(sim_game)
    score_payload = sim_payload.get("score") if isinstance(sim_payload.get("score"), dict) else {}
    # Model margin/total means: the sim detail's score payload first, then the
    # pred_margin/pred_total game_cards columns (written by
    # refresh_nba_oddsapi_props.py since 2026-08-02). Never the market line --
    # a probability derived from the book's own line is the book's own price.
    margin_hint = _safe_float(score_payload.get("margin_mean"))
    if margin_hint is None:
        margin_hint = _safe_float(row.get("pred_margin"))
    total_hint = _safe_float(score_payload.get("total_mean"))
    if total_hint is None:
        total_hint = _safe_float(row.get("pred_total"))
    # Sim-margin probability must outrank the market-implied one (same bug
    # class fixed in wnba/cards.py's _source_betting, 2026-08-02): the old
    # derivation used _implied_prob_from_american(home_ml) unconditionally, so
    # whenever a book moneyline existed the "model" probability WAS the book's
    # own vig-inclusive price and every edge computed from it was structurally
    # zero. Market-implied stays as the last resort only, for rows with no sim
    # projection at all.
    sim_home_win_prob = _margin_win_prob(margin_hint, scale=6.5) if margin_hint is not None else None
    if sim_home_win_prob is not None:
        p_home_win, p_away_win = sim_home_win_prob, 1.0 - sim_home_win_prob
    else:
        p_home_win, p_away_win = _normalize_two_way(
            _implied_prob_from_american(home_ml),
            _implied_prob_from_american(away_ml),
        )
    p_home_cover = _margin_win_prob(margin_hint + home_spread, scale=7.5) if margin_hint is not None and home_spread is not None else None
    p_total_over = _margin_win_prob(total_hint - total, scale=10.5) if total_hint is not None and total is not None else None
    market_home_margin = -home_spread if home_spread is not None else None
    home_score_mean = ((total + market_home_margin) / 2.0) if total is not None and market_home_margin is not None else None
    away_score_mean = ((total - market_home_margin) / 2.0) if total is not None and market_home_margin is not None else None
    segment_total = (total / 4.0) if total is not None else None
    segment_margin = (market_home_margin / 4.0) if market_home_margin is not None else None
    props_payload = props_game.get("prop_recommendations") if isinstance(props_game, dict) and isinstance(props_game.get("prop_recommendations"), dict) else (
        props_game if isinstance(props_game, dict) else {}
    )
    market_payload = sim_payload.get("market") if isinstance(sim_payload.get("market"), dict) else {}
    context_payload = sim_payload.get("context") if isinstance(sim_payload.get("context"), dict) else {}
    periods_payload = sim_payload.get("periods") if isinstance(sim_payload.get("periods"), dict) else {}
    players_payload = sim_payload.get("players") if isinstance(sim_payload.get("players"), dict) else {"away": [], "home": []}
    missing_players_payload = sim_payload.get("missing_prop_players") if isinstance(sim_payload.get("missing_prop_players"), dict) else {"away": [], "home": []}
    injuries_payload = sim_payload.get("injuries") if isinstance(sim_payload.get("injuries"), dict) else {"away": [], "home": []}
    players_summary_payload = sim_payload.get("players_summary") if isinstance(sim_payload.get("players_summary"), dict) else {}
    periods = {
        "q1": periods_payload.get("q1") if isinstance(periods_payload.get("q1"), dict) else _default_segment(segment_total, segment_margin, p_home_win),
        "q2": periods_payload.get("q2") if isinstance(periods_payload.get("q2"), dict) else _default_segment(segment_total, segment_margin, p_home_win),
        "q3": periods_payload.get("q3") if isinstance(periods_payload.get("q3"), dict) else _default_segment(segment_total, segment_margin, p_home_win),
        "q4": periods_payload.get("q4") if isinstance(periods_payload.get("q4"), dict) else _default_segment(segment_total, segment_margin, p_home_win),
    }

    normalized_status = _normalized_game_status(
        status_text=row.get("status"),
        detail_text=row.get("commence_time"),
        start_time_utc=row.get("commence_time"),
        in_progress=row.get("in_progress"),
        final=row.get("final"),
    )
    return {
        "gamePk": game_id,
        "event_id": row.get("event_id"),
        "away_tri": away_tri,
        "away_name": away_name,
        "home_tri": home_tri,
        "home_name": home_name,
        "away_logo": _nba_logo_url(away_tri),
        "home_logo": _nba_logo_url(home_tri),
        "away": {
            "abbr": away_tri,
            "name": away_name,
            "logo": _nba_logo_url(away_tri),
            "primary_color": _nba_primary_color(away_tri),
            "secondary_color": _nba_secondary_color(away_tri),
        },
        "home": {
            "abbr": home_tri,
            "name": home_name,
            "logo": _nba_logo_url(home_tri),
            "primary_color": _nba_primary_color(home_tri),
            "secondary_color": _nba_secondary_color(home_tri),
        },
        "status": normalized_status["status"],
        "detail": normalized_status["detail"],
        "summary": f"{row.get('bookmaker') or 'Consensus'} market snapshot",
        "gameType": "NBA",
        "odds": {
            "commence_time": str(row.get("commence_time") or "").strip() or None,
            "bookmaker": str(row.get("bookmaker") or "").strip() or None,
        },
        "betting": {
            "home_ml": home_ml,
            "away_ml": away_ml,
            "home_spread": home_spread,
            "away_spread": away_spread,
            "home_spread_price": home_spread_price,
            "away_spread_price": away_spread_price,
            "total": total,
            "total_over_price": total_over_price,
            "total_under_price": total_under_price,
            "p_home_win": p_home_win,
            "p_away_win": p_away_win,
            # Sim-derived when a model margin/total exists; None (not a
            # fabricated coin-flip 0.5) otherwise, matching wnba/cards.py's
            # _source_betting so basketball_market_board drops the row instead
            # of scoring a structurally zero edge.
            "p_home_cover": p_home_cover,
            "p_away_cover": (1.0 - p_home_cover) if p_home_cover is not None else None,
            "p_total_over": p_total_over,
            "p_total_under": (1.0 - p_total_over) if p_total_over is not None else None,
            "home_ml_ev": 0.0,
            "away_ml_ev": 0.0,
            "home_spread_ev": 0.0,
            "away_spread_ev": 0.0,
            "over_ev": 0.0,
            "under_ev": 0.0,
        },
        "sim": {
            "game_id": game_id,
            "score": {
                "away_mean": score_payload.get("away_mean", away_score_mean),
                "home_mean": score_payload.get("home_mean", home_score_mean),
                "total_mean": score_payload.get("total_mean", total),
                "margin_mean": score_payload.get("margin_mean", market_home_margin),
            },
            "market": {
                "market_home_spread": market_payload.get("market_home_spread", home_spread),
            },
            "context": {
                "away_pace": context_payload.get("away_pace", 99.0),
                "home_pace": context_payload.get("home_pace", 99.0),
            },
            "periods": periods,
            "players": players_payload,
            "missing_prop_players": missing_players_payload,
            "injuries": injuries_payload,
            "players_summary": {
                "away": players_summary_payload.get("away", len(players_payload.get("away") or [])),
                "home": players_summary_payload.get("home", len(players_payload.get("home") or [])),
                "missing_away": players_summary_payload.get("missing_away", len(missing_players_payload.get("away") or [])),
                "missing_home": players_summary_payload.get("missing_home", len(missing_players_payload.get("home") or [])),
                "injured_away": players_summary_payload.get("injured_away", len(injuries_payload.get("away") or [])),
                "injured_home": players_summary_payload.get("injured_home", len(injuries_payload.get("home") or [])),
            },
        },
        "prop_recommendations": {
            "away": props_payload.get("away") if isinstance(props_payload.get("away"), list) else [],
            "home": props_payload.get("home") if isinstance(props_payload.get("home"), list) else [],
        },
        "live_state": {
            "in_progress": bool(normalized_status["in_progress"]),
            "final": bool(normalized_status["final"]),
            "status": normalized_status["detail"],
        },
        "game_market_recommendations": [],
        "metrics": [
            {"label": "Away ML", "value": format_moneyline(row.get("away_ml"))},
            {"label": "Home ML", "value": format_moneyline(row.get("home_ml"))},
            {"label": "Spread", "value": f"{home_tri} {format_signed_num(row.get('home_spread'))}"},
            {"label": "Total", "value": format_num(row.get("total"))},
            {"label": "Books", "value": str(row.get("books_count") or "-")},
            {"label": "Tip win", "value": format_num(float(row.get("prob_home_tip") or 0) * 100) + "%"},
            {"label": "Early 3s", "value": _format_pct_100((_safe_float(row.get("early_threes_prob_ge_1")) or 0.0) * 100)},
        ],
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
                "body": "Top picks are pulled from the processed NBA recommendation slate artifact.",
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
                "body": "Cards props snapshots surface the strongest team-side recommendations saved for the board when available.",
                "table_groups": props_groups or None,
                "items": prop_items or ["No props snapshot was linked for this matchup."],
            },
        ],
        "href": f"/nba/game/{game_id}?date={selected_date}",
        "href_label": "Open NBA game",
    }

def _payload_games_by_event_id(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    by_event: dict[str, dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        event_id = str(game.get("event_id") or "").strip()
        if event_id:
            by_event[event_id] = game
    return by_event


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
    return games, str(bundle["paths"]["cards"]), str(bundle["paths"]["recommendations"])


def _game_has_actionable_data(game: dict[str, Any]) -> bool:
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    sim_score = (_sim_payload(game).get("score") or {})
    game_recs = game.get("game_market_recommendations") if isinstance(game.get("game_market_recommendations"), list) else []
    prop_recs = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}

    has_market = any(betting.get(key) is not None for key in ("home_ml", "away_ml", "home_spread", "total"))
    has_sim = any(sim_score.get(key) is not None for key in ("away_mean", "home_mean", "total_mean", "margin_mean"))
    has_game_recs = bool(game_recs)
    has_prop_recs = bool(prop_recs.get("away")) or bool(prop_recs.get("home"))
    return bool(has_market or has_sim or has_game_recs or has_prop_recs)


def _games_have_actionable_data(games: list[dict[str, Any]]) -> bool:
    return any(_game_has_actionable_data(game) for game in games if isinstance(game, dict))


def _next_available_actionable_cards_date(selected_date: str, *, max_days: int = 30) -> str | None:
    parsed_date = parse_iso_date(selected_date)
    for offset in range(1, max_days + 1):
        candidate = (parsed_date + timedelta(days=offset)).isoformat()
        games, _, _ = _games_from_artifacts(candidate)
        if games and _games_have_actionable_data(games):
            return candidate
    for offset in range(1, max_days + 1):
        candidate = (parsed_date - timedelta(days=offset)).isoformat()
        games, _, _ = _games_from_artifacts(candidate)
        if games and _games_have_actionable_data(games):
            return candidate
    return None


def build_cards_page_context(selected_date: str, *, allow_stored_date_fallback: bool = False) -> dict[str, Any]:
    requested_date = str(selected_date or "").strip() or parse_iso_date(selected_date).isoformat()
    cache_key = (
        requested_date,
        bool(allow_stored_date_fallback),
        tuple(available_dates()),
        _path_cache_signature(_artifact_paths(requested_date)["cards"]),
        _path_cache_signature(_artifact_paths(requested_date)["recommendations"]),
        _path_cache_signature(_artifact_paths(requested_date)["sim"]),
        _path_cache_signature(_artifact_paths(requested_date)["props"]),
        _live_snapshot_or_state_signature(live_snapshot_path(f"live_state_{requested_date}.jsonl")),
    )
    cached_context = _cache_get_context(cache_key)
    if cached_context is not None:
        return deepcopy(cached_context)

    resolved_date = requested_date
    source_title = "NBA processed game cards"
    parsed_date = parse_iso_date(resolved_date)
    games, cards_path, recs_path = _games_from_artifacts(resolved_date)
    had_artifact_games = bool(games)
    if not _render_web_dyno():
        games, live_source_path, supplemented_count, updated_count = _merge_games_with_live_state(games, resolved_date)
        if supplemented_count > 0 or updated_count > 0:
            if had_artifact_games:
                source_title = "NBA processed game cards + live scoreboard supplement"
                cards_path = f"{cards_path} | {live_source_path}"
            else:
                source_title = "NBA live scoreboard fallback"
                cards_path = str(live_source_path)
                recs_path = str(live_source_path)
    has_actionable_data = _games_have_actionable_data(games)

    if not _render_web_dyno() and not games and resolved_date == central_today_iso():
        live_games, live_source_path = _games_from_live_state_fallback(resolved_date)
        if live_games:
            games = live_games
            cards_path = live_source_path
            recs_path = live_source_path
            source_title = "NBA live scoreboard fallback"
            has_actionable_data = _games_have_actionable_data(games)

    # Prefer nearby local artifact-backed slates before any live/remote fallback.
    if not _render_web_dyno() and allow_stored_date_fallback and (not games or not has_actionable_data):
        fallback_date = None
        if games and not has_actionable_data:
            fallback_date = _next_available_actionable_cards_date(resolved_date)
        if not fallback_date:
            fallback_date = _next_available_cards_date(resolved_date, max_ahead_days=30)
        if isinstance(fallback_date, str) and fallback_date and fallback_date != resolved_date:
            resolved_date = fallback_date
            parsed_date = parse_iso_date(resolved_date)
            games, cards_path, recs_path = _games_from_artifacts(resolved_date)
            source_title = "NBA processed game cards"
            had_artifact_games = bool(games)
            games, live_source_path, supplemented_count, updated_count = _merge_games_with_live_state(games, resolved_date)
            if supplemented_count > 0 or updated_count > 0:
                if had_artifact_games:
                    source_title = "NBA processed game cards + live scoreboard supplement"
                    cards_path = f"{cards_path} | {live_source_path}"
                else:
                    source_title = "NBA live scoreboard fallback"
                    cards_path = str(live_source_path)
                    recs_path = str(live_source_path)
            has_actionable_data = _games_have_actionable_data(games)
            if not games and resolved_date == central_today_iso():
                live_games, live_source_path = _games_from_live_state_fallback(resolved_date)
                if live_games:
                    games = live_games
                    cards_path = live_source_path
                    recs_path = live_source_path
                    source_title = "NBA live scoreboard fallback"
                    has_actionable_data = _games_have_actionable_data(games)

    has_games_on_slate = bool(games)

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

    context = {
        "date": resolved_date,
        "requested_date": requested_date,
        "lookahead_applied": bool(resolved_date != requested_date),
        "has_games_on_slate": has_games_on_slate,
        "prev_date": prev_date,
        "next_date": next_date,
        "games": games,
        "scoreboard_items": scoreboard_items,
        "using_sample_data": using_sample_data,
        "source_path": cards_path,
        "source_title": source_title if games else "NBA cards unavailable",
        "empty_state": {
            "eyebrow": "NBA cards",
            "title": "No NBA games are scheduled for this date",
            "body": "No local processed or live artifacts were available for this date.",
            "list_items": [
                f"Requested date: {requested_date}",
                "Choose another NBA date from the date control if you want a different stored slate.",
            ],
        } if not games else None,
        "header_stats": [
            {"label": "Games", "value": str(len(games))},
            {"label": "Recommendations", "value": recs_path.split("\\")[-1] if games else "No data"},
            *([
                {"label": "Data", "value": "Placeholder fallback"},
            ] if games and not has_actionable_data else []),
        ],
        "route_path": "/nba/cards",
        "intro_title": "NBA Cards",
        "intro_body": "This first NBA Syndicate pass maps committed processed game-card, slate, and SmartSim artifacts into the shared board shell instead of leaving NBA behind the generic placeholder route.",
        "cards_control_links": [
            {"label": "Betting Card", "href": f"/nba/season/{parse_iso_date(resolved_date).year}/betting-card?date={resolved_date}"},
            {"label": "Picks", "href": f"/nba/picks?date={resolved_date}"},
            {"label": "Prop Ladders", "href": f"/nba/prop-ladders?date={resolved_date}"},
            {"label": "Live Prop Audit", "href": f"/nba/live-player-props-audit?date={resolved_date}"},
        ],
        "cards_grid_class": "wnba-cards-grid",
        "cards_stylesheet": "nba/cards.css",
        "pregame_portfolio": {"enabled": False, "selected": 0, "candidates": 0},
        "teaser": {
            "label": "NBA module rollout",
            "body": "This is the first live NBA surface inside Syndicate. Picks, props, and deeper drill-ins come next after the shared board contract settles.",
            "href": "/nba",
            "cta": "Open NBA hub",
        },
        "module_links": build_module_links(resolved_date, "Cards"),
        "active_sport_name": "NBA",
    }
    result = apply_game_board_contract(context, sport="nba", module="cards")
    result["refresh_policy"] = {
        "enabled": True,
        "intervalMs": 30000,
        "refreshOnVisible": True,
        "refreshOnFocus": True,
        "stopOnPageHide": True,
        "preventOverlap": True,
        "skipWhenHidden": False,
        "poller": "shared.polling",
    }
    _cache_put_context(cache_key, deepcopy(result))
    return deepcopy(result)


def build_cards_api_payload(selected_date: str, *, allow_stored_date_fallback: bool = False) -> dict[str, Any]:
    return build_game_board_api_payload(
        build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    )


def _nba_raw_player_props_for_date(selected_date: str) -> dict[str, dict[str, dict[str, Any]]]:
    # scripts/fetch_basketball_oddsapi_props_local.py's raw feed, aliased
    # to this path by refresh_nba_oddsapi_props.py -- confirmed via direct
    # research 2026-07-23 to carry every real quoted player prop, not just
    # the recommendation engine's own picks.
    path = processed_path(f"oddsapi_player_props_{selected_date}.csv")
    try:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return {}
    return parse_raw_basketball_player_props_rows(rows)


def build_nba_market_board(selected_date: str) -> dict[str, Any]:
    """Layer 1 market/odds inventory for NBA (Phase 3c), reusing the same
    row-builder as WNBA's -- see shared.basketball_market_board for why
    one implementation serves both sports.
    """
    payload = build_cards_api_payload(selected_date)
    games = payload.get("games") if isinstance(payload.get("games"), list) else []
    event_ids = [event_id for event_id in (str(g.get("event_id") or g.get("gamePk") or "").strip() for g in games if isinstance(g, dict)) if event_id]
    live_player_lens_payload = None
    if event_ids:
        # Lazy import: nba.live_lens imports FROM this module at load time
        # (build_cards_page_context/build_live_player_lens_payload etc.),
        # so a top-level import here would be circular.
        from syndicate.features.nba.live_lens import read_latest_live_player_lens_payload

        live_player_lens_payload = read_latest_live_player_lens_payload(selected_date, event_ids)
    return build_basketball_market_board(
        sport_slug="nba",
        selected_date=selected_date,
        games=games,
        live_player_lens_payload=live_player_lens_payload,
        raw_player_props=_nba_raw_player_props_for_date(selected_date),
        odds_history=basketball_odds_history_payload("nba", selected_date),
    )


def build_cards_sim_detail_payload(selected_date: str, away_tri: str, home_tri: str) -> dict[str, Any]:
    away_key = str(away_tri or "").strip().upper()
    home_key = str(home_tri or "").strip().upper()
    bundle = _artifact_bundle(selected_date)
    sim_detail = bundle.get((home_key, away_key)) if isinstance(bundle, dict) else None
    if not isinstance(sim_detail, dict) and isinstance(bundle.get("sim"), dict):
        sim_detail = bundle.get("sim", {}).get((home_key, away_key))
    if isinstance(sim_detail, dict):
        sim_payload = sim_detail.get("sim") if isinstance(sim_detail.get("sim"), dict) else sim_detail
        return {
            "date": selected_date,
            "requested_date": selected_date,
            "players_included": True,
            "games": [
                {
                    "home_tri": home_key,
                    "away_tri": away_key,
                    "sim": {
                        "players_loaded": True,
                        "players_summary": dict(sim_payload.get("players_summary") or sim_detail.get("players_summary") or {}),
                        "players": {
                            "home": [dict(row) for row in ((sim_payload.get("players") or {}).get("home") or []) if isinstance(row, dict)],
                            "away": [dict(row) for row in ((sim_payload.get("players") or {}).get("away") or []) if isinstance(row, dict)],
                        },
                        "missing_prop_players": {
                            "home": [dict(row) for row in ((sim_payload.get("missing_prop_players") or {}).get("home") or []) if isinstance(row, dict)],
                            "away": [dict(row) for row in ((sim_payload.get("missing_prop_players") or {}).get("away") or []) if isinstance(row, dict)],
                        },
                        "injuries": {
                            "home": [dict(row) for row in ((sim_payload.get("injuries") or {}).get("home") or []) if isinstance(row, dict)],
                            "away": [dict(row) for row in ((sim_payload.get("injuries") or {}).get("away") or []) if isinstance(row, dict)],
                        },
                    },
                }
            ],
        }

    context = build_cards_page_context(selected_date)
    games = context.get("games") if isinstance(context.get("games"), list) else []
    game = next(
        (
            item
            for item in games
            if isinstance(item, dict)
            and str(item.get("away_tri") or "").strip().upper() == away_key
            and str(item.get("home_tri") or "").strip().upper() == home_key
        ),
        None,
    )
    return {
        "date": selected_date,
        "requested_date": selected_date,
        "players_included": False,
        "games": [dict(game)] if isinstance(game, dict) else [],
    }


def build_live_state_payload(selected_date: str, ttl: int = 12, *, allow_stored_date_fallback: bool = True) -> dict[str, Any]:
    is_today = str(selected_date).strip() == central_today_iso()
    if _render_web_dyno():
        local_payload = _best_live_state_payload(selected_date)
        if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list) and bool(local_payload.get("games")):
            return _attach_odds_refresh_timestamp(local_payload)
        return _attach_odds_refresh_timestamp({
            "date": selected_date,
            "requested_date": selected_date,
            "lookahead_applied": False,
            "ttl": int(ttl),
            "source": "render_web_dyno_empty",
            "games": [],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
    if is_today:
        espn_payload = _espn_live_state_payload(selected_date)
        if isinstance(espn_payload, dict) and isinstance(espn_payload.get("games"), list) and bool(espn_payload.get("games")):
            return _attach_odds_refresh_timestamp(espn_payload)

    local_payload = _best_live_state_payload(selected_date)
    if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list) and bool(local_payload.get("games")):
        return _attach_odds_refresh_timestamp(local_payload)

    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    resolved_date = str(context.get("date") or selected_date).strip() or selected_date
    games = context.get("games") if isinstance(context.get("games"), list) else []
    out_games = []
    for game in games:
        if not isinstance(game, dict):
            continue
        normalized_status = _normalized_game_status(
            status_text=game.get("status"),
            detail_text=game.get("detail"),
            start_time_utc=((game.get("odds") or {}).get("commence_time") if isinstance(game.get("odds"), dict) else None) or game.get("detail") or game.get("status"),
            in_progress=((game.get("live_state") or {}).get("in_progress") if isinstance(game.get("live_state"), dict) else False),
            final=((game.get("live_state") or {}).get("final") if isinstance(game.get("live_state"), dict) else False),
            away_pts=(_sim_payload(game).get("score", {}).get("away_mean") if isinstance(_sim_payload(game).get("score"), dict) else None),
            home_pts=(_sim_payload(game).get("score", {}).get("home_mean") if isinstance(_sim_payload(game).get("score"), dict) else None),
        )
        out_games.append(
            {
                "game_id": game.get("gamePk"),
                "event_id": game.get("event_id"),
                "home": game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else None),
                "away": game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else None),
                "home_pts": None,
                "away_pts": None,
                "status_id": None,
                "status": normalized_status["detail"],
                "period": normalized_status.get("period"),
                "clock": normalized_status.get("clock") or "",
                "in_progress": bool(normalized_status["in_progress"]),
                "final": bool(normalized_status["final"]),
                "periods": [],
            }
        )

    return _attach_odds_refresh_timestamp({
        "date": resolved_date,
        "requested_date": selected_date,
        "lookahead_applied": bool(resolved_date != selected_date),
        "ttl": int(ttl),
        "source": "syndicate_cards_fallback",
        "games": out_games,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
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
    if _render_web_dyno():
        return _attach_odds_refresh_timestamp({
            "ok": True,
            "ttl": int(ttl),
            "date": selected_date or None,
            "requested_date": selected_date,
            "lookahead_applied": False,
            "games": [{"event_id": event_id, "players": []} for event_id in normalized_event_ids],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    resolved_date = str(context.get("date") or selected_date).strip() or selected_date
    # Mirrors build_live_player_lens_payload's own staleness gate (same
    # file) and the identical fix applied to WNBA's copy of this function
    # (syndicate/features/wnba/cards.py) 2026-07-30 -- without it, a local
    # snapshot captured near tip-off (real players listed, legitimately 0
    # pts/reb/ast/min at that instant) satisfies
    # _payload_has_live_boxscore_players forever and is served indefinitely,
    # never re-fetched, while live_state (which already has this gate) keeps
    # ticking with the real score.
    is_today = str(selected_date).strip() == central_today_iso()

    def _discard_if_stale(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not is_today or payload is None:
            return payload
        timestamp = _parse_payload_timestamp(payload.get("odds_refreshed_at") or payload.get("generated_at"))
        if timestamp is not None and (datetime.now(timezone.utc) - timestamp) > timedelta(minutes=20):
            return None
        return payload

    local_payload = _discard_if_stale(_filtered_local_live_snapshot_payload("live_player_boxscore", resolved_date, normalized_event_ids))
    if _payload_has_live_boxscore_players(local_payload):
        return _attach_odds_refresh_timestamp(local_payload)
    public_payload = _public_live_player_boxscore_payload(resolved_date, normalized_event_ids)
    if _payload_has_live_boxscore_players(public_payload):
        return _attach_odds_refresh_timestamp(public_payload)
    game_index = _resolve_games_for_event_ids(resolved_date, normalized_event_ids)
    resolved_event_ids = resolve_event_ids_from_games(game_index, normalized_event_ids)
    if resolved_event_ids:
        local_payload = _discard_if_stale(_filtered_local_live_snapshot_payload("live_player_boxscore", resolved_date, resolved_event_ids))
        if _payload_has_live_boxscore_players(local_payload):
            return _attach_odds_refresh_timestamp(local_payload)

        public_payload = _public_live_player_boxscore_payload(resolved_date, resolved_event_ids)
        if _payload_has_live_boxscore_players(public_payload):
            return _attach_odds_refresh_timestamp(public_payload)

    fallback_games = [
        _fallback_live_player_boxscore_game(game, event_id=event_id, selected_date=resolved_date)
        for event_id in normalized_event_ids
        for game in [game_index.get(event_id)]
        if isinstance(game, dict)
    ]
    if fallback_games:
        return _attach_odds_refresh_timestamp({
            "ok": True,
            "ttl": int(ttl),
            "date": resolved_date or None,
            "requested_date": selected_date,
            "lookahead_applied": bool(resolved_date != selected_date),
            "games": fallback_games,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
    return _attach_odds_refresh_timestamp({
        "ok": True,
        "ttl": int(ttl),
        "date": resolved_date or None,
        "requested_date": selected_date,
        "lookahead_applied": bool(resolved_date != selected_date),
        "games": [{"event_id": event_id, "players": []} for event_id in normalized_event_ids],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
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
    if _render_web_dyno():
        return _attach_odds_refresh_timestamp({
            "ok": True,
            "ttl": int(ttl),
            "date": selected_date or None,
            "requested_date": selected_date,
            "lookahead_applied": False,
            "games": [
                {
                    "event_id": event_id,
                    "game_id": None,
                    "home": None,
                    "away": None,
                    "status": {"in_progress": False, "final": False, "period": None, "clock": ""},
                    "rows": [],
                }
                for event_id in normalized_event_ids
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
    context = build_cards_page_context(selected_date, allow_stored_date_fallback=allow_stored_date_fallback)
    resolved_date = str(context.get("date") or selected_date).strip() or selected_date
    local_payload = _filtered_local_live_snapshot_payload("live_player_lens", resolved_date, normalized_event_ids)
    is_today = str(selected_date).strip() == central_today_iso()
    local_timestamp = _parse_payload_timestamp((local_payload or {}).get("odds_refreshed_at") or (local_payload or {}).get("generated_at"))
    if is_today and local_timestamp and (datetime.now(timezone.utc) - local_timestamp) > timedelta(minutes=20):
        local_payload = None
    if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list) and bool(local_payload.get("games")):
        hydrated_local_payload = _hydrate_live_player_lens_payload(
            local_payload,
            resolved_date,
            normalized_event_ids,
            allow_stored_date_fallback=allow_stored_date_fallback,
        )
        if any(isinstance(game, dict) and bool(game.get("rows")) for game in (hydrated_local_payload.get("games") if isinstance(hydrated_local_payload.get("games"), list) else [])):
            return _attach_odds_refresh_timestamp(hydrated_local_payload)
    artifact_payload = _artifact_live_player_lens_payload(
        resolved_date,
        normalized_event_ids,
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
    if isinstance(artifact_payload, dict) and isinstance(artifact_payload.get("games"), list) and bool(artifact_payload.get("games")):
        hydrated_artifact_payload = _hydrate_live_player_lens_payload(
            artifact_payload,
            resolved_date,
            normalized_event_ids,
            allow_stored_date_fallback=allow_stored_date_fallback,
        )
        if any(isinstance(game, dict) and bool(game.get("rows")) for game in (hydrated_artifact_payload.get("games") if isinstance(hydrated_artifact_payload.get("games"), list) else [])):
            return _attach_odds_refresh_timestamp(hydrated_artifact_payload)
    game_index = _resolve_games_for_event_ids(
        resolved_date,
        normalized_event_ids,
        allow_stored_date_fallback=allow_stored_date_fallback,
    )
    fallback_games = [
        _fallback_live_player_lens_game(game, event_id=event_id)
        for event_id in normalized_event_ids
        for game in [game_index.get(event_id)]
        if isinstance(game, dict)
    ]
    if fallback_games:
        return _attach_odds_refresh_timestamp(
            _hydrate_live_player_lens_payload(
                {
                    "ok": True,
                    "ttl": int(ttl),
                    "date": resolved_date or None,
                    "requested_date": selected_date,
                    "lookahead_applied": bool(resolved_date != selected_date),
                    "games": fallback_games,
                    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                },
                resolved_date,
                normalized_event_ids,
                allow_stored_date_fallback=allow_stored_date_fallback,
            )
        )
    return _attach_odds_refresh_timestamp({
        "ok": True,
        "ttl": int(ttl),
        "date": resolved_date or None,
        "requested_date": selected_date,
        "lookahead_applied": bool(resolved_date != selected_date),
        "games": [
            {
                "event_id": event_id,
                "game_id": None,
                "home": None,
                "away": None,
                "status": {"in_progress": False, "final": False, "period": None, "clock": ""},
                "rows": [],
            }
            for event_id in normalized_event_ids
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
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
    if _render_web_dyno():
        return _attach_odds_refresh_timestamp({
            "ok": True,
            "ttl": int(ttl),
            "date": selected_date,
            "requested_date": selected_date,
            "lookahead_applied": False,
            "include_period_totals": bool(include_period_totals),
            "games": [{"event_id": event_id, "found": False} for event_id in normalized_event_ids],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
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
        _fallback_live_lines_game(game, include_period_totals=bool(include_period_totals))
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
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
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
        "games": [{"event_id": event_id, "found": False} for event_id in normalized_event_ids],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    })

def build_live_pbp_stats_payload(
    selected_date: str,
    event_ids: list[str],
    ttl: int = 20,
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    if _render_web_dyno():
        return _attach_odds_refresh_timestamp({
            "ok": True,
            "ttl": int(ttl),
            "date": selected_date or None,
            "requested_date": selected_date,
            "lookahead_applied": False,
            "games": [
                {
                    "event_id": event_id,
                    "game_id": None,
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
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
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
                "game_id": None,
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
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
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
    }
