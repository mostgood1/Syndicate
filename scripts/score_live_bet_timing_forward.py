"""Score the PRE-REGISTERED live-timing candidates C1-C6 (todo #830) from `live_bet_timing_study.py` JSONs -- READ-ONLY.

The rules are fixed here and in `.syndicate/findings_2026-11-17_live_bet_timing.md` § "Forward test, PRE-REGISTERED";
change neither after reading an outcome. Every cell is a FRESH-quote cell (family `main_fresh`: the book had seen the
current score and the quote was <= 60 s old), game-clustered, 90% CI. A cell with fewer than MIN_GAMES games is
INSUFFICIENT, never support.

    python scripts/score_live_bet_timing_forward.py --dir /mnt/c/tmp/livetiming_fwd

Each candidate: HOLDS (every registered cell meets its rule), FAILS (a registered cell's CI sits on the wrong side of 0),
INSUFFICIENT (a registered cell has < MIN_GAMES games), else NOT CONFIRMED (cells point the registered way but a CI
includes 0).
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

MIN_GAMES = 30
F = "main_fresh"

# (candidate, label, sport, table, key, rule). rule: "pos" = CI lower > 0; "neg" = CI upper < 0; "zero" = CI includes 0
# (the registered claim is NO edge). Keys are the study JSON's row keys.
CELLS: list[tuple[str, str, str, str, tuple, str]] = [
    ("C1", "NCAAB totals flags, last 10% of regulation", "ncaab", "flags", ("totals", F, "any", "phase", "90-100"), "pos"),
    ("C1", "NCAAB spreads flags, 75-90%", "ncaab", "flags", ("spreads", F, "any", "phase", "75-90"), "pos"),
    ("C1", "NCAAF spreads flags, 75-90%", "ncaaf", "flags", ("spreads", F, "any", "phase", "75-90"), "pos"),
    ("C1", "NCAAF spreads flags, last 10%", "ncaaf", "flags", ("spreads", F, "any", "phase", "90-100"), "pos"),
    ("C1", "NCAAF totals flags, 75-90%", "ncaaf", "flags", ("totals", F, "any", "phase", "75-90"), "pos"),
    ("C2", "NCAAB under flags", "ncaab", "flags", ("totals", F, "under", "all", "all"), "pos"),
    ("C2", "NCAAF under flags", "ncaaf", "flags", ("totals", F, "under", "all", "all"), "pos"),
    ("C2", "WNCAAB under flags", "wncaab", "flags", ("totals", F, "under", "all", "all"), "pos"),
    ("C2", "NCAAB over flags (no edge)", "ncaab", "flags", ("totals", F, "over", "all", "all"), "zero"),
    ("C2", "NCAAF over flags (no edge)", "ncaaf", "flags", ("totals", F, "over", "all", "all"), "zero"),
    ("C2x", "NCAAB totals ahead of pace: over under-priced", "ncaab", "market", ("totals", F, "home_or_over", "pace", "ahead"), "pos"),
    ("C3", "NCAAB totals flags WITH the scoring heat", "ncaab", "flags", ("totals", F, "any", "vs_heat", "with_heat"), "pos"),
    ("C3", "NCAAB spreads flags WITH the run", "ncaab", "flags", ("spreads", F, "any", "vs_run", "with_run"), "pos"),
    ("C4", "NHL live ML: home over-priced", "nhl", "market", ("h2h", F, "home_or_over", "all", "all"), "neg"),
    ("C4", "NFL live ML: home over-priced", "nfl", "market", ("h2h", F, "home_or_over", "all", "all"), "neg"),
    ("C4r", "WNCAAB live ML: home under-priced", "wncaab", "market", ("h2h", F, "home_or_over", "all", "all"), "pos"),
    ("C5", "NCAAB model ML flags, first 25% of regulation", "ncaab", "flags", ("h2h", F, "any", "phase", "0-25"), "neg"),
    ("C6", "NBA totals flags (no edge)", "nba", "flags", ("totals", F, "any", "all", "all"), "zero"),
    ("C6", "NBA spreads flags (no edge)", "nba", "flags", ("spreads", F, "any", "all", "all"), "zero"),
]
# C3's contrast: the WITH cell must also beat the AGAINST cell's mean (reported; part of HOLDS).
CONTRASTS = {
    ("ncaab", ("totals", F, "any", "vs_heat", "with_heat")): ("totals", F, "any", "vs_heat", "against_heat"),
    ("ncaab", ("spreads", F, "any", "vs_run", "with_run")): ("spreads", F, "any", "vs_run", "against_run"),
}
# C1's contrast: the late cell's mean must exceed the same market's first-quarter-of-regulation (0-25) mean.
LATE_VS_EARLY = "0-25"


def cell_verdict(row: dict[str, Any] | None, rule: str) -> str:
    if row is None or row.get("games", 0) < MIN_GAMES or not row.get("ci90_pp"):
        return "INSUFFICIENT"
    lo, hi = row["ci90_pp"]
    if rule == "pos":
        return "MEETS" if lo > 0 else "FAILS" if hi < 0 else "OPEN"
    if rule == "neg":
        return "MEETS" if hi < 0 else "FAILS" if lo > 0 else "OPEN"
    return "MEETS" if lo <= 0 <= hi else "FAILS"          # "zero": the claim is no edge


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    data: dict[str, dict[str, dict[tuple, dict[str, Any]]]] = {}
    for sport in sorted({c[2] for c in CELLS}):
        p = os.path.join(args.dir, f"{sport}.json")
        if os.path.exists(p):
            d = json.load(open(p))
            data[sport] = {"flags": {tuple(r["key"]): r for r in d["flags"]}, "market": {tuple(r["key"]): r for r in d["market"]},
                           "games": d["stats"].get("graded_games"), "days": len(d.get("ledger_days") or [])}
    by_cand: dict[str, list[str]] = {}
    for cand, label, sport, table, key, rule in CELLS:
        row = (data.get(sport) or {}).get(table, {}).get(key)
        v = cell_verdict(row, rule)
        note = ""
        if v == "MEETS" and (sport, key) in CONTRASTS:
            other = data[sport]["flags"].get(CONTRASTS[(sport, key)])
            if other is None or other["mean_pp"] >= row["mean_pp"]:
                v, note = "OPEN", " (does not beat its AGAINST cell)"
            else:
                note = f" (against cell {other['mean_pp']:+.1f})"
        if v == "MEETS" and cand == "C1":
            early = data[sport]["flags"].get(key[:4] + (LATE_VS_EARLY,))
            if early is not None and early["mean_pp"] >= row["mean_pp"]:
                v, note = "OPEN", " (not above the 0-25% cell)"
            elif early is not None:
                note = f" (0-25% cell {early['mean_pp']:+.1f})"
        by_cand.setdefault(cand, []).append(v)
        shown = f"{row['mean_pp']:+6.1f} [{row['ci90_pp'][0]:+.1f}, {row['ci90_pp'][1]:+.1f}] {row['games']}g" if row and row.get("ci90_pp") else "no cell"
        print(f"{cand:4} {label:50} {sport:7} {shown:32} rule={rule:4} -> {v}{note}")
    print()
    for cand, vs in by_cand.items():
        verdict = ("FAILS" if "FAILS" in vs else "INSUFFICIENT" if "INSUFFICIENT" in vs
                   else "HOLDS" if all(v == "MEETS" for v in vs) else "NOT CONFIRMED")
        print(f"{cand}: {verdict}  ({', '.join(vs)})")
    for sport, d in sorted(data.items()):
        print(f"  {sport}: {d['games']} graded games over {d['days']} ledger days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
