"""Skater vs goalie for the cheat sheets (lane `cheat-sheets`, user 2026-10-15: "add skater vs goalie for NHL").

Source: the NHL's public API (api-web.nhle.com), free and keyless.
  * `schedule/{date}` -> the day's games; `gamecenter/{id}/landing` `matchup.goalieComparison` -> each team's goalies
    with this season's games played. The LIKELY starter is the one with the most games -- shown as "likely starter",
    because starters are not confirmed until warmups.
  * `roster/{team}/current` -> name -> id inside the game's two teams (never a league-wide name guess).
  * `player/{id}/game-log/{season}/2` -> every regular-season game a player played, with the opponent.
  * `gamecenter/{id}/play-by-play` -> every shot with `shootingPlayerId` / `scoringPlayerId` and `goalieInNetId`.

A SKATER prop gets his shots on goal and goals against the opposing likely starter: the games both played on
opposite sides (their game logs, so a trade or a goalie's move does not lose history), counted shot by shot with
that goalie in net. A GOALIE prop (saves) gets his record against today's opponent from his own game logs.
Finished games never change, so their slimmed shot lists are cached for good; everything else is cached for the day.
Samples are small and the price knows them -- context, not a pick.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

NHL_API = "https://api-web.nhle.com/v1"
SEASONS_BACK = 4                 # this season and the three before it
GOALIE_MARKETS = frozenset({"saves", "goalie_saves", "player_total_saves", "goals_against", "goalie_goals_against"})


def _norm(name: Any) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", text)


def is_goalie_market(market: Any) -> bool:
    key = str(market or "").strip().lower()
    return key in GOALIE_MARKETS or "save" in key


def seasons_for(date: str, back: int = SEASONS_BACK) -> list[str]:
    """NHL season ids ('20262027') for the season in play on `date` and the ones before it."""
    year, month = int(date[:4]), int(date[5:7])
    start = year if month >= 8 else year - 1
    return [f"{y}{y + 1}" for y in range(start, start - back, -1)]


class NhlApi:
    """GETs through a disk cache: `permanent` for finished games' shot lists, `daily` for everything else."""

    def __init__(self, daily: Path | None, permanent: Path | None = None, fetch: Callable[[str], Any] | None = None,
                 pause: float = 0.05):
        self.daily, self.permanent = daily, permanent
        self.fetch = fetch or self._http
        self.pause = pause if fetch is None else 0.0
        self.calls = 0

    @staticmethod
    def _http(url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "Syndicate cheat sheets"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)

    def _cached(self, folder: Path | None, key: str) -> Path | None:
        return folder / f"{hashlib.sha1(key.encode()).hexdigest()}.json" if folder is not None else None

    def get(self, path: str, *, permanent: bool = False, slim: Callable[[Any], Any] | None = None) -> Any:
        url = f"{NHL_API}/{path}"
        hit = self._cached(self.permanent if permanent else self.daily, url)
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
        if doc is not None and slim is not None:
            doc = slim(doc)
        if hit is not None and doc is not None:
            hit.parent.mkdir(parents=True, exist_ok=True)
            hit.write_text(json.dumps(doc), encoding="utf-8")
        return doc


def slate(api: NhlApi, date: str) -> list[dict[str, Any]]:
    doc = api.get(f"schedule/{date}") or {}
    out = []
    for week in doc.get("gameWeek") or []:
        if week.get("date") != date:
            continue
        for g in week.get("games") or []:
            out.append({"id": g.get("id"), "home": (g.get("homeTeam") or {}).get("abbrev"),
                        "away": (g.get("awayTeam") or {}).get("abbrev")})
    return out


def likely_goalies(api: NhlApi, game_id: Any) -> dict[str, dict[str, Any]]:
    """side -> {id, name, games} for the goalie with the most games this season (unconfirmed)."""
    land = api.get(f"gamecenter/{game_id}/landing") or {}
    comp = ((land.get("matchup") or {}).get("goalieComparison")) or {}
    out = {}
    for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
        leaders = ((comp.get(key) or {}).get("leaders")) or []
        if leaders:
            top = max(leaders, key=lambda x: int(x.get("gamesPlayed") or 0))
            out[side] = {"id": top.get("playerId"), "name": (top.get("name") or {}).get("default"),
                         "games": int(top.get("gamesPlayed") or 0), "started": False}
    if out:
        return out
    # Once the game starts the pre-game matchup block is gone (measured 2026-10-14); the box score then names who was
    # actually in net -- the goalie with the most time on ice -- which is better than a guess for the day's record.
    box = api.get(f"gamecenter/{game_id}/boxscore") or {}
    stats = box.get("playerByGameStats") or {}
    for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
        goalies = [g for g in ((stats.get(key) or {}).get("goalies")) or [] if _toi_seconds(g.get("toi")) > 0]
        if goalies:
            top = max(goalies, key=lambda g: _toi_seconds(g.get("toi")))
            out[side] = {"id": top.get("playerId"), "name": (top.get("name") or {}).get("default"), "games": None,
                         "started": True}
    return out


def _toi_seconds(toi: Any) -> int:
    try:
        minutes, seconds = str(toi or "0:0").split(":")
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return 0


def roster(api: NhlApi, team: str) -> dict[str, dict[str, Any]]:
    doc = api.get(f"roster/{team}/current") or {}
    out: dict[str, dict[str, Any]] = {}
    clash: set[str] = set()
    for group in ("forwards", "defensemen", "goalies"):
        for p in doc.get(group) or []:
            name = f"{(p.get('firstName') or {}).get('default', '')} {(p.get('lastName') or {}).get('default', '')}".strip()
            key = _norm(name)
            if not key or key in clash:
                continue
            if key in out:
                clash.add(key)
                out.pop(key, None)
                continue
            out[key] = {"id": p.get("id"), "name": name, "goalie": group == "goalies"}
    return out


def game_log(api: NhlApi, player_id: Any, season: str) -> list[dict[str, Any]]:
    doc = api.get(f"player/{player_id}/game-log/{season}/2") or {}
    return list(doc.get("gameLog") or [])


def _slim_shots(doc: Any) -> list[list[Any]]:
    """[shooter, goalie, is_goal] for every shot on goal and goal -- all a skater-vs-goalie count needs."""
    out = []
    for p in (doc or {}).get("plays") or []:
        kind = p.get("typeDescKey")
        if kind not in ("shot-on-goal", "goal"):
            continue
        d = p.get("details") or {}
        shooter = d.get("scoringPlayerId") if kind == "goal" else d.get("shootingPlayerId")
        out.append([shooter, d.get("goalieInNetId"), kind == "goal"])
    return out


def skater_vs_goalie(api: NhlApi, skater_id: Any, goalie_id: Any, seasons: list[str]) -> dict[str, Any] | None:
    """Games both played on opposite sides, and the skater's SOG + goals with that goalie in net."""
    shared = []
    for season in seasons:
        sk = {g.get("gameId"): g for g in game_log(api, skater_id, season)}
        for g in game_log(api, goalie_id, season):
            mine = sk.get(g.get("gameId"))
            if mine and mine.get("teamAbbrev") != g.get("teamAbbrev"):
                shared.append(g.get("gameId"))
    if not shared:
        return None
    sog = goals = games = 0
    for game_id in shared:
        shots = api.get(f"gamecenter/{game_id}/play-by-play", permanent=True, slim=_slim_shots)
        if shots is None:
            continue
        games += 1
        for shooter, goalie, is_goal in shots:
            if shooter == skater_id and goalie == goalie_id:
                sog += 1
                goals += 1 if is_goal else 0
    return {"games": games, "sog": sog, "goals": goals} if games else None


def goalie_vs_team(api: NhlApi, goalie_id: Any, opponent: str, seasons: list[str]) -> dict[str, Any] | None:
    games = [g for season in seasons for g in game_log(api, goalie_id, season) if g.get("opponentAbbrev") == opponent]
    games = [g for g in games if g.get("shotsAgainst") is not None]
    if not games:
        return None
    sa = sum(int(g.get("shotsAgainst") or 0) for g in games)
    ga = sum(int(g.get("goalsAgainst") or 0) for g in games)
    return {"games": len(games), "shots_against": sa, "goals_against": ga, "saves": sa - ga,
            "sv_pct": round((sa - ga) / sa, 3) if sa else None}


def matchups(rows: list[dict[str, Any]], *, date: str, api: NhlApi) -> dict[tuple[str, str], dict[str, Any]]:
    """(normalized player, market) -> the player-vs-player block for that sheet row."""
    seasons = seasons_for(date)
    games = slate(api, date)
    rosters = {team: roster(api, team) for g in games for team in (g["home"], g["away"]) if team}
    goalies = {g["id"]: likely_goalies(api, g["id"]) for g in games}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key, market = _norm(r.get("player")), str(r.get("market") or "").strip().lower()
        if not key or (key, market) in out:
            continue
        found = None
        for g in games:
            for side, other in (("home", "away"), ("away", "home")):
                who = rosters.get(g[side], {}).get(key)
                if who:
                    found = (g, side, other, who)
                    break
            if found:
                break
        if not found:
            continue
        g, side, other, who = found
        if who["goalie"] or is_goalie_market(market):
            line = goalie_vs_team(api, who["id"], g[other], seasons)
            if line:
                out[(key, market)] = {"kind": "goalie_vs_team", "opponent": g[other], "line": line,
                                      "summary": f"{line['games']} GP vs {g[other]}: {line['saves'] / line['games']:.1f} saves/g, "
                                                 f"{line['sv_pct']:.3f} SV%" if line["sv_pct"] is not None else f"{line['games']} GP vs {g[other]}"}
            continue
        goalie = goalies.get(g["id"], {}).get(other)
        if not goalie or not goalie.get("id"):
            continue
        line = skater_vs_goalie(api, who["id"], goalie["id"], seasons)
        if line:
            tag = "started" if goalie.get("started") else "likely starter"
            out[(key, market)] = {"kind": "skater_vs_goalie", "opponent": f"{goalie['name']} ({tag})", "line": line,
                                  "summary": f"{line['goals']} G on {line['sog']} SOG in {line['games']} game"
                                             f"{'s' if line['games'] != 1 else ''} vs {goalie['name']}"}
    return out
