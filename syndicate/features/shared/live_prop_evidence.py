"""Live player-prop evidence: Phase 1B M1, live stat progress (lane `live-props-evidence`, 2026-11-10).

WHY. The NBA live re-sim publishes `liveProps` on every game it re-sims (`nba/live_resim.py build_live_props`): per
player, stat and line, the banked actual, the live projection and P(over) from the rest-of-game draws. Like the rest
of the snapshot it is OVERWRITTEN each tick, so a learner has no record of what the model said about a player's pace
at any instant. The plan (`docs/ai_context/plan_one_engine_pregame_live.md` section 4, item 2) ranks live props from
stat progress second among the places the engine can plausibly pay, and M2 needs weeks of logged evidence.

WHAT. The M0 collector (`live_evidence_log.Collector`) already reads each live snapshot through the shared store every
~30 s. On each new tick it now also hands the snapshot here, and one row per GAME is appended to
`<data root>/live_evidence/<sport>/<date>.props.jsonl` whenever that game's props content changed. The lane rows in
`<date>.jsonl` are untouched, and the props row carries the same `t` / `event_id`, so a reader joins the game state
from the lane row at the same `t`.

COMPACT AND LOSSLESS. A raw tick is large: the NBA snapshot measured 1.09-1.34 MB per write on 2026-11-10 01:52-02:22Z,
one write every ~2.5 min, because each posted line is published with +-3 neighbour lines. Rows are grouped by
(playerName, prop); a group's fields that are equal on every row are stored once (`f`), the fields that vary are
stored as columns (`c`) with one value list per row (`r`), and a field only some rows carry (`unpricedReason`,
`quotePulled`, `liveDisplayProbOver`) rides as a trailing dict on that row. `expand_props` rebuilds the published rows
exactly, as a multiset (the order of rows within a game is not kept). Nothing here knows NBA's field names: any sport
whose snapshot the collector reads gets the same treatment with no code change.

Local disk only, never the keyvalue store, never on a request path. A failure is printed by the collector and
swallowed. `SYNDICATE_LIVE_EVIDENCE_PROPS=off` turns this half off (absent = on: it only appends local files); the
M0 switch `SYNDICATE_LIVE_EVIDENCE_LOG=off` stops the collector and therefore this too.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional

from syndicate.features.shared.live_evidence_log import _data_root, _parse, _scalar, _snapshot_t

SCHEMA_VERSION = 1
PROPS_ENV = "SYNDICATE_LIVE_EVIDENCE_PROPS"
# The game keys that carry live prop content (`nba/live_lens.py _NATIVE_RESIM_GAME_KEYS`, wnba lens).
GAME_KEYS: tuple[str, ...] = ("liveProps", "livePropsCoverage", "livePropsRefusal")
# A bound, not a budget: the largest measured NBA SNAPSHOT (all games, every key) was 1.34 MB.
ROW_MAX_BYTES = 2_000_000


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(PROPS_ENV) or "").strip().lower()
    return raw not in ("0", "false", "off", "no")


def props_path(sport: str, date_str: str, *, root: Optional[Path] = None) -> Path:
    return _data_root(root) / "live_evidence" / str(sport).lower() / f"{date_str}.props.jsonl"


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compact_props(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """`liveProps` rows -> entries `{"f": fixed, "c": columns, "r": [[values...(, extras)], ...]}`, one per
    (playerName, prop) in first-seen order. Lossless for JSON values; `expand_props` is the inverse. A row that is not
    a mapping is dropped (the caller counts it from `n`)."""
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows or ():
        if isinstance(row, Mapping):
            groups.setdefault((_canon(row.get("playerName")), _canon(row.get("prop"))), []).append(row)
    entries: list[dict[str, Any]] = []
    for members in groups.values():
        common = set(members[0])
        for row in members[1:]:
            common &= set(row)
        fixed = {k: members[0][k] for k in sorted(common)
                 if all(_canon(row[k]) == _canon(members[0][k]) for row in members[1:])}
        columns = sorted(k for k in common if k not in fixed)
        if "line" in columns:
            columns.remove("line")
            columns.insert(0, "line")
        packed: list[list[Any]] = []
        for row in members:
            values: list[Any] = [row[k] for k in columns]
            extras = {k: v for k, v in row.items() if k not in common}
            if extras:
                values.append(extras)
            packed.append(values)
        entries.append({"f": fixed, "c": columns, "r": packed})
    return entries


def expand_props(entries: Iterable[Any]) -> list[dict[str, Any]]:
    """The published rows back from `compact_props` entries."""
    out: list[dict[str, Any]] = []
    for entry in entries or ():
        if not isinstance(entry, Mapping):
            continue
        fixed = entry.get("f") if isinstance(entry.get("f"), Mapping) else {}
        columns = list(entry.get("c") or [])
        for values in entry.get("r") or []:
            if not isinstance(values, list):
                continue
            row = dict(fixed)
            row.update(zip(columns, values[:len(columns)]))
            if len(values) > len(columns) and isinstance(values[len(columns)], Mapping):
                row.update(values[len(columns)])
            out.append(row)
    return out


def _has_props_content(game: Mapping[str, Any]) -> bool:
    return any(key in game for key in GAME_KEYS)


def _game_ident(date_str: str, game: Mapping[str, Any], index: int) -> tuple[str, str]:
    return (date_str, str(game.get("event_id") or game.get("home_name") or f"#{index}"))


def game_signature(game: Mapping[str, Any]) -> str:
    """A digest of the game's props content; equal digest = nothing new to write."""
    payload = _canon([game.get(key) for key in GAME_KEYS])
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=16).hexdigest()


def game_prop_row(sport: str, date_str: str, t: Optional[str], observed_at: str,
                  game: Mapping[str, Any]) -> dict[str, Any]:
    """One row for one game's props at one tick. An absent or emptied `liveProps` is a row too (`n` = 0): the reader
    must learn that the props went away, not keep the last ones."""
    live = game.get("liveProps")
    raw = live if isinstance(live, list) else []
    row: dict[str, Any] = {
        "v": SCHEMA_VERSION,
        "kind": "props",
        "sport": sport,
        "date": date_str,
        "t": t,
        "observed_at": observed_at,
        "event_id": game.get("event_id"),
        "home": game.get("home_code") or game.get("home") or game.get("home_name"),
        "away": game.get("away_code") or game.get("away") or game.get("away_name"),
        "home_name": game.get("home_name"),
        "away_name": game.get("away_name"),
        "game_status": game.get("status") if _scalar(game.get("status")) else None,
        "n": len(raw),
        "refusal": game.get("livePropsRefusal"),
        "coverage": game.get("livePropsCoverage") if isinstance(game.get("livePropsCoverage"), Mapping) else None,
        "props": compact_props(raw),
    }
    if game.get("slateDate"):
        row["slate_date"] = game.get("slateDate")
    if live is not None and not isinstance(live, list):
        row["props_type"] = type(live).__name__
    if len(_canon(row)) > ROW_MAX_BYTES:
        row["props"] = []
        row["dropped"] = ["props"]
    return row


def snapshot_prop_rows(sport: str, snapshot: Mapping[str, Any], *, observed_at: str,
                       seen: Mapping[tuple, str]) -> tuple[list[dict[str, Any]], dict[tuple, str]]:
    """The props rows a snapshot adds, and the signature updates to commit once they are WRITTEN (`seen` is not
    mutated, so a failed write is retried on the next tick rather than lost).

    A game is written when its props content changed since the last committed row. A game that had props and now
    carries none of `GAME_KEYS` gets one clearing row (`n` = 0)."""
    if not isinstance(snapshot, Mapping):
        return [], {}
    date_str = str(snapshot.get("date") or "")
    t = _snapshot_t(snapshot)
    rows: list[dict[str, Any]] = []
    updates: dict[tuple, str] = {}
    for index, game in enumerate(snapshot.get("games") or []):
        if not isinstance(game, Mapping):
            continue
        ident = _game_ident(date_str, game, index)
        if not _has_props_content(game) and ident not in seen:
            continue
        sig = game_signature(game)
        if seen.get(ident) == sig or updates.get(ident) == sig:
            continue
        updates[ident] = sig
        rows.append(game_prop_row(sport, date_str, t, observed_at, game))
    return rows, updates


def append_rows(sport: str, date_str: str, rows: list[dict[str, Any]], *, root: Optional[Path] = None) -> tuple[int, int]:
    """(rows, bytes) appended."""
    if not rows:
        return 0, 0
    path = props_path(sport, date_str, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, separators=(",", ":"), default=str) + "\n" for row in rows)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)
    return len(rows), len(text.encode("utf-8"))


# ---------------------------------------------------------------- reading it back


def iter_prop_rows(sport: str, date_str: str, *, root: Optional[Path] = None) -> Iterator[dict[str, Any]]:
    path = props_path(sport, date_str, root=root)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a torn last line from a killed process is skipped, never fatal
            if isinstance(row, dict):
                yield row


def props_at(rows: Iterable[Mapping[str, Any]], at: Any) -> dict[str, dict[str, Any]]:
    """What had been PUBLISHED by `at`: the latest props row per game whose producer time `t` <= `at`.

    Keyed by event_id (home_name when there is none). Uses `t`, never `observed_at`. `expand_props(row["props"])`
    gives that instant's published rows."""
    cutoff = _parse(at)
    if cutoff is None:
        raise ValueError(f"unparseable instant: {at!r}")
    latest: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for row in rows:
        t = _parse(row.get("t"))
        if t is None or t > cutoff:
            continue
        key = str(row.get("event_id") or row.get("home_name") or "")
        if key not in latest or t >= latest[key][0]:
            latest[key] = (t, dict(row))
    return {k: v[1] for k, v in latest.items()}
