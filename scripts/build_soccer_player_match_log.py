"""Soccer player MATCH log: one dated row per player per league match, from ESPN match summaries.

WHY (lane `intelligence-evidence-coverage`; user 2026-10-08: "build the soccer player history source").
Player props must weigh recency and history vs the opponent, and soccer had no dated per-match player
source: `players_<season>.csv` is season rates (no dates), and the live_state player boxes the prop
evidence reads exist only since 2026-09-09. The H3 backtest found soccer NOT REACHABLE for exactly that
reason. ESPN's match-summary rosters -- the source `espn_player_stats.aggregate_season_player_stats`
already parses into season rates -- carry the per-match lines; this keeps them per match instead of
summing them away.

Writes `soccer_source/<league>/history/player_match_log_<season>.csv`:
    league, season, date (UTC kickoff day), event_id, team, opponent, side, player_id, player_name,
    position, starter, minutes, shots, shots_on_target, goals, assists
Only players who entered the match (minutes from `compute_minutes_played`; an unused substitute has no
row). League matches only (each league's own ESPN slug; cups and friendlies are other slugs).

INCREMENTAL: event_ids already in the file are never re-fetched, and the SCOREBOARD walk is bounded too:
a season that ended more than SETTLED_DAYS ago and already has a file is skipped outright, and the current
season is re-read only from RESCAN_DAYS before its newest logged match. ESPN refuses date-range scoreboard
requests, so each window costs one request per DAY: the first version re-walked every day of both seasons
for all 10 leagues and took 1,255 s on 2026-10-08 (lead in leads.md). `--full` walks everything (to pick up
a match a failed fetch missed). Atomic rewrite of the whole file.

    python scripts/build_soccer_player_match_log.py                          # every league, this + last season
    python scripts/build_soccer_player_match_log.py --league epl --seasons 2025,2026
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FIELDS = ("league", "season", "date", "event_id", "team", "opponent", "side", "player_id", "player_name",
          "position", "starter", "minutes", "shots", "shots_on_target", "goals", "assists")


def soccer_root() -> Path:
    override = str(os.environ.get("SYNDICATE_SOCCER_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / "soccer_source"


def match_rows(league: str, season: int, event: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    """The dated player lines of one finished match (players who entered only)."""
    from syndicate.features.soccer.ingestion.espn_lineups import extract_match_player_rows
    from syndicate.features.soccer.ingestion.espn_match_events import compute_minutes_played, extract_key_events

    rows = extract_match_player_rows(summary, event_id=str(event["event_id"]))
    if not rows:
        return []
    minutes = compute_minutes_played(extract_key_events(summary), rows)
    teams = {r["team"] for r in rows}
    out = []
    for r in rows:
        pid = str(r.get("player_id") or "")
        played = minutes.get(pid)
        if played is None:
            continue  # unused substitute
        others = teams - {r["team"]}
        out.append({
            "league": league, "season": season, "date": str(event.get("date") or "")[:10],
            "event_id": str(event["event_id"]), "team": r["team"], "opponent": next(iter(others), ""),
            "side": r.get("side") or "", "player_id": pid, "player_name": r.get("player_name") or "",
            "position": r.get("position") or "", "starter": int(bool(r.get("starter"))), "minutes": round(float(played), 1),
            "shots": r.get("total_shots") or 0, "shots_on_target": r.get("shots_on_target") or 0,
            "goals": r.get("total_goals") or 0, "assists": r.get("goal_assists") or 0,
        })
    return out


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (str(r["date"]), str(r["event_id"]), str(r["team"]), str(r["player_name"]))):
            writer.writerow({k: row.get(k, "") for k in FIELDS})
    os.replace(tmp, path)


SETTLED_DAYS = 7    # a season whose last day is this far back gains no matches
RESCAN_DAYS = 3     # the current season is re-read from this many days before its newest logged match
WINDOW_DAYS = 15


def windows_to_scan(league: str, season: int, existing: list[dict[str, str]], *, today: dt.date, full: bool) -> list[str]:
    """`YYYYMMDD-YYYYMMDD` windows this run must walk; [] when the season is settled and logged."""
    from syndicate.features.soccer.features.schedule import season_date_range

    start, end = season_date_range(league, season)
    end = min(end, today)
    if end < start:
        return []
    if not full and existing:
        if end <= today - dt.timedelta(days=SETTLED_DAYS) and season_date_range(league, season)[1] < today:
            return []
        newest = max((str(r.get("date") or "") for r in existing), default="")
        if newest:
            start = max(start, dt.date.fromisoformat(newest) - dt.timedelta(days=RESCAN_DAYS))
    windows, cursor = [], start
    while cursor <= end:
        window_end = min(cursor + dt.timedelta(days=WINDOW_DAYS - 1), end)
        windows.append(f"{cursor:%Y%m%d}-{window_end:%Y%m%d}")
        cursor = window_end + dt.timedelta(days=1)
    return windows


def run_league(league: str, season: int, *, pause: float = 0.25, full: bool = False, today: dt.date | None = None) -> dict[str, Any]:
    from syndicate.features.soccer.ingestion.espn_lineups import fetch_completed_events, fetch_match_summary

    path = soccer_root() / league / "history" / f"player_match_log_{season}.csv"
    existing = _read(path)
    have = {r["event_id"] for r in existing}
    windows = windows_to_scan(league, season, existing, today=today or dt.date.today(), full=full)
    summary = {"league": league, "season": season, "windows": len(windows), "kept_events": len(have),
               "new_events": 0, "failed": 0, "rows": len(existing)}
    if not windows:
        why = "settled and logged -- skipped" if existing else "season not started"
        print("[soccer_log] " + " ".join(f"{k}={v}" for k, v in summary.items()) + f" ({why})", flush=True)
        return summary
    events = fetch_completed_events(league, date_windows=windows)
    rows: list[dict[str, Any]] = list(existing)
    for event in events:
        if str(event["event_id"]) in have:
            continue
        try:
            payload = fetch_match_summary(league, str(event["event_id"]))
        except Exception as exc:  # noqa: BLE001 -- one bad summary must not lose the rest
            summary["failed"] += 1
            print(f"[soccer_log] SUMMARY_FAILED league={league} event={event['event_id']} {type(exc).__name__}", flush=True)
            continue
        got = match_rows(league, season, event, payload)
        if got:
            rows.extend(got)
            summary["new_events"] += 1
        time.sleep(pause)
    if summary["new_events"] or not path.is_file():
        _write(path, rows)
    summary["rows"] = len(rows)
    summary["events_total"] = len({r["event_id"] for r in rows})
    print("[soccer_log] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    from syndicate.features.soccer.features.schedule import default_season
    from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--league", action="append", help="default: every league with an ESPN slug")
    parser.add_argument("--seasons", default=None, help="comma list; default: this season and last")
    parser.add_argument("--full", action="store_true", help="walk every day of each season (recover a missed match)")
    args = parser.parse_args(argv)
    for league in args.league or sorted(LEAGUE_ESPN_SLUGS):
        current = default_season(league)
        seasons = [int(s) for s in args.seasons.split(",")] if args.seasons else [current - 1, current]
        for season in seasons:
            try:
                run_league(league, season, full=args.full)
            except Exception as exc:  # noqa: BLE001 -- one league's outage must not stop the others
                print(f"[soccer_log] LEAGUE_FAILED league={league} season={season} {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
