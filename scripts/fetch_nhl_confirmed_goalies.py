"""Confirmed NHL starting goalies, per date, from Daily Faceoff's public starting-goalies pages.

WHY. Production's projected starter (`ingestion/collect.py`, source `hockeysim_toi`) named the
actual starter in only 55.4% of 2,264 team-games (2025-26, 11-01..04-16; lane
`nhl-game-lines-model`), and a goalie-quality input is worthless with the wrong goalie. Daily
Faceoff publishes each game's starter with a STATUS (Confirmed / Likely / Unconfirmed ...) and the
TIMESTAMP the news was posted (`NewsCreatedAt`), so whether the starter was known BEFORE puck drop
is provable per game rather than assumed.

SOURCE. `https://www.dailyfaceoff.com/starting-goalies/<YYYY-MM-DD>` (robots.txt: `Allow: /`,
only `/api/` and `/cms/` disallowed). The page is server-rendered Next.js; the data is the
`__NEXT_DATA__` JSON, `props.pageProps.data` = one record per game. We do not call `/api/`.

POLITENESS. One request per --delay seconds (default 1.5), browser User-Agent, every page cached
under `<out>/dfo/<date>.json` (only the extracted fields are kept) and never re-fetched.

OUTPUT ROWS (`<out>/dfo/<date>.json` -> `{"date", "fetched_at", "games": [...]}`), per game:
  home_team, away_team, home_goalie, away_goalie, home_status, away_status,
  home_news_at, away_news_at (ISO UTC; when the status/news was posted), game_time (if present)

Usage:
  py -3 scripts/fetch_nhl_confirmed_goalies.py --dates 2025-10-07..2026-06-14 --out C:/tmp/nhllines
  py -3 scripts/fetch_nhl_confirmed_goalies.py --dates 2026-10-03 --out C:/tmp/nhllines --refresh
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

URL = "https://www.dailyfaceoff.com/starting-goalies/{date}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _dates(spec: str) -> List[str]:
    out: List[str] = []
    for part in spec.split(","):
        part = part.strip()
        if ".." in part:
            a, b = part.split("..")
            d, e = _date.fromisoformat(a), _date.fromisoformat(b)
            while d <= e:
                out.append(d.isoformat())
                d += timedelta(days=1)
        elif part:
            out.append(part)
    return out


def parse_page(html: str) -> Optional[List[Dict[str, Any]]]:
    """Extract the per-game starter records. None when the page carries no data block (a
    layout change must fail LOUDLY, not read as 'no games')."""
    m = _NEXT.search(html)
    if not m:
        return None
    data = ((json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}).get("data")
    if not isinstance(data, list):
        return None
    games = []
    for g in data:
        games.append({
            "home_team": g.get("homeTeamName"), "away_team": g.get("awayTeamName"),
            "home_goalie": g.get("homeGoalieName"), "away_goalie": g.get("awayGoalieName"),
            "home_status": g.get("homeNewsStrengthName"), "away_status": g.get("awayNewsStrengthName"),
            "home_news_at": g.get("homeNewsCreatedAt"), "away_news_at": g.get("awayNewsCreatedAt"),
            "game_time": g.get("dateGmt") or g.get("date") or g.get("gameTime"),
        })
    return games


def fetch(date: str, out: Path, *, refresh: bool = False) -> Dict[str, Any]:
    path = out / "dfo" / f"{date}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(URL.format(date=date), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # a failed fetch is NOT an empty slate (learnings 2026-09-25): record the error, write nothing
        return {"date": date, "error": f"HTTP {exc.code}"}
    games = parse_page(html)
    if games is None:
        return {"date": date, "error": "no __NEXT_DATA__ data block (layout change?)"}
    res = {"date": date, "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "games": games}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res), encoding="utf-8")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True, help="YYYY-MM-DD, a..b ranges, comma-separated")
    ap.add_argument("--out", default="C:/tmp/nhllines")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    errors, games = [], 0
    for i, d in enumerate(_dates(a.dates)):
        cached = (out / "dfo" / f"{d}.json").exists() and not a.refresh
        res = fetch(d, out, refresh=a.refresh)
        if "error" in res:
            errors.append((d, res["error"]))
        else:
            games += len(res["games"])
        if not cached:
            time.sleep(a.delay)
        if i % 25 == 0:
            print(f"  {d}: games so far {games}, errors {len(errors)}", flush=True)
    print(f"done: {games} game records; errors {len(errors)} {errors[:10]}")
    return 1 if errors and not games else 0


if __name__ == "__main__":
    raise SystemExit(main())
