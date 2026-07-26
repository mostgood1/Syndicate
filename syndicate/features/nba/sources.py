from __future__ import annotations

from functools import lru_cache
import os
from datetime import date
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.odds_control_plane import current_odds_root_for_sport
from syndicate.features.shared.timezone import central_today
from syndicate.features.shared.timezone import central_today_iso


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _artifact_roots() -> list[Path]:
    roots = preferred_source_roots(
        __file__,
        env_var="SYNDICATE_NBA_SOURCE_ROOT",
        local_dir_name="nba_source",
    )
    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def artifact_processed_root() -> Path:
    return current_odds_root_for_sport("nba")


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def processed_path(filename: str) -> Path:
    return artifact_processed_root() / filename


def live_snapshot_path(filename: str) -> Path:
    return artifact_processed_root() / "live_snapshots" / filename


def _processed_candidate_path(filename: str, *, root: Path | None = None) -> Path:
    roots = _artifact_roots()
    base_root = root or (roots[0] if roots else (_repo_root() / "data" / "nba_source"))
    return base_root / "data" / "processed" / filename


def _resolve_processed_candidates(filenames: list[str]) -> Path:
    roots = _artifact_roots()
    if not roots:
        return _processed_candidate_path(filenames[0], root=None)
    candidates: list[Path] = []
    for root in roots:
        for filename in filenames:
            candidates.append(root / "data" / "processed" / filename)
    best = _first_existing_path(candidates)
    if best is not None:
        return best
    if roots:
        return roots[0] / "data" / "processed" / filenames[0]
    return _processed_candidate_path(filenames[0], root=None)


def _artifact_roots_signature() -> tuple[tuple[str, int], ...]:
    signature: list[tuple[str, int]] = []
    for root in _artifact_roots():
        processed_dir = root / "data" / "processed"
        try:
            mtime_ns = int(processed_dir.stat().st_mtime_ns) if processed_dir.exists() else 0
        except OSError:
            mtime_ns = 0
        signature.append((str(processed_dir).lower(), mtime_ns))
    return tuple(signature)


@lru_cache(maxsize=8)
def _available_dates_cached(signature: tuple[tuple[str, int], ...]) -> tuple[str, ...]:
    dates: set[str] = set()
    roots = _artifact_roots()
    if not roots:
        return ()

    for root in roots:
        processed_dir = root / "data" / "processed"
        if not processed_dir.exists():
            continue
        for pattern in ("recommendations_slate_*.json", "game_cards_*.csv", "cards_sim_detail_*.json"):
            for path in processed_dir.glob(pattern):
                match = _DATE_PATTERN.search(path.stem)
                if match:
                    dates.add(match.group(1))
    return tuple(sorted(dates))


def season_betting_card_manifest_path(season: int, *, profile: str = "retuned", requested_date: str | None = None) -> Path:
    profile_slug = str(profile or "retuned").strip().lower() or "retuned"
    filenames: list[str] = []
    if requested_date:
        filenames.append(f"season_betting_card_manifest_{int(season)}_{profile_slug}_{str(requested_date).strip()}.json")
    filenames.append(f"season_betting_card_manifest_{int(season)}_{profile_slug}.json")
    return _resolve_processed_candidates(filenames)


def season_betting_card_day_path(
    season: int,
    selected_date: str,
    *,
    profile: str = "retuned",
    include_prop_insights: bool = False,
) -> Path:
    profile_slug = str(profile or "retuned").strip().lower() or "retuned"
    suffix = "_insights.json" if include_prop_insights else ".json"
    filename = f"season_betting_card_day_{int(season)}_{profile_slug}_{str(selected_date).strip()}{suffix}"
    return _resolve_processed_candidates([filename])


_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")


def available_dates() -> list[str]:
    return list(_available_dates_cached(_artifact_roots_signature()))


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


def format_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number:.1f}".rstrip("0").rstrip(".")


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


def build_module_links(selected_date: str, active_label: str) -> list[dict[str, Any]]:
    season = parse_iso_date(selected_date).year
    links = [
        ("Cards", "Cards", f"/nba/cards?date={selected_date}"),
        ("Betting Card", "Betting Card", f"/nba/season/{season}/betting-card?profile=retuned&date={selected_date}"),
        ("Picks", "Picks", f"/nba/picks?date={selected_date}"),
        ("Props", "Prop Ladders", f"/nba/prop-ladders?date={selected_date}"),
        ("Live Lens", "Live Lens", f"/nba/season/{season}/live-lens?date={selected_date}&profile=retuned"),
        ("Archive", "Daily Archive", f"/nba/archive?date={selected_date}"),
        ("Hub", "Hub", "/nba/hub"),
    ]
    return [
        {"label": display_label, "href": href, "active": internal_label == active_label}
        for internal_label, display_label, href in links
    ]


def betting_card_href(selected_date: str, *, profile: str = "retuned") -> str:
    season = parse_iso_date(selected_date).year
    resolved_profile = str(profile or "retuned").strip().lower() or "retuned"
    return f"/nba/season/{season}/betting-card?profile={resolved_profile}&date={selected_date}"


def live_lens_href(selected_date: str, *, season: int | None = None) -> str:
    resolved_season = int(season) if season is not None else parse_iso_date(selected_date).year
    return f"/nba/season/{resolved_season}/live-lens?date={selected_date}"
