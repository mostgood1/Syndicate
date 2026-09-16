"""Confirmed lineups + per-match player stats via ESPN's public site API.

The one source in this pipeline with genuine starting-XI ground truth:
ESPN's match summary endpoint carries a ``starter: true/false`` flag per
player plus real per-match stats (shots, shots on target, goals, assists)
for completed games. That combination is what makes a real (non-heuristic,
non-circular) validation of ``player_props.build_usage_profiles``'s
starter-awareness lever possible -- compare predicted shot/goal allocation
under the real confirmed lineup against what actually happened, independent
of any bookmaker.

Same unauthenticated ``site.api.espn.com`` surface already used elsewhere
in this repo (``fetch_espn_live_status_for_date.py``). ESPN's scoreboard
date-range query appears capped around 100 events per call, so pulling a
full season means paging through sub-ranges (a few weeks each) rather than
one wide query.
"""

from __future__ import annotations

from typing import Any

import requests

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
# Was {"User-Agent": "Mozilla/5.0 (SyndicateSoccerSim)", "Accept":
# "application/json,text/plain,*/*"}. A prior session's temporary probe
# (81f091b7, 2026-08-04) tested this exact string against usa.1's bare
# scoreboard (no date-range param) from a live Render deploy and got 200,
# concluding soccer ingestion was not affected by the ded23a0d ESPN-403
# fix that dropped this same class of header elsewhere in the repo
# (fetch_espn_live_status_for_date.py, wnba/cards.py, schedule_adapter.py --
# all confirmed 403 on the bare "Mozilla/5.0" string, 200 with no custom
# header at all).
#
# That conclusion held for the narrower case it tested, not the general
# one. Confirmed live 2026-08-05, during a real manual soccer refresh
# through /api/ops/odds-refresh/run: this exact header on THIS function
# (fetch_espn_scoreboard, called via fetch_events from
# build_soccer_artifacts.py's _fetch_fixtures) returned a genuine 403 for
# ned.1 (eredivisie) and por.1 (primeira_liga) WITH a real dates=
# YYYYMMDD-YYYYMMDD range param -- the one difference from the earlier
# probe's request shape. That single failure then silently blocked
# odds_history for the ENTIRE soccer sport (see todo.md's "ROOT CAUSED
# 2026-08-05" entry) -- refresh_odds_sources.py's per-sport result
# aggregation treats one league's failure as disqualifying every other
# league sharing the same sport slug, MLS included, even though MLS's own
# ingestion never touches this failing code path.
#
# No local repro is possible for either the 403 or the fix -- only
# Render's outbound IP is affected (confirmed empirically for the other 3
# sites; ESPN's public scoreboard/summary endpoints work from every other
# tested origin regardless of headers). Dropping the custom header
# entirely is the same proven remediation already applied at those 3
# sites: sending no custom User-Agent/Accept -- the underlying library's
# own honest default -- returned 200 in every case tested. Do not
# reintroduce a custom header here without re-verifying against a real
# Render deploy first.

LEAGUE_ESPN_SLUGS: dict[str, str] = {
    "epl": "eng.1",
    "la_liga": "esp.1",
    "bundesliga": "ger.1",
    "serie_a": "ita.1",
    "ligue_1": "fra.1",
    "mls": "usa.1",
    "eredivisie": "ned.1",
    "primeira_liga": "por.1",
    "championship": "eng.2",
    "belgian_pro_league": "bel.1",
}


def fetch_espn_scoreboard(league: str, *, date_range: str | None = None, timeout: int = 20) -> dict[str, Any]:
    slug = LEAGUE_ESPN_SLUGS[str(league).strip().lower()]
    url = f"{_ESPN_BASE}/{slug}/scoreboard"
    params = {"dates": date_range} if date_range else {}
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


#: Longest window the single-date fallback will expand. A window wider than this
#: is a caller bug, not something to answer with dozens of requests.
_MAX_FALLBACK_DAYS = 62


def _window_days(window: str) -> list[str]:
    """``YYYYMMDD-YYYYMMDD`` -> every ``YYYYMMDD`` in it, inclusive.

    ``[]`` for anything that is not a well-formed, bounded range, so the caller
    re-raises instead of guessing at dates.
    """
    from datetime import datetime, timedelta

    start_text, sep, end_text = str(window or "").strip().partition("-")
    if not sep:
        return []
    try:
        start = datetime.strptime(start_text, "%Y%m%d").date()
        end = datetime.strptime(end_text, "%Y%m%d").date()
    except ValueError:
        return []
    span = (end - start).days
    if span < 0 or span >= _MAX_FALLBACK_DAYS:
        return []
    return [(start + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(span + 1)]


def _scoreboard_payloads(league: str, window: str, timeout: int) -> list[dict[str, Any]]:
    """The scoreboard for one window, retried ONE DATE AT A TIME when ESPN
    refuses the range.

    ESPN REFUSES SOME DATE RANGES, AND WHICH ONES DEPENDS ON THE DATES. Measured
    2026-09-15 against the live endpoint (lane `soccer-player-substrate`):

      - ``20260801-20260815`` returned 400 on eng.2, ned.1 and usa.1.
      - The ONE-DAY range ``20260815-20260815`` -- the exact shape
        ``build_soccer_artifacts._fetch_fixtures`` sends -- returned 400 on all
        four slugs tried.
      - ``20260915-20260915`` and ``20260901-20260915`` returned 200 on the same
        slugs.
      - Every bare ``YYYYMMDD`` request returned 200, including 2026-08-15 with
        8 events on eng.2.

    RE-MEASURED 2026-09-16 03:51Z (lane `soccer-espn-window-validation`) AND THE
    ANSWER CHANGED OVERNIGHT: **every range form now returns 400**, including the
    two windows recorded above as returning 200 the day before --
    ``20260915-20260915`` and ``20260901-20260915`` on eng.2 -- plus
    ``20260901-20260915`` on ned.1. The bare form still returns 200 (eng.2
    ``20260901``: 8 events). So this fallback is no longer the exception: on
    2026-09-16 it fires for EVERY range caller, one wasted 400 each. Callers that
    want a single date should send the bare ``YYYYMMDD`` and skip the 400 entirely
    -- `build_soccer_artifacts` and `poll_soccer_live_state` now do.

    So the range form still exists but fails on some dates, and a refusal used
    to raise straight out of every caller. `aggregate_season_player_stats` walks
    the season in ranges from 1 August and died on its first window. That made
    the four ESPN leagues' current-season producer unrunnable even once it was
    allowlisted. A builder or live poll asking for a bad date failed the same
    way.

    ONLY a 400 on a parseable range falls back. Any other error, or a 400 on
    something that is not a range, still raises: a 5xx is not this failure, and
    splitting an unknown window would be guessing.
    """
    try:
        return [fetch_espn_scoreboard(league, date_range=window, timeout=timeout)]
    except requests.HTTPError as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        days = _window_days(window) if status == 400 else []
        if not days:
            raise
    print(
        f"[espn_lineups] ESPN_RANGE_REFUSED league={league} window={window} status=400 "
        f"-> retrying as {len(days)} single-date request(s)",
        flush=True,
    )
    return [fetch_espn_scoreboard(league, date_range=day, timeout=timeout) for day in days]


def _window_day_set(windows: list[str]) -> set[str] | None:
    """Every ``YYYYMMDD`` the requested windows cover, PLUS ONE DAY EITHER SIDE.

    ``None`` when any window is unparseable, which means "do not filter" -- a guard
    that silently drops everything because it could not read its own input is worse
    than no guard.

    WHY A ONE-DAY SKIRT RATHER THAN AN EXACT MATCH. ESPN keys ``dates`` to US
    EASTERN while ``event["date"]`` comes back in UTC, so a 19:30 ET kickoff on the
    15th is ``2026-09-16T23:30Z`` and an exact UTC-day match would drop a legitimate
    fixture. `zoneinfo` would answer this precisely but needs `tzdata`, which is
    routinely absent on Windows, so the skirt is deliberate: it cannot over-filter a
    real kickoff, and it still catches the failure this guard exists for -- a payload
    for a different WEEK, which is what a stale 200 returns.
    """
    from datetime import datetime, timedelta

    days: set[str] = set()
    for window in windows or []:
        start_text, sep, end_text = str(window or "").strip().partition("-")
        try:
            start = datetime.strptime(start_text, "%Y%m%d").date()
            end = datetime.strptime(end_text, "%Y%m%d").date() if sep else start
        except ValueError:
            return None
        if (end - start).days < 0:
            return None
        cursor = start - timedelta(days=1)
        last = end + timedelta(days=1)
        while cursor <= last:
            days.add(cursor.strftime("%Y%m%d"))
            cursor += timedelta(days=1)
    return days or None


def _event_utc_day(event: dict[str, Any]) -> str | None:
    """``YYYYMMDD`` of the event in UTC, or ``None`` if it has no readable date --
    in which case the caller KEEPS it, because an unreadable date is not evidence
    that the event is off-window."""
    from datetime import datetime, timezone

    raw = str(event.get("date") or "")
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when.astimezone(timezone.utc).strftime("%Y%m%d")


def fetch_events(
    league: str,
    *,
    date_windows: list[str],
    statuses: set[str] | None = None,
    timeout: int = 20,
) -> list[dict[str, Any]]:
    """Events across a list of ``YYYYMMDD-YYYYMMDD`` windows, optionally
    filtered by ESPN status state (``"pre"``, ``"in"``, ``"post"``; default
    None keeps all). Callers should keep each window to a few weeks --
    ESPN's scoreboard endpoint silently truncates around ~100 events per
    call. A window ESPN refuses with a 400 is retried one date at a time
    (see ``_scoreboard_payloads``)."""
    found: dict[str, dict[str, Any]] = {}
    payloads = [payload for window in date_windows for payload in _scoreboard_payloads(league, window, timeout)]
    # THE WINDOW IS NOT SELF-ENFORCING. Nothing in this function used to compare a
    # returned event against the dates it asked for: a 200 carrying another period's
    # events became fixtures for the requested date, and `_fetch_fixtures` handed
    # them to the builder, whose `_attach_confirmed_starters` then set
    # `start_probability` from the wrong lineup -- the input both the conditional
    # shot ladder and the goal mixture key off.
    #
    # NOT DEMONSTRATED LIVE, and recorded that way: on 2026-09-16 every range
    # request returned 400, so ESPN offered no range 200 to catch (lane
    # `soccer-espn-window-validation`, 10 probes). This is a guard against a shape
    # the endpoint has produced before, not a fix for a measured failure.
    allowed_days = _window_day_set(date_windows)
    dropped_off_window = 0
    for payload in payloads:
        for event in payload.get("events") or []:
            competition = (event.get("competitions") or [{}])[0]
            # `status_block` is ESPN's `competition.status`; `status` is its
            # nested `.type`. Kept under the old name because `state` and the
            # detail strings genuinely live on `.type` -- but the CLOCK does
            # not. `clock`/`displayClock`/`period` sit on the OUTER block, and
            # reading them off `.type` returns None for all three on a match
            # that is very much in progress. Measured on live fixture
            # 401882908: `.type` has no `clock` key at all, while the outer
            # block reads `clock: 4200.0, displayClock: "70'", period: 2`.
            status_block = competition.get("status") or {}
            status = status_block.get("type") or {}
            state = str(status.get("state") or "").lower()
            if statuses is not None and state not in statuses:
                continue
            if allowed_days is not None:
                event_day = _event_utc_day(event)
                if event_day is not None and event_day not in allowed_days:
                    dropped_off_window += 1
                    continue
            event_id = str(event.get("id") or "")
            if not event_id:
                continue
            competitors = competition.get("competitors") or []
            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})
            # THE LIVE CLOCK, which this function saw and threw away.
            #
            # `build_live_state`'s docstring is explicit that it cannot infer a
            # live clock ("a quiet spell with no shots/cards would make it look
            # earlier than it is") and that "live callers must source the actual
            # current clock from ESPN's live status and pass it explicitly".
            # `status` is that live status, and it was already in hand here --
            # the only caller that needed it had no way to ask for it, so
            # `poll_soccer_live_state` called `build_live_state` with no
            # `as_of_seconds` and got the default full-match cutoff every time.
            #
            # `clock` is a continuous match-clock value in SECONDS (verified
            # against live fixture 401882908 on 2026-08-20: `clock: 4200.0`,
            # `displayClock: "70'"`, `period: 2`) -- which is exactly the unit
            # `build_live_state(as_of_seconds=...)` wants, no conversion.
            # `displayClock`/`detail` are ESPN's own rendering of the same
            # instant and are what a card should show a human ("70'", not
            # "1200 seconds remaining in half 2").
            found[event_id] = {
                "event_id": event_id,
                "date": event.get("date"),
                "status_state": state,
                "home_team": (home.get("team") or {}).get("displayName"),
                "away_team": (away.get("team") or {}).get("displayName"),
                "home_score": home.get("score"),
                "away_score": away.get("score"),
                "status_clock_seconds": status_block.get("clock"),
                "status_display_clock": status_block.get("displayClock"),
                "status_period": status_block.get("period"),
                "status_detail": status.get("detail") or status.get("shortDetail"),
                "status_description": status.get("description"),
            }
    if dropped_off_window:
        print(
            f"[espn_lineups] ESPN_OFF_WINDOW_EVENTS_DROPPED league={league} "
            f"windows={date_windows} dropped={dropped_off_window} kept={len(found)}",
            flush=True,
        )
    return list(found.values())


def fetch_completed_events(league: str, *, date_windows: list[str], timeout: int = 20) -> list[dict[str, Any]]:
    """Completed (status=post) events. Thin wrapper over ``fetch_events``."""
    return fetch_events(league, date_windows=date_windows, statuses={"post"}, timeout=timeout)


def fetch_match_summary(league: str, event_id: str, *, timeout: int = 20) -> dict[str, Any]:
    slug = LEAGUE_ESPN_SLUGS[str(league).strip().lower()]
    response = requests.get(f"{_ESPN_BASE}/{slug}/summary", params={"event": event_id}, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _stat_value(stats: list[dict[str, Any]], name: str) -> float:
    for stat in stats:
        if stat.get("name") == name:
            try:
                return float(stat.get("value") or 0.0)
            except Exception:
                return 0.0
    return 0.0


def extract_match_player_rows(summary: dict[str, Any], *, event_id: str) -> list[dict[str, Any]]:
    """Flatten an ESPN match summary's rosters into per-player rows with the
    real starter flag and real match stats (goals/shots/assists)."""
    rows: list[dict[str, Any]] = []
    for team_block in summary.get("rosters") or []:
        team_name = ((team_block.get("team") or {}).get("displayName")) or ""
        side = str(team_block.get("homeAway") or "")
        for entry in team_block.get("roster") or []:
            athlete = entry.get("athlete") or {}
            stats = entry.get("stats") or []
            position = (entry.get("position") or {}).get("name") or ""
            rows.append(
                {
                    "event_id": event_id,
                    "team": team_name,
                    "side": side,
                    "player_id": str(athlete.get("id") or ""),
                    "player_name": athlete.get("displayName") or athlete.get("fullName") or "",
                    "position": position,
                    "starter": bool(entry.get("starter")),
                    "subbed_in": bool(entry.get("subbedIn")),
                    "is_goalkeeper": position.strip().lower() == "goalkeeper",
                    "total_shots": _stat_value(stats, "totalShots"),
                    "shots_on_target": _stat_value(stats, "shotsOnTarget"),
                    "total_goals": _stat_value(stats, "totalGoals"),
                    "goal_assists": _stat_value(stats, "goalAssists"),
                }
            )
    return rows


__all__ = [
    "LEAGUE_ESPN_SLUGS",
    "extract_match_player_rows",
    "fetch_completed_events",
    "fetch_espn_scoreboard",
    "fetch_events",
    "fetch_match_summary",
]
