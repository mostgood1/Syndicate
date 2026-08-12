"""The runner for the two disk jobs. Nothing invoked them before this.

`#396`/`#398` (retention) and `#399` (book_quotes compaction) were both built as
functions with a dry-run default and deliberately left unwired -- "scheduling it
is a separate decision with a memory budget attached". This is that decision.

WHY A RUNNER IS NEEDED AT ALL, rather than an env var. Both jobs must run on the
disk they manage, and Render disks attach to exactly one service, so neither can
run from web or from a cron service -- they have to run in-process on each
worker. There is also no shell access to a Render worker, so there is no
manual-invocation path. Until something calls them, setting
`SYNDICATE_ARTIFACT_RETENTION_ENABLED=true` changes nothing at all: it is read by
code that never executes. That is the specific trap this module removes.

THREE SWITCHES, DELIBERATELY SEPARATE, so the ladder can be climbed one rung at
a time and each rung is observable before the next:

    SYNDICATE_DISK_MAINTENANCE_ENABLED       runs the sweep AT ALL (default off)
    SYNDICATE_BOOK_QUOTES_COMPACTION_ENABLED compaction ACTS (default off, dry run)
    SYNDICATE_ARTIFACT_RETENTION_ENABLED     retention DELETES (default off, dry run)

Turning the first on with the other two off is the useful state and the one to
start in: it produces the production numbers nobody has, on the disks that
actually matter, while deleting nothing. Every number in the reports so far comes
from web's hot-allowlisted subset (6,968 files) or from the local git mirror --
neither is a worker disk, and the rules have never been run against one.

`#241` IS THE PRECEDENT FOR THE COST. Adding periodic work to these workers put
production into a restart loop. So:
  - Once per day, gated on a persisted timestamp, not per tick.
  - Runs AFTER a tick returns, never during one.
  - Skipped entirely when the process is already near its memory ceiling --
    a tidy-up job that OOMs the worker it is tidying for is a worse problem than
    the disk.
  - Compaction before retention, because compaction makes files smaller and
    retention then has less to consider. Neither depends on the other.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_INTERVAL_DEFAULT_SECONDS = 86400

# Skip the sweep when RSS is already above this share of the container limit.
# The sweep is I/O over the whole disk; the page cache it pulls in is charged to
# the container, and on a 2 GiB box with ~1.4 GB of headroom that is the
# difference between a tidy-up and an OOM kill.
_MEMORY_HEADROOM_FRACTION = 0.75


def _flag(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _interval_seconds() -> int:
    raw = str(os.environ.get("SYNDICATE_DISK_MAINTENANCE_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(float(raw or _INTERVAL_DEFAULT_SECONDS))
    except (TypeError, ValueError):
        return _INTERVAL_DEFAULT_SECONDS
    # A zero or negative interval would run this every tick. Treated as unset --
    # an unparseable config must not map onto the most expensive branch.
    return value if value > 0 else _INTERVAL_DEFAULT_SECONDS


def _status_path() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "refresh_status" / "latest" / "disk_maintenance_status.json"


def _due() -> bool:
    from syndicate.features.shared.refresh_state_store import read_json_file

    payload = read_json_file(_status_path()) or {}
    try:
        last = float(payload.get("epoch") or 0.0)
    except (TypeError, ValueError):
        last = 0.0
    # An unreadable or missing status file means "never run", which is due. The
    # permissive direction is safe here precisely because both jobs default to
    # dry run -- the worst case of running too often is wasted I/O, not data loss.
    return last <= 0.0 or (time.time() - last) >= float(_interval_seconds())


def _memory_pressure_blocks() -> tuple[bool, dict[str, Any]]:
    """True when this process is too close to its ceiling to spend a disk sweep."""
    facts: dict[str, Any] = {}
    try:
        import psutil

        rss = int(psutil.Process().memory_info().rss)
    except Exception:
        try:
            with open("/proc/self/status", encoding="utf-8", errors="ignore") as handle:
                rss = 0
                for line in handle:
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1]) * 1024
                        break
        except Exception:
            # Cannot measure -> do NOT block. An unmeasurable guard that refuses
            # would silently disable maintenance forever, and the job it is
            # guarding deletes nothing by default.
            return False, {"rss_unknown": True}
    limit = _container_limit_bytes()
    facts["rss_bytes"] = rss
    facts["limit_bytes"] = limit
    if not limit:
        return False, facts
    blocked = rss > int(limit * _MEMORY_HEADROOM_FRACTION)
    facts["headroom_fraction"] = _MEMORY_HEADROOM_FRACTION
    return blocked, facts


def _container_limit_bytes() -> int:
    for candidate in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = Path(candidate).read_text(encoding="utf-8").strip()
            if raw and raw != "max":
                value = int(raw)
                # cgroup v1 reports an absurd sentinel when unlimited.
                if 0 < value < (1 << 62):
                    return value
        except Exception:
            continue
    return 0


def run_disk_maintenance(*, sports: tuple[str, ...] = ("mlb", "wnba", "nba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")) -> dict[str, Any]:
    """One daily pass: compact closed book_quotes shards, then sweep retention.

    Never raises. Returns a summary dict; also prints it, because `logger.info`
    does not reach Render's log collector from a worker process.
    """
    summary: dict[str, Any] = {"ran": False}
    try:
        if not _flag("SYNDICATE_DISK_MAINTENANCE_ENABLED"):
            return {"ran": False, "reason": "disabled"}
        if not _due():
            return {"ran": False, "reason": "not_due"}

        blocked, memory_facts = _memory_pressure_blocks()
        if blocked:
            print(
                f"[disk_maintenance] SKIPPED_MEMORY_PRESSURE {json.dumps(memory_facts, sort_keys=True)}",
                flush=True,
            )
            return {"ran": False, "reason": "memory_pressure", "memory": memory_facts}

        started = time.time()
        summary = {"ran": True, "memory": memory_facts, "compaction": {}, "retention": {}}

        # --- 1. compaction (lossless; changes representation, not information)
        compaction_applies = _flag("SYNDICATE_BOOK_QUOTES_COMPACTION_ENABLED")
        try:
            from syndicate.features.shared.odds_book_quotes import compress_closed_shards
            from syndicate.features.shared.timezone import central_today_iso

            today = central_today_iso()
            for sport in sports:
                try:
                    result = compress_closed_shards(sport=sport, today=today, apply=compaction_applies)
                except Exception as exc:
                    summary["compaction"][sport] = f"error {type(exc).__name__}: {exc}"
                    continue
                if result.get("compressed") or result.get("skipped"):
                    summary["compaction"][sport] = {
                        "files": len(result.get("compressed") or []),
                        "mb_before": round(int(result.get("bytes_before") or 0) / 1024 / 1024, 1),
                        "mb_after": round(int(result.get("bytes_after") or 0) / 1024 / 1024, 1),
                        "skipped": result.get("skipped"),
                    }
        except Exception as exc:
            summary["compaction"] = f"error {type(exc).__name__}: {exc}"

        # --- 2. retention
        #
        # SKIPPED ENTIRELY UNLESS ASKED FOR, and this is a correction, not a
        # precaution. The first production run measured the cost I had assumed
        # away: on refresh-worker the dry-run sweep blocked the MAIN POLL LOOP
        # for over ten minutes.
        #
        #     22:28:51  deploy
        #     22:29:48  MLB_SIM_TICK          <- last main-loop tick
        #     22:30:11  compaction starts
        #     22:30:16  compaction done (658.6 MB reclaimed)
        #     22:40+    retention sweep STILL RUNNING, no summary emitted
        #
        # Other threads (live-lens, publisher) kept logging, so the worker
        # looked healthy from outside while its poll loop was stalled. The
        # sweep is an rglob over 14.2 GB on a box measured at 100% of its
        # 2-core limit in 72% of 5-minute buckets, and I had benchmarked it at
        # 15.6s against a 38k-file local mirror -- the real disk holds 117,377.
        # That is `#241` exactly: periodic work on this worker is never free,
        # and I added some.
        #
        # Worse than a one-off: the completion stamp is only written after the
        # sweep finishes, so a restart before then means it re-runs on the NEXT
        # boot. With tonight's deploy cadence that is a stall per deploy, not
        # per day.
        #
        # So the observation pass now needs an explicit opt-in of its own.
        # Compaction is unaffected -- it is bounded by shard count, finished in
        # 5 seconds, and is the job actually wanted here.
        retention_wanted = _flag("SYNDICATE_ARTIFACT_RETENTION_ENABLED") or _flag(
            "SYNDICATE_ARTIFACT_RETENTION_OBSERVE"
        )
        if not retention_wanted:
            summary["retention"] = {"skipped": "not_enabled_and_not_observing"}
            summary["seconds"] = round(time.time() - started, 1)
            summary["compaction_applied"] = compaction_applies
            try:
                from syndicate.features.shared.refresh_state_store import write_json_file

                write_json_file(_status_path(), {"epoch": time.time(), "summary": summary})
            except Exception:
                pass
            print(
                f"[disk_maintenance] DISK_MAINTENANCE {json.dumps(summary, sort_keys=True, default=str)}",
                flush=True,
            )
            return summary

        try:
            from syndicate.features.shared.artifact_retention import run_retention_sweep

            retention = run_retention_sweep()
            summary["retention"] = {
                "dry_run": retention.dry_run,
                "scanned": retention.scanned,
                "matched": retention.matched,
                "deleted": retention.deleted,
                "reclaimable_mb": round(retention.bytes_reclaimable / 1024 / 1024, 1),
                "freed_mb": round(retention.bytes_deleted / 1024 / 1024, 1),
                "by_tier": retention.by_tier,
                "unsettled_kept": retention.unsettled_kept,
                "unknown_settlement": retention.unknown_settlement,
            }
        except Exception as exc:
            summary["retention"] = f"error {type(exc).__name__}: {exc}"

        summary["seconds"] = round(time.time() - started, 1)
        summary["compaction_applied"] = compaction_applies

        # Stamped only after a completed pass, so a crash mid-sweep retries
        # tomorrow rather than being recorded as done.
        try:
            from syndicate.features.shared.refresh_state_store import write_json_file

            write_json_file(_status_path(), {"epoch": time.time(), "summary": summary})
        except Exception:
            pass

        print(f"[disk_maintenance] DISK_MAINTENANCE {json.dumps(summary, sort_keys=True, default=str)}", flush=True)
        return summary
    except Exception as exc:  # pragma: no cover - must never take a worker down
        print(f"[disk_maintenance] FAILED {type(exc).__name__}: {exc}", flush=True)
        return {"ran": False, "error": f"{type(exc).__name__}: {exc}"}
