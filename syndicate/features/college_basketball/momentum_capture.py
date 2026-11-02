"""Live game shape for college basketball chips (lane wncaab-module, Phase 2, 2026-11-02).

NBA / WNBA chips carry a live line ("OKC on a 9–2 run · in bonus") read from the momentum events file
`scripts/poll_basketball_momentum.py` writes inside the live-lens tick. College basketball has no
live-lens tick and 50-100 live games at once, so this is its producer: one daemon thread on the
live-odds-worker that, every `SYNDICATE_COLLEGE_MOMENTUM_INTERVAL_SECONDS` (150 s) and for each league,

- takes the live games from the D1 slate (`ncaab/slate.py`) -- no scoreboard request;
- streams ONE ESPN summary at a time through `build_momentum_payload_streamed`, so the memory peak is
  one summary whatever the slate size;
- overwrites the same `momentum_events_<date>.json` NBA writes, under `<league>_source/`, which the
  chip's `live_detail` reads -- with each game's team fouls in the current bonus window added.

Team fouls are COUNTED FROM THE PLAY-BY-PLAY: ESPN's college `fouls` header block is a placeholder
(measured 2026-11-02 on live games: every women's team read `bonusState=DOUBLE`, every men's team
`NONE`, all with 0 team fouls). The play count reproduced the box score exactly (UCSD 4+4+7 = 15,
WASH 2+3 = 5).

No per-tick append record (NBA's `live_momentum_<date>.jsonl`): at college slate sizes that is tens of
MB a night, and nothing reads it.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from syndicate.features.college_basketball.league import league_for

LEAGUES = ("ncaab", "wncaab")
_DEFAULT_INTERVAL_SECONDS = 150
_MIN_INTERVAL_SECONDS = 60
# A team's fouls in the window that put its OPPONENT in the bonus. Women: two shots from the 5th
# foul of a quarter (no 1-and-1). Men: 1-and-1 from the 7th foul of a half, two shots from the 10th.
# Overtime continues the last regulation period's count (4th quarter / 2nd half).
_BONUS_AT = {"wncaab": ((5, "bonus"),), "ncaab": ((10, "double bonus"), (7, "bonus"))}

_thread_lock = threading.Lock()
_thread: threading.Thread | None = None


def capture_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_COLLEGE_MOMENTUM_CAPTURE") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def capture_interval_seconds() -> int:
    raw = str(os.environ.get("SYNDICATE_COLLEGE_MOMENTUM_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_INTERVAL_SECONDS
    except ValueError:
        value = _DEFAULT_INTERVAL_SECONDS
    return max(_MIN_INTERVAL_SECONDS, value)


def live_event_ids(league: str, date_iso: str) -> list[str]:
    """ESPN event ids of the slate's D1 games in progress."""
    from syndicate.features.ncaab.slate import read_slate

    out = []
    for game in (read_slate(date_iso, league) or {}).get("games") or []:
        live = game.get("live_state") if isinstance(game.get("live_state"), Mapping) else {}
        if live.get("in_progress") and not live.get("final") and game.get("event_id"):
            out.append(str(game["event_id"]))
    return out


def _window_periods(league: str, period: int) -> range:
    """Periods whose fouls count toward the bonus now: the current quarter / half, OT extending the last."""
    regulation = league_for(league).periods
    return range(regulation, period + 1) if period >= regulation else range(period, period + 1)


def team_fouls(summary: Mapping[str, Any], league: str) -> dict[str, Any] | None:
    """{"period", "away": {"abbr", "fouls"}, "home": {...}} for the current bonus window, or None."""
    comp = (((summary.get("header") or {}).get("competitions")) or [{}])[0]
    status = comp.get("status") or {}
    try:
        period = int(status.get("period") or 0)
    except (TypeError, ValueError):
        period = 0
    # Between periods the count is about to reset (halftime for the men; every quarter break for the
    # women), so no bonus is stated. Measured 2026-11-02: UTEP @ NKU at HALF read 9-9 first-half fouls.
    on_break = str((status.get("type") or {}).get("name") or "") in {"STATUS_HALFTIME", "STATUS_END_PERIOD"}
    sides: dict[str, dict[str, Any]] = {}
    by_team: dict[str, str] = {}
    for competitor in comp.get("competitors") or []:
        side = str(competitor.get("homeAway") or "")
        team = competitor.get("team") or {}
        if side in ("away", "home") and team.get("id") is not None:
            sides[side] = {"abbr": team.get("abbreviation"), "fouls": 0}
            by_team[str(team["id"])] = side
    if period <= 0 or len(sides) != 2:
        return None
    window = _window_periods(league, period)
    for play in summary.get("plays") or []:
        if "foul" not in str((play.get("type") or {}).get("text") or "").lower():
            continue
        try:
            play_period = int((play.get("period") or {}).get("number") or 0)
        except (TypeError, ValueError):
            continue
        side = by_team.get(str((play.get("team") or {}).get("id") or ""))
        if side and play_period in window:
            sides[side]["fouls"] += 1
    return {"period": period, "on_break": on_break, **sides}


def bonus_text(fouls: Mapping[str, Any] | None, league: str) -> str | None:
    """"UCSD in bonus" / "both in bonus" / "UTEP in double bonus · NKU in bonus", or None."""
    if not fouls or fouls.get("on_break"):
        return None

    def level(opponent: str) -> str | None:
        count = int((fouls.get(opponent) or {}).get("fouls") or 0)
        return next((name for threshold, name in _BONUS_AT.get(league, ()) if count >= threshold), None)

    away, home = level("home"), level("away")
    if away and away == home:
        return f"both in {away}"
    parts = [f"{(fouls.get(side) or {}).get('abbr')} in {lvl}" for side, lvl in (("away", away), ("home", home)) if lvl]
    return " · ".join(parts) or None


def capture_once(
    league: str,
    date_iso: str,
    *,
    fetch_summary: Callable[[str], Mapping[str, Any] | None] | None = None,
    out_root: Path | None = None,
    event_ids: list[str] | None = None,
) -> dict[str, Any]:
    """One pass for one league: build every live game's block, write the events file. Never raises."""
    from syndicate.features.shared.basketball_momentum_artifacts import (
        build_momentum_payload_streamed,
        momentum_events_path,
        write_momentum_events,
    )

    started = time.monotonic()
    ids = live_event_ids(league, date_iso) if event_ids is None else list(event_ids)
    if not ids:
        return {"league": league, "live": 0, "written": False}
    if fetch_summary is None:
        from scripts.poll_basketball_momentum import fetch_summary as _espn_summary

        fetch_summary = lambda event_id: _espn_summary(league, event_id)  # noqa: E731
    extra: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    def _fetch(event_id: str) -> Mapping[str, Any] | None:
        summary = fetch_summary(event_id)
        if isinstance(summary, Mapping):
            fouls = team_fouls(summary, league)
            extra[event_id] = {"fouls": fouls, "bonus": bonus_text(fouls, league)}
        return summary

    payload = build_momentum_payload_streamed(
        ids, _fetch, league_code=league, date_str=date_iso, on_missing=missing.append, include_rows=True,
    )
    result = {"league": league, "live": len(ids), "fetched": payload.get("count"), "with_series": payload.get("with_series"),
              "missing": len(missing), "written": False}
    if payload.get("with_series"):
        if out_root is None:
            from syndicate.features.shared.refresh_state_store import data_root

            out_root = data_root()
        path = momentum_events_path(Path(out_root), league_code=league, date_str=date_iso)
        result["rows"] = write_momentum_events(payload, path=path, extra_by_event=extra)
        result["written"] = True
    result["ms"] = int((time.monotonic() - started) * 1000)
    print(f"[college_momentum] CAPTURED league={league} date={date_iso} live={result['live']} fetched={result['fetched']} "
          f"with_series={result['with_series']} missing={result['missing']} written={result['written']} "
          f"rows={result.get('rows', 0)} bonus_games={sum(1 for v in extra.values() if v.get('bonus'))} ms={result['ms']}", flush=True)
    return result


def _loop() -> None:
    from syndicate.features.shared.timezone import central_today_iso

    while True:
        if capture_enabled():
            for league in LEAGUES:
                try:
                    capture_once(league, central_today_iso())
                except Exception as exc:  # noqa: BLE001 -- capture must never take the worker down
                    print(f"[college_momentum] CAPTURE_FAILED league={league} {type(exc).__name__}: {exc}", flush=True)
        time.sleep(capture_interval_seconds())


def ensure_capture_thread() -> bool:
    """Start the capture thread once per process. Returns True when this call started it."""
    global _thread
    if not capture_enabled():
        return False
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return False
        _thread = threading.Thread(target=_loop, name="college-momentum-capture", daemon=True)
        _thread.start()
    print(f"[college_momentum] THREAD_STARTED interval_s={capture_interval_seconds()} leagues={','.join(LEAGUES)}", flush=True)
    return True
