"""Empirical null for the two-stage goal-timing sweep.

WHY THIS EXISTS. The sweep reported "417 selected on fit -> 36 survive on
holdout (25 distinct cells)", against a chance expectation I computed as
`0.05 * 417 ~= 20`. That arithmetic is worthless: the holdout test is not a
p=0.05 test, it is "CI lower bound > 0.25 AND delta >= 0.02" evaluated on
correlated samples. The only honest way to know how many cells survive when
NOTHING is there is to run the identical pipeline on data where nothing is
there, and count.

HOW THE NULL IS BUILT, and why not the obvious way. The obvious shuffle --
permute `label` across samples within a band -- destroys the association but
ALSO destroys the within-match correlation: adjacent samples in one match share
the same goal, so their labels move together. Breaking that makes the null
tighter than reality and would make chance survivors look rarer than they are,
which is the error direction that manufactures discoveries.

Instead the goal series are permuted BETWEEN MATCHES within a league. Features
come from match A, labels from match B. Within-match label clustering survives
intact, per-league base rates are preserved, and the feature-label link is
severed -- which is exactly the null hypothesis being tested.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.soccer_goal_timing_2y import _BAND, _BE_31, _hold, cell_score, samples
from scripts.soccer_load_2y import load_2y


def permute_goals(matches: list[dict], rng: random.Random) -> list[dict]:
    """Reassign each match's goal series to a different match in the same league."""
    by_league: dict[str, list[int]] = {}
    for i, m in enumerate(matches):
        by_league.setdefault(m["league"], []).append(i)
    out = [dict(m) for m in matches]
    for idxs in by_league.values():
        if len(idxs) < 2:
            continue
        donors = idxs[:]
        rng.shuffle(donors)
        # derangement-ish: nudge any match that drew its own goals
        for pos, i in enumerate(idxs):
            if donors[pos] == i and len(donors) > 1:
                swap = (pos + 1) % len(donors)
                donors[pos], donors[swap] = donors[swap], donors[pos]
        for pos, i in enumerate(idxs):
            out[i]["goals"] = matches[donors[pos]]["goals"]
    return out


def run_pipeline(matches: list[dict], feats: list[str], *, half_life: float,
                 window: float, step: float, pct: float) -> tuple[int, int, int]:
    """(selected, survivors, distinct cells) -- the identical two-stage sweep."""
    fit = [m for m in matches if not _hold(m["match_id"])]
    hold = [m for m in matches if _hold(m["match_id"])]
    leagues = sorted({m["league"] for m in matches})

    cand = []
    for feature in feats:
        fit_s = samples(fit, half_life=half_life, window=window, step=step, feature=feature)
        for lg in leagues + ["_pooled"]:
            rows_lg = fit_s if lg == "_pooled" else [r for r in fit_s if r["league"] == lg]
            fb: dict[int, list[dict]] = {}
            for r in rows_lg:
                fb.setdefault(int(r["t"] // _BAND), []).append(r)
            for b, rows in fb.items():
                if len(rows) < 200:
                    continue
                clock, hit, n, fci = cell_score(rows, pct)
                if n >= 40 and (hit - clock) >= 0.02 and fci[0] > _BE_31:
                    cand.append({"league": lg, "band": b, "feature": feature,
                                 "fit_delta": hit - clock})
    cand.sort(key=lambda c: -c["fit_delta"])

    cache: dict[str, list[dict]] = {}
    survivors = []
    for c in cand[:120]:
        if c["feature"] not in cache:
            cache[c["feature"]] = samples(hold, half_life=half_life, window=window,
                                          step=step, feature=c["feature"])
        rows = [r for r in cache[c["feature"]] if int(r["t"] // _BAND) == c["band"]
                and (c["league"] == "_pooled" or r["league"] == c["league"])]
        clock, hit, n, ci = cell_score(rows, pct)
        if n >= 40 and ci[0] > _BE_31 and (hit - clock) >= 0.02:
            survivors.append((c["league"], c["band"]))
    return len(cand), len(survivors), len(set(survivors))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--window", type=float, default=600.0)
    ap.add_argument("--step", type=float, default=60.0)
    ap.add_argument("--half-life", type=float, default=900.0)
    ap.add_argument("--pct", type=float, default=0.75)
    ap.add_argument("--features",
                    default="xg,count,ontarget,inbox,bigchance,vmom_abs,vmom_slope,red_adv,subs")
    ap.add_argument("--out", default="reports/soccer_backtest/goal_timing_null.json")
    args = ap.parse_args()

    matches = load_2y()["matches"]
    feats = [f.strip() for f in args.features.split(",") if f.strip()]
    print("null control: %d matches, %d features, %d runs"
          % (len(matches), len(feats), args.runs))

    real = run_pipeline(matches, feats, half_life=args.half_life, window=args.window,
                        step=args.step, pct=args.pct)
    print("\nREAL DATA      selected %4d   survivors %3d   distinct cells %3d"
          % real)

    print("\nPERMUTED (goal series swapped between matches within league):")
    nulls = []
    for i in range(args.runs):
        rng = random.Random(1000 + i)
        shuffled = permute_goals(matches, rng)
        res = run_pipeline(shuffled, feats, half_life=args.half_life, window=args.window,
                           step=args.step, pct=args.pct)
        nulls.append(res)
        print("  run %d        selected %4d   survivors %3d   distinct cells %3d"
              % (i + 1, res[0], res[1], res[2]))

    d_null = [n[2] for n in nulls]
    mean_null = statistics.mean(d_null)
    print("\n=== VERDICT ===")
    print("  real distinct cells      %d" % real[2])
    print("  null distinct cells      mean %.1f   range %d-%d"
          % (mean_null, min(d_null), max(d_null)))
    beat = sum(1 for x in d_null if x >= real[2])
    print("  null runs matching/beating real: %d of %d" % (beat, len(d_null)))
    if real[2] > max(d_null) and real[2] >= 2 * max(1.0, mean_null):
        v = "SIGNAL -- real clears every null run and at least doubles the null mean."
    elif real[2] > mean_null * 1.5:
        v = "WEAK -- real exceeds the null but not decisively. Treat cells as leads, not findings."
    else:
        v = ("NOISE -- the sweep produces this many 'survivors' on data with NO "
             "feature-label link. The surviving cells are not evidence.")
    print("  %s" % v)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"real": {"selected": real[0], "survivors": real[1], "distinct": real[2]},
         "null": [{"selected": n[0], "survivors": n[1], "distinct": n[2]} for n in nulls],
         "null_mean_distinct": mean_null, "verdict": v}, indent=2), encoding="utf-8")
    print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
