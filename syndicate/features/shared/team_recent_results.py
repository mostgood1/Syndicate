"""Each team's recent final scores, for the board's game-line "last 10" charts.

User 2026-10-08 (approved mockup board 11, lane layer2-board-ui-redesign):
game rows show how each team has done against TODAY's line over its last 10
games -- totals over/under, covers against the spread, wins and losses. This
module only supplies the scores; the page derives every one of those from
(points for, points against) and the row's own line.

Display only. Nothing scores on these.

One local file per sport, parsed once per (path, mtime, size) into
``{team key: [(date, pts_for, pts_against), ...]}``. No network.

* nfl   -- nflverse ``schedules_games.csv`` (unplayed games have blank scores).
* ncaaf -- ``historical_truth/games_<season>.json.gz``, ``completed`` only.
* nhl   -- skater ``goals`` summed per (gamePk, team); REGULAR SEASON only
           (gamePk type ``02``). A shootout winner's extra goal is not in
           skater goals, so a shootout game reads as tied.
* mlb   -- batter-log ``r`` summed per (game_pk, team).
* soccer -- every league's ``api/schedule/schedule_<season>.json``, ``post`` only.

* nba / wnba -- ``player_game_log_<season>.csv`` ``PTS`` summed per (game_id,
           team), regular season and playoffs only (lane board-history-charts,
           user 2026-10-09 "proceed" on the history-charts plan). These logs are
           refreshed daily for the CURRENT season. They used to be left out because
           the box-score history then ended with LAST season's playoffs. Only the
           NEWEST season's file is read (the 120-day window alone would still reach
           last June's Finals from an October board), so an NBA preseason board gets
           ``[]`` until this season's games exist.
           Exhibition teams the board cannot name (WNBA All-Star COOP / SPO) map to
           no key and are dropped.

INTERVALS ONLY WHERE THE SOURCE HAS THEM (user 2026-10-08: "are we sure the
game interval charts are actually showing interval historical results and not
full game?" -- they were not: 65 first-5 / half / quarter rows were drawn
against full-game finals). ``segment`` other than full returns ``[]`` except
NCAAF, whose game files carry per-quarter line scores (h1 = q1+q2,
h2 = q3+q4+OT, qN = that quarter). MLB innings and NFL quarters have no
single-file source, so those rows get no team history at all.

Only games inside ``_WINDOW_DAYS`` before the slate count, so an early-season
"last 10" is honestly short ("last 4") instead of reaching into last season.
"""

from __future__ import annotations

import csv
import glob
import gzip
import json
import os
import threading
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from syndicate.features.shared.prop_evidence.common import data_root

_WINDOW_DAYS = 120
# Markets these scores do NOT settle (lane board-history-charts, 2026-10-10):
# a corners or cards total is not the game's goal total, and a team total is
# one side's score, not the sum. Measured on the served board that day: 132
# soccer `alternate_totals_corners` rows carried goal totals against a corners
# line ("over 10.5 0/10"), because "total" matched any totals market.
_NOT_SCORE_MARKET_WORDS = ("corner", "card", "booking", "team_total")
_LOCK = threading.Lock()


def is_score_market(market: Any) -> bool:
    """True when the row's market is settled by the final (or interval) score."""
    text = str(market or "").lower()
    return bool(text) and not any(word in text for word in _NOT_SCORE_MARKET_WORDS)
_CACHE: dict[tuple[str, tuple[tuple[str, int, int], ...]], dict[str, list[tuple[str, float, float]]]] = {}


def _key(sport: str, name: Any) -> str | None:
    if not name:
        return None
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        key = chip_join_key(sport, str(name))
    except Exception:  # noqa: BLE001 -- display join
        key = None
    return key or str(name).strip().lower() or None


def _num(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


_NCAAF_SEGMENTS = ("h1", "h2", "q1", "q2", "q3", "q4")


def _quarters(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) < 4:
        return None
    vals = [_num(v) for v in raw]
    return None if any(v is None for v in vals[:4]) else [float(v or 0.0) for v in vals]


def _segment_points(quarters: list[float], segment: str) -> float | None:
    if segment == "h1":
        return quarters[0] + quarters[1]
    if segment == "h2":
        return sum(quarters[2:])  # q3 + q4 + every overtime, as segment_actuals grades it
    if segment in {"q1", "q2", "q3", "q4"}:
        return quarters[int(segment[1]) - 1]
    return None


def _add(index: dict, sport: str, day: str, home: Any, away: Any, hs: float, as_: float, *, segment: str = "full") -> None:
    hk, ak = _key(sport, home), _key(sport, away)
    if segment != "full":
        hk, ak = (f"{hk}|{segment}" if hk else None), (f"{ak}|{segment}" if ak else None)
    if hk:
        index[hk].append((day, hs, as_))
    if ak:
        index[ak].append((day, as_, hs))


def _nfl(paths: list[Path]) -> dict:
    index: dict = defaultdict(list)
    with open(paths[0], encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            hs, as_ = _num(row.get("home_score")), _num(row.get("away_score"))
            if hs is None or as_ is None:
                continue
            _add(index, "nfl", str(row.get("gameday") or "")[:10], row.get("home_team"), row.get("away_team"), hs, as_)
    return index


def _ncaaf(paths: list[Path]) -> dict:
    index: dict = defaultdict(list)
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        games = payload if isinstance(payload, list) else (payload.get("games") or [])
        for g in games:
            if not isinstance(g, dict) or not g.get("completed"):
                continue
            hs, as_ = _num(g.get("homePoints")), _num(g.get("awayPoints"))
            if hs is None or as_ is None:
                continue
            # startDate is UTC; a 7:30pm ET kickoff is the next UTC day. The
            # window is days wide, so a one-day slip cannot change membership
            # except at its edge.
            day = str(g.get("startDate") or "")[:10]
            _add(index, "ncaaf", day, g.get("homeTeam"), g.get("awayTeam"), hs, as_)
            home_q, away_q = _quarters(g.get("homeLineScores")), _quarters(g.get("awayLineScores"))
            if home_q and away_q:
                for seg in _NCAAF_SEGMENTS:
                    h, a = _segment_points(home_q, seg), _segment_points(away_q, seg)
                    if h is not None and a is not None:
                        _add(index, "ncaaf", day, g.get("homeTeam"), g.get("awayTeam"), h, a, segment=seg)
    return index


def _summed(paths: list[Path], sport: str, game_col: str, team_col: str, value_col: str,
            keep: Callable[[str], bool]) -> dict:
    """Per-player rows -> one score per (game, team) -> the opponent is the other team."""
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    days: dict[str, str] = {}
    with open(paths[0], encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            game = str(row.get(game_col) or "")
            team = row.get(team_col)
            if not game or not team or not keep(game):
                continue
            totals[game][str(team)] += _num(row.get(value_col)) or 0.0
            days.setdefault(game, str(row.get("date") or "")[:10])
    index: dict = defaultdict(list)
    for game, teams in totals.items():
        if len(teams) != 2:
            continue  # one side missing from the log: no honest score
        (a, sa), (b, sb) = teams.items()
        ka, kb = _key(sport, a), _key(sport, b)
        if ka:
            index[ka].append((days[game], sa, sb))
        if kb:
            index[kb].append((days[game], sb, sa))
    return index


def _nhl(paths: list[Path]) -> dict:
    return _summed(paths, "nhl", "gamePk", "team", "goals", lambda gid: len(gid) >= 6 and gid[4:6] == "02")


def _mlb(paths: list[Path]) -> dict:
    return _summed(paths, "mlb", "game_pk", "team", "r", lambda gid: True)


_BASKETBALL_SEASON_TYPES = frozenset({"regular", "playoffs"})


def _basketball(sport: str) -> Callable[[list[Path]], dict]:
    """Per-player PTS -> one score per (game_id, team), across every given season file."""

    def build(paths: list[Path]) -> dict:
        totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        days: dict[str, str] = {}
        for path in paths:
            with open(path, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    game = str(row.get("game_id") or "")
                    team = str(row.get("TEAM_ABBREVIATION") or "").strip()
                    if not game or not team:
                        continue
                    if str(row.get("season_type") or "").strip().lower() not in _BASKETBALL_SEASON_TYPES:
                        continue
                    totals[game][team] += _num(row.get("PTS")) or 0.0
                    days.setdefault(game, str(row.get("date") or "")[:10])
        index: dict = defaultdict(list)
        for game, teams in totals.items():
            if len(teams) != 2:
                continue  # one side missing from the log: no honest score
            (a, sa), (b, sb) = teams.items()
            ka, kb = _key(sport, a), _key(sport, b)
            if ka:
                index[ka].append((days[game], sa, sb))
            if kb:
                index[kb].append((days[game], sb, sa))
        return index

    return build


def _soccer(paths: list[Path]) -> dict:
    index: dict = defaultdict(list)
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for m in payload.get("matches") or []:
            if not isinstance(m, dict) or str(m.get("status_state") or "").lower() != "post":
                continue
            hs, as_ = _num(m.get("home_score")), _num(m.get("away_score"))
            if hs is None or as_ is None:
                continue
            _add(index, "soccer", str(m.get("date") or "")[:10], m.get("home_team"), m.get("away_team"), hs, as_)
    return index


def _sources(sport: str) -> tuple[list[Path], Callable[[list[Path]], dict]] | None:
    root = data_root()
    if sport == "nfl":
        found = [root / "nfl_source" / "tracking" / "nflverse" / "schedules_games.csv"]
        return ([p for p in found if p.is_file()], _nfl)
    if sport == "ncaaf":
        found = sorted(glob.glob(str(root / "ncaaf_source" / "historical_truth" / "games_*.json.gz")))[-2:]
        return ([Path(p) for p in found], _ncaaf)
    if sport == "nhl":
        rel = Path("raw") / "player_game_stats.csv"
        found = [root / "nhl_source" / "source_artifacts" / "data" / rel, root / "nhl_source" / "data" / rel]
        return ([p for p in found if p.is_file()][:1], _nhl)
    if sport == "mlb":
        rel = Path("processed") / "mlb_batter_game_log.csv"
        found = [root / "mlb_source" / "source_artifacts" / "data" / rel, root / "mlb_source" / "data" / rel]
        return ([p for p in found if p.is_file()][:1], _mlb)
    if sport == "soccer":
        found = sorted(glob.glob(str(root / "soccer_source" / "*" / "api" / "schedule" / "schedule_*.json")))
        return ([Path(p) for p in found], _soccer)
    if sport in {"nba", "wnba"}:
        # THE NEWEST SEASON'S LOG ONLY. The 120-day window is not enough here: on an October NBA
        # preseason board it still reaches last June's Finals, i.e. another season and another phase.
        # The newest file is the current season's (the daily job creates it, empty, before the season
        # starts), so an NBA board gets [] until this season's games exist.
        for base in (root / f"{sport}_source" / "data" / "processed",
                     root / f"{sport}_source" / "source_artifacts" / "data" / "processed"):
            found = sorted(glob.glob(str(base / "player_game_log_*.csv")))[-1:]
            if found:
                return ([Path(p) for p in found], _basketball(sport))
        return ([], _basketball(sport))
    return None


def _index(sport: str) -> dict[str, list[tuple[str, float, float]]]:
    spec = _sources(sport)
    if not spec or not spec[0]:
        return {}
    paths, builder = spec
    sig = []
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            continue
        sig.append((str(p), st.st_mtime_ns, st.st_size))
    key = (sport, tuple(sig))
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        built = builder(paths)
    except Exception:  # noqa: BLE001 -- a chart must never break a board build
        built = {}
    built = {team: sorted(games, reverse=True) for team, games in built.items()}
    with _LOCK:
        for stale in [k for k in _CACHE if k[0] == sport]:
            _CACHE.pop(stale, None)
        _CACHE[key] = built
    return built


def team_recent_results(sport: Any, team: Any, before: Any, n: int = 10, *, segment: Any = "full") -> list[list[Any]]:
    """Newest-first ``[date, pts_for, pts_against]`` for ``team``'s games strictly
    before ``before`` (an ISO date or datetime), within ``_WINDOW_DAYS``. ``[]``
    when the sport has no source or the team is unknown -- never a guess."""
    sport = str(sport or "").lower()
    day = str(before or "")[:10]
    try:
        cutoff = date.fromisoformat(day)
    except ValueError:
        return []
    key = _key(sport, team)
    if not key:
        return []
    segment = str(segment or "full").strip().lower() or "full"
    if segment not in {"full", "game"}:
        if sport != "ncaaf" or segment not in _NCAAF_SEGMENTS:
            return []
        key = f"{key}|{segment}"
    floor = (cutoff - timedelta(days=_WINDOW_DAYS)).isoformat()
    games = _index(sport).get(key) or []
    out = [[d, f, a] for d, f, a in games if floor <= d < day]
    return out[:n]
