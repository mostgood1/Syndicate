"""Measure the stolen-base multipliers the sim needs (lane mlb-combined-calibration).

The sim (simulate.py, pre-PA steal block) draws, before each PA with a runner on 1B,
2B empty and <= 1 out, P(attempt of 2B) = the runner's `sb_attempt_rate`, then
P(success) = `sb_success_rate`. build_roster derives the attempt rate as
(SB+CS) / (1B+BB+HBP) -- a per-TIME-ON-BASE rate -- while the sim applies it per PA.

This measures, over the REAL opportunities of the same games (StatsAPI pbp, true
pre-PA base state from scripts/mlb_dp_advancement_rates.py):
  attempt_mult = real attempts of 2B / sum of the runner's profile attempt rate
  success_mult = real steals of 2B   / sum of the runner's profile success rate over attempts
using each runner's profile from the game's roster artifact (lineup + bench), clamped
exactly as the sim clamps it. They become GameConfig `sb_attempt_mult` / `sb_success_mult`.

  python scripts/mlb_steal_rate_calibration.py --data-root <fleet mlb data> --roster-root <rebuilt root> \\
      --dates 2026-06-15 ... --cache ~/mlb_pbp_cache --out steals.json
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mlb_dp_advancement_rates as pbp  # noqa: E402

ATTEMPT = ("stolen_base_2b", "caught_stealing_2b", "pickoff_caught_stealing_2b")


def profiles(roster_root: Path, date: str) -> dict[int, dict]:
    """game_pk -> {mlbam_id: (attempt_rate, success_rate)} from the roster artifacts."""
    out = {}
    for f in glob.glob(str(roster_root / "daily" / "snapshots" / date / "roster_objs" / "roster_obj_*.json")):
        m = re.search(r"pk(\d+)", Path(f).name)
        if not m:
            continue
        o = json.loads(Path(f).read_text(encoding="utf-8"))
        rates = {}
        for side in ("away", "home"):
            lu = (o.get(side) or {}).get("lineup") or {}
            for b in (lu.get("batters") or []) + (lu.get("bench") or []):
                pid = int(((b.get("player") or {}).get("mlbam_id")) or 0)
                if pid:
                    ar = max(0.0, min(0.40, float(b.get("sb_attempt_rate") or 0.0)))
                    sr = max(0.40, min(0.95, float(b.get("sb_success_rate") or 0.72)))
                    rates[pid] = (ar, sr)
        out[int(m.group(1))] = rates
    return out


def game_counts(data: dict, rates: dict, acc: dict) -> None:
    for pre, outs_before, play in pbp.plays_with_state(data):
        rid = pre.get("1B")
        if not rid or pre.get("2B") or outs_before > 1:
            continue
        if rid not in rates:
            acc["runner_not_in_roster"] += 1
            continue
        ar, sr = rates[rid]
        acc["opportunities"] += 1
        acc["expected_attempts"] += ar
        kinds = {(r.get("details") or {}).get("eventType") for r in play.get("runners") or []
                 if ((r.get("details") or {}).get("runner") or {}).get("id") == rid}
        att = kinds & set(ATTEMPT)
        if att:
            acc["attempts"] += 1
            acc["expected_successes"] += sr
            acc["steals"] += "stolen_base_2b" in att


def poisson_ratio_ci(k: int, expected: float) -> list[float]:
    if expected <= 0:
        return [float("nan"), float("nan")]
    lo = 0.0 if k == 0 else (k - 1.96 * math.sqrt(k)) / expected
    return [max(0.0, lo), (k + 1.96 * math.sqrt(max(k, 1))) / expected]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", required=True, help="fleet mlb data (stored sims -> game pks)")
    ap.add_argument("--roster-root", required=True, help="root whose roster_objs supply the profiles")
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--cache", default="~/mlb_pbp_cache")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    data_dir = Path(os.path.expanduser(args.data_root))
    roster_root = Path(os.path.expanduser(args.roster_root))
    cache = Path(os.path.expanduser(args.cache))
    acc = {"opportunities": 0, "expected_attempts": 0.0, "attempts": 0, "expected_successes": 0.0, "steals": 0,
           "runner_not_in_roster": 0, "games": 0, "games_without_roster": 0}
    for d in sorted(set(args.dates)):
        profs = profiles(roster_root, d)
        for pk in pbp.game_pks(data_dir, d):
            if pk not in profs:
                acc["games_without_roster"] += 1
                continue
            acc["games"] += 1
            game_counts(pbp.feed(pk, cache), profs[pk], acc)
    am = acc["attempts"] / acc["expected_attempts"] if acc["expected_attempts"] else None
    sm = acc["steals"] / acc["expected_successes"] if acc["expected_successes"] else None
    rep = {**acc, "sb_attempt_mult": am, "attempt_mult_ci95": poisson_ratio_ci(acc["attempts"], acc["expected_attempts"]),
           "sb_success_mult": sm, "real_success_rate": acc["steals"] / acc["attempts"] if acc["attempts"] else None,
           "profile_success_rate": acc["expected_successes"] / acc["attempts"] if acc["attempts"] else None,
           "real_attempts_per_opportunity": acc["attempts"] / acc["opportunities"] if acc["opportunities"] else None,
           "profile_attempts_per_opportunity": acc["expected_attempts"] / acc["opportunities"] if acc["opportunities"] else None}
    Path(args.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
