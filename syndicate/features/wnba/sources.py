from __future__ import annotations

from datetime import date
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.timezone import central_today
from syndicate.features.shared.timezone import central_today_iso


def _source_roots() -> list[Path]:
    roots = preferred_source_roots(
        __file__,
        env_var="SYNDICATE_WNBA_SOURCE_ROOT",
        local_dir_name="wnba_source",
    )
    expanded: list[Path] = []
    seen: set[Path] = set()
    candidate_roots = [*roots, *(root / "source_artifacts" for root in roots)]
    for candidate in candidate_roots:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            expanded.append(resolved)
    return expanded


def default_wnba_source_root() -> Path:
    return _source_roots()[0]


def processed_path(filename: str) -> Path:
    roots = _source_roots()
    for root in roots:
        candidate = root / "data" / "processed" / filename
        if candidate.exists():
            return candidate
    return roots[0] / "data" / "processed" / filename


def live_snapshot_path(filename: str) -> Path:
    roots = _source_roots()
    for root in roots:
        candidate = root / "data" / "processed" / "live_snapshots" / filename
        if candidate.exists():
            return candidate
    return roots[0] / "data" / "processed" / "live_snapshots" / filename


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return central_today()


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def available_dates() -> list[str]:
    dates: set[str] = set()
    for root in _source_roots():
        processed_dir = root / "data" / "processed"
        if not processed_dir.exists():
            continue
        for pattern in ("game_cards_*.csv", "recommendations_slate_*.json"):
            for path in sorted(processed_dir.glob(pattern)):
                if path.stem.startswith("game_cards_"):
                    dates.add(path.stem.replace("game_cards_", "", 1))
                elif path.stem.startswith("recommendations_slate_"):
                    dates.add(path.stem.replace("recommendations_slate_", "", 1))
    return sorted(dates)


def default_date() -> str:
    return central_today_iso()


def default_date_for_season(season: int) -> str:
    today_value = central_today_iso()
    if today_value.startswith(f"{int(season)}-"):
        return today_value
    season_str = str(int(season))
    season_dates = [value for value in available_dates() if str(value).startswith(f"{season_str}-")]
    if season_dates:
        return season_dates[-1]
    return default_date()


def format_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number:.1f}".rstrip("0").rstrip(".")


def format_pct(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number * 100:.1f}%"


def format_signed_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{format_num(number)}"


def format_moneyline(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    rounded = int(round(number))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def market_label(value: Any) -> str:
    code = str(value or "").strip().lower()
    labels = {
        "pts": "PTS",
        "reb": "REB",
        "ast": "AST",
        "pra": "PRA",
        "pa": "PTS+AST",
        "pr": "PTS+REB",
        "ra": "REB+AST",
        "threes": "3PM",
        "blk": "BLK",
        "stl": "STL",
        "bs": "BLK+STL",
    }
    return labels.get(code, code.upper() or "PROP")


def build_module_links(selected_date: str, active_label: str, *, season: int | None = None) -> list[dict[str, Any]]:
    resolved_season = int(season) if season is not None else parse_iso_date(selected_date).year
    links = [
        ("Cards", f"/wnba/cards?date={selected_date}"),
        ("Betting Card", f"/wnba/season/{resolved_season}/betting-card?date={selected_date}"),
        ("Picks", f"/wnba/picks?date={selected_date}"),
        ("Props", f"/wnba/props?date={selected_date}"),
        ("Live Lens", f"/wnba/live-lens?date={selected_date}"),
        ("Daily Archive", f"/wnba/archive?date={selected_date}"),
        ("Hub", "/wnba/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]
