"""Turn a captured event dump into projection rows: STATE at t -> OUTCOME after t.

**THIS IS THE SUBSTRATE, NOT A MODEL.** It emits the table that both fitting and
evaluating a live interval projection need, and it takes no view on what the
projection should be. `model_engine_standard.md` binds on anything that consumes
it -- in particular, adding a mechanism to a calibrated engine requires re-fitting
the rates that were absorbing it.

## WHY INTERVALS AND NOT THE FULL GAME

The existing live game-line model reads brier **0.28706 vs market 0.24700** and
is bounded at **`games_with_outcome: 3`** -- its n=985 is repeated snapshots of
those same three games. A full-game win probability is limited by the number of
GAMES, because one game contributes exactly one outcome no matter how often it is
sampled. At four games a night that is ~25 nights to reach 100 outcomes.

Quarter-level outcomes arrive four times faster (~7 nights) AND are far less
correlated within a game: a team can win Q1 and lose Q3, while a game has one
winner however you slice it. So interval projections are both what is being bet
and the only thing a short capture window can actually validate.

## THE STATE / OUTCOME SPLIT IS THE WHOLE CONTRACT

Every field is one or the other, and they are named apart (`state_` / `fwd_`) so a
caller cannot mix them by accident. **`state_` fields must be computable from the
feed truncated at `t`, and nothing else.** `test_state_is_identical_when_the_
future_is_appended` is the falsification: build rows from a truncated feed and
from the full one, and every `state_` value at the same probe must match exactly.
A state field that moves when future events arrive is leaking the outcome, and a
leaking feature makes any model look brilliant in backtest and lose money live.

## WHAT IS DELIBERATELY LEGITIMATE, AND WHAT IS NOT

`state_margin` and `state_total` -- the score so far -- ARE legitimate inputs.
They are public at time `t` and every live model on earth uses them.

The decayed NARRATOR series is NOT emitted here. `basketball_momentum_artifacts`
records why: it counts points, so it correlates with scoring by construction and
predicts nothing. Cumulative score is state; a decayed recent-scoring curve
dressed as a signal is the thing that must never reach a model.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared.momentum_core import momentum_at

# Emitted at each of these half-lives on each axis, so a fit can choose rather
# than inherit a constant nobody swept.
STATE_HALF_LIVES_SECONDS = (60.0, 180.0, 600.0)
STATE_HALF_LIVES_POSSESSIONS = (4.0, 12.0, 40.0)
FORWARD_HORIZONS_SECONDS = (180.0, 600.0, 1200.0)

PROBE_STEP_SECONDS = 30.0
PROBE_WARMUP_SECONDS = 180.0


def _forward(
    scoring: Sequence[Mapping[str, Any]], probe: float, horizon: float
) -> tuple[float, float]:
    """(signed margin, unsigned total) in `(probe, probe + horizon]`.

    Exclusive on the left for the reason the whole module exists: an event AT
    the probe instant is state, not outcome, and counting it on both sides makes
    every model look prescient.
    """
    margin = 0.0
    total = 0.0
    for row in scoring:
        try:
            t = float(row["clock_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        if t <= probe or t > probe + horizon:
            continue
        weight = float(row.get("weight") or 0.0)
        margin += float(row.get("sign") or 0.0) * weight
        total += abs(weight)
    return margin, total


def build_projection_rows(
    pressure: Sequence[Mapping[str, Any]],
    scoring: Sequence[Mapping[str, Any]],
    *,
    event_id: str,
    regulation_seconds: float,
    step_seconds: float = PROBE_STEP_SECONDS,
    warmup_seconds: float = PROBE_WARMUP_SECONDS,
) -> list[dict[str, Any]]:
    """One row per probe. `state_*` known at `t`; `fwd_*` strictly after it."""
    if not pressure or not scoring:
        return []

    last = max(float(r["clock_seconds"]) for r in pressure)
    rows: list[dict[str, Any]] = []

    probe = warmup_seconds
    while probe <= last:
        # --- STATE: everything from events at or before the probe ------------
        past_scoring = [r for r in scoring if float(r["clock_seconds"]) <= probe]
        past_pressure = [r for r in pressure if float(r["clock_seconds"]) <= probe]
        if not past_pressure:
            probe += step_seconds
            continue

        margin = sum(float(r.get("sign") or 0.0) * float(r.get("weight") or 0.0)
                     for r in past_scoring)
        total = sum(abs(float(r.get("weight") or 0.0)) for r in past_scoring)
        possessions = max(float(r.get("possession_index") or 0.0) for r in past_pressure)
        minutes = max(probe / 60.0, 1e-6)
        remaining = max(0.0, regulation_seconds - probe)

        row: dict[str, Any] = {
            "event_id": event_id,
            "t_seconds": round(probe, 1),
            "state_seconds_remaining": round(remaining, 1),
            "state_margin": round(margin, 2),
            "state_total": round(total, 2),
            "state_possessions": round(possessions, 2),
            "state_pace_per_min": round(possessions / minutes, 4),
            # Pace x time left -- the single biggest lever on a live TOTAL, and
            # the reason the possession estimator's ~2.6% high bias matters here
            # in a way it never did for a chart.
            "state_possessions_remaining_est": round(
                (possessions / minutes) * (remaining / 60.0), 2
            ),
        }
        for half_life in STATE_HALF_LIVES_SECONDS:
            row[f"state_pressure_s{int(half_life)}"] = momentum_at(
                past_pressure, probe, half_life_seconds=half_life,
                axis_key="clock_seconds",
            )
        for half_life in STATE_HALF_LIVES_POSSESSIONS:
            row[f"state_pressure_p{int(half_life)}"] = momentum_at(
                past_pressure, possessions, half_life_seconds=half_life,
                axis_key="possession_index",
            )

        # --- OUTCOME: strictly after the probe -------------------------------
        for horizon in FORWARD_HORIZONS_SECONDS:
            fwd_margin, fwd_total = _forward(scoring, probe, horizon)
            # `complete` says whether the whole window is inside the captured
            # feed. A truncated window looks like a low-scoring one, and a fit
            # that trains on both learns that late-game means low totals.
            row[f"fwd_margin_{int(horizon)}"] = round(fwd_margin, 2)
            row[f"fwd_total_{int(horizon)}"] = round(fwd_total, 2)
            row[f"fwd_complete_{int(horizon)}"] = bool(probe + horizon <= last)

        rows.append(row)
        probe += step_seconds

    return rows


def rows_from_events_dump(
    dump: Mapping[str, Any], *, regulation_seconds: float = 2400.0, **kwargs: Any
) -> list[dict[str, Any]]:
    """Every game in a captured `momentum_events_<date>.json`, flattened."""
    out: list[dict[str, Any]] = []
    for event_id, game in ((dump or {}).get("games") or {}).items():
        if not isinstance(game, Mapping):
            continue
        out.extend(build_projection_rows(
            game.get("pressure") or [],
            game.get("narrator") or [],
            event_id=str(event_id),
            regulation_seconds=regulation_seconds,
            **kwargs,
        ))
    return out


def state_columns(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """The `state_` columns, sorted. What a fit is ALLOWED to use as input."""
    seen: set[str] = set()
    for row in rows:
        seen.update(k for k in row if k.startswith("state_"))
    return sorted(seen)


def outcome_columns(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """The `fwd_` columns. What a fit may PREDICT and must never consume."""
    seen: set[str] = set()
    for row in rows:
        seen.update(k for k in row if k.startswith("fwd_") and not k.startswith("fwd_complete_"))
    return sorted(seen)
