"""#202 -- the pre-registered MLB conditional-edge scan, executed as written.

RUN 2026-09-01 (`#624` step 4), on 9,479 graded rows over 51 dates pulled from
PRODUCTION. RESULT: **4 tests run, 0 candidates, NO EDGE FOUND** -- which is the
pre-registration's own stated prior, and a real finding rather than a failed
search.

THE LARGER RESULT, and why this scan sat unrun for a month: **7 of the 8
hypotheses are NOT EXECUTABLE against the production graded surface.**

  H1/H2  K quartiles     `pitcher_k_rate` 0/197 K rows, `lineup_k_rate` 6/197
  H3     K line height   RAN -- and failed, see below
  H4/H5/H6  HR slices    park / platoon / pitch-mix fields 0/1,691 HR rows
  H7     sim favourite   `ml` rows carry NO model probability, only odds
  H8     NRFI / first1   no segment bucket exists, 0 settled first-inning rows

The per-row MECHANISM payload those hypotheses slice on survives on **534 of
9,479 graded rows -- two dates of fifty-one** (2026-05-09, 05-18), and it is
DATE-scoped rather than root-scoped: both artifact roots carry it on those two
dates and neither carries it on the rest. Restoring it to the graded rows is
the precondition for ever running H1/H2/H4/H5/H6. H8 was ordered FIRST by the
pre-registration and is blocked by a different thing entirely -- segments
publish a distribution and no ACTUAL, which the MLB accuracy assessment had
already recorded.

H3, the only hypothesis that ran, FAILED IN THE OPPOSITE DIRECTION to its
prediction. Of its four cells only `<=4.5` clears the >=60-bet size rule
(n=128), and that cell is ROI **-0.142** with both chronological halves
negative (-0.109 / -0.181), fragility -0.200, a bootstrap CI of
[-0.295, +0.015] spanning zero, and monotonicity across cells SPIKY. The
pre-registration is explicit that a result in the wrong direction is a failure,
not a discovery.

RULES ARE TRANSCRIBED, NOT INVENTED. They come from
`docs/ai_context/mlb_edge_scan_preregistration.md`, committed 2026-08-05 BEFORE
any segment numbers were computed, precisely so they could not be adjusted after
seeing results. A slice is a CANDIDATE only if it clears ALL SIX:

  1. SIZE          >= 60 bets in the cell on the full sample
  2. BOTH HALVES   chronological 50/50 split, ROI > 0 in BOTH halves
  3. FRAGILITY     dropping the top 5 WINNING bets still leaves ROI > 0
  4. BOOTSTRAP     2,000-resample 95% CI on full-sample ROI excludes zero
  5. DIRECTION     matches the pre-registered directional prediction
  6. MONOTONICITY  where the mechanism implies ordering (H1, H2, H3)

Reporting requirement, also pre-registered: state the TOTAL number of tests run
and how many candidates survived. If survivors are about what chance predicts
(~5% of tests), the honest conclusion is "no edge found", regardless of how good
any single cell looks.

Input: `reports/edge_scan/scan_rows.jsonl`, produced by pulling
`*betting_day_payloads_retuned/season_betting_day_*.json` from
`/api/ops/artifacts/export` -- Render, never the local `data/**` mirror.
"""
from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROWS = Path(__file__).resolve().parents[1] / "reports" / "edge_scan" / "scan_rows.jsonl"
random.seed(2026)  # pre-registration names seed 2026 for its splits


# --------------------------------------------------------------------- payoff
def profit_units(row: dict) -> float | None:
    """Realised profit per 1u staked. Uses the artifact's own settlement where
    present so this scan cannot disagree with the ledger about who won."""
    profit = row.get("profit_u")
    stake = row.get("stake_u")
    try:
        if profit is not None and stake:
            return float(profit) / float(stake)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    odds = row.get("odds")
    try:
        price = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if row.get("result") == "win":
        return price / 100.0 if price > 0 else 100.0 / abs(price)
    return -1.0


def roi(rows: list[dict]) -> float | None:
    payoffs = [p for p in (profit_units(r) for r in rows) if p is not None]
    return (sum(payoffs) / len(payoffs)) if payoffs else None


# ---------------------------------------------------------------- the 6 rules
def rule_size(rows: list[dict]) -> tuple[bool, str]:
    return len(rows) >= 60, f"n={len(rows)}"


def rule_both_halves(rows: list[dict]) -> tuple[bool, str]:
    dates = sorted({r["date"] for r in rows})
    if len(dates) < 2:
        return False, "one date"
    cut = dates[len(dates) // 2]
    first = [r for r in rows if r["date"] < cut]
    second = [r for r in rows if r["date"] >= cut]
    a, b = roi(first), roi(second)
    if a is None or b is None:
        return False, "empty half"
    return (a > 0 and b > 0), f"{a:+.3f}/{b:+.3f}"


def rule_fragility(rows: list[dict]) -> tuple[bool, str]:
    """Drop the five biggest WINNERS. This is the rule that killed the earlier
    moneyline candidate: 5 of 358 bets carried the whole result."""
    payoffs = sorted((p for p in (profit_units(r) for r in rows) if p is not None), reverse=True)
    trimmed = payoffs[5:]
    if not trimmed:
        return False, "too few"
    value = sum(trimmed) / len(trimmed)
    return value > 0, f"{value:+.3f}"


def rule_bootstrap(rows: list[dict], resamples: int = 2000) -> tuple[bool, str]:
    payoffs = [p for p in (profit_units(r) for r in rows) if p is not None]
    if len(payoffs) < 2:
        return False, "too few"
    n = len(payoffs)
    means = []
    for _ in range(resamples):
        means.append(sum(random.choice(payoffs) for _ in range(n)) / n)
    means.sort()
    lo = means[int(0.025 * resamples)]
    hi = means[int(0.975 * resamples)]
    return (lo > 0 or hi < 0), f"[{lo:+.3f},{hi:+.3f}]"


def rule_direction(observed_roi: float | None, predicted: str) -> tuple[bool, str]:
    """A result in the WRONG direction is a failure, not a discovery."""
    if observed_roi is None:
        return False, "no roi"
    if predicted == "positive":
        return observed_roi > 0, f"{observed_roi:+.3f} vs >0"
    if predicted == "negative":
        return observed_roi < 0, f"{observed_roi:+.3f} vs <0"
    return True, "none stated"


def rule_monotonic(cell_rois: list[tuple[str, float | None]]) -> tuple[bool, str]:
    values = [v for _, v in cell_rois if v is not None]
    if len(values) < 3:
        return False, "too few cells"
    up = all(b >= a for a, b in zip(values, values[1:]))
    down = all(b <= a for a, b in zip(values, values[1:]))
    return (up or down), ("monotone" if (up or down) else "spiky")


# ----------------------------------------------------------------- slicing
def quartile_buckets(rows: list[dict], field: str) -> list[tuple[str, list[dict]]]:
    have = [r for r in rows if isinstance(r.get(field), (int, float))]
    if len(have) < 8:
        return []
    have.sort(key=lambda r: float(r[field]))
    size = len(have) // 4
    out = []
    for index in range(4):
        chunk = have[index * size:(index + 1) * size] if index < 3 else have[3 * size:]
        if chunk:
            lo = float(chunk[0][field])
            hi = float(chunk[-1][field])
            out.append((f"Q{index + 1} [{lo:.3f}..{hi:.3f}]", chunk))
    return out


def line_buckets(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    edges = [(("<=4.5"), lambda v: v <= 4.5), (("5.5"), lambda v: 4.5 < v <= 5.5),
             (("6.5"), lambda v: 5.5 < v <= 6.5), ((">=7.5"), lambda v: v > 6.5)]
    out = []
    for label, test in edges:
        chunk = [r for r in rows if isinstance(r.get("market_line"), (int, float)) and test(float(r["market_line"]))]
        if chunk:
            out.append((label, chunk))
    return out


def main() -> int:
    rows = [json.loads(line) for line in ROWS.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"graded rows pulled from production: {len(rows)}")
    dates = sorted({r["date"] for r in rows})
    print(f"dates: {len(dates)}  {dates[0]}..{dates[-1]}")
    from collections import Counter
    print("roots:", dict(Counter(r["root"] for r in rows)))
    print("props:", dict(Counter(str(r.get('prop') or r.get('bucket')) for r in rows).most_common(10)))

    k_rows = [r for r in rows if str(r.get("prop") or "") == "strikeouts"]
    hr_rows = [r for r in rows if str(r.get("prop") or "") == "batter_home_runs"]
    ml_rows = [r for r in rows if r.get("bucket") == "ml"]
    print(f"\nK props {len(k_rows)} | HR {len(hr_rows)} | game ml {len(ml_rows)}")

    hypotheses = [
        ("H1", "K: pitcher season K-rate quartile", k_rows,
         lambda rs: quartile_buckets(rs, "pitcher_k_rate"), "positive", True),
        ("H2", "K: opposing lineup avg K-rate quartile", k_rows,
         lambda rs: quartile_buckets(rs, "lineup_k_rate"), "positive", True),
        ("H3", "K: market line height", k_rows, line_buckets, "positive", True),
        ("H4", "HR: park HR multiplier quartile", hr_rows,
         lambda rs: quartile_buckets(rs, "park_hr_mult"), "none", False),
        ("H5", "HR: platoon-edge magnitude quartile", hr_rows,
         lambda rs: quartile_buckets(rs, "batter_platoon_hr_mult"), "positive", False),
        ("H6", "HR: pitch-mix fit quartile", hr_rows,
         lambda rs: quartile_buckets(rs, "pitcher_primary_pitch_type_hr_mult"), "none", False),
        ("H7", "game: sim favourite vs underdog", ml_rows,
         lambda rs: quartile_buckets(rs, "model_prob_over"), "negative", False),
    ]

    tests_run = 0
    candidates = []
    print("\n" + "=" * 108)
    for tag, title, source, slicer, predicted, needs_monotone in hypotheses:
        print(f"\n{tag}  {title}   (source rows {len(source)}, prediction: {predicted})")
        if not source:
            print("    NOT RUNNABLE - no graded rows for this market")
            continue
        cells = slicer(source)
        if not cells:
            print("    NOT RUNNABLE - slicing field absent on these rows")
            continue
        cell_rois: list[tuple[str, float | None]] = []
        print(f"    {'cell':<26}{'n':>6}{'ROI':>9}{'size':>7}{'halves':>16}{'fragile':>10}{'boot95':>20}{'dir':>6}")
        for label, chunk in cells:
            tests_run += 1
            value = roi(chunk)
            cell_rois.append((label, value))
            ok_size, s_size = rule_size(chunk)
            ok_half, s_half = rule_both_halves(chunk)
            ok_frag, s_frag = rule_fragility(chunk)
            ok_boot, s_boot = rule_bootstrap(chunk)
            ok_dir, _ = rule_direction(value, predicted)
            print(f"    {label:<26}{len(chunk):>6}{(value if value is not None else float('nan')):>+9.3f}"
                  f"{('ok' if ok_size else 'FAIL'):>7}{s_half:>16}{s_frag:>10}{s_boot:>20}"
                  f"{('ok' if ok_dir else 'FAIL'):>6}")
            if ok_size and ok_half and ok_frag and ok_boot and ok_dir:
                candidates.append((tag, label, len(chunk), value))
        if needs_monotone:
            ok_mono, s_mono = rule_monotonic(cell_rois)
            print(f"    monotonicity across cells: {s_mono}"
                  + ("" if ok_mono else "   -> any candidate in this hypothesis FAILS rule 6"))
            if not ok_mono:
                candidates = [c for c in candidates if c[0] != tag]

    print("\n" + "=" * 108)
    print(f"TESTS RUN: {tests_run}")
    print(f"CANDIDATES SURVIVING ALL SIX RULES: {len(candidates)}")
    for tag, label, n, value in candidates:
        print(f"   {tag} {label} n={n} ROI {value:+.3f}")
    expected = 0.05 * tests_run
    print(f"\nChance expectation at p<0.05 over {tests_run} tests: ~{expected:.1f} apparent edges.")
    if len(candidates) <= expected:
        print("VERDICT: survivors are at or below the chance expectation -> NO EDGE FOUND.")
        print("That is the pre-registered prior and it is a real finding, not a failed search.")
    else:
        print("VERDICT: survivors EXCEED chance. Per the pre-registration these earn a")
        print("FORWARD-LOOKING PAPER-TRADE LOG on dates they were not discovered on -- nothing")
        print("ships to the board on this evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
