"""Score rows and player-box rows for the non-MLB sports (lane settlement-graders-all-sports).

User 2026-10-12 ("go with option a" + every sport): board prop results settled
for MLB only. MLB's grader emits two row types the matcher already knows how to
use (`graded_outcomes.SCORE_ROW_MARKET` -> any game line at any line from the
final score; `PLAYER_BOX_ROW_MARKET` -> props from the player's own stat line),
and every other sport emitted neither:

    measured 2026-10-12 over 10-08..10-11, Layer 2 picks matched:
      MLB ~95%   NFL lines 149/2,619, props 0/14,603   soccer 0 (game_absent)
      NCAAF / NHL / NBA / WNBA: 0 graded rows at all

This module builds those two row types per sport from data already on the
fleet. It decides NOTHING about a bet: `settlement_identity` grades, exactly as
it does for MLB. Rows are only emitted for games the source calls FINISHED, and
a player appears only with stats the source actually recorded (absent is
absent, never zero).

Shapes (the MLB contract, `graded_outcomes`):
  score row: sport, game_id, market=game_score, segment, home, away, title,
             home_score, away_score, source
  box row:   sport, game_id, market=player_box, segment=full, home, away, title,
             players=[{id, name, name_key, team, player: {stat: value}}], source
The prop group for every non-MLB sport is "player" (`settlement_identity`
maps each sport's market labels onto these stat keys).
"""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

SCORE_ROW_MARKET = "game_score"
PLAYER_BOX_ROW_MARKET = "player_box"
PROP_GROUP = "player"


def _num(value: Any) -> float | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        out = float(text)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _stamp(path: Path) -> tuple[str, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_mtime_ns, st.st_size)


def _name_key(value: Any) -> str:
    from syndicate.features.shared.graded_outcomes import player_name_key

    return player_name_key(value)


def _score_row(sport: str, game_id: str, home: str, away: str, home_score: float, away_score: float, source: str,
               segment: str = "full", game_date: str | None = None) -> dict[str, Any]:
    return {
        "sport": sport,
        "game_id": game_id,
        "game_date": game_date,
        "market": SCORE_ROW_MARKET,
        "segment": segment,
        "home": home,
        "away": away,
        "title": f"{away} @ {home}",
        "home_score": home_score,
        "away_score": away_score,
        "source": source,
    }


def _box_row(sport: str, game_id: str, home: str, away: str, players: list[dict[str, Any]], source: str,
            game_date: str | None = None) -> dict[str, Any]:
    return {
        "sport": sport,
        "game_id": game_id,
        "game_date": game_date,
        "market": PLAYER_BOX_ROW_MARKET,
        "segment": "full",
        "home": home,
        "away": away,
        "title": f"{away} @ {home}",
        "players": players,
        "source": source,
    }


# ---------------------------------------------------------------------- NFL


def _nfl_tracking(relative: str) -> Path | None:
    try:
        from syndicate.features.nfl.sources import _resolve_nfl_tracking_path

        path = _resolve_nfl_tracking_path(Path(relative))
    except Exception:  # noqa: BLE001
        return None
    return path if path.is_file() else None


@lru_cache(maxsize=4)
def _nfl_schedule(stamp: tuple[str, int, int]) -> tuple[dict[str, Any], ...]:
    with open(stamp[0], encoding="utf-8", newline="") as fh:
        return tuple(dict(row) for row in csv.DictReader(fh))


@lru_cache(maxsize=4)
def _nfl_full_names(stamp: tuple[str, int, int]) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(stamp[0], encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            gsis = str(row.get("gsis_id") or "").strip()
            name = str(row.get("full_name") or "").strip()
            if gsis and name:
                out[gsis] = name
    return out


def _nfl_segment_scores(per_quarter: Mapping[int, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """{segment: (home, away)} from cumulative scores at the end of each period.
    h2 = q3 + q4 + every overtime, exactly as `segment_actuals` grades it."""
    ends = {q: per_quarter[q] for q in sorted(per_quarter)}
    if not all(q in ends for q in (1, 2, 3, 4)):
        return {}
    def pts(q: int) -> tuple[float, float]:
        prev = ends.get(q - 1, (0.0, 0.0)) if q > 1 else (0.0, 0.0)
        return ends[q][0] - prev[0], ends[q][1] - prev[1]
    out = {f"q{q}": pts(q) for q in (1, 2, 3, 4)}
    last = ends[max(ends)]
    out["h1"] = ends[2]
    out["h2"] = (last[0] - ends[2][0], last[1] - ends[2][1])
    return out


@lru_cache(maxsize=2)
def _nfl_game_quarter_ends(stamp: tuple[str, int, int]) -> dict[str, dict[int, tuple[float, float]]]:
    """{game_id: {qtr: (home total, away total) at the LAST play of that qtr}}."""
    out: dict[str, dict[int, tuple[float, float]]] = defaultdict(dict)
    with open(stamp[0], encoding="utf-8", newline="") as fh:
        for p in csv.DictReader(fh):
            game, qtr = p.get("game_id") or "", _num(p.get("qtr"))
            h, a = _num(p.get("total_home_score")), _num(p.get("total_away_score"))
            if not game or qtr is None or h is None or a is None:
                continue
            q = int(qtr)
            prev = out[game].get(q)
            if prev is None or (h + a) >= (prev[0] + prev[1]):
                out[game][q] = (h, a)
    return {game: dict(v) for game, v in out.items()}


@lru_cache(maxsize=2)
def _nfl_game_player_stats(stamp: tuple[str, int, int]) -> dict[str, dict[str, dict[str, Any]]]:
    """{game_id: {player_id: {"team":..., stats...}}} from one season's pbp.

    Standard box-score definitions: two-point tries and sacks are not attempts;
    a completion credits the receiver with a reception and its yards."""
    games: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    def bump(game: str, pid: str, team: str, stat: str, value: float) -> None:
        if not pid:
            return
        entry = games[game].setdefault(pid, {"team": team})
        entry[stat] = entry.get(stat, 0.0) + value

    with open(stamp[0], encoding="utf-8", newline="") as fh:
        for p in csv.DictReader(fh):
            game = p.get("game_id") or ""
            if not game or p.get("two_point_attempt") == "1":
                continue
            team = p.get("posteam") or ""
            passer, rusher, receiver = p.get("passer_player_id"), p.get("rusher_player_id"), p.get("receiver_player_id")
            if passer and p.get("pass_attempt") == "1" and p.get("sack") != "1":
                bump(game, passer, team, "pass_att", 1)
                if p.get("complete_pass") == "1":
                    bump(game, passer, team, "pass_cmp", 1)
                bump(game, passer, team, "pass_yds", _num(p.get("passing_yards")) or 0.0)
                if p.get("pass_touchdown") == "1":
                    bump(game, passer, team, "pass_td", 1)
                if p.get("interception") == "1":
                    bump(game, passer, team, "pass_int", 1)
            if rusher and p.get("rush_attempt") == "1":
                bump(game, rusher, team, "rush_att", 1)
                bump(game, rusher, team, "rush_yds", _num(p.get("rushing_yards")) or 0.0)
                if p.get("rush_touchdown") == "1":
                    bump(game, rusher, team, "rush_td", 1)
            if receiver and p.get("complete_pass") == "1":
                bump(game, receiver, team, "rec", 1)
                bump(game, receiver, team, "rec_yds", _num(p.get("receiving_yards")) or 0.0)
                if p.get("pass_touchdown") == "1":
                    bump(game, receiver, team, "rec_td", 1)
    # A player who appears in the game's plays PLAYED it, so a stat he did not
    # record is 0 (books settle "played, no rushing attempts" as 0, not void);
    # a player with no plays at all is absent from the box and stays pending.
    _NFL_STATS = ("pass_att", "pass_cmp", "pass_yds", "pass_td", "pass_int", "rush_att", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td")
    for players in games.values():
        for entry in players.values():
            for stat in _NFL_STATS:
                entry.setdefault(stat, 0.0)
            entry["rush_rec_yds"] = entry.get("rush_yds", 0.0) + entry.get("rec_yds", 0.0)
            entry["pass_rush_yds"] = entry.get("pass_yds", 0.0) + entry.get("rush_yds", 0.0)
            entry["anytime_td"] = entry.get("rush_td", 0.0) + entry.get("rec_td", 0.0)
    return {game: dict(players) for game, players in games.items()}


def nfl_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    """Score + box rows for NFL games played on `date_str` (the schedule's
    ET gameday), from the nflverse schedule, play-by-play and roster."""
    schedule = _nfl_tracking("tracking/nflverse/schedules_games.csv")
    if schedule is None:
        return []
    games = [g for g in _nfl_schedule(_stamp(schedule)) if str(g.get("gameday") or "").strip() == date_str]
    rows: list[dict[str, Any]] = []
    stats_by_season: dict[str, dict] = {}
    names_by_season: dict[str, dict] = {}
    for game in games:
        home_score, away_score = _num(game.get("home_score")), _num(game.get("away_score"))
        if home_score is None or away_score is None:
            continue  # not played (or not yet recorded): absent, never 0-0
        game_id = str(game.get("game_id") or "").strip()
        home, away = str(game.get("home_team") or "").strip(), str(game.get("away_team") or "").strip()
        if not game_id or not home or not away:
            continue
        rows.append(_score_row("nfl", game_id, home, away, home_score, away_score, "nflverse_schedule", game_date=date_str))
        season = str(game.get("season") or date_str[:4])
        if season not in stats_by_season:
            pbp = _nfl_tracking(f"tracking/nflverse/pbp/pbp_{season}.csv")
            roster = _nfl_tracking(f"tracking/nflverse/roster/roster_{season}.csv")
            stats_by_season[season] = _nfl_game_player_stats(_stamp(pbp)) if pbp else {}
            names_by_season[season] = _nfl_full_names(_stamp(roster)) if roster else {}
        pbp_path = _nfl_tracking(f"tracking/nflverse/pbp/pbp_{season}.csv")
        quarter_ends = (_nfl_game_quarter_ends(_stamp(pbp_path)) if pbp_path else {}).get(game_id) or {}
        segments = _nfl_segment_scores(quarter_ends)
        # A segment row only when the pbp's final agrees with the schedule's,
        # so a half-loaded game never grades a quarter.
        if segments and quarter_ends and abs(sum(quarter_ends[max(quarter_ends)]) - (home_score + away_score)) < 1e-9:
            for segment, (seg_home, seg_away) in segments.items():
                rows.append(_score_row("nfl", game_id, home, away, seg_home, seg_away, "nflverse_pbp", segment=segment, game_date=date_str))
        per_player = stats_by_season[season].get(game_id) or {}
        names = names_by_season[season]
        players = []
        for pid, stats in per_player.items():
            name = names.get(pid)
            if not name:
                continue  # an id the roster cannot name cannot be joined by name -- skipped, not guessed
            players.append({
                "id": pid,
                "name": name,
                "name_key": _name_key(name),
                "team": stats.get("team"),
                PROP_GROUP: {k: v for k, v in stats.items() if k != "team"},
            })
        if players:
            rows.append(_box_row("nfl", game_id, home, away, players, "nflverse_pbp", game_date=date_str))
    return rows


# ---------------------------------------------------------------------- NHL


def _nhl_roots() -> list[Path]:
    roots = []
    env = os.environ.get("SYNDICATE_DATA_ROOT")
    if env:
        roots.append(Path(env) / "nhl_source")
    roots.append(Path(__file__).resolve().parents[3] / "data" / "nhl_source")
    return [r for r in roots if r.exists()]


@lru_cache(maxsize=4)
def _nhl_boxscore_dates(signature: tuple[str, int, int]) -> dict[str, tuple[str, ...]]:
    """{gameDate: (boxscore paths)} for one cache directory listing."""
    out: dict[str, list[str]] = defaultdict(list)
    for path in sorted(Path(signature[0]).glob("boxscore_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        day = str(payload.get("gameDate") or "")[:10]
        if day:
            out[day].append(str(path))
    return {day: tuple(paths) for day, paths in out.items()}


def _nhl_cache_dir() -> Path | None:
    for root in _nhl_roots():
        for rel in ("data/ingestion_cache", "source_artifacts/data/ingestion_cache"):
            if (root / rel).is_dir():
                return root / rel
    return None


@lru_cache(maxsize=512)
def _nhl_full_names(stamp: tuple[str, int, int]) -> dict[int, str]:
    out: dict[int, str] = {}
    with open(stamp[0], encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                out[int(str(row.get("player_id") or "").strip())] = str(row.get("full_name") or "").strip()
            except ValueError:
                continue
    return out


def _nhl_roster_names() -> dict[int, str]:
    """Every roster snapshot, newest name winning per id. A daily snapshot
    holds only that day's teams (6 of 32 on 2026-10-12), so one file names
    a fifth of the league."""
    found: list[Path] = []
    for root in _nhl_roots():
        for rel in ("data/processed", "source_artifacts/data/processed"):
            found += sorted((root / rel).glob("roster_snapshot_*.csv"))
    out: dict[int, str] = {}
    for path in sorted(found, key=lambda p: p.name):
        stamp = _stamp(path)
        if stamp:
            out.update(_nhl_full_names(stamp))
    return out


_NHL_FINAL_STATES = frozenset({"OFF", "FINAL"})


def nhl_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    """Score + box rows for NHL games on `date_str` (the API's local gameDate)
    from the boxscore cache. Final score is the API's, which counts a shootout
    winner's goal -- how books settle moneylines, puck lines and totals."""
    cache = _nhl_cache_dir()
    if cache is None:
        return []
    try:
        st = cache.stat()
    except OSError:
        return []
    listing = (str(cache), st.st_mtime_ns, len(list(cache.glob("boxscore_*.json"))))
    paths = _nhl_boxscore_dates(listing).get(date_str) or ()
    names = _nhl_roster_names()
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            box = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(box.get("gameState") or "").upper() not in _NHL_FINAL_STATES or str(box.get("gameScheduleState") or "OK").upper() != "OK":
            continue
        home_t, away_t = box.get("homeTeam") or {}, box.get("awayTeam") or {}
        home, away = str(home_t.get("abbrev") or ""), str(away_t.get("abbrev") or "")
        hs, as_ = _num(home_t.get("score")), _num(away_t.get("score"))
        game_id = str(box.get("id") or "")
        if not home or not away or hs is None or as_ is None or not game_id:
            continue
        rows.append(_score_row("nhl", game_id, home, away, hs, as_, "nhl_boxscore", game_date=date_str))
        players = []
        by_side = box.get("playerByGameStats") or {}
        for side_key, team in (("homeTeam", home), ("awayTeam", away)):
            groups = by_side.get(side_key) or {}
            for group in ("forwards", "defense"):
                for p in groups.get(group) or []:
                    if str(p.get("toi") or "00:00") in ("00:00", "0:00", ""):
                        continue  # dressed, did not play: absent, not zero
                    pid = p.get("playerId")
                    name = names.get(int(pid)) if pid is not None else None
                    if not name:
                        continue
                    stats = {k: _num(p.get(k)) for k in ("goals", "assists", "points", "sog", "blockedShots", "hits", "powerPlayGoals", "pim")}
                    players.append({"id": pid, "name": name, "name_key": _name_key(name), "team": team,
                                    PROP_GROUP: {k: v for k, v in stats.items() if v is not None}})
            for p in groups.get("goalies") or []:
                saves_text = str(p.get("saveShotsAgainst") or "")
                if "/" not in saves_text or saves_text.startswith("0/0") or str(p.get("toi") or "00:00") in ("00:00", ""):
                    continue
                pid = p.get("playerId")
                name = names.get(int(pid)) if pid is not None else None
                if not name:
                    continue
                saves, _shots = saves_text.split("/", 1)
                players.append({"id": pid, "name": name, "name_key": _name_key(name), "team": team,
                                PROP_GROUP: {"saves": _num(saves), "goals_against": _num(p.get("goalsAgainst"))}})
        if players:
            rows.append(_box_row("nhl", game_id, home, away, players, "nhl_boxscore", game_date=date_str))
    return rows


# ------------------------------------------------------------ NBA / WNBA


def _sport_files(sport: str, pattern: str) -> list[Path]:
    roots = []
    env = os.environ.get("SYNDICATE_DATA_ROOT")
    if env:
        roots.append(Path(env) / f"{sport}_source")
    roots.append(Path(__file__).resolve().parents[3] / "data" / f"{sport}_source")
    out: list[Path] = []
    for root in roots:
        for rel in ("data/processed", "source_artifacts/data/processed"):
            out += sorted((root / rel).glob(pattern))
    return out


def _espn_scoreboard_events(sport: str, date_str: str) -> list[dict[str, Any]]:
    """[{game_id, home, away, completed, home_score, away_score}] from ESPN's
    scoreboard cache. The cache is often the PRE-game snapshot (10-10 NBA read
    'Scheduled' after the games), so it is trusted for WHO is home, and for a
    score only when it says completed."""
    files = _sport_files(sport, f"_espn_cache/scoreboard_{date_str.replace('-', '')}.json")
    if not files:
        return []
    try:
        payload = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for event in payload.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, Mapping)}
        home, away = sides.get("home") or {}, sides.get("away") or {}
        ha, aa = (home.get("team") or {}).get("abbreviation"), (away.get("team") or {}).get("abbreviation")
        if not ha or not aa:
            continue
        completed = bool(((event.get("status") or {}).get("type") or {}).get("completed"))
        out.append({"game_id": str(event.get("id") or ""), "home": ha, "away": aa, "completed": completed,
                    "home_score": _num(home.get("score")) if completed else None,
                    "away_score": _num(away.get("score")) if completed else None})
    return out


_BASKETBALL_RECON_STATS = {"pts": "points", "reb": "rebounds", "ast": "assists", "threes": "threes",
                           "stl": "steals", "blk": "blocks", "tov": "turnovers"}
_BASKETBALL_BOX_STATS = {"PTS": "points", "REB": "rebounds", "AST": "assists", "FG3M": "threes",
                         "STL": "steals", "BLK": "blocks", "TOV": "turnovers"}


def _basketball_players(sport: str, date_str: str) -> dict[str, list[dict[str, Any]]]:
    """{game_id: players} from `recon_props_<date>.csv` (the pipeline's own
    actuals), else `boxscores_<date>.csv`. 0 minutes = did not play = absent."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pattern, cols, name_col, team_col, id_col, min_col in (
        (f"recon_props_{date_str}.csv", _BASKETBALL_RECON_STATS, "player_name", "team_abbr", "player_id", "min"),
        (f"boxscores_{date_str}.csv", _BASKETBALL_BOX_STATS, "PLAYER_NAME", "TEAM_ABBREVIATION", "PLAYER_ID", "MIN"),
    ):
        files = _sport_files(sport, pattern)
        if not files:
            continue
        with open(files[0], encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                minutes = _num(str(row.get(min_col) or "").split(":")[0])
                name = str(row.get(name_col) or "").strip()
                if not minutes or not name:
                    continue
                stats = {key: (_num(row.get(col)) or 0.0) for col, key in cols.items()}
                stats["pra"] = stats["points"] + stats["rebounds"] + stats["assists"]
                stats["pts_reb"] = stats["points"] + stats["rebounds"]
                stats["pts_ast"] = stats["points"] + stats["assists"]
                stats["reb_ast"] = stats["rebounds"] + stats["assists"]
                stats["stl_blk"] = stats["steals"] + stats["blocks"]
                out[str(row.get("game_id") or row.get("gameId") or "")].append({
                    "id": str(row.get(id_col) or ""), "name": name, "name_key": _name_key(name),
                    "team": row.get(team_col), PROP_GROUP: stats})
        if out:
            break
    return out


def _basketball_rows_for_date(sport: str, date_str: str) -> list[dict[str, Any]]:
    """Score rows: `recon_games` (home_tri/away_tri/home_pts/visitor_pts),
    else ESPN completed events, else box points summed per team with ESPN's
    home/away -- only when the box covers BOTH teams."""
    rows: list[dict[str, Any]] = []
    games: dict[str, dict[str, Any]] = {}
    files = _sport_files(sport, f"recon_games_{date_str}.csv")
    if files:
        with open(files[0], encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                hs, as_ = _num(row.get("home_pts")), _num(row.get("visitor_pts"))
                gid = str(row.get("game_id") or row.get("gameId") or "")
                if gid and hs is not None and as_ is not None and row.get("home_tri") and row.get("away_tri"):
                    games[gid] = {"game_id": gid, "home": row["home_tri"], "away": row["away_tri"], "home_score": hs, "away_score": as_}
    events = _espn_scoreboard_events(sport, date_str)
    players = _basketball_players(sport, date_str)
    for event in events:
        if event["game_id"] in games:
            continue
        if event["completed"] and event["home_score"] is not None:
            games[event["game_id"]] = event
            continue
        box = players.get(event["game_id"]) or []
        by_team: dict[str, float] = defaultdict(float)
        for p in box:
            by_team[str(p.get("team") or "")] += p[PROP_GROUP]["points"]
        if event["home"] in by_team and event["away"] in by_team:
            games[event["game_id"]] = {**event, "home_score": by_team[event["home"]], "away_score": by_team[event["away"]]}
    for game in games.values():
        rows.append(_score_row(sport, game["game_id"], game["home"], game["away"], game["home_score"], game["away_score"],
                               "basketball_actuals", game_date=date_str))
        box = players.get(game["game_id"]) or []
        if box:
            rows.append(_box_row(sport, game["game_id"], game["home"], game["away"], box, "basketball_actuals", game_date=date_str))
    return rows


def nba_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    return _basketball_rows_for_date("nba", date_str)


def wnba_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    return _basketball_rows_for_date("wnba", date_str)


# ------------------------------------------------------------------- window

# A board (ledger) date carries picks for its whole horizon -- the 10-08 board
# already holds Sunday 10-11 NFL picks -- and settlement asks for the LEDGER
# date's graded rows. So each sport's rows are built for the ledger date and
# the days after it; every row is tagged with its own `game_date`, and the
# fixture join requires the pick's own game date to match it.
WINDOW_DAYS = 8

_BUILDERS = {"nfl": nfl_rows_for_date, "nhl": nhl_rows_for_date, "nba": nba_rows_for_date, "wnba": wnba_rows_for_date}


def rows_for_ledger_date(sport: str, date_str: str, *, days: int = WINDOW_DAYS) -> list[dict[str, Any]]:
    from datetime import date, timedelta

    builder = _BUILDERS.get(str(sport or "").lower())
    if builder is None:
        return []
    try:
        start = date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return []
    out: list[dict[str, Any]] = []
    for offset in range(days):
        try:
            out.extend(builder((start + timedelta(days=offset)).isoformat()))
        except Exception as exc:  # noqa: BLE001 -- one bad day must not cost the rest
            print(f"[settlement_sport_rows] BUILD_FAILED sport={sport} date={start + timedelta(days=offset)} error={type(exc).__name__}", flush=True)
    return out
