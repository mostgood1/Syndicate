"""Phase C: does basketball momentum LEAD scoring, and at what half-life?

**WHAT THIS ANSWERS, AND WHAT IT REFUSES TO ANSWER.** It answers whether a
pressure value at instant `t` carries information about the scoring margin over
`(t, t+horizon]`, and which half-life on which axis carries the most of it. It
does NOT answer whether momentum is worth displaying, and it must never be read
as licence to feed momentum to a sim -- `model_engine_standard.md` binds in full
for that, including a re-fit of the rates a new mechanism would displace.

## THE DESIGN GAP THIS SCRIPT RAN INTO, STATED UP FRONT

**The published artifact cannot support a half-life sweep on its own.**
`build_momentum_block` stores SAMPLED SERIES (`{t, v}` at a fixed step) and a
`current`, not the raw pressure rows. A sweep needs to re-decay raw events at
several half-lives, and a decayed series cannot be inverted back into the events
that produced it. So the artifact is sufficient to REPLAY what was displayed and
insufficient to RE-FIT it.

Rather than widen the artifact -- raw rows are ~105 per game per tick, appended
every ~2.5 min, and would grow the jsonl by orders of magnitude for data ESPN
will hand back anyway -- this script takes the split the module docstring
already argued for:

  * the OUTCOME and the SWEEP come from ESPN's summary, which is
    RETROSPECTIVELY COMPLETE (the final feed contains every play of the game);
  * the CAUSALITY CHECK comes from the captured jsonl, which is the only thing
    that can prove the value we DISPLAYED at instant `t` was the causal one.

That second half is the whole reason per-tick capture exists, and it is the
check a nightly job could not make.

## WHY IT RUNS ON THE WORKER

The artifact lives on the worker's mounted disk. `/api/ops/artifacts/export`
is unreachable from a Claude Code session (403 at CONNECT, an organisation
policy denial that no token changes), and ESPN is 403 from that sandbox too.
So this is a worker-side script whose findings arrive through the log
collector, not a local notebook.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from syndicate.features.shared.basketball_momentum import basketball_pressure_events
from syndicate.features.shared.basketball_momentum import basketball_scoring_events
from syndicate.features.shared.basketball_momentum_artifacts import momentum_artifact_path
from syndicate.features.shared.momentum_core import momentum_at

# The sweep grid. Seconds are the axis soccer chose; possessions are the axis
# that would port across NBA/WNBA/NCAAB pace regimes without re-tuning, which is
# the whole reason both were published (scope section 7, decision 1).
HALF_LIVES_SECONDS = (60.0, 90.0, 120.0, 180.0)
HALF_LIVES_POSSESSIONS = (4.0, 6.0, 8.0, 12.0)
HORIZONS_SECONDS = (60.0, 120.0, 180.0)

# Probes are placed on a grid rather than at every event, so a stretch with many
# events does not dominate the correlation purely by being dense.
PROBE_STEP_SECONDS = 30.0
# Ignore the opening minutes: with few events, momentum is dominated by whichever
# side happened to act first, and the forward window overlaps the warm-up.
PROBE_WARMUP_SECONDS = 180.0


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Correlation, or None when it is not defined.

    Returns None rather than 0.0 for a degenerate input. A zero correlation and
    an uncomputable one are different findings, and `model_engine_standard.md`
    names the neutral default as the trap that makes an unfed value
    indistinguishable from a working one.
    """
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def forward_margin(
    scoring_rows: Sequence[Mapping[str, Any]],
    probe: float,
    horizon: float,
    *,
    axis_key: str = "clock_seconds",
) -> float:
    """Signed points scored in `(probe, probe + horizon]`.

    **STRICTLY AFTER the probe.** The boundary is exclusive on the left for the
    same reason `momentum_at` is inclusive on the right: an event exactly at the
    probe instant belongs to what we KNEW, not to what happened next. Counting
    it on both sides would leak the outcome into the predictor and make every
    lead/lag test pass.
    """
    total = 0.0
    for row in scoring_rows:
        try:
            t = float(row[axis_key])
        except (KeyError, TypeError, ValueError):
            continue
        if t <= probe or t > probe + horizon:
            continue
        total += float(row.get("sign") or 0.0) * float(row.get("weight") or 0.0)
    return total


def sweep_game(
    summary: Mapping[str, Any],
    *,
    league_code: str,
) -> dict[str, Any]:
    """Lead/lag correlations over the half-life x horizon grid, both axes."""
    pressure = basketball_pressure_events(summary, league_code=league_code)
    scoring = basketball_scoring_events(summary, league_code=league_code)
    if not pressure or not scoring:
        return {
            "ok": False,
            "reason": f"pressure={len(pressure)} scoring={len(scoring)} -- need both",
        }

    last_seconds = max(float(r["clock_seconds"]) for r in pressure)
    last_poss = max(float(r["possession_index"]) for r in pressure)

    results: list[dict[str, Any]] = []

    # --- SECONDS AXIS -----------------------------------------------------
    for horizon in HORIZONS_SECONDS:
        probes = []
        t = PROBE_WARMUP_SECONDS
        while t + horizon <= last_seconds:
            probes.append(t)
            t += PROBE_STEP_SECONDS
        if len(probes) < 3:
            continue
        outcomes = [forward_margin(scoring, p, horizon) for p in probes]
        for half_life in HALF_LIVES_SECONDS:
            values = [
                momentum_at(pressure, p, half_life_seconds=half_life,
                            axis_key="clock_seconds")
                for p in probes
            ]
            results.append({
                "axis": "seconds",
                "half_life": half_life,
                "horizon_seconds": horizon,
                "n": len(probes),
                "r": _pearson(values, outcomes),
            })

    # --- POSSESSIONS AXIS -------------------------------------------------
    # The probe grid stays in SECONDS (the outcome horizon is a real-time
    # window, not a possession count) while the DECAY runs in possessions. To
    # decay at a probe we need that probe's possession index, which is the last
    # index at or before it -- the same rule `build_momentum_block` uses.
    for horizon in HORIZONS_SECONDS:
        probes = []
        t = PROBE_WARMUP_SECONDS
        while t + horizon <= last_seconds:
            probes.append(t)
            t += PROBE_STEP_SECONDS
        if len(probes) < 3:
            continue
        outcomes = [forward_margin(scoring, p, horizon) for p in probes]
        poss_at_probe = [
            max((float(r["possession_index"]) for r in pressure
                 if float(r["clock_seconds"]) <= p), default=0.0)
            for p in probes
        ]
        for half_life in HALF_LIVES_POSSESSIONS:
            values = [
                momentum_at(pressure, pp, half_life_seconds=half_life,
                            axis_key="possession_index")
                for pp in poss_at_probe
            ]
            results.append({
                "axis": "possessions",
                "half_life": half_life,
                "horizon_seconds": horizon,
                "n": len(probes),
                "r": _pearson(values, outcomes),
            })

    return {
        "ok": True,
        "pressure_events": len(pressure),
        "scoring_events": len(scoring),
        "last_seconds": round(last_seconds, 1),
        "last_possessions": round(last_poss, 2),
        "grid": results,
    }


def causality_check(
    rows: Iterable[Mapping[str, Any]],
    summary: Mapping[str, Any],
    *,
    league_code: str,
    event_id: str,
) -> dict[str, Any]:
    """Did the value we PUBLISHED at each tick match a retrospective recompute?

    **THIS IS THE CHECK ONLY PER-TICK CAPTURE CAN MAKE, and the reason Phase B
    appends rather than snapshots.** `momentum_at` claims to be strictly causal:
    only events at or before the probe contribute. If that holds, recomputing at
    a past tick's `as_of_seconds` from the COMPLETE final feed must reproduce
    exactly the value that tick published -- the extra events the final feed
    carries are all in the future and are excluded.

    A mismatch is therefore not a rounding nit. It means either the published
    value saw events it should not have, or the taxonomy is not deterministic
    over the same feed. Both invalidate every correlation in `sweep_game`.
    """
    pressure = basketball_pressure_events(summary, league_code=league_code)
    if not pressure:
        return {"ok": False, "reason": "no pressure rows in the retrospective feed"}

    compared = 0
    mismatches: list[dict[str, Any]] = []
    for row in rows:
        block = ((row.get("games") or {}).get(event_id)) or {}
        published = ((block.get("pressure") or {}).get("seconds") or {})
        as_of = published.get("as_of")
        current = published.get("current")
        if as_of is None or current is None:
            continue
        half_life = float(published.get("half_life") or 0.0)
        if half_life <= 0.0:
            continue
        recomputed = momentum_at(
            pressure, float(as_of), half_life_seconds=half_life,
            axis_key="clock_seconds",
        )
        compared += 1
        # `momentum_at` rounds to 4dp, so an exact match is the expectation.
        if abs(float(recomputed) - float(current)) > 1e-4:
            mismatches.append({
                "as_of": as_of,
                "published": current,
                "recomputed": recomputed,
                "delta": round(float(recomputed) - float(current), 6),
            })
    return {
        "ok": True,
        "compared": compared,
        "mismatches": len(mismatches),
        "examples": mismatches[:5],
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # A torn final line is expected on a file being appended to
                # live; it is not a reason to lose the rows before it.
                continue
    return rows


def _report(label: str, payload: Mapping[str, Any]) -> None:
    print(f"[momentum_phase_c] {label} {json.dumps(payload, sort_keys=True)}", flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="wnba")
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT"))
    parser.add_argument(
        "--skip-fetch", action="store_true",
        help="causality check only; no ESPN call, so no sweep",
    )
    args = parser.parse_args(argv)

    root = Path(args.data_root) if args.data_root else _REPO_ROOT / "data"
    path = momentum_artifact_path(root, league_code=args.league, date_str=args.date)
    rows = read_rows(path)
    print(f"[momentum_phase_c] artifact={path} rows={len(rows)}", flush=True)
    if not rows:
        # NOT exit 0. A silent empty run is how a broken analysis is mistaken
        # for a null result, which is the failure this repo names repeatedly.
        print("[momentum_phase_c] NO ROWS -- nothing captured for this date", flush=True)
        return 3

    event_ids: list[str] = []
    for row in rows:
        for event_id in (row.get("games") or {}):
            if event_id not in event_ids:
                event_ids.append(event_id)
    print(f"[momentum_phase_c] games={len(event_ids)} ids={','.join(event_ids)}", flush=True)

    from scripts.poll_basketball_momentum import fetch_summary

    exit_code = 0
    for event_id in event_ids:
        if args.skip_fetch:
            continue
        summary = fetch_summary(args.league, event_id)
        if not summary:
            print(f"[momentum_phase_c] SUMMARY_FAILED event={event_id}", flush=True)
            exit_code = max(exit_code, 4)
            continue

        causal = causality_check(
            rows, summary, league_code=args.league, event_id=event_id
        )
        _report(f"CAUSALITY event={event_id}", causal)
        if causal.get("mismatches"):
            # A failed causality check invalidates the sweep that follows, so it
            # sets the exit code even though the sweep may still print.
            exit_code = max(exit_code, 5)

        swept = sweep_game(summary, league_code=args.league)
        if not swept.get("ok"):
            _report(f"SWEEP_SKIPPED event={event_id}", swept)
            continue
        print(
            f"[momentum_phase_c] SWEEP event={event_id} "
            f"pressure={swept['pressure_events']} scoring={swept['scoring_events']} "
            f"last_s={swept['last_seconds']} last_poss={swept['last_possessions']}",
            flush=True,
        )
        for cell in swept["grid"]:
            r = cell["r"]
            print(
                f"[momentum_phase_c] CELL event={event_id} axis={cell['axis']} "
                f"hl={cell['half_life']} horizon={cell['horizon_seconds']} "
                f"n={cell['n']} r={'NA' if r is None else round(r, 4)}",
                flush=True,
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
