"""NFL defender matchups for the cheat sheets (lane `cheat-sheets`, user 2026-10-15: "add defender matchups for NFL and NBA").

WHAT THIS IS NOT: a coverage matchup. No free source records which defender covered which receiver -- that is charted
by PFF and Next Gen Stats (paid), and Pro Football Reference forbids automated use. The user chose (2026-10-15) the
closest honest thing in open data: PLAYS ON THE BALL, from the nflverse play-by-play the data root already refreshes
daily (`nfl_source/tracking/nflverse/pbp/pbp_<season>.csv`):

  * a pass breakup (`pass_defense_1/2_player_id`) or an interception (`interception_player_id`) on a target, and
  * the tackler(s) on a completed catch (`solo_tackle_*`, `assist_tackle_*`, `tackle_with_assist_*`).

A RECEIVER's line is those plays on his targets by TODAY's opponent's active defenders (the 2026 nflverse roster), this
season and the two before -- whatever team the defender was on then. A QUARTERBACK's line is the same on his throws.
Each of those defenders' plays on the ball this season, league-wide, is the defense's side ("ball hawks").

It UNDERCOUNTS what a defender gave up: a catch that scores or goes out of bounds has no tackler, so it credits no one.
The page says so. No network: both files are read from the data root.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping

SEASONS_BACK = 3                    # this season and the two before it
DEFENDER_POSITIONS = frozenset({"DB", "CB", "S", "SS", "FS", "LB", "ILB", "OLB", "MLB"})
TEAM_ALIASES = {"LAR": "LA", "STL": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC"}   # -> nflverse codes
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")
_TACKLERS = ("solo_tackle_1_player_id", "solo_tackle_2_player_id", "assist_tackle_1_player_id",
             "assist_tackle_2_player_id", "tackle_with_assist_1_player_id", "tackle_with_assist_2_player_id")


def _norm(name: Any) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", _SUFFIX.sub("", text))


def team_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    return TEAM_ALIASES.get(code, code)


def market_role(market: Any) -> str | None:
    """'receiver' for receiving props, 'passer' for passing props, None for everything else."""
    m = str(market or "").lower()
    if "recept" in m or "receiving" in m:
        return "receiver"
    if "pass" in m or "interception" in m or "completion" in m:
        return "passer"
    return None


def seasons_for(date: str, back: int = SEASONS_BACK) -> list[int]:
    year, month = int(date[:4]), int(date[5:7])
    start = year if month >= 3 else year - 1          # January / February games belong to the season before
    return list(range(start, start - back, -1))


def _nflverse(data_root: Path) -> Path:
    return Path(data_root) / "nfl_source" / "tracking" / "nflverse"


def targets(rows: Iterable[Mapping[str, str]]) -> list[tuple[str, str, str, bool, int, tuple[tuple[str, str], ...]]]:
    """(game, passer, receiver, complete, yards, credits) for every targeted pass; credits = ((defender, kind), ...)
    with kind 'int', 'pbu' or 'tkl' (a tackle after the catch)."""
    out = []
    for r in rows:
        receiver = r.get("receiver_player_id") or ""
        if (not receiver or r.get("pass_attempt") != "1" or r.get("sack") == "1" or r.get("two_point_attempt") == "1"
                or r.get("play_deleted") == "1" or r.get("season_type") not in ("REG", "POST")):
            continue
        complete = r.get("complete_pass") == "1"
        credits: list[tuple[str, str]] = []
        seen: set[str] = set()
        if r.get("interception") == "1" and r.get("interception_player_id"):
            credits.append((r["interception_player_id"], "int"))
            seen.add(r["interception_player_id"])
        for col in ("pass_defense_1_player_id", "pass_defense_2_player_id"):
            who = r.get(col) or ""
            if who and who not in seen:
                credits.append((who, "pbu"))
                seen.add(who)
        if complete:
            for col in _TACKLERS:
                who = r.get(col) or ""
                if who and who not in seen:
                    credits.append((who, "tkl"))
                    seen.add(who)
        try:
            yards = int(float(r.get("receiving_yards") or 0)) if complete else 0
        except ValueError:
            yards = 0
        out.append((r.get("game_id") or "", r.get("passer_player_id") or "", receiver, complete, yards, tuple(credits)))
    return out


def load_targets(data_root: Path, season: int) -> list[tuple]:
    path = _nflverse(data_root) / "pbp" / f"pbp_{season}.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return targets(csv.DictReader(fh))


def load_roster(data_root: Path, season: int) -> list[dict[str, str]]:
    path = _nflverse(data_root) / "roster" / f"roster_{season}.csv"
    if not path.is_file():
        return []
    latest: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            gid = r.get("gsis_id") or ""
            if gid and (gid not in latest or int(r.get("week") or 0) >= int(latest[gid].get("week") or 0)):
                latest[gid] = r
    return list(latest.values())


def find_player(roster: list[dict[str, str]], name: Any, team: str) -> str | None:
    """gsis id for a sheet name -- inside the player's team first, then a league-wide UNIQUE match only."""
    key = _norm(name)
    if not key:
        return None
    hits = [r for r in roster if key in (_norm(r.get("full_name")), _norm(f"{r.get('football_name', '')} {r.get('last_name', '')}"))]
    mine = [r for r in hits if team_code(r.get("team")) == team]
    pick = mine if mine else hits
    ids = {r.get("gsis_id") for r in pick}
    return next(iter(ids)) if len(ids) == 1 else None


def active_defenders(roster: list[dict[str, str]], team: str) -> dict[str, dict[str, str]]:
    out = {}
    for r in roster:
        pos = r.get("depth_chart_position") or r.get("position") or ""
        if team_code(r.get("team")) == team and r.get("status") == "ACT" and (pos in DEFENDER_POSITIONS
                                                                              or r.get("position") in DEFENDER_POSITIONS):
            out[r["gsis_id"]] = {"name": r.get("full_name") or "", "pos": pos}
    return out


def _tally(plays: Iterable[tuple], defenders: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for game, _passer, _receiver, _complete, yards, credits in plays:
        for who, kind in credits:
            if who not in defenders:
                continue
            t = out.setdefault(who, {"plays": 0, "catches": 0, "yards": 0, "pbu": 0, "int": 0, "games": set()})
            t["plays"] += 1
            t["games"].add(game)
            if kind == "tkl":
                t["catches"] += 1
                t["yards"] += yards
            else:
                t[kind] += 1
    return out


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _parts(t: Mapping[str, Any]) -> str:
    bits = []
    if t["int"]:
        bits.append(f"{t['int']} INT")
    if t["pbu"]:
        bits.append(f"{t['pbu']} PBU")
    if t["catches"]:
        bits.append(f"{_plural(t['catches'], 'catch', 'catches')} for {t['yards']} yds tackled")
    return ", ".join(bits)


def _short(name: str) -> str:
    first, _, rest = name.partition(" ")
    return f"{first[:1]}. {rest}" if rest else name


class Source:
    """The season files, read once per build."""

    def __init__(self, data_root: Path, date: str):
        self.seasons = seasons_for(date)
        self.roster = load_roster(data_root, self.seasons[0])
        self.by_receiver: dict[str, list[tuple]] = {}
        self.by_passer: dict[str, list[tuple]] = {}
        self.current: list[tuple] = []
        for season in self.seasons:
            plays = load_targets(data_root, season)
            if season == self.seasons[0]:
                self.current = plays
            for p in plays:
                self.by_receiver.setdefault(p[2], []).append(p)
                if p[1]:
                    self.by_passer.setdefault(p[1], []).append(p)


def matchups(rows: list[dict[str, Any]], *, date: str, source: Source) -> dict[tuple[str, str], dict[str, Any]]:
    """(normalized player, market) -> the defender block for a receiving or passing prop."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    hawks_by_team: dict[str, dict[str, dict[str, Any]]] = {}
    for r in rows:
        key, market = _norm(r.get("player")), str(r.get("market") or "").strip().lower()
        role = market_role(market)
        team, opp = team_code(r.get("team")), team_code(r.get("opponent"))
        if not key or role is None or not opp or (key, market) in out:
            continue
        pid = find_player(source.roster, r.get("player"), team)
        defenders = active_defenders(source.roster, opp)
        if not pid or not defenders:
            continue
        if opp not in hawks_by_team:
            hawks_by_team[opp] = _tally(source.current, defenders)
        mine = (source.by_receiver if role == "receiver" else source.by_passer).get(pid, [])
        h2h = _tally(mine, defenders)
        total = {k: sum(t[k] for t in h2h.values()) for k in ("plays", "catches", "yards", "pbu", "int")}
        games = set().union(*(t["games"] for t in h2h.values())) if h2h else set()
        top = sorted(h2h.items(), key=lambda kv: (-kv[1]["plays"], -(kv[1]["int"] + kv[1]["pbu"])))[:3]
        hawks = sorted(hawks_by_team[opp].items(), key=lambda kv: (-(2 * kv[1]["int"] + kv[1]["pbu"]), -kv[1]["plays"]))
        hawks = [kv for kv in hawks if kv[1]["int"] + kv[1]["pbu"]][:2]
        line = {**total, "games": len(games), "since": source.seasons[-1],
                "defenders": [{"name": defenders[d]["name"], "pos": defenders[d]["pos"], "games": len(t["games"]),
                               **{k: t[k] for k in ("plays", "catches", "yards", "pbu", "int")}} for d, t in top],
                "hawks": [{"name": defenders[d]["name"], "pos": defenders[d]["pos"],
                           **{k: t[k] for k in ("plays", "catches", "yards", "pbu", "int")}} for d, t in hawks]}
        if role == "receiver":
            summary = "; ".join(f"{_short(x['name'])} ({x['pos']}): {_parts(x)} ({_plural(x['games'], 'game', 'games')})"
                                for x in line["defenders"][:2])
        else:
            summary = (f"{_plural(total['int'], 'INT', 'INTs')} and {total['pbu']} PBU by today's {opp} defenders on his "
                       f"throws since {source.seasons[-1]}" if total["plays"] else "")
        out[(key, market)] = {"kind": "receiver_vs_defenders" if role == "receiver" else "qb_vs_defenders",
                              "opponent": f"{opp} defense", "line": line,
                              "summary": summary or f"No plays on the ball by today's {opp} defenders since {source.seasons[-1]}"}
    return out
