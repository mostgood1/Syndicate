from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaab.mirror_export import export_api_bundle_from_raw


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _copy_output_file(source_path: Path, destination_path: Path, *, mirror_root: Path) -> str:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)
    return str(destination_path.relative_to(mirror_root)).replace("\\", "/")


def _relative_display_path(path: Path, *roots: Path) -> str:
    for root in roots:
        try:
            return str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
    return str(path).replace("\\", "/")


def _summarize_existing_raw_outputs(*, raw_root: Path, target_date: str, mirror_root: Path) -> dict:
    raw_manifest = _read_json(raw_root / "manifest.json") or {}
    manifest_config_files = [str(item) for item in list(raw_manifest.get("config_files") or []) if str(item).strip()]
    if manifest_config_files:
        config_files = sorted(manifest_config_files)
    else:
        config_files = sorted(
            _relative_display_path(path, mirror_root, raw_root.parent)
            for path in (raw_root / "config").glob("*")
            if path.is_file()
        ) if (raw_root / "config").exists() else []

    manifest_date_files = [
        str(item)
        for item in list(raw_manifest.get("date_files") or [])
        if f"/by_date/{target_date}/" in str(item).replace("\\", "/") and str(item).strip()
    ]
    if manifest_date_files:
        date_files = sorted(manifest_date_files)
    else:
        date_files = sorted(
            _relative_display_path(path, mirror_root, raw_root.parent)
            for path in (raw_root / "by_date" / target_date).glob("*")
            if path.is_file()
        ) if (raw_root / "by_date" / target_date).exists() else []
    return {
        "source_root": str(raw_manifest.get("source_root") or raw_root),
        "config_files": config_files,
        "date_files": date_files,
    }


def collect_raw_output_artifacts(*, source_outputs_root: Path, mirror_root: Path, target_date: str, existing_raw_root: Path | None = None) -> dict:
    raw_outputs_root = mirror_root / "raw_outputs"
    existing = (
        _summarize_existing_raw_outputs(raw_root=existing_raw_root, target_date=target_date, mirror_root=mirror_root)
        if existing_raw_root is not None and existing_raw_root.exists()
        else {"config_files": [], "date_files": []}
    )
    result = {
        "source_root": str(source_outputs_root),
        "date": target_date,
        "config_files": list(existing.get("config_files") or []),
        "date_files": list(existing.get("date_files") or []),
    }
    if not source_outputs_root.exists() or not target_date:
        return result

    def _add_unique(items: list[str], rel_path: str) -> None:
        if rel_path not in items:
            items.append(rel_path)

    config_names = [
        "live_lens_tuning.json",
    ]
    for name in config_names:
        source_path = source_outputs_root / name
        if not source_path.exists():
            continue
        rel_path = _copy_output_file(source_path, raw_outputs_root / "config" / name, mirror_root=mirror_root)
        _add_unique(result["config_files"], rel_path)

    file_names = [
        f"games_{target_date}.csv",
        f"games_with_odds_{target_date}.csv",
        f"predictions_{target_date}.csv",
        f"predictions_unified_enriched_{target_date}.csv",
        f"live_features_{target_date}.csv",
    ]

    for name in file_names:
        source_path = source_outputs_root / name
        if not source_path.is_file():
            continue
        rel_path = _copy_output_file(
            source_path,
            raw_outputs_root / "by_date" / target_date / source_path.name,
            mirror_root=mirror_root,
        )
        _add_unique(result["date_files"], rel_path)

    odds_history_path = source_outputs_root / "odds_history" / f"odds_{target_date}.csv"
    if odds_history_path.is_file():
        rel_path = _copy_output_file(
            odds_history_path,
            raw_outputs_root / "by_date" / target_date / odds_history_path.name,
            mirror_root=mirror_root,
        )
        _add_unique(result["date_files"], rel_path)

    manifest = {
        "source_root": result["source_root"],
        "date": target_date,
        "config_count": len(result["config_files"]),
        "date_file_count": len(result["date_files"]),
        "config_files": result["config_files"],
        "date_files": result["date_files"],
    }
    _write_json(raw_outputs_root / "manifest.json", manifest)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the NCAAB Syndicate mirror from source outputs using local raw-output synthesis only.")
    parser.add_argument("dest_api_root")
    parser.add_argument("date")
    parser.add_argument("--source-root")
    parser.add_argument("--raw-root")
    args = parser.parse_args()

    dest_api_root = Path(args.dest_api_root).resolve()
    mirror_root = dest_api_root.parent
    raw_root = Path(args.raw_root).resolve() if args.raw_root else (mirror_root / "raw_outputs")
    source_root = Path(args.source_root).resolve() if args.source_root else None

    if source_root is not None:
        source_outputs_root = source_root / "outputs"
        raw_outputs = collect_raw_output_artifacts(
            source_outputs_root=source_outputs_root,
            mirror_root=mirror_root,
            target_date=args.date,
            existing_raw_root=raw_root,
        )
    elif raw_root.exists():
        raw_outputs = _summarize_existing_raw_outputs(raw_root=raw_root, target_date=args.date, mirror_root=mirror_root)
    else:
        raise SystemExit("Either --source-root must be provided or --raw-root must point to an existing raw_outputs directory.")

    manifest = export_api_bundle_from_raw(dest_api_root, raw_root, args.date)
    manifest["source_repo"] = str(source_root) if source_root is not None else None
    manifest["export_root"] = str(dest_api_root)
    manifest["raw_outputs"] = {
        "source_root": raw_outputs.get("source_root"),
        "config_count": len(raw_outputs.get("config_files") or []),
        "date_file_count": len(raw_outputs.get("date_files") or []),
    }
    manifest["fallback_used"] = False

    _write_json(dest_api_root / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())