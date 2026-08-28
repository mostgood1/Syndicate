"""Retain the live game-line model-vs-market score, worker-side.

Lane `live-game-line-projection`.

WHY THIS EXISTS. `live_gameline_score` is computed on every board build and
served on `/api/board/book-grid`, but **nothing retained it** — each build
overwrites the snapshot, and the board rolls to the next slate date at midnight
Central, taking the completed-game numbers with it. The retention mechanism was
a laptop cron (`scripts/snapshot_live_gameline_score.py`, task
`live-gameline-accuracy-snapshot`, 23:25 CT) that fetched the served API and
appended a row locally.

**That design lost 7 of its first 8 nights, to two unrelated failures:**

1. The task sat DISABLED 08-21..08-27. A one-off meant to re-enable it never
   did. Six nights.
2. Measured 2026-08-28: the task fired ON TIME at 04:34:17Z and its Bash call
   did not return until **13:49:37Z** — 9h13m later. Windows entered Modern
   Standby at 03:57:42Z (Kernel-Power 506, Idle Timeout) and left it at
   13:48:00Z (507, "Reason: Input Mouse"). Modern Standby keeps the network
   alive, so the scheduler fired and the model emitted a tool call, while the
   Desktop Activity Moderator suspended the child process. The slate had rolled
   by the time python ran; the row landed with `games_with_outcome=0`.
   Corroborated across three other concurrent sessions, all stalled and all
   resuming within the same 72 seconds.

**So the capture is moved to where the score is already computed** — the board
build, on the refresh-worker. That removes both failure modes at once, and a
third that was latent: the wall-clock DEADLINE. A cron at 23:25 CT is racing
the midnight roll and gets one attempt. The worker rebuilds the board every few
minutes all day, so this records continuously and the best build of the night
wins on its own.

DESIGN, each point from a rule this repo already paid for.

1. **Direct `path.open()`, never `write_json_file`.** `_keyvalue_backed()`
   routes everything outside `migration_runs/` to the keyvalue store and
   returns BEFORE touching disk, so a `HOT_ARTIFACT_PATTERNS` entry for such a
   path is inert — it turns a 403 into an empty result and looks like a fix.
   (`learnings.md`, 2026-08-27.) The allowlist is only meaningful for a real
   disk write, which is what this does — same as `live_gameline_ledger`.

2. **Disk, not `reports/**`.** `reports/` is keyvalue-backed with an 8 MB
   payload ceiling on a 256 MB shared store. This writes under
   `data/<sport>_source/`, which is disk-backed and allowlisted.

3. **Append ONLY when `games_with_outcome` improves.** The board rebuilds every
   few minutes; recording unconditionally would multiply the file by the build
   rate for no information. `games_with_outcome` is monotonic across a slate as
   games finalise, so improvement-only bounds appends at roughly one per game
   per date, and the last row for a date is its most complete reading. This is
   the same dedup philosophy as `live_gameline_ledger`, and it encodes the
   pooling rule readers already use ("take the max per date") into the file.

4. **Never raises.** The board is the product; this is instrumentation. A
   failure is reported in the returned counters rather than logged only, so a
   silent zero cannot be mistaken for "the model scored nothing". Same rule as
   `record_live_gamelines` and the scorer above it.

WHAT IS DELIBERATELY NOT HERE. No pooling, no Brier arithmetic, no opinion
about whether the model is any good. `score_ledger_records` owns the scoring;
this retains its output. Aggregation stays with the reader, which is where the
"independent unit is `games_with_outcome`, not the record count" bound lives.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# v1 is the shape the laptop collector wrote to
# `reports/live_gameline_accuracy/history.jsonl`, minus its capture-time
# framing. **Load-bearing for any reader**: rows written by the old collector
# carry no `v` at all, and rows recovered from the retained ledger carry
# `recovered_from_ledger: true`. Filter on provenance before pooling — a
# reconstruction and a live capture are not the same evidence.
ACCURACY_VERSION = 1

# One row per game that finalises, per sport-date, is the realistic ceiling for
# improvement-only appends (~15 for MLB). 2,000 is far above that and still
# bounds a pathological build loop that somehow keeps improving.
_MAX_ROWS_PER_FILE = 2_000

# The cuts `score_ledger_records` produces. Copied wholesale so the retained row
# carries the same populations the served payload did -- including
# `populations_matched` and `model_paired`, without which a Brier difference
# spans two different row sets.
_SCORE_CUTS = ("all_records", "last_per_game", "priceable_only")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def history_path(sport: str) -> Path:
    """One file per sport, ALL dates.

    Deliberately not date-partitioned like the ledger: this file holds one row
    per date (a few hundred bytes), so a year is well under a megabyte and a
    single pull returns the whole history. The ledger is partitioned because it
    is megabytes PER DAY.
    """
    from syndicate.features.shared.refresh_state_store import data_root

    slug = str(sport or "").strip().lower()
    return (
        data_root()
        / f"{slug}_source"
        / "data"
        / "live_gameline_accuracy"
        / f"live_gameline_accuracy_{slug}.jsonl"
    )


def _enabled() -> bool:
    """Default ON with an env kill switch.

    Absent means ENABLED, matching `live_gameline_ledger`. Stated explicitly
    because "absent != off" is a documented trap in this repo: the same edit is
    a no-op or a behaviour change depending on the code's default, and
    `render.yaml` syncs rewrite the whole env block.
    """
    raw = str(os.environ.get("SYNDICATE_LIVE_GAMELINE_ACCURACY_ENABLED") or "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "no", "off"}


def read_rows(path: Path) -> list[dict[str, Any]]:
    """Every row, oldest first. Malformed lines are SKIPPED, not fatal.

    A half-written line (killed mid-append) must not make the whole history
    unreadable -- that would turn an instrumentation hiccup into the loss of
    every night already recorded.
    """
    rows: list[dict[str, Any]] = []
    try:
        if not path.exists():
            return rows
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        return rows
    return rows


def best_by_date(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The most complete row per date -- max `games_with_outcome`, ties to last.

    THE POOLING RULE, in one place. Readers must never average Briers across
    dates unweighted: a 3-game day would count the same as a 15-game day. This
    picks the row to pool; weighting is the caller's job.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        date_str = str(row.get("date") or "").strip()
        if not date_str:
            continue
        current = best.get(date_str)
        if current is None or _games(row) >= _games(current):
            best[date_str] = row
    return best


def _games(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("games_with_outcome") or 0)
    except Exception:
        return 0


def build_row(
    score: Mapping[str, Any],
    *,
    sport: str,
    date_str: str,
    board_generated_at: str = "",
) -> dict[str, Any]:
    """Flatten one `live_gameline_score` payload into a retained row.

    Carries the cuts VERBATIM rather than reducing to a headline number. The
    headline (`model_minus_market_brier`) is meaningless without
    `populations_matched` and the paired `n` beside it -- that was the defect
    `model_paired` was added to fix, and dropping it here would reintroduce it
    one layer down.
    """
    row: dict[str, Any] = {
        "v": ACCURACY_VERSION,
        "sport": str(sport or "").strip().lower(),
        "date": str(date_str or "").strip(),
        "captured_at": _now_iso(),
        "board_generated_at": str(board_generated_at or ""),
        "captured_by": "board_build",
        "games_with_outcome": _games(score),
        "records_considered": score.get("records_considered"),
    }
    for cut in _SCORE_CUTS:
        value = score.get(cut)
        if isinstance(value, Mapping):
            row[cut] = dict(value)
    for extra in ("finals_index", "unscored", "reason"):
        value = score.get(extra)
        if value is not None:
            row[extra] = value
    return row


def append_if_improved(path: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """Append `row` only if it beats what this date already has.

    Returns counters, and NEVER raises -- the caller is a board build.
    """
    counters: dict[str, Any] = {
        "enabled": True,
        "written": 0,
        "skipped_not_improved": 0,
        "previous_best": None,
        "truncated_file_cap": False,
    }
    date_str = str(row.get("date") or "").strip()
    if not date_str:
        counters["error"] = "row_carries_no_date"
        return counters

    existing = read_rows(path)
    previous = best_by_date(existing).get(date_str)
    previous_games = _games(previous) if previous else -1
    counters["previous_best"] = previous_games if previous else None

    # STRICTLY greater. An equal reading is the same slate re-scored by a later
    # build and adds nothing but bytes; the board rebuilds every few minutes and
    # most of those builds see no new final.
    if _games(row) <= previous_games:
        counters["skipped_not_improved"] = 1
        return counters

    if len(existing) >= _MAX_ROWS_PER_FILE:
        # Say so in the counters rather than dropping quietly. A silent cap
        # reads as "that is all that happened", which is the exact failure mode
        # `book_grid_artifact` documents at length.
        counters["truncated_file_cap"] = True
        return counters

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(row), ensure_ascii=False, default=str) + "\n")
    except Exception as exc:  # pragma: no cover - instrumentation must not break the board
        counters["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return counters

    counters["written"] = 1
    return counters


def record_live_gameline_score(
    score: Mapping[str, Any] | None,
    *,
    sport: str,
    date_str: str,
    board_generated_at: str = "",
) -> dict[str, Any]:
    """Retain one build's score. The entry point the board build calls.

    NEVER RAISES. Returns counters that ride the board payload, so a failure is
    attributable from a served surface rather than only from a worker log that
    `logger.info` would not reach anyway.
    """
    if not _enabled():
        return {"enabled": False, "written": 0, "reason": "disabled_by_env"}
    try:
        if not isinstance(score, Mapping):
            return {"enabled": True, "written": 0, "reason": "no_score_payload"}
        # A build with no final game is the NORMAL mid-slate state. Retaining a
        # zero row would be indistinguishable from the collector's 9-hour-late
        # empty capture -- the very thing this module exists to stop recording.
        if _games(score) <= 0:
            return {"enabled": True, "written": 0, "reason": "no_games_with_outcome"}
        row = build_row(
            score, sport=sport, date_str=date_str, board_generated_at=board_generated_at
        )
        counters = append_if_improved(history_path(sport), row)
        counters["games_with_outcome"] = _games(row)
        return counters
    except Exception as exc:  # pragma: no cover - instrumentation must not break the board
        return {"enabled": True, "written": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}
