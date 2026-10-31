"""Calibration behind the D7 capital-ladder pre-registration (plan #736, decision D7).

`.syndicate/findings_2026-10-31_d7_capital_ladder_preregistration.md` quotes every
number this prints. Offline and self-contained: numpy only, a fixed seed, no repo
import and no ledger, record or venue read.

The two per-bet spreads are derived from published aggregates, not from bets:
- CLV: the Suggested grade's pooled EV at the Shin close, +1.51% [+0.63, +2.44]
  (95% by game) on 457 bets (`findings_2026-10-26_suggested_grade.md`):
  SE 0.462pp, so a game-clustered effective SD of 9.87pp per bet.
- ROI: the live Kalshi pregame book, -11.8% flat, CI90 [-20, -4] by game, on 548
  bets (`findings_2026-10-24_live_cell_scorecard.md`): SE 4.86pp, effective SD
  113.8pp per bet.

    py -3 scripts/capital_ladder_calibration.py [--paths 400000] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np

SEED = 20261031
SD_CLV = 0.462 * math.sqrt(457)          # pp per bet
SD_ROI = (16.0 / (2 * 1.645)) * math.sqrt(548)  # pp per bet

# The Phase 2 gate's three-look O'Brien-Fleming boundaries at one-sided 0.025
# (prereg 8d16ab07 section 7 reproduces these textbook values).
OBF3 = (3.471, 2.454, 2.004)
LOOK_BETS = (400, 800, 1200)

KELLY_AT_MAX = 0.05
BELIEVED_EDGE = 0.02      # the edge the sizer believes, whatever the truth is
PRICE_LO, PRICE_HI = 0.40, 0.75   # the live price band (user 10-23)
FUND_FRACTION = 0.01      # rung max <= 1% of the funding capital (--fund overrides)


def three_look_alpha(rng: np.random.Generator, paths: int) -> float:
    """Type I error of OBF3 under the null, by simulation (should read ~0.025)."""
    info = np.array(LOOK_BETS, dtype=float)
    inc = rng.standard_normal((paths, 3)) * np.sqrt(np.diff(np.concatenate([[0.0], info])))
    z = np.cumsum(inc, axis=1) / np.sqrt(info)
    return float(np.mean((z >= np.array(OBF3)).any(axis=1)))


def look_pass_probability(rng: np.random.Generator, paths: int, mean_pp: float, sd_pp: float,
                          bets: tuple[float, ...], bounds: tuple[float, ...]) -> list[float]:
    """Cumulative P(passed by look k) for a mean of `mean_pp` per bet."""
    info = np.array(bets, dtype=float)
    steps = np.diff(np.concatenate([[0.0], info]))
    sums = np.cumsum(rng.standard_normal((paths, len(bets))) * sd_pp * np.sqrt(steps) + mean_pp * steps, axis=1)
    z = (sums / info) / (sd_pp / np.sqrt(info))
    passed = np.zeros(paths, dtype=bool)
    out = []
    for k in range(len(bets)):
        passed |= z[:, k] >= bounds[k]
        out.append(float(passed.mean()))
    return out


def edge_stop_probability(rng: np.random.Generator, paths: int, mean_pp: float,
                          first: int = 200, step: int = 50, last: int = 1200, z_stop: float = -2.0) -> float:
    """P(the weekly CLV read ever shows Z <= z_stop) between `first` and `last` bets at a rung."""
    reads = np.arange(first, last + 1, step, dtype=float)
    steps = np.diff(np.concatenate([[0.0], reads]))
    sums = np.cumsum(rng.standard_normal((paths, reads.size)) * SD_CLV * np.sqrt(steps) + mean_pp * steps, axis=1)
    z = (sums / reads) / (SD_CLV / np.sqrt(reads))
    return float(np.mean((z <= z_stop).any(axis=1)))


def simulate_bets(rng: np.random.Generator, paths: int, bets: int, true_roi: float) -> np.ndarray:
    """P&L per bet in units of the rung's MAX stake (min = max / 2, as every rung is)."""
    c = rng.uniform(PRICE_LO, PRICE_HI, size=(paths, bets))
    kelly = BELIEVED_EDGE * c / (1.0 - c)
    stake = 0.5 + 0.5 * np.minimum(1.0, kelly / KELLY_AT_MAX)
    p_win = np.minimum(0.999, c * (1.0 + true_roi))
    win = rng.random((paths, bets)) < p_win
    return np.where(win, stake * (1.0 / c - 1.0), -stake)


def loss_stop_probability(rng: np.random.Generator, paths: int, true_roi: float, bets_per_day: int,
                          days: int, loss_fraction: float, fund_fraction: float) -> float:
    """P(any trailing-7-day loss >= loss_fraction of capital within `days`), capital = max / fund_fraction."""
    capital_units = 1.0 / fund_fraction
    daily = simulate_bets(rng, paths, bets_per_day * days, true_roi).reshape(paths, days, bets_per_day).sum(axis=2)
    cum = np.concatenate([np.zeros((paths, 1)), np.cumsum(daily, axis=1)], axis=1)
    week = cum[:, 7:] - cum[:, :-7]
    return float(np.mean((week <= -loss_fraction * capital_units).any(axis=1)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--paths", type=int, default=400_000)
    ap.add_argument("--fund", type=float, default=FUND_FRACTION, help="rung max as a share of funding capital")
    ap.add_argument("--json", help="also write the readings here")
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)
    out: dict = {"seed": SEED, "sd_clv_pp": round(SD_CLV, 2), "sd_roi_pp": round(SD_ROI, 1), "obf3": OBF3,
                 "fund_fraction": args.fund}

    out["obf3_null_alpha"] = round(three_look_alpha(rng, 2_000_000), 4)

    out["clv_rung_read_power"] = {
        f"{d:+.2f}pp": [round(x, 3) for x in look_pass_probability(rng, args.paths, d, SD_CLV, LOOK_BETS, OBF3)]
        for d in (0.0, 0.5, 0.75, 1.0, 1.5, 2.0)
    }
    out["edge_stop_probability"] = {
        f"{d:+.2f}pp": round(edge_stop_probability(rng, args.paths // 4, d), 4) for d in (1.0, 0.5, 0.0, -0.5, -1.0)
    }

    # ROI over ALL venue-settled live bets: a sharp-graded share q of them counts toward the CLV looks.
    roi = {}
    for q in (0.28, 0.5):
        for label, sharp in (("R0->R1", (400, 800, 1200)), ("R2->R3", (1200, 1600, 2000))):
            n = tuple(s / q for s in sharp)
            roi[f"q={q} {label} n_roi={[round(x) for x in n]}"] = {
                f"{r:+.1f}%": [round(x, 3) for x in look_pass_probability(rng, args.paths, r, SD_ROI, n, OBF3)]
                for r in (1.0, 2.0, 3.0, 4.0)
            }
    out["roi_ci_above_zero_power"] = roi

    small = max(2_000, args.paths // 100)
    loss = {}
    for per_day in (10, 20):
        for frac in (0.10, 0.15, 0.20, 0.25):
            loss[f"{per_day}/day loss>={int(frac * 100)}%"] = {
                f"{r:+.0%}": round(loss_stop_probability(rng, small, r, per_day, 98, frac, args.fund), 4)
                for r in (0.02, 0.0, -0.04, -0.08)
            }
    out["loss_stop_14_weeks"] = loss

    print(json.dumps(out, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
