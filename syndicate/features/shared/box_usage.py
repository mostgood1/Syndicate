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
  NFL  the nflverse play-by-play already on the data root (`nfl_source/tracking/nflverse/pbp/pbp_<season>.csv`,
       refreshed daily) -> TARGETS for a receiving prop, CARRIES for a rushing prop, PASS ATTEMPTS (sacks out) for a
       passing prop; the usual from the season's earlier games. No network.
  NBA / WNBA  Syndicate's own player game logs on the data root (`<league>_source/data/processed/player_game_log_<season
       >.csv`) -> MINUTES (2026-10-22: NBA prop losses carried no usage at all, 0 of 63). The usual comes from the SAME
       phase as the graded game -- regular vs playoffs are different populations and are never mixed; a playoff game with
       under three playoff games before it falls back to the regular season. No network.

The usual is the mean over the `USUAL_GAMES` games before the graded one, across the season boundary (early in a
season a player has three or four games). Every miss is reported as None -- a blank line on the card, never a guess.
"""
from __future__ import annotations

import re
import statistics
from functools import lru_cache
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


_NFL_METRICS = (("recei", "Targets", "target", "receiver_player_name", "target"),
                ("reception", "Targets", "target", "receiver_player_name", "target"),
                ("rush", "Carries", "carry", "rusher_player_name", "carry"),
                ("pass", "Pass attempts", "pass attempt", "passer_player_name", "attempt"))
_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}


def _nfl_key(name: Any) -> tuple[str, str] | None:
    """First initial + last name: 'Tory Horton' and nflverse's 'T.Horton' meet here; suffixes dropped."""
    parts = [p for p in re.split(r"[\s.]+", str(name or "").lower().replace("'", "")) if p and p not in _SUFFIX]
    return (parts[0][0], re.sub(r"[^a-z]", "", parts[-1])) if len(parts) >= 2 else None


@lru_cache(maxsize=2)
def _nfl_index(path: str, mtime: float) -> dict[tuple[str, str], dict[str, dict[str, int]]]:
    """(initial, last) -> game_date -> {target, carry, attempt}; ambiguous keys (two players in one game) dropped."""
    import csv

    out: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
    seen: dict[tuple[tuple[str, str], str], set] = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("two_point_attempt") == "1" or not row.get("game_date"):
                continue
            date = row["game_date"]
            for col, kind, cond in (("receiver_player_name", "target", row.get("pass_attempt") == "1"),
                                    ("rusher_player_name", "carry", row.get("rush_attempt") == "1"),
                                    ("passer_player_name", "attempt", row.get("pass_attempt") == "1" and row.get("sack") != "1")):
                key = _nfl_key(row.get(col)) if cond else None
                if key is None:
                    continue
                pid = row.get(col.replace("_name", "_id")) or row.get(col)
                seen.setdefault((key, date), set()).add(pid)
                day = out.setdefault(key, {}).setdefault(date, {"target": 0, "carry": 0, "attempt": 0})
                day[kind] += 1
    for (key, date), ids in seen.items():
        if len(ids) > 1:                                 # two players share the key that day: never guessed
            out.get(key, {}).pop(date, None)
    return out


def nfl_usage(data_root: Path, player: Any, date: str, market: Any) -> dict[str, Any] | None:
    m = str(market or "").lower()
    metric = next((x for x in _NFL_METRICS if x[0] in m), None)
    key = _nfl_key(player)
    if metric is None or key is None or "td" in m.split() or "touchdown" in m:
        return None
    year, month = int(date[:4]), int(date[5:7])
    path = Path(data_root) / "nfl_source" / "tracking" / "nflverse" / "pbp" / f"pbp_{year if month >= 8 else year - 1}.csv"
    if not path.is_file():
        return None
    games = _nfl_index(str(path), path.stat().st_mtime).get(key) or {}
    if date not in games:
        return None
    kind = metric[4]
    before = [games[d][kind] for d in sorted(games, reverse=True) if d < date][:USUAL_GAMES]
    usual = _usual([float(v) for v in before])
    if usual is None:
        return None
    return {"metric": metric[1], "unit": "", "per": metric[2], "actual": float(games[date][kind]), "usual": round(usual, 1),
            "games": len(before), "count": True, "source": "nflverse play-by-play"}


def _hoops_key(name: Any) -> str | None:
    """Full name, lower-cased, punctuation and suffixes dropped ('Kelly Oubre Jr.' == 'kelly oubre')."""
    parts = [p for p in re.sub(r"[^a-z ]", "", str(name or "").lower().replace("-", " ").replace(".", "")).split()
             if p not in _SUFFIX]
    return " ".join(parts) or None


@lru_cache(maxsize=8)
def _hoops_index(path: str, mtime: float) -> dict[str, dict[str, tuple[float, str]]]:
    """player key -> {date: (minutes, season_type)} from one season's game log; `mtime` keys the cache."""
    import csv

    out: dict[str, dict[str, tuple[float, str]]] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            key, day = _hoops_key(row.get("PLAYER_NAME")), str(row.get("date") or "")
            try:
                minutes = float(row.get("MIN"))
            except (TypeError, ValueError):
                continue
            if key and day:
                out.setdefault(key, {})[day] = (minutes, str(row.get("season_type") or "regular").lower())
    return out


def hoops_usage(data_root: Path, league: str, player: Any, date: str) -> dict[str, Any] | None:
    """Minutes in the graded game against the player's usual, from the league's own game logs (any season file that
    exists around the date). None when he has no row that day (did not play) or too few earlier games."""
    key = _hoops_key(player)
    if not key or len(date) < 10:
        return None
    games: dict[str, tuple[float, str]] = {}
    year = int(date[:4])
    for season in (year - 1, year, year + 1):
        path = Path(data_root) / f"{league}_source" / "data" / "processed" / f"player_game_log_{season}.csv"
        if path.is_file():
            games.update(_hoops_index(str(path), path.stat().st_mtime).get(key) or {})
    if date not in games:
        return None
    actual, phase = games[date]
    before = sorted(((d, m, t) for d, (m, t) in games.items() if d < date), reverse=True)
    usual_from = [m for _d, m, t in before if t == phase][:USUAL_GAMES]
    if len(usual_from) < MIN_USUAL_GAMES and phase != "regular":
        usual_from = [m for _d, m, t in before if t == "regular"][:USUAL_GAMES]
    usual = _usual(usual_from)
    if usual is None:
        return None
    return {"metric": "Minutes", "unit": " min", "per": "minute", "actual": round(actual, 1), "usual": round(usual, 1),
            "games": len(usual_from), "source": f"Syndicate {league.upper()} game log"}


def usage_for(card: Mapping[str, Any], item: Mapping[str, Any], *, cache: Path, fetch: Any = None,
              data_root: Path | None = None) -> dict[str, Any] | None:
    """The graded game's usage for a player prop, or None (not a prop, an unsupported sport, a goalie, no id)."""
    sport = str(card.get("sport") or "").lower()
    if (item.get("kind") or "prop") != "prop" or sport not in ("nhl", "mlb", "nfl", "nba", "wnba"):
        return None
    if sport in ("nba", "wnba"):
        try:
            return hoops_usage(Path(data_root), sport, card.get("player") or item.get("player") or item.get("player_name"),
                               str(card.get("date") or "")) if data_root else None
        except Exception:  # noqa: BLE001 -- usage is a line on a card, never a failed grade
            return None
    if sport == "nfl":
        try:
            return nfl_usage(Path(data_root), card.get("player") or item.get("player") or item.get("player_name"),
                             str(card.get("date") or ""), card.get("market")) if data_root else None
        except Exception:  # noqa: BLE001 -- usage is a line on a card, never a failed grade
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
