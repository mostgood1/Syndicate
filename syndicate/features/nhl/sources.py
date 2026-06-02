from __future__ import annotations

from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any
import re
import unicodedata

from syndicate.features.shared.formatters import format_num
from syndicate.features.shared.formatters import format_pct
from syndicate.features.shared.formatters import format_signed_price
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.timezone import central_today
from syndicate.features.shared.timezone import central_today_iso


def _source_roots() -> list[Path]:
    return preferred_source_roots(
        __file__,
        env_var="SYNDICATE_NHL_SOURCE_ROOT",
        local_dir_name="nhl_source",
    )


def default_nhl_source_root() -> Path:
    return _source_roots()[0]


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _resolve_processed_path(*parts: str) -> Path:
    roots = _source_roots()
    candidates = [(root / "data" / "processed" / Path(*parts)).resolve() for root in reversed(roots)]
    best = _first_existing_path(candidates)
    if best is not None:
        return best
    return candidates[0]


def processed_path(*parts: str) -> Path:
    return _resolve_processed_path(*parts)


def scoreboard_snapshot_path(date_str: str) -> Path:
    roots = _source_roots()
    candidates = [
        (root / "data" / "odds" / "games" / f"date={date_str}" / "scoreboard.csv").resolve()
        for root in reversed(roots)
    ]
    best = _first_existing_path(candidates)
    if best is not None:
        return best
    return candidates[0]


def props_lines_snapshot_path(date_str: str) -> Path:
    roots = _source_roots()
    candidates = [
        (root / "data" / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.csv").resolve()
        for root in reversed(roots)
    ]
    best = _first_existing_path(candidates)
    if best is not None:
        return best
    return candidates[0]


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return central_today()


def _candidate_paths(date_str: str) -> list[Path]:
    return [
        processed_path(f"recommendations_sim_{date_str}.csv"),
        processed_path(f"recommendations_{date_str}.csv"),
    ]


def recommendation_path(date_str: str) -> Path:
    for path in _candidate_paths(date_str):
        if path.exists():
            return path
    return _candidate_paths(date_str)[0]


def slate_summaries() -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    root = default_nhl_source_root()
    processed = root / "data" / "processed"
    if processed.exists():
        for path in sorted(processed.glob("predictions_*.csv")):
            if path.stem.startswith("predictions_sim_"):
                continue
            date_str = path.stem.replace("predictions_", "", 1)
            seen.setdefault(date_str, {"date": date_str, "path": str(path), "kind": "Predictions snapshot"})
        for path in sorted(processed.glob("recommendations_sim_*.csv")):
            date_str = path.stem.replace("recommendations_sim_", "", 1)
            seen[date_str] = {"date": date_str, "path": str(path), "kind": "Sim snapshot"}
        for path in sorted(processed.glob("recommendations_*.csv")):
            if path.stem.startswith("recommendations_sim_"):
                continue
            date_str = path.stem.replace("recommendations_", "", 1)
            seen.setdefault(date_str, {"date": date_str, "path": str(path), "kind": "Direct snapshot"})

    scoreboard_root = root / "data" / "odds" / "games"
    if scoreboard_root.exists():
        for path in sorted(scoreboard_root.glob("date=*/scoreboard.csv")):
            parent_name = path.parent.name
            if not parent_name.startswith("date="):
                continue
            date_str = parent_name.replace("date=", "", 1)
            seen.setdefault(date_str, {"date": date_str, "path": str(path), "kind": "Archived scoreboard"})

    return sorted(seen.values(), key=lambda item: item["date"])


def available_dates() -> list[str]:
    return [item["date"] for item in slate_summaries()]


def default_date() -> str:
    return central_today_iso()


def format_price(value: Any) -> str:
    return format_signed_price(value)


_TEAM_NAME_TO_ABBR = {
    "anaheim ducks": "ANA",
    "utah mammoth": "UTA",
    "utah hockey club": "UTA",
    "utah hc": "UTA",
    "arizona coyotes": "ARI",
    "boston bruins": "BOS",
    "buffalo sabres": "BUF",
    "carolina hurricanes": "CAR",
    "columbus blue jackets": "CBJ",
    "calgary flames": "CGY",
    "chicago blackhawks": "CHI",
    "colorado avalanche": "COL",
    "dallas stars": "DAL",
    "detroit red wings": "DET",
    "edmonton oilers": "EDM",
    "florida panthers": "FLA",
    "los angeles kings": "LAK",
    "minnesota wild": "MIN",
    "montreal canadiens": "MTL",
    "new jersey devils": "NJD",
    "nashville predators": "NSH",
    "new york islanders": "NYI",
    "new york rangers": "NYR",
    "ottawa senators": "OTT",
    "philadelphia flyers": "PHI",
    "pittsburgh penguins": "PIT",
    "san jose sharks": "SJS",
    "seattle kraken": "SEA",
    "st. louis blues": "STL",
    "st louis blues": "STL",
    "tampa bay lightning": "TBL",
    "toronto maple leafs": "TOR",
    "vancouver canucks": "VAN",
    "vegas golden knights": "VGK",
    "winnipeg jets": "WPG",
    "washington capitals": "WSH",
}


def _normalize_team_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    normalized = normalized.lower()
    return re.sub(r"\s+", " ", normalized).strip()


def team_abbreviation(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = _normalize_team_name(raw)
    mapped = _TEAM_NAME_TO_ABBR.get(normalized)
    if mapped:
        return mapped
    upper = raw.upper()
    if 2 <= len(upper) <= 3 and upper.isalpha():
        return upper
    return upper[:3]


def team_logo_url(value: Any) -> str | None:
    abbr = team_abbreviation(value)
    if not abbr:
        return None
    return f"https://assets.nhle.com/logos/nhl/svg/{abbr}_dark.svg"


def market_label(value: Any) -> str:
    key = str(value or "").strip().upper()
    labels = {
        "PL": "Puck line",
        "ML": "Moneyline",
        "TOTAL": "Total",
        "TOTALS": "Total",
    }
    return labels.get(key, key.title() or "Bet")


def build_module_links(selected_date: str, active_label: str, *, season: int | None = None) -> list[dict[str, Any]]:
    resolved_season = int(season) if season is not None else parse_iso_date(selected_date).year
    links = [
        ("Cards", f"/nhl/cards?date={selected_date}"),
        ("Betting Card", f"/nhl/season/{resolved_season}/betting-card?date={selected_date}"),
        ("Picks", f"/nhl/picks?date={selected_date}"),
        ("Live Lens", f"/nhl/live-lens?date={selected_date}"),
        ("Daily Archive", f"/nhl/archive?date={selected_date}"),
        ("Hub", "/nhl/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]