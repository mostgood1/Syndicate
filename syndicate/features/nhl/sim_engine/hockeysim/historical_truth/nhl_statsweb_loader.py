"""NHL StatsWeb truth loader — real finished-game feeds -> HistoricalGameRecord.

Reads the public ``api-web.nhle.com/v1`` endpoints (the same source ``syndicate.local_nhl_odds``
already uses):
  * ``/score/{date}``            -> the day's games + final states (to enumerate finished games)
  * ``/gamecenter/{id}/landing`` -> one finished game's full settled feed (score, sog, per-period
                                    goals with strength / empty-net flags, OT/SO markers)

Every fetched ``landing`` payload is cached to disk (``data/nhl_source/data/truth/raw``) so a truth
baseline is reproducible offline and tests never hit the network. Parsing is pure (``parse_landing``
takes a dict), so the aggregation + unit tests run without a connection.

This is offline/analysis tooling (a producer-side concern), not a request-path reader — consistent
with the render/worker split: the web service never calls this.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .contracts import HistoricalGameRecord

_NHLE_BASE = (os.getenv("NHLE_BASE_URL", "https://api-web.nhle.com/v1") or "").rstrip("/")
_FINISHED_STATES = {"OFF", "FINAL"}


def _default_cache_dir() -> Path:
    # loader.py -> historical_truth -> hockeysim -> sim_engine -> nhl -> features -> syndicate -> repo
    repo = Path(__file__).resolve().parents[6]
    root = os.getenv("SYNDICATE_ARTIFACT_ROOT_NHL")
    base = Path(root) if root else repo / "data" / "nhl_source"
    return base / "data" / "truth" / "raw"


class NhlStatsWebTruthLoader:
    """Fetches + caches real finished-game feeds and parses them into truth records."""

    def __init__(
        self,
        *,
        cache_dir: Optional[Path] = None,
        rate_limit_per_sec: float = 4.0,
        timeout: float = 30.0,
        offline: bool = False,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else _default_cache_dir()
        self._min_interval = 1.0 / rate_limit_per_sec if rate_limit_per_sec > 0 else 0.0
        self._timeout = timeout
        self._offline = offline
        self._last_call = 0.0

    # -- low-level fetch (cache-first) --------------------------------------

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get_json(self, url: str) -> Dict:
        self._throttle()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Syndicate hockeysim truth)"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 (trusted public host)
            return json.loads(resp.read().decode("utf-8"))

    def _cached_landing(self, game_id: str) -> Optional[Dict]:
        path = self.cache_dir / f"landing_{game_id}.json"
        if path.exists() and path.stat().st_size > 0:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def fetch_landing(self, game_id: str, *, use_cache: bool = True) -> Optional[Dict]:
        """Return a game's landing payload, from disk cache if present else the network."""
        gid = str(game_id)
        if use_cache:
            cached = self._cached_landing(gid)
            if cached is not None:
                return cached
        if self._offline:
            return None
        data = self._get_json(f"{_NHLE_BASE}/gamecenter/{gid}/landing")
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"landing_{gid}.json").write_text(
                json.dumps(data), encoding="utf-8"
            )
        except OSError:
            pass
        return data

    def finished_game_ids_for_date(self, date: str, *, game_types: Iterable[int] = (2, 3)) -> List[str]:
        """Game ids for finished games on a date (``/score/{date}``). Network unless offline."""
        if self._offline:
            return []
        data = self._get_json(f"{_NHLE_BASE}/score/{date}")
        wanted = set(game_types)
        out: List[str] = []
        for g in data.get("games", []):
            if g.get("gameState") in _FINISHED_STATES and int(g.get("gameType", 0)) in wanted:
                gid = g.get("id")
                if gid is not None:
                    out.append(str(gid))
        return out

    # -- record assembly ----------------------------------------------------

    def load_dates(self, dates: Iterable[str], *, game_types: Iterable[int] = (2,)) -> List[HistoricalGameRecord]:
        """Load truth records for every finished game across a set of dates."""
        records: List[HistoricalGameRecord] = []
        for date in dates:
            for gid in self.finished_game_ids_for_date(date, game_types=game_types):
                landing = self.fetch_landing(gid)
                if not landing:
                    continue
                rec = parse_landing(landing)
                if rec is not None:
                    records.append(rec)
        return records

    def load_from_cache(self) -> List[HistoricalGameRecord]:
        """Parse every cached ``landing_*.json`` — a fully offline, network-free rebuild.

        Lets the truth baseline be regenerated deterministically from the local cache (no ``/score``
        or ``/gamecenter`` calls), which is what tests + reproducible report builds use.
        """
        records: List[HistoricalGameRecord] = []
        if not self.cache_dir.exists():
            return records
        for path in sorted(self.cache_dir.glob("landing_*.json")):
            try:
                landing = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rec = parse_landing(landing)
            if rec is not None:
                records.append(rec)
        return records


def _abbr_of(value: object) -> str:
    """Landing ``teamAbbrev`` may be a plain string or ``{'default': 'MTL'}``."""
    if isinstance(value, dict):
        return str(value.get("default") or "").upper()
    return str(value or "").upper()


def parse_landing(landing: Dict) -> Optional[HistoricalGameRecord]:
    """Parse a StatsWeb ``landing`` payload into a :class:`HistoricalGameRecord` (pure)."""
    if not isinstance(landing, dict):
        return None
    state = landing.get("gameState")
    if state not in _FINISHED_STATES:
        return None

    home = landing.get("homeTeam") or {}
    away = landing.get("awayTeam") or {}
    home_abbr = _abbr_of(home.get("abbrev"))
    away_abbr = _abbr_of(away.get("abbrev"))
    if not home_abbr or not away_abbr:
        return None

    def _int(v: object) -> int:
        try:
            return int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    summary = landing.get("summary") or {}
    scoring = summary.get("scoring") or []

    period_goals: List[tuple] = []
    pp_h = pp_a = en_h = en_a = 0
    went_ot = went_so = False

    for period in scoring:
        desc = period.get("periodDescriptor") or {}
        ptype = str(desc.get("periodType") or "REG").upper()
        goals = period.get("goals") or []
        if ptype == "SO":
            # Shootout: the winner is credited one goal in the final score, but no real period goal.
            went_so = True
            continue
        if ptype == "OT":
            went_ot = True
        h = a = 0
        for goal in goals:
            is_home = bool(goal.get("isHome"))
            # Fallback to team abbrev when isHome is absent.
            if "isHome" not in goal:
                is_home = _abbr_of(goal.get("teamAbbrev")) == home_abbr
            if is_home:
                h += 1
            else:
                a += 1
            strength = str(goal.get("strength") or "").lower()
            modifier = str(goal.get("goalModifier") or "").lower()
            if strength == "pp":
                if is_home:
                    pp_h += 1
                else:
                    pp_a += 1
            if modifier in ("empty-net", "empty_net", "emptynet"):
                if is_home:
                    en_h += 1
                else:
                    en_a += 1
        period_goals.append((h, a))

    # OT/SO can also be inferred from the final period descriptor.
    final_desc = landing.get("periodDescriptor") or {}
    final_ptype = str(final_desc.get("periodType") or "REG").upper()
    if final_ptype == "OT":
        went_ot = True
    elif final_ptype == "SO":
        went_ot = True
        went_so = True

    return HistoricalGameRecord(
        game_id=str(landing.get("id") or ""),
        date=str(landing.get("gameDate") or ""),
        season=str(landing.get("season") or ""),
        game_type=_int(landing.get("gameType")),
        home_abbr=home_abbr,
        away_abbr=away_abbr,
        home_goals=_int(home.get("score")),
        away_goals=_int(away.get("score")),
        home_sog=_int(home.get("sog")),
        away_sog=_int(away.get("sog")),
        period_goals=tuple(period_goals),
        pp_goals_home=pp_h,
        pp_goals_away=pp_a,
        en_goals_home=en_h,
        en_goals_away=en_a,
        went_ot=went_ot,
        went_shootout=went_so,
    )
