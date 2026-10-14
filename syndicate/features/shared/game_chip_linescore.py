"""The games-rail card's line score: per-interval scores, or R/H/E for baseball.

User request 2026-10-13 (lane games-rail-full-detail): "fit intervals into
them as well (quarters, periods, halves, etc -- innings would prob not be
helpful but for baseball maybe we do H/R/E like a traditional box?)".

`{"kind": "periods" | "rhe", "labels": [...], "away": [...], "home": [...]}`
on live and final chips, or nothing. Each sport reads the source that already
holds the numbers -- nothing is fetched here, nothing is inferred:

    nfl / ncaaf  game `live_state.away_linescores / home_linescores` (ESPN)
    nba / wnba   `pbp_espn_<date>.csv` -- cumulative score at each period's
                 last play, differenced (finals once the daily pbp lands)
    nhl          `ingestion_cache/landing_<gamePk>.json` summary.scoring --
                 goals counted per period by team (finals once cached)
    soccer       the poller's `match_box` home/away_linescores (one per half)
    mlb          `feed_live/<season>/<date>/<gamePk>.json.gz` linescore.teams
                 runs / hits / errors

A source that does not have the game yields None: the card keeps its plain
score rows. Display only.
"""

from __future__ import annotations

import csv
import glob
import gzip
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping

_LOCK = threading.Lock()
_CACHE: dict[tuple, tuple[float, Any]] = {}
_TTL_S = 60.0


def _cached(key: tuple, loader) -> Any:
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None and now - hit[0] < _TTL_S:
        return hit[1]
    try:
        value = loader()
    except Exception:  # noqa: BLE001 -- a line score must never break a chip
        value = None
    with _LOCK:
        _CACHE[key] = (now, value)
        if len(_CACHE) > 256:
            _CACHE.pop(next(iter(_CACHE)), None)
    return value


def _data_root() -> Path:
    env = os.environ.get("SYNDICATE_DATA_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[3] / "data"


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _period_labels(count: int, regulation: int, ot: str = "OT") -> list[str]:
    labels = [str(i + 1) for i in range(min(count, regulation))]
    extra = count - regulation
    labels += [ot if extra == 1 else f"{ot}{i + 1}" for i in range(extra)] if extra > 0 else []
    return labels


def _periods(away: list, home: list, regulation: int, ot: str = "OT") -> dict[str, Any] | None:
    away = [_int(v) for v in away or []]
    home = [_int(v) for v in home or []]
    n = max(len(away), len(home))
    if n == 0 or all(v is None for v in away + home):
        return None
    away += [None] * (n - len(away))
    home += [None] * (n - len(home))
    return {"kind": "periods", "labels": _period_labels(n, regulation, ot), "away": away, "home": home}


# ------------------------------------------------------------------ football

def _football(game: Mapping[str, Any]) -> dict[str, Any] | None:
    live = game.get("live_state") if isinstance(game.get("live_state"), Mapping) else {}
    return _periods(live.get("away_linescores") or [], live.get("home_linescores") or [], 4)


# ---------------------------------------------------------------- basketball

def _pbp_quarters(path: str) -> dict[str, tuple[list[int], list[int]]]:
    """{game id: (away per period, home per period)} from one day's ESPN pbp."""
    last: dict[str, dict[int, tuple[int, int]]] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            period, hs, as_ = _int(row.get("period")), _int(row.get("home_score")), _int(row.get("away_score"))
            if period is None or hs is None or as_ is None:
                continue
            for gid in {str(row.get("game_id") or ""), str(row.get("event_id") or "")} - {""}:
                last.setdefault(gid, {})[period] = (as_, hs)
    out: dict[str, tuple[list[int], list[int]]] = {}
    for gid, by_period in last.items():
        away, home, prev = [], [], (0, 0)
        for period in sorted(by_period):
            a, h = by_period[period]
            away.append(a - prev[0])
            home.append(h - prev[1])
            prev = (a, h)
        out[gid] = (away, home)
    return out


def _canon(sport: str, abbr: Any) -> str:
    """One spelling for a club across ESPN ("NY", "GS") and the cards ("NYK", "GSW")."""
    text = str(abbr or "").strip()
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        return chip_join_key(sport, text) or text.lower()
    except Exception:  # noqa: BLE001
        return text.lower()


def _tri(sport: str, game: Mapping[str, Any], side: str) -> str:
    container = game.get(side) if isinstance(game.get(side), Mapping) else {}
    return _canon(sport, game.get(f"{side}_tri") or container.get("abbr") or container.get("name"))


def _basketball(sport: str, game: Mapping[str, Any], date: str) -> dict[str, Any] | None:
    live = game.get("live_state") if isinstance(game.get("live_state"), Mapping) else {}
    periods = live.get("periods") if isinstance(live.get("periods"), list) else []
    if periods and all(isinstance(p, Mapping) for p in periods):
        got = _periods([p.get("away") for p in periods], [p.get("home") for p in periods], 4)
        if got:
            return got
    processed = _data_root() / f"{sport}_source" / "data" / "processed"
    daily = processed / f"linescores_{date}.json"
    if daily.is_file():
        st = daily.stat()
        games = _cached(("ls", str(daily), st.st_mtime_ns), lambda: json.loads(daily.read_text(encoding="utf-8")).get("games") or {}) or {}
        hit = next((games.get(str(game.get(k) or "")) for k in ("game_id", "event_id", "gamePk") if games.get(str(game.get(k) or ""))), None)
        if hit is None:
            want = (_tri(sport, game, "away"), _tri(sport, game, "home"))
            hit = next((g for g in games.values() if (_canon(sport, g.get("away")), _canon(sport, g.get("home"))) == want), None)
        if hit:
            return _periods(hit.get("away_periods") or [], hit.get("home_periods") or [], 4)
    path = processed / f"pbp_espn_{date}.csv"
    if not path.is_file():
        return None
    st = path.stat()
    table = _cached(("pbp", str(path), st.st_mtime_ns, st.st_size), lambda: _pbp_quarters(str(path))) or {}
    for key in ("game_id", "event_id", "gamePk"):
        hit = table.get(str(game.get(key) or ""))
        if hit:
            return _periods(hit[0], hit[1], 4)
    return None


# ----------------------------------------------------------------------- nhl

def _nhl_periods(path: str, away_abbr: str, home_abbr: str) -> dict[str, Any] | None:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    scoring = ((payload.get("summary") or {}).get("scoring")) or []
    away, home = [], []
    for block in scoring:
        desc = block.get("periodDescriptor") or {}
        if str(desc.get("periodType") or "").upper() == "SO":
            continue  # a shootout decides the game, not a period's score
        goals = block.get("goals") or []
        away.append(sum(1 for g in goals if str(g.get("teamAbbrev", {}).get("default") if isinstance(g.get("teamAbbrev"), Mapping) else g.get("teamAbbrev")).upper() == away_abbr))
        home.append(sum(1 for g in goals if str(g.get("teamAbbrev", {}).get("default") if isinstance(g.get("teamAbbrev"), Mapping) else g.get("teamAbbrev")).upper() == home_abbr))
    return _periods(away, home, 3)


def _nhl_game_ids(cache_dir: str) -> dict[tuple[str, str, str], str]:
    """{(gameDate, away, home): NHL game id} from the cached box scores. The
    NHL card's own `gamePk` is a slate index ("1"), not the league's id."""
    out: dict[tuple[str, str, str], str] = {}
    for path in glob.glob(os.path.join(cache_dir, "boxscore_*.json")):
        try:
            box = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        away = str((box.get("awayTeam") or {}).get("abbrev") or "").upper()
        home = str((box.get("homeTeam") or {}).get("abbrev") or "").upper()
        if box.get("gameDate") and away and home and box.get("id"):
            out[(str(box["gameDate"]), away, home)] = str(box["id"])
    return out


def _nhl(game: Mapping[str, Any], date: str, away_abbr: str, home_abbr: str) -> dict[str, Any] | None:
    cache_dir = _data_root() / "nhl_source" / "data" / "ingestion_cache"
    if not cache_dir.is_dir():
        return None
    ids = _cached(("nhl_ids", str(cache_dir), cache_dir.stat().st_mtime_ns), lambda: _nhl_game_ids(str(cache_dir))) or {}
    gid = ids.get((date, away_abbr, home_abbr))
    if not gid:
        return None
    path = cache_dir / f"landing_{gid}.json"
    if not path.is_file():
        return None
    st = path.stat()
    return _cached(("nhl", str(path), st.st_mtime_ns, away_abbr, home_abbr), lambda: _nhl_periods(str(path), away_abbr, home_abbr))


# -------------------------------------------------------------------- soccer

def _soccer(game: Mapping[str, Any], date: str) -> dict[str, Any] | None:
    event_id, league = str(game.get("event_id") or "").strip(), str(game.get("league") or "").strip()
    if not event_id or not league:
        return None

    def load() -> dict:
        from syndicate.features.soccer.sources import board_live_state_payload

        payload = board_live_state_payload(league, date) or {}
        return payload.get("match_box") if isinstance(payload.get("match_box"), Mapping) else {}

    box = (_cached(("soccer", league, date), load) or {}).get(event_id)
    if not isinstance(box, Mapping):
        return None
    got = _periods(box.get("away_linescores") or [], box.get("home_linescores") or [], 2, "ET")
    if got:
        got["labels"] = ["1H", "2H", "ET1", "ET2", "PK"][: len(got["labels"])]
    return got


# ----------------------------------------------------------------------- mlb

def _mlb_rhe(path: str) -> dict[str, Any] | None:
    with gzip.open(path, "rt", encoding="utf-8") if path.endswith(".gz") else open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    teams = (((payload.get("liveData") or {}).get("linescore") or {}).get("teams")) or {}
    away, home = teams.get("away") or {}, teams.get("home") or {}
    row = lambda t: [_int(t.get("runs")), _int(t.get("hits")), _int(t.get("errors"))]  # noqa: E731
    if row(away)[0] is None or row(home)[0] is None:
        return None
    return {"kind": "rhe", "labels": ["R", "H", "E"], "away": row(away), "home": row(home)}


def _mlb_live_board(date: str) -> dict[str, dict]:
    """{gamePk: {away / home [R, H, E], inning, half}} from StatsAPI's schedule
    with the linescore hydrated -- one request per date.

    User report 2026-10-14 ~02:25Z ("mlb score is wrong"): CLE @ TB live in the
    7th showed R/H/E 0 0 0 -- the cached feed_live file for a game that day is
    the PRE-game copy -- and "TOP 7" while StatsAPI read Bottom 7th, R/H/E
    1 6 1 / 3 7 0.
    """
    import urllib.request

    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}&hydrate=linescore"
    with urllib.request.urlopen(url, timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    out: dict[str, dict] = {}
    for day in payload.get("dates") or []:
        for g in day.get("games") or []:
            ls = g.get("linescore") or {}
            teams = ls.get("teams") or {}
            row = lambda t: [_int((teams.get(t) or {}).get(k)) for k in ("runs", "hits", "errors")]  # noqa: E731
            out[str(g.get("gamePk"))] = {"away": row("away"), "home": row("home"),
                                         "inning": _int(ls.get("currentInning")), "state": str(ls.get("inningState") or "")}
    return out


def _mlb_live(game: Mapping[str, Any], date: str) -> dict | None:
    pk = str(game.get("gamePk") or game.get("game_pk") or game.get("game_id") or "").strip()
    if not pk.isdigit():
        return None
    board = _cached(("mlb_live", date, int(time.monotonic() // _LIVE_TTL_S)), lambda: _mlb_live_board(date)) or {}
    return board.get(pk)


def mlb_inning_token(game: Mapping[str, Any], date: str) -> str | None:
    """"TOP 7" / "MID 7" / "BOT 7" / "END 7" from StatsAPI for a live game."""
    try:
        hit = _mlb_live(game, date)
    except Exception:  # noqa: BLE001
        return None
    if not hit or not hit.get("inning"):
        return None
    half = {"top": "TOP", "middle": "MID", "bottom": "BOT", "end": "END"}.get(hit["state"].lower())
    return f"{half} {hit['inning']}" if half else None


def _mlb(game: Mapping[str, Any], date: str) -> dict[str, Any] | None:
    pk = str(game.get("gamePk") or game.get("game_pk") or "").strip()
    if not pk.isdigit():
        return None
    base = _data_root() / "mlb_source" / "source_artifacts" / "data" / "raw" / "statsapi" / "feed_live"
    candidates = [base / date[:4] / date / f"{pk}.json.gz", base / date[:4] / date / f"{pk}.json"]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        found = glob.glob(str(base / date[:4] / "*" / f"{pk}.json*"))
        path = Path(sorted(found)[-1]) if found else None
    if path is None:
        return None
    st = path.stat()
    return _cached(("mlb", str(path), st.st_mtime_ns), lambda: _mlb_rhe(str(path)))


# --------------------------------------------------------- live (ESPN board)

# User report 2026-10-13 ~00:50Z: live NBA / NHL cards showed no periods. The
# finals sources above are daily files; the live sources drop the per-period
# numbers (NBA's ESPN-built live state hard-codes `periods: []`, NHL's schedule
# feed has none, and NHL's /score endpoint 403s a plain client). ESPN's
# scoreboard carries `competitors[].linescores` DURING play, one request per
# league per date -- measured that night: NBA CLE @ ORL 28 24 17 / 35 37 23,
# NHL FLA @ CBJ 0 4 2 / 1 0 1.
_ESPN_PATHS = {"nba": "basketball/nba", "wnba": "basketball/wnba", "nhl": "hockey/nhl",
               "nfl": "football/nfl", "ncaaf": "football/college-football"}
# All FBS games for college football (the default board is a curated subset);
# NOT for the NFL, where `groups` returns no events at all (measured 2026-10-14).
_ESPN_QUERY = {"ncaaf": "&groups=80&limit=300"}
_ESPN_ABBR_FIX = {"UTAH": "UTA"}
_LIVE_TTL_S = 45.0


def _espn_board(sport: str, date: str) -> dict[str, dict]:
    import urllib.request

    url = f"https://site.api.espn.com/apis/site/v2/sports/{_ESPN_PATHS[sport]}/scoreboard?dates={date.replace('-', '')}{_ESPN_QUERY.get(sport, '')}"
    # No custom User-Agent: ESPN 403s some UA strings (wnba/cards._public_scoreboard_live_state_payload).
    with urllib.request.urlopen(url, timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    out: dict[str, dict] = {}
    for event in payload.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, Mapping)}
        away, home = sides.get("away") or {}, sides.get("home") or {}
        status = event.get("status") or {}
        names = lambda c: {str(v).strip().lower() for v in ((c.get("team") or {}).get(k) for k in ("location", "displayName")) if v}  # noqa: E731
        situation = comp.get("situation") or {}
        out[str(event.get("id"))] = {
            "id": str(event.get("id")),
            "away_names": names(away),
            "home_names": names(home),
            "away_team_id": str((away.get("team") or {}).get("id") or ""),
            "home_team_id": str((home.get("team") or {}).get("id") or ""),
            "down_distance": str(situation.get("downDistanceText") or "").strip(),
            "possession": str(situation.get("possession") or ""),
            "red_zone": bool(situation.get("isRedZone")),
            "away": (away.get("team") or {}).get("abbreviation"),
            "home": (home.get("team") or {}).get("abbreviation"),
            "away_periods": [_int(x.get("value")) for x in away.get("linescores") or []],
            "home_periods": [_int(x.get("value")) for x in home.get("linescores") or []],
            "period": _int(status.get("period")),
            "clock": str(status.get("displayClock") or "").strip(),
            "status_name": str((status.get("type") or {}).get("name") or ""),
        }
    return out


def _espn_game(sport: str, game: Mapping[str, Any], date: str, away_abbr: str, home_abbr: str) -> dict | None:
    key = ("espn", sport, date, int(time.monotonic() // _LIVE_TTL_S))
    board = _cached(key, lambda: _espn_board(sport, date)) or {}
    hit = next((board[str(game.get(k))] for k in ("game_id", "event_id", "gamePk") if str(game.get(k) or "") in board), None)
    if hit is None and game.get("_away_key") and game.get("_home_key"):
        # Football card keys are nflverse ids / composite names, and NCAAF
        # tri-codes are the card's own ("TAM", "MIS"): join on the full name the
        # card carries (NFL "tampa bay buccaneers" == ESPN displayName, NCAAF
        # "west virginia" == ESPN location).
        ak, hk = str(game["_away_key"]).lower(), str(game["_home_key"]).lower()
        hit = next((g for g in board.values() if ak in g.get("away_names", ()) and hk in g.get("home_names", ())), None)
    if hit is None:
        want = (_canon(sport, away_abbr or _tri(sport, game, "away")), _canon(sport, home_abbr or _tri(sport, game, "home")))
        hit = next((g for g in board.values()
                    if (_canon(sport, _ESPN_ABBR_FIX.get(str(g.get("away")), g.get("away"))),
                        _canon(sport, _ESPN_ABBR_FIX.get(str(g.get("home")), g.get("home")))) == want), None)
    return hit


def live_clock_token(sport: str, game: Mapping[str, Any], date: str, *, away_abbr: str = "", home_abbr: str = "") -> str | None:
    """`P2 11:26`, or `END P2` between periods, from ESPN -- for a live chip whose
    own feed has no clock. NHL's schedule feed carries the period only (user
    report 2026-10-14 ~02:05Z: every live NHL card read "P3" while NBA read
    "Q4 9:33"); ESPN measured the same night: COL @ DAL 2 '11:26', MIN @ WPG
    2 '0:00' STATUS_END_PERIOD."""
    try:
        hit = _espn_game(sport, game, date, away_abbr, home_abbr) if sport in _ESPN_PATHS else None
    except Exception:  # noqa: BLE001 -- a clock must never break a chip
        return None
    if not hit or not hit.get("period"):
        return None
    prefix = "P" if sport == "nhl" else "Q"
    period = hit["period"]
    if sport == "nhl" and period >= 4:
        label = "OT" if period == 4 else "SO"
    elif sport in ("nfl", "ncaaf") and period >= 5:
        label = "OT" if period == 5 else f"OT{period - 4}"
    else:
        label = f"{prefix}{period}"
    if hit.get("status_name") == "STATUS_HALFTIME":
        return "HALF"
    if hit.get("status_name") == "STATUS_END_PERIOD":
        return f"END {label}"
    return f"{label} {hit['clock']}".strip() if hit.get("clock") else label


def _espn_fouls(sport: str, event_id: str) -> dict[str, dict]:
    """{"away"|"home": competitor `fouls` block} from ESPN's live game summary."""
    import urllib.request

    url = f"https://site.api.espn.com/apis/site/v2/sports/{_ESPN_PATHS[sport]}/summary?event={event_id}"
    with urllib.request.urlopen(url, timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    comp = (((payload.get("header") or {}).get("competitions")) or [{}])[0]
    return {str(c.get("homeAway")): (c.get("fouls") or {}) for c in comp.get("competitors") or [] if isinstance(c, Mapping)}


def live_bonus_text(sport: str, game: Mapping[str, Any], date: str, *, away_abbr: str = "", home_abbr: str = "") -> str | None:
    """"OKC in bonus" / "both in bonus" for a live NBA / WNBA game, or None.

    User report 2026-10-14 ~02:10Z: the basketball card's live line had the run
    but no bonus. ESPN's summary header gives each team's `fouls` block --
    measured that night on IND @ OKC: {"teamFouls": 18, "teamFoulsCurrent": 1,
    "foulsToGive": 3, "bonusState": "NONE"}. A team with NO fouls to give puts
    its OPPONENT in the bonus; that one field already folds in the 5th-foul and
    last-two-minutes rules, so nothing is re-derived here.
    """
    if sport not in ("nba", "wnba"):
        return None
    try:
        hit = _espn_game(sport, game, date, away_abbr, home_abbr)
        if not hit or not hit.get("id"):
            return None
        key = ("fouls", sport, hit["id"], int(time.monotonic() // _LIVE_TTL_S))
        fouls = _cached(key, lambda: _espn_fouls(sport, hit["id"])) or {}
    except Exception:  # noqa: BLE001 -- a bonus line must never break a chip
        return None

    def no_fouls_left(side: str) -> bool:
        value = _int((fouls.get(side) or {}).get("foulsToGive"))
        return value is not None and value <= 0

    away_in, home_in = no_fouls_left("home"), no_fouls_left("away")
    if away_in and home_in:
        return "both in bonus"
    if away_in:
        return f"{away_abbr or hit.get('away')} in bonus"
    if home_in:
        return f"{home_abbr or hit.get('home')} in bonus"
    return None


def football_situation(sport: str, game: Mapping[str, Any], date: str, *, away_abbr: str = "", home_abbr: str = "") -> str | None:
    """"KC ball · 3rd & 4 at BUF 32 · red zone" for a live NFL / NCAAF game."""
    try:
        hit = _espn_game(sport, game, date, away_abbr, home_abbr) if sport in ("nfl", "ncaaf") else None
    except Exception:  # noqa: BLE001
        return None
    if not hit or not hit.get("down_distance"):
        return None
    side = "away" if hit.get("possession") and hit["possession"] == hit.get("away_team_id") else (
        "home" if hit.get("possession") and hit["possession"] == hit.get("home_team_id") else None)
    parts = []
    if side:
        parts.append(f"{away_abbr if side == 'away' else home_abbr} ball")
    parts.append(hit["down_distance"])
    if hit.get("red_zone"):
        parts.append("red zone")
    return " · ".join(parts)


def espn_event_id(sport: str, game: Mapping[str, Any], date: str, *, away_abbr: str = "", home_abbr: str = "") -> str | None:
    """ESPN's event id for a live game (the NHL card's own key is a slate index)."""
    try:
        hit = _espn_game(sport, game, date, away_abbr, home_abbr) if sport in _ESPN_PATHS else None
    except Exception:  # noqa: BLE001
        return None
    return (hit or {}).get("id")


def _espn_linescore(sport: str, game: Mapping[str, Any], date: str, away_abbr: str, home_abbr: str) -> dict[str, Any] | None:
    hit = _espn_game(sport, game, date, away_abbr, home_abbr)
    if not hit or not hit["away_periods"] or not hit["home_periods"]:
        return None
    got = _periods(hit["away_periods"], hit["home_periods"], 3 if sport == "nhl" else 4)
    if got and sport == "nhl" and len(got["labels"]) == 5:
        # Regular season / preseason: one 5-minute OT, then the shootout, which
        # ESPN lists as a fifth "period" worth the one deciding goal (measured
        # 2026-10-13 BUF @ MTL 3-4: home 1 2 0 0 1). Not a second overtime.
        got["labels"] = ["1", "2", "3", "OT", "SO"]
    return got


def _recent(date: str) -> bool:
    from datetime import date as _date, timedelta

    from syndicate.features.shared.timezone import central_today_iso

    today = _date.fromisoformat(central_today_iso())
    return today - timedelta(days=1) <= _date.fromisoformat(date) <= today


def linescore(sport: str, game: Mapping[str, Any], date: str, *, away_abbr: str = "", home_abbr: str = "", live: bool = False) -> dict[str, Any] | None:
    sport = str(sport or "").lower()
    try:
        if sport in ("nfl", "ncaaf"):
            if live:
                got = _espn_linescore(sport, game, date, away_abbr, home_abbr)
                if got:
                    return got
            return _football(game)
        if sport in _ESPN_PATHS and live:
            return _espn_linescore(sport, game, date, away_abbr, home_abbr)
        if sport in ("nba", "wnba"):
            got = _basketball(sport, game, date)
            return got or (_espn_linescore(sport, game, date, away_abbr, home_abbr) if _recent(date) else None)
        if sport == "nhl":
            got = _nhl(game, date, away_abbr.upper(), home_abbr.upper())
            return got or (_espn_linescore(sport, game, date, away_abbr, home_abbr) if _recent(date) else None)
        if sport == "soccer":
            return _soccer(game, date)
        if sport == "mlb":
            # Today / yesterday from StatsAPI (live R/H/E; the day's feed file can
            # be a pre-game copy); older dates from the cached feed files.
            if live or _recent(date):
                hit = _mlb_live(game, date)
                if hit and None not in hit["away"] and None not in hit["home"]:
                    return {"kind": "rhe", "labels": ["R", "H", "E"], "away": hit["away"], "home": hit["home"]}
            return _mlb(game, date)
    except Exception:  # noqa: BLE001 -- a line score must never break a chip
        return None
    return None
