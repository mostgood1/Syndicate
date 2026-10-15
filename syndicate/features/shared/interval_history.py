"""Each team's recent INTERVAL scores -- an inning, a quarter, a half, a period -- for a segment pick's case.

User 2026-10-15: "we should fix the gaps - for example we need the interval data". A first-3-innings moneyline or a
first-quarter spread read against full-game finals is a different bet, so `team_recent_results` returns nothing for
every interval except NCAAF's (the one sport whose local game files carry line scores). This module supplies the
rest from FREE public feeds -- no OddsAPI credit is spent:

* mlb -- StatsAPI ``schedule?hydrate=linescore``: per-inning runs, a whole date range in one call. Regular season
         and postseason only (spring training and exhibitions are another population).
* nfl / nba / wnba / ncaab / nhl -- ESPN's scoreboard, one call per date (it refuses ranges: HTTP 400, measured
         2026-10-15), ``competitors[].linescores`` read by the grader's own `linescores_from_competitor`. Preseason
         (season type 1) is left out.
* ncaaf -- `team_recent_results` already has its quarters; this defers to it.

A segment means what the grader settles it on (`segment_actuals`, `live_gameline_segment_actuals`): first-N innings
= innings 1..N; qN / pN = that period alone; h1 = periods 1-2; h2 = 3-4 AND every overtime (NCAAB: period 2 and
overtime). A period missing from a final linescore is a hole and the game is skipped -- never read as zero.

Each date is cached under ``<cache_dir>/<sport>/<date>.json`` once it is in the past and every game on it is decided;
finals do not change, so a date is fetched once. Display only: nothing scores on these.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_FOOTBALL = {"q1": (1,), "q2": (2,), "q3": (3,), "q4": (4,), "h1": (1, 2), "h2": (3, 4, None)}
SEGMENTS: Mapping[str, Mapping[str, tuple[int | None, ...]]] = {
    "mlb": {"first1": (1,), "first3": (1, 2, 3), "first5": (1, 2, 3, 4, 5)},
    "nfl": _FOOTBALL, "nba": _FOOTBALL, "wnba": _FOOTBALL,
    "ncaab": {"h1": (1,), "h2": (2, None)},
    "nhl": {"p1": (1,), "p2": (2,), "p3": (3,)},
}
ESPN_PATHS = {"nfl": "football/nfl", "nba": "basketball/nba", "wnba": "basketball/wnba",
              "ncaab": "basketball/mens-college-basketball", "nhl": "hockey/nhl"}
_ESPN_QUERY = {"ncaab": "&groups=50&limit=400"}
# How far back a team's last ten intervals can sit: daily sports reach ten games in under a month (the window allows
# for an off week); the NFL plays weekly.
WINDOW_DAYS = {"nfl": 80}
DEFAULT_WINDOW_DAYS = 40
MLB_GAME_TYPES = frozenset({"R", "F", "D", "L", "W"})       # regular season and every postseason round
_MAX_FETCHES = 90                                          # per call; the next build continues a cold cache


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _get(url: str) -> Any:
    # No custom User-Agent for ESPN: it 403s some (`game_chip_linescore._espn_board`).
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def team_key(sport: str, name: Any) -> str | None:
    if not name:
        return None
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        key = chip_join_key(sport, str(name))
    except Exception:  # noqa: BLE001 -- display join
        key = None
    return key or str(name).strip().lower() or None


def mlb_games(payload: Any) -> dict[str, list[dict[str, Any]]]:
    """StatsAPI schedule (hydrate=linescore) -> {date: [game]}, regular season and postseason, final games only."""
    out: dict[str, list[dict[str, Any]]] = {}
    for block in (payload or {}).get("dates") or []:
        day = str(block.get("date") or "")[:10]
        games = out.setdefault(day, [])
        for g in block.get("games") or []:
            if g.get("gameType") not in MLB_GAME_TYPES:
                continue
            final = str(((g.get("status") or {}).get("abstractGameState")) or "") == "Final"
            innings = ((g.get("linescore") or {}).get("innings")) or []
            home = [_int((i.get("home") or {}).get("runs")) for i in innings if isinstance(i, Mapping)]
            away = [_int((i.get("away") or {}).get("runs")) for i in innings if isinstance(i, Mapping)]
            teams = g.get("teams") or {}
            games.append({"home": ((teams.get("home") or {}).get("team") or {}).get("name"),
                          "away": ((teams.get("away") or {}).get("team") or {}).get("name"),
                          "final": final, "decided": final or str((g.get("status") or {}).get("codedGameState")) in ("D", "C"),
                          "home_periods": home, "away_periods": away})
    return out


def espn_games(payload: Any) -> list[dict[str, Any]]:
    """ESPN scoreboard -> [game], regular season and postseason only, with each side's per-period points."""
    from syndicate.features.shared.segment_actuals import linescores_from_competitor

    out = []
    for event in (payload or {}).get("events") or []:
        if _int(((event.get("season") or {}).get("type"))) == 1:
            continue                                        # preseason is another population
        comp = (event.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, Mapping)}
        home, away = sides.get("home") or {}, sides.get("away") or {}
        state = (((event.get("status") or {}).get("type")) or {})
        final = bool(state.get("completed"))
        out.append({"home": (home.get("team") or {}).get("displayName"), "away": (away.get("team") or {}).get("displayName"),
                    "final": final, "decided": final or str(state.get("state")) == "post",
                    "home_periods": linescores_from_competitor(home) or [], "away_periods": linescores_from_competitor(away) or []})
    return out


def segment_sum(periods: Sequence[int | None], spans: tuple[int | None, ...]) -> int | None:
    """Points over a segment's periods; None when a period it needs is missing (a hole is never a zero). A trailing
    None in `spans` means "and every later period" -- overtime belongs to the second half."""
    fixed = [p for p in spans if p is not None]
    if not fixed or len(periods) < fixed[-1] or any(periods[p - 1] is None for p in fixed):
        return None
    total = sum(int(periods[p - 1]) for p in fixed)
    if spans[-1] is None:
        total += sum(int(v) for v in periods[fixed[-1]:] if v is not None)
    return total


class IntervalHistory:
    """Per-date games for one data root, cached on disk; `fetch` is injectable for tests."""

    def __init__(self, cache_dir: Path | str, *, today: str | None = None, fetch: Callable[[str], Any] | None = None):
        self.cache_dir = Path(cache_dir)
        self.today = today or date.today().isoformat()
        self.fetch = fetch or _get
        self.fetches = 0
        self._mem: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def _path(self, sport: str, day: str) -> Path:
        return self.cache_dir / sport / f"{day}.json"

    def _keep(self, sport: str, day: str, games: list[dict[str, Any]]) -> None:
        self._mem[(sport, day)] = games
        if day < self.today and all(g.get("decided") for g in games):
            path = self._path(sport, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(games), encoding="utf-8")
            tmp.replace(path)

    def _cached(self, sport: str, day: str) -> list[dict[str, Any]] | None:
        if (sport, day) in self._mem:
            return self._mem[(sport, day)]
        try:
            games = json.loads(self._path(sport, day).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        self._mem[(sport, day)] = games
        return games

    def _prefetch_mlb(self, days: list[str]) -> None:
        missing = [d for d in days if self._cached("mlb", d) is None]
        if not missing or self.fetches >= _MAX_FETCHES:
            return
        self.fetches += 1
        url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&hydrate=linescore"
               f"&startDate={min(missing)}&endDate={max(missing)}")
        try:
            by_day = mlb_games(self.fetch(url))
        except Exception:  # noqa: BLE001 -- a case point must never break a sheet
            return
        for d in missing:
            self._keep("mlb", d, by_day.get(d, []))

    def games_on(self, sport: str, day: str) -> list[dict[str, Any]]:
        hit = self._cached(sport, day)
        if hit is not None:
            return hit
        if sport == "mlb":
            self._prefetch_mlb([day])
            return self._cached("mlb", day) or []
        if sport not in ESPN_PATHS or self.fetches >= _MAX_FETCHES:
            return []
        self.fetches += 1
        url = (f"https://site.api.espn.com/apis/site/v2/sports/{ESPN_PATHS[sport]}/scoreboard"
               f"?dates={day.replace('-', '')}{_ESPN_QUERY.get(sport, '')}")
        try:
            games = espn_games(self.fetch(url))
        except Exception:  # noqa: BLE001
            return []
        self._keep(sport, day, games)
        return games

    def team_results(self, sport: Any, team: Any, before: Any, segment: Any, n: int = 10) -> list[list[Any]]:
        """Newest-first ``[date, for, against]`` over ``segment`` for ``team``'s final games strictly before
        ``before``, inside the sport's window. ``[]`` for a sport / segment with no source -- never a guess."""
        sport, segment = str(sport or "").lower(), str(segment or "").strip().lower()
        if sport == "ncaaf":
            from syndicate.features.shared.team_recent_results import team_recent_results

            return team_recent_results(sport, team, before, n, segment=segment)
        spans = SEGMENTS.get(sport, {}).get(segment)
        key = team_key(sport, team)
        try:
            first = date.fromisoformat(str(before or "")[:10])
        except ValueError:
            return []
        if not spans or not key:
            return []
        days = [(first - timedelta(days=k)).isoformat() for k in range(1, WINDOW_DAYS.get(sport, DEFAULT_WINDOW_DAYS) + 1)]
        if sport == "mlb":
            self._prefetch_mlb(days)
        out: list[list[Any]] = []
        for day in days:
            for g in self.games_on(sport, day):
                if not g.get("final"):
                    continue
                side = "home" if team_key(sport, g.get("home")) == key else "away" if team_key(sport, g.get("away")) == key else None
                if side is None:
                    continue
                other = "away" if side == "home" else "home"
                mine, theirs = segment_sum(g.get(f"{side}_periods") or [], spans), segment_sum(g.get(f"{other}_periods") or [], spans)
                if mine is not None and theirs is not None:
                    out.append([day, float(mine), float(theirs)])
            if len(out) >= n:
                break
        return out[:n]
