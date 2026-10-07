"""Backfill one league-season of corner counts from ESPN into ``<league>/history/matches_<season>.csv``.

WHY (lane ``soccer-mls-corner-history-backfill``, 2026-10-07). ``corners_estimator.estimate_corners``
declines below ``MIN_LEAGUE_ROWS`` (30) and the match then publishes the possession sim's corners
(``corners_basis=sim``). Its rows come from ``history/matches_*.csv`` (football-data, which has NO MLS)
plus this season's ``api/live_state/live_state_*.json`` box scores. On Render, MLS cleared the floor from a
season of live_state files on Render's disk. Those never reached git, and the local fleet started
2026-09-30 with 3 MLS corner rows, so every fleet MLS freeze since then is ``sim`` (33 of 33, against 0 of 99
for the other leagues).

The rows come from the SAME ESPN summary payload and the SAME ``extract_team_box`` the live poller uses, so
team names match the live_state rows and the fixtures. Only corners are filled: the only production reader
of an MLS ``matches_*.csv`` is the corners estimator (MLS ratings come from ASA in ``build_soccer_artifacts``,
and the history seeders/fetchers skip MLS).

``--end`` MUST precede the first live_state file on the target disk: ``history_corner_rows`` and
``live_state_corner_rows`` are not de-duplicated against each other, so an overlapping match would count twice.

    py -3 scripts/soccer_season_audit/backfill_mls_corner_history.py --league mls --start 2026-02-15 \
        --end 2026-09-29 --cache C:/tmp/mls-corner-backfill --out C:/tmp/mls-corner-backfill/matches_2026.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from syndicate.features.soccer.ingestion.espn_lineups import fetch_espn_scoreboard, fetch_match_summary  # noqa: E402
from syndicate.features.soccer.ingestion.espn_match_box import extract_team_box  # noqa: E402

COLUMNS = ("league", "season", "match_id", "date", "home_team", "away_team", "home_corners", "away_corners")


def _finished_events(league: str, day: date) -> list[str]:
    # Bare YYYYMMDD: ESPN refuses range forms (espn_lineups._scoreboard_payloads, measured 2026-09-16).
    payload = fetch_espn_scoreboard(league, date_range=day.strftime("%Y%m%d"))
    out = []
    for event in payload.get("events") or []:
        state = (((event.get("status") or {}).get("type") or {}).get("state")) or ""
        if state == "post" and event.get("id"):
            out.append(str(event["id"]))
    return out


def _summary(league: str, event_id: str, cache: Path) -> dict:
    path = cache / f"{league}__{event_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    summary = fetch_match_summary(league, event_id)
    path.write_text(json.dumps(summary), encoding="utf-8")
    time.sleep(0.2)
    return summary


def _as_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--league", default="mls")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    rows: dict[str, dict] = {}
    tally = {"days": 0, "events_post": 0, "rows": 0, "no_corners": 0, "fetch_failed": 0}
    day = start
    while day <= end:
        tally["days"] += 1
        try:
            event_ids = _finished_events(args.league, day)
        except Exception as exc:  # noqa: BLE001 -- counted and reported, never silent
            print(f"SCOREBOARD_FAILED {day} {type(exc).__name__}: {exc}", flush=True)
            tally["fetch_failed"] += 1
            event_ids = []
        for event_id in event_ids:
            if event_id in rows:
                continue
            tally["events_post"] += 1
            try:
                summary = _summary(args.league, event_id, cache)
            except Exception as exc:  # noqa: BLE001
                print(f"SUMMARY_FAILED {event_id} {type(exc).__name__}: {exc}", flush=True)
                tally["fetch_failed"] += 1
                continue
            box = extract_team_box(summary)
            home, away = box.get("home") or {}, box.get("away") or {}
            hc, ac = _as_int((home.get("stats") or {}).get("Corners")), _as_int((away.get("stats") or {}).get("Corners"))
            if hc is None or ac is None or not home.get("team") or not away.get("team"):
                tally["no_corners"] += 1
                continue
            # The usa.1 scoreboard carries the All-Star game (2026-07-29, MLS All-Stars v Liga MX All-Stars):
            # not a league fixture, and two "teams" the estimator would otherwise rate.
            if "all-star" in f"{home['team']} {away['team']}".casefold():
                tally["exhibition_skipped"] = tally.get("exhibition_skipped", 0) + 1
                continue
            rows[event_id] = {"league": args.league, "season": start.year, "match_id": event_id,
                              "date": day.isoformat(), "home_team": home["team"], "away_team": away["team"],
                              "home_corners": hc, "away_corners": ac}
        day += timedelta(days=1)

    tally["rows"] = len(rows)
    ordered = sorted(rows.values(), key=lambda r: (r["date"], r["match_id"]))
    with open(args.out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)
    tally["first"] = ordered[0]["date"] if ordered else None
    tally["last"] = ordered[-1]["date"] if ordered else None
    print(json.dumps(tally), flush=True)
    return 0 if ordered else 1


if __name__ == "__main__":
    sys.exit(main())
