"""Persist NBA live per-player box lines as an artifact a worker can read.

THE NBA SIBLING OF `scripts/capture_wnba_live_player_box.py`, and the same
artifact shape (`{"date", "source", "payload": {"games": [{event_id, players}]}}`)
so the two basketball resolvers read one contract.

WHY IT DOES NOT CALL WEB, which is what the WNBA capture does. Measured on the
fleet 2026-10-24 00:30Z with six NBA games on the slate and one in the 1st
quarter: `/nba/api/live_player_boxscore?date=2026-10-23` returned six games and
ZERO players in every one -- `build_live_player_boxscore_payload` short-circuits
to an empty list on a web dyno (`_render_web_dyno()`), so a copy of the WNBA
capture would have stored nothing, forever, and looked wired.

WHY IT CALLS THE LIVE TICK'S OWN FETCHERS INSTEAD. The NBA live tick already
fetches every live game's ESPN `/summary` on this worker and extracts the whole
player box -- points, rebounds, assists, threes, steals, BLOCKS, turnovers --
for the live lens, then throws the box away. This reuses
`_live_fetch_espn_summary` (15 s TTL cache) and
`_live_extract_player_boxscore_from_espn_summary` rather than writing a third
ESPN box parser. Called right after the NBA lens build, so the summaries the
build just fetched are normally still cached.

WHAT IT ADDS THAT THE WNBA ARTIFACT LACKS: game state. The WNBA live box has no
status field, so `bet_status_wnba` hardcodes `is_final=False` and an under can
never decide from it. ESPN's scoreboard says `pre` / `in` / `post` per game, and
that is recorded here per game, so the resolver can say "not started", and
grade an under once the game is over.

A FINISHED GAME IS NOT REFETCHED. Once a game is captured with `final=True` its
box is carried forward from the artifact on every later tick, so a slate that
finishes through the evening costs one scoreboard call per tick afterwards.

AN IN-PROGRESS GAME WHOSE FETCH CAME BACK EMPTY KEEPS ITS PREVIOUS PLAYERS.
A failed or empty fetch is not "nobody has a stat" -- persisting it would read
that way to every consumer (the failure `capture_wnba_pbp.py` records).

NEVER RAISES out of `capture`; the caller is a live-lens tick that every sport
shares.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

__all__ = ["artifact_relative_path", "capture", "games_from_scoreboard"]

SOURCE = "nba/live_tick espn summary"


def artifact_relative_path(date_str: str) -> str:
    """Where the capture lands, relative to the data root. Same layout as WNBA's."""
    return f"nba_source/data/live/live_player_box_{date_str}.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _score(competitor: Mapping[str, Any]) -> float | None:
    try:
        raw = competitor.get("score")
        if raw is None or str(raw).strip() == "":
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def games_from_scoreboard(scoreboard: Any, to_tri: Callable[[str], Any]) -> list[dict[str, Any]]:
    """Per game: event id, the two tri-codes, scores and state. Skips anything partial."""
    out: list[dict[str, Any]] = []
    events = scoreboard.get("events") if isinstance(scoreboard, Mapping) else None
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, Mapping):
            continue
        event_id = str(event.get("id") or "").strip()
        comps = event.get("competitions")
        if not event_id or not isinstance(comps, list) or not comps or not isinstance(comps[0], Mapping):
            continue
        comp = comps[0]
        status = comp.get("status") if isinstance(comp.get("status"), Mapping) else {}
        st_type = status.get("type") if isinstance(status.get("type"), Mapping) else {}
        state = str(st_type.get("state") or "").strip().lower()
        if state not in {"pre", "in", "post"}:
            continue
        sides: dict[str, Mapping[str, Any]] = {}
        for competitor in comp.get("competitors") or []:
            if isinstance(competitor, Mapping) and competitor.get("homeAway") in {"home", "away"}:
                sides[str(competitor["homeAway"])] = competitor
        if set(sides) != {"home", "away"}:
            continue
        tris = {}
        for side, competitor in sides.items():
            team = competitor.get("team") if isinstance(competitor.get("team"), Mapping) else {}
            tris[side] = str(to_tri(str(team.get("abbreviation") or "")) or "").strip().upper()
        if not tris["home"] or not tris["away"]:
            continue
        out.append(
            {
                "event_id": event_id,
                "home_tri": tris["home"],
                "away_tri": tris["away"],
                "state": state,
                "final": bool(st_type.get("completed")) or state == "post",
                "status_detail": str(st_type.get("shortDetail") or st_type.get("detail") or "").strip() or None,
                # Pregame ESPN reports 0-0; a score is only a fact once the game is on.
                "home_score": _score(sides["home"]) if state != "pre" else None,
                "away_score": _score(sides["away"]) if state != "pre" else None,
            }
        )
    return out


def _tick_fetchers():
    from syndicate.features.nba.live_tick.tick import (
        _espn_to_tri,
        _live_extract_player_boxscore_from_espn_summary,
        _live_fetch_espn_scoreboard,
        _live_fetch_espn_summary,
    )

    return _live_fetch_espn_scoreboard, _live_fetch_espn_summary, _live_extract_player_boxscore_from_espn_summary, _espn_to_tri


def capture(
    date_str: str,
    *,
    fetch_scoreboard: Callable[[str], Any] | None = None,
    fetch_summary: Callable[[str], Any] | None = None,
    extract_players: Callable[[Any], list] | None = None,
    to_tri: Callable[[str], Any] | None = None,
    read_existing: Callable[[], Any] | None = None,
    write: Callable[[dict[str, Any]], None] | None = None,
    now: Callable[[], str] = _utc_now,
) -> dict[str, Any]:
    """Capture the slate's live box. Returns counts; writes only when a game is on the slate.

    The fetchers are injectable so the merge rules are testable without ESPN;
    the defaults are the live tick's own.
    """
    result: dict[str, Any] = {"date": date_str, "written": False, "games": 0, "live": 0, "final": 0,
                              "players": 0, "fetched": 0, "carried": 0}
    try:
        if fetch_scoreboard is None or fetch_summary is None or extract_players is None or to_tri is None:
            sb, summ, extract, tri = _tick_fetchers()
            fetch_scoreboard = fetch_scoreboard or sb
            fetch_summary = fetch_summary or summ
            extract_players = extract_players or extract
            to_tri = to_tri or tri
        if read_existing is None or write is None:
            from syndicate.features.shared.refresh_state_store import data_root, read_json_file, write_json_file

            path = data_root() / artifact_relative_path(date_str)
            read_existing = read_existing or (lambda: read_json_file(path))
            write = write or (lambda record: write_json_file(path, record))

        games = games_from_scoreboard(fetch_scoreboard(date_str) or {}, to_tri)
        if not games:
            result["reason"] = "no_games_on_scoreboard"
            return result

        previous: dict[str, Mapping[str, Any]] = {}
        try:
            existing = read_existing()
        except Exception:
            existing = None
        payload = existing.get("payload") if isinstance(existing, Mapping) else None
        for game in (payload or {}).get("games") or []:
            if isinstance(game, Mapping) and game.get("event_id"):
                previous[str(game["event_id"])] = game

        stamp = now()
        out_games: list[dict[str, Any]] = []
        for game in games:
            prior = previous.get(game["event_id"])
            players: list = []
            captured_at = None
            if game["state"] == "pre":
                pass
            elif prior and prior.get("final") and prior.get("players"):
                # FINISHED AND ALREADY HELD: the box cannot change again.
                game = {**game, **{k: prior.get(k) for k in ("home_score", "away_score", "status_detail")}}
                players = list(prior.get("players") or [])
                captured_at = prior.get("captured_at")
                result["carried"] += 1
            else:
                try:
                    fetched = extract_players(fetch_summary(game["event_id"]) or {}) or []
                except Exception:
                    fetched = []
                result["fetched"] += 1
                if fetched:
                    players = fetched
                    captured_at = stamp
                elif prior and prior.get("players"):
                    # An empty fetch is not "nobody has a stat"; keep the last real box,
                    # and its own stamp, so the as-of says how old it is.
                    players = list(prior.get("players") or [])
                    captured_at = prior.get("captured_at")
                    result["carried"] += 1
                if game["final"] and not fetched:
                    # Never mark a box FINAL that was not read after the game ended:
                    # an under would grade off a mid-game number.
                    game = {**game, "final": False, "final_unconfirmed": True}
            out_games.append({**game, "captured_at": captured_at, "players": players})

        result["games"] = len(out_games)
        result["live"] = sum(1 for g in out_games if g["state"] == "in")
        result["final"] = sum(1 for g in out_games if g.get("final"))
        result["players"] = sum(len(g["players"]) for g in out_games)
        write(
            {
                "date": date_str,
                "source": SOURCE,
                "captured_at": stamp,
                "counts": {k: result[k] for k in ("games", "live", "final", "players")},
                "payload": {"games": out_games},
            }
        )
        result["written"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result
