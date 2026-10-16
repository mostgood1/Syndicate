"""Box-score usage for result cards: the opportunity a player got in the graded game against a usual (lane
`result-cards`, user 2026-10-16: "what REALLY happened in the game that caused the win or loss ie what did we get
wrong").

A prop's miss is either OPPORTUNITY (less or more time than usual) or EFFICIENCY (normal time, a different rate) --
the split the engine can act on: a minutes / ice-time / workload model fixes the first, a rate model the second.
Free, keyless sources the cheat sheets already use (no OddsAPI):

  NHL  api-web.nhle.com `player/{id}/game-log/{season}/2` -> ice time per game (skaters; goalies are left out --
       a goalie's opportunity is the shots he faces, not his minutes)
  MLB  StatsAPI `people/{id}/stats?stats=gameLog&group=hitting|pitching&gameType=R|P` -> plate appearances for a
       batter, batters faced for a pitcher (his usual from STARTS only, when the graded game was a start)

The usual is the mean over the `USUAL_GAMES` games before the graded one, across the season boundary (early in a
season a player has three or four games). Every miss is reported as None -- a blank line on the card, never a guess.
"""
from __future__ import annotations

import re
import statistics
from pathlib import Path
from typing import Any, Mapping

USUAL_GAMES = 10
MIN_USUAL_GAMES = 3


def player_id(sport: str, item: Mapping[str, Any]) -> str | None:
    pid = item.get("player_id")
    if pid not in (None, ""):
        return str(pid)
    url = str(item.get("headshot_url") or "")
    m = re.search(r"/(\d{7})\.png", url) if sport == "nhl" else re.search(r"/people/(\d+)/", url) if sport == "mlb" else None
    return m.group(1) if m else None


def _minutes(toi: Any) -> float | None:
    try:
        m, s = str(toi).split(":")
        return int(m) + int(s) / 60
    except (TypeError, ValueError):
        return None


def _usual(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if len(values) >= MIN_USUAL_GAMES else None


def nhl_usage(api: Any, pid: str, date: str) -> dict[str, Any] | None:
    from syndicate.features.nhl.skater_vs_goalie import game_log, seasons_for

    logs = [g for season in seasons_for(date, 2) for g in game_log(api, pid, season)]
    logs.sort(key=lambda g: str(g.get("gameDate") or ""), reverse=True)
    game = [g for g in logs if g.get("gameDate") == date]
    if len(game) != 1:
        return None
    actual = _minutes(game[0].get("toi"))
    before = [m for m in (_minutes(g.get("toi")) for g in logs if str(g.get("gameDate") or "") < date) if m is not None][:USUAL_GAMES]
    usual = _usual(before)
    if actual is None or usual is None:
        return None
    return {"metric": "Ice time", "unit": " min", "per": "minute", "actual": round(actual, 1), "usual": round(usual, 1),
            "games": len(before), "source": "api-web.nhle.com game log"}


def mlb_usage(api: Any, pid: str, date: str, *, pitcher: bool) -> dict[str, Any] | None:
    group = "pitching" if pitcher else "hitting"
    splits: list[dict[str, Any]] = []
    for game_type in ("R", "P"):
        doc = api.get(f"people/{pid}/stats?stats=gameLog&group={group}&season={date[:4]}&gameType={game_type}") or {}
        for block in doc.get("stats") or []:
            splits.extend(block.get("splits") or [])
    splits.sort(key=lambda s: str(s.get("date") or ""), reverse=True)
    key = "battersFaced" if pitcher else "plateAppearances"
    game = [s for s in splits if s.get("date") == date]
    if len(game) != 1:                                  # no game, or a doubleheader: not guessed
        return None
    stat = game[0].get("stat") or {}
    started = pitcher and int(stat.get("gamesStarted") or 0) == 1
    before = [s for s in splits if str(s.get("date") or "") < date
              and (not started or int((s.get("stat") or {}).get("gamesStarted") or 0) == 1)]
    values = [float((s.get("stat") or {}).get(key)) for s in before if (s.get("stat") or {}).get(key) is not None][:USUAL_GAMES]
    usual, actual = _usual(values), stat.get(key)
    if actual is None or usual is None:
        return None
    return {"metric": "Batters faced" if pitcher else "Plate appearances", "unit": "",
            "per": "batter faced" if pitcher else "plate appearance", "actual": float(actual), "usual": round(usual, 1),
            "games": len(values), "of": "starts" if started else "games", "count": True, "source": "MLB StatsAPI game log"}


def usage_for(card: Mapping[str, Any], item: Mapping[str, Any], *, cache: Path, fetch: Any = None) -> dict[str, Any] | None:
    """The graded game's usage for a player prop, or None (not a prop, an unsupported sport, a goalie, no id)."""
    sport = str(card.get("sport") or "").lower()
    if (item.get("kind") or "prop") != "prop" or sport not in ("nhl", "mlb"):
        return None
    pid, date, market = player_id(sport, item), str(card.get("date") or ""), card.get("market")
    if not pid or not date:
        return None
    folder = Path(cache) / sport / date
    try:
        if sport == "nhl":
            from syndicate.features.nhl.skater_vs_goalie import NhlApi, is_goalie_market

            if is_goalie_market(market):
                return None
            return nhl_usage(NhlApi(folder, fetch=fetch), pid, date)
        from syndicate.features.mlb.batter_vs_pitcher import StatsApi, is_batter_market, is_pitcher_market

        if is_pitcher_market(market):
            return mlb_usage(StatsApi(folder, fetch=fetch), pid, date, pitcher=True)
        if is_batter_market(market):
            return mlb_usage(StatsApi(folder, fetch=fetch), pid, date, pitcher=False)
    except Exception:  # noqa: BLE001 -- usage is a line on a card, never a failed grade
        return None
    return None
