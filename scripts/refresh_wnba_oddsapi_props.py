from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
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


def _json_ready(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _copy_if_exists(source_path: str | None, destination_path: Path) -> bool:
    source_text = str(source_path or "").strip()
    if not source_text:
        return False
    source = Path(source_text)
    if not source.exists() or not source.is_file():
        return False
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination_path)
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
        shutil.copy2(source, destination)
        copied.append(str(destination))
    return copied


def _copy_existing_processed_artifact(*, source_root: Path, processed_root: Path, file_name: str) -> str | None:
    source = source_root / "data" / "processed" / file_name
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / file_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


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
    shutil.copy2(source, destination)
    return str(destination)


def _read_live_snapshot_payload(path: Path) -> dict[str, object] | None:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"payload": payload}
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


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

    if state_payload is None:
        state_payload = _fetch_json(f"/api/live_state?date={date_str}")
        if state_payload and _write_live_snapshot_payload(state_destination, state_payload):
            copied["live_state_path"] = str(state_destination)

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
        if existing:
            if copied_key:
                copied[copied_key] = existing
            continue
        if not joined_event_ids:
            continue
        query = f"/api/{kind}?date={date_str}&event_ids={joined_event_ids}"
        if kind == "live_lines":
            query = f"{query}&include_period_totals=1"
        payload = _fetch_json(query)
        if payload and _write_live_snapshot_payload(destination, payload) and copied_key:
            copied[copied_key] = str(destination)

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
    return env


def _owned_snapshot_cli_args(*, date_str: str, out_path: Path, regions: str, bookmakers: str, markets: str) -> list[str]:
    args = [
        _local_python(),
        str(REPO_ROOT / "scripts" / "fetch_basketball_oddsapi_props_local.py"),
        "--league",
        "wnba",
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
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("OMP_THREAD_LIMIT", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("NUMEXPR_NUM_THREADS", "1")
    return env


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

    rc = _run_to_file(
        [
            _source_python(source_root),
            "-m",
            f"{package_name}.cli",
            command_name,
            "--date",
            date_str,
        ],
        log_file,
        cwd=source_root,
        env=_source_worker_env(source_root),
        timeout_s=15 * 60,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )

    if _path_has_meaningful_content(existing_path):
        return str(existing_path), int(rc)

    _append_log(log_file, f"{command_name} did not create expected artifact: {existing_path}")
    return None, int(rc)


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
    out.to_csv(processed_path, index=False)
    _append_log(log_file, f"Seeded fallback game odds slate from raw history: {processed_path} (rows={len(out)})")
    return True


def _seed_game_odds_from_props_snapshot(*, source_root: Path, date_str: str, log_file: Path) -> bool:
    processed_path = source_root / "data" / "processed" / f"game_odds_{date_str}.csv"
    if _path_has_meaningful_content(processed_path):
        return True

    snapshot_candidates = (
        source_root / "data" / "processed" / f"oddsapi_player_props_{date_str}.csv",
        source_root / "data" / "raw" / f"odds_wnba_player_props_{date_str}.csv",
    )
    import pandas as pd

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
        out = frame[["home_team", "away_team"]].dropna().drop_duplicates().copy()
        out = out.rename(columns={"away_team": "visitor_team"})
        out.insert(0, "date", date_str)
        if "commence_time" in frame.columns:
            times = frame[["home_team", "away_team", "commence_time"]].dropna(subset=["home_team", "away_team"]).copy()
            times = times.rename(columns={"away_team": "visitor_team"})
            times = times.drop_duplicates(subset=["home_team", "visitor_team"], keep="first")
            out = out.merge(times, on=["home_team", "visitor_team"], how="left")
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(processed_path, index=False)
        _append_log(log_file, f"Seeded fallback game odds slate from props snapshot: {processed_path} (rows={len(out)})")
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
    return _run_to_file(
        [
            _source_python(source_root),
            "-m",
            f"{package_name}.cli",
            *command_parts,
        ],
        log_file,
        cwd=source_root,
        env=_source_worker_env(source_root),
        timeout_s=timeout_s,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )


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

    rc_fetch = 0
    if not any(path.exists() and path.is_file() and path.stat().st_size > 0 for path in raw_candidates):
        rc_fetch = _run_source_subprocess_cli_command(
            source_root=source_root,
            package_name=package_name,
            command_parts=["fetch", "--years", "10", "--no-periods"],
            log_file=log_file,
            heartbeat_cb=heartbeat_cb,
            timeout_s=45 * 60,
        )

    rc_build_features = 0
    if not any(path.exists() and path.is_file() and path.stat().st_size > 0 for path in feature_candidates):
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

    rc_predict_date = _run_source_predict_date(
        source_root=source_root,
        package_name=package_name,
        date_str=date_str,
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
    )
    if int(rc_predict_date) != 0:
        _append_log(log_file, f"predict-date failed with exit code {int(rc_predict_date)}; retrying via CPU daily-update fallback")
        rc_predict_date = _run_source_daily_update_cpu_fallback(
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
    return _run_to_file(
        [
            _source_python(source_root),
            "-m",
            f"{package_name}.cli",
            "predict-date",
            "--date",
            date_str,
        ],
        log_file,
        cwd=source_root,
        env=_source_worker_env(source_root),
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
    return _run_to_file(
        [
            _source_python(source_root),
            "-m",
            f"{package_name}.cli",
            "daily-update",
            "--date",
            date_str,
            "--no-npu",
            "--no-git-push",
        ],
        log_file,
        cwd=source_root,
        env=_source_worker_env(source_root),
        timeout_s=45 * 60,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )


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
            league_code="wnba",
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
    if any(path.exists() and path.stat().st_size > 0 for path in (_active_player_logs_paths(source_root) + _active_player_logs_fallback_paths(source_root))):
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


def _predict_props_cli_args(*, source_root: Path, date_str: str, out_path: Path) -> list[str]:
    smart_sim_n_sims = max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS", 150))
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
) -> dict[str, object]:
    raw_root = source_root / "data" / "raw"
    processed_root = source_root / "data" / "processed"
    raw_fp = raw_root / f"odds_wnba_player_props_{date_str}.csv"
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
        "snapshot_path": str(raw_fp),
        "predictions_path": str(pred_fp),
        "edges_path": str(edges_fp),
        "recs_path": str(rec_fp),
        "snapshot_alias_path": str(processed_root / f"oddsapi_player_props_{date_str}.csv"),
        "snapshot_alias_rows": 0,
        "duration_s": None,
        "error": None,
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
    if not state.get("error") and int(state["snapshot_rows"] or 0) > 0 and (do_edges or do_export):
        state["phase"] = "predictions"
        state["phase_started_at"] = dt.datetime.utcnow().isoformat()
        source_predictions_path = processed_root / f"predictions_{date_str}.csv"
        source_game_odds_path = processed_root / f"game_odds_{date_str}.csv"
        if (not source_predictions_path.exists()) or (not source_game_odds_path.exists()):
            _ensure_source_game_inputs(
                source_root=source_root,
                package_name="wnba_betting",
                date_str=date_str,
                log_file=log_file,
                heartbeat_cb=_touch_progress,
            )
        player_logs_ok, player_logs_error = _ensure_player_logs_for_props_refresh(
            source_root=source_root,
            date_str=date_str,
            log_file=log_file,
            heartbeat_cb=_touch_progress,
        )
        if not player_logs_ok:
            state["error"] = player_logs_error or f"player_logs missing before predict-props for {date_str}"
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
                    smart_sim_n_sims=max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS", 150)),
                    smart_sim_pbp=_env_bool("REFRESH_PREDICT_PROPS_SMART_SIM_PBP", True),
                    smart_sim_workers=max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_WORKERS", 1)),
                    log_file=log_file,
                    heartbeat_cb=_touch_progress,
                    heartbeat_every_s=5.0,
                )
                _touch_progress()
                rc_pred = 0
            except Exception:
                rc_pred = 1
            state["predictions_rows"] = int(_count_csv_rows_quick(pred_fp))
            existing_edges_rows = int(_count_csv_rows_quick(edges_fp))
            existing_recs_rows = int(_count_csv_rows_quick(rec_fp))
            existing_game_cards_rows = int(_count_csv_rows_quick(source_root / 'data' / 'processed' / f'game_cards_{date_str}.csv'))
            have_downstream_artifacts = (
                (not do_edges or existing_edges_rows > 0)
                and (not do_export or existing_recs_rows > 0)
                and (not do_export or existing_game_cards_rows > 0)
            )
            if int(rc_pred) != 0:
                if have_downstream_artifacts:
                    _append_log(log_file, f"predict-props returned exit code {int(rc_pred)} but downstream artifacts already exist for {date_str}; continuing")
                else:
                    state["error"] = f"predict-props failed with exit code {int(rc_pred)}"
            elif int(state["predictions_rows"] or 0) <= 0:
                if have_downstream_artifacts:
                    _append_log(log_file, f"predict-props wrote no rows to {pred_fp.name} but downstream artifacts already exist for {date_str}; continuing")
                else:
                    state["error"] = f"predict-props completed without writing rows to {pred_fp.name}"
            else:
                pred_ready = True
    elif int(state["snapshot_rows"] or 0) <= 0:
        state["rc_edges"] = None if do_edges else state.get("rc_edges")
        state["rc_export"] = None if do_export else state.get("rc_export")

    if pred_ready and do_edges:
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

    if do_export and not state.get("error"):
        state["phase"] = "export"
        state["phase_started_at"] = dt.datetime.utcnow().isoformat()
        state["rc_export"] = -1
        try:
            _touch_progress()
            game_input_rcs = _ensure_source_game_inputs(
                source_root=source_root,
                package_name="wnba_betting",
                date_str=date_str,
                log_file=log_file,
                heartbeat_cb=_touch_progress,
            )
            rc_local_props_export = 0
            if pred_ready:
                _, _ = export_props_recommendations_local(processed_root=processed_root, date_str=date_str)
                _touch_progress()
            else:
                _append_log(log_file, f"Skipping local props recommendations export for {date_str}: props predictions were not refreshed")
            _, rc_recommendations = _run_source_processed_export(
                source_root=source_root,
                package_name="wnba_betting",
                command_name="export-recommendations",
                date_str=date_str,
                expected_file_name=f"recommendations_{date_str}.csv",
                log_file=log_file,
                heartbeat_cb=_touch_progress,
            )
            _, rc_game_cards = _run_source_processed_export(
                source_root=source_root,
                package_name="wnba_betting",
                command_name="export-game-cards",
                date_str=date_str,
                expected_file_name=f"game_cards_{date_str}.csv",
                log_file=log_file,
                heartbeat_cb=_touch_progress,
            )
            rc_export = 0 if all(int(value) == 0 for value in game_input_rcs.values()) and int(rc_local_props_export) == 0 and int(rc_recommendations) == 0 and int(rc_game_cards) == 0 else 1
        except Exception:
            _append_log(log_file, traceback.format_exc())
            rc_export = 1
        state["rc_export"] = int(rc_export)
        state["recs_rows"] = int(_count_csv_rows_quick(rec_fp))
        source_game_cards_rows = int(_count_csv_rows_quick(source_root / 'data' / 'processed' / f'game_cards_{date_str}.csv'))
        if int(rc_export) != 0 and int(state["recs_rows"] or 0) > 0 and source_game_cards_rows > 0:
            state["rc_export"] = 0
        elif int(rc_export) != 0:
            state["error"] = f"export-props-recommendations failed with exit code {int(rc_export)}"
        elif int(state["snapshot_rows"] or 0) > 0 and source_game_cards_rows <= 0:
            state["error"] = f"export-game-cards completed without writing rows to game_cards_{date_str}.csv"

    state["snapshot_rows"] = int(_count_csv_rows_quick(raw_fp))
    state["predictions_rows"] = int(_count_csv_rows_quick(pred_fp))
    state["edges_rows"] = int(_count_csv_rows_quick(edges_fp))
    state["recs_rows"] = int(_count_csv_rows_quick(rec_fp))
    state["snapshot_alias_rows"] = int(_count_csv_rows_quick(Path(str(state.get("snapshot_alias_path") or ""))))
    state["phase"] = "done"
    ended = dt.datetime.utcnow().isoformat()
    state["phase_started_at"] = ended
    state["heartbeat_at"] = ended
    state["ended_at"] = ended
    state["duration_s"] = float(max(0.0, time.time() - started_ts))
    if do_push:
        _append_log(log_file, "do_push requested but push is not implemented in the Syndicate-owned runner")
    return state


def _existing_refresh_state(*, source_root: Path, date_str: str, do_edges: bool, do_export: bool, started_at: str | None = None) -> dict[str, object] | None:
    raw_root = source_root / "data" / "raw"
    processed_root = source_root / "data" / "processed"
    snapshot_path = raw_root / f"odds_wnba_player_props_{date_str}.csv"
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
    if any(not path.exists() or not path.is_file() for path in required_paths):
        return None

    started = str(started_at or "") or str(dt.datetime.utcnow().isoformat())
    ended = str(dt.datetime.utcnow().isoformat())
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


def _existing_artifact_bundle_state(*, artifact_root: Path, date_str: str, do_edges: bool, do_export: bool, started_at: str | None = None) -> dict[str, object] | None:
    raw_root = artifact_root / "data" / "raw"
    processed_root = artifact_root / "data" / "processed"
    snapshot_path = raw_root / f"odds_wnba_player_props_{date_str}.csv"
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
    if any(not path.exists() or not path.is_file() for path in required_paths):
        return None

    started = str(started_at or "") or str(dt.datetime.utcnow().isoformat())
    ended = str(dt.datetime.utcnow().isoformat())
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
    spec.loader.exec_module(module)
    return module


def _target_refresh_dates(*, date_str: str, days_ahead: int) -> list[str]:
    parsed = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    return [(parsed + dt.timedelta(days=offset)).isoformat() for offset in range(0, max(0, int(days_ahead)) + 1)]


def _run_playoff_transition_if_needed(*, source_root: Path, date_str: str) -> dict[str, object]:
    module_path = source_root / "src" / "wnba_betting" / "playoff_transition.py"
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
        module = importlib.import_module("wnba_betting.playoff_transition")
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


def _load_source_app(source_root: Path):
    app_path = source_root / "app.py"
    if not app_path.exists() or not app_path.is_file():
        return None
    return _load_module_from_path("syndicate_wnba_source_app", app_path)


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

    tool_specs = (
        (
            source_root / "tools" / "build_recon_players.py",
            "syndicate_wnba_build_recon_players",
            "build_recon_players",
            processed_root / f"recon_players_{date_str}.csv",
            "recon_players_path",
        ),
        (
            source_root / "tools" / "build_live_player_lens_tuning.py",
            "syndicate_wnba_build_live_player_lens_tuning",
            "build_live_player_lens_tuning",
            processed_root / f"live_player_lens_tuning_{date_str}.csv",
            "live_player_lens_tuning_path",
        ),
    )
    for module_path, module_name, function_name, out_path, copied_key in tool_specs:
        try:
            module = _load_module_from_path(module_name, module_path)
            builder = getattr(module, function_name, None)
            if builder is None:
                continue
            df = builder(date_str)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out_path, index=False)
            copied[copied_key] = str(out_path)
        except Exception:
            continue
    return copied


def _export_top_by_game_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"props_recommendations_top_by_game_{date_str}.json",
    )
    if existing:
        return existing
    source_app = _load_source_app(source_root)
    if source_app is None:
        return None
    out_path = processed_root / f"props_recommendations_top_by_game_{date_str}.json"
    query = (
        f"/api/props/recommendations?date={date_str}&compact=1&portfolio_only=1"
        "&use_snapshot=0&limit=25&per_game_limit=3&per_market=1&slate_per_market_limit=4"
        "&markets=pts,reb,ast,threes,blk,stl,pra,pr,pa,ra,dd,td"
    )
    client = source_app.app.test_client()
    response = client.get(query)
    try:
        payload = response.get_json() if response is not None else None
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        payload = {"error": "no_json", "status": int(getattr(response, "status_code", 0) or 0)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out_path)


def _export_recommendations_slate_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recommendations_slate_{date_str}.json",
    )
    if existing:
        return existing
    source_app = _load_source_app(source_root)
    if source_app is None:
        return None
    out_path = processed_root / f"recommendations_slate_{date_str}.json"
    client = source_app.app.test_client()
    response = client.get(f"/recommendations?format=json&view=slate&date={date_str}")
    try:
        payload = response.get_json() if response is not None else None
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        payload = {"error": "no_json", "status": int(getattr(response, "status_code", 0) or 0)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out_path)


def _export_cards_props_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"cards_props_snapshot_{date_str}.json",
    )
    if existing:
        return existing
    source_app = _load_source_app(source_root)
    if source_app is None:
        return None
    out_path = processed_root / f"cards_props_snapshot_{date_str}.json"
    client = source_app.app.test_client()
    response = client.get(f"/api/cards?date={date_str}&props_source=source")
    try:
        payload = response.get_json() if response is not None else None
    except Exception:
        payload = None

    games_out = []
    if isinstance(payload, dict):
        for game in payload.get("games") or []:
            if not isinstance(game, dict):
                continue
            prop_recommendations = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}
            games_out.append(
                {
                    "home_tri": game.get("home_tri"),
                    "away_tri": game.get("away_tri"),
                    "prop_recommendations": {
                        "home": [row for row in (prop_recommendations.get("home") or []) if isinstance(row, dict)],
                        "away": [row for row in (prop_recommendations.get("away") or []) if isinstance(row, dict)],
                    },
                }
            )

    out = {"date": date_str, "games": games_out}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return str(out_path)


def _export_cards_sim_detail_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"cards_sim_detail_{date_str}.json",
    )
    if existing:
        return existing
    source_app = _load_source_app(source_root)
    if source_app is None:
        return None
    out_path = processed_root / f"cards_sim_detail_{date_str}.json"
    client = source_app.app.test_client()
    response = client.get(f"/api/cards?date={date_str}&include_players=1&props_source=auto")
    try:
        payload = response.get_json() if response is not None else None
    except Exception:
        payload = None

    games_out = []
    if isinstance(payload, dict):
        for game in payload.get("games") or []:
            if not isinstance(game, dict):
                continue
            sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
            players = sim.get("players") if isinstance(sim.get("players"), dict) else {}
            missing = sim.get("missing_prop_players") if isinstance(sim.get("missing_prop_players"), dict) else {}
            injuries = sim.get("injuries") if isinstance(sim.get("injuries"), dict) else {}
            summary = sim.get("players_summary") if isinstance(sim.get("players_summary"), dict) else {
                "home": len(players.get("home") or []),
                "away": len(players.get("away") or []),
                "missing_home": len(missing.get("home") or []),
                "missing_away": len(missing.get("away") or []),
                "injured_home": len(injuries.get("home") or []),
                "injured_away": len(injuries.get("away") or []),
            }
            games_out.append(
                {
                    "home_tri": game.get("home_tri"),
                    "away_tri": game.get("away_tri"),
                    "sim": {
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

    out = {"date": date_str, "games": games_out}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return str(out_path)


def _export_recon_games_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recon_games_{date_str}.csv",
    )
    if existing:
        return existing
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
    shutil.copy2(source, destination)
    return str(destination)


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
        missing_exports.append((file_name, query, destinations))
    if not missing_exports:
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


def _materialize_artifact_bundle(*, state: dict[str, object], artifact_root: Path, source_root: Path) -> dict[str, object]:
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
    if date_text and source_directory is not None:
        smart_sim_files = _copy_matching_files(
            source_directory=source_directory,
            pattern=f"smart_sim_{date_text}_*.json",
            destination_directory=processed_root,
        )
        if smart_sim_files:
            copied["smart_sim_paths"] = smart_sim_files
        recon_games_path = _export_recon_games_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recon_games_path:
            copied["recon_games_path"] = recon_games_path
        recon_quarters_path = _export_recon_quarters_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recon_quarters_path:
            copied["recon_quarters_path"] = recon_quarters_path
        game_cards_path = _export_game_cards_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if game_cards_path:
            copied["game_cards_path"] = game_cards_path
        boxscores_path = _export_boxscores_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if boxscores_path:
            copied["boxscores_path"] = boxscores_path
        recommendations_path = _export_recommendations_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recommendations_path:
            copied["recommendations_path"] = recommendations_path
        recon_props_path = _export_recon_props_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recon_props_path:
            copied["recon_props_path"] = recon_props_path
        recommendations_slate_path = _export_recommendations_slate_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recommendations_slate_path:
            copied["recommendations_slate_path"] = recommendations_slate_path
        cards_props_snapshot_path = _export_cards_props_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if cards_props_snapshot_path:
            copied["cards_props_snapshot_path"] = cards_props_snapshot_path
        cards_sim_detail_path = _export_cards_sim_detail_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if cards_sim_detail_path:
            copied["cards_sim_detail_path"] = cards_sim_detail_path
        top_by_game_path = _export_top_by_game_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if top_by_game_path:
            copied["top_by_game_path"] = top_by_game_path
        copied.update(_export_live_lens_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root, live_lens_root=live_lens_root))
        copied.update(_export_live_snapshot_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root))
        copied.update(_build_optional_player_recon_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root))
    boxscores_history_path = _refresh_boxscores_history_artifact(source_root=source_root, processed_root=processed_root)
    if boxscores_history_path:
        copied["boxscores_history_path"] = boxscores_history_path
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
    shutil.copy2(source, destination)
    return str(destination)


def _export_recon_props_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recon_props_{date_str}.csv",
    )
    if existing:
        return existing
    source = source_root / "data" / "processed" / f"recon_props_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


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
    shutil.copy2(source, destination)
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
    shutil.copy2(source, destination)
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
    shutil.copy2(source, destination)
    return str(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the WNBA OddsAPI props refresh job through a Syndicate-owned entrypoint.")
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
    args = parser.parse_args()

    source_root_arg = str(args.source_root or "").strip()
    source_root = Path(source_root_arg).resolve() if source_root_arg else None
    artifact_root = str(args.artifact_root or "").strip()
    target_dates = _target_refresh_dates(date_str=args.date, days_ahead=int(args.days_ahead or 0))
    states: list[dict[str, object]] = []
    artifact_root_path = Path(artifact_root).resolve() if artifact_root else None
    for index, target_date in enumerate(target_dates):
        state = None
        started_at = args.started_at if index == 0 else None
        if source_root is not None and not bool(args.force_refresh):
            state = _existing_refresh_state(
                source_root=source_root,
                date_str=target_date,
                do_edges=bool(args.do_edges),
                do_export=bool(args.do_export),
                started_at=started_at,
            )
        if state is None and artifact_root and not bool(args.force_refresh):
            state = _existing_artifact_bundle_state(
                artifact_root=artifact_root_path,
                date_str=target_date,
                do_edges=bool(args.do_edges),
                do_export=bool(args.do_export),
                started_at=started_at,
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
            )
        if source_root is not None:
            state["playoff_transition"] = _run_playoff_transition_if_needed(source_root=source_root, date_str=target_date)
        if artifact_root_path and source_root is not None and not state.get("reused_existing_artifact_bundle"):
            copied = _materialize_artifact_bundle(
                state=state,
                artifact_root=artifact_root_path,
                source_root=source_root,
            )
            if copied:
                state["artifact_bundle_root"] = str(artifact_root_path)
                state["artifact_bundle_files"] = copied
        states.append(state)
    state = states[0] if states else {"date": str(args.date), "error": "no refresh states generated"}
    if len(states) > 1:
        state["lookahead_runs"] = states[1:]
    print(json.dumps(_json_ready(state), indent=2, sort_keys=True))

    snapshot_rows = int(state.get("snapshot_rows") or 0)
    alias_rows = int(state.get("snapshot_alias_rows") or 0)
    edges_rows = int(state.get("edges_rows") or 0)
    recs_rows = int(state.get("recs_rows") or 0)
    if state.get("error"):
        return 1
    for extra_state in states[1:]:
        if extra_state.get("error"):
            return 1
    if snapshot_rows > 0 and alias_rows <= 0:
        return 1
    if bool(args.do_edges) and snapshot_rows > 0 and edges_rows <= 0:
        return 1
    if bool(args.do_export) and snapshot_rows > 0 and recs_rows <= 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())