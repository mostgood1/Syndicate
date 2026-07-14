from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.odds_control_plane import odds_history_paths_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_roots_for_sport
from syndicate.features.shared.odds_control_plane import shared_odds_history_root
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import write_text_file


_SPORTS = ("mlb", "nhl", "wnba", "nba", "ncaab", "nfl", "ncaaf")


def _old_combined_paths(sport_slug: str) -> list[Path]:
    slug = sport_slug.strip().lower()
    sport_root = odds_history_roots_for_sport(slug)[-1]
    return [
        shared_odds_history_root() / slug / "odds_history.json",
        sport_root / "artifacts" / slug / "odds_history.json",
        sport_root / "tracking" / "odds_history.json",
    ]


def _load_combined_payload(sport_slug: str) -> dict[str, Any] | None:
    for path in _old_combined_paths(sport_slug):
        payload = read_json_file(path)
        if isinstance(payload, dict):
            return payload
    return None


def _market_states(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    markets = payload.get("markets")
    if isinstance(markets, dict) and markets:
        return {str(key): value for key, value in markets.items() if isinstance(value, dict)}
    states: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if key in {"sport", "date", "updated_at", "history_limit", "markets"}:
            continue
        if isinstance(value, dict) and isinstance(value.get("history"), list):
            states[str(key)] = value
    return states


def _recompute_market_state(entries: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(entries, key=lambda item: str(item.get("captured_at") or item.get("timestamp") or ""))
    latest = ordered[-1] if ordered else {}
    return {
        "history": ordered,
        "last_line": latest.get("current_line"),
        "previous_line": latest.get("previous_line"),
        "last_odds": latest.get("last_odds"),
        "last_snapshot_ts": latest.get("snapshot_ts"),
        "delta": latest.get("delta"),
        "delta_line": latest.get("delta_line"),
        "percent_change": latest.get("percent_change"),
        "movement": latest.get("movement"),
        "last_updated": latest.get("captured_at") or latest.get("timestamp"),
        "last_source_path": latest.get("last_source_path"),
    }


def migrate_sport(sport_slug: str, *, dry_run: bool = False) -> dict[str, Any]:
    slug = sport_slug.strip().lower()
    payload = _load_combined_payload(slug)
    if not isinstance(payload, dict):
        return {"sport": slug, "ok": True, "skipped": True, "reason": "no_combined_payload", "shards": {}}

    markets = _market_states(payload)
    shard_entries: dict[str, dict[str, list[dict[str, Any]]]] = {}
    unassigned_entries = 0
    for market_key, market_state in markets.items():
        history = market_state.get("history")
        if not isinstance(history, list):
            continue
        for entry in history:
            if not isinstance(entry, dict):
                continue
            shard_key = str(entry.get("date") or "").strip()
            if not shard_key:
                unassigned_entries += 1
                continue
            shard_entries.setdefault(shard_key, {}).setdefault(market_key, []).append(entry)

    shard_results: dict[str, dict[str, Any]] = {}
    for shard_key, shard_markets_entries in sorted(shard_entries.items()):
        shard_markets = {
            market_key: _recompute_market_state(entries)
            for market_key, entries in shard_markets_entries.items()
        }
        shard_payload = {
            "schema_version": 1,
            "sport": slug,
            "shard_key": shard_key,
            "markets": shard_markets,
        }
        shard_payload.update(shard_markets)
        paths = odds_history_paths_for_sport(slug, shard_key)
        if not dry_run:
            payload_text = json.dumps(shard_payload, indent=2, default=str)
            for path in paths:
                write_text_file(path, payload_text)
        shard_results[shard_key] = {
            "markets": len(shard_markets),
            "entries": sum(len(state["history"]) for state in shard_markets.values()),
            "paths": [str(path) for path in paths],
        }

    return {
        "sport": slug,
        "ok": True,
        "skipped": False,
        "shard_count": len(shard_results),
        "unassigned_entries": unassigned_entries,
        "shards": shard_results,
    }


def cleanup_old_files(sport_slug: str) -> list[str]:
    removed: list[str] = []
    for path in _old_combined_paths(sport_slug):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Split each sport's combined odds_history.json into per-date/per-week shard files.")
    parser.add_argument("--sport", action="append", dest="sports", choices=_SPORTS, help="Sport slug to migrate (repeatable).")
    parser.add_argument("--all", action="store_true", help="Migrate all supported sports.")
    parser.add_argument("--dry-run", action="store_true", help="Report shard counts without writing any files.")
    parser.add_argument("--cleanup", action="store_true", help="After migrating, delete the old combined odds_history.json files. Run only after verifying shard output looks correct.")
    args = parser.parse_args()

    sports = list(dict.fromkeys(args.sports or []))
    if args.all:
        sports = list(_SPORTS)
    if not sports:
        parser.error("Specify --sport <slug> (repeatable) or --all.")

    for sport_slug in sports:
        result = migrate_sport(sport_slug, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
        if args.cleanup and not args.dry_run and not result.get("skipped"):
            removed = cleanup_old_files(sport_slug)
            print(json.dumps({"sport": sport_slug, "cleanup_removed": removed}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
