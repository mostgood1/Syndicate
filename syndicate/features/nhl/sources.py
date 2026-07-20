from __future__ import annotations

from datetime import date
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
import re
import unicodedata

from syndicate.features.shared.formatters import format_num
from syndicate.features.shared.formatters import format_pct
from syndicate.features.shared.formatters import format_signed_price
from syndicate.features.shared.odds_control_plane import current_odds_root_for_sport
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.team_branding import read_team_branding_snapshot
from syndicate.features.shared.team_branding import team_branding_index_by_abbreviation
from syndicate.features.shared.timezone import central_today
from syndicate.features.shared.timezone import central_today_iso


def _source_roots() -> list[Path]:
    return preferred_source_roots(
        __file__,
        env_var="SYNDICATE_NHL_SOURCE_ROOT",
        local_dir_name="nhl_source",
    )


def _artifact_roots() -> list[Path]:
    return preferred_artifact_roots(
        __file__,
        env_var="SYNDICATE_NHL_SOURCE_ROOT",
        local_dir_name="nhl_source",
    )


def default_nhl_source_root() -> Path:
    return _source_roots()[0]


def _data_roots() -> list[Path]:
    return [current_odds_root_for_sport("nhl")]


def default_nhl_data_root() -> Path:
    return _data_roots()[0]


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _resolve_processed_path(*parts: str) -> Path:
    roots = _data_roots()
    if roots:
        return roots[0] / "processed" / Path(*parts)
    return Path(__file__).resolve().parents[3] / "data" / "nhl_source" / "data" / "processed" / Path(*parts)


def processed_path(*parts: str) -> Path:
    return _resolve_processed_path(*parts)


def scoreboard_snapshot_path(date_str: str) -> Path:
    roots = _data_roots()
    if roots:
        return roots[0] / "odds" / "games" / f"date={date_str}" / "scoreboard.csv"
    return Path(__file__).resolve().parents[3] / "data" / "nhl_source" / "data" / "odds" / "games" / f"date={date_str}" / "scoreboard.csv"


def team_odds_snapshot_path(date_str: str) -> Path:
    roots = _data_roots()
    if roots:
        return roots[0] / "odds" / "team" / f"date={date_str}" / "oddsapi.csv"
    return Path(__file__).resolve().parents[3] / "data" / "nhl_source" / "data" / "odds" / "team" / f"date={date_str}" / "oddsapi.csv"


def props_lines_snapshot_path(date_str: str) -> Path:
    roots = _data_roots()
    if roots:
        return roots[0] / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.csv"
    return Path(__file__).resolve().parents[3] / "data" / "nhl_source" / "data" / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.csv"


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
    roots = _data_roots()
    if not roots:
        return []

    root = roots[0]
    processed = root / "processed"
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

    scoreboard_root = root / "odds" / "games"
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
    return date.today().isoformat()


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


@lru_cache(maxsize=1)
def _team_branding_index() -> dict[str, Any]:
    root = _source_roots()[0]
    path = root / "source_artifacts" / "data" / "processed" / "team_branding" / "nhl_team_branding.csv"
    return team_branding_index_by_abbreviation(read_team_branding_snapshot(path))


# ESPN's own abbreviation occasionally differs from this module's
# team_abbreviation() (e.g. Utah's franchise rename settled on "UTAH" at
# ESPN vs. this module's existing "UTA") -- translated here only for the
# branding lookup, not touching team_abbreviation()'s own established output.
_ESPN_BRANDING_ABBR_ALIASES: dict[str, str] = {
    "UTA": "UTAH",
}


def team_branding(value: Any) -> Any | None:
    abbr = team_abbreviation(value)
    if not abbr:
        return None
    index = _team_branding_index()
    upper = abbr.upper()
    return index.get(upper) or index.get(_ESPN_BRANDING_ABBR_ALIASES.get(upper, upper))


def team_logo_url(value: Any) -> str | None:
    branding = team_branding(value)
    if branding and branding.logo_url:
        return branding.logo_url
    abbr = team_abbreviation(value)
    if not abbr:
        return None
    return f"https://assets.nhle.com/logos/nhl/svg/{abbr}_dark.svg"


def team_primary_color(value: Any) -> str | None:
    branding = team_branding(value)
    return branding.primary_color if branding else None


def team_secondary_color(value: Any) -> str | None:
    branding = team_branding(value)
    return branding.secondary_color if branding else None


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