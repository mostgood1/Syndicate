from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse
from typing import Any

from syndicate.features.nba.sources import load_json
from syndicate.features.nba.sources import season_betting_card_day_path
from syndicate.features.nba.sources import season_betting_card_manifest_path


def _artifact_root() -> Path:
    env_value = str(os.environ.get("SYNDICATE_NBA_ARTIFACT_ROOT") or "").strip()
    if env_value:
        return Path(env_value).resolve()
    return (Path(__file__).resolve().parents[3] / "data" / "nba_source").resolve()


def source_web_text(filename: str) -> str | None:
    path = (_artifact_root() / "web" / filename).resolve()
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


@lru_cache(maxsize=1)
def source_betting_card_asset_version() -> str:
    paths = [
        _artifact_root() / "web" / name
        for name in ("betting-card-v2.css", "betting-card-v2.js")
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


def _normalize_route_value(key: str, value: str, date_str: str) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    parsed = urlparse(text)
    query_date = parse_qs(parsed.query).get("date", [""])[0].strip()
    resolved_date = query_date or date_str
    if key == "cards_url" and text == "/":
        return f"/nba/cards?date={resolved_date}"
    if key == "cards_url" and parsed.path == "/" and query_date:
        return f"/nba/cards?date={query_date}"
    if text.startswith("/api/season/"):
        return f"/nba{text}"
    if parsed.path == "/betting-card" and query_date:
        return f"/nba/cards?date={query_date}"
    if parsed.path == "/live-player-props-audit" and query_date:
        return f"/nba/season/{query_date[:4]}/live-lens?date={query_date}&profile=retuned"
    return text


def _normalize_payload_routes(payload: Any, date_str: str) -> Any:
    if isinstance(payload, dict):
        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(key, str) and key.endswith(("_url", "_href")) and isinstance(value, str):
                normalized[key] = _normalize_route_value(key, value, date_str)
            else:
                normalized[key] = _normalize_payload_routes(value, date_str)
        return normalized
    if isinstance(payload, list):
        return [_normalize_payload_routes(item, date_str) for item in payload]
    return payload


@lru_cache(maxsize=64)
def build_season_betting_card_manifest_payload(season: int, profile: str, selected_date: str) -> dict[str, Any] | None:
    payload = load_json(
        season_betting_card_manifest_path(int(season), profile=profile, requested_date=selected_date)
    )
    if not isinstance(payload, dict):
        return None
    return _normalize_payload_routes(payload, selected_date)


@lru_cache(maxsize=256)
def build_season_betting_card_day_payload(
    season: int,
    date_str: str,
    profile: str,
    *,
    include_prop_insights: bool = False,
) -> dict[str, Any] | None:
    payload = load_json(
        season_betting_card_day_path(
            int(season),
            date_str,
            profile=profile,
            include_prop_insights=include_prop_insights,
        )
    )
    if not isinstance(payload, dict):
        return None
    return _normalize_payload_routes(payload, date_str)


@lru_cache(maxsize=1)
def source_betting_card_css() -> str | None:
    return source_web_text("betting-card-v2.css")


@lru_cache(maxsize=1)
def source_betting_card_js() -> str | None:
    content = source_web_text("betting-card-v2.js")
    if content is None:
        return None
    content = re.sub(
        r"window\.location\.pathname\.match\(/\\/season\\/\(\\d\+\)\\/betting-card\\/\?\$/\)",
        r"window.location.pathname.match(/\\/nba\\/season\\/(\\d+)\\/betting-card\\/?$/)",
        content,
    )
    content = content.replace("/api/season/", "/nba/api/season/")
    content = content.replace("/betting-card?date=", "/nba/cards?date=")
    content = re.sub(
        r"root\.liveAuditLink\.href\s*=\s*`/live-player-props-audit\?date=\$\{encodeURIComponent\(state\.selectedDate\)\}`;",
        "root.liveAuditLink.href = `/nba/season/${encodeURIComponent(state.season)}/live-lens?date=${encodeURIComponent(state.selectedDate)}&profile=${encodeURIComponent(state.profile)}`;",
        content,
    )
    content = content.replace(
        "    nextUrl.searchParams.set('date', state.selectedDate);\n    nextUrl.searchParams.set('profile', state.profile);",
        "    nextUrl.searchParams.set('profile', state.profile);\n    nextUrl.searchParams.set('date', state.selectedDate);",
    )
    return content