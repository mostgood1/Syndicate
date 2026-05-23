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

PROCESSED_FILES = (
    "predictions_{date}.csv",
    "predictions_sim_{date}.csv",
    "recommendations_{date}.csv",
    "recommendations_sim_{date}.csv",
    "reconciliations_log.csv",
    "props_reconciliations_log.csv",
    "recon_games_{date}.csv",
    "recon_props_{date}.csv",
    "props_boxscores_sim_{date}.csv",
    "props_boxscores_sim_hist_{date}.csv",
    "props_recommendations_{date}.csv",
)

LIVE_LENS_FILES = (
    "live_lens_projections_{date}.jsonl",
    "live_lens_signals_{date}.jsonl",
    "live_lens_tuning_override.json",
)


def _copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _copy_first_existing(*, sources: list[Path], destination: Path) -> bool:
    for source in sources:
        if _copy_if_exists(source, destination):
            return True
    return False


def _load_source_cli(source_root: Path):
    source_root = source_root.resolve()
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    importlib.invalidate_caches()
    return importlib.import_module("nhl_betting.cli")


@contextmanager
def _pushd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _materialize_artifact_bundle(*, source_root: Path, artifact_root: Path, date_str: str) -> dict[str, object]:
    processed_root = artifact_root / "data" / "processed"
    live_lens_root = artifact_root / "data" / "live_lens"
    odds_games_root = artifact_root / "data" / "odds" / "games" / f"date={date_str}"
    odds_team_root = artifact_root / "data" / "odds" / "team" / f"date={date_str}"
    props_root = artifact_root / "data" / "props" / "player_props_lines" / f"date={date_str}"

    copied: dict[str, object] = {}

    for template in PROCESSED_FILES:
        filename = template.format(date=date_str)
        source = source_root / "data" / "processed" / filename
        destination = processed_root / filename
        if _copy_if_exists(source, destination):
            copied.setdefault("processed_files", []).append(str(destination))

    for template in LIVE_LENS_FILES:
        filename = template.format(date=date_str)
        processed_destination = processed_root / filename
        live_lens_destination = live_lens_root / filename
        sources = [
            source_root / "data" / "processed" / filename,
            source_root / "data" / "processed" / "live_lens" / filename,
            source_root / "data" / "live_lens" / filename,
        ]
        if _copy_first_existing(sources=sources, destination=processed_destination):
            copied.setdefault("live_lens_processed_files", []).append(str(processed_destination))
        if _copy_first_existing(sources=sources, destination=live_lens_destination):
            copied.setdefault("live_lens_files", []).append(str(live_lens_destination))

    scoreboard_source = source_root / "data" / "odds" / "games" / f"date={date_str}" / "scoreboard.csv"
    scoreboard_destination = odds_games_root / "scoreboard.csv"
    if _copy_if_exists(scoreboard_source, scoreboard_destination):
        copied["scoreboard_path"] = str(scoreboard_destination)

    for name in ("oddsapi.csv", "oddsapi.parquet"):
        team_source = source_root / "data" / "odds" / "team" / f"date={date_str}" / name
        team_destination = odds_team_root / name
        if _copy_if_exists(team_source, team_destination):
            copied.setdefault("team_odds_paths", []).append(str(team_destination))

        props_source = source_root / "data" / "props" / "player_props_lines" / f"date={date_str}" / name
        props_destination = props_root / name
        if _copy_if_exists(props_source, props_destination):
            copied.setdefault("props_line_paths", []).append(str(props_destination))

    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NHL OddsAPI snapshots through a Syndicate-owned runner.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--artifact-root", required=False, default=str(REPO_ROOT / "data" / "nhl_source" / "source_artifacts"))
    parser.add_argument("--team-markets", default="h2h,spreads,totals")
    parser.add_argument("--props-source", default="oddsapi")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    artifact_root = Path(args.artifact_root).resolve()
    cli_module = _load_source_cli(source_root)

    try:
        with _pushd(source_root):
            cli_module.team_odds_collect(date=args.date, markets=str(args.team_markets or "h2h,spreads,totals"))
            cli_module.props_collect(date=args.date, source=str(args.props_source or "oddsapi"))
    except Exception as exc:
        print(json.dumps({"ok": False, "date": args.date, "error": str(exc)}))
        return 1

    copied = _materialize_artifact_bundle(source_root=source_root, artifact_root=artifact_root, date_str=args.date)
    print(
        json.dumps(
            {
                "ok": True,
                "date": args.date,
                "artifact_bundle_root": str(artifact_root),
                "artifact_bundle_files": copied,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())