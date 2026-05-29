from __future__ import annotations

from datetime import datetime
from datetime import timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse

from syndicate.features.mlb.sources import available_daily_summary_dates
from syndicate.features.mlb.sources import load_json_file
from syndicate.features.mlb.sources import season_betting_card_day_path
from syndicate.features.mlb.sources import season_betting_card_manifest_path
from syndicate.features.mlb.sources import season_frontend_day_path
from syndicate.features.shared.timezone import central_today_iso


def _vendor_web_root() -> Path:
    return (Path(__file__).resolve().parents[3] / "vendor" / "mlb_bettingv2" / "tools" / "web").resolve()


def source_web_text(filename: str) -> str | None:
    path = (_vendor_web_root() / "static" / filename).resolve()
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


@lru_cache(maxsize=1)
def source_betting_card_asset_version() -> str:
    paths = [
        _vendor_web_root() / "static" / name
        for name in ("cards.css", "season.css", "betting_card.js", "back_to_top.js")
    ]
    mtimes: list[int] = []
    for path in paths:
        try:
            mtimes.append(int(path.stat().st_mtime_ns))
        except OSError:
            continue
    if mtimes:
        return str(max(mtimes))
    return "1"


def _normalize_route_value(key: str, value: str, season: int, date_str: str) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    parsed = urlparse(text)
    query_date = parse_qs(parsed.query).get("date", [""])[0].strip()
    resolved_date = query_date or date_str
    if key == "cards_url" and (text == "/" or parsed.path == "/"):
        return f"/mlb/cards?date={resolved_date}"
    if text.startswith("/api/season/"):
        return f"/mlb{text}"
    if parsed.path == "/betting-card":
        return f"/mlb/season/{int(season)}/betting-card?date={resolved_date}"
    if parsed.path.startswith("/season/"):
        return f"/mlb{parsed.path}?date={resolved_date}"
    if parsed.path == "/pitcher-top-props":
        return f"/mlb/pitcher-ladders?date={resolved_date}"
    if parsed.path == "/hitter-top-props":
        return f"/mlb/hitter-ladders?date={resolved_date}"
    return text


def _normalize_payload_routes(payload: Any, season: int, date_str: str) -> Any:
    if isinstance(payload, dict):
        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(key, str) and key.endswith(("_url", "_href")) and isinstance(value, str):
                normalized[key] = _normalize_route_value(key, value, season, date_str)
            else:
                normalized[key] = _normalize_payload_routes(value, season, date_str)
        return normalized
    if isinstance(payload, list):
        return [_normalize_payload_routes(item, season, date_str) for item in payload]
    return payload


def _format_start_time(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime("%-I:%M %p")
    except Exception:
        try:
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return ""


def _lead_market_row(markets: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("totals", "ml"):
        item = markets.get(key)
        if isinstance(item, dict):
            return item
    for key in ("pitcherProps", "hitterProps", "extraPitcherProps", "extraHitterProps"):
        rows = markets.get(key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    return row
    return None


def _starter_names_from_markets(markets: dict[str, Any]) -> dict[str, str]:
    starters = {"away": "", "home": ""}
    for key in ("pitcherProps", "extraPitcherProps"):
        rows = markets.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            team_side = str(row.get("team_side") or "").strip().lower()
            pitcher_name = str(row.get("pitcher_name") or "").strip()
            if team_side in starters and pitcher_name and not starters[team_side]:
                starters[team_side] = pitcher_name
    return starters


def _status_for_date(date_str: str, unresolved_n: int) -> dict[str, str]:
    if str(date_str) < central_today_iso() and int(unresolved_n) <= 0:
        return {"abstract": "Final", "detailed": "Final"}
    return {"abstract": "Preview", "detailed": "Scheduled"}


def _cards_available_for_date(date_str: str) -> bool:
    return str(date_str) in set(available_daily_summary_dates())


def _official_games_from_raw_payload(payload: dict[str, Any], date_str: str) -> list[dict[str, Any]]:
    games = payload.get("games") if isinstance(payload.get("games"), dict) else {}
    unresolved_n = int(((payload.get("summary") if isinstance(payload.get("summary"), dict) else {}) or {}).get("unresolved_n") or 0)
    out: list[dict[str, Any]] = []
    for raw_game_pk, raw_game in games.items():
        if not isinstance(raw_game, dict):
            continue
        markets = raw_game.get("markets") if isinstance(raw_game.get("markets"), dict) else {}
        lead_row = _lead_market_row(markets)
        if not isinstance(lead_row, dict):
            continue
        away_abbr = str(lead_row.get("away_abbr") or lead_row.get("away") or "Away").strip() or "Away"
        home_abbr = str(lead_row.get("home_abbr") or lead_row.get("home") or "Home").strip() or "Home"
        away_name = str(lead_row.get("away") or away_abbr).strip() or away_abbr
        home_name = str(lead_row.get("home") or home_abbr).strip() or home_abbr
        game_date = str(lead_row.get("commence_time") or lead_row.get("game_date") or "").strip()
        starters = _starter_names_from_markets(markets)
        out.append(
            {
                "game_pk": int(raw_game_pk),
                "game_date": game_date,
                "start_time": _format_start_time(game_date),
                "official_date": str(lead_row.get("date") or date_str),
                "status": _status_for_date(date_str, unresolved_n),
                "away": {"id": None, "abbr": away_abbr, "name": away_name},
                "home": {"id": None, "abbr": home_abbr, "name": home_name},
                "starter_names": {
                    "away": starters.get("away") or "TBD",
                    "home": starters.get("home") or "TBD",
                },
                "betting": raw_game,
            }
        )
    out.sort(key=lambda row: (str(row.get("game_date") or ""), int(row.get("game_pk") or 0)))
    return out


def _sum_stake_units(games: list[dict[str, Any]]) -> float:
    total = 0.0
    for game in games:
        betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
        markets = betting.get("markets") if isinstance(betting.get("markets"), dict) else {}
        rows: list[dict[str, Any]] = []
        for key in ("totals", "ml"):
            item = markets.get(key)
            if isinstance(item, dict):
                rows.append(item)
        for key in ("pitcherProps", "hitterProps"):
            bucket = markets.get(key)
            if isinstance(bucket, list):
                rows.extend(item for item in bucket if isinstance(item, dict))
        for row in rows:
            try:
                total += float(row.get("stake_u") or 0.0)
            except Exception:
                continue
    return round(total, 4)


def _staking_plan(games: list[dict[str, Any]], daily_budget: float) -> dict[str, float] | None:
    total_stake_units = _sum_stake_units(games)
    if total_stake_units <= 0:
        return {
            "daily_budget_dollars": round(float(daily_budget), 2),
            "total_stake_dollars": 0.0,
            "unit_dollars": 0.0,
        }
    unit_dollars = round(float(daily_budget) / total_stake_units, 2)
    return {
        "daily_budget_dollars": round(float(daily_budget), 2),
        "total_stake_dollars": round(unit_dollars * total_stake_units, 2),
        "unit_dollars": unit_dollars,
    }


def build_betting_card_page_context(
    season: int,
    selected_date: str,
    *,
    profile: str = "retuned",
    initial_manifest: dict[str, Any] | None = None,
    initial_day: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "season": int(season),
        "date": str(selected_date),
        "profile": str(profile or "retuned").strip().lower() or "retuned",
        "initial_manifest": initial_manifest,
        "initial_day": initial_day,
        "asset_version": source_betting_card_asset_version(),
        "rank_cards": [],
        "using_sample_data": False,
        "source_title": "MLB betting card unavailable",
        "empty_state": {
            "eyebrow": "MLB betting card",
            "title": "No stored MLB betting card was available for this date",
            "body": "The dedicated MLB betting-card page only renders stored season betting-card artifacts, and none were available for the requested date.",
            "list_items": [f"Requested date: {selected_date}"],
        },
    }


@lru_cache(maxsize=64)
def build_season_betting_card_manifest_payload(season: int, profile: str) -> dict[str, Any] | None:
    profile_slug = str(profile or "retuned").strip().lower() or "retuned"
    payload = load_json_file(season_betting_card_manifest_path(int(season), profile=profile_slug))
    if not isinstance(payload, dict):
        return None
    out = dict(payload)
    out["season"] = int(season)
    out["profile"] = profile_slug
    out["found"] = bool(out.get("days"))
    available_profiles = out.get("available_profiles")
    if not isinstance(available_profiles, list) or not available_profiles:
        out["available_profiles"] = [profile_slug]
    return _normalize_payload_routes(out, int(season), central_today_iso())


def _day_payload_from_frontend_doc(
    season: int,
    date_str: str,
    profile: str,
    frontend_doc: dict[str, Any],
    daily_budget: float,
) -> dict[str, Any]:
    betting = frontend_doc.get("betting") if isinstance(frontend_doc.get("betting"), dict) else {}
    games = frontend_doc.get("games") if isinstance(frontend_doc.get("games"), list) else []
    out = dict(betting)
    out.setdefault("season", int(season))
    out.setdefault("date", str(date_str))
    out["profile"] = str(out.get("profile") or profile or "retuned").strip().lower() or "retuned"
    out["found"] = bool(out.get("found", True))
    out["games"] = games
    out["cards_available"] = bool(frontend_doc.get("cards_available") if frontend_doc.get("cards_available") is not None else _cards_available_for_date(date_str))
    out["cards_url"] = frontend_doc.get("cards_url") or f"/mlb/cards?date={date_str}"
    out["staking_plan"] = _staking_plan(games, daily_budget)
    return _normalize_payload_routes(out, int(season), date_str)


def _day_payload_from_raw_doc(
    season: int,
    date_str: str,
    profile: str,
    raw_doc: dict[str, Any],
    daily_budget: float,
) -> dict[str, Any]:
    games = _official_games_from_raw_payload(raw_doc, date_str)
    out = dict(raw_doc)
    out.setdefault("season", int(season))
    out.setdefault("date", str(date_str))
    out["profile"] = str(out.get("profile") or profile or "retuned").strip().lower() or "retuned"
    out["found"] = bool(out.get("found", True))
    out["games"] = games
    out["cards_available"] = _cards_available_for_date(date_str)
    out["cards_url"] = f"/mlb/cards?date={date_str}" if out.get("cards_available") else None
    out["staking_plan"] = _staking_plan(games, daily_budget)
    return _normalize_payload_routes(out, int(season), date_str)


def _day_payload_from_manifest_row(
    season: int,
    date_str: str,
    profile: str,
    row: dict[str, Any],
    daily_budget: float,
) -> dict[str, Any]:
    games: list[dict[str, Any]] = []
    out: dict[str, Any] = {
        "season": int(season),
        "date": str(date_str),
        "profile": str(profile or "retuned").strip().lower() or "retuned",
        "available_profiles": [str(profile or "retuned").strip().lower() or "retuned"],
        "found": True,
        "source_kind": "season_manifest_row",
        "summary": {
            "date": str(date_str),
            "month": row.get("month"),
            "card_path": row.get("card_path"),
            "report_path": row.get("report_path"),
            "payload_path": row.get("payload_path"),
            "unresolved_n": int(row.get("unresolved_n") or 0),
            "warnings": row.get("warnings") if isinstance(row.get("warnings"), list) else [],
        },
        "cap_profile": row.get("cap_profile"),
        "selected_counts": row.get("selected_counts") if isinstance(row.get("selected_counts"), dict) else {},
        "results": row.get("results") if isinstance(row.get("results"), dict) else {},
        "cards_available": _cards_available_for_date(date_str),
        "cards_url": f"/mlb/cards?date={date_str}" if _cards_available_for_date(date_str) else None,
        "games": games,
        "staking_plan": _staking_plan(games, daily_budget),
    }
    return _normalize_payload_routes(out, int(season), date_str)


def build_season_betting_card_day_payload(
    season: int,
    date_str: str,
    profile: str,
    *,
    daily_budget: float = 500.0,
) -> dict[str, Any] | None:
    profile_slug = str(profile or "retuned").strip().lower() or "retuned"
    frontend_doc = load_json_file(season_frontend_day_path(int(season), date_str, profile=profile_slug))
    if isinstance(frontend_doc, dict) and frontend_doc.get("found") is not False:
        return _day_payload_from_frontend_doc(int(season), str(date_str), profile_slug, frontend_doc, float(daily_budget))

    raw_doc = load_json_file(season_betting_card_day_path(int(season), date_str, profile=profile_slug))
    if isinstance(raw_doc, dict):
        return _day_payload_from_raw_doc(int(season), str(date_str), profile_slug, raw_doc, float(daily_budget))

    manifest = build_season_betting_card_manifest_payload(int(season), profile_slug)
    if isinstance(manifest, dict):
        days = manifest.get("days") if isinstance(manifest.get("days"), list) else []
        for row in days:
            if isinstance(row, dict) and str(row.get("date") or "") == str(date_str):
                return _day_payload_from_manifest_row(int(season), str(date_str), profile_slug, row, float(daily_budget))
    return None


@lru_cache(maxsize=1)
def source_cards_css() -> str | None:
    return source_web_text("cards.css")


@lru_cache(maxsize=1)
def source_season_css() -> str | None:
    return source_web_text("season.css")


@lru_cache(maxsize=1)
def source_betting_card_js() -> str | None:
    content = source_web_text("betting_card.js")
    if content is None:
        return None
    content = content.replace("/api/season/", "/mlb/api/season/")
    content = content.replace("new URL(`/season/${encodeURIComponent(state.season)}?date=${encodeURIComponent(state.day.date)}`, window.location.origin)", "new URL(`/mlb/season/${encodeURIComponent(state.season)}?date=${encodeURIComponent(state.day.date)}`, window.location.origin)")
    content = content.replace('href="/?date=', 'href="/mlb/cards?date=')
    content = content.replace('`/?date=${encodeURIComponent(state.day.date)}`', '`/mlb/cards?date=${encodeURIComponent(state.day.date)}`')
    content = content.replace('`/season/${encodeURIComponent(state.season)}?date=${encodeURIComponent(state.day.date)}`', '`/mlb/season/${encodeURIComponent(state.season)}?date=${encodeURIComponent(state.day.date)}`')
    return content


@lru_cache(maxsize=1)
def source_back_to_top_js() -> str | None:
    return source_web_text("back_to_top.js")