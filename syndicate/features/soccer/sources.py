from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.timezone import central_today_iso


LEAGUE_DISPLAY_NAMES: dict[str, str] = {
    "epl": "EPL",
    "la_liga": "La Liga",
    "bundesliga": "Bundesliga",
    "serie_a": "Serie A",
    "ligue_1": "Ligue 1",
    "mls": "MLS",
    "eredivisie": "Eredivisie",
    "primeira_liga": "Primeira Liga",
    "championship": "Championship",
    "belgian_pro_league": "Belgian Pro League",
}

DEFAULT_LEAGUE = "epl"


def league_display_name(league: str) -> str:
    return LEAGUE_DISPLAY_NAMES.get(str(league or "").strip().lower(), str(league or "").upper())


def normalize_league(league: str | None) -> str:
    text = str(league or "").strip().lower()
    return text if text in LEAGUE_DISPLAY_NAMES else DEFAULT_LEAGUE


def _source_roots() -> list[Path]:
    return preferred_source_roots(
        __file__,
        env_var="SYNDICATE_SOCCER_SOURCE_ROOT",
        local_dir_name="soccer_source",
    )


def _api_root(league: str) -> Path:
    return _source_roots()[0] / normalize_league(league) / "api"


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def recommendations_path(league: str, selected_date: str) -> Path:
    return _api_root(league) / "recommendations" / f"recommendations_{selected_date}.json"


@lru_cache(maxsize=256)
def recommendations_payload(league: str, selected_date: str) -> dict[str, Any] | None:
    return load_json(recommendations_path(league, selected_date))


def live_state_path(league: str, selected_date: str) -> Path:
    return _api_root(league) / "live_state" / f"live_state_{selected_date}.json"


def live_state_payload(league: str, selected_date: str) -> dict[str, Any] | None:
    # Not cached: this file is overwritten by the live poller every cycle,
    # unlike the once-per-date recommendations artifact below.
    return load_json(live_state_path(league, selected_date))


def date_index_path(league: str) -> Path:
    return _api_root(league) / "display_prediction_dates.json"


def available_dates(league: str) -> list[str]:
    payload = load_json(date_index_path(league)) or {}
    dates = payload.get("dates") if isinstance(payload.get("dates"), list) else []
    out = sorted({str(item).strip() for item in dates if str(item).strip()})
    return out


def default_date(league: str) -> str:
    dates = available_dates(league)
    today = central_today_iso()
    if today in dates:
        return today
    return dates[-1] if dates else today


def build_module_links(league: str, selected_date: str, active_label: str) -> list[dict[str, Any]]:
    league = normalize_league(league)
    links = [
        ("Cards", f"/soccer/{league}/cards?date={selected_date}"),
        ("Props", f"/soccer/{league}/props?date={selected_date}"),
        ("Live Lens", f"/soccer/{league}/live-lens?date={selected_date}"),
        ("Daily Archive", f"/soccer/{league}/archive?date={selected_date}"),
        ("Hub", "/soccer/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]
