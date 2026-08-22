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

        block: dict[str, Any] = {
            "schema": SCHEMA,
            "supported": True,
            "reason": None,
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
    supported = sum(1 for block in games.values() if block.get("supported") and block.get("pressure"))
    return {
        "schema": SCHEMA,
        "ok": True,
        "league": str(league_code or "").strip().lower(),
        "date": date_str,
        "generated_at": _utc_now(),
        "count": len(games),
        # A COUNT THAT DISTINGUISHES "no games" FROM "games we could not read".
        # `count` alone cannot: both are a number next to an empty chart.
        "with_series": supported,
        "games": games,
    }


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
