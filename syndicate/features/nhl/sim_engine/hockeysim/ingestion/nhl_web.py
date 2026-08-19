"""Thin NHL StatsWeb (api-web.nhle.com) client for ingestion — schedule + boxscore TOI.

Focused on what the owned lineup/goalie collector needs: a team's recent finished games and each
game's per-player time-on-ice. Boxscore payloads are disk-cached (like the truth loader) so
collection is reproducible and tests can run offline against a cache.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

_NHLE_BASE = (os.getenv("NHLE_BASE_URL", "https://api-web.nhle.com/v1") or "").rstrip("/")
_FINISHED = {"OFF", "FINAL"}


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


class NhlWebIngestClient:
    """Cache-first NHL api-web client for ingestion (schedule + boxscore)."""

    def __init__(self, *, cache_dir: Optional[Path] = None, rate_limit_per_sec: float = 5.0,
                 timeout: float = 30.0, offline: bool = False) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else _default_cache_dir()
        self._min_interval = 1.0 / rate_limit_per_sec if rate_limit_per_sec > 0 else 0.0
        self._timeout = timeout
        self._offline = offline
        self._last = 0.0

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

    def recent_finished_game_ids(self, team_abbr: str, season: str, *, before_date: str, n: int = 8) -> List[str]:
        """The team's last ``n`` finished game ids strictly before ``before_date`` this season."""
        data = self._get(f"{_NHLE_BASE}/club-schedule-season/{team_abbr}/{season}")
        if not data:
            return []
        out: List[str] = []
        for g in data.get("games", []):
            if g.get("gameState") not in _FINISHED:
                continue
            gdate = str(g.get("gameDate") or "")[:10]
            if before_date and gdate >= before_date:
                continue
            gid = g.get("id")
            if gid is not None:
                out.append(str(gid))
        return out[-n:] if n and len(out) > n else out
