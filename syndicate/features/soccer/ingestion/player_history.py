"""Player-history ingestion for SoccerSim usage profiles.

Two free sources cover the engine's leagues:

- **Understat** (big-five European leagues): season player tables with
  minutes, games, shots, goals, xG, xA, key passes, position — embedded as
  escaped JSON in the league page. Seasons are keyed by start year
  (2025 = the 2025-26 season).
- **American Soccer Analysis** (MLS): public API with per-player xgoals
  tables (minutes, shots, xG, xA) joined against the player directory.

Both normalize to the per-90 row shape that
``soccersim.player_props.build_usage_profiles`` consumes:
``player_id, player_name, team, position, minutes, games, shots_per90,
xg_per90, xa_per90, expected_minutes_share, is_goalkeeper``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

import requests

UNDERSTAT_LEAGUES: dict[str, str] = {
    "epl": "EPL",
    "la_liga": "La_liga",
    "bundesliga": "Bundesliga",
    "serie_a": "Serie_A",
    "ligue_1": "Ligue_1",
}

_ASA_BASE = "https://app.americansocceranalysis.com/api/v1/mls"

_USER_AGENT = {"User-Agent": "Mozilla/5.0 (SyndicateSoccerSim)"}
_UNDERSTAT_XHR_HEADERS = {**_USER_AGENT, "X-Requested-With": "XMLHttpRequest"}


# --------------------------------------------------------------------------
# Understat OUTAGE GUARD (lane `understat-fetch-failures`, 2026-11-18).
#
# WHAT HAPPENED. From 2026-11-03 2:54 PM CST every understat.com URL -- the
# home page, every league page, every `getLeagueData` call -- answers HTTP 200
# with the same 26,719-byte "We will come back soon" HTML page, from the fleet
# and from another network alike. Before that, 11-01 6:34 PM .. 11-03 3:06 PM
# CST, the name did not resolve and then connections timed out. The fetchers
# met that as `requests.JSONDecodeError` (teams) and as `playersData not
# available` (players, after a SECOND request to the same host's legacy page),
# every soccer run, on all five Understat leagues: 5,152 of 5,152 steps failed
# in 800 runs (manifests 11-10..11-20), ~990 requests a day to a site in
# maintenance, and p50 324 s per run of connect timeouts during the DNS phase.
#
# WHAT THE GUARD DOES, AND WHAT IT DOES NOT. It cannot make the site return
# data, and it does not pretend to: a fetch that gets no data still FAILS.
# It (a) names what came back -- `UnderstatUnavailable` with the reason,
# status, content type, size and visible page text -- instead of a JSON decode
# traceback; (b) stops the players path from asking the same host again for
# the legacy page after `getLeagueData` was unavailable; (c) when given a
# status file, records the outage there and, for `UNDERSTAT_OUTAGE_COOLDOWN_
# SECONDS` after a failed probe, raises `UnderstatUnavailable("cooldown")`
# WITHOUT a request. The first probe after the cooldown that gets JSON clears
# it, so recovery needs no human.
#
# Switch: ON unless `SYNDICATE_UNDERSTAT_OUTAGE_GUARD` is 0/false/off/no, and
# OFF is today's code path exactly (the reachability test pins both).
# --------------------------------------------------------------------------

UNDERSTAT_OUTAGE_GUARD_ENV = "SYNDICATE_UNDERSTAT_OUTAGE_GUARD"
#: After a failed probe, Understat steps exit without a request for this long.
#: One probe an hour host-wide (~24 a day) against ~990 requests a day without it;
#: on recovery the first refetch lags at most this, on a 1-day refresh cadence.
UNDERSTAT_OUTAGE_COOLDOWN_SECONDS = 3600.0
#: HTTP statuses that mean "the site is not serving", not "this URL is wrong".
_UNDERSTAT_OUTAGE_STATUSES = frozenset({403, 429})


class UnderstatUnavailable(RuntimeError):
    """Understat did not serve data. ``reason`` is one of ``non_json`` (a 200
    that is not JSON -- the maintenance page), ``http_<status>``,
    ``unreachable`` (DNS / connect / read failure) or ``cooldown`` (no request
    was sent: a recent probe failed). Never a silent outcome: callers exit
    non-zero with :meth:`summary`."""

    def __init__(self, reason: str, *, url: str, detail: str = "") -> None:
        self.reason = reason
        self.url = url
        self.detail = detail
        super().__init__(self.summary())

    def summary(self) -> str:
        return f"reason={self.reason} url={self.url}" + (f" {self.detail}" if self.detail else "")


def understat_outage_guard_enabled() -> bool:
    raw = str(os.environ.get(UNDERSTAT_OUTAGE_GUARD_ENV) or "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _visible_text(html: str, limit: int = 80) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _understat_get_json(url: str, *, timeout: int, headers: dict[str, str]) -> Any:
    """GET ``url`` and return its JSON, or raise `UnderstatUnavailable` naming
    what came back. A 4xx other than 403/429 is a wrong URL, not an outage, and
    raises ``requests.HTTPError`` as before."""
    try:
        response = requests.get(url, timeout=timeout, headers=headers)
    except requests.exceptions.RequestException as exc:
        raise UnderstatUnavailable("unreachable", url=url, detail=f"error={type(exc).__name__}") from exc
    status = int(response.status_code)
    content_type = str(response.headers.get("content-type") or "")
    size = len(response.content or b"")
    if status >= 500 or status in _UNDERSTAT_OUTAGE_STATUSES:
        raise UnderstatUnavailable(
            f"http_{status}", url=url, detail=f"content_type={content_type!r} bytes={size}"
        )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise UnderstatUnavailable(
            "non_json",
            url=url,
            detail=(
                f"status={status} content_type={content_type!r} bytes={size} "
                f"text={_visible_text(response.text)!r}"
            ),
        ) from exc


def read_understat_status(status_path: Path | None) -> dict[str, Any] | None:
    """The outage marker, or None when absent or unreadable (unknown is not
    "down": an unreadable marker must not stop a probe)."""
    if status_path is None:
        return None
    try:
        payload = json.loads(Path(status_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_understat_status(status_path: Path, payload: dict[str, Any]) -> None:
    path = Path(status_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        # The marker only saves requests; failing to write it must not turn a
        # named UnderstatUnavailable into an OSError traceback.
        print(f"UNDERSTAT_STATUS_WRITE_FAILED path={path} error={type(exc).__name__}", file=sys.stderr, flush=True)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_understat_down(status_path: Path | None, exc: UnderstatUnavailable, now: float) -> None:
    if status_path is None:
        return
    previous = read_understat_status(status_path) or {}
    was_down = previous.get("state") == "down"
    _write_understat_status(
        status_path,
        {
            "state": "down",
            "down_since": previous.get("down_since") if was_down else _iso(now),
            "last_probe_at": _iso(now),
            "last_probe_epoch": now,
            "last_reason": exc.reason,
            "last_url": exc.url,
            "last_detail": exc.detail,
            "probes": (int(previous.get("probes") or 0) if was_down else 0) + 1,
            "cooldown_seconds": UNDERSTAT_OUTAGE_COOLDOWN_SECONDS,
            "last_ok_at": previous.get("last_ok_at"),
        },
    )


def _record_understat_up(status_path: Path | None, now: float) -> None:
    if status_path is None:
        return
    previous = read_understat_status(status_path) or {}
    payload: dict[str, Any] = {"state": "up", "last_ok_at": _iso(now)}
    if previous.get("state") == "down":
        payload["last_outage"] = {
            "down_since": previous.get("down_since"),
            "ended_at": _iso(now),
            "probes": previous.get("probes"),
            "last_reason": previous.get("last_reason"),
        }
    elif isinstance(previous.get("last_outage"), dict):
        payload["last_outage"] = previous["last_outage"]
    _write_understat_status(status_path, payload)


def _raise_if_cooling_down(status_path: Path | None, url: str, now: float) -> None:
    status = read_understat_status(status_path)
    if not status or status.get("state") != "down":
        return
    try:
        last_probe = float(status.get("last_probe_epoch"))
    except (TypeError, ValueError):
        return  # unknown probe time: probe rather than block
    remaining = last_probe + UNDERSTAT_OUTAGE_COOLDOWN_SECONDS - now
    if remaining <= 0:
        return
    raise UnderstatUnavailable(
        "cooldown",
        url=url,
        detail=(
            f"no_request_sent down_since={status.get('down_since')} "
            f"last_probe_at={status.get('last_probe_at')} last_reason={status.get('last_reason')} "
            f"probes={status.get('probes')} next_probe_in_s={int(remaining)}"
        ),
    )


def _clock() -> float:
    """Wall clock for the cooldown (a seam, so tests need not patch `time.time`)."""
    return time.time()


def _guarded_league_data(url: str, *, timeout: int, status_path: Path | None) -> Any:
    now = _clock()
    _raise_if_cooling_down(status_path, url, now)
    try:
        payload = _understat_get_json(url, timeout=timeout, headers=_UNDERSTAT_XHR_HEADERS)
    except UnderstatUnavailable as exc:
        _record_understat_down(status_path, exc, now)
        raise
    _record_understat_up(status_path, now)
    return payload


def fetch_understat_league_data(
    league: str,
    season_start_year: int,
    *,
    timeout: int = 30,
    status_path: Path | None = None,
) -> dict[str, Any]:
    """Fetch Understat's league bundle: ``players``, ``teams`` (with
    per-match history: xG, xGA, PPDA, deep entries), and ``dates``.

    With the outage guard on (the default), an outage raises
    `UnderstatUnavailable`; ``status_path`` (the host-wide marker) adds the
    cooldown. Guard off: the original request, ``raise_for_status`` and
    ``response.json()``, and ``status_path`` is ignored."""
    league_key = UNDERSTAT_LEAGUES[str(league).strip().lower()]
    url = f"https://understat.com/getLeagueData/{league_key}/{int(season_start_year)}"
    if understat_outage_guard_enabled():
        return _guarded_league_data(url, timeout=timeout, status_path=status_path)
    response = requests.get(url, timeout=timeout, headers=_UNDERSTAT_XHR_HEADERS)
    response.raise_for_status()
    return response.json()


def fetch_understat_players(
    league: str,
    season_start_year: int,
    *,
    timeout: int = 30,
    status_path: Path | None = None,
) -> list[dict[str, Any]]:
    guard = understat_outage_guard_enabled()
    try:
        league_data = fetch_understat_league_data(
            league, season_start_year, timeout=timeout, status_path=status_path if guard else None
        )
        players = league_data.get("players")
        if isinstance(players, list) and players:
            return players
    except UnderstatUnavailable:
        # Guard on only (it is never raised with the guard off). The legacy
        # page is on the SAME host: asking it again during an outage is a
        # second request that can only fail, and its "playersData not
        # available" error hid the real reason for 15 days.
        raise
    except Exception:
        pass
    # Fallback: legacy embedded-JSON page scrape.
    league_key = UNDERSTAT_LEAGUES[str(league).strip().lower()]
    url = f"https://understat.com/league/{league_key}/{int(season_start_year)}"
    response = requests.get(url, timeout=timeout, headers=_USER_AGENT)
    response.raise_for_status()
    match = re.search(r"var playersData\s*=\s*JSON\.parse\('([^']+)'\)", response.text)
    if not match:
        raise ValueError(f"playersData not available for {url}")
    decoded = match.group(1).encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    return json.loads(decoded)


def normalize_understat_team_history(
    league_data: dict[str, Any],
    *,
    league: str,
    season: int,
) -> list[dict[str, Any]]:
    """Flatten Understat team blocks into per-team per-match history rows."""
    rows: list[dict[str, Any]] = []
    teams = league_data.get("teams") or {}
    for team in teams.values() if isinstance(teams, dict) else teams:
        title = str(team.get("title") or "").strip()
        for match_index, entry in enumerate(team.get("history") or []):
            rows.append(
                {
                    "league": league,
                    "season": season,
                    "team": title,
                    "match_index": match_index,
                    "date": str(entry.get("date") or ""),
                    "home_away": str(entry.get("h_a") or ""),
                    "xg_for": _safe_number(entry.get("xG")),
                    "xg_against": _safe_number(entry.get("xGA")),
                    "npxg_for": _safe_number(entry.get("npxG")),
                    "npxg_against": _safe_number(entry.get("npxGA")),
                    "ppda": _ppda_value(entry.get("ppda")),
                    "ppda_allowed": _ppda_value(entry.get("ppda_allowed")),
                    "deep_entries": _safe_number(entry.get("deep")),
                    "deep_entries_allowed": _safe_number(entry.get("deep_allowed")),
                    "goals_for": _safe_number(entry.get("scored")),
                    "goals_against": _safe_number(entry.get("missed")),
                    "expected_points": _safe_number(entry.get("xpts")),
                    "points": _safe_number(entry.get("pts")),
                    "result": str(entry.get("result") or ""),
                }
            )
    return rows


def _safe_number(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return round(float(value), 4)
    except Exception:
        return None


def _ppda_value(value: Any) -> float | None:
    # Understat PPDA arrives as {"att": passes, "def": defensive_actions}.
    if isinstance(value, dict):
        att = _safe_number(value.get("att"))
        defensive = _safe_number(value.get("def"))
        if att is None or not defensive:
            return None
        return round(att / defensive, 4)
    return _safe_number(value)


def _per90(value: Any, minutes: float) -> float:
    try:
        numeric = float(value or 0.0)
    except Exception:
        numeric = 0.0
    return round(numeric / minutes * 90.0, 4) if minutes > 0 else 0.0


#: Per-90 fields that are SHRUNK toward a positional prior. `expected_minutes_
#: share` is deliberately absent: it is a share of a player's own appearances,
#: not a rate estimated from them, so shrinking it would distort the very
#: quantity that says how thin the sample is.
_SHRUNK_PER90_FIELDS = (
    "shots_per90", "xg_per90", "xa_per90",
    "goals_per90", "assists_per90", "key_passes_per90",
)

#: Minutes at which a player's own rate carries HALF the weight of the prior.
#: This is the 180.0 that used to be a cutoff, doing the job it was really for.
_RATE_STABILISATION_MINUTES = 180.0


def _shrink_toward_prior(rows: list[dict[str, Any]]) -> None:
    """Pull each per-90 toward its (league, position) mean by sample size.

    THE WEIGHT IS `minutes / (minutes + 180)`, so the old constant now expresses
    what it always meant -- 180 minutes is where a player's own rate becomes as
    trustworthy as the prior -- instead of where they stop existing.

        1 min    -> 0.6% own rate    (effectively the positional prior)
        180 min  -> 50%
        1800 min -> 91%

    Mutates in place. The prior is the MINUTES-WEIGHTED mean of the same
    population, so a squad of thin samples cannot bootstrap a confident prior
    out of itself.
    """
    if not rows:
        return
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        # THE FIRST TOKEN, not the first two characters. Understat writes
        # multi-position strings, so `[:2]` turned 'D' and 'D M' into the
        # separate keys 'D' and 'D ' -- measured at 154 rows against 26 on real
        # EPL data. Two priors where there should be one, each noisier, and the
        # prior is what a thin-minute player is shrunk TOWARD.
        position = str(row.get("position") or "").upper().split()
        key = position[0] if position else "?"
        buckets.setdefault(key, []).append(row)
    for key, bucket in buckets.items():
        total_minutes = sum(float(r.get("minutes") or 0.0) for r in bucket)
        if total_minutes <= 0:
            continue
        prior = {
            field: sum(float(r.get(field) or 0.0) * float(r.get("minutes") or 0.0)
                       for r in bucket) / total_minutes
            for field in _SHRUNK_PER90_FIELDS
        }
        for row in bucket:
            minutes = float(row.get("minutes") or 0.0)
            weight = minutes / (minutes + _RATE_STABILISATION_MINUTES)
            for field in _SHRUNK_PER90_FIELDS:
                own = float(row.get(field) or 0.0)
                row[field] = round(weight * own + (1.0 - weight) * prior[field], 4)
            # SAY HOW MUCH OF THIS IS THE PLAYER. A consumer that cannot tell a
            # 2,000-minute rate from a shrunken 20-minute one will treat them
            # alike, which is the whole hazard the cutoff was avoiding.
            row["rate_own_weight"] = round(weight, 4)


def normalize_understat_players(
    raw_players: list[dict[str, Any]],
    *,
    league: str,
    season: int,
    minimum_minutes: float = 1.0,
) -> list[dict[str, Any]]:
    """Understat rows -> per-90 player rows, THIN SAMPLES INCLUDED AND SHRUNK.

    `minimum_minutes` was 180.0 and acted as a ROSTER FILTER: measured on the
    live feed, epl 2026-27 yields 100 rows at 180 and 364 at 1, and 41 of 288
    production fixture-sides published ZERO players. Those absences are ~80% of
    the soccer projection gap and no name-matching rule can reach them.

    It is now 1.0 -- a player must have actually played -- and rate stability is
    handled where it belongs, by shrinking each per-90 toward its positional
    prior rather than by deleting the player. See `_shrink_toward_prior`.
    """
    rows: list[dict[str, Any]] = []
    for player in raw_players:
        try:
            minutes = float(player.get("time") or 0.0)
        except Exception:
            minutes = 0.0
        if minutes < minimum_minutes:
            continue
        try:
            games = int(player.get("games") or 0)
        except Exception:
            games = 0
        position = str(player.get("position") or "")
        rows.append(
            {
                "league": league,
                "season": season,
                "player_id": f"understat_{player.get('id')}",
                "player_name": str(player.get("player_name") or "").strip(),
                "team": str(player.get("team_title") or "").strip(),
                "position": position,
                "minutes": minutes,
                "games": games,
                "shots_per90": _per90(player.get("shots"), minutes),
                "xg_per90": _per90(player.get("xG"), minutes),
                "xa_per90": _per90(player.get("xA"), minutes),
                "goals_per90": _per90(player.get("goals"), minutes),
                "assists_per90": _per90(player.get("assists"), minutes),
                "key_passes_per90": _per90(player.get("key_passes"), minutes),
                "expected_minutes_share": round(min(1.0, minutes / (games * 90.0)), 4) if games > 0 else 0.0,
                "is_goalkeeper": "GK" in position.upper(),
                "source": "understat",
            }
        )
    # AFTER the loop, because the prior is computed from the population.
    _shrink_toward_prior(rows)
    return rows


#: MLS's minutes floor is applied SERVER-SIDE by ASA, as a request parameter --
#: which is why lowering the local `normalize_*` threshold in `3355d621` did
#: nothing here: thin rows never arrived to be shrunk. Lowered to match the
#: Understat path now that `normalize_asa_players` shrinks toward the positional
#: prior (`6ec3c99d`) instead of publishing raw 90-shots/90 rates.
_ASA_MINIMUM_MINUTES = 1


def fetch_asa_mls_players(
    season_name: str | int,
    *,
    minimum_minutes: int = _ASA_MINIMUM_MINUTES,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Fetch MLS player xgoals rows joined with the ASA player directory."""
    xgoals = requests.get(
        f"{_ASA_BASE}/players/xgoals",
        params={"season_name": str(season_name), "minimum_minutes": int(minimum_minutes)},
        timeout=timeout,
        headers=_USER_AGENT,
    )
    xgoals.raise_for_status()
    players = requests.get(f"{_ASA_BASE}/players", timeout=timeout, headers=_USER_AGENT)
    players.raise_for_status()
    directory = {str(row.get("player_id")): row for row in players.json()}
    teams = fetch_asa_mls_team_directory(timeout=timeout)
    merged: list[dict[str, Any]] = []
    for row in xgoals.json():
        info = directory.get(str(row.get("player_id"))) or {}
        team_id = row.get("team_id")
        if isinstance(team_id, list) and team_id:
            team_id = team_id[-1]
        merged.append(
            {
                **row,
                "player_name": info.get("player_name"),
                "position": info.get("primary_general_position"),
                "team_name": teams.get(str(team_id), str(team_id or "")),
            }
        )
    return merged


def fetch_asa_mls_team_directory(*, timeout: int = 30) -> dict[str, str]:
    """ASA team_id -> team name."""
    response = requests.get(f"{_ASA_BASE}/teams", timeout=timeout, headers=_USER_AGENT)
    response.raise_for_status()
    return {str(row.get("team_id")): str(row.get("team_name") or "") for row in response.json()}


def fetch_asa_mls_team_history(season_name: str | int, *, timeout: int = 30) -> list[dict[str, Any]]:
    """MLS per-team season xG rows normalized to the team-history row shape
    ``compute_team_ratings`` consumes (per-match averages, not totals)."""
    response = requests.get(
        f"{_ASA_BASE}/teams/xgoals",
        params={"season_name": str(season_name)},
        timeout=timeout,
        headers=_USER_AGENT,
    )
    response.raise_for_status()
    directory = fetch_asa_mls_team_directory(timeout=timeout)
    rows: list[dict[str, Any]] = []
    for team in response.json():
        games = _safe_number(team.get("count_games")) or 0.0
        if games <= 0:
            continue
        xg_for = _safe_number(team.get("xgoals_for")) or 0.0
        xg_against = _safe_number(team.get("xgoals_against")) or 0.0
        rows.append(
            {
                "league": "mls",
                "season": str(season_name),
                "team": directory.get(str(team.get("team_id")), str(team.get("team_id"))),
                "xg_for": round(xg_for / games, 4),
                "xg_against": round(xg_against / games, 4),
                "ppda": None,
                "games": games,
            }
        )
    return rows


def normalize_asa_players(
    raw_players: list[dict[str, Any]],
    *,
    season: int,
    # 1.0, matching the Understat path: a player with minutes has a rate worth
    # estimating and shrinking; a player with none has nothing to shrink.
    minimum_minutes: float = 1.0,
) -> list[dict[str, Any]]:
    # ASA rows lack games-played; approximate each player's minutes share
    # as minutes relative to the team's most-used player (a proxy for the
    # team's playable season minutes so far).
    team_max_minutes: dict[str, float] = {}
    for player in raw_players:
        team_key = str(player.get("team_name") or player.get("team_id") or "")
        try:
            minutes = float(player.get("minutes_played") or 0.0)
        except Exception:
            minutes = 0.0
        team_max_minutes[team_key] = max(team_max_minutes.get(team_key, 0.0), minutes)

    rows: list[dict[str, Any]] = []
    for player in raw_players:
        try:
            minutes = float(player.get("minutes_played") or 0.0)
        except Exception:
            minutes = 0.0
        if minutes < minimum_minutes:
            continue
        position = str(player.get("position") or player.get("general_position") or "")
        team = str(player.get("team_name") or "")
        if not team:
            team_id = player.get("team_id")
            if isinstance(team_id, list) and team_id:
                team = str(team_id[-1])
            elif team_id:
                team = str(team_id)
        team_key = str(player.get("team_name") or player.get("team_id") or "")
        max_minutes = team_max_minutes.get(team_key) or 0.0
        minutes_share = round(min(1.0, minutes / max_minutes), 4) if max_minutes > 0 else None
        rows.append(
            {
                "league": "mls",
                "season": season,
                "player_id": f"asa_{player.get('player_id')}",
                "player_name": str(player.get("player_name") or "").strip(),
                "team": team,
                "position": position,
                "minutes": minutes,
                "games": None,
                "shots_per90": _per90(player.get("shots"), minutes),
                "xg_per90": _per90(player.get("xgoals"), minutes),
                "xa_per90": _per90(player.get("xassists"), minutes),
                "goals_per90": _per90(player.get("goals"), minutes),
                "assists_per90": _per90(player.get("primary_assists"), minutes),
                "key_passes_per90": _per90(player.get("key_passes"), minutes),
                "expected_minutes_share": minutes_share,
                "is_goalkeeper": position.upper() in {"GK", "GOALKEEPER"},
                "source": "asa",
            }
        )
    # SAME SHRINKAGE AS THE UNDERSTAT PATH. Inert today -- ASA applies
    # `minimum_minutes` SERVER-SIDE as a request parameter, so thin rows do
    # not arrive -- but wiring it now means lowering that parameter (which
    # the `--kind players` producer step will want) cannot start publishing
    # raw 90-shots/90 rows into a share that normalises to ~1.0.
    _shrink_toward_prior(rows)
    return rows


__all__ = [
    "UNDERSTAT_LEAGUES",
    "UNDERSTAT_OUTAGE_COOLDOWN_SECONDS",
    "UNDERSTAT_OUTAGE_GUARD_ENV",
    "UnderstatUnavailable",
    "fetch_asa_mls_players",
    "fetch_asa_mls_team_directory",
    "fetch_asa_mls_team_history",
    "fetch_understat_league_data",
    "fetch_understat_players",
    "normalize_asa_players",
    "normalize_understat_players",
    "normalize_understat_team_history",
    "read_understat_status",
    "understat_outage_guard_enabled",
]
