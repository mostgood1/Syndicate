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

INCREMENTAL: event_ids already in the file are never re-fetched, so a daily run costs one summary request
per newly finished match plus the scoreboard windows. Atomic rewrite of the whole file.

    python scripts/build_soccer_player_match_log.py                          # every league, this + last season
    python scripts/build_soccer_player_match_log.py --league epl --seasons 2025,2026
"""

from __future__ import annotations

import argparse
import csv
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


def run_league(league: str, season: int, *, pause: float = 0.25) -> dict[str, Any]:
    from syndicate.features.soccer.ingestion.espn_lineups import fetch_completed_events, fetch_match_summary
    from syndicate.features.soccer.ingestion.espn_player_stats import season_date_windows

    path = soccer_root() / league / "history" / f"player_match_log_{season}.csv"
    existing = _read(path)
    have = {r["event_id"] for r in existing}
    windows = season_date_windows(league, season)
    summary = {"league": league, "season": season, "windows": len(windows), "kept_events": len(have),
               "new_events": 0, "failed": 0, "rows": len(existing)}
    if not windows:
        print("[soccer_log] " + " ".join(f"{k}={v}" for k, v in summary.items()) + " (season not started)", flush=True)
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
    args = parser.parse_args(argv)
    for league in args.league or sorted(LEAGUE_ESPN_SLUGS):
        current = default_season(league)
        seasons = [int(s) for s in args.seasons.split(",")] if args.seasons else [current - 1, current]
        for season in seasons:
            try:
                run_league(league, season)
            except Exception as exc:  # noqa: BLE001 -- one league's outage must not stop the others
                print(f"[soccer_log] LEAGUE_FAILED league={league} season={season} {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
