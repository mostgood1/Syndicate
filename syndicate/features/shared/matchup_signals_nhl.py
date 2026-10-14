"""NHL matchup signals: game-log parsing, as-of team / goalie / skater features, the registered rules, the registry.

Lane `signal-engine-nhl` (2026-10-14). Plan: `.syndicate/findings_2026-10-13_matchup_signal_plan.md` §6. Statistics and
the SignalSpec shape are shared with the NBA engine (`matchup_signals.py`).

SOURCES. The NHL web API game logs the fleet already keeps, one schema for both files:
`nhl_source/source_artifacts/data/raw/player_game_log_<YYYYYYYY>.csv` (prior seasons) and `raw/player_game_stats.csv`
(2026-05-01 onward). `gamePk` encodes the game type in digits 5-6 (01 preseason, 02 regular season, 03 playoffs); only
regular-season games feed features or grades -- the phases are different populations. `date` is the game day at 16:00Z,
so `date[:10]` is the Eastern game day. Names are "B. Marchand"; a prop's "Brad Marchand" joins on first initial +
surname, inside the game's two teams.

AS-OF RULE. Features for a game on day D read regular-season games of the SAME season dated before D.
"""
from __future__ import annotations

import ast
import csv
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared.matchup_signals import SignalSpec, norm_player

__all__ = [
    "NHL_MARKET_STATS",
    "THRESHOLDS",
    "NHL_REGISTRY",
    "game_type",
    "name_key",
    "load_game_log",
    "team_games",
    "AsOf",
    "saves_fires",
    "saves_eligible",
    "skater_fires",
    "skater_eligible",
]

# market key in the quote logs / OddsAPI -> game-log stat
NHL_MARKET_STATS = {
    "player_total_saves": "saves", "SAVES": "saves", "player_shots_on_goal": "shots", "SOG": "shots",
    "player_points": "points", "POINTS": "points", "player_assists": "assists", "ASSISTS": "assists",
    "player_goals": "goals", "GOALS": "goals",
}
SKATER_MARKETS = ("shots", "points", "assists", "goals")
MIN_TEAM_GAMES = 5

# The registered thresholds (lane block `signal-engine-nhl`, "NHL v1 PRE-REGISTERED" 2026-10-14T01:16:45Z). RULE as football v1:
# the 10th / 90th percentile of each feature over the DISCOVER population, rounded to one decimal, read from features
# only -- saves: 2025-26 saves main lines before 2025-12-09; skaters: 2025-26 regular-season skater-games of regulars
# (season TOI >= 12 min) and team-games (`grade_nhl_forward.py --mode distributions`). Do not edit after registration.
THRESHOLDS: dict[str, float] = {
    "saves_opp_sf_high": 30.2,  # opponent season-to-date shots for per game >= -> saves OVER   (p90 30.192)
    "saves_opp_sf_low": 23.3,   # <= -> saves UNDER                                              (p10 23.25)
    "saves_sa_trend_up": 3.3,   # own team shots against, last 5 - season >= -> saves OVER       (p90 3.271)
    "toi_up": 2.4,              # skater TOI last 3 - base (minutes) >= -> OVER                  (p90 2.431)
    "toi_down": 2.3,            # <= -2.3 -> UNDER                                               (p10 -2.253)
    "opp_sa_high": 28.7,        # opponent season-to-date shots against per game >= -> SOG OVER  (p90 28.739)
    "opp_sa_low": 23.9,         # <= -> SOG UNDER                                                (p10 23.938)
}


def game_type(game_pk: Any) -> str:
    return str(game_pk or "")[4:6]


def _toi(value: Any) -> float | None:
    text = str(value or "").strip()
    if ":" not in text:
        return None
    mins, _, secs = text.partition(":")
    try:
        return round(int(mins) + int(secs) / 60.0, 3)
    except ValueError:
        return None


def _name(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("{"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, Mapping):
                return str(parsed.get("default") or "")
        except (ValueError, SyntaxError):
            return text
    return text


def name_key(name: Any) -> str:
    """First initial + surname: "Brad Marchand" and "B. Marchand" -> "b marchand"."""
    tokens = norm_player(_name(name)).split()
    if len(tokens) < 2:
        return " ".join(tokens)
    return f"{tokens[0][0]} {' '.join(tokens[1:])}"


def _f(value: Any) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_game_log(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """Rows from the game-log CSVs, deduplicated on (gamePk, player_id); later paths win."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for path in paths:
        if not Path(path).is_file():
            continue
        with Path(path).open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                pk, pid = str(r.get("gamePk") or ""), str(r.get("player_id") or "")
                if len(pk) < 6 or not pid:
                    continue
                goals, assists = _f(r.get("goals")), _f(r.get("assists"))
                rows[(pk, pid)] = {
                    "game": pk, "season": pk[:4], "gtype": game_type(pk), "date": str(r.get("date") or "")[:10],
                    "team": r.get("team") or "", "opponent": r.get("opponent") or "", "player_id": pid,
                    "player": _name(r.get("player")), "key": name_key(r.get("player")),
                    "role": (r.get("role") or "").strip().lower(), "shots": _f(r.get("shots")), "goals": goals,
                    "assists": assists, "points": goals + assists, "toi": _toi(r.get("timeOnIce")),
                    "saves": _f(r.get("saves")), "shots_against": _f(r.get("shotsAgainst")),
                }
    return list(rows.values())


def team_games(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """(game, team) -> {date, season, gtype, opponent, sf, sa}. sf = the team's skater shots; sa = the opponent's sf."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    teams_in: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        teams_in[r["game"]].add(r["team"])
        t = out.setdefault((r["game"], r["team"]), {"date": r["date"], "season": r["season"], "gtype": r["gtype"], "sf": 0.0})
        if r["role"] != "goalie":
            t["sf"] += r["shots"]
    for (game, team), t in out.items():
        others = teams_in[game] - {team}
        t["opponent"] = next(iter(others)) if len(others) == 1 else None
        t["sa"] = out[(game, t["opponent"])]["sf"] if t["opponent"] else None
    return out


def _rest(last: str | None, day: str) -> int | None:
    if not last:
        return None
    return (date.fromisoformat(day) - date.fromisoformat(last)).days


class AsOf:
    """As-of features for any day of one season, from regular-season games dated strictly before it."""

    def __init__(self, rows: Sequence[Mapping[str, Any]]):
        self.rows = [r for r in rows if r["gtype"] == "02"]
        self.by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (_game, team), t in team_games(self.rows).items():
            if t["sa"] is not None:
                self.by_team[team].append(t)
        self.by_player: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in self.rows:
            self.by_player[r["player_id"]].append(r)

    def team(self, team: str, season: str, day: str) -> dict[str, Any] | None:
        games = sorted((t for t in self.by_team.get(team, ()) if t["season"] == season and t["date"] < day),
                       key=lambda t: t["date"])
        if not games:
            return None
        out: dict[str, Any] = {"games": len(games), "rest_days": _rest(games[-1]["date"], day)}
        if len(games) >= MIN_TEAM_GAMES:
            out["sf_pg"] = round(statistics.fmean(t["sf"] for t in games), 3)
            out["sa_pg"] = round(statistics.fmean(t["sa"] for t in games), 3)
            out["sa_l5"] = round(statistics.fmean(t["sa"] for t in games[-5:]), 3)
            out["sa_trend"] = round(out["sa_l5"] - out["sa_pg"], 3) if len(games) >= 2 * MIN_TEAM_GAMES else None
        return out

    def skater(self, player_id: str, season: str, day: str) -> dict[str, Any] | None:
        games = sorted((r for r in self.by_player.get(player_id, ()) if r["season"] == season and r["date"] < day
                        and r["role"] != "goalie" and r["toi"] is not None), key=lambda r: r["date"])
        if not games:
            return None
        tois = [g["toi"] for g in games]
        l3, base = tois[-3:], tois[:-3]
        out = {"games": len(games), "toi_season": round(statistics.fmean(tois), 3),
               "toi_l3": round(statistics.fmean(l3), 3) if len(l3) == 3 else None,
               "toi_base": round(statistics.fmean(base), 3) if len(base) >= 3 else None}
        out["toi_trend"] = round(out["toi_l3"] - out["toi_base"], 3) if out["toi_l3"] is not None and out["toi_base"] is not None else None
        return out


def saves_fires(f: Mapping[str, Any], t: Mapping[str, float] = THRESHOLDS) -> list[str]:
    """f: opp_sf_pg, team_sa_trend, team_rest_days. Unknown inputs and unregistered (0.0) thresholds never fire."""
    fired = []
    sf = f.get("opp_sf_pg")
    if sf is not None and t["saves_opp_sf_high"] > 0 and sf >= t["saves_opp_sf_high"]:
        fired.append("nhl.saves_opp_volume_high")
    if sf is not None and t["saves_opp_sf_low"] > 0 and sf <= t["saves_opp_sf_low"]:
        fired.append("nhl.saves_opp_volume_low")
    trend = f.get("team_sa_trend")
    if trend is not None and t["saves_sa_trend_up"] > 0 and trend >= t["saves_sa_trend_up"]:
        fired.append("nhl.saves_team_leaky")
    if f.get("team_rest_days") == 1:
        fired.append("nhl.saves_team_b2b")
    return fired


def saves_eligible(name: str, f: Mapping[str, Any]) -> bool:
    if name in ("nhl.saves_opp_volume_high", "nhl.saves_opp_volume_low"):
        return f.get("opp_sf_pg") is not None
    if name == "nhl.saves_team_leaky":
        return f.get("team_sa_trend") is not None
    if name == "nhl.saves_team_b2b":
        return f.get("team_rest_days") is not None
    return False


def skater_fires(f: Mapping[str, Any], t: Mapping[str, float] = THRESHOLDS) -> list[str]:
    """f: toi_trend, opp_sa_pg."""
    fired = []
    trend = f.get("toi_trend")
    if trend is not None and t["toi_up"] > 0 and trend >= t["toi_up"]:
        fired.append("nhl.toi_up")
    if trend is not None and t["toi_down"] > 0 and trend <= -t["toi_down"]:
        fired.append("nhl.toi_down")
    sa = f.get("opp_sa_pg")
    if sa is not None and t["opp_sa_high"] > 0 and sa >= t["opp_sa_high"]:
        fired.append("nhl.opp_allows_shots")
    if sa is not None and t["opp_sa_low"] > 0 and sa <= t["opp_sa_low"]:
        fired.append("nhl.opp_suppresses_shots")
    return fired


def skater_eligible(name: str, f: Mapping[str, Any]) -> bool:
    if name in ("nhl.toi_up", "nhl.toi_down"):
        return f.get("toi_trend") is not None
    if name in ("nhl.opp_allows_shots", "nhl.opp_suppresses_shots"):
        return f.get("opp_sa_pg") is not None
    return False


_LOG = "NHL web API game logs (regular season, same season, games before)"
NHL_REGISTRY: dict[str, SignalSpec] = {
    spec.name: spec
    for spec in (
        SignalSpec("nhl.saves_opp_volume_high", "nhl", "over", ("saves",),
                   "The opponent shoots a lot: more shots for the goalie to save.", _LOG,
                   "opponent season-to-date shots for per game >= saves_opp_sf_high (>= 5 games)"),
        SignalSpec("nhl.saves_opp_volume_low", "nhl", "under", ("saves",),
                   "The opponent shoots little.", _LOG, "opponent shots for per game <= saves_opp_sf_low"),
        SignalSpec("nhl.saves_team_leaky", "nhl", "over", ("saves",),
                   "The goalie's own team has been allowing more shots lately.", _LOG,
                   "own team shots against: last 5 - season >= saves_sa_trend_up (>= 10 games)"),
        SignalSpec("nhl.saves_team_b2b", "nhl", "over", ("saves",),
                   "Second night of a back-to-back: tired skaters allow more shots.", _LOG,
                   "the goalie's team played the previous day"),
        SignalSpec("nhl.saves_under_bias", "nhl", "under", ("saves",),
                   "Saves UNDERS priced too long (the NBA / NCAAF pattern).", "saves prop closes",
                   "every main-line saves prop, UNDER side"),
        SignalSpec("nhl.toi_up", "nhl", "over", ("shots", "points"),
                   "Ice time rising: a bigger role than the season shows.", _LOG,
                   "TOI last 3 games - mean of the earlier games (>= 3) >= toi_up minutes"),
        SignalSpec("nhl.toi_down", "nhl", "under", ("shots", "points"),
                   "Ice time falling.", _LOG, "TOI last 3 - base <= -toi_down minutes"),
        SignalSpec("nhl.opp_allows_shots", "nhl", "over", ("shots",),
                   "The opponent allows many shots (props ignore the opponent today).", _LOG,
                   "opponent season-to-date shots against per game >= opp_sa_high"),
        SignalSpec("nhl.opp_suppresses_shots", "nhl", "under", ("shots",),
                   "The opponent suppresses shots.", _LOG, "opponent shots against per game <= opp_sa_low"),
        SignalSpec("nhl.skater_under_bias", "nhl", "under", SKATER_MARKETS,
                   "Skater prop UNDERS priced too long (the NBA / NCAAF pattern).", "skater prop closes",
                   "every main-line two-sided skater prop, UNDER side"),
    )
}


# ----------------------------------------------------------------------------- v1 saves result (2026-10-14)
#
# The registered saves test (`scripts/nhl_saves_lift.py --mode lift`, after the 01:16:45Z registration): all four
# signals NOT SUPPORTED -- underpowered as stated (~25-70 fired lines per window) -- and the saves UNDER tilt is NOT
# there: confirm residual -5.4% [-10.2, -0.4] (the over beat the close Dec-Feb). Tuple: (discover residual, discover n,
# confirm residual, confirm CI, confirm n, confirm games). Skater K1-K5 stay `candidate` until the forward final read.
from dataclasses import replace as _replace  # noqa: E402

_SAVES_V1 = {
    "nhl.saves_opp_volume_high": (0.0354, 31, 0.1057, [-0.0549, 0.2588], 34, 32),
    "nhl.saves_opp_volume_low": (-0.0224, 34, -0.0218, [-0.1735, 0.1438], 40, 39),
    "nhl.saves_team_leaky": (0.0969, 25, 0.1023, [-0.0344, 0.2351], 53, 50),
    "nhl.saves_team_b2b": (-0.0218, 62, 0.0365, [-0.0926, 0.1606], 72, 64),
    "nhl.saves_under_bias": (0.0259, 405, -0.0537, [-0.1023, -0.0039], 405, 224),
}
NHL_REGISTRY.update({
    name: _replace(NHL_REGISTRY[name], status="null", evidence={
        "tested": "2026-10-14 lane signal-engine-nhl v1, 2025-26 saves closes, discover < 2025-12-09 <= confirm",
        "discover_residual": r[0], "discover_n": r[1], "confirm_residual": r[2], "confirm_ci95": r[3],
        "confirm_n": r[4], "confirm_games": r[5], "verdict": "NOT SUPPORTED"})
    for name, r in _SAVES_V1.items()
})
_FWD = "registered forward test K1-K5 on 2026-27 (lane signal-engine-nhl, 2026-10-14T01:16:45Z); final read 2026-12-31"
NHL_REGISTRY.update({name: _replace(NHL_REGISTRY[name], evidence={"registered": _FWD})
                     for name in ("nhl.toi_up", "nhl.toi_down", "nhl.opp_allows_shots", "nhl.opp_suppresses_shots",
                                  "nhl.skater_under_bias")})
