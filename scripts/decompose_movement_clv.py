r"""Decompose REALISED CLV by the MOVEMENT term's contribution to the blended score.

WHY THIS EXISTS. `_SCORE_MOVEMENT_WEIGHT`'s own comment states the condition
under which it may be changed, in the same words `_SCORE_SIM_WEIGHT` uses:
*"you need settled rows, with CLV decomposed by component, so 'did the moved
rows actually win' is a measurement rather than a preference. Until then the cap
is doing the work, not the weight."* That decomposition was run for the sim term
on 2026-09-04 (`scripts/decompose_sim_clv.py`) and has never been run for
movement. This is its counterpart, and it could not simply be copied -- see the
next two sections, which are the whole reason this file is long.

------------------------------------------------------------------------------
WHY THE SIM SCRIPT'S METHOD DOES NOT TRANSFER: MOVEMENT IS NOT RECONSTRUCTIBLE
------------------------------------------------------------------------------
`decompose_sim_clv.py` works because `sim_component` is an exact deterministic
function of ONE field stored on the opening record:

    sim_component = clip(_SCORE_SIM_WEIGHT * model_edge_pct, +/-_SCORE_SIM_CAP_PCT)

so it is recomputed from the live constants and never needs to have been saved.

**Movement has no such field and cannot have one.** It is measured AGAINST the
opening, so the opening record's own movement is 0 by construction -- storing
`movement_price_delta` on it would persist a column of zeros. The quantity only
exists at the LATER builds that re-rank an already-published row, and the only
artifact that records those is `clv_price_trail` (`reports/intelligence/
clv_price_trail/<date>.jsonl`), which keeps `(epoch, line, fair, price, book)`
per published bet per build.

------------------------------------------------------------------------------
THE CIRCULARITY TRAP, WHICH IS THE REAL METHODOLOGICAL CONTENT HERE
------------------------------------------------------------------------------
The obvious test -- "bucket rows by movement, compare `clv_pct`" -- IS INVALID,
and invalid in a way that manufactures a strong positive result out of nothing.

CLV is the price change from OUR OPEN to the CLOSE. Movement at build `Tk` is
the price change from OUR OPEN to `Tk`. `Tk` lies BETWEEN the two, so movement
is a **leading segment of the very path CLV measures**. Regressing one on the
other partly regresses a quantity on itself: a row that has already moved toward
us has, by arithmetic and not by skill, banked part of its own CLV. Run naively,
the movement term would look like the best predictor on the board and the number
would mean nothing.

**So this script measures FORWARD CLV, from the observation onward:**

    open ............ Tk ............ close
         \__________/  \____________/
          movement      FORWARD CLV   <- the only non-circular target
          (the signal)  (the outcome)

Both segments come from the same trail, which is why the trail is required
rather than convenient. The naive contrast is computed too, and REPORTED
ALONGSIDE AS A CONTROL: if `--show-circular` prints a large positive effect
while the forward contrast is null, that gap IS the arithmetic overlap, and
seeing them side by side is the cheapest possible guard against anyone rerunning
the naive version later and believing it.

------------------------------------------------------------------------------
WHAT THIS DOES NOT CLAIM
------------------------------------------------------------------------------
  - CLV is not ROI. This grades the ranking signal, not the bet slate.
  - The population is the PUBLISHED BOARD, not filled orders. That is the right
    population for a RANKING weight and the wrong one for a claim about fills.
  - Book scopes are never pooled. `different_book_close` carries the best-of-N
    selection effect; `same_book` is the clean scope. The sim decomposition
    found +0.411 vs -0.132 across that split on the same underlying data.
  - Price movement and LINE movement are reported SEPARATELY. They carry
    different coefficients (`_SCORE_MOVEMENT_WEIGHT` in cents,
    `_SCORE_MOVEMENT_LINE_WEIGHT` in probability points) and pooling them would
    average two estimators.

------------------------------------------------------------------------------
GETTING THE TRAIL
------------------------------------------------------------------------------
The trail is written on refresh-worker as HOURLY CHUNKS (`<date>T<hh>.jsonl`),
each published to web exactly ONCE when its hour seals. Both shapes are read
here: a date before 2026-09-20 is a single `<date>.jsonl`, after it a set of
chunks, and a date spanning the change is both.

It IS allowlisted in `HOT_ARTIFACT_PATTERNS` (2026-09-20) -- but the allowlist
alone never moved this file, and that is worth knowing before trusting an empty
result. Nothing in refresh-worker's MAIN LOOP sweeps (the generic sweep runs
only from intermittently spawned jobs), and the old whole-day file exceeded the
12 MiB `_PUBLISH_MAX_BYTES` silently, with no `_FAILED_DIRECT_PUBLISH` exemption
because there was no direct call to fail. The publish-on-seal in
`record_price_trail` is what actually pushes it. Two routes, and `--trail-dir`
accepts either:

  1. Locally, against an exported or mirrored copy.
  2. On refresh-worker, against `$SYNDICATE_DATA_ROOT/intelligence/clv_price_trail/`.

**A ZERO HERE IS AMBIGUOUS UNTIL YOU CHECK WHICH.** An empty export can mean
"no trail" or "not allowlisted" or "over the 8 MB per-file export cap" -- that
last one is live, because the trail is bounded at 48 MB and the export refuses
single files above 8 MB. `record_price_trail` reports `bytes_on_disk` so the
third case is distinguishable from the first two. This script REFUSES to print a
verdict on zero rows rather than reporting a null result, because a null result
needs a live population and an unreadable directory cannot supply one.

Read-only. Reads the trail from disk and `/api/ops/clv/report?rows=1` over HTTP;
writes nothing to production.
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
from datetime import date as _date, timedelta
from pathlib import Path
from typing import Any

BASE = os.environ.get("SYNDICATE_BASE_URL", "https://syndicate-an21.onrender.com")

# The production defaults, mirrored here so a CANDIDATE (weight, cap) can be
# scored over the same data without a deploy -- the same property that made the
# sim decomposition able to screen a weight change offline.
MOVEMENT_WEIGHT = 0.05
MOVEMENT_LINE_WEIGHT = 0.3096
MOVEMENT_CAP_PCT = 1.0

# `#624` step 1: every one of the 993 zero-probability HRR rows falls in this
# window, so any statistic spanning it is poisoned for props.
POISON_START, POISON_END = "2026-06-04", "2026-07-08"


# ---------------------------------------------------------------------------
# The scoring curve, copied deliberately rather than imported.
# ---------------------------------------------------------------------------
# Importing `opportunity_signals` would bind this harness to whatever the LIVE
# constants are, and the whole point of a weight screen is to score data under a
# weight production is NOT running. The shape is pinned by
# `tests/test_layer2_line_movement_scoring.py::test_harness_curve_matches_production`,
# so a divergence is caught by a test rather than by a wrong answer.
def movement_contribution(move: float, weight: float, cap: float) -> float:
    if cap <= 0 or weight <= 0:
        return max(-cap, min(cap, weight * move))
    magnitude = cap * (1.0 - math.exp(-weight * abs(move) / cap))
    return magnitude if move > 0 else -magnitude


def american_to_prob(price: float | None) -> float | None:
    """Implied probability from American odds, vig included."""
    if price is None:
        return None
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    return 100.0 / (value + 100.0) if value > 0 else (-value) / ((-value) + 100.0)


def american_cents(price: float | None) -> float | None:
    """American odds on a continuous scale where -100 and +100 are both 0.

    Mirrors `layer2_board._american_cents`. Without it, -104 -> +104 reads as a
    208-point move instead of an 8-cent one, which is what fired the board's
    only steam flag on 2026-09-15.
    """
    if price is None:
        return None
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value >= 100:
        return value - 100.0
    if value <= -100:
        return 100.0 + value
    return None


def fetch(path: str, token: str, timeout: int = 240) -> dict[str, Any]:
    req = urllib.request.Request(f"{BASE}{path}", headers={"X-Admin-Token": token})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_trail_file(path: Path) -> dict[str, list[dict]]:
    """`key -> [{t, l, p, b}, ...]` in time order. Unreadable lines are COUNTED.

    A silently skipped malformed line is how a join quietly loses its
    population; the caller reports `bad_lines` beside every other denominator.
    """
    out: dict[str, list[dict]] = defaultdict(list)
    bad = 0
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return {}
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:  # noqa: BLE001
                bad += 1
                continue
            key = record.get("k")
            if not key:
                bad += 1
                continue
            out[key].append(record)
    for points in out.values():
        points.sort(key=lambda r: r.get("t") or 0)
    out["__bad_lines__"] = [{"n": bad}]  # type: ignore[assignment]
    return out


def observations(points: list[dict]) -> list[dict]:
    """Every re-rank of an already-published bet, with its movement AT THAT TIME.

    The FIRST point is our open and is never itself an observation -- its
    movement is 0 by construction, which is exactly the degenerate row the
    opening ledger would have given us.
    """
    if len(points) < 2:
        return []
    opening = points[0]
    open_price, open_line = opening.get("p"), opening.get("l")
    open_cents = american_cents(open_price)
    open_prob = american_to_prob(open_price)
    out: list[dict] = []
    for point in points[1:]:
        now_price, now_line = point.get("p"), point.get("l")
        same_line = (open_line is None and now_line is None) or (
            open_line is not None and now_line is not None and abs(float(open_line) - float(now_line)) < 1e-9
        )
        record = {"t": point.get("t"), "price": now_price, "line": now_line, "same_line": same_line}
        if same_line:
            now_cents = american_cents(now_price)
            if open_cents is None or now_cents is None:
                continue
            # NEGATED, exactly as `layer2_board` negates it at the one call
            # site: a SHORTENING price is a move toward the pick, and a raw
            # cents delta is negative when the price shortens.
            record["kind"] = "price"
            record["move"] = -(now_cents - open_cents)
        else:
            now_prob = american_to_prob(now_price)
            if open_prob is None or now_prob is None:
                continue
            # Already signed toward-the-pick, matching
            # `movement_line_prob_delta_pp`.
            record["kind"] = "line"
            record["move"] = (now_prob - open_prob) * 100.0
        out.append(record)
    return out


def forward_clv_pct(observed_price: float | None, close_price: float | None) -> float | None:
    """Probability points gained between the OBSERVATION and the close.

    The non-circular outcome. Positive means the market moved further toward
    this side AFTER we saw the movement -- which is the only thing a movement
    term can claim to predict.
    """
    a, b = american_to_prob(observed_price), american_to_prob(close_price)
    if a is None or b is None:
        return None
    return (b - a) * 100.0


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


def contrast(name: str, positive: list[float], negative: list[float]) -> dict[str, Any]:
    t, se = welch(positive, negative)
    mu_p, mu_n = _mean(positive), _mean(negative)
    diff = None if (mu_p is None or mu_n is None) else mu_p - mu_n
    ci = None
    if diff is not None and se:
        ci = (round(diff - 1.96 * se, 4), round(diff + 1.96 * se, 4))
    sd = _stdev(positive + negative)
    return {
        "contrast": name,
        "n_positive": len(positive),
        "n_negative": len(negative),
        "mean_positive": None if mu_p is None else round(mu_p, 4),
        "mean_negative": None if mu_n is None else round(mu_n, 4),
        "diff": None if diff is None else round(diff, 4),
        "welch_t": None if t is None else round(t, 3),
        "ci95": ci,
        "n_needed_for_0.25pp": n_required(0.25, sd) if sd else -1,
    }


def dates_in_range(start: str, end: str) -> list[str]:
    a, b = _date.fromisoformat(start), _date.fromisoformat(end)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", required=True, help="First date (YYYY-MM-DD).")
    parser.add_argument("--end", required=True, help="Last date (YYYY-MM-DD), inclusive.")
    parser.add_argument("--sports", default="mlb,nfl,ncaaf,soccer,wnba")
    parser.add_argument(
        "--trail-dir",
        default=None,
        help="Directory of <date>.jsonl price trails. Defaults to "
        "$SYNDICATE_DATA_ROOT/intelligence/clv_price_trail.",
    )
    parser.add_argument("--weight", type=float, default=MOVEMENT_WEIGHT)
    parser.add_argument("--line-weight", type=float, default=MOVEMENT_LINE_WEIGHT)
    parser.add_argument("--cap", type=float, default=MOVEMENT_CAP_PCT)
    parser.add_argument(
        "--show-circular",
        action="store_true",
        help="Also print the INVALID open->close contrast as a control. See the "
        "circularity section of this file's docstring before quoting it.",
    )
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    token = os.environ.get("ADMIN_TOKEN", "").strip()
    if not token:
        print("ADMIN_TOKEN is not set; the clv/report join needs it.", flush=True)
        return 2

    trail_dir = Path(
        args.trail_dir
        or (Path(os.environ.get("SYNDICATE_DATA_ROOT", "data")) / "intelligence" / "clv_price_trail")
    )
    dates = dates_in_range(args.start, args.end)
    sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]

    poisoned = [d for d in dates if POISON_START <= d <= POISON_END]
    if poisoned:
        print(
            f"REFUSING: {len(poisoned)} date(s) fall in the HRR-poisoned window "
            f"{POISON_START}..{POISON_END}, which invalidates prop statistics spanning it.",
            flush=True,
        )
        return 3

    # ---- 1. the closes, from the CLV join --------------------------------
    closes: dict[tuple[str, str], dict] = {}
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
            rows = payload.get("rows") or []
            for row in rows:
                key = row.get("key")
                if key:
                    closes[(date, key)] = row
            print(
                f"{date} {sport}: openings={payload.get('openings')} "
                f"resolved={payload.get('resolved')} rows={len(rows)}",
                flush=True,
            )
            # PACED ON PURPOSE: this endpoint runs on WEB, which has an OOM
            # history under exactly this kind of tight join loop.
            time.sleep(2.0)

    # ---- 2. the observations, from the trail ------------------------------
    arms: dict[tuple[str, str], list[float]] = defaultdict(list)
    circular: dict[tuple[str, str], list[float]] = defaultdict(list)
    stats = {
        "dates": len(dates),
        "trail_files_found": 0,
        "trail_files_missing": 0,
        "trail_bad_lines": 0,
        "keys_in_trail": 0,
        "keys_joined_to_close": 0,
        "observations": 0,
        "observations_scored": 0,
        "no_close": 0,
        "no_forward_clv": 0,
    }
    for date in dates:
        # EVERY file for the date: the legacy whole-day `<date>.jsonl` AND the
        # hourly `<date>T<hh>.jsonl` chunks the writer produces since
        # 2026-09-20. Reading only one shape would silently halve the
        # population depending on which side of that change the date falls on.
        paths = sorted(trail_dir.glob(f"{date}*.jsonl"))
        if not paths:
            stats["trail_files_missing"] += 1
            continue
        stats["trail_files_found"] += len(paths)
        trail = defaultdict(list)
        for path in paths:
            part = load_trail_file(path)
            stats["trail_bad_lines"] += (part.pop("__bad_lines__", [{"n": 0}]) or [{"n": 0}])[0]["n"]
            for key, points in part.items():
                trail[key].extend(points)
        # Chunks are individually ordered; merged they are not, and
        # `observations()` treats the FIRST point as our open.
        for points in trail.values():
            points.sort(key=lambda r: r.get("t") or 0)
        for key, points in trail.items():
            stats["keys_in_trail"] += 1
            close_row = closes.get((date, key))
            if close_row is None:
                stats["no_close"] += 1
                continue
            stats["keys_joined_to_close"] += 1
            close_price = close_row.get("close_price")
            scope = str(close_row.get("book_scope") or "unknown")
            for obs in observations(points):
                stats["observations"] += 1
                forward = forward_clv_pct(obs.get("price"), close_price)
                if forward is None:
                    stats["no_forward_clv"] += 1
                    continue
                weight = args.line_weight if obs["kind"] == "line" else args.weight
                component = movement_contribution(obs["move"], weight, args.cap)
                if abs(component) < 1e-12:
                    continue
                stats["observations_scored"] += 1
                arm = "positive" if component > 0 else "negative"
                arms[(f"{obs['kind']}:{scope}", arm)].append(forward)
                if args.show_circular:
                    clv = close_row.get("clv_pct")
                    if isinstance(clv, (int, float)):
                        circular[(f"{obs['kind']}:{scope}", arm)].append(float(clv))

    # ---- 3. refuse to grade an empty population ---------------------------
    print("\n=== POPULATION ===", flush=True)
    for name, value in stats.items():
        print(f"  {name:26} {value}", flush=True)
    if stats["observations_scored"] == 0:
        print(
            "\nREFUSING TO REPORT A VERDICT: zero scored observations.\n"
            "  A null result needs a live population and this frame has none.\n"
            f"  trail dir: {trail_dir}\n"
            "  If trail_files_found is 0 the trail is not on this disk -- it is written on\n"
            "  refresh-worker and (as of 2026-09-20) is NOT in HOT_ARTIFACT_PATTERNS, so an\n"
            "  export returns count=0. Check `record_price_trail`'s `bytes_on_disk` before\n"
            "  reading an empty export as an empty trail: the file is bounded at 48 MB and\n"
            "  the export refuses any single file over 8 MB.",
            flush=True,
        )
        return 4

    # ---- 4. the contrasts --------------------------------------------------
    print("\n=== FORWARD CLV (observation -> close), probability points ===", flush=True)
    print("    the non-circular target. positive = market kept moving toward the pick.\n", flush=True)
    results = []
    scopes = sorted({scope for scope, _ in arms})
    for scope in scopes:
        row = contrast(scope, arms.get((scope, "positive"), []), arms.get((scope, "negative"), []))
        results.append(row)
        print(
            f"  {row['contrast']:28} diff {str(row['diff']):>8}  CI {row['ci95']}  "
            f"n {row['n_positive']}/{row['n_negative']}  t {row['welch_t']}",
            flush=True,
        )

    circular_results = []
    if args.show_circular:
        print("\n=== CONTROL: open->close CLV (CIRCULAR -- DO NOT QUOTE) ===", flush=True)
        print("    movement is a LEADING SEGMENT of this path. A large positive here", flush=True)
        print("    beside a null above IS the arithmetic overlap, not a finding.\n", flush=True)
        for scope in sorted({scope for scope, _ in circular}):
            row = contrast(scope, circular.get((scope, "positive"), []), circular.get((scope, "negative"), []))
            circular_results.append(row)
            print(
                f"  {row['contrast']:28} diff {str(row['diff']):>8}  CI {row['ci95']}  "
                f"n {row['n_positive']}/{row['n_negative']}",
                flush=True,
            )

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "window": {"start": args.start, "end": args.end},
                    "config": {"weight": args.weight, "line_weight": args.line_weight, "cap": args.cap},
                    "population": stats,
                    "forward_clv": results,
                    "circular_control": circular_results,
                },
                handle,
                indent=2,
            )
        print(f"\nwrote {args.json_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
