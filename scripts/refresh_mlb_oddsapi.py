from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

FILE_TEMPLATES = (
    ("data/daily/daily_summary_{date_slug}.json", "data/daily/daily_summary_{date_slug}.json"),
    ("data/daily/daily_summary_{date_slug}_profile_bundle.json", "data/daily/daily_summary_{date_slug}_profile_bundle.json"),
    ("data/daily/daily_summary_{date_slug}_locked_policy.json", "data/daily/daily_summary_{date_slug}_locked_policy.json"),
    ("data/daily/daily_summary_{date_slug}_hr_targets.json", "data/daily/daily_summary_{date_slug}_hr_targets.json"),
    ("data/daily/daily_summary_{date_slug}_rfi_targets.json", "data/daily/daily_summary_{date_slug}_rfi_targets.json"),
    ("data/daily/ladders/daily_ladders_{date_slug}.json", "data/daily/ladders/daily_ladders_{date_slug}.json"),
    ("data/daily/top_props/daily_top_props_{date_slug}.json", "data/daily/top_props/daily_top_props_{date_slug}.json"),
    ("data/daily/ops/daily_ops_{date_slug}.json", "data/daily/ops/daily_ops_{date_slug}.json"),
    ("data/daily/season_frontend/season_betting_day_{date_slug}.json", "data/daily/season_frontend/season_betting_day_{date_slug}.json"),
    ("data/live_lens/live_lens_{date_slug}.jsonl", "data/live_lens/live_lens_{date_slug}.jsonl"),
    ("data/live_lens/live_lens_report_{date_slug}.json", "data/live_lens/live_lens_report_{date_slug}.json"),
    ("data/live_lens/prop_registry/live_prop_registry_{date_slug}.json", "data/live_lens/prop_registry/live_prop_registry_{date_slug}.json"),
    ("data/live_lens/prop_registry/live_prop_registry_{date_slug}.jsonl", "data/live_lens/prop_registry/live_prop_registry_{date_slug}.jsonl"),
    ("data/live_lens/prop_registry/live_prop_observations_{date_slug}.jsonl", "data/live_lens/prop_registry/live_prop_observations_{date_slug}.jsonl"),
    ("data/tuning/live_prop_ranking/default.json", "data/tuning/live_prop_ranking/default.json"),
    ("sim_engine/live_prop_ranking.py", "sim_engine/live_prop_ranking.py"),
)

DIRECTORY_TEMPLATES = (
    ("data/daily/snapshots/{date_str}", "data/daily/snapshots/{date_str}"),
    ("data/daily/sims/{date_str}", "data/daily/sims/{date_str}"),
    ("data/market/oddsapi/refresh_history/{date_slug}", "data/market/oddsapi/refresh_history/{date_slug}"),
    ("data/raw/statsapi/feed_live/{season}/{date_str}", "data/raw/statsapi/feed_live/{season}/{date_str}"),
)

SEASON_MANIFEST_FILES = (
    "season_betting_cards_retuned_manifest.json",
    "season_betting_cards_retuned_hrr_manifest.json",
)


def _copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _copy_tree_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_dir():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return True


def _load_source_modules(source_root: Path):
    source_root = source_root.resolve()
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    importlib.invalidate_caches()
    odds_module = importlib.import_module("tools.oddsapi.fetch_daily_oddsapi_markets")
    web_module = importlib.import_module("tools.web.flask_frontend")
    return odds_module, web_module


@contextmanager
def _pushd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _refresh_source_artifacts(*, odds_module, web_module, source_root: Path, date_str: str, regions: str, overwrite: bool) -> dict[str, object]:
    recorded_at = web_module._local_now()
    frozen_pregame = web_module._freeze_oddsapi_pregame_markets(date_str)
    result = odds_module.fetch_and_write_live_odds_for_date(
        date_str,
        out_dir=source_root / "data" / "market" / "oddsapi",
        overwrite=overwrite,
        regions=regions,
    )

    snapshot_dir = Path(web_module._daily_snapshot_dir(date_str))
    copied: dict[str, str] = {}
    web_module._ensure_dir(snapshot_dir)
    for key in ("game_lines_path", "pitcher_props_path", "hitter_props_path"):
        raw_source_path = result.get(key)
        source_path = Path(str(raw_source_path)).resolve() if raw_source_path else None
        if not source_path or not source_path.exists() or not source_path.is_file():
            continue
        destination = snapshot_dir / source_path.name
        shutil.copy2(source_path, destination)
        copied[source_path.name] = str(destination)

    archived = web_module._archive_oddsapi_refresh_outputs(date_str, result, recorded_at=recorded_at)
    meta = {
        "recordedAt": web_module._local_timestamp_text(recorded_at),
        "date": str(date_str),
        "overwrite": bool(overwrite),
        "frozenPregame": frozen_pregame,
        "result": result,
        "copied": copied,
        "archived": archived,
    }
    web_module._write_json_file(Path(web_module._cron_meta_dir()) / "latest_refresh_oddsapi.json", meta)
    live_lens = web_module._persist_live_lens_tick(date_str, trigger="syndicate_refresh", refresh_markets=False)
    return {
        "market_refresh": {
            "ok": True,
            "date": str(date_str),
            "result": result,
            "copied": copied,
            "archived": archived,
        },
        "live_lens": live_lens,
    }


def _materialize_artifact_bundle(*, source_root: Path, artifact_root: Path, date_str: str) -> dict[str, object]:
    date_slug = str(date_str).replace("-", "_")
    season = str(date_str).split("-", 1)[0]
    season_payload_slug = date_slug
    prefix = f"{season}_"
    if season_payload_slug.startswith(prefix):
        season_payload_slug = season_payload_slug[len(prefix) :]

    copied: dict[str, object] = {}
    format_values = {
        "date_str": date_str,
        "date_slug": date_slug,
        "season": season,
        "season_payload_slug": season_payload_slug,
    }

    for source_template, destination_template in FILE_TEMPLATES:
        source = source_root / Path(source_template.format(**format_values))
        destination = artifact_root / Path(destination_template.format(**format_values))
        if _copy_if_exists(source, destination):
            copied.setdefault("files", []).append(str(destination))

    for source_template, destination_template in DIRECTORY_TEMPLATES:
        source = source_root / Path(source_template.format(**format_values))
        destination = artifact_root / Path(destination_template.format(**format_values))
        if _copy_tree_if_exists(source, destination):
            copied.setdefault("directories", []).append(str(destination))

    season_eval_root = source_root / "data" / "eval" / "seasons" / season
    season_manifest = season_eval_root / "season_eval_manifest.json"
    if _copy_if_exists(season_manifest, artifact_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json"):
        copied.setdefault("files", []).append(str(artifact_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json"))

    for name in SEASON_MANIFEST_FILES:
        source = season_eval_root / name
        destination = artifact_root / "data" / "eval" / "seasons" / season / name
        if _copy_if_exists(source, destination):
            copied.setdefault("files", []).append(str(destination))

    for parent in season_eval_root.glob("betting_day_payloads*"):
        if not parent.is_dir():
            continue
        pattern = f"season_betting_day_{season}_{season_payload_slug}*.json"
        for source in parent.glob(pattern):
            destination = artifact_root / "data" / "eval" / "seasons" / season / parent.name / source.name
            if _copy_if_exists(source, destination):
                copied.setdefault("files", []).append(str(destination))

    for parent in season_eval_root.glob("betting_day_recaps*"):
        if not parent.is_dir():
            continue
        pattern = f"season_betting_day_{season}_{season_payload_slug}*.json"
        for source in parent.glob(pattern):
            destination = artifact_root / "data" / "eval" / "seasons" / season / parent.name / source.name
            if _copy_if_exists(source, destination):
                copied.setdefault("files", []).append(str(destination))

    live_lens_recap = source_root / "data" / "live_lens" / "recaps" / f"live_lens_daily_recap_{date_slug}.json"
    recap_destination = artifact_root / "data" / "live_lens" / "recaps" / f"live_lens_daily_recap_{date_slug}.json"
    if _copy_if_exists(live_lens_recap, recap_destination):
        copied.setdefault("files", []).append(str(recap_destination))

    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh MLB OddsAPI snapshots through a Syndicate-owned runner.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--artifact-root", required=False, default=str(REPO_ROOT / "data" / "mlb_source" / "source_artifacts"))
    parser.add_argument("--regions", default="us")
    parser.add_argument("--overwrite", choices=("on", "off"), default="on")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    artifact_root = Path(args.artifact_root).resolve()
    odds_module, web_module = _load_source_modules(source_root)

    try:
        with _pushd(source_root):
            refresh_payload = _refresh_source_artifacts(
                odds_module=odds_module,
                web_module=web_module,
                source_root=source_root,
                date_str=str(args.date),
                regions=str(args.regions or "us"),
                overwrite=str(args.overwrite) == "on",
            )
    except Exception as exc:
        print(json.dumps({"ok": False, "date": args.date, "error": str(exc)}))
        return 1

    copied = _materialize_artifact_bundle(source_root=source_root, artifact_root=artifact_root, date_str=str(args.date))
    print(
        json.dumps(
            {
                "ok": True,
                "date": args.date,
                "artifact_bundle_root": str(artifact_root),
                "refresh": refresh_payload,
                "artifact_bundle_files": copied,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())