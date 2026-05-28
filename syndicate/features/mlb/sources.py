from __future__ import annotations

import gzip
import json
import os
import re
from pathlib import Path
from typing import Any


_DATE_TOKEN_RE = re.compile(r"(\d{4})_(\d{2})_(\d{2})")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_roots() -> list[Path]:
    env_value = str(os.environ.get("SYNDICATE_MLB_SOURCE_ROOT") or "").strip()
    if env_value:
        return [Path(env_value).resolve()]

    data_root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    roots: list[Path] = []
    if data_root:
        roots.append((Path(data_root).resolve() / "mlb_source").resolve())
    roots.append((_repo_root() / "data" / "mlb_source").resolve())

    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        deduped.append(root)
    return deduped


def _resolve_data_path(*parts: str) -> Path:
    return default_mlb_source_root().joinpath("data", *parts)


def default_mlb_source_root() -> Path:
    for root in _source_roots():
        if root.exists():
            return root
    return _source_roots()[0]


def daily_artifact_path(selected_date: str, suffix: str = "") -> Path:
    filename = f"daily_summary_{selected_date.replace('-', '_')}{suffix}.json"
    return _resolve_data_path("daily", filename)


def available_daily_summary_dates() -> list[str]:
    dates: set[str] = set()
    pattern = "daily_summary_*.json"
    daily_dir = default_mlb_source_root() / "data" / "daily"
    if not daily_dir.exists():
        return []
    for path in daily_dir.glob(pattern):
        match = _DATE_TOKEN_RE.search(path.name)
        if not match or any(token in path.name for token in ("_hr_targets", "_rfi_targets", "_locked_policy")):
            continue
        dates.add(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")
    return sorted(dates)


def daily_ladders_path(selected_date: str) -> Path:
    filename = f"daily_ladders_{selected_date.replace('-', '_')}.json"
    return _resolve_data_path("daily", "ladders", filename)


def daily_rfi_targets_path(selected_date: str) -> Path:
    filename = f"daily_summary_{selected_date.replace('-', '_')}_rfi_targets.json"
    return _resolve_data_path("daily", filename)


def daily_top_props_path(selected_date: str) -> Path:
    filename = f"daily_top_props_{selected_date.replace('-', '_')}.json"
    return _resolve_data_path("daily", "top_props", filename)


def daily_snapshot_lineups_path(selected_date: str) -> Path:
    return _resolve_data_path("daily", "snapshots", selected_date, "lineups.json")


def daily_snapshot_file_path(selected_date: str, filename: str) -> Path:
    return _resolve_data_path("daily", "snapshots", selected_date, filename)


def daily_snapshot_meta_path(selected_date: str) -> Path:
    return daily_snapshot_file_path(selected_date, "meta.json")


def daily_snapshot_probables_path(selected_date: str) -> Path:
    return daily_snapshot_file_path(selected_date, "probables.json")


def daily_snapshot_injuries_path(selected_date: str) -> Path:
    return daily_snapshot_file_path(selected_date, "injuries_raw.json")


def daily_snapshot_oddsapi_game_lines_path(selected_date: str) -> Path:
    filename = f"oddsapi_game_lines_{selected_date.replace('-', '_')}.json"
    return daily_snapshot_file_path(selected_date, filename)


def daily_snapshot_oddsapi_hitter_props_path(selected_date: str) -> Path:
    filename = f"oddsapi_hitter_props_{selected_date.replace('-', '_')}.json"
    return daily_snapshot_file_path(selected_date, filename)


def daily_snapshot_oddsapi_pitcher_props_path(selected_date: str) -> Path:
    filename = f"oddsapi_pitcher_props_{selected_date.replace('-', '_')}.json"
    return daily_snapshot_file_path(selected_date, filename)


def market_refresh_history_oddsapi_path(selected_date: str, prefix: str) -> Path | None:
    slug = selected_date.replace('-', '_')
    filename = f"{prefix}_{slug}.json"
    history_root = default_mlb_source_root() / "data" / "market" / "oddsapi" / "refresh_history" / slug
    if not history_root.exists() or not history_root.is_dir():
        return None
    matches = sorted(path for path in history_root.glob(f"*/{filename}") if path.is_file())
    if matches:
        return matches[0]
    return None


def daily_ops_report_path(selected_date: str) -> Path:
    filename = f"daily_ops_{selected_date.replace('-', '_')}.json"
    return _resolve_data_path("daily", "ops", filename)


def daily_sim_artifact_path(selected_date: str, game_pk: int) -> Path | None:
    sims_dir = default_mlb_source_root() / "data" / "daily" / "sims" / selected_date
    if not sims_dir.exists():
        return None
    matches = sorted(sims_dir.glob(f"sim_*_pk{int(game_pk)}_*.json"))
    if matches:
        return matches[0]
    return None


def raw_feed_live_path(selected_date: str, game_pk: int) -> Path | None:
    season = str(selected_date or "").split("-", 1)[0].strip()
    if not season:
        return None
    day_dir = default_mlb_source_root() / "data" / "raw" / "statsapi" / "feed_live" / season / selected_date
    for suffix in (".json.gz", ".json"):
        candidate = day_dir / f"{int(game_pk)}{suffix}"
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def live_lens_report_path(selected_date: str) -> Path:
    filename = f"live_lens_report_{selected_date.replace('-', '_')}.json"
    return _resolve_data_path("live_lens", filename)


def live_prop_registry_path(selected_date: str) -> Path:
    filename = f"live_prop_registry_{selected_date.replace('-', '_')}.json"
    return _resolve_data_path("live_lens", "prop_registry", filename)


def season_betting_card_day_path(season: int, selected_date: str, *, profile: str = "retuned") -> Path:
    profile_slug = str(profile or "retuned").strip().lower() or "retuned"
    if profile_slug == "retuned":
        directory = "betting_day_payloads_retuned"
    else:
        directory = f"betting_day_payloads_{profile_slug}"
    slug = selected_date.replace('-', '_')
    if slug.startswith(f"{int(season)}_"):
        slug = slug[len(f"{int(season)}_"):]
    filename = f"season_betting_day_{int(season)}_{slug}.json"
    return _resolve_data_path("eval", "seasons", str(int(season)), directory, filename)


def season_eval_manifest_path(season: int) -> Path:
    return _resolve_data_path("eval", "seasons", str(int(season)), "season_eval_manifest.json")


def season_frontend_day_path(season: int, selected_date: str, *, profile: str = "retuned") -> Path:
    profile_slug = str(profile or "retuned").strip().lower() or "retuned"
    filename = f"season_day_{int(season)}_{selected_date.replace('-', '_')}_{profile_slug}.json"
    return _resolve_data_path("daily", "season_frontend", filename)


def load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_json_or_gz_file(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        opener = gzip.open if str(path).endswith(".gz") else Path.open
        with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[arg-type]
            payload = json.load(handle)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None