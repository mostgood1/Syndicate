"""Shot-level xG from FotMob.

THE ONE THING ESPN STRUCTURALLY CANNOT GIVE US. ESPN's commentary carries shot
COUNTS with a natural-language location; FotMob's shotmap carries per-shot
`expectedGoals`, i.e. chance QUALITY. That distinction is not cosmetic here:
measured 2026-08-22 over 370 matches, `shot-on-target` predicted goals BELOW
the base rate (lift 0.97) while `shot-off-target` scored 1.19 -- shot counts are
a demonstrably poor proxy for danger, which is exactly the gap xG fills.

ENDPOINT, VERIFIED 2026-08-22 rather than assumed:

    https://www.fotmob.com/api/matchDetails?matchId=      -> 404
    https://www.fotmob.com/api/data/matchDetails?matchId= -> 200

The path moved to `/api/data/`. NO `x-mas` signing header was required, and no
custom User-Agent beyond a browser-ish string. `.syndicate/scope_2026-08-21_
fotmob_xg_enrichment.md` recorded the old path and assumed signing; both were
wrong, and the 404 read as "blocked" when it meant "moved".

NOT WIRED INTO THE SIM, and deliberately. This is a research ingestion: it
exists so xG can be scored against the bar the clock already set (0.3320 at
80-84', +0.02 increment). It becomes a production dependency only if it clears
that, and only after the ESPN<->FotMob id join is solved -- which this module
does NOT need, because it reads goals from the same payload as the shots.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

_BASE = "https://www.fotmob.com/api/data"
_UA = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 25


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def matches_for_date(date_yyyymmdd: str) -> list[dict[str, Any]]:
    """Every fixture FotMob lists for a date, flattened across leagues."""
    payload = _get(f"{_BASE}/matches?date={date_yyyymmdd}")
    out: list[dict[str, Any]] = []
    for league in payload.get("leagues") or []:
        for match in league.get("matches") or []:
            out.append({
                "match_id": match.get("id"),
                "league_id": league.get("id"),
                "league": league.get("name"),
                "ccode": league.get("ccode"),
                "home": (match.get("home") or {}).get("longName") or (match.get("home") or {}).get("name"),
                "away": (match.get("away") or {}).get("longName") or (match.get("away") or {}).get("name"),
                "home_id": (match.get("home") or {}).get("id"),
                "away_id": (match.get("away") or {}).get("id"),
                "status": (match.get("status") or {}).get("reason", {}).get("short")
                          if isinstance(match.get("status"), dict) else None,
                "finished": bool((match.get("status") or {}).get("finished")) if isinstance(match.get("status"), dict) else False,
                "time": match.get("time"),
            })
    return out


def _clock_seconds(shot: dict[str, Any]) -> float | None:
    """Shot time in seconds from kickoff.

    `min` is the displayed minute and `minAdded` is stoppage on top of it, so a
    90+4 shot is min=90, minAdded=4. Both are folded in: dropping `minAdded`
    would stack every stoppage shot onto the 45th and 90th minute and corrupt
    exactly the late window that matters most.
    """
    minute = shot.get("min")
    if minute is None:
        return None
    try:
        total = float(minute) + float(shot.get("minAdded") or 0.0)
    except (TypeError, ValueError):
        return None
    return total * 60.0


def shots_for_match(match_id: Any) -> dict[str, Any] | None:
    """Per-shot xG plus goals, from one matchDetails payload.

    Goals are taken from the SHOTMAP (`eventType == "Goal"`), not from a
    separate feed, so shot times and goal times share one clock by
    construction. Mixing two sources here would reintroduce the join problem
    this module exists to avoid.
    """
    try:
        payload = _get(f"{_BASE}/matchDetails?matchId={match_id}")
    except Exception:
        return None
    content = payload.get("content") or {}
    shotmap = content.get("shotmap") or {}
    raw = shotmap.get("shots") if isinstance(shotmap, dict) else None
    if not isinstance(raw, list) or not raw:
        return None

    general = payload.get("general") or {}
    home_id = (general.get("homeTeam") or {}).get("id")

    shots: list[dict[str, Any]] = []
    goals: list[dict[str, Any]] = []
    for shot in raw:
        seconds = _clock_seconds(shot)
        if seconds is None:
            continue
        try:
            xg = float(shot.get("expectedGoals") or 0.0)
        except (TypeError, ValueError):
            xg = 0.0
        is_home = shot.get("teamId") == home_id
        row = {
            "t": seconds,
            "xg": xg,
            "home": bool(is_home),
            "on_target": bool(shot.get("isOnTarget")),
            "in_box": bool(shot.get("isFromInsideBox")),
            "blocked": bool(shot.get("isBlocked")),
            "situation": str(shot.get("situation") or ""),
            "event": str(shot.get("eventType") or ""),
        }
        shots.append(row)
        if row["event"] == "Goal":
            # An own goal is credited to the shooting team in the shotmap but
            # counts for the OTHER side on the scoreboard. It is still a goal
            # for "did a goal happen", which is the question being scored.
            goals.append({"t": seconds, "home": (not row["home"]) if shot.get("isOwnGoal") else row["home"]})

    # --- FotMob's OWN per-minute momentum, normalised to [{minute, value}] ---
    # Their MODEL output, not an observation. Kept so it can be scored against
    # the same bar as everything else rather than trusted because it is theirs.
    vendor: list[dict[str, Any]] = []
    main = ((content.get("momentum") or {}).get("main") or {}) if isinstance(content.get("momentum"), dict) else {}
    for point in (main.get("data") or []):
        if not isinstance(point, dict):
            continue
        try:
            vendor.append({"t": float(point["minute"]) * 60.0, "value": float(point["value"])})
        except (KeyError, TypeError, ValueError):
            continue

    # --- Timed events: cards and substitutions ---
    # These carry a clock, so they are legitimately available live. Match-level
    # `content.stats` is NOT extracted as a feature: those are FULL-MATCH
    # TOTALS known only at the whistle, so using one at minute 70 would leak
    # the future into a live prediction. Kept out of the feature set on purpose.
    events: list[dict[str, Any]] = []
    facts = content.get("matchFacts") or {}
    raw_events = (facts.get("events") or {}).get("events") if isinstance(facts.get("events"), dict) else None
    for e in (raw_events or []):
        if not isinstance(e, dict):
            continue
        minute = e.get("time")
        if minute is None:
            continue
        try:
            t = (float(minute) + float(e.get("minutesAddedTime") or 0.0)) * 60.0
        except (TypeError, ValueError):
            continue
        events.append({
            "t": t,
            "type": str(e.get("type") or ""),
            "home": bool(e.get("isHome")),
            "card": str(e.get("card") or "") or None,
        })

    return {
        "match_id": match_id,
        "home_team": (general.get("homeTeam") or {}).get("name"),
        "away_team": (general.get("awayTeam") or {}).get("name"),
        "shots": sorted(shots, key=lambda s: s["t"]),
        "goals": sorted(goals, key=lambda g: g["t"]),
        "vendor_momentum": vendor,
        "events": sorted(events, key=lambda e: e["t"]),
    }


__all__ = ["matches_for_date", "shots_for_match"]
