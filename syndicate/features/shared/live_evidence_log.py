"""The live evidence log: Phase 1B M0 of the one-engine plan (lane `live-evidence-log`, 2026-11-09).

WHY. Every live re-sim and lens OVERWRITES its own snapshot each tick (`live/<sport>_live_resim.json`,
`live/<sport>_live_lens.json`), so a live learner has nothing to train on: the evidence at an instant is gone
by the next tick. NBA already keeps a per-tick history for its own forward read (`nba/live_resim.py`,
`live_resim_history`, 2026-10-16); no other sport does. The adopted plan
(`docs/ai_context/plan_one_engine_pregame_live.md`, D9-D12, user 2026-11-09) needs the evidence of EVERY live
sport kept, as-of stamped, so the engine can rebuild what it knew at any instant `t`.

WHAT. One collector reads each sport's live snapshot through the shared store (the same store the board reads)
every ~30 s, and appends one compact row per game lane per new tick to
`<data root>/live_evidence/<sport>/<date>.jsonl`. It never edits, and never imports, a sport's re-sim module, so
those files stay with their owner lanes. The rows are read back by `iter_rows` / `evidence_at`.

A row is the lane's state (period, clock, score, and the sport's own extras: down / distance / yard line /
possession...), its projection scalars (total, margin, win probability...), the margin and total distributions,
the segment table, the lane's provenance (source, refusal, `liveStateAsOf`), and two clocks:
- `t`: the snapshot's own `generatedAt` -- when the producer published it;
- `observed_at`: when the collector read it (always >= `t`).

`evidence_at` answers "what had been published by `t`", using `t`, never `observed_at`.

Not every producer puts its state in `projection`: the NFL re-sim publishes `live_state` / `margin_dist` /
`total_dist` at lane level (2026-11-09). The writer keeps those verbatim in `extra`, and `iter_rows` fills the
shared names (`state`, `marginDist`, `totalRunsDist`) through `normalize_row`. Read rows through `iter_rows`.

WHAT IT KEEPS AND DROPS.
- A FRESH projection lane: one row every tick it changes (its `t` moves).
- A refusal or carried lane, and a pregame lane with no live state: a row only when its signature (source,
  refusal, `liveStateAsOf`) changes. A 67-game NCAAF snapshot of pregame lanes every 75 s would otherwise be
  ~77k identical rows a day.
- A row larger than `ROW_MAX_BYTES` drops its segment distributions first, then extras, and names what it dropped.

Local disk only, never the keyvalue store, never read on a request path. A failure is printed and swallowed: the
log can never stop a worker. `SYNDICATE_LIVE_EVIDENCE_LOG=off` turns it off (absent = on: it only appends local
files). `SYNDICATE_LIVE_EVIDENCE_INTERVAL_SECONDS` (default 30, floor 10).
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional

SCHEMA_VERSION = 1
LOG_ENV = "SYNDICATE_LIVE_EVIDENCE_LOG"
INTERVAL_ENV = "SYNDICATE_LIVE_EVIDENCE_INTERVAL_SECONDS"
DEFAULT_INTERVAL_SECONDS = 30.0
MIN_INTERVAL_SECONDS = 10.0
ROW_MAX_BYTES = 24_000

# The snapshot each sport's live producer publishes, under `<data root>/live/`.
# (nba/ncaab/wncaab/wnba re-sims; ncaaf/nhl lenses; nfl re-sim -- file names from each module's
# `live_lens_snapshot_path`.) MLB and soccer publish page payloads / their own logs, not this shape.
LIVE_SNAPSHOTS: dict[str, str] = {
    "nba": "nba_live_resim.json",
    "wnba": "wnba_live_resim.json",
    "ncaab": "ncaab_live_resim.json",
    "wncaab": "wncaab_live_resim.json",
    "ncaaf": "ncaaf_live_lens.json",
    "nfl": "nfl_live_resim.json",
    "nhl": "nhl_live_lens.json",
}

# Projection keys that describe the GAME STATE rather than the forecast. Everything else scalar in a
# projection is forecast.
STATE_KEYS: frozenset[str] = frozenset({
    "period", "clockSeconds", "clock", "homeScore", "awayScore", "scoreSource",
    "down", "distance", "yardLine", "possession", "redZone",
    "strength", "powerPlay", "emptyNet",
    "inning", "half", "outs", "baseState",
    "quarter", "bonus", "homeFouls", "awayFouls", "homeTimeouts", "awayTimeouts",
})
DIST_KEYS: tuple[str, ...] = ("marginDist", "totalRunsDist")
LANE_SCALARS: tuple[str, ...] = (
    "modelHomeWinProb", "rawModelHomeWinProb", "simsRun", "liveScoreChangedAt", "resumeMatch", "closed", "ok",
)
LANE_SKIP: frozenset[str] = frozenset({
    "projection", "inputs", "key", "label", "source", "liveResimRefusal", "liveResimRefusalDetail", "refusal",
    "liveStateAsOf", "as_of", "carriedForward", "carriedRefusal", "refusedStateAsOf", *LANE_SCALARS,
})

# The NFL live re-sim publishes its game state and distributions at LANE level, snake_case, with only `homeMargin`
# and `total` in `projection` (fleet, Monday night football 2026-11-09): `live_state` {period, clock_seconds,
# home_score, away_score}, `margin_dist`, `total_dist`. The writer keeps them verbatim in `extra`; `normalize_row`
# fills the shared names from there on READ, so rows written before and after this read alike.
LANE_STATE_ALIASES: dict[str, str] = {
    "period": "period", "clock_seconds": "clockSeconds", "home_score": "homeScore", "away_score": "awayScore",
    "down": "down", "distance": "distance", "yard_line": "yardLine", "possession": "possession",
}
LANE_DIST_ALIASES: dict[str, str] = {"margin_dist": "marginDist", "total_dist": "totalRunsDist"}


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(LOG_ENV) or "").strip().lower()
    return raw not in ("0", "false", "off", "no")


def interval_seconds(env: Optional[Mapping[str, str]] = None) -> float:
    raw = (env if env is not None else os.environ).get(INTERVAL_ENV)
    try:
        value = float(raw) if raw not in (None, "") else DEFAULT_INTERVAL_SECONDS
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, value)


def _data_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root())


def log_path(sport: str, date_str: str, *, root: Optional[Path] = None) -> Path:
    return _data_root(root) / "live_evidence" / str(sport).lower() / f"{date_str}.jsonl"


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _snapshot_t(snapshot: Mapping[str, Any]) -> str | None:
    t = snapshot.get("generatedAt") or snapshot.get("generated_at")
    return str(t) if t else None


def _lane_as_of(lane: Mapping[str, Any]) -> str:
    return str(lane.get("liveStateAsOf") or lane.get("as_of") or "")


def _lane_refusal(lane: Mapping[str, Any]) -> Any:
    if "liveResimRefusal" in lane:
        return lane.get("liveResimRefusal")
    return lane.get("refusal")


def lane_row(sport: str, date_str: str, t: str | None, observed_at: str, game: Mapping[str, Any],
             lane: Mapping[str, Any]) -> dict[str, Any]:
    """One compact, self-describing row for one game lane at one tick."""
    projection = lane.get("projection") if isinstance(lane.get("projection"), Mapping) else {}
    state = {k: projection.get(k) for k in projection if k in STATE_KEYS and _scalar(projection.get(k))}
    proj = {k: v for k, v in projection.items() if k not in STATE_KEYS and k not in DIST_KEYS and k != "segments"
            and _scalar(v)}
    row: dict[str, Any] = {
        "v": SCHEMA_VERSION,
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
        "lane": lane.get("key"),
        "label": lane.get("label"),
        "source": lane.get("source"),
        "refusal": _lane_refusal(lane),
        "refusal_detail": lane.get("liveResimRefusalDetail") if _scalar(lane.get("liveResimRefusalDetail")) else None,
        "as_of": _lane_as_of(lane) or None,
        "carried": bool(lane.get("carriedForward")),
    }
    for key in LANE_SCALARS:
        if key in lane and _scalar(lane.get(key)):
            row[key] = lane.get(key)
    if state:
        row["state"] = state
    if proj:
        row["proj"] = proj
    for key in DIST_KEYS:
        if isinstance(projection.get(key), Mapping):
            row[key] = dict(projection[key])
    if isinstance(projection.get("segments"), Mapping):
        row["segments"] = dict(projection["segments"])
    inputs = lane.get("inputs")
    if isinstance(inputs, Mapping):
        scalars = {k: v for k, v in inputs.items() if _scalar(v)}
        if scalars:
            row["inputs"] = scalars
    extra = {k: v for k, v in lane.items() if k not in LANE_SKIP}
    if extra:
        row["extra"] = extra
    return _fit_row(row)


def _fit_row(row: dict[str, Any]) -> dict[str, Any]:
    """Keep a row under ROW_MAX_BYTES: segment detail goes first, then extras; what was dropped is named."""
    def size(r: Mapping[str, Any]) -> int:
        return len(json.dumps(r, separators=(",", ":"), default=str))

    dropped: list[str] = []
    if size(row) > ROW_MAX_BYTES and isinstance(row.get("segments"), dict):
        row["segments"] = {k: ({kk: vv for kk, vv in v.items() if _scalar(vv)} if isinstance(v, Mapping) else v)
                           for k, v in row["segments"].items()}
        dropped.append("segments.detail")
    if size(row) > ROW_MAX_BYTES and "extra" in row:
        row.pop("extra")
        dropped.append("extra")
    if size(row) > ROW_MAX_BYTES and "inputs" in row:
        row.pop("inputs")
        dropped.append("inputs")
    if dropped:
        row["dropped"] = dropped
    return row


def _is_fresh_projection(lane: Mapping[str, Any]) -> bool:
    projection = lane.get("projection")
    return (isinstance(projection, Mapping) and bool(projection)
            and not lane.get("carriedForward") and not _lane_refusal(lane))


def _signature(lane: Mapping[str, Any]) -> tuple:
    # NOT `liveStateAsOf`: a pregame or refusing lane stamps it with the TICK time (nhl / ncaaf, fleet dry run
    # 2026-11-09), so including it would rewrite every pregame lane every tick -- ~32k identical NCAAF rows a day.
    return (lane.get("source"), json.dumps(_lane_refusal(lane), sort_keys=True, default=str),
            bool(lane.get("carriedForward")))


def snapshot_rows(sport: str, snapshot: Mapping[str, Any], *, observed_at: str,
                  seen: dict[tuple, tuple]) -> list[dict[str, Any]]:
    """The rows a snapshot adds. `seen` (mutated) remembers each non-fresh lane's last signature."""
    if not isinstance(snapshot, Mapping):
        return []
    date_str = str(snapshot.get("date") or "")
    t = _snapshot_t(snapshot)
    rows: list[dict[str, Any]] = []
    for game in snapshot.get("games") or []:
        if not isinstance(game, Mapping):
            continue
        for index, lane in enumerate(game.get("gameLens") or []):
            if not isinstance(lane, Mapping):
                continue
            ident = (date_str, str(game.get("event_id") or game.get("home_name") or ""),
                     str(lane.get("key") or index))
            if _is_fresh_projection(lane):
                seen.pop(ident, None)
                rows.append(lane_row(sport, date_str, t, observed_at, game, lane))
                continue
            sig = _signature(lane)
            if seen.get(ident) == sig:
                continue
            seen[ident] = sig
            rows.append(lane_row(sport, date_str, t, observed_at, game, lane))
    return rows


def append_rows(sport: str, date_str: str, rows: list[dict[str, Any]], *, root: Optional[Path] = None) -> int:
    if not rows:
        return 0
    path = log_path(sport, date_str, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    return len(rows)


def _default_reader(root: Path) -> Callable[[str], Any]:
    from syndicate.features.shared.refresh_state_store import read_json_file

    def read(name: str) -> Any:
        return read_json_file(root / "live" / name)

    return read


class Collector:
    """One collector pass per call. Holds only the last `t` per sport and the non-fresh lane signatures."""

    def __init__(self, *, root: Optional[Path] = None, read: Optional[Callable[[str], Any]] = None,
                 sports: Optional[Mapping[str, str]] = None) -> None:
        self.root = _data_root(root)
        self.read = read or _default_reader(self.root)
        self.sports = dict(sports or LIVE_SNAPSHOTS)
        self.last_t: dict[str, str] = {}
        self.seen: dict[str, dict[tuple, tuple]] = {}

    def collect_once(self, *, now: Optional[datetime] = None) -> dict[str, int]:
        observed_at = (now or datetime.now(timezone.utc)).isoformat()
        written: dict[str, int] = {}
        for sport, name in self.sports.items():
            try:
                snapshot = self.read(name)
            except Exception as exc:  # noqa: BLE001 -- one unreadable sport never stops the others
                print(f"[live_evidence] READ_FAILED sport={sport} {type(exc).__name__}: {str(exc)[:120]}", flush=True)
                continue
            if not isinstance(snapshot, Mapping):
                continue
            t = _snapshot_t(snapshot)
            if t is not None and self.last_t.get(sport) == t:
                continue  # the producer has not ticked since the last pass
            date_str = str(snapshot.get("date") or "")
            if not date_str:
                continue
            seen = self.seen.setdefault(sport, {})
            if len(seen) > 20_000:
                seen.clear()  # a bound, not a correctness rule: the worst case is a repeated non-fresh row
            rows = snapshot_rows(sport, snapshot, observed_at=observed_at, seen=seen)
            try:
                written[sport] = append_rows(sport, date_str, rows, root=self.root)
            except Exception as exc:  # noqa: BLE001
                print(f"[live_evidence] WRITE_FAILED sport={sport} {type(exc).__name__}: {str(exc)[:120]}", flush=True)
                continue
            if t is not None:
                self.last_t[sport] = t
        return {k: v for k, v in written.items() if v}


_LOOP_THREAD: Optional[threading.Thread] = None


def _loop(collector: Collector, interval: float) -> None:
    while True:
        started = time.monotonic()
        try:
            written = collector.collect_once()
            if written:
                print("[live_evidence] TICK rows=" + str(sum(written.values())) + " by_sport="
                      + json.dumps(written, separators=(",", ":"), sort_keys=True), flush=True)
        except Exception as exc:  # noqa: BLE001 -- the log can never stop a worker
            print(f"[live_evidence] TICK_FAILED {type(exc).__name__}: {str(exc)[:160]}", flush=True)
        time.sleep(max(1.0, interval - (time.monotonic() - started)))


def start_live_evidence_loop(env: Optional[Mapping[str, str]] = None) -> bool:
    """Start the collector thread once per process. False when switched off or already running."""
    global _LOOP_THREAD
    if not enabled(env):
        print("[live_evidence] LOOP_OFF", flush=True)
        return False
    if _LOOP_THREAD is not None and _LOOP_THREAD.is_alive():
        return False
    interval = interval_seconds(env)
    _LOOP_THREAD = threading.Thread(target=_loop, args=(Collector(), interval), name="syndicate-live-evidence",
                                    daemon=True)
    _LOOP_THREAD.start()
    print(f"[live_evidence] LOOP_STARTED interval_s={interval:g} sports={','.join(LIVE_SNAPSHOTS)}", flush=True)
    return True


# ---------------------------------------------------------------- reading it back


def iter_rows(sport: str, date_str: str, *, root: Optional[Path] = None) -> Iterator[dict[str, Any]]:
    path = log_path(sport, date_str, root=root)
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
                yield normalize_row(row)


def normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """`row` with `state` / `marginDist` / `totalRunsDist` filled from a lane-level snake_case copy in `extra`
    (`live_state`, `margin_dist`, `total_dist`) when the projection supplied none. A field the projection supplied
    is never overridden. Returns a new dict and names what it filled under `normalized`."""
    out = dict(row)
    extra = row.get("extra")
    if not isinstance(extra, Mapping):
        return out
    filled: list[str] = []
    live_state = extra.get("live_state")
    if not out.get("state") and isinstance(live_state, Mapping):
        state = {LANE_STATE_ALIASES[k]: v for k, v in live_state.items()
                 if k in LANE_STATE_ALIASES and v is not None and _scalar(v)}
        if state:
            out["state"] = state
            filled.append("state")
    for src, dst in LANE_DIST_ALIASES.items():
        if not out.get(dst) and isinstance(extra.get(src), Mapping) and extra.get(src):
            out[dst] = dict(extra[src])
            filled.append(dst)
    if filled:
        out["normalized"] = filled
    return out


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evidence_at(rows: Iterable[Mapping[str, Any]], at: Any) -> dict[tuple, dict[str, Any]]:
    """What had been PUBLISHED by `at`: the latest row per (event, lane) whose producer time `t` <= `at`.

    Uses the producer's `t`, never `observed_at`, so the answer does not depend on when the collector happened to
    poll. A row with no parseable `t` is ignored."""
    cutoff = _parse(at)
    if cutoff is None:
        raise ValueError(f"unparseable instant: {at!r}")
    latest: dict[tuple, tuple[datetime, dict[str, Any]]] = {}
    for row in rows:
        t = _parse(row.get("t"))
        if t is None or t > cutoff:
            continue
        key = (row.get("event_id") or row.get("home_name"), row.get("lane"))
        if key not in latest or t >= latest[key][0]:
            latest[key] = (t, dict(row))
    return {k: v[1] for k, v in latest.items()}
