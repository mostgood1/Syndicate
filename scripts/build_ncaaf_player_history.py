"""NCAAF player game HISTORY (prior seasons, with opponent) for "history vs this team" on player props.

WHY (lane `intelligence-evidence-coverage`; user 2026-10-08: "build the NCAAF player history vs team
source"). The prop evidence reads `ncaaf_player_game_stats_snapshot.csv`, which holds the current and the
previous season only; a college player meets most opponents once a year (conference rivals), so "vs this
team" needs the seasons before that. The snapshot is NOT extended in place: the prop provider indexes the
whole snapshot on every board build, and two more full seasons would roughly triple that on the
refresh-worker. This is a separate, compact file instead, read only for the vs-opponent split:

    ncaaf_source/source_artifacts/data/processed/player_game_stats/ncaaf_player_game_history.csv
        = the snapshot's columns + `opponent`, regular season, for players who appear in the snapshot's
          newest season (the only ones who can carry a prop).

Uses the snapshot's own CFBD client and row builder (`CfbdClient.fetch_player_game_stats`,
`build_ncaaf_player_game_stats_rows`). Needs CFBD_API_KEY. INCREMENTAL: a (season, week) already in the
file is not re-fetched (`--force` re-fetches). Model inputs are untouched: `prop_model.resolve_history_season`
and `player_stats` read the snapshot, never this file.

    python scripts/build_ncaaf_player_history.py                       # the two seasons before the snapshot's
    python scripts/build_ncaaf_player_history.py --seasons 2023,2024
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MAX_WEEK = 16


def history_path() -> Path:
    from syndicate.features.ncaaf.sources import player_game_stats_snapshot_path

    return player_game_stats_snapshot_path().with_name("ncaaf_player_game_history.csv")


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def current_players(snapshot_rows: Iterable[dict[str, str]]) -> tuple[int | None, set[str]]:
    """(newest season in the snapshot, player ids that played in it)."""
    rows = list(snapshot_rows)
    seasons = [int(r["season"]) for r in rows if str(r.get("season") or "").isdigit()]
    if not seasons:
        return None, set()
    newest = max(seasons)
    return newest, {str(r.get("player_id") or "") for r in rows if str(r.get("season")) == str(newest)}


def with_opponent(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(rows)
    teams: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        teams[str(r.get("game_id") or "")].add(str(r.get("team") or ""))
    out = []
    for r in rows:
        others = teams[str(r.get("game_id") or "")] - {str(r.get("team") or "")}
        out.append(dict(r, opponent=next(iter(sorted(others)), "") if len(others) == 1 else ""))
    return out


def run(seasons: list[int] | None = None, *, force: bool = False, client: Any = None, pause: float = 0.5) -> dict[str, Any]:
    from syndicate.features.ncaaf.cfbd import PLAYER_GAME_STATS_COLUMNS, CfbdClient, build_ncaaf_player_game_stats_rows
    from syndicate.features.ncaaf.sources import player_game_stats_snapshot_path

    newest, keep = current_players(_read(player_game_stats_snapshot_path()))
    if newest is None:
        raise SystemExit("snapshot has no seasons; nothing to anchor 'current players' on")
    seasons = seasons or [newest - 3, newest - 2]  # the snapshot holds `newest` and `newest - 1`
    seasons = sorted(set(seasons))
    path = history_path()
    existing = _read(path)
    have = {(r["season"], r["week"]) for r in existing}
    rows: list[dict[str, Any]] = [r for r in existing if not force or int(r["season"]) not in seasons]
    client = client or CfbdClient.from_env()
    summary: dict[str, Any] = {"seasons": seasons, "current_players": len(keep), "weeks_fetched": 0, "weeks_kept": 0, "failed": 0}
    for season in seasons:
        for week in range(1, MAX_WEEK + 1):
            if not force and (str(season), str(week)) in have:
                summary["weeks_kept"] += 1
                continue
            try:
                payload = client.fetch_player_game_stats(season=season, week=week, season_type="regular")
            except Exception as exc:  # noqa: BLE001 -- one week must not lose the rest
                summary["failed"] += 1
                print(f"[ncaaf_history] FETCH_FAILED season={season} week={week} {type(exc).__name__}", flush=True)
                continue
            built = build_ncaaf_player_game_stats_rows(season=season, week=week, games_payload=payload)
            rows.extend(r for r in with_opponent(built) if str(r.get("player_id") or "") in keep)
            summary["weeks_fetched"] += 1
            time.sleep(pause)
    columns = list(PLAYER_GAME_STATS_COLUMNS) + ["opponent"]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in sorted(rows, key=lambda r: (int(r["season"]), int(r["week"]), str(r["game_id"]), str(r["player_id"]))):
            writer.writerow({k: r.get(k, "") for k in columns})
    os.replace(tmp, path)
    summary.update(rows=len(rows), players=len({r["player_id"] for r in rows}), written=str(path))
    print("[ncaaf_history] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seasons", default=None, help="comma list; default: the two seasons before the snapshot's two")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    run([int(s) for s in args.seasons.split(",")] if args.seasons else None, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
