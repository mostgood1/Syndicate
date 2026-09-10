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

TWO PASSES, because fixing this service's copy does not fix web's.

1. LOCAL. For yesterday and a bounded look-back, rows whose status is not final
   are checked against ONE StatsAPI schedule call per date. A game StatsAPI
   calls final gets its status written into its row, the report's `counts` are
   recounted, a `finalPass` entry records what changed and from where, and the
   file is replaced atomically. No other field is touched and no report is
   rebuilt.

2. WEB. The first version stopped at 1 and said the publish sweep would carry
   the rewrite to web the same cycle. IT DOES NOT, measured 2026-09-10 after
   live-odds-worker `e4410f37`: the pass finalized 6 rows here at 22:19:54Z and
   web went on serving all 9 games `Live`. Two reasons:
   - the sweep refuses any artifact dated more than a day old
     (`artifact_publisher._PUBLISH_MAX_AGE_DAYS`, "never exempted"), and every
     sweep logged `stale_slate=[..09_03, 09_01, 09_06..]`;
   - web reads the report through `sources._resolve_data_path_with_reconcile`,
     which copies the slim `mlb_source/data/` form over the served
     `source_artifacts` target whenever the slim one is NEWER. 09-09's full
     final copy (8,736,835 B) was accepted at 22:25:39.302Z and the slim copy
     (132,548 B, 823900 `Live`) 175 ms later; the next read served the slim one.
   So this pass reads WEB'S OWN copy of whichever form web serves, finalizes its
   stale rows the same way, and publishes it back directly. Web's own copy, not
   this service's: web's 09-04/09-05 targets are the FULL reports (2.28/1.59 MB)
   and the cards merge copies `actual_box_panel`, `gameLens`, `market_tiles` and
   `predictions` from them, so publishing a slimmer local copy would strip
   past-date cards. Only the SERVED form is written, so the reconcile has
   nothing newer to copy over it.

CHEAP BY CONSTRUCTION. Throttled. Locally, a date is skipped while its file is
UNCHANGED since this pass last saw it all-final -- keyed on mtime rather than
remembered as "done", because a second writer (`scripts/refresh_mlb_oddsapi.py`)
also writes these files and could re-freeze one. On web, a date whose served
copy was seen all-final is skipped until one of THIS service's two local forms
changes, which is how this service's own sweep could publish over web's copy
again. The served form is found with a headers-only request (`?since=` far in
the future answers 304 with `X-Artifact-Mtime`), so one body is downloaded per
date, and the web pass stops at a time budget and resumes on the next pass.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from syndicate.features.mlb.game_state import mlb_status_is_final, mlb_status_is_live
from syndicate.features.mlb.sources import live_lens_report_path, load_json_file

STATSAPI_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
DEFAULT_LOOKBACK_DAYS = 10
DEFAULT_MIN_INTERVAL_SECONDS = 600.0
DEFAULT_WEB_BUDGET_SECONDS = 60.0
# Web's largest measured copy is 8.7 MB (09-09's full target). Anything past
# this is not a live-lens report this pass should be parsing on a 2 GB worker.
WEB_MAX_BYTES = 24 * 1024 * 1024
# `since=` later than any real mtime, so the stream endpoint answers 304 with
# the headers and no body.
_WEB_PROBE_SINCE = 4102444800.0  # 2100-01-01

# One date's two published forms, relative to the data root. The TARGET is what
# web's `live_lens_report_path` returns; the SLIM form is the reconcile
# candidate that gets copied over it whenever it is newer.
WEB_TARGET_FORM = "mlb_source/source_artifacts/data/live_lens/{name}"
WEB_SLIM_FORM = "mlb_source/data/live_lens/{name}"

_LOCAL_NOTE = (
    "status only -- the live-lens loop writes today's report only, so this date's rows froze at the "
    "midnight-Central roll"
)

_LAST_RUN_EPOCH = 0.0
# date -> the report's st_mtime_ns when this pass last saw every row final.
_VERIFIED_FINAL: dict[str, int] = {}
# date -> this service's (slim, target) local mtimes when web's SERVED copy was
# last seen all-final.
_WEB_VERIFIED_FINAL: dict[str, tuple[int, int]] = {}


@dataclass(frozen=True)
class WebCopy:
    """One of web's copies. `state` is ok / absent / failed / too_large."""

    state: str
    mtime: float | None = None
    size: int | None = None
    text: str = ""


def final_pass_enabled() -> bool:
    """ON unless explicitly switched off: a correctness fix gated OFF is inert."""
    raw = str(os.environ.get("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def web_pass_enabled() -> bool:
    """The web half alone. ON unless explicitly switched off, like the pass."""
    raw = str(os.environ.get("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS_WEB") or "").strip().lower()
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


def _open_rows(report: Any) -> list[dict[str, Any]] | None:
    """The rows not yet final; None when there is no report to judge."""
    games = report.get("games") if isinstance(report, dict) else None
    if not isinstance(games, list) or not games:
        return None
    return [row for row in games if isinstance(row, dict) and not mlb_status_is_final(*_row_status(row))]


def _finalize_open_rows(
    open_rows: list[dict[str, Any]], statuses: dict[int, dict[str, str]]
) -> list[dict[str, Any]]:
    """Write StatsAPI's final status into each open row it calls final. Status only."""
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
    return finalized


def _stamp_final_pass(report: dict[str, Any], finalized: list[dict[str, Any]], note: str) -> None:
    _recount(report)
    history = report.get("finalPass")
    history = list(history) if isinstance(history, list) else ([history] if isinstance(history, dict) else [])
    history.append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "statsapi schedule",
        "finalized": finalized,
        "note": note,
    })
    report["finalPass"] = history


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


# --- web ---------------------------------------------------------------------


def _web_configured() -> bool:
    from syndicate.features.shared import artifact_publisher

    return bool(artifact_publisher._publish_url() and artifact_publisher._admin_token())


def _web_get(relative_path: str, *, since: float | None, timeout: float):
    from syndicate.features.shared import artifact_publisher

    url = artifact_publisher._stream_url(relative_path, since_epoch=since)
    token = artifact_publisher._admin_token()
    if not url or not token:
        return None
    request = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {token}"})
    return urllib.request.urlopen(request, timeout=timeout)


def _float_header(headers: Any, name: str) -> float | None:
    try:
        raw = headers.get(name) if headers is not None else None
        return float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def probe_web_copy(relative_path: str, *, timeout: float = 30.0) -> WebCopy:
    """Web's mtime and size for one copy, WITHOUT its body (a 304 carries both headers)."""
    try:
        response = _web_get(relative_path, since=_WEB_PROBE_SINCE, timeout=timeout)
        if response is None:
            return WebCopy("failed")
        with response:
            headers = response.headers  # a 200 means since= was ignored; the body is left unread
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return WebCopy("absent")
        if exc.code != 304:
            return WebCopy("failed")
        headers = exc.headers
    except Exception:
        return WebCopy("failed")
    size = _float_header(headers, "X-Artifact-Size")
    return WebCopy("ok", mtime=_float_header(headers, "X-Artifact-Mtime"), size=int(size) if size is not None else None)


def read_web_copy(relative_path: str, *, timeout: float = 60.0) -> WebCopy:
    """One of web's copies, whole. Streamed from web's disk, so web never holds it in memory."""
    try:
        response = _web_get(relative_path, since=None, timeout=timeout)
        if response is None:
            return WebCopy("failed")
        with response:
            mtime = _float_header(response.headers, "X-Artifact-Mtime")
            body = response.read(WEB_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return WebCopy("absent" if exc.code == 404 else "failed")
    except Exception:
        return WebCopy("failed")
    if len(body) > WEB_MAX_BYTES:
        return WebCopy("too_large", mtime=mtime)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return WebCopy("failed", mtime=mtime)
    return WebCopy("ok", mtime=mtime, size=len(body), text=text)


def publish_web_copy(relative_path: str, text: str, *, timeout: int = 60) -> bool:
    """Publish `text` AS `relative_path`, from a temp file, so this service's own copy is untouched.

    `_publish_streamed` rather than `publish_hot_artifact`: the latter publishes
    the file AT the relative path, which here would mean first overwriting this
    service's copy with web's.
    """
    from syndicate.features.shared import artifact_publisher

    url, token = artifact_publisher._publish_url(), artifact_publisher._admin_token()
    if not url or not token:
        return False
    handle, temp_name = tempfile.mkstemp(prefix="mlb_final_pass_", suffix=".json")
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        outcome = artifact_publisher._publish_streamed(
            temp, relative_path=relative_path, url=url, token=token, timeout_seconds=timeout
        )
        return outcome is True
    except Exception:
        return False
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def _local_form_mtime_ns(relative_path: str) -> int:
    from syndicate.features.shared.refresh_state_store import data_root

    try:
        return (data_root() / relative_path).stat().st_mtime_ns
    except OSError:
        return -1


def _dumps_like(original: str, payload: dict[str, Any]) -> str:
    """Keep web's layout: an indented copy stays indented, a compact one compact."""
    return json.dumps(payload, indent=2) if "\n" in original[:64] else json.dumps(payload)


def _finalize_web_copies(
    today: date,
    days: int,
    statuses_for: Callable[[str], dict[int, dict[str, str]] | None],
    *,
    deadline: float,
    clock: Callable[[], float],
) -> dict[str, Any]:
    web: dict[str, Any] = {
        "ran": True,
        "dates_checked": 0,
        "skipped_verified": 0,
        "served_slim": 0,
        "absent": 0,
        "read_failed": 0,
        "too_large": 0,
        "open_rows": 0,
        "finalized": 0,
        "still_open": 0,
        "published": 0,
        "publish_failed": 0,
        "fetch_failed": 0,
        "deferred": 0,
        "finalized_games": [],
    }
    for offset in range(1, days + 1):
        date_str = (today - timedelta(days=offset)).isoformat()
        name = f"live_lens_report_{date_str.replace('-', '_')}.json"
        slim_rel, target_rel = WEB_SLIM_FORM.format(name=name), WEB_TARGET_FORM.format(name=name)
        local_key = (_local_form_mtime_ns(slim_rel), _local_form_mtime_ns(target_rel))
        if _WEB_VERIFIED_FINAL.get(date_str) == local_key:
            web["skipped_verified"] += 1
            continue
        if clock() >= deadline:
            web["deferred"] += 1
            continue
        target = probe_web_copy(target_rel)
        slim = probe_web_copy(slim_rel)
        if "failed" in (target.state, slim.state):
            web["read_failed"] += 1
            continue
        if target.state == "absent" and slim.state == "absent":
            web["absent"] += 1
            _WEB_VERIFIED_FINAL[date_str] = local_key
            continue
        # Web's reconcile rule, restated: the slim form is copied over the
        # target when the target is missing or empty, or when it is NEWER.
        served_slim = slim.state == "ok" and (
            target.state != "ok" or not target.size or (slim.mtime or 0.0) > (target.mtime or 0.0)
        )
        served_rel = slim_rel if served_slim else target_rel
        served = read_web_copy(served_rel)
        if served.state == "too_large":
            web["too_large"] += 1
            continue
        if served.state != "ok":
            web["read_failed"] += 1
            continue
        try:
            report = json.loads(served.text)
        except ValueError:
            web["read_failed"] += 1
            continue
        web["dates_checked"] += 1
        web["served_slim"] += int(served_slim)
        open_rows = _open_rows(report)
        if not open_rows:
            _WEB_VERIFIED_FINAL[date_str] = local_key
            continue
        web["open_rows"] += len(open_rows)
        statuses = statuses_for(date_str)
        if statuses is None:
            web["fetch_failed"] += 1
            continue
        finalized = _finalize_open_rows(open_rows, statuses)
        still_open = len(open_rows) - len(finalized)
        web["still_open"] += still_open
        if not finalized:
            continue
        _stamp_final_pass(
            report,
            finalized,
            note=f"status only, applied to web's own {served_rel} -- the form web serves; {_LOCAL_NOTE}",
        )
        if not publish_web_copy(served_rel, _dumps_like(served.text, report)):
            web["publish_failed"] += 1
            continue
        web["published"] += 1
        web["finalized"] += len(finalized)
        web["finalized_games"].extend(f"{date_str}:{item['gamePk']}" for item in finalized)
        if still_open == 0:
            _WEB_VERIFIED_FINAL[date_str] = local_key
    return web


def finalize_recent_mlb_live_lens_reports(
    today_iso: str,
    *,
    now_epoch: float | None = None,
    fetch: Callable[[str], dict[int, dict[str, str]] | None] | None = None,
    lookback_days: int | None = None,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    web_budget_seconds: float = DEFAULT_WEB_BUDGET_SECONDS,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Finalize stale rows in the reports of the `lookback_days` dates before `today_iso`, here and on web."""
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
    # One StatsAPI call per date per pass, shared by both halves.
    fetched: dict[str, dict[int, dict[str, str]] | None] = {}

    def statuses_for(date_str: str) -> dict[int, dict[str, str]] | None:
        if date_str not in fetched:
            fetched[date_str] = fetch(date_str)
        return fetched[date_str]

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
        open_rows = _open_rows(report)
        if open_rows is None:
            stats["dates_without_report"] += 1
            continue
        stats["dates_checked"] += 1
        if not open_rows:
            _VERIFIED_FINAL[date_str] = mtime_ns
            continue
        stats["open_rows"] += len(open_rows)
        statuses = statuses_for(date_str)
        if statuses is None:
            stats["fetch_failed"] += 1
            continue

        finalized = _finalize_open_rows(open_rows, statuses)
        still_open = len(open_rows) - len(finalized)
        stats["still_open"] += still_open
        if not finalized:
            continue

        _stamp_final_pass(report, finalized, note=_LOCAL_NOTE)
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

    if not web_pass_enabled():
        web: dict[str, Any] = {"ran": False, "reason": "disabled"}
    elif not _web_configured():
        web = {"ran": False, "reason": "not_configured"}
    else:
        tick = clock or time.monotonic
        try:
            web = _finalize_web_copies(today, days, statuses_for, deadline=tick() + web_budget_seconds, clock=tick)
        except Exception as exc:
            web = {"ran": False, "reason": f"error:{type(exc).__name__}: {exc}"}
    stats["web"] = web
    if web.get("ran"):
        print(
            f"[live_lens_final_pass] MLB_LIVE_LENS_FINAL_PASS_WEB today={today_iso} lookback={days} "
            f"dates_checked={web['dates_checked']} skipped_verified={web['skipped_verified']} "
            f"served_slim={web['served_slim']} absent={web['absent']} read_failed={web['read_failed']} "
            f"too_large={web['too_large']} open_rows={web['open_rows']} finalized={web['finalized']} "
            f"still_open={web['still_open']} published={web['published']} "
            f"publish_failed={web['publish_failed']} fetch_failed={web['fetch_failed']} "
            f"deferred={web['deferred']} games={web['finalized_games']}",
            flush=True,
        )
    else:
        # Said out loud: a web half that is off and one with nothing to do must not look alike.
        print(f"[live_lens_final_pass] MLB_LIVE_LENS_FINAL_PASS_WEB ran=False reason={web.get('reason')}", flush=True)
    return stats


def _reset_state_for_tests() -> None:
    global _LAST_RUN_EPOCH
    _LAST_RUN_EPOCH = 0.0
    _VERIFIED_FINAL.clear()
    _WEB_VERIFIED_FINAL.clear()
