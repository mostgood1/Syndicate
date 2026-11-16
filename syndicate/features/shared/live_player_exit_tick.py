"""One live tick's player-exit read for a sport (lane live-player-exit-gate).

`collect_exit_statuses(sport, live_rows)` fetches each IN-PROGRESS game's ESPN summary and runs the pure
detector (`live_player_status.exits_from_espn_summary`) on it. -> ({event_id: GameExitStatus}, tally).

The NFL re-sim keeps its own copy (`nfl/live_resim._player_exit_statuses`, loaded 2026-11-15); every
other sport's producer calls this. Differences from that copy, on purpose:

* GETs run on a small thread pool. A college Saturday has ~50 games live at once on a 75 s tick; one
  GET each, sequential at ~0.4 s, would cost the tick ~20 s (`#241`: worker periodic work is never free).
* A row is in progress when `state` is in/live/in_progress OR `in_progress` is true (the NCAAF live
  index carries the bool, not the ESPN state).

A summary that cannot be read gives NO status for that game and is COUNTED (`unreadable`) -- never a
silent "nobody is out". A game not reached inside the budget is counted (`budget_exhausted`). Never raises.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Callable, Iterable, Mapping

ESPN_SUMMARY_PATHS: dict[str, str] = {
    "nfl": "football/nfl",
    "ncaaf": "football/college-football",
    "nba": "basketball/nba",
    "wnba": "basketball/wnba",
    "ncaab": "basketball/mens-college-basketball",
    "wncaab": "basketball/womens-college-basketball",
    "nhl": "hockey/nhl",
}
DEFAULT_BUDGET_SECONDS = 20.0
FETCH_TIMEOUT_SECONDS = 8.0
MAX_WORKERS = 6
_LIVE_STATES = {"in", "live", "in_progress"}


def fetch_espn_summary(sport: str, event_id: str) -> Mapping[str, Any] | None:
    """The public ESPN summary (no custom headers, like `nfl/live_player_box._fetch_summary`). None on any failure."""
    path = ESPN_SUMMARY_PATHS.get(sport)
    if not path:
        return None
    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={urllib.parse.quote(str(event_id))}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=FETCH_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, Mapping) else None


def row_in_progress(row: Mapping[str, Any]) -> bool:
    if str(row.get("state") or "").strip().lower() in _LIVE_STATES:
        return True
    return row.get("in_progress") is True


def new_tally() -> dict[str, Any]:
    return {"live_games": 0, "read": 0, "unreadable": 0, "no_event_id": 0,
            "budget_exhausted": 0, "players_out": 0, "key_players_out": 0}


def status_from_summary(sport: str, summary: Any, event_id: str, tally: dict[str, Any], *,
                        env: Mapping[str, str] | None = None, log_tag: str | None = None) -> Any:
    """For a producer that ALREADY fetched the game's ESPN summary (NBA re-sim): no extra GET.
    -> GameExitStatus, or None (gate off, or the summary is unreadable -- counted, never "nobody out"). Never raises."""
    try:
        from syndicate.features.shared import live_player_status as lps
    except Exception as exc:  # noqa: BLE001 -- deploy-skew guard
        tally["error"] = type(exc).__name__
        return None
    if not lps.gate_enabled(env):
        tally["enabled"] = False
        return None
    tally["live_games"] += 1
    if not isinstance(summary, Mapping):
        tally["unreadable"] += 1
        return None
    try:
        status = lps.exits_from_espn_summary(sport, summary, game_id=str(event_id))
    except Exception as exc:  # noqa: BLE001
        tally["unreadable"] += 1
        tally["error"] = type(exc).__name__
        return None
    tally["read"] += 1
    tally["players_out"] += len(status.players_out)
    tally["key_players_out"] += len(status.key_players_out)
    tag = log_tag or f"{sport}_live_resim"
    for p in status.players_out:
        print(f"[{tag}] PLAYER_OUT event={event_id} team={p.team} player={p.player!r} "
              f"reason={p.reason} key={p.key} source={p.source} since={p.since}", flush=True)
    return status


def collect_exit_statuses(
    sport: str,
    live_rows: Iterable[Any],
    *,
    env: Mapping[str, str] | None = None,
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
    fetch: Callable[[str], Any] | None = None,
    max_workers: int = MAX_WORKERS,
    log_tag: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tally: dict[str, Any] = new_tally()
    statuses: dict[str, Any] = {}
    tag = log_tag or f"{sport}_live_resim"
    try:
        from syndicate.features.shared import live_player_status as lps
    except Exception as exc:  # noqa: BLE001 -- deploy-skew guard
        tally["error"] = type(exc).__name__
        return statuses, tally
    if not lps.gate_enabled(env):
        tally["enabled"] = False
        return statuses, tally
    if fetch is None:
        def fetch(event_id: str, _sport: str = sport) -> Any:
            return fetch_espn_summary(_sport, event_id)

    event_ids: list[str] = []
    for row in live_rows or ():
        if not isinstance(row, Mapping) or not row_in_progress(row):
            continue
        tally["live_games"] += 1
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            tally["no_event_id"] += 1
        elif event_id not in event_ids:
            event_ids.append(event_id)

    started = time.monotonic()
    summaries: dict[str, Any] = {}  # only games whose GET FINISHED inside the budget
    if event_ids:
        def one(event_id: str) -> Any:
            try:
                return fetch(event_id)
            except Exception:  # noqa: BLE001
                return None

        pool = ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), len(event_ids))),
                                  thread_name_prefix=f"{sport}-exit")
        try:
            futures = {pool.submit(one, e): e for e in event_ids}
            done, _late = wait(futures, timeout=max(0.0, float(budget_seconds)))
            for future in done:
                summaries[futures[future]] = future.result()
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    for event_id in event_ids:
        if event_id not in summaries:
            tally["budget_exhausted"] += 1
            continue
        summary = summaries[event_id]
        if not isinstance(summary, Mapping):
            tally["unreadable"] += 1
            continue
        status = lps.exits_from_espn_summary(sport, summary, game_id=event_id)
        statuses[event_id] = status
        tally["read"] += 1
        tally["players_out"] += len(status.players_out)
        tally["key_players_out"] += len(status.key_players_out)
        for p in status.players_out:
            print(f"[{tag}] PLAYER_OUT event={event_id} team={p.team} player={p.player!r} "
                  f"reason={p.reason} key={p.key} source={p.source} since={p.since}", flush=True)
    tally["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if tally["live_games"]:
        print(f"[{tag}] PLAYER_EXIT_TICK " + " ".join(f"{k}={v}" for k, v in tally.items()), flush=True)
    return statuses, tally
