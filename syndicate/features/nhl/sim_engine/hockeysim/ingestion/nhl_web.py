"""Thin NHL StatsWeb (api-web.nhle.com) client for ingestion — schedule + boxscore TOI.

Focused on what the owned lineup/goalie collector needs: a team's recent finished games and each
game's per-player time-on-ice. Boxscore payloads are disk-cached (like the truth loader) so
collection is reproducible and tests can run offline against a cache.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

_NHLE_BASE = (os.getenv("NHLE_BASE_URL", "https://api-web.nhle.com/v1") or "").rstrip("/")
_FINISHED = {"OFF", "FINAL"}
_NOT_STARTED = {"FUT", "PRE"}  # the stats API holds no rows for a game that has not started
_NHL_STATS_BASE = (os.getenv("NHL_STATS_BASE_URL", "https://api.nhle.com/stats/rest/en") or "").rstrip("/")
_COMPETITIVE_GAME_TYPES = {2, 3}  # regular season, playoffs -- never preseason (1)

# THE STATS-REPORT CACHE `[2026-11-18, lane nhl-stats-rest-cache, todo #838 follow-up]`.
# Every slate team used to make 6 uncached `limit=-1` stats-REST calls per generation (timeonice +
# goalsForAgainst, gameType 2 and 3; goalsForAgainst for last season too): 168 for the 11-17 + 11-18
# slates. On 11-17 5 of 7 sampled calls took 21-44 s or returned 520, and the generation never fit
# its 1,800 s timeout (`findings_2026-11-17_odds_lane_sport_deadline.md`). With this on, a report is
#   * SKIPPED (empty) when the team's club schedule -- already fetched for the usage window -- lists
#     no game of that type: measured 64 of 64 team-seasons on 11-18, 48 such reports empty and the
#     16 playoff teams' reports holding exactly their scheduled finished playoff games;
#   * REUSED from disk when it already holds every FINISHED game of that type dated before the slate
#     date, none of them is in progress, and it is SETTLED (fetched >= SETTLE_HOURS after the newest
#     such game started) or younger than UNSETTLED_MAX_AGE_HOURS. The settle window is where an NHL
#     scoring change lands; a settled report is reused until the team finishes another game.
#   * otherwise fetched exactly as before, and written.
# Absent = ON. "off" (or 0/false/no) is the pre-cache transport, byte for byte: no skip, no read,
# no write.
STATS_CACHE_ENV = "SYNDICATE_NHL_STATS_REPORT_CACHE"
SETTLE_HOURS_ENV = "SYNDICATE_NHL_STATS_REPORT_SETTLE_HOURS"
UNSETTLED_MAX_AGE_ENV = "SYNDICATE_NHL_STATS_REPORT_UNSETTLED_MAX_AGE_HOURS"
# 18 h, not 24: games start at about the same hour every night, so start + 24 h is the NEXT evening's puck
# drop -- the hour the stats API was slowest on 11-17. Start + 18 h is ~noon CST next day, after the
# league's morning scoring reviews and while the pregame generations run on a healthy API.
DEFAULT_SETTLE_HOURS = 18.0
DEFAULT_UNSETTLED_MAX_AGE_HOURS = 6.0


def stats_report_cache_enabled() -> bool:
    return str(os.getenv(STATS_CACHE_ENV, "") or "").strip().lower() not in {"0", "off", "false", "no"}


def _env_hours(name: str, default: float) -> float:
    try:
        value = float(str(os.getenv(name, "") or "").strip())
    except ValueError:
        return default
    return value if value >= 0 else default


def _utc(text: object) -> Optional[datetime]:
    s = str(text or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _game_start_utc(game: Dict) -> Optional[datetime]:
    start = _utc(game.get("startTimeUTC"))
    if start is not None:
        return start
    # No start time: noon UTC the NEXT day, later than any North American local start on that date,
    # so a missing field can only lengthen the settle window, never shorten it.
    day = _utc(f"{str(game.get('gameDate') or '')[:10]}T12:00:00+00:00")
    return day + timedelta(days=1) if day is not None else None


def _season_complete(season: str, now: datetime) -> bool:
    """A season's games can no longer change once its playoffs are over: by Oct 1 of its end year
    (the 2020 bubble final ended Sep 28). Only gates the club-schedule disk cache below."""
    s = str(season or "")
    if len(s) != 8 or not s.isdigit():
        return False
    return now >= datetime(int(s[4:]), 10, 1, tzinfo=timezone.utc)


def season_code_for_date(date: str) -> str:
    """NHL season code ``YYYYYYYY`` (e.g. ``20252026``) from a ``YYYY-MM-DD`` date."""
    try:
        year = int(str(date)[:4])
        month = int(str(date)[5:7])
    except (ValueError, IndexError):
        return ""
    start = year if month >= 7 else year - 1
    return f"{start}{start + 1}"


def _default_cache_dir() -> Path:
    repo = Path(__file__).resolve().parents[6]
    root = os.getenv("SYNDICATE_ARTIFACT_ROOT_NHL")
    base = Path(root) if root else repo / "data" / "nhl_source"
    return base / "data" / "ingestion_cache"


def _default_stats_cache_dir() -> Path:
    """The stats-report cache lives under the DATA ROOT (`model_engine_standard.md`), not the checkout.

    Measured 11-18: the live-odds-worker sets no `SYNDICATE_ARTIFACT_ROOT_NHL`, so `_default_cache_dir()`
    -- the boxscore cache -- resolves to the fleet CHECKOUT (`~/Syndicate/data/nhl_source/...`, 578
    boxscores), while `SYNDICATE_DATA_ROOT/nhl_source/data/ingestion_cache` holds the other producers'
    1,092 files. A cache in a checkout is lost to a re-clone and invisible to every other reader."""
    root = os.getenv("SYNDICATE_ARTIFACT_ROOT_NHL")
    if root:
        return Path(root) / "data" / "ingestion_cache"
    data_root = os.getenv("SYNDICATE_DATA_ROOT")
    if data_root:
        return Path(data_root) / "nhl_source" / "data" / "ingestion_cache"
    return _default_cache_dir()


class NhlWebIngestClient:
    """Cache-first NHL api-web client for ingestion (schedule + boxscore)."""

    def __init__(self, *, cache_dir: Optional[Path] = None, rate_limit_per_sec: float = 5.0,
                 timeout: float = 30.0, offline: bool = False, stats_cache: Optional[bool] = None,
                 stats_cache_dir: Optional[Path] = None, now: Optional[Callable[[], datetime]] = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else _default_cache_dir()
        self._min_interval = 1.0 / rate_limit_per_sec if rate_limit_per_sec > 0 else 0.0
        self._timeout = timeout
        self._offline = offline
        self._last = 0.0
        # stats-report cache (see STATS_CACHE_ENV). An explicit cache_dir (tests, backtests) holds it too.
        self.stats_cache = stats_report_cache_enabled() if stats_cache is None else bool(stats_cache)
        self.stats_cache_dir = (Path(stats_cache_dir) if stats_cache_dir
                                else Path(cache_dir) if cache_dir else _default_stats_cache_dir())
        self._settle = timedelta(hours=_env_hours(SETTLE_HOURS_ENV, DEFAULT_SETTLE_HOURS))
        self._unsettled_max_age = timedelta(hours=_env_hours(UNSETTLED_MAX_AGE_ENV, DEFAULT_UNSETTLED_MAX_AGE_HOURS))
        self._now = now or (lambda: datetime.now(timezone.utc))
        # The club schedule each (TEAM, season) last returned in THIS process -- recorded, never reused for
        # the usage window itself (`_finished_competitive_ids` still fetches every time).
        self._schedules: Dict[Tuple[str, str], List[Dict]] = {}
        # outcome -> count, for the per-date line collect.py prints: fetch:<reason> / hit / skip_empty
        self.stats_report_counts: Counter = Counter()
        self.stats_fetch_seconds = 0.0

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _get(self, url: str) -> Optional[Dict]:
        if self._offline:
            return None
        self._throttle()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Syndicate hockeysim ingest)"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 (trusted public host)
            return json.loads(resp.read().decode("utf-8"))

    def boxscore(self, game_id: str, *, use_cache: bool = True) -> Optional[Dict]:
        gid = str(game_id)
        path = self.cache_dir / f"boxscore_{gid}.json"
        if use_cache and path.exists() and path.stat().st_size > 0:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        data = self._get(f"{_NHLE_BASE}/gamecenter/{gid}/boxscore")
        if data is not None:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
        return data

    def play_by_play(self, game_id: str, *, use_cache: bool = True) -> Optional[Dict]:
        """`plays[]` with event coordinates -- the substrate for a real shot-quality (xG) model
        (`historical_truth/shot_xg_model.py`). Same cache-first convention as `boxscore()`, its own
        cache key (`playbyplay_{gid}.json`) so both endpoints for a game can be cached side by
        side without collision."""
        gid = str(game_id)
        path = self.cache_dir / f"playbyplay_{gid}.json"
        if use_cache and path.exists() and path.stat().st_size > 0:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        data = self._get(f"{_NHLE_BASE}/gamecenter/{gid}/play-by-play")
        if data is not None:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
        return data

    def roster_full_names(self, team_abbr: str, season: str) -> Dict[int, str]:
        """``{player_id: "First Last"}`` from the club roster.

        The boxscore's ``name.default`` is ABBREVIATED ("A. Copp") while every sportsbook prop line
        carries the full name ("Andrew Copp"), so a lineup built from boxscores alone cannot be
        joined to a book line by name. Not cached: a roster changes through the season, and it is
        one call per team. An unreachable roster returns ``{}`` and the caller keeps the boxscore
        name.
        """
        try:
            data = self._get(f"{_NHLE_BASE}/roster/{team_abbr}/{season}")
        except Exception:  # noqa: BLE001 - names are an enrichment; the lineup must still build
            return {}
        out: Dict[int, str] = {}
        for group in ("forwards", "defensemen", "goalies"):
            for p in (data or {}).get(group) or []:
                first = (p.get("firstName") or {}).get("default") if isinstance(p.get("firstName"), dict) else p.get("firstName")
                last = (p.get("lastName") or {}).get("default") if isinstance(p.get("lastName"), dict) else p.get("lastName")
                name = " ".join(str(x).strip() for x in (first, last) if x and str(x).strip())
                if p.get("id") is not None and name:
                    out[int(p["id"])] = name
        return out

    def _finished_competitive_ids(self, team_abbr: str, season: str, before_date: str) -> List[str]:
        data = self._get(f"{_NHLE_BASE}/club-schedule-season/{team_abbr}/{season}")
        self._record_schedule(team_abbr, season, data)
        out: List[str] = []
        for g in (data or {}).get("games", []):
            if g.get("gameState") not in _FINISHED:
                continue
            if int(g.get("gameType") or 0) not in _COMPETITIVE_GAME_TYPES:
                continue
            gdate = str(g.get("gameDate") or "")[:10]
            if before_date and gdate >= before_date:
                continue
            gid = g.get("id")
            if gid is not None:
                out.append(str(gid))
        return out

    # ---- stats-report cache (STATS_CACHE_ENV) ------------------------------------------------------
    @staticmethod
    def _usable_schedule(data: object) -> Optional[List[Dict]]:
        """The schedule's games, or None unless it is evidently real: it must list a regular-season
        game. An empty or malformed payload must read as UNKNOWN (fetch the report), never as "no
        games of that type" (skip it) -- that would silently turn an outage into an empty report."""
        games = (data or {}).get("games") if isinstance(data, dict) else None
        if not isinstance(games, list):
            return None
        if not any(isinstance(g, dict) and str(g.get("gameType")) == "2" for g in games):
            return None
        return [g for g in games if isinstance(g, dict)]

    def _record_schedule(self, team_abbr: str, season: str, data: object) -> None:
        games = self._usable_schedule(data)
        if games is not None:
            self._schedules[(str(team_abbr).upper(), str(season))] = games

    def _season_games(self, team_abbr: str, season: str) -> Optional[List[Dict]]:
        """The team's club schedule for the season: the one fetched for the usage window in this process
        if any; for a COMPLETE season, a disk copy (written only when every competitive game in it is
        final); otherwise a fresh fetch. None when unknown."""
        key = (str(team_abbr).upper(), str(season))
        if key in self._schedules:
            return self._schedules[key]
        path = self.stats_cache_dir / f"club_schedule_{key[0]}_{key[1]}.json"
        complete = _season_complete(key[1], self._now())
        if complete and path.exists():
            try:
                games = self._usable_schedule(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                games = None
            if games is not None:
                self._schedules[key] = games
                return games
        try:
            data = self._get(f"{_NHLE_BASE}/club-schedule-season/{key[0]}/{key[1]}")
        except Exception:  # noqa: BLE001 - unknown schedule -> the report is fetched, as before
            return None
        self._record_schedule(key[0], key[1], data)
        games = self._schedules.get(key)
        if games is not None and complete and all(
                g.get("gameState") in _FINISHED or g.get("gameScheduleState") == "CNCL"
                for g in games if str(g.get("gameType")) in ("2", "3")):
            self._write_json(path, data)
        return games

    def _write_json(self, path: Path, data: object) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, path)  # atomic: a concurrent reader sees the old file or the new one
        except OSError:
            pass

    def _report_plan(self, team_abbr: str, season: str, game_type: int,
                     before_date: str) -> Tuple[str, Set[str], Optional[datetime]]:
        """("skip_empty" | "check" | "fetch:<reason>", required game ids, newest required start)."""
        games = self._season_games(team_abbr, season)
        if games is None:
            return "fetch:no_schedule", set(), None
        typed = [g for g in games if str(g.get("gameType")) == str(game_type)]
        if not typed:
            return "skip_empty", set(), None
        relevant = [g for g in typed if str(g.get("gameDate") or "")[:10] < str(before_date)[:10]]
        if any(g.get("gameState") not in _FINISHED | _NOT_STARTED for g in relevant):
            return "fetch:in_progress", set(), None  # a live game's rows move under any cached copy
        finished = [g for g in relevant if g.get("gameState") in _FINISHED and g.get("id") is not None]
        starts = [s for s in (_game_start_utc(g) for g in finished) if s is not None]
        return "check", {str(g["id"]) for g in finished}, (max(starts) if starts else None)

    def _stats_report(self, report: str, team_abbr: str, season: str, game_type: int,
                      before_date: Optional[str]) -> Optional[Dict]:
        exp = urllib.parse.quote(f'teamAbbrev="{team_abbr}" and seasonId={season} and gameTypeId={game_type}')
        url = f"{_NHL_STATS_BASE}/skater/{report}?isAggregate=false&isGame=true&limit=-1&cayenneExp={exp}"
        if not self.stats_cache or not before_date:
            # the pre-cache transport: same call, no read, no write -- only counted, so the switch-off line
            # in a role log is a real baseline
            self.stats_report_counts["fetch:off" if not self.stats_cache else "fetch:no_date"] += 1
            t0 = time.monotonic()
            try:
                return self._get(url)
            finally:
                self.stats_fetch_seconds += time.monotonic() - t0
        plan, required, newest_start = self._report_plan(team_abbr, season, game_type, before_date)
        if plan == "skip_empty":
            self.stats_report_counts["skip_empty"] += 1
            return {"data": [], "total": 0}
        path = self.stats_cache_dir / f"statsrest_{report}_{str(team_abbr).upper()}_{season}_gt{game_type}.json"
        reason = plan.split(":", 1)[1] if plan.startswith("fetch:") else "no_cache"
        if plan == "check" and path.exists():
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                payload = entry.get("payload")
                fetched_at = _utc(entry.get("fetched_at_utc"))
                held = {str(int(r["gameId"])) for r in (payload or {}).get("data") or []
                        if isinstance(r, dict) and str(r.get("gameId") or "").isdigit()}
            except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
                payload, fetched_at, held = None, None, set()
            if not isinstance(payload, dict) or fetched_at is None:
                reason = "unreadable"
            elif not required <= held:
                reason = "new_game"
            elif newest_start is None or fetched_at >= newest_start + self._settle:
                self.stats_report_counts["hit"] += 1
                return payload
            elif self._now() - fetched_at <= self._unsettled_max_age:
                self.stats_report_counts["hit_unsettled"] += 1
                return payload
            else:
                reason = "unsettled_stale"
        self.stats_report_counts[f"fetch:{reason}"] += 1
        t0 = time.monotonic()
        fetched_at = self._now()
        try:
            data = self._get(url)
        finally:
            self.stats_fetch_seconds += time.monotonic() - t0
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            self._write_json(path, {"fetched_at_utc": fetched_at.isoformat(), "url": url, "payload": data})
        return data

    def special_teams_toi(self, team_abbr: str, season: str, *,
                          before_date: Optional[str] = None) -> Dict[str, Dict[int, Tuple[float, float]]]:
        """``{game_id: {player_id: (pp_seconds, sh_seconds)}}`` for one team's regular-season and
        playoff games of a season, from the NHL stats API's per-game time-on-ice report.

        The api-web boxscore carries only TOTAL ice time, so power-play / penalty-kill units used
        to be the top skaters by total TOI with a forced 3F+2D shape; real PP1s are often 4F+1D
        (Montreal 2025-26: Suzuki, Caufield, Hutson, Slafkovsky, Demidov) `[2026-10-04, lane
        nhl-pp-units-real-toi]`. One call per team per game type; an unreachable report returns
        ``{}`` and the caller keeps its positional fallback. Needs the browser-style User-Agent
        ``_get`` sends -- Python's default is refused with 403.

        ``before_date`` (the slate date) opts into the stats-report cache (``STATS_CACHE_ENV``): the
        cache must hold every finished game of the type dated before it. Without it, always fetched.
        """
        out: Dict[str, Dict[int, Tuple[float, float]]] = {}
        for game_type in (2, 3):
            try:
                data = self._stats_report("timeonice", team_abbr, season, game_type, before_date)
            except Exception:  # noqa: BLE001 - special-teams minutes are an enrichment
                continue
            for row in (data or {}).get("data") or []:
                try:
                    gid = str(int(row.get("gameId")))
                    pid = int(row.get("playerId"))
                    pp = float(row.get("ppTimeOnIce") or 0.0)
                    sh = float(row.get("shTimeOnIce") or 0.0)
                except (TypeError, ValueError):
                    continue
                out.setdefault(gid, {})[pid] = (pp, sh)
        return out

    def onice_goals(self, team_abbr: str, season: str, *,
                    before_date: Optional[str] = None) -> Dict[str, Tuple[str, Dict[int, Tuple[int, int]]]]:
        """``{game_id: (game_date, {player_id: (teammate_goals_on_ice, assists)})}`` for one team's
        regular-season and playoff games of a season, from the NHL stats API's per-game
        ``skater/goalsForAgainst`` report. ``teammate_goals_on_ice`` = on-ice goals for (EV + PP + SH)
        minus the player's own goals: the goals he could have assisted on.

        Feeds `lineups.attach_assist_share` `[2026-10-05, lane nhl-elite-assists]`; the boxscore has
        assists but no on-ice goals, so assists per game cannot tell a playmaker from a passenger on
        a high-scoring line. Same transport and failure mode as `special_teams_toi`: an unreachable
        report returns ``{}`` and the share falls back to its position prior. ``before_date``: as in
        `special_teams_toi` -- the share reads every game dated before it, which is what the cache checks.
        """
        out: Dict[str, Tuple[str, Dict[int, Tuple[int, int]]]] = {}
        for game_type in (2, 3):
            try:
                data = self._stats_report("goalsForAgainst", team_abbr, season, game_type, before_date)
            except Exception:  # noqa: BLE001 - an enrichment; the lineup must still build
                continue
            for row in (data or {}).get("data") or []:
                try:
                    gid = str(int(row.get("gameId")))
                    pid = int(row.get("playerId"))
                    gf = sum(int(row.get(k) or 0) for k in ("evenStrengthGoalsFor", "powerPlayGoalFor", "shortHandedGoalsFor"))
                    goals = int(row.get("goals") or 0)
                    assists = int(row.get("assists") or 0)
                except (TypeError, ValueError):
                    continue
                entry = out.setdefault(gid, (str(row.get("gameDate") or "")[:10], {}))
                entry[1][pid] = (max(0, gf - goals), assists)
        return out

    def recent_finished_game_ids(self, team_abbr: str, season: str, *, before_date: str, n: int = 8) -> List[str]:
        """The team's last ``n`` finished REGULAR-SEASON or PLAYOFF game ids strictly before ``before_date``.

        PRESEASON GAMES ARE EXCLUDED, and an early-season window is topped up from the PREVIOUS
        season's last games `[2026-10-03, lane nhl-player-props-projection]`. Two days into 2026-27
        the window was all preseason split-squad games, so stars were slotted on the third and fourth
        lines (Caufield L3 12.5 min, Batherson L4 12.2) and the 10-03 board priced 29 of 53 SOG lines
        at >10% edge, every big one an under, projections 0.31 shots below the player's own average.
        """
        out = self._finished_competitive_ids(team_abbr, season, before_date)
        if n and len(out) < n and len(str(season)) == 8 and str(season).isdigit():
            start = int(str(season)[:4])
            prev = self._finished_competitive_ids(team_abbr, f"{start - 1}{start}", before_date)
            out = prev + out
        return out[-n:] if n and len(out) > n else out