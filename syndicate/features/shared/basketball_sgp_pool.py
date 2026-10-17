"""High-hit-rate WNBA / NBA same-game parlays from every priced alt rung (lane `basketball-sgp-builder`, user 2026-10-17:
"we need sgp work done for alll sports - wnba needs all the same work done as NHL").

The NHL design (`syndicate.features.nhl.sgp_pool`; the shared gate, tiers and search in
`syndicate.features.shared.sgp_hit_rate`) with basketball's own three reads:

  market   the books' median price on the alt rung, de-vigged by the market's typical main-line margin
  record   the player's last 10 played games before today (`player_game_log_<season>.csv`, regular + playoffs)
  sim      the engine's P(over) -- Normal on its per-player mean and spread (`cards_sim_detail_<date>.json`); a combo
           (PRA, P+R, P+A, R+A) sums the parts' means and their variances (ASSUMES the parts independent, so its spread
           is too narrow where they move together -- the sim is a veto here, not a driver)

A player must be in tonight's sim with >= MIN_SIM_MINUTES projected minutes (the sim drops the injured and the
inactive). Roles are minutes ranks over the team's last ROLE_WINDOW games (S1-S5, B1-B3), the cells' role names.
Nested same-player pairs (a stat and a combo that contains it) are never a ticket.
"""
from __future__ import annotations

import collections
import csv
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared import sgp_hit_rate as shared

SHEET_TO_CODE = {"player_points": "PTS", "player_rebounds": "REB", "player_assists": "AST", "player_threes": "FG3M",
                 "player_points_rebounds_assists": "PRA", "player_points_rebounds": "PR", "player_points_assists": "PA",
                 "player_rebounds_assists": "RA"}
PARTS = {"PTS": ("PTS",), "REB": ("REB",), "AST": ("AST",), "FG3M": ("FG3M",), "PRA": ("PTS", "REB", "AST"),
         "PR": ("PTS", "REB"), "PA": ("PTS", "AST"), "RA": ("REB", "AST")}
SIM_KEY = {"PTS": "pts", "REB": "reb", "AST": "ast", "FG3M": "threes"}
NESTED = frozenset(frozenset({a, b}) for a in PARTS for b in PARTS if a != b and set(PARTS[a]) <= set(PARTS[b]))
# Two combos of one player that share a part are near-duplicate bets (2026-10-17 basketball study, real lines: same
# player P+A x P+R +0.92 NBA / +0.91 WNBA, P+R x R+A +0.48): never one ticket either.
NEAR_DUPLICATE = frozenset(frozenset({a, b}) for a in ("PR", "PA", "RA") for b in ("PR", "PA", "RA") if a != b)
LABEL = {"player_points": "points", "player_rebounds": "rebounds", "player_assists": "assists", "player_threes": "threes",
         "player_points_rebounds_assists": "pts+reb+ast", "player_points_rebounds": "pts+reb", "player_points_assists": "pts+ast",
         "player_rebounds_assists": "reb+ast"}
MIN_SIM_MINUTES = 12.0
ROLE_WINDOW = 8
ROLES = ("S1", "S2", "S3", "S4", "S5", "B1", "B2", "B3")
LOG_SEASONS = 4
STALE_LOG_DAYS = 3


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z]", "", str(name or "").lower().replace(" jr", "").replace(" sr", "").replace(" iii", "").replace(" ii", ""))


def _canon(sport: str, team: Any) -> str | None:
    from syndicate.features.shared.team_aliases import canonical_team

    return canonical_team(sport, team) if team else None


def _num(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    if ":" in text:                                     # "34:12" minutes
        mins, secs = text.split(":", 1)
        try:
            return float(mins) + float(secs) / 60.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _processed(data_root: Path, sport: str) -> list[Path]:
    root = Path(data_root) / f"{sport}_source"
    return [root / "data" / "processed", root / "source_artifacts" / "data" / "processed"]


def normal_over(mean: float | None, sd: float | None, line: float) -> float | None:
    if mean is None or not sd or sd <= 0:
        return None
    return 0.5 * math.erfc((line - mean) / (sd * math.sqrt(2.0)))


# ----------------------------------------------------------------------------- the game log
class GameLog:
    """Every played regular-season / playoff game per player (preseason is another population), newest first."""

    def __init__(self, rows: Iterable[Mapping[str, Any]], sport: str):
        self.sport = sport
        games: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
        self.last_date = ""
        for row in rows:
            pid, gid = str(row.get("PLAYER_ID") or "").strip(), str(row.get("game_id") or "").strip()
            kind = str(row.get("season_type") or "").lower()
            if not pid or not gid or "pre" in kind:
                continue
            minutes = _num(row.get("MIN"))
            if not minutes:
                continue
            games[pid].setdefault(gid, dict(row, _min=minutes))
            self.last_date = max(self.last_date, str(row.get("date") or "")[:10])
        self.games = {pid: sorted(g.values(), key=lambda r: str(r.get("date") or ""), reverse=True) for pid, g in games.items()}
        self.by_name: dict[str, list[str]] = collections.defaultdict(list)
        self.by_team: dict[str, dict[str, list[tuple[str, float, str]]]] = collections.defaultdict(lambda: collections.defaultdict(list))
        for pid, rows_ in self.games.items():
            self.by_name[_norm(rows_[0].get("PLAYER_NAME"))].append(pid)
            for r in rows_:
                self.by_team[str(r.get("TEAM_ABBREVIATION") or "")][str(r.get("game_id"))].append((pid, r["_min"], str(r.get("date") or "")[:10]))

    @classmethod
    def load(cls, data_root: Path, sport: str) -> "GameLog":
        seen: dict[str, Path] = {}
        for folder in _processed(data_root, sport):
            for path in sorted(folder.glob("player_game_log_????.csv"), reverse=True):
                seen.setdefault(path.name, path)
        rows: list[dict[str, Any]] = []
        for name in sorted(seen, reverse=True)[:LOG_SEASONS]:
            try:
                with open(seen[name], encoding="utf-8") as fh:
                    rows.extend(csv.DictReader(fh))
            except OSError:
                continue
        return cls(rows, sport)

    def team_of(self, pid: str) -> str:
        rows = self.games.get(pid) or []
        return str(rows[0].get("TEAM_ABBREVIATION") or "") if rows else ""

    def resolve(self, name: Any, clubs: Iterable[Any]) -> str | None:
        wanted = {_canon(self.sport, c) for c in clubs} - {None}
        hits = [pid for pid in self.by_name.get(_norm(name), []) if _canon(self.sport, self.team_of(pid)) in wanted]
        return hits[0] if len(hits) == 1 else None

    def _value(self, row: Mapping[str, Any], code: str) -> float | None:
        total = 0.0
        for part in PARTS[code]:
            v = _num(row.get(part))
            if v is None:
                return None
            total += v
        return total

    def values(self, pid: str, code: str, *, before: str, n: int = shared.LEG_GAMES) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        for row in self.games.get(pid) or []:
            if str(row.get("date") or "")[:10] >= before:
                continue
            v = self._value(row, code)
            if v is None:
                continue
            out.append((str(row.get("game_id")), v))
            if len(out) >= n:
                break
        return out

    def actual(self, pid: str, code: str, day: str) -> float | None:
        for row in self.games.get(pid) or []:
            if str(row.get("date") or "")[:10] == day:
                return self._value(row, code)
        return None

    def roles(self, team: str, *, before: str) -> dict[str, str]:
        """pid -> S1..S5 / B1..B3 by average minutes over the team's last ROLE_WINDOW games before `before`."""
        games = sorted(((gid, players) for gid, players in (self.by_team.get(team) or {}).items()
                        if players and players[0][2] < before), key=lambda x: x[1][0][2], reverse=True)[:ROLE_WINDOW]
        if not games:
            return {}
        minutes: dict[str, float] = collections.defaultdict(float)
        for _gid, players in games:
            for pid, mins, _d in players:
                minutes[pid] += mins
        ranked = sorted(minutes, key=lambda p: -minutes[p])
        return {pid: role for pid, role in zip(ranked, ROLES)}


# ----------------------------------------------------------------------------- the sim
def sim_players(data_root: Path, sport: str, day: str) -> dict[str, dict[str, Any]]:
    """normalized name -> the sim's player block for `day` (every game in cards_sim_detail_<day>.json)."""
    for folder in _processed(data_root, sport):
        path = folder / f"cards_sim_detail_{day}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out: dict[str, dict[str, Any]] = {}
        for game in payload.get("games") or []:
            players = ((game.get("sim") or {}).get("players") or {})
            for side in ("home", "away"):
                for p in players.get(side) or []:
                    if isinstance(p, dict) and p.get("player_name"):
                        out.setdefault(_norm(p["player_name"]), p)
        return out
    return {}


def sim_over(player: Mapping[str, Any] | None, code: str, rung: float) -> float | None:
    if not player:
        return None
    mean = var = 0.0
    for part in PARTS[code]:
        key = SIM_KEY[part]
        m, s = player.get(f"{key}_mean"), player.get(f"{key}_sd")
        if m is None or s is None:
            return None
        mean += float(m)
        var += float(s) ** 2
    return normal_over(mean, math.sqrt(var), rung)


# ----------------------------------------------------------------------------- the legs
def legs_by_game(sheet: Mapping[str, Any], data_root: Path, day: str, sport: str, *, log: GameLog | None = None,
                 sims: Mapping[str, Mapping[str, Any]] | None = None,
                 alt_rows: Iterable[Mapping[str, Any]] | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict]:
    """Every rung that passes all three reads, per game; and the counts behind it (what each gate removed)."""
    from syndicate.features.shared import alt_consistency as ac

    log = log if log is not None else GameLog.load(data_root, sport)
    sims = sims if sims is not None else sim_players(data_root, sport, day)
    alt_rows = list(alt_rows) if alt_rows is not None else ac.load_alt_rows(data_root, sport, day)
    margins = shared.margins(sheet)
    rungs, games = shared.alt_rungs(alt_rows, {k: k for k in SHEET_TO_CODE})
    faces: dict[str, dict[str, Any]] = {}
    for src in list(sheet.get("ladders") or []) + list(sheet.get("rows") or []):
        faces.setdefault(_norm(src.get("player")), {k: src.get(k) for k in ("headshot_src", "headshot_url", "team_logo_src",
                                                                             "team_logo", "team_name", "pos") if src.get(k)})
    counts: collections.Counter = collections.Counter()
    role_cache: dict[str, dict[str, str]] = {}
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for (event, player, market), ladder in rungs.items():
        code = SHEET_TO_CODE[market]
        game = games.get(event) or {}
        counts["player_stats"] += 1
        sim = sims.get(_norm(player))
        if not sim or float(sim.get("min_mean") or 0) < MIN_SIM_MINUTES:
            counts["not_in_sim"] += 1
            continue
        pid = log.resolve(player, (game.get("home"), game.get("away")))
        if pid is None:
            counts["no_game_log"] += 1
            continue
        history = log.values(pid, code, before=day)
        if len(history) < shared.LEG_GAMES:
            counts["short_history"] += 1
            continue
        team = log.team_of(pid)
        if team not in role_cache:
            role_cache[team] = log.roles(team, before=day)
        role = role_cache[team].get(pid, "UNK")
        factor = margins.get(market) or margins["*"]
        for rung, books in ladder.items():
            counts["rungs"] += 1
            p_market = shared.market_prob(books, factor)
            hits = sum(1 for _g, v in history if v > rung)
            p_sim = sim_over(sim, code, rung)
            if not shared.gate(p_market, hits, p_sim, counts):
                continue
            p_leg = shared.leg_prob(p_market, hits, len(history))
            counts["legs"] += 1
            out[event].append({
                "player": player, "team": team, "market": market, "market_label": LABEL.get(market, market),
                "side": "over", "line": rung,
                "p_over": p_leg, "p_side": p_leg, "type": f"{code}|{role}", "role": role, "prices": dict(books),
                "event_id": event, "p_market": round(p_market, 4), "p_sim": round(p_sim, 4), "hits": hits,
                "games": len(history), "alt": True, "player_id": pid, "_history": history,
                **faces.get(_norm(player), {})})
    info = {"counts": dict(counts), "games": games, "log_last_date": log.last_date}
    if log.last_date and log.last_date < _days_before(day, STALE_LOG_DAYS):
        info["stale_log"] = True                    # the record misses the latest games: say so, never hide it
    return shared.cap(out), info


def _days_before(day: str, n: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


def exclude(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """A stat and a combo containing it, same player (points + PRA): one implies much of the other."""
    if a["player"] != b["player"]:
        return False
    pair = frozenset({str(a["type"]).split("|")[0], str(b["type"]).split("|")[0]})
    return pair in NESTED or pair in NEAR_DUPLICATE


def tickets(pool: Mapping[str, list[dict[str, Any]]], cells: Mapping[str, Any], games: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return shared.tickets(pool, cells, games, exclude=exclude)


# ----------------------------------------------------------------------------- the sheet's hooks
def load_cells(data_root: Path, sport: str) -> dict[str, Any] | None:
    try:
        return json.loads((Path(data_root) / f"{sport}_source" / "sgp" / f"{sport}_sgp_correlations.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def for_sport(sport: str) -> SimpleNamespace:
    """The module shape `build_cheat_sheets.attach_sgp` calls (load_cells / current_roles / suggest)."""
    def suggest(sheet, cells, roles, *, data_root=None, day=None, **_kw):
        if not cells or data_root is None or not day:
            return []
        pool, info = legs_by_game(sheet, data_root, day, sport)
        if info.get("stale_log"):
            print(f"CHEAT_SHEET {sport} sgp: the game log ends {info.get('log_last_date')} -- records miss the latest games",
                  flush=True)
        return tickets(pool, cells, sheet.get("games") or [])

    return SimpleNamespace(load_cells=lambda data_root: load_cells(data_root, sport),
                           current_roles=lambda data_root, day: {}, suggest=suggest)


# ----------------------------------------------------------------------------- grading
def leg_actuals(data_root: Path, day: str, tickets_: Iterable[Mapping[str, Any]], *, sport: str,
                log: GameLog | None = None) -> dict[str, float]:
    from syndicate.features.shared.cheat_sheets import prop_result_key

    log = log if log is not None else GameLog.load(data_root, sport)
    out: dict[str, float] = {}
    for t in tickets_:
        for leg in t.get("legs") or []:
            pid, market = str(leg.get("player_id") or ""), str(leg.get("market") or "")
            if not pid or market not in SHEET_TO_CODE:
                continue
            value = log.actual(pid, SHEET_TO_CODE[market], day)
            if value is not None:
                parts = prop_result_key(leg).split("|")
                out[f"{parts[0]}|{parts[1]}"] = value
    return out
