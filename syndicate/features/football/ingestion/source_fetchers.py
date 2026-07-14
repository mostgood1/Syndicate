from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _repo_root_from(file_path: str | Path) -> Path:
    return Path(file_path).resolve().parents[4]


def tracking_root(local_dir_name: str) -> Path:
    repo_root = _repo_root_from(__file__)
    data_root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if data_root:
        return (Path(data_root).resolve() / local_dir_name / "tracking").resolve()
    return (repo_root / "data" / local_dir_name / "tracking").resolve()


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_bytes(url: str) -> bytes | None:
    try:
        with urlopen(url, timeout=30) as response:
            return response.read()
    except (URLError, TimeoutError, OSError):
        return None


def _write_bytes(path: Path, data: bytes) -> None:
    ensure_directory(path.parent)
    path.write_bytes(data)


def _write_text(path: Path, text: str) -> None:
    ensure_directory(path.parent)
    path.write_text(text, encoding="utf-8")


def download_to_cache(url: str, target_path: Path) -> Path | None:
    data = _download_bytes(url)
    if data is None:
        return None
    _write_bytes(target_path, data)
    return target_path


def load_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def load_json_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "records", "games", "plays", "players", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, dict)]
        return [dict(payload)]
    return []


def load_tabular_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_dir():
        rows: list[dict[str, Any]] = []
        for child in sorted(path.iterdir()):
            rows.extend(load_tabular_rows(child))
        return rows
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_csv_rows(path)
    if suffix == ".json":
        return load_json_rows(path)
    return []


def save_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def save_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_directory(path.parent)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    ensure_directory(target.parent)
    shutil.copy2(source, target)
    return True
