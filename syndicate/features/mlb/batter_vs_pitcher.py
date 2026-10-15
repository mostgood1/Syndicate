"""Batter vs pitcher for the cheat sheets (lane `cheat-sheets`, user 2026-10-15: "add player vs player matchups like
batter vs pitcher").

Source: MLB StatsAPI, free and keyless -- `schedule?hydrate=probablePitcher` for each game's probable starters,
`teams/{id}/roster` to resolve a name to its MLBAM id INSIDE the two teams of that game (never a league-wide name
guess), and `people/{batter}/stats?stats=vsPlayer&opposingPlayerId={pitcher}` for the career line. Every response is
cached on the data root for the day, so a sheet build makes each call once and the web never calls out.

Two views:
  * a BATTER prop gets that hitter's career line against the opposing probable starter;
  * a PITCHER prop gets the opposing roster's hitters' COMBINED career line against him.
Samples are small (a typical pair has fewer than 15 plate appearances) and the price knows them; the sheet shows the
line, the sample size and the price check side by side -- context, not a pick.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

STATSAPI = "https://statsapi.mlb.com/api/v1"
PITCHER_MARKETS = frozenset({"strikeouts", "pitcher_strikeouts", "outs", "pitcher_outs", "hits_allowed",
                             "pitcher_hits_allowed", "walks_allowed", "pitcher_walks", "earned_runs",
                             "pitcher_earned_runs", "pitcher_record_a_win"})


def _norm(name: Any) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", text)
    return re.sub(r"[^a-z]", "", text)


def is_pitcher_market(market: Any) -> bool:
    key = str(market or "").strip().lower()
    return key in PITCHER_MARKETS or key.startswith("pitcher_")


def is_batter_market(market: Any) -> bool:
    return str(market or "").strip().lower().startswith("batter_")


class StatsApi:
    """GETs through a per-day disk cache. `fetch` is injectable for tests."""

    def __init__(self, cache_dir: Path | None, fetch: Callable[[str], Any] | None = None):
        self.cache_dir = cache_dir
        self.fetch = fetch or self._http
        self.calls = 0

    @staticmethod
    def _http(url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "Syndicate cheat sheets"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)

    def get(self, path: str) -> Any:
        url = f"{STATSAPI}/{path}"
        hit = None
        if self.cache_dir is not None:
            hit = self.cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.json"
            if hit.is_file():
                try:
                    return json.loads(hit.read_text(encoding="utf-8"))
                except ValueError:
                    pass
        self.calls += 1
        try:
            doc = self.fetch(url)
        except Exception:  # noqa: BLE001 -- a missing matchup is a blank cell, never a failed sheet
            return None
        if hit is not None and doc is not None:
            hit.parent.mkdir(parents=True, exist_ok=True)
            hit.write_text(json.dumps(doc), encoding="utf-8")
        return doc


def slate(api: StatsApi, date: str) -> list[dict[str, Any]]:
    doc = api.get(f"schedule?sportId=1&date={date}&hydrate=probablePitcher") or {}
    games = []
    for day in doc.get("dates") or []:
        for g in day.get("games") or []:
            sides = {}
            for side in ("home", "away"):
                t = (g.get("teams") or {}).get(side) or {}
                sp = t.get("probablePitcher") or {}
                sides[side] = {"team_id": (t.get("team") or {}).get("id"), "team": (t.get("team") or {}).get("name"),
                               "pitcher_id": sp.get("id"), "pitcher": sp.get("fullName")}
            games.append({"game_pk": g.get("gamePk"), **sides})
    return games


def roster(api: StatsApi, team_id: Any) -> dict[str, dict[str, Any]]:
    """normalized name -> {id, name, position}; a name on two players of one roster is dropped (never guessed)."""
    doc = api.get(f"teams/{team_id}/roster?rosterType=active") or {}
    out: dict[str, dict[str, Any]] = {}
    clash: set[str] = set()
    for entry in doc.get("roster") or []:
        person = entry.get("person") or {}
        key = _norm(person.get("fullName"))
        if not key or key in clash:
            continue
        if key in out:
            clash.add(key)
            out.pop(key, None)
            continue
        out[key] = {"id": person.get("id"), "name": person.get("fullName"),
                    "position": ((entry.get("position") or {}).get("abbreviation"))}
    return out


_STAT_KEYS = ("plateAppearances", "atBats", "hits", "doubles", "triples", "homeRuns", "strikeOuts", "baseOnBalls")


def career_vs(api: StatsApi, batter_id: Any, pitcher_id: Any) -> dict[str, Any] | None:
    doc = api.get(f"people/{batter_id}/stats?stats=vsPlayer&opposingPlayerId={pitcher_id}&group=hitting&sportId=1") or {}
    for block in doc.get("stats") or []:
        if (block.get("type") or {}).get("displayName") == "vsPlayerTotal":
            for split in block.get("splits") or []:
                st = split.get("stat") or {}
                if int(st.get("plateAppearances") or 0) > 0:
                    return {k: int(st.get(k) or 0) for k in _STAT_KEYS} | {"avg": st.get("avg"), "ops": st.get("ops")}
    return None


def summarize(line: Mapping[str, Any]) -> str:
    """'4-for-12, 2 HR, 4 K, 2 BB (15 PA)'"""
    parts = [f"{line['hits']}-for-{line['atBats']}"]
    if line.get("homeRuns"):
        parts.append(f"{line['homeRuns']} HR")
    parts.append(f"{line.get('strikeOuts', 0)} K")
    if line.get("baseOnBalls"):
        parts.append(f"{line['baseOnBalls']} BB")
    return ", ".join(parts) + f" ({line['plateAppearances']} PA)"


def _combine(lines: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    lines = [ln for ln in lines if ln]
    if not lines:
        return None
    total = {k: sum(int(ln.get(k) or 0) for ln in lines) for k in _STAT_KEYS}
    ab = total["atBats"] or 0
    total["avg"] = f"{total['hits'] / ab:.3f}".lstrip("0") if ab else None
    total["k_rate"] = round(total["strikeOuts"] / total["plateAppearances"], 3) if total["plateAppearances"] else None
    total["hitters"] = len(lines)
    return total


def matchups(rows: list[dict[str, Any]], *, date: str, api: StatsApi) -> dict[tuple[str, str], dict[str, Any]]:
    """(normalized player, market) -> the player-vs-player block for that sheet row.

    The player's game is found by name inside the two rosters of each scheduled game; the side he is on decides the
    opposing probable starter. No starter announced -> no batter block (a TBD starter is not a matchup)."""
    games = slate(api, date)
    rosters: dict[Any, dict[str, dict[str, Any]]] = {}
    for g in games:
        for side in ("home", "away"):
            if g[side]["team_id"] and g[side]["team_id"] not in rosters:
                rosters[g[side]["team_id"]] = roster(api, g[side]["team_id"])
    out: dict[tuple[str, str], dict[str, Any]] = {}
    lineup_cache: dict[tuple[Any, Any], dict[str, Any] | None] = {}
    for r in rows:
        key = _norm(r.get("player"))
        market = str(r.get("market") or "").strip().lower()
        if (key, market) in out or not key:
            continue
        found = None
        for g in games:
            for side, other in (("home", "away"), ("away", "home")):
                who = rosters.get(g[side]["team_id"], {}).get(key)
                if who:
                    found = (g, side, other, who)
                    break
            if found:
                break
        if not found:
            continue
        g, side, other, who = found
        if is_pitcher_market(market):
            opp_team = g[other]["team_id"]
            cache_key = (who["id"], opp_team)
            if cache_key not in lineup_cache:
                hitters = [p for p in rosters.get(opp_team, {}).values() if p.get("position") not in ("P", None)]
                lines = [career_vs(api, h["id"], who["id"]) for h in hitters]
                lineup_cache[cache_key] = _combine(lines)
            agg = lineup_cache[cache_key]
            if agg:
                out[(key, market)] = {"kind": "pitcher_vs_lineup", "opponent": g[other]["team"], "line": agg,
                                      "summary": f"{g[other]['team']} hitters {agg['hits']}-for-{agg['atBats']}, "
                                                 f"{agg['homeRuns']} HR, {round(100 * (agg['k_rate'] or 0))}% K "
                                                 f"({agg['plateAppearances']} PA, {agg['hitters']} hitters)"}
        elif is_batter_market(market):
            pitcher_id, pitcher = g[other]["pitcher_id"], g[other]["pitcher"]
            if not pitcher_id:
                continue
            line = career_vs(api, who["id"], pitcher_id)
            out[(key, market)] = {"kind": "batter_vs_pitcher", "opponent": pitcher, "line": line,
                                  "summary": summarize(line) if line else f"never faced {pitcher}"}
    return out
