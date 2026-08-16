from __future__ import annotations

import ast
import argparse
import contextlib
import csv
import datetime as dt
import errno
import importlib
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.basketball_props_edges import export_props_edges_local
from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local
from syndicate.features.shared.basketball_props_recommendations import export_props_recommendations_local
from syndicate.features.shared.basketball_props_smart_sim import _to_tricode_local
from syndicate.features.shared.refresh_state_store import build_input_hash
from syndicate.features.shared.refresh_state_store import path_fingerprint
from syndicate.features.shared.refresh_state_store import read_json_file as _keyvalue_read_json_file
from syndicate.features.shared.refresh_state_store import record_refresh_state
from syndicate.features.shared.refresh_state_store import should_recompute
from syndicate.features.shared.refresh_state_store import write_json_file as _keyvalue_write_json_file
from syndicate.features.shared.timezone import central_date_from_iso

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.atomic_artifact_write import atomic_write_csv



def _json_ready(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _refresh_state_scope_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(Path(path))


def _source_app_fallback_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_NBA_SOURCE_APP_FALLBACK") or "").strip().lower() in {"1", "true", "yes", "on"}


def _copy_if_exists(source_path: str | None, destination_path: Path) -> bool:
    source_text = str(source_path or "").strip()
    if not source_text:
        return False
    source = Path(source_text)
    if not source.exists() or not source.is_file():
        return False
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    _copy_file_with_fallback(source, destination_path)
    return True


def _copy_matching_files(*, source_directory: Path, pattern: str, destination_directory: Path) -> list[str]:
    if not source_directory.exists() or not source_directory.is_dir():
        return []
    copied: list[str] = []
    for source in sorted(source_directory.glob(pattern)):
        if not source.is_file():
            continue
        destination = destination_directory / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_with_fallback(source, destination)
        copied.append(str(destination))
    return copied


def _copy_existing_processed_artifact(*, source_root: Path, processed_root: Path, file_name: str) -> str | None:
    source = source_root / "data" / "processed" / file_name
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / file_name
    try:
        if source.resolve() == destination.resolve():
            return str(destination)
    except Exception:
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_file_with_fallback(source, destination)
    return str(destination)


def _copy_file_with_fallback(source: Path, destination: Path) -> None:
    try:
        if source.resolve() == destination.resolve():
            return
    except Exception:
        pass
    try:
        shutil.copy2(source, destination)
        return
    except OSError as exc:
        if exc.errno != errno.EINVAL:
            raise
    source_fd = os.open(str(source), os.O_RDONLY)
    try:
        destination_fd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        try:
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                os.write(destination_fd, chunk)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)
    try:
        shutil.copystat(source, destination)
    except OSError:
        pass


def _copy_existing_live_lens_artifact(*, source_root: Path, file_name: str, destinations: tuple[tuple[Path, str | None], ...]) -> dict[str, str]:
    candidates = (
        source_root / "data" / "processed" / file_name,
        source_root / "data" / "live_lens" / file_name,
    )
    source = next((path for path in candidates if path.exists() and path.is_file()), None)
    if source is None:
        return {}
    copied: dict[str, str] = {}
    raw = source.read_bytes()
    for out_path, copied_key in destinations:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        if copied_key:
            copied[copied_key] = str(out_path)
    return copied


def _copy_existing_live_snapshot_artifact(*, source_root: Path, file_name: str, destination: Path) -> str | None:
    source = source_root / "data" / "processed" / "live_snapshots" / file_name
    if not source.exists() or not source.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.resolve() == destination.resolve():
            return str(destination)
    except Exception:
        pass
    shutil.copy2(source, destination)
    return str(destination)


def _read_live_snapshot_payload(path: Path) -> dict[str, object] | None:
    # The production writer below always overwrites with a single record, so
    # try the keyvalue-aware reader first (cross-service consistent) before
    # falling back to the old multi-line-JSONL local read, which only
    # matters for files an external source app's own exporter appended to.
    # Mirrors the identical fix already applied to WNBA's copy of this
    # function (scripts/refresh_wnba_oddsapi_props.py) -- same bug, same
    # root cause: live-odds-worker computes this snapshot and the syndicate
    # web service (a separate disk on Render) is what actually serves the
    # request that reads it back, so a plain local-disk read/write here was
    # invisible cross-service no matter how fresh the write was.
    keyvalue_record = _keyvalue_read_json_file(path)
    if isinstance(keyvalue_record, dict):
        payload = keyvalue_record.get("payload") if isinstance(keyvalue_record.get("payload"), dict) else None
        if isinstance(payload, dict):
            return payload
        if isinstance(keyvalue_record.get("games"), list):
            return keyvalue_record

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except Exception:
            continue
        payload = record.get("payload") if isinstance(record, dict) and isinstance(record.get("payload"), dict) else None
        if isinstance(payload, dict):
            return payload
        if isinstance(record, dict) and isinstance(record.get("games"), list):
            return record
    return None


def _write_live_snapshot_payload(path: Path, payload: dict[str, object]) -> bool:
    if not isinstance(payload, dict):
        return False
    # Written cross-service through the keyvalue store: the live-odds-worker
    # refresh loop and the on-demand web request path run on different
    # Render services with separate local disks, so a plain local write here
    # would be invisible to whichever service didn't just write it.
    record = {"payload": payload}
    _keyvalue_write_json_file(path, record)
    return True


def _payload_has_snapshot_content(kind: str, payload: dict[str, object] | None) -> bool:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    if not games:
        return False
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind == "live_player_lens":
        return any(isinstance(game, dict) and bool(game.get("rows")) for game in games)
    if normalized_kind == "live_player_boxscore":
        # A non-empty players list alone isn't enough here -- every player
        # can legitimately show 0 pts/reb/ast and no minutes right at
        # tip-off, which made a payload captured in that instant look
        # "already has content" forever, so the refresh loop kept reusing it
        # instead of re-fetching once the game was actually underway. Same
        # bug found and fixed on WNBA's copy of this check
        # (scripts/refresh_wnba_oddsapi_props.py) 2026-07-30.
        return any(
            isinstance(game, dict)
            and any(
                isinstance(player, dict)
                and (
                    any((_float_or_none(player.get(key)) or 0.0) > 0 for key in ("pts", "reb", "ast", "threes_made"))
                    or str(player.get("mp") or "").strip().lower() not in ("", "0", "0:00", "00:00", "--", "-")
                )
                for player in (game.get("players") or [])
            )
            for game in games
        )
    if normalized_kind == "live_lines":
        return any(
            isinstance(game, dict)
            and (
                bool(game.get("found"))
                or (isinstance(game.get("lines"), dict) and bool(game.get("lines")))
            )
            for game in games
        )
    if normalized_kind == "live_pbp_stats":
        return any(
            isinstance(game, dict)
            and any(game.get(key) is not None for key in ("pbp_recent", "pbp_attempts", "pbp_possessions", "pbp_quarters"))
            for game in games
        )
    return True


def _live_lines_interval_count(payload: dict[str, object] | None) -> int:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    interval_count = 0
    for game in games:
        if not isinstance(game, dict):
            continue
        lines = game.get("lines") if isinstance(game.get("lines"), dict) else {}
        for key in ("period_totals", "period_spreads"):
            values = lines.get(key) if isinstance(lines.get(key), dict) else {}
            interval_count += sum(1 for value in values.values() if _float_or_none(value) is not None)
    return interval_count


def _prefer_live_lines_payload(current: dict[str, object] | None, candidate: dict[str, object] | None) -> dict[str, object] | None:
    if not _payload_has_snapshot_content("live_lines", candidate):
        return current
    if not _payload_has_snapshot_content("live_lines", current):
        return candidate
    if _live_lines_interval_count(candidate) > _live_lines_interval_count(current):
        return candidate
    return current


def _snapshot_artifact_has_meaningful_content(kind: str, path: Path | None) -> bool:
    payload = _read_live_snapshot_payload(path) if path is not None else None
    return _payload_has_snapshot_content(kind, payload)


def _build_local_live_snapshot_payload(*, kind: str, date_str: str, event_ids: list[str]) -> dict[str, object] | None:
    normalized_kind = str(kind or "").strip().lower()
    try:
        from syndicate.features.nba.cards import build_live_lines_payload
        from syndicate.features.nba.cards import build_live_pbp_stats_payload
        from syndicate.features.nba.cards import build_live_player_boxscore_payload
        from syndicate.features.nba.cards import build_live_player_lens_payload
        from syndicate.features.nba.cards import build_live_state_payload

        if normalized_kind == "live_state":
            return build_live_state_payload(date_str, ttl=12, allow_stored_date_fallback=True)
        if normalized_kind == "live_pbp_stats":
            return build_live_pbp_stats_payload(date_str, event_ids, ttl=20, allow_stored_date_fallback=True)
        if normalized_kind == "live_lines":
            return build_live_lines_payload(date_str, event_ids, ttl=20, include_period_totals=True, allow_stored_date_fallback=True)
        if normalized_kind == "live_player_boxscore":
            return build_live_player_boxscore_payload(date_str, event_ids, ttl=20, allow_stored_date_fallback=True)
        if normalized_kind == "live_player_lens":
            return build_live_player_lens_payload(date_str, event_ids, ttl=20, allow_stored_date_fallback=True)
    except Exception:
        return None
    return None


def _build_bundle_local_live_snapshot_payload(*, kind: str, date_str: str, event_ids: list[str], processed_root: Path) -> dict[str, object] | None:
    bundle_root = processed_root.parents[1]
    env_name = "SYNDICATE_NBA_ARTIFACT_ROOT"
    previous_value = os.environ.get(env_name)
    os.environ[env_name] = str(bundle_root)
    try:
        try:
            from syndicate.features.nba import cards as cards_module

            cache_clear = getattr(getattr(cards_module, "_local_live_snapshot_payload", None), "cache_clear", None)
            if callable(cache_clear):
                cache_clear()
        except Exception:
            cards_module = None
        payload = _build_local_live_snapshot_payload(kind=kind, date_str=date_str, event_ids=event_ids)
        try:
            cache_clear = getattr(getattr(cards_module, "_local_live_snapshot_payload", None), "cache_clear", None)
            if callable(cache_clear):
                cache_clear()
        except Exception:
            pass
        return payload
    finally:
        if previous_value is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = previous_value


def _boxscores_history_sources(*, source_root: Path, processed_root: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for root in (source_root / "data" / "processed", processed_root):
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.glob("boxscores_*.csv")):
            try:
                key = str(path.resolve())
            except Exception:
                key = str(path)
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            candidates.append(path)
    return candidates


def _refresh_boxscores_history_artifact(*, source_root: Path, processed_root: Path) -> str | None:
    sources = _boxscores_history_sources(source_root=source_root, processed_root=processed_root)
    if not sources:
        existing = source_root / "data" / "processed" / "boxscores_history.csv"
        if not existing.exists() or not existing.is_file():
            return None
        destination = processed_root / existing.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(existing, destination)
        return str(destination)

    rows: list[dict[str, str]] = []
    header_order: list[str] = []
    seen_rows: set[tuple[str, ...]] = set()
    for source in sources:
        with source.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                continue
            for field in reader.fieldnames:
                if field not in header_order:
                    header_order.append(field)
            for row in reader:
                normalized = {field: str((row or {}).get(field, "") or "") for field in header_order}
                row_key = tuple(normalized.get(field, "") for field in header_order)
                if row_key in seen_rows:
                    continue
                seen_rows.add(row_key)
                rows.append(normalized)

    if not header_order:
        return None

    destination = processed_root / "boxscores_history.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header_order)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in header_order})
    return str(destination)


def _export_team_advanced_stats_artifacts(*, source_root: Path, processed_root: Path) -> list[str]:
    copied: list[str] = []
    source_processed = source_root / "data" / "processed"
    if not source_processed.exists() or not source_processed.is_dir():
        return copied
    for source in sorted(source_processed.glob("team_advanced_stats_*.csv")):
        if not source.is_file():
            continue
        destination = processed_root / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_with_fallback(source, destination)
        copied.append(str(destination))
    return copied


def _count_csv_rows_quick(path: Path | None) -> int:
    try:
        if path is None or not path.exists() or not path.is_file():
            return 0
        newline_count = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                newline_count += chunk.count(b"\n")
        return max(0, int(newline_count - 1))
    except Exception:
        return 0


def _count_cards_sim_detail_games(path: Path | None) -> int:
    try:
        if path is None or not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return 0
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        games = payload.get("games") if isinstance(payload, dict) else None
        if not isinstance(games, list):
            return 0
        count = 0
        for row in games:
            if not isinstance(row, dict):
                continue
            sim = row.get("sim") if isinstance(row.get("sim"), dict) else {}
            players = sim.get("players") if isinstance(sim.get("players"), dict) else {}
            home_players = players.get("home") if isinstance(players.get("home"), list) else []
            away_players = players.get("away") if isinstance(players.get("away"), list) else []
            if len(home_players) + len(away_players) > 0:
                count += 1
        return int(count)
    except Exception:
        return 0


def _count_matching_files(source_directory: Path | None, pattern: str) -> int:
    try:
        if source_directory is None or not source_directory.exists() or not source_directory.is_dir():
            return 0
        return int(sum(1 for path in source_directory.glob(pattern) if path.is_file()))
    except Exception:
        return 0


def _path_has_meaningful_content(path: Path | None) -> bool:
    try:
        if path is None or not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return False
        if path.suffix.lower() == ".csv":
            return _count_csv_rows_quick(path) > 0
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            return False
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                return bool(payload)
            if isinstance(payload, list):
                return len(payload) > 0
        return True
    except Exception:
        return False


def _append_log(log_file: Path, line: str) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8", errors="ignore") as out:
            out.write(f"[{dt.datetime.utcnow().isoformat(timespec='seconds')}] {line.rstrip()}\n")
    except Exception:
        pass


def _refresh_step_input_hash(*, source_root: Path, processed_root: Path, date_str: str, do_edges: bool, do_export: bool, artifact_root: Path | None = None) -> str:
    smart_sim_paths = sorted(processed_root.glob(f"smart_sim_{date_str}_*.json"))
    return build_input_hash(
        {
            "step": "nba_refresh",
            "date": date_str,
            "do_edges": bool(do_edges),
            "do_export": bool(do_export),
            "artifact_root": str(artifact_root) if artifact_root is not None else None,
            "inputs": [
                path_fingerprint(source_root / "data" / "raw" / f"odds_nba_player_props_{date_str}.csv"),
                path_fingerprint(processed_root / f"oddsapi_player_props_{date_str}.csv"),
                path_fingerprint(processed_root / f"game_cards_{date_str}.csv"),
                path_fingerprint(processed_root / f"cards_sim_detail_{date_str}.json"),
                *[path_fingerprint(path) for path in smart_sim_paths],
            ],
        }
    )


def _materialize_processed_snapshot_alias(*, processed_root: Path, date_str: str, snapshot_path: Path, log_file: Path | None = None) -> tuple[Path, int, str | None]:
    alias_path = processed_root / f"oddsapi_player_props_{date_str}.csv"
    try:
        if not snapshot_path.exists() or not snapshot_path.is_file() or snapshot_path.stat().st_size <= 0:
            return alias_path, 0, None
        alias_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot_path, alias_path)
        rows = int(_count_csv_rows_quick(alias_path))
        if log_file is not None:
            _append_log(log_file, f"Materialized processed OddsAPI props snapshot alias: {alias_path} (rows={rows})")
        return alias_path, rows, None
    except Exception as exc:
        if log_file is not None:
            _append_log(log_file, f"Failed to materialize processed OddsAPI props snapshot alias: {exc}")
        return alias_path, 0, str(exc)


def _source_python(source_root: Path) -> str:
    override = str(os.environ.get("SYNDICATE_PYTHON_EXE") or "").strip()
    if override and Path(override).exists() and "windowsapps" not in override.lower():
        return override
    if sys.executable and Path(sys.executable).exists() and "windowsapps" not in str(sys.executable).lower():
        return sys.executable
    for installed in (
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "python.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311-arm64" / "python.exe",
    ):
        if installed.exists():
            return str(installed)
    candidates = [
        source_root / ".venv" / "Scripts" / "python.exe",
        source_root / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists() and "windowsapps" not in str(candidate).lower():
            return str(candidate)
    if sys.executable and Path(sys.executable).exists():
        return sys.executable
    return "python"


def _local_python() -> str:
    override = str(os.environ.get("SYNDICATE_PYTHON_EXE") or "").strip()
    if override and Path(override).exists() and "windowsapps" not in override.lower():
        return override
    if sys.executable and Path(sys.executable).exists() and "windowsapps" not in str(sys.executable).lower():
        return sys.executable
    for installed in (
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "python.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311-arm64" / "python.exe",
    ):
        if installed.exists():
            return str(installed)
    return "python"


def _local_worker_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _owned_snapshot_cli_args(*, date_str: str, out_path: Path, regions: str, bookmakers: str, markets: str) -> list[str]:
    args = [
        _local_python(),
        str(REPO_ROOT / "scripts" / "fetch_basketball_oddsapi_props_local.py"),
        "--league",
        "nba",
        "--date",
        date_str,
        "--out",
        str(out_path),
        "--regions",
        str(regions or "us").strip() or "us",
    ]
    if bookmakers:
        args.extend(["--bookmakers", bookmakers])
    if markets:
        args.extend(["--markets", markets])
    return args


def _source_worker_env(source_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    src_dir = str(source_root / "src")
    existing = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = src_dir if not existing else f"{src_dir}{os.pathsep}{existing}"
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("OMP_THREAD_LIMIT", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("NUMEXPR_NUM_THREADS", "1")
    return env


def _vendor_code_root(package_name: str) -> Path:
    # The hosted "source_root" for a sport (e.g. SYNDICATE_NBA_SOURCE_ROOT on
    # Render) is a persistent *data* disk, not a code checkout -- the vendored
    # nba_betting/wnba_betting package only ever lives in this repo's own
    # vendor/<package>_repo checkout, so subprocess invocations of it must use
    # this root for cwd/PYTHONPATH regardless of where source_root resolves.
    override = str(os.environ.get(f"SYNDICATE_VENDOR_ROOT_{package_name.upper()}") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return REPO_ROOT / "vendor" / f"{package_name}_repo"


def _games_history_max_date(path: Path) -> str | None:
    try:
        if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return None
        import pandas as pd

        frame = pd.read_csv(path, usecols=["date"])
        if frame.empty:
            return None
        max_date = pd.to_datetime(frame["date"], errors="coerce").max()
        if pd.isna(max_date):
            return None
        return max_date.date().isoformat()
    except Exception:
        return None


def _games_history_is_stale(path: Path, *, date_str: str, stale_days: int = 30) -> bool:
    max_date_text = _games_history_max_date(path)
    if not max_date_text:
        return True
    try:
        target = dt.date.fromisoformat(str(date_str))
        newest = dt.date.fromisoformat(max_date_text)
    except Exception:
        return True
    return (target - newest).days > int(stale_days)


def _features_are_behind_history(
    feature_candidates: tuple[Path, ...], raw_candidates: tuple[Path, ...]
) -> bool:
    """True when the derived features are older than the history they derive from.

    THE WNBA TWIN OF THIS GATE SHIPPED THE DEFECT (`#351`). It asked
    `not any(path.exists() and size > 0)` -- "is there a features file" -- so a
    features file built from ONE season kept the rebuild from ever running while
    a full 10-season history sat underneath it. The model reads the FEATURES, so
    the fetch could succeed perfectly and the model still train on 2017, with
    nothing anywhere reporting a problem.

    NBA is NOT currently affected -- raw and features both end 2026-04-12,
    measured 2026-08-11 -- precisely because its season is over and neither side
    is moving. The gate becomes wrong the moment the raw history advances, which
    is every day of a live season. Fixed here rather than after it bites.

    Fails CLOSED: an unreadable date on either side returns False and leaves the
    old behaviour, because a rebuild is ~20 minutes of subprocess time and must
    not fire on every tick.
    """
    features_max = next(
        (_games_history_max_date(path) for path in feature_candidates if _games_history_max_date(path)),
        None,
    )
    history_max = next(
        (_games_history_max_date(path) for path in raw_candidates if _games_history_max_date(path)),
        None,
    )
    if not features_max or not history_max:
        return False
    return features_max < history_max


def _games_history_fetch_years_needed(path: Path, *, bootstrap_years: int = 10, incremental_years: int = 1) -> int:
    """Decide how many seasons `fetch --years N` needs to re-walk.

    Mirrors refresh_wnba_oddsapi_props.py. Prior seasons are final and
    immutable, so once the file already has broad multi-season coverage
    there's nothing to gain from re-walking them -- only the current
    season can have new games. Matters most on the WNBA twin, where
    there's no bulk history endpoint and a --years 10 walk measured out
    to ~80 minutes against a 45-minute subprocess timeout, but applies
    here too if NBA's LeagueGameLog ever gets blocked and it falls back
    to the same day-by-day path.
    """
    try:
        import pandas as pd

        if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return bootstrap_years
        frame = pd.read_csv(path, usecols=["season"]) if _csv_has_column(path, "season") else None
        if frame is None or frame.empty:
            return bootstrap_years
        distinct_seasons = frame["season"].nunique(dropna=True)
        return incremental_years if int(distinct_seasons) >= 3 else bootstrap_years
    except Exception:
        return bootstrap_years


def _csv_has_column(path: Path, column: str) -> bool:
    try:
        import pandas as pd

        header = pd.read_csv(path, nrows=0)
        return column in header.columns
    except Exception:
        return False


def _seed_games_history_from_checkout_if_fresher(
    *, raw_path: Path, package_name: str, date_str: str, feature_candidates: tuple[Path, ...], log_file: Path
) -> bool:
    """Heal a missing/stale raw games history from the vendored checkout copy.

    Mirrors refresh_wnba_oddsapi_props.py: the checkout ships a committed
    full-history games_nba_api.csv, a reliable offline fallback when the
    network fetch fails or returns a partial file (a --years 10 fetch on a
    cold/stale start can exceed the pipeline's subprocess timeout -- see
    _games_history_fetch_years_needed). Only overwrites when the checkout's
    newest game date is strictly fresher, and invalidates derived features
    files so they rebuild from the new data.
    """
    if not _games_history_is_stale(raw_path, date_str=date_str):
        return False
    checkout_path = _vendor_code_root(package_name) / "data" / "raw" / "games_nba_api.csv"
    checkout_max = _games_history_max_date(checkout_path)
    if not checkout_max:
        return False
    current_max = _games_history_max_date(raw_path)
    if current_max and checkout_max <= current_max:
        return False
    try:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_with_fallback(checkout_path, raw_path)
    except Exception as exc:
        _append_log(log_file, f"games history seed from checkout failed: {exc}")
        return False
    _append_log(
        log_file,
        f"Seeded games history from vendored checkout: {checkout_path} -> {raw_path} "
        f"(checkout max date {checkout_max}, previous max date {current_max or 'none'})",
    )
    for stale_feature_path in feature_candidates:
        try:
            if stale_feature_path.exists():
                stale_feature_path.unlink()
                _append_log(log_file, f"Invalidated stale derived features {stale_feature_path.name} after history seed")
        except Exception:
            pass
    return True


def _run_source_processed_export(
    *,
    source_root: Path,
    package_name: str,
    command_name: str,
    date_str: str,
    expected_file_name: str,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> tuple[str | None, int]:
    existing_path = source_root / "data" / "processed" / expected_file_name
    if _path_has_meaningful_content(existing_path):
        return str(existing_path), 0

    code_root = _vendor_code_root(package_name)
    rc = _run_to_file(
        [
            _source_python(code_root),
            "-m",
            f"{package_name}.cli",
            command_name,
            "--date",
            date_str,
        ],
        log_file,
        cwd=code_root,
        env=_source_worker_env(code_root),
        timeout_s=15 * 60,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )

    if _path_has_meaningful_content(existing_path):
        return str(existing_path), int(rc)

    _append_log(log_file, f"{command_name} did not create expected artifact: {existing_path}")
    return None, int(rc)


def _ensure_source_game_cards_export(
    *,
    source_root: Path,
    package_name: str,
    date_str: str,
    processed_root: Path,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> tuple[int, Path | None]:
    _run_source_subprocess_cli_command(
        source_root=source_root,
        package_name=package_name,
        command_parts=["export-game-cards", "--date", date_str],
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
        timeout_s=20 * 60,
    )
    return _build_local_game_cards_artifact(
        source_root=source_root,
        processed_root=processed_root,
        date_str=date_str,
        log_file=log_file,
    )


def _recommendation_tier(*, market: str, ev_value: float | None, edge_value: float | None) -> str:
    if str(market or "").strip().upper() == "ML":
        if ev_value is None:
            return "Low"
        if ev_value >= 0.04:
            return "High"
        if ev_value >= 0.02:
            return "Medium"
        return "Low"
    if edge_value is None:
        return "Low"
    abs_edge = abs(float(edge_value))
    if abs_edge >= 4.0:
        return "High"
    if abs_edge >= 2.0:
        return "Medium"
    return "Low"


def _float_or_none(value: object) -> float | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _mean_or_none(values: list[float]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return None
    return float(sum(cleaned) / len(cleaned))


def _structured_literal_or_none(value: object) -> object | None:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return None


def _american_price_to_prob(value: object) -> float | None:
    number = _float_or_none(value)
    if number is None or number == 0:
        return None
    if number > 0:
        return 100.0 / (number + 100.0)
    return abs(number) / (abs(number) + 100.0)


# The None-skip that replaced `... or 0.5` is SILENT by construction: it writes
# win_prob=None where it used to fabricate a 0.5, and emits nothing. That left
# the fix UNMEASURABLE in production -- grepping the log for it returns zero
# whether it is working or has simply never been exercised, which is a fact
# about the emitter rather than about the code. NBA compounds it: the sport is
# out of season, so this producer has written no artifact at all today.
#
# `_clamp_probability` is the right place to count because it is a DEDICATED
# chokepoint -- every win_prob in this file passes through it and nothing else
# does, so the denominator is exactly "win_prob values computed". A new site
# added later is counted automatically.
_WIN_PROB_STATS: dict[str, int] = {"rows": 0, "null_no_price": 0}
# Set once from argv so the emitter in `__main__`'s `finally` can name the slate
# it counted. A reading with no date cannot be aged against the run that made it.
_WIN_PROB_RUN_DATE: dict[str, str | None] = {"date": None}


def _clamp_probability(value: float | None) -> float | None:
    _WIN_PROB_STATS["rows"] += 1
    if value is None:
        _WIN_PROB_STATS["null_no_price"] += 1
        return None
    return max(0.0, min(1.0, float(value)))


_WIN_PROB_LAST: dict[str, int] = {"rows": 0, "null_no_price": 0}


def _emit_win_prob_build(build: str, tag: str = "refresh_nba_oddsapi_props") -> None:
    """Per-ARTIFACT delta, because the exit emit can be hours late.

    `_emit_win_prob_stats` fires from `finally`, so it only prints when the
    process ends -- correct for a total, useless for a first reading: measured
    2026-08-16, the producer was still mid-run 70+ minutes after deploy and had
    emitted nothing. This fires as each artifact lands, so the branch is
    observable at the moment it is exercised.

    Deltas, not running totals: consecutive builds otherwise print a growing
    number that cannot be attributed to the artifact that caused it.
    """
    rows = _WIN_PROB_STATS["rows"] - _WIN_PROB_LAST["rows"]
    nulls = _WIN_PROB_STATS["null_no_price"] - _WIN_PROB_LAST["null_no_price"]
    _WIN_PROB_LAST.update(_WIN_PROB_STATS)
    pct = (100.0 * nulls / rows) if rows else 0.0
    print(
        f"[{tag}] WIN_PROB_NULL_NO_PRICE build={build} null={nulls} rows={rows} pct={pct:.1f}",
        flush=True,
    )


def _emit_win_prob_stats(tag: str = "refresh_nba_oddsapi_props") -> None:
    """Report the null rate, not a bare count -- through a channel that is read.

    A count with no denominator cannot be read: `null=0` means "the fix held" if
    rows is large and "nothing ran" if rows is 0, and those need opposite
    responses. Emitted on EVERY run including the all-zero one.

    **THE PRINT BELOW IS NOT THE CHANNEL**, for the reason recorded in the WNBA
    twin: `refresh_odds_sources._run_command` runs this script under
    `subprocess.run(capture_output=True)` and discards a successful step's
    stdout, so no print here reaches Render's logs on a normal run (proven for
    the WNBA producer 2026-08-15/16 -- it ran, and the line was nowhere).
    Production reads the keyvalue record instead.

    NBA reporting `rows=0` is EXPECTED while the sport is out of season, and it
    is a real reading, not a failure: it says the producer reported and computed
    no win_prob, which is different from never having reported at all.
    """
    rows = _WIN_PROB_STATS["rows"]
    nulls = _WIN_PROB_STATS["null_no_price"]
    pct = (100.0 * nulls / rows) if rows else 0.0
    print(
        f"[{tag}] WIN_PROB_NULL_NO_PRICE build=TOTAL null={nulls} rows={rows} pct={pct:.1f}",
        flush=True,
    )
    # Never raises (see `record`'s contract): this runs in a `finally` guarding
    # the process exit code.
    try:
        from syndicate.features.shared.win_prob_null_diag import record as _record_win_prob_null

        _record_win_prob_null(
            sport="nba",
            tag=tag,
            rows=rows,
            nulls=nulls,
            date=_WIN_PROB_RUN_DATE.get("date"),
        )
    except Exception:
        pass


def _format_signed_line(value: float | None) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f"{number:+.1f}"


def _format_plain_line(value: float | None) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f"{number:.1f}"


def _local_props_tier(ev_pct: float | None) -> str:
    if ev_pct is None:
        return "Low"
    if ev_pct >= 8.0:
        return "High"
    if ev_pct >= 4.0:
        return "Medium"
    return "Low"


def _local_game_cards_index(*, processed_root: Path, date_str: str) -> tuple[list[dict[str, str]], dict[str, dict[str, str]], dict[tuple[str, str], dict[str, str]]]:
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    if not game_cards_path.exists() or not game_cards_path.is_file() or _count_csv_rows_quick(game_cards_path) <= 0:
        return [], {}, {}

    rows: list[dict[str, str]] = []
    by_team: dict[str, dict[str, str]] = {}
    by_names: dict[tuple[str, str], dict[str, str]] = {}
    with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not isinstance(row, dict):
                continue
            normalized = {str(key): str(value or "").strip() for key, value in row.items()}
            home_tri = normalized.get("home_tri", "").upper()
            away_tri = normalized.get("away_tri", "").upper()
            home_team = normalized.get("home_team", "")
            away_team = normalized.get("visitor_team", "")
            if not home_tri or not away_tri:
                continue
            rows.append(normalized)
            by_team[home_tri] = {
                "side": "home",
                "opponent": away_tri,
                "home_tri": home_tri,
                "away_tri": away_tri,
                "home_team": home_team,
                "away_team": away_team,
                "game_id": normalized.get("game_id", ""),
            }
            by_team[away_tri] = {
                "side": "away",
                "opponent": home_tri,
                "home_tri": home_tri,
                "away_tri": away_tri,
                "home_team": home_team,
                "away_team": away_team,
                "game_id": normalized.get("game_id", ""),
            }
            if home_team and away_team:
                by_names[(home_team.lower(), away_team.lower())] = normalized
    return rows, by_team, by_names


def _load_local_props_recommendations(*, processed_root: Path, date_str: str) -> list[dict[str, object]]:
    out_path = processed_root / f"props_recommendations_{date_str}.csv"
    if not out_path.exists() or not out_path.is_file() or _count_csv_rows_quick(out_path) <= 0:
        return []

    rows_out: list[dict[str, object]] = []
    with out_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not isinstance(row, dict):
                continue
            parsed = dict(row)
            parsed["model"] = _structured_literal_or_none(row.get("model")) or {}
            parsed["top_play"] = _structured_literal_or_none(row.get("top_play")) or {}
            parsed["top_play_reasons"] = _structured_literal_or_none(row.get("top_play_reasons")) or []
            parsed["top_play_explain"] = str(row.get("top_play_explain") or "").strip()
            rows_out.append(parsed)
    return rows_out


def _basketball_recent_form_fields(row: dict[str, object], *, line_value: float | None = None) -> dict[str, float]:
    sources: list[dict[str, object]] = [row]
    for key in ("top_play", "model"):
        nested = row.get(key)
        if isinstance(nested, dict):
            sources.append(nested)

    def first_numeric(*names: str) -> float | None:
        for source in sources:
            for name in names:
                value = _float_or_none(source.get(name))
                if value is not None:
                    return float(value)
        return None

    payload: dict[str, float] = {}
    scalar_fields = (
        (("basketball_last5_average", "last5_average", "last_5_average", "last5_avg"), "last5_average"),
        (("basketball_last10_average", "last10_average", "last_10_average", "last10_avg"), "last10_average"),
        (("basketball_last_game_value", "last_game_value", "last_game", "last_game_stat"), "last_game_value"),
        (("basketball_projected_minutes", "projected_minutes"), "projected_minutes"),
        (("basketball_last10_workload", "last10_workload", "last_10_workload"), "last10_workload"),
        (("basketball_last5_delta", "last5_delta_signal", "last5_delta"), "last5_delta_signal"),
        (("basketball_last10_delta", "last10_delta_signal", "last10_delta"), "last10_delta_signal"),
        (("basketball_last_game_delta", "last_game_delta_signal", "last_game_delta"), "last_game_delta_signal"),
        (("basketball_minutes_workload_delta", "workload_delta_signal", "minutes_workload_delta"), "workload_delta_signal"),
    )
    for candidate_names, output_name in scalar_fields:
        value = first_numeric(*candidate_names)
        if value is not None:
            payload[output_name] = round(float(value), 3)

    if line_value is not None and line_value > 0:
        for raw_key, delta_key in (("last5_average", "last5_delta_signal"), ("last10_average", "last10_delta_signal"), ("last_game_value", "last_game_delta_signal")):
            if delta_key in payload or raw_key not in payload:
                continue
            payload[delta_key] = round((float(payload[raw_key]) - line_value) / max(line_value, 8.0), 3)

    if "workload_delta_signal" not in payload and "projected_minutes" in payload and "last10_workload" in payload:
        payload["workload_delta_signal"] = round(
            (float(payload["projected_minutes"]) - float(payload["last10_workload"])) / max(float(payload["last10_workload"]), 12.0),
            3,
        )
    return payload


def _build_local_recommendations_slate_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    rows, _, by_names = _local_game_cards_index(processed_root=processed_root, date_str=date_str)
    recommendations_path = processed_root / f"recommendations_{date_str}.csv"
    if not rows or not recommendations_path.exists() or not recommendations_path.is_file() or _count_csv_rows_quick(recommendations_path) <= 0:
        return 0, None

    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    with recommendations_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not isinstance(row, dict):
                continue
            home_name = str(row.get("home") or "").strip()
            away_name = str(row.get("away") or "").strip()
            game_row = by_names.get((home_name.lower(), away_name.lower()))
            if game_row is None:
                continue
            home_tri = str(game_row.get("home_tri") or "").strip().upper()
            away_tri = str(game_row.get("away_tri") or "").strip().upper()
            market = str(row.get("market") or "").strip().upper()
            side = str(row.get("side") or "").strip() or market
            line = _float_or_none(row.get("line"))
            price = _float_or_none(row.get("price"))
            ev = _float_or_none(row.get("ev"))
            implied_prob = _float_or_none(row.get("implied_prob"))
            edge = _float_or_none(row.get("edge"))
            pred_margin = _float_or_none(row.get("pred_margin"))
            pred_total = _float_or_none(row.get("pred_total"))
            market_home_margin = _float_or_none(row.get("market_home_margin"))
            ev_pct = (ev * 100.0) if ev is not None else None
            # No implied probability means no price to imply it from, and
            # "0.5 plus the edge" reads on the board as a confident
            # 50-something percent that nothing computed. Absence propagates.
            win_prob = (
                _clamp_probability(implied_prob + (ev or 0.0))
                if implied_prob is not None
                else _clamp_probability(None)
            )

            if market == "ATS":
                side_is_home = side.lower() == home_name.lower()
                signed_line = market_home_margin if market_home_margin is not None and side_is_home else (
                    (-market_home_margin) if market_home_margin is not None else (-abs(line) if side_is_home and line is not None else abs(line) if line is not None else None)
                )
                display_pick = f"{side} {_format_signed_line(signed_line)}".strip()
                summary = f"Model margin {_format_plain_line(pred_margin)} vs market {_format_signed_line(signed_line)}"
                team_label = side
            else:
                display_pick = f"{side} {_format_plain_line(line)}".strip()
                summary = f"Model total {_format_plain_line(pred_total)} vs line {_format_plain_line(line)}"
                team_label = "Total"

            grouped.setdefault((home_tri, away_tri), []).append(
                {
                    "market": market,
                    "team": team_label,
                    "display_pick": display_pick,
                    "selection": side,
                    "price": price,
                    "score": edge if edge is not None else ev_pct,
                    "ev_pct": ev_pct,
                    "win_prob": win_prob,
                    "p_win": win_prob,
                    "basketball_summary": summary,
                    "top_play_reasons": [
                        bit
                        for bit in [
                            f"Edge {_format_plain_line(edge)}" if edge is not None else "",
                            f"EV {ev_pct:.1f}%" if ev_pct is not None else "",
                        ]
                        if bit
                    ],
                    "matchup": f"{away_tri} @ {home_tri}",
                }
            )

    per_game: list[dict[str, object]] = []
    picks_count = 0
    for game_row in rows:
        home_tri = str(game_row.get("home_tri") or "").strip().upper()
        away_tri = str(game_row.get("away_tri") or "").strip().upper()
        picks = grouped.get((home_tri, away_tri), [])
        if not picks:
            continue
        picks.sort(key=lambda item: float(item.get("ev_pct") or float("-inf")), reverse=True)
        picks_count += len(picks)
        per_game.append({"home": home_tri, "away": away_tri, "matchup": f"{away_tri} @ {home_tri}", "picks": picks})

    if not per_game:
        return 0, None

    payload = {"date": date_str, "counts": {"games": len(per_game), "picks": picks_count}, "per_game": per_game}
    out_path = processed_root / f"recommendations_slate_{date_str}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _emit_win_prob_build("recommendations_slate")
    return len(per_game), out_path


def _build_local_top_by_game_snapshot(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    _, by_team, _ = _local_game_cards_index(processed_root=processed_root, date_str=date_str)
    prop_rows = _load_local_props_recommendations(processed_root=processed_root, date_str=date_str)
    if not by_team or not prop_rows:
        return 0, None

    rows_out: list[dict[str, object]] = []
    per_game_counts: dict[str, int] = {}
    ordered = sorted(
        prop_rows,
        key=lambda row: float((((row.get("top_play") or {}) if isinstance(row.get("top_play"), dict) else {}).get("ev_pct") or float("-inf"))),
        reverse=True,
    )
    for row in ordered:
        team_tri = str(row.get("team") or "").strip().upper()
        meta = by_team.get(team_tri)
        top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
        if meta is None or not top_play:
            continue
        home_tri = str(meta.get("home_tri") or "").strip().upper()
        away_tri = str(meta.get("away_tri") or "").strip().upper()
        game_key = f"{away_tri}@{home_tri}"
        if per_game_counts.get(game_key, 0) >= 3:
            continue
        ev_pct = _float_or_none(top_play.get("ev_pct"))
        implied_prob = _american_price_to_prob(top_play.get("price"))
        win_prob = (
            _clamp_probability(implied_prob + (_float_or_none(top_play.get("ev")) or 0.0))
            if implied_prob is not None
            else _clamp_probability(None)
        )
        enriched_top_play = dict(top_play)
        enriched_top_play.update(_basketball_recent_form_fields(row, line_value=_float_or_none(top_play.get("line"))))
        enriched_top_play["p_win"] = win_prob
        enriched_top_play["snapshot_ts"] = None
        row_out = {
            "game_key": game_key,
            "game_id": meta.get("game_id"),
            "player": str(row.get("player") or "").strip(),
            "team": team_tri,
            "team_tricode": team_tri,
            "opponent": str(meta.get("opponent") or "").strip().upper(),
            "score": ev_pct,
            "score_adj": ev_pct,
            "tier": _local_props_tier(ev_pct),
            "model": row.get("model") if isinstance(row.get("model"), dict) else {},
            "top_play": enriched_top_play,
            "top_play_reasons": row.get("top_play_reasons") if isinstance(row.get("top_play_reasons"), list) else [],
            "basketball_summary": str(row.get("top_play_explain") or "").strip() or None,
        }
        row_out.update(_basketball_recent_form_fields(row, line_value=_float_or_none(top_play.get("line"))))
        rows_out.append(row_out)
        per_game_counts[game_key] = int(per_game_counts.get(game_key, 0) + 1)
        if len(rows_out) >= 25:
            break

    if not rows_out:
        return 0, None

    out_path = processed_root / f"props_recommendations_top_by_game_{date_str}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"date": date_str, "data": rows_out}, indent=2), encoding="utf-8")
    _emit_win_prob_build("top_by_game")
    return len(rows_out), out_path


def _build_local_cards_props_snapshot_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    rows, by_team, _ = _local_game_cards_index(processed_root=processed_root, date_str=date_str)
    prop_rows = _load_local_props_recommendations(processed_root=processed_root, date_str=date_str)
    if not rows or not by_team or not prop_rows:
        return 0, None

    grouped: dict[tuple[str, str], dict[str, list[dict[str, object]]]] = {}
    for game_row in rows:
        home_tri = str(game_row.get("home_tri") or "").strip().upper()
        away_tri = str(game_row.get("away_tri") or "").strip().upper()
        grouped[(home_tri, away_tri)] = {"home": [], "away": []}

    for row in prop_rows:
        team_tri = str(row.get("team") or "").strip().upper()
        meta = by_team.get(team_tri)
        top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
        if meta is None or not top_play:
            continue
        home_tri = str(meta.get("home_tri") or "").strip().upper()
        away_tri = str(meta.get("away_tri") or "").strip().upper()
        if (home_tri, away_tri) not in grouped:
            continue
        ev_pct = _float_or_none(top_play.get("ev_pct"))
        implied_prob = _american_price_to_prob(top_play.get("price"))
        win_prob = (
            _clamp_probability(implied_prob + (_float_or_none(top_play.get("ev")) or 0.0))
            if implied_prob is not None
            else _clamp_probability(None)
        )
        base_pick = dict(top_play)
        base_pick.update(_basketball_recent_form_fields(row, line_value=_float_or_none(top_play.get("line"))))
        base_pick["player"] = str(row.get("player") or "").strip()
        base_pick["team"] = team_tri
        base_pick["opponent"] = str(meta.get("opponent") or "").strip().upper()
        base_pick["p_win"] = win_prob
        base_pick["tier"] = _local_props_tier(ev_pct)
        base_pick["score"] = ev_pct
        base_pick["recommendation_priority_score"] = ev_pct
        base_pick["basketball_priority_score"] = ev_pct
        base_pick["basketball_summary"] = str(row.get("top_play_explain") or "").strip() or None
        pick_row = dict(base_pick)
        pick_row["picks"] = [dict(base_pick)]
        pick_row["best"] = dict(base_pick)
        grouped[(home_tri, away_tri)][str(meta.get("side") or "away")].append(pick_row)

    games_out: list[dict[str, object]] = []
    for game_row in rows:
        home_tri = str(game_row.get("home_tri") or "").strip().upper()
        away_tri = str(game_row.get("away_tri") or "").strip().upper()
        current = grouped.get((home_tri, away_tri), {"home": [], "away": []})
        home_rows = sorted(current.get("home") or [], key=lambda item: float(item.get("ev_pct") or float("-inf")), reverse=True)
        away_rows = sorted(current.get("away") or [], key=lambda item: float(item.get("ev_pct") or float("-inf")), reverse=True)
        if not home_rows and not away_rows:
            continue
        games_out.append({"home_tri": home_tri, "away_tri": away_tri, "game_id": game_row.get("game_id"), "prop_recommendations": {"home": home_rows, "away": away_rows}})

    if not games_out:
        return 0, None

    out_path = processed_root / f"cards_props_snapshot_{date_str}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"date": date_str, "games": games_out}, indent=2), encoding="utf-8")
    _emit_win_prob_build("cards_props_snapshot")
    return len(games_out), out_path


def _build_local_game_cards_artifact(*, source_root: Path, processed_root: Path, date_str: str, log_file: Path) -> tuple[int, Path | None]:
    out_path = processed_root / f"game_cards_{date_str}.csv"

    # Added 2026-08-02 (straight port of the WNBA zero-edge-board fix from
    # refresh_wnba_oddsapi_props.py). pred_margin/pred_total are the smart-sim
    # means -- probability derivation stays in nba/cards.py's _game_from_row so
    # there is exactly one margin->probability transform site. The four price
    # columns are real per-side book quotes; readers use DictReader + .get()
    # so older CSVs without these columns keep working.
    projection_price_columns = [
        "pred_margin",
        "pred_total",
        "home_spread_price",
        "away_spread_price",
        "total_over_price",
        "total_under_price",
    ]
    sim_projections = _smart_sim_projection_index(processed_root=processed_root, date_str=date_str)

    def _sim_projection_fields(home_tri: object, away_tri: object) -> dict[str, object]:
        projection = sim_projections.get((str(home_tri or "").strip().upper(), str(away_tri or "").strip().upper())) or {}
        pred_margin = _float_or_none(projection.get("pred_margin"))
        pred_total = _float_or_none(projection.get("pred_total"))
        return {
            "pred_margin": round(pred_margin, 3) if pred_margin is not None else None,
            "pred_total": round(pred_total, 3) if pred_total is not None else None,
        }

    def _build_from_source_cards_api() -> tuple[int, Path | None]:
        if not _source_app_fallback_enabled():
            return 0, None
        source_app = _load_source_app(source_root)
        if source_app is None:
            return 0, None
        try:
            client = source_app.app.test_client()
            response = client.get(f"/api/cards?date={date_str}&props_source=source")
            if int(getattr(response, "status_code", 0) or 0) != 200:
                return 0, None
            payload = response.get_json() if response is not None else None
        except Exception as exc:
            _append_log(log_file, f"Source app cards fallback failed for {date_str}: {exc}")
            return 0, None
        games = []
        if isinstance(payload, dict):
            if isinstance(payload.get("games"), list):
                games = [game for game in payload.get("games") if isinstance(game, dict)]
            elif isinstance(payload.get("cards"), list):
                games = [game for game in payload.get("cards") if isinstance(game, dict)]
        if not games:
            return 0, None

        def _team_name(side: dict[str, object], fallback_abbr: str) -> str:
            name = str(side.get("name") or side.get("team_name") or side.get("full_name") or side.get("abbr") or fallback_abbr).strip()
            return name or fallback_abbr

        def _market_value(markets: dict[str, object], primary_key: str, *fallback_keys: str) -> object:
            section = markets.get(primary_key) if isinstance(markets.get(primary_key), dict) else {}
            for key in ("line", "market_line", "homeLine", "awayLine", *fallback_keys):
                value = section.get(key)
                if value is not None:
                    return value
            return None

        rows_out: list[dict[str, object]] = []
        for index, game in enumerate(games, start=1):
            home = game.get("home") if isinstance(game.get("home"), dict) else {}
            away = game.get("away") if isinstance(game.get("away"), dict) else {}
            markets = game.get("markets") if isinstance(game.get("markets"), dict) else {}
            ml = markets.get("ml") if isinstance(markets.get("ml"), dict) else {}
            totals = markets.get("totals") if isinstance(markets.get("totals"), dict) else {}
            spreads = markets.get("spreads") if isinstance(markets.get("spreads"), dict) else {}
            game_id = str(game.get("game_id") or game.get("game_pk") or game.get("gamePk") or f"{away.get('abbr') or away.get('teamTricode') or 'AWY'}@{home.get('abbr') or home.get('teamTricode') or 'HOM'}").strip()
            home_abbr = str(home.get("abbr") or home.get("teamTricode") or home.get("tricode") or "HOM").strip().upper() or "HOM"
            away_abbr = str(away.get("abbr") or away.get("teamTricode") or away.get("tricode") or "AWY").strip().upper() or "AWY"
            rows_out.append(
                {
                    "date": date_str,
                    "game_id": game_id,
                    "home_team": _team_name(home, home_abbr),
                    "visitor_team": _team_name(away, away_abbr),
                    "commence_time": str(game.get("commence_time") or game.get("startTime") or game.get("detail") or "").strip(),
                    "home_ml": ml.get("home_odds") if isinstance(ml, dict) else None,
                    "away_ml": ml.get("away_odds") if isinstance(ml, dict) else None,
                    "home_spread": spreads.get("home_line") if isinstance(spreads, dict) else None,
                    "away_spread": spreads.get("away_line") if isinstance(spreads, dict) else None,
                    "total": totals.get("line") if isinstance(totals, dict) else None,
                    "bookmaker": str(ml.get("bookmaker") or totals.get("bookmaker") or game.get("bookmaker") or "source_app").strip() or "source_app",
                    "home_tri": home_abbr,
                    "away_tri": away_abbr,
                    **_sim_projection_fields(home_abbr, away_abbr),
                }
            )

        if not rows_out:
            return 0, None

        header_order = [
            "date",
            "game_id",
            "home_team",
            "visitor_team",
            "commence_time",
            "home_ml",
            "away_ml",
            "home_spread",
            "away_spread",
            "total",
            "bookmaker",
            "home_tri",
            "away_tri",
            *projection_price_columns,
        ]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header_order)
            writer.writeheader()
            for current in rows_out:
                writer.writerow({field: current.get(field, "") for field in header_order})
        _append_log(log_file, f"Built game_cards from source app cards fallback: {out_path} (rows={len(rows_out)})")
        return len(rows_out), out_path

    raw_candidates = [
        source_root / "data" / "raw" / f"odds_nba_current_{date_str}.csv",
        source_root / "data" / "raw" / f"odds_nba_current_{date_str}.parquet",
    ]
    raw_path = next((path for path in raw_candidates if path.exists() and path.is_file()), None)
    if raw_path is None:
        # Fallback to processed game_odds when raw team odds snapshots are unavailable.
        game_odds_path = source_root / "data" / "processed" / f"game_odds_{date_str}.csv"
        if not game_odds_path.exists() or not game_odds_path.is_file() or _count_csv_rows_quick(game_odds_path) <= 0:
            _append_log(log_file, f"Local game_cards build skipped for {date_str}: no raw team odds snapshot found")
            return _build_from_source_cards_api()

        rows_out: list[dict[str, object]] = []
        with game_odds_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for idx, row in enumerate(reader, start=1):
                if not isinstance(row, dict):
                    continue
                home_name = str(row.get("home_team") or "").strip()
                away_name = str(row.get("visitor_team") or row.get("away_team") or "").strip()
                if not home_name or not away_name:
                    continue
                home_tri = _to_tricode_local(home_name)
                away_tri = _to_tricode_local(away_name)
                rows_out.append(
                    {
                        "date": date_str,
                        "game_id": str(row.get("game_id") or idx),
                        "home_team": home_name,
                        "visitor_team": away_name,
                        "commence_time": str(row.get("commence_time") or "").strip(),
                        "home_ml": _float_or_none(row.get("home_ml")),
                        "away_ml": _float_or_none(row.get("away_ml")),
                        "home_spread": _float_or_none(row.get("home_spread")),
                        "away_spread": _float_or_none(row.get("away_spread")),
                        "total": _float_or_none(row.get("total")),
                        "bookmaker": str(row.get("bookmaker") or "oddsapi_consensus").strip() or "oddsapi_consensus",
                        "home_tri": home_tri,
                        "away_tri": away_tri,
                        **_sim_projection_fields(home_tri, away_tri),
                        "home_spread_price": _float_or_none(row.get("home_spread_price")),
                        "away_spread_price": _float_or_none(row.get("away_spread_price")),
                        "total_over_price": _float_or_none(row.get("total_over_price")),
                        "total_under_price": _float_or_none(row.get("total_under_price")),
                    }
                )

        if not rows_out:
            _append_log(log_file, f"Local game_cards build skipped for {date_str}: processed game_odds had no usable rows")
            return _build_from_source_cards_api()

        header_order = [
            "date",
            "game_id",
            "home_team",
            "visitor_team",
            "commence_time",
            "home_ml",
            "away_ml",
            "home_spread",
            "away_spread",
            "total",
            "bookmaker",
            "home_tri",
            "away_tri",
            *projection_price_columns,
        ]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header_order)
            writer.writeheader()
            for current in rows_out:
                writer.writerow({field: current.get(field, "") for field in header_order})

        _append_log(log_file, f"Built local game_cards from game_odds fallback: {out_path} (rows={len(rows_out)})")
        return len(rows_out), out_path

    try:
        import pandas as pd

        if raw_path.suffix.lower() == ".parquet":
            raw_frame = pd.read_parquet(raw_path)
        else:
            raw_frame = pd.read_csv(raw_path)
    except Exception as exc:
        _append_log(log_file, f"Failed to read raw team odds snapshot {raw_path}: {exc}")
        return _build_from_source_cards_api()

    if raw_frame.empty:
        return _build_from_source_cards_api()

    required_columns = {"event_id", "commence_time", "market", "outcome_name", "point", "price", "home_team", "away_team"}
    if not required_columns.issubset(set(str(column) for column in raw_frame.columns)):
        _append_log(log_file, f"Local game_cards build skipped for {date_str}: raw team odds snapshot missing required columns")
        return _build_from_source_cards_api()

    working = raw_frame.copy()
    working["commence_time"] = working["commence_time"].astype(str)
    # Bug found 2026-07-21 (same one fixed in refresh_wnba_oddsapi_props.py):
    # comparing the raw UTC commence_time string's date PREFIX against
    # date_str is wrong for evening games -- a 7pm Central tip-off is
    # 00:00 UTC the *next* calendar day, so this was actually selecting the
    # PRIOR day's evening slate for most games. Compare the Central-converted
    # date directly instead.
    try:
        _target_date = dt.date.fromisoformat(date_str)
    except Exception:
        _target_date = None
    working = working[working["commence_time"].apply(lambda value: central_date_from_iso(value) == _target_date)].copy()
    if working.empty:
        return _build_from_source_cards_api()

    rows_out: list[dict[str, object]] = []
    grouped = working.groupby(["event_id", "commence_time", "home_team", "away_team"], dropna=False, sort=True)
    for (event_id, commence_time, home_team, away_team), group in grouped:
        home_name = str(home_team or "").strip()
        away_name = str(away_team or "").strip()
        if not home_name or not away_name:
            continue

        group_rows = group.to_dict("records")
        aggregated = _aggregate_game_odds_from_market_rows(group_rows, home_name=home_name, away_name=away_name)

        home_tri = _to_tricode_local(home_name)
        away_tri = _to_tricode_local(away_name)
        rows_out.append(
            {
                "date": date_str,
                "game_id": f"0{str(event_id or '').strip()}" if str(event_id or "").strip() else "",
                "home_team": home_name,
                "visitor_team": away_name,
                "commence_time": str(commence_time or "").strip(),
                "home_ml": aggregated["home_ml"],
                "away_ml": aggregated["away_ml"],
                "home_spread": aggregated["home_spread"],
                "away_spread": aggregated["away_spread"],
                "total": aggregated["total"],
                "bookmaker": "oddsapi_consensus",
                "home_tri": home_tri,
                "away_tri": away_tri,
                **_sim_projection_fields(home_tri, away_tri),
                "home_spread_price": aggregated["home_spread_price"],
                "away_spread_price": aggregated["away_spread_price"],
                "total_over_price": aggregated["total_over_price"],
                "total_under_price": aggregated["total_under_price"],
            }
        )

    if not rows_out:
        return 0, None

    header_order = [
        "date",
        "game_id",
        "home_team",
        "visitor_team",
        "commence_time",
        "home_ml",
        "away_ml",
        "home_spread",
        "away_spread",
        "total",
        "bookmaker",
        "home_tri",
        "away_tri",
        *projection_price_columns,
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header_order)
        writer.writeheader()
        for current in rows_out:
            writer.writerow({field: current.get(field, "") for field in header_order})
    return len(rows_out), out_path


def _smart_sim_projection_index(*, processed_root: Path, date_str: str) -> dict[tuple[str, str], dict[str, float]]:
    index: dict[tuple[str, str], dict[str, float]] = {}
    for path in sorted(processed_root.glob(f"smart_sim_{date_str}_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        home = str(payload.get("home") or "").strip().upper()
        away = str(payload.get("away") or "").strip().upper()
        quarters = payload.get("quarters") if isinstance(payload.get("quarters"), list) else []
        if not quarters:
            periods_payload = payload.get("periods") if isinstance(payload.get("periods"), dict) else {}
            for quarter_number in range(1, 5):
                quarter_payload = periods_payload.get(f"q{quarter_number}") if isinstance(periods_payload.get(f"q{quarter_number}"), dict) else None
                if not isinstance(quarter_payload, dict):
                    continue
                quarters.append(
                    {
                        "home_pts_mu": quarter_payload.get("home_mean"),
                        "away_pts_mu": quarter_payload.get("away_mean"),
                    }
                )
        if not home or not away or not quarters:
            continue
        home_total = 0.0
        away_total = 0.0
        for quarter in quarters:
            if not isinstance(quarter, dict):
                continue
            home_total += float(_float_or_none(quarter.get("home_pts_mu")) or 0.0)
            away_total += float(_float_or_none(quarter.get("away_pts_mu")) or 0.0)
        if home_total <= 0 and away_total <= 0:
            continue
        index[(home, away)] = {
            "pred_margin": home_total - away_total,
            "pred_total": home_total + away_total,
        }
    return index


def _build_local_live_lens_signals_artifact(*, processed_root: Path, date_str: str, live_lens_root: Path) -> dict[str, str]:
    try:
        from syndicate.features.nba.cards import build_live_lens_tuning_payload

        tuning_payload = build_live_lens_tuning_payload()
    except Exception:
        tuning_payload = {}

    total_market = tuning_payload.get("markets", {}).get("total", {}) if isinstance(tuning_payload, dict) else {}
    watch_threshold = float(_float_or_none(total_market.get("watch")) or 3.0)
    bet_threshold = float(_float_or_none(total_market.get("bet")) or 6.0)

    projections = _smart_sim_projection_index(processed_root=processed_root, date_str=date_str)
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    if not projections or not game_cards_path.exists() or not game_cards_path.is_file():
        return {}

    rows_out: list[dict[str, object]] = []
    with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            home_tri = str(row.get("home_tri") or "").strip().upper()
            away_tri = str(row.get("away_tri") or "").strip().upper()
            projection = projections.get((home_tri, away_tri))
            total_line = _float_or_none(row.get("total"))
            if projection is None or total_line is None:
                continue
            pred_total = _float_or_none(projection.get("pred_total"))
            if pred_total is None:
                continue
            edge = pred_total - total_line
            abs_edge = abs(float(edge))
            if abs_edge < watch_threshold:
                continue
            rows_out.append(
                {
                    "market": "total",
                    "klass": "BET" if abs_edge >= bet_threshold else "WATCH",
                    "game_id": str(row.get("game_id") or "").strip(),
                    "home": str(row.get("home_tri") or row.get("home_team") or "").strip().upper(),
                    "away": str(row.get("away_tri") or row.get("visitor_team") or "").strip().upper(),
                    "side": "OVER" if edge > 0 else "UNDER",
                    "live_line": round(total_line, 3),
                    "pred": round(pred_total, 3),
                    "edge": round(edge, 3),
                    "edge_adj": round(edge, 3),
                    "elapsed": 0,
                    "remaining": 48,
                    "tags": ["sim:pregame"],
                }
            )

    raw = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows_out).encode("utf-8")
    copied: dict[str, str] = {}
    for out_path, copied_key in (
        (processed_root / f"live_lens_signals_{date_str}.jsonl", "live_lens_signals_path"),
        (live_lens_root / f"live_lens_signals_{date_str}.jsonl", None),
    ):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        if copied_key:
            copied[copied_key] = str(out_path)
    return copied


def _build_local_live_lens_projections_artifact(*, processed_root: Path, date_str: str, live_lens_root: Path) -> dict[str, str]:
    predictions_path = processed_root / f"props_predictions_{date_str}.csv"
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    if not predictions_path.exists() or not predictions_path.is_file() or not game_cards_path.exists() or not game_cards_path.is_file():
        return {}

    game_lookup: dict[tuple[str, str], dict[str, str]] = {}
    pair_lookup: dict[tuple[str, str], dict[str, str]] = {}
    with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            home_tri = str(row.get("home_tri") or "").strip().upper()
            away_tri = str(row.get("away_tri") or "").strip().upper()
            if not home_tri or not away_tri:
                continue
            payload = {
                "game_id": str(row.get("game_id") or "").strip(),
                "home": home_tri,
                "away": away_tri,
            }
            game_lookup[(home_tri, away_tri)] = payload
            pair_lookup[tuple(sorted((home_tri, away_tri)))] = payload

    line_lookup: dict[tuple[str, str, str], float] = {}
    edges_path = processed_root / f"props_edges_{date_str}.csv"
    if edges_path.exists() and edges_path.is_file():
        with edges_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                player_name = str(row.get("player_name") or row.get("player") or "").strip()
                team_tri = str(row.get("team") or "").strip().upper()
                stat_key = str(row.get("stat") or row.get("market") or "").strip().lower()
                line_value = _float_or_none(row.get("line"))
                if not player_name or not team_tri or not stat_key or line_value is None:
                    continue
                line_lookup.setdefault((player_name.upper(), team_tri, stat_key), float(line_value))

    stat_columns = (
        ("pts", "pred_pts", "mean_pts"),
        ("reb", "pred_reb", "mean_reb"),
        ("ast", "pred_ast", "mean_ast"),
        ("threes", "pred_threes", "mean_threes"),
        ("stl", "pred_stl", "mean_stl"),
        ("blk", "pred_blk", "mean_blk"),
        ("tov", "pred_tov", "mean_tov"),
        ("pra", "pred_pra", "mean_pra"),
    )
    rows_out: list[dict[str, object]] = []
    with predictions_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            player_name = str(row.get("player_name") or row.get("player") or "").strip()
            team_tri = str(row.get("team") or "").strip().upper()
            opponent_tri = str(row.get("opponent") or "").strip().upper()
            if not player_name or not team_tri:
                continue

            matchup = None
            if team_tri and opponent_tri:
                matchup = game_lookup.get((team_tri, opponent_tri)) or game_lookup.get((opponent_tri, team_tri)) or pair_lookup.get(tuple(sorted((team_tri, opponent_tri))))
            if matchup is None:
                continue

            line_name_key = player_name.upper()
            for stat_key, proj_col, sim_col in stat_columns:
                proj = _float_or_none(row.get(proj_col))
                sim_mu = _float_or_none(row.get(sim_col))
                if proj is None and sim_mu is None:
                    continue
                if proj is None:
                    proj = sim_mu
                if sim_mu is None:
                    sim_mu = proj
                line_value = line_lookup.get((line_name_key, team_tri, stat_key))
                context: dict[str, object] = {
                    "pregame_team_total_ratio": 1.0,
                    "pregame_game_total_ratio": 1.0,
                }
                if line_value is not None and sim_mu is not None:
                    context["sim_vs_line"] = round(float(sim_mu) - float(line_value), 3)
                    context["sim_vs_line_adjusted"] = round(float(sim_mu) - float(line_value), 3)
                rows_out.append(
                    {
                        "market": "player_prop",
                        "game_id": matchup.get("game_id"),
                        "home": matchup.get("home"),
                        "away": matchup.get("away"),
                        "player": player_name,
                        "name_key": player_name,
                        "team_tri": team_tri,
                        "stat": stat_key,
                        "line": line_value,
                        "proj": round(float(proj), 3) if proj is not None else None,
                        "proj_original": round(float(proj), 3) if proj is not None else None,
                        "sim_mu": round(float(sim_mu), 3) if sim_mu is not None else None,
                        "sim_mu_adjusted": round(float(sim_mu), 3) if sim_mu is not None else None,
                        "sim_mu_adjusted_original": round(float(sim_mu), 3) if sim_mu is not None else None,
                        "elapsed": 0,
                        "strength": abs(float(sim_mu) - float(line_value)) if (sim_mu is not None and line_value is not None) else None,
                        "context": context,
                    }
                )

    if not rows_out:
        return {}

    raw = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows_out).encode("utf-8")
    copied: dict[str, str] = {}
    for out_path, copied_key in (
        (processed_root / f"live_lens_projections_{date_str}.jsonl", "live_lens_projections_path"),
        (live_lens_root / f"live_lens_projections_{date_str}.jsonl", None),
    ):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        if copied_key:
            copied[copied_key] = str(out_path)
    return copied


def _build_local_game_recommendations_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    # One transform site for margin->probability (same logistic + scales
    # nba/cards.py's _game_from_row uses for its betting probabilities), and
    # the repo's existing American-odds profit helper -- imported lazily like
    # the other syndicate.features imports in this script's artifact builders.
    from syndicate.features.nba.cards import _margin_win_prob
    from syndicate.features.shared.evaluation_settlement import _american_profit

    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    if not game_cards_path.exists() or not game_cards_path.is_file() or _count_csv_rows_quick(game_cards_path) <= 0:
        return 0, None
    sim_index = _smart_sim_projection_index(processed_root=processed_root, date_str=date_str)
    if not sim_index:
        return 0, None

    def _side_price(row: dict[str, object], column: str) -> float:
        price = _float_or_none(row.get(column))
        if price is not None and price != 0:
            return price
        # Placeholder ONLY for a missing per-side quote (older game_cards
        # CSVs without the 2026-08-02 price columns, or a book that never
        # quoted this side) -- never preferred over a real price.
        return -110.0

    def _probability_ev(model_prob: float, price: float) -> float:
        profit_multiplier = _american_profit(price)
        if profit_multiplier is None:
            profit_multiplier = 100.0 / 110.0
        return model_prob * profit_multiplier - (1.0 - model_prob)

    rows: list[dict[str, object]] = []
    with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not isinstance(row, dict):
                continue
            home_tri = str(row.get("home_tri") or "").strip().upper()
            away_tri = str(row.get("away_tri") or "").strip().upper()
            projection = sim_index.get((home_tri, away_tri))
            if projection is None:
                continue
            home_name = str(row.get("home_team") or home_tri).strip() or home_tri
            away_name = str(row.get("visitor_team") or away_tri).strip() or away_tri
            pred_margin = float(projection.get("pred_margin") or 0.0)
            pred_total = float(projection.get("pred_total") or 0.0)
            market_home_margin = _float_or_none(row.get("home_spread"))
            if market_home_margin is None:
                away_spread = _float_or_none(row.get("away_spread"))
                if away_spread is not None:
                    market_home_margin = -away_spread
            total_line = _float_or_none(row.get("total"))

            if market_home_margin is not None:
                # market_home_margin is the quoted home HANDICAP (home_spread,
                # negative when home is favored) -- the name and CSV column are
                # kept for reader compat (_export_recommendations_slate_snapshot
                # displays it as the home side's signed line). Home covers iff
                # actual margin + handicap > 0. The old cover_edge
                # (pred_margin - handicap) subtracted the handicap instead,
                # double-counting the spread toward the favorite, and the row's
                # price/implied_prob/ev were fabricated constants (-110 juice,
                # ev = points/100) rather than computed -- same bug pair fixed
                # for WNBA in refresh_wnba_oddsapi_props.py (2026-08-02
                # end-to-end assessment).
                cover_edge = pred_margin + market_home_margin
                pick_home = cover_edge >= 0
                # Unreachable `or 0.5` -- cover_edge is arithmetic on two
                # values the enclosing guard proved non-None, and the logistic
                # cannot return 0.0 for a finite input. Kept as an explicit
                # skip so it stays unreachable if that guard is ever relaxed.
                home_cover_prob = _margin_win_prob(cover_edge, scale=7.5)
                if home_cover_prob is None:
                    continue
                model_prob = home_cover_prob if pick_home else (1.0 - home_cover_prob)
                price = _side_price(row, "home_spread_price" if pick_home else "away_spread_price")
                edge_value = abs(cover_edge)
                ev_value = _probability_ev(model_prob, price)
                rows.append(
                    {
                        "market": "ATS",
                        "side": home_name if pick_home else away_name,
                        "home": home_name,
                        "away": away_name,
                        "date": date_str,
                        "ev": round(ev_value, 6),
                        "price": price,
                        # A row with no price has no implied probability.
                        "implied_prob": (
                            round(_american_price_to_prob(price), 6)
                            if _american_price_to_prob(price) is not None
                            else None
                        ),
                        "edge": round(edge_value, 6),
                        "line": round(abs(market_home_margin), 6),
                        "pred_margin": round(pred_margin if pick_home else (-pred_margin), 6),
                        "market_home_margin": round(market_home_margin, 6),
                        "pred_total": "",
                        "tier": _recommendation_tier(market="ATS", ev_value=ev_value, edge_value=edge_value),
                    }
                )

            if total_line is not None:
                total_edge = pred_total - total_line
                pick_over = total_edge >= 0
                total_over_prob = _margin_win_prob(total_edge, scale=10.5)
                if total_over_prob is None:
                    continue
                model_prob = total_over_prob if pick_over else (1.0 - total_over_prob)
                price = _side_price(row, "total_over_price" if pick_over else "total_under_price")
                ev_value = _probability_ev(model_prob, price)
                rows.append(
                    {
                        "market": "TOTAL",
                        "side": "Over" if pick_over else "Under",
                        "home": home_name,
                        "away": away_name,
                        "date": date_str,
                        "ev": round(ev_value, 6),
                        "price": price,
                        # A row with no price has no implied probability.
                        "implied_prob": (
                            round(_american_price_to_prob(price), 6)
                            if _american_price_to_prob(price) is not None
                            else None
                        ),
                        "edge": round(total_edge, 6),
                        "line": round(total_line, 6),
                        "pred_margin": "",
                        "market_home_margin": "",
                        "pred_total": round(pred_total, 6),
                        "tier": _recommendation_tier(market="TOTAL", ev_value=ev_value, edge_value=total_edge),
                    }
                )

    if not rows:
        return 0, None

    out_path = processed_root / f"recommendations_{date_str}.csv"
    header_order = [
        "market",
        "side",
        "home",
        "away",
        "date",
        "ev",
        "price",
        "implied_prob",
        "edge",
        "line",
        "pred_margin",
        "market_home_margin",
        "pred_total",
        "tier",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header_order)
        writer.writeheader()
        for current in rows:
            writer.writerow({field: current.get(field, "") for field in header_order})
    return len(rows), out_path
    
def _seed_game_odds_from_raw_history(*, source_root: Path, date_str: str, log_file: Path) -> bool:
    processed_path = source_root / "data" / "processed" / f"game_odds_{date_str}.csv"
    if _path_has_meaningful_content(processed_path):
        return True

    raw_candidates = (
        source_root / "data" / "raw" / "games_nba_api.csv",
        source_root / "data" / "raw" / "games_nba_api.parquet",
    )
    raw_frame = None
    for candidate in raw_candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            if candidate.suffix.lower() == ".parquet":
                import pandas as pd

                raw_frame = pd.read_parquet(candidate)
            else:
                import pandas as pd

                raw_frame = pd.read_csv(candidate)
            break
        except Exception as exc:
            _append_log(log_file, f"Failed to read raw games history {candidate}: {exc}")
    if raw_frame is None or raw_frame.empty:
        return False

    import pandas as pd

    date_col = next((col for col in ("date", "game_date", "date_utc", "date_est") if col in raw_frame.columns), None)
    home_col = next((col for col in ("home_team", "home") if col in raw_frame.columns), None)
    away_col = next((col for col in ("visitor_team", "away_team", "away") if col in raw_frame.columns), None)
    if not date_col or not home_col or not away_col:
        return False

    day_frame = raw_frame.copy()
    day_frame[date_col] = pd.to_datetime(day_frame[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    day_frame = day_frame[day_frame[date_col] == date_str].copy()
    if day_frame.empty:
        return False

    out = day_frame[[date_col, home_col, away_col]].rename(
        columns={date_col: "date", home_col: "home_team", away_col: "visitor_team"}
    )
    out = out.dropna(subset=["home_team", "visitor_team"]).drop_duplicates().reset_index(drop=True)
    if out.empty:
        return False

    processed_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_csv(processed_path, out)
    _append_log(log_file, f"Seeded fallback game odds slate from raw history: {processed_path} (rows={len(out)})")
    return True


def _aggregate_game_odds_from_market_rows(
    group_rows: list[dict[str, object]], *, home_name: str, away_name: str
) -> dict[str, float | None]:
    # Ported from refresh_wnba_oddsapi_props.py: consensus moneyline/spread/
    # total from the raw h2h/spreads/totals rows in a props snapshot group.
    home_ml_values: list[float] = []
    away_ml_values: list[float] = []
    home_spread_values: list[float] = []
    away_spread_values: list[float] = []
    home_spread_price_values: list[float] = []
    away_spread_price_values: list[float] = []
    total_values: list[float] = []
    total_over_price_values: list[float] = []
    total_under_price_values: list[float] = []

    for current in group_rows:
        market = str(current.get("market") or "").strip().lower()
        outcome_name = str(current.get("outcome_name") or "").strip()
        point_value = _float_or_none(current.get("point"))
        price_value = _float_or_none(current.get("price"))
        if market == "h2h":
            if outcome_name == home_name and price_value is not None:
                home_ml_values.append(price_value)
            elif outcome_name == away_name and price_value is not None:
                away_ml_values.append(price_value)
        elif market == "spreads" and point_value is not None:
            if outcome_name == home_name:
                home_spread_values.append(point_value)
                if price_value is not None:
                    home_spread_price_values.append(price_value)
            elif outcome_name == away_name:
                away_spread_values.append(point_value)
                if price_value is not None:
                    away_spread_price_values.append(price_value)
        elif market == "totals" and point_value is not None:
            total_values.append(point_value)
            # The raw feed always carried per-side prices on the same rows
            # this loop was already reading for the point value -- they were
            # simply thrown away, which is why every downstream spread/total
            # row surfaced with fabricated -110 juice or got dropped (same
            # fix as refresh_wnba_oddsapi_props.py, 2026-08-02 assessment).
            if price_value is not None:
                if outcome_name.lower() == "over":
                    total_over_price_values.append(price_value)
                elif outcome_name.lower() == "under":
                    total_under_price_values.append(price_value)

    home_spread = _mean_or_none(home_spread_values)
    away_spread = _mean_or_none(away_spread_values)
    if home_spread is None and away_spread is not None:
        home_spread = -float(away_spread)
    if away_spread is None and home_spread is not None:
        away_spread = -float(home_spread)

    return {
        "home_ml": _mean_or_none(home_ml_values),
        "away_ml": _mean_or_none(away_ml_values),
        "home_spread": home_spread,
        "away_spread": away_spread,
        "home_spread_price": _mean_or_none(home_spread_price_values),
        "away_spread_price": _mean_or_none(away_spread_price_values),
        "total": _mean_or_none(total_values),
        "total_over_price": _mean_or_none(total_over_price_values),
        "total_under_price": _mean_or_none(total_under_price_values),
    }


def _game_odds_frame_has_prices(frame) -> bool:
    import pandas as pd

    if frame is None or getattr(frame, "empty", True):
        return False
    for column in ("home_ml", "away_ml", "home_spread", "away_spread", "total"):
        if column in frame.columns and pd.to_numeric(frame[column], errors="coerce").notna().any():
            return True
    return False


def _build_game_odds_rows_from_snapshot_frame(frame, *, date_str: str):
    """One consensus-priced game_odds row per matchup from a props snapshot.

    Same enrichment as refresh_wnba_oddsapi_props.py: the snapshot is fetched
    with h2h/spreads/totals alongside player-prop markets, so consensus
    moneyline/spread/total are derivable here instead of writing a bare
    matchup skeleton that leaves the smart sim's market anchors null.
    """
    import pandas as pd

    rows_out: list[dict[str, object]] = []
    working = frame.dropna(subset=["home_team", "away_team"])
    for (home_name, away_name), group in working.groupby(["home_team", "away_team"], sort=False):
        home_text = str(home_name).strip()
        away_text = str(away_name).strip()
        if not home_text or not away_text:
            continue
        row_payload: dict[str, object] = {
            "date": date_str,
            "game_id": "",
            "home_team": home_text,
            "visitor_team": away_text,
            "commence_time": "",
            "home_ml": None,
            "away_ml": None,
            "home_spread": None,
            "away_spread": None,
            "home_spread_price": None,
            "away_spread_price": None,
            "total": None,
            "total_over_price": None,
            "total_under_price": None,
            "bookmaker": "oddsapi_consensus",
        }
        for column, key in (("event_id", "game_id"), ("commence_time", "commence_time")):
            if column in group.columns:
                values = group[column].dropna()
                if not values.empty:
                    row_payload[key] = str(values.iloc[0]).strip()
        if "market" in group.columns:
            aggregated = _aggregate_game_odds_from_market_rows(
                group.to_dict("records"), home_name=home_text, away_name=away_text
            )
            for key in (
                "home_ml",
                "away_ml",
                "home_spread",
                "away_spread",
                "home_spread_price",
                "away_spread_price",
                "total",
                "total_over_price",
                "total_under_price",
            ):
                row_payload[key] = aggregated.get(key)
        rows_out.append(row_payload)
    return pd.DataFrame(rows_out)


def _seed_game_odds_from_props_snapshot(*, source_root: Path, date_str: str, log_file: Path) -> bool:
    processed_path = source_root / "data" / "processed" / f"game_odds_{date_str}.csv"
    snapshot_candidates = (
        source_root / "data" / "processed" / f"oddsapi_player_props_{date_str}.csv",
        source_root / "data" / "raw" / f"odds_nba_player_props_{date_str}.csv",
    )
    import pandas as pd

    if _path_has_meaningful_content(processed_path):
        snapshot_has_market_rows = False
        for candidate in snapshot_candidates:
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                candidate_frame = pd.read_csv(candidate, nrows=5)
            except Exception:
                continue
            if "market" in candidate_frame.columns:
                snapshot_has_market_rows = True
                break
        try:
            existing = pd.read_csv(processed_path)
        except Exception:
            existing = pd.DataFrame()
        if snapshot_has_market_rows and not _game_odds_frame_has_prices(existing):
            # A price-less skeleton (the old seeder's output) would otherwise
            # satisfy the reuse check forever, keeping the sim's market
            # anchors null even though the snapshot has real market rows.
            _append_log(
                log_file,
                f"Enriching price-less game_odds slate for {date_str} with consensus prices from props snapshot",
            )
        else:
            return True

    for candidate in snapshot_candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            frame = pd.read_csv(candidate)
        except Exception as exc:
            _append_log(log_file, f"Failed to read props snapshot {candidate}: {exc}")
            continue
        if frame.empty or not {"home_team", "away_team"}.issubset(frame.columns):
            continue
        out = _build_game_odds_rows_from_snapshot_frame(frame, date_str=date_str)
        if out.empty:
            continue
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_csv(processed_path, out)
        priced = int(pd.to_numeric(out.get("total"), errors="coerce").notna().sum()) if "total" in out.columns else 0
        _append_log(log_file, f"Seeded game odds slate from props snapshot: {processed_path} (rows={len(out)}, priced={priced})")
        return True
    return False


def _run_source_subprocess_cli_command(
    *,
    source_root: Path,
    package_name: str,
    command_parts: list[str],
    log_file: Path,
    heartbeat_cb: callable | None,
    timeout_s: float,
) -> int:
    code_root = _vendor_code_root(package_name)
    return _run_to_file(
        [
            _source_python(code_root),
            "-m",
            f"{package_name}.cli",
            *command_parts,
        ],
        log_file,
        cwd=code_root,
        env=_source_worker_env(code_root),
        timeout_s=timeout_s,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )


def _ensure_rotation_inputs_for_props_refresh(
    *,
    source_root: Path,
    package_name: str,
    date_str: str,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> None:
    """Build the rotation/lineup artifacts the smart sim silently degrades without.

    Mirrors refresh_wnba_oddsapi_props.py (minus write-pregame-expected-minutes,
    which only the WNBA fork's CLI provides). All steps are non-fatal and
    once-per-date via a marker file.
    """
    processed_root = source_root / "data" / "processed"
    marker_path = processed_root / f"_rotation_inputs_{date_str}.json"
    if _path_has_meaningful_content(marker_path):
        return
    try:
        yesterday = (dt.date.fromisoformat(str(date_str)) - dt.timedelta(days=1)).isoformat()
    except Exception:
        return
    results: dict[str, int] = {}
    steps = (
        (["update-rotations-espn-history", "--date", yesterday], 10 * 60),
        (["update-pbp-espn-history", "--date", yesterday], 10 * 60),
        (["build-lineup-teammate-effects"], 10 * 60),
    )
    for command_parts, timeout_s in steps:
        rc = _run_source_subprocess_cli_command(
            source_root=source_root,
            package_name=package_name,
            command_parts=list(command_parts),
            log_file=log_file,
            heartbeat_cb=heartbeat_cb,
            timeout_s=timeout_s,
        )
        results[command_parts[0]] = int(rc)
        if int(rc) != 0:
            _append_log(log_file, f"rotation input step {command_parts[0]} failed with exit code {int(rc)}; continuing")
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            json.dumps({"date": date_str, "built_at": dt.datetime.utcnow().isoformat(), "results": results}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _ensure_source_game_inputs(
    *,
    source_root: Path,
    package_name: str,
    date_str: str,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> dict[str, int]:
    processed_root = source_root / "data" / "processed"
    raw_root = source_root / "data" / "raw"
    raw_candidates = (
        raw_root / "games_nba_api.csv",
        raw_root / "games_nba_api.parquet",
    )
    feature_candidates = (
        processed_root / "features.csv",
        processed_root / "features.parquet",
    )

    rc_schedule = _run_source_subprocess_cli_command(
        source_root=source_root,
        package_name=package_name,
        command_parts=["fetch-schedule"],
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
        timeout_s=10 * 60,
    )

    # A bare exists/size check let a partial fetch (confirmed live on the
    # WNBA twin: a single-season stub) satisfy this forever, which fed the
    # models multi-year rest-day outliers and produced garbage predictions.
    # Fetch when the history is missing OR stale, then heal from the
    # vendored checkout's committed copy if the fetch still left us stale.
    #
    # NBA's fetch prefers a bulk LeagueGameLog call (one per season) and
    # only falls back to walking ESPN/ScoreboardV2 one day at a time when
    # that endpoint is blocked -- but on the WNBA twin that day-by-day path
    # is the ONLY option (no bulk endpoint exists), and it measured out to
    # ~80 minutes for a full --years 10 walk against a 45-minute subprocess
    # timeout: it always dies partway through the first season on a
    # cold/stale start. Since prior seasons are final and can't gain new
    # games, only request the full bootstrap when genuinely needed --
    # this caps NBA's worst-case exposure too if LeagueGameLog ever gets
    # blocked on Render's IP and it falls onto the same slow path.
    rc_fetch = 0
    if _games_history_is_stale(raw_candidates[0], date_str=date_str):
        fetch_years = _games_history_fetch_years_needed(raw_candidates[0])
        rc_fetch = _run_source_subprocess_cli_command(
            source_root=source_root,
            package_name=package_name,
            command_parts=["fetch", "--years", str(fetch_years)],
            log_file=log_file,
            heartbeat_cb=heartbeat_cb,
            timeout_s=45 * 60,
        )
        _seed_games_history_from_checkout_if_fresher(
            raw_path=raw_candidates[0],
            package_name=package_name,
            date_str=date_str,
            feature_candidates=feature_candidates,
            log_file=log_file,
        )

    rc_build_features = 0
    features_missing = not any(
        path.exists() and path.is_file() and path.stat().st_size > 0 for path in feature_candidates
    )
    features_stale = _features_are_behind_history(feature_candidates, raw_candidates)
    if features_missing or features_stale:
        # Which of the two fired, because they mean different things: missing is
        # a cold start, stale is the `#351` case where the history moved and the
        # derived features silently did not.
        print(
            f"[nba] BUILD_FEATURES_TRIGGERED missing={features_missing} stale_vs_history={features_stale}",
            flush=True,
        )
        rc_build_features = _run_source_subprocess_cli_command(
            source_root=source_root,
            package_name=package_name,
            command_parts=["build-features"],
            log_file=log_file,
            heartbeat_cb=heartbeat_cb,
            timeout_s=20 * 60,
        )

    _seed_game_odds_from_props_snapshot(source_root=source_root, date_str=date_str, log_file=log_file)
    _seed_game_odds_from_raw_history(source_root=source_root, date_str=date_str, log_file=log_file)

    # Non-fatal: injury data feeds the enhanced feature set (9 features) and
    # the sim's exclusion/pace-drag inputs. Without this the only fetch was
    # the live loop's interval-gated lineup check, so downstream prediction
    # steps regularly ran with zero injury signal.
    rc_injuries = _run_source_subprocess_cli_command(
        source_root=source_root,
        package_name=package_name,
        command_parts=["fetch-injuries", "--date", date_str],
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
        timeout_s=3 * 60,
    )
    if int(rc_injuries) != 0:
        _append_log(log_file, f"fetch-injuries failed with exit code {int(rc_injuries)}; continuing without fresh injury data")

    _ensure_rotation_inputs_for_props_refresh(
        source_root=source_root,
        package_name=package_name,
        date_str=date_str,
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
    )

    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    if not game_cards_path.exists() or not game_cards_path.is_file() or _count_csv_rows_quick(game_cards_path) <= 0:
        _run_source_subprocess_cli_command(
            source_root=source_root,
            package_name=package_name,
            command_parts=["export-game-cards", "--date", date_str],
            log_file=log_file,
            heartbeat_cb=heartbeat_cb,
            timeout_s=20 * 60,
        )
    
    rc_predict_date = _run_source_predict_date(
        source_root=source_root,
        package_name=package_name,
        date_str=date_str,
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
    )
    return {
        "schedule": int(rc_schedule),
        "fetch": int(rc_fetch),
        "build_features": int(rc_build_features),
        "predict_date": int(rc_predict_date),
    }


def _run_source_predict_date(
    *,
    source_root: Path,
    package_name: str,
    date_str: str,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> int:
    code_root = _vendor_code_root(package_name)
    return _run_to_file(
        [
            _source_python(code_root),
            "-m",
            f"{package_name}.cli",
            "predict-date",
            "--date",
            date_str,
        ],
        log_file,
        cwd=code_root,
        env=_source_worker_env(code_root),
        timeout_s=20 * 60,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )


def _run_source_daily_update_cpu_fallback(
    *,
    source_root: Path,
    package_name: str,
    date_str: str,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> int:
    raise RuntimeError("CPU daily-update fallback is disabled; fix predict-date input failures instead")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(str(os.environ.get(name, str(default))).strip()))
    except Exception:
        return int(default)


def _env_timeout_s(name: str, default_s: float) -> float | None:
    try:
        raw = str(os.environ.get(name, str(default_s))).strip()
        value = float(raw)
    except Exception:
        value = float(default_s)
    return None if value <= 0 else float(value)


def _run_to_file(
    args: list[str],
    log_file: Path,
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: float | None,
    heartbeat_cb: callable | None,
    heartbeat_every_s: float = 15.0,
) -> int:
    cmd_text = " ".join(shlex.quote(str(a)) for a in args)
    _append_log(log_file, f"$ {cmd_text}")
    start = time.time()
    last_heartbeat = start
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8", errors="ignore") as out:
        proc = subprocess.Popen(
            [str(a) for a in args],
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        while True:
            try:
                return int(proc.wait(timeout=1.0))
            except subprocess.TimeoutExpired:
                now = time.time()
                if heartbeat_cb and (now - last_heartbeat) >= max(1.0, float(heartbeat_every_s)):
                    try:
                        heartbeat_cb()
                    except Exception:
                        pass
                    last_heartbeat = now
                if timeout_s is not None and (now - start) >= float(timeout_s):
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=5.0)
                    except Exception:
                        pass
                    _append_log(log_file, f"Command timed out after {int(timeout_s)}s")
                    return 124


def _season_year_for_date(date_str: str) -> int:
    parsed = dt.datetime.strptime(date_str, "%Y-%m-%d")
    return parsed.year if parsed.month >= 7 else (parsed.year - 1)


def _season_str_from_year(season_year: int) -> str:
    return f"{season_year}-{(season_year + 1) % 100:02d}"


def _active_player_logs_paths(source_root: Path) -> list[Path]:
    return [
        source_root / "data" / "processed" / "player_logs.parquet",
        source_root / "data" / "processed" / "player_logs.csv",
    ]


def _active_player_logs_fallback_paths(source_root: Path) -> list[Path]:
    processed_root = source_root / "data" / "processed"
    paths = [
        processed_root / "boxscores_history.parquet",
        processed_root / "boxscores_history.csv",
    ]
    for pattern in ("boxscores_*.parquet", "boxscores_*.csv"):
        paths.extend(sorted(processed_root.glob(pattern)))
    return [path for path in paths if path.exists() and path.stat().st_size > 0]


def _file_is_fresh(path: Path, *, max_age_minutes: int) -> bool:
    try:
        if max_age_minutes <= 0:
            return path.exists() and path.stat().st_size > 0
        if not path.exists() or path.stat().st_size <= 0:
            return False
        age_s = max(0.0, time.time() - float(path.stat().st_mtime))
        return age_s <= (float(max_age_minutes) * 60.0)
    except Exception:
        return False


def _player_logs_ready(source_root: Path, *, max_age_minutes: int) -> bool:
    paths = _active_player_logs_paths(source_root) + _active_player_logs_fallback_paths(source_root)
    return any(_file_is_fresh(path, max_age_minutes=max_age_minutes) for path in paths)


def _bootstrap_local_boxscores_history_for_props(*, source_root: Path, date_str: str, log_file: Path) -> tuple[bool, str | None]:
    processed_root = source_root / "data" / "processed"
    try:
        from syndicate.features.shared.basketball_boxscores_history import bootstrap_boxscores_history_local

        result = bootstrap_boxscores_history_local(
            processed_root=processed_root,
            date_str=date_str,
            league_code="nba",
            lookback_days=max(7, _env_int("REFRESH_PLAYER_LOGS_BOOTSTRAP_LOOKBACK_DAYS", 35)),
        )
    except Exception as exc:
        _append_log(log_file, f"local boxscores bootstrap failed: {exc}")
        return False, f"local boxscores bootstrap failed: {exc}"

    if int(result.get("history_rows") or 0) > 0 and str(result.get("wrote") or "").strip():
        _append_log(log_file, f"bootstrapped local boxscores history via ESPN: {result.get('wrote')}")
        return True, None
    reason = str(result.get("error") or "local boxscores bootstrap wrote no history rows").strip()
    _append_log(log_file, f"local boxscores bootstrap unavailable: {reason}")
    return False, reason


def _ensure_player_logs_for_props_refresh(*, source_root: Path, date_str: str, log_file: Path, heartbeat_cb: callable) -> tuple[bool, str | None]:
    raw_max_age = (
        os.environ.get("REFRESH_PLAYER_LOGS_MAX_AGE_HOURS")
        or os.environ.get("DAILY_PLAYER_LOGS_MAX_AGE_HOURS")
        or "12"
    ).strip()
    try:
        max_age_minutes = int(max(0.0, float(raw_max_age) * 60.0))
    except Exception:
        max_age_minutes = 12 * 60

    if _player_logs_ready(source_root, max_age_minutes=max_age_minutes):
        return True, None
    if any(path.exists() and path.stat().st_size > 0 for path in _active_player_logs_paths(source_root)):
        return True, None
    fallback_paths = [path for path in _active_player_logs_fallback_paths(source_root) if path.exists() and path.stat().st_size > 0]
    if fallback_paths:
        # Bare existence used to be treated as "good enough" here forever --
        # once boxscores_history.csv/.parquet existed at all, this branch
        # returned True on every refresh tick and the (network-fetching)
        # bootstrap below never ran again, so the file could go weeks stale
        # silently (observed 2026-07-20 on the WNBA side of this same gate).
        # Keep the original leniency (don't hard-block props modeling over a
        # short outage) but bound it: only skip the bootstrap when the
        # file's own newest game date is within max_age_days.
        from syndicate.features.shared.basketball_boxscores_history import boxscore_history_is_stale

        max_age_days = _env_int("REFRESH_PLAYER_LOGS_FALLBACK_MAX_AGE_DAYS", 5)
        if not boxscore_history_is_stale(source_root / "data" / "processed", max_age_days=max_age_days):
            return True, None

    bootstrapped_ok, bootstrap_error = _bootstrap_local_boxscores_history_for_props(
        source_root=source_root,
        date_str=date_str,
        log_file=log_file,
    )
    if bootstrapped_ok:
        return True, None

    allow_fetch_on_miss = (os.environ.get("REFRESH_PLAYER_LOGS_FETCH_ON_MISS") or "0").strip().lower() in {"1", "true", "yes"}
    if not allow_fetch_on_miss:
        return False, bootstrap_error or "player_logs not found and no local boxscores fallback is available; run fetch-player-logs"
    _append_log(log_file, "player_logs missing and source fetch fallback is disabled in Syndicate-only mode")
    return False, "player_logs missing and no local fetch fallback is available"


def _predict_date_backoff_marker_path(*, source_root: Path, date_str: str) -> Path:
    return source_root / "data" / "processed" / f".predict_date_attempt_{date_str}.json"


def _predict_date_recently_attempted(*, source_root: Path, date_str: str, cooldown_minutes: float) -> bool:
    if cooldown_minutes <= 0:
        return False
    marker_path = _predict_date_backoff_marker_path(source_root=source_root, date_str=date_str)
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
        started_at = dt.datetime.fromisoformat(str(payload.get("started_at") or ""))
    except Exception:
        return False
    age_minutes = (dt.datetime.now(dt.timezone.utc) - started_at).total_seconds() / 60.0
    return age_minutes < cooldown_minutes


def _mark_predict_date_attempt(*, source_root: Path, date_str: str) -> None:
    marker_path = _predict_date_backoff_marker_path(source_root=source_root, date_str=date_str)
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            json.dumps({"started_at": dt.datetime.now(dt.timezone.utc).isoformat()}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _predict_date_backoff_minutes() -> float:
    raw = (os.environ.get("REFRESH_PREDICT_DATE_BACKOFF_MINUTES") or "10").strip()
    try:
        return max(0.0, float(raw))
    except Exception:
        return 10.0


def _ensure_game_predictions_for_props_refresh(*, source_root: Path, date_str: str, log_file: Path, heartbeat_cb: callable) -> tuple[bool, str | None]:
    processed_root = source_root / "data" / "processed"
    pred_path = processed_root / f"predictions_{date_str}.csv"
    if pred_path.exists() and pred_path.is_file() and _count_csv_rows_quick(pred_path) > 0:
        return True, None

    fallback_candidates = [
        processed_root / f"games_predictions_npu_{date_str}.csv",
        source_root / f"predictions_{date_str}.csv",
        source_root / "data" / "processed" / f"games_predictions_npu_{date_str}.csv",
    ]
    for candidate in fallback_candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            if candidate.resolve() != pred_path.resolve():
                pred_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, pred_path)
        except Exception:
            pass
        if pred_path.exists() and pred_path.is_file() and _count_csv_rows_quick(pred_path) > 0:
            _append_log(log_file, f"Using existing game predictions artifact: {pred_path}")
            return True, None

    backoff_minutes = _predict_date_backoff_minutes()
    if _predict_date_recently_attempted(source_root=source_root, date_str=date_str, cooldown_minutes=backoff_minutes):
        # predict-date loads ~20 sklearn/ONNX models (measured ~175MB peak RSS)
        # that this pipeline never used to pay for while predict-date was
        # silently failing with ModuleNotFoundError (fixed above). Now that it
        # actually runs, a crash mid-load (OOM-killed container, timeout) would
        # otherwise retry this same expensive bootstrap every single refresh
        # cycle with no cooldown -- a tight crash-loop. Back off instead.
        return False, f"predict-date bootstrap attempted within the last {backoff_minutes:.0f} min; backing off to avoid repeated OOM retries"

    _append_log(log_file, f"Generating required game predictions artifact via source bootstrap: {pred_path}")
    _mark_predict_date_attempt(source_root=source_root, date_str=date_str)
    bootstrap_result = _ensure_source_game_inputs(
        source_root=source_root,
        package_name="nba_betting",
        date_str=date_str,
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
    )
    code_root = _vendor_code_root("nba_betting")
    for repo_pred_path in (
        code_root / "data" / "processed" / f"predictions_{date_str}.csv",
        source_root / f"predictions_{date_str}.csv",
    ):
        if (not pred_path.exists() or _count_csv_rows_quick(pred_path) <= 0) and repo_pred_path.exists() and repo_pred_path.is_file():
            try:
                pred_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo_pred_path, pred_path)
            except Exception:
                pass
    if _count_csv_rows_quick(pred_path) <= 0:
        game_odds_path = processed_root / f"game_odds_{date_str}.csv"
        return False, f"source bootstrap did not produce {pred_path.name} (rc={bootstrap_result.get('predict_date')})"
    _append_log(log_file, f"Generated game predictions at {pred_path} (rows={_count_csv_rows_quick(pred_path)})")
    return True, None


def _predict_props_cli_args(*, source_root: Path, date_str: str, out_path: Path) -> list[str]:
    # Mirrors refresh_wnba_oddsapi_props.py: 150 made sense when smart_sim
    # was a flat point-mean stub, now that the real engine is wired in more
    # samples meaningfully tighten prop tails/interval bands. NBA slates run
    # larger than WNBA's (up to ~12-13 games some nights) -- at the measured
    # ~0.16-0.2s/sim/game (workers=1, sequential), a full slate at 500 sims
    # could run ~15-20+ minutes; re-check this default once NBA season is
    # actually active and tune SMART_SIM_WORKERS/N_SIMS per real slate sizes
    # rather than assuming WNBA's numbers transfer directly.
    smart_sim_n_sims = max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS", 500))
    smart_sim_workers = max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_WORKERS", 1))
    calib_window = max(1, _env_int("REFRESH_PREDICT_PROPS_CALIB_WINDOW", 7))
    player_calib_window = max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_CALIB_WINDOW", 30))
    player_min_pairs = max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_MIN_PAIRS", 6))
    player_shrink_k = max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_SHRINK_K", 8))
    args = [
        "predict-props",
        "--date",
        date_str,
        "--out",
        str(out_path),
        "--slate-only",
        "--calibrate",
        "--calib-window",
        str(calib_window),
        "--use-pure-onnx",
    ]
    if _env_bool("REFRESH_PREDICT_PROPS_CALIBRATE_PLAYER", True):
        args.extend([
            "--calibrate-player",
            "--player-calib-window",
            str(player_calib_window),
            "--player-min-pairs",
            str(player_min_pairs),
            "--player-shrink-k",
            str(player_shrink_k),
        ])
    else:
        args.append("--no-calibrate-player")
    if _env_bool("REFRESH_PREDICT_PROPS_USE_SMART_SIM", True):
        args.extend([
            "--use-smart-sim",
            "--smart-sim-n-sims",
            str(smart_sim_n_sims),
            "--smart-sim-workers",
            str(smart_sim_workers),
        ])
        args.append("--smart-sim-pbp" if _env_bool("REFRESH_PREDICT_PROPS_SMART_SIM_PBP", True) else "--no-smart-sim-pbp")
    else:
        args.append("--no-use-smart-sim")
    return args


def _run_source_cli_command(
    source_root: Path,
    args: list[str],
    log_file: Path,
    *,
    heartbeat_cb: callable | None,
    heartbeat_every_s: float = 15.0,
) -> int:
    cmd_text = " ".join(shlex.quote(str(a)) for a in args)
    _append_log(log_file, f"$ source-cli {cmd_text}")

    cli_module = _load_source_cli(source_root)
    stop_event = threading.Event()
    heartbeat_thread = None
    if heartbeat_cb is not None:
        def _heartbeat_loop() -> None:
            while not stop_event.wait(max(1.0, float(heartbeat_every_s))):
                try:
                    heartbeat_cb()
                except Exception:
                    pass

        heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
        heartbeat_thread.start()

    previous_cwd = Path.cwd()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_file.open("a", encoding="utf-8", errors="ignore") as out:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                os.chdir(source_root)
                try:
                    cli_module.cli.main(args, standalone_mode=False)  # type: ignore[attr-defined]
                    return 0
                except SystemExit as exc:
                    code = exc.code
                    if code is None:
                        return 0
                    if isinstance(code, int):
                        return int(code)
                    return 1
                except Exception:
                    traceback.print_exc(file=out)
                    return 1
    finally:
        try:
            os.chdir(previous_cwd)
        except Exception:
            pass
        stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1.0)


def _run_refresh_via_cli(
    *,
    source_root: Path,
    date_str: str,
    regions: str,
    bookmakers: str,
    markets: str,
    do_edges: bool,
    do_export: bool,
    do_push: bool,
    log_file: Path,
    started_at: str | None = None,
    mode: str = "full",
) -> dict[str, object]:
    refresh_mode = str(mode or "full").strip().lower() or "full"
    raw_root = source_root / "data" / "raw"
    processed_root = source_root / "data" / "processed"
    package_name = source_root.name
    raw_fp = raw_root / f"odds_nba_player_props_{date_str}.csv"
    pred_fp = processed_root / f"props_predictions_{date_str}.csv"
    edges_fp = processed_root / f"props_edges_{date_str}.csv"
    rec_fp = processed_root / f"props_recommendations_{date_str}.csv"
    started_iso = started_at or dt.datetime.utcnow().isoformat()
    state: dict[str, object] = {
        "date": str(date_str),
        "started_at": started_iso,
        "ended_at": None,
        "phase": "snapshot",
        "phase_started_at": started_iso,
        "heartbeat_at": dt.datetime.utcnow().isoformat(),
        "rc_snapshot": -1,
        "rc_edges": (-2 if do_edges else None),
        "rc_export": (-2 if do_export else None),
        "snapshot_rows": 0,
        "predictions_rows": 0,
        "edges_rows": 0,
        "recs_rows": 0,
        "game_cards_rows": 0,
        "cards_sim_detail_games": 0,
        "smart_sim_files": 0,
        "snapshot_path": str(raw_fp),
        "predictions_path": str(pred_fp),
        "edges_path": str(edges_fp),
        "recs_path": str(rec_fp),
        "snapshot_alias_path": str(processed_root / f"oddsapi_player_props_{date_str}.csv"),
        "snapshot_alias_rows": 0,
        "duration_s": None,
        "error": None,
        "mode": refresh_mode,
    }
    started_ts = time.time()

    def _touch_progress() -> None:
        state["heartbeat_at"] = dt.datetime.utcnow().isoformat()

    py = _source_python(source_root)
    env = _source_worker_env(source_root)

    rc_snapshot = _run_to_file(
        _owned_snapshot_cli_args(
            date_str=date_str,
            out_path=raw_fp,
            regions=regions,
            bookmakers=bookmakers,
            markets=markets,
        ),
        log_file,
        cwd=REPO_ROOT,
        env=_local_worker_env(),
        timeout_s=15 * 60,
        heartbeat_cb=_touch_progress,
    )
    state["rc_snapshot"] = int(rc_snapshot)
    state["snapshot_rows"] = int(_count_csv_rows_quick(raw_fp))
    alias_path, alias_rows, alias_error = _materialize_processed_snapshot_alias(
        processed_root=processed_root,
        date_str=date_str,
        snapshot_path=raw_fp,
        log_file=log_file,
    )
    state["snapshot_alias_path"] = str(alias_path)
    state["snapshot_alias_rows"] = int(alias_rows)
    if alias_error and int(state["snapshot_rows"] or 0) > 0:
        state["error"] = f"snapshot alias write failed: {alias_error}"

    pred_ready = False
    if refresh_mode == "full" and not state.get("error") and int(state["snapshot_rows"] or 0) > 0 and (do_edges or do_export):
        state["phase"] = "predictions"
        state["phase_started_at"] = dt.datetime.utcnow().isoformat()
        player_logs_ok, player_logs_error = _ensure_player_logs_for_props_refresh(
            source_root=source_root,
            date_str=date_str,
            log_file=log_file,
            heartbeat_cb=_touch_progress,
        )
        if state.get("error"):
            pass
        elif not player_logs_ok:
            state["error"] = player_logs_error or f"player_logs missing before predict-props for {date_str}"
        else:
            game_predictions_ok, game_predictions_error = _ensure_game_predictions_for_props_refresh(
                source_root=source_root,
                date_str=date_str,
                log_file=log_file,
                heartbeat_cb=_touch_progress,
            )
            rc_pred = 1
            if not game_predictions_ok:
                state["error"] = game_predictions_error or f"predictions missing before predict-props for {date_str}"
            else:
                try:
                    _touch_progress()
                    _, _ = export_props_predictions_local(
                        source_root=source_root,
                        date_str=date_str,
                        out_path=pred_fp,
                        calib_window=max(1, _env_int("REFRESH_PREDICT_PROPS_CALIB_WINDOW", 7)),
                        calibrate_player=_env_bool("REFRESH_PREDICT_PROPS_CALIBRATE_PLAYER", True),
                        player_calib_window=max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_CALIB_WINDOW", 30)),
                        player_min_pairs=max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_MIN_PAIRS", 6)),
                        player_shrink_k=max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_SHRINK_K", 8)),
                        use_smart_sim=_env_bool("REFRESH_PREDICT_PROPS_USE_SMART_SIM", True),
                        smart_sim_n_sims=max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS", 500)),
                        smart_sim_pbp=_env_bool("REFRESH_PREDICT_PROPS_SMART_SIM_PBP", True),
                        smart_sim_workers=max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_WORKERS", 1)),
                        log_file=log_file,
                        heartbeat_cb=_touch_progress,
                        heartbeat_every_s=5.0,
                    )
                    _touch_progress()
                    rc_pred = 0
                except Exception:
                    _append_log(log_file, traceback.format_exc())
                    rc_pred = 1
            state["predictions_rows"] = int(_count_csv_rows_quick(pred_fp))
            if int(rc_pred) != 0:
                state["error"] = f"predict-props failed with exit code {int(rc_pred)}"
            elif int(state["predictions_rows"] or 0) <= 0:
                state["error"] = f"predict-props wrote no rows to {pred_fp.name} for {date_str}"
            else:
                pred_ready = True
    elif int(state["snapshot_rows"] or 0) <= 0:
        state["rc_edges"] = None if do_edges else state.get("rc_edges")
        state["rc_export"] = None if do_export else state.get("rc_export")

    if refresh_mode == "full" and pred_ready and do_edges:
        state["phase"] = "edges"
        state["phase_started_at"] = dt.datetime.utcnow().isoformat()
        state["rc_edges"] = -1
        try:
            _touch_progress()
            _, _ = export_props_edges_local(
                source_root=source_root,
                date_str=date_str,
                raw_path=raw_fp,
                predictions_path=pred_fp,
                out_path=edges_fp,
                bookmakers=bookmakers,
                log_file=log_file,
                heartbeat_cb=_touch_progress,
                heartbeat_every_s=5.0,
            )
            _touch_progress()
            rc_edges = 0
        except Exception:
            rc_edges = 1
        state["rc_edges"] = int(rc_edges)
        state["edges_rows"] = int(_count_csv_rows_quick(edges_fp))
        if int(rc_edges) != 0:
            state["error"] = f"props-edges failed with exit code {int(rc_edges)}"
        elif int(state["snapshot_rows"] or 0) > 0 and int(state["edges_rows"] or 0) <= 0:
            state["error"] = "props-edges produced zero rows after a non-empty snapshot"

    if refresh_mode == "full" and do_export and not state.get("error"):
        state["phase"] = "export"
        state["phase_started_at"] = dt.datetime.utcnow().isoformat()
        state["rc_export"] = -1
        try:
            _touch_progress()
            rc_local_props_export = 0
            if pred_ready:
                _, _ = export_props_recommendations_local(processed_root=processed_root, date_str=date_str)
                _touch_progress()
            else:
                _append_log(log_file, f"Skipping local props recommendations export for {date_str}: props predictions were not refreshed")
            game_cards_rows, local_game_cards_path = _ensure_source_game_cards_export(
                source_root=source_root,
                package_name=package_name,
                date_str=date_str,
                processed_root=processed_root,
                log_file=log_file,
                heartbeat_cb=_touch_progress,
            )
            rc_game_cards = 0 if local_game_cards_path is not None and int(game_cards_rows) > 0 else 1
            _, local_recommendations_path = _build_local_game_recommendations_artifact(processed_root=processed_root, date_str=date_str)
            rc_recommendations = 0 if local_recommendations_path is not None else 1
            rc_export = 0 if int(rc_local_props_export) == 0 and int(rc_recommendations) == 0 and int(rc_game_cards) == 0 else 1
        except Exception:
            _append_log(log_file, traceback.format_exc())
            rc_export = 1
        state["rc_export"] = int(rc_export)
        state["recs_rows"] = int(_count_csv_rows_quick(rec_fp))
        source_game_cards_rows = int(_count_csv_rows_quick(source_root / 'data' / 'processed' / f'game_cards_{date_str}.csv'))
        if int(rc_export) != 0:
            no_data_export = (
                int(state.get("snapshot_rows") or 0) <= 0
                and int(state.get("predictions_rows") or 0) <= 0
                and int(state.get("edges_rows") or 0) <= 0
                and int(state.get("recs_rows") or 0) <= 0
                and int(game_cards_rows or 0) <= 0
                and source_game_cards_rows <= 0
            )
            export_artifacts_ready = (
                int(state.get("snapshot_rows") or 0) > 0
                and int(state.get("predictions_rows") or 0) > 0
                and (not do_edges or int(state.get("edges_rows") or 0) > 0)
                and int(state.get("recs_rows") or 0) > 0
                and int(game_cards_rows or 0) > 0
            )
            if no_data_export:
                state["warning"] = f"NBA odds refresh produced no rows for {date_str}; export was skipped as a no-data run"
                state["rc_export"] = 0
                rc_export = 0
            elif export_artifacts_ready:
                state["warning"] = f"NBA export stage returned {rc_export} but required artifacts were present; treating as warning for {date_str}"
                state["rc_export"] = 0
                rc_export = 0
            else:
                state["error"] = f"export-props-recommendations failed with exit code {int(rc_export)}"

    # Build cards_sim_detail in source processed space before parity gating.
    # The source CLI does not emit this file directly; we derive it from /api/cards.
    source_processed_root = source_root / "data" / "processed"
    if refresh_mode == "full" and do_export and not state.get("error") and int(state.get("snapshot_rows") or 0) > 0:
        try:
            _export_cards_sim_detail_snapshot(
                source_root=source_root,
                date_str=date_str,
                processed_root=source_processed_root,
            )
        except Exception as exc:
            _append_log(log_file, f"cards_sim_detail snapshot export failed before parity gate: {exc}")

    state["snapshot_rows"] = int(_count_csv_rows_quick(raw_fp))
    state["predictions_rows"] = int(_count_csv_rows_quick(pred_fp)) if refresh_mode == "full" else int(state.get("predictions_rows") or 0)
    state["edges_rows"] = int(_count_csv_rows_quick(edges_fp)) if refresh_mode == "full" else int(state.get("edges_rows") or 0)
    state["recs_rows"] = int(_count_csv_rows_quick(rec_fp)) if refresh_mode == "full" else int(state.get("recs_rows") or 0)
    state["snapshot_alias_rows"] = int(_count_csv_rows_quick(Path(str(state.get("snapshot_alias_path") or ""))))
    source_game_cards_path = source_processed_root / f"game_cards_{date_str}.csv"
    source_cards_sim_detail_path = source_processed_root / f"cards_sim_detail_{date_str}.json"
    state["game_cards_rows"] = int(_count_csv_rows_quick(source_game_cards_path))
    state["cards_sim_detail_games"] = int(_count_cards_sim_detail_games(source_cards_sim_detail_path))
    state["smart_sim_files"] = int(_count_matching_files(source_processed_root, f"smart_sim_{date_str}_*.json"))
    if bool(do_export) and int(state["snapshot_rows"] or 0) > 0 and int(state["game_cards_rows"] or 0) > 0 and int(state["cards_sim_detail_games"] or 0) <= 0:
        state["error"] = f"cards_sim_detail_{date_str}.json has zero games while game_cards_{date_str}.csv has rows"
        state["game_cards_rows"] = int(_count_csv_rows_quick(source_game_cards_path))
        state["cards_sim_detail_games"] = int(_count_cards_sim_detail_games(source_cards_sim_detail_path))
        state["smart_sim_files"] = int(_count_matching_files(source_processed_root, f"smart_sim_{date_str}_*.json"))
    state["phase"] = "done"
    ended = dt.datetime.utcnow().isoformat()
    state["phase_started_at"] = ended
    state["heartbeat_at"] = ended
    state["ended_at"] = ended
    state["duration_s"] = float(max(0.0, time.time() - started_ts))
    if do_push:
        _append_log(log_file, "do_push requested but push is not implemented in the Syndicate-owned runner")
    return state


def _existing_refresh_state(*, source_root: Path, date_str: str, do_edges: bool, do_export: bool, started_at: str | None = None, input_hash: str | None = None) -> dict[str, object] | None:
    raw_root = source_root / "data" / "raw"
    processed_root = source_root / "data" / "processed"
    snapshot_path = raw_root / f"odds_nba_player_props_{date_str}.csv"
    snapshot_alias_path = processed_root / f"oddsapi_player_props_{date_str}.csv"
    predictions_path = processed_root / f"props_predictions_{date_str}.csv"
    edges_path = processed_root / f"props_edges_{date_str}.csv"
    recs_path = processed_root / f"props_recommendations_{date_str}.csv"

    required_paths = [snapshot_path, snapshot_alias_path]
    if do_edges or do_export:
        required_paths.append(predictions_path)
    if do_edges:
        required_paths.append(edges_path)
    if do_export:
        required_paths.append(recs_path)
    if any(not _path_has_meaningful_content(path) for path in required_paths):
        return None

    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    cards_sim_detail_path = processed_root / f"cards_sim_detail_{date_str}.json"
    game_cards_rows = int(_count_csv_rows_quick(game_cards_path))
    cards_sim_detail_games = int(_count_cards_sim_detail_games(cards_sim_detail_path))
    smart_sim_files = int(_count_matching_files(processed_root, f"smart_sim_{date_str}_*.json"))
    if bool(do_export) and int(_count_csv_rows_quick(snapshot_path)) > 0 and game_cards_rows > 0 and cards_sim_detail_games <= 0 and smart_sim_files <= 0:
        return None

    started = str(started_at or dt.datetime.utcnow().isoformat())
    ended = dt.datetime.utcnow().isoformat()
    return {
        "date": str(date_str),
        "started_at": started,
        "ended_at": ended,
        "phase": "done",
        "phase_started_at": ended,
        "heartbeat_at": ended,
        "rc_snapshot": 0,
        "rc_edges": (0 if do_edges else None),
        "rc_export": (0 if do_export else None),
        "snapshot_rows": int(_count_csv_rows_quick(snapshot_path)),
        "predictions_rows": int(_count_csv_rows_quick(predictions_path)),
        "edges_rows": int(_count_csv_rows_quick(edges_path)),
        "recs_rows": int(_count_csv_rows_quick(recs_path)),
        "game_cards_rows": game_cards_rows,
        "cards_sim_detail_games": cards_sim_detail_games,
        "smart_sim_files": smart_sim_files,
        "snapshot_path": str(snapshot_path),
        "predictions_path": str(predictions_path),
        "edges_path": str(edges_path),
        "recs_path": str(recs_path),
        "snapshot_alias_path": str(snapshot_alias_path),
        "snapshot_alias_rows": int(_count_csv_rows_quick(snapshot_alias_path)),
        "duration_s": 0.0,
        "error": None,
        "reused_existing_outputs": True,
    }


def _existing_artifact_bundle_state(*, artifact_root: Path, date_str: str, do_edges: bool, do_export: bool, started_at: str | None = None, input_hash: str | None = None) -> dict[str, object] | None:
    raw_root = artifact_root / "data" / "raw"
    processed_root = artifact_root / "data" / "processed"
    snapshot_path = raw_root / f"odds_nba_player_props_{date_str}.csv"
    snapshot_alias_path = processed_root / f"oddsapi_player_props_{date_str}.csv"
    predictions_path = processed_root / f"props_predictions_{date_str}.csv"
    edges_path = processed_root / f"props_edges_{date_str}.csv"
    recs_path = processed_root / f"props_recommendations_{date_str}.csv"

    required_paths = [snapshot_path, snapshot_alias_path]
    if do_edges or do_export:
        required_paths.append(predictions_path)
    if do_edges:
        required_paths.append(edges_path)
    if do_export:
        required_paths.append(recs_path)
    if any(not _path_has_meaningful_content(path) for path in required_paths):
        return None

    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    cards_sim_detail_path = processed_root / f"cards_sim_detail_{date_str}.json"
    game_cards_rows = int(_count_csv_rows_quick(game_cards_path))
    cards_sim_detail_games = int(_count_cards_sim_detail_games(cards_sim_detail_path))
    smart_sim_files = int(_count_matching_files(processed_root, f"smart_sim_{date_str}_*.json"))
    if bool(do_export) and int(_count_csv_rows_quick(snapshot_path)) > 0 and game_cards_rows > 0 and cards_sim_detail_games <= 0 and smart_sim_files <= 0:
        return None

    started = str(started_at or dt.datetime.utcnow().isoformat())
    ended = dt.datetime.utcnow().isoformat()
    return {
        "date": str(date_str),
        "started_at": started,
        "ended_at": ended,
        "phase": "done",
        "phase_started_at": ended,
        "heartbeat_at": ended,
        "rc_snapshot": 0,
        "rc_edges": (0 if do_edges else None),
        "rc_export": (0 if do_export else None),
        "snapshot_rows": int(_count_csv_rows_quick(snapshot_path)),
        "predictions_rows": int(_count_csv_rows_quick(predictions_path)),
        "edges_rows": int(_count_csv_rows_quick(edges_path)),
        "recs_rows": int(_count_csv_rows_quick(recs_path)),
        "game_cards_rows": game_cards_rows,
        "cards_sim_detail_games": cards_sim_detail_games,
        "smart_sim_files": smart_sim_files,
        "snapshot_path": str(snapshot_path),
        "predictions_path": str(predictions_path),
        "edges_path": str(edges_path),
        "recs_path": str(recs_path),
        "snapshot_alias_path": str(snapshot_alias_path),
        "snapshot_alias_rows": int(_count_csv_rows_quick(snapshot_alias_path)),
        "duration_s": 0.0,
        "error": None,
        "reused_existing_artifact_bundle": True,
        "artifact_bundle_root": str(artifact_root),
    }


def _processed_source_directory(state: dict[str, object]) -> Path | None:
    for key in ("snapshot_alias_path", "predictions_path", "edges_path", "recs_path"):
        source_text = str(state.get(key) or "").strip()
        if not source_text:
            continue
        source = Path(source_text)
        if source.exists():
            return source.resolve().parent
    return None


def _load_module_from_path(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _canon_boxscore_game_id(value: object) -> str:
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 8:
        return f"00{digits}"
    if len(digits) == 9:
        return f"0{digits}"
    return digits or text


def _split_player_name(value: object) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    parts = text.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _materialize_local_boxscore_cache_for_player_artifacts(*, processed_root: Path, date_str: str) -> int:
    boxscores_path = processed_root / f"boxscores_{date_str}.csv"
    if not boxscores_path.exists():
        return 0

    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    team_to_game_id: dict[str, str] = {}
    if game_cards_path.exists():
        with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                game_id = _canon_boxscore_game_id((row or {}).get("game_id"))
                if not game_id:
                    continue
                for key in ("home_tri", "away_tri"):
                    team_tri = str((row or {}).get(key) or "").strip().upper()
                    if team_tri and team_tri not in team_to_game_id:
                        team_to_game_id[team_tri] = game_id

    rows_by_game: dict[str, list[dict[str, str]]] = {}
    with boxscores_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized = {str(key or "").strip().upper(): value for key, value in (row or {}).items()}
            team_tri = str(normalized.get("TEAM_ABBREVIATION") or normalized.get("TEAM") or "").strip().upper()
            game_id = _canon_boxscore_game_id(normalized.get("GAME_ID") or normalized.get("GAMEID") or team_to_game_id.get(team_tri))
            player_name = str(normalized.get("PLAYER_NAME") or normalized.get("PLAYER") or "").strip()
            if not game_id or not team_tri or not player_name:
                continue
            first_name, family_name = _split_player_name(player_name)
            rows_by_game.setdefault(game_id, []).append(
                {
                    "personId": str(normalized.get("PLAYER_ID") or normalized.get("PERSONID") or "").strip(),
                    "teamTricode": team_tri,
                    "minutes": str(normalized.get("MIN") or normalized.get("MINUTES") or "").strip(),
                    "points": str(normalized.get("PTS") or normalized.get("POINTS") or "").strip(),
                    "reboundsTotal": str(normalized.get("REB") or normalized.get("TREB") or normalized.get("REBOUNDSTOTAL") or "").strip(),
                    "assists": str(normalized.get("AST") or normalized.get("ASSISTS") or "").strip(),
                    "threePointersMade": str(normalized.get("FG3M") or normalized.get("THREEPOINTERSMADE") or "").strip(),
                    "threePointersAttempted": str(normalized.get("FG3A") or normalized.get("THREEPOINTERSATTEMPTED") or "").strip(),
                    "fieldGoalsMade": str(normalized.get("FGM") or normalized.get("FIELDGOALSMADE") or "").strip(),
                    "fieldGoalsAttempted": str(normalized.get("FGA") or normalized.get("FIELDGOALSATTEMPTED") or "").strip(),
                    "freeThrowsMade": str(normalized.get("FTM") or normalized.get("FREETHROWSMADE") or "").strip(),
                    "freeThrowsAttempted": str(normalized.get("FTA") or normalized.get("FREETHROWSATTEMPTED") or "").strip(),
                    "steals": str(normalized.get("STL") or normalized.get("STEALS") or "").strip(),
                    "blocks": str(normalized.get("BLK") or normalized.get("BLOCKS") or "").strip(),
                    "turnovers": str(normalized.get("TOV") or normalized.get("TURNOVERS") or normalized.get("TO") or "").strip(),
                    "foulsPersonal": str(normalized.get("PF") or normalized.get("FOULSPERSONAL") or "").strip(),
                    "reboundsOffensive": str(normalized.get("OREB") or normalized.get("REBOUNDSOFFENSIVE") or "").strip(),
                    "reboundsDefensive": str(normalized.get("DREB") or normalized.get("REBOUNDSDEFENSIVE") or "").strip(),
                    "plusMinusPoints": str(normalized.get("PLUS_MINUS") or normalized.get("PLUSMINUSPOINTS") or "").strip(),
                    "firstName": first_name,
                    "familyName": family_name,
                    "nameI": player_name,
                }
            )

    if not rows_by_game:
        return 0

    boxscore_dir = processed_root / "boxscores"
    boxscore_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "personId",
        "teamTricode",
        "minutes",
        "points",
        "reboundsTotal",
        "assists",
        "threePointersMade",
        "threePointersAttempted",
        "fieldGoalsMade",
        "fieldGoalsAttempted",
        "freeThrowsMade",
        "freeThrowsAttempted",
        "steals",
        "blocks",
        "turnovers",
        "foulsPersonal",
        "reboundsOffensive",
        "reboundsDefensive",
        "plusMinusPoints",
        "firstName",
        "familyName",
        "nameI",
    ]
    total_rows = 0
    for game_id, rows in rows_by_game.items():
        out_path = boxscore_dir / f"boxscore_{game_id}.csv"
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})
        total_rows += len(rows)
    return total_rows


def _build_local_optional_player_recon_artifacts(*, processed_root: Path, date_str: str) -> dict[str, str]:
    if _materialize_local_boxscore_cache_for_player_artifacts(processed_root=processed_root, date_str=date_str) <= 0:
        return {}

    copied: dict[str, str] = {}
    data_root = processed_root.parent
    vendor_root = REPO_ROOT / "vendor" / "nba_betting_repo"
    tool_specs = (
        (
            vendor_root / "tools" / "build_recon_players.py",
            "syndicate_nba_vendor_build_recon_players",
            "build_recon_players",
            processed_root / f"recon_players_{date_str}.csv",
            "recon_players_path",
        ),
        (
            vendor_root / "tools" / "build_live_player_lens_tuning.py",
            "syndicate_nba_vendor_build_live_player_lens_tuning",
            "build_live_player_lens_tuning",
            processed_root / f"live_player_lens_tuning_{date_str}.csv",
            "live_player_lens_tuning_path",
        ),
    )
    original_nba_root = os.environ.get("NBA_BETTING_DATA_ROOT")
    original_wnba_root = os.environ.get("WNBA_BETTING_DATA_ROOT")
    try:
        os.environ["NBA_BETTING_DATA_ROOT"] = str(data_root)
        os.environ["WNBA_BETTING_DATA_ROOT"] = str(data_root)
        for module_path, module_name, function_name, out_path, copied_key in tool_specs:
            if not module_path.exists() or not module_path.is_file():
                continue
            try:
                module = _load_module_from_path(module_name, module_path)
                builder = getattr(module, function_name, None)
                if builder is None:
                    continue
                df = builder(date_str)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_csv(out_path, df)
                copied[copied_key] = str(out_path)
            except Exception:
                continue
    finally:
        if original_nba_root is None:
            os.environ.pop("NBA_BETTING_DATA_ROOT", None)
        else:
            os.environ["NBA_BETTING_DATA_ROOT"] = original_nba_root
        if original_wnba_root is None:
            os.environ.pop("WNBA_BETTING_DATA_ROOT", None)
        else:
            os.environ["WNBA_BETTING_DATA_ROOT"] = original_wnba_root
    return copied


def _target_refresh_dates(*, date_str: str, days_ahead: int) -> list[str]:
    parsed = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    return [(parsed + dt.timedelta(days=offset)).isoformat() for offset in range(0, max(0, int(days_ahead)) + 1)]


def _run_playoff_transition_if_needed(*, source_root: Path, date_str: str) -> dict[str, object]:
    module_path = source_root / "src" / "nba_betting" / "playoff_transition.py"
    if not module_path.exists() or not module_path.is_file():
        return {"status": "unavailable"}
    src_root = source_root / "src"
    try:
        src_root_text = str(src_root)
        inserted = False
        if src_root_text not in sys.path:
            sys.path.insert(0, src_root_text)
            inserted = True
        importlib.invalidate_caches()
        module = importlib.import_module("nba_betting.playoff_transition")
        runner = getattr(module, "run_playoff_transition", None)
        if runner is None:
            return {"status": "unavailable"}
        summary = runner(target_date=dt.datetime.strptime(date_str, "%Y-%m-%d").date())
        return {"status": "ok", "summary": _json_ready(summary)}
    except Exception as exc:
        if isinstance(exc, ModuleNotFoundError):
            return {"status": "unavailable", "reason": f"missing dependency: {getattr(exc, 'name', 'unknown')}"}
        message = str(exc)
        lowered = message.lower()
        if "regular season has not completed" in lowered or "regular-season" in lowered:
            return {"status": "skipped", "reason": message}
        return {"status": "error", "error": message}
    finally:
        try:
            if inserted:
                sys.path.remove(src_root_text)
        except Exception:
            pass


def _export_game_cards_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"game_cards_{date_str}.csv",
    )
    if existing:
        return existing
    source = source_root / "data" / "processed" / f"game_cards_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Same-path safe: source_root and artifact_root are the same directory in
    # production, so a raw copy2 here raises SameFileError (crashed the WNBA
    # twin's export stage live on 7/17).
    _copy_file_with_fallback(source, destination)
    return str(destination)


def _export_boxscores_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"boxscores_{date_str}.csv",
    )
    if existing:
        return existing
    source = source_root / "data" / "processed" / f"boxscores_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Same-path safe: source_root and artifact_root are the same directory in
    # production, so a raw copy2 here raises SameFileError (crashed the WNBA
    # twin's export stage live on 7/17).
    _copy_file_with_fallback(source, destination)
    return str(destination)


def _export_recommendations_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recommendations_{date_str}.csv",
    )
    if existing:
        return existing
    source = source_root / "data" / "processed" / f"recommendations_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Same-path safe: source_root and artifact_root are the same directory in
    # production, so a raw copy2 here raises SameFileError (crashed the WNBA
    # twin's export stage live on 7/17).
    _copy_file_with_fallback(source, destination)
    return str(destination)


def _load_source_app(source_root: Path):
    app_path = source_root / "app.py"
    if not app_path.exists() or not app_path.is_file():
        return None
    return _load_module_from_path("syndicate_nba_source_app", app_path)


def _resolve_nba_season_year(date_str: str) -> int:
    parsed = dt.datetime.strptime(date_str, "%Y-%m-%d")
    return parsed.year if parsed.month >= 7 else parsed.year - 1


def _build_optional_player_recon_artifacts(*, source_root: Path, date_str: str, processed_root: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    existing_specs = (
        (f"recon_players_{date_str}.csv", "recon_players_path"),
        (f"live_player_lens_tuning_{date_str}.csv", "live_player_lens_tuning_path"),
    )
    for file_name, copied_key in existing_specs:
        existing = _copy_existing_processed_artifact(
            source_root=source_root,
            processed_root=processed_root,
            file_name=file_name,
        )
        if existing:
            copied[copied_key] = existing
    if len(copied) == len(existing_specs):
        return copied

    copied.update(_build_local_optional_player_recon_artifacts(processed_root=processed_root, date_str=date_str))
    return copied


# PARITY WITH WNBA, 2026-08-16. All three props-snapshot exporters below took a
# prior `<name>_<date>.json` as permission to skip the rebuild FOREVER, with no
# way to override it -- WNBA fixed two of its three long ago and the third on the
# same day as this. NBA is out of season, so this cannot be verified in
# production now; the `False` default keeps every path byte-identical until
# someone actually passes --force-refresh.
def _export_top_by_game_snapshot(*, source_root: Path, date_str: str, processed_root: Path, force_refresh: bool = False) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"props_recommendations_top_by_game_{date_str}.json",
    )
    if existing and not force_refresh:
        return existing
    _, out_path = _build_local_top_by_game_snapshot(processed_root=processed_root, date_str=date_str)
    return str(out_path) if out_path is not None else None


def _export_recommendations_slate_snapshot(*, source_root: Path, date_str: str, processed_root: Path, force_refresh: bool = False) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recommendations_slate_{date_str}.json",
    )
    if existing and not force_refresh:
        return existing
    _, out_path = _build_local_recommendations_slate_artifact(processed_root=processed_root, date_str=date_str)
    return str(out_path) if out_path is not None else None


def _build_local_season_betting_card_artifacts(*, source_root: Path, date_str: str, processed_root: Path) -> dict[str, str]:
    season = _resolve_nba_season_year(date_str)
    profile = "retuned"
    manifest_path = processed_root / f"season_betting_card_manifest_{season}_{profile}_{date_str}.json"
    generic_manifest_path = processed_root / f"season_betting_card_manifest_{season}_{profile}.json"
    day_path = processed_root / f"season_betting_card_day_{season}_{profile}_{date_str}.json"
    day_insights_path = processed_root / f"season_betting_card_day_{season}_{profile}_{date_str}_insights.json"

    try:
        from syndicate.features.nba.betting_card import build_season_betting_card_day_payload
        from syndicate.features.nba.betting_card import build_season_betting_card_manifest_payload
    except Exception:
        return {}

    original_root = os.environ.get("SYNDICATE_NBA_ARTIFACT_ROOT")
    os.environ["SYNDICATE_NBA_ARTIFACT_ROOT"] = str(source_root)
    try:
        clear_manifest = getattr(build_season_betting_card_manifest_payload, "cache_clear", None)
        clear_day = getattr(build_season_betting_card_day_payload, "cache_clear", None)
        if callable(clear_manifest):
            clear_manifest()
        if callable(clear_day):
            clear_day()
        manifest_payload = build_season_betting_card_manifest_payload(season, profile, date_str)
        day_payload = build_season_betting_card_day_payload(season, date_str, profile)
        day_insights_payload = build_season_betting_card_day_payload(season, date_str, profile, include_prop_insights=True)
    except Exception:
        return {}
    finally:
        if original_root is None:
            os.environ.pop("SYNDICATE_NBA_ARTIFACT_ROOT", None)
        else:
            os.environ["SYNDICATE_NBA_ARTIFACT_ROOT"] = original_root
        try:
            if callable(clear_manifest):
                clear_manifest()
            if callable(clear_day):
                clear_day()
        except Exception:
            pass

    copied: dict[str, str] = {}
    if isinstance(manifest_payload, dict):
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
        shutil.copy2(manifest_path, generic_manifest_path)
        copied["season_betting_card_manifest_path"] = str(manifest_path)
        copied["season_betting_card_manifest_generic_path"] = str(generic_manifest_path)
    if isinstance(day_payload, dict):
        day_path.parent.mkdir(parents=True, exist_ok=True)
        day_path.write_text(json.dumps(day_payload, indent=2), encoding="utf-8")
        copied["season_betting_card_day_path"] = str(day_path)
    if isinstance(day_insights_payload, dict):
        day_insights_path.parent.mkdir(parents=True, exist_ok=True)
        day_insights_path.write_text(json.dumps(day_insights_payload, indent=2), encoding="utf-8")
        copied["season_betting_card_day_insights_path"] = str(day_insights_path)
    return copied


def _export_season_betting_card_artifacts(*, source_root: Path, date_str: str, processed_root: Path) -> dict[str, str]:
    season = _resolve_nba_season_year(date_str)
    profile = "retuned"
    manifest_path = processed_root / f"season_betting_card_manifest_{season}_{profile}_{date_str}.json"
    generic_manifest_path = processed_root / f"season_betting_card_manifest_{season}_{profile}.json"
    day_path = processed_root / f"season_betting_card_day_{season}_{profile}_{date_str}.json"
    day_insights_path = processed_root / f"season_betting_card_day_{season}_{profile}_{date_str}_insights.json"

    copied: dict[str, str] = {}
    existing_targets = (
        (manifest_path.name, manifest_path, "season_betting_card_manifest_path"),
        (day_path.name, day_path, "season_betting_card_day_path"),
        (day_insights_path.name, day_insights_path, "season_betting_card_day_insights_path"),
    )
    for file_name, target_path, copied_key in existing_targets:
        existing = _copy_existing_processed_artifact(
            source_root=source_root,
            processed_root=processed_root,
            file_name=file_name,
        )
        if existing:
            copied[copied_key] = str(target_path)
    if "season_betting_card_manifest_path" in copied:
        generic_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_path, generic_manifest_path)
        copied["season_betting_card_manifest_generic_path"] = str(generic_manifest_path)
    if len(copied) == 4:
        return copied

    local = _build_local_season_betting_card_artifacts(source_root=source_root, date_str=date_str, processed_root=processed_root)
    for key, value in local.items():
        copied[key] = value
    if len(copied) == 4:
        return copied

    if not _source_app_fallback_enabled():
        return copied

    source_app = _load_source_app(source_root)
    if source_app is None:
        return copied
    client = source_app.app.test_client()

    def _fetch_json(query: str) -> dict[str, object]:
        response = client.get(query)
        try:
            payload = response.get_json() if response is not None else None
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            payload = {"error": "no_json", "status": int(getattr(response, "status_code", 0) or 0)}
        return payload

    artifacts = {
        manifest_path: _fetch_json(f"/api/season/{season}/betting-card?profile={profile}&date={date_str}"),
        day_path: _fetch_json(f"/api/season/{season}/betting-card/day/{date_str}?profile={profile}"),
        day_insights_path: _fetch_json(
            f"/api/season/{season}/betting-card/day/{date_str}?profile={profile}&include_prop_insights=1"
        ),
    }
    for out_path, payload in artifacts.items():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    shutil.copy2(manifest_path, generic_manifest_path)
    copied["season_betting_card_manifest_path"] = str(manifest_path)
    copied["season_betting_card_manifest_generic_path"] = str(generic_manifest_path)
    copied["season_betting_card_day_path"] = str(day_path)
    copied["season_betting_card_day_insights_path"] = str(day_insights_path)
    return copied


def _export_cards_props_snapshot(*, source_root: Path, date_str: str, processed_root: Path, force_refresh: bool = False) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"cards_props_snapshot_{date_str}.json",
    )
    if existing and not force_refresh:
        return existing
    _, out_path = _build_local_cards_props_snapshot_artifact(processed_root=processed_root, date_str=date_str)
    return str(out_path) if out_path is not None else None


def _build_cards_sim_detail_from_local_smart_sim(*, processed_root: Path, date_str: str) -> list[dict[str, object]]:
    games_out: list[dict[str, object]] = []
    for path in sorted(processed_root.glob(f"smart_sim_{date_str}_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        home_tri = str(payload.get("home") or "").strip().upper()
        away_tri = str(payload.get("away") or "").strip().upper()
        if not home_tri or not away_tri:
            stem = str(path.stem or "")
            prefix = f"smart_sim_{date_str}_"
            if stem.startswith(prefix):
                suffix = stem[len(prefix):]
                parts = suffix.split("_")
                if len(parts) >= 2:
                    home_tri = home_tri or str(parts[0] or "").strip().upper()
                    away_tri = away_tri or str(parts[1] or "").strip().upper()
        players = payload.get("players") if isinstance(payload.get("players"), dict) else {}
        home_players = [row for row in (players.get("home") or []) if isinstance(row, dict)]
        away_players = [row for row in (players.get("away") or []) if isinstance(row, dict)]
        if not home_tri or not away_tri:
            continue
        missing = payload.get("missing_prop_players") if isinstance(payload.get("missing_prop_players"), dict) else {}
        injuries = payload.get("injuries") if isinstance(payload.get("injuries"), dict) else {}
        players_summary = payload.get("players_summary") if isinstance(payload.get("players_summary"), dict) else {}
        periods_payload = payload.get("periods") if isinstance(payload.get("periods"), dict) else {}
        quarters = []
        for quarter_number in range(1, 5):
            quarter_payload = periods_payload.get(f"q{quarter_number}") if isinstance(periods_payload.get(f"q{quarter_number}"), dict) else None
            if not isinstance(quarter_payload, dict):
                continue
            quarters.append(
                {
                    "q": int(quarter_number),
                    "away_pts_mu": quarter_payload.get("away_mean"),
                    "home_pts_mu": quarter_payload.get("home_mean"),
                    "total_mean": quarter_payload.get("total_mean"),
                    "margin_mean": quarter_payload.get("margin_mean"),
                    "p_home_win": quarter_payload.get("p_home_win"),
                }
            )
        summary = {
            "home": int(players_summary.get("home") or len(home_players)),
            "away": int(players_summary.get("away") or len(away_players)),
            "missing_home": int(players_summary.get("missing_home") or len(missing.get("home") or [])),
            "missing_away": int(players_summary.get("missing_away") or len(missing.get("away") or [])),
            "injured_home": int(players_summary.get("injured_home") or len(injuries.get("home") or [])),
            "injured_away": int(players_summary.get("injured_away") or len(injuries.get("away") or [])),
        }
        games_out.append(
            {
                "home_tri": home_tri,
                "away_tri": away_tri,
                "sim": {
                    "quarters": quarters,
                    "players_summary": summary,
                    "players": {
                        "home": home_players,
                        "away": away_players,
                    },
                    "missing_prop_players": {
                        "home": [row for row in (missing.get("home") or []) if isinstance(row, dict)],
                        "away": [row for row in (missing.get("away") or []) if isinstance(row, dict)],
                    },
                    "injuries": {
                        "home": [row for row in (injuries.get("home") or []) if isinstance(row, dict)],
                        "away": [row for row in (injuries.get("away") or []) if isinstance(row, dict)],
                    },
                },
            }
        )
    return games_out


def _export_cards_sim_detail_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"cards_sim_detail_{date_str}.json",
    )
    if existing:
        return existing
    out_path = processed_root / f"cards_sim_detail_{date_str}.json"
    games_out = _build_cards_sim_detail_from_local_smart_sim(processed_root=processed_root, date_str=date_str)
    if not games_out and _source_app_fallback_enabled():
        source_app = _load_source_app(source_root)
        if source_app is not None:
            client = source_app.app.test_client()
            try:
                response = client.get(f"/api/cards?date={date_str}&include_players=1&include_sim_ladders=1")
                if int(getattr(response, "status_code", 0) or 0) == 200:
                    payload = response.get_json() if response is not None else None
                    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
                    for game in games:
                        if not isinstance(game, dict):
                            continue
                        home_tri = str(game.get("home_tri") or "").strip().upper()
                        away_tri = str(game.get("away_tri") or "").strip().upper()
                        sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
                        if not home_tri or not away_tri or not isinstance(sim, dict):
                            continue
                        players = sim.get("players") if isinstance(sim.get("players"), dict) else {"home": [], "away": []}
                        missing = sim.get("missing_prop_players") if isinstance(sim.get("missing_prop_players"), dict) else {"home": [], "away": []}
                        injuries = sim.get("injuries") if isinstance(sim.get("injuries"), dict) else {"home": [], "away": []}
                        summary = sim.get("players_summary") if isinstance(sim.get("players_summary"), dict) else {}
                        games_out.append(
                            {
                                "home_tri": home_tri,
                                "away_tri": away_tri,
                                "sim": {
                                    "players_loaded": True,
                                    "players_summary": dict(summary),
                                    "players": {
                                        "home": [row for row in (players.get("home") or []) if isinstance(row, dict)],
                                        "away": [row for row in (players.get("away") or []) if isinstance(row, dict)],
                                    },
                                    "missing_prop_players": {
                                        "home": [row for row in (missing.get("home") or []) if isinstance(row, dict)],
                                        "away": [row for row in (missing.get("away") or []) if isinstance(row, dict)],
                                    },
                                    "injuries": {
                                        "home": [row for row in (injuries.get("home") or []) if isinstance(row, dict)],
                                        "away": [row for row in (injuries.get("away") or []) if isinstance(row, dict)],
                                    },
                                },
                            }
                        )
            except Exception:
                pass
    if not games_out:
        return None

    out = {"date": date_str, "games": games_out}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return str(out_path)


def _build_local_recon_games_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    boxscores_path = processed_root / f"boxscores_{date_str}.csv"
    if not game_cards_path.exists() or not boxscores_path.exists():
        return 0, None

    games_by_id: dict[str, dict[str, str]] = {}
    with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            game_id = str((row or {}).get("game_id") or "").strip()
            if not game_id or game_id in games_by_id:
                continue
            games_by_id[game_id] = {
                "game_id": game_id,
                "home_team": str((row or {}).get("home_team") or "").strip(),
                "visitor_team": str((row or {}).get("visitor_team") or "").strip(),
                "home_tri": str((row or {}).get("home_tri") or "").strip().upper(),
                "away_tri": str((row or {}).get("away_tri") or "").strip().upper(),
            }

    if not games_by_id:
        return 0, None

    team_points_by_game: dict[str, dict[str, float]] = {}
    with boxscores_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized = {str(key or "").strip().upper(): value for key, value in (row or {}).items()}
            game_id = str(normalized.get("GAME_ID") or normalized.get("GAMEID") or "").strip()
            team_tri = str(normalized.get("TEAM_ABBREVIATION") or normalized.get("TEAM") or "").strip().upper()
            try:
                pts_value = float(normalized.get("PTS"))
            except (TypeError, ValueError):
                continue
            if not game_id or not team_tri:
                continue
            per_game = team_points_by_game.setdefault(game_id, {})
            per_game[team_tri] = float(per_game.get(team_tri, 0.0)) + pts_value

    rows: list[dict[str, str]] = []
    for game_id, game_row in games_by_id.items():
        home_tri = str(game_row.get("home_tri") or "").strip().upper()
        away_tri = str(game_row.get("away_tri") or "").strip().upper()
        points = team_points_by_game.get(game_id) or {}
        home_pts = points.get(home_tri)
        away_pts = points.get(away_tri)
        if not home_tri or not away_tri or home_pts is None or away_pts is None:
            continue
        total_actual = float(home_pts) + float(away_pts)
        rows.append(
            {
                "game_id": game_id,
                "home_team": str(game_row.get("home_team") or home_tri),
                "visitor_team": str(game_row.get("visitor_team") or away_tri),
                "home_tri": home_tri,
                "away_tri": away_tri,
                "home_pts": f"{home_pts:g}",
                "visitor_pts": f"{away_pts:g}",
                "total_actual": f"{total_actual:g}",
            }
        )

    if not rows:
        return 0, None

    out_path = processed_root / f"recon_games_{date_str}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["game_id", "home_team", "visitor_team", "home_tri", "away_tri", "home_pts", "visitor_pts", "total_actual"]
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return len(rows), out_path


def _export_recon_games_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recon_games_{date_str}.csv",
    )
    if existing:
        return existing
    local_rows, local_path = _build_local_recon_games_artifact(processed_root=processed_root, date_str=date_str)
    if local_rows > 0 and local_path is not None:
        return str(local_path)
    if not _source_app_fallback_enabled():
        return None
    source_app = _load_source_app(source_root)
    if source_app is None:
        return None
    if hasattr(source_app, "_cron_auth_ok"):
        try:
            source_app._cron_auth_ok = lambda _request: True
        except Exception:
            pass
    client = source_app.app.test_client()
    response = client.get(f"/api/cron/reconcile-games?date={date_str}")
    try:
        payload = response.get_json() if response is not None else None
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return None
    output_path = str(payload.get("output") or "").strip()
    if not output_path:
        return None
    source = Path(output_path)
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Same-path safe: source_root and artifact_root are the same directory in
    # production, so a raw copy2 here raises SameFileError (crashed the WNBA
    # twin's export stage live on 7/17).
    _copy_file_with_fallback(source, destination)
    return str(destination)


def _build_local_live_lens_tuning_artifact(*, processed_root: Path, live_lens_root: Path) -> dict[str, str]:
    try:
        from syndicate.features.nba.cards import build_live_lens_tuning_payload

        payload = build_live_lens_tuning_payload()
    except Exception:
        return {}
    if not isinstance(payload, dict) or not payload:
        return {}

    raw = json.dumps(payload, indent=2).encode("utf-8")
    outputs = (
        (processed_root / "live_lens_tuning_override.json", "live_lens_tuning_override_path"),
        (live_lens_root / "live_lens_tuning_override.json", "live_lens_tuning_override_live_lens_path"),
    )
    copied: dict[str, str] = {}
    for out_path, copied_key in outputs:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        copied[copied_key] = str(out_path)
    return copied


def _export_live_lens_artifacts(*, source_root: Path, date_str: str, processed_root: Path, live_lens_root: Path) -> dict[str, str]:
    exports = (
        (
            f"live_lens_signals_{date_str}.jsonl",
            f"/api/download_live_lens_signals?date={date_str}",
            (
                (processed_root / f"live_lens_signals_{date_str}.jsonl", "live_lens_signals_path"),
                (live_lens_root / f"live_lens_signals_{date_str}.jsonl", None),
            ),
        ),
        (
            f"live_lens_projections_{date_str}.jsonl",
            f"/api/download_live_lens_projections?date={date_str}",
            (
                (processed_root / f"live_lens_projections_{date_str}.jsonl", "live_lens_projections_path"),
                (live_lens_root / f"live_lens_projections_{date_str}.jsonl", None),
            ),
        ),
        (
            "live_lens_tuning_override.json",
            "/api/download_live_lens_tuning",
            (
                (processed_root / "live_lens_tuning_override.json", "live_lens_tuning_override_path"),
                (live_lens_root / "live_lens_tuning_override.json", "live_lens_tuning_override_live_lens_path"),
            ),
        ),
    )
    copied: dict[str, str] = {}
    missing_exports: list[tuple[str, str, tuple[tuple[Path, str | None], ...]]] = []
    for file_name, query, destinations in exports:
        existing = _copy_existing_live_lens_artifact(source_root=source_root, file_name=file_name, destinations=destinations)
        if existing:
            copied.update(existing)
            continue
        if file_name == f"live_lens_signals_{date_str}.jsonl":
            local = _build_local_live_lens_signals_artifact(processed_root=processed_root, date_str=date_str, live_lens_root=live_lens_root)
            if local:
                copied.update(local)
                continue
        if file_name == f"live_lens_projections_{date_str}.jsonl":
            local = _build_local_live_lens_projections_artifact(processed_root=processed_root, date_str=date_str, live_lens_root=live_lens_root)
            if local:
                copied.update(local)
                continue
        if file_name == "live_lens_tuning_override.json":
            local = _build_local_live_lens_tuning_artifact(processed_root=processed_root, live_lens_root=live_lens_root)
            if local:
                copied.update(local)
                continue
        missing_exports.append((file_name, query, destinations))
    if not missing_exports:
        return copied

    if not _source_app_fallback_enabled():
        return copied

    source_app = _load_source_app(source_root)
    if source_app is None:
        return copied
    client = source_app.app.test_client()
    for _file_name, query, destinations in missing_exports:
        try:
            response = client.get(query)
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code != 200:
                continue
            raw = b""
            get_data = getattr(response, "get_data", None)
            if callable(get_data):
                raw = get_data()
            elif hasattr(response, "data"):
                raw = getattr(response, "data") or b""
            if not isinstance(raw, (bytes, bytearray)) or not raw:
                continue
            for out_path, copied_key in destinations:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(bytes(raw))
                if copied_key:
                    copied[copied_key] = str(out_path)
        except Exception:
            continue
    return copied


def _export_live_snapshot_artifacts(*, source_root: Path, date_str: str, processed_root: Path) -> dict[str, str]:
    live_snapshots_root = processed_root / "live_snapshots"
    snapshot_specs = (
        ("live_state", None),
        ("live_pbp_stats", "live_pbp_stats_path"),
        ("live_lines", "live_lines_path"),
        ("live_player_boxscore", "live_player_boxscore_path"),
        ("live_player_lens", "live_player_lens_path"),
    )
    copied: dict[str, str] = {}
    state_payload: dict[str, object] | None = None

    state_file = f"live_state_{date_str}.jsonl"
    state_destination = live_snapshots_root / state_file
    existing_state = _copy_existing_live_snapshot_artifact(
        source_root=source_root,
        file_name=state_file,
        destination=state_destination,
    )
    if existing_state:
        copied["live_state_path"] = existing_state
        state_payload = _read_live_snapshot_payload(state_destination)

    source_app = None
    client = None

    def _ensure_client():
        nonlocal source_app, client
        if client is not None:
            return client
        source_app = _load_source_app(source_root)
        if source_app is None:
            return None
        client = source_app.app.test_client()
        return client

    def _fetch_json(query: str) -> dict[str, object] | None:
        test_client = _ensure_client()
        if test_client is None:
            return None
        try:
            response = test_client.get(query)
            if int(getattr(response, "status_code", 0) or 0) != 200:
                return None
            payload = response.get_json() if response is not None else None
        except Exception:
            payload = None
        return payload if isinstance(payload, dict) else None

    refreshed_state_payload = _fetch_json(f"/api/live_state?date={date_str}") if _source_app_fallback_enabled() else None
    if _payload_has_snapshot_content("live_state", refreshed_state_payload):
        state_payload = refreshed_state_payload
    if not _payload_has_snapshot_content("live_state", state_payload):
        local_state_payload = _build_local_live_snapshot_payload(kind="live_state", date_str=date_str, event_ids=[])
        if _payload_has_snapshot_content("live_state", local_state_payload):
            state_payload = local_state_payload
    if _payload_has_snapshot_content("live_state", state_payload) and _write_live_snapshot_payload(state_destination, state_payload):
        copied["live_state_path"] = str(state_destination)
    elif existing_state and not _snapshot_artifact_has_meaningful_content("live_state", state_destination):
        try:
            state_destination.unlink(missing_ok=True)
        except Exception:
            pass

    event_ids = [
        str(game.get("event_id") or "").strip()
        for game in ((state_payload or {}).get("games") or [])
        if isinstance(game, dict) and str(game.get("event_id") or "").strip()
    ]
    joined_event_ids = ",".join(dict.fromkeys(event_ids))

    for kind, copied_key in snapshot_specs[1:]:
        file_name = f"{kind}_{date_str}.jsonl"
        destination = live_snapshots_root / file_name
        existing = _copy_existing_live_snapshot_artifact(
            source_root=source_root,
            file_name=file_name,
            destination=destination,
        )
        payload = None
        if joined_event_ids and _source_app_fallback_enabled():
            query = f"/api/{kind}?date={date_str}&event_ids={joined_event_ids}"
            if kind == "live_lines":
                query = f"{query}&include_period_totals=1"
            payload = _fetch_json(query)
        local_payload = _build_local_live_snapshot_payload(kind=kind, date_str=date_str, event_ids=event_ids)
        if kind == "live_lines":
            payload = _prefer_live_lines_payload(payload, local_payload)
        elif not _payload_has_snapshot_content(kind, payload):
            payload = local_payload
        bundle_payload = _build_bundle_local_live_snapshot_payload(
            kind=kind,
            date_str=date_str,
            event_ids=event_ids,
            processed_root=processed_root,
        )
        if kind == "live_lines":
            payload = _prefer_live_lines_payload(payload, bundle_payload)
        elif not _payload_has_snapshot_content(kind, payload):
            payload = bundle_payload
        if isinstance(payload, dict) and _payload_has_snapshot_content(kind, payload) and _write_live_snapshot_payload(destination, payload):
            if copied_key:
                copied[copied_key] = str(destination)
            continue
        if existing and _snapshot_artifact_has_meaningful_content(kind, destination) and copied_key:
            copied[copied_key] = existing
            continue
        if existing:
            try:
                destination.unlink(missing_ok=True)
            except Exception:
                pass

    return copied


def _materialize_artifact_bundle(*, state: dict[str, object], artifact_root: Path, source_root: Path, force_refresh: bool = False) -> dict[str, object]:
    processed_root = artifact_root / "data" / "processed"
    raw_root = artifact_root / "data" / "raw"
    live_lens_root = artifact_root / "data" / "live_lens"
    copied: dict[str, object] = {}
    artifact_map = {
        "snapshot_alias_path": processed_root / Path(str(state.get("snapshot_alias_path") or "")).name,
        "predictions_path": processed_root / Path(str(state.get("predictions_path") or "")).name,
        "edges_path": processed_root / Path(str(state.get("edges_path") or "")).name,
        "recs_path": processed_root / Path(str(state.get("recs_path") or "")).name,
        "snapshot_path": raw_root / Path(str(state.get("snapshot_path") or "")).name,
    }
    for key, destination in artifact_map.items():
        if _copy_if_exists(str(state.get(key) or ""), destination):
            copied[key] = str(destination)
    date_text = str(state.get("date") or "").strip()
    source_directory = _processed_source_directory(state)
    reuse_existing_run = bool(state.get("reused_existing_outputs") or state.get("reused_existing_artifact_bundle"))
    reuse_local_processed = False
    if source_directory is not None:
        try:
            reuse_local_processed = source_directory.resolve() == processed_root.resolve()
        except Exception:
            reuse_local_processed = source_directory == processed_root
    if date_text and source_directory is not None:
        smart_sim_files = _copy_matching_files(
            source_directory=source_directory,
            pattern=f"smart_sim_{date_text}_*.json",
            destination_directory=processed_root,
        )
        if smart_sim_files:
            copied["smart_sim_paths"] = smart_sim_files
        if not reuse_local_processed:
            recon_games_path = _export_recon_games_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
            if recon_games_path:
                copied["recon_games_path"] = recon_games_path
            game_cards_path = _export_game_cards_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
            if game_cards_path:
                copied["game_cards_path"] = game_cards_path
            boxscores_path = _export_boxscores_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
            if boxscores_path:
                copied["boxscores_path"] = boxscores_path
            recommendations_path = _export_recommendations_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
            if recommendations_path:
                copied["recommendations_path"] = recommendations_path
            recon_quarters_path = _export_recon_quarters_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
            if recon_quarters_path:
                copied["recon_quarters_path"] = recon_quarters_path
            recon_props_path = _export_recon_props_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
            if recon_props_path:
                copied["recon_props_path"] = recon_props_path
            recommendations_slate_path = _export_recommendations_slate_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root, force_refresh=bool(force_refresh))
            if recommendations_slate_path:
                copied["recommendations_slate_path"] = recommendations_slate_path
            cards_props_snapshot_path = _export_cards_props_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root, force_refresh=bool(force_refresh))
            if cards_props_snapshot_path:
                copied["cards_props_snapshot_path"] = cards_props_snapshot_path
            cards_sim_detail_path = _export_cards_sim_detail_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
            if cards_sim_detail_path:
                copied["cards_sim_detail_path"] = cards_sim_detail_path
            top_by_game_path = _export_top_by_game_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root, force_refresh=bool(force_refresh))
            if top_by_game_path:
                copied["top_by_game_path"] = top_by_game_path
            copied.update(_export_season_betting_card_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root))
            copied.update(_export_live_lens_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root, live_lens_root=live_lens_root))
            copied.update(_build_optional_player_recon_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root))
        if not reuse_existing_run:
            copied.update(_export_live_snapshot_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root))
    boxscores_history_path = _refresh_boxscores_history_artifact(source_root=source_root, processed_root=processed_root)
    if boxscores_history_path:
        copied["boxscores_history_path"] = boxscores_history_path
    advanced_stats_paths = _export_team_advanced_stats_artifacts(source_root=source_root, processed_root=processed_root)
    if advanced_stats_paths:
        copied["team_advanced_stats_paths"] = advanced_stats_paths
    for transition_path in sorted((source_root / "data" / "processed").glob(f"playoff_transition_*_{date_text}.json")):
        if not transition_path.is_file():
            continue
        destination = processed_root / transition_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(transition_path, destination)
        copied.setdefault("playoff_transition_paths", []).append(str(destination))
    return copied


def _load_source_cli(source_root: Path):
    raise RuntimeError("source CLI fallback removed; use local artifacts or local Syndicate builders")


def _export_recon_quarters_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recon_quarters_{date_str}.csv",
    )
    if existing:
        return existing
    source = source_root / "data" / "processed" / f"recon_quarters_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Same-path safe: source_root and artifact_root are the same directory in
    # production, so a raw copy2 here raises SameFileError (crashed the WNBA
    # twin's export stage live on 7/17).
    _copy_file_with_fallback(source, destination)
    return str(destination)


def _build_local_recon_props_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    boxscores_path = processed_root / f"boxscores_{date_str}.csv"

    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    team_to_game_id: dict[str, str] = {}
    if game_cards_path.exists():
        with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                game_id = str((row or {}).get("game_id") or "").strip()
                if not game_id:
                    continue
                for team_key in ("home_tri", "away_tri"):
                    team_tri = str((row or {}).get(team_key) or "").strip().upper()
                    if team_tri and team_tri not in team_to_game_id:
                        team_to_game_id[team_tri] = game_id

    rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    if boxscores_path.exists():
        with boxscores_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                normalized = {str(key or "").strip().upper(): value for key, value in (row or {}).items()}
                game_id = str(normalized.get("GAME_ID") or normalized.get("GAMEID") or "").strip()
                team_abbr = str(normalized.get("TEAM_ABBREVIATION") or normalized.get("TEAM") or "").strip().upper()
                if not game_id and team_abbr:
                    game_id = str(team_to_game_id.get(team_abbr) or "").strip()
                player_name = str(normalized.get("PLAYER_NAME") or normalized.get("PLAYER") or "").strip()
                player_id = str(normalized.get("PLAYER_ID") or "").strip()
                if not game_id or not player_name:
                    continue

                dedupe_key = (game_id, team_abbr, player_name.casefold())
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                def _stat_value(*keys: str) -> str:
                    for key in keys:
                        value = normalized.get(key)
                        if value is None:
                            continue
                        text = str(value).strip()
                        if text:
                            return text
                    return ""

                pts = _stat_value("PTS")
                reb = _stat_value("REB")
                ast = _stat_value("AST")
                threes = _stat_value("FG3M", "FG3_M")
                stl = _stat_value("STL")
                blk = _stat_value("BLK")
                tov = _stat_value("TOV", "TO")

                pra = ""
                pr = ""
                pa = ""
                ra = ""
                try:
                    pts_num = float(pts) if pts else None
                    reb_num = float(reb) if reb else None
                    ast_num = float(ast) if ast else None
                except ValueError:
                    pts_num = reb_num = ast_num = None
                if pts_num is not None and reb_num is not None:
                    pr = f"{pts_num + reb_num:g}"
                if pts_num is not None and ast_num is not None:
                    pa = f"{pts_num + ast_num:g}"
                if reb_num is not None and ast_num is not None:
                    ra = f"{reb_num + ast_num:g}"
                if pts_num is not None and reb_num is not None and ast_num is not None:
                    pra = f"{pts_num + reb_num + ast_num:g}"

                rows.append(
                    {
                        "game_id": game_id,
                        "player_id": player_id,
                        "player_name": player_name,
                        "team_abbr": team_abbr,
                        "pts": pts,
                        "reb": reb,
                        "ast": ast,
                        "threes": threes,
                        "stl": stl,
                        "blk": blk,
                        "tov": tov,
                        "pr": pr,
                        "pa": pa,
                        "ra": ra,
                        "pra": pra,
                    }
                )

    out_path = processed_root / f"recon_props_{date_str}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["game_id", "player_id", "player_name", "team_abbr", "pts", "reb", "ast", "threes", "stl", "blk", "tov", "pr", "pa", "ra", "pra"]
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return len(rows), out_path


def _export_recon_props_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recon_props_{date_str}.csv",
    )
    if existing:
        return existing
    local_rows, local_path = _build_local_recon_props_artifact(processed_root=processed_root, date_str=date_str)
    if local_path is not None:
        return str(local_path)
    source = source_root / "data" / "processed" / f"recon_props_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Same-path safe: source_root and artifact_root are the same directory in
    # production, so a raw copy2 here raises SameFileError (crashed the WNBA
    # twin's export stage live on 7/17).
    _copy_file_with_fallback(source, destination)
    return str(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NBA OddsAPI props refresh job through a Syndicate-owned entrypoint.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--regions", default="us")
    parser.add_argument("--bookmakers", default="")
    parser.add_argument("--markets", default="")
    parser.add_argument("--source-root")
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--artifact-root")
    parser.add_argument("--do-edges", action="store_true")
    parser.add_argument("--do-export", action="store_true")
    parser.add_argument("--do-push", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--days-ahead", type=int, default=0)
    parser.add_argument("--started-at")
    parser.add_argument("--mode", choices=("fast", "full"), default="full")
    args = parser.parse_args()
    _WIN_PROB_RUN_DATE["date"] = str(getattr(args, "date", "") or "").strip() or None

    source_root_arg = str(args.source_root or "").strip()
    source_root = Path(source_root_arg).resolve() if source_root_arg else None
    artifact_root = str(args.artifact_root or "").strip()
    fast_mode = str(args.mode or "full").strip().lower() == "fast"
    target_dates = _target_refresh_dates(date_str=args.date, days_ahead=int(args.days_ahead or 0))
    states: list[dict[str, object]] = []
    artifact_root_path = Path(artifact_root).resolve() if artifact_root else None
    for index, target_date in enumerate(target_dates):
        state = None
        started_at = args.started_at if index == 0 else None
        source_root_for_inputs = source_root if source_root is not None else (artifact_root_path or Path(artifact_root or ".")).resolve()
        refresh_input_hash = _refresh_step_input_hash(
            source_root=source_root_for_inputs,
            processed_root=(source_root_for_inputs / "data" / "processed"),
            date_str=target_date,
            do_edges=bool(args.do_edges),
            do_export=bool(args.do_export),
            artifact_root=artifact_root_path,
        )
        if source_root is not None and not bool(args.force_refresh):
            state = _existing_refresh_state(
                source_root=source_root,
                date_str=target_date,
                do_edges=bool(args.do_edges),
                do_export=bool(args.do_export),
                started_at=started_at,
                input_hash=refresh_input_hash,
            )
        if state is None and artifact_root and not bool(args.force_refresh):
            state = _existing_artifact_bundle_state(
                artifact_root=artifact_root_path,
                date_str=target_date,
                do_edges=bool(args.do_edges),
                do_export=bool(args.do_export),
                started_at=started_at,
                input_hash=refresh_input_hash,
            )
        if state is None:
            if source_root is None:
                state = {
                    "date": str(target_date),
                    "error": "source-root is required when no reusable artifact bundle is available",
                    "artifact_bundle_root": str(artifact_root_path) if artifact_root_path else None,
                }
                states.append(state)
                continue
            state = _run_refresh_via_cli(
                source_root=source_root,
                date_str=target_date,
                regions=args.regions,
                bookmakers=args.bookmakers,
                markets=args.markets,
                do_edges=bool(args.do_edges),
                do_export=bool(args.do_export),
                do_push=bool(args.do_push),
                log_file=Path(args.log_file).resolve(),
                started_at=started_at,
                mode=str(args.mode or "full"),
            )
        if source_root is not None:
            state["playoff_transition"] = _run_playoff_transition_if_needed(source_root=source_root, date_str=target_date)
        if not fast_mode and artifact_root_path and source_root is not None and not state.get("reused_existing_artifact_bundle") and not state.get("error"):
            copied = _materialize_artifact_bundle(
                state=state,
                artifact_root=artifact_root_path,
                source_root=source_root,
                force_refresh=bool(args.force_refresh),
            )
            if copied:
                state["artifact_bundle_root"] = str(artifact_root_path)
                state["artifact_bundle_files"] = copied
        if state and not state.get("error"):
            record_refresh_state(
                f"nba_artifact_bundle:{_refresh_state_scope_path(artifact_root_path)}:{target_date}:{int(bool(args.do_edges))}:{int(bool(args.do_export))}",
                refresh_input_hash,
                outputs=[str(path) for path in (artifact_root_path / "data" / "processed").glob("*")][:0] if artifact_root_path else [],
                metadata={
                    "date": target_date,
                    "reused": bool(state.get("reused_existing_outputs") or state.get("reused_existing_artifact_bundle")),
                    "artifact_root": str(artifact_root_path) if artifact_root_path else None,
                },
            )
        states.append(state)
    state = states[0] if states else {"date": str(args.date), "error": "no refresh states generated"}
    if len(states) > 1:
        state["lookahead_runs"] = states[1:]
    print(json.dumps(_json_ready(state), indent=2, sort_keys=True))

    snapshot_rows = int(state.get("snapshot_rows") or 0)
    alias_rows = int(state.get("snapshot_alias_rows") or 0)
    edges_rows = int(state.get("edges_rows") or 0)
    recs_rows = int(state.get("recs_rows") or 0)
    game_cards_rows = int(state.get("game_cards_rows") or 0)
    cards_sim_detail_games = int(state.get("cards_sim_detail_games") or 0)
    smart_sim_files = int(state.get("smart_sim_files") or 0)
    if state.get("error"):
        return 1
    for extra_state in states[1:]:
        if extra_state.get("error"):
            return 1
        if bool(args.do_export) and int(extra_state.get("snapshot_rows") or 0) > 0 and int(extra_state.get("game_cards_rows") or 0) > 0 and int(extra_state.get("cards_sim_detail_games") or 0) <= 0 and int(extra_state.get("smart_sim_files") or 0) <= 0:
            return 1
    if snapshot_rows > 0 and alias_rows <= 0:
        return 1
    if bool(args.do_edges) and snapshot_rows > 0 and edges_rows <= 0:
        return 1
    predictions_rows = int(state.get("predictions_rows") or 0)
    if bool(args.do_export) and snapshot_rows > 0 and game_cards_rows > 0 and predictions_rows > 0 and recs_rows <= 0:
        return 1
    if bool(args.do_export) and snapshot_rows > 0 and game_cards_rows > 0 and cards_sim_detail_games <= 0 and smart_sim_files <= 0:
        return 1
    return 0


if __name__ == "__main__":
    # `finally`, not a line before a `return`: main() has several return points
    # and can raise, and a counter that only reports on the happy path would go
    # silent in exactly the runs worth investigating.
    try:
        _exit_code = main()
    finally:
        _emit_win_prob_stats()
    raise SystemExit(_exit_code)