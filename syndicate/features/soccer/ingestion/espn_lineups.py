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
    call."""
    found: dict[str, dict[str, Any]] = {}
    for window in date_windows:
        payload = fetch_espn_scoreboard(league, date_range=window, timeout=timeout)
        for event in payload.get("events") or []:
            competition = (event.get("competitions") or [{}])[0]
            status = (competition.get("status") or {}).get("type") or {}
            state = str(status.get("state") or "").lower()
            if statuses is not None and state not in statuses:
                continue
            event_id = str(event.get("id") or "")
            if not event_id:
                continue
            competitors = competition.get("competitors") or []
            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})
            found[event_id] = {
                "event_id": event_id,
                "date": event.get("date"),
                "status_state": state,
                "home_team": (home.get("team") or {}).get("displayName"),
                "away_team": (away.get("team") or {}).get("displayName"),
                "home_score": home.get("score"),
                "away_score": away.get("score"),
            }
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
