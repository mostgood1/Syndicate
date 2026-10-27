"""High-hit-rate NFL same-game parlays from EVERY priced alt rung (lane `nfl-sgp-builder`, user 2026-10-17: "once NHL is
up and running we need NFL to function the same way" -- after "use the consistency sheets to build them so we can
deliver high hit rates, not long shots", "Two tiers", long shots "Off the sheet").

The NHL design (`syndicate.features.nhl.sgp_pool`, the shared half in `syndicate.features.shared.sgp_hit_rate`) with
NFL's own three reads:

  market   the books' median price on the alt rung, de-vigged by the market's typical main-line margin
  record   the player's last 10 played games before this week (`nfl_fantasy_usage_<season>.json`, four seasons)
  sim      the engine's P(over) -- Normal on its projected mean and spread (`nfl_prop_projections_<season>_wk<week>.json`)

A player must be ACTIVE on the nflverse roster and not Out / Doubtful on the week's injury report (a ruled-out player's
rung can sit on a book for hours). Every leg carries the gsis id, so the reconcile grades it from the usage file even
when the sheet never graded that player (`leg_actuals`).
"""
from __future__ import annotations

import collections
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.nfl import sgp as core
from syndicate.features.shared import sgp_hit_rate as shared

NFL_DIR = Path("nfl_source")
# sheet market -> (usage column(s), sim stat)
STATS: dict[str, tuple[tuple[str, ...], str]] = {
    "Passing Yards": (("pass_yards",), "passing_yards"), "Passing Attempts": (("pass_attempts",), "passing_attempts"),
    "Passing TDs": (("pass_tds",), "passing_tds"), "Interceptions": (("interceptions",), "interceptions"),
    "Rushing Yards": (("rush_yards",), "rushing_yards"), "Rushing Attempts": (("carries",), "rushing_attempts"),
    "Receptions": (("receptions",), "receptions"), "Receiving Yards": (("rec_yards",), "receiving_yards"),
}
USAGE_SEASONS = 4
OUT_STATUSES = frozenset({"Out", "Doubtful"})


def _alt_market() -> dict[str, str]:
    from syndicate.features.shared.alt_consistency import ALT_TO_SHEET

    return dict(ALT_TO_SHEET["nfl"])


def _canon(team: Any) -> str | None:
    from syndicate.features.shared.team_aliases import canonical_team

    return canonical_team("nfl", team) if team else None


def _full(name: Any) -> str:
    """'Brian Thomas Jr.' / 'Brian Thomas Jr' / 'brian thomas' -> 'brianthomas'."""
    import re

    parts = [p for p in re.split(r"[\s.]+", str(name or "").lower().replace("'", "")) if p and p not in core._SUFFIX]
    return re.sub(r"[^a-z]", "", "".join(parts))


def season_of(day: str) -> int:
    return int(day[:4]) if int(day[5:7]) >= 8 else int(day[:4]) - 1


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def week_of(data_root: Path, day: str) -> int | None:
    """The NFL week with a game on `day` (schedule_<season>.csv gameday is the Eastern date, same as Central)."""
    for row in _read_csv(Path(data_root) / NFL_DIR / f"schedule_{season_of(day)}.csv"):
        if row.get("gameday") == day and str(row.get("game_type") or "REG") in ("REG", "WC", "DIV", "CON", "SB"):
            try:
                return int(row.get("week") or "")
            except ValueError:
                return None
    return None


def normal_over(mean: float | None, sd: float | None, line: float) -> float | None:
    if mean is None or not sd or sd <= 0:
        return None
    return 0.5 * math.erfc((line - mean) / (sd * math.sqrt(2.0)))


# ----------------------------------------------------------------------------- the game log
class GameLog:
    """Every game line per gsis id from the usage files (this season and the three before), newest first."""

    def __init__(self, lines: Iterable[Mapping[str, Any]]):
        games: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
        for line in lines:
            pid, gid = str(line.get("player_id") or ""), str(line.get("game_id") or "")
            if pid and gid:
                games[pid].setdefault(gid, dict(line))
        self.games = {pid: sorted(g.values(), key=lambda l: (int(l.get("season") or 0), int(l.get("week") or 0)), reverse=True)
                      for pid, g in games.items()}

    @classmethod
    def load(cls, data_root: Path, season: int) -> "GameLog":
        lines: list[dict[str, Any]] = []
        for year in range(season, season - USAGE_SEASONS, -1):
            try:
                payload = json.loads((Path(data_root) / NFL_DIR / "fantasy" / f"nfl_fantasy_usage_{year}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            lines += [l for l in payload.get("player_game_lines") or [] if isinstance(l, dict)]
        return cls(lines)

    @staticmethod
    def _value(line: Mapping[str, Any], market: str) -> float | None:
        cols = STATS[market][0]
        try:
            return sum(float(line.get(c) or 0.0) for c in cols)
        except (TypeError, ValueError):
            return None

    def values(self, pid: str, market: str, *, before: tuple[int, int], n: int = shared.LEG_GAMES) -> list[tuple[str, float]]:
        """(game_id, stat) for the player's last `n` games before (season, week), newest first."""
        out: list[tuple[str, float]] = []
        for line in self.games.get(pid) or []:
            if (int(line.get("season") or 0), int(line.get("week") or 0)) >= before:
                continue
            value = self._value(line, market)
            if value is None:
                continue
            out.append((str(line.get("game_id")), value))
            if len(out) >= n:
                break
        return out

    def actual(self, pid: str, market: str, season: int, week: int) -> float | None:
        for line in self.games.get(pid) or []:
            if int(line.get("season") or 0) == season and int(line.get("week") or 0) == week:
                return self._value(line, market)
        return None


# ----------------------------------------------------------------------------- the roster, injuries, the sim
class Roster:
    """name key -> this season's players (each one's latest roster week): gsis id, team, status, position, headshot."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]):
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            gsis = str(row.get("gsis_id") or "").strip()
            if not gsis:
                continue
            try:
                week = int(row.get("week") or 0)
            except ValueError:
                week = 0
            if gsis not in latest or week >= latest[gsis]["_week"]:
                latest[gsis] = dict(row, _week=week)
        self.by_key: dict[tuple, list[dict[str, Any]]] = collections.defaultdict(list)
        for row in latest.values():
            key = core.name_key(row.get("full_name"))
            if key:
                self.by_key[key].append(row)

    @classmethod
    def load(cls, data_root: Path, season: int) -> "Roster":
        return cls(_read_csv(Path(data_root) / NFL_DIR / "tracking" / "nflverse" / "roster" / f"roster_{season}.csv"))

    def resolve(self, name: Any, clubs: Iterable[Any]) -> dict[str, Any] | None:
        """The one ACTIVE-or-not player in tonight's game with this name. Initial + surname first; when that is shared
        (measured 10-18: Bijan and Brian Robinson, both ATL; Bryce Young CAR vs Byron Young LA in one game), the full
        name decides, suffixes and punctuation aside. Still two -> None: a wrong player's record is worse than none."""
        wanted = {_canon(c) for c in clubs} - {None}
        hits = [r for r in self.by_key.get(core.name_key(name) or ("", ""), []) if _canon(r.get("team")) in wanted]
        if len(hits) > 1:
            hits = [r for r in hits if _full(r.get("full_name")) == _full(name)]
        return hits[0] if len(hits) == 1 else None


def ruled_out(data_root: Path, season: int, week: int) -> set[str]:
    path = Path(data_root) / NFL_DIR / "tracking" / "nflverse" / "injuries" / f"injuries_{season}.csv"
    return {str(r.get("gsis_id") or "") for r in _read_csv(path)
            if str(r.get("week") or "") == str(week) and str(r.get("report_status") or "").strip() in OUT_STATUSES}


def sim_params(data_root: Path, season: int, week: int) -> dict[tuple[tuple[str, str], str], tuple[float, float]]:
    """(name key, sim stat) -> (projected mean, spread) from THIS week's prop artifact; an older week's is not used
    (a different opponent), so a week with no artifact vetoes every leg."""
    path = Path(data_root) / NFL_DIR / f"nfl_prop_projections_{season}_wk{week}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[tuple[tuple[str, str], str], tuple[float, float]] = {}
    for row in payload.get("sim_rows") or []:
        if not isinstance(row, dict):
            continue
        parts = str(row.get("market") or "").split("::")
        key = core.name_key(row.get("entity") or (parts[1] if len(parts) > 1 else ""))
        try:
            mean, sd = float(row.get("projected_value")), float(row.get("projected_sd"))
        except (TypeError, ValueError):
            continue
        if key and sd > 0:
            out.setdefault((key, parts[0]), (mean, sd))
    return out


# ----------------------------------------------------------------------------- the legs
def legs_by_game(sheet: Mapping[str, Any], data_root: Path, day: str, roles: Mapping[tuple[str, tuple[str, str]], str], *,
                 log: GameLog | None = None, roster: Roster | None = None, alt_rows: Iterable[Mapping[str, Any]] | None = None,
                 sims: Mapping | None = None, out_ids: set[str] | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict]:
    """Every rung that passes all three reads, per game; and the counts behind it (what each gate removed)."""
    from syndicate.features.shared import alt_consistency as ac

    counts: collections.Counter = collections.Counter()
    week = week_of(data_root, day)
    if week is None:
        return {}, {"counts": {"no_nfl_week": 1}, "games": {}}
    season = season_of(day)
    log = log if log is not None else GameLog.load(data_root, season)
    roster = roster if roster is not None else Roster.load(data_root, season)
    alt_rows = list(alt_rows) if alt_rows is not None else ac.load_alt_rows(data_root, "nfl", day)
    sims = sims if sims is not None else sim_params(data_root, season, week)
    out_ids = out_ids if out_ids is not None else ruled_out(data_root, season, week)
    margins = shared.margins(sheet)
    rungs, games = shared.alt_rungs(alt_rows, _alt_market())
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for (event, player, market), ladder in rungs.items():
        if market not in STATS:
            continue
        game = games.get(event) or {}
        counts["player_stats"] += 1
        who = roster.resolve(player, (game.get("home"), game.get("away")))
        if who is None:
            counts["no_roster_match"] += 1
            continue
        gsis = str(who.get("gsis_id"))
        if str(who.get("status") or "").upper() != "ACT" or gsis in out_ids:
            counts["not_active"] += 1
            continue
        history = log.values(gsis, market, before=(season, week))
        if len(history) < shared.LEG_GAMES:
            counts["short_history"] += 1
            continue
        key = core.name_key(player)
        mean_sd = sims.get((key, STATS[market][1])) if key else None
        team = str(who.get("team") or "")
        role = roles.get((core._TEAM_TO_PBP.get(team, team), key), "UNK") if key else "UNK"
        factor = margins.get(market) or margins["*"]
        for rung, books in ladder.items():
            counts["rungs"] += 1
            p_market = shared.market_prob(books, factor)
            hits = sum(1 for _g, v in history if v > rung)
            p_sim = normal_over(mean_sd[0], mean_sd[1], rung) if mean_sd else None
            if not shared.gate(p_market, hits, p_sim, counts):
                continue
            p_leg = shared.leg_prob(p_market, hits, len(history))
            counts["legs"] += 1
            out[event].append({
                "player": player, "team": team, "market": market, "side": "over", "line": rung,
                "p_over": p_leg, "p_side": p_leg, "type": f"{market}|{role}", "role": role, "prices": dict(books),
                "event_id": event, "p_market": round(p_market, 4), "p_sim": round(p_sim, 4), "hits": hits,
                "games": len(history), "alt": True, "player_id": gsis, "_history": history,
                "pos": who.get("position"), "headshot_url": who.get("headshot_url")})
    return shared.cap(out), {"counts": dict(counts), "games": games, "week": week}


def tickets(pool: Mapping[str, list[dict[str, Any]]], cells: Mapping[str, Any], games: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return shared.tickets(pool, cells, games)


# ----------------------------------------------------------------------------- grading
ANYTIME_TD = "Anytime TD"


def touchdowns(log: GameLog, pid: str, season: int, week: int) -> float | None:
    """Rushing + receiving TDs in that week's game -- what an anytime-TD leg pays on (the usage lines carry no return
    TDs, which are rare)."""
    for line in log.games.get(pid) or []:
        if int(line.get("season") or 0) == season and int(line.get("week") or 0) == week:
            try:
                return float(line.get("rush_tds") or 0.0) + float(line.get("rec_tds") or 0.0)
            except (TypeError, ValueError):
                return None
    return None


def leg_actuals(data_root: Path, day: str, tickets_: Iterable[Mapping[str, Any]], *, log: GameLog | None = None,
                roster: Roster | None = None) -> dict[str, float]:
    """`prop_result_key` prefix (player|market) -> the player's stat in `day`'s week, from the usage file, for every
    leg -- the legs the sheet itself never graded. A leg without a gsis id (the correlation family, built off the
    sheet's rows) is resolved by name and its own team through the roster; anytime-TD legs read the week's TDs.
    Measured 2026-10-27 (todo #743): every pending NFL ledger leg had no id, and 20 of the 27 were anytime TDs."""
    from syndicate.features.shared.cheat_sheets import prop_result_key

    week = week_of(data_root, day)
    if week is None:
        return {}
    season = season_of(day)
    log = log if log is not None else GameLog.load(data_root, season)
    out: dict[str, float] = {}
    for t in tickets_:
        for leg in t.get("legs") or []:
            market = str(leg.get("market") or "")
            if market not in STATS and market != ANYTIME_TD:
                continue
            pid = str(leg.get("player_id") or "")
            if not pid and leg.get("team"):
                roster = roster if roster is not None else Roster.load(data_root, season)
                pid = str((roster.resolve(leg.get("player"), (leg.get("team"),)) or {}).get("gsis_id") or "")
            if not pid:
                continue
            value = touchdowns(log, pid, season, week) if market == ANYTIME_TD else log.actual(pid, market, season, week)
            if value is not None:
                parts = prop_result_key(leg).split("|")
                out[f"{parts[0]}|{parts[1]}"] = value
    return out
