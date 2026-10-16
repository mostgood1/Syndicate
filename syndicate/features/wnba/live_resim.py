"""WNBA LIVE RE-SIM: the native engine resumed from the live game state, for the WNBA game lens (P5).

Lane `wnba-native-live-cutover`. User decision 2026-10-16 ("game lens only, coordinate"): the native re-sim replaces
the LINEAR `_wnba_live_*` game lens in `wnba/cards.py` -- live total, home win probability, cover and over -- and
nothing else. The vendored tick in `wnba/live_lens.py` belongs to lane `nba-live-tick-native` (its faithful port);
live props stay on that tick.

WHY: the 2026 checkpoint backtest (1,360 rows, production engine, 0 refusals; findings_2026-10-09_wnba_live_vendored_
inventory.md "P5 BACKTEST RESULT") -- native minus linear, regular season: ML Brier end Q2 -0.0115 [-0.017, -0.005],
end Q3 -0.0085 [-0.014, -0.003], over Brier end Q3 -0.0058 [-0.011, -0.001]; no cell worse.

EVERYTHING HERE IS P3's MACHINERY (`syndicate/features/nba/live_resim.py`, league-parametric since 2026-10-12): the
resume, the refusals, the snapshot builder, the size budget. This module only supplies WNBA's league, team names,
its own switch, tick and thread, and the lens lookup. NOTHING HERE IMPORTS `vendor.`.

SWITCH: `SYNDICATE_WNBA_LIVE_RESIM` -- OFF unless truthy (absent is off). It starts the worker thread AND lets
`cards.py` use the snapshot; with it off, the WNBA game lens is exactly today's linear lens. The live reading is owed
at the 2027 WNBA opener (todo #694) before anyone turns it on.

RUNS ON A WORKER, NEVER IN A REQUEST HANDLER (P3's builder calls `refuse_if_compute_in_request_path`). `cards.py`
only READS the snapshot.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Mapping, Optional

from syndicate.features.nba import live_resim as lr

LEAGUE = "wnba"
LIVE_RESIM_ENV = "SYNDICATE_WNBA_LIVE_RESIM"
INTERVAL_ENV = "SYNDICATE_WNBA_LIVE_RESIM_INTERVAL_SECONDS"
SIMS_ENV = "SYNDICATE_WNBA_LIVE_RESIM_SIMS"
BUDGET_ENV = "SYNDICATE_WNBA_LIVE_RESIM_BUDGET_SECONDS"
# A snapshot older than this is not used by the lens (a stalled worker must not serve a stale live number).
MAX_SNAPSHOT_AGE_SECONDS = 600.0


def _register_team_names() -> None:
    from syndicate.features.basketball_engine.orchestrator.wnba_teams import _NAME_TO_TRI

    lr.register_team_names(LEAGUE, {tri: name for name, tri in _NAME_TO_TRI.items()})


_register_team_names()


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(LIVE_RESIM_ENV, "") or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def _num_env(name: str, default: float, env: Optional[Mapping[str, str]] = None) -> float:
    raw = str((env if env is not None else os.environ).get(name, "") or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def snapshot_path():
    return lr.live_lens_snapshot_path(league=LEAGUE)


def run_tick(date_str: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
    """One tick: P3's builder for league='wnba', size budget, write. Printed with prefix WNBA_LIVE_RESIM_TICK."""
    from syndicate.features.shared.refresh_state_store import write_json_file
    from syndicate.features.shared.timezone import central_today_iso

    date_str = date_str or central_today_iso()
    started = time.monotonic()
    kwargs.setdefault("sims", int(_num_env(SIMS_ENV, 200)))
    kwargs.setdefault("budget_seconds", _num_env(BUDGET_ENV, 240.0))
    snapshot = lr.build_live_lens_snapshot(date_str, league=LEAGUE, **kwargs)
    snapshot, size = lr.fit_snapshot_to_budget(snapshot)
    status = {
        "date": date_str,
        "games": len(snapshot.get("games") or []),
        "resimmed": sum(1 for g in snapshot.get("games") or []
                        for lane in g.get("gameLens") or [] if lane.get("source") == lr.LIVE_RESIM_LENS_SOURCE),
        "refusals": snapshot.get("refusalsByReason") or {},
        "bytes": size,
        "written": False,
    }
    if size <= lr.MAX_SNAPSHOT_BYTES:
        write_json_file(snapshot_path(), snapshot)
        status["written"] = True
    status["elapsed_s"] = round(time.monotonic() - started, 1)
    print("WNBA_LIVE_RESIM_TICK " + " ".join(f"{k}={v}" for k, v in status.items()), flush=True)
    return status


_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()
_LOCK = threading.Lock()


def _loop() -> None:
    while not _STOP.is_set():
        try:
            run_tick()
        except Exception as exc:  # noqa: BLE001 -- a bad tick must not kill the loop; named, never silent
            print(f"WNBA_LIVE_RESIM_TICK_ERROR {type(exc).__name__}: {str(exc)[:300]}", flush=True)
        _STOP.wait(max(30.0, _num_env(INTERVAL_ENV, 120.0)))


def start_loop() -> bool:
    """Start the dedicated thread once per process, only when SYNDICATE_WNBA_LIVE_RESIM is on."""
    global _THREAD
    if not enabled():
        return False
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="syndicate-wnba-live-resim", daemon=True)
        _THREAD.start()
        print("WNBA_LIVE_RESIM_LOOP_STARTED", flush=True)
        return True


# ------------------------------------------------------------------------------------------------ the lens lookup

def p_win_given_no_push(dist: Mapping[str, Any], line: Optional[float], *, offset_sign: int = 1) -> Optional[float]:
    """P(x + sign*line > 0 | x + sign*line != 0) from an integer histogram {str(x): count}. Pushes are excluded, as
    the market settles them and as the P5 backtest graded them.
      cover: x = home margin, line = home spread;  over: x = total, line = total line, sign = -1."""
    if line is None or not dist:
        return None
    win = push = n = 0
    for k, c in dist.items():
        try:
            v = float(k) + offset_sign * float(line)
            c = int(c)
        except (TypeError, ValueError):
            continue
        n += c
        if v > 0:
            win += c
        elif v == 0:
            push += c
    return win / (n - push) if n - push > 0 else None


def _age_seconds(generated_at: Any, now: Optional[float]) -> Optional[float]:
    from datetime import datetime, timezone

    try:
        ts = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now if now is not None else time.time()) - ts.timestamp()


def native_lane(game: Mapping[str, Any], *, snapshot: Optional[Mapping[str, Any]] = None,
                now: Optional[float] = None, env: Optional[Mapping[str, str]] = None) -> Optional[dict[str, Any]]:
    """The published `live_resim` lane for this card game, or None (switch off, no snapshot, stale, other date,
    game not in it, or the game was REFUSED -- a refusal carries no probability and the lens keeps the linear one).
    Matched on ESPN `event_id`, else on (home, away) codes. Never computes anything."""
    if not enabled(env):
        return None
    if snapshot is None:
        from syndicate.features.shared.refresh_state_store import read_json_file

        snapshot = read_json_file(snapshot_path())
    if not isinstance(snapshot, Mapping):
        return None
    # Staleness from P3's ISO `generatedAt`. Missing or unparseable is NOT fresh (unknown never defaults permissive).
    age = _age_seconds(snapshot.get("generatedAt"), now)
    if age is None or age > MAX_SNAPSHOT_AGE_SECONDS:
        return None
    event_id = str(game.get("event_id") or "").strip()
    home = str(game.get("home_tri") or game.get("home") or "").strip().upper()
    away = str(game.get("away_tri") or game.get("away") or "").strip().upper()
    for g in snapshot.get("games") or []:
        same = (event_id and str(g.get("event_id") or "") == event_id) or (
            not event_id and home and away and str(g.get("home_code") or "").upper() == home
            and str(g.get("away_code") or "").upper() == away)
        if not same:
            continue
        for lane in g.get("gameLens") or []:
            if lane.get("source") == lr.LIVE_RESIM_LENS_SOURCE and lane.get("modelHomeWinProb") is not None:
                return dict(lane)
        return None
    return None
