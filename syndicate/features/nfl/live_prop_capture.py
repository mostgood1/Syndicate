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

WHAT IT DOES NOT DO. It does not project, price, or publish anything. It writes
observations to disk. The model that reads them is a separate, gradeable piece of
work, and building this first is what makes that work possible at all.
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
    "snapshot_rows",
    "record_quarter_snapshot",
]

CAPTURE_SCHEMA_VERSION = 1

# The boundaries worth capturing. Q4's boundary is the FINAL score, which the
# box score already gives us for free, so capturing it would duplicate a source
# that is not lossy. 1..3 are the cutoffs a model would ever be asked about.
CAPTURE_PERIODS = (1, 2, 3)

# The fields a prop model needs, and only those. `live_player_box` merges ESPN's
# stat groups into these names already; re-deriving them here would be a second
# copy of a mapping that is allowed to change.
CAPTURED_FIELDS = (
    "pass_yards", "rush_yards", "rec_yards", "total_yards",
    "receptions", "pass_td", "rush_td", "rec_td", "td_scored",
    "pass_attempts", "pass_completions", "rush_attempts", "targets",
    "interceptions",
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


def capture_path(data_root: Any, date_str: str) -> Path:
    """One JSONL per date, beside the other NFL source data.

    JSONL rather than JSON because this is APPENDED to during a slate by a
    process that may be restarted at any moment -- refresh-worker terminated 8
    times in 16.8 h on 2026-09-27. A partially written JSON array is unreadable;
    a partially written JSONL file loses at most its last line.
    """
    return Path(data_root) / "nfl_source" / "live_prop_capture" / f"{date_str}.jsonl"


def snapshot_rows(
    *,
    event_id: str,
    period: int,
    date_str: str,
    player_rows: Iterable[Mapping[str, Any]],
    home_score: Any = None,
    away_score: Any = None,
) -> list[dict[str, Any]]:
    """The rows that WOULD be written, without writing them.

    Split out from the write so the shape can be tested without a filesystem,
    and so a caller can count what it is about to persist.
    """
    if int(period) not in CAPTURE_PERIODS:
        return []
    out: list[dict[str, Any]] = []
    for row in player_rows or ():
        name = str(row.get("player") or row.get("name") or "").strip()
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
            "team": str(row.get("team") or "").strip() or None,
        }
        if home_score is not None:
            rec["home_score_at"] = int(home_score)
        if away_score is not None:
            rec["away_score_at"] = int(away_score)
        for field in CAPTURED_FIELDS:
            value = row.get(field)
            if value is not None:
                rec[field] = value
        out.append(rec)
    return out


def record_quarter_snapshot(
    data_root: Any,
    *,
    event_id: str,
    period: int,
    date_str: str,
    player_rows: Iterable[Mapping[str, Any]],
    home_score: Any = None,
    away_score: Any = None,
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
                             home_score=home_score, away_score=away_score)
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
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        print(f"[nfl_prop_capture] CAPTURE_FAILED event={event_id} "
              f"period={period} {type(exc).__name__}: {exc}", flush=True)
        return 0
