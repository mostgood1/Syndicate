from __future__ import annotations

import json
import os
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.mlb.game_state import mlb_status_is_final
from syndicate.features.mlb.game_state import mlb_status_is_live
from syndicate.features.mlb.sources import default_mlb_source_root
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
    # response.url, not url: the markets= the attribution buckets read live in
    # params, and the recorder redacts apiKey before persisting.
    record_oddsapi_quota(response.headers, sport="mlb", endpoint=response.url)
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
    # The standard market's line wins outright (#16). Previously this picked
    # whichever lane had the most balanced two-way pricing across BOTH the
    # standard and alternate_* markets, so an alternate could win and be
    # displayed as "the total" -- which is not what the board is claiming when
    # it shows one number. Balance is still the tiebreak WITHIN each group.
    standard = [lane for lane in lanes if str((lane or {}).get("_src") or "") == "standard"]
    pool = standard or lanes
    return min(pool, key=_game_total_lane_sort_key) if pool else {}


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
    # See _select_primary_game_total_lane: the standard market's line wins, so
    # MLB shows the actual runline rather than whichever alternate happened to
    # be priced closest to a coin flip.
    standard = [lane for lane in lanes if str((lane or {}).get("_src") or "") == "standard"]
    pool = standard or lanes
    return min(pool, key=_game_spread_lane_sort_key) if pool else {}


def _game_line_alternates(lanes: list[dict[str, Any]], primary: dict[str, Any], *, line_key: str) -> list[dict[str, Any]]:
    """Every other quoted lane, as a ladder, sorted by line.

    Game lines used to keep only the primary and discard the rest, while props
    already preserved theirs (see _finalize_prop_market). That asymmetry meant
    the alternate_* markets were being paid for and thrown away, and no edge
    could be computed anywhere off the primary number.
    """
    primary_line = (primary or {}).get(line_key)
    out: list[dict[str, Any]] = []
    for lane in lanes:
        if not isinstance(lane, dict) or lane.get(line_key) is None:
            continue
        if primary_line is not None and _line_matches(lane.get(line_key), primary_line):
            continue
        out.append(lane)
    return sorted(out, key=lambda item: float(item.get(line_key) or 0.0))


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
        },
    }
    home = str(home_team or "").strip().lower()
    away = str(away_team or "").strip().lower()
    spread_lanes = {key: {} for key in ("full", "first1", "first3", "first5")}
    total_lanes = {key: {} for key in ("full", "first1", "first3", "first5")}
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
                lane = total_lanes[segment_key].setdefault(
                    lane_key, {"line": line_value, "over_odds": None, "under_odds": None, "_src": "alternate"}
                )
                if market_key == "totals":
                    # A line quoted by the standard market is THE line, even if
                    # an alternate also quotes it.
                    lane["_src"] = "standard"
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
                    lane = spread_lanes[segment_key].setdefault(
                        lane_key, {"home_line": point_value, "home_odds": None, "away_line": None, "away_odds": None, "_src": "alternate"}
                    )
                    if market_key == "spreads":
                        lane["_src"] = "standard"
                    if lane.get("home_odds") is None:
                        lane["home_odds"] = _american_str(outcome.get("price"))
                elif name == away:
                    home_line = -float(point_value)
                    lane_key = f"{home_line:.3f}"
                    lane = spread_lanes[segment_key].setdefault(
                        lane_key, {"home_line": home_line, "home_odds": None, "away_line": point_value, "away_odds": None, "_src": "alternate"}
                    )
                    if market_key == "spreads":
                        lane["_src"] = "standard"
                    lane["away_line"] = point_value
                    if lane.get("away_odds") is None:
                        lane["away_odds"] = _american_str(outcome.get("price"))
    for segment_key, lane_map in total_lanes.items():
        lanes = [lane for lane in lane_map.values() if isinstance(lane, dict) and lane.get("line") is not None]
        primary = _select_primary_game_total_lane(lanes)
        if primary:
            primary = dict(primary)
            primary["alternates"] = _game_line_alternates(lanes, primary, line_key="line")
            out["segments"][segment_key]["totals"] = primary
            if segment_key == "full":
                out["totals"] = primary
    for segment_key, lane_map in spread_lanes.items():
        lanes = [lane for lane in lane_map.values() if isinstance(lane, dict) and (lane.get("home_line") is not None or lane.get("away_line") is not None)]
        primary = _select_primary_game_spread_lane(lanes)
        if primary:
            primary = dict(primary)
            primary["alternates"] = _game_line_alternates(lanes, primary, line_key="home_line")
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


# OddsAPI bills per (market x region) PER REQUEST. The core three are served
# by the slate endpoint (/sports/{sport}/odds), which returns every game on
# the board in ONE request -- so they cost 3 credits for the whole slate
# instead of 3 per game. The inning-segment markets below are "additional
# markets" that the slate endpoint does not serve; those genuinely require
# the per-event endpoint and stay there. Splitting them is #17.
_CORE_GAME_MARKET_KEYS = ["h2h", "spreads", "totals"]

# first7 dropped 2026-07-25 (#16): six markets, ~90 credits/sweep on a
# 15-game slate, and the sim never produced a first7 projection at all --
# _daily_summary_row emits full/first1/first3/first5 only -- so the F7 tab was
# showing book lines with no model behind them. Removing the markets AND the
# tab together, rather than leaving a tab that silently renders nothing.
_SEGMENT_GAME_MARKET_KEYS = [
    "h2h_1st_1_innings", "h2h_3_way_1st_1_innings", "spreads_1st_1_innings", "alternate_spreads_1st_1_innings", "totals_1st_1_innings", "alternate_totals_1st_1_innings",
    "h2h_1st_3_innings", "h2h_3_way_1st_3_innings", "spreads_1st_3_innings", "alternate_spreads_1st_3_innings", "totals_1st_3_innings", "alternate_totals_1st_3_innings",
    "h2h_1st_5_innings", "h2h_3_way_1st_5_innings", "spreads_1st_5_innings", "alternate_spreads_1st_5_innings", "totals_1st_5_innings", "alternate_totals_1st_5_innings",
]


def _fetch_live_slate_odds(api_key: str, *, markets_csv: str, regions: str, bookmakers: str | None) -> dict[str, dict[str, Any]]:
    """Core game lines for the WHOLE slate in one request, keyed by event id.

    Returns {} on any failure rather than raising: the caller falls back to
    requesting the core markets per event, which is what it did before #17.
    A cheaper path that can break the expensive one is not worth having.
    """
    params: dict[str, Any] = {
        "apiKey": api_key,
        "regions": str(regions or "us"),
        "oddsFormat": "american",
        "markets": str(markets_csv or "").strip(),
    }
    if bookmakers:
        params["bookmakers"] = str(bookmakers)
    try:
        raw, _ = _http_get(f"{API_BASE}/sports/{SPORT}/odds", params)
    except requests.HTTPError as exc:
        status_code, error_code, message = _http_error_details(exc)
        if _is_fatal_live_odds_error(status_code, error_code):
            # Out of credits / bad key must still surface -- silently falling
            # back to the 15x-more-expensive per-event path on an
            # OUT_OF_USAGE_CREDITS response would be the worst possible
            # reaction to running out of credits.
            detail = str(message or error_code or f"HTTP {status_code or 'error'}").strip()
            raise OddsApiLiveFetchError(f"OddsAPI slate odds request failed: {detail}") from exc
        return {}
    by_event: dict[str, dict[str, Any]] = {}
    for event in _as_events_list(raw):
        event_id = str(event.get("id") or "").strip()
        if event_id:
            by_event[event_id] = event
    return by_event


def _merge_event_odds_payloads(primary: dict[str, Any] | None, secondary: dict[str, Any] | None) -> dict[str, Any] | None:
    """Union two odds payloads for the same event, per bookmaker.

    Needed because core and segment markets now arrive from two different
    requests, while _best_bookmaker_game_lines scores ONE payload and picks
    the single best bookmaker. Scoring them separately would pick a book for
    core and a different book for segments, silently mixing prices from two
    books into one game's lines.
    """
    if not isinstance(primary, dict):
        return secondary if isinstance(secondary, dict) else None
    if not isinstance(secondary, dict):
        return primary

    merged = dict(primary)
    by_key: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for payload in (primary, secondary):
        for bookmaker in (payload.get("bookmakers") or []):
            if not isinstance(bookmaker, dict):
                continue
            key = str(bookmaker.get("key") or bookmaker.get("title") or "").strip()
            if not key:
                continue
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = dict(bookmaker)
                by_key[key]["markets"] = list(bookmaker.get("markets") or [])
                continue
            seen_markets = {str((m or {}).get("key") or "") for m in existing.get("markets") or []}
            for market in bookmaker.get("markets") or []:
                if not isinstance(market, dict):
                    continue
                if str(market.get("key") or "") in seen_markets:
                    continue
                existing.setdefault("markets", []).append(market)
    merged["bookmakers"] = list(by_key.values())
    return merged


def _event_scoping_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_ODDS_EVENT_SCOPING_ENABLED") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _event_scoping_window_seconds() -> int:
    # Matches live_refresh_loop.py's own _T_WINDOW_RAMP_SECONDS (75 min) --
    # a game inside its own T-window is exactly the case that window exists
    # to catch, so "hot" here should agree with it rather than invent a
    # second boundary.
    raw = str(os.environ.get("SYNDICATE_ODDS_EVENT_SCOPING_WINDOW_SECONDS") or "").strip()
    try:
        return max(0, int(raw)) if raw else 75 * 60
    except ValueError:
        return 75 * 60


def _normalize_matchup_team(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _load_mlb_status_by_matchup(date_str: str) -> dict[tuple[str, str], dict[str, object]]:
    # Event scoping (#16 budget lever): per-event, not per-slate, is-this-
    # game-hot decision, so a finished or far-pregame game doesn't pull the
    # 18 segment/alternate markets every ~90s cycle just because some OTHER
    # game on the same slate is live. Reuses the same MLB StatsAPI schedule
    # snapshot (schedule_raw.json) every daily-update run already writes
    # under this same source root -- not a new fetch, just a new read.
    # Keyed by (away, home) team name since that's what OddsAPI's own event
    # objects carry; gamePk isn't available on the OddsAPI side to join on.
    path = default_mlb_source_root() / "source_artifacts" / "data" / "daily" / "snapshots" / date_str / "schedule_raw.json"
    try:
        games = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(games, list):
        return {}
    by_matchup: dict[tuple[str, str], dict[str, object]] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        teams = game.get("teams") if isinstance(game.get("teams"), dict) else {}
        away = ((teams.get("away") or {}).get("team") or {}).get("name") if isinstance(teams.get("away"), dict) else None
        home = ((teams.get("home") or {}).get("team") or {}).get("name") if isinstance(teams.get("home"), dict) else None
        away_key = _normalize_matchup_team(away)
        home_key = _normalize_matchup_team(home)
        if not away_key or not home_key:
            continue
        status = game.get("status") if isinstance(game.get("status"), dict) else {}
        by_matchup[(away_key, home_key)] = {
            "abstract": status.get("abstractGameState"),
            "detailed": status.get("detailedState"),
            "commence": game.get("gameDate"),
        }
    return by_matchup


def _event_wants_full_game_markets(
    *,
    away_team: object,
    home_team: object,
    commence_time: object,
    status_by_matchup: dict[tuple[str, str], dict[str, object]],
    now: datetime,
    window_seconds: int,
) -> bool:
    """Whether THIS event needs the full (segment/alternate) game-market set
    this cycle, vs skipping the per-event segment fetch entirely.

    Full whenever: the schedule snapshot doesn't have this exact matchup
    (fail open -- an unmatched game must not silently lose coverage), the
    game is live, or it's within its own T-window. Reduced only for a
    confirmed-final game or a confirmed-pregame game still outside its
    window.
    """
    key = (_normalize_matchup_team(away_team), _normalize_matchup_team(home_team))
    status = status_by_matchup.get(key)
    if status is None:
        return True
    abstract = status.get("abstract")
    detailed = status.get("detailed")
    if mlb_status_is_live(abstract, detailed):
        return True
    if mlb_status_is_final(abstract, detailed):
        return False
    commence_text = str(commence_time or status.get("commence") or "").strip()
    if not commence_text:
        return True
    try:
        commence = datetime.fromisoformat(commence_text.replace("Z", "+00:00"))
    except ValueError:
        return True
    if commence.tzinfo is None:
        commence = commence.replace(tzinfo=timezone.utc)
    seconds_to_start = (commence - now).total_seconds()
    return seconds_to_start <= window_seconds


def fetch_live_game_lines_for_date(api_key: str, date_str: str, *, regions: str = "us", bookmakers: str | None = None, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    live_events = list(events or _fetch_live_events_for_date(api_key, date_str))
    game_market_keys = _CORE_GAME_MARKET_KEYS + _SEGMENT_GAME_MARKET_KEYS

    # #17: pull the core three for the entire slate in one request. At 15
    # games that is 3 credits instead of 45, and the saving scales with the
    # slate rather than being a fixed win.
    slate_by_event = _fetch_live_slate_odds(
        api_key, markets_csv=",".join(_CORE_GAME_MARKET_KEYS), regions=regions, bookmakers=bookmakers
    )
    # Only drop core from the per-event request if the slate call actually
    # returned something. An empty result means the cheap path failed, and a
    # game with no h2h/totals/spreads is worse than a more expensive request.
    slate_covered = bool(slate_by_event)
    per_event_market_keys = _SEGMENT_GAME_MARKET_KEYS if slate_covered else game_market_keys

    # Event scoping (#16 budget lever). Until now this per-event loop always
    # fetched the full 18 segment/alternate markets for EVERY game on EVERY
    # ~90s cycle, regardless of that game's own state -- including games
    # hours from first pitch and games already final, as long as some OTHER
    # game on the same slate was live (confirmed live 2026-07-27: this is
    # the actual default production code path -- SYNDICATE_ODDS_MARKET_TIER
    # from #82 Phase 2 was never read anywhere in this file, only in
    # refresh_mlb_oddsapi.py's fast-mode path, which live_refresh_loop.py's
    # own launches don't use). A cold event now either skips the per-event
    # call entirely (when the cheap slate-wide core call already covered
    # it) or, in the rare slate-call-failed fallback, only pulls core
    # markets instead of the full set -- never the segments.
    event_scoping_enabled = _event_scoping_enabled()
    status_by_matchup: dict[tuple[str, str], dict[str, object]] = {}
    if event_scoping_enabled:
        status_by_matchup = _load_mlb_status_by_matchup(date_str)
        if not status_by_matchup:
            # Schedule snapshot missing/unreadable: fail open to the
            # original every-event-gets-segments behavior.
            event_scoping_enabled = False
    event_scoping_window_seconds = _event_scoping_window_seconds()
    scoping_now = datetime.now(timezone.utc)

    games: list[dict[str, Any]] = []
    events_scoped_full = 0
    events_scoped_reduced = 0
    for event in live_events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        wants_full = True
        if event_scoping_enabled:
            wants_full = _event_wants_full_game_markets(
                away_team=event.get("away_team"),
                home_team=event.get("home_team"),
                commence_time=event.get("commence_time"),
                status_by_matchup=status_by_matchup,
                now=scoping_now,
                window_seconds=event_scoping_window_seconds,
            )
        if wants_full:
            events_scoped_full += 1
        else:
            events_scoped_reduced += 1
        payload = None
        if wants_full or not slate_covered:
            event_market_keys = per_event_market_keys if wants_full else _CORE_GAME_MARKET_KEYS
            try:
                payload = _fetch_live_event_odds(api_key, event_id, markets_csv=",".join(event_market_keys), regions=regions, bookmakers=bookmakers)
            except requests.HTTPError:
                payload = None
        # Merge before scoring: _best_bookmaker_game_lines picks ONE bookmaker
        # from a single payload, so scoring core and segments separately would
        # mix two books' prices into one game. A cold, slate-covered event
        # has no per-event payload at all -- this just carries the
        # slate-wide core payload through unchanged.
        payload = _merge_event_odds_payloads(slate_by_event.get(event_id), payload)
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
    return {
        "date": str(date_str),
        "mode": "live",
        "retrieved_at": datetime.utcnow().isoformat(),
        "games": games,
        "meta": {
            "markets": game_market_keys,
            "regions": str(regions or "us"),
            "bookmakers": (str(bookmakers).split(",") if bookmakers else None),
            "counts": counts,
            "event_scoping": {
                "enabled": bool(event_scoping_enabled),
                "full_tier_events": int(events_scoped_full),
                "reduced_tier_events": int(events_scoped_reduced),
            },
        },
    }


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