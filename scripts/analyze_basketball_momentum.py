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
from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path
from syndicate.features.shared.momentum_core import momentum_at

# The sweep grid. Seconds are the axis soccer chose; possessions are the axis
# that would port across NBA/WNBA/NCAAB pace regimes without re-tuning, which is
# the whole reason both were published (scope section 7, decision 1).
# **THE GRID GOES OUT TO A FULL QUARTER, because the live readings said it
# had to.** Measured on the 2026-08-22 WNBA slate at the 120s half-life this
# shipped with: `current` moved x4.5 UP and later x0.30 DOWN, each inside 55
# SECONDS of game clock. A quantity that swings three- to four-fold in under a
# minute is describing "right now".
#
# But the horizons being predicted are a QUARTER (600s) and a HALF (1200s) --
# those are the markets the live slate actually discovered (`spreads_q4`,
# `totals_h2`). Asking a 120s half-life about the next ten minutes is asking a
# fast signal a slow question, and a grid topping out at 180s could only ever
# have returned "no signal" for the interval markets without saying why.
#
# So the sweep now spans 60s (twitchy) to 600s (a whole quarter), and the
# possessions axis spans 4 to 40 -- roughly the same range in the units a
# basketball game actually advances in (~4 combined possessions per minute,
# measured 7/7 last night).
HALF_LIVES_SECONDS = (60.0, 120.0, 180.0, 300.0, 600.0)
HALF_LIVES_POSSESSIONS = (4.0, 8.0, 12.0, 20.0, 40.0)
# **HORIZONS ARE THE INTERVALS ACTUALLY TRADED, not round numbers.**
#
# The stated purpose of this signal is to inform INTERVAL BETS -- moneyline,
# spread and over/under on a segment of the game. So the horizon has to be the
# segment a book actually prices, or the correlation answers a question nobody
# can bet. Observed live on the WNBA slate 2026-08-23, the discovered market
# keys for NYL@IND were `h2h_q4`, `spreads_q4`, `totals_q4`, `h2h_h2`,
# `spreads_h2`, `totals_h2` -- quarters and halves.
#
# 600s is a WNBA quarter, 1200s a half. The two short ones stay because a
# signal that only shows up over a full quarter and not at all over three
# minutes is a different (and more suspicious) finding than one that does both.
HORIZONS_SECONDS = (60.0, 180.0, 600.0, 1200.0)

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


def forward_total(
    scoring_rows: Sequence[Mapping[str, Any]],
    probe: float,
    horizon: float,
    *,
    axis_key: str = "clock_seconds",
) -> float:
    """UNSIGNED points by both sides in `(probe, probe + horizon]` -- the
    over/under outcome.

    **`forward_margin` CANNOT ANSWER A TOTAL, and the difference is the whole
    point of measuring both.** Margin is who outscored whom; a 14-2 quarter and
    a 26-14 quarter have the same margin and wildly different totals. Momentum
    is a signed, side-relative quantity, so there is no reason to assume it
    carries the same information about both -- it could easily predict WHO
    scores next while saying nothing about HOW MUCH gets scored, which is
    exactly the split soccer measured on its own momentum series (directional
    dAUC +0.071, whether/how-many/when +0.0007).

    Same exclusive-left boundary as `forward_margin`, for the same reason: an
    event at the probe instant is what we knew, not what happened next.
    """
    total = 0.0
    for row in scoring_rows:
        try:
            t = float(row[axis_key])
        except (KeyError, TypeError, ValueError):
            continue
        if t <= probe or t > probe + horizon:
            continue
        total += abs(float(row.get("weight") or 0.0))
    return total


def sweep_season(
    games: Any,
    *,
    regulation_seconds: float = 2400.0,
) -> dict[str, Any]:
    """ONE pooled grid across every captured game, not one grid per game.

    **THE PER-GAME SWEEP DOES NOT SCALE AND ITS NUMBERS DO NOT MEAN MUCH.**
    282 games x 40 cells is 11,280 log lines nobody reads, and a correlation
    computed on ~50 probes from a single game is noise -- one run decides it.

    Pooling is also the only way the question gets answered honestly: the claim
    "momentum leads scoring" is a claim about BASKETBALL, not about one night in
    May. So probe/outcome pairs are accumulated across all games per cell and
    correlated once, with the number of contributing GAMES reported beside the
    probe count -- because probes within a game overlap and games do not.
    """
    # cell -> (values, margins, totals)
    buckets: dict[tuple, tuple[list, list, list]] = {}
    games_seen = 0
    probes_total = 0

    for game in (games or []):
        pressure = list(game.get("pressure") or [])
        scoring = list(game.get("narrator") or [])
        if not pressure or not scoring:
            continue
        games_seen += 1
        last = max(float(r["clock_seconds"]) for r in pressure)

        for horizon in HORIZONS_SECONDS:
            probes = []
            t = PROBE_WARMUP_SECONDS
            while t + horizon <= last:
                probes.append(t)
                t += PROBE_STEP_SECONDS
            if len(probes) < 3:
                continue
            margins = [forward_margin(scoring, p, horizon) for p in probes]
            totals = [forward_total(scoring, p, horizon) for p in probes]
            probes_total += len(probes)

            poss_at = [
                max((float(r["possession_index"]) for r in pressure
                     if float(r["clock_seconds"]) <= p), default=0.0)
                for p in probes
            ]

            for axis, half_lives, axis_key, probe_values in (
                ("seconds", HALF_LIVES_SECONDS, "clock_seconds", probes),
                ("possessions", HALF_LIVES_POSSESSIONS, "possession_index", poss_at),
            ):
                for half_life in half_lives:
                    values = [
                        momentum_at(pressure, pv, half_life_seconds=half_life,
                                    axis_key=axis_key)
                        for pv in probe_values
                    ]
                    key = (axis, half_life, horizon)
                    v, m, tt = buckets.setdefault(key, ([], [], []))
                    v.extend(values)
                    m.extend(margins)
                    tt.extend(totals)

    grid = []
    for (axis, half_life, horizon), (values, margins, totals) in sorted(buckets.items()):
        grid.append({
            "axis": axis,
            "half_life": half_life,
            "horizon_seconds": horizon,
            "n": len(values),
            "r_margin": _pearson(values, margins),
            "r_total": _pearson(values, totals),
            "r_total_abs": _pearson([abs(x) for x in values], totals),
        })
    return {"ok": bool(grid), "games": games_seen, "probes": probes_total, "grid": grid}


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
    return _sweep_from_rows(pressure, scoring)


def _sweep_from_rows(
    pressure: list[dict[str, Any]], scoring: list[dict[str, Any]]
) -> dict[str, Any]:
    """The grid itself. Shared by the captured-rows and re-fetched paths so the
    two can never compute a different answer from the same events."""
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
        # BOTH OUTCOMES, because they are different bets. `margin` is the
        # ML/spread question (who outscores whom); `total` is the over/under
        # question (how much gets scored). A signed signal has no automatic
        # claim on the second.
        margins = [forward_margin(scoring, p, horizon) for p in probes]
        totals = [forward_total(scoring, p, horizon) for p in probes]
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
                "r_margin": _pearson(values, margins),
                # Momentum is SIGNED and a total is not, so the sensible
                # predictor of a total is its MAGNITUDE -- "is anyone imposing
                # themselves" rather than "which side". Both are reported:
                # signed-vs-total is the null this is measured against.
                "r_total": _pearson(values, totals),
                "r_total_abs": _pearson([abs(v) for v in values], totals),
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
        margins = [forward_margin(scoring, p, horizon) for p in probes]
        totals = [forward_total(scoring, p, horizon) for p in probes]
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
                "r_margin": _pearson(values, margins),
                "r_total": _pearson(values, totals),
                "r_total_abs": _pearson([abs(v) for v in values], totals),
            })

    return {
        "ok": True,
        "pressure_events": len(pressure),
        "scoring_events": len(scoring),
        "last_seconds": round(last_seconds, 1),
        "last_possessions": round(last_poss, 2),
        "grid": results,
    }


def sweep_rows(
    pressure: Sequence[Mapping[str, Any]],
    scoring: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """`sweep_game`, but from ALREADY-EXTRACTED rows.

    The taxonomy step (summary -> rows) is exactly what the captured event dump
    has already done, so re-running it from a re-fetched summary would be work
    AND a reproducibility risk: ESPN may not return the same feed later.
    """
    if not pressure or not scoring:
        return {"ok": False,
                "reason": f"pressure={len(pressure)} scoring={len(scoring)} -- need both"}
    return _sweep_from_rows(list(pressure), list(scoring))


def causality_check_rows(
    rows: Iterable[Mapping[str, Any]],
    pressure: Sequence[Mapping[str, Any]],
    *,
    event_id: str,
) -> dict[str, Any]:
    """`causality_check` against captured rows rather than a re-fetched feed."""
    return _causality_from_pressure(rows, list(pressure), event_id=event_id)


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
    return _causality_from_pressure(rows, pressure, event_id=event_id)


def _causality_from_pressure(
    rows: Iterable[Mapping[str, Any]],
    pressure: list[dict[str, Any]],
    *,
    event_id: str,
) -> dict[str, Any]:
    if not pressure:
        return {"ok": False, "reason": "no pressure rows available"}

    compared = 0
    distinct_as_of: set[float] = set()
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
        distinct_as_of.add(round(float(as_of), 3))
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
        # **`compared` OVERSTATES how much was actually checked, and by a lot.**
        # Measured 2026-08-23 00:04:07Z and 00:08:47Z: two consecutive captures
        # of a live WNBA game emitted BYTE-IDENTICAL blocks (`events=117`,
        # `as_of_s=1198.0`) because the game was at halftime -- the clock is
        # frozen at the end of the period and ESPN's feed adds no plays. Every
        # tick through a ~15-minute break appends another duplicate row.
        #
        # Those rows re-verify the same instant, so counting them as separate
        # comparisons makes a thin check look thorough. `distinct_as_of` is the
        # number of DIFFERENT instants actually covered, and it is the figure to
        # quote.
        "distinct_as_of": len(distinct_as_of),
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


def _emit_sweep(event_id: str, swept: Mapping[str, Any]) -> None:
    """One printer for both input paths -- a second copy is a second format."""
    if not swept.get("ok"):
        _report(f"SWEEP_SKIPPED event={event_id}", swept)
        return
    print(
        f"[momentum_phase_c] SWEEP event={event_id} "
        f"pressure={swept['pressure_events']} scoring={swept['scoring_events']} "
        f"last_s={swept['last_seconds']} last_poss={swept['last_possessions']}",
        flush=True,
    )

    def _fmt(value: Any) -> str:
        return "NA" if value is None else f"{value:+.4f}"

    for cell in swept["grid"]:
        print(
            f"[momentum_phase_c] CELL event={event_id} axis={cell['axis']} "
            f"hl={cell['half_life']} horizon={cell['horizon_seconds']} "
            f"n={cell['n']} "
            f"r_margin={_fmt(cell['r_margin'])} "
            f"r_total={_fmt(cell['r_total'])} "
            f"r_total_abs={_fmt(cell['r_total_abs'])}",
            flush=True,
        )


def season_main(argv: Sequence[str] | None = None) -> int:
    """Pooled sweep over a RANGE of captured dates. One grid, not one per game.

    Reads only the captured event dumps -- no network, so it runs anywhere the
    artifacts are, and a re-run weeks from now sees the same feed it saw today.
    """
    parser = argparse.ArgumentParser(description="Pooled season momentum sweep")
    parser.add_argument("--league", default="wnba")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT"))
    args = parser.parse_args(argv)

    from datetime import date as _date, timedelta as _timedelta

    root = Path(args.data_root) if args.data_root else _REPO_ROOT / "data"
    a, b = _date.fromisoformat(args.start), _date.fromisoformat(args.end)

    games: list[dict[str, Any]] = []
    dates_seen = 0
    while a <= b:
        path = momentum_events_path(root, league_code=args.league, date_str=a.isoformat())
        a += _timedelta(days=1)
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        dates_seen += 1
        for game in (doc.get("games") or {}).values():
            if isinstance(game, dict):
                games.append(game)

    print(f"[momentum_phase_c] SEASON league={args.league} {args.start}..{args.end} "
          f"dates={dates_seen} games={len(games)}", flush=True)
    if not games:
        # Not 0. A silent empty sweep reads exactly like "no signal found".
        print("[momentum_phase_c] NO GAMES -- nothing captured for this range", flush=True)
        return 3

    swept = sweep_season(games)

    def _fmt(value: Any) -> str:
        return "NA" if value is None else f"{value:+.4f}"

    print(f"[momentum_phase_c] POOLED games={swept['games']} probes={swept['probes']} "
          f"cells={len(swept['grid'])}", flush=True)
    for cell in swept["grid"]:
        print(
            f"[momentum_phase_c] POOLED_CELL axis={cell['axis']} "
            f"hl={cell['half_life']} horizon={cell['horizon_seconds']} n={cell['n']} "
            f"r_margin={_fmt(cell['r_margin'])} "
            f"r_total={_fmt(cell['r_total'])} "
            f"r_total_abs={_fmt(cell['r_total_abs'])}",
            flush=True,
        )

    # THE HEADLINE, so nobody has to eyeball 40 rows to find it.
    best = max(
        (c for c in swept["grid"] if c["r_margin"] is not None),
        key=lambda c: abs(c["r_margin"]), default=None,
    )
    if best is not None:
        print(
            f"[momentum_phase_c] STRONGEST_MARGIN axis={best['axis']} "
            f"hl={best['half_life']} horizon={best['horizon_seconds']} "
            f"r={best['r_margin']:+.4f} n={best['n']} games={swept['games']} "
            f"-- CORRELATION ONLY, no fit, no edge claim",
            flush=True,
        )
    return 0


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

    # **PREFER THE CAPTURED EVENT DUMP OVER RE-FETCHING ESPN.**
    #
    # `momentum_events_<date>.json` holds the raw pressure and narrator rows,
    # overwritten each tick with the complete cumulative feed. Reading it means
    # the sweep needs no network at all -- which matters twice over: ESPN is 403
    # from a Claude Code sandbox, so a fetch-only analyser could ONLY ever run
    # on the worker; and a re-fetch weeks later may not return the same feed,
    # making a backtest silently unreproducible.
    #
    # The ESPN path stays as the fallback for dates captured before the dump
    # existed.
    events_path = momentum_events_path(root, league_code=args.league, date_str=args.date)
    captured: dict[str, Any] = {}
    if events_path.exists():
        try:
            captured = (json.loads(events_path.read_text(encoding="utf-8")) or {}).get("games") or {}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[momentum_phase_c] EVENTS_UNREADABLE {type(exc).__name__}: {exc}", flush=True)
    print(
        f"[momentum_phase_c] events_dump={'present' if captured else 'ABSENT'} "
        f"games={len(captured)} path={events_path}",
        flush=True,
    )

    from scripts.poll_basketball_momentum import fetch_summary

    exit_code = 0
    for event_id in event_ids:
        rows_for_event = captured.get(event_id) or {}
        pressure_rows = rows_for_event.get("pressure") or []
        narrator_rows = rows_for_event.get("narrator") or []
        if pressure_rows and narrator_rows:
            swept = sweep_rows(pressure_rows, narrator_rows)
            causal = causality_check_rows(rows, pressure_rows, event_id=event_id)
            _report(f"CAUSALITY event={event_id}", causal)
            _emit_sweep(event_id, swept)
            if causal.get("mismatches"):
                exit_code = max(exit_code, 5)
            continue

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
        if causal.get("ok") and causal.get("distinct_as_of", 0) < 3:
            # Say it rather than let a thin check read as a clean one.
            print(
                f"[momentum_phase_c] THIN event={event_id} "
                f"only {causal.get('distinct_as_of')} distinct instants across "
                f"{causal.get('compared')} rows -- duplicates, not coverage",
                flush=True,
            )
        if causal.get("mismatches"):
            # A failed causality check invalidates the sweep that follows, so it
            # sets the exit code even though the sweep may still print.
            exit_code = max(exit_code, 5)

        _emit_sweep(event_id, sweep_game(summary, league_code=args.league))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
