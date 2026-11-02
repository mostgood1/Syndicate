"""The NCAAB Division I slate: ESPN's scoreboard, cut to D1 vs D1, as ONE artifact.

WHY THIS EXISTS (2026-11-02, opening day). Nothing in Syndicate produced an
NCAAB game list. Every NCAAB game surface read `recommendations_<date>.json`,
which only the retired external NCAAB app ever wrote, so on the 2026-27 opener
the fleet served:

    /api/board/game-chips sports=ncaab      0 chips (nba 15, nhl 4, soccer 309)
    /ncaab (cards)                          "No game cards were available"
    /api/board/layer1 sport=ncaab           16 games, every one state `unknown`,
                                            rows_enriched 0 (attach_game_state
                                            reads the same empty chips)
    Layer 2 Games rail                      chip-less cards: no logos, no time,
                                            no line, "15 opportunities"

The odds were there (book grid 11-02, Layer 2 `ncaab cand=268`); the GAMES were
not. This module is the games.

D1 ONLY, BOTH SIDES (user, 2026-11-02: "we only want NCAA D1 basketball").
`groups=50` is ESPN's Division I filter, but it means "a D1 team is playing":
measured on 2026-11-02 it returned 182 events, 116 D1 vs D1 and 66 against a
non-D1 opponent. A game is kept only when BOTH teams' ESPN ids are in the
committed registry (`ncaab_team_registry.csv`, 362 programmes).

WORKER FETCHES, WEB READS. The fetch is one free ESPN request, but it is still
network IO, and the web is display-only. `slate_games` refreshes the artifact
only in a non-gunicorn process (`game_chip_plays._is_worker`, the predicate that
already survived the fleet's one-env-file-for-every-role layout); the web reads
whatever the worker last wrote. Chips are built on the refresh-worker every
publish, so the artifact is as fresh as the scoreboard the board already shows.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from syndicate.features.shared.timezone import CENTRAL_TIMEZONE

SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/"
    "scoreboard?dates={compact}&groups=50&limit=500"
)
# A live game's score moves every possession; the worker's chip publish runs
# every few minutes, so this only stops two builds in one minute paying twice.
_REFRESH_AFTER_SECONDS = 60.0
_FETCH_TIMEOUT_SECONDS = 10.0


def _data_root() -> Path:
    env = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data"


# ONE MODULE, BOTH COLLEGE LEAGUES (lane wncaab-module, 2026-11-02): every function takes `league`
# (`ncaab` default, unchanged) -- women's college basketball reads ESPN's women's board, its own
# registry, its own data dir and its own book grid through the same code.
def _league(league: str):
    from syndicate.features.college_basketball.league import league_for

    return league_for(league)


def slate_artifact_path(date_iso: str, league: str = "ncaab") -> Path:
    return _data_root() / _league(league).data_dir / "data" / "scoreboard" / f"scoreboard_{date_iso}.json"


def _d1_ids(league: str = "ncaab") -> frozenset[str]:
    from syndicate.features.shared.ncaab_team_registry import registry_rows

    return frozenset(str(row.get("espn_id") or "").strip() for row in registry_rows(league) if str(row.get("espn_id") or "").strip())


def _score(value: Any) -> int | None:
    try:
        text = str(value).strip()
        return int(float(text)) if text else None
    except (TypeError, ValueError):
        return None


def _side(competitor: Mapping[str, Any], *, show_score: bool) -> dict[str, Any]:
    team = competitor.get("team") if isinstance(competitor.get("team"), Mapping) else {}
    periods = [
        _score((item or {}).get("value"))
        for item in (competitor.get("linescores") or [])
        if isinstance(item, Mapping)
    ]
    color = str(team.get("color") or "").strip()
    return {
        "espn_id": str(team.get("id") or "").strip(),
        "abbr": str(team.get("abbreviation") or "").strip(),
        "name": str(team.get("displayName") or "").strip(),
        "short_name": str(team.get("shortDisplayName") or "").strip(),
        "logo": str(team.get("logo") or "").strip() or None,
        "primary_color": f"#{color}" if color else None,
        # A pregame ESPN score is "0", a placeholder, not an observation.
        "score": _score(competitor.get("score")) if show_score else None,
        "periods": periods if show_score else [],
    }


def parse_scoreboard(payload: Any, *, d1_ids: frozenset[str]) -> tuple[list[dict[str, Any]], int]:
    """(D1-vs-D1 games, count dropped for a non-D1 side)."""
    events = payload.get("events") if isinstance(payload, Mapping) else None
    games: list[dict[str, Any]] = []
    dropped = 0
    for event in events or []:
        if not isinstance(event, Mapping):
            continue
        competitions = event.get("competitions") or []
        comp = competitions[0] if competitions and isinstance(competitions[0], Mapping) else {}
        competitors = [c for c in comp.get("competitors") or [] if isinstance(c, Mapping)]
        home = next((c for c in competitors if str(c.get("homeAway") or "").lower() == "home"), None)
        away = next((c for c in competitors if str(c.get("homeAway") or "").lower() == "away"), None)
        if home is None or away is None:
            continue
        ids = {str((c.get("team") or {}).get("id") or "").strip() for c in (home, away)}
        if not ids <= d1_ids:
            dropped += 1
            continue
        status = comp.get("status") if isinstance(comp.get("status"), Mapping) else (event.get("status") or {})
        status_type = status.get("type") if isinstance(status.get("type"), Mapping) else {}
        state = str(status_type.get("state") or "").strip().lower()
        final = bool(status_type.get("completed")) or state == "post"
        in_progress = state == "in" and not final
        show_score = in_progress or final
        event_id = str(event.get("id") or "").strip()
        away_side = _side(away, show_score=show_score)
        home_side = _side(home, show_score=show_score)
        period = _score(status.get("period"))
        games.append({
            "event_id": event_id,
            "gamePk": event_id,
            "game_id": event_id,
            "matchup": f"{away_side['name']} @ {home_side['name']}",
            "start_time_utc": str(event.get("date") or "").strip() or None,
            "neutral_site": bool(comp.get("neutralSite")),
            "venue": str(((comp.get("venue") or {}) if isinstance(comp.get("venue"), Mapping) else {}).get("fullName") or "").strip() or None,
            "away": away_side,
            "home": home_side,
            "live_state": {
                "in_progress": in_progress,
                "final": final,
                "period": period if in_progress else None,
                "clock": str(status.get("displayClock") or "").strip() if in_progress else None,
                # "Postponed" / "Canceled" ride here, where the chip's
                # not-played check reads them.
                "status": str(status_type.get("shortDetail") or status_type.get("description") or "").strip(),
                "away_linescores": away_side["periods"],
                "home_linescores": home_side["periods"],
            },
        })
    return games, dropped


def _team_key(name: Any, league: str = "ncaab") -> str | None:
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        return chip_join_key(league, str(name or "")) or None
    except Exception:  # noqa: BLE001
        return None


def _odds_feed_pairs(date_iso: str, league: str = "ncaab") -> set[tuple[str, str]]:
    """(away key, home key) for every NCAAB game the book grid prices on this
    Central date or the next UTC one (an evening tip is tomorrow in UTC)."""
    from datetime import date, timedelta

    pairs: set[tuple[str, str]] = set()
    day = date.fromisoformat(date_iso)
    for d in (day, day + timedelta(days=1)):
        path = _data_root() / _league(league).data_dir / "data" / "book_grid" / f"book_grid_{d.isoformat()}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- no grid yet means no orientation evidence
            continue
        rows = payload.get("rows") if isinstance(payload, Mapping) else payload
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            away, home = _team_key(row.get("away_team"), league), _team_key(row.get("home_team"), league)
            if away and home:
                pairs.add((away, home))
    return pairs


def _swap_sides(game: dict[str, Any]) -> dict[str, Any]:
    live = dict(game.get("live_state") or {})
    live["away_linescores"], live["home_linescores"] = live.get("home_linescores"), live.get("away_linescores")
    away, home = game["home"], game["away"]
    return {**game, "away": away, "home": home, "live_state": live, "matchup": f"{away['name']} @ {home['name']}"}


def orient_neutral_site_games(games: list[dict[str, Any]], odds_pairs: set[tuple[str, str]], league: str = "ncaab") -> tuple[list[dict[str, Any]], int]:
    """At a NEUTRAL SITE, list home/away the way the odds feed does.

    "Home" at a neutral site is a label each vendor assigns, and ESPN and
    OddsAPI disagree. Measured 2026-11-02: after the alias fix, 113 of 119
    in-window odds games joined their ESPN game, and the other 6 were ALL
    neutral-site games with home/away swapped (Florida-Miami, Purdue-Gonzaga,
    UCLA-Arizona, ...). Every consumer joins `away @ home` in order -- the
    Games rail's canonical index, Layer 1's `attach_game_state`, the chip
    footer's grid lookup -- so a swapped game had no chip, no state, no line.
    Reorienting here, where the game list is made, fixes all three at once.

    Only neutral-site games, and only when the odds feed has the REVERSED pair
    and not the direct one. A true home game is never touched.
    """
    out: list[dict[str, Any]] = []
    swapped = 0
    for game in games:
        if game.get("neutral_site") and odds_pairs:
            direct = (_team_key(game["away"].get("name"), league), _team_key(game["home"].get("name"), league))
            if direct not in odds_pairs and (direct[1], direct[0]) in odds_pairs:
                out.append(_swap_sides(game))
                swapped += 1
                continue
        out.append(game)
    return out, swapped


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def refresh_slate(date_iso: str, *, fetch_json: Callable[[str], Any] = _fetch_json, league: str = "ncaab") -> dict[str, Any] | None:
    """Fetch, cut to D1 vs D1, write the artifact. None (and nothing written) on failure."""
    compact = date_iso.replace("-", "")
    try:
        payload = fetch_json((SCOREBOARD_URL if league == "ncaab" else _league(league).scoreboard_url).format(compact=compact))
    except Exception as exc:  # noqa: BLE001 -- the last good artifact keeps serving
        print(f"[ncaab_slate] FETCH_FAILED league={league} date={date_iso} error={type(exc).__name__}: {exc}", flush=True)
        return None
    d1_ids = _d1_ids(league)
    if not d1_ids:
        # An empty registry would drop every game and write an empty slate that
        # looks exactly like a day off. Refuse instead.
        print(f"[ncaab_slate] REGISTRY_EMPTY league={league} date={date_iso} -- not writing", flush=True)
        return None
    games, dropped = parse_scoreboard(payload, d1_ids=d1_ids)
    games, reoriented = orient_neutral_site_games(games, _odds_feed_pairs(date_iso, league), league)
    artifact = {
        "date": date_iso,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "espn_scoreboard_groups50",
        "league": league,
        "games": games,
        "dropped_non_d1": dropped,
        "reoriented_neutral_site": reoriented,
    }
    path = slate_artifact_path(date_iso, league)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(artifact), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        print(f"[ncaab_slate] WRITE_FAILED league={league} date={date_iso} error={type(exc).__name__}: {exc}", flush=True)
    return artifact


_read_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def read_slate(date_iso: str, league: str = "ncaab") -> dict[str, Any] | None:
    path = slate_artifact_path(date_iso, league)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _read_cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        payload = None
    payload = payload if isinstance(payload, dict) else None
    _read_cache[str(path)] = (mtime, payload)
    return payload


def _is_worker() -> bool:
    from syndicate.features.shared.game_chip_plays import _is_worker as is_worker

    return is_worker()


def slate_games(date_iso: str, *, refresh: bool | None = None, league: str = "ncaab") -> list[dict[str, Any]]:
    """The D1 games for a Central date. Refreshes (worker only) when the artifact is >60 s old."""
    date_value = str(date_iso or "").strip()[:10]
    if len(date_value) != 10:
        return []
    allowed = _is_worker() if refresh is None else refresh
    current = read_slate(date_value, league)
    if allowed:
        age = None
        try:
            age = time.time() - slate_artifact_path(date_value, league).stat().st_mtime
        except OSError:
            pass
        if age is None or age > _REFRESH_AFTER_SECONDS:
            current = refresh_slate(date_value, league=league) or current
    games = (current or {}).get("games")
    return [dict(game) for game in games] if isinstance(games, list) else []


def central_start_label(start_time_utc: Any) -> str | None:
    text = str(start_time_utc or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    local = parsed.astimezone(CENTRAL_TIMEZONE)
    return f"{local.strftime('%I:%M').lstrip('0')} {local.strftime('%p')} CT"
