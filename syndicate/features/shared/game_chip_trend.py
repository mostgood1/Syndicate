"""Game TREND on the live games-rail card for NHL and soccer -- their "9-2 run".

User request 2026-10-14 (lane games-rail-full-detail): "NHL and soccer to show
something similarly informative as the NBA 'team is on a 9-2 run' ... pressure,
possession time, something about game trend".

PRESSURE, from ESPN's live summary (one request per live game, 45 s cache):

    nhl     unblocked shot attempts (Shot / Missed / Goal plays) per team in the
            last 10 minutes of play -> "NYI pressing · 9–3 shots, last 10'".
            Plays carry period + ELAPSED period clock (measured 2026-10-14:
            3rd-period plays 16:27, 17:55, 18:19 in order). Blocked plays are
            left out: ESPN credits them to an ambiguous team.
    soccer  shots (on / off target, blocked, goals) and corners per team in the
            last 15 match minutes from `commentary` (each has a minute and a
            team) -> "ATA pressing · 5–1 shots, 3–0 corners, last 15'".
            Possession is a whole-match number only, so it cannot show a trend.

Shown only when one side clearly leads the window; an even game says nothing,
like the basketball run line. Display only.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from typing import Any, Mapping

_LOCK = threading.Lock()
_CACHE: dict[tuple, tuple[float, Any]] = {}
_TTL_S = 45.0
_BASE = "https://site.api.espn.com/apis/site/v2/sports"

_NHL_ATTEMPTS = {"Shot", "Missed", "Goal"}
_NHL_WINDOW_MIN = 10
_SOCCER_SHOTS = ("Shot On Target", "Shot Off Target", "Shot Blocked", "Goal")
_SOCCER_WINDOW_MIN = 15


def _summary(path: str, event_id: str) -> dict:
    key = (path, event_id, int(time.monotonic() // _TTL_S))
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit[1]
    # No custom User-Agent: ESPN 403s some UA strings (espn_lineups' note).
    with urllib.request.urlopen(f"{_BASE}/{path}/summary?event={event_id}", timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    with _LOCK:
        _CACHE[key] = (time.monotonic(), payload)
        if len(_CACHE) > 128:
            _CACHE.pop(next(iter(_CACHE)), None)
    return payload


def _sides(payload: Mapping[str, Any]) -> dict[str, str]:
    """{team id or display name: "away"|"home"} from the summary header."""
    comp = (((payload.get("header") or {}).get("competitions")) or [{}])[0]
    out: dict[str, str] = {}
    for c in comp.get("competitors") or []:
        side = str(c.get("homeAway") or "")
        team = c.get("team") or {}
        for value in (team.get("id"), team.get("displayName"), team.get("name")):
            if value:
                out[str(value)] = side
    return out


def _pressing(counts: dict[str, int], *, min_lead: int, min_gap: int) -> str | None:
    a, h = counts.get("away", 0), counts.get("home", 0)
    if max(a, h) >= min_lead and abs(a - h) >= min_gap:
        return "away" if a > h else "home"
    return None


def nhl_pressure(payload: Mapping[str, Any], away_abbr: str, home_abbr: str) -> str | None:
    sides = _sides(payload)
    attempts = []
    for play in payload.get("plays") or []:
        if str((play.get("type") or {}).get("text") or "") not in _NHL_ATTEMPTS:
            continue
        side = sides.get(str((play.get("team") or {}).get("id") or ""))
        period = (play.get("period") or {}).get("number")
        m = re.match(r"^(\d{1,2}):(\d{2})$", str((play.get("clock") or {}).get("displayValue") or ""))
        if side not in ("away", "home") or not isinstance(period, int) or not m:
            continue
        attempts.append(((period - 1) * 20 + int(m.group(1)) + int(m.group(2)) / 60.0, side))
    if not attempts:
        return None
    now = max(t for t, _ in attempts)
    counts = {"away": 0, "home": 0}
    for t, side in attempts:
        if t >= now - _NHL_WINDOW_MIN:
            counts[side] += 1
    lead = _pressing(counts, min_lead=5, min_gap=4)
    if not lead:
        return None
    other = "home" if lead == "away" else "away"
    team = away_abbr if lead == "away" else home_abbr
    return f"{team} pressing · {counts[lead]}–{counts[other]} shots, last {_NHL_WINDOW_MIN}'"


def _minute(text: str) -> int | None:
    m = re.match(r"^(\d{1,3})'(?:\+(\d{1,2})')?", str(text or "").strip())
    return int(m.group(1)) + (int(m.group(2)) if m.group(2) else 0) if m else None


def soccer_pressure(payload: Mapping[str, Any], away_abbr: str, home_abbr: str) -> str | None:
    sides = _sides(payload)
    events = []
    for item in payload.get("commentary") or []:
        play = item.get("play") or {}
        kind = str((play.get("type") or {}).get("text") or "")
        side = sides.get(str((play.get("team") or {}).get("displayName") or ""))
        minute = _minute((item.get("time") or {}).get("displayValue"))
        if side not in ("away", "home") or minute is None:
            continue
        if kind.startswith(_SOCCER_SHOTS):
            events.append((minute, side, "shot"))
        elif kind == "Corner Awarded":
            events.append((minute, side, "corner"))
    if not events:
        return None
    now = max(m for m, _, _ in events)
    shots, corners = {"away": 0, "home": 0}, {"away": 0, "home": 0}
    for minute, side, kind in events:
        if minute >= now - _SOCCER_WINDOW_MIN:
            (shots if kind == "shot" else corners)[side] += 1
    lead = _pressing(shots, min_lead=3, min_gap=3) or _pressing(corners, min_lead=3, min_gap=3)
    if not lead:
        return None
    other = "home" if lead == "away" else "away"
    team = away_abbr if lead == "away" else home_abbr
    parts = [f"{shots[lead]}–{shots[other]} shots"]
    if corners[lead] or corners[other]:
        parts.append(f"{corners[lead]}–{corners[other]} corners")
    return f"{team} pressing · {', '.join(parts)}, last {_SOCCER_WINDOW_MIN}'"


def live_trend(sport: str, *, event_id: str | None, league: str | None, away_abbr: str, home_abbr: str) -> str | None:
    """The pressure line for a live NHL / soccer game, or None."""
    try:
        if not event_id:
            return None
        if sport == "nhl":
            return nhl_pressure(_summary("hockey/nhl", str(event_id)), away_abbr, home_abbr)
        if sport == "soccer":
            from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS

            slug = LEAGUE_ESPN_SLUGS.get(str(league or "").strip().lower())
            return soccer_pressure(_summary(f"soccer/{slug}", str(event_id)), away_abbr, home_abbr) if slug else None
    except Exception:  # noqa: BLE001 -- a trend line must never break a chip
        return None
    return None
