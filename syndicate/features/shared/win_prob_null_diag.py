"""The `win_prob` null-counter, on a channel that can actually be read.

WHY THIS MODULE EXISTS -- the counter it replaces was unobservable by
construction, and that was measured, not suspected.

A fix removed 15 `... or 0.5` substitutions from the two prop producers, so a
price-missing prop row publishes `win_prob=None` instead of a fabricated
coin-flip. The fix is silent by design, so a counter was added to both
producers and deployed (refresh-worker `903d09c5`, live-odds-worker
`b7ae47e6`, 2026-08-15). It printed:

    [refresh_wnba_oddsapi_props] WIN_PROB_NULL_NO_PRICE null=<n> rows=<n> pct=<n>

**That line can never reach Render's logs on a successful run.** Measured
2026-08-15/16: the WNBA producer DID run after the deploy carrying the counter
-- live-odds-worker's `ALL_PROCESS_MEMORY` census at 23:36:05Z lists PID 1900,
`scripts/refresh_wnba_oddsapi_props.py --date 2026-08-15 --do-edges
--do-export`, started 23:36:04Z, ppid 1880 (`refresh_odds_sources.py`) -- and a
bounded log read over the whole window since the deploy returned ZERO matches
on both workers. `refresh_odds_sources._run_command` launches every producer
under `subprocess.run(capture_output=True)`, and a SUCCESSFUL step's captured
stdout is discarded entirely (only a bounded stderr tail survives, and only for
a FAILED step). `ops.py:2263` documented that exact trap on 2026-08-01, for
this exact script; the counter was added into it anyway.

The reading that absence invites -- "the producer has not run yet" -- is the
wrong one, and it is the repo's own recurring shape: **an absent signal is a
fact about the emitter until the emitter is shown to be capable of speaking.**
A scheduled task built to watch that log line would have returned silence
forever and called it a pending result.

WHY A KEYVALUE WRITE IS THE RIGHT CHANNEL, and not a guess.
`refresh_state_store._keyvalue_backed` routes every path except
`migration_runs/` through the shared keyvalue store when the backend is
`keyvalue`. Verified 2026-08-15 by reading the live env of all three services,
not by assuming:

    SYNDICATE_REPORTS_ROOT          = /opt/render/project/data/reports  (all 3)
    SYNDICATE_REFRESH_STATE_BACKEND = keyvalue                          (all 3)
    SYNDICATE_REFRESH_LANE          = web / refresh-worker / live-odds-worker

So `reports_root()` builds a byte-identical key string on the worker that
writes and the web service that reads -- which is the whole requirement, since
`_state_key_for_path` keys off the normalized path text. This is the same
mechanism `disk_maintenance._status_path` and the live-lens tick already use to
cross the service boundary.

PER-SERVICE KEYS, deliberately. `disk_maintenance._status_path`'s docstring
records what one shared key cost: both workers point at the SAME Redis, so a
single key made a per-service fact into a race, and the loser's state was
silently overwritten by the winner's. Here a shared key would let whichever
worker ran last erase the other's reading. Each service writes only its own
key, so there is no write race at all and a per-service `rows=0` stays
distinguishable from "some other service reported rows".
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.refresh_state_store import read_json_file_result
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file

# The sports whose producers carry the counter. Both had the `or 0.5`
# substitutions removed, so both must be able to report; NBA reporting
# `rows=0` while out of season is a CORRECT reading, not a failure.
KNOWN_SPORTS: tuple[str, ...] = ("wnba", "nba")

# Read from the live env of all three services 2026-08-15 (SYNDICATE_REFRESH_LANE),
# not guessed. The reader probes these; the index below covers anything added
# later, so a new lane value degrades to "found via index", never to silence.
KNOWN_SERVICES: tuple[str, ...] = ("live-odds-worker", "refresh-worker", "web", "local")

# How many prior runs each service keeps. A single latest reading cannot
# distinguish "ran once, computed nothing" from "ran nine times, computed
# nothing every time" -- and those justify different next steps.
_RECENT_LIMIT = 10


def service_slug() -> str:
    """Which service is writing. Mirrors `disk_maintenance._service_slug`."""
    for name in ("SYNDICATE_REFRESH_LANE", "RENDER_SERVICE_NAME", "RENDER_SERVICE_ID"):
        value = str(os.environ.get(name) or "").strip().lower()
        if value:
            return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)
    return "local"


def diag_path(sport: str, service: str | None = None) -> Path:
    """The one place the key is constructed, for writer and reader alike.

    Same argument `_keyvalue_backed` makes for routing reads and writes through
    one predicate: if the producer and the route each built this path
    themselves, a divergence would read as "the artifact never appeared" rather
    than as a bug -- which is precisely the failure this module was written to
    end.

    A dedicated directory rather than `refresh_status/latest/`: nothing globs
    or lane-indexes this prefix, so these keys cannot be mistaken for refresh
    manifests by a lister that expects that shape.
    """
    sport_slug = str(sport or "").strip().lower() or "unknown"
    service_part = str(service or service_slug()).strip().lower() or "unknown"
    return reports_root() / "win_prob_null" / f"{sport_slug}_{service_part}.json"


def _index_path() -> Path:
    return reports_root() / "win_prob_null" / "_index.json"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _commit() -> str | None:
    for name in ("RENDER_GIT_COMMIT", "SYNDICATE_GIT_COMMIT"):
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def build_reading(
    *,
    sport: str,
    tag: str,
    rows: int,
    nulls: int,
    date: str | None = None,
    service: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A rate, never a bare count.

    `null=0` means "the fix held" when rows is large and "nothing ran" when rows
    is 0, and those need opposite responses -- so the denominator travels with
    the numerator and `exercised` states the distinction outright instead of
    leaving it to whoever reads the number next.
    """
    rows_value = max(0, int(rows or 0))
    nulls_value = max(0, int(nulls or 0))
    reading: dict[str, Any] = {
        "sport": str(sport or "").strip().lower(),
        "tag": str(tag or "").strip(),
        "service": str(service or service_slug()),
        "rows": rows_value,
        "null_no_price": nulls_value,
        "pct": round((100.0 * nulls_value / rows_value), 4) if rows_value else 0.0,
        # The whole point of the counter: was the branch ever reached at all?
        "exercised": rows_value > 0,
        "date": str(date or "").strip() or None,
        "generated_at": _now_iso(),
        "pid": os.getpid(),
        "commit": _commit(),
    }
    if isinstance(extra, Mapping):
        for key, value in extra.items():
            if key not in reading:
                reading[key] = value
    return reading


def record(
    *,
    sport: str,
    tag: str,
    rows: int,
    nulls: int,
    date: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Publish one run's reading. Returns the payload written, or None.

    NEVER raises. This is called from the producers' `finally` block, where an
    exception would replace a real exit code with a diagnostic's failure -- an
    instrument that can break the thing it measures is worse than no instrument.
    """
    try:
        service = service_slug()
        reading = build_reading(sport=sport, tag=tag, rows=rows, nulls=nulls, date=date, service=service, extra=extra)
        path = diag_path(reading["sport"], service)

        previous, _ok = read_json_file_result(path)
        recent: list[dict[str, Any]] = []
        if isinstance(previous, dict):
            prior_recent = previous.get("recent")
            if isinstance(prior_recent, list):
                recent = [item for item in prior_recent if isinstance(item, dict)]
            prior_latest = previous.get("latest")
            if isinstance(prior_latest, dict):
                recent.insert(0, prior_latest)

        payload = {
            "latest": reading,
            # Only one service ever writes this key and its runs are sequential
            # (one subprocess per refresh step), so this read-modify-write has
            # no competing writer to race.
            "recent": recent[: _RECENT_LIMIT - 1],
            "runs_recorded": int((previous or {}).get("runs_recorded") or 0) + 1 if isinstance(previous, dict) else 1,
            "updated_at": reading["generated_at"],
        }
        write_json_file(path, payload)
        _record_index_entry(reading["sport"], service)
        return payload
    except Exception:
        return None


def _record_index_entry(sport: str, service: str) -> None:
    """Best-effort registry of which (sport, service) keys exist.

    The reader already probes `KNOWN_SPORTS x KNOWN_SERVICES`, so this is not
    load-bearing today -- it exists so a service slug nobody predicted still
    shows up instead of being invisible. A lost entry (two services rewriting
    the index at once) is self-healing: the next run of either writes it back.
    """
    try:
        path = _index_path()
        existing, _ok = read_json_file_result(path)
        entries: list[dict[str, str]] = []
        if isinstance(existing, dict) and isinstance(existing.get("entries"), list):
            entries = [item for item in existing["entries"] if isinstance(item, dict)]
        if not any(item.get("sport") == sport and item.get("service") == service for item in entries):
            entries.append({"sport": sport, "service": service})
        write_json_file(path, {"entries": entries[:64], "updated_at": _now_iso()})
    except Exception:
        return


def read_all(
    *,
    sports: Iterable[str] | None = None,
    services: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Every reading this store holds, plus what was probed to find them.

    `probed` is not decoration. A healthy-looking empty result is evidence only
    once you can see what was looked for: without it, "no readings" and "looked
    in the wrong place" render identically, which is the same instrument
    blindness that made the log-line version unreadable.

    `read_failed` separates a confirmed-absent key from a backend hiccup --
    `read_json_file` collapses both into None, and treating a transient failure
    as "the producer never ran" would repeat the original mistake one layer up.
    """
    targets: list[tuple[str, str]] = []
    for sport in [str(item).strip().lower() for item in (sports or KNOWN_SPORTS)]:
        for service in [str(item).strip().lower() for item in (services or KNOWN_SERVICES)]:
            if sport and service and (sport, service) not in targets:
                targets.append((sport, service))

    index_entries: list[dict[str, Any]] = []
    index_payload, index_ok = read_json_file_result(_index_path())
    if isinstance(index_payload, dict) and isinstance(index_payload.get("entries"), list):
        for item in index_payload["entries"]:
            if not isinstance(item, dict):
                continue
            sport = str(item.get("sport") or "").strip().lower()
            service = str(item.get("service") or "").strip().lower()
            if sport and service:
                index_entries.append({"sport": sport, "service": service})
                if (sport, service) not in targets:
                    targets.append((sport, service))

    probed: list[dict[str, Any]] = []
    readings: list[dict[str, Any]] = []
    for sport, service in targets:
        path = diag_path(sport, service)
        payload, ok = read_json_file_result(path)
        present = isinstance(payload, dict) and isinstance(payload.get("latest"), dict)
        probed.append(
            {
                "sport": sport,
                "service": service,
                "key_path": str(path).replace("\\", "/"),
                "present": bool(present),
                "read_failed": not ok,
            }
        )
        if present:
            entry = dict(payload)
            entry["sport"] = sport
            entry["service"] = service
            readings.append(entry)

    exercised = [item for item in readings if bool((item.get("latest") or {}).get("exercised"))]
    return {
        "ok": True,
        "readings": readings,
        "probed": probed,
        "index": {"ok": bool(index_ok), "entries": index_entries},
        "reports_root": str(reports_root()).replace("\\", "/"),
        # The headline, stated so a reader cannot mistake "no run" for "no nulls".
        "any_exercised": bool(exercised),
        "summary": _summarize(readings),
        "generated_at": _now_iso(),
    }


def _summarize(readings: list[dict[str, Any]]) -> dict[str, Any]:
    total_rows = 0
    total_nulls = 0
    for item in readings:
        latest = item.get("latest") if isinstance(item.get("latest"), dict) else {}
        try:
            total_rows += int(latest.get("rows") or 0)
            total_nulls += int(latest.get("null_no_price") or 0)
        except (TypeError, ValueError):
            continue
    return {
        "services_reporting": len(readings),
        "rows": total_rows,
        "null_no_price": total_nulls,
        "pct": round((100.0 * total_nulls / total_rows), 4) if total_rows else 0.0,
        # Reading guide, carried with the data rather than left in a doc:
        #   rows=0            -> the producer ran and computed no win_prob. Says
        #                        nothing about the fix.
        #   rows>0, null=0    -> the fix is holding AND has been exercised.
        #   null>0            -> the branch fired: that many rows had no price and
        #                        published None instead of a fabricated 0.5. That
        #                        is the fix WORKING.
        "interpretation": (
            "no producer has reported yet"
            if not readings
            else (
                "producers reported but computed no win_prob (says nothing about the fix)"
                if total_rows == 0
                else (
                    f"fix exercised on {total_rows} win_prob rows, {total_nulls} published None instead of 0.5"
                    if total_nulls
                    else f"fix holding on {total_rows} win_prob rows, no price-missing rows this run"
                )
            )
        ),
    }
