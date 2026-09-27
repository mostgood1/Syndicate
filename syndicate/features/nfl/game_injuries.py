"""NFL GAME-DAY injury statuses, captured per game from ESPN's game summary.

WHY THIS EXISTS (lane `nfl-game-day-injuries`, 2026-09-27). The only NFL injury
input was nflverse's season CSV (`fetch_nfl_injuries.py`), which follows the
PRACTICE REPORTS -- Wednesday to Friday designations. Nothing captured what
changes on game day, which is exactly the window the starting-soon phase
(`slate_phase.py`) exists for: a Questionable player ruled Out 90 minutes before
kickoff moves props, and the board priced him as Questionable.

THE SOURCE AND WHAT IS KNOWN ABOUT IT. ESPN's public game summary
(`/apis/site/v2/sports/football/nfl/summary?event=<id>`) carries a top-level
`injuries` list -- one entry per team, each with rows of `athlete`, `status`,
`type`, `details`, `date`. That SHAPE is confirmed from 132 cached ESPN
summaries in `vendor/*/data/processed/_espn_cache/` (same endpoint family,
other sports). What those rows ARE is the team injury report: across all 132,
the statuses were only `Out` (430) and `Day-To-Day` (59), and the word
"inactive" never appears. So:

  * CONFIRMED: a game-day Out / Doubtful / Questionable change is captured.
  * NOT CONFIRMED: whether ESPN adds a player to this list, or flips his
    status, when teams publish INACTIVES ~90 min before kickoff. A healthy
    scratch is not an injury and may never appear. `site.api.espn.com` was
    blocked from the session that built this, so no live NFL payload was read.

Every unknown fails LOUD rather than empty: a summary without the expected
shape is counted as `shape_unknown` and printed, so "ESPN changed its format"
cannot read as "no injuries today".

No custom User-Agent is sent -- `fetch_espn_live_status_for_date.py` records
that ESPN returns 403 to browser-like UA strings from Render's IP.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={compact_date}"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"

#: Capture from T-3h -- the starting-soon window -- until shortly after kickoff,
#: so a late scratch announced at the whistle is still caught.
DEFAULT_WINDOW_BEFORE_SECONDS = 3 * 3600
DEFAULT_WINDOW_AFTER_SECONDS = 15 * 60


def _env_int(name: str, default: int, env: Mapping[str, str] | None = None) -> int:
    raw = str((os.environ if env is None else env).get(name) or "").strip()
    try:
        return max(0, int(raw)) if raw else default
    except ValueError:
        return default


def window_seconds(env: Mapping[str, str] | None = None) -> tuple[int, int]:
    return (
        _env_int("NFL_GAME_INJURIES_WINDOW_BEFORE_SECONDS", DEFAULT_WINDOW_BEFORE_SECONDS, env),
        _env_int("NFL_GAME_INJURIES_WINDOW_AFTER_SECONDS", DEFAULT_WINDOW_AFTER_SECONDS, env),
    )


@dataclass(frozen=True)
class GameEvent:
    event_id: str
    start_epoch: float
    name: str


@dataclass(frozen=True)
class InjuryRow:
    event_id: str
    team_id: str
    team_abbr: str
    athlete_id: str
    athlete_name: str
    position: str
    status: str
    status_type: str
    fantasy_status: str
    injury_type: str
    detail: str

    def key(self) -> tuple[str, str]:
        return (self.team_id, self.athlete_id or self.athlete_name)


def _parse_iso_epoch(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def parse_scoreboard_events(payload: Any) -> list[GameEvent]:
    """Every event with an id and a parsable start time, soonest first."""
    events = payload.get("events") if isinstance(payload, dict) else None
    out: list[GameEvent] = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip()
        start = _parse_iso_epoch(event.get("date"))
        if event_id and start is not None:
            out.append(GameEvent(event_id, start, str(event.get("shortName") or event.get("name") or "")))
    return sorted(out, key=lambda item: item.start_epoch)


def events_in_window(
    events: Iterable[GameEvent], *, now_epoch: float, env: Mapping[str, str] | None = None
) -> list[GameEvent]:
    before, after = window_seconds(env)
    return [event for event in events if -after <= (event.start_epoch - now_epoch) <= before]


def _text(value: Any) -> str:
    return str(value or "").strip()


def parse_summary_injuries(payload: Any, event_id: str) -> tuple[list[InjuryRow], bool]:
    """(rows, shape_ok). `shape_ok` is False when the payload is not a summary
    with an `injuries` LIST -- which is different from an empty list (a game with
    nobody on the report), and must not be mistaken for it."""
    if not isinstance(payload, dict) or not isinstance(payload.get("injuries"), list):
        return [], False
    rows: list[InjuryRow] = []
    for team_entry in payload["injuries"]:
        if not isinstance(team_entry, dict):
            continue
        team = team_entry.get("team") if isinstance(team_entry.get("team"), dict) else {}
        for row in team_entry.get("injuries") or []:
            if not isinstance(row, dict):
                continue
            athlete = row.get("athlete") if isinstance(row.get("athlete"), dict) else {}
            position = athlete.get("position") if isinstance(athlete.get("position"), dict) else {}
            status_type = row.get("type") if isinstance(row.get("type"), dict) else {}
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            fantasy = details.get("fantasyStatus") if isinstance(details.get("fantasyStatus"), dict) else {}
            rows.append(
                InjuryRow(
                    event_id=str(event_id),
                    team_id=_text(team.get("id")),
                    team_abbr=_text(team.get("abbreviation")),
                    athlete_id=_text(athlete.get("id")),
                    athlete_name=_text(athlete.get("displayName")),
                    position=_text(position.get("abbreviation")),
                    status=_text(row.get("status")),
                    status_type=_text(status_type.get("name")),
                    fantasy_status=_text(fantasy.get("abbreviation")),
                    injury_type=_text(details.get("type")),
                    detail=_text(details.get("detail")),
                )
            )
    rows.sort(key=lambda r: (r.team_abbr, r.athlete_name, r.athlete_id))
    return rows, True


def diff_rows(previous: Iterable[Mapping[str, Any]], current: Iterable[InjuryRow]) -> list[dict[str, Any]]:
    """Per-player changes: added to the list, removed from it, or status moved."""
    before = {(str(r.get("team_id") or ""), str(r.get("athlete_id") or r.get("athlete_name") or "")): r for r in previous}
    after = {row.key(): row for row in current}
    changes: list[dict[str, Any]] = []
    for key, row in after.items():
        old = before.get(key)
        if old is None:
            changes.append({"change": "added", **asdict(row)})
        elif str(old.get("status") or "") != row.status:
            changes.append({"change": "status", "from": old.get("status"), **asdict(row)})
    for key, old in before.items():
        if key not in after:
            changes.append({"change": "removed", **dict(old)})
    return changes


# ---------------------------------------------------------------------------
# Storage. Under `nfl_artifact_output_root()` -- the MOUNTED disk on Render, not
# the ephemeral checkout (`#389`) -- because the refresh-worker tick that reads
# `statuses_<date>.json` runs on the same service that writes it.
# ---------------------------------------------------------------------------


def game_injuries_dir(date_str: str) -> Path:
    from syndicate.features.nfl.sources import nfl_artifact_output_root

    return nfl_artifact_output_root() / "tracking" / "espn" / "game_injuries" / str(date_str)


def statuses_path(date_str: str) -> Path:
    """The file the starting-soon trigger fingerprints. Content is statuses ONLY
    -- no timestamps -- so it changes exactly when a status does."""
    return game_injuries_dir(date_str) / f"statuses_{date_str}.json"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def record_game(date_str: str, event: GameEvent, rows: list[InjuryRow], *, captured_at: str) -> list[dict[str, Any]]:
    """Write the game's latest snapshot and append any changes to the log.
    Returns the changes (empty on first sight of a game: a baseline, not news)."""
    directory = game_injuries_dir(date_str)
    snapshot_path = directory / f"{event.event_id}.json"
    previous = _read_json(snapshot_path)
    changes = diff_rows(previous.get("rows") or [], rows) if isinstance(previous, dict) else []
    _atomic_write_text(
        snapshot_path,
        json.dumps(
            {"event_id": event.event_id, "name": event.name, "start_epoch": event.start_epoch,
             "captured_at": captured_at, "rows": [asdict(r) for r in rows]},
            sort_keys=True,
        ),
    )
    if changes:
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "changes.jsonl", "a", encoding="utf-8") as handle:
            for change in changes:
                handle.write(json.dumps({"captured_at": captured_at, "event_name": event.name, **change}, sort_keys=True) + "\n")
    return changes


def rebuild_statuses(date_str: str) -> bool:
    """Rewrite `statuses_<date>.json` from every game snapshot of the date, and
    only if its content changed. Returns True when it was rewritten."""
    directory = game_injuries_dir(date_str)
    combined: dict[str, list[dict[str, str]]] = {}
    for snapshot in sorted(directory.glob("*.json")) if directory.exists() else []:
        if snapshot.name.startswith("statuses_"):
            continue
        payload = _read_json(snapshot)
        if not isinstance(payload, dict):
            continue
        combined[str(payload.get("event_id") or snapshot.stem)] = [
            {"team": r.get("team_abbr", ""), "athlete_id": r.get("athlete_id", ""), "name": r.get("athlete_name", ""), "status": r.get("status", "")}
            for r in payload.get("rows") or []
            if isinstance(r, dict)
        ]
    text = json.dumps(combined, sort_keys=True, indent=1)
    path = statuses_path(date_str)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    _atomic_write_text(path, text)
    return True
