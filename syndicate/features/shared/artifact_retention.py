"""`#396` -- retention for the Render persistent disk. Nothing ever deleted.

MEASURED 2026-08-12: the disk grows ~700 MB/day and sat at ~40% of 50 GB, so it
fills around **late September 2026**. Repo-wide, the only `unlink()` calls in the
publish path are temp-file cleanup during atomic writes (`artifact_publisher.py`
`:1124`, `:1739`). There is no TTL, no pruning, no compaction anywhere.

**DEFAULTS TO DRY RUN, AND THAT IS THE POINT.** CLAUDE.md's first rule is that
Render is the source of truth and the git tree is a lossy mirror -- so a file
deleted here may be the only copy that exists. A retention job that starts out
deleting is a data-loss incident waiting for its first bad glob. This one
reports what it *would* remove until someone reads those numbers and sets
`SYNDICATE_ARTIFACT_RETENTION_ENABLED=true`.

**TWO TIERS, because "old" is not one thing:**

`DERIVED` artifacts are recomputable from something else on disk. `book_grid` is
built from `book_quotes` (`book_grid_artifact.build_book_grid_artifact` reads
`odds_book_quotes.book_quotes_path`), so deleting a 12 MB grid costs a rebuild,
not a fact. These get the short window.

`SOURCE` artifacts are captures -- odds quotes, feed payloads, boxscores. Once
a price at a moment in time is gone it cannot be recreated at any cost, and S6
settlement and CLV both read history. These get the long window, and the
default is deliberately long enough that this job is not what breaks a backtest.

**Anything that does not match a rule is KEPT.** An unknown path is not evidence
that a file is disposable, and the failure directions are not symmetric: keeping
junk costs disk, deleting a capture costs the record.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from syndicate.features.shared.artifact_publisher import _artifact_date, _data_root


# Recomputable from something else on disk. Short window -- the cost of being
# wrong is CPU on the next rebuild.
DERIVED_PATTERNS: tuple[str, ...] = (
    "*_source/data/book_grid/*",
    "*_source/data/live_lens/*",
    "*_source/*/api/live_state/*",
    "*_source/data/daily/snapshots/*",
    "*_source/source_artifacts/data/live_lens/*",
)

# Captures. Long window -- the cost of being wrong is a fact nobody can rebuild.
SOURCE_PATTERNS: tuple[str, ...] = (
    "*_source/tracking/book_quotes/*",
    "*_source/tracking/odds_history/*",
    "*_source/raw/*",
    "*_source/source_artifacts/data/daily/*",
)

_DERIVED_DEFAULT_DAYS = 7
_SOURCE_DEFAULT_DAYS = 120


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    # 0 or negative would delete everything dated. Treated as "unset" rather
    # than "delete all" -- an unparseable config must never map onto the most
    # destructive branch.
    return value if value > 0 else default


def retention_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_ARTIFACT_RETENTION_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass
class RetentionResult:
    scanned: int = 0
    matched: int = 0
    deleted: int = 0
    bytes_reclaimable: int = 0
    bytes_deleted: int = 0
    failures: int = 0
    dry_run: bool = True
    oldest_kept: date | None = None
    by_tier: dict[str, int] = field(default_factory=dict)

    def as_log_line(self) -> str:
        mode = "DRY_RUN" if self.dry_run else "ENABLED"
        return (
            f"[artifact_retention] RETENTION_SWEEP mode={mode} scanned={self.scanned} "
            f"matched={self.matched} deleted={self.deleted} "
            f"reclaimable_mb={self.bytes_reclaimable / 1024 / 1024:.1f} "
            f"freed_mb={self.bytes_deleted / 1024 / 1024:.1f} "
            f"failures={self.failures} tiers={self.by_tier}"
        )


def _matches(relative: str, patterns: Iterable[str]) -> bool:
    from fnmatch import fnmatch

    posix = relative.replace(os.sep, "/")
    return any(fnmatch(posix, pattern) for pattern in patterns)


def _cutoffs(today: date) -> dict[str, date]:
    return {
        "derived": today - timedelta(days=_env_int("SYNDICATE_RETENTION_DERIVED_DAYS", _DERIVED_DEFAULT_DAYS)),
        "source": today - timedelta(days=_env_int("SYNDICATE_RETENTION_SOURCE_DAYS", _SOURCE_DEFAULT_DAYS)),
    }


def sweep_expired_artifacts(*, today: date | None = None, root: Path | None = None) -> RetentionResult:
    """Report (and only if enabled, delete) artifacts past their tier's window.

    Never raises: a retention job that can take down the worker it is tidying up
    for is a worse problem than the disk it is managing.
    """
    today = today or date.today()
    root = root or _data_root()
    cutoffs = _cutoffs(today)
    enabled = retention_enabled()
    result = RetentionResult(dry_run=not enabled)

    try:
        candidates = [p for p in root.rglob("*") if p.is_file()]
    except OSError:
        return result

    for path in candidates:
        result.scanned += 1
        try:
            relative = str(path.relative_to(root))
        except ValueError:
            continue

        if _matches(relative, DERIVED_PATTERNS):
            tier = "derived"
        elif _matches(relative, SOURCE_PATTERNS):
            tier = "source"
        else:
            # Unmatched is KEPT. See the module docstring -- an unknown path is
            # not evidence that a file is disposable.
            continue

        # Undated files are never aged out. `_artifact_date` returns None for
        # them and its own docstring explains why: there is nothing to judge
        # them against, and dropping them would be a coverage bug wearing a
        # disk fix's clothes.
        artifact_date = _artifact_date(path)
        if artifact_date is None:
            continue
        if artifact_date >= cutoffs[tier]:
            if result.oldest_kept is None or artifact_date < result.oldest_kept:
                result.oldest_kept = artifact_date
            continue

        try:
            size = path.stat().st_size
        except OSError:
            continue

        result.matched += 1
        result.bytes_reclaimable += size
        result.by_tier[tier] = result.by_tier.get(tier, 0) + 1

        if not enabled:
            continue
        try:
            path.unlink()
            result.deleted += 1
            result.bytes_deleted += size
        except OSError:
            result.failures += 1

    return result


def run_retention_sweep() -> RetentionResult:
    """Entry point for the worker loop. Logs its own result and returns it."""
    result = sweep_expired_artifacts()
    # `print`, not `logger.info` -- logger output does not reach Render's log
    # collector from the worker process.
    print(result.as_log_line(), flush=True)
    if result.dry_run and result.matched:
        print(
            "[artifact_retention] RETENTION_DRY_RUN nothing was deleted; set "
            "SYNDICATE_ARTIFACT_RETENTION_ENABLED=true to act on the numbers above",
            flush=True,
        )
    return result


if __name__ == "__main__":  # pragma: no cover - operator entry point
    # Runnable as `python -m syndicate.features.shared.artifact_retention`.
    #
    # DELIBERATELY NOT WIRED INTO THE WORKER LOOP. `rglob` over a 20 GB disk is
    # real work, and periodic work on this worker is never free -- `#241` put
    # production into a restart loop by adding some. Run it from a schedule or
    # by hand, look at `reclaimable_mb`, then decide about
    # SYNDICATE_ARTIFACT_RETENTION_ENABLED. Wiring it into the loop is a
    # separate decision with a memory budget attached.
    import json as _json

    _result = run_retention_sweep()
    print(
        _json.dumps(
            {
                "dry_run": _result.dry_run,
                "scanned": _result.scanned,
                "matched": _result.matched,
                "deleted": _result.deleted,
                "reclaimable_mb": round(_result.bytes_reclaimable / 1024 / 1024, 1),
                "freed_mb": round(_result.bytes_deleted / 1024 / 1024, 1),
                "by_tier": _result.by_tier,
                "oldest_kept": _result.oldest_kept.isoformat() if _result.oldest_kept else None,
            },
            indent=2,
        )
    )
