"""NHL's per-game player log, `player_game_stats.csv`, kept current from the NHL's own API. `#674`.

WHY THIS EXISTS. NHL prop evidence fills its RECENT FORM layer from this file
(`prop_evidence/nhl.py`, and Ask's older `_nhl_last10_evidence`). Its only writer was the
vendor CLI `collect_player_game_stats` (`vendor/nhl_betting_repo/nhl_betting/data/collect.py`),
and nothing called it. Measured 2026-09-18: web held one copy, 1,640 rows from 41 games,
2026-05-01..06-15 (the 2025-26 playoffs), last modified 2026-06-19. The 2026-27 preseason
starts 2026-09-19, so without a producer every NHL prop answer would show last season's
playoffs as "recent form", flagged stale every time.

WHERE IT RUNS. `scripts/refresh_nhl_oddsapi.py` calls `refresh_hosted_game_log` once per NHL
refresh, inside refresh-worker's queued refresh job. That job publishes changed allowlisted
files when it ends (`run_queued_refresh_job.py`), and this module also publishes the file
itself so the reading does not depend on the sweep.

THE PATH IS THE READERS' PATH, NOT THE RUNNER'S. The runner's root on Render is
`<data_root>/nhl_source`, but both readers look in `nhl_source/source_artifacts/data` first
(`prop_evidence.common.sport_roots`), and Ask's older reader looks nowhere else. Writing the
runner's `nhl_source/data/raw/...` would have left the frozen copy shadowing the fresh one.
`nhl_source/source_artifacts/data/raw/player_game_stats.csv` is allowlisted for publishing.

THE FEED, reusing what `bet_status_nhl` measured rather than re-deriving it:
`/v1/score/{date}` lists each game filed under that (Eastern) date, and
`/v1/gamecenter/{id}/boxscore` lists every dressed player. The feed refuses urllib's default
User-Agent. Preseason box scores are full, and preseason games stay `FINAL` (never `OFF`),
so both states count as finished.

THE LEGACY SCHEMA IS KEPT EXACTLY. The columns, the serialized `player` dict
(`{'default': 'B. Gallagher'}`), `team` as the full club name (place + common name) and `date`
as the UTC start are all as the existing rows have them. On the recorded 2025030126 box, this
module reproduces the web file's 40 rows field for field. The one exception is the vendor
parser's zero bug: its `or` chain (`stats.get("shots") or stats.get("sog") or ...`) turned
`sog == 0` into a blank, so skater `shots` and goalie `shotsAgainst` were never 0 (411 blank
skater shots on web, not one `0.0`). New rows write 0, and `repair_legacy_zero_blanks` fixes
the existing ones.
"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

NHLE_BASE = "https://api-web.nhle.com/v1"
USER_AGENT = "syndicate-nhl/1.0"
FETCH_TIMEOUT_SECONDS = 20
COLUMNS = (
    "gamePk", "date", "team", "player_id", "player", "primary_position", "role",
    "shots", "goals", "assists", "blocked", "timeOnIce", "saves", "shotsAgainst", "decision",
)
FINAL_STATES = frozenset({"FINAL", "OFF"})
#: Preseason, regular season, playoffs. The All-Star game and exhibitions are not form.
GAME_TYPES = frozenset({1, 2, 3})
#: How far back a run looks when the file's newest game is older than this. Covers a worker
#: that was down for a week; the offseason gap is never scanned day by day.
LOOKBACK_DAYS = 10
#: Box-score requests per run. A normal night is <= 16 games; a backfill is bounded.
MAX_GAMES_PER_RUN = 120
#: Under `<data_root>/nhl_source`: the path the readers read (see the module docstring).
RELATIVE_PATH = Path("source_artifacts") / "data" / "raw" / "player_game_stats.csv"
PUBLISHED_PATH = "nhl_source/" + RELATIVE_PATH.as_posix()
ENV_SWITCH = "SYNDICATE_NHL_GAME_LOG_REFRESH"

FetchJson = Callable[[str], Any]


def fetch_json(url: str) -> Any:
    """GET -> parsed JSON, or None. Never raises. Sends a User-Agent: the feed 403s without one."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - a missing day must not stop the others
        return None


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("default")
    return str(value or "").strip()


def _cell(value: Any) -> str:
    """A number as the CSV holds it. 0 stays "0": the whole point of the zero-bug fix."""
    if value is None or isinstance(value, bool):
        return ""
    return str(value)


def rows_from_boxscore(box: Any) -> list[dict[str, str]]:
    """Legacy-schema rows for every dressed player in one `/v1/gamecenter/{id}/boxscore`."""
    if not isinstance(box, Mapping) or not isinstance(box.get("playerByGameStats"), Mapping):
        return []
    game_pk = _cell(box.get("id"))
    start = str(box.get("startTimeUTC") or "").strip()
    rows: list[dict[str, str]] = []
    for side in ("homeTeam", "awayTeam"):
        team_block = box.get(side) if isinstance(box.get(side), Mapping) else {}
        team = " ".join(part for part in (_text(team_block.get("placeName")), _text(team_block.get("commonName"))) if part)
        players = box["playerByGameStats"].get(side)
        if not isinstance(players, Mapping):
            continue
        for group in ("forwards", "defense", "goalies"):
            for entry in players.get(group) or []:
                if not isinstance(entry, Mapping) or entry.get("playerId") is None:
                    continue
                goalie = group == "goalies"
                row = {column: "" for column in COLUMNS}
                row.update({
                    "gamePk": game_pk,
                    "date": start,
                    "team": team,
                    "player_id": _cell(entry.get("playerId")),
                    # The legacy file stores the API's WHOLE name object serialized, localized
                    # spellings included ({'default': 'N. Kucherov', 'cs': 'N. Kučerov', ...}).
                    # Both readers take `default`; the rest is kept so old and new rows match.
                    "player": repr(dict(entry["name"])) if isinstance(entry.get("name"), Mapping)
                    else repr({"default": _text(entry.get("name"))}),
                    "primary_position": str(entry.get("position") or ""),
                    "role": "goalie" if goalie else "skater",
                    "timeOnIce": str(entry.get("toi") or ""),
                })
                if goalie:
                    row["saves"] = _cell(entry.get("saves"))
                    row["shotsAgainst"] = _cell(entry.get("shotsAgainst"))
                    row["decision"] = str(entry.get("decision") or "")
                else:
                    row["shots"] = _cell(entry.get("sog"))
                    row["goals"] = _cell(entry.get("goals"))
                    row["assists"] = _cell(entry.get("assists"))
                    row["blocked"] = _cell(entry.get("blockedShots"))
                rows.append(row)
    return rows


def repair_legacy_zero_blanks(rows: Iterable[dict[str, str]]) -> int:
    """Blank skater `shots` / goalie `shotsAgainst` -> "0". Returns how many cells changed.

    Exact, not a guess: the vendor parser's last fallback key for both (`shots`) does not exist
    in the API, so a real 0 fell through to None and every nonzero value survived. The web file
    holds no `0.0` in either column, against 411 blank skater shots.
    """
    changed = 0
    for row in rows:
        role = str(row.get("role") or "").strip().lower()
        column = "shots" if role == "skater" else "shotsAgainst" if role == "goalie" else ""
        if column and str(row.get(column) or "").strip() == "":
            row[column] = "0"
            changed += 1
    return changed


def _game_date(row: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(row.get("date") or "")[:10])
    except ValueError:
        return None


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [{column: str(row.get(column) or "") for column in COLUMNS} for row in csv.DictReader(handle)]


def write_rows_atomic(path: Path, rows: list[dict[str, str]]) -> None:
    """Write via a temp file and `os.replace`: a reader or a publish never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    fd, tmp = tempfile.mkstemp(prefix=".player_game_stats.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(buffer.getvalue())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class UpdateResult:
    path: str
    rows_before: int = 0
    rows_after: int = 0
    days_scanned: list[str] = field(default_factory=list)
    games_added: list[str] = field(default_factory=list)
    games_not_final: int = 0
    games_already_present: int = 0
    unreadable_days: list[str] = field(default_factory=list)
    unreadable_boxes: list[str] = field(default_factory=list)
    repaired_cells: int = 0
    capped: bool = False
    newest_before: str | None = None
    newest_after: str | None = None
    wrote: bool = False

    def summary(self) -> str:
        return (
            f"rows {self.rows_before}->{self.rows_after} games_added={len(self.games_added)} "
            f"days={self.days_scanned[0] + '..' + self.days_scanned[-1] if self.days_scanned else 'none'} "
            f"not_final={self.games_not_final} already={self.games_already_present} "
            f"unreadable_days={len(self.unreadable_days)} unreadable_boxes={len(self.unreadable_boxes)} "
            f"repaired={self.repaired_cells} capped={self.capped} newest {self.newest_before}->{self.newest_after} "
            f"wrote={self.wrote}"
        )


def update_game_log(
    path: Path,
    *,
    today: date,
    fetch: FetchJson = fetch_json,
    base: str = NHLE_BASE,
    lookback_days: int = LOOKBACK_DAYS,
    max_games: int = MAX_GAMES_PER_RUN,
) -> UpdateResult:
    """Add every finished game since the file's newest to `path`, keeping every existing row.

    The window starts at the newest game's date minus a day (a late game may not have been
    final last run) or at `today - lookback_days`, whichever is later, and ends at `today`.
    Games already in the file are skipped by `gamePk`, so a rerun is a no-op.
    """
    from syndicate.features.shared.bet_status_nhl import parse_score_games

    rows = read_rows(path)
    result = UpdateResult(path=str(path), rows_before=len(rows))
    have = {row["gamePk"] for row in rows if row.get("gamePk")}
    dated = [d for d in (_game_date(row) for row in rows) if d is not None]
    newest = max(dated) if dated else None
    result.newest_before = newest.isoformat() if newest else None
    start = today - timedelta(days=max(lookback_days, 0))
    if newest is not None:
        start = max(start, newest - timedelta(days=1))

    added: list[dict[str, str]] = []
    day = start
    while day <= today:
        iso = day.isoformat()
        result.days_scanned.append(iso)
        games = parse_score_games(fetch(f"{base}/score/{iso}"))
        if games is None:
            result.unreadable_days.append(iso)
        for game in games or []:
            game_id = str(game.get("game_id") or "")
            if not game_id or game.get("game_type") not in GAME_TYPES:
                continue
            if game_id in have:
                result.games_already_present += 1
                continue
            if game.get("state") not in FINAL_STATES:
                result.games_not_final += 1
                continue
            if len(result.games_added) >= max_games:
                result.capped = True
                continue
            box_rows = rows_from_boxscore(fetch(f"{base}/gamecenter/{game_id}/boxscore"))
            if not box_rows:
                result.unreadable_boxes.append(game_id)
                continue
            added.extend(box_rows)
            have.add(game_id)
            result.games_added.append(game_id)
        day += timedelta(days=1)

    result.repaired_cells = repair_legacy_zero_blanks(rows)
    merged = rows + added
    merged.sort(key=lambda row: (row.get("date") or "", row.get("gamePk") or ""))
    result.rows_after = len(merged)
    dated_after = [d for d in (_game_date(row) for row in merged) if d is not None]
    result.newest_after = max(dated_after).isoformat() if dated_after else None
    if added or result.repaired_cells:
        write_rows_atomic(path, merged)
        result.wrote = True
    return result


def _eastern_today() -> date:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:  # noqa: BLE001
        return datetime.utcnow().date()


def refresh_hosted_game_log(artifact_root: Path, *, today: date | None = None, fetch: FetchJson = fetch_json) -> dict[str, Any]:
    """The scheduled entry point: update, then publish. Never raises; returns what it did.

    ONLY ON THE HOSTED ROOT. The runner is also called with a local or temporary
    `artifact_root` (tests, a laptop mirror), where there is nothing to publish to. The guard
    is the one `_ensure_season_inputs` uses: the root must be `<data_root>/nhl_source`.

    NEVER PUBLISHES LESS HISTORY THAN WEB HOLDS. With no local copy it first pulls web's
    copy. If that pull FAILS, the run skips rather than publishing a file that would replace
    web's history with tonight's games alone. A pull that succeeds but finds nothing on web
    starts a fresh file.
    """
    status: dict[str, Any] = {"published": None}
    switch = str(os.environ.get(ENV_SWITCH) or "").strip().lower()
    if switch in {"0", "false", "no", "off"}:
        status["skipped"] = f"{ENV_SWITCH}={switch}"
        return _report(status)
    try:
        from syndicate.features.shared import artifact_publisher as publisher

        data_root = Path(publisher._data_root()).resolve()
    except Exception as exc:  # noqa: BLE001
        status["skipped"] = f"no_data_root {type(exc).__name__}"
        return _report(status)
    if Path(artifact_root).resolve() != data_root / "nhl_source":
        status["skipped"] = "root_mismatch"
        return _report(status)

    path = data_root / "nhl_source" / RELATIVE_PATH
    if not path.is_file():
        token = publisher._admin_token()
        url = publisher._export_url(exact_path=PUBLISHED_PATH)
        if not token or not url:
            status["skipped"] = "seed_not_configured"
            return _report(status)
        try:
            ok, written = publisher._pull_hot_artifacts_request(url, token, timeout_seconds=60)
        except Exception as exc:  # noqa: BLE001
            ok, written = False, f"{type(exc).__name__}: {exc}"
        status["seed_pull"] = f"ok={ok},written={written}"
        if not ok:
            status["skipped"] = "seed_pull_failed"
            return _report(status)

    try:
        result = update_game_log(path, today=today or _eastern_today(), fetch=fetch)
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
        return _report(status)
    status["update"] = result.summary()
    if result.wrote:
        try:
            status["published"] = bool(publisher.publish_hot_artifact(path, timeout_seconds=60))
        except Exception as exc:  # noqa: BLE001
            status["published"] = f"error {type(exc).__name__}"
    return _report(status)


def _report(status: dict[str, Any]) -> dict[str, Any]:
    # print, not logger: `logger.info` never reaches Render's log collector (CLAUDE.md).
    print(f"[nhl_runner] NHL_GAME_LOG {' '.join(f'{k}={v}' for k, v in status.items())}", flush=True)
    return status


__all__ = [
    "COLUMNS",
    "PUBLISHED_PATH",
    "RELATIVE_PATH",
    "UpdateResult",
    "fetch_json",
    "read_rows",
    "refresh_hosted_game_log",
    "repair_legacy_zero_blanks",
    "rows_from_boxscore",
    "update_game_log",
    "write_rows_atomic",
]
