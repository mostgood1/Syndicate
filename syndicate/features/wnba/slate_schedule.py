"""Does the WNBA schedule put a game on DATE?  The per-date gate for polls that ask web about a slate.

`[2026-11-17, lane wnba-boxscore-polling-per-date]`

WHY THIS EXISTS
---------------
In the WNBA offseason two production loops kept asking fleet web about dates with
no WNBA games on them:

  * live-odds-worker's live-lens tick (`live_lens_loop._run_live_lens_tick`) ->
    `GET /wnba/api/live_player_boxscore?date=<today>` every ~1.5 min: ~1,000-1,160 a
    day, each an empty 199-byte answer costing a web worker 0.7 s (p50) to 1.1 s (p90);
  * refresh-worker's settlement pass (`intelligence_state._refresh_wnba_boxscores`) ->
    `GET /wnba/api/final_player_boxscore?date=<today|yesterday>&count_only=1` every
    ~3 min: ~550-770 a day.

Measured from the fleet's web.log, 2026-10-31..2026-11-17: 29,449 of 100,005 web
requests (29.4%) were these two routes; on 2026-11-17 to 3:39 PM CST, 1,614 of 2,408
(67.0%). Web workers recycle for memory about once per 10 requests, so it is the
request COUNT these cost, not their size.

PER DATE, NEVER PER SPORT OR SEASON
-----------------------------------
The user's rule is that every line and every date is its own decision. There is no
"season over" flag here and no sport switch: a date is skipped only when the
schedule for its year is readable, has rows, and lists no game on that date. The
next date with a game is polled exactly as before.

THE SOURCE
----------
`<data root>/wnba_source/data/processed/schedule_<YYYY>.csv`, which the WNBA
refresh's `fetch-schedule` (`syndicate/features/wnba/source_cli/cli.py`) rewrites
from ESPN on every run. Fleet copy read 2026-11-17: mtime 3:34 PM CST, 374 rows,
2026-04-25..2026-10-31, the playoff dates included, 0 rows on 2026-11-17.

NOT the published cards context on its own. On 2026-11-17 the context for that
date said `games: []`, but its `source_path` (`game_cards_2026-11-17.csv`) did not
exist on disk, so an empty context can mean "no card source", and that is not "no
games". Absent is not empty. The context is used one way only: when it has games
on a date the schedule calls empty, the date is POLLED (`cards_context_has_games`).

UNKNOWN NEVER SKIPS
-------------------
Any of these is UNKNOWN (`games is None`), and callers poll exactly as before and
log the reason by name:

  * the date does not parse (`bad_date`);
  * the data root is unavailable (`data_root_unavailable`);
  * the schedule file is absent (`schedule_absent`) or unreadable (`schedule_unreadable`);
  * it has no data rows (`schedule_empty`);
  * it has neither date column (`schedule_no_date_columns`);
  * a row carries no date at all (`schedule_undated_rows`).

An unreadable slate must not quietly turn polling off for a date that has games
(`learnings`: unknown must not default permissive).

COUNTING LEANS TOWARDS POLLING. A row counts for DATE if `date_est` OR `date_utc`
equals it, because an evening game's UTC date is the next day. Every status counts,
postponed included. Over-counting costs one poll; under-counting could skip a live
game.

Stdlib only at import time: `live_lens_loop` and `intelligence_state` import this on
their hot paths, and the check that dates were read correctly runs against the fleet
file with a bare `python3`.
"""

from __future__ import annotations

import csv
import io
import os
import threading
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import Any

#: Read in this order; a row counts for a date if EITHER matches (see the module docstring).
SCHEDULE_DATE_COLUMNS = ("date_est", "date_utc")

REASON_HAS_GAMES = "schedule_has_games"
REASON_NO_GAMES = "schedule_has_no_games"
REASON_CONTEXT_HAS_GAMES = "cards_context_has_games"


def schedule_relative_path(date_str: str) -> str:
    """Relative to the data root -- the same tree `fetch-schedule` writes and the boxscore producer uses."""
    return f"wnba_source/data/processed/schedule_{str(date_str).strip()[:4]}.csv"


@dataclass(frozen=True)
class SlateVerdict:
    """What the schedule says about one date. `games is None` means UNKNOWN: poll."""

    date: str
    games: int | None
    reason: str
    schedule_path: str = ""
    schedule_rows: int | None = None
    detail: str = ""

    @property
    def skip(self) -> bool:
        """True ONLY for a readable schedule that lists no game on the date."""
        return self.games == 0

    @property
    def unknown(self) -> bool:
        return self.games is None

    def log_fields(self) -> str:
        parts = [
            f"reason={self.reason}",
            f"games={'unknown' if self.games is None else self.games}",
            f"schedule={Path(self.schedule_path).name if self.schedule_path else 'none'}",
        ]
        if self.schedule_rows is not None:
            parts.append(f"schedule_rows={self.schedule_rows}")
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)


@dataclass(frozen=True)
class _ScheduleIndex:
    rows: int
    by_date: dict[str, int]
    undated_rows: int
    has_date_columns: bool


# (path, mtime_ns, size) -> index. A rewrite changes mtime, so a fresh `fetch-schedule`
# is picked up on the next call; an unchanged file is parsed once per process, not once
# per tick.
_INDEX_MEMO: dict[tuple[str, int, int], _ScheduleIndex] = {}
_INDEX_LOCK = threading.Lock()


def _parse_schedule(text: str) -> _ScheduleIndex:
    reader = csv.DictReader(io.StringIO(text))
    fields = [str(name or "").strip() for name in (reader.fieldnames or [])]
    columns = [column for column in SCHEDULE_DATE_COLUMNS if column in fields]
    by_date: dict[str, int] = {}
    rows = 0
    undated = 0
    for row in reader:
        if not isinstance(row, dict) or not any(str(value or "").strip() for value in row.values()):
            continue  # a blank line is not a game
        rows += 1
        dates = {str(row.get(column) or "").strip()[:10] for column in columns}
        dates.discard("")
        if not dates:
            undated += 1
            continue
        for value in dates:
            by_date[value] = by_date.get(value, 0) + 1
    return _ScheduleIndex(rows=rows, by_date=by_date, undated_rows=undated, has_date_columns=bool(columns))


def _load_index(path: Path) -> _ScheduleIndex:
    stat = os.stat(path)  # FileNotFoundError is the caller's `schedule_absent`
    key = (str(path), int(stat.st_mtime_ns), int(stat.st_size))
    with _INDEX_LOCK:
        cached = _INDEX_MEMO.get(key)
    if cached is not None:
        return cached
    index = _parse_schedule(path.read_text(encoding="utf-8"))
    with _INDEX_LOCK:
        # One file per year at most is live; drop older spellings of the same path.
        for stale in [k for k in _INDEX_MEMO if k[0] == key[0]]:
            _INDEX_MEMO.pop(stale, None)
        _INDEX_MEMO[key] = index
    return index


def _default_data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root())


def _cards_context_game_count(date_str: str) -> int | None:
    """Games in the PUBLISHED cards context for the date, or None when there is none / it is unreadable.

    Only ever used to OVERRULE a 0-game schedule (see the module docstring), never to
    skip. Reached only on dates the schedule calls empty, where the context is either
    absent or a ~250-byte `games: []`, so it adds no cost on a game day.
    """
    try:
        from syndicate.features.wnba.cards import load_published_cards_page_context

        payload, _age, _stale = load_published_cards_page_context(date_str)
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
        return None
    if str(payload.get("date") or date_str).strip() != str(date_str).strip():
        return None  # another date's slate says nothing about this one
    return len(payload["games"])


def wnba_slate_verdict(
    date_str: str,
    *,
    data_root: Path | None = None,
    corroborate_with_cards_context: bool = True,
) -> SlateVerdict:
    """The per-date verdict. NEVER RAISES: a failure is an UNKNOWN verdict, which polls."""
    date_text = str(date_str or "").strip()
    try:
        _date.fromisoformat(date_text)
    except (TypeError, ValueError):
        return SlateVerdict(date=date_text, games=None, reason="bad_date")

    try:
        root = Path(data_root) if data_root is not None else _default_data_root()
    except Exception as exc:  # noqa: BLE001
        return SlateVerdict(date=date_text, games=None, reason="data_root_unavailable",
                            detail=type(exc).__name__)
    path = root / schedule_relative_path(date_text)

    try:
        index = _load_index(path)
    except FileNotFoundError:
        return SlateVerdict(date=date_text, games=None, reason="schedule_absent", schedule_path=str(path))
    except Exception as exc:  # noqa: BLE001 -- OSError, UnicodeError, csv.Error: all UNKNOWN
        return SlateVerdict(date=date_text, games=None, reason="schedule_unreadable",
                            schedule_path=str(path), detail=type(exc).__name__)

    def _verdict(games: int | None, reason: str, detail: str = "") -> SlateVerdict:
        return SlateVerdict(date=date_text, games=games, reason=reason, schedule_path=str(path),
                            schedule_rows=index.rows, detail=detail)

    if not index.has_date_columns:
        return _verdict(None, "schedule_no_date_columns")
    if index.rows <= 0:
        return _verdict(None, "schedule_empty")
    games = int(index.by_date.get(date_text, 0))
    if games > 0:
        return _verdict(games, REASON_HAS_GAMES)
    if index.undated_rows:
        # A row with no date could be on THIS date. Not a skip.
        return _verdict(None, "schedule_undated_rows", detail=f"undated={index.undated_rows}")
    if corroborate_with_cards_context:
        context_games = _cards_context_game_count(date_text)
        if context_games:
            return _verdict(context_games, REASON_CONTEXT_HAS_GAMES, detail="schedule_has_none")
    return _verdict(0, REASON_NO_GAMES)


def _clear_memo_for_tests() -> None:
    with _INDEX_LOCK:
        _INDEX_MEMO.clear()


__all__: list[Any] = [
    "SCHEDULE_DATE_COLUMNS",
    "SlateVerdict",
    "schedule_relative_path",
    "wnba_slate_verdict",
]
