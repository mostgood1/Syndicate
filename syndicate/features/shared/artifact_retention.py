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

**TIERS, because "old" is not one thing:**

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

**EVERY RULE CARRIES ITS READER'S LOOKBACK** (lane `worker-disk-auto-retention`,
2026-09-16). A window is only safe relative to how far back the code that READS
the family reaches on its own. `Rule.__post_init__` refuses any rule whose
`days < min_reader_lookback_days + 7`, at import, so a rule that would delete a
file its own reader still opens cannot be written down. The same guard runs
again at sweep time against env overrides: a refused rule keeps every file and
says so. Tracing readers found two legacy rules that were already inside their
readers' windows -- `live_lens` (30-day default accuracy windows) and the MLB
`prop_registry` (up to 60 days) -- and both now keep longer. Nothing in this
change makes any rule delete sooner.

**NEW RULES NEVER ACT BY DEFAULT.** Rules added by that lane (`legacy=False`)
are report-only even when `SYNDICATE_ARTIFACT_RETENTION_ENABLED=true`; a `delete`
among them acts only if `SYNDICATE_DISK_RETENTION_NEW_RULES_APPLY=true` is ALSO
set. `gzip` and `dedupe_twin` have no acting path at all in this module -- they
are measured, not performed.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

from syndicate.features.shared.timezone import central_today

from syndicate.features.shared.artifact_publisher import _artifact_date, _data_root


class RetentionRuleError(ValueError):
    """A rule that could delete a file its own reader still opens."""


_TIERS = ("derived", "source", "eval", "settlement", "ops")
_ACTIONS = ("delete", "gzip", "dedupe_twin")
_DATE_FROM = ("name", "dirname")

# The margin between the oldest date a reader reaches and the oldest date a rule
# may remove. A week, so a reader's window can widen by a few days (an env
# override, a late slate, a UTC/Central boundary) without silently crossing into
# deleted territory.
LOOKBACK_MARGIN_DAYS = 7


@dataclass(frozen=True)
class Rule:
    """One retention rule. First matching rule (in `RULES` order) wins.

    `min_reader_lookback_days` is how many days before today the family's
    READERS open on their own (no human picking a historical date). `reader` is
    the file:line that number was taken from, or says it is a conservative
    placeholder. `legacy` marks rules that existed before the rule table; only
    those act under `SYNDICATE_ARTIFACT_RETENTION_ENABLED` alone.
    """

    name: str
    pattern: str
    tier: str
    days: int
    min_reader_lookback_days: int
    action: str = "delete"
    date_from: str = "name"
    reader: str = ""
    legacy: bool = False

    def __post_init__(self) -> None:
        if self.tier not in _TIERS:
            raise RetentionRuleError(f"rule {self.name!r}: unknown tier {self.tier!r}")
        if self.action not in _ACTIONS:
            raise RetentionRuleError(f"rule {self.name!r}: unknown action {self.action!r}")
        if self.date_from not in _DATE_FROM:
            raise RetentionRuleError(f"rule {self.name!r}: unknown date_from {self.date_from!r}")
        if self.min_reader_lookback_days < 0:
            raise RetentionRuleError(f"rule {self.name!r}: negative reader lookback")
        check_lookback(self.name, self.days, self.min_reader_lookback_days)


def check_lookback(name: str, days: int, lookback: int) -> None:
    if int(days) < int(lookback) + LOOKBACK_MARGIN_DAYS:
        raise RetentionRuleError(
            f"rule {name!r}: days={days} < reader lookback {lookback} + {LOOKBACK_MARGIN_DAYS} -- "
            "this rule would delete files its own reader still opens"
        )


_DERIVED_DEFAULT_DAYS = 7
_SOURCE_DEFAULT_DAYS = 120
_EVAL_DEFAULT_DAYS = 180

# Grace period AFTER a date is confirmed settled, per the owner's decision
# 2026-08-12. Not measured from the file's date -- from its settlement.
_SETTLEMENT_GRACE_DAYS = 30

# Env overrides that existed before the rule table, per legacy tier. New rules
# have none: a knob that can shorten a window is a knob that can fail the guard.
_TIER_DAYS_ENV = {
    "derived": ("SYNDICATE_RETENTION_DERIVED_DAYS", _DERIVED_DEFAULT_DAYS),
    "source": ("SYNDICATE_RETENTION_SOURCE_DAYS", _SOURCE_DEFAULT_DAYS),
    "eval": ("SYNDICATE_RETENTION_EVAL_DAYS", _EVAL_DEFAULT_DAYS),
}

# `fnmatch`'s `*` crosses `/` throughout -- that is relied on (see the
# `source_artifacts/data/daily` note below) and is why ORDER matters: the
# prop_registry rules must sit above the derived `live_lens` rules they are
# nested inside.
RULES: tuple[Rule, ...] = (
    # --- settlement: age is the WRONG axis here -- see `_settlement_state`.
    # Checked FIRST: `settlement_inputs/*` must never fall through to a plain
    # age rule. `days` is the grace AFTER settlement.
    Rule(
        "settlement_inputs", "settlement_inputs/*", "settlement", _SETTLEMENT_GRACE_DAYS, 14,
        reader="CONSERVATIVE: emitted per date by scripts/run_refresh_worker.py:3070 (emit_for_date); "
        "no in-process reader walks back further -- 14 d set as a placeholder",
        legacy=True,
    ),
    # --- eval output: backtest batches and locked season payloads. Not captures,
    # but regenerating one means re-running an evaluation over a slate that has
    # to be reconstructed first, so the short derived window is wrong for them.
    Rule(
        "eval_source_artifacts", "*_source/source_artifacts/data/eval/*", "eval", _EVAL_DEFAULT_DAYS, 90,
        reader="CONSERVATIVE: readers not fully traced; 90 d placeholder", legacy=True,
    ),
    Rule(
        "eval_data", "*_source/data/eval/*", "eval", _EVAL_DEFAULT_DAYS, 90,
        reader="CONSERVATIVE: readers not fully traced; 90 d placeholder", legacy=True,
    ),
    # --- MLB prop registry. Was inside the derived `live_lens` 7 d rule, but
    # `live_prop_observations_*` are CAPTURES (scripts/refresh_mlb_oddsapi.py:420)
    # and `live_prop_registry_*` is read over a window of up to 60 days by
    # `build_live_lens_daily_accuracy_payload`. A 7 d rule was deleting inside
    # its own reader's window.
    Rule(
        "mlb_prop_registry_source_artifacts", "*_source/source_artifacts/data/live_lens/prop_registry/*", "source",
        _SOURCE_DEFAULT_DAYS, 60,
        reader="syndicate/features/mlb/live_lens_daily_accuracy.py:52-66 (_parse_window, span capped at 60) "
        "-> :342 live_prop_registry_path", legacy=True,
    ),
    Rule(
        "mlb_prop_registry_data", "*_source/data/live_lens/prop_registry/*", "source", _SOURCE_DEFAULT_DAYS, 60,
        reader="syndicate/features/mlb/live_lens_daily_accuracy.py:52-66 -> :342; writer "
        "scripts/refresh_mlb_oddsapi.py:420", legacy=True,
    ),
    # --- derived: recomputable from something else on disk.
    Rule(
        "book_grid", "*_source/data/book_grid/*", "derived", 7, 0,
        reader="syndicate/features/shared/layer1_board.py:240 (resolve_window_dates, FORWARD only) + :261 "
        "(artifact_read_dates adds today and the +1 UTC neighbour)", legacy=True,
    ),
    Rule(
        "live_lens_data", "*_source/data/live_lens/*", "derived", 37, 30,
        reader="syndicate/features/shared/live_lens_local.py:159-160 (window ends yesterday) with "
        "default_days=30 at :624/:689 (explicit `days` may reach 120, :156)", legacy=True,
    ),
    Rule(
        "live_state_api", "*_source/*/api/live_state/*", "derived", 8, 1,
        reader="CONSERVATIVE: syndicate/features/shared/bet_status_soccer.py:502 reads the selected date; "
        "1 d allows settling yesterday", legacy=True,
    ),
    Rule(
        "daily_snapshots_data", "*_source/data/daily/snapshots/*", "derived", 8, 1,
        reader="syndicate/features/mlb/hr_targets.py:1086 reads the previous date's snapshots", legacy=True,
    ),
    Rule(
        "live_lens_source_artifacts", "*_source/source_artifacts/data/live_lens/*", "derived", 37, 30,
        reader="syndicate/features/shared/live_lens_local.py:159-160, default_days=30 at :624/:689", legacy=True,
    ),
    # Dated board-state snapshots. `intelligence_state.json` -- the LIVE one --
    # is undated and so can never be aged out by `_artifact_date`; only the
    # `_YYYY_MM_DD` history files match here. 267.9 MB and matching no rule at
    # all before this (measured on web, 2026-08-12).
    Rule(
        "intelligence_state_history", "reports/intelligence/intelligence_state_*.json", "derived", 7, 0,
        reader="syndicate/blueprints/intelligence.py:155 (newest-first glob for the latest date)", legacy=True,
    ),
    Rule(
        "steam_events", "reports/steam/steam_events_*.json", "derived", 7, 0,
        reader="syndicate/features/intelligence.py:5092/:5308 (selected date only)", legacy=True,
    ),
    Rule(
        "mlb_odds_diag", "reports/mlb_odds_diag/*", "derived", 7, 0,
        reader="no reader found; writer scripts/fetch_mlb_oddsapi_local.py:650/:746", legacy=True,
    ),
    # --- source: captures. Long window -- the cost of being wrong is a fact
    # nobody can rebuild.
    Rule(
        "book_quotes", "*_source/tracking/book_quotes/*", "source", _SOURCE_DEFAULT_DAYS, 60,
        reader="CONSERVATIVE: read per date via odds_book_quotes.resolve_book_quotes_path (:313); CLV and "
        "settlement callers not fully traced -- 60 d placeholder", legacy=True,
    ),
    Rule(
        "odds_history_tracking", "*_source/tracking/odds_history/*", "source", _SOURCE_DEFAULT_DAYS, 60,
        reader="CONSERVATIVE: shard lookback is 1 (odds_lifecycle.py:24) but evaluation_settlement.py:619 "
        "reads by record date -- 60 d placeholder", legacy=True,
    ),
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
    Rule(
        "odds_history_artifacts", "*_source/artifacts/*/odds_history/*", "source", _SOURCE_DEFAULT_DAYS, 60,
        reader="CONSERVATIVE: same readers as odds_history_tracking", legacy=True,
    ),
    Rule(
        "raw", "*_source/raw/*", "source", _SOURCE_DEFAULT_DAYS, 60,
        reader="CONSERVATIVE: readers not traced -- 60 d placeholder", legacy=True,
    ),
    Rule(
        "daily_source_artifacts", "*_source/source_artifacts/data/daily/*", "source", _SOURCE_DEFAULT_DAYS, 60,
        reader="CONSERVATIVE: hr_targets.py:1086 reads 1 d back; offline backtests read further -- 60 d placeholder",
        legacy=True,
    ),
    # `fnmatch`'s `*` crosses `/`, so the entry above already covers
    # `source_artifacts/data/daily/ladders/**` and `.../top_props/**`. This is
    # the same tree at its OTHER root -- `<sport>_source/data/daily/**`, which
    # holds a second copy of the ladders (335.8 MB) and top_props (44.7 MB) and
    # matched nothing.
    Rule(
        "daily_data", "*_source/data/daily/*", "source", _SOURCE_DEFAULT_DAYS, 60,
        reader="CONSERVATIVE: as daily_source_artifacts", legacy=True,
    ),
    # --- NEW (lane worker-disk-auto-retention). Report-only unless
    # SYNDICATE_DISK_RETENTION_NEW_RULES_APPLY is set as well as ENABLED.
    Rule(
        "odds_events", "odds_events/*", "ops", 14, 7,
        reader="syndicate/features/shared/odds_lifecycle.py:299 (load_recent_odds_events days_back=7); callers "
        ":422/:781/:973 all default 7 and none passes more",
    ),
    Rule(
        "migration_runs", "reports/migration_runs/*", "ops", 14, 2, date_from="dirname",
        reader="syndicate/features/shared/ops_refresh.py:347/:380/:945 read only the latest manifest's "
        "artifactsDir; 2 d covers a run spanning midnight",
    ),
    # Capture-first archive: `venue_daily_odds` says nothing reads it except
    # `record_daily_odds`' own read-modify-write of the game-date file
    # (venue_daily_odds.py:468). Kalshi keeps markets open days after the game,
    # so that write can recur well past the game date -- how long is not
    # measured, hence 7 d and a 14 d rule rather than the proposed 7 d.
    Rule(
        "venue_odds", "reports/intelligence/venue_odds/*", "ops", 14, 7,
        reader="CONSERVATIVE: syndicate/features/shared/venue_daily_odds.py:468 (record_daily_odds RMW); "
        "post-game write tail unmeasured -- 7 d placeholder",
    ),
    # One of the three `odds_history` copies (odds_control_plane.py:94). Only
    # removable when the `tracking/` copy exists and is at least as large, so
    # `load_odds_history_payload_for_sport` still finds the full shard.
    Rule(
        "odds_control_plane_history_twin", "reports/odds_control_plane/odds_history/*", "ops", 14, 1,
        action="dedupe_twin",
        reader="syndicate/features/shared/odds_lifecycle.py:24 (_ODDS_HISTORY_SHARD_LOOKBACK_DEFAULT = 1) via "
        "odds_control_plane.py:268",
    ),
)

# Kept as names for anything that still imports them. Derived from RULES so the
# two cannot disagree.
DERIVED_PATTERNS: tuple[str, ...] = tuple(r.pattern for r in RULES if r.tier == "derived")
SOURCE_PATTERNS: tuple[str, ...] = tuple(r.pattern for r in RULES if r.tier == "source")
EVAL_PATTERNS: tuple[str, ...] = tuple(r.pattern for r in RULES if r.tier == "eval")
SETTLEMENT_PATTERNS: tuple[str, ...] = tuple(r.pattern for r in RULES if r.tier == "settlement")

# Files examined per pass. Sized so a pass is seconds, not minutes: the 18-minute
# stall was 65,025 files, so ~8k is roughly two minutes of the same work and
# still covers a worker disk inside a week of daily passes.
_MAX_FILES_PER_PASS = 8000

_DIR_DATE = re.compile(r"^(20\d{2})[-_](\d{2})[-_](\d{2})$")


def _cursor_path(root: Path) -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    slug = str(os.environ.get("SYNDICATE_REFRESH_LANE") or os.environ.get("RENDER_SERVICE_ID") or "local").strip().lower()
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in slug) or "local"
    return reports_root() / "refresh_status" / "latest" / f"retention_cursor_{slug}.json"


def _read_resume_cursor(root: Path) -> str:
    """Where the last pass stopped. Per-service for the same reason the daily
    stamp is (`#405`) -- the state store is keyvalue-backed and shared, so one
    path would make two workers fight over one cursor."""
    from syndicate.features.shared.refresh_state_store import read_json_file

    try:
        payload = read_json_file(_cursor_path(root)) or {}
        return str(payload.get("after") or "")
    except Exception:
        return ""


def _write_resume_cursor(root: Path, after: str) -> None:
    from syndicate.features.shared.refresh_state_store import write_json_file

    try:
        write_json_file(_cursor_path(root), {"after": after})
    except Exception:
        pass


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


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def retention_enabled() -> bool:
    return _truthy_env("SYNDICATE_ARTIFACT_RETENTION_ENABLED")


def new_rules_apply() -> bool:
    """Second, separate switch for rules added after the rule table. Default off."""
    return _truthy_env("SYNDICATE_DISK_RETENTION_NEW_RULES_APPLY")


@dataclass
class RuleStats:
    files: int = 0
    bytes: int = 0
    oldest: date | None = None
    newest_affected: date | None = None
    acted: int = 0
    refused_twin: int = 0
    refused_lookback: bool = False

    def note(self, artifact_date: date, size: int) -> None:
        self.files += 1
        self.bytes += size
        if self.oldest is None or artifact_date < self.oldest:
            self.oldest = artifact_date
        if self.newest_affected is None or artifact_date > self.newest_affected:
            self.newest_affected = artifact_date


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
    # True when the pass stopped at max_files rather than finishing the disk.
    # Surfaced so a partial sweep is never mistaken for a clean one.
    hit_pass_limit: bool = False
    by_rule: dict[str, RuleStats] = field(default_factory=dict)
    # Rule name -> whether that rule would really act this pass.
    rule_acts: dict[str, bool] = field(default_factory=dict)
    elapsed_s: float = 0.0

    def as_log_line(self) -> str:
        mode = "DRY_RUN" if self.dry_run else "ENABLED"
        return (
            f"[artifact_retention] RETENTION_SWEEP mode={mode} scanned={self.scanned} "
            f"matched={self.matched} deleted={self.deleted} "
            f"reclaimable_mb={self.bytes_reclaimable / 1024 / 1024:.1f} "
            f"freed_mb={self.bytes_deleted / 1024 / 1024:.1f} "
            f"failures={self.failures} tiers={self.by_tier} "
            f"unsettled_kept={self.unsettled_kept} unknown_settlement={self.unknown_settlement} "
            f"hit_pass_limit={self.hit_pass_limit}"
        )

    def path_log_payloads(self) -> list[dict[str, Any]]:
        rows = []
        for rule in RULES:
            stats = self.by_rule.get(rule.name) or RuleStats()
            rows.append(
                {
                    "rule": rule.name,
                    "pattern": rule.pattern,
                    "action": rule.action,
                    "files": stats.files,
                    "bytes": stats.bytes,
                    "oldest": stats.oldest.isoformat() if stats.oldest else None,
                    "newest_affected": stats.newest_affected.isoformat() if stats.newest_affected else None,
                    "dry_run": not self.rule_acts.get(rule.name, False),
                    "refused_lookback": stats.refused_lookback,
                    "refused_twin": stats.refused_twin,
                }
            )
        return rows

    def summary_payload(self) -> dict[str, Any]:
        per_action: dict[str, dict[str, int]] = {}
        for rule in RULES:
            stats = self.by_rule.get(rule.name)
            bucket = per_action.setdefault(rule.action, {"files": 0, "bytes": 0})
            if stats:
                bucket["files"] += stats.files
                bucket["bytes"] += stats.bytes
        return {
            "per_action": per_action,
            "dry_run": not any(self.rule_acts.values()),
            "elapsed_s": round(self.elapsed_s, 2),
            "cursor_complete": not self.hit_pass_limit,
            "scanned": self.scanned,
            "deleted": self.deleted,
            "failures": self.failures,
        }


def _match_rule(relative: str) -> Rule | None:
    """First matching rule, or None (KEPT)."""
    from fnmatch import fnmatch

    posix = relative.replace(os.sep, "/")
    for rule in RULES:
        if fnmatch(posix, rule.pattern):
            return rule
    return None


def _rule_for(relative: str) -> Rule | None:
    """Every examined file passes through here exactly once per pass. A seam for
    the coverage test, which records what each pass examined."""
    return _match_rule(relative)


def _dirname_date(relative: str) -> date | None:
    """The deepest ANCESTOR directory whose whole name is a date.

    `reports/migration_runs/<date>/odds_refresh_<stamp>/odds_refresh.json` names
    nothing dated in its filename, so `_artifact_date` returns None and the tree
    never aged out. Only a directory whose entire name is a date counts -- a
    stamp that merely contains digits is not evidence of a slate.
    """
    parts = relative.replace(os.sep, "/").split("/")[:-1]
    for part in reversed(parts):
        match = _DIR_DATE.match(part)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
    return None


def _date_for(rule: Rule, path: Path, relative: str) -> date | None:
    if rule.date_from == "dirname":
        return _dirname_date(relative)
    return _artifact_date(path)


def _effective_days(rule: Rule) -> int:
    """Legacy tiers honour their old env override; the guard is re-applied by
    the caller, so an override can never shorten a rule past its reader."""
    if not (rule.legacy and rule.tier in _TIER_DAYS_ENV):
        return rule.days
    name, _default = _TIER_DAYS_ENV[rule.tier]
    # Junk, zero or negative falls back to the RULE's own days, never to 0.
    return _env_int(name, rule.days)


def _twin_ok(root: Path, relative: str, size: int) -> bool:
    """`reports/odds_control_plane/odds_history/<sport>/<shard>.json` is removable
    only when `<sport>_source/tracking/odds_history/<shard>.json` exists and is
    at least as large. Anything else -- a missing twin, a smaller twin, an
    unexpected path shape, an unreadable stat -- refuses."""
    parts = relative.split("/")
    if len(parts) != 5 or parts[:3] != ["reports", "odds_control_plane", "odds_history"]:
        return False
    sport, name = parts[3], parts[4]
    twin = root / f"{sport}_source" / "tracking" / "odds_history" / name
    try:
        return twin.is_file() and int(twin.stat().st_size) >= int(size)
    except OSError:
        return False


def _sorted_walk(root: Path, resume_after: str) -> Iterator[tuple[str, Path]]:
    """Every file under `root`, in LEXICOGRAPHIC order of its relative path.

    THE CURSOR BUG THIS FIXES. The resume cursor stores the last path examined
    and the next pass skips everything `<=` it. That is only a seek if the walk
    visits paths in that same order -- and `rglob` promises no order. A capped
    pass that walked `z/...` first stored a cursor that made every later pass
    skip `a/...` to `y/...` until the cycle reset. Coverage was silently partial.

    Sorting each directory by `name + "/"` for directories and `name` for files
    makes the depth-first order equal to string order of the joined path (a
    directory `a` sorts after file `a.txt`, exactly as `a/x` > `a.txt`). And
    because order is exact, a whole subtree that sorts entirely at or below the
    cursor can be pruned without listing it.
    """
    # Explicit stack of iterators so recursion depth is never a concern.
    iterators: list[Iterator[tuple[str, Path, bool]]] = []

    def _children(directory: Path, prefix: str) -> Iterator[tuple[str, Path, bool]]:
        try:
            with os.scandir(directory) as handle:
                entries = []
                for entry in handle:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    entries.append((entry.name + "/" if is_dir else entry.name, entry.name, is_dir))
        except OSError:
            return iter(())
        entries.sort(key=lambda item: item[0])
        return iter([(prefix + name, directory / name, is_dir) for _key, name, is_dir in entries])

    iterators.append(_children(root, ""))
    while iterators:
        try:
            relative, path, is_dir = next(iterators[-1])
        except StopIteration:
            iterators.pop()
            continue
        if is_dir:
            subtree = relative + "/"
            if resume_after and subtree < resume_after and not resume_after.startswith(subtree):
                # Every path in this subtree starts with `subtree` and so sorts
                # below the cursor: already covered by an earlier pass.
                continue
            iterators.append(_children(path, subtree))
            continue
        if resume_after and relative <= resume_after:
            continue
        yield relative, path


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


# Columns `emit_settlement_inputs` adds to `closing_lines_{date}.csv` ONLY when
# a grader actually matched rows (`row.update(facts)` at :300). A file written
# for a date nothing graded carries the 15 base columns and none of these.
_GRADED_VERDICT_COLUMN = "result"


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


# Today and yesterday are never touched by ANY rule, whatever its window: a
# writer may still hold today's file, and yesterday's slate can still be
# finishing (late games, UTC/Central boundary, settlement).
_NEVER_TOUCH_DAYS = 1


def sweep_expired_artifacts(
    *,
    today: date | None = None,
    root: Path | None = None,
    force_dry_run: bool = False,
) -> RetentionResult:
    """Report (and only if enabled, delete) artifacts past their rule's window.

    `force_dry_run=True` guarantees nothing is removed whatever the env says --
    the path `SYNDICATE_DISK_RETENTION_DRY_RUN` uses.

    Never raises: a retention job that can take down the worker it is tidying up
    for is a worse problem than the disk it is managing.
    """
    started = time.monotonic()
    today = today or central_today()
    root = root or _data_root()
    enabled = retention_enabled() and not force_dry_run
    new_apply = enabled and new_rules_apply()
    settlement_cache: dict[date, bool | None] = {}
    result = RetentionResult(dry_run=not enabled)

    # Which rules act this pass, and which are refused by the lookback guard
    # after env overrides. Decided ONCE, before the walk.
    effective_days: dict[str, int] = {}
    for rule in RULES:
        stats = result.by_rule.setdefault(rule.name, RuleStats())
        days = _effective_days(rule)
        try:
            check_lookback(rule.name, days, rule.min_reader_lookback_days)
        except RetentionRuleError:
            stats.refused_lookback = True
        effective_days[rule.name] = days
        acts = (
            not stats.refused_lookback
            and rule.action == "delete"
            and (enabled if rule.legacy else new_apply)
        )
        result.rule_acts[rule.name] = acts

    # STREAMED, not materialised, and BOUNDED. Measured 2026-08-12: an
    # unbounded walk took 18 MINUTES over 65,025 files on refresh-worker and
    # blocked that worker's main poll loop for the whole of it. A cap plus a
    # resume cursor makes the worst case a SLOW sweep rather than a BLOCKED
    # loop, and since 2026-09-16 the walk is SORTED (`_sorted_walk`) so the
    # cursor is a real seek and coverage completes across capped passes.
    #
    # THE DISTINCTION THAT FAILED, and it is worth naming: this job was called
    # safe because it is dry-run by default. Dry run describes what it does not
    # DELETE. It says nothing about what it COSTS. A read-only walk of 65,025
    # files is exactly as expensive as a destructive one, and "cannot do damage"
    # is not "cannot do harm".
    max_files = _env_int("SYNDICATE_RETENTION_MAX_FILES_PER_PASS", _MAX_FILES_PER_PASS)
    resume_after = _read_resume_cursor(root)
    last_path = ""
    if not root.is_dir():
        result.elapsed_s = time.monotonic() - started
        return result

    for relative, path in _sorted_walk(root, resume_after):
        if result.scanned >= max_files:
            result.hit_pass_limit = True
            break
        result.scanned += 1
        last_path = relative

        rule = _rule_for(relative)
        if rule is None:
            # Unmatched is KEPT. See the module docstring -- an unknown path is
            # not evidence that a file is disposable.
            continue
        stats = result.by_rule[rule.name]
        if stats.refused_lookback:
            continue

        # Undated files are never aged out: there is nothing to judge them
        # against, and dropping them would be a coverage bug wearing a disk
        # fix's clothes.
        artifact_date = _date_for(rule, path, relative)
        if artifact_date is None:
            continue
        if (today - artifact_date).days <= _NEVER_TOUCH_DAYS:
            continue

        if rule.tier == "settlement":
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
            if (today - artifact_date).days <= effective_days[rule.name]:
                if result.oldest_kept is None or artifact_date < result.oldest_kept:
                    result.oldest_kept = artifact_date
                continue
        elif artifact_date >= today - timedelta(days=effective_days[rule.name]):
            if result.oldest_kept is None or artifact_date < result.oldest_kept:
                result.oldest_kept = artifact_date
            continue

        try:
            size = path.stat().st_size
        except OSError:
            continue

        if rule.action == "dedupe_twin" and not _twin_ok(root, relative, size):
            stats.refused_twin += 1
            continue

        stats.note(artifact_date, size)
        result.matched += 1
        result.bytes_reclaimable += size
        result.by_tier[rule.tier] = result.by_tier.get(rule.tier, 0) + 1

        if not result.rule_acts.get(rule.name):
            continue
        try:
            path.unlink()
            result.deleted += 1
            result.bytes_deleted += size
            stats.acted += 1
        except OSError:
            result.failures += 1

    # A completed pass clears the cursor so the next one starts from the top;
    # a truncated pass records where to resume.
    _write_resume_cursor(root, last_path if result.hit_pass_limit else "")
    result.elapsed_s = time.monotonic() - started
    return result


def run_retention_sweep(*, force_dry_run: bool = False, today: date | None = None, root: Path | None = None) -> RetentionResult:
    """Entry point for the worker. Logs its own result and returns it."""
    result = sweep_expired_artifacts(today=today, root=root, force_dry_run=force_dry_run)
    # `print`, not `logger.info` -- logger output does not reach Render's log
    # collector from the worker process.
    print(result.as_log_line(), flush=True)
    for payload in result.path_log_payloads():
        print(f"[artifact_retention] DISK_RETENTION_PATH {json.dumps(payload, sort_keys=True)}", flush=True)
    print(
        f"[artifact_retention] DISK_RETENTION_SUMMARY {json.dumps(result.summary_payload(), sort_keys=True)}",
        flush=True,
    )
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
    _result = run_retention_sweep()
    print(
        json.dumps(
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
