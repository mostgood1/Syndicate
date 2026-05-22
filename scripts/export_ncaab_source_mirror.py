from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import quote_plus

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
    config_files = sorted(
        _relative_display_path(path, mirror_root, raw_root.parent)
        for path in (raw_root / "config").glob("*")
        if path.is_file()
    ) if (raw_root / "config").exists() else list(raw_manifest.get("config_files") or [])
    date_files = sorted(
        _relative_display_path(path, mirror_root, raw_root.parent)
        for path in (raw_root / "by_date" / target_date).glob("*")
        if path.is_file()
    ) if (raw_root / "by_date" / target_date).exists() else []
    if not date_files:
        for raw_path in list(raw_manifest.get("date_files") or []):
            if f"/by_date/{target_date}/" in str(raw_path).replace("\\", "/"):
                date_files.append(str(raw_path))
    return {
        "source_root": str(raw_manifest.get("source_root") or raw_root),
        "config_files": config_files,
        "date_files": date_files,
    }


def collect_raw_output_artifacts(*, source_outputs_root: Path, mirror_root: Path, target_date: str) -> dict:
    raw_outputs_root = mirror_root / "raw_outputs"
    result = {
        "source_root": str(source_outputs_root),
        "date": target_date,
        "config_files": [],
        "date_files": [],
    }
    if not source_outputs_root.exists() or not target_date:
        return result

    config_names = [
        "live_lens_tuning.json",
    ]
    for name in config_names:
        source_path = source_outputs_root / name
        if not source_path.exists():
            continue
        rel_path = _copy_output_file(source_path, raw_outputs_root / "config" / name, mirror_root=mirror_root)
        result["config_files"].append(rel_path)

    file_names = [
        f"games_{target_date}.csv",
        f"games_with_odds_{target_date}.csv",
        f"predictions_{target_date}.csv",
        f"predictions_display_{target_date}.csv",
        f"predictions_unified_enriched_{target_date}.csv",
        f"live_features_{target_date}.csv",
        f"live_snapshot_lines_{target_date}.csv",
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
        result["date_files"].append(rel_path)

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


def _request_json(client, path: str) -> dict | None:
    try:
        response = client.get(path)
        payload = response.get_json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _run_source_app_fallback(*, source_root: Path, dest_api_root: Path, target_date: str, existing_manifest: dict) -> dict:
    sys.path.insert(0, str(source_root))
    from app import app as source_app  # type: ignore

    copied = list(existing_manifest.get("copied_artifacts") or [])
    with source_app.test_client() as client:
        display_dates = _request_json(client, "/api/display_prediction_dates") or {"dates": [], "latest": None}
        schedule_dates = _request_json(client, "/api/dates") or {"dates": [], "latest": None}
        results_dates = _request_json(client, "/api/results_dates") or {"dates": [], "latest": None}
        live_lens_tuning = _request_json(client, "/api/live_lens_tuning?ttl=0") or {}

        _write_json(dest_api_root / "display_prediction_dates.json", display_dates)
        _write_json(dest_api_root / "dates.json", schedule_dates)
        _write_json(dest_api_root / "results_dates.json", results_dates)
        _write_json(dest_api_root / "live_lens_tuning.json", live_lens_tuning)

        recommendation_path = dest_api_root / "recommendations" / f"recommendations_{target_date}.json"
        results_path = dest_api_root / "results_by_date" / f"results_{target_date}.json"
        live_state_path = dest_api_root / "live_state" / f"live_state_{target_date}.json"
        live_lines_path = dest_api_root / "live_lines" / f"live_lines_{target_date}.json"

        if not recommendation_path.exists():
            payload = _request_json(client, f"/api/recommendations?date={quote_plus(target_date)}")
            if payload:
                _write_json(recommendation_path, payload)
                copied.append(f"api/recommendations/recommendations_{target_date}.json")

        if not results_path.exists():
            payload = _request_json(client, f"/api/results_by_date?date={quote_plus(target_date)}")
            if payload:
                _write_json(results_path, payload)
                copied.append(f"api/results_by_date/results_{target_date}.json")

        if not live_state_path.exists():
            payload = _request_json(client, f"/api/live_state?date={quote_plus(target_date)}&ttl=0")
            if payload:
                _write_json(live_state_path, payload)
                copied.append(f"api/live_state/live_state_{target_date}.json")

        if not live_lines_path.exists():
            rows_payload = _request_json(client, f"/api/recommendations?date={quote_plus(target_date)}") or {}
            rows = rows_payload.get("data") if isinstance(rows_payload.get("data"), list) else []
            event_ids: list[str] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                game_id = str(row.get("event_id") or row.get("game_id") or "").strip()
                if game_id and game_id not in event_ids:
                    event_ids.append(game_id)
            payload = _request_json(
                client,
                f"/api/live_lines?date={quote_plus(target_date)}&event_ids={quote_plus(','.join(event_ids))}&ttl=0",
            ) if event_ids else {"status": "ok", "date": target_date, "count": 0, "lines": {}}
            if payload:
                _write_json(live_lines_path, payload)
                copied.append(f"api/live_lines/live_lines_{target_date}.json")

    existing_manifest["copied_artifacts"] = copied
    existing_manifest["fallback_used"] = True
    return existing_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the NCAAB Syndicate mirror from source outputs, preferring local raw-output synthesis before source-app fallback.")
    parser.add_argument("dest_api_root")
    parser.add_argument("date")
    parser.add_argument("--source-root")
    parser.add_argument("--raw-root")
    parser.add_argument("--allow-source-app-fallback", action="store_true")
    args = parser.parse_args()

    dest_api_root = Path(args.dest_api_root).resolve()
    mirror_root = dest_api_root.parent
    raw_root = Path(args.raw_root).resolve() if args.raw_root else (mirror_root / "raw_outputs")
    source_root = Path(args.source_root).resolve() if args.source_root else None

    if source_root is not None:
        source_outputs_root = source_root / "outputs"
        raw_outputs = collect_raw_output_artifacts(source_outputs_root=source_outputs_root, mirror_root=mirror_root, target_date=args.date)
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

    if args.allow_source_app_fallback:
        if source_root is None:
            raise SystemExit("--allow-source-app-fallback requires --source-root so the source app can be imported.")
        recommendation_path = dest_api_root / "recommendations" / f"recommendations_{args.date}.json"
        results_path = dest_api_root / "results_by_date" / f"results_{args.date}.json"
        live_state_path = dest_api_root / "live_state" / f"live_state_{args.date}.json"
        live_lines_path = dest_api_root / "live_lines" / f"live_lines_{args.date}.json"
        if not all(path.exists() for path in (recommendation_path, results_path, live_state_path, live_lines_path)):
            manifest = _run_source_app_fallback(
                source_root=source_root,
                dest_api_root=dest_api_root,
                target_date=args.date,
                existing_manifest=manifest,
            )

    _write_json(dest_api_root / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())