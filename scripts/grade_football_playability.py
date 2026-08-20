"""Which picks, if any, are PLAYABLE? -- ATS, not MAE.

Everything measured so far is MEAN ABSOLUTE ERROR: how close the model's margin
lands to the result. That is the wrong metric for a betting decision and I had
not tested the right one. A model can carry WORSE MAE and still be playable if
its disagreements with the market are DIRECTIONALLY right; it can also carry
better MAE and be unplayable if it is only accurate where it agrees.

THE TEST. For each game:

    edge = model_margin - market_margin          (market_margin = -spread)
    bet the side the model favours when |edge| >= threshold
    did that side COVER?

Graded against the **52.4% breakeven** at standard -110 juice, not against 50%.
A 51% strategy loses money, so 50% is the wrong bar and using it is how a losing
system reads as an edge.

THREE THINGS THAT KEEP THIS HONEST:

1. **A threshold sweep is a MULTIPLE COMPARISON.** Testing six thresholds and
   reporting the best is data mining -- this session already caught two TIED
   NCAAF buckets that were pure multiplicity. Every threshold is printed, so the
   sweep is visible rather than filtered.
2. **Binomial confidence intervals**, because an ATS rate on 40 bets has a
   +-15pt CI and "58%" on small n is indistinguishable from noise.
3. **An UNDER-DISPERSED model biases toward one side systematically.** If the
   model always says "closer than the market", every large edge is a bet on the
   UNDERDOG. That is a market-fade strategy, not model skill, so the underdog
   share of bets is reported: near 100% means the threshold is selecting a side,
   not a signal.

NCAAF carries the power here (858 games, clean out-of-sample); NFL preseason has
96 and can only ever be indicative.
"""
import csv
import glob
import statistics
import sys
from pathlib import Path

REPO = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")
sys.path.insert(0, str(REPO))
from syndicate.features.football.pick_ledger import load_ledger  # noqa: E402

BREAKEVEN = 0.5238  # -110 both sides


def wilson(k: int, n: int) -> tuple[float, float]:
    """95% Wilson interval -- correct at small n, unlike normal approximation."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    z = 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - m), min(1.0, c + m))


def games_from_ledger(sport: str, seasons) -> dict:
    rows = []
    for s in seasons:
        rows += load_ledger(sport, s)
    out = {}
    for r in rows:
        if r.model_margin is None or r.spread_close is None or r.realised_margin is None:
            continue
        g = out.setdefault((r.season, r.game_id), {"m": r.model_margin, "a": r.realised_margin, "l": []})
        g["l"].append(r.spread_close)
    return out


def games_from_csv(pattern: str, ledger_lookup: dict) -> dict:
    return ledger_lookup


def report(label: str, games: dict) -> None:
    print("\n" + "=" * 78)
    print("%s  --  %d gradable games" % (label, len(games)))
    print("=" * 78)
    if not games:
        return
    rows = []
    for k, v in games.items():
        market = -statistics.median(v["l"])          # implied home margin
        edge = v["m"] - market                        # + => model likes HOME more
        # ATS: bet the model's side. home covers when actual > market margin.
        home_covers = v["a"] > market
        push = abs(v["a"] - market) < 1e-9
        won = (home_covers if edge > 0 else (not home_covers))
        # underdog = the side the market has as the non-favourite
        model_side_is_dog = (edge > 0 and market < 0) or (edge < 0 and market > 0)
        rows.append({"edge": edge, "won": won, "push": push, "dog": model_side_is_dog})

    print("  %-10s %6s %8s %8s %-18s %8s" % ("|edge| >=", "bets", "ATS W%", "vs 52.4%", "95% CI", "dog%"))
    print("  " + "-" * 68)
    for thr in (0.0, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0):
        sel = [r for r in rows if abs(r["edge"]) >= thr and not r["push"]]
        n = len(sel)
        if n < 10:
            print("  %-10.1f %6d   (too few to judge)" % (thr, n))
            continue
        k = sum(1 for r in sel if r["won"])
        p = k / n
        lo, hi = wilson(k, n)
        dog = sum(1 for r in sel if r["dog"]) / n
        flag = "  <-- above breakeven" if lo > BREAKEVEN else ""
        print("  %-10.1f %6d %7.1f%% %+8.1f  [%4.1f%%, %4.1f%%] %7.0f%%%s"
              % (thr, n, 100 * p, 100 * (p - BREAKEVEN), 100 * lo, 100 * hi, 100 * dog, flag))
    print()
    print("  A row is PLAYABLE only if the CI LOWER BOUND clears 52.4%.")
    print("  dog% near 100 means the threshold is selecting a SIDE, not a signal.")


ncaaf = games_from_ledger("ncaaf", (2024,))
report("NCAAF 2024 -- clean out-of-sample (2023 SP+ on 2024 games)", ncaaf)

nfl = games_from_ledger("nfl", (2023, 2024))
report("NFL PRESEASON 2023+2024 -- leak-free by construction", nfl)

print("\n" + "=" * 78)
print("MULTIPLICITY: 7 thresholds x 2 sports = 14 tests. At 95% confidence you")
print("expect ~0.7 false positives by chance. A single row clearing the bar is")
print("NOT a discovery -- it needs pre-specification and an out-of-sample season.")
print("=" * 78)
