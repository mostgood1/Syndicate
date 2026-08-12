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
    # Dated board-state snapshots. `intelligence_state.json` -- the LIVE one --
    # is undated and so can never be aged out by `_artifact_date`; only the
    # `_YYYY_MM_DD` history files match here. 267.9 MB and matching no rule at
    # all before this (measured on web, 2026-08-12).
    "reports/intelligence/intelligence_state_*.json",
    "reports/steam/steam_events_*.json",
    "reports/mlb_odds_diag/*",
)

# Captures. Long window -- the cost of being wrong is a fact nobody can rebuild.
SOURCE_PATTERNS: tuple[str, ...] = (
    "*_source/tracking/book_quotes/*",
    "*_source/tracking/odds_history/*",
    # THE TWIN OF THE LINE ABOVE, and its absence was the bug.
    #
    # `odds_history` is deliberately written to THREE paths together by
    # `odds_refresh_tracking._sync_odds_history_for_refresh`, and
    # `odds_control_plane.load_odds_history_payload_for_sport` reads whichever
    # is FRESHEST by mtime. That redundancy is load-bearing -- it fixed a real
    # 2026-08-04 incident where a stale shared copy shadowed a freshly pulled
    # one and every MLB board candidate sat at history_points=0 -- so the copies
    # must not be deleted individually.
    #
    # But retaining only `tracking/` meant its identical twin under `artifacts/`
    # grew forever: 655.3 MB unmanaged on web against 655.0 MB managed, the same
    # bytes twice with only one of them subject to a window. Retiring a shard has
    # to retire every copy of it, or the policy just relocates the growth.
    "*_source/artifacts/*/odds_history/*",
    "*_source/raw/*",
    "*_source/source_artifacts/data/daily/*",
    # `fnmatch`'s `*` crosses `/`, so the entry above already covers
    # `source_artifacts/data/daily/ladders/**` and `.../top_props/**`. This is
    # the same tree at its OTHER root -- `<sport>_source/data/daily/**`, which
    # holds a second copy of the ladders (335.8 MB) and top_props (44.7 MB) and
    # matched nothing.
    "*_source/data/daily/*",
)

# Evaluation output: backtest batches and locked season payloads. Not captures,
# but regenerating one means re-running an evaluation over a slate that has to
# be reconstructed first, so the short derived window is wrong for them.
EVAL_PATTERNS: tuple[str, ...] = (
    "*_source/source_artifacts/data/eval/*",
    "*_source/data/eval/*",
)

# Evidence for grading and CLV. Age alone is the WRONG axis here -- see
# `_settlement_state`.
SETTLEMENT_PATTERNS: tuple[str, ...] = (
    "settlement_inputs/*",
)

_DERIVED_DEFAULT_DAYS = 7
_SOURCE_DEFAULT_DAYS = 120
_EVAL_DEFAULT_DAYS = 180

# Grace period AFTER a date is confirmed settled, per the owner's decision
# 2026-08-12. Not measured from the file's date -- from its settlement.
_SETTLEMENT_GRACE_DAYS = 30


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
    # Settlement evidence kept because the date has NOT graded. A real answer.
    unsettled_kept: int = 0
    # Settlement evidence kept because the join could not be resolved. NOT the
    # same thing, and deliberately counted apart from it: a rising number here
    # means the resolver is broken, which under any two-valued design would have
    # looked like successful cleanup.
    unknown_settlement: int = 0

    def as_log_line(self) -> str:
        mode = "DRY_RUN" if self.dry_run else "ENABLED"
        return (
            f"[artifact_retention] RETENTION_SWEEP mode={mode} scanned={self.scanned} "
            f"matched={self.matched} deleted={self.deleted} "
            f"reclaimable_mb={self.bytes_reclaimable / 1024 / 1024:.1f} "
            f"freed_mb={self.bytes_deleted / 1024 / 1024:.1f} "
            f"failures={self.failures} tiers={self.by_tier} "
            f"unsettled_kept={self.unsettled_kept} unknown_settlement={self.unknown_settlement}"
        )


def _matches(relative: str, patterns: Iterable[str]) -> bool:
    from fnmatch import fnmatch

    posix = relative.replace(os.sep, "/")
    return any(fnmatch(posix, pattern) for pattern in patterns)


def _cutoffs(today: date) -> dict[str, date]:
    return {
        "derived": today - timedelta(days=_env_int("SYNDICATE_RETENTION_DERIVED_DAYS", _DERIVED_DEFAULT_DAYS)),
        "source": today - timedelta(days=_env_int("SYNDICATE_RETENTION_SOURCE_DAYS", _SOURCE_DEFAULT_DAYS)),
        "eval": today - timedelta(days=_env_int("SYNDICATE_RETENTION_EVAL_DAYS", _EVAL_DEFAULT_DAYS)),
        # Placeholder so every tier has an entry; the settlement tier never
        # consults it (see `_settlement_state`).
        "settlement": today - timedelta(days=_SETTLEMENT_GRACE_DAYS),
    }


# Columns `emit_settlement_inputs` adds to `closing_lines_{date}.csv` ONLY when
# a grader actually matched rows (`row.update(facts)` at :300). A file written
# for a date nothing graded carries the 15 base columns and none of these.
_GRADED_VERDICT_COLUMN = "result"


def _settlement_state(artifact_date: date, root: Path, cache: dict[date, bool | None]) -> bool | None:
    """Memoised wrapper. THE MEMO IS LOAD-BEARING, not an optimisation.

    `closing_lines_{date}.csv` is itself a `settlement_inputs/*` file, so the
    same sweep that reads it as EVIDENCE can also delete it as a SUBJECT. Path
    order decides which happens first, and `closing_lines` sorts before
    `finals`: without this, a settled date deleted its own evidence and then the
    matching `finals_{date}.json` resolved as UNKNOWN and was kept forever. The
    sweep's result depended on filesystem iteration order, and the failure was
    silent -- files simply never aged out.

    Caching on first encounter fixes it: the state for a date is resolved while
    every file for that date is still present, and no later deletion can change
    the answer.
    """
    if artifact_date not in cache:
        cache[artifact_date] = _resolve_settlement_state(artifact_date, root)
    return cache[artifact_date]


def _resolve_settlement_state(artifact_date: date, root: Path) -> bool | None:
    """Has this date actually settled? True / False / None-for-unknown.

    THE THREE-VALUED RETURN IS THE POINT. The owner's rule is "keep
    settlement_inputs for 30 days after SETTLEMENT", and the failure that rule
    exists to prevent is deleting evidence for a date that never graded. A
    two-valued resolver has to map "I could not tell" onto either settled or
    unsettled, and mapping it onto settled is a guard that deletes precisely
    when its own join is broken -- silently, and only in production, where the
    join is the thing most likely to break.

    So `None` is a distinct answer, it is treated as KEEP, and it is counted and
    logged as RETENTION_UNKNOWN. A broken join then shows up as the disk failing
    to shrink plus a loud counter, never as missing evidence.

    Evidence, not inference: `closing_lines_{date}.csv` gains `result` /
    `actual` / `home_score` / `away_score` columns only when
    `emit_settlement_inputs` matched a grader. Verified against the real tree --
    `closing_lines_2026-07-14.csv` has 15 columns and none of these (a date that
    genuinely never graded, which must be kept), while 07-17 onward have 20 and
    do.
    """
    closing = root / "settlement_inputs" / f"closing_lines_{artifact_date.isoformat()}.csv"
    try:
        if not closing.is_file():
            # No closing file at all: cannot conclude anything about grading.
            return None
        with closing.open("r", encoding="utf-8", errors="replace") as handle:
            header_line = handle.readline()
            if not header_line:
                return None
            header = [column.strip() for column in header_line.rstrip("\r\n").split(",")]
            if _GRADED_VERDICT_COLUMN not in header:
                # File exists and carries no graded verdict column -> genuinely
                # ungraded. A real answer, and the answer is "do not delete".
                return False
            # Present as a column is not the same as populated, and the
            # distinction is not pedantic: a row can carry `home_score` /
            # `away_score` (the game finished) while `result` is empty (the BET
            # was never graded). Scores are not a settlement. Only a populated
            # verdict counts.
            index = header.index(_GRADED_VERDICT_COLUMN)
            for row_line in handle:
                cells = row_line.rstrip("\r\n").split(",")
                if index < len(cells) and cells[index].strip():
                    return True
            return False
    except OSError:
        return None


def sweep_expired_artifacts(*, today: date | None = None, root: Path | None = None) -> RetentionResult:
    """Report (and only if enabled, delete) artifacts past their tier's window.

    Never raises: a retention job that can take down the worker it is tidying up
    for is a worse problem than the disk it is managing.
    """
    today = today or date.today()
    root = root or _data_root()
    cutoffs = _cutoffs(today)
    enabled = retention_enabled()
    settlement_cache: dict[date, bool | None] = {}
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

        # Settlement is checked FIRST: `settlement_inputs/*` must never fall
        # through to a plain age rule, whichever other pattern might also match
        # it later.
        if _matches(relative, SETTLEMENT_PATTERNS):
            tier = "settlement"
        elif _matches(relative, EVAL_PATTERNS):
            tier = "eval"
        elif _matches(relative, DERIVED_PATTERNS):
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

        if tier == "settlement":
            settled = _settlement_state(artifact_date, root, settlement_cache)
            if settled is None:
                # Join unresolved -> KEEP, and say so. Never the permissive
                # branch.
                result.unknown_settlement += 1
                continue
            if settled is False:
                # A real answer: this date never graded. The evidence is exactly
                # what would be needed to grade it later.
                result.unsettled_kept += 1
                continue
            if (today - artifact_date).days <= _SETTLEMENT_GRACE_DAYS:
                if result.oldest_kept is None or artifact_date < result.oldest_kept:
                    result.oldest_kept = artifact_date
                continue
        elif artifact_date >= cutoffs[tier]:
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
    if result.unknown_settlement:
        # Loud on purpose. This is the number that distinguishes "settlement
        # evidence is being retained correctly" from "the settlement join is
        # broken and every date now looks unresolvable".
        print(
            f"[artifact_retention] RETENTION_UNKNOWN settlement_files={result.unknown_settlement} "
            "-- kept, settlement state could not be resolved (missing or unreadable "
            "settlement_inputs/closing_lines_<date>.csv). These will never age out "
            "until the join resolves.",
            flush=True,
        )
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
