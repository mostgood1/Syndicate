"""NHL's in-play player-prop pull on its own clock (lane nhl-inplay-props-drop, 2026-11-17).

WHY. The board's in-play overlay keeps a live row only while its quote was SEEN within 300 s
(`book_grid_artifact.is_inplay_fresh_row`, `SYNDICATE_INPLAY_OVERLAY_MAX_PRICE_AGE_SECONDS`). Every other
live sport has an in-play capture lane on the live-odds-worker's 30 s capture thread; NHL had none. Its
live player props were captured only by `refresh_nhl_oddsapi.py` inside the shared live sweep, so every
NHL prop line shared ONE capture clock, and that clock was slower than the window.
Measured on the fleet 11-17 (`.syndicate/findings_2026-11-17_nhl_inplay_props_drop.md`):
- 18 prop captures, median gap 335 s (> 300), max 1,869 s while the NHL sweep step hung;
- 76 of 76 NHL overlay builds split exactly at 300 s of that capture's age: 43 carried 464-956 rows,
  33 carried 0-99 and no props;
- no fresh live props on the overlay for 53% of the in-play window (22% before the hangs).

WHAT A PULL DOES (`scripts/refresh_nhl_inplay_props.py`):
- OddsAPI `/events`, which draws nothing on the quota, then only games that started less than
  `_LIVE_AFTER_START_SECONDS` ago;
- one `event_odds` call per live game, with the sweep's own prop markets and books
  (`NHL_INPLAY_PROP_MARKETS`, `NHL_PROP_BOOKMAKERS`). NO fallback retries and NO historical calls:
  each is a multiplier on credits, and a live pull that misses is simply retried on the next tick;
- the rows go through the sweep's own writer, `local_nhl_odds._append_nhl_book_quotes(kind="prop")`.
  That refreshes every line's last-seen stamp, so a quote the book still shows stays in-play-fresh
  line by line.
It never calls the NHL web API, which is where the 11-17 sweep hangs sat.

COST: 5 credits per live game per pull (5 markets x 1 region; a 10-book list bills as one region).
At the default 120 s, an 11-game night (~28.6 live game-hours) is ~4,300 credits, an upper estimate,
against the 5M monthly cap. Every call is recorded by `record_oddsapi_quota`.

ABSENT MEANS OFF, the NFL lines lane's rule, because this one spends credits:
  SYNDICATE_ENABLE_NHL_INPLAY_PROPS_AUTORUN=1      turn it on (the fleet builds env only at `up`)
  SYNDICATE_NHL_INPLAY_PROPS_INTERVAL_SECONDS      seconds between launches (default 120, floor 60)
  SYNDICATE_NHL_INPLAY_PROPS_TIMEOUT_SECONDS       a pull still running after this is killed (default 90)

ONE CHILD AT A TIME. The launcher runs under the capture thread's shared lock, so it must never block:
it starts the child, returns, and checks on it at the next 30 s tick.
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ENABLE_ENV = "SYNDICATE_ENABLE_NHL_INPLAY_PROPS_AUTORUN"
INTERVAL_ENV = "SYNDICATE_NHL_INPLAY_PROPS_INTERVAL_SECONDS"
TIMEOUT_ENV = "SYNDICATE_NHL_INPLAY_PROPS_TIMEOUT_SECONDS"

_INTERVAL_DEFAULT_SECONDS = 120
_INTERVAL_FLOOR_SECONDS = 60
_TIMEOUT_DEFAULT_SECONDS = 90
# A game that started this long ago and is not FINAL is treated as live. An NHL game with overtime and a
# shootout runs ~2.5-3 h; past this a stale "LIVE" on an old scoreboard must not keep spending.
_LIVE_AFTER_START_SECONDS = 4 * 3600
_ON_VALUES = frozenset({"1", "true", "yes", "on"})
# The sweep's scoreboard (`local_nhl_odds.write_scoreboard_snapshot`) states.
_LIVE_STATES = frozenset({"LIVE", "CRIT"})
_DONE_STATES = frozenset({"FINAL", "OFF"})

#: The sweep's prop markets (`local_nhl_odds.collect_oddsapi_props`), each to the grid CODE the sweep
#: files it under. A test holds this equal to the sweep's own list, so the two cannot drift apart.
NHL_INPLAY_PROP_MARKETS: dict[str, str] = {
    "player_points": "POINTS",
    "player_assists": "ASSISTS",
    "player_goals": "GOALS",
    "player_shots_on_goal": "SOG",
    "player_total_saves": "SAVES",
}

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "refresh_nhl_inplay_props.py"

# The one running pull: (process, monotonic start, date). Module state is right: one process owns the
# capture thread, and a restart has no child to find.
_CHILD: tuple[Any, float, str] | None = None
_LAST_LAUNCH_EPOCH = 0.0


def nhl_inplay_props_enabled() -> bool:
    return str(os.environ.get(ENABLE_ENV) or "").strip().lower() in _ON_VALUES


def _env_int(name: str, default: int, floor: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(floor, value)


def nhl_inplay_props_interval_seconds() -> int:
    return _env_int(INTERVAL_ENV, _INTERVAL_DEFAULT_SECONDS, _INTERVAL_FLOOR_SECONDS)


def nhl_inplay_props_timeout_seconds() -> int:
    return _env_int(TIMEOUT_ENV, _TIMEOUT_DEFAULT_SECONDS, 10)


def _scoreboard_path(date_iso: str) -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root() / "nhl_source" / "data" / "odds" / "games" / f"date={date_iso}" / "scoreboard.csv"


def _parse_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def nhl_live_game_count(date_iso: str, *, now: datetime | None = None) -> int:
    """Games on the sweep's NHL scoreboard for `date_iso` that are in play. No network.

    LIVE / CRIT counts, unless the game started more than 4 h ago. A game the scoreboard still shows
    FUT / PRE also counts once its start time has passed: the sweep writes this file, and the sweep is
    exactly what stalls. A missing or unreadable file counts 0, which launches nothing: today's
    behaviour, and no credits spent on a guess.
    """
    moment = now or datetime.now(timezone.utc)
    try:
        with _scoreboard_path(date_iso).open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return 0
    except Exception:  # noqa: BLE001 -- a torn file is "unknown", which launches nothing
        return 0
    count = 0
    for row in rows:
        state = str(row.get("gameState") or "").strip().upper()
        if state in _DONE_STATES:
            continue
        start = _parse_utc(row.get("gameDate"))
        if start is not None and (moment - start).total_seconds() > _LIVE_AFTER_START_SECONDS:
            continue
        if state in _LIVE_STATES:
            count += 1
        elif start is not None and start <= moment:
            count += 1
    return count


def _slate_dates(now: datetime) -> list[str]:
    """Today on the board's (Central) calendar, and yesterday: a late game runs past midnight Central."""
    from syndicate.features.shared.timezone import CENTRAL_TIMEZONE

    today = now.astimezone(CENTRAL_TIMEZONE).date()
    return [today.isoformat(), (today - timedelta(days=1)).isoformat()]


def _reap(now_mono: float) -> bool:
    """Settle the running child. True while one is still running (nothing may launch)."""
    global _CHILD
    if _CHILD is None:
        return False
    process, started, date_iso = _CHILD
    rc = process.poll()
    if rc is None:
        elapsed = now_mono - started
        if elapsed <= nhl_inplay_props_timeout_seconds():
            return True
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass
        print(f"[live_odds_worker] NHL_INPLAY_PROPS_TIMEOUT date={date_iso} elapsed_s={elapsed:.0f} "
              f"timeout_s={nhl_inplay_props_timeout_seconds()} pid={getattr(process, 'pid', None)}", flush=True)
        _CHILD = None
        return False
    print(f"[live_odds_worker] NHL_INPLAY_PROPS_DONE date={date_iso} rc={rc} elapsed_s={now_mono - started:.0f}",
          flush=True)
    _CHILD = None
    return False


def launch_autorun_nhl_inplay_props(*, now: datetime | None = None,
                                    popen: Callable[..., Any] = subprocess.Popen) -> dict[str, Any] | None:
    """One capture-thread tick. Returns what it launched, or None. Never blocks on the child."""
    global _CHILD, _LAST_LAUNCH_EPOCH
    if not nhl_inplay_props_enabled():
        return None
    if _reap(time.monotonic()):
        return None
    if _LAST_LAUNCH_EPOCH > 0.0 and (time.time() - _LAST_LAUNCH_EPOCH) < nhl_inplay_props_interval_seconds():
        return None
    moment = now or datetime.now(timezone.utc)
    live_by_date = {date_iso: nhl_live_game_count(date_iso, now=moment) for date_iso in _slate_dates(moment)}
    live_games = sum(live_by_date.values())
    if live_games <= 0:
        return None
    selected_date = next(d for d, n in live_by_date.items() if n > 0)
    command = [sys.executable, str(_SCRIPT), "--date", selected_date]
    nice = shutil.which("nice")
    if nice:
        command = [nice, "-n", "5", *command]
    # stdout is inherited, so the child's one PULL line lands in the live-odds-worker log.
    process = popen(command, cwd=str(_REPO_ROOT))
    _CHILD = (process, time.monotonic(), selected_date)
    _LAST_LAUNCH_EPOCH = time.time()
    print(f"[live_odds_worker] NHL_INPLAY_PROPS_LAUNCHED date={selected_date} live_games={live_games} "
          f"interval_s={nhl_inplay_props_interval_seconds()} pid={getattr(process, 'pid', None)}", flush=True)
    return {"date": selected_date, "live_games": live_games, "pid": getattr(process, "pid", None)}


def parse_prop_event(event: dict[str, Any], *, date: str, collected_at: str) -> list[dict[str, Any]]:
    """One `event_odds` payload -> rows in `collect_oddsapi_props`' shape, which `_append_nhl_book_quotes` reads."""
    rows: list[dict[str, Any]] = []
    if not isinstance(event, dict):
        return rows
    for bookmaker in event.get("bookmakers") or []:
        book_key = (bookmaker or {}).get("key") or "oddsapi"
        for market in (bookmaker or {}).get("markets") or []:
            code = NHL_INPLAY_PROP_MARKETS.get(str((market or {}).get("key") or ""))
            if not code:
                continue
            for outcome in (market or {}).get("outcomes") or []:
                side = str(outcome.get("name") or "").strip().upper()
                player = (outcome.get("description") or outcome.get("participant") or outcome.get("player_name")
                          or outcome.get("player") or "")
                try:
                    line = float(outcome.get("point")) if outcome.get("point") is not None else None
                except (TypeError, ValueError):
                    line = None
                odds = outcome.get("price")
                if not player or line is None or odds is None or side not in {"OVER", "UNDER"}:
                    continue
                rows.append({
                    "market": code,
                    "player": player,
                    "line": line,
                    "odds": odds,
                    "side": side,
                    "book": book_key,
                    "date": date,
                    "event_id": event.get("id"),
                    "commence_time": event.get("commence_time"),
                    "home_team": event.get("home_team"),
                    "away_team": event.get("away_team"),
                    "collected_at": collected_at,
                })
    return rows


def live_events(events: list[dict[str, Any]], *, now: datetime) -> list[dict[str, Any]]:
    """The listed events that have started and started less than 4 h ago."""
    out = []
    for event in events or []:
        start = _parse_utc((event or {}).get("commence_time"))
        if start is None or not event.get("id"):
            continue
        if 0 <= (now - start).total_seconds() <= _LIVE_AFTER_START_SECONDS:
            out.append(event)
    return out


def reset_for_tests() -> None:
    global _CHILD, _LAST_LAUNCH_EPOCH
    _CHILD = None
    _LAST_LAUNCH_EPOCH = 0.0
