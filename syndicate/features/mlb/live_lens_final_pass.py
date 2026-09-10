"""Give PAST MLB live-lens reports a final pass after the midnight-Central roll.

WHY. `live_lens_loop` writes only TODAY's report (`central_today_iso()`), so a
game still in progress when the date rolls at midnight Central keeps a mid-game
row in YESTERDAY's report for good. On web that report is a past date's ONLY
status source -- web holds no `feed_live` files for September
(`/api/ops/artifacts/export?names_only=1` `count=0`; the June control reads 78)
-- so `_merge_live_lens_row_into_game` serves the game `Live` indefinitely.

Measured 2026-09-10 (lane `mlb-final-state-mapping`): web's
`live_lens_report_2026_09_03.json`, last written 23:59:10 CT, holds 823095 and
823907 at `Live / In Progress`, though both ended 00:05/00:09 CT. The served
cards payload and the board chips still carried them `live` six days later:
9 games on 7 of the 9 dates 09-01..09-09.

WHAT IT DOES, AND DELIBERATELY NOTHING MORE. Past-date reports are SLIM -- a
row is `gamePk`, `startTime`, `status`, and a frozen one adds `props` /
`liveProps` -- so `status` is the only stale field. For yesterday and a bounded
look-back, rows whose status is not final are checked against ONE StatsAPI
schedule call per date. A game StatsAPI calls final gets its status written
into its row, the report's `counts` are recounted, a `finalPass` entry records
what changed and from where, and the file is replaced atomically.
`live_lens_loop`'s own publish sweep runs right after the tick, so the rewrite
reaches web the same cycle. No other field is touched and no report is rebuilt.

CHEAP BY CONSTRUCTION. Throttled, and a date is skipped while its file is
UNCHANGED since this pass last saw it all-final. That gate is keyed on the
file's mtime rather than remembered as "done", because a second writer
(`scripts/refresh_mlb_oddsapi.py`) also writes these files and could re-freeze
one; a changed file is simply read again.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from syndicate.features.mlb.game_state import mlb_status_is_final, mlb_status_is_live
from syndicate.features.mlb.sources import live_lens_report_path, load_json_file

STATSAPI_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
DEFAULT_LOOKBACK_DAYS = 10
DEFAULT_MIN_INTERVAL_SECONDS = 600.0

_LAST_RUN_EPOCH = 0.0
# date -> the report's st_mtime_ns when this pass last saw every row final.
_VERIFIED_FINAL: dict[str, int] = {}


def final_pass_enabled() -> bool:
    """ON unless explicitly switched off: a correctness fix gated OFF is inert."""
    raw = str(os.environ.get("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def final_pass_lookback_days() -> int:
    raw = str(os.environ.get("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS_LOOKBACK_DAYS") or "").strip()
    try:
        return max(1, min(30, int(raw))) if raw else DEFAULT_LOOKBACK_DAYS
    except ValueError:
        return DEFAULT_LOOKBACK_DAYS


def fetch_schedule_statuses(date_str: str, *, timeout: float = 15.0) -> dict[int, dict[str, str]] | None:
    """`{gamePk: {"abstract", "detailed"}}` for one date; None when StatsAPI could not be read.

    `fields=` keeps the response to the two strings the pass reads, so a slate
    costs a few KB rather than the full schedule document.
    """
    url = (
        f"{STATSAPI_SCHEDULE}?sportId=1&date={date_str}"
        "&fields=dates,games,gamePk,status,abstractGameState,detailedState"
    )
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "syndicate-live-lens-final-pass"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    statuses: dict[int, dict[str, str]] = {}
    for day in payload.get("dates") or []:
        for game in (day or {}).get("games") or []:
            try:
                game_pk = int(game.get("gamePk"))
            except (TypeError, ValueError):
                continue
            status = game.get("status") or {}
            statuses[game_pk] = {
                "abstract": str(status.get("abstractGameState") or ""),
                "detailed": str(status.get("detailedState") or ""),
            }
    return statuses


def _row_status(row: dict[str, Any]) -> tuple[str, str]:
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    return (
        str(status.get("abstract") or status.get("abstractGameState") or ""),
        str(status.get("detailed") or status.get("detailedState") or ""),
    )


def _recount(report: dict[str, Any]) -> None:
    """Recount only the keys the report already carries, from its rows."""
    counts = report.get("counts")
    games = [row for row in report.get("games") or [] if isinstance(row, dict)]
    if not isinstance(counts, dict):
        return
    final = sum(1 for row in games if mlb_status_is_final(*_row_status(row)))
    live = sum(1 for row in games if mlb_status_is_live(*_row_status(row)))
    if "final" in counts:
        counts["final"] = final
    if "live" in counts:
        counts["live"] = live
    if "pregame" in counts:
        counts["pregame"] = len(games) - final - live


def _write_atomically(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name(path.name + ".final_pass.tmp")
    try:
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        # Never leave a .tmp where the next pass, or a sweep glob, could trip on it.
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass


def finalize_recent_mlb_live_lens_reports(
    today_iso: str,
    *,
    now_epoch: float | None = None,
    fetch: Callable[[str], dict[int, dict[str, str]] | None] | None = None,
    lookback_days: int | None = None,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Finalize stale rows in the reports of the `lookback_days` dates before `today_iso`."""
    global _LAST_RUN_EPOCH
    now = time.time() if now_epoch is None else float(now_epoch)
    stats: dict[str, Any] = {
        "ran": False,
        "dates_checked": 0,
        "dates_skipped_verified": 0,
        "dates_without_report": 0,
        "open_rows": 0,
        "finalized": 0,
        "still_open": 0,
        "fetch_failed": 0,
        "write_failed": 0,
        "finalized_games": [],
    }
    if not final_pass_enabled():
        stats["reason"] = "disabled"
        return stats
    if now - _LAST_RUN_EPOCH < min_interval_seconds:
        stats["reason"] = "throttled"
        return stats
    _LAST_RUN_EPOCH = now
    stats["ran"] = True
    fetch = fetch or fetch_schedule_statuses
    days = int(lookback_days) if lookback_days else final_pass_lookback_days()
    today = date.fromisoformat(str(today_iso))

    for offset in range(1, days + 1):
        date_str = (today - timedelta(days=offset)).isoformat()
        path = live_lens_report_path(date_str)
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            stats["dates_without_report"] += 1
            continue
        if _VERIFIED_FINAL.get(date_str) == mtime_ns:
            stats["dates_skipped_verified"] += 1
            continue
        report = load_json_file(path)
        games = report.get("games") if isinstance(report, dict) else None
        if not isinstance(games, list) or not games:
            stats["dates_without_report"] += 1
            continue
        stats["dates_checked"] += 1
        open_rows = [row for row in games if isinstance(row, dict) and not mlb_status_is_final(*_row_status(row))]
        if not open_rows:
            _VERIFIED_FINAL[date_str] = mtime_ns
            continue
        stats["open_rows"] += len(open_rows)
        statuses = fetch(date_str)
        if statuses is None:
            stats["fetch_failed"] += 1
            continue

        finalized: list[dict[str, Any]] = []
        for row in open_rows:
            try:
                game_pk = int(row.get("gamePk"))
            except (TypeError, ValueError):
                continue
            fresh = statuses.get(game_pk)
            if not fresh or not mlb_status_is_final(fresh.get("abstract"), fresh.get("detailed")):
                continue
            old_abstract, old_detailed = _row_status(row)
            status = dict(row["status"]) if isinstance(row.get("status"), dict) else {}
            status["abstract"] = fresh["abstract"]
            status["detailed"] = fresh["detailed"]
            row["status"] = status
            row["finalizedBy"] = "live_lens_final_pass"
            finalized.append({
                "gamePk": game_pk,
                "from": {"abstract": old_abstract, "detailed": old_detailed},
                "to": {"abstract": fresh["abstract"], "detailed": fresh["detailed"]},
            })
        still_open = len(open_rows) - len(finalized)
        stats["still_open"] += still_open
        if not finalized:
            continue

        _recount(report)
        history = report.get("finalPass")
        history = list(history) if isinstance(history, list) else ([history] if isinstance(history, dict) else [])
        history.append({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "statsapi schedule",
            "finalized": finalized,
            "note": "status only -- the live-lens loop writes today's report only, so this date's rows froze at the midnight-Central roll",
        })
        report["finalPass"] = history
        try:
            _write_atomically(path, report)
        except Exception:
            stats["write_failed"] += 1
            continue
        stats["finalized"] += len(finalized)
        stats["finalized_games"].extend(f"{date_str}:{item['gamePk']}" for item in finalized)
        if still_open == 0:
            try:
                _VERIFIED_FINAL[date_str] = path.stat().st_mtime_ns
            except OSError:
                pass

    # print, not logger.info -- logger.info never reaches Render's collector.
    print(
        f"[live_lens_final_pass] MLB_LIVE_LENS_FINAL_PASS today={today_iso} lookback={days} "
        f"dates_checked={stats['dates_checked']} skipped_verified={stats['dates_skipped_verified']} "
        f"no_report={stats['dates_without_report']} open_rows={stats['open_rows']} "
        f"finalized={stats['finalized']} still_open={stats['still_open']} "
        f"fetch_failed={stats['fetch_failed']} write_failed={stats['write_failed']} "
        f"games={stats['finalized_games']}",
        flush=True,
    )
    return stats


def _reset_state_for_tests() -> None:
    global _LAST_RUN_EPOCH
    _LAST_RUN_EPOCH = 0.0
    _VERIFIED_FINAL.clear()
