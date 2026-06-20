from __future__ import annotations

from datetime import date
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.timezone import central_today_iso


def _source_roots() -> list[Path]:
    return preferred_artifact_roots(
        __file__,
        env_var="SYNDICATE_NCAAB_SOURCE_ROOT",
        local_dir_name="ncaab_source",
    )

def _mirror_path(*parts: str) -> Path:
    roots = _source_roots()
    for root in roots:
        candidate = root.joinpath("api", *parts)
        if candidate.exists():
            return candidate
    return roots[0].joinpath("api", *parts)


def _load_mirror_json(*parts: str) -> dict[str, Any] | None:
    path = _mirror_path(*parts)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _mirror_dates(filename: str) -> list[str]:
    payload = _load_mirror_json(filename) or {}
    dates = payload.get("dates") if isinstance(payload.get("dates"), list) else []
    out = [str(item).strip() for item in dates if str(item).strip()]
    latest = str(payload.get("latest") or "").strip()
    if latest and latest not in out:
        out.append(latest)
    return sorted(set(out))


def _missing_live_payload(kind: str, selected_date: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "date": selected_date,
        "count": 0,
        "message": message,
        "source": "local_mirror",
        "kind": kind,
    }

def available_dates() -> list[str]:
    payload = _load_mirror_json("display_prediction_dates.json") or {}
    dates = payload.get("dates") if isinstance(payload.get("dates"), list) else []
    out = [str(item).strip() for item in dates if str(item).strip()]
    latest = str(payload.get("latest") or "").strip()
    if latest and latest not in out:
        out.append(latest)
    return sorted(set(out))


def mirrored_available_dates() -> list[str]:
    return _mirror_dates("display_prediction_dates.json")


def latest_date() -> str:
    payload = _load_mirror_json("display_prediction_dates.json") or {}
    latest = str(payload.get("latest") or "").strip()
    if latest:
        return latest
    dates = available_dates()
    return dates[-1] if dates else ""


def default_date() -> str:
    return date.today().isoformat()


def schedule_dates() -> list[str]:
    payload = _load_mirror_json("dates.json") or {}
    dates = payload.get("dates") if isinstance(payload.get("dates"), list) else []
    return sorted({str(item).strip() for item in dates if str(item).strip()})


def mirrored_schedule_dates() -> list[str]:
    return _mirror_dates("dates.json")


def results_dates() -> list[str]:
    payload = _load_mirror_json("results_dates.json") or {}
    dates = payload.get("dates") if isinstance(payload.get("dates"), list) else []
    return sorted({str(item).strip() for item in dates if str(item).strip()})


def mirrored_results_dates() -> list[str]:
    return _mirror_dates("results_dates.json")


@lru_cache(maxsize=64)
def results_by_date_payload(selected_date: str) -> dict[str, Any] | None:
    return _load_mirror_json("results_by_date", f"results_{selected_date}.json")


@lru_cache(maxsize=64)
def mirrored_results_by_date_payload(selected_date: str) -> dict[str, Any] | None:
    return _load_mirror_json("results_by_date", f"results_{selected_date}.json")


def season_for_date(selected_date: str) -> int:
    text = str(selected_date or "").strip()
    if len(text) >= 7:
        try:
            year = int(text[:4])
            month = int(text[5:7])
            return year if month >= 11 else year - 1
        except Exception:
            pass
    return 2025


def season_dates(season: int) -> list[str]:
    start = f"{int(season)}-11-01"
    end = f"{int(season) + 1}-04-30"
    all_dates = set(schedule_dates()) | set(available_dates()) | set(results_dates())
    return sorted(date_str for date_str in all_dates if start <= date_str <= end)


def mirrored_season_dates(season: int) -> list[str]:
    start = f"{int(season)}-11-01"
    end = f"{int(season) + 1}-04-30"
    all_dates = set(mirrored_schedule_dates()) | set(mirrored_available_dates()) | set(mirrored_results_dates())
    return sorted(date_str for date_str in all_dates if start <= date_str <= end)


def default_season_date(season: int) -> str:
    today_value = central_today_iso()
    if season_for_date(today_value) == int(season):
        return today_value
    dates = season_dates(season)
    return dates[-1] if dates else f"{int(season)}-11-01"


@lru_cache(maxsize=64)
def recommendations_payload(selected_date: str) -> dict[str, Any] | None:
    return _load_mirror_json("recommendations", f"recommendations_{selected_date}.json")


@lru_cache(maxsize=64)
def mirrored_recommendations_payload(selected_date: str) -> dict[str, Any] | None:
    return _load_mirror_json("recommendations", f"recommendations_{selected_date}.json")


def live_state_payload(selected_date: str, ttl: int = 12) -> dict[str, Any] | None:
    mirrored = _load_mirror_json("live_state", f"live_state_{selected_date}.json")
    if mirrored is not None:
        return mirrored
    return _missing_live_payload(
        "live_state",
        selected_date,
        "Mirror live-state payload unavailable for the selected date. Refresh the NCAAB source mirror before using live lens.",
    )


def live_lines_payload(selected_date: str, event_ids: list[str], ttl: int = 20) -> dict[str, Any] | None:
    cleaned = [str(item).strip() for item in event_ids if str(item).strip()]
    mirrored = _load_mirror_json("live_lines", f"live_lines_{selected_date}.json")
    if mirrored is not None:
        lines = mirrored.get("lines") if isinstance(mirrored.get("lines"), dict) else {}
        if cleaned:
            filtered = {event_id: lines.get(event_id) for event_id in cleaned if event_id in lines}
            payload = dict(mirrored)
            payload["count"] = len(filtered)
            payload["lines"] = filtered
            return payload
        return mirrored
    return {
        **_missing_live_payload(
            "live_lines",
            selected_date,
            "Mirror live-lines payload unavailable for the selected date. Refresh the NCAAB source mirror before using live lens.",
        ),
        "lines": {},
    }


def live_lens_tuning_payload(ttl: int = 3600) -> dict[str, Any] | None:
    mirrored = _load_mirror_json("live_lens_tuning.json")
    if mirrored is not None:
        return mirrored
    return {
        "status": "error",
        "message": "Mirror live-lens tuning payload unavailable. Refresh the NCAAB source mirror before using live lens.",
        "source": "local_mirror",
        "pace_hi": None,
        "pps_hi": None,
    }


def build_module_links(selected_date: str, active_label: str) -> list[dict[str, Any]]:
    season = season_for_date(selected_date)
    links = [
        ("Cards", f"/ncaab/cards?date={selected_date}"),
        ("Betting Card", f"/ncaab/season/{season}/betting-card?date={selected_date}"),
        ("Live Lens", f"/ncaab/live-lens?date={selected_date}"),
        ("Daily Archive", f"/ncaab/archive?date={selected_date}"),
        ("Season Review", f"/ncaab/season/{season}?date={selected_date}"),
        ("Hub", "/ncaab/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]