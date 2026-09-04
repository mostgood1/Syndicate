"""Decompose REALISED CLV by the sim's contribution to the blended score.

WHY THIS EXISTS. `_SCORE_SIM_WEIGHT`'s own comment states the condition under
which it may be raised: *"settled > 0 and CLV decomposed BY COMPONENT, so the
EV term and the sim term can be compared on outcomes rather than on taste."*
`layer2_board.py` and `scripts/score_sim_weight_impact.py` name the same
condition verbatim. Nothing has ever run it.

THE JOIN THAT MAKES IT POSSIBLE, and it is NOT the order ledger.
`clv_opening_ledger._opening_record` carries `model_edge_pct` and `ev_pct` on
every recorded opening -- deliberately, "so CLV can later be split by whether a
model had a view at all" -- and `clv_join.compute_clv_for_date` carries both
through onto each resolved row alongside `clv_pct`. So the decomposition is a
BOARD-side measurement over openings, not an order-side one over fills.

That matters because the order-side join is not available: `_LEAN_FIELDS`
started persisting `model_edge_pct`/`ev_pct` on 2026-09-03 and `sim_view` on
2026-09-04, while settlement runs once daily at ~06:00 CT, so the
settled-AND-attributed intersection is a handful of orders in ONE bucket. The
openings ledger has carried `model_edge_pct` since 2026-08-14.

`sim_component` IS NOT STORED AND DOES NOT NEED TO BE. It is an exact
deterministic function of `model_edge_pct`:

    sim_component = clip(_SCORE_SIM_WEIGHT * model_edge_pct, +/-_SCORE_SIM_CAP_PCT)

so it is recomputed here from the live constants rather than read, which also
lets the same data be re-bucketed at a CANDIDATE (weight, cap) without a deploy.

WHAT IS FILTERED OUT, and every exclusion is counted rather than dropped:
  - `close_age_seconds < 0` -- the "close" was observed AFTER first pitch. An
    in-play price differenced against a pregame opening is not CLV. Measured on
    mlb 2026-08-15: 37 of 172 same-book rows (21.5%) carried 60% of the loss.
  - book scope is reported per scope and NEVER pooled. `different_book_close`
    read +6.206 avg at a 91% beat rate on 150 real openings -- that is the
    best-of-N selection effect, not skill.

Read-only. Hits `/api/ops/clv/report?rows=1` and writes nothing to production.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any

BASE = os.environ.get("SYNDICATE_BASE_URL", "https://syndicate-an21.onrender.com")

# The production defaults. NEITHER env override is set on any service --
# verified 2026-09-04 against the live env-vars API.
SIM_WEIGHT = 0.125
SIM_CAP_PCT = 1.5

# `#624` step 1: every one of the 993 zero-probability HRR rows falls in this
# window, so any statistic spanning it is poisoned for props.
POISON_START, POISON_END = "2026-06-04", "2026-07-08"

# Tail calibration shipped on this date. Split here, or the pre- and post-fix
# sim are pooled as if they were one estimator.
CALIBRATION_SHIP_DATE = "2026-09-01"


def sim_component(model_edge_pct: float | None, weight: float, cap: float) -> float | None:
    """The CAPPED contribution, exactly as `opportunity_signals` computes it."""
    if model_edge_pct is None:
        return None
    return max(-cap, min(cap, weight * model_edge_pct))


def fetch(path: str, token: str, timeout: int = 240) -> dict[str, Any]:
    req = urllib.request.Request(f"{BASE}{path}", headers={"X-Admin-Token": token})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def harvest(dates: list[str], sports: list[str], token: str, out_path: str) -> list[dict]:
    """One `clv/report` call per (date, sport). Paced, because this runs on WEB."""
    rows: list[dict] = []
    for date in dates:
        for sport in sports:
            try:
                payload = fetch(f"/api/ops/clv/report?date={date}&sport={sport}&rows=1", token)
            except urllib.error.HTTPError as exc:
                print(f"{date} {sport}: HTTP {exc.code}", flush=True)
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"{date} {sport}: {type(exc).__name__}: {exc}", flush=True)
                continue
            got = payload.get("rows") or []
            for row in got:
                row["_date"] = date
                row["_sport"] = sport
            rows.extend(got)
            print(
                f"{date} {sport}: openings={payload.get('openings')} "
                f"resolved={payload.get('resolved')} rows={len(got)} "
                f"unresolved={payload.get('unresolved_reasons')}",
                flush=True,
            )
            # PACED ON PURPOSE. This endpoint runs on WEB, which `#632` is
            # actively OOM-profiling; a tight loop of ~1.3MB joins is exactly
            # the load that lane is trying to attribute.
            time.sleep(2.0)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle)
    return rows


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mu = sum(values) / len(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (len(values) - 1))


def welch(a: list[float], b: list[float]) -> tuple[float | None, float | None]:
    """Welch t and the SE of the difference. No SciPy in this repo."""
    if len(a) < 2 or len(b) < 2:
        return None, None
    sa, sb = _stdev(a), _stdev(b)
    if sa is None or sb is None:
        return None, None
    se = math.sqrt(sa**2 / len(a) + sb**2 / len(b))
    if se == 0:
        return None, None
    return (_mean(a) - _mean(b)) / se, se


def n_required(effect_pts: float, sd: float, alpha_z: float = 1.96, power_z: float = 0.84) -> int:
    """Per-arm n to detect `effect_pts` at 5% two-sided, 80% power."""
    if effect_pts <= 0 or sd <= 0:
        return -1
    return int(math.ceil(2 * ((alpha_z + power_z) * sd / effect_pts) ** 2))


def bucketise(rows: list[dict], weight: float, cap: float) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        comp = sim_component(row.get("model_edge_pct"), weight, cap)
        if comp is None:
            buckets["absent"].append(row)
        elif comp > 1e-9:
            buckets["positive"].append(row)
        elif comp < -1e-9:
            buckets["negative"].append(row)
        else:
            buckets["zero"].append(row)
    return buckets


def _line(name: str, clvs: list[float]) -> str:
    if not clvs:
        return f"   {name:<10} n=0"
    beat = sum(1 for c in clvs if c > 0)
    sd = _stdev(clvs)
    mean = _mean(clvs) or 0.0
    se = (sd / math.sqrt(len(clvs))) if (sd and len(clvs) > 1) else None
    return (
        f"   {name:<10} n={len(clvs):<6} avg_clv={mean:+8.4f} "
        f"se={('%.4f' % se) if se is not None else '   n/a':>8} "
        f"sd={('%.3f' % sd) if sd is not None else 'n/a':>8} "
        f"beat={beat}/{len(clvs)} ({100.0 * beat / len(clvs):.1f}%)"
    )


def _clvs(rows: list[dict]) -> list[float]:
    return [float(r["clv_pct"]) for r in rows if r.get("clv_pct") is not None]


def contrast(a_name: str, a: list[float], b_name: str, b: list[float]) -> None:
    """The difference, its SE, and the n that WOULD have been needed. An
    underpowered null is not evidence of no effect, so the n is printed with
    every comparison rather than only when the result is null."""
    if not a or not b:
        print(f"   {a_name} - {b_name}: one arm empty (n={len(a)}/{len(b)}) -- NOT a null result")
        return
    t, se = welch(a, b)
    diff = (_mean(a) or 0.0) - (_mean(b) or 0.0)
    print(
        f"   {a_name} - {b_name}: {diff:+.4f} pts  "
        f"se={('%.4f' % se) if se else 'n/a'}  t={('%.3f' % t) if t else 'n/a'}"
    )
    sd = _stdev(a + b) or 0.0
    if sd:
        need = {e: n_required(e, sd) for e in (0.25, 0.5, 1.0)}
        print(
            f"     powered for: {need[0.25]}/arm @0.25pt, {need[0.5]}/arm @0.5pt, "
            f"{need[1.0]}/arm @1.0pt  (sd={sd:.2f}; have {len(a)}/{len(b)})"
        )


def report(rows: list[dict], weight: float, cap: float, label: str) -> None:
    """Rates with denominators, per book scope. NEVER pooled across scopes --
    `different_book_close` reads +6.2 at a 91% beat rate on real data, which is
    the best-of-N selection effect and not skill."""
    print(f"\n===== {label}  (weight={weight} cap={cap}) =====")
    print(f"rows in: {len(rows)}")
    by_scope: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_scope[str(row.get("close_book_scope") or "unknown")].append(row)
    for scope, scope_rows in sorted(by_scope.items()):
        buckets = bucketise(scope_rows, weight, cap)
        print(f"\n-- close_book_scope={scope}  n={len(scope_rows)}")
        for name in ("negative", "zero", "positive", "absent"):
            print(_line(name, _clvs(buckets.get(name) or [])))
        pos, neg = _clvs(buckets.get("positive") or []), _clvs(buckets.get("negative") or [])
        absent = _clvs(buckets.get("absent") or [])
        # THE DECISIVE CONTRAST. A non-zero sim component is what the board
        # ACTS on, so "does having one beat not having one" is the claim.
        contrast("nonzero", pos + neg, "absent ", absent)
        # And the DIRECTIONAL one: the board REWARDS positive and PENALISES
        # negative, so if the sim is right, positive must beat negative.
        contrast("positive", pos, "negative", neg)

        # MAGNITUDE. A bare sign test cannot see a dose-response, and a weight
        # change is precisely a change in dose.
        graded = [
            (sim_component(r.get("model_edge_pct"), weight, cap), r)
            for r in scope_rows
            if r.get("model_edge_pct") is not None and r.get("clv_pct") is not None
        ]
        if len(graded) >= 40:
            graded.sort(key=lambda pair: pair[0])
            k = 5
            size = len(graded) // k
            print(f"   -- by sim_component quintile (n={len(graded)}):")
            for i in range(k):
                chunk = graded[i * size : (i + 1) * size if i < k - 1 else len(graded)]
                comps = [c for c, _ in chunk]
                vals = [float(r["clv_pct"]) for _, r in chunk]
                print(
                    f"      Q{i + 1} sim_component [{comps[0]:+.3f},{comps[-1]:+.3f}] "
                    f"n={len(vals)} avg_clv={_mean(vals):+7.4f} "
                    f"beat={sum(1 for v in vals if v > 0)}/{len(vals)}"
                )

        # CAPPED ROWS. `sim_capped` is the board's own flag for a row whose
        # model disagreement exceeded the allowance; if the cap is protecting
        # us, these are the rows it protects us from.
        capped = [
            r
            for r in scope_rows
            if r.get("model_edge_pct") is not None
            and abs(weight * float(r["model_edge_pct"])) > cap + 1e-12
        ]
        print(_line("CAPPED", _clvs(capped)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", required=True, help="comma-separated ISO dates")
    parser.add_argument("--sports", default="mlb,soccer,ncaaf,nfl,wnba")
    parser.add_argument("--out", required=True)
    parser.add_argument("--from-file", action="store_true", help="skip harvest, read --out")
    parser.add_argument("--weight", type=float, default=SIM_WEIGHT)
    parser.add_argument("--cap", type=float, default=SIM_CAP_PCT)
    args = parser.parse_args()

    if args.from_file:
        with open(args.out, encoding="utf-8") as handle:
            rows = json.load(handle)
    else:
        token = os.environ.get("ADMIN_TOKEN") or ""
        if not token:
            print("ADMIN_TOKEN not set")
            return 2
        rows = harvest(args.dates.split(","), args.sports.split(","), token, args.out)

    # UNKNOWN TIMING DOES NOT COUNT AS PREGAME -- a missing `close_age_seconds`
    # cannot say which side of first pitch the close came from, and a guard that
    # maps absent onto its permissive branch is how this class of bug ships.
    pregame, in_play, unknown_timing = [], [], []
    for row in rows:
        age = row.get("close_age_seconds")
        if age is None:
            unknown_timing.append(row)
        elif float(age) < 0:
            in_play.append(row)
        else:
            pregame.append(row)
    print(
        f"timing split: pregame={len(pregame)} in_play={len(in_play)} "
        f"unknown={len(unknown_timing)} of {len(rows)}"
    )

    report(pregame, args.weight, args.cap, "PREGAME CLOSES ONLY")
    pre = [r for r in pregame if str(r.get("_date") or "") < CALIBRATION_SHIP_DATE]
    post = [r for r in pregame if str(r.get("_date") or "") >= CALIBRATION_SHIP_DATE]
    if pre:
        report(pre, args.weight, args.cap, f"PRE tail-calibration (< {CALIBRATION_SHIP_DATE})")
    if post:
        report(post, args.weight, args.cap, f"POST tail-calibration (>= {CALIBRATION_SHIP_DATE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
