"""NBA defender matchups for the cheat sheets (lane `cheat-sheets`, user 2026-10-15: "add defender matchups for NFL and NBA").

Source: NBA.com player tracking, `stats.nba.com/stats/leagueseasonmatchups` -- for every stretch of a possession, who
was guarding whom, credited in PARTIAL possessions, with the offensive player's points, FGM/FGA, 3PM/3PA, assists and
turnovers in those stretches. Free; the platform already reads stats.nba.com (source_cli, the live ticks).

A player's line is his matchups against TODAY's opponent's current roster (`commonallplayers`, this season), summed
over the regular seasons in `seasons_for` -- whatever team the defender was on then -- next to his rate against
everyone. REGULAR SEASON ONLY: preseason and playoffs are different populations. A completed season never changes, so
it is cached for good; the current season and the rosters are cached for the day. Samples are small and the price
knows them -- context, not a pick.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

STATS = "https://stats.nba.com/stats"
HEADERS = {
    "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nba.com", "Referer": "https://www.nba.com/stats/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "x-nba-stats-origin": "stats", "x-nba-stats-token": "true",
}
SEASONS_BACK = 3                    # this season and the two before it
TOP_DEFENDERS = 3
TEAM_ALIASES = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "NOR": "NOP", "PHO": "PHX", "UTAH": "UTA",
                "WSH": "WAS", "BRK": "BKN", "CHO": "CHA"}
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")
_SUMS = ("GP", "PARTIAL_POSS", "PLAYER_PTS", "MATCHUP_FGM", "MATCHUP_FGA", "MATCHUP_FG3M", "MATCHUP_FG3A",
         "MATCHUP_AST", "MATCHUP_TOV")


def _norm(name: Any) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", _SUFFIX.sub("", text))


def team_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    return TEAM_ALIASES.get(code, code)


def scoring_market(market: Any) -> bool:
    """The matchup data is about scoring and creating: points, threes, assists and the combos that hold them."""
    m = str(market or "").lower()
    return any(k in m for k in ("point", "pts", "three", "3pt", "3pm", "assist", "pra"))


def seasons_for(date: str, back: int = SEASONS_BACK) -> list[str]:
    """NBA season ids ('2026-27') for the season in play on `date` and the ones before it."""
    year, month = int(date[:4]), int(date[5:7])
    start = year if month >= 8 else year - 1
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(start, start - back, -1)]


class NbaApi:
    """GETs through a disk cache: `permanent` for completed seasons, `daily` for everything else."""

    def __init__(self, daily: Path | None, permanent: Path | None = None, fetch: Callable[[str], Any] | None = None,
                 pause: float = 0.6):
        self.daily, self.permanent = daily, permanent
        self.fetch = fetch or self._http
        self.pause = pause if fetch is None else 0.0
        self.calls = 0

    @staticmethod
    def _http(url: str) -> Any:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as resp:
            return json.load(resp)

    def get(self, endpoint: str, params: Mapping[str, Any], *, permanent: bool = False) -> Any:
        url = f"{STATS}/{endpoint}?{urllib.parse.urlencode(params)}"
        folder = self.permanent if permanent else self.daily
        hit = folder / f"{hashlib.sha1(url.encode()).hexdigest()}.json" if folder is not None else None
        if hit is not None and hit.is_file():
            try:
                return json.loads(hit.read_text(encoding="utf-8"))
            except ValueError:
                pass
        self.calls += 1
        if self.pause:
            time.sleep(self.pause)
        try:
            doc = self.fetch(url)
        except Exception:  # noqa: BLE001 -- a missing matchup is a blank cell, never a failed sheet
            return None
        if hit is not None and doc is not None:
            hit.parent.mkdir(parents=True, exist_ok=True)
            hit.write_text(json.dumps(doc), encoding="utf-8")
        return doc


def _table(doc: Any) -> list[dict[str, Any]]:
    sets = (doc or {}).get("resultSets") or (doc or {}).get("resultSet") or []
    first = sets[0] if isinstance(sets, list) and sets else sets
    if not isinstance(first, dict):
        return []
    heads = first.get("headers") or []
    return [dict(zip(heads, row)) for row in first.get("rowSet") or []]


def players(api: NbaApi, season: str) -> list[dict[str, Any]]:
    return _table(api.get("commonallplayers", {"IsOnlyCurrentSeason": 1, "LeagueID": "00", "Season": season}))


def season_matchups(api: NbaApi, player_id: Any, season: str, *, completed: bool) -> list[dict[str, Any]]:
    params = {"LeagueID": "00", "PerMode": "Totals", "Season": season, "SeasonType": "Regular Season",
              "OffPlayerID": player_id, "DefPlayerID": "", "OffTeamID": "", "DefTeamID": ""}
    return _table(api.get("leagueseasonmatchups", params, permanent=completed))


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def scorer_line(api: NbaApi, player_id: Any, defenders: Mapping[Any, str], seasons: list[str]) -> dict[str, Any] | None:
    """His matchups against `defenders`, summed over `seasons`, next to his points per 100 partial possessions overall."""
    per: dict[Any, dict[str, float]] = {}
    all_poss = all_pts = 0.0
    for season in seasons:
        for m in season_matchups(api, player_id, season, completed=season != seasons[0]):
            all_poss += _num(m.get("PARTIAL_POSS"))
            all_pts += _num(m.get("PLAYER_PTS"))
            did = m.get("DEF_PLAYER_ID")
            if did in defenders:
                t = per.setdefault(did, {k: 0.0 for k in _SUMS})
                for k in _SUMS:
                    t[k] += _num(m.get(k))
    if not per:
        return None
    tot = {k: sum(t[k] for t in per.values()) for k in _SUMS}
    top = sorted(per.items(), key=lambda kv: -kv[1]["PARTIAL_POSS"])[:TOP_DEFENDERS]

    def slim(t: Mapping[str, float]) -> dict[str, Any]:
        return {"gp": int(t["GP"]), "poss": round(t["PARTIAL_POSS"], 1), "pts": int(t["PLAYER_PTS"]),
                "fgm": int(t["MATCHUP_FGM"]), "fga": int(t["MATCHUP_FGA"]), "fg3m": int(t["MATCHUP_FG3M"]),
                "fg3a": int(t["MATCHUP_FG3A"]), "ast": int(t["MATCHUP_AST"]), "tov": int(t["MATCHUP_TOV"])}

    return {**slim(tot), "pts_per_100": round(100 * tot["PLAYER_PTS"] / tot["PARTIAL_POSS"], 1) if tot["PARTIAL_POSS"] else None,
            "overall_pts_per_100": round(100 * all_pts / all_poss, 1) if all_poss else None,
            "since": seasons[-1], "defenders": [{"name": defenders[d], **slim(t)} for d, t in top]}


def _short(name: str) -> str:
    first, _, rest = name.partition(" ")
    return f"{first[:1]}. {rest}" if rest else name


def matchups(rows: list[dict[str, Any]], *, date: str, api: NbaApi) -> dict[tuple[str, str], dict[str, Any]]:
    """(normalized player, market) -> the defender block; one block per player, shared by all his props."""
    seasons = seasons_for(date)
    people = players(api, seasons[0])
    by_name: dict[str, list[dict[str, Any]]] = {}
    by_team: dict[str, dict[Any, str]] = {}
    for p in people:
        by_name.setdefault(_norm(p.get("DISPLAY_FIRST_LAST")), []).append(p)
        team = team_code(p.get("TEAM_ABBREVIATION"))
        if team:
            by_team.setdefault(team, {})[p.get("PERSON_ID")] = p.get("DISPLAY_FIRST_LAST") or ""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    done: dict[str, dict[str, Any] | None] = {}
    for r in rows:
        key, market = _norm(r.get("player")), str(r.get("market") or "").strip().lower()
        team, opp = team_code(r.get("team")), team_code(r.get("opponent"))
        if not key or not opp or not scoring_market(market) or (key, market) in out:
            continue
        if key not in done:
            cands = by_name.get(key) or []
            mine = [p for p in cands if team_code(p.get("TEAM_ABBREVIATION")) == team] or cands
            defenders = by_team.get(opp) or {}
            line = (scorer_line(api, mine[0].get("PERSON_ID"), defenders, seasons)
                    if len(mine) == 1 and defenders else None)
            done[key] = None if line is None else {
                "kind": "scorer_vs_defenders", "opponent": f"{opp} defenders", "line": line,
                "summary": "; ".join(f"{_short(x['name'])}: {x['pts']} pts, {x['fgm']}/{x['fga']} FG in {x['poss']:.0f} poss "
                                     f"({x['gp']} GP)" for x in line["defenders"][:2])}
        if done[key] is not None:
            out[(key, market)] = done[key]
    return out
