"""Phase B: turn ESPN summaries into a published basketball momentum artifact.

**NOTHING CALLS THIS YET, AND THAT IS THE POINT OF SAYING SO HERE.** Wiring it
into the live-lens tick is a one-line change in `live_lens_loop.py` /
`wnba/live_lens.py`, both claimed by other OPEN lanes, and belongs to the
deploy step the user deferred. `#208`'s lesson generalises: allowlisting
permits a transfer but does not make one happen, and a producer that EXISTS is
not a producer that RUNS. Phase B ships capture CAPABILITY, not capture.

WHAT IT WRITES, and why two destinations (scope section 4):

  (a) `<sport>_source/.../live_lens/live_momentum_<date>.jsonl` -- appended per
      tick. This is what makes the Phase C backtest possible at all: ESPN's
      summary is retrospectively complete, so a nightly capture would nearly
      do, but only a per-tick record proves the value we DISPLAYED at instant
      `t` was the causal one we later claim it was.
  (b) the live-lens aggregate, by returning a payload the caller merges. That
      is the path that actually crosses services -- `learnings.md` records
      soccer's per-league files being written with a raw `write_text()` on one
      worker while the board builds on another, so neither the filesystem nor
      the keyvalue key resolves.

BOTH DECAY AXES ARE PUBLISHED (scope section 7, decision 1). Seconds and
possessions, from the same rows, so Phase C's sweep is a read rather than a
rebuild.

THE NARRATOR IS NAMED `scoring_narrator`, NEVER `scoring_momentum`. It counts
points, so it correlates with scoring by construction and predicts nothing;
`learnings.md` 2026-08-21 FORBIDS publishing a field under a name that
describes a different quantity, and calling this one "momentum" would be
exactly that.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared.basketball_momentum import DEFAULT_HALF_LIFE_POSSESSIONS
from syndicate.features.shared.basketball_momentum import DEFAULT_HALF_LIFE_SECONDS
from syndicate.features.shared.basketball_momentum import basketball_pressure_events
from syndicate.features.shared.basketball_momentum import basketball_scoring_events
from syndicate.features.shared.momentum_core import momentum_at
from syndicate.features.shared.momentum_core import momentum_series

SCHEMA = "basketball_momentum_v1"

# Sampling step for the published series, in each axis's own units.
_STEP_SECONDS = 60.0
_STEP_POSSESSIONS = 2.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _axis_block(
    rows: list[dict[str, Any]],
    *,
    axis_key: str,
    half_life: float,
    step: float,
    as_of: float,
) -> dict[str, Any]:
    """One decayed series on one axis, sampled up to `as_of` and no further.

    `as_of` is the LIVE instant, not the end of the feed. Reading the whole
    feed would let a card show pressure from after the moment it claims to
    describe -- soccer's `_momentum_block` states the same rule.
    """
    return {
        "half_life": half_life,
        "as_of": round(float(as_of), 3),
        "current": momentum_at(rows, as_of, half_life_seconds=half_life, axis_key=axis_key),
        "series": [
            {"t": round(t, 3), "v": v}
            for t, v in momentum_series(
                rows,
                until_seconds=as_of,
                half_life_seconds=half_life,
                step_seconds=step,
                axis_key=axis_key,
            )
        ],
    }


def build_momentum_block(
    summary: Mapping[str, Any],
    *,
    league_code: str,
    home_tri: str | None = None,
    as_of_seconds: float | None = None,
    include_rows: bool = False,
) -> dict[str, Any]:
    """Both series on both axes for ONE game, or a STATED REASON.

    Never raises. A game whose feed is thin or unparseable returns
    `supported` with a `reason`, because a flat series and an absent one mean
    different things to anyone reading the card -- and because a bare 0.0 is
    the neutral-default trap `model_engine_standard.md` exists to stop: it
    makes an unfed series indistinguishable from a balanced game at every
    level except the data.
    """
    try:
        pressure = basketball_pressure_events(summary, league_code=league_code, home_tri=home_tri)
        narrator = basketball_scoring_events(summary, league_code=league_code, home_tri=home_tri)
        if not pressure:
            return {
                "schema": SCHEMA,
                "supported": True,
                "reason": "no pressure events in the play feed yet",
                "pressure": None,
                "scoring_narrator": None,
                "events": 0,
            }

        last_seconds = max(float(row["clock_seconds"]) for row in pressure)
        as_of_sec = float(as_of_seconds) if as_of_seconds is not None else last_seconds
        as_of_poss = max((float(row["possession_index"]) for row in pressure if float(row["clock_seconds"]) <= as_of_sec), default=0.0)

        # **THE TRICODES, SO THE BLOCK CAN BE JOINED BY SOMETHING OTHER THAN
        # ITS OWN KEY.** The artifact is keyed by ESPN event id, and the
        # consumer does not always have one: a WNBA card whose game is not in
        # play carries `"AWY@HOM"` or an opaque hash in `event_id`
        # (`_wnba_row_game_id`), because only `_supplement_games_with_live_
        # state` repairs it and only for live rows. First production reading of
        # the card join was `blocks=2 attached=0`.
        #
        # `_team_index` has already resolved both sides here -- the sign on
        # every row depends on it -- so recording them costs nothing and makes
        # the block self-describing rather than joinable only by a key the
        # reader may not hold.
        teams = sorted({str(row.get("team") or "").strip() for row in pressure} - {""})
        home_side = next(
            (str(row.get("team") or "").strip() for row in pressure
             if float(row.get("sign") or 0.0) > 0.0),
            None,
        )
        away_side = next((t for t in teams if t != home_side), None)

        block: dict[str, Any] = {
            "schema": SCHEMA,
            "supported": True,
            "reason": None,
            "home_tri": home_side,
            "away_tri": away_side,
            "events": len(pressure),
            "as_of_seconds": round(as_of_sec, 3),
            "as_of_possessions": round(as_of_poss, 3),
            "pressure": {
                "seconds": _axis_block(
                    pressure, axis_key="clock_seconds",
                    half_life=DEFAULT_HALF_LIFE_SECONDS, step=_STEP_SECONDS, as_of=as_of_sec,
                ),
                "possessions": _axis_block(
                    pressure, axis_key="possession_index",
                    half_life=DEFAULT_HALF_LIFE_POSSESSIONS, step=_STEP_POSSESSIONS, as_of=as_of_poss,
                ),
            },
            # NARRATOR. Correlates with scoring by construction. May drive a
            # label; may NEVER be fed to a model or reported as predictive.
            "scoring_narrator": {
                "events": len(narrator),
                "seconds": _axis_block(
                    narrator, axis_key="clock_seconds",
                    half_life=DEFAULT_HALF_LIFE_SECONDS, step=_STEP_SECONDS, as_of=as_of_sec,
                ),
            } if narrator else None,
        }
        if include_rows:
            # **THE RAW EVENTS, so the sweep never needs ESPN again.**
            # A decayed series cannot be inverted back into the events that
            # produced it, so the published series can REPLAY what was shown and
            # cannot RE-FIT it at another half-life. These rows are what make
            # Phase C self-sufficient.
            #
            # Stripped before the per-tick jsonl append -- they belong in the
            # overwritten events artifact, not repeated in every appended row.
            block["pressure_rows"] = pressure
            block["narrator_rows"] = narrator
        return block
    except Exception as exc:  # pragma: no cover - defensive, never fatal
        return {
            "schema": SCHEMA,
            "supported": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "pressure": None,
            "scoring_narrator": None,
            "events": 0,
        }


def assemble_momentum_payload(
    games: Mapping[str, Any], *, league_code: str, date_str: str
) -> dict[str, Any]:
    """Wrap already-built blocks in the slate envelope.

    Split out so a caller can build blocks ONE AT A TIME and still produce the
    identical payload -- see `build_momentum_payload_streamed`.
    """
    supported = sum(
        1 for block in games.values()
        if isinstance(block, Mapping) and block.get("supported") and block.get("pressure")
    )
    return {
        "schema": SCHEMA,
        "ok": True,
        "league": str(league_code or "").strip().lower(),
        "date": date_str,
        "generated_at": _utc_now(),
        "count": len(games),
        "with_series": supported,
        "games": dict(games),
    }


def build_momentum_payload_streamed(
    event_ids: Any,
    fetch_summary: Any,
    *,
    league_code: str,
    date_str: str,
    as_of_by_event: Mapping[str, float] | None = None,
    on_missing: Any = None,
    include_rows: bool = False,
) -> dict[str, Any]:
    """Same payload, but never holding more than ONE summary at a time.

    **THIS EXISTS BECAUSE OF SLATE SIZE, and the headroom is already thin.**
    The dict-comprehension form fetches every game's summary FIRST and holds
    them all while the blocks are built. An ESPN basketball summary carries the
    full play-by-play plus box score, so a late-game one is megabytes of parsed
    Python -- and `live-odds-worker` was measured at **93.7% of its 2048MB**
    with ~129MB of headroom while capturing a TWO-game slate.

    A four-game slate multiplies the peak by four for no benefit: each summary
    is read once, turned into a block of a few dozen sampled points, and never
    needed again. Streaming keeps the peak at one summary regardless of how many
    games are in play.

    `on_missing` is called with the event id when a fetch returns nothing, so
    the caller can log it without this function importing a logger.
    """
    as_of_map = dict(as_of_by_event or {})
    games: dict[str, Any] = {}
    for event_id in (event_ids or []):
        key = str(event_id or "").strip()
        if not key:
            continue
        summary = fetch_summary(key)
        if not summary:
            if on_missing is not None:
                on_missing(key)
            continue
        games[key] = build_momentum_block(
            summary, league_code=league_code, as_of_seconds=as_of_map.get(key),
            include_rows=include_rows,
        )
        # Dropped before the next fetch, not after the loop. The whole point is
        # that two summaries are never live at once.
        del summary
    return assemble_momentum_payload(games, league_code=league_code, date_str=date_str)


def build_momentum_payload(
    summaries_by_event: Mapping[str, Mapping[str, Any]],
    *,
    league_code: str,
    date_str: str,
    as_of_by_event: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """The whole slate's momentum, keyed by ESPN event id."""
    as_of_map = dict(as_of_by_event or {})
    games: dict[str, Any] = {}
    for event_id, summary in (summaries_by_event or {}).items():
        key = str(event_id or "").strip()
        if not key:
            continue
        games[key] = build_momentum_block(
            summary, league_code=league_code, as_of_seconds=as_of_map.get(key)
        )
    # Delegated so the streamed and buffered paths CANNOT drift: `with_series`
    # is the number every diagnostic keys on, and two copies of that sum is two
    # places for it to quietly disagree.
    return assemble_momentum_payload(games, league_code=league_code, date_str=date_str)


def momentum_artifact_path(root: Path, *, league_code: str, date_str: str) -> Path:
    """`<root>/<league>_source/source_artifacts/data/live_lens/live_momentum_<date>.jsonl`.

    Under `data/live_lens/` because `artifact_publisher.HOT_ARTIFACT_PATTERNS`
    already allowlists that directory's siblings by pattern; the two entries
    this adds follow the same twin shape every other family there uses.
    """
    league = str(league_code or "").strip().lower()
    return (
        Path(root) / f"{league}_source" / "source_artifacts" / "data" / "live_lens"
        / f"live_momentum_{date_str}.jsonl"
    )


def append_momentum_artifact(payload: Mapping[str, Any], *, path: Path) -> Path:
    """APPEND one tick. Never truncates.

    JSONL and append-only because the Phase C backtest needs the sequence of
    what was true at each tick, not the last frame. Overwriting would leave a
    file that looks like a record and is a snapshot.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return path


__all__ = [
    "SCHEMA",
    "append_momentum_artifact",
    "build_momentum_block",
    "build_momentum_payload",
    "momentum_artifact_path",
]


def momentum_events_path(root: Path, *, league_code: str, date_str: str) -> Path:
    """`<root>/<league>_source/.../live_lens/momentum_events_<date>.json`.

    Sits beside the per-tick jsonl and under the same allowlisted directory.
    """
    league = str(league_code or "").strip().lower()
    return (
        Path(root) / f"{league}_source" / "source_artifacts" / "data" / "live_lens"
        / f"momentum_events_{date_str}.json"
    )


def write_momentum_events(payload: Mapping[str, Any], *, path: Path) -> int:
    """OVERWRITE the raw-event dump. Never append.

    **BECAUSE ESPN'S FEED IS CUMULATIVE.** Every tick's summary carries the whole
    game from tip-off, so appending would rewrite the same early plays on every
    pass -- measured at ~20x the storage of a single overwrite for a four-game
    slate, and the appended copy is no more complete than the last one.

    The latest overwrite is therefore always the full game, with no dedup logic
    and no cross-tick state to get wrong. ~0.1MB per night for four games.

    This is the SWEEP's input. The append-only jsonl remains the CAUSAL record --
    proof of what was displayed at instant t -- and the two are not
    interchangeable: an overwrite cannot show what a card showed an hour ago,
    and the sampled series in it cannot be re-fitted at another half-life.
    """
    rows_out: dict[str, Any] = {}
    total = 0
    for event_id, block in (payload.get("games") or {}).items():
        if not isinstance(block, Mapping):
            continue
        pressure = block.get("pressure_rows") or []
        narrator = block.get("narrator_rows") or []
        if not pressure:
            continue
        rows_out[str(event_id)] = {
            "home_tri": block.get("home_tri"),
            "away_tri": block.get("away_tri"),
            "as_of_seconds": block.get("as_of_seconds"),
            "pressure": pressure,
            "narrator": narrator,
        }
        total += len(pressure)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Atomic replace: a reader must never see a half-written dump, and this file
    # is overwritten while Phase C may be reading it.
    tmp.write_text(
        json.dumps({
            "schema": "basketball_momentum_events_v1",
            "league": payload.get("league"),
            "date": payload.get("date"),
            "generated_at": _utc_now(),
            "games": rows_out,
        }, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)
    return total


def strip_rows(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The payload without raw rows, for the append-only per-tick record.

    The rows live in the overwritten events artifact. Repeating them in every
    appended row is the 20x duplication `write_momentum_events` exists to avoid.
    """
    out = dict(payload)
    games = {}
    for event_id, block in (payload.get("games") or {}).items():
        if isinstance(block, Mapping):
            trimmed = {k: v for k, v in block.items()
                       if k not in ("pressure_rows", "narrator_rows")}
            games[event_id] = trimmed
        else:
            games[event_id] = block
    out["games"] = games
    return out
