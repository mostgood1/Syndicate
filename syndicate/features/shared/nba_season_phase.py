"""NBA season phase -- preseason / regular / play_in / postseason -- for a slate date (lane `nba-season-phase`).

WHY. Nothing in the NBA lines/props path knew the season phase (findings "NBA season phase", design
`.syndicate/design_2026-10-05_nba_season_phase.md`). A preseason game is a different population (starters ~20
minutes, 15-deep rotations), and preseason rows must never enter a regular-season window.

SOURCES, in order:
  1. the ESPN scoreboard the sim caches for the date (`_espn_cache/nba/scoreboard_<ymd>.json`,
     `events[].season.type`) -- what the game itself says;
  2. ESPN's season-types table for the season (`seasons/<end year>/types`: each phase's start/end), cached once per
     season beside the scoreboards -- covers dates with no scoreboard yet (future slates, history windows).
ESPN codes: 1 preseason, 2 regular, 3 postseason, 5 play-in (4 off-season). Measured 2026-10-05 for 2027: preseason
2026-09-30..10-20 06:59Z, regular 10-20 07:00Z..2027-04-12 06:59Z, play-in ..04-17, postseason ..06-26.

UNKNOWN IS NEVER "REGULAR": every function returns None when it cannot tell, and every caller treats None as its
most conservative branch. Never raises.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

PHASE_BY_TYPE = {1: "preseason", 2: "regular", 3: "postseason", 4: "off_season", 5: "play_in"}
TYPES_URL = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{year}/types"
# ESPN's boundaries are 07:00Z (midnight US Pacific); a slate's local calendar date d belongs to the phase whose
# [start, end) contains d at noon UTC.
_LOCAL_OFFSET = timedelta(hours=7)


def _cache_dir(processed_root: Optional[Path]) -> Optional[Path]:
    if processed_root is None:
        try:
            from syndicate.features.nba.sources import artifact_processed_root
            processed_root = artifact_processed_root()
        except Exception:  # noqa: BLE001
            return None
    return Path(processed_root) / "_espn_cache" / "nba"


def season_end_year(date_str: str) -> int:
    """The ESPN season year (the calendar year the season ENDS in): 2026-10-05 -> 2027, 2026-04-01 -> 2026."""
    y, m = int(str(date_str)[:4]), int(str(date_str)[5:7])
    return y + 1 if m >= 7 else y


def _parse(ts: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(ts).replace("Z", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return None


def _fetch_types(year: int, timeout: float = 10.0) -> Optional[List[Dict]]:
    hdr = {"User-Agent": "Mozilla/5.0"}
    doc = json.load(urllib.request.urlopen(urllib.request.Request(TYPES_URL.format(year=year), headers=hdr), timeout=timeout))
    out = []
    for item in doc.get("items") or []:
        ref = str(item.get("$ref") or "").replace("http://", "https://")
        x = json.load(urllib.request.urlopen(urllib.request.Request(ref, headers=hdr), timeout=timeout))
        out.append({"type": int(x.get("type")), "name": x.get("name"), "start": x.get("startDate"), "end": x.get("endDate")})
    return out or None


@lru_cache(maxsize=16)
def _types_cached(cache_s: str, year: int, allow_fetch: bool) -> Optional[tuple]:
    path = Path(cache_s) / f"season_types_{year}.json"
    rows = None
    try:
        if path.is_file():
            rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        rows = None
    if not rows and allow_fetch:
        try:
            rows = _fetch_types(year)
            if rows:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            rows = None
    if not rows:
        return None
    return tuple((int(r["type"]), str(r.get("start") or ""), str(r.get("end") or "")) for r in rows)


def season_types(date_str: str, *, processed_root: Optional[Path] = None, allow_fetch: bool = True) -> Optional[tuple]:
    """((type, start_iso, end_iso), ...) for the season containing date_str, or None."""
    cache = _cache_dir(processed_root)
    if cache is None:
        return None
    return _types_cached(str(cache), season_end_year(date_str), bool(allow_fetch))


def _phase_from_scoreboard(date_str: str, cache: Path) -> Optional[str]:
    path = cache / f"scoreboard_{str(date_str)[:10].replace('-', '')}.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        types = {int((ev.get("season") or {}).get("type")) for ev in doc.get("events") or []
                 if (ev.get("season") or {}).get("type") is not None}
    except Exception:  # noqa: BLE001
        return None
    return PHASE_BY_TYPE.get(types.pop()) if len(types) == 1 else None


def phase_for_date(date_str: str, *, processed_root: Optional[Path] = None, allow_fetch: bool = True) -> Optional[str]:
    """The phase of a slate date, or None (unknown). Scoreboard first, then the season-types table."""
    try:
        d = str(date_str)[:10]
        cache = _cache_dir(processed_root)
        if cache is None:
            return None
        hit = _phase_from_scoreboard(d, cache)
        if hit:
            return hit
        noon = datetime.strptime(d, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
        year = season_end_year(d)
        # Jul-Sep dates belong to the NEXT season by year arithmetic, but ESPN files that summer's off-season under
        # the season that just ended, so try the adjacent table when the first has no range covering the date.
        for yr in (year, year - 1):
            rows = _types_cached(str(cache), yr, bool(allow_fetch))
            for t, start, end in rows or ():
                s, e = _parse(start), _parse(end)
                if s and e and s <= noon < e:
                    return PHASE_BY_TYPE.get(t)
        return None
    except Exception:  # noqa: BLE001
        return None


def phase_start(date_str: str, phase: str, *, processed_root: Optional[Path] = None,
                allow_fetch: bool = True) -> Optional[str]:
    """First local date (YYYY-MM-DD) of `phase` in the season containing date_str, or None."""
    want = {v: k for k, v in PHASE_BY_TYPE.items()}.get(str(phase))
    rows = season_types(str(date_str)[:10], processed_root=processed_root, allow_fetch=allow_fetch) if want else None
    for t, start, _end in rows or ():
        if t == want:
            s = _parse(start)
            return (s - _LOCAL_OFFSET).date().isoformat() if s else None
    return None


# Which history phases a slate of each phase may read (design section 2). Unknown -> nothing.
SAME_FAMILY = {"regular": {"regular"}, "play_in": {"play_in", "postseason"}, "postseason": {"play_in", "postseason"}}


def same_phase_date_filter(slate_date: str, *, processed_root: Optional[Path] = None, allow_fetch: bool = True):
    """A predicate over history dates: True only for dates in the slate's own phase family. A preseason or unknown
    slate gets a predicate that admits NOTHING (no calibration window is built from preseason or a guess)."""
    slate = phase_for_date(slate_date, processed_root=processed_root, allow_fetch=allow_fetch)
    allowed = SAME_FAMILY.get(slate or "", set())

    def ok(d: str) -> bool:
        return bool(allowed) and phase_for_date(d, processed_root=processed_root, allow_fetch=allow_fetch) in allowed

    ok.slate_phase = slate  # type: ignore[attr-defined]
    return ok
