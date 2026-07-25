from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota


API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"
SCHEDULE_TZ = os.environ.get("SCHEDULE_TZ", "America/New_York")
DEFAULT_HITTER_MARKETS = [
    "batter_hits",
    "batter_hits_runs_rbis",
    "batter_total_bases",
    "batter_home_runs",
    "batter_rbis",
    "batter_runs_scored",
    "batter_strikeouts",
]
PITCHER_MARKET_KEY_MAP = {
    "pitcher_strikeouts": "strikeouts",
    "pitcher_outs": "outs",
    "pitcher_hits_allowed": "hits_allowed",
    "pitcher_walks": "walks_allowed",
    "pitcher_earned_runs": "earned_runs",
}
PLAYER_PROP_PRIMARY_LINE_PREFERENCES = {
    "batter_home_runs": (0.5,),
    "batter_hits": (0.5,),
    "batter_hits_runs_rbis": (1.5, 2.5, 3.5),
    "batter_rbis": (0.5,),
    "batter_runs_scored": (0.5,),
    "batter_strikeouts": (0.5, 1.5),
    "batter_total_bases": (1.5,),
    "hits_allowed": (5.5, 4.5, 6.5),
    "walks_allowed": (1.5, 2.5, 0.5),
    "earned_runs": (1.5, 2.5, 0.5, 3.5),
}


class OddsApiLiveFetchError(RuntimeError):
    pass


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, obj: Any) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _http_get(url: str, params: dict[str, Any], timeout: int = 30) -> tuple[Any, dict[str, str]]:
    response = requests.get(url, params=params, timeout=timeout)
    # Recorded BEFORE raise_for_status: a 4xx/5xx still carries the quota
    # headers, and a call that failed may well have been billed. Dropping
    # those observations would bias measured burn downward -- exactly the
    # direction that makes an over-budget account look fine.
    record_oddsapi_quota(response.headers, sport="mlb", endpoint=url)
    response.raise_for_status()
    return response.json(), {str(key).lower(): str(value) for key, value in response.headers.items()}


def _as_events_list(obj: Any) -> list[dict[str, Any]]:
    if obj is None:
        return []
    if isinstance(obj, list):
        return [item for item in obj if isinstance(item, dict)]
    if isinstance(obj, dict):
        for key in ("data", "events"):
            value = obj.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_matches_slate_date(event: dict[str, Any], date_str: str) -> bool:
    parsed = _parse_iso(str(event.get("commence_time") or ""))
    if parsed is None:
        return False
    try:
        return parsed.astimezone(ZoneInfo(SCHEDULE_TZ)).strftime("%Y-%m-%d") == str(date_str)
    except Exception:
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d") == str(date_str)


def _american_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.upper() == "EVEN":
            return "+100"
        return text
    try:
        odds = int(float(value))
    except Exception:
        return None
    if odds == 0:
        return None
    return f"{odds:+d}" if odds > 0 else str(odds)


def _american_implied_prob(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        odds = int(text)
    except Exception:
        return None
    if odds == 0:
        return None
    if odds > 0:
        return 100.0 / (float(odds) + 100.0)
    return float(-odds) / (float(-odds) + 100.0)


def _prop_lane_row(*, line: float, src: str = "oddsapi") -> dict[str, Any]:
    return {"line": float(line), "over_odds": None, "under_odds": None, "_src": str(src)}


def _merge_prop_lane_row(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    out = dict(dst or {})
    if out.get("line") is None and src.get("line") is not None:
        out["line"] = src.get("line")
    if out.get("over_odds") is None and src.get("over_odds") is not None:
        out["over_odds"] = src.get("over_odds")
    if out.get("under_odds") is None and src.get("under_odds") is not None:
        out["under_odds"] = src.get("under_odds")
    if not out.get("_src") and src.get("_src"):
        out["_src"] = src.get("_src")
    return out


def _line_matches(value: Any, target: float, tol: float = 1e-9) -> bool:
    try:
        return abs(float(value) - float(target)) <= float(tol)
    except Exception:
        return False


def _primary_lane_sort_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    p_over = _american_implied_prob(row.get("over_odds"))
    p_under = _american_implied_prob(row.get("under_odds"))
    line_value = float(row.get("line") or 0.0)
    if p_over is not None and p_under is not None:
        return (0.0, abs(float(p_over) - float(p_under)), abs(float(p_over + p_under) - 1.0), abs(line_value))
    implied = p_over if p_over is not None else p_under
    if implied is not None:
        return (1.0, abs(float(implied) - 0.5), 0.0, abs(line_value))
    return (2.0, 1e9, 1e9, abs(line_value))


def _select_primary_prop_lane(lanes: list[dict[str, Any]], market_name: str | None) -> dict[str, Any]:
    for preferred_line in PLAYER_PROP_PRIMARY_LINE_PREFERENCES.get(str(market_name or ""), ()):
        for require_two_way in (True, False):
            for lane in lanes:
                if not _line_matches(lane.get("line"), preferred_line):
                    continue
                if require_two_way and (lane.get("over_odds") is None or lane.get("under_odds") is None):
                    continue
                return lane
    return min(lanes, key=_primary_lane_sort_key) if lanes else {}


def _game_total_lane_sort_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    p_over = _american_implied_prob(row.get("over_odds"))
    p_under = _american_implied_prob(row.get("under_odds"))
    line_value = float(row.get("line") or 0.0)
    if p_over is not None and p_under is not None:
        return (0.0, abs(float(p_over) - float(p_under)), abs(float(p_over + p_under) - 1.0), abs(line_value))
    implied = p_over if p_over is not None else p_under
    if implied is not None:
        return (1.0, abs(float(implied) - 0.5), 0.0, abs(line_value))
    return (2.0, 1e9, 1e9, abs(line_value))


def _select_primary_game_total_lane(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    return min(lanes, key=_game_total_lane_sort_key) if lanes else {}


def _game_spread_lane_sort_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    p_home = _american_implied_prob(row.get("home_odds"))
    p_away = _american_implied_prob(row.get("away_odds"))
    line_value = abs(float(row.get("home_line") or 0.0))
    if p_home is not None and p_away is not None:
        return (0.0, abs(float(p_home) - float(p_away)), abs(float(p_home + p_away) - 1.0), line_value)
    implied = p_home if p_home is not None else p_away
    if implied is not None:
        return (1.0, abs(float(implied) - 0.5), 0.0, line_value)
    return (2.0, 1e9, 1e9, line_value)


def _select_primary_game_spread_lane(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    return min(lanes, key=_game_spread_lane_sort_key) if lanes else {}


def _finalize_prop_market(row: dict[str, Any], market_name: str | None = None) -> dict[str, Any]:
    lanes_map = (row or {}).get("_lanes") or {}
    lanes: list[dict[str, Any]] = []
    for lane in lanes_map.values():
        if not isinstance(lane, dict) or lane.get("line") is None:
            continue
        lanes.append(
            {
                "line": float(lane.get("line")),
                "over_odds": lane.get("over_odds"),
                "under_odds": lane.get("under_odds"),
                "_src": str(lane.get("_src") or "oddsapi"),
            }
        )
    lanes.sort(key=lambda item: float(item.get("line") or 0.0))
    primary = _select_primary_prop_lane(lanes, market_name)
    primary_line = primary.get("line") if isinstance(primary, dict) else None
    alternates = [lane for lane in lanes if lane.get("line") != primary_line]
    return {
        "line": primary.get("line") if isinstance(primary, dict) else None,
        "over_odds": primary.get("over_odds") if isinstance(primary, dict) else None,
        "under_odds": primary.get("under_odds") if isinstance(primary, dict) else None,
        "_src": str((primary or {}).get("_src") or (row or {}).get("_src") or "oddsapi"),
        "lanes": lanes,
        "alternates": alternates,
    }


def _merge_prop_market_rows(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    merged_lanes: dict[str, dict[str, Any]] = {}
    for container in (dst or {}, src or {}):
        lanes_map = container.get("_lanes") if isinstance(container, dict) else None
        if isinstance(lanes_map, dict):
            for line_key, lane in lanes_map.items():
                if not isinstance(lane, dict):
                    continue
                merged_lanes[str(line_key)] = _merge_prop_lane_row(merged_lanes.get(str(line_key), {}), lane)
            continue
        line_value = container.get("line") if isinstance(container, dict) else None
        if line_value is None:
            continue
        line_key = f"{float(line_value):.3f}"
        merged_lanes[line_key] = _merge_prop_lane_row(
            merged_lanes.get(line_key, {}),
            {
                "line": float(line_value),
                "over_odds": container.get("over_odds") if isinstance(container, dict) else None,
                "under_odds": container.get("under_odds") if isinstance(container, dict) else None,
                "_src": container.get("_src") if isinstance(container, dict) else "oddsapi",
            },
        )
    return {"_src": str((dst or {}).get("_src") or (src or {}).get("_src") or "oddsapi"), "_lanes": merged_lanes}


def _finalize_prop_market_map(markets: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for name, market_rows in (markets or {}).items():
        if not isinstance(market_rows, dict):
            continue
        out[name] = {}
        for market_name, row in market_rows.items():
            if not isinstance(row, dict):
                continue
            out[name][market_name] = _finalize_prop_market(row, market_name)
    return out


def _as_market_list(markets: Any) -> list[dict[str, Any]]:
    if markets is None:
        return []
    if isinstance(markets, list):
        return [market for market in markets if isinstance(market, dict)]
    if isinstance(markets, dict):
        return [market for market in markets.values() if isinstance(market, dict)]
    return []


def _extract_player_props(markets: Any, *, key_map: dict[str, str]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for market in _as_market_list(markets):
        key = str(market.get("key") or "").lower().strip()
        if key not in key_map:
            continue
        internal = str(key_map[key])
        outcomes = market.get("outcomes")
        if not isinstance(outcomes, list):
            continue
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            name = str(outcome.get("description") or outcome.get("participant") or "").strip()
            if not name:
                continue
            line = outcome.get("point")
            if line is None:
                continue
            side = str(outcome.get("name") or "").strip().lower()
            try:
                line_value = float(line)
            except Exception:
                continue
            row = out.setdefault(name.lower().strip(), {}).setdefault(internal, {"_src": "oddsapi", "_lanes": {}})
            line_key = f"{line_value:.3f}"
            lane = row.setdefault("_lanes", {}).setdefault(line_key, _prop_lane_row(line=line_value))
            if side.startswith("over") and lane.get("over_odds") is None:
                lane["over_odds"] = _american_str(outcome.get("price"))
            elif side.startswith("under") and lane.get("under_odds") is None:
                lane["under_odds"] = _american_str(outcome.get("price"))
    return _finalize_prop_market_map(out)


def _extract_game_lines(markets: Any, *, home_team: str, away_team: str) -> dict[str, Any]:
    segment_market_map = {
        "h2h": ("full", "h2h"),
        "spreads": ("full", "spreads"),
        "totals": ("full", "totals"),
        "h2h_1st_1_innings": ("first1", "h2h"),
        "h2h_3_way_1st_1_innings": ("first1", "h2h_3_way"),
        "spreads_1st_1_innings": ("first1", "spreads"),
        "alternate_spreads_1st_1_innings": ("first1", "spreads_alt"),
        "totals_1st_1_innings": ("first1", "totals"),
        "alternate_totals_1st_1_innings": ("first1", "totals_alt"),
        "h2h_1st_3_innings": ("first3", "h2h"),
        "h2h_3_way_1st_3_innings": ("first3", "h2h_3_way"),
        "spreads_1st_3_innings": ("first3", "spreads"),
        "alternate_spreads_1st_3_innings": ("first3", "spreads_alt"),
        "totals_1st_3_innings": ("first3", "totals"),
        "alternate_totals_1st_3_innings": ("first3", "totals_alt"),
        "h2h_1st_5_innings": ("first5", "h2h"),
        "h2h_3_way_1st_5_innings": ("first5", "h2h_3_way"),
        "spreads_1st_5_innings": ("first5", "spreads"),
        "alternate_spreads_1st_5_innings": ("first5", "spreads_alt"),
        "totals_1st_5_innings": ("first5", "totals"),
        "alternate_totals_1st_5_innings": ("first5", "totals_alt"),
        "h2h_1st_7_innings": ("first7", "h2h"),
        "h2h_3_way_1st_7_innings": ("first7", "h2h_3_way"),
        "spreads_1st_7_innings": ("first7", "spreads"),
        "alternate_spreads_1st_7_innings": ("first7", "spreads_alt"),
        "totals_1st_7_innings": ("first7", "totals"),
        "alternate_totals_1st_7_innings": ("first7", "totals_alt"),
    }
    out: dict[str, Any] = {
        "h2h": None,
        "spreads": None,
        "totals": None,
        "segments": {
            "full": {"h2h": None, "spreads": None, "totals": None},
            "first1": {"h2h": None, "spreads": None, "totals": None},
            "first3": {"h2h": None, "spreads": None, "totals": None},
            "first5": {"h2h": None, "spreads": None, "totals": None},
            "first7": {"h2h": None, "spreads": None, "totals": None},
        },
    }
    home = str(home_team or "").strip().lower()
    away = str(away_team or "").strip().lower()
    spread_lanes = {key: {} for key in ("full", "first1", "first3", "first5", "first7")}
    total_lanes = {key: {} for key in ("full", "first1", "first3", "first5", "first7")}
    for market in _as_market_list(markets):
        key = str(market.get("key") or "").lower().strip()
        segment_spec = segment_market_map.get(key)
        if segment_spec is None:
            continue
        segment_key, market_key = segment_spec
        outcomes = market.get("outcomes") or []
        if market_key == "h2h":
            row = {"home_odds": None, "away_odds": None}
            for outcome in outcomes:
                name = str(outcome.get("name") or "").strip().lower()
                if not name:
                    continue
                if name == home and row["home_odds"] is None:
                    row["home_odds"] = _american_str(outcome.get("price"))
                elif name == away and row["away_odds"] is None:
                    row["away_odds"] = _american_str(outcome.get("price"))
            if row["home_odds"] is not None or row["away_odds"] is not None:
                out["segments"][segment_key]["h2h"] = row
                if segment_key == "full":
                    out["h2h"] = row
        elif market_key == "h2h_3_way":
            row = {"home_odds": None, "away_odds": None, "draw_odds": None, "is_3_way": True}
            for outcome in outcomes:
                name = str(outcome.get("name") or "").strip().lower()
                if not name:
                    continue
                if name == home and row["home_odds"] is None:
                    row["home_odds"] = _american_str(outcome.get("price"))
                elif name == away and row["away_odds"] is None:
                    row["away_odds"] = _american_str(outcome.get("price"))
                elif name in {"draw", "tie"} and row["draw_odds"] is None:
                    row["draw_odds"] = _american_str(outcome.get("price"))
            current_h2h = ((out.get("segments") or {}).get(segment_key) or {}).get("h2h")
            if not isinstance(current_h2h, dict) and (row["home_odds"] is not None or row["away_odds"] is not None):
                out["segments"][segment_key]["h2h"] = row
                if segment_key == "full":
                    out["h2h"] = row
        elif market_key in {"totals", "totals_alt"}:
            for outcome in outcomes:
                side = str(outcome.get("name") or "").strip().lower()
                try:
                    line_value = float(outcome.get("point"))
                except Exception:
                    continue
                lane_key = f"{line_value:.3f}"
                lane = total_lanes[segment_key].setdefault(lane_key, {"line": line_value, "over_odds": None, "under_odds": None})
                if side.startswith("over") and lane.get("over_odds") is None:
                    lane["over_odds"] = _american_str(outcome.get("price"))
                elif side.startswith("under") and lane.get("under_odds") is None:
                    lane["under_odds"] = _american_str(outcome.get("price"))
        elif market_key in {"spreads", "spreads_alt"}:
            for outcome in outcomes:
                name = str(outcome.get("name") or "").strip().lower()
                if not name:
                    continue
                try:
                    point_value = float(outcome.get("point"))
                except Exception:
                    continue
                if name == home:
                    lane_key = f"{point_value:.3f}"
                    lane = spread_lanes[segment_key].setdefault(lane_key, {"home_line": point_value, "home_odds": None, "away_line": None, "away_odds": None})
                    if lane.get("home_odds") is None:
                        lane["home_odds"] = _american_str(outcome.get("price"))
                elif name == away:
                    home_line = -float(point_value)
                    lane_key = f"{home_line:.3f}"
                    lane = spread_lanes[segment_key].setdefault(lane_key, {"home_line": home_line, "home_odds": None, "away_line": point_value, "away_odds": None})
                    lane["away_line"] = point_value
                    if lane.get("away_odds") is None:
                        lane["away_odds"] = _american_str(outcome.get("price"))
    for segment_key, lane_map in total_lanes.items():
        lanes = [lane for lane in lane_map.values() if isinstance(lane, dict) and lane.get("line") is not None]
        primary = _select_primary_game_total_lane(lanes)
        if primary:
            out["segments"][segment_key]["totals"] = primary
            if segment_key == "full":
                out["totals"] = primary
    for segment_key, lane_map in spread_lanes.items():
        lanes = [lane for lane in lane_map.values() if isinstance(lane, dict) and (lane.get("home_line") is not None or lane.get("away_line") is not None)]
        primary = _select_primary_game_spread_lane(lanes)
        if primary:
            out["segments"][segment_key]["spreads"] = primary
            if segment_key == "full":
                out["spreads"] = primary
    if not any(any(bucket.get(market) is not None for market in ("h2h", "spreads", "totals")) for key, bucket in (out.get("segments") or {}).items() if key != "full" and isinstance(bucket, dict)):
        out.pop("segments", None)
    return out


def _market_doc_entry_count(doc: dict[str, Any] | None, kind: str) -> int:
    if not isinstance(doc, dict):
        return 0
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    counts = meta.get("counts") if isinstance(meta.get("counts"), dict) else {}
    if kind == "game_lines":
        return int(counts.get("games") or 0)
    if kind in {"pitcher_props", "hitter_props"}:
        return int(counts.get("players") or 0)
    return 0


def _unwrap_live_odds_payload(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        for row in obj:
            if isinstance(row, dict):
                return row
    return None


def _http_error_details(exc: requests.HTTPError) -> tuple[int | None, str | None, str | None]:
    response = getattr(exc, "response", None)
    status_code = None
    error_code = None
    message = None
    if response is None:
        return status_code, error_code, message
    try:
        status_code = int(response.status_code)
    except Exception:
        status_code = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        raw_error = payload.get("error_code")
        raw_message = payload.get("message")
        error_code = str(raw_error).strip() or None
        message = str(raw_message).strip() or None
    else:
        try:
            text = str(response.text or "").strip()
        except Exception:
            text = ""
        if text:
            message = text
            upper = text.upper()
            if "OUT_OF_USAGE_CREDITS" in upper:
                error_code = "OUT_OF_USAGE_CREDITS"
            elif "INVALID_API_KEY" in upper:
                error_code = "INVALID_API_KEY"
    return status_code, error_code, message


def _is_fatal_live_odds_error(status_code: int | None, error_code: str | None) -> bool:
    code = str(error_code or "").strip().upper()
    if code in {"OUT_OF_USAGE_CREDITS", "INVALID_API_KEY", "MISSING_API_KEY", "SUBSCRIPTION_INACTIVE"}:
        return True
    return status_code in {401, 403, 429}


def _fetch_live_events_for_date(api_key: str, date_str: str) -> list[dict[str, Any]]:
    raw, _ = _http_get(f"{API_BASE}/sports/{SPORT}/events", {"apiKey": api_key})
    return [event for event in _as_events_list(raw) if _event_matches_slate_date(event, date_str)]


def _fetch_live_event_odds(api_key: str, event_id: str, *, markets_csv: str, regions: str, bookmakers: str | None) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "apiKey": api_key,
        "regions": str(regions or "us"),
        "oddsFormat": "american",
        "markets": str(markets_csv or "").strip(),
    }
    if bookmakers:
        params["bookmakers"] = str(bookmakers)
    try:
        raw, _ = _http_get(f"{API_BASE}/sports/{SPORT}/events/{event_id}/odds", params)
    except requests.HTTPError as exc:
        status_code, error_code, message = _http_error_details(exc)
        if _is_fatal_live_odds_error(status_code, error_code):
            detail = str(message or error_code or f"HTTP {status_code or 'error'}").strip()
            raise OddsApiLiveFetchError(f"OddsAPI live odds request failed: {detail}") from exc
        raise
    return _unwrap_live_odds_payload(raw)


def _best_bookmaker_game_lines(payload: dict[str, Any], *, home_team: str, away_team: str) -> tuple[dict[str, Any] | None, str | None]:
    best_lines = None
    best_key = None
    best_score = -1
    for bookmaker in (payload.get("bookmakers") or []):
        if not isinstance(bookmaker, dict):
            continue
        lines = _extract_game_lines(bookmaker.get("markets"), home_team=home_team, away_team=away_team)
        score = int(bool(lines.get("h2h"))) + int(bool(lines.get("totals"))) + int(bool(lines.get("spreads")))
        segments = lines.get("segments") if isinstance(lines.get("segments"), dict) else {}
        for bucket in segments.values():
            if not isinstance(bucket, dict):
                continue
            score += int(bool(bucket.get("h2h"))) + int(bool(bucket.get("totals"))) + int(bool(bucket.get("spreads")))
        if score <= best_score or score <= 0:
            continue
        best_lines = lines
        best_key = str(bookmaker.get("key") or bookmaker.get("title") or "")
        best_score = score
    return best_lines, best_key


def _prop_market_counts(props_by_name: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    players = 0
    markets: dict[str, int] = {}
    for market_rows in (props_by_name or {}).values():
        if not isinstance(market_rows, dict):
            continue
        player_has_market = False
        for market_name, row in market_rows.items():
            if not isinstance(row, dict) or row.get("line") is None:
                continue
            player_has_market = True
            markets[str(market_name)] = int(markets.get(str(market_name), 0) + 1)
        if player_has_market:
            players += 1
    return {"players": int(players), "markets": {key: int(value) for key, value in sorted(markets.items())}}


def fetch_live_game_lines_for_date(api_key: str, date_str: str, *, regions: str = "us", bookmakers: str | None = None, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    live_events = list(events or _fetch_live_events_for_date(api_key, date_str))
    game_market_keys = [
        "h2h", "spreads", "totals",
        "h2h_1st_1_innings", "h2h_3_way_1st_1_innings", "spreads_1st_1_innings", "alternate_spreads_1st_1_innings", "totals_1st_1_innings", "alternate_totals_1st_1_innings",
        "h2h_1st_3_innings", "h2h_3_way_1st_3_innings", "spreads_1st_3_innings", "alternate_spreads_1st_3_innings", "totals_1st_3_innings", "alternate_totals_1st_3_innings",
        "h2h_1st_5_innings", "h2h_3_way_1st_5_innings", "spreads_1st_5_innings", "alternate_spreads_1st_5_innings", "totals_1st_5_innings", "alternate_totals_1st_5_innings",
        "h2h_1st_7_innings", "h2h_3_way_1st_7_innings", "spreads_1st_7_innings", "alternate_spreads_1st_7_innings", "totals_1st_7_innings", "alternate_totals_1st_7_innings",
    ]
    games: list[dict[str, Any]] = []
    for event in live_events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        try:
            payload = _fetch_live_event_odds(api_key, event_id, markets_csv=",".join(game_market_keys), regions=regions, bookmakers=bookmakers)
        except requests.HTTPError:
            continue
        if not isinstance(payload, dict):
            continue
        home_team = str(event.get("home_team") or payload.get("home_team") or "")
        away_team = str(event.get("away_team") or payload.get("away_team") or "")
        best_lines, bookmaker_key = _best_bookmaker_game_lines(payload, home_team=home_team, away_team=away_team)
        if not isinstance(best_lines, dict):
            continue
        games.append({"event_id": event_id, "commence_time": event.get("commence_time") or payload.get("commence_time"), "home_team": home_team, "away_team": away_team, "bookmaker": bookmaker_key, "markets": best_lines})
    counts = {
        "events_matched": int(len(live_events)),
        "games": int(len(games)),
        "h2h_games": int(sum(1 for row in games if isinstance((row.get("markets") or {}).get("h2h"), dict))),
        "totals_games": int(sum(1 for row in games if isinstance((row.get("markets") or {}).get("totals"), dict))),
        "spreads_games": int(sum(1 for row in games if isinstance((row.get("markets") or {}).get("spreads"), dict))),
    }
    return {"date": str(date_str), "mode": "live", "retrieved_at": datetime.utcnow().isoformat(), "games": games, "meta": {"markets": game_market_keys, "regions": str(regions or "us"), "bookmakers": (str(bookmakers).split(",") if bookmakers else None), "counts": counts}}


def fetch_live_pitcher_props_for_date(api_key: str, date_str: str, *, regions: str = "us", bookmakers: str | None = None, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    live_events = list(events or _fetch_live_events_for_date(api_key, date_str))
    desired_markets = list(PITCHER_MARKET_KEY_MAP.keys())
    pitcher_props: dict[str, dict[str, dict[str, Any]]] = {}
    market_warnings: list[str] = []
    for event in live_events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        try:
            payload = _fetch_live_event_odds(api_key, event_id, markets_csv=",".join(desired_markets), regions=regions, bookmakers=bookmakers)
        except requests.HTTPError:
            fallback_markets = [market for market in desired_markets if market != "pitcher_earned_runs"]
            if not fallback_markets:
                continue
            market_warnings.append(f"pitcher_earned_runs unavailable for event {event_id}; fetched legacy pitcher markets only")
            try:
                payload = _fetch_live_event_odds(api_key, event_id, markets_csv=",".join(fallback_markets), regions=regions, bookmakers=bookmakers)
            except requests.HTTPError:
                continue
        if not isinstance(payload, dict):
            continue
        for bookmaker in (payload.get("bookmakers") or []):
            if not isinstance(bookmaker, dict):
                continue
            extracted = _extract_player_props(bookmaker.get("markets"), key_map=PITCHER_MARKET_KEY_MAP)
            for name, market_rows in extracted.items():
                dst = pitcher_props.setdefault(name, {})
                for market_name, row in market_rows.items():
                    dst[market_name] = _merge_prop_market_rows(dst.get(market_name, {}), row)
    finalized = _finalize_prop_market_map(pitcher_props)
    counts = _prop_market_counts(finalized)
    counts["events_matched"] = int(len(live_events))
    return {"date": str(date_str), "mode": "live", "retrieved_at": datetime.utcnow().isoformat(), "pitcher_props": finalized, "meta": {"markets": desired_markets, "regions": str(regions or "us"), "bookmakers": (str(bookmakers).split(",") if bookmakers else None), "counts": counts, "warnings": market_warnings}}


def fetch_live_hitter_props_for_date(api_key: str, date_str: str, *, regions: str = "us", bookmakers: str | None = None, markets: list[str] | None = None, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    live_events = list(events or _fetch_live_events_for_date(api_key, date_str))
    desired_markets = [str(market).strip().lower() for market in (markets or []) if str(market).strip()]
    if not desired_markets:
        desired_markets = [str(market).strip().lower() for market in DEFAULT_HITTER_MARKETS]
    hitter_props: dict[str, dict[str, dict[str, Any]]] = {}
    for event in live_events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        try:
            payload = _fetch_live_event_odds(api_key, event_id, markets_csv=",".join(desired_markets), regions=regions, bookmakers=bookmakers)
        except requests.HTTPError:
            continue
        if not isinstance(payload, dict):
            continue
        for bookmaker in (payload.get("bookmakers") or []):
            if not isinstance(bookmaker, dict):
                continue
            extracted = _extract_player_props(bookmaker.get("markets"), key_map={market_name: market_name for market_name in desired_markets})
            for name, market_rows in extracted.items():
                dst = hitter_props.setdefault(name, {})
                for market_name, row in market_rows.items():
                    dst[market_name] = _merge_prop_market_rows(dst.get(market_name, {}), row)
    finalized = _finalize_prop_market_map(hitter_props)
    counts = _prop_market_counts(finalized)
    counts["events_matched"] = int(len(live_events))
    return {"date": str(date_str), "mode": "live", "retrieved_at": datetime.utcnow().isoformat(), "hitter_props": finalized, "meta": {"markets": desired_markets, "regions": str(regions or "us"), "bookmakers": (str(bookmakers).split(",") if bookmakers else None), "counts": counts}}


def fetch_and_write_live_odds_for_date(date_str: str, *, out_dir: Path | None = None, overwrite: bool = True, regions: str = "us", bookmakers: str | None = None, hitter_markets: list[str] | None = None) -> dict[str, Any]:
    _load_env()
    api_key = os.environ.get("ODDS_API_KEY") or os.environ.get("ODDSAPI_KEY")
    if not api_key:
        raise RuntimeError("ODDS_API_KEY not set")
    target_dir = Path(out_dir) if out_dir else (Path(__file__).resolve().parents[1] / "data" / "market" / "oddsapi")
    _ensure_dir(target_dir)
    token = str(date_str).replace("-", "_")
    game_lines_path = target_dir / f"oddsapi_game_lines_{token}.json"
    pitcher_props_path = target_dir / f"oddsapi_pitcher_props_{token}.json"
    hitter_props_path = target_dir / f"oddsapi_hitter_props_{token}.json"
    if not overwrite and game_lines_path.exists() and pitcher_props_path.exists() and hitter_props_path.exists():
        return {"status": "skipped", "date": str(date_str), "out_dir": str(target_dir), "game_lines_path": str(game_lines_path), "pitcher_props_path": str(pitcher_props_path), "hitter_props_path": str(hitter_props_path), "reason": "overwrite=off and market files already exist"}
    live_events = _fetch_live_events_for_date(api_key, date_str)
    game_lines_doc = fetch_live_game_lines_for_date(api_key, date_str, regions=regions, bookmakers=bookmakers, events=live_events)
    pitcher_props_doc = fetch_live_pitcher_props_for_date(api_key, date_str, regions=regions, bookmakers=bookmakers, events=live_events)
    hitter_props_doc = fetch_live_hitter_props_for_date(api_key, date_str, regions=regions, bookmakers=bookmakers, markets=hitter_markets, events=live_events)
    warnings: list[str] = []
    existing_game_lines_doc = _read_json_if_exists(game_lines_path)
    existing_pitcher_props_doc = _read_json_if_exists(pitcher_props_path)
    existing_hitter_props_doc = _read_json_if_exists(hitter_props_path)
    if _market_doc_entry_count(game_lines_doc, "game_lines") <= 0 and _market_doc_entry_count(existing_game_lines_doc, "game_lines") > 0:
        game_lines_doc = existing_game_lines_doc or game_lines_doc
        warnings.append(f"preserved existing game lines for {date_str} because live refresh returned no matched events")
    if _market_doc_entry_count(pitcher_props_doc, "pitcher_props") <= 0 and _market_doc_entry_count(existing_pitcher_props_doc, "pitcher_props") > 0:
        pitcher_props_doc = existing_pitcher_props_doc or pitcher_props_doc
        warnings.append(f"preserved existing pitcher props for {date_str} because live refresh returned no player props")
    if _market_doc_entry_count(hitter_props_doc, "hitter_props") <= 0 and _market_doc_entry_count(existing_hitter_props_doc, "hitter_props") > 0:
        hitter_props_doc = existing_hitter_props_doc or hitter_props_doc
        warnings.append(f"preserved existing hitter props for {date_str} because live refresh returned no player props")
    _write_json(game_lines_path, game_lines_doc)
    _write_json(pitcher_props_path, pitcher_props_doc)
    _write_json(hitter_props_path, hitter_props_doc)
    result = {
        "status": ("warning" if warnings else "ok"),
        "date": str(date_str),
        "mode": "live",
        "out_dir": str(target_dir),
        "game_lines_path": str(game_lines_path),
        "pitcher_props_path": str(pitcher_props_path),
        "hitter_props_path": str(hitter_props_path),
        "counts": {
            "game_lines": dict(((game_lines_doc.get("meta") or {}).get("counts") or {})),
            "pitcher_props": dict(((pitcher_props_doc.get("meta") or {}).get("counts") or {})),
            "hitter_props": dict(((hitter_props_doc.get("meta") or {}).get("counts") or {})),
        },
    }
    if warnings:
        result["warnings"] = list(warnings)
    return result