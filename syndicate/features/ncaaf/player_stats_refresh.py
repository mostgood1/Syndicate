"""Per-week refresh of the CFBD player-game-stats snapshot the NCAAF game
card's Box Score tab joins against.

WHY THIS MODULE EXISTS
----------------------
`scripts/build_ncaaf_player_game_stats_snapshot.py` has always been able to
build ONE week for ONE season. Nobody ran it for the current season, so
`ncaaf_player_game_stats_snapshot.csv` sat at **35,829 rows, every one
`season=2025`, weeks 1-16, `source_snapshot_date=2026-08-26`** -- measured,
not assumed. `_ncaaf_player_box_section` in `cards.py` joins STRICTLY on the
card's own season, so every 2026 card matched zero rows and rendered a stated
empty state. That refusal is correct and stays: last season's numbers printed
under this game's teams would be a fabricated box score that looks completely
plausible and is wrong in every cell.

What was missing is the job that keeps the snapshot current. This module is
that job's policy and safety layer; `scripts/refresh_ncaaf_player_game_stats.py`
is its entry point.

THE TWO THINGS THAT CAN GO WRONG, AND THE GUARDS FOR THEM
---------------------------------------------------------
**1. An empty week silently wiping the file.** CFBD's `/games/players` returns
`[]` for a week that has not been played -- confirmed live 2026-09-09:
`year=2026&week=2` returned HTTP 200 with a 2-byte body while `week=1`
returned 203 games / 6.01 MB. A refresh that treats "no games" as "write what
you got" is one scheduled run away from being the thing that destroys the
artifact it maintains. So a week that yields no rows is a NO-OP: the writer is
never called, and the CSV is not even reopened. See `refresh_week`.

**2. Gaining one week by losing a season.** `write_ncaaf_player_game_stats_snapshot_csv`
merges through `_merge_season_week_aware_rows`, which replaces only the
(season, week) groups present in the new rows -- so 2025 survives a 2026
refresh by construction. That is the DESIGN; this module additionally VERIFIES
it, because a design that is only asserted in a docstring is a design that can
regress silently. `refresh_week` counts rows per (season, week) before and
after the write and raises `NcaafPlayerStatsHistoryLoss` if any group it did
not target lost rows. A refresh that damaged history should fail loudly, not
report success.

CADENCE
-------
NCAAF slates finish Saturday night, so the natural cadence is daily-ish, not
per-tick: `NCAAF_PLAYER_STATS_REFRESH_INTERVAL_SECONDS` defaults to 86400 with
a 3600s floor. Each run refreshes a small trailing window of weeks
(`DEFAULT_LOOKBACK_WEEKS`) rather than only the newest one, because CFBD
back-fills and corrects stat lines for a day or two after a game and a
one-shot fetch would freeze the first, incomplete reading.

DEFAULT OFF, like every sibling autorun in this repo.
`NCAAF_PLAYER_STATS_ENABLE_REFRESH_WORKER_AUTORUN` is absent = OFF, matching
`NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN`,
`NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN` and the rest of the
`*_ENABLE_REFRESH_WORKER_AUTORUN` family. Shipping an autorun default-on has
broken this repo's tests before; absent must mean off here, and
`player_stats_autorun_enabled` is written so that an unparseable value is off
too rather than falling through to the permissive branch.
"""

from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.ncaaf.cfbd import (
    PLAYER_GAME_STATS_COLUMNS,
    build_ncaaf_player_game_stats_rows,
    write_ncaaf_player_game_stats_snapshot_csv,
)
from syndicate.features.ncaaf.sources import player_game_stats_snapshot_path

#: Absent = OFF. Same name shape as every sibling autorun flag in
#: `scripts/run_refresh_worker.py`.
AUTORUN_ENV_VAR = "NCAAF_PLAYER_STATS_ENABLE_REFRESH_WORKER_AUTORUN"
INTERVAL_ENV_VAR = "NCAAF_PLAYER_STATS_REFRESH_INTERVAL_SECONDS"

#: Daily. A weekly sport's stat lines settle overnight after Saturday's
#: slate; a tighter interval spends CFBD calls to re-read a finished week.
DEFAULT_INTERVAL_SECONDS = 86400
#: Floor, matching the NFL snapshot autoruns' `max(3600, value)`.
MIN_INTERVAL_SECONDS = 3600

#: How many weeks back from the target week each run re-fetches. 2 == the
#: week in progress plus the one just completed, so CFBD's post-game
#: corrections land instead of freezing whatever the first fetch saw.
DEFAULT_LOOKBACK_WEEKS = 2

_TRUE_VALUES = {"1", "true", "yes", "on"}


class NcaafPlayerStatsHistoryLoss(RuntimeError):
    """A refresh removed rows from a (season, week) group it did not target.

    Raised rather than returned: the caller cannot make a sensible decision
    about a half-destroyed history file, and a job that damaged the artifact
    it maintains must not exit 0.
    """


@dataclass(frozen=True)
class WeekRefreshResult:
    season: int
    week: int
    games_fetched: int = 0
    rows_written: int = 0
    skipped: bool = False
    skip_reason: str = ""
    validation_issues: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.validation_issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "week": self.week,
            "games_fetched": self.games_fetched,
            "rows_written": self.rows_written,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "validation_issues": list(self.validation_issues),
        }


@dataclass(frozen=True)
class RefreshReport:
    season: int
    output_path: Path
    weeks: tuple[WeekRefreshResult, ...] = field(default_factory=tuple)
    total_rows_before: int = 0
    total_rows_after: int = 0

    @property
    def rows_written(self) -> int:
        return sum(item.rows_written for item in self.weeks)

    @property
    def weeks_refreshed(self) -> tuple[int, ...]:
        return tuple(item.week for item in self.weeks if not item.skipped)

    @property
    def weeks_skipped(self) -> tuple[int, ...]:
        return tuple(item.week for item in self.weeks if item.skipped)

    @property
    def validation_issues(self) -> tuple[str, ...]:
        return tuple(issue for item in self.weeks for issue in item.validation_issues)

    @property
    def ok(self) -> bool:
        return not self.validation_issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "output_path": str(self.output_path),
            "weeks": [item.as_dict() for item in self.weeks],
            "weeks_refreshed": list(self.weeks_refreshed),
            "weeks_skipped": list(self.weeks_skipped),
            "rows_written": self.rows_written,
            "total_rows_before": self.total_rows_before,
            "total_rows_after": self.total_rows_after,
            "ok": self.ok,
            "validation_issues": list(self.validation_issues),
        }


def player_stats_autorun_enabled(env: Mapping[str, str] | None = None) -> bool:
    """True only for an explicit affirmative value.

    Absent, empty, and unrecognised all map to OFF. This is deliberately
    the strict direction: an autorun whose unknown state defaults permissive
    turns a typo into a scheduled production job.
    """
    source = os.environ if env is None else env
    raw = str(source.get(AUTORUN_ENV_VAR) or "").strip().lower()
    return raw in _TRUE_VALUES


def player_stats_refresh_interval_seconds(env: Mapping[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    raw = str(source.get(INTERVAL_ENV_VAR) or "").strip()
    try:
        value = int(raw or DEFAULT_INTERVAL_SECONDS)
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, value)


def weeks_to_refresh(target_week: int | None, *, lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS) -> tuple[int, ...]:
    """The trailing window of weeks one run re-fetches, oldest first.

    `target_week` is `sources.ncaaf_target_week` semantics -- "the lowest week
    with an unplayed game", i.e. the week currently in progress. None (season
    not loaded, or every game already complete) yields an empty window rather
    than a guess: fetching a made-up week spends a CFBD call to learn nothing.
    """
    if target_week is None:
        return ()
    try:
        end = int(target_week)
    except (TypeError, ValueError):
        return ()
    if end < 1:
        return ()
    span = max(1, int(lookback_weeks))
    start = max(1, end - span + 1)
    return tuple(range(start, end + 1))


def _row_counts_by_season_week(path: Path) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            counts[(str(row.get("season") or "").strip(), str(row.get("week") or "").strip())] += 1
    return counts


def _assert_history_preserved(
    *,
    before: Counter[tuple[str, str]],
    after: Counter[tuple[str, str]],
    targeted: tuple[str, str],
) -> None:
    losses = [
        f"{season or '?'}wk{week or '?'}: {count} -> {after.get((season, week), 0)}"
        for (season, week), count in sorted(before.items())
        if (season, week) != targeted and after.get((season, week), 0) < count
    ]
    if losses:
        raise NcaafPlayerStatsHistoryLoss(
            "NCAAF player-game-stats refresh removed rows from groups it did not target "
            f"(targeted season={targeted[0]} week={targeted[1]}): " + "; ".join(losses)
        )


def refresh_week(
    *,
    client: Any,
    season: int,
    week: int,
    output_path: Path | None = None,
    season_type: str = "regular",
    source_snapshot_date: str | None = None,
    games_payload: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> WeekRefreshResult:
    """Fetch one week and merge it into the snapshot, or do nothing at all.

    A week with no completed games is a NO-OP -- the CSV is not opened, let
    alone written. See the module docstring: CFBD answers an unplayed week
    with HTTP 200 and an empty list, so "write whatever came back" is the
    failure mode that costs the whole artifact.
    """
    path = output_path or player_game_stats_snapshot_path()
    payload = (
        list(games_payload)
        if games_payload is not None
        else list(client.fetch_player_game_stats(season=season, week=week, season_type=season_type))
    )
    if not payload:
        return WeekRefreshResult(season=season, week=week, skipped=True, skip_reason="no_completed_games")

    snapshot_date = source_snapshot_date or date_type.today().isoformat()
    candidate_rows = build_ncaaf_player_game_stats_rows(
        season=season,
        week=week,
        games_payload=payload,
        source_snapshot_date=snapshot_date,
    )
    if not candidate_rows:
        # A non-empty games payload that yields no player rows -- e.g. games
        # scheduled and listed but with no stat categories posted yet. Same
        # rule as the empty payload: never write a group we cannot fill.
        return WeekRefreshResult(
            season=season,
            week=week,
            games_fetched=len(payload),
            skipped=True,
            skip_reason="no_player_rows",
        )

    before = _row_counts_by_season_week(path)
    result = write_ncaaf_player_game_stats_snapshot_csv(
        client=client,
        season=season,
        week=week,
        games_payload=payload,
        output_path=path,
        source_snapshot_date=snapshot_date,
    )
    after = _row_counts_by_season_week(path)
    _assert_history_preserved(before=before, after=after, targeted=(str(season), str(week)))

    return WeekRefreshResult(
        season=season,
        week=week,
        games_fetched=len(payload),
        rows_written=len(result.rows),
        validation_issues=tuple(result.validation_issues),
    )


def refresh_player_game_stats(
    *,
    client: Any,
    season: int,
    weeks: tuple[int, ...] | list[int],
    output_path: Path | None = None,
    season_type: str = "regular",
    source_snapshot_date: str | None = None,
) -> RefreshReport:
    """Refresh a window of weeks into the one snapshot CSV.

    Weeks are processed oldest-first so a partial failure leaves the newest
    weeks unwritten rather than a hole in the middle.
    """
    path = output_path or player_game_stats_snapshot_path()
    total_before = sum(_row_counts_by_season_week(path).values())
    results: list[WeekRefreshResult] = []
    for week in sorted({int(item) for item in weeks}):
        results.append(
            refresh_week(
                client=client,
                season=season,
                week=week,
                output_path=path,
                season_type=season_type,
                source_snapshot_date=source_snapshot_date,
            )
        )
    total_after = sum(_row_counts_by_season_week(path).values())
    return RefreshReport(
        season=season,
        output_path=path,
        weeks=tuple(results),
        total_rows_before=total_before,
        total_rows_after=total_after,
    )


def snapshot_columns() -> tuple[str, ...]:
    """Re-exported so a test can assert the written schema without importing
    the whole CFBD module."""
    return tuple(PLAYER_GAME_STATS_COLUMNS)
