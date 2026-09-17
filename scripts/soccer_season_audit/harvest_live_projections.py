# -*- coding: utf-8 -*-
"""Harvest soccer LIVE projection snapshots into an append-only cache, so H32 has evidence to grade.

Lane `soccer-live-corners-stage2`. H32 (`.syndicate/log/2026-09-17.md` ~15:05 CT) grades the published live
corners against the sim's kept values on production snapshots, per match, in the 20-40' / 40-60' / 60-80'
buckets.

WHY THIS EXISTS AT ALL, AND WHY IT IS NOT A DAILY JOB. `live_state_<date>.json` carries only the matches
IN PLAY at the tick that wrote it. Measured 2026-09-17 22:01:52Z: la_liga's file for a date with two
completed matches had `games: []` and only `match_box` finals -- the projections were gone about 45 minutes
after full time, not after the family's 8-day retention. A once-a-day harvest would therefore capture
NOTHING. This has to run while matches are in play.

WHAT IT DOES. Pulls the served `live_state` for the given dates, and appends one row per (league, event,
`generated_at`) it has not already stored. Re-running is safe and cheap: same tick, same key, no duplicate.

    py -3 scripts/soccer_season_audit/harvest_live_projections.py --out <dir> [--dates 2026-09-18,...]
        [--env-root <checkout with .env>]

Rows are JSONL under `<out>/live_projections_<date>.jsonl`, one per snapshot:
    league, event_id, generated_at, home_team, away_team, status_display_clock, half, clock_remaining,
    home_corners_so_far, away_corners_so_far, score_home, score_away,
    corners_basis, projected_total_corners, sim_projected_total_corners, live_corners (the audit),
    projected_final_total (the goals arm, untouched by the corners change)

A durable fix would have the poller append this itself, where the code already runs, instead of depending
on an external scheduler; that is written up as a proposal rather than built here.
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]

# Mirrors `syndicate/features/soccer/features/live_projection_history.HISTORY_KEY`. Spelled out rather than
# imported so this script runs from a bare checkout of `scripts/` with no package import path.
HISTORY_KEY = "projection_history"

FIELDS_FROM_GAME = ("home_team", "away_team", "status_display_clock", "half", "clock_remaining",
                    "score_home", "score_away", "home_corners_so_far", "away_corners_so_far",
                    # Shots as well, matching the artifact's own history rows. `*_shots_on_target_so_far` is a
                    # commentary-derived LOWER BOUND on ESPN's figure (exact on 39 of 48 team-matches, short on
                    # 9, never over), not the box score's number.
                    "home_shots_so_far", "away_shots_so_far",
                    "home_shots_on_target_so_far", "away_shots_on_target_so_far")
FIELDS_FROM_PROJECTION = ("corners_basis", "projected_total_corners", "projected_home_corners",
                          "projected_away_corners", "sim_projected_total_corners",
                          "sim_projected_home_corners", "sim_projected_away_corners", "projected_final_total")


def snapshot_rows(payload: dict) -> list[dict]:
    """One row per in-play game in a live_state payload. Pure: no network, no disk."""
    league = payload.get("league")
    generated_at = payload.get("generated_at")
    rows = []
    for event_id, game in (payload.get("games") or {}).items():
        if not isinstance(game, dict):
            continue
        projection = game.get("projection") or {}
        row = {"league": league, "event_id": str(event_id), "generated_at": generated_at}
        row.update({key: game.get(key) for key in FIELDS_FROM_GAME})
        row.update({key: projection.get(key) for key in FIELDS_FROM_PROJECTION})
        row["live_corners"] = game.get("live_corners")
        rows.append(row)
    return rows


def history_rows(payload: dict) -> list[dict]:
    """Rows from the artifact's OWN per-tick history (`projection_history`), which the poller has carried
    since 2026-09-17. This is why the harvest no longer has to arrive within the hour: every tick is kept
    inside the artifact, so a puller only has to beat the family's 8-day retention.

    A history row is a snapshot row minus the team names, and its key is built the same way, so a date
    pulled both ways de-duplicates instead of double-counting the tick that is in both.
    """
    league = payload.get("league")
    rows = []
    for event_id, entries in (payload.get(HISTORY_KEY) or {}).items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            row = {"league": league, "event_id": str(event_id), "source": HISTORY_KEY}
            row.update(entry)
            rows.append(row)
    return rows


def snapshot_key(row: dict) -> str:
    return f"{row.get('league')}|{row.get('event_id')}|{row.get('generated_at')}"


def existing_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                keys.add(snapshot_key(json.loads(line)))
            except Exception:  # noqa: BLE001 -- a half-written last line must not lose the file
                continue
    return keys


def append_rows(path: Path, rows: list[dict]) -> int:
    """Append only rows whose (league, event, generated_at) is new. Returns how many were written.

    De-duplicates WITHIN the batch as well as against the file: one tick appears in both the live `games`
    block and the artifact's own `projection_history`, so a batch carrying both would otherwise store it
    twice and inflate every count H32 reads off this cache.
    """
    known = existing_keys(path)
    fresh = []
    for row in rows:
        key = snapshot_key(row)
        if key in known:
            continue
        known.add(key)
        fresh.append(row)
    if not fresh:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        for row in fresh:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(fresh)


def default_dates() -> list[str]:
    """Today and yesterday in UTC: a late kickoff's date rolls over mid-match."""
    now = datetime.now(timezone.utc)
    return [(now - timedelta(days=1)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")]


def harvest(out_dir: Path, dates: list[str], env_root: Path | None = None) -> dict:
    sys.path.insert(0, str(CHECKOUT / "scripts"))
    import fetch_prod_artifacts_paced as prod  # noqa: E402

    if env_root is not None:
        prod.REPO_ROOT = Path(env_root)
    token = prod.admin_token()
    tally: dict = {"read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dates": {}}
    for date in dates:
        arts = prod.export(prod.DEFAULT_BASE, token,
                           {"pattern": f"soccer_source/*/api/live_state/live_state_{date}.json"}, 900).get("artifacts") or {}
        rows: list[dict] = []
        history_seen = 0
        for body in arts.values():
            payload = body if isinstance(body, dict) else json.loads(body)
            rows.extend(snapshot_rows(payload))
            from_history = history_rows(payload)
            history_seen += len(from_history)
            rows.extend(from_history)
        written = append_rows(out_dir / f"live_projections_{date}.jsonl", rows)
        bases = collections.Counter(str(r.get("corners_basis")) for r in rows)
        tally["dates"][date] = {"files": len(arts), "in_play_games": len(rows) - history_seen,
                                "history_rows_seen": history_seen, "appended": written,
                                "corners_basis": dict(bases)}
    return tally


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--dates", default=None, help="comma-separated; default yesterday,today (UTC)")
    ap.add_argument("--env-root", default=None, help="checkout holding the gitignored .env")
    args = ap.parse_args(argv)
    dates = [d.strip() for d in args.dates.split(",")] if args.dates else default_dates()
    tally = harvest(Path(args.out), dates, Path(args.env_root) if args.env_root else None)
    print(json.dumps(tally, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
