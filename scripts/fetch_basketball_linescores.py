"""Daily NBA / WNBA quarter scores for the games-rail line score.

User decision 2026-10-13 (lane games-rail-full-detail): keep the daily ESPN
fetch the line score needs. The card used to read `pbp_espn_<date>.csv`, which
the `update-pbp-espn-history` bootstrap step wrote -- retired in 2708dbe3 with
its only other reader. That step fetched one ESPN summary PER GAME to rebuild
full play-by-play; the line score needs only each team's points per period,
which ESPN's scoreboard carries for every completed game in ONE call per league
(`competitors[].linescores[].value`).

Writes `<SYNDICATE_DATA_ROOT>/<league>_source/data/processed/linescores_<date>.json`:
    {"date": ..., "fetched_at": ..., "games": {<espn event id>: {"away": tri,
     "home": tri, "away_periods": [...], "home_periods": [...]}}}
Completed games only. Read by `syndicate/features/shared/game_chip_linescore.py`.

Usage: python scripts/fetch_basketball_linescores.py [--date YYYY-MM-DD] [--leagues nba,wnba]
Default date: yesterday, US Central.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/{league}/scoreboard?dates={compact}"


def _data_root() -> Path:
    env = os.environ.get("SYNDICATE_DATA_ROOT")
    return Path(env) if env else ROOT / "data"


def _num(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_scoreboard(payload: dict) -> dict[str, dict]:
    games: dict[str, dict] = {}
    for event in payload.get("events") or []:
        status = ((event.get("status") or {}).get("type") or {})
        if not status.get("completed"):
            continue
        comp = (event.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, dict)}
        home, away = sides.get("home") or {}, sides.get("away") or {}
        hp = [_num(x.get("value")) for x in home.get("linescores") or []]
        ap = [_num(x.get("value")) for x in away.get("linescores") or []]
        if not hp or not ap or None in hp or None in ap:
            continue
        games[str(event.get("id"))] = {
            "away": (away.get("team") or {}).get("abbreviation"),
            "home": (home.get("team") or {}).get("abbreviation"),
            "away_periods": ap,
            "home_periods": hp,
        }
    return games


def fetch(league: str, date: str) -> dict:
    # No custom User-Agent: ESPN 403s some UA strings (see wnba/cards._public_scoreboard_live_state_payload).
    with urllib.request.urlopen(URL.format(league=league, compact=date.replace("-", "")), timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--leagues", default="nba,wnba")
    args = parser.parse_args(argv)
    from syndicate.features.shared.timezone import CENTRAL_TIMEZONE

    date = args.date or (datetime.now(CENTRAL_TIMEZONE).date() - timedelta(days=1)).isoformat()
    rc = 0
    for league in [x.strip() for x in args.leagues.split(",") if x.strip()]:
        try:
            games = parse_scoreboard(fetch(league, date))
        except Exception as exc:  # noqa: BLE001 -- one league failing must not cost the other
            print(f"[basketball_linescores] FETCH_FAILED league={league} date={date} {type(exc).__name__}: {exc}", flush=True)
            rc = 1
            continue
        out = _data_root() / f"{league}_source" / "data" / "processed" / f"linescores_{date}.json"
        if not games and out.exists():
            print(f"[basketball_linescores] league={league} date={date} games=0 (kept existing file)", flush=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"date": date, "fetched_at": datetime.now(timezone.utc).isoformat(), "games": games}), encoding="utf-8")
        tmp.replace(out)
        print(f"[basketball_linescores] league={league} date={date} games={len(games)} -> {out}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
