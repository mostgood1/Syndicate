"""Persist NFL per-quarter player production, so a live prop model can be FITTED.

WHY THIS IS THE FIRST THING BUILT, and why it is urgent in a way nothing else in
this lane is. An empirical live prop model needs the distribution of a player's
REMAINING production given the quarter and what he has already done. ESPN's
public summary cannot supply that historically: `drives.previous[].plays[]`
carries `period` and `clock`, but `participants` is ABSENT on every play
(measured 2026-09-27, all 169 plays of event 401772510) -- only
`teamParticipants`, `statYardage`, `type` and free `text`. `boxscore.players` is
FINAL-only. Reconstructing it means parsing play text and joining abbreviated
names, which is fragile and is how silent wrong numbers get made.

Meanwhile `live_player_box` already fetches exactly the right rows during a live
game -- and its cache is IN-MEMORY ONLY (`_cache`, TTL, capped at 64 entries).
**So every live slate generates the dataset and throws it away.** A slate not
captured is gone: there is no backfill. That is the whole argument for writing
this before any model.

QUARTER BOUNDARIES ONLY, and that is a cost decision as much as a design one.
`#241` restarted production in a loop over periodic worker work, so this captures
one snapshot per (event, period) rather than one per tick: roughly 16 games x 3
boundaries x ~40 players per slate instead of a row every time the loop comes
round. It is also the shape the fit wants, because it matches the cutoff-replay
methodology the game-line models are graded with -- the score is exact and the
clock is 0:00, so nothing has to be interpolated.

WHAT IT DOES NOT DO. It does not project or price anything. It writes
observations to disk and pushes the file to the web service so it can be
retrieved. The model that reads them is a separate, gradeable piece of work, and
building this first is what makes that work possible at all.

IT DID NOT ALWAYS PUSH, and the gap is worth recording because it was one
verification away from being reported as done. Allowlisting the path in
`HOT_ARTIFACT_PATTERNS` makes it ELIGIBLE to cross services and moves no bytes:
the capture is written on refresh-worker, which serves no HTTP, while
`/api/ops/artifacts/stream` reads WEB's disk. See `publish_snapshot`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "CAPTURE_SCHEMA_VERSION",
    "capture_enabled",
    "capture_path",
    "default_capture_dir",
    "snapshot_rows",
    "record_quarter_snapshot",
    "publish_snapshot",
]

CAPTURE_SCHEMA_VERSION = 1

# The boundaries worth capturing. Q4's boundary is the FINAL score, which the
# box score already gives us for free, so capturing it would duplicate a source
# that is not lossy. 1..3 are the cutoffs a model would ever be asked about.
CAPTURE_PERIODS = (1, 2, 3)

# The fields a prop model needs, and only those. `live_player_box` merges ESPN's
# stat groups into these names already; re-deriving them here would be a second
# copy of a mapping that is allowed to change.
# EXACTLY `live_player_box._ROW_FIELDS`, verified against it rather than guessed.
# The first version invented plausible names -- `pass_completions`,
# `interceptions`, `total_yards`, `td_scored` -- none of which the producer emits
# (`completions`, `pass_int`, and no derived totals on the UNFILTERED grading
# rows). Guessing a producer's field names is how a capture writes rows with
# every stat missing and still looks like it worked.
CAPTURED_FIELDS = (
    "pass_yards", "rush_yards", "rec_yards",
    "pass_td", "rush_td", "rec_td",
    "completions", "pass_attempts", "pass_int",
    "rush_attempts", "receptions", "targets",
)


def capture_enabled() -> bool:
    """DEFAULT ON, and stated because the code's default is what decides.

    CLAUDE.md's standing rule is that absent is not off. Here absent is ON: the
    cost of a missed slate is permanent (there is no backfill) while the cost of
    an unwanted capture is a small file, so the asymmetry points at collecting.
    `off`/`0`/`false`/`no` disables it without a deploy.
    """
    raw = str(os.environ.get("SYNDICATE_NFL_PROP_CAPTURE") or "").strip().lower()
    return raw not in {"off", "0", "false", "no"}


def default_capture_dir() -> Path:
    """Where captures are WRITTEN. `nfl_artifact_output_root`, not the read root.

    THE FIRST VERSION OF THIS WAS WRONG AND SHIPPED WRONG, which is why the
    correction is stated here rather than quietly swapped. It used
    `default_nfl_source_root()`, whose docstring says in terms that it resolves
    a root by PROBING for `upcoming_recs_*.csv` -- an unrelated artifact family
    the repo mirror ships and the mounted disk does not. `#389`/`#441` measured
    that exact selector sending NFL writes to

        /opt/render/project/src/data/nfl_source     <- the CHECKOUT, ephemeral

    instead of `/opt/render/project/data/nfl_source`, the mounted disk, so every
    run wrote a real artifact somewhere nothing reads and every deploy discarded
    it. A capture is the worst possible thing to put there: the data cannot be
    regenerated, so a wiped capture is not a stale artifact, it is a lost slate.

    `nfl_artifact_output_root()` is the write-side twin that exists for this --
    env var, else the shared data root, NO filesystem probing.
    """
    from syndicate.features.nfl.sources import nfl_artifact_output_root

    return nfl_artifact_output_root() / "live_prop_capture"


def capture_path(data_root: Any, date_str: str) -> Path:
    """One JSONL per date, beside the other NFL source data.

    JSONL rather than JSON because this is APPENDED to during a slate by a
    process that may be restarted at any moment -- refresh-worker terminated 8
    times in 16.8 h on 2026-09-27. A partially written JSON array is unreadable;
    a partially written JSONL file loses at most its last line.
    """
    return Path(data_root) / "live_prop_capture" / f"{date_str}.jsonl"


def snapshot_rows(
    *,
    event_id: str,
    period: int,
    date_str: str,
    player_rows: Iterable[Mapping[str, Any]],
    home_score: Any = None,
    away_score: Any = None,
    clock_seconds: Any = None,
) -> list[dict[str, Any]]:
    """The rows that WOULD be written, without writing them.

    Split out from the write so the shape can be tested without a filesystem,
    and so a caller can count what it is about to persist.
    """
    if int(period) not in CAPTURE_PERIODS:
        return []
    out: list[dict[str, Any]] = []
    for row in player_rows or ():
        # `player_name` IS THE PRODUCER'S KEY, and this cost the first real
        # boundary of the night. `_merged_player_rows` builds
        # `{"player_name": ..., "team_abbr": ...}`; this looked for `player`/
        # `name`, matched nothing, dropped EVERY row, and wrote an empty file --
        # while the tick reported `captured=1`, because the caller did not check
        # what the writer returned. Two failures stacked: a wrong field name and
        # a success signal that was not one.
        name = str(row.get("player_name") or row.get("player")
                   or row.get("name") or "").strip()
        if not name:
            # NO SYNTHETIC KEY. A row that cannot be joined back to a player is
            # not a cheap observation, it is an unattributable one, and it would
            # pollute a per-player fit permanently.
            continue
        rec: dict[str, Any] = {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "date": str(date_str),
            "event_id": str(event_id),
            "period": int(period),
            "player": name,
            "team": str(row.get("team_abbr") or row.get("team") or "").strip() or None,
        }
        if home_score is not None:
            rec["home_score_at"] = int(home_score)
        if away_score is not None:
            rec["away_score_at"] = int(away_score)
        if clock_seconds is not None:
            # HOW CLOSE TO THE BOUNDARY THIS ACTUALLY IS. The capture fires
            # inside a window before the quarter ends rather than exactly at
            # 0:00, because a tick can miss the instant. Recording it lets the
            # fit filter to genuine boundaries instead of assuming every row is
            # one -- an assumption that would quietly mix mid-quarter
            # observations into a cutoff distribution.
            rec["clock_seconds_at"] = int(clock_seconds)
        for field in CAPTURED_FIELDS:
            value = row.get(field)
            if value is not None:
                rec[field] = value
        out.append(rec)
    return out


def publish_snapshot(path: Path) -> bool:
    """Push the capture file to the web service. Best effort, never raises.

    WHY THIS EXISTS AS A SEPARATE STEP, and why allowlisting alone was not
    enough. Adding `nfl_source/live_prop_capture/*.jsonl` to
    `HOT_ARTIFACT_PATTERNS` makes the path ELIGIBLE to cross services. It does
    not move a byte. The three services hold three separate disks: this file is
    written on refresh-worker, which runs `scripts/run_refresh_worker.py` and
    serves no HTTP at all, while `/api/ops/artifacts/stream` is served by web
    off WEB's disk. Without an explicit push the capture is as unreachable
    allowlisted as it was unallowlisted -- the only difference being that the
    retrieval attempt would now return 404 instead of 403, which is a WORSE
    failure because it reads as "the capture did not happen".

    That distinction is the whole reason this is written out rather than
    assumed: presence is not reachability, and the allowlist commit was one
    verification away from being reported as "the captures are retrievable".

    WHOLE FILE, NOT A TAIL. The file only ever grows, but `_is_append_only` is a
    deliberately tiny explicit list gated on `/book_quotes/` and it is not
    extended here. An append-only assumption applied to the wrong family
    concatenates two versions into corruption; a whole-file publish of a ~40-row
    snapshot is cheap and cannot. The cost is re-sending the day's accumulated
    rows at each of ~48 boundaries per slate, which the publish budget bounds on
    its own.
    """
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        ok = bool(publish_hot_artifact(Path(path)))
        print(f"[nfl_prop_capture] PUBLISH {'OK' if ok else 'REFUSED'} path={path}",
              flush=True)
        return ok
    except Exception as exc:  # noqa: BLE001
        # A failed publish costs a retrieval, not an observation -- the rows are
        # already on the mounted disk. Losing the tick would cost a board.
        print(f"[nfl_prop_capture] PUBLISH_FAILED path={path} "
              f"{type(exc).__name__}: {exc}", flush=True)
        return False


def record_quarter_snapshot(
    data_root: Any,
    *,
    event_id: str,
    period: int,
    date_str: str,
    player_rows: Iterable[Mapping[str, Any]],
    home_score: Any = None,
    away_score: Any = None,
    clock_seconds: Any = None,
) -> int:
    """Append one (event, period) snapshot. Returns rows written. NEVER raises.

    IDEMPOTENT PER (event, period). The loop comes round every tick and a game
    sits at "end of Q2" for as long as halftime lasts, so without this a single
    boundary would be written dozens of times and the fit would weight that game
    dozens of times over. The marker is a sibling `.done` file rather than a
    re-read of the JSONL, because re-reading grows linearly with the slate while
    the check has to run on every tick.

    A capture must never be able to break the tick that carries it, so every
    failure is printed and swallowed -- the same posture as the memory
    heartbeat. Losing a snapshot is a lost observation; raising would be a lost
    board.
    """
    if not capture_enabled():
        return 0
    try:
        rows = snapshot_rows(event_id=event_id, period=period, date_str=date_str,
                             player_rows=player_rows,
                             home_score=home_score, away_score=away_score,
                             clock_seconds=clock_seconds)
        if not rows:
            return 0
        path = capture_path(data_root, date_str)
        marker = path.with_suffix(f".{event_id}.p{int(period)}.done")
        if marker.exists():
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for rec in rows:
                handle.write(json.dumps(rec, sort_keys=True) + "\n")
        # WRITTEN AFTER the rows, so a crash between them re-captures rather
        # than silently skipping. A duplicated snapshot is detectable in the
        # data; a missing one is not.
        marker.write_text("", encoding="utf-8")
        print(f"[nfl_prop_capture] CAPTURED event={event_id} period={int(period)} "
              f"rows={len(rows)} path={path}", flush=True)
        publish_snapshot(path)
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        print(f"[nfl_prop_capture] CAPTURE_FAILED event={event_id} "
              f"period={period} {type(exc).__name__}: {exc}", flush=True)
        return 0
