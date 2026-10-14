"""Timestamped, append-only news collectors: injuries, referee crews -- the facts whose ARRIVAL TIME matters.

Lane `news-collectors-backfill` (2026-10-13, user: "start ... the collectors ... this should spend no money and needs
to watch oddsapi limits"). Plan: `findings_2026-10-13_matchup_signal_plan.md` §1.

WHY. The matchup engine's news signals (teammate ruled out -> usage shift; how fast a prop price follows an injury; a
referee crew's foul rate) need to know WHEN each fact became public. Nothing on the fleet records that: NBA
`raw/injuries.csv` carries a date and no capture time, NHL's injury builder is a placeholder, and NFL inactives start
10-01 with no practice-week history. That history cannot be rebuilt later, so it is collected from now on.

WHAT, every run (cheap, free, no keys, NO OddsAPI):
  injuries   ESPN `site.api.espn.com/apis/site/v2/sports/<path>/injuries` for nba, nhl, nfl, wnba, mlb: 1 request
             each. (MLB added 2026-10-14, user: "collect MLB injuries now, flag in 2027" -- the history builds through
             the offseason; the board flag waits for the 2027 regular season, `news_availability.REGULAR_SEASONS`.)
             (ESPN's college-football feed is dead -- newest entry 2022 -- so NCAAF is not polled; the
             men's college basketball and soccer feeds were empty on 2026-10-14.)
  referees   nba: official.nba.com/referee-assignments/ (1 request; posted ~9am ET).
             nhl: api-web.nhle.com schedule + one `right-rail` request per game starting within 4 h, until it starts:
             referees, linesmen AND each team's scratches (logged whenever they change).

OUTPUT under `<data root>/news/` (the fleet's SYNDICATE_DATA_ROOT):
  <sport>/injuries/<UTC date>.jsonl   one line per CHANGE: event new | changed | cleared, our `captured_at`, the
                                      source's own `source_updated_at`, status, type, comment, team, athlete id/name.
  nba/referees/<UTC date>.jsonl       one line per game crew FIRST SEEN (and again if the crew changes).
  nhl/gameinfo/<UTC date>.jsonl       officials + scratches per game, whenever they change before puck drop.
  _state/<sport>_<kind>.json          last-seen state, so a run writes only changes.
  _status/last_run.json               counts, errors, request totals of the latest run.
A first run writes every current injury as `new` (a baseline). Writes are append-only; state is replaced atomically.

    python scripts/collect_news_snapshots.py --data-root ~/syndicate-prod/data            # one run
    python scripts/collect_news_snapshots.py --data-root ... --sports nba,nhl --kinds injuries
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ESPN_INJURY_PATHS = {
    "nba": "basketball/nba",
    "nhl": "hockey/nhl",
    "nfl": "football/nfl",
    "wnba": "basketball/wnba",
    "mlb": "baseball/mlb",
}
NBA_REFEREES_URL = "https://official.nba.com/referee-assignments/"
NHL_SCHEDULE_URL = "https://api-web.nhle.com/v1/schedule/now"
NHL_RIGHT_RAIL_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/right-rail"
USER_AGENT = "Mozilla/5.0 (compatible; syndicate-news-collector/1.0)"
NHL_REF_LOOKAHEAD = timedelta(hours=4)

Fetcher = Callable[[str], bytes]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ----------------------------------------------------------------------------- storage


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root / "news"

    def state_path(self, sport: str, kind: str) -> Path:
        return self.root / "_state" / f"{sport}_{kind}.json"

    def load_state(self, sport: str, kind: str) -> dict[str, Any]:
        path = self.state_path(sport, kind)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self, sport: str, kind: str, state: Mapping[str, Any]) -> None:
        path = self.state_path(sport, kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def append(self, sport: str, kind: str, captured: datetime, records: list[Mapping[str, Any]]) -> None:
        if not records:
            return
        path = self.root / sport / kind / f"{captured.strftime('%Y-%m-%d')}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")

    def write_status(self, status: Mapping[str, Any]) -> None:
        path = self.root / "_status" / "last_run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(status, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)


# ----------------------------------------------------------------------------- injuries


def parse_espn_injuries(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """athlete id -> the fields whose change is news."""
    out: dict[str, dict[str, Any]] = {}
    for team in payload.get("injuries") or []:
        team_name = team.get("displayName")
        for item in team.get("injuries") or []:
            athlete = item.get("athlete") or {}
            athlete_id = str(athlete.get("id") or item.get("id") or "").strip()
            if not athlete_id:
                continue
            kind = item.get("type") or {}
            details = item.get("details") or {}
            out[athlete_id] = {
                "athlete_id": athlete_id,
                "athlete": athlete.get("displayName"),
                "team": team_name,
                "status": item.get("status"),
                "type": kind.get("abbreviation") or kind.get("name"),
                "detail_type": details.get("type"),
                "return_date": details.get("returnDate"),
                "comment": item.get("shortComment"),
                "source_updated_at": item.get("date"),
            }
    return out


_INJURY_CHANGE_FIELDS = ("status", "type", "detail_type", "return_date", "comment", "team")


def injury_changes(previous: Mapping[str, Mapping[str, Any]], current: Mapping[str, Mapping[str, Any]],
                   *, sport: str, captured: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    stamp = iso(captured)
    for athlete_id, now in current.items():
        before = previous.get(athlete_id)
        if before is None:
            event = "new"
        elif any(before.get(f) != now.get(f) for f in _INJURY_CHANGE_FIELDS):
            event = "changed"
        else:
            continue
        rec = {"event": event, "sport": sport, "captured_at": stamp, "source": "espn", **now}
        if before is not None:
            rec["previous_status"] = before.get("status")
        events.append(rec)
    for athlete_id, before in previous.items():
        if athlete_id not in current:
            events.append({"event": "cleared", "sport": sport, "captured_at": stamp, "source": "espn",
                           "athlete_id": athlete_id, "athlete": before.get("athlete"), "team": before.get("team"),
                           "previous_status": before.get("status")})
    return events


def collect_injuries(sport: str, store: Store, fetch: Fetcher, captured: datetime) -> dict[str, Any]:
    url = f"https://site.api.espn.com/apis/site/v2/sports/{ESPN_INJURY_PATHS[sport]}/injuries"
    current = parse_espn_injuries(json.loads(fetch(url)))
    previous = store.load_state(sport, "injuries")
    events = injury_changes(previous, current, sport=sport, captured=captured)
    store.append(sport, "injuries", captured, events)
    store.save_state(sport, "injuries", current)
    return {"requests": 1, "listed": len(current), "events": len(events),
            "by_event": {e: sum(1 for x in events if x["event"] == e) for e in ("new", "changed", "cleared")}}


# ----------------------------------------------------------------------------- referees


_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_nba_referees(page: str) -> list[dict[str, Any]]:
    """Rows of the assignments table: game, crew chief, referee, umpire, alternate (names with #numbers)."""
    rows = []
    for body in _ROW_RE.findall(page):
        cells = [re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", c))).strip() for c in _CELL_RE.findall(body)]
        if len(cells) < 4 or "@" not in cells[0]:
            continue
        rows.append({"game": cells[0], "crew_chief": cells[1] or None, "referee": cells[2] or None,
                     "umpire": cells[3] or None, "alternate": (cells[4] if len(cells) > 4 else "") or None})
    return rows


def _crew_hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha1(json.dumps(row, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def collect_nba_referees(store: Store, fetch: Fetcher, captured: datetime) -> dict[str, Any]:
    rows = parse_nba_referees(fetch(NBA_REFEREES_URL).decode("utf-8", "replace"))
    state = store.load_state("nba", "referees")
    day = captured.strftime("%Y-%m-%d")
    seen = state.get(day) or {}
    events = []
    for row in rows:
        h = _crew_hash(row)
        if seen.get(row["game"]) == h:
            continue
        events.append({"event": "new" if row["game"] not in seen else "changed", "sport": "nba",
                       "captured_at": iso(captured), "source": "official.nba.com", "page_date_utc": day, **row})
        seen[row["game"]] = h
    store.append("nba", "referees", captured, events)
    store.save_state("nba", "referees", {day: seen})
    return {"requests": 1, "games_listed": len(rows), "events": len(events)}


def nhl_games_starting_soon(schedule: Mapping[str, Any], now: datetime) -> list[dict[str, Any]]:
    games = []
    for day in schedule.get("gameWeek") or []:
        for g in day.get("games") or []:
            try:
                start = datetime.fromisoformat(str(g.get("startTimeUTC")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if now - timedelta(hours=1) <= start <= now + NHL_REF_LOOKAHEAD:
                games.append({"game_id": str(g.get("id")), "start_utc": iso(start),
                              "away": (g.get("awayTeam") or {}).get("abbrev"), "home": (g.get("homeTeam") or {}).get("abbrev")})
    return games


def _person(item: Any) -> str | None:
    if not isinstance(item, Mapping):
        return str(item) if item else None
    full = item.get("fullName")
    if isinstance(full, Mapping) and full.get("default"):
        return str(full["default"])
    first = (item.get("firstName") or {}).get("default") if isinstance(item.get("firstName"), Mapping) else None
    last = (item.get("lastName") or {}).get("default") if isinstance(item.get("lastName"), Mapping) else None
    name = " ".join(x for x in (first, last) if x)
    return name or (str(item.get("default")) if item.get("default") else None)


def parse_nhl_gameinfo(rail: Mapping[str, Any]) -> dict[str, Any]:
    """Officials and each team's scratches from the right-rail `gameInfo` (both empty until posted)."""
    info = rail.get("gameInfo") or {}

    def people(items: Any) -> list[str]:
        return [n for n in (_person(it) for it in items or []) if n]

    def scratches(team: Any) -> list[dict[str, Any]]:
        team = team if isinstance(team, Mapping) else {}
        return [{"id": it.get("id"), "name": _person(it)} for it in team.get("scratches") or [] if isinstance(it, Mapping)]

    return {"referees": people(info.get("referees")), "linesmen": people(info.get("linesmen")),
            "away_scratches": scratches(info.get("awayTeam")), "home_scratches": scratches(info.get("homeTeam"))}


def collect_nhl_gameinfo(store: Store, fetch: Fetcher, captured: datetime) -> dict[str, Any]:
    """Re-read each game starting within the window until it starts; log officials / scratches whenever they change."""
    games = [g for g in nhl_games_starting_soon(json.loads(fetch(NHL_SCHEDULE_URL)), captured)
             if datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00")) >= captured - timedelta(minutes=15)]
    state = store.load_state("nhl", "gameinfo")
    requests, events = 1, []
    for game in games:
        requests += 1
        info = parse_nhl_gameinfo(json.loads(fetch(NHL_RIGHT_RAIL_URL.format(game_id=game["game_id"]))))
        if not (info["referees"] or info["linesmen"] or info["away_scratches"] or info["home_scratches"]):
            continue  # nothing posted yet
        h = _crew_hash(info)
        if state.get(game["game_id"]) == h:
            continue
        events.append({"event": "new" if game["game_id"] not in state else "changed", "sport": "nhl",
                       "captured_at": iso(captured), "source": "api-web.nhle.com", **game, **info})
        state[game["game_id"]] = h
    if len(state) > 400:
        state = dict(sorted(state.items())[-400:])
    store.append("nhl", "gameinfo", captured, events)
    store.save_state("nhl", "gameinfo", state)
    return {"requests": requests, "games_in_window": len(games), "events": len(events)}


# ----------------------------------------------------------------------------- driver


def run(data_root: Path, sports: list[str], kinds: list[str], fetch: Fetcher = http_get,
        now: datetime | None = None) -> dict[str, Any]:
    captured = now or utc_now()
    store = Store(data_root)
    status: dict[str, Any] = {"captured_at": iso(captured), "results": {}, "errors": {}, "requests": 0,
                              "oddsapi_requests": 0}
    jobs: list[tuple[str, Callable[[], dict[str, Any]]]] = []
    if "injuries" in kinds:
        for sport in sports:
            if sport in ESPN_INJURY_PATHS:
                jobs.append((f"{sport}_injuries", lambda s=sport: collect_injuries(s, store, fetch, captured)))
    if "referees" in kinds:
        if "nba" in sports:
            jobs.append(("nba_referees", lambda: collect_nba_referees(store, fetch, captured)))
        if "nhl" in sports:
            jobs.append(("nhl_gameinfo", lambda: collect_nhl_gameinfo(store, fetch, captured)))
    for name, job in jobs:
        try:
            result = job()
            status["results"][name] = result
            status["requests"] += int(result.get("requests") or 0)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            status["errors"][name] = f"{type(exc).__name__}: {exc}"[:300]
        time.sleep(0.5)  # polite spacing between hosts
    store.write_status(status)
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--sports", default="nba,nhl,nfl,wnba,mlb")
    ap.add_argument("--kinds", default="injuries,referees")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root and no SYNDICATE_DATA_ROOT", flush=True)
        return 2
    status = run(Path(os.path.expanduser(args.data_root)),
                 [s.strip() for s in args.sports.split(",") if s.strip()],
                 [k.strip() for k in args.kinds.split(",") if k.strip()])
    print("NEWS_COLLECT " + json.dumps(status, sort_keys=True), flush=True)
    return 1 if status["errors"] and not status["results"] else 0


if __name__ == "__main__":
    sys.exit(main())
