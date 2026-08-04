from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.week_calendar import shard_key_for_week
from syndicate.features.shared.week_calendar import week_for_date


_WEEKLY_SPORTS = {"nfl", "ncaaf"}
_WEEKLY_SHARD_KEY_RE = re.compile(r"^(?P<season>\d{4})_wk(?P<week>\d+)$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_odds_root_for_sport(sport_slug: str) -> Path:
    slug = str(sport_slug or "").strip().lower()
    if slug == "nba":
        roots = preferred_source_roots(__file__, env_var="SYNDICATE_NBA_SOURCE_ROOT", local_dir_name="nba_source")
        if roots:
            return (roots[0] / "data" / "processed").resolve()
        return (Path(__file__).resolve().parents[3] / "data" / "nba_source" / "data" / "processed").resolve()
    if slug == "wnba":
        roots = preferred_artifact_roots(__file__, env_var="SYNDICATE_WNBA_SOURCE_ROOT", local_dir_name="wnba_source")
        if roots:
            return (roots[0] / "data" / "processed").resolve()
        return (Path(__file__).resolve().parents[3] / "data" / "wnba_source" / "data" / "processed").resolve()
    if slug == "nhl":
        roots = preferred_source_roots(__file__, env_var="SYNDICATE_NHL_SOURCE_ROOT", local_dir_name="nhl_source")
        if roots:
            return (roots[0] / "data").resolve()
        return (Path(__file__).resolve().parents[3] / "data" / "nhl_source" / "data").resolve()
    raise ValueError(f"Unsupported sport for current odds root resolution: {sport_slug!r}")


def odds_control_plane_root() -> Path:
    return reports_root() / "odds_control_plane"


def odds_control_plane_snapshot_path() -> Path:
    return odds_control_plane_root() / "latest.json"


def shared_odds_history_root() -> Path:
    return reports_root() / "odds_control_plane" / "odds_history"


def odds_history_roots_for_sport(sport_slug: str) -> list[Path]:
    slug = str(sport_slug or "").strip().lower()
    roots: list[Path] = [shared_odds_history_root() / slug]
    data_root_path = data_root()
    sport_root = (data_root_path / f"{slug}_source").resolve()
    if sport_root not in roots:
        roots.append(sport_root)
    return roots


def odds_history_paths_for_sport(sport_slug: str, shard_key: str) -> list[Path]:
    slug = str(sport_slug or "").strip().lower()
    paths: list[Path] = []
    shared_path = shared_odds_history_root() / slug / f"{shard_key}.json"
    paths.append(shared_path)
    for root in odds_history_roots_for_sport(slug):
        if root == shared_path.parent:
            continue
        for candidate in (
            root / "artifacts" / slug / "odds_history" / f"{shard_key}.json",
            root / "tracking" / "odds_history" / f"{shard_key}.json",
        ):
            if candidate not in paths:
                paths.append(candidate)
    return paths


def _read_odds_history_candidate(path: Path) -> dict[str, Any] | None:
    """Pure local-disk read, no keyvalue involved. odds_history shards are
    routinely tens of MB on a real slate (measured live 2026-07-28: 51.1MB
    for one MLB day) -- not an occasional overflow of the keyvalue store's
    8MB ceiling, the ordinary case always exceeding it. Per explicit user
    direction the same day ("the file size limit is frankly unrealistic
    from keyvalue - we need this to be artifact written/artifact read
    based"), the write side
    (odds_refresh_tracking._sync_odds_history_for_refresh /
    _write_odds_history_artifact) never attempts a keyvalue write for this
    data at all -- it writes straight to local disk and publishes for
    cross-service reach. This read matches: publish_hot_artifact is what
    gets a worker's write onto web's own local disk for this function to
    then pick up, not a keyvalue round-trip.
    """
    try:
        if not path.is_file():
            return None
        candidate = json.loads(path.read_text(encoding="utf-8-sig"))
        return candidate if isinstance(candidate, dict) else None
    except Exception:
        return None


def load_odds_history_payload_for_sport(sport_slug: str, shard_key: str, *, cache: dict[tuple[str, str], dict[str, Any] | None] | None = None) -> dict[str, Any] | None:
    """Freshest available copy of a sport's odds_history shard.

    Was first-hit over odds_history_paths_for_sport's fixed precedence
    (shared -> artifacts -> tracking). That silently preferred a STALE copy
    over a current one, because the paths do not all refresh through the same
    route: the shared copy (reports/odds_control_plane/...) is deliberately
    not in HOT_ARTIFACT_PATTERNS and so can never cross services, while the
    artifacts copy does. On any service that both writes a partial shard
    locally and pulls the full one from web, the local partial won on
    precedence alone and the pulled file was never read.

    Confirmed live 2026-08-04 on refresh-worker, minutes after the streamed
    odds_history pull started working: STREAM_PULL_OK wrote 19,798,176 bytes
    of the 3,436-market MLB shard, and the very next board build still logged
    odds_history_input entry_count=611 -- the stale shared copy, shadowing it.
    Every MLB board candidate stayed at history_points=0.

    Newest mtime wins instead. On the writing service all three copies are
    written together by _sync_odds_history_for_refresh, so they tie and the
    choice is a no-op; on a pulling service the freshly pulled copy is newer,
    which is exactly the intent. Ordering is only ever a tie-break by
    precedence, never a reason to read older data.
    """
    cache_key = (str(sport_slug or "").strip().lower(), str(shard_key or ""))
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    freshest_path: Path | None = None
    freshest_mtime: float | None = None
    for path in odds_history_paths_for_sport(sport_slug, shard_key):
        try:
            if not path.is_file():
                continue
            mtime = path.stat().st_mtime
        except Exception:
            continue
        # Strictly-greater keeps the existing precedence order as the
        # tie-break when copies were written together.
        if freshest_mtime is None or mtime > freshest_mtime:
            freshest_path = path
            freshest_mtime = mtime

    payload = _read_odds_history_candidate(freshest_path) if freshest_path is not None else None
    if cache is not None:
        cache[cache_key] = payload
    return payload


def odds_history_path_status_for_sport(sport_slug: str, shard_key: str) -> dict[str, Any]:
    candidate_paths = odds_history_paths_for_sport(sport_slug, shard_key)
    active_path = None
    active_payload: dict[str, Any] | None = None
    for candidate_path in candidate_paths:
        payload = read_json_file(candidate_path)
        if isinstance(payload, dict):
            active_path = candidate_path
            active_payload = payload
            break

    return {
        "sport": str(sport_slug or "").strip().lower(),
        "shard_key": shard_key,
        "candidate_paths": [str(path) for path in candidate_paths],
        "active_path": str(active_path) if active_path is not None else None,
        "has_payload": bool(active_payload),
        "source_precedence": ["shared_history", "artifact_history", "tracking_history"],
    }


def _current_tracked_week(sport_slug: str, root: Path) -> tuple[int, int] | None:
    if str(sport_slug or "").strip().lower() != "nfl":
        return None
    for candidate in (root / "current_week.json", root / "source_artifacts" / "current_week.json"):
        payload = read_json_file(candidate)
        if isinstance(payload, dict):
            try:
                return int(payload["season"]), int(payload["week"])
            except Exception:
                continue
    return None


def resolve_current_shard_key(sport_slug: str, date_str: str | None, *, source_root: Path | None = None) -> str:
    slug = str(sport_slug or "").strip().lower()
    date_str = str(date_str or "").strip() or datetime.now(timezone.utc).date().isoformat()
    if slug not in _WEEKLY_SPORTS:
        return date_str
    root = source_root or odds_history_roots_for_sport(slug)[-1]
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        target_date = None
    if target_date is not None:
        resolved = week_for_date(slug, target_date, source_root=root)
        if resolved is not None:
            return shard_key_for_week(*resolved)
    tracked = _current_tracked_week(slug, root)
    if tracked is not None:
        return shard_key_for_week(*tracked)
    return date_str


def list_available_shard_keys(sport_slug: str) -> list[str]:
    slug = str(sport_slug or "").strip().lower()
    keys: set[str] = set()
    shared_dir = shared_odds_history_root() / slug
    if shared_dir.exists():
        for path in shared_dir.glob("*.json"):
            keys.add(path.stem)
    for root in odds_history_roots_for_sport(slug):
        if root == shared_dir:
            continue
        for base in (root / "artifacts" / slug / "odds_history", root / "tracking" / "odds_history"):
            if base.exists():
                for path in base.glob("*.json"):
                    keys.add(path.stem)
    return sorted(keys)


def odds_history_lookback_shard_keys(sport_slug: str, shard_key: str, lookback: int) -> list[str]:
    slug = str(sport_slug or "").strip().lower()
    if lookback <= 0:
        return []
    if slug in _WEEKLY_SPORTS:
        match = _WEEKLY_SHARD_KEY_RE.match(shard_key)
        if not match:
            return []
        season = int(match.group("season"))
        week = int(match.group("week"))
        keys: list[str] = []
        for _ in range(lookback):
            week -= 1
            if week < 1:
                # Week counts vary by season/sport; this is a best-effort
                # lookback across a season boundary, not an exact calendar
                # walk, since no schedule is consulted here.
                season -= 1
                week = 22
            keys.append(shard_key_for_week(season, week))
        return keys
    try:
        current = datetime.strptime(shard_key, "%Y-%m-%d").date()
    except Exception:
        return []
    return [(current - timedelta(days=offset)).isoformat() for offset in range(1, lookback + 1)]


def build_odds_control_plane_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    results = summary.get("results") if isinstance(summary, dict) else []
    sport_snapshots: list[dict[str, Any]] = []
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        sport = str(result.get("sport") or "").strip().lower()
        shard_keys = list_available_shard_keys(sport)
        odds_history_shards = [odds_history_path_status_for_sport(sport, shard_key) for shard_key in shard_keys]
        sport_snapshots.append(
            {
                "sport": sport,
                "ok": bool(result.get("ok")),
                "generation_mode": result.get("generation_mode"),
                "ingestion_mode": result.get("ingestion_mode"),
                "source_repo": result.get("source_repo"),
                "source_root_env_var": result.get("source_root_env_var"),
                "artifact_paths": list(result.get("artifact_paths") or []),
                "post_refresh_ok": (result.get("sport_manifest") or {}).get("payload", {}).get("metadata", {}).get("post_refresh_ok") if isinstance(result.get("sport_manifest"), dict) else None,
                "mirror_ok": (result.get("sport_manifest") or {}).get("payload", {}).get("metadata", {}).get("mirror_ok") if isinstance(result.get("sport_manifest"), dict) else None,
                "odds_history": {
                    "sport": sport,
                    "shard_count": len(shard_keys),
                    "shards": odds_history_shards,
                    "source_precedence": ["shared_history", "artifact_history", "tracking_history"],
                },
            }
        )

    return {
        "generated_at": _utc_now(),
        "date": summary.get("date") if isinstance(summary, dict) else None,
        "phase": summary.get("phase") if isinstance(summary, dict) else None,
        "execution_mode": summary.get("execution_mode") if isinstance(summary, dict) else None,
        "dry_run": bool(summary.get("dry_run")) if isinstance(summary, dict) else False,
        "publish_parity": summary.get("publish_parity") if isinstance(summary, dict) else None,
        "sports": sport_snapshots,
        "source_precedence": ["shared_history", "artifact_history", "tracking_history"],
        "summary_ok": bool(summary.get("ok")) if isinstance(summary, dict) else False,
    }


def write_odds_control_plane_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    snapshot = build_odds_control_plane_snapshot(summary)
    snapshot_path = odds_control_plane_snapshot_path()
    write_json_file(snapshot_path, snapshot)
    return {
        "path": str(snapshot_path),
        "payload": snapshot,
    }


def load_odds_control_plane_snapshot() -> dict[str, Any] | None:
    payload = read_json_file(odds_control_plane_snapshot_path())
    return payload if isinstance(payload, dict) else None