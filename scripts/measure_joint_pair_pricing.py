"""Does the MEASURED same-game correlation price co-occurrence better than the guess?

FIRST RESULT, 2026-09-04, 6,396 pairs / 6 games (substrate `render`):

    arm             log-loss    brier
    independence     0.16407   0.03644
    heuristic        0.19851   0.04706
    MEASURED         0.17115   0.03870

The joint BEATS the heuristic it replaced (-0.02715 log-loss, 95% CI
[-0.030, -0.023]) and the mechanism is visible: cross-player pairs measure a
median +0.031 where the heuristic asserts +0.530, a ~17x overstatement on 95%
of all pairs. But INDEPENDENCE beats both, and same-player it beats MEASURED by
+0.101 once the parlay cap is lifted -- monotonically worse the further off
independence you move.

THE DIAGNOSED CAUSE, and it is a unit error, not a bad model. This joint
publishes SPEARMAN RANK CORRELATION OF COUNTS. The parlay needs the correlation
of the THRESHOLDED over/under INDICATORS at the traded line, and thresholding
attenuates dependence hard -- under a Gaussian copula, phi(indicator) is only
54-68% of rho(counts) at these marginals:

    p=0.30, rho=0.575  ->  phi = 0.374   (65%)
    p=0.20, rho=0.575  ->  phi = 0.350   (61%)

So feeding rho_counts straight into a joint-probability estimator overstates
dependence by ~1.5-1.9x, which is exactly the observed failure and exactly why
it scales with the cap. THE FIX BELONGS IN THE RESOLVER, not the sim: the
marginals are available at pricing time, the traded line is not available at
sim time.

CAVEAT THAT BOUNDS ALL OF THE ABOVE: 6 game clusters, one date. The bootstrap
resamples 4-6 items, so its intervals are an artefact of having almost no
clusters. Suggestive, not conclusive. Re-run across ~20 dates before acting.

THE INSTRUMENT, and why it is not "settled parlays". A parlay's probability is
P(A and B). We have settled SINGLE legs. For any two graded legs on the same
game we know whether BOTH won -- that is a realised joint outcome, and it needs
no parlay to have been placed. A prior measurement in this repo died waiting for
an arm that structurally could never fill (13 of 667 settled orders, all one
arm, ~108 days to power).

THREE ARMS ON IDENTICAL MARGINALS. p_A and p_B come from the SIM's own published
distribution for that player/market/line and are held FIXED across arms, so this
tests the dependence term and nothing else:

    independence   p_A * p_B
    heuristic      the flag-sum path (correlation_engine, no resolver)
    measured       the joint's Spearman coefficient

All three go through the PRODUCTION estimator
`intelligence_parlay_runtime._correlation_adjusted_probability`, not a
reimplementation of it.

THREE FILTERS THAT ARE NOT OPTIONAL:
  * `is_lineup_batter` -- bench batters carry `pa_mean` ~0.04 and constant
    columns, which manufacture degenerate correlations (a +1.000 HR x TB was
    observed on one). They are not evidence about dependence.
  * `undefined == -32768` -- a constant column has NO measured correlation. It
    must fall back, never to 0.0: a measured zero is a real and large claim
    ("independent") and mapping unknown onto it is the permissive-default
    failure this ledger names repeatedly.
  * degenerate marginals -- p in {0, 1} carries no information and makes
    log-loss infinite.

CLUSTERING. Pairs inside one game are NOT independent: a game with 20 graded
legs yields 190 correlated pairs. All intervals bootstrap over GAMES, never over
pairs, or they would be far too narrow -- the single most likely route to a
confident wrong answer here.
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import random
import sys
import unicodedata
from collections import defaultdict

REPO = pathlib.Path(r"C:\tmp\soccer-players-wt")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.correlation_engine import compute_correlation  # noqa: E402
from syndicate.features.intelligence_parlay_runtime import (  # noqa: E402
    _correlation_adjusted_probability,
)

CACHE = pathlib.Path(r"C:\tmp\joint-cache")
#: props_actuals label -> joint label segment. Verified against the real file's
#: vocabulary (2026-09-04): the actuals say "Hits", not "Batter Hits".
#: `strikeouts` is a joint dimension with NO market to grade against -- the
#: hitter-props snapshot requests 7 markets and returns 6, 0 of 289 players
#: carrying strikeouts -- so it rides in the matrix and out of this measurement.
#: "Runs" and "Hits + Runs + RBIs" are graded but are not joint dimensions.
MARKETS = {
    "Hits": "hits",
    "Home Runs": "home_runs",
    "Total Bases": "total_bases",
    "RBIs": "rbi",
}
MIN_PA = 1.0
EPS = 1e-6


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace(".", " ").replace("-", " ").split())


def p_over(dist: dict, line: float) -> float | None:
    """P(value > line) from the sim's published distribution."""
    if not isinstance(dist, dict) or not dist:
        return None
    total = 0.0
    over = 0.0
    for k, v in dist.items():
        try:
            key = float(k)
            cnt = float(v)
        except (TypeError, ValueError):
            continue
        total += cnt
        if key > line:
            over += cnt
    if total <= 0:
        return None
    return over / total


def tri(i: int, k: int) -> int:
    if i < k:
        i, k = k, i
    return i * (i - 1) // 2 + k


def log_loss(p: float, y: int) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -(math.log(p) if y else math.log(1 - p))


def main() -> int:
    actuals = defaultdict(dict)   # norm(player) -> market -> (actual, line)
    src = None
    for cand in CACHE.glob("props_actuals_*.csv"):
        src = cand
    if src is None:
        print("no props_actuals csv cached"); return 2
    for row in csv.DictReader(src.open(encoding="utf-8", errors="replace")):
        mk = MARKETS.get(str(row.get("market") or "").strip())
        if not mk:
            continue
        try:
            actuals[norm(row.get("player"))][mk] = (
                float(row["actual"]), float(row["line"]))
        except (TypeError, ValueError, KeyError):
            continue
    print("graded batter legs: %d players" % len(actuals))

    per_game = []
    skipped = defaultdict(int)
    for path in sorted(CACHE.glob("sim_*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        sim = rec.get("sim") or {}
        j = sim.get("joint") or {}
        labels = j.get("labels") or []
        lower = j.get("corr_lower") or []
        UND = j.get("undefined", -32768)
        scale = float(j.get("scale") or 1000.0)
        hp = sim.get("hitter_props") or {}
        if not labels or not lower:
            skipped["no_joint"] += 1
            continue
        pos = {l: i for i, l in enumerate(labels)}

        legs = []
        for pid, prof in hp.items():
            if not isinstance(prof, dict) or not prof.get("is_lineup_batter"):
                skipped["not_lineup"] += 1
                continue
            if float(prof.get("pa_mean") or 0.0) < MIN_PA:
                skipped["thin_pa"] += 1
                continue
            got = actuals.get(norm(prof.get("name")))
            if not got:
                skipped["no_graded_row"] += 1
                continue
            for mk, (actual, line) in got.items():
                lab = f"batter|{pid}|{mk}"
                if lab not in pos:
                    skipped["no_label"] += 1
                    continue
                p = p_over(prof.get(f"{mk}_dist"), line)
                if p is None or p <= EPS or p >= 1 - EPS:
                    skipped["degenerate_marginal"] += 1
                    continue
                legs.append({
                    "pid": pid, "name": prof.get("name"), "market": mk,
                    "label": lab, "p": p, "won": 1 if actual > line else 0,
                    "team": prof.get("team"),
                })

        pairs = []
        for a in range(len(legs)):
            for b in range(a + 1, len(legs)):
                la, lb = legs[a], legs[b]
                raw = lower[tri(pos[la["label"]], pos[lb["label"]])]
                measured = None if raw == UND else raw / scale
                if measured is None:
                    skipped["undefined_corr"] += 1
                    continue
                cand_a = {"sport": "mlb", "sport_slug": "mlb",
                          "game_key": path.stem, "event_id": path.stem,
                          "team": la["team"], "team_key": la["team"],
                          "subject": la["name"], "player_name": la["name"],
                          "market": la["market"], "market_key": la["market"],
                          "selection": "over", "side": "over"}
                cand_b = dict(cand_a, team=lb["team"], team_key=lb["team"],
                              subject=lb["name"], player_name=lb["name"],
                              market=lb["market"], market_key=lb["market"])
                heur = float(compute_correlation(cand_a, cand_b).get("correlation_score") or 0.0)
                y = 1 if (la["won"] and lb["won"]) else 0
                probs = [la["p"], lb["p"]]
                pairs.append({
                    "y": y,
                    "indep": _correlation_adjusted_probability(probs, 0.0),
                    "heur": _correlation_adjusted_probability(probs, heur),
                    "meas": _correlation_adjusted_probability(probs, measured),
                    "same_player": la["pid"] == lb["pid"],
                    "measured": measured, "heuristic": heur,
                })
        if pairs:
            per_game.append((path.stem, pairs))

    total = sum(len(p) for _, p in per_game)
    print("games with pairs: %d   pairs: %d" % (len(per_game), total))
    print("skipped:", dict(skipped))
    if not total:
        return 3

    def score(arm):
        n = sum(len(p) for _, p in per_game)
        ll = sum(log_loss(x[arm], x["y"]) for _, p in per_game for x in p) / n
        br = sum((x[arm] - x["y"]) ** 2 for _, p in per_game for x in p) / n
        return ll, br

    print("\n%-14s %10s %10s" % ("arm", "log-loss", "brier"))
    res = {}
    for arm, lbl in (("indep", "independence"), ("heur", "heuristic"), ("meas", "MEASURED")):
        ll, br = score(arm)
        res[arm] = (ll, br)
        print("%-14s %10.5f %10.5f" % (lbl, ll, br))

    # bootstrap over GAMES -- pairs within a game are not independent
    rng = random.Random(20260905)
    diffs = {"heur": [], "indep": []}
    for _ in range(2000):
        pick = [per_game[rng.randrange(len(per_game))] for _ in per_game]
        n = sum(len(p) for _, p in pick)
        if not n:
            continue
        m = sum(log_loss(x["meas"], x["y"]) for _, p in pick for x in p) / n
        for arm in ("heur", "indep"):
            o = sum(log_loss(x[arm], x["y"]) for _, p in pick for x in p) / n
            diffs[arm].append(m - o)
    print("\nlog-loss difference, MEASURED minus other (negative = measured BETTER)")
    print("bootstrap over %d games, 2000 resamples:" % len(per_game))
    for arm, lbl in (("heur", "vs heuristic"), ("indep", "vs independence")):
        d = sorted(diffs[arm])
        if not d:
            continue
        print("  %-16s %+0.5f   95%% CI [%+0.5f, %+0.5f]" % (
            lbl, sum(d) / len(d), d[int(0.025 * len(d))], d[int(0.975 * len(d))]))

    # SUBGROUP SCORING. 95% of pairs are cross-player, where the measured
    # correlation is ~+0.03 -- so the pooled result mostly tests "is the
    # heuristic's cross-player claim wrong", not "does dependence help". The
    # population where a same-game parlay actually lives is SAME PLAYER.
    for lbl, keep in (("SAME-PLAYER", True), ("CROSS-PLAYER", False)):
        sub = [(g, [x for x in pp if x["same_player"] is keep]) for g, pp in per_game]
        sub = [(g, pp) for g, pp in sub if pp]
        n = sum(len(pp) for _, pp in sub)
        if not n:
            continue
        print("\n%s pairs: n=%d over %d games" % (lbl, n, len(sub)))
        print("  %-14s %10s %10s" % ("arm", "log-loss", "brier"))
        for arm, name in (("indep", "independence"), ("heur", "heuristic"), ("meas", "MEASURED")):
            ll = sum(log_loss(x[arm], x["y"]) for _, pp in sub for x in pp) / n
            br = sum((x[arm] - x["y"]) ** 2 for _, pp in sub for x in pp) / n
            print("  %-14s %10.5f %10.5f" % (name, ll, br))
        r2 = random.Random(7)
        dd = {"heur": [], "indep": []}
        for _ in range(2000):
            pick = [sub[r2.randrange(len(sub))] for _ in sub]
            m = sum(len(pp) for _, pp in pick)
            if not m:
                continue
            mm = sum(log_loss(x["meas"], x["y"]) for _, pp in pick for x in pp) / m
            for arm in ("heur", "indep"):
                oo = sum(log_loss(x[arm], x["y"]) for _, pp in pick for x in pp) / m
                dd[arm].append(mm - oo)
        for arm, name in (("heur", "vs heuristic"), ("indep", "vs independence")):
            d = sorted(dd[arm])
            if d:
                print("  MEASURED %-16s %+0.5f  95%% CI [%+0.5f, %+0.5f]" % (
                    name, sum(d)/len(d), d[int(.025*len(d))], d[int(.975*len(d))]))

    sp = [x for _, p in per_game for x in p if x["same_player"]]
    cp = [x for _, p in per_game for x in p if not x["same_player"]]
    print("\npopulation: same-player %d, cross-player %d" % (len(sp), len(cp)))
    for lbl, grp in (("same-player", sp), ("cross-player", cp)):
        if grp:
            print("  %-13s measured med %+.3f | heuristic med %+.3f" % (
                lbl,
                sorted(x["measured"] for x in grp)[len(grp) // 2],
                sorted(x["heuristic"] for x in grp)[len(grp) // 2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
