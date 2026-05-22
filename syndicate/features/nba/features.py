from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.nba.sources import _artifact_roots


def _artifact_root() -> Path:
    roots = _artifact_roots()
    base_root = roots[0] if roots else (Path(__file__).resolve().parents[3] / "data" / "nba_source")
    return (base_root / "data" / "processed").resolve()


def _catalog_path() -> Path:
    return _artifact_root().parent / "features_catalog.json"


def _latest_for(pattern: str) -> tuple[str | None, Path | None]:
    processed_root = _artifact_root()
    best_date: str | None = None
    best_path: Path | None = None
    try:
        for path in sorted(processed_root.glob(pattern)):
            date_value = path.stem.split("_")[-1]
            if len(date_value) != 10:
                continue
            try:
                datetime.strptime(date_value, "%Y-%m-%d")
            except Exception:
                continue
            if best_date is None or date_value > best_date:
                best_date = date_value
                best_path = path
    except Exception:
        return None, None
    return best_date, best_path


def _columns_for(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            header = handle.readline().strip()
        return [column for column in header.split(",") if column] if header else []
    except Exception:
        return []


def _descriptions() -> tuple[str, dict[str, str]]:
    catalog_path = _catalog_path()
    catalog: dict[str, Any] = {}
    if catalog_path.exists():
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8")) or {}
        except Exception:
            catalog = {}
    descriptions: dict[str, str] = {}
    datasets = catalog.get("datasets") if isinstance(catalog, dict) else None
    if isinstance(datasets, dict):
        for dataset_key, mapping in datasets.items():
            if not isinstance(mapping, dict):
                continue
            for column, text in mapping.items():
                if column and text is not None:
                    descriptions[f"{dataset_key}.{column}"] = str(text)
    flat = catalog.get("descriptions") if isinstance(catalog, dict) else None
    if isinstance(flat, dict):
        for key, text in flat.items():
            if key and text is not None:
                descriptions[str(key)] = str(text)
    relative_catalog = "data/features_catalog.json"
    if catalog_path.exists():
        try:
            relative_catalog = str(catalog_path.relative_to(_artifact_root().parents[1])).replace("\\", "/")
        except Exception:
            pass
    return relative_catalog, descriptions


@lru_cache(maxsize=16)
def build_features_payload() -> dict[str, Any] | None:
    catalog_path, descriptions = _descriptions()
    datasets = []
    for key, pattern in [
        ("predictions", "predictions_*.csv"),
        ("recommendations", "recommendations_*.csv"),
        ("recon_games", "recon_games_*.csv"),
        ("props_predictions", "props_predictions_*.csv"),
        ("props_recommendations", "props_recommendations_*.csv"),
        ("recon_props", "recon_props_*.csv"),
        ("props_edges", "props_edges_*.csv"),
    ]:
        latest_date, path = _latest_for(pattern)
        relative_path = None
        if path is not None:
            try:
                relative_path = str(path.relative_to(_artifact_root().parents[1])).replace("\\", "/")
            except Exception:
                relative_path = str(path).replace("\\", "/")
        datasets.append(
            {
                "key": key,
                "latest_date": latest_date,
                "path": relative_path,
                "columns": _columns_for(path),
            }
        )
    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "catalog_path": catalog_path,
        "datasets": datasets,
        "descriptions": descriptions,
    }